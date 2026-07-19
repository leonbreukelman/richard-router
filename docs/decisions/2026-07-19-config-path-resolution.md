# ADR: Explicit config paths are authoritative

Date: 2026-07-19
Status: accepted
Scope: router configuration path selection and startup diagnostics

## Context

The router historically replaced a missing `config/router.yaml` with
`config/router.example.yaml`. The resolver made that replacement based only on the
selected path string, so it could not distinguish an implicit default from the same
path explicitly supplied through `--config`, `ROUTER_CONFIG`, or
`RICHARD_ROUTER_CONFIG`. An operator could therefore request one file and unknowingly
start with example providers and weights.

## Decision

Paths supplied by the CLI or either supported environment variable are authoritative.
If an explicit path does not exist, configuration loading fails with an error naming
that path. The resolver never substitutes another file for it.

Retain the development convenience fallback only when no path was supplied. When the
default `config/router.yaml` is absent and `config/router.example.yaml` exists, the
resolver emits a warning that names the example file before using it.

Every successful resolution also emits an informational diagnostic naming the active
config path. Diagnostics may identify paths and environment-variable names, but must
not expose environment-variable values or config secret values.

Validation and runtime loading continue to use the same resolver so their path
selection cannot diverge.

## Consequences

- Explicitly configured deployments fail closed instead of starting from example
  routing policy.
- Source checkouts can still start without copying the example config, but the fallback
  is visible in logs.
- Operators can confirm the active config file from startup diagnostics.
- A missing implicit default fails with a path-specific error when no example file is
  available.
