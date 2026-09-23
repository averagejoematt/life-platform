"""accessory_strength_trend.py — the accessory half of the two-tier strength trend (#4112).

Owner ruling, 2026-09-23 ~06:00 PT, on which lifts can trigger a strength-drop flag: *"B but
more emphasis on A as a benchmark, B more ancillary tracked."* The four core anchors (bench,
row, squat, hinge) stay the ONE benchmark that can change or veto the plan
(`plan_engine.anchor_lift_strength_drop`, `mcp.tools_plan._worst_anchor`, #4069/#4098) — that
machinery is unchanged by this module. Every OTHER drafted lift's e1RM trend used to
disappear once #4069 narrowed the tripwire to core anchors only; it is tracked and reported
here instead.

ONE TREND COMPUTATION, TWO TIERS. This module computes no e1RM trend of its own — every row
it reads already carries `plan_engine.anchor_e1rm_trend`'s output
(`mcp.tools_plan._anchor_trend`, the SAME per-exercise rows `_worst_anchor` reads for the core
tier, built in `mcp.tools_plan._gather_draft_evidence`). It only SHAPES the accessory half —
the rows with no `anchor_family` (#4069's own marker for "this is one of the four core
anchors") — and states, in the block itself, that an accessory reading is tracked and
reported and can never become a `change` or `veto` (`coach.critics.build_muscle_defense_packet`
enforces that half of the rule; `test_the_critic_never_escalates_an_accessory_drop_4112` holds
it).
"""

from __future__ import annotations

from typing import Any

BLOCK_VERSION = "accessory-strength-trend@1.0.0"  # #4112
NOTE = (
    "tracked and reported only — the four core anchors (bench, row, squat, hinge) are the "
    "benchmark that can change or veto the plan; an accessory trend never does (owner ruling, #4112)"
)


def build(evidence_exercises: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The accessory tier: every drafted lift that is NOT a core anchor and has a computed
    e1RM trend (even an `insufficient` one — tracked means reported, not just the drops).

    A row with neither `anchor_family` nor any trend field (`_anchor_trend` returned `{}` —
    no resolvable history at all for that movement) is not an accessory reading; it is
    nothing to report, and is left out rather than padded with an empty entry.
    """
    lifts = [
        {
            "idx": e.get("idx"),
            "label": e.get("label"),
            "identity": e.get("identity"),
            "n_sessions": e.get("n_sessions"),
            "n_sessions_e1rm": e.get("n_sessions_e1rm"),
            "insufficient": e.get("insufficient"),
            "drop_pct": e.get("drop_pct"),
            "sessions_below": e.get("sessions_below"),
            "recent_median_e1rm_lb": e.get("recent_median_e1rm_lb"),
            "baseline_median_e1rm_lb": e.get("baseline_median_e1rm_lb"),
            "last_top_lbs": e.get("last_top_lbs"),
        }
        for e in evidence_exercises or []
        if not e.get("anchor_family") and e.get("n_sessions") is not None
    ]
    return {"version": BLOCK_VERSION, "state": "tracked" if lifts else "no_accessory_trend_data", "lifts": lifts, "note": NOTE}


def attach(block: dict[str, Any], evidence: dict[str, Any] | None) -> None:
    """Mutates `block["accessory_strength_trend"]` in place — mirrors `mcp.tools_plan`'s
    `_merge_walking_volume` / `_attach_session_loads` shape, so `plan_engine.constraint_block`
    stays pure and this stays a one-line call at the site that already has `evidence` in hand."""
    block["accessory_strength_trend"] = build((evidence or {}).get("exercises"))
