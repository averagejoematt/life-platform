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
              + the two OPERATOR-TRUTH CI gates (reader_truth_qa, visual_ai_qa —
              ADR-125's 2026-08-03 amendment, #1927): they run whenever Bedrock
              runs at all and stop only when everything stops, because a gate
              that cannot run cannot tell an operator whether a deploy is safe.

Adding a feature? Classify it into a band here AND in tests/test_budget_guard_ladder.py
— an unlisted feature silently defaults to cutoff 3 and outlives every reader surface
(the pre-ADR-125 coherence_semantic bug). CI_GATE_FEATURES below is the derived set the
QA harnesses read; never hand-list those names at a call site.

Fail-open: if SSM is unreadable (transient error, missing grant, param absent)
we return tier 0 — a monitoring blip must never take AI down. The AWS Budgets
notifications are the backstop for that rare window.

This module is bundled into every function's deploy package (#781 retired the shared Lambda layer).
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

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
    # eyeball_estimate (#1390): the meal-photo Haiku vision macro estimate — a self-grading
    # calibration probe (`lambdas/eyeball_calibration.py`), never a reader narrative and never
    # nutrition data. Internal/self-grading, so it pauses FIRST like the rest of band 1; a paused
    # call returns an explicit {"status": "paused"} (never a fabricated estimate). ~$1/mo, so it
    # is the cheapest thing to sacrifice under any pressure.
    "eyeball_estimate": 1,
    # conversation_enrichment (#1577): the Haiku sweep over the conversational corpus
    # (coach check-in answers, habit reflections, field-note responses) that turns
    # them into analysis-only enriched signals + hypothesis-candidate seeds. An
    # internal analysis layer — nothing a reader reads pauses with it, and the
    # verbatim records remain fully stored either way (enrichment just resumes and
    # backfills when the tier drops). ~a few short Haiku calls/day.
    "conversation_enrichment": 1,
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
    # horizons_retrospective (#1707, epic #1686 S3): the Mind coach's weekly grounded
    # "why I recommended it" retrospective on the /data/horizons/ feed — a reader
    # NARRATIVE surface, so it pauses in band 2 with the rest of the reader narrative,
    # after all internal AI and before the two irreducible reader promises. Weekly +
    # cached (stored on the pick, never regenerated per request), so ~pennies/mo; the
    # band placement is audience-order, not dollars. A paused call yields NO
    # retrospective (honest "coach's note coming" state), never a fabricated one.
    "horizons_retrospective": 2,
    # coach_nudge (#1382, epic #1080): the proactive decision-moment nudge — one
    # short Haiku phrasing call per day AT MOST (deterministic triggers + a ≤1/day
    # ledger cap decide everything; the model only phrases). Matthew-facing coach
    # voice, so it sits in band 2 with the rest of the coach narrative: tier ≥2
    # silences it entirely (AC2), and a silenced day is a silent day — no fallback
    # copy, no template nudge (a canned nudge would be noise, not coaching).
    "coach_nudge": 2,
    # coach_diary_reaction (#1574, epic #1564): the coach's short grounded reaction to
    # a Video Diary / Solo Recording entry, rendered on the public lab-notes surface
    # (the coaches responding to the human, not the sensors). A reader NARRATIVE
    # surface, so it pauses in band 2 with the rest of the reader narrative — after all
    # internal AI, before the two irreducible reader promises. One short Haiku/Sonnet
    # call per entry; a paused call yields NO reaction (nothing renders — AC3), never a
    # fabricated one.
    "coach_diary_reaction": 2,
    # coach_social_reaction (#1675, epic #1668): the SAME reaction mechanism as
    # coach_diary_reaction, pointed at the social channel — the routed coach's short
    # grounded reaction to a public post of Matthew's, rendered on the same lab-notes
    # surface. Same audience, so ADR-125 puts it in the same band (2): it outlives every
    # internal/dev AI feature and pauses before the two irreducible reader promises. It
    # is a SEPARATE feature name rather than a shared one purely for observability — the
    # per-channel Bedrock cost is then separable at the chokepoint, and either channel
    # can be re-banded later without moving the other. One short Haiku/Sonnet call per
    # post; a paused call yields NO reaction (nothing renders), never a fabricated one.
    "coach_social_reaction": 2,
    # semantic_recall (#1384): the "when did I feel like this before?" precedent
    # retrieval — Titan-v2 embeddings + cosine. A reader-narrative ENHANCEMENT (the
    # coach precedent line + chronicle recall card), so it pauses in band 2 with the
    # rest of the reader narrative: when the reader narratives it decorates are
    # themselves paused, spending on precedents for them is pointless. Titan is
    # ~$0.02/1M tokens so the cost is negligible; the band placement is about
    # audience order, not dollars. A paused call ⇒ no precedent block/card (the
    # coach reads exactly as it did before recall existed).
    "semantic_recall": 2,
    # ── Band 3: the two IRREDUCIBLE reader promises + the two OPERATOR-TRUTH CI
    #    gates — pause LAST (ADR-100/125, the latter added by the ADR-125
    #    2026-08-03 amendment, #1927).
    #
    # reader_truth_qa (#1095/#1096) and visual_ai_qa (#1428) are the AI halves of
    # the deploy pipeline's own QA: the CI post-deploy prose pass (visual_qa
    # --reader-truth), the vision pass on the visual-qa job, and the nightly
    # qa_smoke "Reader Truth" category. They sat at cutoff 1 as "internal QA" and
    # were consequently DARK for 26 of 30 days (#1927's measurement) — while still
    # reporting green, because a gate that does not run produces no findings.
    #
    # Why cutoff 3 and not a band of their own: ADR-125 orders the ladder by
    # AUDIENCE, and these two serve the OPERATOR — the person deciding whether the
    # deploy that just landed is safe. That answer is upstream of every reader
    # surface below it, so it cannot be the first thing sacrificed. Their cost
    # profile agrees: both are per-DEPLOY and bounded (one Haiku batch over <= 8
    # surfaces; <= 3 images x 6 tier-1 doors at ~$0.001/image — pennies per run),
    # not per-day and open-ended like their former band-mates, and their value
    # peaks exactly when shipping, which is when a pause is most likely in force.
    # At cutoff 3 they stop precisely when bedrock_client stops everything — "they
    # run whenever Bedrock runs at all" — and the pause is then reported, not
    # inferred: SKIPPED-BY-BUDGET in the run output, the CI job summary + a
    # ::warning:: annotation, the QAPausedByBudget metric, and a qa_smoke ⏸ check.
    # This is NOT the pre-ADR-125 coherence_semantic defect (an UNLISTED feature
    # defaulting to 3 by accident): the placement is deliberate, documented, and
    # pinned by tests/test_budget_guard_ladder.py's _OPERATOR_TRUTH band.
    "reader_truth_qa": 3,
    "visual_ai_qa": 3,
    #
    # website_ai: the PUBLIC /api/ask + /api/board_ask hook — the platform's most
    # differentiating surface. Rate limits (5/hr/IP) + Haiku pricing bound the
    # worst case; the tier-3 hard stop keeps its honest 'paused' message.
    "website_ai": 3,
    # daily_brief_ai: the 10 AM PT brief (cron(0 17 * * ? *)) — "protect longest" by
    # design. Falls back to a data-only brief at tier 3.
    "daily_brief_ai": 3,
}

_HARD_STOP_TIER = 3

# The AI gates the DEPLOY PIPELINE reports on (#1927). Exported so the harnesses,
# the qa_smoke hook and the tests all read one list instead of re-typing the names
# (the "guard the SET, not the instance" rule). Membership is asserted against
# _FEATURE_CUTOFF in tests/test_budget_guard_ladder.py.
CI_GATE_FEATURES = ("reader_truth_qa", "visual_ai_qa")

# dict[str, Any]: the values are heterogeneous (int tier + float timestamp), and
# without the annotation mypy joins them to `float`, so `return _cache["tier"]`
# reads as returning a float from `-> int` (#2638).
_cache: dict[str, Any] = {"tier": 0, "ts": 0.0}
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


def paused_features(tier=None):
    """The features currently disabled at `tier` (default: the live tier).

    Derived from _FEATURE_CUTOFF, never hand-listed — #1927's whole finding was
    that nobody could name what a tier had switched off. CI gates sort FIRST
    (they are the ones an operator must know about before trusting a green
    pipeline), then alphabetically, so the readout is deterministic.
    """
    if tier is None:
        tier = current_tier()
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        return []
    paused = [f for f, cutoff in _FEATURE_CUTOFF.items() if tier >= cutoff]
    return sorted(paused, key=lambda f: (f not in CI_GATE_FEATURES, f))


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
        # #2381: the crossing-date clause — the NEXT tier band's projected
        # in-force date at this burn, so a budget-posture decision is visible
        # ~two weeks out instead of arriving as a mid-month scramble (July
        # 2026's shape). Optional key: older payloads simply omit the clause.
        crossings = breakdown.get("tier_crossings") or {}
        for _t in (1, 2, 3):
            if _t > tier and crossings.get(str(_t)):
                line += f" · tier {_t} ~{crossings[str(_t)]} at this burn"
                break
        line += format_paused_clause(tier)
        return line
    except Exception:
        return ""  # fail-soft: a malformed field costs the line, nothing else


def format_paused_clause(tier, max_names: int = 3) -> str:
    """The ` · paused: N AI features (a, b, c +k more)` clause, or "" at tier 0.

    #1927: the headroom line said WHICH tier, never WHAT that tier had switched
    off — so the 26-day band-1 blackout was legible only to someone who could
    recite _FEATURE_CUTOFF from memory. This puts the answer in the one budget
    line the daily brief already renders. Names are truncated (a tier-2 pause is
    13 features) but the COUNT is always exact, and CI gates sort first so they
    can never be the ones truncated away.
    """
    try:
        paused = paused_features(int(tier))
        if not paused:
            return ""
        shown = ", ".join(paused[:max_names])
        extra = len(paused) - len(paused[:max_names])
        if extra > 0:
            shown += f" +{extra} more"
        return f" · paused: {len(paused)} AI feature{'s' if len(paused) != 1 else ''} ({shown})"
    except Exception:
        return ""  # fail-soft: a malformed field costs the line, nothing else
