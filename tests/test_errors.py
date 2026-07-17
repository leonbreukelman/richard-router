from __future__ import annotations

import httpx

from richard_router.errors import RETRYABLE_STATUS, classify_exception, classify_status


def test_retryable_statuses():
    for status_code in [408, 409, 429, 500, 502, 503, 504, 599]:
        assert classify_status(status_code) == "retryable"


def test_fatal_statuses():
    for status_code in [400, 401, 403, 404, 422]:
        assert classify_status(status_code) == "fatal"


def test_explicit_empty_retry_on_status_retries_nothing():
    empty: set[int] = set()
    for status_code in [429, 500, 502, 503, 504, 599]:
        assert classify_status(status_code, empty) == "fatal"


def test_explicit_429_only_does_not_retry_5xx():
    policy = {429}
    assert classify_status(429, policy) == "retryable"
    for status_code in [500, 502, 503, 504, 599]:
        assert classify_status(status_code, policy) == "fatal"
    assert classify_status(400, policy) == "fatal"


def test_omitted_policy_matches_default_set_and_blanket_5xx():
    assert classify_status(429) == "retryable"
    assert classify_status(503) == "retryable"
    assert classify_status(599) == "retryable"
    for code in RETRYABLE_STATUS:
        assert classify_status(code) == "retryable"


def test_retryable_exceptions():
    assert classify_exception(httpx.ConnectError("down")) == "retryable"
    assert classify_exception(httpx.ReadTimeout("slow")) == "retryable"


def test_unknown_exception_is_fatal():
    assert classify_exception(ValueError("bad request shape")) == "fatal"
