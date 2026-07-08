# Verification

This directory holds evidence artifacts that prove or falsify status, spec, and completion claims.

Use it for:

- command output summaries and raw-log pointers;
- Opus/Fable/reviewer prompts and JSON;
- CI/API readbacks;
- audit ledgers;
- browser/screenshot metadata;
- install/deployment ledgers;
- generated proof files that should travel with the repo.

Rules:

- Status states the claim; verification stores the proof.
- Do not paste secrets, tokens, passwords, credential values, or connection strings. Redact accidental values as `[REDACTED]`.
- For huge logs or generated reports, store the bulky file under `reports/` or another repo-local generated area and put a summary plus path here.
- Prefer exact commands, exit codes, file paths, commit IDs, PR/check URLs, and reviewer model identity over narrative summaries.
