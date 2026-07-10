# Pool metrics hardening independent review

Date: 2026-07-10
Reviewer: Claude Code Opus
Branch reviewed: `harden-pool-metrics`

## Verdict

`ACCEPT_WITH_NOTES`

No blockers. No must-fix-before-merge items.

## Valid criticism patched before this review

- Added observability config validation for invalid metric windows/thresholds.
- Added validation for `down_threshold < degraded_threshold`.
- Added regression coverage in `tests/test_config.py`.

## Remaining notes accepted as non-blocking

- `MetricsCollector.snapshot()` now does O(N) entry formatting while holding the collector lock. This is correct for consistency and documented; a future optimization could copy raw primitives under lock and format outside it.
- `UpstreamMetrics.record(window_size=...)` remains as a direct-test/future-resize hook, while production collectors set deque `maxlen` at entry creation.
- Wall-clock timestamps can move backward if system time changes, but they are display-only and no health classification depends on them.

## Certification

The review found no correctness blocker and no required patch before merge. Combined with the local gate (`ruff` clean, targeted config/metrics/pool tests passing, and full pytest passing), this hardening branch is ready for PR lifecycle.
