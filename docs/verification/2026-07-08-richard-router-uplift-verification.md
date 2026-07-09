# Track F router-core uplift verification

Date: 2026-07-08
Mode: `github-pr`
Current branch: `phase1-provider-registry`
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

- PR: https://github.com/leonbreukelman/richard-router/pull/4
- Implementation commit: `58a764a84a81b0b7c4a245a3a11cdff073084fe4`
- Merge commit: `394f58ad3f406d70200318dc8b0b3404fda107f3`
- PR-head CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Post-merge push-to-`main` CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Final PR ledger comment: https://github.com/leonbreukelman/richard-router/pull/4#issuecomment-4921441175

## Independent review

Opus review output: `docs/verification/2026-07-08-phase0-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: narrowed ADR language so Phase 3/4 items are recorded as later-phase handoff decisions rather than Phase 0 implementation, clarified PR-run CI evidence in this verification file, and added `workflow_dispatch` plus concurrency cancellation to CI.

## Phase 1 local gates

Targeted tests:

```bash
uv run pytest -q tests/test_config.py tests/test_cli_validate.py
```

Observed result before review patch: `9 passed in 0.10s`.

Full repo gate:

```bash
uv run ruff check . && uv run pytest -v
```

Observed result:

- Ruff: `All checks passed!`
- Pytest before review patch: `26 passed, 1 warning in 0.12s`
- Pytest after review patch: `27 passed, 1 warning in 0.12s`

Validate CLI smoke:

```bash
NVIDIA_API_KEY=dummy OPENROUTER_API_KEY=dummy uv run richard-router validate --config config/router.example.yaml
uv run richard-router validate --config /tmp/richard-router-invalid.yaml
```

Observed result:

- Example config: `config ok`
- Missing `CLI_VALIDATE_API_KEY`: printed `virtual_models.coding.upstreams[0] env var CLI_VALIDATE_API_KEY is not set`, exit `1`

## Phase 1 PR/API ledger

Pending push/PR/CI/merge.

## Phase 1 independent review

Opus review output: `docs/verification/2026-07-08-phase1-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: added direct CLI coverage for dangling provider references and restored trailing newlines in edited text files.
