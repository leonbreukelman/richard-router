from __future__ import annotations

from typing import Literal

import httpx

Classification = Literal["retryable", "fatal"]

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def classify_status(
    status_code: int, retryable_status: set[int] | frozenset[int] | None = None
) -> Classification:
    retryable = retryable_status or RETRYABLE_STATUS
    if status_code in retryable:
        return "retryable"
    if 500 <= status_code <= 599:
        return "retryable"
    return "fatal"


def classify_exception(exc: Exception) -> Classification:
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return "retryable"
    return "fatal"
