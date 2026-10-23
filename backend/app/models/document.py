"""
 Document + DocumentChunk — 跨数据库模型

 Document 继承 MySQLBase    → 存在 MySQL（业务数据）
 DocumentChunk 继承 PostgreSQLBase → 存在 PostgreSQL（向量数据）

"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 同时导入两个 Base，分别用于两个数据库
from app.database.base import MySQLBase, PostgreSQLBase
from app.utils.datetime_utils import utc_now

# 可选导入 pgvector Vector 类型
# 如果未安装 pgvector 包，则回退到 Text 类型存储向量（JSON 字符串）
try:
    from pgvector.sqlalchemy import Vector

    _HAS_PGVECTOR = True
except ImportError:
    Vector = None
    _HAS_PGVECTOR = False


class Document(MySQLBase):
    """
    上传的文档（MySQL）

    只存文档的元信息（文件名、大小、状态等），
    实际文本内容存在 DocumentChunk 的切片中。
    """
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ondelete="CASCADE" → 数据库级别的级联删除
    # 当 knowledge_bases 表中的记录被删除时，自动删除这个文档
    knowledge_base_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属知识库ID"
    )

    filename: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始文件名"
    )
    file_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="文件类型：pdf/docx/md/txt"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="文件大小（字节）"
    )
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="服务器存储路径"
    )

    # 状态字段 — 跟踪文档处理进度
    # pending → processing → completed / failed
    # index=True → 经常按状态查询（如查询所有处理失败的文档）
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True,
        comment="状态：pending/processing/completed/failed"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="切片数量"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="更新时间（UTC）",
    )

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}')>"


class DocumentChunk(PostgreSQLBase):
    """
    文档切片 + 向量嵌入（PostgreSQL + pgvector）

    这个表继承的是 PostgreSQLBase
    它存储在 PostgreSQL 中，为了使用 pgvector 插件做向量相似度检索。

    这个表没有 ForeignKey，因为 Document 在 MySQL 中，
    跨数据库无法建立数据库级的外键约束。
    """
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # document_id 是普通 Integer 而不是 ForeignKey
    # 原因：Document 在 MySQL，DocumentChunk 在 PostgreSQL
    # 跨数据库无法建立 FK，只能由应用层保证数据一致性
    document_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="所属文档ID（跨库引用，无FK约束）"
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, default=0, comment="切片序号（文档内的第几个切片）"
    )

    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="切片文本内容"
    )

    # embedding — 向量嵌入字段（pgvector Vector 类型）
    # pgvector 的 Vector 类型提供了 余弦相似度/欧氏距离 等运算能力
    # 如果 pgvector 不可用，降级为 Text 类型存储 JSON 数组
    if _HAS_PGVECTOR:
        from app.core.config import settings

        embedding: Mapped[list[float] | None] = mapped_column(
            Vector(settings.EMBEDDING_DIMENSION), nullable=True, comment="向量嵌入"
        )
    else:
        embedding: Mapped[str | None] = mapped_column(
            Text, nullable=True, comment="向量嵌入（未安装 pgvector，使用 Text 降级存储）"
        )

    # JSON 字段 — 灵活存储扩展信息
    # JSON 字段的好处：不需要为每种文档类型建不同的表
    # 注意：字段名用 extra_meta 而非 metadata，
    # 因为 metadata 是 SQLAlchemy DeclarativeBase 的保留属性
    extra_meta: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="额外元数据（如页码、章节标题等）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, idx={self.chunk_index})>"
