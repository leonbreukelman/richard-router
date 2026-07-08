# Handoff Method — Global Invariant Contract

Status: active. This file is global for repos using this scaffold. Per-project instantiation lives in `docs/method/PROJECT.md`; project cards may select modes and add stricter constraints, but may not loosen this contract.

Agents load this file first, then `docs/method/PROJECT.md`.

## 0. Override governance

`PROJECT.md` fills slots and may add constraints. It may not weaken this contract.

Local overrides may never:

- remove or soften an operator gate;
- weaken anti-fabrication evidence;
- delete a tier from the escalation ladder;
- turn a hard stop into a soft one;
- invent a looser lifecycle mode than this file defines.

If a repo needs a looser rule, change this global method deliberately and record the rationale in `docs/method/DESIGN-RECORD.md`. Do not hide the change in a local project card.

## 1. Lifecycle modes

Every repo selects one mode in `PROJECT.md`.

### `local-scaffold`

Default for new, local-only, remoteless, experimental, or first-install repos.

Terminal state: scaffold files installed locally, AGENTS.md load hook present, structural acceptance checks pass, and a local ledger is reported. No push, PR, merge, branch deletion, or deploy is implied.

### `github-pr`

Use only when Leon explicitly asked for PR lifecycle or the repo is already governed that way.

Terminal state: `certify → PR → merge on CI-green → delete branch → report ledger`.

Never push-and-stop. Never call it done without merged PR evidence, changed-file list read from GitHub, CI check-run conclusion, and the named artifact.

### `protected-production`

Use for repos/systems where production impact, irreversible actions, secrets, infrastructure, or public state are in play.

Branch/PR work may be in scope. Deploy, production mutation, destructive actions, credential changes, billing/spend, privacy/security judgments, and public-state changes remain operator-gated.

## 2. Roles

- Operator (Leon): intent, value gate, irreversible-action gates. Not a developer; evidence must be in product terms.
- Implementer (Hermes/Codex/agent): lead developer. Codes, runs gates, and reports evidence within scope.
- Certifier/reviewer (Claude Code Opus unless otherwise routed): independent review/certification against the spec.
- Verifier: checks returned ledgers against live repo/API evidence when needed.

Independence between verifier and certifier is procedural, not epistemic. Claim no more than it proves.

## 3. Preflight before edits

1. Identify mode, base commit, repo root, and protected paths.
2. Run or inspect the repo's gate commands on base when mode requires code work.
3. Re-read every path under the spec's grounding section.
4. If base is red or grounding contradicts the spec, stop and file BLOCKED or SCOPE-DELTA.

For `local-scaffold`, structural checks replace test gates unless the repo already has relevant gates.

## 4. Escalation ladder

"Stuck" is mechanical, not felt. Leave self-attempt on any of:

- 3 distinct failed attempts at the same failing test/error;
- a grounding contradiction;
- required work outside the scope lock.

Tiers:

0. Self-attempt budget.
1. Cheap automated review (Copilot or local equivalent when wired).
2. Divergent consult (Grok/xAI when wired).
3. Claude Code Opus design review.
4. Fable escalation only after live preflight and only when reasoning-hard.
5. BLOCKED record + operator.

Log each consultation in the ledger, or state none needed.

## 5. Scope amendment: SCOPE-DELTA

On discovering the locked scope is insufficient, stop and return a SCOPE-DELTA:

1. what was found, grounded to file/line/contract;
2. minimal expansion;
3. why it is load-bearing;
4. whether it touches protected paths or changes public contract.

No work on the delta before the ruling.

## 6. Documentation and decision discipline

The repo's durable memory lives in docs artifacts, not chat and not root context-file drift.

Use this topology unless `PROJECT.md` declares stricter local paths:

- `docs/specs/YYYY-MM-DD-<slug>.md` — scoped task, feature, strategy, or handoff specs.
- `docs/decisions/YYYY-MM-DD-<slug>.md` — durable ADR/decision records.
- `docs/status/` — current-state claims, readiness summaries, multi-phase progress, blockers, next actions.
- `docs/verification/` — evidence that proves status/spec claims: command output summaries, reviewer packets, audit ledgers, CI/API readbacks, run manifests, screenshots metadata.
- `reports/` — optional bulky generated reports/logs; if used, cite or summarize them from `docs/verification/`.
- `docs/method/DESIGN-RECORD.md` — rationale/history for changes to this method, scaffold, lifecycle mode, or governance process.

Filename slugs are local-date plus short kebab-case: `YYYY-MM-DD-short-kebab-slug.md`.

### Decisions / ADRs

Before a structural/product/API/governance-adjacent change, read relevant prior decision records. After making a durable decision, write or update a decision record.

Use `docs/decisions/` for product and architecture decisions that future agents must not re-litigate, especially changes to component boundaries, public API/CLI/schema/config behavior, protected/generated/security-sensitive paths, external connector assumptions, deployment assumptions, or long-lived product direction.

Tie-break: method/scaffold/governance/lifecycle-mode changes go first in `docs/method/DESIGN-RECORD.md`. If the same change also makes a product/architecture/API decision, write the ADR under `docs/decisions/` and cross-link it from `DESIGN-RECORD.md`.

### Status vs verification

Status states the claim. Verification stores the proof.

A CI readback, reviewer JSON, command log, or audit ledger belongs in `docs/verification/`. The readiness conclusion citing that proof belongs in `docs/status/` or the repo-specific current-state file named by `PROJECT.md`.

Never use `AGENTS.md` as a status log. Keep root context files stable: operating constraints and pointers only.

### Secrets

No secret values, tokens, passwords, credential material, or connection strings belong in repo docs. Use env-var names only, and redact any accidental values as `[REDACTED]`.

## 7. Failure record

Blocked or rejected turns write a `docs/specs/YYYY-MM-DD-<slug>.BLOCKED.md` record or mark the active spec `Status: blocked`. Include attempts, blocker, escalation log, and last grounded state.

## 8. Evidence ledger

Required evidence depends on mode.

For `local-scaffold`:

- files created/updated/preserved;
- AGENTS.md load hook exactly once;
- `PROJECT.md` mode and repo facts;
- structural checks output;
- local git diff/status if git exists;
- docs/decision/status/verification artifacts touched, if any;
- open decisions.

For `github-pr`:

- PR # + URL;
- implementation commit SHA and merge commit SHA on default branch;
- branch lifecycle: pushed → merged → deleted;
- changed-file list read from GitHub and compared to expected set;
- CI check-run conclusion read from API;
- escalation log;
- certification statement;
- docs/decision/status/verification artifacts touched, if any;
- protected paths untouched;
- operator value summary.

For `protected-production`:

- all `github-pr` evidence for code changes;
- explicit list of production/irreversible actions not taken;
- operator approvals for any gated action that was taken.

## 9. Anti-fabrication

Done means the named artifact exists and the mode-appropriate evidence proves it. Self-reported summaries and local test text are not enough for `github-pr`; API-read merge/check/file evidence is required.

If the goal names code and only a doc ships, that is not done. If the goal names a doc/scaffold and that artifact exists with structural checks, that can be done in `local-scaffold` mode.

## 10. Operator gates

Stop for Leon before:

- destructive or irreversible action;
- non-free spend or live model/API runs outside existing subscription/default budget;
- production push/deploy/mutation;
- credential, auth, privacy, or security judgment;
- public-state change not explicitly in scope.

## 11. Control words

- `scope`: halt drift and return to the scope lock.
- `SCOPE-DELTA`: request scope expansion.
- `BLOCKED`: no honest path within current scope/mode.

Load `docs/method/PROJECT.md` now for this repo's mode, gates, protected paths, connector scope, docs paths, and pairing.
