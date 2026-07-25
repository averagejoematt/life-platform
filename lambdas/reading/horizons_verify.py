"""horizons_verify.py — the Horizons link-verification gate (#1705, epic #1686 S1).

Load-bearing safety rule (ADR-104: no fabricated / unresolvable links). Before a
Horizons pick is ever stored as publishable, its URL is fetched and confirmed to
resolve to *real content* — a 2xx response with a non-trivial body. Anything else
(non-http scheme, 4xx/5xx, empty body, timeout, DNS failure, any exception) is
**rejected — fail-closed**. A pick that does not verify is never stored.

Repo rule: HTTP is stdlib `urllib` only — no requests / httpx. The actual fetch
is injected via `fetcher` so the gate is unit-testable offline (a resolving stub
AND a dead one) without touching the network. The default fetcher is a thin
`urllib.request` GET that reads a small prefix of the body.

`verify_url` is pure-ish: given a `fetcher`, it has no I/O of its own and never
raises — it always returns a verdict dict.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger()

# A 2xx with fewer than this many bytes of body is treated as an empty/error
# shell (parked domains, blank error pages) → rejected.
MIN_CONTENT_BYTES = 64
# How much of the body we read to judge "real content" — we never need the whole
# page, just enough to know it isn't empty.
_READ_BYTES = 4096
_DEFAULT_TIMEOUT = 6.0
# A plausible desktop UA — some outlets 403 the default python-urllib agent.
_UA = "Mozilla/5.0 (compatible; AverageJoeMattHorizons/1.0; +https://averagejoematt.com)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _urllib_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    """Default fetcher: stdlib urllib GET → (status_code, body_prefix_bytes).

    Reads at most `_READ_BYTES`. Raises on any network / protocol error (the
    caller turns every exception into a fail-closed rejection).
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — scheme is validated before this call
        status = getattr(resp, "status", None) or resp.getcode() or 0
        body = resp.read(_READ_BYTES) or b""
    return int(status), body


def verify_url(url: str, *, fetcher=None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Fetch `url` and return a verdict. NEVER raises.

    Returns:
        {
          "verified": bool,      # True only on a 2xx + real content
          "status": int | None,  # HTTP status (None if the fetch never landed)
          "url": str,            # the URL we checked
          "reason": str,         # human-readable disposition
          "checkedAt": iso8601,  # when we checked
        }

    Fail-closed: a non-http(s) scheme, a non-2xx status, an empty/too-small body,
    a timeout, or ANY exception → verified=False.
    """
    verdict = {"verified": False, "status": None, "url": url, "reason": "", "checkedAt": _now_iso()}

    if not url or not isinstance(url, str):
        verdict["reason"] = "empty or non-string url"
        return verdict

    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme not in ("http", "https"):
        verdict["reason"] = f"unsupported scheme {scheme!r} (only http/https)"
        return verdict

    fetch = fetcher or _urllib_fetch
    try:
        status, body = fetch(url, timeout)
    except urllib.error.HTTPError as e:  # a landed-but-error response (404, 403, 500…)
        verdict["status"] = int(getattr(e, "code", 0) or 0)
        verdict["reason"] = f"http error {verdict['status']}"
        return verdict
    except Exception as e:  # noqa: BLE001 — timeout / DNS / reset / anything → fail-closed
        verdict["reason"] = f"fetch failed ({type(e).__name__})"
        logger.info("[horizons_verify] fetch failed for %s (%s) — rejecting fail-closed", url, type(e).__name__)
        return verdict

    verdict["status"] = int(status) if status is not None else None
    if verdict["status"] is None or not (200 <= verdict["status"] < 300):
        verdict["reason"] = f"non-2xx status {verdict['status']}"
        return verdict

    content_len = len((body or b"").strip())
    if content_len < MIN_CONTENT_BYTES:
        verdict["reason"] = f"body too small ({content_len} bytes) — treated as empty/error page"
        return verdict

    verdict["verified"] = True
    verdict["reason"] = f"resolved: {verdict['status']}, {content_len}+ bytes of content"
    return verdict
