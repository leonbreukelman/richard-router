# richard-router initial status

Status: implemented and verified locally/live; public GitHub push pending.

Scope:
- Standalone OpenAI-compatible router for Hermes Agent.
- Virtual model: `coding`.
- Default upstream policy: NVIDIA `z-ai/glm-5.2` primary, OpenRouter `z-ai/glm-5.2` fallback.
- Hermes integration through a separate `routertest` profile, not the default profile.

Verification target:
- Fake-upstream tests prove model exposure, request rewrite, failover, non-failover on 400, tool passthrough, and secret redaction.
- Tiny live smoke proves configured upstream access with existing NVIDIA/OpenRouter credentials.
- Hermes one-shot through `routertest` proves the real profile can use `custom:richard-router` model `coding`.
