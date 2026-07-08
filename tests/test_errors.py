from __future__ import annotations

import httpx

from richard_router.errors import classify_exception, classify_status


def test_retryable_statuses():
    for status_code in [408, 409, 429, 500, 502, 503, 504, 599]:
        assert classify_status(status_code) == "retryable"


def test_fatal_statuses():
    for status_code in [400, 401, 403, 404, 422]:
        assert classify_status(status_code) == "fatal"


def test_retryable_exceptions():
    assert classify_exception(httpx.ConnectError("down")) == "retryable"
    assert classify_exception(httpx.ReadTimeout("slow")) == "retryable"


def test_unknown_exception_is_fatal():
    assert classify_exception(ValueError("bad request shape")) == "fatal"
