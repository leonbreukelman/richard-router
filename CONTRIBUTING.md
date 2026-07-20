# Contributing to Richard Router

This repository accepts normal pull requests and bounded task requests for SmactorIO. Humans and coding agents should follow the same repository checks and safety boundaries.

## Start here

Before editing:

1. Read `AGENTS.md`.
2. Read `docs/method/METHOD.md` and `docs/method/PROJECT.md`.
3. Read relevant files under `docs/decisions/` and `docs/specs/`.
4. Fetch the current default branch and base your branch on current `origin/main`.
5. Keep one pull request focused on one outcome.

Do not commit credentials, `.env` files, `config/router.yaml`, `config/*.local.yaml`, logs, caches, runtime state, or generated local evidence.

## Normal pull-request path

A human or coding agent may create a normal pull request without using SmactorIO.

Before opening the pull request, run from the repository root:

```bash
uv sync --all-groups
uv run ruff check .
uv run pytest -v
```

Update or add tests for behavior changes. Add a decision record under `docs/decisions/` when changing a durable API, configuration, architecture, path, deployment, or security boundary. Add verification evidence under `docs/verification/` when the method requires it.

GitHub must report the exact required check `uv / ruff / pytest` as successful before merge. Passing local tests does not grant merge or deployment authority.

## Requesting SmactorIO work

Open a [new SmactorIO task](https://github.com/leonbreukelman/richard-router/issues/new?template=smactorio-task.yml) to request maintainer triage for a bounded low-risk task. The tracked source is `.github/ISSUE_TEMPLATE/smactorio-task.yml`; see the [SmactorIO task form](.github/ISSUE_TEMPLATE/smactorio-task.yml) when reviewing changes to the form itself.

The form applies only `smactorio`. It does not authorize autonomous pickup.

### Exact filing path for maintainer coding agents

The browser form is the normal path for public contributors and their agents because it can apply `smactorio` without granting them repository label permissions.

A maintainer-authorized coding agent with repository triage permission may instead use GitHub CLI. Its completed body file must contain the same required sections as the browser form:

- owner or user outcome;
- current behavior and evidence;
- acceptance criteria;
- expected file scope;
- test plan; and
- safety and triage confirmations covering every required checkbox in the form.

Replace the example title and body path, then create the issue with only the intake label:

```bash
gh issue create \
  --repo leonbreukelman/richard-router \
  --title "[SmactorIO] Replace with the observable outcome" \
  --body-file /absolute/path/to/completed-smactorio-request.md \
  --label smactorio
```

Use the issue number returned by GitHub and read the complete issue back before authorization:

```bash
ISSUE_NUMBER=123
gh issue view "$ISSUE_NUMBER" \
  --repo leonbreukelman/richard-router \
  --json number,state,title,body,labels
```

Confirm that the issue is open, every required body section is complete, all safety and triage confirmations are present, and the task meets the criteria below.

A maintainer adds `autonomy:ready` and `risk:low` after confirming that the issue is:

- open;
- bounded to one objectively testable repository outcome;
- reversible and low-risk;
- clear about acceptance criteria, expected files, and tests; and
- inside the current autonomous path boundary.

The following command is maintainer-only, requires repository triage permission, and must never run during issue creation:

```bash
gh issue edit "$ISSUE_NUMBER" \
  --repo leonbreukelman/richard-router \
  --add-label autonomy:ready \
  --add-label risk:low
```

Verify the final state and labels from GitHub:

```bash
gh issue view "$ISSUE_NUMBER" \
  --repo leonbreukelman/richard-router \
  --json state,labels \
  --jq '{state, labels: [.labels[].name]}'
```

The complete required label set is therefore:

- `smactorio`
- `autonomy:ready`
- `risk:low`

Necessary, not sufficient: those labels do not bypass issue-state, blocked-label, title, path, secret-scanning, independent-review, CI, or exact-head merge gates. Maintainers may decline, narrow, or re-triage any request.

### Work that must not enter autonomous pickup

SmactorIO will not intentionally claim work involving:

- production or deployment changes;
- credentials, secrets, authentication, 2FA, or account recovery;
- billing, spend, or payment;
- destructive or irreversible actions;
- branch-protection or workflow-governance changes;
- security/compliance judgment;
- strategic, product, or research decisions; or
- medium/high/production/strategic risk.

Do not put destructive, credential, billing, authentication, or branch-protection requests in the issue title. The issue body may state stop conditions so the worker knows when to stop.

### Blocking and lifecycle labels

These labels prevent or describe autonomous execution:

- `smactorio:claimed` — the runtime has claimed the issue;
- `smactorio:blocked` — execution is blocked;
- `smactorio:needs-attention` — an operator must inspect the issue;
- `smactorio:done` — the runtime completed the issue;
- `blocked`, `blocked:human`, `blocked:external`;
- `risk:medium`, `risk:high`, `risk:strategic`, `risk:production`, `risk:security-compliance`;
- `type:research`, `type:research-proposal`;
- `needs-human`, `needs:human`, `autonomy:blocked`.

The `smactorio:claimed`, `smactorio:blocked`, `smactorio:needs-attention`, and `smactorio:done` labels are runtime/operator-managed. Contributors and their agents must not add or remove them manually.

A blocked or needs-attention issue is requeued only by a maintainer after the underlying control-plane or issue defect is fixed and verified. Repaired issues are released one at a time and monitored to a terminal result.

## Autonomous path boundary

The current SmactorIO lane may change only:

- `richard_router/`
- `tests/`, except `tests/test_repository_guidance.py`
- `docs/`, except `docs/method/`
- `README.md`
- `config/router.example.yaml`

Everything else is human-controlled. Examples include `AGENTS.md`, `CONTRIBUTING.md`, `.github/`, `.gitmodules`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `docs/method/`, `tests/test_repository_guidance.py`, secret-bearing configuration, and runtime artifacts. The repository-guidance test is a governance guardrail; changing or weakening it requires explicit human justification.

A normal human-reviewed pull request may propose a human-controlled path change when it is explicitly justified. It is not eligible for autonomous SmactorIO implementation merely because it has the intake labels.

## Pull-request expectations

Every pull request should state:

- the owner/user outcome;
- the linked issue, if one exists;
- the exact changed scope;
- tests added or updated;
- local Ruff and pytest results;
- documentation or decision records changed;
- any human-controlled path touched and why; and
- remaining risk or unverified behavior.

The repository workflow is branch → local verification → pull request → `uv / ruff / pytest` → review → merge. Deployment and credential changes are separate operator-gated actions.
