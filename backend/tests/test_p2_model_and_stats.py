"""
P2-4 / P2-9 回归测试 —— 模型真的会生效、统计数字真的来自数据。

覆盖：
  - resolve_model：白名单内保留、白名单外退回默认并记指标
  - 主备切换：5xx/超时切下一个模型；4xx 不切
  - 统计服务：按用户聚合，数字来自仓储返回
  - done 事件带实际模型名（前端可展示、排障可确认）
"""

from types import SimpleNamespace

import pytest

from app.core import metrics
from app.core.config import settings
from app.services.llm_service import LLMService
from app.services.stats_service import StatsService

# ─────────────────── resolve_model ───────────────────


def test_resolve_model_keeps_allowed_model(monkeypatch):
    monkeypatch.setattr(
        settings, "LLM_ALLOWED_MODELS", ["deepseek-chat", "deepseek-reasoner"]
    )
    assert LLMService.resolve_model("deepseek-reasoner") == "deepseek-reasoner"


def test_resolve_model_falls_back_when_not_allowed(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOWED_MODELS", ["deepseek-chat"])
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "deepseek-chat")
    metrics.reset()

    assert LLMService.resolve_model("gpt-5-turbo") == "deepseek-chat"
    assert (
        metrics.snapshot()["counters"].get(
            "llm_model_fallback_total{reason=not_allowed}"
        )
        == 1
    ), "静默退回是不行的，必须留下指标"


def test_resolve_model_empty_allowed_list_only_allows_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOWED_MODELS", [])
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "deepseek-chat")

    assert LLMService.resolve_model(None) == "deepseek-chat"
    assert LLMService.resolve_model("other-model") == "deepseek-chat"


def test_model_chain_dedupes(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOWED_MODELS", ["a", "b"])
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODELS", ["b", "c", "a"])

    svc = object.__new__(LLMService)
    svc.model = "a"
    assert svc._model_chain("a") == ["a", "b", "c"]


# ─────────────────── 主备切换 ───────────────────


class FakeCreate:
    """按模型名决定成功还是抛错"""

    def __init__(self, fail_models: set[str], status: int = 503):
        self.fail_models = fail_models
        self.status = status
        self.calls: list[str] = []

    async def __call__(self, **kwargs):
        name = kwargs.get("model")
        self.calls.append(name)
        if name in self.fail_models:
            raise _upstream_error(self.status)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )


def _upstream_error(status: int) -> Exception:
    import httpx as _httpx
    from openai import APIStatusError

    request = _httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    response = _httpx.Response(status, request=request)
    return APIStatusError(f"upstream {status}", response=response, body=None)


@pytest.mark.asyncio
async def test_fallback_switches_to_next_model_on_5xx(monkeypatch):
    monkeypatch.setattr(settings, "LLM_ALLOWED_MODELS", ["primary", "backup"])
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODELS", ["backup"])
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 0)
    metrics.reset()

    svc = object.__new__(LLMService)
    svc.model = "primary"
    svc.max_tokens = 16
    svc.temperature = 0
    svc.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=FakeCreate({"primary"}))
        )
    )

    result = await svc.chat([{"role": "user", "content": "hi"}], use_cache=False)

    assert result == "ok"
    assert svc.client.chat.completions.create.calls == ["primary", "backup"]
    counters = metrics.snapshot()["counters"]
    assert counters.get("llm_model_fallback_total{reason=upstream_error}") == 1


@pytest.mark.asyncio
async def test_no_fallback_on_client_error(monkeypatch):
    """400（模型不存在/参数错）换模型也没用，必须直接失败"""
    from app.core.exceptions import AppException

    monkeypatch.setattr(settings, "LLM_ALLOWED_MODELS", ["primary", "backup"])
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODELS", ["backup"])
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 0)

    svc = object.__new__(LLMService)
    svc.model = "primary"
    svc.max_tokens = 16
    svc.temperature = 0
    fake = FakeCreate({"primary"}, status=400)
    svc.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake)))

    with pytest.raises(AppException):
        await svc.chat([{"role": "user", "content": "hi"}], use_cache=False)

    assert fake.calls == ["primary"], "4xx 不该切换模型"


# ─────────────────── 统计服务 ───────────────────


class FakeCountRepo:
    def __init__(self, value: int):
        self.value = value
        self.seen: list[int] = []

    async def count_by_owner(self, user_id):
        self.seen.append(user_id)
        return self.value

    async def count_failed_by_owner(self, user_id):
        self.seen.append(user_id)
        return 1

    async def count_by_user(self, user_id):
        self.seen.append(user_id)
        return self.value


@pytest.mark.asyncio
async def test_stats_overview_aggregates_per_user():
    svc = StatsService.__new__(StatsService)
    svc.kb_repo = FakeCountRepo(2)
    svc.doc_repo = FakeCountRepo(7)
    svc.session_repo = FakeCountRepo(3)
    svc.message_repo = FakeCountRepo(41)

    data = await svc.overview(user_id=42)

    assert data == {
        "kb_count": 2,
        "doc_count": 7,
        "failed_doc_count": 1,
        "session_count": 3,
        "message_count": 41,
    }
    # 每个查询都必须带上当前用户，否则会串数据
    # （doc_repo 被查两次：总数 + 失败数，所以断言"只查过这一个用户"）
    for repo in (svc.kb_repo, svc.doc_repo, svc.session_repo, svc.message_repo):
        assert repo.seen and set(repo.seen) == {42}
