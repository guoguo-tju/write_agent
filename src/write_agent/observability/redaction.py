"""
可观测负载脱敏。
"""
from __future__ import annotations

import hashlib
from typing import Any


SENSITIVE_KEYS = {
    "source_article",
    "final_content",
    "content",
    "prompt",
    "style_description",
    "review_feedback",
    "authorization",
    "api_key",
    "token",
    "openai_api_key",
    "github_token",
}


def _text_digest(value: str) -> dict[str, Any]:
    normalized = value or ""
    return {
        "len": len(normalized),
        "sha256_12": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
        "preview": normalized[:80],
    }


def redact_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in SENSITIVE_KEYS:
                if isinstance(item, str):
                    output[key] = _text_digest(item)
                else:
                    output[key] = {"redacted": True, "type": type(item).__name__}
                continue
            output[key] = redact_payload(item)
        return output
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str) and len(value) > 2048:
        return _text_digest(value)
    return value
