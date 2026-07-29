"""One credential detector, shared by every path that handles venue strings.

Two jobs, deliberately in one module so they cannot drift apart:

* :func:`redact` scrubs a string that is about to be logged or stored.
* :func:`looks_like_credential` answers a different question -- may this string
  be used VERBATIM as a readable filename fragment? -- and is intentionally
  broader. A key like ``api_key_live_sk_1234`` contains no separator for
  :func:`redact` to find, so redaction leaves it whole; it still must never
  become a path.
"""

from __future__ import annotations

import re

_LABEL = r"(?:authorization|api[-_ ]?key|apikey|secret|token|password|passwd|credential)"

#: Scrubbing patterns, most specific first.
#:
#: The structured forms are not optional extras. A venue error commonly
#: arrives as a serialized body -- {"apiKey":"secret"} or {'api_key':'secret'}
#: -- where the separator is `":"` rather than `:` or `=`, so a pattern built
#: only for `key: value` walks straight past it.
_PATTERNS = (
    # {"apiKey": "secret"} / {'api_key':'secret'}
    re.compile(rf'(?P<pre>["\']{_LABEL}["\']\s*:\s*)(?P<q>["\'])[^"\']*(?P=q)',
               re.IGNORECASE),
    # Authorization: Bearer sk-live-xxx  |  api_key=xxx
    re.compile(rf"(?P<pre>\b{_LABEL}\b\s*[:=]\s*)(?:bearer\s+)?[^\s,;)\]}}\"']+",
               re.IGNORECASE),
    # bare "Bearer sk-live-xxx"
    re.compile(r"\bbearer\s+[^\s,;)\]}\"']+", re.IGNORECASE),
)

#: Anything containing one of these may not appear verbatim in a path, even
#: with no separator anywhere. Substring match, not word-boundary: the point
#: is `api_key_live_sk_1234` and `Bearer_xyz`.
_CREDENTIAL_MARKERS = (
    "authorization", "apikey", "api_key", "api-key", "secret", "token",
    "password", "passwd", "bearer", "credential", "sk_live", "sk-live",
    "sk_test", "sk-test",
)


def redact(message: str) -> str:
    """Scrub credential-looking values out of a string, keeping the label."""
    for pattern in _PATTERNS:
        message = pattern.sub(_replace, message)
    return message


def _replace(match: re.Match) -> str:
    groups = match.groupdict()
    prefix = groups.get("pre")
    if prefix is None:
        return "[REDACTED]"
    quote = groups.get("q")
    return f"{prefix}{quote}[REDACTED]{quote}" if quote else f"{prefix}[REDACTED]"


def looks_like_credential(text: str) -> bool:
    """Is this string unsafe to use verbatim as a readable path fragment?

    Broader than :func:`redact` on purpose. Redaction needs a separator to
    find a value; a filename needs no separator to leak one.
    """
    lowered = text.casefold()
    if any(marker in lowered for marker in _CREDENTIAL_MARKERS):
        return True
    return redact(text) != text
