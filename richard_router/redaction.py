from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"nvapi-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
]

SENSITIVE_KEYS = {"authorization", "api_key", "api-key", "x-api-key", "cookie", "set-cookie"}


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            key_lower = key_s.lower()
            if key_lower in SENSITIVE_KEYS or "token" in key_lower or "secret" in key_lower:
                out[key_s] = "[REDACTED]"
            else:
                out[key_s] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
