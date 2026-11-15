"""live_week.py — the week-shaped live helpers that survived fix round 9 (#5861). LIVE only (reached from live hooks that check
the live mark first): the conditioning block's week-to-week progression (`cardio_progress`, `cardio_model.progress`), the medical
stop line and his own logged symptoms (`symptom_gate`, `review_line`: no hard cardio until reviewed), and a vertical pull that
survives a garage (`vertical_pull_fallback`, VERTICAL_PULL_FALLBACK: the first servable vertical pull, gates fail-closed).

Deleted in round 9 (consolidation): the kettlebell slot machinery, the cardio-room trims, the behind-schedule week, the novelty
start and familiar-swap rules (`live_load`'s three novelty rules replace them) and the press-set option (`live_volume`)."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

VERTICAL_PULL_FALLBACK: tuple[str, ...] = (
    "pull_up_band",
    "chin_up_band",
    "pull_up_negative",
    "chin_up",
    "pull_up",
    "db_lat_pullovers",
    "pullover_dumbbell",
)
"""HEURISTIC fallback order (practitioner consensus) when a vertical-pull anchor has no available member (a garage with a bar
and no pulldown station): a band-assisted pull-up (when the library carries one — a data-lane key), a negative, the bodyweight
pull-up/chin-up (each only while its gates open: fail-closed), then the dumbbell pull-over (the lat through shoulder
extension, no gate). A key the library or the catalog does not carry is skipped."""
CARDIO_PROTOCOL = {
    "easy": "moderate_continuous",
    "incline_treadmill_walk": "moderate_continuous",
    "hills": "incline_resistance_progression",
    "tempo": "tempo_threshold",
    "intervals": "structured_intervals",
}
"""The menu kind -> the cardio model's protocol whose progression rule doses it (`cardio_model.progress`)."""


# ── 1. the kettlebell slot ────────────────────────────────────────────────────


# ── 2. cardio room and progression ────────────────────────────────────────────


EASY_MIN_BLOCK = 20
"""Heuristic: a conditioning block's progression never takes it under 20 minutes (its warm-up costs the rest)."""


def _performed(kind: str, live: dict[str, Any]) -> list[dict[str, Any]]:
    """His performed blocks of `kind` before the draft day, most recent first: {date, minutes, rpe}."""
    from training import cardio_menu

    out = []
    for key, sessions in (live.get("by_machine") or {}).items():
        for s in sessions or []:
            d = str(s.get("date") or "")[:10]
            if not d or d >= str(live.get("target_date") or "9999"):
                continue
            k = cardio_menu.kind_of_performed(key, s.get("note"), s.get("served_kind"), s.get("served_swap_kind"), s.get("set_rpe"))
            if k != kind:
                continue
            rpe = s.get("set_rpe") if s.get("set_rpe") is not None else cardio_menu.logged_rpe(s.get("note"))
            out.append({"date": d, "minutes": int(s.get("duration_sec") or 0) // 60, "rpe": rpe})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def cardio_progress(kind: str, live: dict[str, Any], minutes: int) -> tuple[int, list[str]]:
    """The block's minutes this week by `cardio_model.progress` over his performed blocks of the same kind (the protocol's
    rule: symptoms, recovery and logged effort first; then duration, then frequency, then intensity). Only a DURATION step
    or a step back moves the minutes (within CARDIO_ROOM min_block and the menu's cap); a frequency or intensity step is
    named for the owner — the charter's placement owns frequency. No performed block of this kind: the menu's dose."""
    from common.pacific_time import shift_day_key

    from training import cardio_menu, cardio_model

    name = CARDIO_PROTOCOL.get(kind)
    rows = _performed(kind, live) if name else []
    if not rows or not rows[0]["minutes"]:
        return minutes, []
    last = rows[0]
    held = next((i for i, r in enumerate(rows) if abs(r["minutes"] - last["minutes"]) > 1), len(rows))
    week_ago = shift_day_key(str(live.get("target_date")), -7)
    band = cardio_menu.wire_band(kind) or (0, 99)
    rpe = last["rpe"]
    state = {
        "minutes": last["minutes"],
        "sessions_per_wk": sum(1 for r in rows if r["date"] >= week_ago),
        "held_sessions": held,
        "rpe": None if rpe is None else ("over" if float(rpe) > band[1] else ("under" if float(rpe) < band[0] else "in")),
        "recovery": "poor" if live.get("state") in ("strained", "overreached") else "ok",
        "symptoms": bool(live.get("tripwire")),
    }
    p = cardio_model.progress(name, state)
    out = minutes
    if p["action"] in ("add_duration", "step_back"):
        out = max(EASY_MIN_BLOCK, min(int(p["minutes"]), int(minutes)))
    return out, [
        f"cardio progression (live): {name} — last {last['minutes']} min on {last['date']} -> {out} min: {p['action']} "
        f"({p['reason']}; cardio_model.progress, heuristic)"
    ]


# ── 3. the medical stop line ─────────────────────────────────────────────────
def symptom_gate(row: Any, workouts: Any = None, as_of: Any = None) -> dict[str, Any] | None:
    """The `medical_stop_lines` tripwire row (`health.tripwire_readers.medical_stop_lines`) -> {tripwire, lines} when TRIPPED,
    else None. `unknown` (the self-report palpitations / syncope arms with no input) is never read as tripped or as clear.
    #5861 FIX5: those two arms' self-report — a symptom he logged on a Hevy note in the last fortnight (`live_rules.self_report`,
    over `workouts` before `as_of`) — trips the draft's gate too."""
    if not isinstance(row, dict) or row.get("state") != "tripped":
        from training.live_rules import self_report

        return self_report(workouts, as_of)
    arms = (row.get("observed") or {}).get("arms") or {}
    hit = sorted(k for k, a in arms.items() if isinstance(a, dict) and a.get("state") == "tripped")
    return {"tripwire": str(row.get("id") or "medical_stop_lines"), "lines": hit or ["a stop line"]}


def review_line(trip: dict[str, Any]) -> str:
    return (
        f"review (live): {trip['tripwire']} tripped ({', '.join(trip['lines'])}) — no hard cardio until it is reviewed "
        "(owner_redlines medical_stop_lines; the clinical action is his clinician's, not the engine's)"
    )


# ── 4. behind schedule ───────────────────────────────────────────────────────


# ── 5. coverage ──────────────────────────────────────────────────────────────
def vertical_pull_fallback(e: dict[str, Any], ctx: dict[str, Any], taken: set[str]) -> str | None:
    """A live-only fallback for a VERTICAL-PULL anchor no member of which the gym can serve (`live_session.fit_exposures`):
    the first key of VERTICAL_PULL_FALLBACK the catalog can write, the gym has, no locked gate holds (fail-closed) and the
    skill ceiling allows. None when the exposure is not a vertical pull or nothing is servable."""
    from training import live_session as ls

    if e.get("kind") != "anchor" or e.get("pattern") != "vertical_pull":
        return None
    for key in VERTICAL_PULL_FALLBACK:
        c = ctx["catalog"].get(key)
        if not c or key in taken or int(c.get("skill_tier", 99)) > ctx["ceiling"]:
            continue
        if ls._blocked(key, ctx, False) is None and ls._servable(key, ctx) is None:
            return key
    return None
