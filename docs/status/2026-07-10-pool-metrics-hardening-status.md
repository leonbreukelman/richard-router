# Pool metrics hardening status

Date: 2026-07-10
Branch: `harden-pool-metrics`
Base: `origin/main` at `d0fed77` (`Merge pull request #14 from leonbreukelman/context-length-per-model`)

## Scope
Address the follow-up review items from the current-state inspection after PR #13/#14:
- stop rebuilding the rolling-window deque on every metrics write;
- make metrics snapshots internally consistent under concurrent writes;
- fix `richard-router status` blank-line grouping between virtual models;
- replace unbacked performance/benchmark claims in the pool-visibility spec;
- update stale certification/test-count notes.

## Current implementation state
- `richard_router/metrics.py` now initializes each upstream deque with the configured `metrics_window` and reuses it on steady-state writes.
- `MetricsCollector.snapshot()` now derives response entries while holding the collector lock, avoiding torn counters or mutation-during-iteration risks.
- Metrics timestamps now store wall-clock epoch seconds directly instead of converting monotonic timestamps back to wall time.
- `validate_config()` now reports invalid observability metric thresholds/windows, including `down_threshold < degraded_threshold`, instead of silently masking bad config.
- `richard_router/main.py` now prints blank separators before later VM groups, not after the second and later groups.
- `tests/test_metrics.py` adds unchanged-window and concurrent snapshot/write regression coverage.
- `tests/test_pool_endpoint.py` adds CLI table grouping coverage.
- `docs/specs/2026-07-09-pool-visibility-metrics.md` now describes design properties without unsupported benchmark guarantees and matches the actual `/v1/pool` JSON shape.
- `docs/verification/2026-07-09-pool-visibility-certification.md` now reflects the follow-up hardening and current test counts.

## Verification
- Targeted gate: `uv run ruff check . && uv run pytest -q tests/test_config.py tests/test_metrics.py tests/test_pool_endpoint.py` — passed, Ruff clean and `42 passed in 0.15s`.
- Full local gate: `uv run pytest -v` — passed, `80 passed in 0.19s`.
- Independent review: Claude Code Opus returned `ACCEPT_WITH_NOTES` with no blockers and no must-fix-before-merge items. Public-safe summary: `docs/verification/2026-07-10-pool-metrics-hardening-review-summary.md`.

## Pending
- Push branch, open PR, verify CI/API evidence, merge, and post final ledger.
