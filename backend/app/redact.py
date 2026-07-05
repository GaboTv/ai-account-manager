"""Secret redaction for logs, audit metadata, and persisted command output.

NOT applied to the live terminal stream shown to the session owner (they need
to see login URLs and device codes to complete auth). Applied to everything
that gets persisted or logged.
"""
import re

_PATTERNS = [
    # Anthropic / OpenAI style API keys and OAuth tokens
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    # OAuth authorization codes / tokens in URLs
    re.compile(r"([?&#](code|token|access_token|refresh_token|id_token)=)[^&\s\"']+", re.I),
    # Bearer headers
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I),
    # JWTs
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
]

REDACTED = "[REDACTED]"


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pat in _PATTERNS:
        # keep the named prefix group when present so logs stay readable
        text = pat.sub(
            lambda m: (m.group(1) + REDACTED) if m.lastindex else REDACTED, text
        )
    return text
