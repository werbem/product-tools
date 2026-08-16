"""Minimal retry and timeout helpers for the MCP service layer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")

COLLECT_TIMEOUT_SECONDS = 120.0
ANALYSIS_TIMEOUT_SECONDS = 240.0
DEFAULT_RETRY_ATTEMPTS = 2

# Validation and schema errors are raised before workflow execution and should
# never be retried here.
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    TimeoutError,
    ConnectionError,
    RuntimeError,
)


async def run_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    retryable_exceptions: tuple[type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> T:
    """Run an async operation with a small retry policy.

    Only ``TimeoutError``, ``ConnectionError``, and ``RuntimeError`` are
    retried. Validation and schema errors should be handled before reaching
    this helper.
    """

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except retryable_exceptions as exc:
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(0.2 * (2 ** (attempt - 1)))

    assert last_error is not None
    raise last_error
