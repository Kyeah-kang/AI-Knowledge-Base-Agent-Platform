"""
LLM 服务 — 对接 DeepSeek API（OpenAI 兼容）

作用：相当于连接 DeepSeek 大模型的"电话线"

支持两种模式：
  1. 一次性返回（非流式）：适用于需要完整回复的场景
  2. SSE 流式输出：逐 token 推送，用户体验更好
"""

import logging
import time
from collections.abc import AsyncGenerator
from functools import partial
from typing import Any

from openai import AsyncOpenAI

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.retry import call_with_retry

logger = logging.getLogger(__name__)


class LLMService:
    """
    LLM 调用服务
    """

    def __init__(self, model: str | None = None):
        # 初始化异步客户端，传入模型密钥、接口地址
        # 超时与重试（P1-14）：
        #   - timeout 必须有，否则上游卡住时请求会一直挂着
        #   - max_retries=0 是故意的：重试统一交给 app.core.retry，
        #     否则 SDK 自带重试会和自研重试相乘，一次故障被放大成 N×M 次调用
        # 未配置 key 时也要能构造出来（CI/纯离线环境）：
        # OpenAI SDK 不接受空 api_key，会直接抛 OpenAIError，
        # 那会让"任何实例化 LLMService 的路径"（聊天、Agent、测试）全部崩掉，
        # 而不是给出一个"调用时 401"的清晰错误。
        self.is_available = bool(settings.LLM_API_KEY)
        if not self.is_available:
            logger.warning(
                "LLM_API_KEY 未配置：服务仍可启动，但所有 LLM 调用都会失败（请检查环境变量）"
            )
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY or "unset",
            base_url=settings.LLM_API_BASE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        # 从配置读取模型名称、最大生成长度、温度系数
        # P2-4：model 允许在构造时指定（会话/请求级），不再死用配置值
        self.model = self.resolve_model(model)
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.temperature = settings.LLM_TEMPERATURE

    # 逻辑在模块级 resolve_model_name() 里，service 层可直接 import；
    # 这里保留一个真正的 staticmethod 包装（动态赋值 mypy 认不出来）
    @staticmethod
    def resolve_model(requested: str | None) -> str:
        return resolve_model_name(requested)

    def _model_chain(self, requested: str | None = None) -> list[str]:
        """主模型 + 备选链（去重、保序）"""
        chain = [self.resolve_model(requested or self.model)]
        for candidate in settings.LLM_FALLBACK_MODELS:
            if candidate and candidate not in chain:
                chain.append(candidate)
        return chain

    async def _call_with_model_fallback(self, factory, operation: str, model: str | None):
        """
        调上游并支持**主备切换**（P2-4）。

        factory(model_name) -> awaitable
        只有"换模型可能有用"的错误才切下一个：超时、连接失败、429、5xx。
        400（模型不存在/参数错）换模型也白搭，直接抛。

        注意：流式调用只在**建流**阶段走这里；一旦开始吐 token 就不能再切，
        否则前端会收到两个模型的片段拼在一起。
        """
        chain = self._model_chain(model)
        last_error: Exception | None = None

        for index, candidate in enumerate(chain):
            try:
                # partial 把当前 candidate 绑定住：循环变量是晚绑定的，
                # 用 lambda 会让"重试时用的是最后一次循环的模型"
                return await call_with_retry(
                    partial(factory, candidate),
                    operation=operation,
                    max_retries=settings.LLM_MAX_RETRIES,
                )
            except Exception as e:
                last_error = e
                has_next = index < len(chain) - 1
                if not has_next or not _is_switchable(e):
                    raise
                metrics.incr("llm_model_fallback_total", reason="upstream_error")
                logger.warning(
                    "模型 %s 调用失败（%s），切换到 %s", candidate, e, chain[index + 1]
                )

        raise last_error or RuntimeError("模型调用失败")  # pragma: no cover

    def _record_usage(self, response, operation: str) -> None:
        """
        记录 token 用量与延迟（P1-14 的可观测部分）。

        接入正式监控（B4-1）之前，这些数字至少能在 `/health` 的 metrics 里看到，
        用来回答"每次问答大概花多少 token"。
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        metrics.incr(
            "llm_tokens_total",
            value=int(getattr(usage, "prompt_tokens", 0) or 0),
            kind="prompt",
            operation=operation,
        )
        metrics.incr(
            "llm_tokens_total",
            value=int(getattr(usage, "completion_tokens", 0) or 0),
            kind="completion",
            operation=operation,
        )

    async def chat(
        self, messages: list[dict], use_cache: bool = True, model: str | None = None
    ) -> str:
        """
        非流式调用 — 等待完整回复后一次性返回。

        messages 格式示例：
            [
                {"role": "system", "content": "你是一个AI助手"},
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！有什么可以帮你的？"},
                {"role": "user", "content": "今天天气怎么样？"},
            ]

        参数：
            messages: LLM 消息列表
            use_cache: 是否使用缓存（默认 True）。Agent 工具调用等场景建议关闭。

        返回：
            LLM 的回复文本
        """
        effective_model = self.resolve_model(model or self.model)

        # 尝试从缓存读取（非工具调用场景）
        if use_cache:
            try:
                from app.core.cache import get_cached_llm_response
                cached = await get_cached_llm_response(messages, effective_model)
                if cached is not None:
                    return cached
            except ImportError:
                pass

        started = time.perf_counter()
        try:
            # 调用大模型接口，关闭流式输出（超时/429/5xx 由 call_with_retry 兜住）
            response = await self._call_with_model_fallback(
                # 我们的 messages 是普通 dict 列表，运行时与 SDK 的 TypedDict 完全兼容，
                # 但静态类型对不上（SDK 用 ChatCompletionMessageParam 联合类型）
                lambda name: self.client.chat.completions.create(
                    model=name,
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stream=False,
                ),
                operation="llm_chat",
                model=effective_model,
            )
            # 提取模型返回的文本内容并返回
            result = response.choices[0].message.content or ""
            self._record_usage(response, "llm_chat")

            # 非工具调用场景下缓存结果
            if use_cache:
                try:
                    from app.core.cache import cache_llm_response
                    await cache_llm_response(messages, effective_model, result)
                except ImportError:
                    pass

            return result

        except Exception as e:
            # 统一包装成 AppException，让异常处理器统一处理
            raise AppException(
                code=502,
                message=f"LLM 调用失败：{str(e)}",
                http_status_code=502,
            )
        finally:
            metrics.observe_ms(
                "llm_latency", (time.perf_counter() - started) * 1000, operation="chat"
            )

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        """
        调用 LLM，传入消息 + 工具定义（function calling）。

        LLM 可能返回两种结果：
          1. 直接回答 → {"type": "content", "content": "回答文本"}
          2. 工具调用 → {"type": "tool_calls", "tool_calls": [...]}

        参数：
            messages: 消息列表（system/user/assistant/tool 角色）
            tools: OpenAI 格式的工具定义列表（function calling schema）

        返回：
            包含 type 字段的字典，调用方根据 type 决定后续流程
        """
        started = time.perf_counter()
        try:
            base_kwargs = {
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            if tools:
                base_kwargs["tools"] = tools
                base_kwargs["tool_choice"] = "auto"

            response = await self._call_with_model_fallback(
                # **base_kwargs 把 tools/tool_choice 一起展开，SDK 的 overload 推断不了
                lambda name: self.client.chat.completions.create(
                    model=name, **base_kwargs  # type: ignore[call-overload]
                ),
                operation="llm_tools",
                model=model or self.model,
            )
            self._record_usage(response, "llm_tools")
            message = response.choices[0].message

            # 情况 1：LLM 返回了工具调用请求
            if hasattr(message, "tool_calls") and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )
                return {"type": "tool_calls", "tool_calls": tool_calls}

            # 情况 2：LLM 直接返回文本回答
            return {"type": "content", "content": message.content or ""}

        except Exception as e:
            raise AppException(
                code=502,
                message=f"LLM 工具调用失败：{str(e)}",
                http_status_code=502,
            )
        finally:
            metrics.observe_ms(
                "llm_latency", (time.perf_counter() - started) * 1000, operation="tools"
            )

    async def chat_stream(
        self, messages: list[dict], model: str | None = None
    ) -> AsyncGenerator[str]:
        """
        流式调用 — 逐 token 异步生成，用于 SSE 推送。

        使用 async for 逐块读取，每块包含一个 token 片段。

        重试策略（P1-14）：**只重试"建流"这一步**。
          流一旦开始吐 token 就没法回滚，重试会让前端收到重复片段；
          所以建流失败按 429/5xx/超时重试，读流中途失败直接抛错。
        """
        started = time.perf_counter()
        first_token_ms: float | None = None
        try:
            # 开启流式输出，获取流式响应对象（这一步可重试、可切备用模型）
            # 注意：只对"建流"做重试与主备切换 —— 一旦开始吐 token 就不能换模型，
            # 否则前端会收到两个模型的片段拼在一起。
            stream = await self._call_with_model_fallback(
                lambda name: self.client.chat.completions.create(
                    model=name,
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    stream=True,  # ← 启用流式
                ),
                operation="llm_stream",
                model=model or self.model,
            )
            # 循环逐块读取模型返回内容
            async for chunk in stream:
                # 只有当前 chunk 包含有效候选回答时，才继续处理。
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    # 逐片段向外输出文本，实现打字机效果
                    if delta.content:
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - started) * 1000
                            metrics.observe_ms("llm_first_token_latency", first_token_ms)
                        yield delta.content

        except Exception as e:
            raise AppException(
                code=502,
                message=f"LLM 流式调用失败：{str(e)}",
                http_status_code=502,
            )
        finally:
            metrics.observe_ms(
                "llm_latency", (time.perf_counter() - started) * 1000, operation="stream"
            )

    async def chat_with_tools_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[tuple[str, Any]]:
        """
        流式版工具调用：**边生成边吐 token**，同时把 tool_calls 收齐。

        产出：
            ("token", "文本片段")     —— 模型正在直接回答，逐片段推送
            ("tool_calls", [...])     —— 流结束后若有工具调用，一次性交出完整参数

        为什么不像非流式那样"先问一次有没有工具调用"：
          那个判断本身就要花掉一次完整调用。这里用一次流式调用同时拿到两样东西：
          想回答就边生成边推给前端；想调工具，就在流结束后收齐参数再去执行。
          这正是 P1-6「Agent 不是真流式」的修法 —— 原来是把完整回答攒好再一次性推。

        注意：不重试"读流"（吐出去的内容无法回滚，重试会出现重复片段），
        只重试"建流"这一步。
        """
        base_kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if tools:
            base_kwargs["tools"] = tools
            base_kwargs["tool_choice"] = "auto"

        started = time.perf_counter()
        first_token_ms: float | None = None
        try:
            # 同上：只在建流阶段允许重试与切换备用模型
            stream = await self._call_with_model_fallback(
                lambda name: self.client.chat.completions.create(
                    model=name, **base_kwargs  # type: ignore[call-overload]
                ),
                operation="llm_tools_stream",
                model=model or self.model,
            )

            # index → 工具调用片段累积（流式下 function.arguments 是分片到达的）
            buffers: dict[int, dict[str, Any]] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                text = getattr(delta, "content", None)
                if text:
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000
                        metrics.observe_ms("llm_first_token_latency", first_token_ms)
                    yield ("token", text)

                for tc in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc, "index", 0) or 0
                    slot = buffers.setdefault(
                        index, {"id": None, "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    function = getattr(tc, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            slot["arguments"] += function.arguments

            if buffers:
                tool_calls = [
                    {
                        "id": slot["id"] or f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": slot["name"],
                            "arguments": slot["arguments"] or "{}",
                        },
                    }
                    for index, slot in sorted(buffers.items())
                ]
                yield ("tool_calls", tool_calls)

        except Exception as e:
            raise AppException(
                code=502,
                message=f"LLM 流式工具调用失败：{str(e)}",
                http_status_code=502,
            )
        finally:
            metrics.observe_ms(
                "llm_latency",
                (time.perf_counter() - started) * 1000,
                operation="tools_stream",
            )

    @staticmethod
    def build_messages(
        user_content: str,
        history: list[dict] | None = None,
        system_prompt: str | None = None,
    ) -> list[dict]:
        """
        构建发送给 LLM 的消息列表。

        组装顺序（按 LLM API 要求）：
            1. system（可选）
            2. 历史消息（可选，按时间正序）
            3. 当前用户消息
        """
        messages = []

        # 拼接系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 拼接历史对话上下文
        if history:
            messages.extend(history)

        # 拼接当前用户提问
        messages.append({"role": "user", "content": user_content})

        return messages

    @staticmethod
    def count_tokens(text: str) -> int:
        """
        粗略估算 token 数量（用于上下文预算裁剪）。

        注意：这不是精确值，只是估算，且**故意偏保守**：
          中文字符基本是 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。
        原来的实现是 `len(text)//4 + 1`，对中文会低估到 25%，
        用它做预算会让"已经超窗"的历史被当成没超（P1-5）。
        """
        if not text:
            return 0
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return cjk + other // 4 + 1

def resolve_model_name(requested: str | None) -> str:
    """
    把"请求里写的模型名"解析成"真正可用的模型名"（P2-4）。

    规则：在白名单里就用它；不在就用默认模型，并记一次指标 + 一条 warn。
    为什么不直接抛 400：模型名是前端/用户传的，写错一个字母就整轮问答失败，
    体验比"悄悄退回默认"差得多；但**必须可见**，所以有指标和日志。
    """
    allowed = settings.LLM_ALLOWED_MODELS or [settings.LLM_MODEL_NAME]
    if requested and requested in allowed:
        return requested
    if requested and requested != settings.LLM_MODEL_NAME:
        metrics.incr("llm_model_fallback_total", reason="not_allowed")
        logger.warning(
            "模型 %s 不在允许列表 %s 中，改用默认模型 %s",
            requested,
            allowed,
            settings.LLM_MODEL_NAME,
        )
    return settings.LLM_MODEL_NAME


def _is_switchable(exc: Exception) -> bool:
    """
    这个错误"换一个模型重试"有没有意义？

    有：超时、连接失败、429 限流、5xx（上游或某个模型挂了）
    没有：4xx 参数错误、模型不存在（换谁都一样，重试只是浪费配额）
    """
    from app.core.retry import RETRYABLE_STATUS

    status = getattr(exc, "status_code", None)
    if status in RETRYABLE_STATUS:
        return True
    return type(exc).__name__ in {
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "RateLimitError",
    }