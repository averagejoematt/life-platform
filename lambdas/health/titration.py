"""health/titration.py — the weekly calorie titration engine (#5096, epic #5091).

The redlines carried a titration rule in prose (14-day trend, a ~150 kcal step, 14-day spacing,
steps before food) that nothing read. This module is its one reader. The rule's numbers are the
charter's ``nutrition.titration`` block (``config/training_charter.json``); the calorie values it
moves are ``nutrition.calories``; the band it steers into is the charter rate band.

THE DECISION (``decide``, pure — every input is a value the caller already read):

  insufficient data  no measured trend, a provisional trend window, no weigh-in, no band, too few
                     complete food logs (a day under the redlines' dark-day line is not complete), or ANY
                     rule value unreadable (``NEED`` — no fallback literal) -> ``hold`` /
                     ``insufficient_data``, never a guess (ADR-104)
  too early          the experiment day is before ``not_before_day`` -> ``hold`` / ``too_early``
  in the band        -> ``hold`` / ``in_band``
  out of the band    counted in consecutive weekly reads on the same side; fewer than
                     ``consecutive_out_of_band_reads`` -> ``hold`` / ``awaiting_confirmation``
  spacing            a step inside ``min_days_between_steps`` of the last one -> ``hold`` / ``spacing``
  first step         no step yet and fewer than the redlines' ``complete_days_before_first_titration``
                     complete days in the trailing window -> ``hold`` / ``logs_before_first_step``
  above the ceiling  (losing faster than the band) -> ``up`` by the step (panel default R1: eat up to
                     the band now, refit weekly — built on the panel default, pending R1)
  below the floor    (losing slower) -> FEET BEFORE FORK, in order: steps unknown -> ``steps_unknown``;
                     the trailing steps mean under ``steps.floor`` -> ``steps_first``; then the redlines'
                     owner rule (walking FIRST, then food, never both inside the spacing): the first
                     confirmed read is a ``walking_first`` hold, the run waits ``min_days_between_steps``
                     (``walking_first_wait``), and only then ``down`` by the step, never under
                     ``nutrition.calories.planned_minimum_any_weight_kcal`` (``at_minimum`` when there)

THE STEP: the miss outside the band edge (lb/wk) x ``kcal_per_lb_wk`` (3500 kcal per lb over 7 days),
rounded to ``step_rounding_kcal`` and held inside ``min_step_kcal``..``max_step_kcal`` (100..150).

THE BAND (``band_for``): above the landing, the charter rate band through ``training.rate_band``
with the clinical guidance cap applied (the record outranks the band; only its bare cap is read);
from the landing down, the redlines' own landing step (target to cap) through
``training.redline_rate.rate_schedule_step``. One band source — the redlines' old "target +/- 0.5
lb/wk" titration band is retired.

THE RECORD: ``USER#matthew#SOURCE#nutrition_titration`` / ``WEEK#<iso-monday>`` — the shape
``health.calorie_target.resolve`` reads (``kcal``, ``band_low``, ``band_high``, ``reason``) plus the
decision and its inputs. A hold carries the previous target forward, so every week has a record and
the dead-man can tell a missed week from a held one. Written ONCE per week (a conditional put): the
first decision for a week stands. Owner-only (``privacy.field_tiers``); never on a published surface.

I/O lives at the bottom (table injected): the history read, the record read, the write, the
Lambda default reader the resolver uses, and the dead-man row the calibration sweep carries.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional

from health.calorie_target import TITRATION_PK, TITRATION_SK_PREFIX, _day, week_monday

logger = logging.getLogger(__name__)

ENGINE_VERSION = "titration@1.0.0"
CHARTER_PATH = "nutrition.titration"
CALIBRATION_KIND = "nutrition_titration"
DEADMAN_LOG_MARK = "NUTRITION_TITRATION_MISSED"
DECISION_LOG_MARK = "NUTRITION_TITRATION_DECISION"
HOLD, UP, DOWN = "hold", "up", "down"
HISTORY_WEEKS = 8

CharterReader = Callable[[str], Any]


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _default_charter_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def _redline(path: str) -> Any:
    """A value the redlines own (``"<redline id>.<key>"`` or ``"tripwire:<id>.<key>"``), or None. Read, never copied."""
    try:
        from training import owner_redlines as orl  # noqa: PLC0415 — lazy: import-safe offline

        rid, key = path.split(".", 1)
        if rid.startswith("tripwire:"):
            return next((t for t in orl.TRIPWIRES if t.get("id") == rid[9:]), {}).get(key)
        return (orl.REDLINES.get(rid) or {}).get(key)
    except Exception as e:  # noqa: BLE001 — an unreadable redline is None, and None holds the week
        logger.warning("[titration] redline read failed (%s)", type(e).__name__)
        return None


def settings(charter_reader: Optional[CharterReader] = None) -> Dict[str, Any]:
    """The titration rule + the calorie values it moves + the steps floor, from the charter; the logging bars and the
    walking-first cue from the redlines (paths named in the charter block). A value that cannot be read is None — no
    fallback literal — and ``decide`` holds the week as ``insufficient_data``; ``readable`` is False when the rule
    block itself is missing."""
    read = charter_reader or _default_charter_reader
    t = read(CHARTER_PATH)
    t = t if isinstance(t, dict) else {}
    cal = read("nutrition.calories")
    cal = cal if isinstance(cal, dict) else {}
    sbf_raw = t.get("steps_before_food")
    sbf: Dict[str, Any] = sbf_raw if isinstance(sbf_raw, dict) else {}
    logs_raw = t.get("complete_logs")
    logs: Dict[str, Any] = logs_raw if isinstance(logs_raw, dict) else {}
    walk_raw = t.get("walking_first")
    walk: Dict[str, Any] = walk_raw if isinstance(walk_raw, dict) else {}
    band = cal.get("prescribed_band_kcal")
    version = read("version")
    reads = _num(t.get("consecutive_out_of_band_reads"))
    window = _num(sbf.get("steps_window_days"))

    def via(src: Dict[str, Any], key: str, reader: Callable[[str], Any]) -> Any:
        path = src.get(key)
        return reader(path) if isinstance(path, str) and path else None

    return {
        "readable": bool(t),
        "not_before_day": _num(t.get("not_before_day")),
        "trend_days": _num(t.get("trend_days")),
        "min_complete_logs": _num(t.get("never_on_a_week_with_fewer_complete_logs_than")),
        "complete_log_kcal": _num(via(logs, "complete_day_min_kcal_path", _redline)),
        "first_step_complete_days": _num(via(logs, "complete_days_before_first_step_path", _redline)),
        "reads_required": int(reads) if reads is not None else None,
        "min_step_kcal": _num(t.get("min_step_kcal")),
        "max_step_kcal": _num(t.get("max_step_kcal")),
        "rounding_kcal": _num(t.get("step_rounding_kcal")),
        "kcal_per_lb_wk": _num(t.get("kcal_per_lb_wk")),
        "spacing_days": _num(t.get("min_days_between_steps")),
        "steps_window_days": int(window) if window is not None else None,
        "steps_floor": _num(via(sbf, "steps_floor_path", read)),
        "walking_first_action": via(walk, "action_path", _redline),
        "target_kcal": _num(cal.get("target_kcal")),
        "band_kcal": [_num(band[0]), _num(band[1])] if isinstance(band, (list, tuple)) and len(band) == 2 else None,
        "minimum_kcal": _num(cal.get("planned_minimum_any_weight_kcal")),
        "dead_man_armed_from": (t.get("dead_man") or {}).get("armed_from") if isinstance(t.get("dead_man"), dict) else None,
        "charter_version": version if isinstance(version, str) else None,
    }


# every key ``decide`` needs; a None among them holds the week as insufficient_data (never a fallback literal)
NEED = (
    "min_step_kcal",
    "max_step_kcal",
    "rounding_kcal",
    "kcal_per_lb_wk",
    "spacing_days",
    "reads_required",
    "min_complete_logs",
    "complete_log_kcal",
    "first_step_complete_days",
    "not_before_day",
    "trend_days",
    "steps_window_days",
    "steps_floor",
)


def target_week(run_day: Any) -> str:
    """The ISO Monday a run on ``run_day`` decides for: the NEXT week (a decision is made before its week starts)."""
    return (_day(week_monday(run_day)) + timedelta(days=7)).isoformat()


def band_for(weight_lb: Optional[float], guidance_cap: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The loss-rate band at a bodyweight (lb/wk and % of bodyweight). None when the weight or the band is unreadable."""
    if not weight_lb or weight_lb <= 0:
        return None
    from training import rate_band, redline_rate  # noqa: PLC0415 — lazy: the training package is only needed here

    if rate_band.governs(weight_lb):
        b = rate_band.band(weight_lb, guidance_cap)
        if b is None:
            return None
        floor, ceiling, capped, source = b["floor_lb_wk"], b["ceiling_lb_wk"], b["guidance_capped"], "charter rate band"
    else:
        step = redline_rate.rate_schedule_step(weight_lb)
        floor, ceiling = _num(step.get("target")), _num(step.get("cap"))
        if floor is None or ceiling is None:
            return None
        capped = guidance_cap is not None and guidance_cap < ceiling
        if capped:
            ceiling = float(guidance_cap)
            floor = min(floor, ceiling)
        source = "landing schedule step"
    return {
        "floor_lb_wk": float(floor),
        "ceiling_lb_wk": float(ceiling),
        "floor_pct_bodyweight_per_wk": round(float(floor) / weight_lb * 100, 2),
        "ceiling_pct_bodyweight_per_wk": round(float(ceiling) / weight_lb * 100, 2),
        "source": source,
        "guidance_capped": bool(capped),
    }


def step_size(miss_lb_wk: float, cfg: Mapping[str, Any]) -> int:
    """|step| in kcal: the miss x kcal_per_lb_wk, rounded, held inside min..max (the charter's cap is never exceeded)."""
    lo, hi, per, rnd = cfg["min_step_kcal"], cfg["max_step_kcal"], cfg["kcal_per_lb_wk"], cfg["rounding_kcal"]
    raw = abs(miss_lb_wk) * per
    return int(max(lo, min(hi, math.floor(raw / rnd + 0.5) * rnd)))  # half-up: a 125 kcal miss is a 150 step


def _prior(history: Optional[List[Mapping[str, Any]]], week: str) -> List[Mapping[str, Any]]:
    """Records strictly before ``week``, newest first, tombstones dropped."""
    rows = [r for r in history or () if not r.get("tombstone") and str(r.get("week") or "") < week]
    return sorted(rows, key=lambda r: str(r.get("week")), reverse=True)


def decide(
    *,
    week: str,
    trend_lb_wk: Optional[float],
    trend_provisional: Optional[bool],
    weight_lb: Optional[float],
    band: Optional[Mapping[str, Any]],
    steps_avg: Optional[float],
    complete_log_days: Optional[int],
    history: Optional[List[Mapping[str, Any]]],
    expenditure_best_match: Optional[str] = None,
    experiment_day: Optional[int] = None,
    read_errors: Optional[Mapping[str, str]] = None,
    complete_days_trailing: Optional[int] = None,
    cfg: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """THE weekly decision for ``week`` (an ISO Monday). Pure. See the module docstring for the rules."""
    c = dict(cfg if cfg is not None else settings())
    prior = _prior(history, week)
    last = next((r for r in prior if _num(r.get("kcal")) is not None), None)
    base = _num(last.get("kcal")) if last else c.get("target_kcal")
    last_step = next((r for r in prior if r.get("action") in (UP, DOWN)), None)
    last_step_date = str(last_step.get("week")) if last_step else None
    pct = round(trend_lb_wk / weight_lb * 100, 2) if (trend_lb_wk is not None and weight_lb) else None
    out: Dict[str, Any] = {
        "week": week,
        "action": HOLD,
        "step_kcal": 0,
        "base_kcal": int(base) if base is not None else None,
        "new_target_kcal": int(base) if base is not None else None,
        "position": None,
        "out_of_band_reads": 0,
        "reason_code": None,
        "reason": None,
        "detail": None,
        "inputs": {
            "trend_lb_wk": trend_lb_wk,
            "trend_pct_bw": pct,
            "trend_provisional": trend_provisional,
            "band": dict(band) if band else None,
            "steps_avg": int(round(steps_avg)) if steps_avg is not None else None,
            "steps_floor": int(c["steps_floor"]) if c.get("steps_floor") else None,
            "complete_log_days": complete_log_days,
            "complete_days_trailing": complete_days_trailing,
            "expenditure_best_match": expenditure_best_match,
            "last_step_date": last_step_date,
            "base_source": f"titration record WEEK#{last.get('week')}" if last else "charter nutrition.calories.target_kcal",
            "experiment_day": experiment_day,
            "read_errors": dict(read_errors or {}) or None,
        },
        "charter_version": c.get("charter_version"),
        "engine_version": ENGINE_VERSION,
    }

    def hold(code: str, reason: str, detail: Optional[str] = None) -> Dict[str, Any]:
        out.update(reason_code=code, reason=reason, detail=detail)
        return _with_band(out, c)

    missing = [k for k in NEED if c.get(k) is None]
    if not c.get("readable") or missing or base is None:
        return hold(
            "insufficient_data",
            "insufficient data: the charter's titration rule or calorie target is unreadable",
            f"unreadable: {', '.join(missing) or 'the rule block or the base target'}",
        )
    if experiment_day is not None and experiment_day < c["not_before_day"]:
        return hold("too_early", f"too early: no titration before experiment day {int(c['not_before_day'])}")
    if trend_lb_wk is None or trend_provisional or trend_provisional is None:
        return hold("insufficient_data", "insufficient data: no measured 14-day trend this week")
    if not weight_lb or not band:
        return hold("insufficient_data", "insufficient data: no weigh-in or no readable band")
    if complete_log_days is None or complete_log_days < c["min_complete_logs"]:
        return hold(
            "insufficient_data",
            f"insufficient data: fewer than {int(c['min_complete_logs'])} complete food logs in the week",
            f"complete logs: {complete_log_days if complete_log_days is not None else 'unreadable'}",
        )

    floor, ceiling = float(band["floor_lb_wk"]), float(band["ceiling_lb_wk"])
    position = "below" if trend_lb_wk < floor else "above" if trend_lb_wk > ceiling else "in"
    out["position"] = position
    detail = f"trend {trend_lb_wk:+.2f} lb/wk ({pct} %BW/wk) against the band {floor:g}-{ceiling:g} lb/wk ({band.get('source')})"
    if position == "in":
        return hold("in_band", "in the band: hold", detail)

    prev = prior[0] if prior else None
    contiguous = bool(prev) and str(prev.get("week")) == (_day(week) - timedelta(days=7)).isoformat()  # type: ignore[union-attr]
    carried = contiguous and prev.get("position") == position and prev.get("action") == HOLD  # type: ignore[union-attr]
    reads = int(_num(prev.get("out_of_band_reads")) or 0) + 1 if carried else 1  # type: ignore[union-attr]
    out["out_of_band_reads"] = reads
    side = "under the band floor" if position == "below" else "over the band ceiling"
    if reads < c["reads_required"]:
        return hold("awaiting_confirmation", f"{side} on read {reads} of {c['reads_required']}: hold until it repeats", detail)
    if last_step_date and (_day(week) - _day(last_step_date)).days < c["spacing_days"]:
        return hold("spacing", f"{side}, but the last step ({last_step_date}) is inside the {int(c['spacing_days'])}-day spacing", detail)

    first = last_step is None and (last is None or _num(last.get("kcal")) == c.get("target_kcal"))
    need_days = int(c["first_step_complete_days"])
    if first and (complete_days_trailing is None or complete_days_trailing < need_days):
        return hold(
            "logs_before_first_step",
            f"{side}, but the first step waits for {need_days} complete days of food logs in a row",
            detail
            + f"; complete days in the last {need_days}: {complete_days_trailing if complete_days_trailing is not None else 'unreadable'}",
        )

    miss = (trend_lb_wk - ceiling) if position == "above" else (floor - trend_lb_wk)
    step = step_size(miss, c)
    if position == "above":
        out.update(action=UP, step_kcal=step, new_target_kcal=int(base + step))
        return _stepped(out, c, f"+{step} kcal: {side} on {reads} weekly reads (eat up to the band, refit weekly)", detail)

    if steps_avg is None:
        return hold("steps_unknown", f"{side}, steps unreadable: steps come before food, so food holds", detail)
    if steps_avg < c["steps_floor"]:
        return hold(
            "steps_first",
            f"{side}, steps mean under the {int(c['steps_floor']):,} floor: walk to the floor before food comes down",
            detail + f"; steps mean {int(round(steps_avg)):,} over {c['steps_window_days']} days",
        )
    walked = _walking_first_since(prior, week)
    if walked is None:
        return hold(
            "walking_first",
            f"{side} with steps at the floor: walking first ({str(c.get('walking_first_action') or 'feet before fork').split(';')[0]}); "
            f"food comes down no sooner than {int(c['spacing_days'])} days on, if the trend is still under the floor",
            detail,
        )
    if (_day(week) - _day(walked)).days < c["spacing_days"]:
        return hold(
            "walking_first_wait",
            f"{side}: the walking-first week ({walked}) is inside the {int(c['spacing_days'])}-day spacing, so food holds",
            detail,
        )
    minimum = c.get("minimum_kcal")
    new = base - step if minimum is None else max(base - step, minimum)
    if new >= base:
        return hold("at_minimum", f"{side}, but the target is already at the planned minimum", detail)
    taken = int(base - new)
    out.update(action=DOWN, step_kcal=-taken, new_target_kcal=int(new))
    return _stepped(out, c, f"-{taken} kcal: {side} on {reads} weekly reads, steps at the floor, walking first from {walked}", detail)


def _walking_first_since(prior: List[Mapping[str, Any]], week: str) -> Optional[str]:
    """The week of the walking-first hold in the unbroken run of weekly below-floor holds just before ``week``, or None
    (the run broke: back in the band, a step, a missing week -> walking comes first again)."""
    expect = _day(week)
    for r in prior:
        expect -= timedelta(days=7)
        if str(r.get("week")) != expect.isoformat() or r.get("position") != "below" or r.get("action") != HOLD:
            return None
        if r.get("reason_code") == "walking_first":
            return str(r.get("week"))
    return None


def _stepped(out: Dict[str, Any], c: Mapping[str, Any], reason: str, detail: str) -> Dict[str, Any]:
    out.update(reason_code=f"step_{out['action']}", reason=reason, detail=detail)
    return _with_band(out, c)


def _with_band(out: Dict[str, Any], c: Mapping[str, Any]) -> Dict[str, Any]:
    """``kcal`` (the resolver's field) = the new target; the calorie band = the charter's prescribed band moved by the
    same offset the titration has moved the target from the charter's opening target."""
    kcal = out.get("new_target_kcal")
    out["kcal"] = kcal
    band, target = c.get("band_kcal"), c.get("target_kcal")
    if kcal is not None and band and None not in band and target is not None:
        off = kcal - target
        out["band_low"], out["band_high"] = int(band[0] + off), int(band[1] + off)
    else:
        out["band_low"] = out["band_high"] = None
    return out


# ── I/O (table injected) ─────────────────────────────────────────────────────────────────


def _to_ddb(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_ddb(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [_to_ddb(x) for x in v]
    return str(v)


def record_item(decision: Mapping[str, Any], decided_on: str) -> Dict[str, Any]:
    """The DynamoDB item for a decision (Decimal numbers, None fields dropped)."""
    item = {k: v for k, v in decision.items() if v is not None}
    item.update(pk=TITRATION_PK, sk=f"{TITRATION_SK_PREFIX}{decision['week']}", source="nutrition_titration", decided_on=decided_on)
    item["tier"] = "owner_only"
    return _to_ddb(item)


def write_decision(table: Any, decision: Mapping[str, Any], decided_on: str) -> str:
    """Write the week's record once: ``written``, or ``exists`` when a decision for the week is already on file."""
    try:
        table.put_item(Item=record_item(decision, decided_on), ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only the conditional failure is "exists"; anything else propagates
        if "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e):
            return "exists"
        raise
    return "written"


def read_record(table: Any, week: str) -> Optional[Dict[str, Any]]:
    """The stored record for ``week`` (an ISO Monday), or None. A tombstoned record is absent."""
    from experiment.phase_filter import singleton_visible  # noqa: PLC0415 — the #946 item-level tombstone rule

    item = (table.get_item(Key={"pk": TITRATION_PK, "sk": f"{TITRATION_SK_PREFIX}{week}"}) or {}).get("Item")
    return dict(item) if item and singleton_visible(item) else None


def read_history(table: Any, before_week: str, weeks: int = HISTORY_WEEKS) -> List[Dict[str, Any]]:
    """Records for the ``weeks`` weeks before ``before_week``, newest first. Raises on a failed read."""
    start = (_day(before_week) - timedelta(days=7 * weeks)).isoformat()
    end = (_day(before_week) - timedelta(days=1)).isoformat()
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
        ExpressionAttributeValues={":pk": TITRATION_PK, ":lo": f"{TITRATION_SK_PREFIX}{start}", ":hi": f"{TITRATION_SK_PREFIX}{end}"},
        ScanIndexForward=False,
    )
    return [dict(i) for i in resp.get("Items") or [] if not i.get("tombstone")]


_CACHE: Dict[str, tuple] = {}
_CACHE_TTL_S = 900


def lambda_default_reader() -> Optional[Callable[[str], Optional[Dict[str, Any]]]]:
    """The reader ``calorie_target.resolve`` uses when no caller injects one: inside a Lambda only (never in a unit
    test or a laptop session), over TABLE_NAME, cached 15 min per week. A failed read is None (the charter answers),
    logged by class."""
    if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return None

    def read(week: str) -> Optional[Dict[str, Any]]:
        hit = _CACHE.get(week)
        if hit and time.time() - hit[0] < _CACHE_TTL_S:
            return hit[1]
        try:
            import boto3  # noqa: PLC0415

            table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
                os.environ.get("TABLE_NAME", "life-platform")
            )
            rec = read_record(table, week)
        except Exception as e:  # noqa: BLE001 — the charter target answers; the class is logged
            logger.warning("[titration] record read failed (%s) — the charter target answers", type(e).__name__)
            rec = None
        _CACHE[week] = (time.time(), rec)
        return rec

    return read


# ── the dead-man (a row in training.calibration_cadence's block; the Telegram sweep alerts on it) ──────


def deadman_row(today: str, has_record: Optional[bool], armed_from: Optional[str]) -> Dict[str, Any]:
    """The current week's titration record, as a calibration-block row. ``has_record`` None = the read failed.
    ``missed_2`` (the block's dead-man state) when armed and no record exists for the week. Pure."""
    from training import calibration_cadence as cc  # noqa: PLC0415 — the block's vocabulary

    week = week_monday(today)
    row: Dict[str, Any] = {"kind": CALIBRATION_KIND, "week": week, "cycle_start": week, "prompt": None, "source": TITRATION_PK}
    if has_record is None:
        return {**row, "state": cc.READ_FAILED}
    if has_record:
        return {**row, "state": cc.OK}
    if not armed_from or today < armed_from:
        return {**row, "state": cc.OK, "detail": f"no record for {week}; the dead-man is armed from {armed_from}"}
    logger.warning("%s week=%s", DEADMAN_LOG_MARK, week)
    return {
        **row,
        "state": cc.MISSED_2,
        "missed_cycles": 1,
        "last_logged": None,
        "alert": (
            f"No calorie titration decision was written for the week of {week}. The weekly titration run (the nightly "
            "pre-draft's titration leg) did not run or failed; the charter target is serving instead. Check the run log."
        ),
    }


def calibration_row_from_table(table: Any, today: str) -> Dict[str, Any]:
    """The dead-man row over one table. Never raises (a failed read is ``read_failed``)."""
    try:
        has: Optional[bool] = read_record(table, week_monday(today)) is not None
    except Exception as e:  # noqa: BLE001 — named on the row
        logger.warning("[titration] dead-man read failed (%s)", type(e).__name__)
        has = None
    return deadman_row(today, has, settings().get("dead_man_armed_from"))
