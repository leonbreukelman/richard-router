# Status

This directory holds current-state claims, readiness summaries, multi-phase progress, blockers, and next actions.

Use status files when work spans turns, sessions, model switches, or handoffs.

Recommended files:

- `docs/status/CURRENT.md` — optional rolling current-state page.
- `docs/status/YYYY-MM-DD-<slug>.md` — dated status or readiness update.
- `docs/status/INDEX.md` — optional local index maintained by the repo.

Rules:

- Status states the claim. Verification stores the proof.
- Cite proof under `docs/verification/` for test output, CI/API readbacks, reviewer JSON, audit ledgers, or generated evidence.
- Do not use `AGENTS.md` as a status log. Root context files should contain stable operating constraints and pointers only.
- Keep status concise enough for future agents to resume without reading a whole chat transcript.
