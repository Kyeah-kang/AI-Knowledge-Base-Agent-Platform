from app.core.config import settings


def test_cors_origins_default_allow_local_frontend():
    assert "http://localhost:3000" in settings.CORS_ORIGINS
    assert "http://127.0.0.1:3000" in settings.CORS_ORIGINS
