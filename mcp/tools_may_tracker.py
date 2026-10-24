"""mcp/tools_may_tracker.py — the May tracker's readers, its nightly writer and the owner's tool (#5073, C6).

OWNER-ONLY. `training.may_tracker` is the pure core; this module does the sanctioned reads and
hands them in — it computes nothing of its own:

  weight     the Withings partition (`core.query_source`) through `mcp.shared_quantities`' estimator
             (`weekly_loss_rate_weeks_from_rows` for the week, `loss_rate_from_rows` over 28 days);
             the clinical cap through `training.rate_band.guidance_cap_for` (a broken read is
             `read_failed`, never "no cap"; nothing from the record is logged or returned);
  waist      the measurements partition;
  steps      `training.steps_resolver.steps_range` (measured candidates only — the Strava-walk
             derived estimate is not a step count);
  fitness    `mcp.tools_fitness_tests.read_view` (#5078): the battery record, Hevy and the cadence state;
  Hevy       ONE read (`tools_strength._read_hevy_all_phases`) serves the week's working sets
             (`muscle_volume.working_sets_by_muscle`) and the four core anchors' e1RM series
             (`strength_helpers.extract_hevy_sessions` over `plan_draft_evidence._core_anchor_identities`);
  run gate   (#5090) the same Hevy rows plus ONE Strava read feed `shared_quantities.walking_layer` (THE walking
             definition) for each of the gate's walking weeks — the walking modality's hours — and each week's
             lower-leg pain flag (a pain-lexicon note naming a lower-leg site, `training.training_notes` +
             `training.steps_ramp.is_lower_leg`). The HOLD is the plan's own: the pain notes become flag instances
             in `tools_plan._pain_instances`' shape and go through `steps_ramp.lower_leg_holds` with the owner's
             dismissals (`tools_plan._pain_dismissals`, read only when a pain note exists) — so the quiet period,
             a dismissal and an active standing lower-leg constraint resolve here exactly as on the plan path.
             Stage 4 reads the run/walk notes back to `onramp.history_from` (the Hevy read reaches that far;
             every other section reads only its own window). An unread source is None, never a pain-free week.

THE WRITE. `nightly_leg()` rides the nightly pre-draft run (`mcp.nightly_predraft.lambda_entry`,
02:00Z): it rebuilds the newest COMPLETED Monday-Sunday week (with the week before it, for the
two-weeks-running triggers) and overwrites `WEEK#<monday>` — idempotent, so a late weigh-in is
absorbed on the next night. It never raises; its outcome is on the run's logged result. The
staleness of the stored row is also checked on READ: `get_may_tracker` reports `stored.state =
stale` when the newest stored week is not the newest completed one, so a leg that silently stopped
is visible the next time the owner looks.

NEVER on a published surface (owner ruling 2026-10-18: no May countdown on the site):
`tests/test_may_tracker_5073.py` holds that no `lambdas/web/` or `lambdas/emails/` module imports
the tracker.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from common.pacific_time import pacific_today
from training import may_tracker as mt

logger = logging.getLogger("may_tracker")

# The e1RM trend needs 9 sessions of one identity (3 recent + 6 baseline); an anchor trained
# twice a week reaches that in ~4.5 weeks, so 12 weeks before the first tracked Monday holds it.
ANCHOR_LOOKBACK_DAYS = 84
RATE_4WK_DAYS = 28
MAX_WEEKS = 8

GET_MAY_TRACKER_DESCRIPTION = (
    "OWNER-ONLY. The weekly May tracker (#5073): for each completed Monday-Sunday week, the loss rate vs the "
    "charter band (lb/wk AND % of bodyweight), weeks to the target date and the projected weight there, waist, "
    "steps vs the floor and target, the four core anchors' e1RM trends, priority-muscle weekly sets, fitness tests "
    "and the distance to the running gate — every value labelled measured / absent / read_failed with its source — "
    "plus AMBER/RED triggers, each naming the lever to pull. Computed live from the sanctioned reads; `stored` says "
    "whether the nightly row is current. Never quoted on the site or in an email."
)

GET_MAY_TRACKER_INPUT = {
    "type": "object",
    "properties": {
        "weeks": {
            "type": "integer",
            "description": "Completed weeks to return, oldest first (default 4, max 8).",
            "minimum": 1,
            "maximum": 8,
        },
    },
    "required": [],
}


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:200]


def _steps_fetch(source: str, start: str, end: str) -> list[dict[str, Any]]:
    from mcp import core

    return list(core.query_source_range(source, start, end) or [])


def _anchor_series(items: list) -> dict[str, list[dict[str, Any]]]:
    """{core anchor family: [session]} — each identity's sessions once (an alias id and its canonical id
    resolve to one identity)."""
    from mcp.plan_draft_evidence import _core_anchor_identities
    from mcp.strength_helpers import extract_hevy_sessions
    from mcp.tools_strength import template_alias_map

    alias_map, _status = template_alias_map()
    out: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for ident, fam in _core_anchor_identities().items():
        for s in extract_hevy_sessions(items, "", template_id=ident, alias_map=alias_map):
            key = (fam, str(s.get("identity")), str(s.get("date")))
            if key not in seen:
                seen.add(key)
                out.setdefault(fam, []).append(s)
    return out


def _latest_weight(rows: list, sunday: str) -> Optional[tuple[str, float]]:
    from mcp.shared_quantities import _weighins

    pts = [p for p in _weighins(rows) if p[0] <= sunday]
    return pts[-1] if pts else None


def _read(fn, *a, **kw) -> tuple[Any, Optional[str]]:
    try:
        return fn(*a, **kw), None
    except Exception as e:  # noqa: BLE001 — the section reports it as read_failed, by class and message
        logger.warning("[may_tracker] read failed (%s)", type(e).__name__)
        return None, _err(e)


def _guidance() -> dict[str, Any]:
    from training import rate_band

    from mcp import core

    try:
        cap = rate_band.guidance_cap_for(core.table)
    except rate_band.GuidanceReadError:
        return {"state": mt.READ_FAILED, "cap_lb_wk": None}
    return {"state": mt.MEASURED if cap is not None else mt.ABSENT, "cap_lb_wk": cap}


def _fitness_view(as_of: str, hevy_rows: Optional[list] = None) -> dict[str, Any]:
    """#5078: the battery read (record + the sequence position over the tracker's ONE Hevy read) through its own module."""
    from mcp.tools_fitness_tests import read_view

    return read_view(as_of, hevy_rows)


def _fitness_as_of(view: Optional[dict[str, Any]], sunday: str, last_sunday: str) -> Optional[dict[str, Any]]:
    """The newest week carries the cadence state; an earlier week carries its trend only (no due state is back-dated)."""
    if view is None:
        return None
    return {"batteries": view.get("batteries") or [], "due": view.get("due") if sunday == last_sunday else None}


def _rows_in(rows: Optional[list], start: str, end: str) -> list:
    return [r for r in rows or [] if start <= _day(r) <= end]


def _day(r: Any) -> str:
    return str(r.get("date") or str(r.get("sk") or "")[5:15])[:10]


def pain_instances(hevy: Optional[list]) -> Optional[list]:
    """The pain-flag instances in `tools_plan._pain_instances`' shape, one per exercise whose Hevy note the pain net
    (`training_notes.pain_lexicon_hit`, the layer's deterministic pass) flags; None = Hevy unread."""
    from training.training_notes import pain_lexicon_hit

    if hevy is None:
        return None
    by: dict[str, dict[str, Any]] = {}
    for r in hevy:
        for e in r.get("exercises") or []:
            note = str(e.get("notes") or e.get("note") or "")
            if pain_lexicon_hit(note):
                name = str(e.get("name") or e.get("title") or "exercise")
                inst = by.setdefault(name, {"movement": name, "exercise": name, "note_dates": [], "notes": []})
                inst["note_dates"].append(_day(r))
                inst["notes"].append({"date": _day(r), "text": note})
    return list(by.values())


def _lower_leg_dates(instances: Optional[list]) -> Optional[list[str]]:
    from training.steps_ramp import is_lower_leg

    if instances is None:
        return None
    return sorted({n["date"] for i in instances for n in i["notes"] if is_lower_leg(n.get("text"))})


def hold_since(holds: Optional[list], instances: Optional[list], sunday: str) -> Optional[str]:
    """The day the standing hold began: the earliest active standing lower-leg constraint's `dated`, and the first
    lower-leg pain note of the unbroken run (gaps under the quiet period) ending at the newest note — the day from
    which a run/walk stops counting (`run_onramp.stage_progress`). None when nothing holds or no date is known."""
    from training.steps_ramp import RELEASE_QUIET_DAYS
    from training.training_context_registry import RECORDED_CONSTRAINTS

    if not holds:
        return None
    starts = [str(c.get("dated"))[:10] for c in RECORDED_CONSTRAINTS if f"standing_constraint:{c['id']}" in holds and c.get("dated")]
    dates = [d for d in _lower_leg_dates(instances) or [] if d <= sunday]
    if any(str(h).startswith("strain_flag:") for h in holds) and dates:
        start = dates[-1]
        for d in reversed(dates[:-1]):
            if mt.shift(d, RELEASE_QUIET_DAYS) <= start:
                break
            start = d
        starts.append(start)
    return min(starts) if starts else None


def running_inputs(sunday: str, strava: Optional[list], hevy: Optional[list], dismissals: Optional[list] = None) -> dict[str, Any]:
    """The run gate's walking weeks (newest first), hold and Stage 4 progress for the week ending `sunday`, from rows
    already read. `dismissals` are the owner's pain dismissals (None = none read: a flag then holds, the cautious side)."""
    from training import run_onramp, steps_ramp

    from mcp import shared_quantities

    def _slice(source: str, start: str, end: str) -> list:
        rows = strava if source == "strava" else hevy
        if rows is None:
            raise LookupError(f"{source} unread")
        return _rows_in(rows, start, end)

    instances = pain_instances(hevy)
    pain_dates = _lower_leg_dates(instances)
    walking_weeks = []
    for k in range(int(run_onramp.running().get("walking_weeks") or 0)):
        end = mt.shift(sunday, -7 * k)
        layer = shared_quantities.walking_layer(end, days=7, today=mt.shift(sunday, 1), read=_slice)
        hours = None if not layer or layer.get("total_hr") is None else float((layer.get("by_modality") or {}).get("walking") or 0.0)
        pain = None if pain_dates is None else any(mt.shift(end, -6) <= d <= end for d in pain_dates)
        walking_weeks.append({"week_start": mt.shift(end, -6), "hours": hours, "pain_flag": pain})
    # the hold: the plan's own resolution (strain flags in the quiet period, dismissals, active standing constraints)
    holds = None if instances is None else steps_ramp.lower_leg_holds(sunday, instances, dismissals)
    since = hold_since(holds, instances, sunday)
    # Stage 4: his logged run/walks (a treadmill or running block whose note names the run/walk, its level and RPE)
    blocks = [
        {"date": _day(r), "note": e.get("notes") or e.get("note")}
        for r in _rows_in(hevy, run_onramp.history_from() or "0000-00-00", sunday)
        for e in r.get("exercises") or []
        if re.search(r"treadmill|running|\brun\b", str(e.get("name") or ""), re.IGNORECASE)
    ]
    onramp = run_onramp.stage_progress(run_onramp.performed_from_notes(blocks), holds, since) if hevy is not None else None
    return {
        "walking_weeks": walking_weeks,
        "holds": holds,
        "held_since": since,
        "stage4_done": bool((onramp or {}).get("stage4_done")),
        "onramp": onramp,
    }


def _plan_dismissals() -> list:
    from mcp.tools_plan import _pain_dismissals

    return _pain_dismissals()


def compute_weeks(last_monday: str, weeks: int = 4) -> list[dict[str, Any]]:
    """`weeks` completed tracker rows ending with the week of `last_monday`, oldest first; each row's
    triggers read the row before it (the first reads none)."""
    from training.muscle_volume import normalize_hevy_items, working_sets_by_muscle
    from training.run_onramp import history_from, running
    from training.session_sequence import block_start
    from training.steps_resolver import steps_range

    from mcp import core
    from mcp.shared_quantities import loss_rate_from_rows, weekly_loss_rate_weeks_from_rows
    from mcp.tools_strength import _read_hevy_all_phases

    weeks = max(1, min(int(weeks), MAX_WEEKS))
    first = mt.shift(last_monday, -7 * weeks)  # one extra week, so the oldest returned row has a prior
    last_sunday = mt.shift(last_monday, 6)
    wrows, w_err = _read(core.query_source, "withings", mt.shift(first, -RATE_4WK_DAYS), last_sunday)
    mrows, m_err = _read(core.query_source, "measurements", "2000-01-01", last_sunday)
    srange, s_err = _read(steps_range, first, last_sunday, fetch=_steps_fetch, derived=False)
    lookback = mt.shift(first, -ANCHOR_LOOKBACK_DAYS)
    # one Hevy read, reaching back to the on-ramp's history_from for Stage 4 and to the block start for the fitness
    # battery's program position (#5078); the other sections keep their window
    hevy, h_err = _read(_read_hevy_all_phases, min(lookback, history_from() or lookback, block_start()), last_sunday)
    # the run gate's walking weeks reach `gated_movements.running.walking_weeks` before the oldest tracked Sunday
    strava, st_err = _read(core.query_source_range, "strava", mt.shift(first, -7 * int(running().get("walking_weeks") or 0)), last_sunday)
    all_items = list((hevy or ([], []))[0] or [])
    items = [r for r in all_items if _day(r) >= lookback]
    instances = None if h_err else pain_instances(all_items)
    dismissals = _read(_plan_dismissals)[0] if instances else None  # read only when a pain note exists; unread = a flag holds
    workouts = normalize_hevy_items(items) if not h_err else []
    series, a_err = _read(_anchor_series, items) if not h_err else (None, h_err)
    guidance = _guidance() if not w_err else None
    fitness, f_err = _read(_fitness_view, last_sunday, None if h_err else all_items)
    days = (srange or {}).get("days") or []

    rows: list[dict[str, Any]] = []
    prior: Optional[dict[str, Any]] = None
    for k in range(weeks + 1):
        mon = mt.shift(first, 7 * k)
        sun = mt.shift(mon, 6)
        week_rate = None if w_err else weekly_loss_rate_weeks_from_rows(wrows or [], sun, weeks=1)[0]
        rate_4wk = None if w_err else loss_rate_from_rows(wrows or [], sun, window_days=RATE_4WK_DAYS)
        row = mt.build_week(
            mon,
            weight=mt.weight_section(sun, week_rate, rate_4wk, None if w_err else _latest_weight(wrows or [], sun), guidance, w_err),
            waist=mt.waist_section(mrows, sun, m_err),
            steps=mt.steps_section([d for d in days if mon <= d["date"] <= sun], s_err),
            anchors=mt.anchors_section(series, sun, a_err),
            volume=mt.volume_section(None if h_err else working_sets_by_muscle(workouts, mon, sun), h_err),
            fitness=mt.fitness_section(_fitness_as_of(fitness, sun, last_sunday), sun, f_err),
            prior=prior,
            built_at=pacific_today(),
            running=running_inputs(sun, None if st_err else (strava or []), None if h_err else all_items, dismissals),
        )
        rows.append(row)
        prior = row
    return rows[1:]


# ── the nightly write ───────────────────────────────────────────────────────────


def write_latest(today: Optional[str] = None) -> dict[str, Any]:
    """Build and store the newest completed week. Raises on a failed write (the leg reports it)."""
    from mcp import core

    monday = mt.last_completed_monday(today or pacific_today())
    row = compute_weeks(monday, weeks=1)[-1]
    key = mt.write_week(core.table, row)
    return {"outcome": "written", **key, "status": row["triggers"]["status"]}


def nightly_leg(today: Optional[str] = None) -> dict[str, Any]:
    """The fail-soft leg the nightly pre-draft calls. Never raises; logs keys and classes only (no values)."""
    try:
        out = write_latest(today)
    except Exception as e:  # noqa: BLE001 — named on the run's result; get_may_tracker reports a stale row
        logger.warning("[may_tracker] nightly write failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
    logger.info("[may_tracker] wrote %s", out.get("sk"))
    return out


# ── the owner's tool ────────────────────────────────────────────────────────────


def _stored_status(expected_monday: str) -> dict[str, Any]:
    from mcp import core

    got = mt.latest_row(core.table)
    row = got.get("row") or {}
    out = {k: v for k, v in got.items() if k != "row"}
    if row:
        out["week_start"] = row.get("week_start")
        out["charter_version"] = row.get("charter_version")
        if row.get("week_start") != expected_monday:
            out["state"] = "stale"
            out["detail"] = (
                f"the newest stored week is {row.get('week_start')}; the newest completed week is {expected_monday} (the nightly leg)"
            )
    return out


def _trend_line(row: dict[str, Any]) -> dict[str, Any]:
    w = row.get("weight") or {}
    return {
        "week_start": row.get("week_start"),
        "rate_lb_wk": (w.get("rate_week") or {}).get("value"),
        "rate_pct_bodyweight_per_wk": (w.get("rate_week") or {}).get("pct_bodyweight_per_wk"),
        "band_position": w.get("band_position_week"),
        "weight_lb": (w.get("weight_lb") or {}).get("value"),
        "steps_mean": (row.get("steps") or {}).get("value"),  # steps-truth: the tracker row's steps section (steps_resolver output)
        "status": (row.get("triggers") or {}).get("status"),
        "fired": [t["id"] for t in (row.get("triggers") or {}).get("fired") or []],
    }


def tool_get_may_tracker(args):
    """The newest completed weeks, live, plus whether the stored nightly row is current."""
    args = args or {}
    try:
        weeks = max(1, min(int(args.get("weeks") or 4), MAX_WEEKS))
    except (TypeError, ValueError):
        weeks = 4
    monday = mt.last_completed_monday(pacific_today())
    rows = compute_weeks(monday, weeks)
    try:
        stored = _stored_status(monday)
    except Exception as e:  # noqa: BLE001 — the live rows still answer; the stored read's failure is named
        stored = {"state": mt.READ_FAILED, "error": type(e).__name__}
    return {
        "latest": rows[-1],
        "trend": [_trend_line(r) for r in rows],
        "stored": stored,
        "privacy": "owner-only: the target date, the band and every number here stay off the site and out of email",
        "version": mt.TRACKER_VERSION,
    }
