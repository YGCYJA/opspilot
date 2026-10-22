"""Best-effort redaction for exported reports; not a general secret scanner."""
from __future__ import annotations

import re


def redact(value: str) -> str:
    value = re.sub(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\Z)",
                   "[REDACTED PRIVATE KEY]", value, flags=re.S)
    value = re.sub(r"(?i)(\bauthorization[\"']?\s*[:=]\s*[\"']?)(?:Basic|Bearer|Digest|Token)\s+[^\s\"',;<>]+",
                   r"\1[REDACTED]", value)
    value = re.sub(r"(?i)bearer\s+[^\s\"',;]+", "Bearer [REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}", "[REDACTED]", value)
    value = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})", "[REDACTED]", value)
    value = re.sub(r"\bAKIA[A-Z0-9]{16}\b", "[REDACTED]", value)
    sensitive_name = r"[A-Za-z0-9_-]*(?:api[_-]?key|password|passwd|secret|access[_-]?token|authorization)[A-Za-z0-9_-]*"
    assignment = r"(?i)(\b(?:" + sensitive_name + r")[\"']?\s*[:=]\s*)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s\"',;<>]+)"
    return re.sub(assignment, r"\1[REDACTED]", value)


def redact_value(value, secrets: tuple[str, ...] = ()):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return redact(value)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, secrets) for key, item in value.items()}
    return value
