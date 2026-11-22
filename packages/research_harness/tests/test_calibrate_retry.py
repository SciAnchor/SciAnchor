from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_harness.cli_panorama import (
    execute_with_calibrate_retry,
    is_transient_calibrate_error,
)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("temporarily unavailable", True),
        ("Request timed out.", True),
        ("HTTP 502 Bad Gateway", True),
        ("503 service unavailable", True),
        ("connection reset by peer", True),
        ("schema validation failed", False),
        ("", False),
        (None, False),
    ],
)
def test_transient_markers(message: str | None, expected: bool) -> None:
    assert is_transient_calibrate_error(message) is expected


def test_retry_succeeds_after_timeouts() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def execute(_name: str, **_kwargs: object) -> SimpleNamespace:
        calls["n"] += 1
        if calls["n"] < 3:
            return SimpleNamespace(success=False, error="Request timed out.")
        return SimpleNamespace(
            success=True, error=None, prompt_tokens=1, completion_tokens=2, cost_usd=0.0
        )

    result = execute_with_calibrate_retry(
        execute, sleep=sleeps.append, attempts=5, sleep_s=1.5, topic_id=1
    )
    assert result.success is True
    assert calls["n"] == 3
    assert sleeps == [1.5, 1.5]


def test_non_transient_fails_immediately() -> None:
    calls = {"n": 0}

    def execute(_name: str, **_kwargs: object) -> SimpleNamespace:
        calls["n"] += 1
        return SimpleNamespace(success=False, error="invalid fixture")

    with pytest.raises(RuntimeError, match="invalid fixture"):
        execute_with_calibrate_retry(execute, sleep=lambda _s: None, attempts=5)
    assert calls["n"] == 1


def test_exhausts_attempts_on_persistent_502() -> None:
    calls = {"n": 0}

    def execute(_name: str, **_kwargs: object) -> SimpleNamespace:
        calls["n"] += 1
        return SimpleNamespace(success=False, error="502 bad gateway")

    with pytest.raises(RuntimeError, match="502"):
        execute_with_calibrate_retry(execute, sleep=lambda _s: None, attempts=4)
    assert calls["n"] == 4
