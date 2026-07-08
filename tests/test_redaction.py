from __future__ import annotations

from richard_router.redaction import redact, redact_text


def test_redacts_authorization_headers():
    assert redact({"Authorization": "Bearer secret-token-value-1234567890"}) == {
        "Authorization": "[REDACTED]"
    }


def test_redacts_secret_like_text():
    text = redact_text("key sk-or-v1-abcdefghijklmnopqrstuvwxyz012345")
    assert "sk-or-v1" not in text
    assert "[REDACTED]" in text
