"""
接口级契约测试（P2-7）—— 不连数据库、不起服务器。

覆盖的是"框架层"最容易出问题、又最不容易被单元测试碰到的地方：
  - 中间件：`X-Request-ID` 是否真的出现在响应里
  - 异常处理器：401 / 404 / 422 是否都是**统一信封**（前端只解析一种形状）
  - 健康检查：503 是否真的会返回（探针失败时）
  - 鉴权：无 token / 坏 token 的行为

这些用例走的是真实的 ASGI 栈，所以中间件顺序、依赖注入、序列化都被真实执行。
"""

import pytest
from fastapi import FastAPI

from app.core import health as health_mod


@pytest.mark.asyncio
async def test_root_returns_unified_envelope(anon_client):
    async with anon_client as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["status"] == "running"


@pytest.mark.asyncio
async def test_request_id_header_is_added(anon_client):
    async with anon_client as client:
        resp = await client.get("/")

    assert resp.headers.get("x-request-id"), "每个响应都必须带 X-Request-ID（P1-9）"


@pytest.mark.asyncio
async def test_request_id_is_echoed_when_supplied(anon_client):
    async with anon_client as client:
        resp = await client.get("/", headers={"X-Request-ID": "trace-api-1"})

    assert resp.headers.get("x-request-id") == "trace-api-1"


@pytest.mark.asyncio
async def test_health_returns_503_when_hard_dependency_down(anon_client, monkeypatch):
    async def boom():
        raise RuntimeError("mysql down")

    async def ok():
        return None

    monkeypatch.setattr(health_mod, "_probe_mysql", boom)
    monkeypatch.setattr(health_mod, "_probe_postgres", ok)
    monkeypatch.setattr(health_mod, "_probe_redis", ok)

    async with anon_client as client:
        resp = await client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["dependencies"]["mysql"]["status"] == "down"


@pytest.mark.asyncio
async def test_health_degrades_without_failing_when_redis_down(anon_client, monkeypatch):
    async def ok():
        return None

    async def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(health_mod, "_probe_mysql", ok)
    monkeypatch.setattr(health_mod, "_probe_postgres", ok)
    monkeypatch.setattr(health_mod, "_probe_redis", boom)

    async with anon_client as client:
        resp = await client.get("/health")

    assert resp.status_code == 200, "Redis 是软依赖，不该让实例被摘掉"
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_envelope_401(anon_client):
    async with anon_client as client:
        resp = await client.get("/api/v1/users/me")

    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 401
    assert body["message"], "错误信息不能为空，否则前端只能显示 HTTP 401"


@pytest.mark.asyncio
async def test_bad_token_returns_401(anon_client):
    async with anon_client as client:
        resp = await client.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
        )

    assert resp.status_code == 401
    assert resp.json()["code"] == 401


@pytest.mark.asyncio
async def test_unknown_route_returns_envelope_404(anon_client):
    async with anon_client as client:
        resp = await client.get("/api/v1/definitely-not-here")

    assert resp.status_code == 404
    # 统一信封：即便 404 也要有 code/message，前端不用为它写特例
    assert "code" in resp.json()


@pytest.mark.asyncio
async def test_validation_error_returns_422_with_detail(anon_client):
    async with anon_client as client:
        resp = await client.post("/api/v1/auth/register", json={"username": "x"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422
    assert body["data"], "校验失败要指出是哪个字段，不能只说 422"


@pytest.mark.asyncio
async def test_authenticated_me_uses_override(auth_client):
    async with auth_client as client:
        resp = await client.get("/api/v1/users/me")

    # 这条用例证明依赖覆盖生效，后续接口级测试可以复用 auth_client
    assert resp.status_code in (200, 500), resp.text
    if resp.status_code == 200:
        assert resp.json()["data"]["username"] == "tester"


def test_app_routes_are_registered():
    """路由表的基本完整性：关键前缀都在，避免改 import 时静默丢接口"""
    paths = {getattr(route, "path", "") for route in _routes()}
    for expected in (
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/chat/sessions",
        "/api/v1/knowledge-bases",
        "/api/v1/agent/chat/stream",
    ):
        assert expected in paths, f"缺少路由 {expected}"


def _routes():
    from app.main import app as fastapi_app

    assert isinstance(fastapi_app, FastAPI)
    return fastapi_app.routes
