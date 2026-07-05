"""
budget_guard.py — read the budget tier and gate AI features (graceful degradation).

The cost_governor Lambda writes a tier (0-3) to SSM /life-platform/budget-tier
based on near-real-time spend vs the $75/mo ceiling. AI features call allow()
to decide whether to run or degrade; bedrock_client.invoke() calls current_tier()
as the Tier-3 hard backstop.

Tiers (cumulative — higher tier disables more):
  0 Normal    everything runs
  1 Caution   heavy DAILY coach AI off (narrative/ensemble); weekly flagship
              content (chronicle + the Friday Panel podcast) keeps running —
              it's ~$1/wk and is the product, so it survives until tier 2.
  2 Restrict  + chronicle off (matches the Panel's own SKIP_TIER=2, so the two
              stay in lockstep). The PUBLIC ask endpoints keep answering —
              readers degrade LAST (ADR-100): a reader question costs ~$0.02
              at worst and it's the platform's most differentiating hook.
  3 Hard stop + ALL Bedrock off (incl. /api/ask + /api/board_ask, which return
              an honest friendly 'paused' message); daily brief is data-only

Fail-open: if SSM is unreadable (transient error, missing grant, param absent)
we return tier 0 — a monitoring blip must never take AI down. The AWS Budgets
notifications are the backstop for that rare window.

This module is part of the shared Lambda layer.
"""

import os
import time

import boto3

_SSM_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
_REGION = os.environ.get("AWS_REGION", "us-west-2")
_CACHE_TTL_S = 300  # 5 min — matches the governor's hourly cadence well enough

# feature → tier at which it becomes DISABLED (current_tier >= cutoff → blocked)
_FEATURE_CUTOFF = {
    "coach_narrative": 1,
    "ensemble": 1,
    # chronicle_editor (#548): Margaret Calloway's critique + revision pass over
    # the chronicle draft. A narrative embellishment, not the flagship content
    # itself — pauses at the same mild tier as coach_narrative/Elena's state
    # extraction, well before "chronicle" (cutoff 2) takes the whole installment
    # down. A paused pass just means Elena's own draft ships unedited.
    "chronicle_editor": 1,
    # #552: the weekly "State of Matthew" brief's one Haiku narration call — same
    # cutoff as coach_narrative/ensemble per the issue's explicit budget line
    # ("+1 Haiku call/week, tier-1 paused"). A pause still produces a full record;
    # narrate() falls back to a deterministic templated narrative.
    "state_of_matthew": 1,
    # chronicle: was 1 (paused at the mildest budget state, which silently starved
    # the Friday Panel podcast — its only input is the weekly chronicle). Raised to
    # 2 so the flagship weekly Story+podcast survives tier 1, in lockstep with the
    # Panel lambda's own SKIP_TIER=2. Weekly Bedrock cost is ~$1 — negligible vs $75.
    "chronicle": 2,
    # website_ai: was 2 — the budget defense switched off the PUBLIC ask
    # endpoints while internal content kept running, making the reader-facing
    # hook the first casualty of growth. ADR-100 inverts the sacrifice order:
    # readers degrade LAST. Rate limits (5/hr/IP) + Haiku pricing bound the
    # worst case; the tier-3 hard stop keeps its honest 'paused' message.
    "website_ai": 3,
    "daily_brief_ai": 3,
}

_HARD_STOP_TIER = 3

_cache = {"tier": 0, "ts": 0.0}
_ssm = None


class BudgetExceeded(RuntimeError):
    """Raised by the bedrock_client Tier-3 backstop when AI is fully paused."""


def _client():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm", region_name=_REGION)
    return _ssm


def current_tier() -> int:
    """Current budget tier (0-3), cached ~5 min. Fail-open to 0 on any error."""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL_S:
        return _cache["tier"]
    tier = 0
    try:
        tier = int(_client().get_parameter(Name=_SSM_PARAM)["Parameter"]["Value"])
    except Exception:
        tier = 0  # fail-open: never break AI on an SSM blip / missing param
    _cache["tier"] = tier
    _cache["ts"] = now
    return tier


def allow(feature: str) -> bool:
    """True if `feature` may run at the current tier. Unknown features are
    treated as hard-stop-only (cutoff 3)."""
    cutoff = _FEATURE_CUTOFF.get(feature, _HARD_STOP_TIER)
    return current_tier() < cutoff


def hard_stopped() -> bool:
    """True when all Bedrock calls must be refused (Tier 3)."""
    return current_tier() >= _HARD_STOP_TIER
