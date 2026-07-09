# Track F router-core uplift status

Date: 2026-07-08
Status: Phase 2 implementation verified locally on branch `phase2-client-pooling`; PR/API landing pending
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
- Local gate and Opus review passed before PR.

## Phase 2 result

- Router now pools one `httpx.AsyncClient` per upstream id instead of creating and closing a client per attempt.
- Default clients now use split `httpx.Timeout(connect/read/write/pool)` values from normalized upstream config.
- FastAPI app creation now registers a lifespan shutdown hook that closes pooled clients.
- Existing failover happy-path behavior remains covered by unchanged failover tests.

## Boundary

No deploy, credential change, branch protection change, or destructive repository action is in scope. Phases 3-4 remain untouched until Phase 2 is CI-green and merged.
