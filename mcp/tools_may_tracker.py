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
  Hevy       ONE read (`tools_strength._read_hevy_all_phases`) serves the week's working sets
             (`muscle_volume.working_sets_by_muscle`) and the four core anchors' e1RM series
             (`strength_helpers.extract_hevy_sessions` over `plan_draft_evidence._core_anchor_identities`);
  run gate   (#5090) the same Hevy rows plus ONE Strava read feed `shared_quantities.walking_layer` (THE walking
             definition) for each of the gate's walking weeks — the walking modality's hours — and each week's
             lower-leg pain flag (a pain-lexicon note naming a lower-leg site, `training.training_notes` +
             `training.steps_ramp.is_lower_leg`); a lower-leg pain note inside the steps ramp's quiet period
             (`steps_ramp.RELEASE_QUIET_DAYS`) before the Sunday is the hold. Owner dismissals are not read
             here (the plan's steps ramp reads them); an unread source is None, never a pain-free week.

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


def _rows_in(rows: Optional[list], start: str, end: str) -> list:
    return [r for r in rows or [] if start <= str(r.get("date") or str(r.get("sk") or "")[5:15])[:10] <= end]


def _lower_leg_pain(hevy: Optional[list], start: str, end: str) -> Optional[bool]:
    """Any Hevy exercise note in [start, end] that the pain net flags AND that names a lower-leg site; None = unread."""
    from training.steps_ramp import is_lower_leg
    from training.training_notes import pain_lexicon_hit

    if hevy is None:
        return None
    notes = [str(e.get("notes") or e.get("note") or "") for r in _rows_in(hevy, start, end) for e in r.get("exercises") or []]
    return any(pain_lexicon_hit(n) and is_lower_leg(n) for n in notes)


def running_inputs(sunday: str, strava: Optional[list], hevy: Optional[list]) -> dict[str, Any]:
    """The run gate's walking weeks (newest first) and hold for the week ending `sunday`, from rows already read."""
    from training import run_onramp
    from training.steps_ramp import RELEASE_QUIET_DAYS

    from mcp import shared_quantities

    def _slice(source: str, start: str, end: str) -> list:
        rows = strava if source == "strava" else hevy
        if rows is None:
            raise LookupError(f"{source} unread")
        return _rows_in(rows, start, end)

    walking_weeks = []
    for k in range(int(run_onramp.running().get("walking_weeks") or 0)):
        end = mt.shift(sunday, -7 * k)
        layer = shared_quantities.walking_layer(end, days=7, today=mt.shift(sunday, 1), read=_slice)
        hours = None if not layer or layer.get("total_hr") is None else float((layer.get("by_modality") or {}).get("walking") or 0.0)
        walking_weeks.append({"week_start": mt.shift(end, -6), "hours": hours, "pain_flag": _lower_leg_pain(hevy, mt.shift(end, -6), end)})
    recent = _lower_leg_pain(hevy, mt.shift(sunday, -(RELEASE_QUIET_DAYS - 1)), sunday)  # the steps ramp's quiet period
    holds = None if recent is None else ([f"strain_flag:lower_leg_note_to_{sunday}"] if recent else [])
    # Stage 4: his logged run/walks (a treadmill or running block whose note names the run/walk, its level and RPE)
    blocks = [
        {"date": str(r.get("date") or str(r.get("sk") or "")[5:15])[:10], "note": e.get("notes") or e.get("note")}
        for r in _rows_in(hevy, "0000-00-00", sunday)
        for e in r.get("exercises") or []
        if re.search(r"treadmill|running|\brun\b", str(e.get("name") or ""), re.IGNORECASE)
    ]
    onramp = run_onramp.stage_progress(run_onramp.performed_from_notes(blocks), holds) if hevy is not None else None
    return {
        "walking_weeks": walking_weeks,
        "holds": holds,
        "stage4_done": bool((onramp or {}).get("stage4_done")),
        "onramp": onramp,
    }


def compute_weeks(last_monday: str, weeks: int = 4) -> list[dict[str, Any]]:
    """`weeks` completed tracker rows ending with the week of `last_monday`, oldest first; each row's
    triggers read the row before it (the first reads none)."""
    from training.muscle_volume import normalize_hevy_items, working_sets_by_muscle
    from training.run_onramp import running
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
    hevy, h_err = _read(_read_hevy_all_phases, mt.shift(first, -ANCHOR_LOOKBACK_DAYS), last_sunday)
    # the run gate's walking weeks reach `gated_movements.running.walking_weeks` before the oldest tracked Sunday
    strava, st_err = _read(core.query_source_range, "strava", mt.shift(first, -7 * int(running().get("walking_weeks") or 0)), last_sunday)
    items = list((hevy or ([], []))[0] or [])
    workouts = normalize_hevy_items(items) if not h_err else []
    series, a_err = _read(_anchor_series, items) if not h_err else (None, h_err)
    guidance = _guidance() if not w_err else None
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
            fitness=mt.fitness_section(None),
            prior=prior,
            built_at=pacific_today(),
            running=running_inputs(sun, None if st_err else (strava or []), None if h_err else items),
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
