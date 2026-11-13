"""
add documents.error_message and documents.file_hash

为什么加这两列：
  - error_message：P0-1 之后上传失败会落 `failed` 状态，但**原因只存在于响应和日志里**，
    过几天回看只知道"失败"、不知道为什么。这里把它持久化。
  - file_hash：P0-8 的内容去重需要按 sha256 判断"这份文件是不是已经传过"，
    否则同一份文件反复上传会重复切片、重复花 embedding 成本。

Revision ID: b1a2c3d4e5f6
Revises: e24e5d995a17
Create Date: 2026-11-02 13:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, None] = "e24e5d995a17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL 的 ALTER 能力有限，用 batch 模式（必要时会重建表）
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "error_message",
                sa.Text(),
                nullable=True,
                comment="最近一次处理失败的原因（成功后清空）",
            )
        )
        batch_op.add_column(
            sa.Column(
                "file_hash",
                sa.String(length=64),
                nullable=True,
                comment="文件内容 sha256（用于同库去重）",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_documents_file_hash"), ["file_hash"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_file_hash"))
        batch_op.drop_column("file_hash")
        batch_op.drop_column("error_message")
