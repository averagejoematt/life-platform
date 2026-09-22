"""progress_access.py — the gate on the private progress-photo viewer (#3760, epic #3743).

WHAT THIS IS

The viewing half of #3743, and only its LOCK. `progress_capture` puts the photos into
`raw/matthew/progress_photos/`; `web/progress_viewer_lambda` renders them. This module owns the
one question both of those avoid asking twice: *is the person on the other end Matthew?*

The site is static bytes on CloudFront over a PUBLIC repo. Nothing shipped to a browser can
be a secret, so a JS password prompt would be theatre — the check would run on the attacker's
machine, against a comparison string they can read in git. The owner's ask was "a password or
a token you send me, whatever is easiest". This is the token: the bot texts him a link, the
link is exchanged ONCE for a signed cookie, and every later request proves itself with the
cookie. The only secret is an HMAC key in Secrets Manager that never leaves the account.

THE TWO CREDENTIALS, AND WHY THEY ARE NOT ONE

  * **The link token** (`k=` in the URL). Long-lived enough to survive a phone that is face
    down for a day (24h, `LINK_TTL_S`), and **single-use**. A URL is the leakiest credential
    shape there is — it lands in Telegram's servers, the browser's history, and the Referer
    header of anything the page ever links to. Single-use means the copy in all of those
    places is already spent by the time anyone else reads it.
  * **The session cookie**. Short-lived (12h, `SESSION_TTL_S`), `HttpOnly`, `Secure`,
    `SameSite=Lax`, scoped to the viewer path. Never appears in a URL, so it never leaks the
    way the link does, and a stolen one dies the same day.

Both are HMAC-SHA256 over the SAME key with **different domain prefixes** (`link:` / `sess:`).
That separation is load-bearing: without it a link token's signature would verify as a session
cookie, and "one use, 24 hours" would quietly become "unlimited, forever".

WHERE THE ONE-TIME-NESS ACTUALLY LIVES

Not in the token. A signature cannot know it has been used before; only storage can. The nonce
inside the token is written to DynamoDB under `PROGRESS_LINK#<nonce>` with
`attribute_not_exists(pk)`, so the FIRST redemption wins the conditional put and every later
one loses it — an atomic decision at the one place that can make it, with a TTL row that
disappears on its own after the token would have expired anyway.

`consume_nonce` **fails closed on every error**, not just on the condition failure. A DynamoDB
outage during an auth check is not a reason to hand out a session; the failure mode of an
unavailable viewer is that he tries again in a minute, and the failure mode of the other choice
is an unbounded replay window that nothing logs.

PURE, INJECTED, NO CLOCK OF ITS OWN

No boto3 client, no `time.time()`, no environment read happens in this module's verification
path — the caller passes `now` and `table`. That is what makes expiry, tamper and replay all
testable with no AWS and no sleeping, which is the only way a gate like this is ever actually
exercised rather than assumed.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets as _secrets
from typing import Optional

logger = logging.getLogger(__name__)

#: Secrets Manager id of the HMAC key. One key, this purpose only — never derived from, and
#: never shared with, the telegram bot token or the subscriber/ritual signing keys (a key that
#: signs two things lets either one forge the other).
DEFAULT_SECRET_NAME = "life-platform/progress-photos-signing"  # noqa: S105 — a secret NAME, not a credential
SECRET_NAME_ENV = "PROGRESS_SIGNING_SECRET_NAME"  # noqa: S105 — an env-var name, not a credential

#: The viewer's path. Not in any nav, sitemap, RSS or redirects map — see
#: `tests/test_progress_viewer_privacy_3760.py`, which is what keeps that true.
VIEWER_PATH = "/progress-photos/"

COOKIE_NAME = "__lp_progress"

LINK_TTL_S = 24 * 3600  # docs/DATA_GOVERNANCE.md's "24-hour signed link"
SESSION_TTL_S = 12 * 3600
PRESIGN_TTL_S = 600  # ...and its "10-minute presigned GETs"

#: The one-time nonce partition. SYSTEM_STATE in `experiment/phase_taxonomy.py` — TTL'd auth
#: exhaust like `OAUTH#`/`BOARDSESS#`, never experiment data.
LINK_PK_PREFIX = "PROGRESS_LINK#"
LINK_SK = "LINK"

_TOKEN_V = "1"  # noqa: S105 — the token FORMAT version, not a token
_SIG_LEN = 32  # hex chars of a truncated SHA-256 — the `ritual_link` precedent
_NONCE_RE = re.compile(r"^[0-9a-f]{8,64}$")

#: `/progress view` — the text command that mints a link. Anchored at both ends for the same
#: reason `progress_capture.CAPTION_RE` is: a message that merely mentions the words is a
#: message, not a command.
VIEW_COMMAND_RE = re.compile(r"^/progress\s+view\s*$", re.IGNORECASE)


# ── the primitive ─────────────────────────────────────────────────────────────
def _sign(secret: str, payload: str) -> str:
    return hmac.new(str(secret).encode(), payload.encode(), digestmod="sha256").hexdigest()[:_SIG_LEN]


def is_view_command(text: str) -> bool:
    """True for `/progress view` (and nothing else)."""
    return bool(VIEW_COMMAND_RE.match(" ".join(str(text or "").split())))


# ── the link token ────────────────────────────────────────────────────────────
def mint_link_token(secret: str, *, now: float, ttl_s: int = LINK_TTL_S, nonce: Optional[str] = None) -> str:
    """`1.<exp>.<nonce>.<sig>` — the one-time credential the bot texts him.

    `nonce` is injectable for tests only; in production it is 128 bits from
    `secrets.token_hex`, which is the part that makes a token unguessable rather than
    merely unforgeable.
    """
    n = nonce or _secrets.token_hex(16)
    exp = int(now) + int(ttl_s)
    return f"{_TOKEN_V}.{exp}.{n}.{_sign(secret, f'link:{exp}:{n}')}"


def verify_link_token(secret: str, token: str, *, now: float) -> tuple:
    """`(ok, reason, nonce)`. Never raises, never says WHY to the caller's caller.

    The reason string is for the log. What the browser gets back is one 401 with one body,
    whatever went wrong — a response that distinguishes "expired" from "bad signature" is an
    oracle, the same reasoning `telegram_gateway.silent_ok` documents.
    """
    parts = str(token or "").split(".")
    if len(parts) != 4 or parts[0] != _TOKEN_V:
        return (False, "malformed", None)
    _, exp_s, nonce, sig = parts
    if not _NONCE_RE.match(nonce or "") or len(sig or "") != _SIG_LEN:
        return (False, "malformed", None)
    try:
        exp = int(exp_s)
    except (TypeError, ValueError):
        return (False, "malformed", None)
    # Signature BEFORE expiry: an unsigned token is not "expired", it is forged, and an
    # expiry check on attacker-supplied bytes would be reading a number nobody vouched for.
    if not hmac.compare_digest(sig, _sign(secret, f"link:{exp}:{nonce}")):
        return (False, "bad signature", None)
    if float(now) >= exp:
        return (False, "expired", nonce)
    return (True, "ok", nonce)


def consume_nonce(table, nonce: str, *, now: float, ttl_s: int = LINK_TTL_S) -> bool:
    """Burn a link token's nonce. True only for the FIRST caller; False forever after.

    Fails CLOSED on any error (see module docstring). The TTL is the token's own horizon
    plus an hour of slack, so the row outlives every request that could still present the
    token and no longer.
    """
    if not nonce:
        return False
    try:
        table.put_item(
            Item={
                "pk": f"{LINK_PK_PREFIX}{nonce}",
                "sk": LINK_SK,
                "redeemed_at": int(now),
                "ttl": int(now) + int(ttl_s) + 3600,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — fail closed on ConditionalCheckFailed AND on outages
        code = ""
        try:
            code = (getattr(e, "response", {}) or {}).get("Error", {}).get("Code", "")
        except Exception:  # noqa: BLE001
            code = ""
        if code == "ConditionalCheckFailedException":
            logger.warning("[progress] link token replayed — refusing")
        else:
            logger.warning("[progress] nonce write failed (%s) — refusing, fail closed", type(e).__name__)
        return False


def link_url(base_url: str, token: str) -> str:
    """The full https URL he taps."""
    return f"{str(base_url).rstrip('/')}{VIEWER_PATH}?k={token}"


# ── the session cookie ────────────────────────────────────────────────────────
def sign_session(secret: str, *, now: float, ttl_s: int = SESSION_TTL_S) -> str:
    exp = int(now) + int(ttl_s)
    return f"{_TOKEN_V}.{exp}.{_sign(secret, f'sess:{exp}')}"


def verify_session(secret: str, value: str, *, now: float) -> tuple:
    """`(ok, reason)` for a session cookie value."""
    parts = str(value or "").split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_V:
        return (False, "malformed")
    _, exp_s, sig = parts
    if len(sig or "") != _SIG_LEN:
        return (False, "malformed")
    try:
        exp = int(exp_s)
    except (TypeError, ValueError):
        return (False, "malformed")
    if not hmac.compare_digest(sig, _sign(secret, f"sess:{exp}")):
        return (False, "bad signature")
    if float(now) >= exp:
        return (False, "expired")
    return (True, "ok")


def cookie_attributes(value: str, *, ttl_s: int = SESSION_TTL_S) -> str:
    """The `Set-Cookie` value.

    `HttpOnly` (no script on any origin can read it), `Secure` (never crosses plain HTTP),
    `SameSite=Lax` (survives the tap from Telegram, which is a top-level GET, while refusing
    to ride a cross-site POST), and `Path` scoped to the viewer so it is not attached to the
    ~134 public `/api/*` requests every other page makes.
    """
    return f"{COOKIE_NAME}={value}; Path={VIEWER_PATH}; Max-Age={int(ttl_s)}; HttpOnly; Secure; SameSite=Lax"


def cookie_from_header(header_value: str, name: str = COOKIE_NAME) -> Optional[str]:
    """Read one cookie out of a raw `Cookie:` header, or None.

    Hand-parsed rather than via `http.cookies`, which is lenient about malformed input in
    ways that are fine for a browser and wrong for an auth check.
    """
    for chunk in str(header_value or "").split(";"):
        k, _, v = chunk.strip().partition("=")
        if k == name:
            return v.strip().strip('"') or None
    return None
