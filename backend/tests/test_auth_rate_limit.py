import asyncio

import pytest
from fastapi import HTTPException

from app.core.rate_limiter import RateLimiter
from app.routers.v1 import get_current_user


class FakeUser:
    id = 7
    is_active = True


class FakeUserRepo:
    async def get(self, user_id):
        return FakeUser()


def test_get_current_user_rejects_when_user_rate_exceeded(monkeypatch):
    async def deny(*args, **kwargs):
        return False, 0

    async def run():
        monkeypatch.setattr(
            "app.routers.v1.verify_token",
            lambda token, expected_type: {"sub": "7"},
        )
        monkeypatch.setattr("app.routers.v1.UserRepository", lambda db: FakeUserRepo())
        monkeypatch.setattr(RateLimiter, "check_user_rate", deny)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token="token", db=None)
        assert exc_info.value.status_code == 429

    asyncio.run(run())
