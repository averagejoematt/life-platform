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

WHY ``X-Forwarded-For`` IS STILL THE SECOND CHOICE (2026-08-14, measured)
------------------------------------------------------------------------

The first cut of this fix dropped ``X-Forwarded-For`` entirely and fell straight back
to ``requestContext…sourceIp``, on the reasoning that it is coarser but un-forgeable.
Deployed and re-measured, that was **worse**, because ``sourceIp`` is the CloudFront
*edge* address and it is not stable per viewer:

    no XFF header, 6 requests, limit 3/hour  ->  400 429 400 400 400 400

One 429 in six means the identity was changing between requests, so nearly every
request got a fresh bucket and the limiter stopped enforcing anything. The same signal
was already in #1221's body and was misread: ``site_api_ai_lambda``, keying on raw
``sourceIp``, produced *17 consecutive POSTs -> 0 x HTTP 429*. That was not a broken
limiter; it was ``sourceIp`` failing to be an identity at all.

So the order below is deliberate, and each step is the best available:

1. ``CloudFront-Viewer-Address`` — stable AND un-forgeable. The real fix. A forged
   ``X-Forwarded-For`` can never override it; that is the property this module exists
   to guarantee, and it is what makes the origin-request-policy change sufficient.
2. ``X-Forwarded-For`` last hop — **stable for real callers, forgeable by an attacker.**
   This is the pre-#1221 behaviour, kept ONLY as the interim. It enforces correctly
   against ordinary traffic, which the ``sourceIp`` fallback does not.
3. ``sourceIp`` — last resort when no header is present at all.

**The #1221 bypass is therefore still open until the origin request policy lands, and
that is a known, measured, deliberate interim rather than an oversight.** Step 2 is not
a regression to delete casually: removing it does not close the bypass (edge-address
churn hands out fresh buckets anyway) and it does break enforcement against real users.
``client_ip_is_trusted()`` reports whether step 1 was used, so the degraded window is
observable rather than silent.
"""

import logging
import uuid

_LOG = logging.getLogger(__name__)

_VIEWER_ADDRESS_HEADER = "cloudfront-viewer-address"


# #1221: the single bucket every caller collapses into when the trusted header is
# absent. A constant on purpose — anything derived from the request would be
# attacker-chosen, which is the bypass itself.
_FAIL_CLOSED_IDENTITY = "no-trusted-client-ip"

# #2932: the marker prefix for a minted per-request idempotency identity. Never a
# constant on its own — see extract_idempotency_identity for why the two failure
# directions are opposites.
_UNTRUSTED_IDENTITY_PREFIX = "untrusted-client"


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
    """Return the best available rate-limiting identity.

    Order: ``CloudFront-Viewer-Address`` (stable + un-forgeable) → ``X-Forwarded-For``
    last hop (stable for real callers, forgeable — the documented #1221 interim) →
    ``requestContext…sourceIp`` (unstable; last resort) → ``default``.

    The load-bearing guarantee: **a forged ``X-Forwarded-For`` can never override
    ``CloudFront-Viewer-Address``.** Once the origin request policy forwards that
    header, step 2 becomes unreachable and the bypass closes with no code change.
    See the module docstring for why step 2 outranks ``sourceIp`` (measured).
    """
    headers = _headers(event)

    viewer = _strip_port(headers.get(_VIEWER_ADDRESS_HEADER) or "")
    if viewer:
        return viewer

    # ── FAIL CLOSED (#1221 box 2, 2026-08-21) ────────────────────────────────
    # The interim that used to live here returned the last `X-Forwarded-For` hop.
    # That value is chosen by the caller, so rotating it minted a FRESH rate-limit
    # bucket every request — the bypass this issue is about. It was retained only
    # while `CloudFront-Viewer-Address` could not reach the origin.
    #
    # It can now. The origin request policies attached on 2026-08-21 forward it on
    # every /api/* behaviour, verified live: six POSTs with six DIFFERENT forged
    # X-Forwarded-For values were limited at exactly 3/hour (400 400 400 429 429 429),
    # where before every rotation reset the bucket.
    #
    # So absence no longer means "not deployed yet" — it means something is wrong
    # (a behaviour added without the policy, or the policy reverted). Returning an
    # attacker-chosen value in that state is strictly worse than returning nothing,
    # so every such caller collapses into ONE shared bucket.
    #
    # The trade-off, stated because it is real: if the header genuinely stops
    # arriving, legitimate callers share a single limit and IP-gated writes throttle
    # site-wide. That is the intended direction of failure for a security control,
    # and it is loud rather than silent — `client_ip_is_trusted()` returns False and
    # `site_api_ai_lambda.py:920` already reports it. `sourceIp` is deliberately NOT
    # used as a middle ground: measured 2026-08-14 it is the CloudFront edge address,
    # not stable per viewer, and gave almost no enforcement (6 requests against a
    # 3/hour limit -> 400 429 400 400 400 400).
    return _FAIL_CLOSED_IDENTITY


def extract_idempotency_identity(event: dict) -> str:
    """Identity for content-keyed IDEMPOTENCY ids — never for rate limiting.

    Same first choice as ``extract_client_ip``: the un-forgeable
    ``CloudFront-Viewer-Address``. The FAILURE direction is deliberately the
    OPPOSITE (#2932), because the two callers of this module need opposite things
    from a missing identity:

    * A **rate limiter** wants every identity-less caller in ONE bucket — a shared
      limit is a safe failure (requests throttle site-wide, loudly). That is
      ``extract_client_ip``'s fail-closed sentinel.
    * An **idempotency key** wants them APART. The capture doors derive their id as
      ``sha256(f"{ip_hash}:{content}")`` and guard the write with
      ``attribute_not_exists`` / same-key overwrite — so under the shared sentinel,
      two DIFFERENT readers submitting the same words derive the same id and the
      second submission is silently swallowed as a "duplicate" that never reaches
      moderation. That is silent data loss, and it is invisible: a swallowed
      submission is indistinguishable from a genuine retry.

    So when no trusted identity exists this returns a per-request UNIQUE value.
    Dedup degrades — a same-reader retry may mint a second moderation row, which is
    VISIBLE and costs one duplicate review — instead of a stranger's submission
    being lost, which is invisible and costs the submission. The degradation is
    logged loudly below; ``client_ip_is_trusted()`` remains the programmatic probe.

    If this warning ever appears in production, a ``/api/*`` behaviour has stopped
    forwarding ``CloudFront-Viewer-Address`` (the origin-request-policy coupling —
    see ``cdk/stacks/web_cloudfront_policies.py`` and the derived guard in
    ``tests/test_capture_door_untrusted_identity_2932.py``).
    """
    viewer = _strip_port(_headers(event).get(_VIEWER_ADDRESS_HEADER) or "")
    if viewer:
        return viewer

    nonce = uuid.uuid4().hex
    _LOG.warning(
        "[client_ip #2932] no trusted client identity (CloudFront-Viewer-Address absent) — "
        "minting per-request idempotency identity %s…: content dedup is OFF for this request, "
        "so distinct readers cannot be silently collapsed onto one submission. If this logs in "
        "production, a /api/* behaviour has stopped forwarding the header (origin request policy, "
        "cdk/stacks/web_cloudfront_policies.py).",
        nonce[:8],
    )
    return f"{_UNTRUSTED_IDENTITY_PREFIX}:{nonce}"
