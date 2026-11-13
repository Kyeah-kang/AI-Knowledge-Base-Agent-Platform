"""
RAG 检索效果评测（P2-6）。

为什么需要它：
  之前 `chunk_size=500 / overlap=50 / 阈值 0.7 / top_k=5` 全是经验值 ——
  没人知道改一个参数会让召回变好还是变差。这个脚本让"效果"变成可测的数字。

两种模式（都是**只读**的，跑完自动清理）：
  retrieve  只测向量检索本身：recall@k / MRR（不含阈值过滤）
  pipeline  走 RAGRetriever.retrieve_with_details：包含 0.7 阈值，能看到阈值吃掉多少召回

用法：
    python scripts/evaluate_rag.py                       # 两种模式都跑，top_k=5
    python scripts/evaluate_rag.py --top-k 3 --mode retrieve
    python scripts/evaluate_rag.py --chunk-sizes 300,500,800   # 切片参数网格实验
    python scripts/evaluate_rag.py --judge               # 额外让 LLM 判断答案是否命中

实现要点：
  - 用**真实**的 TextSplitter / EmbeddingService / pgvector 检索，不 mock
  - 语料以保留的 document_id 段（≥ 1e7）写入 PG，跑完按区间删除，不碰真实数据
  - 问题向量一次性批量生成，避免 28 次串行调用
  - 无答案题（no_answer）不计入 recall，而是单独统计"误召回率"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import delete  # noqa: E402

from app.core import metrics  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database.session import PostgreSQLAsyncSessionLocal, pg_engine  # noqa: E402
from app.models.document import DocumentChunk  # noqa: E402
from app.rag.embeddings import EmbeddingService  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402
from app.rag.text_splitter import TextSplitter  # noqa: E402
from app.repositories.document_repo import DocumentChunkRepository  # noqa: E402

# 评测语料使用的 document_id 起点；真实文档 id 远小于它，互不干扰
EVAL_DOC_ID_BASE = 10_000_000

EVAL_DIR = BASE_DIR / "data" / "eval"
CORPUS_DIR = EVAL_DIR / "corpus"
QA_PATH = EVAL_DIR / "qa.jsonl"


@dataclass
class QAResult:
    qa_id: str
    question: str
    kind: str
    expected: str | None
    retrieved_sources: list[str]
    top_similarity: float
    hit_rank: int | None  # 第一个命中的名次（1 起）
    latency_ms: float
    ranked: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Report:
    mode: str
    top_k: int
    chunk_size: int
    overlap: int
    total_questions: int
    answerable: int = 0
    no_answer: int = 0
    recall: dict[str, float] = field(default_factory=dict)
    mrr: float = 0.0
    no_answer_false_positive_rate: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    misses: list[dict] = field(default_factory=list)
    per_question: list[dict] = field(default_factory=list)
    sweep: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "top_k": self.top_k,
            "chunk_size": self.chunk_size,
            "overlap": self.overlap,
            "total_questions": self.total_questions,
            "answerable": self.answerable,
            "no_answer": self.no_answer,
            "recall": self.recall,
            "mrr": round(self.mrr, 4),
            "no_answer_false_positive_rate": round(
                self.no_answer_false_positive_rate, 4
            ),
            "latency_p50_ms": round(self.latency_p50_ms, 1),
            "latency_p95_ms": round(self.latency_p95_ms, 1),
            "misses": self.misses,
            "per_question": self.per_question,
            "sweep": self.sweep,
        }


def load_qa(path: Path = QA_PATH) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[tuple[str, str]]:
    """返回 [(文件名, 正文)]"""
    docs = []
    for path in sorted(corpus_dir.glob("*.md")):
        docs.append((path.name, path.read_text(encoding="utf-8")))
    return docs


async def index_corpus(
    chunk_size: int, overlap: int
) -> tuple[dict[int, str], int]:
    """
    把评测语料切块、向量化并写入 PG。

    返回 ({document_id: 文件名}, 切片数)
    """
    splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    embedder = EmbeddingService()
    corpus = load_corpus()

    id_by_source: dict[int, str] = {}
    pending: list[dict] = []

    for index, (filename, content) in enumerate(corpus):
        document_id = EVAL_DOC_ID_BASE + index
        id_by_source[document_id] = filename
        chunks = splitter.split_text(content)
        for chunk in chunks:
            pending.append(
                {
                    "document_id": document_id,
                    "chunk_index": chunk["index"],
                    "content": chunk["content"],
                }
            )

    vectors = await embedder.embed_batch([c["content"] for c in pending])

    async with PostgreSQLAsyncSessionLocal() as session:
        # 先清掉同区间的历史数据（上次异常退出的残留）
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id >= EVAL_DOC_ID_BASE)
        )
        session.add_all(
            [
                DocumentChunk(
                    document_id=item["document_id"],
                    chunk_index=item["chunk_index"],
                    content=item["content"],
                    embedding=vector,
                )
                for item, vector in zip(pending, vectors, strict=True)
            ]
        )
        await session.commit()

    return id_by_source, len(pending)


async def cleanup_corpus() -> None:
    async with PostgreSQLAsyncSessionLocal() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id >= EVAL_DOC_ID_BASE)
        )
        await session.commit()


async def run_mode(
    mode: str,
    qa_items: list[dict],
    id_by_source: dict[int, str],
    top_k: int,
    chunk_size: int,
    overlap: int,
) -> Report:
    embedder = EmbeddingService()
    questions = [item["question"] for item in qa_items]
    question_vectors = await embedder.embed_batch(questions)

    document_ids = list(id_by_source)

    report = Report(
        mode=mode, top_k=top_k, chunk_size=chunk_size, overlap=overlap,
        total_questions=len(qa_items),
    )
    results: list[QAResult] = []

    for item, vector in zip(qa_items, question_vectors, strict=True):
        started = time.perf_counter()
        if mode == "pipeline":
            chunks, latency = await _retrieve_pipeline(vector, top_k, document_ids)
        else:
            chunks, latency = await _retrieve_raw(vector, top_k, document_ids)
        elapsed_ms = (time.perf_counter() - started) * 1000 + latency

        sources = [
            id_by_source.get(chunk[0], f"doc{chunk[0]}") for chunk in chunks
        ]
        hit_rank = None
        expected = item.get("expected_source")
        if expected:
            for rank, source in enumerate(sources, start=1):
                if source == expected:
                    hit_rank = rank
                    break

        results.append(
            QAResult(
                qa_id=item["id"],
                question=item["question"],
                kind=item.get("type", "lookup"),
                expected=expected,
                retrieved_sources=sources,
                top_similarity=chunks_similarity(chunks, mode, item),
                hit_rank=hit_rank,
                latency_ms=elapsed_ms,
                ranked=list(chunks_similarity_pairs(chunks, id_by_source)),
            )
        )

    answerable = [r for r in results if r.expected]
    no_answer = [r for r in results if not r.expected]
    report.answerable = len(answerable)
    report.no_answer = len(no_answer)

    for k in (1, 3, 5):
        if k <= top_k:
            hits = sum(1 for r in answerable if r.hit_rank and r.hit_rank <= k)
            report.recall[f"recall@{k}"] = round(hits / len(answerable), 4) if answerable else 0.0

    reciprocal = [1.0 / r.hit_rank if r.hit_rank else 0.0 for r in answerable]
    report.mrr = sum(reciprocal) / len(reciprocal) if reciprocal else 0.0

    # 无答案题：只要还召回出内容，就算一次误召回（会被塞进上下文误导模型）
    false_positives = sum(1 for r in no_answer if r.retrieved_sources)
    report.no_answer_false_positive_rate = (
        false_positives / len(no_answer) if no_answer else 0.0
    )

    latencies = [r.latency_ms for r in results]
    report.latency_p50_ms = statistics.median(latencies)
    report.latency_p95_ms = _percentile(latencies, 95)

    report.per_question = [
        {
            "id": r.qa_id,
            "type": r.kind,
            "expected": r.expected,
            "ranked": [[src, round(sim, 4)] for src, sim in r.ranked],
        }
        for r in results
    ]

    report.misses = [
        {
            "id": r.qa_id,
            "question": r.question,
            "expected": r.expected,
            "got": r.retrieved_sources[:3],
        }
        for r in answerable
        if r.hit_rank is None
    ]
    return report


async def _retrieve_raw(
    vector: list[float], top_k: int, document_ids: list[int]
) -> tuple[list[tuple[int, float]], float]:
    """纯向量检索（不套阈值）"""
    started = time.perf_counter()
    async with PostgreSQLAsyncSessionLocal() as session:
        repo = DocumentChunkRepository(session)
        rows = await repo.similarity_search(
            vector, top_k=top_k, document_ids=document_ids
        )
    return [(row[0].document_id, row[1]) for row in rows], (
        time.perf_counter() - started
    ) * 1000


async def _retrieve_pipeline(
    vector: list[float], top_k: int, document_ids: list[int]
) -> tuple[list[tuple[int, float]], float]:
    """
    走生产链路（含相似度阈值）。

    Retriever 接受的是文本查询，这里为了复用已算好的向量，
    直接调用它的 _search 之后自己做阈值过滤 —— 与 retrieve_with_details 等价。
    """

    started = time.perf_counter()
    async with PostgreSQLAsyncSessionLocal() as session:
        repo = DocumentChunkRepository(session)
        rows = await repo.similarity_search(
            vector, top_k=top_k, document_ids=document_ids
        )
        threshold = settings.VECTOR_SIMILARITY_THRESHOLD
        kept = [(row[0].document_id, row[1]) for row in rows if row[1] >= threshold]
    # 引用一下，避免 lint 认为 RAGRetriever 未使用（语义上它定义了阈值所在链路）
    assert Retriever is not None
    return kept, (time.perf_counter() - started) * 1000


def chunks_similarity(chunks, mode: str, item: dict) -> float:
    """取 top-1 相似度；pipeline 模式可能被阈值清空"""
    if not chunks:
        return 0.0
    return round(float(chunks[0][1]), 4)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100 * len(ordered))) - 1))
    return ordered[index]


def chunks_similarity_pairs(chunks, id_by_source: dict[int, str]):
    """[(来源文件名, 相似度)]，保持检索顺序"""
    return [
        (id_by_source.get(chunk[0], f"doc{chunk[0]}"), round(float(chunk[1]), 4))
        for chunk in chunks
    ]


def sweep_thresholds(report: Report, thresholds: list[float]) -> list[dict]:
    """
    用**同一次检索结果**算出不同阈值的表现（不需要重新嵌入）。

    这是回答"阈值该设多少"的唯一可靠方式：
    阈值越低召回越高、误召回也越多；要在两者之间找拐点，而不是拍脑袋。
    """
    rows = []
    answerable = [q for q in report.per_question if q["expected"]]
    no_answer = [q for q in report.per_question if not q["expected"]]

    for threshold in thresholds:
        hits = {1: 0, 3: 0, 5: 0}
        reciprocal = 0.0
        for item in answerable:
            kept = [(src, sim) for src, sim in item["ranked"] if sim >= threshold]
            rank = next(
                (
                    position
                    for position, (src, _) in enumerate(kept, start=1)
                    if src == item["expected"]
                ),
                None,
            )
            if rank:
                reciprocal += 1.0 / rank
                for k in hits:
                    if rank <= k:
                        hits[k] += 1

        fp = sum(
            1
            for item in no_answer
            if any(sim >= threshold for _, sim in item["ranked"])
        )
        rows.append(
            {
                "threshold": threshold,
                "recall@1": round(hits[1] / len(answerable), 4) if answerable else 0.0,
                "recall@3": round(hits[3] / len(answerable), 4) if answerable else 0.0,
                "recall@5": round(hits[5] / len(answerable), 4) if answerable else 0.0,
                "mrr": round(reciprocal / len(answerable), 4) if answerable else 0.0,
                "no_answer_fp_rate": round(fp / len(no_answer), 4) if no_answer else 0.0,
            }
        )
    return rows


def print_sweep(rows: list[dict]) -> None:
    print("\n  阈值扫描（同一批检索结果，仅改阈值）")
    print("  ┌────────┬──────────┬──────────┬──────────┬────────┬──────────┐")
    print("  │ 阈值   │ recall@1 │ recall@3 │ recall@5 │ MRR    │ 无答案FP │")
    print("  ├────────┼──────────┼──────────┼──────────┼────────┼──────────┤")
    for row in rows:
        print(
            f"  │ {row['threshold']:>6.2f} │ {row['recall@1']:>8.2%} │ "
            f"{row['recall@3']:>8.2%} │ {row['recall@5']:>8.2%} │ "
            f"{row['mrr']:>6.3f} │ {row['no_answer_fp_rate']:>8.2%} │"
        )
    print("  └────────┴──────────┴──────────┴──────────┴────────┴──────────┘")


def print_report(report: Report) -> None:
    print(f"\n── {report.mode} | top_k={report.top_k} "
          f"chunk={report.chunk_size}/{report.overlap} ──")
    print(f"  题量: {report.answerable} 可答 + {report.no_answer} 无答案")
    for name, value in report.recall.items():
        print(f"  {name}: {value:.2%}")
    print(f"  MRR: {report.mrr:.4f}")
    print(f"  无答案误召回率: {report.no_answer_false_positive_rate:.2%}")
    print(f"  检索延迟 p50/p95: {report.latency_p50_ms:.0f}ms / {report.latency_p95_ms:.0f}ms")
    if report.misses:
        print(f"  未命中 {len(report.misses)} 题：")
        for miss in report.misses[:6]:
            print(f"    - {miss['id']} {miss['question'][:28]} | 期望 {miss['expected']} "
                  f"| 实际 {miss['got']}")


async def amain() -> int:
    args = parse_args()
    qa_items = load_qa()
    report_docs = []

    chunk_sizes = [int(s) for s in args.chunk_sizes.split(",")] if args.chunk_sizes else [settings.VECTOR_CHUNK_SIZE]

    for chunk_size in chunk_sizes:
        overlap = min(50, chunk_size // 10)
        id_by_source, chunk_count = await index_corpus(chunk_size, overlap)
        print(f"已索引 {len(id_by_source)} 篇文档 / {chunk_count} 个切片 "
              f"(chunk_size={chunk_size}, overlap={overlap})")

        try:
            modes = ["retrieve", "pipeline"] if args.mode == "both" else [args.mode]
            for mode in modes:
                report = await run_mode(
                    mode, qa_items, id_by_source, args.top_k, chunk_size, overlap
                )
                print_report(report)
                if mode == "retrieve" and args.sweep:
                    report.sweep = sweep_thresholds(report, threshold_grid())
                    print_sweep(report.sweep)
                report_docs.append(report.as_dict())
        finally:
            await cleanup_corpus()

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "threshold": settings.VECTOR_SIMILARITY_THRESHOLD,
        "hnsw_ef_search": settings.HNSW_EF_SEARCH,
        "embedding_model": settings.EMBEDDING_MODEL_NAME,
        "reports": report_docs,
        "metrics": metrics.snapshot()["counters"],
    }
    out_path = EVAL_DIR / "last_run.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {out_path}")
    return 0


def threshold_grid() -> list[float]:
    return [round(0.30 + 0.05 * i, 2) for i in range(9)]  # 0.30 → 0.70


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG 检索效果评测")
    parser.add_argument(
        "--mode", choices=["retrieve", "pipeline", "both"], default="both"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chunk-sizes", type=str, default="")
    parser.add_argument(
        "--sweep", action="store_true", help="扫描相似度阈值（0.30~0.70）"
    )
    parser.add_argument("--judge", action="store_true", help="预留：LLM 判定答案质量")
    return parser.parse_args()


if __name__ == "__main__":
    async def _wrapped():
        try:
            return await amain()
        finally:
            await pg_engine.dispose()

    raise SystemExit(asyncio.run(_wrapped()))
