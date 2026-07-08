# <Name> — Spec + Handoff

Date: YYYY-MM-DD
Track: F
Status: authored | in-progress | landed | blocked | superseded
Thread: <thread-slug>
Supersedes: <prior spec path, or none>
Repo: <owner/repo or local path>
Branch: <feature-branch> from base <base-commit-SHA>
Mode: local-scaffold | github-pr | protected-production
Driver: Hermes Agent · Certifier: Claude Code Opus · Method: docs/method/METHOD.md

## The one rule

Done = <single sentence in artifact/code terms, keyed to the named artifact in Goal>.

Does NOT count as done:
- shipping anything other than the named artifact;
- a green local run without mode-appropriate ledger evidence;
- a doc summary substituted for requested code, or code substituted for requested doc;
- <task-specific non-counts>.

## Goal

<The capability or artifact that ships, in product terms. Name the artifact whose existence-and-verification = done.>

## Scope lock

Build only this:
1. <numbered, concrete>
2. <...>

Do not build:
- <at least one line; empty means scope was not locked>

## Grounding

Read these paths at base <SHA> before editing; re-read them in your own turn and confirm conflicts. Repo wins on conflict — stop and flag, do not invent.

- `<path>` — <what it establishes>

## Preflight

Base <SHA> checked out. Mode from PROJECT.md: <mode>. Gate commands green on base if this is code work and the repo has gates. If base is red, file BLOCKED instead of fixing unrelated breakage.

## Component contract

For each component that changes:

- Input and validation:
- Selection/routing:
- Output/rendered behavior:
- Never rendered / never exposed:
- Determinism:
- Fail-closed conditions:

## Design decisions

- D1 — <decision + rationale>. Tag operator-deferred items and echo them under Known boundaries.

## Tasks

Use concrete file/test names. No prose-only descriptions.

1. <task> — proven by `<test/check/artifact>`
2. <...>

## Acceptance gate

State mode-appropriate evidence:

- local-scaffold: structural file checks and local diff/status.
- github-pr: PR URL, merge SHA, GitHub changed-file list, CI check-run conclusion.
- protected-production: github-pr evidence plus explicit operator approvals for gated actions.

## If you get stuck

Follow METHOD.md escalation ladder. Scope insufficiency is SCOPE-DELTA, not improvisation.

## Report back

Return the evidence ledger per METHOD.md §8, including escalation log and operator value summary.

## Known boundaries and open items

- <what is not proven, operator-gated, or deferred>

## Stop clause

If you cannot produce the mode-appropriate evidence, it is not done. File BLOCKED and stop.
