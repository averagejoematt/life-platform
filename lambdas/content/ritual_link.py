"""lambdas/ritual_link.py — one-tap link signing for the evening ritual (#769, ADR-124).

The C floor of the fulfillment capture channel: `evening_nudge_lambda` mints two
tappable links per day (connection 0-4, mood valence 0-4); the site-api Lambda
verifies and writes the tap. Both lambdas ship this module in their own code
bundle (#781 — no shared layer, the whole `lambdas/` tree is staged per-function),
so mint and verify always agree with zero drift risk.

Signing follows the existing `_generate_subscriber_token` / `_validate_subscriber_token`
precedent in `lambdas/web/site_api_social.py` / `site_api_ai_lambda.py`: HMAC-SHA256
with a dedicated random secret in Secrets Manager (never derived from another
credential), truncated to 32 hex chars, verified with `hmac.compare_digest`. Unlike
the subscriber token this one has no expiry embedded in the payload — the (date,
metric, value) triple IS the payload, so a token is only ever valid for the exact
tap it was minted for; there is nothing to forge into a different value without the
secret. The site-api endpoint additionally windows how old `date` may be (see
`site_api_social._handle_ritual_log`) as defense in depth.
"""

import hmac

RITUAL_METRICS = (
    "connection",
    "mood_valence",
    "intake_count",
    # #1409: the weekly felt-reality probe (Sunday nudge only — see
    # evening_nudge_lambda). Three WHO-5/SVS-derived items, 0-4 ordinal,
    # ≤20s total; they land in SOURCE#felt_probe and feed the per-pillar
    # calibration card (/api/character_calibration).
    "felt_vitality",
    "felt_rest",
    "felt_connection",
    # #1408: the weekly 1-item Time-Affluence probe (Sunday nudge only). Single
    # 0-4 ordinal "this week: how much time did your week feel like your own?";
    # lands in SOURCE#time_affluence (its own partition, never evening_ritual),
    # feeding the deterministic proxy + the weekly hypothesis-engine edge test.
    "felt_time",
)
RITUAL_VALUE_MIN = 0
RITUAL_VALUE_MAX = 4

# #1405: metrics that persist to the Matthew-PRIVATE intake partition instead of
# the public-aggregated evening_ritual record. The oblique id is deliberate — the
# intake class is named only in private surfaces (nudge email, MCP, daily brief);
# no public payload, site file, or generated artifact may carry it
# (tests/test_intake_privacy_contract.py enforces both directions).
PRIVATE_RITUAL_METRICS = frozenset({"intake_count"})
PRIVATE_INTAKE_SOURCE = "private_intake"  # DDB: USER#matthew#SOURCE#private_intake / DATE#YYYY-MM-DD

# #1409: the weekly felt-reality probe metrics — routed to their own partition
# (never evening_ritual: the daily wellbeing aggregate must not mix cadences,
# and the calibration engine reads exactly one probe per week). Item values are
# Matthew-level self-report but NOT sensitive; the public read surface
# (/api/character_calibration) still serves aggregates only (r/CI/n_eff),
# following the ADR-124 C-floor posture.
WEEKLY_PROBE_METRICS = frozenset({"felt_vitality", "felt_rest", "felt_connection"})
FELT_PROBE_SOURCE = "felt_probe"  # DDB: USER#matthew#SOURCE#felt_probe / DATE#YYYY-MM-DD (the Sunday)

# #1408: the weekly Time-Affluence probe — same Sunday one-tap cadence as the felt
# probe, but routed to its OWN partition (the Time-Affluence proxy + edge test read
# exactly one probe per week and must not mix into the felt-reality calibration).
# A skipped week is a coverage gap in the proxy, never a 0 (ADR-104). Item value is
# Matthew-level self-report but NOT sensitive (no private-intake handling).
TIME_AFFLUENCE_PROBE_METRICS = frozenset({"felt_time"})
TIME_AFFLUENCE_SOURCE = "time_affluence"  # DDB: USER#matthew#SOURCE#time_affluence / DATE#YYYY-MM-DD (the Sunday)

# All metrics asked on the Sunday weekly-probe nudge, across partitions.
ALL_WEEKLY_PROBE_METRICS = WEEKLY_PROBE_METRICS | TIME_AFFLUENCE_PROBE_METRICS

# Probe item → character pillar it calibrates (character_engine pillar names).
# The four unmapped pillars render an honest "unprobed" state on the card.
PROBE_PILLAR_MAP = {
    "felt_rest": "sleep",
    "felt_vitality": "movement",
    "felt_connection": "relationships",
}


def sign_ritual_token(secret: str, date_str: str, metric: str, value: int) -> str:
    """Deterministic HMAC-SHA256 over (date, metric, value), truncated to 32 hex chars."""
    payload = f"{date_str}:{metric}:{value}"
    return hmac.new(secret.encode(), payload.encode(), digestmod="sha256").hexdigest()[:32]


def verify_ritual_token(secret: str, date_str: str, metric: str, value: int, token: str) -> bool:
    """Constant-time verification. False on any malformed input (never raises)."""
    if not token:
        return False
    try:
        expected = sign_ritual_token(secret, date_str, metric, value)
    except Exception:
        return False
    return hmac.compare_digest(token, expected)


# #4189: the morning note's OWNER token — the same signed-link secret, a per-PT-day
# payload. The note's four words are free text the owner types, so the token cannot
# sign the values (the ritual token's shape); it signs the DAY instead, which makes it
# the owner's write permission for exactly one morning. Anything holding the secret
# can mint it (the evening nudge already does for the ritual links; the site lane's
# Today box will carry it the same way). Nothing else on site-api authenticates the
# owner (#4207's finding), so this IS the existing owner check, extended by one payload.
MORNING_NOTE_SIGNING_SCOPE = "morning_note"


def sign_morning_note_token(secret: str, date_str: str) -> str:
    """Deterministic HMAC-SHA256 over (date, "morning_note"), truncated to 32 hex chars."""
    payload = f"{date_str}:{MORNING_NOTE_SIGNING_SCOPE}"
    return hmac.new(secret.encode(), payload.encode(), digestmod="sha256").hexdigest()[:32]


def morning_note_link(site_url: str, secret: str, date_str: str) -> str:
    """The owner's link to the cockpit's four-word box for `date_str`'s morning (#4189 box 3).

    The grant rides in the URL FRAGMENT (`#note=<day>.<token>`) — a browser never sends a
    fragment to the server, so the token never reaches a CloudFront log or a Referer, and
    `site/assets/js/morning_note_box.js` (the only reader of it) strips it from the address
    bar once read. That module's GRANT_RE is the other half of this format."""
    return f"{site_url.rstrip('/')}/cockpit/#note={date_str}.{sign_morning_note_token(secret, date_str)}"


def verify_morning_note_token(secret: str, date_str: str, token) -> bool:
    """Constant-time verification of the owner's per-day note token. False on any malformed input (never raises)."""
    if not token or not isinstance(token, str):
        return False
    try:
        expected = sign_morning_note_token(secret, date_str)
    except Exception:
        return False
    return hmac.compare_digest(token, expected)
