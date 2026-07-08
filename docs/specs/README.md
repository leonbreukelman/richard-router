# Specs

Specs define scoped work before implementation.

Use:

- `docs/specs/TEMPLATE-track-l.md` for small, local, low-risk changes.
- `docs/specs/TEMPLATE-track-f.md` for full feature / architecture / PR-lifecycle work.
- `docs/specs/YYYY-MM-DD-<slug>.md` for real specs.
- `docs/specs/YYYY-MM-DD-<slug>.BLOCKED.md` for blocked/rejected work when no active spec exists.

Rules:

- One spec should name the intended artifact, scope, grounding files, gates, and evidence ledger.
- If scope expands materially, stop and file `SCOPE-DELTA` instead of silently broadening the spec.
- If a spec makes or relies on a durable architecture/product/API decision, add or cite a decision record under `docs/decisions/`.
- If a spec produces proof artifacts, put them under `docs/verification/` and cite them in the final ledger.
