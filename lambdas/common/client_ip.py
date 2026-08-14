"""lambdas/common/client_ip.py — the ONE client-IP extraction helper.

Shipped in every function bundle (#781), so every IP-gated write path keys its
rate limit off the identical derivation.

#1221 — WHY THIS DOES NOT READ ``X-Forwarded-For``
==================================================

The previous implementation took the LAST ``X-Forwarded-For`` hop, on the stated
premise that "CloudFront appends the edge-observed viewer IP as the last entry;
every earlier entry is supplied by the client and is therefore spoofable."

**That premise is false on this distribution**, measured against the live edge on
2026-08-14 via ``/api/submit_finding`` (limit 3/hour, and its rate check runs before
the body parse, so a malformed body probes the limiter without writing anything):

    X-Forwarded-For: 203.0.113.77   ×5  →  400 400 400 429 429   (bucket armed)
    X-Forwarded-For: 198.51.100.42  ×2  →  400 400               (FRESH bucket)
    no header at all                ×5  →  400 400 400 429 429   (a third bucket)

If CloudFront appended a trailing hop, the second run would have shared the first
run's bucket and returned 429. It did not. Exactly one model fits all three runs:
**CloudFront forwards the client's ``X-Forwarded-For`` unchanged, adding its own only
when the header is absent** — so the last hop IS the caller's chosen value. No choice
of hop index fixes this; the header is attacker-controlled in every position.

The consequence was that every IP-gated write (subscribe, votes, follows, nudges,
checkins, board_ask) could be evaded by rotating one header, which is what #1221 has
described since 2026-07-16 — including the whole period it sat closed, "fixed" by
flipping first-hop→last-hop and guarded by a unit test whose fixture hand-built the
appended chain this distribution never produces (docs/CONVENTIONS.md §9a).

THE TRUSTWORTHY SOURCE
----------------------

``CloudFront-Viewer-Address`` is set by CloudFront itself from the TCP peer address
and cannot be influenced by the client. It reaches the origin only when an origin
request policy forwarding it is attached to the ``/api/*`` cache behaviours — an
**owner-run infrastructure change** that is the other half of #1221.

Until that policy is attached this falls back to ``requestContext…sourceIp`` (the
CloudFront edge address for the API-Gateway/Function-URL path). That is coarser —
readers sharing a POP can collapse into one bucket — but it is NOT client-forgeable,
which is the property a rate limiter actually needs. ``client_ip_is_trusted()`` reports
which source was used so the degraded window is observable rather than silent.
"""

_VIEWER_ADDRESS_HEADER = "cloudfront-viewer-address"


def _headers(event: dict) -> dict:
    return {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}


def _strip_port(raw: str) -> str:
    """``CloudFront-Viewer-Address`` is ``address:port`` — for IPv4 and IPv6 alike.

    IPv6 makes this genuinely ambiguous unbracketed: ``2001:db8::1`` is a complete
    address, while ``2001:db8::1:16225`` is that address plus a port, and they differ
    only by whether the last group is meant as a port. Splitting on the last colon
    unconditionally turns a bare IPv6 address into the garbage ``2001:db8:``, so parse
    rather than guess — try the whole value as an address FIRST, and only strip a
    trailing ``:digits`` when doing so leaves something that actually parses.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("["):  # bracketed IPv6, e.g. [2001:db8::1]:443
        host, _, _rest = raw.partition("]")
        return host.lstrip("[").strip()

    head, sep, tail = raw.rpartition(":")
    if not sep or not tail.isdigit():
        return raw  # no port to strip (a bare IPv4, or an unexpected shape)

    # STRIP FIRST, then validate — and keep the original if stripping broke it.
    # Stripping must win when both readings are legal, because `2001:db8::1:5000` is
    # simultaneously a valid address AND that address plus port 5000. A viewer's
    # ephemeral port changes per connection, so keeping it would mint a fresh
    # rate-limit bucket for every request — defeating the limiter as thoroughly as
    # the forgeable header this replaces. Identity stability beats address purity.
    candidate = head.strip()
    try:
        import ipaddress

        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        # Stripping produced nonsense (`2001:db8::1` → `2001:db8:`), so the value was
        # a bare address after all. CloudFront always sends a port, so this is defence
        # against a shape we do not expect rather than a case we have observed.
        return raw
    except Exception:  # pragma: no cover — never let identity derivation raise
        return candidate or raw


def _source_ip(event: dict) -> str:
    ctx = event.get("requestContext") or {}
    http = ctx.get("http") or {}
    identity = ctx.get("identity") or {}
    return (http.get("sourceIp") or identity.get("sourceIp") or "").strip()


def client_ip_is_trusted(event: dict) -> bool:
    """True when the derived identity came from the un-forgeable CloudFront header.

    False means the origin request policy is not (yet) forwarding
    ``CloudFront-Viewer-Address`` and the coarser ``sourceIp`` fallback is in use.
    Callers can emit this so the degraded window is visible instead of silent —
    "reported green while guarding nothing" is the failure mode #1221 itself was.
    """
    return bool(_strip_port(_headers(event).get(_VIEWER_ADDRESS_HEADER) or ""))


def extract_client_ip(event: dict, default: str = "unknown") -> str:
    """Return a rate-limiting identity the caller cannot choose.

    Order: ``CloudFront-Viewer-Address`` (trustworthy, per-viewer) → ``sourceIp``
    (coarser, still un-forgeable) → ``default``.

    ``X-Forwarded-For`` is deliberately NOT consulted in any position. See the module
    docstring for the live measurement showing the client controls its last hop here.
    """
    viewer = _strip_port(_headers(event).get(_VIEWER_ADDRESS_HEADER) or "")
    if viewer:
        return viewer
    return _source_ip(event) or default
