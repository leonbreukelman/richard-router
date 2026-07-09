# Track F router-core uplift status

Date: 2026-07-08
Status: Phase 3 landed on `main`; Phase 4 decision log is next
Mode: `github-pr`
Base: `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`

## What went wrong

The method card was stale. `docs/method/PROJECT.md` still said `local-scaffold`, no git origin, and no CI, while the live repo is already `leonbreukelman/richard-router` on GitHub with `main` at the Track F base. That contradiction blocked honest Phase 1 work because `github-pr` evidence requires an API-readable CI check-run, and the repo had no workflow.

## Phase 0 result

- GitHub Actions CI exists and produced API-readable success on PR #4 and the post-merge push to `main`.
- `PROJECT.md` now selects `github-pr` and records the real GitHub remote.
- `DESIGN-RECORD.md` records the mode/CI rationale.
- The provider-registry ADR exists for Phase 1.

## Phase 1 result

- Optional top-level `providers:` registry added.
- Legacy inline `virtual_models.*.upstreams` remains valid.
- Provider-reference and inline forms normalize to the same internal frozen dataclass shape.
- `validate_config` and `richard-router validate --config <path>` added.
- `config/router.example.yaml` migrated to provider-reference form with a commented inline example.
- Local gate, Opus review, PR-head CI, post-merge CI, and PR ledger passed.

## Phase 2 result

- Router now pools one `httpx.AsyncClient` per upstream cache key instead of creating and closing a client per attempt.
- Default clients now use split `httpx.Timeout(connect/read/write/pool)` values from normalized upstream config.
- FastAPI app creation now registers a lifespan shutdown hook that closes pooled clients.
- Existing failover happy-path behavior remains covered by unchanged failover tests.
- Local gate, Opus review, PR-head CI, post-merge CI, and PR ledger passed.

## Phase 3 result

- Circuit breaker config added under `failover.circuit_breaker` with the Track F defaults: enabled, threshold 5, cooldown 30s, one half-open probe.
- Router now tracks breaker state per upstream cache key and skips open circuits before attempting network calls.
- Retryable HTTP status and transport/timeout exception classification reuses the existing `classify_status` / `classify_exception` taxonomy.
- Caller/configuration failures such as normal 4xx responses do not open the breaker and reset consecutive failure state.
- Streaming and non-streaming paths both respect breaker state and reset it on successful upstream responses.
- Local gate, Opus review, PR-head CI, post-merge CI, branch cleanup, and PR ledger passed.

## Boundary

No deploy, credential change, branch protection change, or destructive repository action is in scope. Phase 4 decision log remains untouched.
