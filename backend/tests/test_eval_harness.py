"""
评测脚本自身的测试（P2-6 / P2-7）。

为什么要测评测脚本：
  "衡量效果的尺子"如果自己算错，后面所有参数决策都是错的。
  这里锁住三件事：
    1. 数据集完整性 —— 题目引用的文档必须真实存在（防止改名后静默失效）
    2. 指标算法 —— recall@k / MRR / 误召回率的定义要和论文/常识一致
    3. 阈值扫描 —— 同一批结果换阈值时，召回只应单调下降，不应出现幻觉式回升

不依赖数据库与网络。
"""

import pytest

from scripts.evaluate_rag import (
    CORPUS_DIR,
    QA_PATH,
    Report,
    _percentile,
    load_corpus,
    load_qa,
    sweep_thresholds,
)

# ─────────────────── 数据集完整性 ───────────────────


def test_qa_dataset_is_loadable_and_well_formed():
    items = load_qa()

    assert len(items) >= 30, "评测集太小，指标没有统计意义"
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids)), "题目 id 必须唯一"

    corpus_names = {name for name, _ in load_corpus()}
    for item in items:
        assert item["question"].strip()
        assert item["type"] in {"lookup", "paraphrase", "reasoning", "cross_doc", "no_answer"}
        if item["type"] == "no_answer":
            assert item["expected_source"] is None
        else:
            assert item["expected_source"] in corpus_names, (
                f"{item['id']} 指向不存在的文档 {item['expected_source']}"
            )
            assert item["expected_keywords"], f"{item['id']} 缺少预期关键词"


def test_corpus_is_non_trivial():
    docs = load_corpus()

    assert len(docs) >= 8, "语料太少，检索任务会过于简单"
    for name, content in docs:
        assert len(content) > 300, f"{name} 太短，切不出有意义的切片"


def test_qa_has_no_answer_probes():
    """没有"无答案"题就无法评估误召回 —— 阈值调低时必须有东西能暴露问题"""
    items = load_qa()
    assert any(item["type"] == "no_answer" for item in items)


def test_qa_and_corpus_paths_exist():
    assert QA_PATH.exists()
    assert CORPUS_DIR.is_dir()


# ─────────────────── 指标算法 ───────────────────


def _report_with(per_question: list[dict]) -> Report:
    report = Report(mode="retrieve", top_k=5, chunk_size=500, overlap=50, total_questions=len(per_question))
    report.per_question = per_question
    return report


def test_sweep_recall_and_mrr_math():
    # 题 1：正确答案排第 1（0.8）；题 2：排第 3（0.4 / 0.3 / 0.2）
    per_question = [
        {
            "id": "a",
            "expected": "doc-a.md",
            "ranked": [["doc-a.md", 0.80], ["doc-b.md", 0.79]],
        },
        {
            "id": "b",
            "expected": "doc-b.md",
            "ranked": [["doc-x.md", 0.40], ["doc-y.md", 0.30], ["doc-b.md", 0.20]],
        },
        {"id": "c", "expected": None, "ranked": [["doc-z.md", 0.65]]},
    ]
    rows = {row["threshold"]: row for row in sweep_thresholds(_report_with(per_question), [0.10, 0.75])}

    # 阈值 0.10：两题都保留 → recall@1 = 1/2，recall@3 = 2/2，MRR = (1 + 1/3)/2
    assert rows[0.10]["recall@1"] == 0.5
    assert rows[0.10]["recall@3"] == 1.0
    assert rows[0.10]["mrr"] == pytest.approx((1.0 + 1 / 3) / 2, abs=1e-4)
    # 无答案题的 top1 = 0.65 ≥ 0.10 → 一次误召回
    assert rows[0.10]["no_answer_fp_rate"] == 1.0

    # 阈值 0.75：只剩题 1 的正确答案；题 2 被过滤 → recall@1 = 1/2，MRR = 1/2
    assert rows[0.75]["recall@1"] == 0.5
    assert rows[0.75]["recall@3"] == 0.5
    assert rows[0.75]["mrr"] == pytest.approx(0.5, abs=1e-4)
    # 0.65 < 0.75 → 无答案题被挡住
    assert rows[0.75]["no_answer_fp_rate"] == 0.0


def test_sweep_recall_is_monotonic_in_threshold():
    per_question = [
        {
            "id": "a",
            "expected": "doc-a.md",
            "ranked": [["doc-b.md", 0.70], ["doc-a.md", 0.60]],
        },
        {"id": "b", "expected": "doc-c.md", "ranked": [["doc-c.md", 0.45]]},
    ]
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7]
    rows = sweep_thresholds(_report_with(per_question), thresholds)

    recalls = [row["recall@5"] for row in rows]
    assert recalls == sorted(recalls, reverse=True), recalls
    assert recalls[0] == 1.0 and recalls[-1] == 0.0


def test_percentile_bounds():
    values = [10, 20, 30, 40]
    assert _percentile([], 95) == 0.0
    assert _percentile(values, 50) in values
    assert _percentile(values, 95) <= max(values)
