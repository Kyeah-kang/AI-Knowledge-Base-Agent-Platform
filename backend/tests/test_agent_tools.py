import math

import pytest

from app.agent.tools import _safe_eval


def test_safe_eval_arithmetic():
    assert _safe_eval("2 + 3 * 4") == 14.0


def test_safe_eval_allowed_math_functions():
    assert _safe_eval("sqrt(16)") == 4.0
    assert _safe_eval("pi") == pytest.approx(math.pi)
    assert _safe_eval("max(1, 5, 3)") == 5.0


@pytest.mark.parametrize(
    "expression",
    [
        "().__class__",
        "[].__class__",
        "open('/etc/passwd')",
        "__import__('os').system('id')",
        "eval('1+1')",
        "{'a': 1}",
        "(1, 2)",
    ],
)
def test_safe_eval_rejects_dangerous_expressions(expression):
    with pytest.raises(ValueError):
        _safe_eval(expression)
