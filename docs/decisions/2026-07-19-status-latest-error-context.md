# Decision: Expose latest pool error context explicitly

Date: 2026-07-19
Status: accepted

## Context

The pool snapshot exposes aggregate `errors_by_code` and `errors_by_type` maps together with the
latest error message. Map serialization order does not represent event order, so the status CLI
cannot reliably pair a code or type from those maps with the latest message.

## Decision

Add nullable `latest_error_code` and `latest_error_type` fields to each pool member in the status
JSON. Update both fields on every failure so they describe that same event, and clear both when the
existing recovery behavior clears the other current-error fields. Keep the aggregate maps and all
existing JSON fields unchanged.

The status CLI uses these explicit fields when present. It retains its aggregate-map fallback for
responses from older router versions, and selects Last Active by comparing `last_ok` and
`last_error`.

## Rationale

Explicit event fields make rendering deterministic without changing the purpose or shape of the
aggregate counters. Additive nullable fields preserve compatibility for existing JSON consumers,
while the CLI fallback allows mixed-version operation.

## Alternatives considered

- Infer recency from map order — rejected because map order is serialization order, not event order.
- Replace the aggregate maps with a latest-error object — rejected because it would remove existing
  counters and break consumers.
- Remove the old-server CLI fallback — rejected because it would make the CLI less tolerant during
  rolling upgrades.

## Consequences

Pool payloads gain two optional-value fields per member. New CLIs render current router payloads
consistently; old router payloads remain renderable with their previous best-effort behavior.
Virtual-model grouping and aggregate counter behavior are unchanged.

## Evidence

- `tests/test_metrics.py`
- `tests/test_pool_endpoint.py`
- `uv run ruff check .`
- `uv run pytest -v`

## Supersession

- Supersedes: none
- Superseded by: none
