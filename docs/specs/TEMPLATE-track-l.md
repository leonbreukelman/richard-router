# <Name> — Spec + Handoff (Lite)

Date: YYYY-MM-DD
Track: L
Status: authored | in-progress | landed | blocked
Thread: <thread-slug>
Repo: <owner/repo or local path> · Branch: <branch> from base <SHA>
Mode: local-scaffold | github-pr | protected-production
Driver: Hermes Agent · Certifier: Claude Code Opus · Method: docs/method/METHOD.md

Track L qualifies only if all hold: one named change; no new public contract/schema/CLI; no protected-path touch; file set is declared and small. If any fails mid-turn, stop and file SCOPE-DELTA — do not silently become Track F.

## Goal

<The one change, in product terms.>

## The one rule

Done = <single sentence>. Does NOT count: <obvious substitutions>.

## Scope lock

Build only this: <the one change, plus its named check/test>.

Files touched, exhaustive: `<path>`, `<path>`.

Do not build: <at least one line>.

## The change

<Verbatim before/after or exact artifact description. No prose-only implementation summary.>

## Acceptance gate

Mode-appropriate evidence plus `<test/check>` covering <assertion>.

## Report back

Ledger per METHOD.md §8. Track-L ledgers may be short but omit nothing required by the selected mode.

## Stop clause

No evidence → not done → BLOCKED record and stop. Never substitute a summary for the named change.
