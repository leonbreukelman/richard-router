# Design Record

No prior method history detected; method scaffold installed 2026-07-07 by repo-project-bootstrap.

## 2026-07-08 — Select `github-pr` lifecycle and add CI

Track F provider-registry/router-core uplift exposed that `PROJECT.md` still reflected the original local scaffold discovery: no origin, no CI, and `local-scaffold` mode. Live repository checks on 2026-07-08 showed the repo is already published at `leonbreukelman/richard-router`, default branch `main`, public visibility, and base `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`.

Decision:
- Switch this project card to `github-pr` for the Track F uplift and later scoped implementation phases.
- Add `.github/workflows/ci.yml` so `uv sync --all-groups`, `uv run ruff check .`, and `uv run pytest -v` produce API-readable GitHub check-runs on PRs and pushes to `main`.
- Keep deploy, credential, destructive repository actions, and branch-protection changes outside this automatic scope unless Leon explicitly authorizes them.

Rationale: Phase work requires PR/merge/API evidence under `METHOD.md` §8. Without a workflow, “CI green” would be fabricated or only locally asserted.
