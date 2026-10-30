"""Unit tests for the timed and retry decorators (no database needed)."""

import logging
import time

import pytest

from app.decorators import retry, timed


def test_timed_returns_the_result_and_keeps_metadata():
    @timed(threshold_ms=1000)
    def add(a, b):
        """Add two numbers."""
        return a + b

    assert add(2, 3) == 5
    assert add.__name__ == "add"
    assert add.__doc__ == "Add two numbers."
    assert add.last_ms >= 0


def test_timed_logs_a_warning_when_the_call_is_slow(caplog):
    @timed(threshold_ms=0)
    def work():
        time.sleep(0.002)

    with caplog.at_level(logging.WARNING, logger="ticketdesk"):
        work()
    assert "work took" in caplog.text


def test_timed_stays_quiet_when_the_call_is_fast(caplog):
    @timed(threshold_ms=10_000)
    def work():
        return None

    with caplog.at_level(logging.WARNING, logger="ticketdesk"):
        work()
    assert caplog.text == ""


def test_timed_records_duration_even_when_the_function_raises():
    @timed(threshold_ms=10_000)
    def boom():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        boom()
    assert boom.last_ms >= 0


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @retry(times=3)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("db not ready")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_reraises_the_last_error_when_attempts_run_out():
    calls = {"n": 0}

    @retry(times=3, exceptions=(ValueError,))
    def always_fails():
        calls["n"] += 1
        raise ValueError("still broken")

    with pytest.raises(ValueError, match="still broken"):
        always_fails()
    assert calls["n"] == 3


def test_retry_does_not_catch_unlisted_exceptions():
    calls = {"n": 0}

    @retry(times=5, exceptions=(ValueError,))
    def wrong_kind():
        calls["n"] += 1
        raise KeyError("different problem")

    with pytest.raises(KeyError):
        wrong_kind()
    assert calls["n"] == 1


def test_retry_sleeps_between_attempts_but_not_after_the_last(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.decorators.time.sleep", sleeps.append)

    @retry(times=3, delay=0.5, exceptions=(ValueError,))
    def always_fails():
        raise ValueError

    with pytest.raises(ValueError):
        always_fails()
    assert sleeps == [0.5, 0.5]


def test_retry_rejects_a_non_positive_attempt_count():
    with pytest.raises(ValueError):
        retry(times=0)
