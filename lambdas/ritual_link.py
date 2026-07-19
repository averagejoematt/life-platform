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
