# Track F router-core uplift verification

Date: 2026-07-08
Mode: `github-pr`
Branch: `phase0-governance-ci`
Base: `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`

## Grounding checks

- `git rev-parse HEAD`: `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`
- `git rev-parse origin/main`: `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`
- `gh repo view`: `leonbreukelman/richard-router`, public, default branch `main`
- `.github/workflows/`: absent before Phase 0
- `docs/method/PROJECT.md` before Phase 0: `local-scaffold`, origin `none`, CI absent

## Base gate before Phase 0 edits

Command from `/home/leonb/projects/richard-router`:

```bash
uv run ruff check . && uv run pytest -v
```

Observed result:

- Ruff: `All checks passed!`
- Pytest: `17 passed, 1 warning in 0.15s`

## GitHub Action refs checked before authoring

- `actions/checkout@v5`: tag resolved through GitHub API
- `actions/setup-python@v5`: tag resolved through GitHub API
- `astral-sh/setup-uv@v5`: tag resolved through GitHub API

Python version note: the workflow sets up Python `3.11`, matching the project's declared `requires-python = ">=3.11"` and the local test interpreter family used by the gate.

## Phase 0 local gates

Command from `/home/leonb/projects/richard-router` after Phase 0 edits and review patches:

```bash
uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest: `17 passed, 1 warning in 0.15s`

Staged diff hygiene:

```bash
git diff --cached --check
```

Observed result: no output / exit 0.

## Phase 0 PR/API ledger

Pending push/PR/CI/merge. The workflow runs on pull requests targeting `main`; API-readable CI evidence is expected from the PR check-run and the post-merge push-to-`main` check-run, not from a feature-branch-only push.

## Independent review

Opus review output: `docs/verification/2026-07-08-phase0-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: narrowed ADR language so Phase 3/4 items are recorded as later-phase handoff decisions rather than Phase 0 implementation, clarified PR-run CI evidence in this verification file, and added `workflow_dispatch` plus concurrency cancellation to CI.
