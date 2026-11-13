"""
文本切片器 — 将长文本分割成适合 LLM 上下文的小块

核心策略：
  1. RecursiveCharacterTextSplitter（LangChain）— 按分隔符递归切分，保持语义完整
  2. 段落分割 — 按 \n\n 切分，每段独立

为什么需要切片？
  - LLM 有上下文窗口限制（如 4K/8K/128K tokens）
  - 一个大文档可能超过限制，需要切成小块
  - RAG 检索时以切片为单位搜索，提高命中精度

用法：
    splitter = TextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(content)
    # → [{"content": "...", "index": 0}, {"content": "...", "index": 1}, ...]
"""

from typing import Any

# 可选导入 LangChain 的 RecursiveCharacterTextSplitter
# LangChain 1.x 已把它拆到独立的 langchain-text-splitters 包；
# 旧路径 `langchain.text_splitter` 在 1.x 里已不存在，静默 ImportError 会让切片
# 悄悄退化成"按字符硬切"，同一份文档在不同机器上切出不同结果（P0-9）。
try:
    from langchain_text_splitters import (
        RecursiveCharacterTextSplitter as LangChainSplitter,
    )

    _HAS_LANGCHAIN = True
except ImportError:  # pragma: no cover - 兼容旧环境
    try:
        from langchain.text_splitter import (  # type: ignore[no-redef]
            RecursiveCharacterTextSplitter as LangChainSplitter,
        )

        _HAS_LANGCHAIN = True
    except ImportError:
        LangChainSplitter = None  # type: ignore[assignment]
        _HAS_LANGCHAIN = False


class TextSplitter:
    """
    文本切片器

    默认使用 LangChain 的 RecursiveCharacterTextSplitter，
    如果 LangChain 不可用，降级为按字符数简单切分。
    """

    def __init__(
        self,
        chunk_size: int = 500,           # 每个切片的目标字符数
        chunk_overlap: int = 50,         # 相邻切片的重叠字符数
        separators: list[str] | None = None,  # 分隔符优先级列表
    ):
        """
        参数：
            chunk_size: 每个切片的目标大小（字符数）
            chunk_overlap: 相邻切片的重叠量，保持上下文连贯
            separators: 分隔符优先级，默认按段落→句子→词递进
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", "。", ".", " ", ""]

    def split_text(self, text: str) -> list[dict[str, Any]]:
        """
        将文本分割成切片列表。

        返回：
            [
                {"content": "第一段...", "index": 0, "metadata": {}},
                {"content": "第二段...", "index": 1, "metadata": {}},
                ...
            ]
        """
        if _HAS_LANGCHAIN:
            return self._split_with_langchain(text)
        else:
            return self._split_simple(text)

    def split_text_with_metadata(
        self,
        text: str,
        base_metadata: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        分割文本并为每个切片附加基础元数据。

        参数：
            text: 要切分的文本
            base_metadata: 附加到每个切片的元数据，如 {"page": 1}

        返回：
            每个切片包含 content、index、metadata
        """
        base = base_metadata or {}
        chunks = self.split_text(text)

        for chunk in chunks:
            # 合并基础元数据
            chunk["metadata"] = {**base, **chunk.get("metadata", {})}

        return chunks

    # ─── 内部实现 ───

    def _split_with_langchain(self, text: str) -> list[dict[str, Any]]:
        """使用 LangChain 的 RecursiveCharacterTextSplitter"""
        splitter = LangChainSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
        )

        docs = splitter.create_documents([text])
        return [
            {
                "content": doc.page_content,
                "index": i,
                "metadata": doc.metadata,
            }
            for i, doc in enumerate(docs)
        ]

    def _split_simple(self, text: str) -> list[dict[str, Any]]:
        """
        简易版分割（LangChain 不可用时的降级方案）。
        按固定字符数切分，优先在换行处断开。
        """
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            # 计算当前切片的结束位置
            end = start + self.chunk_size

            if end >= text_len:
                # 最后一段
                chunks.append(text[start:])
                break

            # 尽量在换行符处断开
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start + self.chunk_size // 2:
                end = newline_pos

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)

            # 移动起始位置（考虑重叠）
            start = end - self.chunk_overlap

        return [
            {"content": chunk, "index": i, "metadata": {}}
            for i, chunk in enumerate(chunks)
        ]
