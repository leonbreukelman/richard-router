# SmactorIO Ticket Entrypoint Verification

Date: 2026-07-20
Status: local implementation and independent review verified; GitHub lifecycle pending
Scope: public repository guidance and guardrails only

## Owner outcome under test

An unfamiliar coding agent can open a SmactorIO request through a direct GitHub form, or—when operating under a maintainer-authorized identity with repository triage permission—use exact CLI create, readback, authorization-label, and final-readback commands without conflating filing with autonomous authorization.

## Design review

Claude Code Opus (`claude-opus-4-8`) returned `ACCEPT_WITH_CHANGES` on the pre-implementation design. Before implementation, the design was corrected to:

- retain the tracked form-source link while adding the direct filing URL;
- require complete safety-confirmation readback before authorization;
- mark the readiness-label command maintainer-only and forbidden during creation; and
- require a negative test proving readiness labels cannot appear in the documented create command.

## TDD evidence

Expected RED after adding the new repository-guidance guardrail:

- `uv run pytest tests/test_repository_guidance.py -q`
- Result: `1 failed, 6 passed`.
- Failure: the direct SmactorIO new-issue URL was absent from `CONTRIBUTING.md`.

GREEN after implementation:

- `uv run pytest tests/test_repository_guidance.py -q`
- Result: `7 passed in 0.01s`.

## Local verification

- `uv sync --all-groups` — passed; 34 packages resolved and 33 checked.
- `uv run ruff check .` — passed (`All checks passed!`).
- `uv run pytest -v` — passed (`175 passed in 0.91s`).
- `git diff --check` — passed.
- GitHub CLI help confirmed installed support for `gh issue create`, `gh issue edit`, and `gh issue view` with the documented flags.
- The direct URL preserves the exact `smactorio-task.yml` template selection through GitHub's unauthenticated sign-in redirect.

## Trust-boundary checks

- The tracked issue form still auto-applies exactly `smactorio`.
- The documented create command contains neither `autonomy:ready` nor `risk:low`.
- The readiness labels appear only in the maintainer-only post-readback edit command.
- The instructions require form-equivalent safety confirmations before authorization.
- Runtime lifecycle labels remain runtime/operator-managed.
- No live issue, label, workflow, credential, branch-protection, or SmactorIO runtime state was changed during local verification.

## Independent implementation review

Claude Code Opus (`claude-opus-4-8`) returned `ACCEPT_WITH_CHANGES` with no blocking implementation or trust-boundary findings. It confirmed that the documentation and commands were factually correct and safe, then found four realistic anti-regression bypasses in the new test. All were patched before PR publication:

- require a final label readback after the authorization edit;
- require exactly one create command, one edit command, and two readback commands so duplicate unsafe instructions cannot evade the checked command block;
- require the direct new-issue link to be the filing action and to precede the retained source link; and
- protect every required CLI body section, not only the safety confirmation.

The reviewer assessed the tracked-only source snapshot and producer evidence with read-only tools; it did not independently rerun the commands.

Post-review verification:

- `uv run pytest tests/test_repository_guidance.py -q` — `7 passed in 0.01s`.
- `uv run ruff check .` — passed.
- `uv run pytest -v` — `175 passed in 0.80s`.
- `git diff --check` — passed.

## GitHub evidence boundary

PR URL, implementation and merge SHAs, GitHub-read changed files, exact-head CI, push-to-main CI, and branch deletion will be read back after publication and reported in the final evidence ledger. They are not claimed by this pre-PR artifact.
