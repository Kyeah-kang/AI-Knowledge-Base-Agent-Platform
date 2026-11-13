"""
B4 回归测试 — 可观测性与安全（P1-9 / P1-10 / P1-12 / P1-13）

四个契约：
  1. 每个请求都有 request_id，并出现在响应头与日志里
  2. /health 真的探活依赖：MySQL/PG down → 503；Redis down → degraded 但仍 200
  3. refresh token 一次性使用（轮换），登出即吊销；Redis 不可用时降级放行
  4. 限流用双窗口加权（交界处不双倍放行），Redis 不可用时 fail-open；登录失败会锁定

不依赖数据库 / Redis / 网络。
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core import health as health_mod
from app.core import metrics, token_store
from app.core import rate_limiter as rl_mod
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import JsonFormatter, RequestIdFilter
from app.core.request_context import get_request_id
from app.core.security import create_refresh_token, verify_token
from app.services import auth_service as auth_mod
from app.services.auth_service import AuthService

# ─────────────────── P1-9：request_id 与日志 ───────────────────


@pytest.mark.asyncio
async def test_middleware_passes_through_upstream_request_id():
    from app.core.middleware import RequestContextMiddleware

    seen: dict = {}

    async def fake_app(scope, receive, send):
        seen["request_id"] = get_request_id()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestContextMiddleware(fake_app)
    sent: list = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(b"x-request-id", b"abc123")],
    }
    await middleware(scope, _receive, send)

    assert seen["request_id"] == "abc123"
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert (b"x-request-id", b"abc123") in start["headers"]


@pytest.mark.asyncio
async def test_middleware_generates_request_id_when_absent():
    from app.core.middleware import RequestContextMiddleware

    seen: dict = {}

    async def fake_app(scope, receive, send):
        seen["request_id"] = get_request_id()
        await send({"type": "http.response.start", "status": 500, "headers": []})

    middleware = RequestContextMiddleware(fake_app)
    sent: list = []

    async def send(message):
        sent.append(message)

    await middleware(
        {"type": "http", "method": "GET", "path": "/y", "headers": []}, _receive, send
    )

    assert len(seen["request_id"]) == 16
    assert get_request_id() == "-", "请求结束后必须复位，不能污染下一个请求"


async def _receive():
    return {"type": "http.request"}


def test_json_formatter_includes_request_id_and_extras():
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.http_status = 200
    RequestIdFilter().filter(record)  # 注入 request_id

    payload = JsonFormatter().format(record)

    assert '"request_id"' in payload
    assert '"http_status": 200' in payload
    assert "hello world" in payload


# ─────────────────── P1-10：真实探活 ───────────────────


def test_health_http_status_mapping():
    assert health_mod.http_status_for("healthy") == 200
    assert health_mod.http_status_for("degraded") == 200, "Redis 挂了不该摘实例"
    assert health_mod.http_status_for("unhealthy") == 503


@pytest.mark.asyncio
async def test_health_unhealthy_when_mysql_down(monkeypatch):
    async def ok():
        return None

    async def boom():
        raise RuntimeError("mysql down")

    monkeypatch.setattr(health_mod, "_probe_mysql", boom)
    monkeypatch.setattr(health_mod, "_probe_postgres", ok)
    monkeypatch.setattr(health_mod, "_probe_redis", ok)

    result = await health_mod.probe_dependencies()

    assert result["status"] == "unhealthy"
    assert result["dependencies"]["mysql"]["status"] == "down"
    assert health_mod.http_status_for(result["status"]) == 503


@pytest.mark.asyncio
async def test_health_degraded_when_only_redis_down(monkeypatch):
    async def ok():
        return None

    async def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(health_mod, "_probe_mysql", ok)
    monkeypatch.setattr(health_mod, "_probe_postgres", ok)
    monkeypatch.setattr(health_mod, "_probe_redis", boom)

    result = await health_mod.probe_dependencies()

    assert result["status"] == "degraded"
    assert health_mod.http_status_for(result["status"]) == 200


def test_sql_echo_is_not_tied_to_debug():
    """DEBUG=True 不该自动把 SQL 参数（含用户消息）打出来"""
    from app.database.session import mysql_engine, pg_engine

    assert settings.DB_ECHO_SQL is False
    assert mysql_engine.echo is False
    assert pg_engine.echo is False


# ─────────────────── P1-13：限流与登录锁定 ───────────────────


class FakeRedis:
    def __init__(self, current=0, previous=0):
        self.current = current
        self.previous = previous
        self.expired = []

    async def get_client(self):
        return self  # 非 None 即"可用"

    async def increment(self, key, amount=1):
        return self.current

    async def get(self, key):
        return str(self.previous)

    async def expire(self, key, seconds):
        self.expired.append((key, seconds))
        return True


@pytest.mark.asyncio
async def test_rate_limit_weights_previous_window(monkeypatch):
    limiter = rl_mod.RateLimiter()

    # 场景 A：窗口刚过去 1 秒（961 = 16*60 + 1）→ 上一窗口权重 ≈ 0.98
    # 估算 ≈ 5 + 10*0.98 = 14.8 > 10 → 拒绝
    monkeypatch.setattr(rl_mod.time, "time", lambda: 961.0)
    limiter._redis = FakeRedis(current=5, previous=10)
    allowed, _ = await limiter._check("k", limit=10, window=60)
    assert allowed is False, "上一窗口的计数必须被加权计入，否则交界处会双倍放行"

    # 场景 B：窗口过去 59 秒（1019）→ 权重 ≈ 0.017，估算 ≈ 5.17 ≤ 10 → 放行
    monkeypatch.setattr(rl_mod.time, "time", lambda: 1019.0)
    limiter._redis = FakeRedis(current=5, previous=10)
    allowed, _ = await limiter._check("k", limit=10, window=60)
    assert allowed is True


@pytest.mark.asyncio
async def test_rate_limit_fails_open_without_redis():
    limiter = rl_mod.RateLimiter()
    limiter._redis = SimpleNamespace(get_client=_none)

    allowed, remaining = await limiter._check("k", limit=5, window=60)

    assert allowed is True
    assert remaining == 5


async def _none():
    return None


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user

    async def get_by_username(self, username):
        return self.user

    async def get(self, user_id):
        return self.user


def _active_user():
    from app.core.security import hash_password

    return SimpleNamespace(
        id=1,
        username="alice",
        hashed_password=hash_password("correct-password"),
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        nickname=None,
        avatar=None,
        is_admin=False,
    )


@pytest.mark.asyncio
async def test_login_locked_after_too_many_failures(monkeypatch):
    async def fake_get(key):
        return str(settings.LOGIN_MAX_FAILURES)

    monkeypatch.setattr(auth_mod.redis_manager, "get", fake_get)

    service = AuthService(FakeUserRepo(_active_user()))
    with pytest.raises(AppException) as exc_info:
        await service.login(
            SimpleNamespace(username="alice", password="correct-password")
        )

    assert exc_info.value.http_status_code == 429
    assert "登录失败次数过多" in exc_info.value.message


@pytest.mark.asyncio
async def test_login_failure_is_counted(monkeypatch):
    calls = {"incr": 0, "expire": 0}

    async def fake_get(key):
        return "0"

    async def fake_incr(key):
        calls["incr"] += 1
        return 1  # 第一次失败

    async def fake_expire(key, seconds):
        calls["expire"] += 1
        return True

    monkeypatch.setattr(auth_mod.redis_manager, "get", fake_get)
    monkeypatch.setattr(auth_mod.redis_manager, "increment", fake_incr)
    monkeypatch.setattr(auth_mod.redis_manager, "expire", fake_expire)

    service = AuthService(FakeUserRepo(_active_user()))
    with pytest.raises(AppException) as exc_info:
        await service.login(SimpleNamespace(username="alice", password="wrong"))

    assert exc_info.value.http_status_code == 401
    assert calls["incr"] == 1
    assert calls["expire"] == 1, "第一次失败时要设置过期时间，否则计数永不过期"


# ─────────────────── P1-12：refresh 轮换与吊销 ───────────────────


def test_refresh_token_carries_jti():
    token = create_refresh_token({"sub": "1"})
    payload = verify_token(token, expected_type="refresh")

    assert payload is not None
    assert payload["jti"]
    assert payload["type"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_rejects_reused_token(monkeypatch):
    """旧 refresh 被消费过（或已吊销）后再次使用 → 401"""
    token = create_refresh_token({"sub": "1"})

    async def fake_consume(jti):
        return True, None  # store 可用，但查不到 → 已用过

    monkeypatch.setattr(auth_mod, "consume_refresh", fake_consume)

    service = AuthService(FakeUserRepo(_active_user()))
    with pytest.raises(AppException) as exc_info:
        await service.refresh_token(token)

    assert exc_info.value.http_status_code == 401
    assert "已失效" in exc_info.value.message


@pytest.mark.asyncio
async def test_refresh_fails_open_when_store_unavailable(monkeypatch):
    """Redis 不可用时不能把所有人挡在门外"""
    token = create_refresh_token({"sub": "1"})

    async def fake_consume(jti):
        return False, None  # Redis 不可用

    async def fake_register(jti, user_id, ttl_seconds):
        return False

    monkeypatch.setattr(auth_mod, "consume_refresh", fake_consume)
    monkeypatch.setattr(auth_mod, "register_refresh", fake_register)

    service = AuthService(FakeUserRepo(_active_user()))
    result = await service.refresh_token(token)

    assert result.access_token
    assert result.refresh_token != token, "每次刷新都应签发新的 refresh（轮换）"


@pytest.mark.asyncio
async def test_logout_revokes_refresh_jti(monkeypatch):
    token = create_refresh_token({"sub": "1"})
    payload = verify_token(token, expected_type="refresh")
    revoked: list[str] = []

    async def fake_revoke(jti):
        revoked.append(jti)
        return True

    monkeypatch.setattr(auth_mod, "revoke_refresh", fake_revoke)

    await AuthService(FakeUserRepo(_active_user())).logout(token)

    assert revoked == [payload["jti"]]


@pytest.mark.asyncio
async def test_consume_refresh_is_single_use():
    """真实实现语义：第二次消费同一个 jti 必须拿不到用户"""

    class OneShotRedis:
        def __init__(self):
            self.store = {"auth:refresh:abc": "7"}

        async def get_client(self):
            return self

        async def get(self, key):
            return self.store.get(key)

        async def delete(self, key):
            return self.store.pop(key, None) is not None

    original = token_store.redis_manager
    token_store.redis_manager = OneShotRedis()
    try:
        first = await token_store.consume_refresh("abc")
        second = await token_store.consume_refresh("abc")
    finally:
        token_store.redis_manager = original

    assert first == (True, 7)
    assert second == (True, None)
    metrics.reset()
