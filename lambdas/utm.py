"""Canonical UTM tagging + privacy-safe referrer normalization (#1621).

Two jobs, one module, because both are the same normalization problem seen from
opposite ends of the funnel:

  `with_utm()`  — the OUTBOUND half. One function that tags a link this platform
                  publishes, so no surface hand-types a `?utm_source=…` string and
                  no two surfaces spell the same campaign differently. Consumed by
                  the RSS builder and the chronicle share kit today; #1620 (footer
                  social links) consumes it rather than inventing its own.

  `referrer_host()` — the INBOUND half. The HTTP `Referer` header is a full URL and
                  can carry PII in its query string (a third party's own tracking
                  params, a search term, a session identifier). Per
                  docs/DATA_GOVERNANCE.md the subscriber partition is third-party
                  PII with an UNSIGNED retention policy, so anything written there
                  is written for keeps. We therefore retain the HOST ONLY, never the
                  path and never the query string.

The JS half of the outbound helper lives in the site's attribution module; the
normalization rules are kept identical on both sides so a link tagged in Python and
a capture parsed in the browser agree on the same token.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Mirrors the charset/length rule in the browser module: campaign tokens are machine
# identifiers, not prose. Anything outside the set is replaced rather than escaped,
# which keeps arbitrary content out of storage entirely.
MAX_LEN = 64
_DISALLOWED = re.compile(r"[^a-z0-9_.-]+")

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def normalize(value: str | None) -> str:
    """Normalize a UTM value to a safe machine token. Returns '' if nothing survives."""
    if not isinstance(value, str):
        return ""
    token = _DISALLOWED.sub("-", value.strip().lower()).strip("-")
    return token[:MAX_LEN]


def with_utm(url: str, source: str, medium: str, campaign: str | None = None) -> str:
    """Return `url` tagged with normalized utm params.

    Existing query params are preserved. A utm key already present on the input URL
    WINS — an already-tagged link is never rewritten, so calling this twice is
    idempotent and a hand-tagged link keeps its author's intent.
    """
    if not url or not isinstance(url, str):
        return url
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, raw in (("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign)):
        token = normalize(raw)
        if token and key not in query:
            query[key] = token
    return urlunparse(parts._replace(query=urlencode(query)))


def referrer_host(referrer: str | None) -> str:
    """Extract the bare host from a `Referer` header. Path and query are DISCARDED.

    Returns '' for anything unparseable, for a same-site referrer (which carries no
    acquisition signal — it is just internal navigation), and for a host that does not
    look like a hostname. Userinfo (`user:pass@host`) and port are stripped: neither is
    an acquisition signal and userinfo is credential material.
    """
    if not isinstance(referrer, str) or not referrer.strip():
        return ""
    try:
        parsed = urlparse(referrer.strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().strip(".")
    if not host or "." not in host:
        return ""
    if host == "averagejoematt.com" or host.endswith(".averagejoematt.com"):
        return ""
    if len(host) > MAX_LEN or _DISALLOWED.search(host):
        return ""
    return host
