"""
Agent 工具数据访问层 — AgentTool 表 CRUD

对应 models/agent.py 中的 AgentTool 模型。
提供"工具注册表"的增删改查 + 获取已启用的工具列表。
"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentTool
from app.repositories.base import BaseRepository


class AgentToolRepository(BaseRepository[AgentTool]):
    """Agent 工具注册表 Repository（MySQL）"""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentTool)

    async def get_by_name(self, name: str) -> AgentTool | None:
        """按工具标识名查询"""
        query = select(self.model).where(self.model.name == name)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_enabled_tools(self) -> list[AgentTool]:
        """获取所有已启用的工具"""
        query = (
            select(self.model)
            .where(self.model.enabled.is_(True))
            .order_by(self.model.id.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_tools(self) -> list[AgentTool]:
        """获取所有工具（含已禁用的）"""
        query = select(self.model).order_by(self.model.id.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def toggle_enabled(self, tool_id: int) -> AgentTool | None:
        """切换工具的启用/禁用状态"""
        tool = await self.get(tool_id)
        if not tool:
            return None
        tool.enabled = not tool.enabled
        await self.db.flush()
        await self.db.refresh(tool)
        return tool

    async def tool_to_definition(self, tool: AgentTool) -> dict:
        """
        将数据库中的 AgentTool 记录转为 OpenAI 格式的 tool definition。

        转换后的格式：
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.params_schema,
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_schema,
            },
        }

    async def get_enabled_definitions(self) -> list[dict]:
        """获取所有启用工具的 LLM tool definition 格式"""
        tools = await self.get_enabled_tools()
        return [await self.tool_to_definition(t) for t in tools]

    async def create_tool(
        self,
        name: str,
        display_name: str,
        description: str,
        params_schema: dict | None = None,
    ) -> AgentTool:
        """创建新工具"""
        return await self.create(
            name=name,
            display_name=display_name,
            description=description,
            params_schema=params_schema or {
                "type": "object",
                "properties": {},
                "required": [],
            },
        )
