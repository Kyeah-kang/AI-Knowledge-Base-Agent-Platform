"""
数据初始化脚本 — 插入种子数据

使用方式：
    cd backend
    python scripts/seed_data.py

当前插入的数据：
  - Agent 内建工具注册（web_search、calculator、knowledge_retrieval）

注意：
  运行前需要先执行 init_db.py 创建数据库表。
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

# 将 backend 目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import MySQLAsyncSessionLocal
from app.models.agent import AgentTool

# ─── 工具种子数据 ───

SEED_TOOLS = [
    {
        "name": "web_search",
        "display_name": "联网搜索",
        "description": "搜索互联网获取实时信息。当用户需要最新的新闻、实时数据、或当前事件时使用。",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，越精确越好",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回结果数量（默认 5）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "enabled": True,
    },
    {
        "name": "calculator",
        "display_name": "数学计算器",
        "description": "执行数学计算。支持加减乘除、幂运算、三角函数等。当用户需要精确计算数值时使用。",
        "params_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '2 + 3 * 4'",
                }
            },
            "required": ["expression"],
        },
        "enabled": True,
    },
    {
        "name": "knowledge_retrieval",
        "display_name": "知识库检索",
        "description": "从知识库中检索与问题相关的文档内容。当用户询问需要参考内部文档、知识库中的资料时使用。",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词或问题",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回最多几条结果（默认 5）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "enabled": True,
    },
]


async def seed_agent_tools():
    """插入 Agent 工具种子数据（如果不存在则创建）"""
    async with MySQLAsyncSessionLocal() as db:
        print("正在初始化 Agent 工具数据...")
        created = 0
        skipped = 0

        for tool_data in SEED_TOOLS:
            # 检查是否已存在
            query = select(AgentTool).where(AgentTool.name == tool_data["name"])
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if existing:
                skipped += 1
                continue

            tool = AgentTool(**tool_data)
            db.add(tool)
            created += 1

        await db.commit()
        print(f"  ✓ 新增 {created} 个工具")
        print(f"  - 已存在 {skipped} 个工具（跳过）")
        print("Agent 工具数据初始化完成！")


async def main():
    print("=" * 50)
    print("开始插入种子数据...")
    print("=" * 50)

    await seed_agent_tools()

    print("=" * 50)
    print("种子数据初始化完成！")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
