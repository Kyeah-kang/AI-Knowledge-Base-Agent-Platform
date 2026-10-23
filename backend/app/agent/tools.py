"""
Agent 工具定义 — LLM 可调用的外部工具

三个内建工具：
  1. web_search           — 联网搜索（通过 httpx 调用外部搜索 API）
  2. calculator           — 数学计算（安全表达式求值）
  3. knowledge_retrieval  — 知识库检索（RAG，从文档切片中查找相关内容）

每个工具包含两个部分：
  - 定义（definition）：OpenAI 格式的 JSON Schema，给 LLM 看
  - 执行（execute）：实际的 Python 实现

工具注册表模式：
  新增工具只需在 TOOL_DEFINITIONS 中添加一条，并实现对应的执行函数。
"""

import ast
import json
import logging
import math

import httpx

from app.core.config import settings
from app.rag.retriever import Retriever

logger = logging.getLogger(__name__)

# ─── 工具定义（给 LLM 的 JSON Schema） ───

# 系统级工具定义（始终可用）
_SYSTEM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索互联网获取实时信息。当用户需要最新的新闻、实时数据、或你的知识库中没有的信息时使用。",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "执行数学计算。支持加减乘除、幂运算、三角函数等。当你需要精确计算数值时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '2 + 3 * 4', 'sqrt(16)', 'log(100)'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_retrieval",
            "description": "从知识库中检索与问题相关的文档内容。当用户询问需要参考内部文档、知识库中的资料时使用。",
            "parameters": {
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
        },
    },
]

# 动态工具注册表（从数据库加载的工具会合并到这里）
_dynamic_tools: list[dict] = []


def get_tool_definitions() -> list[dict]:
    """
    获取所有可用工具定义（系统工具 + 动态工具）。

    OpenAI / DeepSeek API 的 tools 参数格式。
    """
    return _SYSTEM_TOOLS + _dynamic_tools


def register_dynamic_tools(tools: list[dict]) -> None:
    """
    注册动态工具（从数据库加载）。

    参数：
        tools: 与 _SYSTEM_TOOLS 格式一致的 tool definition 列表
    """
    _dynamic_tools.clear()
    _dynamic_tools.extend(tools)
    logger.info(f"已注册 {len(tools)} 个动态工具")


# ─── 工具执行 ───


async def execute_tool(tool_call: dict, context: dict | None = None) -> str:
    """
    执行一个工具调用。

    参数：
        tool_call: LLM 返回的工具调用，格式：
            {
                "id": "call_xxx",
                "function": {
                    "name": "web_search",
                    "arguments": "{\"query\": \"...\"}"
                }
            }
        context: 可选的上下文信息，包含：
            - retriever: Retriever 实例（用于 knowledge_retrieval）
            - kb_ids: 知识库 ID 列表
            - pg_db: PostgreSQL 会话

    返回：
        工具执行结果的文本描述
    """
    func_name = tool_call.get("function", {}).get("name", "")
    try:
        args = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
    except json.JSONDecodeError:
        return f"错误：无法解析工具参数 - {tool_call.get('function', {}).get('arguments', '')}"

    logger.info(f"执行工具: {func_name}({json.dumps(args, ensure_ascii=False)})")

    tool_map = {
        "web_search": _execute_web_search,
        "calculator": _execute_calculator,
        "knowledge_retrieval": _execute_knowledge_retrieval,
    }

    executor = tool_map.get(func_name)
    if not executor:
        return f"错误：未知工具 '{func_name}'，可用工具：{', '.join(tool_map.keys())}"

    try:
        result = await executor(args, context)
        return result
    except Exception as e:
        logger.exception(f"工具 '{func_name}' 执行失败")
        return f"工具 '{func_name}' 执行出错：{str(e)}"


# ─── 工具 1：联网搜索 ───


async def _execute_web_search(args: dict, context: dict | None = None) -> str:
    """
    通过 HTTP 调用外部搜索 API 执行联网搜索。

    配置方式（settings.SEARCH_API_URL）：
      - 如果设置了 SEARCH_API_URL，则调用该地址
      - 否则返回提示信息（开发阶段可 mock）
    """
    query = args.get("query", "")
    max_results = args.get("max_results", 5)

    if not query:
        return "错误：搜索关键词不能为空"

    search_url = getattr(settings, "SEARCH_API_URL", "")

    if not search_url:
        # 开发环境未配置搜索 API，返回 mock 结果
        logger.warning("SEARCH_API_URL 未配置，返回模拟搜索结果")
        return (
            f"【联网搜索 - 模拟结果】\n"
            f"搜索关键词：{query}\n\n"
            f"注意：系统未配置搜索 API，以下为模拟占位结果。\n"
            f"如需真实搜索功能，请在 .env 中配置 SEARCH_API_URL。"
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                search_url,
                params={"q": query, "count": max_results},
            )
            response.raise_for_status()
            data = response.json()

        # 通用解析（适配不同搜索 API 的返回格式）
        results = data.get("results", data.get("items", [data]))
        formatted = []
        for i, item in enumerate(results[:max_results], 1):
            title = item.get("title", item.get("name", "无标题"))
            snippet = item.get("snippet", item.get("description", item.get("content", "")))
            url = item.get("url", item.get("link", ""))
            formatted.append(f"{i}. {title}\n   {snippet}\n   {url}")

        return "\n\n".join(formatted) if formatted else f"未找到 '{query}' 的相关结果"

    except httpx.HTTPError as e:
        logger.error(f"搜索 API 请求失败: {e}")
        return f"搜索请求失败：{str(e)}"
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"搜索 API 返回格式异常: {e}")
        return f"搜索结果解析失败：{str(e)}"


# ─── 工具 2：计算器 ───


# 安全数学环境 — 只允许安全的函数和常量
_SAFE_ENV = {
    # 数学常量
    "pi": math.pi,
    "e": math.e,
    # 基础运算
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    # 数学函数（通过 ast 调用）
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
}

# 允许的 AST 节点类型
_ALLOWED_NODES = {
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.FloorDiv,
    ast.Mod,
    ast.USub,
    ast.UAdd,
}


def _safe_eval(expr: str) -> float:
    """
    安全计算数学表达式。

    只允许白名单中的 AST 节点，杜绝任意代码执行。
    支持：数值、运算符、函数调用、变量引用。
    """
    tree = ast.parse(expr, mode="eval")
    # 递归检查所有节点是否在白名单中
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise ValueError(f"表达式包含不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in _SAFE_ENV:
            raise ValueError(f"不允许的变量或函数：'{node.id}'")

    compiled = compile(tree, "<string>", "eval")
    result = eval(compiled, {"__builtins__": {}}, _SAFE_ENV)
    return float(result)


async def _execute_calculator(args: dict, context: dict | None = None) -> str:
    """安全执行数学计算"""
    expression: str = args.get("expression", "").strip()
    if not expression:
        return "错误：表达式不能为空"

    try:
        result = _safe_eval(expression)
        # 如果是整数结果，去掉多余的 .0
        if result == int(result) and not isinstance(result, bool):
            display = str(int(result))
        else:
            display = f"{result:.6f}".rstrip("0").rstrip(".")
        return f"{expression} = {display}"
    except ValueError as e:
        return f"计算错误：{e}"
    except SyntaxError:
        return f"表达式语法错误：'{expression}'"
    except ZeroDivisionError:
        return "计算错误：除数不能为零"
    except Exception as e:
        return f"计算错误：{str(e)}"


# ─── 工具 3：知识库检索 ───


async def _execute_knowledge_retrieval(args: dict, context: dict | None = None) -> str:
    """
    从知识库中检索相关内容。

    需要 context 中包含 retriever 实例。
    如果 retriever 不可用，返回提示信息。
    """
    query = args.get("query", "")
    top_k = args.get("top_k", 5)

    if not query:
        return "错误：检索关键词不能为空"

    retriever: Retriever | None = context.get("retriever") if context else None
    if not retriever or not retriever.embedder.is_available:
        return "知识库检索不可用：Embedding 服务未配置或不可用"

    try:
        # 如果指定了知识库 ID 范围，传递 document_ids
        kb_ids = context.get("kb_ids") if context else None
        doc_ids = context.get("document_ids") if context else None

        result = await retriever.retrieve_with_details(
            query=query,
            top_k=top_k,
            document_ids=doc_ids,
        )

        if not result["has_results"]:
            return "未在知识库中找到与问题相关的内容。"

        # 格式化检索结果
        parts = [f"从知识库中找到 {result['chunk_count']} 条相关内容：\n"]
        for i, chunk in enumerate(result["chunks"], 1):
            similarity = chunk.get("similarity", 0)
            parts.append(
                f"[结果 {i}]（相似度：{similarity:.2f}）\n"
                f"{chunk['content']}"
            )

        return "\n---\n".join(parts)

    except Exception as e:
        logger.exception("知识库检索失败")
        return f"知识库检索出错：{str(e)}"
