# Method file topology — global core, local override

This scaffold has global method files, local project files, and local evidence artifacts. The split is what makes the method reusable: invariant files can be synced everywhere, while project facts and generated records stay local.

| File | Scope | Audience | Edited per repo? | Overwritten by sync? |
|---|---|---|---|---|
| `docs/method/METHOD.md` | Global invariant contract | Agent loads first | Never | Yes |
| `docs/method/PROJECT.md` | Local instantiation | Agent loads second | Yes | No, unless explicitly regenerated |
| `docs/method/DESIGN-RECORD.md` | Local method/scaffold/governance history | Operator + architect | As needed | No |
| `docs/specs/README.md` | Generic specs guidance | Spec authors | Rarely | Create-if-missing; force only |
| `docs/specs/TEMPLATE-track-*.md` | Global spec templates | Spec authors | Never | Yes |
| `docs/specs/YYYY-MM-DD-*.md` | Local turn specs | Agent per turn | New per turn | No |
| `docs/decisions/README.md` | Generic ADR guidance | Agents + maintainers | Rarely | Create-if-missing; force only |
| `docs/decisions/TEMPLATE-decision.md` | Generic ADR template | Decision authors | Rarely | Create-if-missing; force only |
| `docs/decisions/YYYY-MM-DD-*.md` | Local ADRs/decision records | Future agents + maintainers | New per decision | No |
| `docs/status/README.md` | Generic status guidance | Agents + maintainers | Rarely | Create-if-missing; force only |
| `docs/status/YYYY-MM-DD-*.md`, `docs/status/INDEX.md` | Local current state/progress | Operators + agents | As needed | No |
| `docs/verification/README.md` | Generic evidence guidance | Verifiers + reviewers | Rarely | Create-if-missing; force only |
| `docs/verification/*` | Local evidence artifacts | Verifiers + reviewers | New per run | No |

## Override rule

`PROJECT.md` may add constraints and fill slots. It may not loosen `METHOD.md`. If a repo needs a looser lifecycle, update the global method deliberately and record the rationale in `DESIGN-RECORD.md`.

## Documentation discipline

- Specs answer: what work is proposed or done?
- Decisions answer: what durable decision was made and why?
- Status answers: what is true right now or where did the multi-phase work stop?
- Verification answers: what proof backs the claim?
- Method design records answer: why did the scaffold/governance method change?

Status states claims. Verification stores proof. `AGENTS.md` is not a status log.

## AGENTS.md load hook

The installer adds this line exactly once:

`Before starting any task, load docs/method/METHOD.md then docs/method/PROJECT.md and treat both as binding.`

That hook is intentionally small. The skill using this scaffold must still read the two files before planning.

## Distribution

Preferred first install path:

```bash
python3 ~/.hermes/skills/software-development/repo-project-bootstrap/scripts/install_method_scaffold.py /path/to/repo --mode local-scaffold --json
```

`docs/method/sync-method.sh` is a self-contained update helper for repos that already contain the canonical layout. It preflights sources before writing and preserves existing local files.

By default, sync creates the docs guidance files if they are missing and preserves existing local copies. Use the Python installer's explicit docs-discipline force flag only when deliberately converging those fixed README/template files.

## Onboarding checklist

1. Run the installer in `--dry-run`.
2. Run the installer for real.
3. Read `docs/method/PROJECT.md` and fill/adjust any repo-specific open decisions.
4. Confirm AGENTS.md load hook exists exactly once.
5. First real work turn: write a dated spec under `docs/specs/` from Track L or Track F.
6. Write ADRs under `docs/decisions/` for durable product/architecture/API decisions.
7. Keep multi-phase progress under `docs/status/` and proof artifacts under `docs/verification/`.
8. If CI is absent, make adding CI a first follow-up before claiming `github-pr` governance.
