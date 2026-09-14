"""tools_plan.py — one server-side planning surface, so the client stops deciding (#3751).

Before this, asking for tomorrow's session over chat/MCP got you fourteen data tools and
whatever rigor that one turn happened to bring. The structured procedure existed only in
`.claude/skills/daily-debrief/SKILL.md`, which only Claude Code runs. Same owner, same
data, same question, two different answers depending on which app he opened.

`plan_next_session` is the deterministic stage (`training.plan_engine`) reachable from
every client. It gathers the same inputs the debrief skill enumerates, computes the
constraint block with no model in the loop, and returns it — with what the evidence
cannot support stated in the payload rather than left to the caller's discipline.

It deliberately does NOT claim to have red-teamed anything: the adversarial critics
(#3752) are not wired, and the block says so.
"""

from __future__ import annotations

from common.pacific_time import pacific_today

from mcp.core import LAYER_UNKNOWN


def _safe(fn, *a, **kw):
    """Call a tool defensively — a reader that fails yields None, never a default."""
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        return None


def _walk_hours_last_7d(end_date: str) -> float | None:
    """Walking hours in the trailing 7 days, from Strava.

    Hours, not miles: the blueprint's floor is stated in hours per week, and converting
    between them needs a pace assumption that would be invented here.
    """
    from datetime import date, timedelta

    from mcp.core import query_source_range

    try:
        start = (date.fromisoformat(end_date) - timedelta(days=6)).isoformat()
    except ValueError:
        return None
    items = query_source_range("strava", start, end_date) or []
    seconds = 0.0
    found = False
    for it in items:
        for a in it.get("activities") or []:
            if (a.get("type") or a.get("sport_type") or "").lower() not in ("walk", "hike"):
                continue
            secs = a.get("moving_time_seconds") or a.get("moving_time") or 0
            try:
                seconds += float(secs)
                found = True
            except (TypeError, ValueError):
                continue
    if not items and not found:
        return None
    return round(seconds / 3600.0, 2)


def tool_plan_next_session(args):
    """The deterministic constraint block for a session, from one place (#3751)."""
    args = args or {}
    target_date = args.get("target_date") or pacific_today()

    from training import plan_engine

    # Each reader is the SAME tool a chat turn would have called — the point is not new
    # data, it is that the call set is fixed instead of improvised per conversation.
    from mcp.tools_benchmark import tool_get_benchmark
    from mcp.tools_health import tool_get_readiness_score
    from mcp.tools_strength import tool_get_muscle_volume
    from mcp.tools_training import tool_get_acwr_status

    reference = _safe(tool_get_benchmark, {"view": "prescription", "date": target_date})
    if isinstance(reference, dict) and reference.get("applicable") is False:
        # An inapplicable reference is not a reference. Carry the reason, drop the shape.
        reference = {"proven_target": None, "_inapplicable_reason": reference.get("reason")}

    weight = None
    if isinstance(reference, dict):
        weight = reference.get("current_weight")

    readiness = _safe(tool_get_readiness_score, {"date": target_date}) or {}
    acwr = _safe(tool_get_acwr_status, {}) or {}
    volume = _safe(tool_get_muscle_volume, {"start_date": _minus_days(target_date, 28), "end_date": target_date}) or {}

    # The pain tripwire reads the derived note layer; its STATUS decides whether silence
    # means anything (#3767/#3768). Absent a per-movement query here, the layer's own
    # health is the honest input, and `unknown` is the honest default.
    layer_status = LAYER_UNKNOWN
    try:
        from training.training_notes import training_notes_health

        from mcp.config import table
        from mcp.core import derived_layer_status

        layer_status = derived_layer_status(training_notes_health(table))[0]
    except Exception:  # noqa: BLE001
        pass

    block = plan_engine.constraint_block(
        date=target_date,
        weight_lb=weight,
        walk_hr_wk_now=_safe(_walk_hours_last_7d, target_date),
        # Key names verified against each tool's live return shape rather than assumed —
        # a planner reading a key that does not exist degrades to "unknown" silently,
        # which is the #3767 failure wearing different clothes.
        recovery_tier=_recovery_tier(readiness),
        acwr_flag=(acwr.get("alert") or acwr.get("interpretation")),
        muscle_volume=(volume.get("muscle_sets") or volume.get("by_muscle") or {}),
        reference=reference if isinstance(reference, dict) else None,
        pain_layer_status=layer_status,
    )

    return {
        "target_date": target_date,
        "constraint_block": block,
        "how_to_use": (
            "This is stage 1 of 3 and the ONLY stage that exists today: deterministic constraints, no model. "
            "Draft against it, then say plainly which constraint shaped which choice. The adversarial critics "
            "(#3752) are NOT wired — do not describe a plan built on this as red-teamed. Every line under "
            "`reference.must_say` is required in the answer, verbatim in substance, not summarised away."
        ),
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }


def _recovery_tier(readiness: dict) -> str | None:
    """GREEN / YELLOW / RED from the readiness score, in the authoring spec's bands.

    `get_readiness_score` returns a 0-100 `score`, not a tier; the recovery-adaptive
    authoring spec (SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21) is what maps a number to
    a branch. Doing the mapping here keeps the engine's input in the vocabulary the
    cues are written in.
    """
    score = readiness.get("score")
    if score is None:
        score = readiness.get("recovery_score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


def _minus_days(date_str: str, days: int) -> str:
    from datetime import date, timedelta

    try:
        return (date.fromisoformat(date_str) - timedelta(days=days)).isoformat()
    except ValueError:
        return date_str
