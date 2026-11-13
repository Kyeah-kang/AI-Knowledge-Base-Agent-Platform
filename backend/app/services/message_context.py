"""
LLM 上下文装配 — chat 与 agent 的唯一入口。

为什么单独抽一个模块（P0-2）：
  原来 `chat_service` 与 `agent_service` 各自有一份 `_get_context_messages`，
  两处的时序都是「先保存用户消息 → 再读最近 N 条（已包含当前消息）→ 再拼一次当前问题」，
  于是同一个问题在 prompt 里出现两次。
  这类"同一段逻辑复制两份"的 bug 修一处漏一处，所以收敛成单实现 + 单测。

P1-5 之后，这里同时负责 **token 预算**：
  只按条数截断（固定 20 条）在两种情况下都会出问题 ——
  20 条长消息可能直接超窗，20 条短消息又白白浪费预算。
  现在的策略是「先按条数取候选，再从最旧的开始按 token 预算丢弃」。
"""

import logging

from app.core import metrics
from app.core.config import settings

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """复用 LLMService 的估算口径，保证"预算"和"实际调用"用同一套算法"""
    from app.services.llm_service import LLMService

    return LLMService.count_tokens(text or "")


async def load_history(
    message_repo,
    session_id: int,
    *,
    current_message_id: int | None = None,
    limit: int | None = None,
    token_budget: int | None = None,
) -> list[dict]:
    """
    读取最近的历史消息，排除"当前这条"，并按 token 预算裁剪。

    参数：
        message_repo: ChatMessageRepository（任何提供 get_recent_history 的对象）
        session_id: 会话 ID
        current_message_id: 刚保存的用户消息 ID —— **必须排除**。调用方随后会用
            `LLMService.build_messages()` 把同一条内容再拼一次，不排除就会出现两次。
        limit: 条数上限，默认 `settings.CONTEXT_HISTORY_LIMIT`
        token_budget: token 预算，默认 `settings.CONTEXT_MAX_TOKENS`

    返回：
        LLM API 要求的消息格式：[{"role": "user", "content": "..."}, ...]（时间正序）

    裁剪规则：
        从**最新**往前累加，超出预算就从最旧的那条开始丢；
        永远保留至少一条（哪怕它本身就超预算），否则多轮对话会退化成单轮。
    """
    limit = settings.CONTEXT_HISTORY_LIMIT if limit is None else limit
    budget = settings.CONTEXT_MAX_TOKENS if token_budget is None else token_budget

    recent = await message_repo.get_recent_history(
        session_id, limit=limit, exclude_id=current_message_id
    )
    if not recent:
        return []

    kept: list = []
    used = 0
    for message in reversed(recent):  # 从新到旧
        cost = _estimate_tokens(getattr(message, "content", "") or "")
        if kept and used + cost > budget:
            metrics.incr("context_trim_total", reason="token_budget")
            logger.info(
                "会话 #%s 历史超预算（已用 %s / 预算 %s token），丢弃 %s 条更早的消息",
                session_id,
                used,
                budget,
                len(recent) - len(kept),
            )
            break
        kept.append(message)
        used += cost

    kept.reverse()
    return [{"role": m.role, "content": m.content} for m in kept]
