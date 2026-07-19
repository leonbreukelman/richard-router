# Project Card — richard-router

Local instantiation of `docs/method/METHOD.md`. This is the only method file edited per repo. It may select a globally defined lifecycle mode and add stricter constraints; it may not loosen the global contract.

Generated: 2026-07-07
Updated: 2026-07-19

## Lifecycle mode

`github-pr`

Mode notes:
This repo is live on GitHub and now uses per-phase feature branches and PRs. Done requires the `github-pr` evidence ledger from `docs/method/METHOD.md` §8: PR URL, implementation and merge SHAs on `main`, pushed→merged→deleted branch lifecycle, GitHub-read changed-file list, API-read CI check-run conclusion, certification statement, and operator value summary.

## Protected / frozen paths

The SmactorIO autonomous allowlist is deliberately narrow: only `richard_router/`, `tests/` except `tests/test_repository_guidance.py`, `docs/` except `docs/method/`, `README.md`, and `config/router.example.yaml` are autonomous-worker scope. Everything else is human-controlled.

Protected examples include:
- Governance and contributor contract: `AGENTS.md`, `CONTRIBUTING.md`, `.github/`, `docs/method/`, `tests/test_repository_guidance.py`.
- Dependency/build boundaries: `pyproject.toml`, `uv.lock`, `.gitmodules`, `Dockerfile`.
- Secret material and local config: `.env*`, `config/router.yaml`, `config/*.local.yaml`.
- Ignored local evidence and runtime artifacts: `reports/`, `.venv/`, caches, and logs.

Normal human-reviewed PRs may propose a protected-path change when explicitly justified. Intake labels do not put those paths into autonomous scope.

## Gate commands

- `uv run ruff check .`
- `uv run pytest -v`

## CI

present — `.github/workflows/ci.yml` runs `uv sync --all-groups`, `uv run ruff check .`, and `uv run pytest -v` on push and PR to `main`.

Live `main` branch protection strictly requires `uv / ruff / pytest` on the current PR head before merge.

## Connector scope

Remote: `git@github.com:leonbreukelman/richard-router.git` / `https://github.com/leonbreukelman/richard-router`.

Default branch: `main`.

Visibility: public.

Connector scope: GitHub PR lifecycle for scoped branches only. No deploy, production mutation, credential change, or destructive repository action is implied by this card.

## Contributor and SmactorIO contract

- Public contribution and pre-PR instructions: `CONTRIBUTING.md`.
- SmactorIO requests start through `.github/ISSUE_TEMPLATE/smactorio-task.yml`.
- The form applies only `smactorio`; a maintainer adds `autonomy:ready` and `risk:low` after triage.
- Runtime lifecycle labels are not contributor-controlled.

## Documentation discipline

Default artifact paths unless this repo declares stricter local conventions:

- Specs: `docs/specs/YYYY-MM-DD-short-kebab-slug.md`
- Decisions / ADRs: `docs/decisions/YYYY-MM-DD-short-kebab-slug.md`
- Status: `docs/status/` (`docs/status/CURRENT.md` optional for a rolling current-state page)
- Verification: `docs/verification/`
- Bulky generated reports: `reports/` when needed, with summaries or links from `docs/verification/`
- Method/scaffold history: `docs/method/DESIGN-RECORD.md`

Routing rules:

- Product/architecture/API/config/path decisions go in `docs/decisions/`.
- Method/scaffold/governance/lifecycle-mode rationale goes in `docs/method/DESIGN-RECORD.md`.
- Status states claims; verification stores proof.
- `AGENTS.md` is not a status log.

Repo-specific docs overrides:

- Decision records: default `docs/decisions/`.
- Status: default `docs/status/` (optional `docs/status/CURRENT.md`).
- Verification: default `docs/verification/`.
- No repo-specific docs overrides declared yet.

## Secrets / provider contract

No secret values belong in repo docs. Only env-var names may be listed here.

- `RICHARD_ROUTER_API_KEY` — optional inbound router auth.
- `NVIDIA_API_KEY` — example primary provider credential.
- `OPENROUTER_API_KEY` — example fallback provider credential.
- Test-only fixture names: `TEST_NVIDIA_KEY`, `TEST_OPENROUTER_KEY`.

## Exit codes

No repo-specific exit-code contract declared yet.

## Escalation wiring

- Claude Code CLI: available
- Grok CLI: available
- Copilot CLI: available
- Fable: use only after explicit preflight; never silently substitute another model.

## Pairing

Implementer: Hermes Agent / delegated coding agent within scope.
Certifier/reviewer: Claude Code Opus by default; Fable only after preflight or explicit Tier-4 escalation.
Verifier: Hermes/Leon flow checks ledger against live evidence.

## Current repo facts

- Working-tree path is contributor-specific; resolve the root with `git rev-parse --show-toplevel`.
- Resolve the base from current `origin/main` before every task; do not trust a stored SHA.
- Canonical remote: `git@github.com:leonbreukelman/richard-router.git` / `https://github.com/leonbreukelman/richard-router`.
- GitHub repo: `leonbreukelman/richard-router` (`public`)

## Open decisions

- Confirm any future generated/frozen paths before expanding scope beyond this Track F uplift.
