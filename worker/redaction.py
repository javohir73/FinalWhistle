"""Credential scrubbing shared by the log path and the raw-store path."""

from __future__ import annotations

import re

#: Two shapes, because the naive one misses the common case. Matching only
#: `key: value` turns "Authorization: Bearer sk-live-9f3a" into
#: "Authorization: [REDACTED] sk-live-9f3a" -- the label is hidden and the
#: secret survives. The scheme word is consumed with the value.
_SECRET_TEXT = re.compile(
    r"(?P<label>\b(?:authorization|api[-_ ]?key|apikey|secret|token|password)\b)"
    r"(?P<sep>\s*[:=]\s*)(?:bearer\s+)?[^\s,;)]+"
    r"|\bbearer\s+[^\s,;)]+",
    re.IGNORECASE,
)


def _replace(match: re.Match) -> str:
    label = match.group("label")
    if label is None:
        return "[REDACTED]"
    return f"{label}{match.group('sep')}[REDACTED]"


def redact(message: str) -> str:
    """Strip anything that looks like a credential out of a string."""
    return _SECRET_TEXT.sub(_replace, message)
