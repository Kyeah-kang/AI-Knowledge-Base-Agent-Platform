"""
P1-14 回归测试 — 上游调用的超时、重试与分批

四个契约：
  1. 429 / 5xx / 连接失败 → 自动重试（指数退避），最终成功则不惊动用户
  2. 4xx（参数错误、鉴权失败）→ **不重试**，重试只会白烧钱
  3. 重试用尽 → 抛原始异常，由调用方包装成 502
  4. Embedding 按批提交（默认 32），一批失败不影响其他批，且顺序必须保持

不依赖网络：用 httpx.Response 构造真实的 openai 异常对象。
"""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, BadRequestError, InternalServerError, RateLimitError

from app.core import metrics
from app.core import retry as retry_mod
from app.core.config import settings
from app.rag.embeddings import EmbeddingService
from app.services.llm_service import LLMService

REQ = httpx.Request("POST", "https://api.test/v1/chat/completions")


def rate_limit_error() -> RateLimitError:
    return RateLimitError(
        "429 rate limited", response=httpx.Response(429, request=REQ), body=None
    )


def server_error() -> InternalServerError:
    return InternalServerError(
        "500 internal", response=httpx.Response(500, request=REQ), body=None
    )


def bad_request_error() -> BadRequestError:
    return BadRequestError(
        "400 bad request", response=httpx.Response(400, request=REQ), body=None
    )


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """把退避里的 sleep 换成 no-op，避免测试真的等待"""
    sleeps = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(retry_mod, "_sleep", fake_sleep)
    metrics.reset()
    yield sleeps
    metrics.reset()


# ─────────────────── 重试基础行为 ───────────────────


@pytest.mark.asyncio
async def test_retries_429_then_succeeds(_fast_retry):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise rate_limit_error()
        return "ok"

    assert await retry_mod.call_with_retry(fn, operation="t", max_retries=2) == "ok"
    assert calls["n"] == 2
    assert len(_fast_retry) == 1, "应该退避一次"
    counters = metrics.snapshot()["counters"]
    assert counters.get("external_retry_total{operation=t}") == 1


@pytest.mark.asyncio
async def test_retries_connection_error(_fast_retry):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise APIConnectionError(request=REQ)
        return "ok"

    assert await retry_mod.call_with_retry(fn, operation="t", max_retries=1) == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_does_not_retry_4xx(_fast_retry):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise bad_request_error()

    with pytest.raises(BadRequestError):
        await retry_mod.call_with_retry(fn, operation="t", max_retries=3)

    assert calls["n"] == 1, "4xx 不该重试"
    assert _fast_retry == []


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(_fast_retry):
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise server_error()

    with pytest.raises(InternalServerError):
        await retry_mod.call_with_retry(fn, operation="t", max_retries=2)

    assert calls["n"] == 3, "1 次初始 + 2 次重试"
    counters = metrics.snapshot()["counters"]
    assert counters.get("external_call_total{operation=t,status=fail}") == 1


# ─────────────────── LLMService 接入 ───────────────────


def _fake_completion(content: str = "你好"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.mark.asyncio
async def test_llm_chat_retries_then_succeeds(monkeypatch):
    svc = LLMService()
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise server_error()
        return _fake_completion("重试后的回答")

    svc.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    result = await svc.chat([{"role": "user", "content": "hi"}], use_cache=False)

    assert result == "重试后的回答"
    assert calls["n"] == 2
    counters = metrics.snapshot()["counters"]
    assert counters.get("external_retry_total{operation=llm_chat}") == 1
    assert counters.get("llm_tokens_total{kind=prompt,operation=llm_chat}") == 10


def test_llm_client_disables_sdk_retry_and_sets_timeout():
    """SDK 自带重试必须关掉，否则会和自研重试相乘"""
    svc = LLMService()
    assert svc.client.max_retries == 0
    assert svc.client.timeout == settings.LLM_TIMEOUT_SECONDS


class FakeStream:
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for text in self._chunks:
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
                )

        return gen()


@pytest.mark.asyncio
async def test_llm_stream_retries_create_only(_fast_retry):
    """建流失败可重试；重试成功后不得重复吐 token"""
    svc = LLMService()
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise server_error()
        return FakeStream(["你", "好"])

    svc.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    tokens = [t async for t in svc.chat_stream([{"role": "user", "content": "hi"}])]

    assert tokens == ["你", "好"]
    assert calls["n"] == 2


# ─────────────────── Embedding 分批 ───────────────────


def make_embedding_service(call_log: list[int], dimensions: int = 4) -> EmbeddingService:
    svc = EmbeddingService.__new__(EmbeddingService)
    svc.model = "fake-embed"
    svc.dimension = dimensions
    svc._available = True

    async def fake_create(model: str, input):  # noqa: A002 - 与 SDK 签名一致
        call_log.append(len(input))
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1] * dimensions) for _ in input]
        )

    svc.client = SimpleNamespace(
        embeddings=SimpleNamespace(create=fake_create)
    )
    return svc


@pytest.mark.asyncio
async def test_embed_batch_splits_by_batch_size(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2, raising=False)
    log: list[int] = []
    svc = make_embedding_service(log)

    vectors = await svc.embed_batch(["a", "b", "c", "d", "e"])

    assert log == [2, 2, 1], f"应按 2 条一批切分，实际 {log}"
    assert len(vectors) == 5


@pytest.mark.asyncio
async def test_embed_batch_keeps_order_with_empty_texts(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2, raising=False)
    log: list[int] = []
    svc = make_embedding_service(log, dimensions=4)

    vectors = await svc.embed_batch(["a", "   ", "c"])

    assert log == [2], "空文本不该提交给上游"
    assert vectors[1] == [0.0] * 4, "空文本要补零向量占位"
    assert vectors[0] == [0.1] * 4 and vectors[2] == [0.1] * 4


@pytest.mark.asyncio
async def test_embed_batch_retries_transient_failure(monkeypatch, _fast_retry):
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_MAX_RETRIES", 2, raising=False)

    calls = {"n": 0}

    async def fake_create(model: str, input):  # noqa: A002
        calls["n"] += 1
        if calls["n"] == 1:
            raise server_error()
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1] * 4) for _ in input]
        )

    svc = EmbeddingService.__new__(EmbeddingService)
    svc.model = "fake-embed"
    svc.dimension = 4
    svc._available = True
    svc.client = SimpleNamespace(embeddings=SimpleNamespace(create=fake_create))

    vectors = await svc.embed_batch(["a", "b"])

    assert len(vectors) == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_embed_batch_wraps_final_failure(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_MAX_RETRIES", 0, raising=False)

    async def always_fail(model: str, input):  # noqa: A002
        raise server_error()

    svc = EmbeddingService.__new__(EmbeddingService)
    svc.model = "fake-embed"
    svc.dimension = 4
    svc._available = True
    svc.client = SimpleNamespace(embeddings=SimpleNamespace(create=always_fail))

    with pytest.raises(RuntimeError, match="批量 Embedding 生成失败"):
        await svc.embed_batch(["a"])
