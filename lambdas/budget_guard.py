"""
budget_guard.py — read the budget tier and gate AI features (graceful degradation).

The cost_governor Lambda writes a tier (0-3) to SSM /life-platform/budget-tier
based on near-real-time spend vs the monthly ceiling ($85 base since the
ADR-133 amendment 2026-07-08; floats to $100 in reader-traffic surge mode).
AI features call allow() to decide whether to run or degrade;
bedrock_client.invoke() calls current_tier() as the Tier-3 hard backstop.

Tiers (cumulative — higher tier disables more). The sacrifice order is by
AUDIENCE, not by cost: internal/dev AI dies first, reader-facing product last
(ADR-125). The June-2026 breach that motivated this was dev-session-caused, yet
tier 1 was pausing the coach narratives — the product's soul — while dev re-runs
kept spending. This ladder inverts that.

  0 Normal    everything runs
  1 Caution   INTERNAL / dev AI off — the coach-ensemble meta-digest, the
              coherence-sentinel semantic QA pass, and Margaret's chronicle
              embellishment pass. None of these is a reader-facing surface; each
              has a deterministic fallback. Nothing a reader reads pauses here.
  2 Restrict  + reader NARRATIVE content off — the daily coach commentary
              (coach_narrative), the weekly "State of Matthew" brief narration,
              and the weekly chronicle + Friday Panel podcast (chronicle stays in
              lockstep with the Panel's own SKIP_TIER=2). This is the first tier
              a reader can perceive, and it's the biggest recurring daily bucket,
              so it's the real cost lever — but it still outlives ALL internal AI.
  3 Hard stop + the two irreducible reader promises off: the PUBLIC ask
              endpoints (/api/ask + /api/board_ask — ADR-100's differentiating
              hook, ~$0.02/call, rate-limited) and the daily brief's AI. Both
              return honest 'paused' output; the brief falls back to data-only.
              These degrade LAST by design — a reader question and the morning
              brief are the platform's last two AI commitments to keep.

Fail-open: if SSM is unreadable (transient error, missing grant, param absent)
we return tier 0 — a monitoring blip must never take AI down. The AWS Budgets
notifications are the backstop for that rare window.

This module is bundled into every function's deploy package (#781 retired the shared Lambda layer).
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3

_SSM_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
# #822: the governor's projection breakdown (mtd / projected / ai + non-ai daily
# burn), persisted alongside the tier. Display-only — NEVER an input to
# allow()/current_tier(); a malformed or missing breakdown only costs the daily
# brief its headroom line, never AI enforcement.
_SSM_BREAKDOWN_PARAM = os.environ.get("BUDGET_BREAKDOWN_PARAM", "/life-platform/budget-breakdown")
_REGION = os.environ.get("AWS_REGION", "us-west-2")
_CACHE_TTL_S = 300  # 5 min — comfortably shorter than the governor's every-8h cadence
# A breakdown older than this is not worth showing (the governor runs every 8h,
# so ~6 consecutive missed runs) — stale burn rates mislead more than no line.
_BREAKDOWN_MAX_AGE_S = 48 * 3600

# feature → tier at which it becomes DISABLED (current_tier >= cutoff → blocked).
# Ordered by AUDIENCE band (ADR-125): internal (1) < reader-narrative (2) <
# irreducible-reader (3). Keep this map grouped by band — the band comments below
# are the contract, and tests/test_budget_guard_ladder.py pins the ordering.
_FEATURE_CUTOFF = {
    # ── Band 1: INTERNAL / dev AI — pauses FIRST. Nothing here is a surface a
    #    reader reads; each degrades to a deterministic fallback (ADR-125).
    #
    # ensemble (coach_ensemble_digest): the cross-coach agreement/disagreement
    # meta-synthesis. A derived analysis layer, not first-party coach voice; falls
    # back to a default digest when paused.
    "ensemble": 1,
    # chronicle_editor (#548): Margaret Calloway's critique + revision pass over
    # the chronicle draft — a narrative embellishment, not the content itself. A
    # paused pass just means Elena's own draft ships unedited.
    "chronicle_editor": 1,
    # coherence_semantic: the coherence sentinel's Haiku read on whether served
    # narratives cohere with the facts — the content analogue of the visual AI-QA,
    # advisory only (the DETERMINISTIC verdict is what alarms). Was UNLISTED, so it
    # defaulted to cutoff 3 and outlived every reader surface — the exact inversion
    # ADR-125 fixes. An internal QA pass must pause before any reader content.
    "coherence_semantic": 1,
    # reader_truth_qa (#1095/#1096): the phase-aware reader-truth judge — the CI
    # post-deploy prose pass (visual_qa --reader-truth) + the nightly qa_smoke
    # "Reader Truth" category. Internal QA like coherence_semantic: a paused run
    # is reported as an explicit skip (⏸/warning), never silent green.
    "reader_truth_qa": 1,
    # ── Band 2: reader NARRATIVE content — pauses only under real pressure, a full
    #    tier AFTER all internal AI. The biggest recurring daily bucket, so it's
    #    the real cost lever, but the reader product is never the first sacrifice.
    #
    # coach_narrative: the daily coach commentary — the product's soul. Was 1
    # (paused first, the defect ADR-125 corrects). Raised to 2 so it outlives every
    # internal/dev AI feature; still pauses before the two irreducible promises.
    "coach_narrative": 2,
    # state_of_matthew (#552): the weekly "State of Matthew" brief narration. Was 1;
    # raised to 2 with the rest of the reader narrative band. narrate() falls back
    # to a deterministic templated narrative when paused.
    "state_of_matthew": 2,
    # daily_debrief (#734): the daily ~2-minute "state of Matthew" audio briefing.
    # A reader-narrative surface that degrades to a deterministic template (still
    # publishes audio at $0 AI cost), so it pauses in lockstep with state_of_matthew
    # — after all internal AI, before the two irreducible reader promises.
    "daily_debrief": 2,
    # chronicle: the weekly Story installment + its Friday Panel podcast (the
    # podcast's only input). Kept at 2 in lockstep with the Panel lambda's own
    # SKIP_TIER=2. Weekly Bedrock cost is ~$1 — negligible vs the ceiling.
    "chronicle": 2,
    # ── Band 3: the two IRREDUCIBLE reader promises — pause LAST (ADR-100/125).
    #
    # website_ai: the PUBLIC /api/ask + /api/board_ask hook — the platform's most
    # differentiating surface. Rate limits (5/hr/IP) + Haiku pricing bound the
    # worst case; the tier-3 hard stop keeps its honest 'paused' message.
    "website_ai": 3,
    # daily_brief_ai: the 11 AM brief — "protect longest" by design. Falls back to
    # a data-only brief at tier 3.
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


# ── #822: budget-headroom readout (display-only) ──────────────────────────────
# The tier alone says WHAT is paused, not WHY there's no slack. The governor
# persists its projection breakdown; read_breakdown() + format_headroom_line()
# turn it into the daily brief's one-liner, e.g.:
#   Budget: tier 1 · projected $83 vs $75 ceiling · AI $1.79/day of the
#   $2.68/day burn — near-zero slack for reader growth
# Everything here is fail-soft to None: the brief renders without the line
# rather than ever failing or showing stale/garbled numbers.


def read_breakdown(max_age_s: int = _BREAKDOWN_MAX_AGE_S):
    """The governor's persisted projection breakdown as a dict, or None.

    None when the param is missing/unparseable/incomplete or older than
    `max_age_s` (stale burn rates mislead more than no line). Never raises.
    """
    try:
        raw = _client().get_parameter(Name=_SSM_BREAKDOWN_PARAM)["Parameter"]["Value"]
        b = json.loads(raw)
        for key in ("tier", "mtd", "projected", "ceiling", "ai_daily", "non_ai_daily", "computed_at"):
            if key not in b:
                return None
        computed_at = datetime.fromisoformat(str(b["computed_at"]))
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - computed_at).total_seconds() > max_age_s:
            return None
        return b
    except Exception:
        return None  # fail-soft: display-only, the brief just omits the line


def format_headroom_line(breakdown) -> str:
    """One-line budget-headroom readout from a read_breakdown() dict, or "".

    All values code-derived (Decimal from DDB-sourced callers is coerced via
    float()). The slack clause makes the #822 fact legible: when the projection
    is at/over the ceiling — a dev sprint alone can do this — say so plainly,
    because any concurrent reader growth then lands straight on tier 2.
    """
    if not breakdown:
        return ""
    try:
        tier = int(breakdown["tier"])
        projected = float(breakdown["projected"])
        ceiling = float(breakdown["ceiling"])
        ai_daily = float(breakdown["ai_daily"])
        non_ai_daily = float(breakdown["non_ai_daily"])
        total_daily = ai_daily + non_ai_daily
        line = (
            f"Budget: tier {tier} · projected ${projected:.0f} vs ${ceiling:.0f} ceiling"
            f" · AI ${ai_daily:.2f}/day of the ${total_daily:.2f}/day burn"
        )
        slack = ceiling - projected
        if slack <= 0:
            line += " — near-zero slack for reader growth"
        elif slack < 0.1 * ceiling:
            line += f" — ${slack:.0f} slack, thin for reader growth"
        else:
            line += f" — ${slack:.0f} headroom"
        # ADR-133 (#739): surge mode floats the ceiling for real reader traffic.
        # `surge_active` is optional (older breakdown payloads won't have it) —
        # .get() keeps this line rendering even against a pre-surge JSON shape.
        if breakdown.get("surge_active"):
            uniques = breakdown.get("recent_uniques")
            line += f" — SURGE mode ({uniques} uniques/7d, readers not spend)"
        return line
    except Exception:
        return ""  # fail-soft: a malformed field costs the line, nothing else
