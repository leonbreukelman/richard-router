# SmactorIO Ticket Entrypoint and Labeling Instructions

Status: design reviewed; required corrections applied
Date: 2026-07-20
Lifecycle: `github-pr`

## Owner outcome

A coding agent that follows this repository's instructions can open a correctly structured SmactorIO request, distinguish filing from authorization, apply only labels it is permitted to manage, and verify the resulting issue without needing outside knowledge of this repository's GitHub workflow.

## Grounding

- `AGENTS.md` requires agents to read `CONTRIBUTING.md` before creating an issue or pull request.
- `CONTRIBUTING.md` defines the SmactorIO eligibility, authorization, lifecycle-label, and autonomous-path contracts.
- `.github/ISSUE_TEMPLATE/smactorio-task.yml` applies only `smactorio`; maintainers add `autonomy:ready` and `risk:low` after triage.
- `README.md` repeats the public entrypoint.
- `tests/test_repository_guidance.py` protects the public contract.
- Current instructions link to the issue-form YAML source but provide neither a direct `issues/new?template=` entrypoint nor exact CLI/readback commands.

## Design

### 1. Keep the trust boundary unchanged

The browser issue form remains the normal public/contributor path. It auto-applies only `smactorio`. Filing never self-authorizes pickup.

Only a maintainer or maintainer-authorized coding agent with repository triage permission may use the CLI path that applies labels. The create command applies only `smactorio`. `autonomy:ready` and `risk:low` are added together only after the issue has been read back and confirmed to meet the existing triage criteria.

Runtime/operator lifecycle labels remain forbidden for manual contributor or coding-agent management:

- `smactorio:claimed`
- `smactorio:blocked`
- `smactorio:needs-attention`
- `smactorio:done`

### 2. Add an executable browser entrypoint

Add this direct issue-form URL where users are told to file work, alongside the retained source link for inspection:

`https://github.com/leonbreukelman/richard-router/issues/new?template=smactorio-task.yml`

The source path remains named for inspection, but it is not presented as the filing action.

### 3. Add an exact maintainer coding-agent CLI path

`CONTRIBUTING.md` will state the required body sections and provide exact commands for an authorized maintainer identity:

1. Create an issue with a `[SmactorIO]` title, a completed body file, and only `smactorio`.
2. Read the created issue back before authorization and verify every required body section is complete, including the safety/triage confirmations that mirror the issue form's required checkboxes.
3. After triage, add `autonomy:ready` and `risk:low` together. This command is explicitly maintainer-only, requires repository triage permission, and must never run during issue creation.
4. Read labels back and verify the issue remains open with the complete three-label intake set.

The required CLI body sections mirror the issue form:

- owner or user outcome;
- current behavior and evidence;
- acceptance criteria;
- expected file scope;
- test plan; and
- safety/triage confirmations.

The commands will use placeholders instead of creating a live issue during verification. No automation or credential scope changes are part of this update.

### 4. Protect execution discoverability

Extend `tests/test_repository_guidance.py` to require:

- the direct new-issue URL in `CONTRIBUTING.md` and `README.md`;
- an exact `gh issue create` instruction that applies `smactorio`;
- a negative assertion that the documented `gh issue create` instruction contains neither `autonomy:ready` nor `risk:low`;
- an exact `gh issue edit` instruction that adds `autonomy:ready` and `risk:low` after triage;
- an exact `gh issue view` readback instruction; and
- the existing single-label issue-form and runtime-label ownership checks.

The test must not loosen the current form assertion that only `smactorio` is auto-applied.

## Planned files

- `CONTRIBUTING.md` — canonical browser and authorized-maintainer CLI instructions.
- `README.md` — direct public filing link and pointer to the canonical instructions.
- `tests/test_repository_guidance.py` — regression coverage for executable entrypoints and readback.
- `docs/method/DESIGN-RECORD.md` — governance rationale for the new execution instructions.
- `docs/verification/2026-07-20-smactorio-ticket-entrypoint.md` — final local/review/CI evidence.

Protected-path changes are intentional and owner-authorized for this governance fix. No `.github` workflow or issue-form behavior changes are planned.

## Acceptance criteria

1. A repository reader can follow `AGENTS.md` to one canonical document and find a direct browser filing action.
2. An authorized maintainer coding agent can copy exact create, triage-label, and readback commands.
3. The create path applies only `smactorio`; a regression test proves that its documented command contains neither `autonomy:ready` nor `risk:low`, which appear only in the maintainer-only post-triage edit instruction.
4. The complete pickup label set remains `smactorio`, `autonomy:ready`, and `risk:low`.
5. Runtime lifecycle labels remain explicitly non-contributor-controlled.
6. Focused repository-guidance tests first fail against the missing execution instructions, then pass after implementation.
7. `uv run ruff check .` and `uv run pytest -v` pass locally and in the required GitHub check `uv / ruff / pytest`.
8. Independent Opus implementation review finds no blocking trust-boundary or instruction ambiguity.
9. The PR changes only the planned public-safe files, merges to `main`, and the feature branch is deleted.

## Non-goals

- Creating or triaging a live SmactorIO issue as a test.
- Changing label definitions, issue-form auto-labels, SmactorIO runtime behavior, branch protection, CI, credentials, or repository permissions.
- Allowing public contributors to self-apply authorization labels.
- Manually managing runtime lifecycle labels.

## Design review

Claude Code Opus (`claude-opus-4-8`) returned `ACCEPT_WITH_CHANGES`. The required corrections were applied before implementation:

- preserve the source link while adding the executable form URL;
- require complete safety-confirmation readback before authorization;
- label the authorization command as maintainer-only and never part of creation; and
- add a negative regression assertion preventing readiness labels from entering the create command.

## Verification plan

1. Add the repository-guidance assertions and capture the expected focused-test failure.
2. Implement the documentation and design-record changes.
3. Run the focused guidance test, Ruff, and the full pytest suite.
4. Run one independent Opus review against the final diff and verification summary; patch valid criticism and rerun gates.
5. Push the scoped branch, open a PR, verify its changed-file list and exact-head check-run through GitHub, merge, delete the branch, and verify the push-to-main check-run.
