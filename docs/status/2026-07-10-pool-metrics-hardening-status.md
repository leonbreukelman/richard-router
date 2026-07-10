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

## PR / merge ledger
- Operator value summary: pool observability now keeps its rolling-window history under normal writes, returns internally consistent snapshots under concurrent traffic, rejects invalid health-threshold config before runtime, and has PR/API/local evidence tied back to the shipped merge.
- Implementation PR: https://github.com/leonbreukelman/richard-router/pull/16
- Branch lifecycle: `harden-pool-metrics` pushed, merged, and deleted from origin; local feature branch removed by merge flow.
- Implementation commits: `e2a28ff8e91509c13cecd1b33a2dc9e3389b679e`, `c7f36a8508ac01ef5cca19d21dbd5b01cc5c2834`.
- Merge commit on `main`: `7547b4717397a8411dfd96612aedb2c60378b0d7`.
- GitHub-read changed files: `docs/specs/2026-07-09-pool-visibility-metrics.md`, `docs/status/2026-07-10-pool-metrics-hardening-status.md`, `docs/verification/2026-07-09-pool-visibility-certification.md`, `docs/verification/2026-07-10-pool-metrics-hardening-review-summary.md`, `richard_router/config.py`, `richard_router/main.py`, `richard_router/metrics.py`, `tests/test_config.py`, `tests/test_metrics.py`, `tests/test_pool_endpoint.py`.
- PR-head CI: `uv / ruff / pytest` concluded `success` on `c7f36a8508ac01ef5cca19d21dbd5b01cc5c2834`; check-run URL: https://github.com/leonbreukelman/richard-router/actions/runs/29063517362/job/86270194788
- Push-to-main CI: `uv / ruff / pytest` concluded `success` on merge commit `7547b4717397a8411dfd96612aedb2c60378b0d7`; check-run URL: https://github.com/leonbreukelman/richard-router/actions/runs/29063546448/job/86270278768
- PR ledger comment: https://github.com/leonbreukelman/richard-router/pull/16#issuecomment-4931264802
- Post-merge local gate on `main`: `uv sync --all-groups && uv run ruff check . && uv run pytest -v && git diff --check` passed, `80 passed in 1.34s`.

## Pending
- None for this hardening PR.
