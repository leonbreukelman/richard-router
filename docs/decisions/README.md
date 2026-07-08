# Decisions / ADRs

This directory holds durable decision records for product, architecture, API, config, path, deployment, and connector decisions future agents must not re-litigate.

Use `docs/decisions/YYYY-MM-DD-<slug>.md` with a short kebab-case slug.

Write or update a decision record when a change affects any of:

- architecture or component boundaries;
- public API, CLI, schema, or config behavior;
- protected, generated, security-sensitive, or externally consumed paths;
- external connector assumptions;
- deployment assumptions;
- long-lived product/project direction.

Before making a durable decision, read relevant prior records in this directory.

Tie-break:

- Product/architecture/API/config/path decisions go here.
- Method/scaffold/governance/lifecycle-mode rationale goes first in `docs/method/DESIGN-RECORD.md`.
- If one change is both, write the ADR here and cross-link it from `docs/method/DESIGN-RECORD.md`.

Do not store secret values in decision records. Use env-var names only and redact accidental values as `[REDACTED]`.
