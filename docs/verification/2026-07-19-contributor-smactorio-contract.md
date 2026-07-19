# Contributor and SmactorIO Contract Verification

Date: 2026-07-19
Scope: public repository guidance and templates only

## Problem

The repository exposed development commands and CI, but an external human or coding agent could not discover the complete SmactorIO triage/authorization contract or one consistent pre-PR checklist from project-local files.

## Implemented contract

- `AGENTS.md` points agents to `CONTRIBUTING.md` before issue or PR creation.
- `CONTRIBUTING.md` defines normal contribution checks, SmactorIO triage, maintainer authorization labels, lifecycle-label ownership, path boundaries, and PR evidence.
- The SmactorIO issue form applies only `smactorio`; maintainers retain authorization by applying `autonomy:ready` and `risk:low` after triage.
- The PR template names the exact local and GitHub gates.
- README and PROJECT link or restate the same entry points.
- `tests/test_repository_guidance.py` protects the discoverability and template contract and is itself human-controlled by the private policy.

## Verification before PR

- Issue-form YAML parsed structurally; labels were exactly `['smactorio']` and form IDs were unique.
- `uv sync --all-groups`: passed.
- `uv run ruff check .`: passed.
- `uv run pytest -v`: 174 passed.
- Repository-guidance tests: 6 passed.
- Method-scaffold strict dry-run: success, no errors or warnings.
- Candidate secret scan: no leaks.
- Independent implementation review: accepted; valid nonblocking hardening recommendations were applied and the focused acceptance review then accepted the final contract.

## Boundaries

No live issue was created because that could trigger outward automation. GitHub PR CI and merged-main readback are publication gates and are not claimed by this pre-PR artifact.
