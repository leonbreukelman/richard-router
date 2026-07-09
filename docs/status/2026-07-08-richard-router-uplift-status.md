# Track F router-core uplift status

Date: 2026-07-08
Status: Phase 0 in progress on branch `phase0-governance-ci`
Mode: `github-pr`
Base: `7bcbf7e11ed3ced49e9bf8b51215ed3eea8860a0`

## What went wrong

The method card was stale. `docs/method/PROJECT.md` still said `local-scaffold`, no git origin, and no CI, while the live repo is already `leonbreukelman/richard-router` on GitHub with `main` at the Track F base. That contradiction blocked honest Phase 1 work because `github-pr` evidence requires an API-readable CI check-run, and the repo had no workflow.

## Current Phase 0 scope

- Add GitHub Actions CI for the repo gate.
- Update `PROJECT.md` from stale local-scaffold facts to live GitHub PR governance.
- Record the mode/CI rationale in `docs/method/DESIGN-RECORD.md`.
- Add the provider-registry ADR for Phase 1.

## Boundary

Phase 1 implementation must not start until Phase 0 is PR-reviewed/CI-green/merged, or the mode is explicitly changed back to local-only. No deploy, credential change, branch protection change, or destructive repository action is in Phase 0.
