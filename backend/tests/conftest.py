"""
pytest 共享夹具（P2-7）。

提供两层测试：

1. **接口级（无外部依赖）** —— `client`
   用 `httpx.ASGITransport` 直接打 FastAPI app，不启服务器、不连数据库。
   通过 `app.dependency_overrides` 换掉 `get_db` / `get_vector_db` / `get_current_user`，
   于是中间件、路由、异常处理器、响应信封都能被真实执行到。

2. **集成级（需要真实 MySQL/PG）** —— `real_client`
   标 `@pytest.mark.integration`；数据库不可达时整组跳过，CI 上没有数据库也不会红。

为什么不给单测造一个 SQLite 内存库：
  模型用了 MySQL 方言特性、PG 侧还有 `vector` 类型，换成 SQLite 得到的是"另一个系统"，
  测出来的是假放心。所以：纯逻辑用假对象，真实链路走 integration 标记。
"""

from __future__ import annotations

import os

# 必须在导入 app.* 之前设置：Settings 在 import 时就读环境变量。
# 集成测试会在几十秒内发出上百次请求，开着 IP 限流（60/min）必然自己把自己 429 掉。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.core.deps import get_db, get_vector_db
from app.main import app as fastapi_app
from app.routers.v1 import get_current_user

# ─────────────────── 假对象 ───────────────────


class FakeResult:
    """最小的 Result 替身：仓储层常用的几个取数方法都能用"""

    def __init__(self, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else self._scalar

    def __iter__(self):
        return iter(self._rows)

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class FakeSession:
    """最小可用会话：commit/rollback/flush 是空操作，execute 返回可配置结果"""

    def __init__(self, scalar=None, rows=None) -> None:
        self.commits = 0
        self._scalar = scalar
        self._rows = rows

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def flush(self):
        return None

    async def execute(self, *args, **kwargs):
        return FakeResult(self._scalar, self._rows)

    async def close(self):
        return None


def _fake_user(user_id: int = 1, is_admin: bool = False) -> SimpleNamespace:
    from datetime import datetime

    return SimpleNamespace(
        id=user_id,
        username="tester",
        email="tester@example.com",
        nickname="测试用户",
        avatar=None,
        is_active=True,
        is_admin=is_admin,
        hashed_password="x",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


# ─────────────────── 接口级夹具 ───────────────────


@pytest.fixture
def anon_client():
    """未登录客户端：真实走到鉴权与异常处理链路"""
    transport = httpx.ASGITransport(app=fastapi_app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")  # noqa: RUF006


@pytest.fixture
def auth_client():
    """
    已登录客户端：把 `get_current_user` 换成假用户，其余链路（限流、路由、序列化）保持真实。

    注意这里是**替身当前用户**，不是绕过鉴权逻辑 —— 鉴权本身的用例在 `anon_client` 里覆盖。
    """
    fake_user = _fake_user()
    fastapi_app.dependency_overrides[get_current_user] = lambda: fake_user
    # execute 的默认返回就是"这个用户"，这样接口里再查一次用户也能查到
    fastapi_app.dependency_overrides[get_db] = lambda: FakeSession(scalar=fake_user)
    fastapi_app.dependency_overrides[get_vector_db] = lambda: FakeSession()
    transport = httpx.ASGITransport(app=fastapi_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client
    finally:
        fastapi_app.dependency_overrides.clear()


# ─────────────────── 集成级夹具 ───────────────────


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """只探端口，不建连接池。

    为什么不用 `engine.connect()` 探测：异步引擎的连接是**绑定事件循环**的，
    在 `asyncio.run()` 里探一次，后面的测试再用它就会踩
    "'NoneType' object has no attribute 'send'"（proactor 循环已关闭）。
    探端口是纯阻塞操作，不碰事件循环，安全。
    """
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    from app.core.config import settings

    return _port_open(settings.MYSQL_HOST, settings.MYSQL_PORT) and _port_open(
        settings.POSTGRES_HOST, settings.POSTGRES_PORT
    )


@pytest_asyncio.fixture
async def real_client(db_available):
    """
    真实数据库客户端；数据库不可达时跳过。

    每个测试前后都 dispose 引擎：pytest-asyncio 每个测试一个事件循环，
    池里残留的上一个循环的连接在新循环里用会炸。
    """
    if not db_available:
        pytest.skip("MySQL/PG 端口不可达，跳过集成测试")

    from app.database.session import mysql_engine, pg_engine

    await mysql_engine.dispose()
    await pg_engine.dispose()

    transport = httpx.ASGITransport(app=fastapi_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30)
    try:
        yield client
    finally:
        fastapi_app.dependency_overrides.clear()
        await mysql_engine.dispose()
        await pg_engine.dispose()
