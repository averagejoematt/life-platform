"""tools_development_profile.py — `get_development_profile`, the owner's private personal-development profile (#6294).

READ-ONLY. This module reads the stores the existing MCP read tools read, through the same shared readers, and hands
the rows to the pure assembly `health.development_profile.assemble_profile` (where every rule lives). It writes
nothing: no put, no update, no delete, no cache write, no queue item (`tests/test_development_profile_6294.py`
drives it against a table that refuses every write and records every call).

  measured     zone 2 — `get_zone2_breakdown` itself (its per-week zone_2_activities); lifts — `get_exercise_history`'s
               reader (`tools_strength._read_hevy_all_phases`) and `mcp.strength_helpers.extract_hevy_sessions`;
               training days — days with a Hevy workout or a zone 2 session (context); weight — withings `weight_lbs`;
               aerobic results — the fitness test battery's trend (`tools_fitness_tests.read_view`) and the VO2 max device estimate through `get_training(view="cardio_fitness")`'s own read;
               adherence — `training.session_sequence` credited sessions against the program's intended sessions per
               week (`plan_hevy_windows._block_workouts`, the sequence's sanctioned read); core habits — `habit_scores`
               `core_done`/`core_known`; observed days — days with a habit record or a session; planned pauses — sick
               days (`health.sick_day_checker.get_sick_days_range`) and travel-logged days.
  counted      experiments (the EXP# rows `list_experiments` reads — read directly, because that tool also captures due
               baselines, which is a write; and with no phase filter, see `_experiments`); the recommendation record (`coach.recommendation_record.fold`); decisions
               (the DECISION# rows `get_decisions` reads); personal hypotheses (`research.hypotheses.fold`); reviewed
               personal records (the platform_memory `MEMORY#personal_record#` rows).
  own report   journal self-rating fields only (`mcp.tools_journal._query_journal`, projected to the date and
               `common.inferred_fields.SELF_REPORT_FIELDS` before the assembly sees a row) and the evening check-in's
               mood and stress.
  his view     the corrections ledger rows on the `development_profile` surface (`coach.coach_corrections`).

A failed read is reported in `reads.failed` and reaches the assembly as UNREAD, never as an empty list — so it can
only make a domain read not_enough_to_say, never harder.

OWNER-ONLY: never served by a site route, never injected into a coach prompt, no XP or Walker effect.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from boto3.dynamodb.conditions import Key
from coach import coach_corrections, recommendation_record as rr
from common.inferred_fields import SELF_REPORT_FIELDS
from common.pacific_time import pacific_today, parse_day_key, shift_day_key
from health import development_profile as dp
from health.sick_day_checker import get_sick_days_range
from research import hypotheses as ph
from training.muscle_volume import normalize_hevy_items

from mcp.config import EXPERIMENTS_PK, USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f, query_source
from mcp.strength_helpers import extract_hevy_sessions

TOOL = "get_development_profile"
#: The furthest back a measured or rating rule looks: two windows. Record stores (experiments, decisions, the
#: recommendation record, hypotheses, personal records, corrections) are read whole and windowed by the assembly.
MEASURED_LOOKBACK_DAYS = 2 * max(dp.MEASURED_WINDOW_DAYS, dp.RATING_WINDOW_DAYS)
_PAGE_CAP = 50
_JOURNAL_FIELDS = tuple(sorted({f for fields in SELF_REPORT_FIELDS.values() for f in fields}))

GET_DEVELOPMENT_PROFILE_DESCRIPTION = (
    "OWNER-ONLY, READ-ONLY. Matthew's private personal-development profile (#6294): nine life domains — physical "
    "capacity, behavioural consistency, learning and experimentation, self-understanding, emotional wellbeing, social "
    "connection, meaning and fulfilment, confidence and agency, coping and flexibility. Per domain: a plain status "
    "(improving | steady | harder | mixed | not_enough_to_say | owner_disputed), its `scope` (what the status rests on and "
    "what it does NOT establish — e.g. improving on strength only, aerobic fitness not established), its basis (measured | counted_from_records | own_report | "
    "owner_confirmed_records), the evidence items behind it (date, source, evidence_kind, a short statement or figure; "
    "window and n for measured items), what was not observed, his last view of the line, and how_to_disagree (the exact "
    "log_coach_correction call). There is NO overall score, level, percentage or ranking — never add one up, never "
    "turn the profile into a score, and repeat each domain's basis when you report it. not_enough_to_say is the honest "
    "answer when evidence is thin and means the records are too few, never that nothing happened; missing evidence is never decline. "
    "An OPEN correction of his on a line changes what it asserts until he closes it. A model's reading of his writing is never evidence "
    "here. Use for 'how am I doing beyond fitness'. Optional: today (YYYY-MM-DD, defaults to the Pacific day)."
)

GET_DEVELOPMENT_PROFILE_INPUT = {
    "type": "object",
    "properties": {
        "today": {"type": "string", "description": "Optional YYYY-MM-DD the windows end on (default: today, Pacific)."},
    },
    "required": [],
}


def _query_all(table, **kwargs) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _ in range(_PAGE_CAP):
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    raise RuntimeError(f"more than {_PAGE_CAP} pages — refusing to report a partial read as complete")


def _day_of(row: dict[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "")[5:15])[:10]


def _training_reads(start: str, today: str) -> dict[str, Any]:
    """Zone 2 through `get_zone2_breakdown` itself, lifts through `get_exercise_history`'s own reader — no second copy."""
    from mcp.tools_correlation import tool_get_zone2_breakdown
    from mcp.tools_strength import _read_hevy_all_phases

    z2 = tool_get_zone2_breakdown({"start_date": start, "end_date": today})
    zone2: list[dict[str, Any]] = []
    if not (z2.get("error") and "No recorded sessions" in str(z2["error"])):
        if "weekly_breakdown" not in z2:
            raise RuntimeError(f"get_zone2_breakdown: {z2.get('error') or 'no weekly_breakdown'}")
        for wk in z2["weekly_breakdown"]:
            zone2.extend({"date": a["date"], "minutes": a.get("minutes") or 0} for a in wk.get("zone_2_activities") or [])
    hevy, _phases = _read_hevy_all_phases(start, today)
    workouts = [w for w in normalize_hevy_items(hevy) if start <= str(w.get("date")) <= today]
    tids = sorted({str(ex.get("template_id") or "").upper() for w in workouts for ex in w["exercises"] if ex.get("template_id")})
    lifts = []
    for tid in tids:
        for s in extract_hevy_sessions(hevy, "", template_id=tid):
            if start <= s["date"] <= today and s.get("best_1rm"):
                lifts.append({"date": s["date"], "identity": s["identity"], "name": s["exercise_name"], "best_e1rm_lb": s["best_1rm"]})
    return {
        "zone2_sessions": [z for z in zone2 if start <= z["date"] <= today],
        "training_days": sorted({z["date"] for z in zone2} | {str(w["date"]) for w in workouts}),
        "lift_sessions": lifts,
    }


def _fitness_trend(today: str) -> dict[str, Any]:
    """The fitness test battery's own trend (`get_fitness_tests`' read view); a failed record read raises."""
    from mcp.tools_fitness_tests import read_view

    view = read_view(today)
    rec = view.get("reads", {}).get("record")
    if isinstance(rec, dict) and rec.get("state") == "read_failed":
        raise RuntimeError(f"fitness battery record: {rec.get('error')}")
    return view.get("trend") or {}


def _vo2_estimates(start: str, today: str) -> list[dict[str, Any]]:
    """The VO2 max device estimate per date, through `get_training(view="cardio_fitness")`'s own read and resolver (no
    second copy): the view reads its sources through `read`, which keeps the rows; `common.metric_truth` then resolves
    each date with the device that produced it."""
    from common import metric_truth as mt
    from health import watch_signals as ws
    from health.watch_views import cardio_fitness_view

    captured: dict[str, list] = {}

    def read(src: str, lo: str, hi: str) -> list:
        captured[src] = query_source(src, lo, hi) or []
        return captured[src]

    view = cardio_fitness_view({"start_date": start, "end_date": today}, read)
    if view.get("error"):
        raise RuntimeError(f"cardio_fitness: {view['error']}")
    return [
        {"date": d, "value": r.value, "source": ws._label(r.source)}
        for d, r in sorted(mt.resolve_by_date(mt.VO2_MAX, captured).items())
        if start <= d <= today and r.value is not None
    ]


#: How intent is established for an adherence week (stated on the evidence item).
ADHERENCE_INTENT = (
    "the program's session plan (training.session_sequence: sessions per program week from the committed program "
    "structure — v0.4's four before the cut-over, the charter's lifting days after); a session is credited by the "
    "sequence's own rule (a loaded log whose routine archetype is a program one and whose sets reach the role's "
    "anchors). Weeks before the block start have no record of intent and are not counted."
)


def _adherence_weeks(start: str, today: str) -> list[dict[str, Any]]:
    """Per complete Mon–Sun week from the block start: intended program sessions and credited ones."""
    from health.development_profile_measured import adherence_windows
    from training import session_sequence as seq

    from mcp.plan_hevy_windows import _block_workouts

    block = seq.block_start()
    credited, _refused = seq.classify_sessions(_block_workouts(shift_day_key(today, 1)), shift_day_key(today, 1))
    days = [str(c["date"]) for c in credited]
    out = []
    for mondays in adherence_windows(today).values():
        for m in mondays:
            if m < block:
                continue  # no record of intent before the program's block start
            sunday = shift_day_key(m, 6)
            out.append(
                {
                    "week_start": m,
                    "intended": seq._per_week(m),
                    "credited": sum(1 for d in days if m <= d <= sunday),
                    "program_version": seq._version_on(m),
                }
            )
    return out


def _core_habit_days(start: str, today: str) -> list[dict[str, Any]]:
    """The core set's own day verdict counts (`habit_scores.core_done` / `core_known`) — counts only, no habit name read."""
    return [
        {"date": _day_of(r), "core_done": r.get("core_done"), "core_known": r.get("core_known")}
        for r in query_source("habit_scores", start, today) or []
    ]


def _excluded_days(table, start: str, today: str) -> dict[str, list[str]]:
    sick = sorted({str(r.get("date")) for r in get_sick_days_range(table, _user_id_ref, start, today) or [] if r.get("date")})
    travel = sorted({_day_of(r) for r in query_source("travel", start, today) or []})
    return {"sick": sick, "travel": travel}


# Experiments and decisions are records of what he DID, so the phase filter (ADR-058) is not applied: the assembly's
# date windows scope them, and an experiment run before the current genesis is still something he ran. A superseded
# row (`tombstone`) is dropped, as `phase_filter.singleton_visible` does for a key read.
def _experiments(table) -> list[dict[str, Any]]:
    rows = _query_all(table, KeyConditionExpression=Key("pk").eq(EXPERIMENTS_PK) & Key("sk").begins_with("EXP#"))
    keep = ("experiment_id", "name", "start_date", "end_date", "status")
    return [{k: r.get(k) for k in keep} for r in rows if not r.get("tombstone")]


def _decisions(table) -> list[dict[str, Any]]:
    pk = f"USER#{_user_id_ref}#SOURCE#decisions"
    rows = _query_all(table, KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DECISION#"))
    return [{"sk": r.get("sk"), "date": r.get("date"), "outcome_date": r.get("outcome_date")} for r in rows if not r.get("tombstone")]


def _personal_records(table) -> list[dict[str, Any]]:
    pk = f"USER#{_user_id_ref}#SOURCE#platform_memory"
    return _query_all(table, KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("MEMORY#personal_record#"))


def _journal(start: str, today: str) -> list[dict[str, Any]]:
    from mcp.tools_journal import _query_journal

    return [{"date": r.get("date"), **{f: r.get(f) for f in _JOURNAL_FIELDS if r.get(f) is not None}} for r in _query_journal(start, today)]


def _evening(start: str, today: str) -> list[dict[str, Any]]:
    return [
        {"date": _day_of(r), "mood": r.get("mood"), "stress": r.get("stress")} for r in query_source("evening_checkin", start, today) or []
    ]


def _profile_corrections(table) -> list[dict[str, Any]]:
    rows = coach_corrections.list_corrections(table, limit=1000)
    return [r for r in rows if (r.get("item_ref") or {}).get("surface") == dp.PROFILE_SURFACE]


def gather_inputs(table, today: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Every input the assembly takes, read-only, plus the reads that failed (name -> error class)."""
    t = parse_day_key(today)
    if t is None:
        raise ValueError(f"today must be YYYY-MM-DD, got {today!r}")
    measured_start = (t - timedelta(days=MEASURED_LOOKBACK_DAYS - 1)).isoformat()
    inputs: dict[str, Any] = {}
    failed: dict[str, str] = {}

    def read(names: tuple[str, ...], fn: Callable[[], Any]) -> None:
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001 — a failed read is reported as unread, never as empty
            for n in names:
                failed[n] = type(e).__name__
            return
        if len(names) == 1:
            inputs[names[0]] = got
        else:
            inputs.update({n: got[n] for n in names})

    read(("zone2_sessions", "training_days", "lift_sessions"), lambda: _training_reads(measured_start, today))
    read(("excluded_days",), lambda: _excluded_days(table, measured_start, today))
    read(
        ("weight",),
        lambda: [{"date": _day_of(r), "weight_lbs": r.get("weight_lbs")} for r in query_source("withings", measured_start, today) or []],
    )
    read(
        ("habit_days",),
        lambda: [{"date": _day_of(r)} for r in query_source("habitify", measured_start, today) or []],
    )
    # An OBSERVED day is one with a habit record (Habitify writes a row for every tracked day) or a recorded session —
    # the session days are added by the assembly. A day with neither is not observed: out of the denominator, never a zero.
    if "habit_days" in inputs:
        inputs["observed_days"] = sorted({h["date"] for h in inputs["habit_days"] if h.get("date")})
    else:
        failed["observed_days"] = failed.get("habit_days", "unread")
    read(("fitness_trend",), lambda: _fitness_trend(today))
    read(("vo2_estimates",), lambda: _vo2_estimates(measured_start, today))
    read(("adherence_weeks",), lambda: _adherence_weeks(measured_start, today))
    inputs["adherence_intent"] = ADHERENCE_INTENT
    read(("core_habit_days",), lambda: _core_habit_days(measured_start, today))
    read(("experiments",), lambda: _experiments(table))
    read(("recommendations",), lambda: rr.fold(rr.read_rows(table, _user_id_ref)))
    read(("decisions",), lambda: _decisions(table))
    read(("hypotheses",), lambda: ph.fold(ph.read_rows(table, _user_id_ref)))
    read(("personal_records",), lambda: _personal_records(table))
    read(("journal_entries",), lambda: _journal(measured_start, today))
    read(("evening_checkins",), lambda: _evening(measured_start, today))
    read(("profile_corrections",), lambda: _profile_corrections(table))
    inputs["read_failed"] = failed
    return inputs, failed


def tool_get_development_profile(args: dict | None = None) -> dict[str, Any]:
    """The owner's private development profile. Reads only; see the module docstring."""
    args = args or {}
    today = str(args.get("today") or pacific_today())
    if parse_day_key(today) is None:
        return {"error": f"today must be YYYY-MM-DD, got {today!r}"}
    inputs, failed = gather_inputs(_table_ref, today)
    profile = dp.assemble_profile(_d2f(inputs), today=today)
    profile["reads"] = {"failed": failed, "note": "a failed read is unread, never empty: it can only make a domain not_enough_to_say"}
    return profile
