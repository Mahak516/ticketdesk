"""Reusable decorators: call timing and retry with a fixed delay."""

import functools
import logging
import time
from typing import Callable, ParamSpec, TypeVar

from .config import get_settings

logger = logging.getLogger("ticketdesk")

P = ParamSpec("P")
R = TypeVar("R")


def timed(threshold_ms: float | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log how long a call took; log at WARNING when it exceeds the threshold.

    The threshold defaults to the SLOW_CALL_MS setting. The duration of the most
    recent call is available as ``wrapper.last_ms``, which makes slow paths easy
    to spot while debugging.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                wrapper.last_ms = elapsed_ms  # type: ignore[attr-defined]
                limit = threshold_ms if threshold_ms is not None else get_settings().slow_call_ms
                level = logging.WARNING if elapsed_ms > limit else logging.DEBUG
                logger.log(level, "%s took %.1f ms", func.__name__, elapsed_ms)

        wrapper.last_ms = 0.0  # type: ignore[attr-defined]
        return wrapper

    return decorator


def retry(
    times: int = 3,
    delay: float = 0.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry a call up to ``times`` attempts when one of ``exceptions`` is raised.

    The last exception is re-raised once the attempts are used up. Exceptions that
    are not listed are never retried.
    """
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == times:
                        raise
                    logger.warning(
                        "%s failed (attempt %d/%d): %s", func.__name__, attempt, times, exc
                    )
                    if delay:
                        time.sleep(delay)
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
