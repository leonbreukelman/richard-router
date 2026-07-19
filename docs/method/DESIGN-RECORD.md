# Design Record

No prior method history detected; method scaffold installed 2026-07-07 by repo-project-bootstrap.

## 2026-07-08 — Select `github-pr` lifecycle and add CI

Track F provider-registry/router-core uplift exposed that `PROJECT.md` still reflected the original local scaffold discovery: no origin, no CI, and `local-scaffold` mode. Live repository checks on 2026-07-08 showed the repo is already published at `leonbreukelman/richard-router`, default branch `main`, public visibility, and base `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`.

Decision:
- Switch this project card to `github-pr` for the Track F uplift and later scoped implementation phases.
- Add `.github/workflows/ci.yml` so `uv sync --all-groups`, `uv run ruff check .`, and `uv run pytest -v` produce API-readable GitHub check-runs on PRs and pushes to `main`.
- Keep deploy, credential, destructive repository actions, and branch-protection changes outside this automatic scope unless Leon explicitly authorizes them.

Rationale: Phase work requires PR/merge/API evidence under `METHOD.md` §8. Without a workflow, “CI green” would be fabricated or only locally asserted.

## 2026-07-19 — Publish contributor and SmactorIO intake guidance

A repository-readiness audit found that general development commands were present, but external humans and coding agents could not discover the SmactorIO issue-eligibility contract from the public repository. The repository also had no contributor guide, issue form, or pull-request template, and `PROJECT.md` still described required branch protection as a future decision after it was already active.

Decision:
- Keep `AGENTS.md` stable and short, but add a required pointer to `CONTRIBUTING.md` before issue or PR creation.
- Make `CONTRIBUTING.md` the canonical public contract for normal PRs, SmactorIO triage, lifecycle-label ownership, autonomous path limits, and pre-PR checks.
- Add a SmactorIO request form that applies only `smactorio`; maintainers retain the authorization boundary by adding `autonomy:ready` and `risk:low` after triage.
- Add a pull-request checklist and a human-controlled repository-guidance regression test so the entry points and exact CI contract cannot disappear silently.
- Record the live `uv / ruff / pytest` branch-protection requirement and describe autonomous scope allowlist-first.

Rationale: public issue templates apply configured labels regardless of the filer’s permissions. Auto-applying all three required labels would let an arbitrary public user self-authorize autonomous work. Separating triage request (`smactorio`) from maintainer authorization (`autonomy:ready` plus `risk:low`) makes the process discoverable without weakening the existing trust boundary.
