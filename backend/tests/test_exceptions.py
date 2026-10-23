from app.core.exceptions import AppException


def test_app_exception_keeps_detail():
    exc = AppException(code=400, message="business error", detail="db timeout")
    assert exc.detail == "db timeout"
