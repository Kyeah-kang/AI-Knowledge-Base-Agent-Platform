"""
add HNSW index on document_chunks.embedding

为什么（P1-1）：
  没有向量索引时，每次检索都是全表扫描 + 逐行算余弦距离。
  切片上万后延迟会随数据量线性增长，这是 RAG 最典型的性能坑。

为什么选 HNSW：
  查询快、召回高，且支持增量插入（IVFFlat 需要预先聚类，数据变化后要重建）。
  代价是写入变慢、占内存，对本项目（读多写少）是划算的。

参数：
  m=16              每个节点的最大连接数（默认 16，召回/内存的平衡点）
  ef_construction=64 建索引时的候选集大小（越大越精确、建得越慢）
  查询时用 `SET LOCAL hnsw.ef_search = N` 控制召回（见 HNSW_EF_SEARCH 配置）

注意：向量列是 `vector_cosine_ops`，必须与检索用的 `cosine_distance` 算子一致，
      否则索引不会被使用（PostgreSQL 不会报错，只是退化成全表扫描）。

Revision ID: c2b3d4e5f6a7
Revises: a418d6370212
Create Date: 2026-11-02 13:21:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c2b3d4e5f6a7"
down_revision: Union[str, None] = "a418d6370212"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_document_chunks_embedding_hnsw"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {INDEX_NAME}
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
