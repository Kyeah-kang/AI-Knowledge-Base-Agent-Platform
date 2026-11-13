"""
集成测试（P2-7）—— 打真实 MySQL/PG，没有数据库就整组跳过。

和单元测试的分工：
  单元测试证明"逻辑分支对"，这里证明"装起来还能跑"——依赖注入、事务提交、
  真实 SQL、序列化、鉴权链路。之前的 P0/N 系列问题绝大多数只能在这一层暴露。

运行：
    pytest -m integration                     # 只跑集成
    pytest -m "not integration"               # 只跑单元（CI 无数据库时）
"""

import time

import pytest

pytestmark = pytest.mark.integration


def _username() -> str:
    return f"itest{int(time.time() * 1000) % 100000000}"


@pytest.mark.asyncio
async def test_register_login_me_flow(real_client):
    """注册 → 登录 → 取当前用户，三条接口的字段契约必须对得上"""
    username = _username()
    async with real_client as client:
        reg = await client.post(
            "/api/v1/auth/register", json={"username": username, "password": "Test123456"}
        )
        assert reg.status_code == 200, reg.text
        token = reg.json()["data"]["access_token"]
        assert reg.json()["data"]["refresh_token"]

        headers = {"Authorization": f"Bearer {token}"}
        me = await client.get("/api/v1/users/me", headers=headers)
        assert me.status_code == 200, me.text
        assert me.json()["data"]["username"] == username

        login = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "Test123456"}
        )
        assert login.status_code == 200
        assert login.json()["data"]["user"]["username"] == username


@pytest.mark.asyncio
async def test_knowledge_base_crud_and_ownership(real_client):
    """知识库 CRUD + 越权保护（另一个用户看不到、改不了）"""
    async with real_client as client:
        owner_tokens = await _register(client)
        other_tokens = await _register(client)
        owner = {"Authorization": f"Bearer {owner_tokens}"}
        other = {"Authorization": f"Bearer {other_tokens}"}

        created = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": "集成测试库", "description": "pytest"},
            headers=owner,
        )
        assert created.status_code == 200, created.text
        kb_id = created.json()["data"]["id"]

        listed = await client.get("/api/v1/knowledge-bases", headers=owner)
        assert any(item["id"] == kb_id for item in listed.json()["data"]["items"])

        # 别人的库：读和写都必须被拒
        stolen = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=other)
        assert stolen.status_code in (403, 404), stolen.text

        renamed = await client.put(
            f"/api/v1/knowledge-bases/{kb_id}", json={"name": "改名"}, headers=other
        )
        assert renamed.status_code in (403, 404), renamed.text

        deleted = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=owner)
        assert deleted.status_code == 200, deleted.text

        gone = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=owner)
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_chat_session_lifecycle(real_client):
    """会话创建 → 列表 → 详情；列表里的 message_total 必须真实（P1-4 的回归）"""
    async with real_client as client:
        token = await _register(client)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            "/api/v1/chat/sessions", json={"title": "集成会话"}, headers=headers
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["data"]["id"]

        listed = await client.get("/api/v1/chat/sessions", headers=headers)
        row = next(
            item
            for item in listed.json()["data"]["items"]
            if item["id"] == session_id
        )
        # 列表里的字段名是 message_count（批量 count 的结果，P1-4）
        assert row["message_count"] == 0

        detail = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["messages"] == []

        await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(real_client):
    """登出后 refresh 立刻失效（P1-12，需要 Redis 才能在真实链路验证）"""
    async with real_client as client:
        reg = await client.post(
            "/api/v1/auth/register",
            json={"username": _username(), "password": "Test123456"},
        )
        tokens = reg.json()["data"]

        out = await client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        )
        assert out.status_code == 200, out.text

        again = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert again.status_code == 401, "登出后旧 refresh 必须失效"


async def _register(client) -> str:
    """注册一个临时用户并返回 access_token"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": _username(), "password": "Test123456"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]
