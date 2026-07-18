# Issue #24 non-JSON failover regression proof

Date: 2026-07-18
Base: `92e7289fd96959de5085b42f419a621a9c7b15fa`
Scope: tests only; production behavior was already correct on current `main`.

## Behavior locked

- Retryable HTML/plain-text upstream errors continue to the fallback.
- Malformed `application/json` errors continue to the fallback.
- Non-object JSON errors continue to the fallback.
- Streaming non-JSON errors continue to the fallback and preserve model rewriting.
- When every upstream returns a non-JSON retryable error, the response retains ordered `http_error` attempt evidence for both upstreams.

## Local gates

- `uv run ruff check .` — passed.
- `uv run pytest -v` — 147 tests passed.

## Independent certification

Reviewer: Claude Code Opus
Actual model: `claude-opus-4-8`
Verdict: `ACCEPT`

The reviewer confirmed the tests drive the real `_extract_error_message` branches, would fail if malformed/non-object JSON escaped the suppression boundary, prove both upstreams are invoked in order, exercise the streaming error path, and verify all-failed attempt evidence. No correction was required.

## Operator value

Issue #24 needed no production patch because current `main` already contains the safe error extractor. These tests turn that verified behavior into a durable CI regression instead of relying on a one-time service canary.
