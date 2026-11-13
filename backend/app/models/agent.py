"""
 AgentTool 模型 — 工具注册表 + JSON Schema

工作流程：
  用户提问 → LLM 判断需要什么工具
  → 从 agent_tools 表读取启用的工具列表
  → LLM 根据 description 选择工具
  → 根据 params_schema 生成调用参数
  → 执行工具 → 返回结果给 LLM → LLM 生成最终回答
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import MySQLBase
from app.utils.datetime_utils import utc_now


class AgentTool(MySQLBase):
    """
    Agent 工具注册表（MySQL）

    预设好系统支持的工具，LLM 在对话过程中根据用户问题自动选择调用。
    新增工具只需要在这里插入一条记录，不需要改代码逻辑。
    """
    __tablename__ = "agent_tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # name — 工具的唯一标识符
    # unique=True → 不能有同名的工具
    # 代码中通过这个名字找到对应的处理函数
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="工具标识名（如 web_search）"
    )

    display_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="展示名称（给用户看）"
    )

    # description — LLM 根据这个描述决定是否调用工具
    # 描述越准确，LLM 越能在合适的场景下调用这个工具
    # 比如 "当用户需要查询实时信息时，使用此工具" → LLM 会理解何时调用
    description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="工具描述，LLM 根据描述决定是否调用"
    )

    # params_schema — JSON Schema 格式的参数定义
    # LLM 根据这个 schema 生成调用参数，比如：
    # {
    #   "type": "object",
    #   "properties": {
    #     "query": {"type": "string", "description": "搜索关键词"}
    #   },
    #   "required": ["query"]
    # }
    params_schema: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="参数 JSON Schema（LLM 按此生成参数）"
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用（管理员可开关）"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, comment="创建时间（UTC）"
    )

    def __repr__(self) -> str:
        return f"<AgentTool(id={self.id}, name='{self.name}')>"
