"""
LLM 服务 — 对接 DeepSeek API（OpenAI 兼容）

作用：相当于连接 DeepSeek 大模型的"电话线"

支持两种模式：
  1. 一次性返回（非流式）：适用于需要完整回复的场景
  2. SSE 流式输出：逐 token 推送，用户体验更好
"""

from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import AppException


class LLMService:
    """
    LLM 调用服务
    """

    def __init__(self):
        # 初始化异步客户端，传入模型密钥、接口地址
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
        )
        # 从配置读取模型名称、最大生成长度、温度系数
        self.model = settings.LLM_MODEL_NAME
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.temperature = settings.LLM_TEMPERATURE

    async def chat(self, messages: list[dict], use_cache: bool = True) -> str:
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
        # 尝试从缓存读取（非工具调用场景）
        if use_cache:
            try:
                from app.core.cache import get_cached_llm_response
                cached = await get_cached_llm_response(messages, self.model)
                if cached is not None:
                    return cached
            except ImportError:
                pass

        try:
            # 调用大模型接口，关闭流式输出
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False,
            )
            # 提取模型返回的文本内容并返回
            result = response.choices[0].message.content or ""

            # 非工具调用场景下缓存结果
            if use_cache:
                try:
                    from app.core.cache import cache_llm_response
                    await cache_llm_response(messages, self.model, result)
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

    async def chat_with_tools(
        self, messages: list[dict], tools: list[dict] | None = None
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
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)
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

    async def chat_stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """
        流式调用 — 逐 token 异步生成，用于 SSE 推送。

        使用 async for 逐块读取，每块包含一个 token 片段。
        """
        try:
            # 开启流式输出，获取流式响应对象
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,  # ← 启用流式
            )
            # 循环逐块读取模型返回内容
            async for chunk in stream:
                # 只有当前 chunk 包含有效候选回答时，才继续处理。
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    # 逐片段向外输出文本，实现打字机效果
                    if delta.content:
                        yield delta.content

        except Exception as e:
            raise AppException(
                code=502,
                message=f"LLM 流式调用失败：{str(e)}",
                http_status_code=502,
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
        粗略估算 token 数量。

        注意：这不是精确计算，只是一个估算。
        中文字符约 1.5-2 tokens/字，英文约 1 token/4 字符。
        这里用简单的 4 字符 ≈ 1 token 估算，偏向保守。
        """
        return len(text) // 4 + 1
