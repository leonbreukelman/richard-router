# Project Card — richard-router

Local instantiation of `docs/method/METHOD.md`. This is the only method file edited per repo. It may select a globally defined lifecycle mode and add stricter constraints; it may not loosen the global contract.

Generated: 2026-07-07

## Lifecycle mode

`local-scaffold`

Mode notes:
Local scaffold only. No push/PR/merge/deploy implied. Structural ledger is sufficient for scaffold installation.

## Protected / frozen paths

None declared yet. Add frozen/generated/security-critical paths here before `github-pr` work.

## Gate commands

- No gate detected by installer; define before selecting `github-pr` mode.

## CI

absent — no `.github/workflows/` directory detected; first follow-up before `github-pr` governance is to add CI.

## Connector scope

No git origin detected. Treat as local unless Leon explicitly adds a remote.

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

No repo-specific env-var names discovered by installer. Add names only, never values.

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

- Repo path: `/home/leonb/projects/richard-router`
- Git root: `/home/leonb/projects/richard-router`
- Base SHA at install: `unknown`
- Origin: `none`

## Open decisions

- Confirm protected paths.
- Confirm final gate commands.
- Add CI before `github-pr` governance if CI is absent.
- Verify connector write scope before PR lifecycle work.
