"""tools_plan.py — one server-side planning surface, so the client stops deciding (#3751, #3752).

Before this, asking for tomorrow's session over chat/MCP got you fourteen data tools and
whatever rigor that one turn happened to bring. The structured procedure existed only in
`.claude/skills/daily-debrief/SKILL.md`, which only Claude Code runs. Same owner, same
data, same question, two different answers depending on which app he opened.

STAGE 1 — `plan_next_session()` is the deterministic stage (`training.plan_engine`)
reachable from every client. It gathers the same inputs the debrief skill enumerates,
computes the constraint block with no model in the loop, and returns it — with what the
evidence cannot support stated in the payload rather than left to the caller's discipline.

Its pain-flag evidence set is the movements he PERFORMED in the trailing
`PAIN_LOOKBACK_DAYS` (#4051), read from the Hevy partition cross-phase, unioned with a
draft's exercise list when one exists. It used to be the draft's list ALONE, so on a day
with no draft the set was empty and a live, owner-dismissed pain flag read `clear`.
`_gather_performed_evidence` also states the scope it examined, and `clear` is now
reachable only from a scope that was read and named at least one movement.

STAGE 2 — `plan_next_session(routine_id=...)` is the red team (#3752). Four critics —
`coach.critics` — each get a DISJOINT evidence packet assembled here from the same readers
a chat turn would call, each make ONE model call, and each return approve / change <field>
to <value> / veto with the number they argued from. Changes are applied to the draft and
the revised draft is re-checked deterministically; the verdicts are stored on the routine
(`inputs_snapshot["critics"]`), where `manage_hevy_routine` reads them: a veto blocks the
commit and the verdicts ride into the Hevy notes. A thread row goes to the training coach.

THE OWNER OVERRIDE — `plan_next_session(routine_id=..., veto_override={critic, owner_words})`
(#4076). A veto used to leave two exits: redraft, or skip stage 2 — and skipping stage 2
also threw away every other critic's change. The override re-runs stage 2 as normal and then
marks ONLY the named critic's veto overridden, with his words verbatim, after writing them
to the corrections ledger (the `log_coach_correction` write path). Every other critic's
change is applied exactly as without it; another critic's veto still blocks.

The model calls are tier-gated by `budget_guard` (feature `plan_critics`). When paused,
the deterministic layer still runs and every verdict says the model did not — a routine is
never reported as red-teamed by a model that was not consulted.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common.pacific_time import pacific_today
from training.commit_binding import binding_for  # #4066

from mcp.core import LAYER_UNKNOWN
from mcp.plan_draft_evidence import ANCHOR_HISTORY_LOOKBACK_DAYS, BLOCK_LOOKBACK_DAYS, PAIN_LOOKBACK_DAYS  # noqa: F401 (#4161)
from mcp.plan_helpers import _catalog_and_ceiling, _days_between, _minus_days, _resolver, _safe, _union_evidence_rows  # noqa: F401 (#4149)
from mcp.plan_hevy_windows import _block_workouts, _prescription_window, _rotation_window  # noqa: F401  (#4110 size fix)

logger = logging.getLogger("tools_plan")

STREAK_LOOKBACK_DAYS = 14
# #4051: the stage-1 pain-evidence set is the movements PERFORMED in the trailing
# PAIN_LOOKBACK_DAYS — the same window the note layer is read over, deliberately ONE number.
# The cap is a latency bound, not a semantic one: 27 distinct templates is a live 28-day
# week-and-a-half, so a set that exceeds this is an anomaly and the scope says it truncated
# rather than silently dropping the tail.
PERFORMED_MOVEMENT_CAP = 80


# A tool's `{"error": ...}` that means "the window is empty", not "the read broke" (#4072).
_NO_DATA_ERROR = re.compile(r"\bno\b[^.]{0,40}\b(data|records?|rows?|entries)\b", re.IGNORECASE)


class InputShapeError(Exception):
    """A reader returned, but with none of the keys it is known to carry (#4072).

    This is the 2026-09-15..18 defect's class: `get_readiness_score` returned
    `readiness_score` while the planner read `score`/`recovery_score`, so a fresh source
    read `unknown`. A succeeded read with the wrong shape is a FAILED read, not an absent one.
    """


def _read(name: str, fn, *a, **kw) -> tuple[Any, dict[str, Any]]:
    """(value, input status) — `_safe`, but the failure is KEPT (#4072).

    A raise is `read_failed` with its error class; a tool's own `{"error": ...}` return is
    `read_failed` (`ToolError`) with the value dropped, because an error dict is not data.
    Success is reported `measured`; the caller downgrades to `absent` when the value it
    extracts is empty, since only the caller knows which key the answer lives under.
    """
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED, error_label, input_status

    try:
        value = fn(*a, **kw)
    except Exception as e:  # noqa: BLE001 — reported in the block, never swallowed (#4072)
        logger.warning("plan_next_session input %s read failed: %s", name, e)
        return None, input_status(READ_FAILED, error=error_label(e))
    if isinstance(value, dict) and value.get("error") and len(value) <= 3:
        msg = str(value.get("error"))
        if _NO_DATA_ERROR.search(msg):
            # the tool's own words for an empty window ("No MacroFactor data") — an absence
            return None, input_status(ABSENT, f"the tool reported no data: {msg[:160]}")
        return None, input_status(READ_FAILED, error=f"ToolError: {msg[:180]}")
    return value, input_status(MEASURED)


def _load_anchor_indexes() -> tuple[dict[str, list], dict[str, float]]:
    """(Hevy history index, bodyweight index) — the two reads the band anchor needs (#4090)."""
    from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_bodyweight_index, load_history_indexes

    return load_history_indexes(lookback_days=max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS))[0], load_bodyweight_index()


def _attach_session_loads(block: dict[str, Any], target_date: str, catalog_movements: dict[str, Any] | None) -> None:
    """#4090: stamp the scheduled v0.3 session's exposures with their entry-ramp loads — the
    same `load_ramp.v03_floor` the draft writes (#4107: anchor -> nearest-band fallback -> ramp). A failed
    read is reported by name on `session.loads`, never as an unloaded session."""
    session = (block or {}).get("session") or {}
    rx = session.get("prescription")
    if not rx:
        return
    from training.load_ramp import annotate_prescription

    indexes, status = _read("session_loads", _load_anchor_indexes)
    if indexes is None:
        session["loads"] = {"status": status.get("state"), "error": status.get("error")}
        return
    history, weights = indexes
    session["loads"] = annotate_prescription(rx, catalog_movements, history, weights, target_date=target_date, week=session.get("week"))


def _readiness_low_streak(target_date: str) -> tuple[int | None, dict[str, Any]]:
    """(consecutive days below the readiness_floor threshold, input status) — from Whoop (#4072).

    WHY THIS EXISTS: before #4072 NOTHING supplied `readiness_low_streak_days`. Stage 1 never
    passed it, so the `readiness_floor` row read `unknown — "no recovery series"` on every
    call, on every day, with the Whoop partition fresh (live read 2026-09-22: daily
    `recovery_score` rows 2026-08-25..2026-09-22, no gap). The detail was a claim about the
    data that the engine had never checked.

    The tripwire's signal is Whoop recovery (owner_redlines, v3), so this reads the whoop
    partition directly, cross-phase (`query_source_cross_phase` — whoop is a raw timeseries,
    and a 14-day window from mid-September reaches the pre-genesis `phase=pilot` rows the
    default filter hides). Only the DAILY rows count (`sk == DATE#<day>`) — the same
    partition carries `DATE#<day>#WORKOUT#<id>` rows with no recovery score.

    The streak is counted back from the LATEST measured day; a calendar day with no row
    breaks it (an unmeasured day is not a low day). v3 names a 7-day MEAN < 50; the engine
    computes the simpler consecutive-days proxy, as `owner_redlines` already says.
    """
    from common.digest_utils import filter_day_rows
    from training import owner_redlines
    from training.plan_engine import ABSENT, MEASURED, input_status

    from mcp.core import query_source_cross_phase

    t = next(x for x in owner_redlines.TRIPWIRES if x["id"] == "readiness_floor")
    threshold = float(t["threshold"])
    start = _minus_days(target_date, STREAK_LOOKBACK_DAYS)
    rows = query_source_cross_phase("whoop", start, target_date) or []
    daily = filter_day_rows(rows)  # the #3442 predicate: drops DATE#<day>#WORKOUT#<id> sub-records
    by_day: dict[str, float] = {}
    for r in daily:
        if r.get("recovery_score") is None:
            continue
        try:
            by_day[str(r["sk"])[len("DATE#") :]] = float(r["recovery_score"])
        except (TypeError, ValueError):
            continue
    window = {"start": start, "end": target_date, "days": STREAK_LOOKBACK_DAYS}
    if daily and not by_day:
        # Daily rows exist and none carries a usable `recovery_score`: the writer's shape moved
        # (#2847 seam — whoop_lambda writes, this reads). That is a FAILED read, never an absent one.
        raise InputShapeError(
            f"{len(daily)} Whoop daily row(s) in {start}..{target_date} and none carries a numeric recovery_score "
            f"(keys: {sorted(daily[-1])[:12]})"
        )
    if not by_day:
        return None, input_status(
            ABSENT, f"no Whoop daily recovery_score row in {start}..{target_date}", source="whoop", window=window, n_days=0
        )
    latest = max(by_day)
    streak, day = 0, latest
    while day in by_day and by_day[day] < threshold:
        streak += 1
        day = _minus_days(day, 1)
    return streak, input_status(
        MEASURED,
        f"{len(by_day)} Whoop recovery day(s) read; latest {latest} = {by_day[latest]:g}; streak counted back from {latest}",
        source="whoop",
        window=window,
        n_days=len(by_day),
        latest_day=latest,
        threshold=threshold,
        phases_read=sorted({str(r.get("phase") or "unstamped") for r in daily}),
    )


def _walking_volume_last_7d(end_date: str) -> dict[str, Any] | None:
    """The derived walking-volume layer for the week BEFORE `end_date`'s session (#3930, #4068).

    A union of Strava and Hevy cardio blocks (#3930), de-duplicated in time across devices and
    against Hevy sessions, over the 7 COMPLETED days before the session — all of it defined
    ONCE in `mcp.shared_quantities`, which the nutrition critics and `get_benchmark` read too.
    The window used to END on the target day: a plan for 09-23 read 09-17..09-23 on 09-22 and
    reported 12.82 h beside the adherence critic's 15.82 h for the same week (#4068).

    Hours, not miles and not steps: the blueprint's floor is stated in hours per week.
    """
    from common.pacific_time import shift_day_key

    from mcp import shared_quantities

    return shared_quantities.walking_layer(shift_day_key(end_date, -1))


def _pain_dismissals() -> list[dict[str, Any]]:
    """The owner's pain-flag dismissals (#4036), read from the ONE store that holds them.

    Read through `mcp.tools_training_notes` rather than re-querying the partition here: the
    write and the read share a module, so a change to the key scheme cannot leave a second,
    stale reader behind. A raise propagates — `_safe` turns it into None at the call site,
    which the engine reports as "not read", never as "no dismissals".
    """
    from mcp.tools_training_notes import _dismissal_records

    return _dismissal_records()


def _training_memory_constraints() -> list[dict[str, Any]]:
    """Standing training constraints written from chat (the RDL gate, a toe flag, a back
    flag — #4077) via `write_platform_memory(category='training')`. Read through the SAME
    tool a chat write would have used — `tool_read_platform_memory` — so the category
    registry (`ai.platform_memory.MEMORY_CATEGORIES`) stays the one place this taxonomy is
    validated. A raise (or the tool's own `{"error": ...}` shape) propagates; `_read`
    reports it `read_failed`, never silently as "no constraints"."""
    from mcp.tools_memory import tool_read_platform_memory

    resp = tool_read_platform_memory({"category": "training", "days": 730, "limit": 20})
    if resp.get("error"):
        raise RuntimeError(resp["error"])
    return resp.get("records") or []


def _performed_movements(target_date: str) -> tuple[list[dict[str, Any]], list[str], str, int]:
    """(rows, phases_read, window_start, blocks_without_template_id) — what he actually did (#4051).

    The distinct movements PERFORMED in the trailing `PAIN_LOOKBACK_DAYS`, newest first, read
    through `tools_strength._read_hevy_all_phases` — the ONE sanctioned Hevy read path
    (#4030/#4032). Two things that path buys and a plain `query_source_range("hevy", …)`
    does not: the phase filter comes off because `phase_filter.source_reads_cross_phase`
    DERIVES that from the taxonomy (never a hand-typed `include_pilot`), and the 421
    tombstoned legacy daily aggregates stay out, so no pre-2025-11-08 session is counted
    twice. Read the docstring there before changing this.

    Keyed by `template_id` because that is the handle the derived note layer is keyed by —
    a block with no template id can carry no flag, so it is counted and reported rather than
    silently dropped. The most recent spelling of a template's name wins, because that name
    is what the dismissal record's `movement_keys` are matched against.
    """
    from mcp.strength_helpers import normalize_hevy_items
    from mcp.tools_strength import _read_hevy_all_phases

    start = _minus_days(target_date, PAIN_LOOKBACK_DAYS)
    items, phases = _read_hevy_all_phases(start, target_date)
    by_tid: dict[str, dict[str, Any]] = {}
    orphan_blocks = 0
    for w in normalize_hevy_items(items):
        day = str(w.get("date") or "")[:10]
        if not day or day > target_date:
            continue
        for ex in w.get("exercises") or []:
            tid = str(ex.get("template_id") or "").strip()
            name = str(ex.get("name") or "").strip()
            if not tid or not name:
                orphan_blocks += 1
                continue
            row = by_tid.setdefault(tid, {"label": name, "template_id": tid, "last_performed": day, "sessions": 0})
            row["sessions"] += 1
            if day >= row["last_performed"]:
                row["last_performed"] = day
                row["label"] = name
    rows = sorted(by_tid.values(), key=lambda r: (r["last_performed"], r["label"]), reverse=True)
    for r in rows:
        r["days_since"] = _days_between(r["last_performed"], target_date)
    return rows, phases, start, orphan_blocks


def _gather_performed_evidence(target_date: str, layer_status: str) -> dict[str, Any]:
    """The stage-1 pain-evidence set: every movement he PERFORMED, with its flags (#4051).

    This is the input stage 1 never had. `_gather_draft_evidence` builds the same shape from
    a DRAFT's exercise list, which is empty before a draft exists and incomplete after one
    (a drafted upper-body session cannot show the flag on a lift it omits) — so this set is
    gathered on EVERY call and unioned with the draft's, never instead of it.

    Raises if the Hevy read raises; the caller wraps it in `_safe` and reports the scope
    unreadable, because an unread partition is not an empty one.
    """
    from mcp.tools_training_notes import pain_flags_for_templates

    rows, phases, start, orphans = _performed_movements(target_date)
    considered = rows[:PERFORMED_MOVEMENT_CAP]
    truncated = len(rows) - len(considered)
    # #3769: the layer's status is resolved ONCE by the caller and rides on every entry the
    # batch read returns — no count from a derived layer travels without its status.
    flags = pain_flags_for_templates([r["template_id"] for r in considered], start, layer_status)
    unreadable = 0
    for r in considered:
        f = flags.get(r["template_id"]) or {}
        if f.get("error"):
            unreadable += 1
            r["pain_flag_any"] = None
            r["pain_dates"] = []
            r["pain_read_error"] = f["error"]
            continue
        r["pain_flag_any"] = bool(f.get("pain_flag_any"))
        r["pain_dates"] = f.get("pain_dates") or []
        r["sessions_with_notes"] = f.get("sessions_with_notes")
    scope = {
        # `read` is the only value `plan_engine._evidence_scope_read` accepts, and it also
        # requires movements_considered > 0 — a successful read of an empty window is still
        # "nothing was examined", which is the state that produced this defect.
        "status": "read",
        "source": "hevy",
        "derivation": "movements PERFORMED in the window, cross-phase per #4030/#4032 (taxonomy-derived, tombstones excluded)",
        "window": {"start": start, "end": target_date, "days": PAIN_LOOKBACK_DAYS},
        "phases_read": phases,
        "movements_considered": len(considered),
        "movements_flagged": sum(1 for r in considered if r.get("pain_flag_any")),
        "note_layer_status": layer_status,
        "reason": (
            f"{len(considered)} movement(s) performed in {start}..{target_date} were checked against the derived note layer"
            if considered
            else f"no Hevy session in {start}..{target_date} — no movement was performed to check against the note layer"
        ),
    }
    if not considered:
        scope["status"] = "none"
    if truncated:
        scope["truncated_movements"] = truncated
    if orphans:
        scope["blocks_without_template_id"] = orphans
    if unreadable:
        scope["unreadable_movements"] = unreadable
    return {"exercises": considered, "scope": scope}


def _merge_walking_volume(block: dict[str, Any], layer: dict[str, Any] | None) -> None:
    """Put the per-source breakdown on the block's walking read, beside the total (#3930).

    The engine computes state/gap from one number. That number is now a union of two sources,
    and a union whose parts you cannot see is exactly the shape that produced the wrong flag
    in the first place — so the breakdown, the counting rule, the overlap ruling and the
    steps exclusion all travel WITH the verdict rather than in a separate payload a caller
    may not read. The engine keeps its single-float contract; this is presentation.
    """
    w = block.get("walking")
    if not isinstance(w, dict):
        return
    if not layer:
        w["sources"] = {"status": "unreadable", "detail": "the walking-volume layer could not be built for this window"}
        return
    w["sources"] = layer["by_source"]
    w["by_modality"] = layer["by_modality"]
    w["counted_modalities"] = layer["counted_modalities"]
    w["counting_rule"] = layer["counting_rule"]
    w["overlap_rule"] = layer["overlap_rule"]
    w["excluded_proxies"] = layer["excluded_proxies"]
    w["derived_steps_estimate"] = layer["derived_steps_estimate"]
    w["window"] = layer["window"]
    w["volume_layer"] = layer["version"]
    w["total_is_floor"] = layer["total_is_floor"]
    if layer["honesty"]:
        w["honesty"] = list(layer["honesty"])


def _protein_days_7d(end_date: str) -> tuple[int | None, int | None]:
    """(days below the owner's protein floor, days measured) over THE protein-gate window for a plan on
    `end_date` (#4161: `owner_redlines.protein_window` — the 7 COMPLETED days ending the day before the
    plan and never after yesterday, the same window the nutrition critics' deficit advocate reads).

    Counts only days MacroFactor logged — an unlogged day is not a missed day, it is an
    unmeasured one, and the measured count travels with the answer so 0-of-2 is never
    read as 0-of-7 (ADR-104).
    """
    from training import owner_redlines

    from mcp.tools_nutrition import tool_get_nutrition

    win = owner_redlines.protein_window(end_date, pacific_today())
    res = tool_get_nutrition({"view": "summary", "start_date": win["start"], "end_date": win["end"]}) or {}
    if isinstance(res, dict) and res.get("error"):
        if _NO_DATA_ERROR.search(str(res.get("error"))):
            return None, None  # "No MacroFactor data" is an empty window, not a broken read
        raise RuntimeError(f"get_nutrition returned an error: {str(res.get('error'))[:160]}")
    # LIVE SHAPE (2026-09-20): the summary view returns `daily_breakdown`, not `daily_rows`. The
    # first deployed stage-2 run read the wrong key and reported protein UNKNOWN on a week with
    # six logged days — the #3767 class this module's own comment claims to have checked.
    if res and "daily_breakdown" not in res and "daily_rows" not in res:
        # #4072: a non-empty return with neither key is a shape change, not an empty week.
        raise InputShapeError(f"get_nutrition summary carried neither daily_breakdown nor daily_rows (keys: {sorted(res)[:12]})")
    missed, measured = owner_redlines.protein_days_missed(
        [r.get("protein_g") for r in (res.get("daily_breakdown") or res.get("daily_rows") or [])]
    )
    return (missed, measured) if measured else (None, None)  # #4161: THE count, shared with the nutrition critics


def tool_plan_next_session(args):
    """Stage 1: the deterministic constraint block (#3751). Stage 2, with `routine_id`: the
    four critics over disjoint evidence, verdicts stored on the draft (#3752)."""
    args = args or {}
    target_date = args.get("target_date") or pacific_today()
    routine_id = args.get("routine_id")

    from training import accessory_strength_trend, plan_engine

    # #4076: the owner override is parsed BEFORE anything runs — a malformed one is an error,
    # never a stage-2 run that silently ignored it and left the veto standing unexplained.
    overrides: list[dict[str, Any]] = []
    if args.get("veto_override") not in (None, [], {}):
        from coach.critic_overrides import parse_overrides

        from mcp.utils import mcp_error

        if not routine_id:
            return mcp_error("veto_override needs routine_id — it overrides a stage-2 veto on that routine", error_code="MISSING_ARG")
        overrides, err = parse_overrides(args.get("veto_override"))
        if err:
            return mcp_error(err, error_code="INVALID_ARG")

    # Each reader is the SAME tool a chat turn would have called — the point is not new
    # data, it is that the call set is fixed instead of improvised per conversation.
    from mcp.tools_benchmark import tool_get_benchmark
    from mcp.tools_health import tool_get_readiness_score
    from mcp.tools_strength import tool_get_muscle_volume
    from mcp.tools_training import tool_get_acwr_status

    ir = None
    if routine_id:
        from training.routine_repo import get_current

        from mcp.utils import mcp_error

        ir = _safe(get_current, routine_id)
        if not ir:
            return mcp_error(
                f"routine_id={routine_id} not found — draft it first (manage_hevy_routine draft_custom)", error_code="NOT_FOUND"
            )

    # #4072: every reader reports HOW it came back — measured / absent / read_failed (with the
    # error class) — so a None the engine receives is never ambiguous. Before this, `_safe`
    # turned a raise into None and the engine printed `unknown`, the word it also uses for an
    # empty window; on 2026-09-15..18 that is what the owner was shown with every source fresh.
    status: dict[str, dict[str, Any]] = {}
    ABSENT, READ_FAILED, NOT_READ = plan_engine.ABSENT, plan_engine.READ_FAILED, plan_engine.NOT_READ
    st = plan_engine.input_status

    reference, status["reference"] = _read("reference", tool_get_benchmark, {"view": "prescription", "date": target_date})
    if isinstance(reference, dict) and reference.get("applicable") is False:
        # An inapplicable reference is not a reference. Carry the reason, drop the shape.
        status["reference"] = st(ABSENT, f"no applicable weight-matched reference: {reference.get('reason')}")
        reference = {"proven_target": None, "_inapplicable_reason": reference.get("reason")}

    weight = None
    if isinstance(reference, dict):
        weight = reference.get("current_weight")
    status["weight_lb"] = (
        dict(status["reference"])
        if status["reference"]["state"] == READ_FAILED
        else (
            st(plan_engine.MEASURED, "from the benchmark prescription")
            if weight is not None
            else st(ABSENT, "the benchmark carried no current_weight")
        )
    )

    readiness, status["recovery_tier"] = _read("recovery_tier", tool_get_readiness_score, {"date": target_date})
    readiness = readiness or {}
    recovery_tier = _recovery_tier(readiness)
    if recovery_tier is None and status["recovery_tier"]["state"] != READ_FAILED:
        status["recovery_tier"] = (
            st(ABSENT, "get_readiness_score returned no score for the day")
            if (not readiness or any(k in readiness for k in _READINESS_SCORE_KEYS))
            else st(
                READ_FAILED,
                error=f"InputShapeError: get_readiness_score carried none of {list(_READINESS_SCORE_KEYS)} (keys: {sorted(readiness)[:12]})",
            )
        )

    acwr, status["acwr_flag"] = _read("acwr_flag", tool_get_acwr_status, {})
    acwr = acwr or {}
    acwr_flag = acwr.get("zone") or acwr.get("alert_reason")
    if acwr_flag is None and status["acwr_flag"]["state"] != READ_FAILED:
        status["acwr_flag"] = st(ABSENT, "get_acwr_status returned no zone")

    # #4071: the 28 COMPLETED days before the session — target-28..target-1 inclusive, exactly
    # 4.0 weeks. The per-muscle numbers are `training.muscle_volume.working_sets_by_muscle`'s,
    # through the tool — this module computes none of its own (derivation guard, #4071).
    volume, status["muscle_volume"] = _read(
        "muscle_volume", tool_get_muscle_volume, {"start_date": _minus_days(target_date, 28), "end_date": _minus_days(target_date, 1)}
    )
    volume = volume or {}
    muscle_sets = _muscle_sets(volume)
    if not muscle_sets and status["muscle_volume"]["state"] != READ_FAILED:
        status["muscle_volume"] = (
            st(ABSENT, "no lifting volume in the trailing 28 days")
            if (not volume or any(k in volume for k in _VOLUME_TABLE_KEYS))
            else st(
                READ_FAILED,
                error=f"InputShapeError: get_muscle_volume carried none of {list(_VOLUME_TABLE_KEYS)} (keys: {sorted(volume)[:12]})",
            )
        )

    protein_pair, status["protein_days_missed_7d"] = _read("protein_days_missed_7d", _protein_days_7d, target_date)
    protein_missed, protein_measured = protein_pair or (None, None)
    if protein_missed is None and status["protein_days_missed_7d"]["state"] != READ_FAILED:
        status["protein_days_missed_7d"] = st(ABSENT, "no MacroFactor day with protein logged in the trailing 7 days")

    # #4072: the readiness_floor tripwire's input. Nothing supplied it before this change.
    streak_pair, streak_status = _read("readiness_low_streak_days", _readiness_low_streak, target_date)
    readiness_streak, status["readiness_low_streak_days"] = streak_pair if streak_pair else (None, streak_status)

    # The pain tripwire reads the derived note layer; its STATUS decides whether silence
    # means anything (#3767/#3768). Absent a per-movement query here, the layer's own
    # health is the honest input, and `unknown` is the honest default.
    layer_status = LAYER_UNKNOWN
    status["pain_layer_status"] = st(plan_engine.MEASURED)
    try:
        from training.training_notes import training_notes_health

        from mcp.config import table
        from mcp.core import derived_layer_status

        layer_status = derived_layer_status(training_notes_health(table))[0]
    except Exception as e:  # noqa: BLE001
        status["pain_layer_status"] = st(READ_FAILED, error=plan_engine.error_label(e))

    # #4036: the owner-dismissal layer, read beside the flag layer. A raise yields None, which
    # is NOT an empty list: the engine must never read an unreadable dismissal store as "he
    # has dismissed nothing".
    dismissals, status["pain_dismissals"] = _read("pain_dismissals", _pain_dismissals)
    if dismissals == [] and status["pain_dismissals"]["state"] != READ_FAILED:
        status["pain_dismissals"] = st(ABSENT, "no owner dismissal on file")

    # #4077: standing training constraints (RDL gate, toe flag, back flag, …) written from
    # chat via write_platform_memory(category='training') — the durable home that category
    # used to reject outright.
    training_memory, status["training_memory_constraints"] = _read("training_memory_constraints", _training_memory_constraints)
    if training_memory == [] and status["training_memory_constraints"]["state"] != READ_FAILED:
        status["training_memory_constraints"] = st(ABSENT, "no training constraint recorded in platform memory (category='training')")

    evidence = _gather_draft_evidence(ir, target_date, layer_status) if ir is not None else None
    worst = _worst_anchor(evidence) if evidence else (None, None)
    if evidence is None:
        status["anchor_lift_drop_pct"] = st(NOT_READ, "stage 1 without a draft reads no anchor-lift trend — pass routine_id")
    elif worst[0] is None:
        status["anchor_lift_drop_pct"] = st(ABSENT, "no drafted lift has enough history for a band-matched comparison")
    else:
        status["anchor_lift_drop_pct"] = st(plan_engine.MEASURED)
    for name in ("weight_stall_days", "adherence_on_plan"):
        status[name] = st(NOT_READ, "no reader is wired for this input yet — the weight_stall_with_adherence tripwire cannot evaluate")

    # #4051: the evidence set stage 1 never had — every movement PERFORMED in the trailing
    # window, with the note layer's flags for each. Gathered on EVERY call (a draft's
    # exercise list cannot show a flag on a lift the draft omits) and UNIONED with the
    # draft's rows below. A raise is reported `read_failed` with its error class (#4072) —
    # never as "he performed nothing", and never as a bare unknown.
    performed, performed_status = _read("pain_evidence_scope", _gather_performed_evidence, target_date, layer_status)
    pain_scope = (performed or {}).get("scope") or {
        "status": READ_FAILED if performed_status["state"] == READ_FAILED else "none",
        "source": "hevy",
        "movements_considered": None,
        "note_layer_status": layer_status,
        "error": performed_status.get("error"),
        "reason": (
            f"the Hevy partition could not be read for {_minus_days(target_date, PAIN_LOOKBACK_DAYS)}..{target_date} — "
            "the performed-movement set is unknown, not empty"
            if performed_status["state"] == READ_FAILED
            else "the performed-movement reader returned no scope"
        ),
    }
    if performed_status["state"] == READ_FAILED:
        status["pain_evidence_scope"] = performed_status
    elif pain_scope.get("status") == "read":
        status["pain_evidence_scope"] = st(plan_engine.MEASURED, pain_scope.get("reason"))
    else:
        status["pain_evidence_scope"] = st(ABSENT, pain_scope.get("reason"))
    rows = _union_evidence_rows((performed or {}).get("exercises") or [], (evidence or {}).get("exercises") or [])
    flagged = [r for r in rows if r.get("pain_flag_any")]

    # #3930: the walking read is a UNION layer (Strava + Hevy treadmill/cycling blocks), not a
    # Strava-only number. The engine takes the total in hours — the floor's own unit — and the
    # per-source breakdown is merged onto the block below so no reader has to trust the total.
    walk_layer, status["walk_hr_wk_now"] = _read("walk_hr_wk_now", _walking_volume_last_7d, target_date)
    if status["walk_hr_wk_now"]["state"] != READ_FAILED and (walk_layer or {}).get("total_hr") is None:
        srcs = (walk_layer or {}).get("by_source") or {}
        if srcs and all((b or {}).get("status") == "unreadable" for b in srcs.values()):
            status["walk_hr_wk_now"] = st(READ_FAILED, error="SourceReadError: neither Strava nor Hevy could be read for the window")
        else:
            status["walk_hr_wk_now"] = st(ABSENT, "no walking/treadmill/cycling duration recorded in the trailing 7 days")

    # #3755: the performed Hevy record over the program's rotation window, so the engine
    # can COMPUTE whether the accessory layer is holding still (v0.3: fixed for the block) instead of assuming the pool.
    rotation_pair, status["hevy_workouts_rotation_window"] = _read("hevy_workouts_rotation_window", _rotation_window, target_date)
    rotation_start, rotation_rows = rotation_pair or (None, None)
    if rotation_rows is None and status["hevy_workouts_rotation_window"]["state"] != READ_FAILED:
        status["hevy_workouts_rotation_window"] = st(ABSENT, "the rotation window could not be derived from the target date")
    elif rotation_rows == []:
        status["hevy_workouts_rotation_window"] = st(ABSENT, "no Hevy session in the rotation window")

    # #4081: self_added_volume rows, each with its stored programmed-vs-performed counts.
    prescription_rows, status["hevy_workouts_prescription_window"] = _read(
        "hevy_workouts_prescription_window", _prescription_window, target_date
    )
    if prescription_rows is None and status["hevy_workouts_prescription_window"]["state"] != READ_FAILED:
        status["hevy_workouts_prescription_window"] = st(ABSENT, "the prescription window could not be derived from the target date")
    elif prescription_rows == []:
        status["hevy_workouts_prescription_window"] = st(ABSENT, "no Hevy session in the prescription window")

    # #4064: the movement catalog, so the block's `session` names MOVEMENTS, not only patterns.
    # Read through the generator's own loader (local config, then S3) — the same catalog the
    # draft will be built from. A read that raises leaves the session pattern-level and says so.
    catalog_movements, skill_ceiling = _catalog_and_ceiling()

    # #4110: the session and the program week follow the COMPLETED sessions since the block
    # start, not the weekday — so the Hevy record since then is an engine input of its own.
    block_workouts, status["block_workouts"] = _read("block_workouts", _block_workouts, target_date)
    if block_workouts == [] and status["block_workouts"]["state"] != READ_FAILED:
        status["block_workouts"] = st(ABSENT, "no Hevy session since the program's block start")

    attach_fatigue_inputs(evidence, readiness_low_streak_days=readiness_streak, block_workouts=block_workouts, target_date=target_date)
    block = plan_engine.constraint_block(
        date=target_date,
        catalog_movements=catalog_movements,
        skill_ceiling=skill_ceiling,
        weight_lb=weight,
        walk_hr_wk_now=(walk_layer or {}).get("total_hr"),
        # Key names verified against each tool's live return shape rather than assumed —
        # a planner reading a key that does not exist degrades to "unknown" silently,
        # which is the #3767 failure wearing different clothes.
        recovery_tier=recovery_tier,
        # LIVE SHAPES (2026-09-20, read off the deployed tools, not assumed): get_acwr_status
        # carries the flag as `zone` (`alert` is a bool that is False when safe, so `alert or
        # interpretation` returned the METHODOLOGY PROSE as the flag); get_muscle_volume keys its
        # per-muscle table as `muscle_volume`, each row with `total_sets` / `avg_sets_per_week`.
        acwr_flag=acwr_flag,
        muscle_volume=muscle_sets,
        # #4051: performed UNION drafted, so the day with no draft is no longer the day with
        # no movements — `days_since_movement` is non-empty whenever a session is in the window.
        days_since_movement={r["label"]: r["days_since"] for r in rows if r.get("days_since") is not None},
        reference=reference if isinstance(reference, dict) else None,
        protein_days_missed_7d=protein_missed,
        protein_days_measured_7d=protein_measured,  # #4161 ruling "B": the rate target's protein gate
        protein_window=plan_engine.owner_redlines.protein_window(target_date, pacific_today()),
        readiness_low_streak_days=readiness_streak,
        anchor_lift_drop_pct=worst[0],
        anchor_lift_drop_sessions=worst[1],
        pain_flag_sites=[r["label"] for r in flagged],
        # #4036: the flag's own note dates travel with it, because the owner-dismissal rule
        # is a DATE comparison — a flag with no readable date can never read as dismissed.
        pain_flag_instances=[{"movement": r["label"], "note_dates": r.get("pain_dates") or []} for r in flagged],
        pain_dismissals=dismissals,
        # #4051: what was examined, so `clear` is only reachable from a set that was read.
        pain_evidence_scope=pain_scope,
        # with a draft in hand the per-movement note reads report the layer's status themselves
        pain_layer_status=((evidence or {}).get("pain_layer_status") or layer_status),
        hevy_workouts_rotation_window=rotation_rows,
        rotation_window_start=rotation_start,
        hevy_workouts_prescription_window=prescription_rows,
        block_workouts=block_workouts,
        training_memory_constraints=training_memory,
        input_status=status,
    )
    _merge_walking_volume(block, walk_layer)
    _attach_session_loads(block, target_date, catalog_movements)
    # #4112: the accessory half of the two-tier trend split — tracked/reported, never a
    # change/veto flag. Reads the SAME per-exercise rows `_worst_anchor` already built above.
    accessory_strength_trend.attach(block, evidence)

    out: dict[str, Any] = {
        "target_date": target_date,
        "constraint_block": block,
        "protein_days_measured_7d": protein_measured,
        "how_to_use": (
            "Stage 1 is the deterministic constraint block. `constraint_block.session` is the NEXT UNDONE session "
            f"of the v{plan_engine.program_structure.PROGRAM_VERSION} sequence (its position, and the completed session that advanced it, #4110) with its prescription — "
            "start from it. Draft against the block, then say plainly which constraint "
            "shaped which choice. Every line under `reference.must_say` is required in the answer, verbatim in "
            "substance, not summarised away. Then draft (manage_hevy_routine draft_custom) and call this tool again "
            "WITH routine_id — stage 2, the red team (#3752). A routine that skipped stage 2 is NOT red-teamed and "
            "its commit says so."
        ),
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }
    # #3754 boxes 3+4: the nutrition critics ride beside the constraint block on the daily
    # surface the owner reads — the same block get_deficit_sustainability carries, built by
    # the same resolver, so the two surfaces cannot disagree. Owner-only (MCP), never a site
    # or email surface.
    out["nutrition_critics"] = _safe(_nutrition_critics_block) or {"error": "nutrition critics could not be built", "verdicts": []}
    if ir is None:  # #4084: the overnight pre-draft comes FIRST — the evening chat reviews it instead of rebuilding
        from mcp.nightly_predraft import attach_to_stage_1

        attach_to_stage_1(out, target_date)
    if ir is not None:
        out["critics"] = _run_stage_2(
            ir,
            block,
            reference if isinstance(reference, dict) else None,
            evidence,
            protein_missed,
            protein_measured,
            target_date,
            dismissals,
            overrides=overrides,
        )
        out["how_to_use"] = (
            "Stage 2 ran. Read `critics.verdicts` — each names the metric and number it argued from. A `veto` blocks "
            "commit: redraft and run stage 2 again, or — if Matthew overrules that one critic — run stage 2 again with "
            "veto_override={critic, owner_words} carrying his words verbatim (#4076); every other critic's changes still "
            "apply. `change` verdicts are already applied to the draft (see `critics.changes`); dry_run shows the revised "
            "body. Then commit — the verdicts, and any override, ride in the Hevy notes."
        )
    return out


def _nutrition_critics_block() -> dict[str, Any]:
    """The #3754 block from `get_deficit_sustainability` (one call, its own window ending on the
    latest COMPLETE nutrition day). When that tool refuses (fewer than 7 logged days) the
    resolver still runs, with the deficit tool's own severity named unknown."""
    from mcp import nutrition_critics_inputs
    from mcp.tools_nutrition import _nutrition_through_date, tool_get_deficit_sustainability

    res = _safe(tool_get_deficit_sustainability, {})
    if isinstance(res, dict) and isinstance(res.get("critics"), dict):
        block = dict(res["critics"])
        block["via"] = "get_deficit_sustainability"
        return block
    block = nutrition_critics_inputs.block(_nutrition_through_date())
    block["via"] = (
        "resolver (get_deficit_sustainability unavailable: "
        + str((res or {}).get("error") if isinstance(res, dict) else "raised")[:120]
        + ")"
    )
    return block


# ── stage 2 evidence — extracted to `mcp.plan_draft_evidence` (#4161, the #1665 size ratchet); re-exported ──
from mcp.plan_draft_evidence import (  # noqa: E402,F401
    _anchor_trend,
    _core_anchor_family,
    _core_anchor_identities,
    _gather_draft_evidence,
    _loss_rate_of,
    _training_streaks,
    _weeks_in_block,
    _workout_dates,
    _worst_anchor,
    attach_fatigue_inputs,
)


# ── stage 2: the red team ────────────────────────────────────────────────────────────
def _run_stage_2(
    ir: Any,
    block: dict[str, Any],
    reference: dict[str, Any] | None,
    evidence: dict[str, Any],
    protein_missed,
    protein_measured,
    target_date: str,
    dismissals: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from coach import critic_overrides, critics
    from training.routine_repo import put_versioned

    from mcp.hevy_prescription_gate import critic_set_floors
    from mcp.tools_hevy_routine import _validate_ir_for_hevy

    by_idx = {e["idx"]: e for e in evidence["exercises"]}

    def build(draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "muscle_defense": critics.build_muscle_defense_packet(
                draft,
                anchor_trends={i: e for i, e in by_idx.items() if e.get("drop_pct") is not None},
                program_week=block.get("program_week"),
                protein_days_missed_7d=protein_missed,
                protein_days_measured_7d=protein_measured,
            ),
            "joints_tendons": critics.build_joints_packet(
                draft,
                pain_by_idx={i: e for i, e in by_idx.items() if "pain_flag_any" in e},
                days_since_by_idx={i: e.get("days_since") for i, e in by_idx.items()},
                active_day_streak=evidence.get("active_day_streak"),
                loaded_lifting_streak=evidence.get("loaded_lifting_streak"),
                pain_layer_status=evidence.get("pain_layer_status"),
                dismissals=dismissals,  # #4036 — the owner's own override of a flag instance
                stale_by_idx={i: e["stale"] for i, e in by_idx.items() if e.get("stale")},  # #4161: the cap scales with the gap
                fatigue=evidence.get("fatigue"),  # #4161: performance / readiness, not a loaded-day count
            ),
            "rate_advocate": critics.build_rate_advocate_packet(
                draft,
                tripwires=block.get("tripwires"),
                walking=block.get("walking"),
                rate_target=block.get("rate_target"),
                # #4068: THE loss rate (mcp.shared_quantities via get_benchmark's `loss_rate`
                # block) — the number the deficit critic reads, provisional flag included.
                current_rate_lb_wk=_loss_rate_of(reference)[0],
                rate_provisional=_loss_rate_of(reference)[1],
                lifting_sessions_7d=evidence.get("lifting_sessions_7d"),
            ),
            "blueprint_historian": critics.build_historian_packet(
                draft, reference=reference, weeks_in_block=evidence.get("weeks_in_block")
            ),
        }

    # LIVE FINDING 2026-09-20 (routine 73bc228c v5 -> v6): a re-run on an already-critiqued
    # routine compounded the joints critic's cut (22 -> 18 -> 14) because every `session.total_sets`
    # change is relative to the draft the critic sees. Stage 2 must be a re-EVALUATION of the
    # coach's draft, never a second cut on its own output: restore the pre-critics exercise list
    # first, and keep that snapshot on the record so the next run can do the same.
    prior = (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}
    if prior.get("draft_exercises"):
        from training.routine_ir import _exercise_from_raw

        ir.exercises = [_exercise_from_raw(dict(e)) for e in prior["draft_exercises"]]
    from dataclasses import asdict

    draft_exercises = [asdict(e) for e in ir.exercises]
    draft = critics.draft_summary(ir)
    packets = build(draft)
    allowed, paused = _model_allowed()
    invoke = None
    if allowed:
        from ai.bedrock_client import invoke as _invoke

        invoke = _invoke
    verdicts = critics.run_critics(packets, draft, invoke=invoke, model_allowed=allowed, model_paused_reason=paused)
    ran_at = datetime.now(timezone.utc).isoformat()
    # #4076: the owner's override marks ONLY the named critic's veto; it runs before the
    # changes so the record is complete, and it moves no change — `apply_changes` below sees
    # every other critic's verdict exactly as the critics returned it.
    override_records = critic_overrides.apply_overrides(
        verdicts,
        overrides or [],
        at=ran_at,
        routine_id=getattr(ir, "routine_id", None),
        target_date=target_date,
        record_correction=_record_override_correction,
    )
    changes = critics.apply_changes(ir, verdicts, set_floors=critic_set_floors(ir))  # #4149: held to the commit gate's floor
    overridden = {v["critic"] for v in verdicts if critics.is_overridden(v)}
    rc = critics.recheck(ir, build, overridden=overridden)
    precheck = _validate_ir_for_hevy(ir)
    rc["hevy_precheck_errors"] = precheck["errors"]
    rc["passed"] = bool(rc["passed"] and not precheck["errors"])
    record = {
        "engine": critics.CRITICS_VERSION,
        "ran_at": ran_at,
        "target_date": target_date,
        "model_ran": allowed,
        "model_paused_reason": paused,
        "verdicts": verdicts,
        "changes": changes,
        "recheck": rc,
        "veto": bool(critics.standing_vetoes(verdicts)),
        # #4076: every override asked for on this run, applied or not, with his words verbatim.
        "owner_overrides": override_records,
        "packet_numbers": {cid: p["numbers"] for cid, p in packets.items()},
        # the coach's draft as critiqued, so a re-run re-evaluates THIS, not its own output
        "draft_exercises": draft_exercises,
    }
    ir.inputs_snapshot = {**(getattr(ir, "inputs_snapshot", None) or {}), "critics": record}
    # LIVE FINDING 2026-09-20: Hevy's routine object carries NO `notes` field on the API (GET keys
    # are created_at/exercises/folder_id/id/title/updated_at; a PUT with notes reads back without
    # them). Every routine-level WHY note the compiler has ever sent is invisible there. EXERCISE
    # notes do land, verifiably — the recovery session block already lives there for that reason
    # (`_apply_recovery_adaptation`). So the verdicts ride on the FIRST exercise's notes, where he
    # will actually read them at the gym, as well as the routine-level field.
    _place_block_on_first_exercise(ir)
    ir.parent_version = ir.version
    ir.version = int(ir.version) + 1
    # #4066: bind the verdict to THIS routine and THIS content, stamped after every change and
    # the notes block are applied (`record` IS inputs_snapshot["critics"]) — commit refuses any
    # other routine_id or any later edit.
    record["binding"] = binding_for(ir)
    put_versioned(ir)
    out = dict(record)
    out["routine_id"] = ir.routine_id
    out["routine_version"] = ir.version
    out["thread"] = _write_thread(ir, pacific_today())
    out["notes_preview"] = critics.notes_block(ir)
    if record["veto"]:
        out["next"] = (
            "VETO — redraft (manage_hevy_routine draft_custom), then run stage 2 again; commit will refuse until no veto "
            "stands. If Matthew overrules one critic, re-run with veto_override={critic, owner_words} (#4076)."
        )
    elif overridden:
        out["next"] = (
            f"no standing veto — {', '.join(sorted(overridden))} OVERRIDDEN by the owner (his words are on the record); "
            "every other critic's changes are applied. manage_hevy_routine dry_run shows the revised body, then commit."
        )
    else:
        out["next"] = "no veto — manage_hevy_routine dry_run shows the revised body, then commit."
    return out


def _record_override_correction(item_ref: dict[str, Any], owner_words: str, error_class: str) -> str:
    """#4076: the owner's override words into the corrections ledger — the SAME write the
    `log_coach_correction` tool makes (`coach_corrections.write_correction`, cycle-stamped
    via `coach_checkin.read_cycle`), naming the vetoing critic and signal in `item_ref`.
    Raises on a DDB error: `critics.apply_overrides` then refuses the override."""
    from coach import coach_checkin, coach_corrections

    from mcp.config import table

    return coach_corrections.write_correction(table, item_ref, owner_words, error_class, cycle=coach_checkin.read_cycle())


_BLOCK_MARK = "RED TEAM ("

# #4070: the owner reported the Hevy app cutting exercise notes at ~150 characters,
# flagged across 8 chat sessions (09-16, 09-17, 09-19, 09-21, 09-22). Nothing in this repo
# enforces that cut, and it is not a documented server-side limit — the mirrored OpenAPI
# contract (docs/specs/SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31_PREREQS.md §A.3) carries
# `notes (string, nullable)` with no maxLength, and per the issue's own instruction this
# was NOT re-verified with a live write (owner ruling: do not probe live Hevy to find the
# true cut). So the number below is evidence, not a contract: it is used only to size the
# regression test's "visible window", never as a truncation trigger in code. The actual
# fix is structural and holds at ANY cut point Hevy turns out to apply: the block this
# function writes must land AFTER whatever cues are already on exercises[0].notes — the
# session-adaptive tier cues (`_apply_recovery_adaptation`) and the WHY line the compiler
# prepends at wire time (`hevy_compiler._place_routine_note`) — never ahead of them.
HEVY_NOTE_OBSERVED_VISIBLE_CHARS = 150


def _place_block_on_first_exercise(ir: Any) -> None:
    """Append the critics' verdict block to exercise[0].notes, AFTER whatever cues are
    already there, replacing any earlier block (a re-run must not stack two).

    #4070: this used to PREPEND the block, so the owner's own tier cues (the recovery
    session block + per-lift branch lines `_apply_recovery_adaptation` writes at draft
    time) sat behind a RED TEAM header that can run to 1000+ characters across four
    critics. Whatever cuts a long Hevy note — the app's display, or the API itself, the
    owner has observed ~150 chars but neither is documented or safe to probe live (see
    HEVY_NOTE_OBSERVED_VISIBLE_CHARS above) — a cut there removed the cues he reads at
    the gym and kept only verdict boilerplate. The full verdict record is never at risk:
    it is stored in full on `ir.inputs_snapshot["critics"]` regardless of what reaches
    the wire. Only the block placed here is allowed to be the part a cut lands on.
    """
    from coach import critics

    block = critics.notes_block(ir)
    if not block or not getattr(ir, "exercises", None):
        return
    first = ir.exercises[0]
    existing = first.notes or ""
    if _BLOCK_MARK in existing:
        # drop the old block — it is always the LAST thing this function appended, so
        # everything from the mark onward is the block; nothing trails it.
        existing = existing.split(_BLOCK_MARK, 1)[0].rstrip()
    first.notes = (existing + ("\n\n" + block if block else "")).strip()


def _model_allowed() -> tuple[bool, str | None]:
    """Whether the four model calls may run at the current budget tier."""
    try:
        from ai import budget_guard
        from coach.critics import BUDGET_FEATURE

        if budget_guard.allow(BUDGET_FEATURE):
            return True, None
        return False, f"budget tier {budget_guard.current_tier()} — {BUDGET_FEATURE} paused; deterministic layer only"
    except Exception as e:  # noqa: BLE001
        return False, f"budget guard unreadable ({type(e).__name__}) — deterministic layer only"


def _write_thread(ir: Any, today: str) -> dict[str, Any]:
    """Tonight's verdicts as a training coach thread row — keyed with a `#critics` suffix so it
    sits beside the analyzer's weekly entry and never overwrites it; class-gated phase stamp
    at write time (#3514/#3900)."""
    from coach import critics
    from experiment.phase_taxonomy import experiment_stamp_for

    from mcp.config import table

    item = critics.thread_entry(ir, today=today)
    try:
        item.update(experiment_stamp_for(item["pk"], item["sk"]))
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        clean = json.loads(json.dumps(item, default=str), parse_float=Decimal)
        table.put_item(Item=clean)
        return {"written": True, "sk": item["sk"]}
    except Exception as e:  # noqa: BLE001 — reported in the result, never swallowed (#3670 class)
        logger.warning("critics thread write failed: %s", e)
        return {"written": False, "sk": item["sk"], "error": f"{type(e).__name__}: {e}"[:200]}


# #4072: the keys each reader is KNOWN to carry its answer under. A non-empty return with none
# of them is a shape change — reported `read_failed (InputShapeError)`, never `absent`.
_READINESS_SCORE_KEYS = ("readiness_score", "score", "recovery_score")
_VOLUME_TABLE_KEYS = ("muscle_volume", "muscle_sets", "by_muscle")


def _recovery_tier(readiness: dict) -> str | None:
    """GREEN / YELLOW / RED from the readiness score, in the authoring spec's bands.

    `get_readiness_score` returns a 0-100 `score`, not a tier; the recovery-adaptive
    authoring spec (SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21) is what maps a number to
    a branch. Doing the mapping here keeps the engine's input in the vocabulary the
    cues are written in.
    """
    # LIVE SHAPE (2026-09-20): get_readiness_score returns `readiness_score`; the two names read
    # before it were guesses and the tier came back None on a GREEN 80.1 day.
    score = readiness.get("readiness_score")
    if score is None:
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


def _muscle_sets(volume: dict[str, Any]) -> dict[str, Any]:
    """{muscle: weekly sets} from get_muscle_volume's live shape, or {} when it is absent."""
    table = volume.get("muscle_volume") or volume.get("muscle_sets") or volume.get("by_muscle") or {}
    out: dict[str, Any] = {}
    for muscle, row in table.items():
        if isinstance(row, dict):
            v = row.get("avg_sets_per_week", row.get("total_sets"))
            if v is not None:
                out[muscle] = v
        elif isinstance(row, (int, float)):
            out[muscle] = row
    return out
