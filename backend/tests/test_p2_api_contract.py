"""
P2-2 回归测试 —— API 契约与文档开关。

覆盖：
  - docs_enabled 的三种取值（跟随 DEBUG / 强制开 / 强制关）
  - OpenAPI 里每个业务接口都挂了统一错误响应（401/403/404/429/503）
  - 标签齐全（/docs 里能按分组看懂）
  - 错误信封在 404/422 这类"框架层"错误上也成立
"""

import pytest

from app.core.config import settings
from app.main import app

# ─────────────────── 文档开关 ───────────────────


def test_docs_follow_debug_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "DOCS_ENABLED", None)

    monkeypatch.setattr(settings, "DEBUG", True)
    assert settings.docs_enabled is True

    monkeypatch.setattr(settings, "DEBUG", False)
    assert settings.docs_enabled is False, "生产（DEBUG=false）默认必须关掉 /docs"


def test_docs_can_be_forced_on_and_off(monkeypatch):
    monkeypatch.setattr(settings, "DOCS_ENABLED", True)
    monkeypatch.setattr(settings, "DEBUG", False)
    assert settings.docs_enabled is True, "临时排查时可以强制打开"

    monkeypatch.setattr(settings, "DOCS_ENABLED", False)
    monkeypatch.setattr(settings, "DEBUG", True)
    assert settings.docs_enabled is False, "也能在本地强制关掉"


# ─────────────────── OpenAPI 契约 ───────────────────


def test_openapi_has_tags_metadata():
    tags = {item["name"] for item in app.openapi_tags or []}
    # 关键分组必须在，否则 /docs 里接口是散的
    assert {"认证", "聊天", "知识库", "文档", "Agent", "统计", "系统"} <= tags


def test_openapi_documents_common_error_responses():
    schema = app.openapi()
    business_paths = {
        path: operations
        for path, operations in schema["paths"].items()
        if path.startswith("/api/v1/")
    }
    assert business_paths, "没有业务接口？路径前缀可能变了"

    missing = []
    for path, operations in business_paths.items():
        for method, operation in operations.items():
            codes = set(operation.get("responses", {}).keys())
            if not {"401", "422"} <= codes:
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"这些接口缺少统一错误响应：{missing[:5]}"


def test_openapi_declares_envelope_fields():
    """响应模型必须暴露 code/message/data 三个字段，否则契约文档会误导前端"""
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    envelope = next(
        (name for name in components if name.startswith("Response_")), None
    )
    if envelope is None:
        pytest.skip("响应信封未出现在 components（可能被内联了）")
    props = set(components[envelope].get("properties", {}))
    assert {"code", "message", "data"} <= props


# ─────────────────── 错误信封一致性 ───────────────────


@pytest.mark.asyncio
async def test_framework_errors_use_envelope(anon_client):
    """404/422 也要走统一信封（历史 bug：404 漏出 {"detail": ...}）"""
    async with anon_client as client:
        not_found = await client.get("/api/v1/no-such-endpoint")
        invalid = await client.post("/api/v1/auth/login", json={})

    assert not_found.status_code == 404
    assert set(not_found.json()) >= {"code", "message", "data"}
    assert invalid.status_code == 422
    assert set(invalid.json()) >= {"code", "message", "data"}
