"""live_shape.py — the heavy pull's shape, the lower-volume order and the aerobic walk (#5861). LIVE only.

  * `deadlift_shape` (owner ruling 5): the heavy-day hinge anchor is its top set + ONE back-off.
  * `order_lower_volume`: the squat before the hinge (the RDL tires the erectors the squat needs), a full-body day too.
  * The aerobic walk (`aerobic_gap`, `walk_prompt`, `walk_note`, WALK_PROMPT; owner ruling 12): a week the RECORD
    shows short gets one optional walk prompt; steps of unknown intensity are reported, never turned into a gap.

The volume rules this module carried (VOLUME, QUAD_SLOT, the weekly ceiling, drop-don't-shave, TIME_FIT) are `live_volume`'s one
weekly plan and one time fit since fix round 9."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

WALK_PROMPT: dict[str, dict[str, Any]] = {
    "max_minutes": {
        "value": 40,
        "label": HEURISTIC,
        "basis": "one optional brisk walk covers a weekly aerobic gap up to this size (a 30-45 min walk is an ordinary day's "
        "addition); a larger gap still gets one prompt of this size — never a gym block",
    },
    "min_minutes": {"value": 15, "label": HEURISTIC, "basis": "a gap under 15 minutes is noise against the recorded walking: no prompt"},
    "active_steps": {
        "value": 7500,
        "label": HEURISTIC,
        "basis": "#5861 FIX8 (owner ruling 12; the seventh red team: a 14k-step walker served easy rides and a 40-min walk prompt): "
        "when the recorded workouts leave the week short but the steps average at least ~7,500/day (the conventional 'somewhat "
        "active' line, a population heuristic), the aerobic minutes are UNKNOWN, not missing — reported, never turned into a gap. "
        "A purposeful aerobic prompt needs short recorded minutes AND low steps",
    },
}


def intensity_unknown(aer: dict[str, Any] | None) -> bool:
    """WALK_PROMPT active_steps (ruling 12): the recorded minutes leave the week short, but the steps say he is moving — the
    intensity is unknown, so there is no gap to close."""
    from training import cardio_model

    a = aer or {}
    steps = a.get("steps_per_day")
    short = int(a.get("walking_min_per_wk") or 0) < int(cardio_model.WEEKLY_MODERATE_MIN[0])
    return bool(short and steps is not None and float(steps) >= float(WALK_PROMPT["active_steps"]["value"]))


# ── 1. volume ────────────────────────────────────────────────────────────────


# ── 2. drop, don't shave ─────────────────────────────────────────────────────


# ── 3. order and the heavy pull ──────────────────────────────────────────────
def order_lower_volume(rx: dict[str, Any]) -> list[str]:
    """IN PLACE: on the lower-volume day the squat anchor comes before the hinge anchor (the RDL tires the erectors the squat
    needs). Returns the rationale lines."""
    ex = rx["exposures"]
    full = any(e.get("live_full_body") for e in ex)  # #5861 FIX8: a full-body day's guest squat and hinge too (seventh red team)
    if rx.get("session_role") != "lower_volume" and not full:
        return []
    hinge = next((i for i, e in enumerate(ex) if e.get("kind") == "anchor" and e.get("pattern") == "hinge"), None)
    squat = next((i for i, e in enumerate(ex) if e.get("kind") == "anchor" and e.get("pattern") == "squat"), None)
    if hinge is None or squat is None or squat < hinge:
        return []
    ex.insert(hinge, ex.pop(squat))
    day = "on lower volume" if rx.get("session_role") == "lower_volume" else "on a full-body day"
    return [f"order (live): the squat before the hinge {day} — the RDL tires the erectors the squat needs"]


def deadlift_shape(rx: dict[str, Any]) -> list[str]:
    """IN PLACE, the setting `heavy_day_deadlift_shape`: `top_plus_backoff` serves the heavy-day hinge anchor as its top set +
    ONE back-off; `as_today` (default) leaves the top set + two back-offs. The squat + deadlift pairing itself stays (#5694)."""
    if rx.get("session_role") != "lower_heavy":
        return []
    for e in rx["exposures"]:
        if e.get("kind") != "anchor" or e.get("pattern") != "hinge" or e.get("intensity") != "heavy":
            continue
        backs = [i for i, s in enumerate(e.get("sets") or []) if s.get("kind") == "back_off"]
        if len(backs) <= 1:
            return []
        for i in reversed(backs[1:]):
            e["sets"].pop(i)
        return ["deadlift (live option): top set + one back-off (heavy_day_deadlift_shape=top_plus_backoff); the pairing stays (#5694)"]
    return []


# ── 4. the aerobic gap ───────────────────────────────────────────────────────
def aerobic_gap(live: dict[str, Any], today_minutes: int = 0) -> int | None:
    """The week's aerobic minutes still missing: the guideline floor less the recorded credit, less every block performed this
    week before today, less today's block. None — UNKNOWN, never a gap — when the aerobic record or the steps were not read
    (fix round 12: missing data is not evidence that aerobic work is short) or the steps say he is moving (`intensity_unknown`)."""
    from training import cardio_model, live_sequence

    aer = live.get("aerobic") or {}
    if not aer.get("record_read") or aer.get("steps_per_day") is None or intensity_unknown(aer):
        return None
    since, day = live_sequence.week_start(str(live.get("target_date") or "")), str(live.get("target_date") or "")
    done = sum(
        int(r.get("duration_sec") or 0) // 60
        for rows in (live.get("by_machine") or {}).values()
        for r in rows or []
        if since <= str(r.get("date") or "")[:10] < day
    )
    return int(cardio_model.WEEKLY_MODERATE_MIN[0]) - int(aer.get("walking_min_per_wk") or 0) - done - int(today_minutes)


def walk_prompt(live: dict[str, Any] | None, today_minutes: int = 0) -> list[str]:
    """On the conditioning host's morning (one prompt a week), when the week's gap after steps and every block is at least
    WALK_PROMPT min_minutes: one optional walk, its minutes capped at max_minutes, as a `walk (live):` line. Else []."""
    if not live or live.get("role") != live.get("host"):
        return []
    gap = aerobic_gap(live, today_minutes)
    if gap is None or gap < int(WALK_PROMPT["min_minutes"]["value"]):
        return []
    minutes = min(int(WALK_PROMPT["max_minutes"]["value"]), int(-(-gap // 5) * 5))
    return [
        f"walk (live): optional brisk walk {minutes} min today — the week is ~{gap} min short after recorded walking and blocks (WALK_PROMPT)"
    ]


WALK_LINE = "Optional today: brisk walk {m} min, any time."


def walk_note(ideal: Any, lines: list[str] | None) -> None:
    """IN PLACE: a `walk (live):` line becomes exercise 1's last own line (what he reads at 5 am). Idempotent; no-op otherwise."""
    import re

    hit = next((ln for ln in lines or [] if ln.startswith("walk (live):")), None)
    m = re.search(r"brisk walk (\d+) min", hit or "")
    exercises = getattr(ideal, "exercises", None) or []
    if not m or not exercises:
        return
    text = WALK_LINE.format(m=m.group(1))
    note = exercises[0].notes or ""
    if text not in note:
        exercises[0].notes = f"{note}\n{text}".strip()


# ── 5. the kettlebell slot under strain ──────────────────────────────────────


# ── 5. the 75-minute ceiling on a short week (#5861 FIX8) ───────────────────
