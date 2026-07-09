# Track F router-core uplift verification

Date: 2026-07-08
Mode: `github-pr`
Current active branch: `phase4-decision-log`
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

## Phase 0 independent review

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

- PR: https://github.com/leonbreukelman/richard-router/pull/5
- Implementation commit: `01ac36bd0362b49c119399ed2d40b70760f5aba0`
- Merge commit: `f6b4989f53f93c5e31b33dae98274996fd62b2fd`
- PR-head CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Post-merge push-to-`main` CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Final PR ledger comment: https://github.com/leonbreukelman/richard-router/pull/5#issuecomment-4925664257

## Phase 1 independent review

Opus review output: `docs/verification/2026-07-08-phase1-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: added direct CLI coverage for dangling provider references and restored trailing newlines in edited text files.

## Phase 2 local gates

Base gate before Phase 2 edits on `main` at `f6b4989f53f93c5e31b33dae98274996fd62b2fd`:

```bash
uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest: `27 passed, 1 warning in 0.12s`

Targeted Phase 2 tests after implementation:

```bash
uv run pytest -q tests/test_pooling.py tests/test_service_failover.py
```

Observed result before review patches: `12 passed, 1 warning in 0.13s`.
Observed result after review patches: `13 passed, 1 warning in 0.13s`.

Full repo gate after implementation:

```bash
uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest before review patches: `30 passed, 1 warning in 0.13s`
- Pytest after review patches: `31 passed, 1 warning in 0.14s`

## Phase 2 independent review

Opus review output: `docs/verification/2026-07-08-phase2-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: added streaming pooling coverage, asserted the default 5s connect timeout, changed the client cache key from upstream name only to `(name, base_url, model)` to avoid accidental collisions, and reset the stream-entered guard after the manual non-2xx stream close.

## Phase 2 PR/API ledger

- PR: https://github.com/leonbreukelman/richard-router/pull/6
- Implementation commit: `1225ca88f3990251e49f37ee6bded80ded5ae8d4`
- Merge commit: `e03ab57815e8ef44905e7bc05607b9cd988019c4`
- PR-head CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Post-merge push-to-`main` CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Final PR ledger comment: https://github.com/leonbreukelman/richard-router/pull/6#issuecomment-4925853539

## Phase 3 local gates

Base gate before Phase 3 edits on `main` at `fe95354fbbbc248f514a0f6043645fe74e8323ed`:

```bash
uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest: `31 passed, 1 warning in 0.14s`

Targeted Phase 3 tests after implementation:

```bash
uv run pytest -q tests/test_circuit_breaker.py tests/test_config.py tests/test_service_failover.py tests/test_pooling.py && uv run ruff check .
```

Observed result before review patches: `26 passed, 1 warning in 0.14s`; Ruff: `All checks passed!`.
Observed result after review patches: `28 passed, 1 warning in 0.15s`; Ruff: `All checks passed!`.

Full repo gate after implementation:

```bash
uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest before review patches: `37 passed, 1 warning in 0.14s`
- Pytest after review patches: `39 passed, 1 warning in 0.15s`

## Phase 3 independent review

Opus review output: `docs/verification/2026-07-08-phase3-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: non-retryable HTTP responses now reset breaker state so half-open probes cannot wedge the circuit open and caller/config 4xx responses break the consecutive-failure streak.

## Phase 3 PR/API ledger

- PR: https://github.com/leonbreukelman/richard-router/pull/8
- Implementation commit: `337f6de5bac3774cbe426c0d3674f3c9cf8e7550`
- Merge commit: `31485e266ca44051061e6c931099d9679fbf301d`
- PR-head CI check-runs read through API:
  - `uv / ruff / pytest` -> `completed/success`
  - `copilot-pull-request-reviewer` -> `completed/success`
- Post-merge push-to-`main` CI check-run read through API: `uv / ruff / pytest` -> `completed/success`
- Local post-merge gate: `uv sync --all-groups && uv run ruff check . && uv run pytest -v` -> Ruff passed; Pytest `39 passed, 1 warning in 0.16s`.
- Final PR ledger comment: https://github.com/leonbreukelman/richard-router/pull/8#issuecomment-4928183750
- Branch cleanup: `phase3-circuit-breaker` merged, remote branch deleted, local refs pruned.

## Phase 4 local gates

Base gate before Phase 4 edits on `main` at `ff462f460d8cbfcc062461dad768c74ad60472f0`:

```bash
git pull --ff-only && uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result:

- `git pull --ff-only`: already up to date
- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Pytest: `39 passed, 1 warning in 0.15s`

Targeted Phase 4 tests after implementation:

```bash
uv run pytest -q tests/test_decision_log.py tests/test_config.py tests/test_service_failover.py tests/test_circuit_breaker.py && uv sync --all-groups && uv run ruff check . && uv run pytest -v
```

Observed result before independent review:

- Targeted tests: `29 passed in 0.06s`
- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Full Pytest: `44 passed, 1 warning in 0.15s`

Observed result after independent-review patches:

- Targeted tests: `31 passed in 0.06s`
- `uv sync --all-groups`: resolved 31 packages, checked 30 packages
- Ruff: `All checks passed!`
- Full Pytest: `46 passed, 1 warning in 0.15s`

## Phase 4 independent review

Opus review output: `docs/verification/2026-07-09-phase4-opus-review.json`.

Result: `ACCEPT`, with nonblocking notes. Valid notes patched before PR: decision-log callback/logger failures are isolated so logging cannot break successful routing; exception-attempt logging now has regression coverage proving `error_type` is class-name metadata only and exception text/hosts are not logged; the ADR and README document that streaming `success` means 2xx stream headers were accepted, not full stream-body completion.

## Phase 4 PR/API ledger

Pending push/PR/CI/merge.
