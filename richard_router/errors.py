from __future__ import annotations

from typing import Literal

import httpx

Classification = Literal["retryable", "fatal"]

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def classify_status(
    status_code: int, retryable_status: set[int] | frozenset[int] | None = None
) -> Classification:
    """Classify HTTP status for failover retry.

    * ``retryable_status is None`` (omitted policy): documented defaults —
      ``RETRYABLE_STATUS`` plus any remaining 5xx as retryable.
    * explicit set (including empty): that set is **authoritative** — no
      unconditional 5xx promotion. Empty set ⇒ no status is retryable.
    """
    if retryable_status is None:
        if status_code in RETRYABLE_STATUS:
            return "retryable"
        # Default path only: blanket 5xx (e.g. 599) stays retryable.
        if 500 <= status_code <= 599:
            return "retryable"
        return "fatal"

    # Explicit policy — including empty set — controls classification alone.
    if status_code in retryable_status:
        return "retryable"
    return "fatal"


def classify_exception(exc: Exception) -> Classification:
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return "retryable"
    return "fatal"
