"""plan_draft_evidence.py — stage 2's per-draft evidence, gathered from the SAME readers a chat turn calls.

Extracted from `mcp/tools_plan.py` (#4161) under the #1665 module-size ratchet when the red team's
critic rules (the stale-lift exposures, the fatigue trigger) added inputs; `tools_plan` re-exports
every name, so `patch("mcp.tools_plan._gather_draft_evidence", ...)` and the coach packet's
`from mcp.tools_plan import _training_streaks` keep working unchanged.

#4161 adds two things here, both pure over reads this module already makes:
  * `stale` per drafted lift — `coach.critics_fatigue.stale_exposure` over the lift's own identity,
    read over STALE_HISTORY_LOOKBACK_DAYS (the anchor TREND still reads its 180 days, unchanged), so a
    return inside six months is told apart from one after longer;
  * `attach_fatigue_inputs` — the session role of every completed session (the sequence's ledger),
    the readiness streak and the 48 h same-region read, so the joints critic's trigger is computed
    from performance and readiness, not from a loaded-day count.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.plan_helpers import _days_between, _minus_days, _resolver, _safe

logger = logging.getLogger("tools_plan")

ANCHOR_HISTORY_LOOKBACK_DAYS = 180
STALE_HISTORY_LOOKBACK_DAYS = 400  # #4161: > 6 months + three exposures, so the stale-lift gap class is readable
PAIN_LOOKBACK_DAYS = 28
BLOCK_LOOKBACK_DAYS = 56  # 8 weeks, enough to count the trailing consistent block (>=2 lifts/wk)


def _gather_draft_evidence(ir: Any, target_date: str, layer_status: str) -> dict[str, Any]:
    """Per-draft-exercise evidence for the critics: anchor-lift trend, pain flags, days since.
    Plus the two streaks (#4067) and the lifting-session count from the performed record."""
    from mcp.tools_strength import tool_get_exercise_history
    from mcp.tools_training_notes import tool_get_exercise_notes

    resolver = _safe(_resolver)
    anchor_ids = _safe(_core_anchor_identities) or {}
    exercises: list[dict[str, Any]] = []
    for idx, ex in enumerate(getattr(ir, "exercises", None) or []):
        key = getattr(ex, "movement_key", "") or ""
        label = (getattr(ex, "rationale_tag", "") or "") if (getattr(ex, "rationale_tag", "") or "") != "custom" else key
        tid = _safe(resolver, key) if resolver else None
        row: dict[str, Any] = {"idx": idx, "label": label or key, "template_id": tid}
        hist = (
            _safe(
                tool_get_exercise_history,
                {"template_id": tid, "start_date": _minus_days(target_date, STALE_HISTORY_LOOKBACK_DAYS), "end_date": target_date},
            )
            if tid
            else None
        )
        everything = (hist or {}).get("sessions") or []
        trend_start = _minus_days(target_date, ANCHOR_HISTORY_LOOKBACK_DAYS)
        sessions = [s for s in everything if str(s.get("date") or "")[:10] >= trend_start]
        # #4069: the trend is computed over ONE template identity (see `_anchor_trend`), and the
        # row says which core anchor family — if any — the drafted lift belongs to. #4161: over its own
        # 180 days, unchanged — the wider read only feeds the stale-lift gap and the performance series.
        row.update(_anchor_trend(sessions, target_date))
        if hist is not None:
            row.update(_exposure_history(everything, target_date))
        family = _core_anchor_family(key, row.get("identity") or tid, anchor_ids)
        if family:
            row["anchor_family"] = family
        pain = _safe(tool_get_exercise_notes, {"template_id": tid, "lookback_days": PAIN_LOOKBACK_DAYS}) if tid else None
        if pain and "error" not in pain:
            row["pain_flag_any"] = pain.get("pain_flag_any")
            row["pain_dates"] = pain.get("pain_dates") or []
            row["pain_layer_status"] = pain.get("layer_status")
        exercises.append(row)

    dates = _safe(_workout_dates, _minus_days(target_date, BLOCK_LOOKBACK_DAYS), target_date)
    streaks = _safe(_training_streaks, target_date) or {"active_day_streak": None, "loaded_lifting_streak": None}
    week_start = _minus_days(target_date, 7)
    lifting_7d = len({d for d in dates if week_start <= d < target_date}) if dates is not None else None
    weeks_in_block = _weeks_in_block(dates, target_date) if dates is not None else None
    # the per-movement reads each carry the derived layer's own status; a dark read on ANY
    # drafted movement makes the whole pain input unknown (never clear by omission, #3768)
    statuses = [e.get("pain_layer_status") for e in exercises if e.get("pain_layer_status")]
    if statuses and all(s not in ("dark", "unknown") for s in statuses):
        layer_status = statuses[0]
    elif statuses:
        layer_status = next(s for s in statuses if s in ("dark", "unknown"))
    return {
        "exercises": exercises,
        # #4067: two streaks, both context since #4161 (the fatigue trigger is performance or readiness).
        "active_day_streak": streaks.get("active_day_streak"),
        "loaded_lifting_streak": streaks.get("loaded_lifting_streak"),
        "streaks": streaks,
        "lifting_sessions_7d": lifting_7d,
        "weeks_in_block": weeks_in_block,
        "pain_layer_status": layer_status,
    }


def _exposure_history(sessions: list[dict[str, Any]], target_date: str) -> dict[str, Any]:
    """#4161: the stale-lift exposure over ONE identity (the latest session's, as `_anchor_trend` cuts it),
    and the compact top-set series `attach_fatigue_inputs` reads (popped there, never stored)."""
    from coach import critics_fatigue

    last: dict[str, Any] = sessions[-1] if sessions else {}
    ident = str(last.get("identity") or last.get("template_id") or "").upper()
    series = [s for s in sessions if str(s.get("identity") or s.get("template_id") or "").upper() == ident] if ident else sessions
    window = _minus_days(target_date, STALE_HISTORY_LOOKBACK_DAYS)
    tops = [
        {
            "date": str(s.get("date") or "")[:10],
            "best_weight": s.get("best_weight"),
            "sets": [x for x in s.get("sets") or [] if x.get("weight_lbs") == s.get("best_weight")][:1],
        }
        for s in series
    ]
    dates = [str(s.get("date") or "")[:10] for s in series]
    return {"stale": critics_fatigue.stale_exposure(dates, target_date, window_start=window), "_tops": tops}


def attach_fatigue_inputs(
    evidence: dict[str, Any] | None, *, readiness_low_streak_days: int | None, block_workouts: list | None, target_date: str
) -> None:
    """#4161: stamp the evidence with what the joints critic's fatigue trigger reads — the session role of
    every completed session (THE ledger, `session_sequence`), the readiness streak, each drafted lift's
    same-role performance trend and consecutive-session soreness, and the 48 h same-region read. Pure over
    reads already made; a None block record leaves every role-dependent input unknown, never clear."""
    if evidence is None:
        return
    from coach import critics_fatigue
    from training import session_sequence

    done = session_sequence.completed_positions(block_workouts, target_date) if block_workouts is not None else None
    role_by_date = {p["date"]: p["session_role"] for p in done} if done is not None else None
    served = session_sequence.next_session(target_date, block_workouts) if target_date >= session_sequence.block_start() else None
    role = (served or {}).get("session_role")
    session_dates = sorted(role_by_date) if role_by_date is not None else []
    perf, sore = {}, {}
    for e in evidence.get("exercises") or []:
        tops = e.pop("_tops", None) or []
        perf[e["idx"]] = critics_fatigue.performance_drop(tops, role_by_date, role)
        sore[e["idx"]] = critics_fatigue.soreness_consecutive(e.get("pain_dates") or [], session_dates) if e.get("pain_flag_any") else None
    region = (served or {}).get("archetype")
    evidence["fatigue"] = critics_fatigue.assess(
        readiness_low_streak_days=readiness_low_streak_days,
        perf_by_idx=perf if role_by_date is not None else None,
        soreness_by_idx=sore,
        same_region=critics_fatigue.same_region_recent(block_workouts, target_date, region),
    )
    evidence["fatigue"]["performance"] = {i: p for i, p in perf.items() if p.get("state") != "insufficient"}


def _training_streaks(target_date: str) -> dict[str, Any]:
    """{active_day_streak, loaded_lifting_streak, …} before `target_date` (#4067).

    Hevy through `tools_strength._read_hevy_all_phases` — the ONE sanctioned Hevy read path
    (cross-phase by the taxonomy, tombstoned legacy aggregates out) — because the LOAD is in
    the sets, which `get_workouts`' slim projection drops. Strava only widens the ACTIVE
    streak. A Hevy read that raises propagates (the caller's `_safe` makes both streaks
    unknown); a Strava read that raises leaves the active streak a declared floor."""
    from training import training_streaks

    from mcp.core import query_source_range
    from mcp.strength_helpers import normalize_hevy_items
    from mcp.tools_strength import _read_hevy_all_phases

    start = _minus_days(target_date, BLOCK_LOOKBACK_DAYS)
    end = _minus_days(target_date, 1)
    items, _phases = _read_hevy_all_phases(start, end)
    hevy = normalize_hevy_items(items)
    strava = _safe(query_source_range, "strava", start, end)
    out = training_streaks.streaks(hevy, strava, target_date, window_start=start)
    out["window"] = {"start": start, "end": end}
    out["loaded_streak_role"] = "context only — no rest-day ask since #4161 (the fatigue trigger is performance or readiness)"
    return out


def _weeks_in_block(dates: list[str], target_date: str, min_per_week: int = 2, max_weeks: int = 8) -> int:
    """Trailing consecutive 7-day windows (ending the day before target) with >= min_per_week lifts."""
    weeks = 0
    for w in range(max_weeks):
        end = _minus_days(target_date, 7 * w)  # exclusive
        start = _minus_days(target_date, 7 * (w + 1))
        if len({d for d in dates if start <= d < end}) >= min_per_week:
            weeks += 1
        else:
            break
    return weeks


def _workout_dates(start: str, end: str) -> list[str]:
    """Performed lifting days, read through `get_workouts` — the SAME tool a chat turn calls.

    Deliberately not a direct partition read: a new reader of a partition another module
    writes is a new must-agree seam (#2847), and this module needs only the dates the
    existing tool already normalises."""
    from mcp.tools_hevy import tool_get_workouts

    res = tool_get_workouts({"start_date": start, "end_date": end, "source": "hevy", "limit": 500}) or {}
    return sorted({(w.get("date") or "")[:10] for w in res.get("workouts") or [] if w.get("date")})


def _loss_rate_of(reference: dict[str, Any] | None) -> tuple[float | None, bool | None]:
    """(rate lb/wk, provisional) from the reference's `loss_rate` block (#4068). A reference
    without the block (inapplicable, or an older payload) yields its bare rate, provisional
    unknown."""
    block = (reference or {}).get("loss_rate")
    if isinstance(block, dict):
        return block.get("rate_lb_wk"), block.get("provisional")
    return (reference or {}).get("current_rate_lb_wk"), None


def _anchor_trend(sessions: list[dict[str, Any]], target_date: str) -> dict[str, Any]:
    """The anchor-lift trend over ONE template identity — pure, the tripwire's only input (#4069, #4098).

    `sessions` comes from `get_exercise_history(template_id=…)`, which already selects one
    identity (a raw Hevy template id through the #3929 alias registry). This re-asserts it
    rather than trusting it: the series is cut to the identity of the LATEST session, so a
    history that ever mixed variants (the substring merge that put barbell bench and incline
    DB bench into one '-120 lb' series) compares a lift only with itself. Sessions of any
    other identity are counted in `excluded_other_identity_sessions`, never dropped silently.
    A variant switch therefore starts a NEW series — it can never read as a strength drop.

    #4098: the comparison is the redline's v3 definition — a rolling e1RM median, computed by
    `plan_engine.anchor_e1rm_trend` over each session's `best_1rm` — never the top weight with
    its reps thrown away (75 × 5 against 45 × 8 is ~87 vs ~57 lb e1RM, not "75 vs 45").
    `last_top_lbs` stays on the row for the critic's hold-to load; it is not the comparison.
    """
    from training import plan_engine

    if not sessions:
        return {}

    def _ident(s: dict[str, Any]) -> str:
        return str(s.get("identity") or s.get("template_id") or "").upper()

    ident = _ident(sessions[-1])
    series = [s for s in sessions if _ident(s) == ident]
    out: dict[str, Any] = {"identity": ident or None}
    if len(series) != len(sessions):
        out["excluded_other_identity_sessions"] = len(sessions) - len(series)
    last = series[-1]
    out["days_since"] = _days_between(last.get("date"), target_date)
    out["last_top_lbs"] = last.get("best_weight")
    out["n_sessions"] = len(series)
    out.update(plan_engine.anchor_e1rm_trend([s.get("best_1rm") for s in series]))
    return out


def _core_anchor_identities() -> dict[str, str]:
    """template identity -> core anchor family, for the four the tripwire reads (#4069).

    Built from `program_structure.ANCHORS[family]["catalog_keys"]` for `CORE_ANCHORS`, each
    key resolved READ-ONLY (`peek_template_id` — never the write-capable resolver) and mapped
    through the alias registry. A key with no known template id is simply absent; the drafted
    row can still be recognised by its catalog movement_key (`_core_anchor_family`).
    """
    from training import program_structure
    from training.hevy_template_cache import peek_template_id

    from mcp.strength_helpers import exercise_identity
    from mcp.tools_strength import template_alias_map

    alias_map, _status = template_alias_map()
    out: dict[str, str] = {}
    for family in program_structure.CORE_ANCHORS:
        for key in program_structure.ANCHORS[family]["catalog_keys"]:
            tid = _safe(peek_template_id, key)
            if tid:
                out.setdefault(exercise_identity(tid, "", alias_map), family)
                out.setdefault(str(tid).strip().upper(), family)
    return out


def _core_anchor_family(movement_key: str, identity: str | None, anchor_ids: dict[str, str]) -> str | None:
    """Which of the four core anchors a drafted lift is, by catalog key or template identity — never by name."""
    from training import program_structure

    for family in program_structure.CORE_ANCHORS:
        if movement_key and movement_key in program_structure.ANCHORS[family]["catalog_keys"]:
            return family
    return anchor_ids.get(str(identity or "").upper()) if identity else None


def _worst_anchor(evidence: dict[str, Any]) -> tuple[float | None, int | None]:
    """The engine's `anchor_lift_strength_drop` input: the worst drop among CORE-anchor rows only.

    #4069: the redline's signal names "the four core anchors (bench, row, squat, hinge)"; this
    used to take the max over EVERY drafted exercise, which is how a shoulder-press series (not a
    core anchor) reached the tripwire. Non-anchor rows keep their trend for the per-exercise critic.
    """
    rows = [e for e in evidence.get("exercises", []) if e.get("drop_pct") is not None and e.get("anchor_family")]
    if not rows:
        return None, None
    w = max(rows, key=lambda e: e["drop_pct"])
    return w["drop_pct"], w.get("sessions_below")
