"""owner_redlines.py — what Matthew is signing up for, and what makes the coach pull back (#3753).

WHY THIS EXISTS

On 2026-09-13, after a week of using cycle 17, the owner said the plans felt too
conservative: he is attempting an aggressive transformation, he has done one before, and
he wants the platform to back that with science rather than substitute its own risk
tolerance for his.

He was reading something real. The conservatism is not emergent — it is a written design
decision from June. `PROVEN_BLUEPRINT.md` §"Where the science improves" instructs the
coach to run a SLOWER rate than the prior cut ("3.5 lb/wk is above the platform's own
muscle-loss rate flag"), on the well-evidenced thesis that his failure mode is holding,
not losing: 16 loss episodes since 2012, zero that held, regain at 0.79x the speed of
loss. That thesis is good. But it was the PLATFORM's ruling, carried silently in prose
that every plan inherits, and the client never signed it.

So the posture becomes a file he edits. Two sections, and the distinction is the whole
point:

  REDLINES  — what the plan must PURSUE. His instruction to the coach.
  TRIPWIRES — what makes the coach pull back. The conditions HE accepts as reasons to
              ease off, chosen in advance, in the calm — not improvised mid-cut by a
              model weighing his health against his stated goal on its own authority.

An aggressive plan with named tripwires is safer than a conservative plan with none,
because the conservative one hides its own thresholds and nobody can audit them.

WHY THIS FILE AND NOT config/

`config/*.json` is not staged into the Lambda bundle, so a repo-side edit is inert at
runtime (#3675, #3671). The #3717 attestation module took the same route for the same
reason: a declaration that must reach the planner ships in code.

ADR-105: every threshold below carries its `provenance`. "owner" means he chose the
number. "population-derived" means it came from literature, not from his own variance,
and it says so at the point of use — a threshold whose origin is unstated is the class of
defect the rigor bar exists to prevent.

STATUS: NOT YET ACTIVE. `ACTIVE = False` until the owner has read and edited this file.
An unconfirmed redline must not steer a prescription — the same posture #3717 took, and
for the same reason. `plan_engine` reports the redlines as PROPOSED while this is False.
"""

from __future__ import annotations

from typing import Any

ACTIVE = False
"""Flip to True only when the owner has reviewed the values below. gate:owner (#3753)."""

LAST_REVIEWED_BY_OWNER: str | None = None
"""ISO date the owner last read this file. None means never."""


# ── What the plan must pursue ────────────────────────────────────────────────
REDLINES: dict[str, dict[str, Any]] = {
    "rate_band_pct_bw_per_wk": {
        "low": 0.5,
        "high": 1.0,
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": (
            "From his own platform-memory record of 2026-09-07: 'maximum sustainable fat loss with lean mass "
            "preserved… defensible rate window ~0.5-1.0% bodyweight/wk (at 327 lb that is ~1.6-3.3 lb/wk); his own "
            "proven rate in the 320-329 lb band is ~2.2 lb/wk.' At 319.7 lb the band is ~1.6-3.2 lb/wk."
        ),
        "owner_to_resolve": (
            "UNRESOLVED (2026-09-13). He now says the posture is too safe and he is signing up for a more aggressive "
            "transformation than is usually prescribed. That is in tension with the window above, which is also his. "
            "Two ways to settle it and they are NOT the same: (a) hold the window and target its TOP — 1.0%/wk, ~3.2 "
            "lb/wk at current weight, which is already near the 3.5 lb/wk his last campaign actually ran; or (b) widen "
            "the window, which means accepting a higher expected lean-mass cost and should be written down as that. "
            "Until he picks, the engine plans to the top of (a) and says so out loud."
        ),
    },
    "protein_floor_g": {
        "value": 180,
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": "'Protein is the #1 preservation lever — 180 g/day target, currently under-hitting.' The lever that makes an aggressive rate defensible.",
    },
    "walking_floor_hr_wk": {
        "value": 8.5,
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": (
            "PROVEN_BLUEPRINT's by-band table: at 300-309 lb during the campaign that worked he was walking ~10x/wk, "
            "~8.5 hrs/wk, from day one. The blueprint calls walking 'the single most replicable, highest-confidence "
            "driver in the dataset'. Owner correction 2026-09-19: the planner's Strava-only read (5.09 hr/wk) undercounts — "
            "treadmill and cycling blocks logged inside Hevy count too; 13–19 Sep measured >=8.79 hr, at or above the floor. "
            "Apple Health steps are NOT a walking proxy. The engine names walking first because it is the proven driver."
        ),
    },
    "lifting_sessions_per_wk": {
        "low": 2,
        "high": 3,
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": (
            "'Lifting exists to defend lean mass in a deficit (2-3x/wk, sufficient mechanical tension, hard sets near "
            "but not to failure); extra lifting volume beyond that costs recovery without adding fat loss.' He is "
            "willing to do LONG sessions — route that willingness to walking/Z2, not to more sets."
        ),
    },
    "load_anchoring": {
        "value": "bodyweight-band-matched history, discounted for detraining",
        "detraining_discount_pct": [10, 15],
        "provenance": "owner",
        "stated": "2026-09-08",
        "note": (
            "'Prescribe strength loads against BODYWEIGHT-BAND-MATCHED history, not recent history… TWO axes: (1) "
            "matched bodyweight band tells you what his frame handled, (2) weeks since last consistent block tells you "
            "what his connective tissue is ready for NOW. Matching on weight alone will over-prescribe.' Observed "
            "discount that was correct in practice: ~10-15% under last performed after a ~10 week layoff."
        ),
    },
    "run_gate_lb": {
        "value": 240,
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": "ZERO runs logged above 240 lb across his whole history; running appears at 240 and scales down-weight. Joint-gated from his own data, not a generic caution.",
    },
}


# ── What makes the coach pull back ───────────────────────────────────────────
# Every entry: the signal, the threshold, where the threshold came from, and what the
# coach DOES. "Pull back" is never "stop" unless it says so — a tripwire that can only
# halt everything is one he will learn to ignore.
TRIPWIRES: list[dict[str, Any]] = [
    {
        "id": "anchor_lift_strength_drop",
        "signal": "top-set load on an anchor movement, vs the trailing best at this bodyweight band",
        "threshold_pct": 10,
        "consecutive_sessions": 2,
        "provenance": "population-derived",
        "action": "hold load; add a protein/sleep check to the next debrief before adding any volume",
        "note": (
            "Strength held flat through a 118 lb loss last time and the blueprint calls that 'decent muscle defense'. "
            "A sustained drop is the earliest honest signal that the rate is outrunning recovery. The 10% / 2-session "
            "shape is a common training-literature heuristic, NOT computed from his own variance — the engine must say "
            "so wherever it fires (ADR-105), and it should be re-derived from his own session-to-session spread once "
            "cycle 17 has enough anchor-lift data to estimate one."
        ),
    },
    {
        "id": "protein_floor_missed",
        "signal": "days below the protein floor in the trailing 7",
        "threshold_days": 3,
        "provenance": "owner",
        "action": "nutrition takes priority over added training volume until it is back; the plan does not grow that week",
        "note": "His own stated #1 preservation lever. Missing it is the mechanism by which an aggressive rate costs muscle rather than fat.",
    },
    {
        "id": "readiness_floor",
        "signal": "Whoop recovery",
        "threshold": 34,
        "consecutive_days": 3,
        "provenance": "population-derived",
        "action": "GREEN ceiling drops to the YELLOW baseline; intervals come off; the easy session stays easy",
        "note": (
            "34 is Whoop's own red/yellow boundary — a vendor threshold, not his. The recovery-adaptive authoring spec "
            "already branches on it; this tripwire is the multi-day version, which is the one that means something."
        ),
    },
    {
        "id": "pain_flag_named_site",
        "signal": "a pain flag on a named joint/tendon in the derived note layer",
        "threshold": "any",
        "provenance": "owner",
        "action": "that movement pattern is substituted, not loaded, until he says otherwise",
        "note": (
            "The pain lexicon is over-inclusive by design and the flag is a question, not a verdict. NOTE (#3768): this "
            "tripwire reads a layer that was dark from the day it shipped until 2026-09-13 — so it could not have "
            "fired. The engine reports this tripwire's own layer_status rather than its silence."
        ),
    },
    {
        "id": "weight_stall_with_adherence",
        "signal": "trailing 14d weight trend flat or up WHILE intake and training adherence are on plan",
        "threshold_days": 14,
        "provenance": "owner-history",
        "action": "this is a diet-break / refeed decision, surfaced to him as a decision — never taken silently",
        "note": (
            "The prior campaign ran flat-out with no planned landing and reversed. A stall that is NOT explained by "
            "adherence is the moment the blueprint says to schedule a break rather than push harder."
        ),
    },
]


def summary() -> dict[str, Any]:
    """The block the planner embeds — never a bare number without its provenance."""
    return {
        "active": ACTIVE,
        "last_reviewed_by_owner": LAST_REVIEWED_BY_OWNER,
        "status_note": (
            "PROPOSED — drafted from the owner's own recorded statements, not yet reviewed by him. Reported so the "
            "plan is auditable; not treated as his instruction until ACTIVE is True (#3753, gate:owner)."
            if not ACTIVE
            else f"ACTIVE — owner-reviewed {LAST_REVIEWED_BY_OWNER}."
        ),
        "redlines": REDLINES,
        "tripwires": TRIPWIRES,
        "unresolved": [k for k, v in REDLINES.items() if v.get("owner_to_resolve")],
        "population_derived_thresholds": [t["id"] for t in TRIPWIRES if t.get("provenance") == "population-derived"],
    }


def rate_target_lb_per_wk(weight_lb: float | None) -> dict[str, Any] | None:
    """The rate band in pounds at a given bodyweight, with the unresolved tension attached."""
    if not weight_lb:
        return None
    band = REDLINES["rate_band_pct_bw_per_wk"]
    return {
        "low_lb_wk": round(weight_lb * band["low"] / 100, 1),
        "high_lb_wk": round(weight_lb * band["high"] / 100, 1),
        "provenance": band["provenance"],
        "stated": band["stated"],
        "owner_to_resolve": band.get("owner_to_resolve"),
    }
