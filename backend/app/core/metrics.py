"""
轻量进程内指标 — 让"失败"可被计数，而不是只留在某一行日志里。

为什么需要它？
  P0-1 的核心不是"别降级"，而是"降级必须可观测"。
  没有计数的 warning 日志等于没有告警：翻日志才知道坏过。

设计取舍：
  - 不引入 prometheus_client（P1 再上），只用进程内 dict，零依赖、零配置。
  - 计数用 (name, labels) 作键，与 Prometheus 的 label 语义一致，将来迁移成本低。
  - 耗时只保留 count / sum / max，避免无上限的样本列表把内存吃光。
  - asyncio 单线程下 dict 操作本身不被打断，但仍加锁，
    因为 FastAPI 的同步线程（如文件解析）也可能写入。

用法：
    from app.core import metrics

    metrics.incr("document_upload_total", status="failed")
    metrics.observe_ms("rag_retrieval", 42.7, status="ok")
    metrics.snapshot()      # → {"counters": {...}, "timers": {...}}
"""

import threading
from typing import Any

_lock = threading.Lock()

# {(name, ((label_key, label_value), ...)): value}
_counters: dict[tuple, int] = {}

# {(name, labels): {"count": int, "sum_ms": float, "max_ms": float}}
_timers: dict[tuple, dict[str, float]] = {}


def _key(name: str, labels: dict[str, Any]) -> tuple:
    """把 (名称, 标签) 归一化成可哈希的键"""
    if not labels:
        return (name, ())
    return (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))


def _render(key: tuple) -> str:
    """渲染成人读的形式，如 rag_retrieval_total{status=error}"""
    name, labels = key
    if not labels:
        return name
    return f"{name}{{{','.join(f'{k}={v}' for k, v in labels)}}}"


def incr(name: str, value: int = 1, **labels: Any) -> None:
    """
    计数器 +value（默认 +1）。

    用法：metrics.incr("rag_retrieval_total", status="error")
    """
    key = _key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0) + value


def observe_ms(name: str, elapsed_ms: float, **labels: Any) -> None:
    """
    记录一次耗时（毫秒）。

    用法：metrics.observe_ms("rag_retrieval_latency", 42.0)
    """
    key = _key(name, labels)
    with _lock:
        slot = _timers.setdefault(key, {"count": 0.0, "sum_ms": 0.0, "max_ms": 0.0})
        slot["count"] += 1
        slot["sum_ms"] += elapsed_ms
        slot["max_ms"] = max(slot["max_ms"], elapsed_ms)


def snapshot() -> dict[str, dict[str, float]]:
    """
    导出当前指标快照。

    返回：
        {
          "counters": {"document_upload_total{status=failed}": 2, ...},
          "timers":   {"rag_retrieval{status=ok}": {"count": 3, "avg_ms": 41.2, "max_ms": 88.0}, ...},
        }
    """
    with _lock:
        counters: dict[str, int] = {_render(k): v for k, v in _counters.items()}
        timers: dict[str, Any] = {}
        for key, slot in _timers.items():
            count = slot["count"] or 1
            timers[_render(key)] = {
                "count": int(slot["count"]),
                "avg_ms": round(slot["sum_ms"] / count, 2),
                "max_ms": round(slot["max_ms"], 2),
            }
    return {"counters": counters, "timers": timers}


def reset() -> None:
    """清空指标（仅用于测试）"""
    with _lock:
        _counters.clear()
        _timers.clear()
