"""Remove configured credentials from diagnostics crossing process boundaries."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

_SECRET_NAME = re.compile(
    r"(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)(?:_|$)", re.I
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)


def redact_text(value: str) -> str:
    # Read at use time: worker/provider configuration may be installed after import.
    secrets: set[str] = set()
    for name, secret in os.environ.items():
        if _SECRET_NAME.search(name) and len(secret) >= 8:
            secrets.update((secret, quote(secret, safe="")))
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return _BEARER.sub("Bearer [REDACTED]", value)


def redact_diagnostic(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_diagnostic(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic(item) for item in value]
    return value
