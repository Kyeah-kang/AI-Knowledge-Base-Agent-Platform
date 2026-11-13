"""
UTC 时间处理
"""

from datetime import UTC, datetime
from typing import Optional


def utc_now() -> datetime:
    """
    返回当前 UTC 时间（naive，不带时区信息）。

    流程：
        datetime.now(timezone.utc)   → 获取带时区的 UTC 时间
        .replace(tzinfo=None)        → 去掉时区信息，变成 naive 时间
        存到 MySQL                           → DATETIME 列

    从 MySQL 读回来时：
        得到 naive datetime            → 我们认为它是 UTC
        to_timezone(dt, "Asia/Shanghai") → 转成上海时间展示
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_timezone(dt: datetime, tz: Optional[str] = "Asia/Shanghai") -> datetime:
    """
    将 naive UTC 时间转换为指定时区。
    后续在 response schema 中使用。
    """
    from dateutil import tz as tzutil
    utc_tz = tzutil.gettz("UTC")
    target_tz = tzutil.gettz(tz) if tz else tzutil.gettz("Asia/Shanghai")
    aware_dt = dt.replace(tzinfo=utc_tz)
    return aware_dt.astimezone(target_tz)
