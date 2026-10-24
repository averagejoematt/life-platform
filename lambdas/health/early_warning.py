"""health/early_warning.py — the relapse early-warning detector (IC-5, #5121, epic #5120).

THE DEFECT. ``compute.daily_insight_compute_lambda.detect_early_warning`` saw four markers (journal sparse,
nutrition gap, a T0 habit drop, recovery sliding) while ``config/user_goals.json`` ``failure_mode`` lists the
lapse he has lived through — and the panel's tell is the cadence that stops first: the weigh-ins stop at every
past low, the food log goes dark, the steps fall, the check-in goes quiet, the scale turns up, the sessions thin.
None of those had a detector, and the warning it did raise went into the SHARED brief context, whose TL;DR is the
homepage pull-quote — a sensitive mind state one prompt away from a published surface, answered by every coach
at once while the protocol names ONE (``coach.response_protocol``, #5126).

THE CONTRACT.
  * Ten markers: the four above, plus six cadence signals whose thresholds are the charter's ``early_warning``
    block (``config/training_charter.json``, 1.26.0 — platform defaults pending an owner ruling, two of them
    restating his own ``failure_mode`` words). A threshold the charter does not carry leaves its signal
    UNEVALUATED (named on the row), never a literal fallback.
  * ``min_signals`` (2) markers together raise ONE flag; one alone never does.
  * A channel with no record inside ``lookback_days`` is ABSENT, never silent (ADR-104): a source he never used
    cannot "stop" — the evening check-in had no row at all when this landed.
  * Owner-only (``privacy.field_tiers``: ``early_warning_flag`` TIER_OWNER_ONLY). The row is
    ``USER#matthew#SOURCE#early_warning_flag`` / ``DATE#<evaluated day>``, written every run (an inactive day is
    what ends an episode). Its readers: ``coach.coach_event_triggers`` (the response owner's ONE text per episode
    on the owner's own Telegram seat) and ``coach.coach_domain_facts`` (the mind coach's own thread). No web,
    email, content or site-generator module reads it, and the support contact hears nothing (R2 pending,
    default owner-only) — ``tests/test_relapse_early_warning_5121.py`` holds both sets.

Shape: a pure core (markers, thresholds, evidence — no I/O, no clock) and a thin I/O half (``gather`` over an
injected range reader, ``store``, ``read_recent``). Fail-soft everywhere: an unreadable family is absent.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from common.digest_utils import safe_float

logger = logging.getLogger(__name__)

SOURCE = "early_warning_flag"
VERSION = "early-warning@2.0.0"
CHARTER_PATH = "early_warning"
TIER = "owner_only"

# The four markers the detector read before #5121. Their thresholds predate the charter block and stay here
# (moved, not re-ruled): journal < 50 / nutrition < 40 on 2 of the last 3 days, a 15-point T0 habit drop.
BASE_MARKERS = ("journal_sparse", "nutrition_gap", "habit_declining", "recovery_sliding")
CADENCE_SIGNALS = ("weigh_in_cadence", "food_log_gap", "step_drop", "checkin_silence", "weight_reversal", "sessions_below_plan")
_COMPONENT_FLOORS = (("journal_sparse", "journal", 50), ("nutrition_gap", "nutrition", 40))
_HABIT_DROP = 0.15

BASE_LABELS = {
    "journal_sparse": "journal tracking dropped off (2+ of last 3 days)",
    "nutrition_gap": "nutrition score critically low (2+ of last 3 days)",
    "habit_declining": "T0 habit completion dropped 15%+ this week",
    "recovery_sliding": "recovery/readiness declining 3 consecutive days",
}
_CHECKIN_FIELDS = ("hunger", "stress", "cravings")
_RECENT_ROWS_DAYS = 30


# ── small pure helpers ───────────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _day(v: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _row_day(row: Mapping[str, Any]) -> Optional[str]:
    d = row.get("date") or str(row.get("sk", ""))[len("DATE#") :][:10]
    return str(d)[:10] if _day(d) else None


def _span(as_of: date, days: int, end_offset: int = 0) -> list[str]:
    """``days`` ISO dates ending ``end_offset`` days before ``as_of``, oldest first."""
    return [(as_of - timedelta(days=end_offset + i)).isoformat() for i in range(days - 1, -1, -1)]


def _mean(vals: list) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _t0_rate(rec: Mapping[str, Any]) -> Optional[float]:
    """Tier-0 habit completion (0..1) off a `habit_scores` row (#2221). `tier0_pct` is what
    BOTH writers of that partition write (daily_brief_lambda's store_habit_scores +
    daily_metrics_compute); `t0_completion_rate` is a legacy alias nothing has ever written.
    None-aware: `a or b` read a MEASURED 0.0 day as absence, dropping it from averages (ADR-104)."""
    val = safe_float(rec, "tier0_pct")
    return val if val is not None else safe_float(rec, "t0_completion_rate")


# ── thresholds: the charter block, read — never a fallback literal ───────────────────────


def _default_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def _complete_log_kcal() -> Optional[float]:
    """The titration rule's complete-log line (the redlines' dark-day kcal), the one the food_log_gap signal reads."""
    try:
        from health import titration  # noqa: PLC0415

        return _num(titration.settings().get("complete_log_kcal"))
    except Exception as e:  # noqa: BLE001 — unreadable line -> the signal is unevaluated
        logger.warning("[early-warning] complete-log line unreadable: %s", type(e).__name__)
        return None


def settings(charter_reader: Optional[Callable[[str], Any]] = None, complete_log_kcal: Any = "read") -> dict:
    """``{min_signals, lookback_days, signals{id: {...}}, charter_version, complete_log_kcal}`` from the charter.
    A missing block gives ``min_signals`` None (the flag cannot be raised); a missing signal is an empty dict."""
    read = charter_reader or _default_reader
    try:
        block = read(CHARTER_PATH)
        version = read("version")
    except Exception as e:  # noqa: BLE001
        logger.warning("[early-warning] charter unreadable: %s", type(e).__name__)
        block, version = None, None
    block = block if isinstance(block, dict) else {}
    raw_sigs = block.get("signals")
    sigs: dict = raw_sigs if isinstance(raw_sigs, dict) else {}
    kcal = _complete_log_kcal() if complete_log_kcal == "read" else _num(complete_log_kcal)
    ms, lb = _num(block.get("min_signals")), _num(block.get("lookback_days"))
    return {
        "min_signals": int(ms) if ms else None,
        "lookback_days": int(lb) if lb else None,
        "signals": {k: (sigs.get(k) if isinstance(sigs.get(k), dict) else {}) for k in CADENCE_SIGNALS},
        "complete_log_kcal": kcal,
        "charter_version": version if isinstance(version, str) else None,
    }


def _ints(cfg: Mapping[str, Any], *keys: str) -> Optional[list]:
    vals = [_num(cfg.get(k)) for k in keys]
    return None if any(v is None for v in vals) else vals


# ── the four pre-#5121 markers ───────────────────────────────────────────────────────────


def base_markers(computed_records_7d: list, habit_7d: list, declining: list) -> list:
    """journal_sparse / nutrition_gap (component under its floor on 2+ of the last 3 days), habit_declining
    (T0 completion dropped >= 15pp, last-3d vs prior-4d) and recovery_sliding (from the trend detector)."""
    markers = []
    sorted_recs = sorted(computed_records_7d or [], key=lambda x: x.get("date", ""))
    recent_3 = sorted_recs[-3:]
    for marker, field, floor in _COMPONENT_FLOORS:
        scores = [safe_float(r.get("component_scores", {}), field) for r in recent_3]
        if sum(1 for s in scores if s is not None and s < floor) >= 2:
            markers.append(marker)

    sorted_habits = sorted(habit_7d or [], key=lambda x: x.get("date", ""))
    if len(sorted_habits) >= 4:
        recent_h = sorted_habits[-3:]
        prior_h = sorted_habits[-7:-3] if len(sorted_habits) >= 7 else sorted_habits[:-3]
        recent_c = _mean([v for v in (_t0_rate(r) for r in recent_h) if v is not None])
        prior_c = _mean([v for v in (_t0_rate(r) for r in prior_h) if v is not None])
        if recent_c is not None and prior_c is not None and prior_c - recent_c >= _HABIT_DROP:
            markers.append("habit_declining")

    declining_metrics = {d.get("metric") for d in declining or []}
    if "recovery" in declining_metrics or "readiness_score" in declining_metrics:
        markers.append("recovery_sliding")
    return markers


# ── the six cadence signals (each: (fired, evidence) or None = unevaluated) ──────────────


def _silent_run(days_with: set, as_of: date, lookback: int) -> Optional[tuple]:
    """(consecutive days ending on as_of with no record, last record date) — None when nothing in the lookback."""
    window = set(_span(as_of, lookback))
    seen = sorted(d for d in days_with if d in window)
    if not seen:
        return None
    last = seen[-1]
    return (as_of - _day(last)).days, last


def weigh_in_cadence(weigh_days: set, as_of: date, cfg: Mapping, lookback: int) -> Optional[tuple]:
    n = _ints(cfg, "silent_days")
    run = _silent_run(weigh_days, as_of, lookback) if n else None
    if run is None or n is None:
        return None
    gap, last = run
    return gap >= n[0], f"No weigh-in for {gap} day(s) (last Withings weigh-in {last}; the line is {int(n[0])} silent days)."


def checkin_silence(answered_days: set, as_of: date, cfg: Mapping, lookback: int) -> Optional[tuple]:
    n = _ints(cfg, "silent_days")
    run = _silent_run(answered_days, as_of, lookback) if n else None
    if run is None or n is None:
        return None
    gap, last = run
    return gap >= n[0], f"No evening check-in answered for {gap} evening(s) (last answered {last}; the line is {int(n[0])})."


def food_log_gap(
    food_kcal: Mapping[str, Optional[float]], as_of: date, cfg: Mapping, lookback: int, line: Optional[float]
) -> Optional[tuple]:
    n = _ints(cfg, "window_days", "min_gap_days")
    if not n or line is None or not any(d in food_kcal for d in _span(as_of, lookback)):
        return None
    window = _span(as_of, int(n[0]))
    gaps = [d for d in window if (food_kcal.get(d) is None) or (food_kcal[d] < line)]
    return len(gaps) >= n[1], (
        f"Food log complete on {len(window) - len(gaps)} of the last {len(window)} days "
        f"(MacroFactor; a complete day is at or above {int(line)} kcal logged; the line is {int(n[1])} gap days)."
    )


def step_drop(steps: Mapping[str, float], as_of: date, cfg: Mapping) -> Optional[tuple]:
    n = _ints(cfg, "recent_days", "baseline_days", "min_drop_pct", "min_recent_n", "min_baseline_n")
    if not n:
        return None
    recent = [steps[d] for d in _span(as_of, int(n[0])) if d in steps]
    base = [steps[d] for d in _span(as_of, int(n[1]), end_offset=int(n[0])) if d in steps]
    if len(recent) < n[3] or len(base) < n[4]:
        return None
    r, b = _mean(recent), _mean(base)
    if not b:
        return None
    drop = (b - r) / b * 100
    return drop >= n[2], (
        f"Steps: {int(n[0])}-day mean {round(r):,} against {round(b):,} over the {int(n[1])} days before "
        f"({'-' if drop >= 0 else '+'}{abs(round(drop))}%; n={len(recent)} and {len(base)}; the line is a {int(n[2])}% drop)."
    )


def weight_reversal(weights: Mapping[str, float], as_of: date, cfg: Mapping) -> Optional[tuple]:
    n = _ints(cfg, "window_days", "min_rise_lb", "min_n_per_window")
    if not n:
        return None
    w = int(n[0])
    recent = [weights[d] for d in _span(as_of, w) if d in weights]
    prior = [weights[d] for d in _span(as_of, w, end_offset=w) if d in weights]
    if len(recent) < n[2] or len(prior) < n[2]:
        return None
    rise = _mean(recent) - _mean(prior)
    return rise >= n[1], (
        f"Weigh-in {w}-day mean {'up' if rise >= 0 else 'down'} {abs(round(rise, 1))} lb on the {w} days before "
        f"(n={len(recent)} and {len(prior)}; the line is a {n[1]:g} lb rise)."
    )


def sessions_below_plan(session_days: list, as_of: date, cfg: Mapping, lookback: int, plan: Any = None) -> Optional[tuple]:
    n = _ints(cfg, "min_sessions_per_wk", "consecutive_weeks")
    if not n or not any(d in set(_span(as_of, lookback)) for d in session_days):
        return None
    weeks = [sum(1 for d in session_days if d in set(_span(as_of, 7, end_offset=7 * k))) for k in range(int(n[1]))]
    plan_txt = f"; the plan is {int(_num(plan))} lifting days" if _num(plan) else ""
    return all(c < n[0] for c in weeks), (
        f"Hevy sessions in the last {int(n[1])} 7-day weeks, newest first: {', '.join(str(c) for c in weeks)} "
        f"(the line is under {int(n[0])} a week in each{plan_txt})."
    )


def cadence_markers(cadence: Mapping[str, Any], as_of: date, s: Mapping[str, Any]) -> tuple:
    """(fired ids, {id: evidence line} for every EVALUATED signal, [unevaluated ids])."""
    sig, lb = s.get("signals") or {}, s.get("lookback_days")
    cadence = cadence or {}
    if not lb:
        return [], {}, list(CADENCE_SIGNALS)
    calls = {
        "weigh_in_cadence": lambda: weigh_in_cadence(set(cadence.get("weights") or {}), as_of, sig["weigh_in_cadence"], lb),
        "food_log_gap": lambda: food_log_gap(cadence.get("food_kcal") or {}, as_of, sig["food_log_gap"], lb, s.get("complete_log_kcal")),
        "step_drop": lambda: step_drop(cadence.get("resolved_steps") or {}, as_of, sig["step_drop"]),
        "checkin_silence": lambda: checkin_silence(set(cadence.get("checkin_days") or ()), as_of, sig["checkin_silence"], lb),
        "weight_reversal": lambda: weight_reversal(cadence.get("weights") or {}, as_of, sig["weight_reversal"]),
        "sessions_below_plan": lambda: sessions_below_plan(
            list(cadence.get("session_days") or ()), as_of, sig["sessions_below_plan"], lb, cadence.get("plan_sessions")
        ),
    }
    fired, evidence, unevaluated = [], {}, []
    for sid in CADENCE_SIGNALS:
        try:
            out = calls[sid]() if sid in cadence.get("_read", CADENCE_SIGNALS) else None
        except Exception as e:  # noqa: BLE001 — one bad signal never silences the others
            logger.warning("[early-warning] %s failed: %s", sid, type(e).__name__)
            out = None
        if out is None:
            unevaluated.append(sid)
            continue
        evidence[sid] = out[1]
        if out[0]:
            fired.append(sid)
    return fired, evidence, unevaluated


# ── the detector ─────────────────────────────────────────────────────────────────────────


def detect(computed_records_7d, habit_7d, declining, cadence=None, as_of=None, s=None) -> dict:
    """Every marker, the two-signal rule and the owner-only summary. ``s`` is ``settings()`` (read when None)."""
    s = settings() if s is None else s
    markers = base_markers(computed_records_7d, habit_7d, declining)
    evidence = {m: BASE_LABELS[m] for m in markers}
    unevaluated: list = []
    day = _day(as_of)
    if cadence is not None and day is not None:
        fired, ev, unevaluated = cadence_markers(cadence, day, s)
        markers += fired
        evidence.update(ev)
    else:
        unevaluated = list(CADENCE_SIGNALS)
    min_signals = s.get("min_signals")
    active = bool(min_signals) and len(markers) >= min_signals
    return {
        "active": active,
        "markers": markers,
        "evidence": evidence,
        "unevaluated": unevaluated,
        "min_signals": min_signals,
        "charter_version": s.get("charter_version"),
    }


def summary_block(result: Mapping[str, Any]) -> str:
    """The owner-only text of an active flag ('' when inactive). Never handed to the shared brief context."""
    if not result.get("active"):
        return ""
    ev = result.get("evidence") or {}
    lines = [ev.get(m) or m for m in result.get("markers") or []]
    return (
        "⚠️ EARLY WARNING: Multiple deterioration markers active simultaneously:\n"
        + "\n".join(f"  • {d}" for d in lines)
        + "\nThis pattern often precedes broader health score decline. Address proactively."
    )


# ── I/O half ─────────────────────────────────────────────────────────────────────────────


def gather(fetch_range: Callable[[str, str, str], list], as_of: str, s: Mapping[str, Any]) -> Optional[dict]:
    """The six channels over the lookback, through the caller's per-source range reader. A family that fails is
    left out of ``_read`` (unevaluated), never zero."""
    day, lb = _day(as_of), s.get("lookback_days")
    if day is None or not lb:
        return None
    sig = s.get("signals") or {}
    sd = sig.get("step_drop") or {}
    steps_days = int((_num(sd.get("recent_days")) or 0) + (_num(sd.get("baseline_days")) or 0))
    start = (day - timedelta(days=max(lb, steps_days) - 1)).isoformat()
    out: dict = {"_read": []}

    def family(ids: tuple, fn: Callable[[], None]) -> None:
        try:
            fn()
            out["_read"].extend(ids)
        except Exception as e:  # noqa: BLE001
            logger.warning("[early-warning] %s read failed: %s", ids, type(e).__name__)

    def weights() -> None:
        rows = fetch_range("withings", start, as_of)
        out["weights"] = {d: w for r in rows if (d := _row_day(r)) and (w := _num(r.get("weight_lbs"))) is not None}

    def food() -> None:
        out["food_kcal"] = {d: _num(r.get("total_calories_kcal")) for r in fetch_range("macrofactor", start, as_of) if (d := _row_day(r))}

    def steps() -> None:
        from common import metric_truth  # noqa: PLC0415

        rows = {src: fetch_range(src, start, as_of) for src in metric_truth.steps_sources()}
        out["resolved_steps"] = {
            d: r.value for d, r in metric_truth.resolve_by_date(metric_truth.STEPS, rows).items() if r.value is not None
        }

    def checkins() -> None:
        rows = fetch_range("evening_checkin", start, as_of)
        out["checkin_days"] = sorted({d for r in rows if (d := _row_day(r)) and any(_num(r.get(f)) is not None for f in _CHECKIN_FIELDS)})

    def sessions() -> None:
        rows = [r for r in fetch_range("hevy", start, as_of) if r.get("source_workout_id") and not r.get("tombstone")]
        seen: dict = {}
        for r in rows:
            seen.setdefault(str(r.get("source_workout_id")), _row_day(r))
        out["session_days"] = [d for d in seen.values() if d]
        out["plan_sessions"] = _default_reader(str(sig.get("sessions_below_plan", {}).get("plan_ref") or "split.lifting_days_per_wk"))

    family(("weigh_in_cadence", "weight_reversal"), weights)
    family(("food_log_gap",), food)
    family(("step_drop",), steps)
    family(("checkin_silence",), checkins)
    family(("sessions_below_plan",), sessions)
    return out


def item(as_of: str, result: Mapping[str, Any], user_prefix: str = "USER#matthew#SOURCE#") -> dict:
    """The owner-only row for ``as_of`` (strings, ints and a bool only — nothing DynamoDB rejects)."""
    row = {
        "pk": user_prefix + SOURCE,
        "sk": "DATE#" + as_of,
        "date": as_of,
        "active": bool(result.get("active")),
        "markers": list(result.get("markers") or []),
        "evidence": {k: str(v) for k, v in (result.get("evidence") or {}).items()},
        "unevaluated": list(result.get("unevaluated") or []),
        "tier": TIER,
        "version": VERSION,
    }
    if result.get("min_signals"):
        row["min_signals"] = int(result["min_signals"])
    if result.get("charter_version"):
        row["charter_version"] = result["charter_version"]
    return row


def store(table: Any, as_of: str, result: Mapping[str, Any], user_prefix: str = "USER#matthew#SOURCE#") -> bool:
    """Write the day's row (overwritten on a re-run). Fail-soft: False on any trouble."""
    try:
        row = item(as_of, result, user_prefix)
        try:
            from common.compute_metadata import tag_record  # noqa: PLC0415

            row = tag_record(row, source_id=SOURCE)
        except ImportError:
            pass
        table.put_item(Item=row)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[early-warning] store failed for %s: %s", as_of, type(e).__name__)
        return False


def run(
    table: Any, fetch_range: Callable, as_of: str, computed_records_7d, habit_7d, declining, user_prefix: str = "USER#matthew#SOURCE#"
) -> tuple:
    """The daily-insight entry: settings -> gather -> detect -> store. Returns (active, markers). Never raises."""
    try:
        s = settings()
        result = detect(computed_records_7d, habit_7d, declining, gather(fetch_range, as_of, s), as_of, s)
        store(table, as_of, result, user_prefix)
        log = logger.warning if result["active"] else logger.info
        log(
            "IC-5 early warning %s: markers=%s unevaluated=%s",
            "ACTIVE" if result["active"] else "clear",
            result["markers"],
            result["unevaluated"],
        )
        return result["active"], result["markers"]
    except Exception as e:  # noqa: BLE001 — the insight run never dies on the detector
        logger.warning("IC-5 failed (non-fatal): %s", e)
        return False, []


# ── read side (the owner channels) ───────────────────────────────────────────────────────


def read_recent(table: Any, today: str, days: int = _RECENT_ROWS_DAYS, user_prefix: str = "USER#matthew#SOURCE#") -> list:
    """The flag rows of the last ``days`` days, oldest first ([] on any failure)."""
    end = _day(today)
    if end is None:
        return []
    try:
        from experiment.phase_filter import with_phase_filter  # noqa: PLC0415

        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
            "ExpressionAttributeValues": {
                ":pk": user_prefix + SOURCE,
                ":lo": f"DATE#{(end - timedelta(days=days - 1)).isoformat()}",
                ":hi": f"DATE#{today}~",
            },
        }
        rows = table.query(**with_phase_filter(kwargs)).get("Items") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("[early-warning] flag read failed: %s", type(e).__name__)
        return []
    return sorted((r for r in rows if _row_day(r)), key=_row_day)


def episode(rows: list) -> Optional[dict]:
    """The current episode when the newest row is active: ``{start, latest, row}``. A day with no row does not end
    an episode (a missed run is not a clear day); an explicit inactive row does."""
    ordered = sorted((r for r in rows or [] if _row_day(r)), key=_row_day)
    if not ordered or not ordered[-1].get("active"):
        return None
    start = _row_day(ordered[-1])
    for r in reversed(ordered[:-1]):
        if not r.get("active"):
            break
        start = _row_day(r)
    return {"start": start, "latest": _row_day(ordered[-1]), "row": ordered[-1]}


def evidence_lines(row: Mapping[str, Any]) -> list:
    ev = row.get("evidence") or {}
    return [str(ev.get(m) or m) for m in row.get("markers") or []]


def owner_lines(rows: list, today: str, fresh_days: int = 2) -> list:
    """The mind coach's thread lines: the active flag and its signals, a clear reading, or an honest absence."""
    ordered = sorted((r for r in rows or [] if _row_day(r)), key=_row_day)
    latest = ordered[-1] if ordered else None
    age = (_day(today) - _day(_row_day(latest))).days if latest and _day(today) else None
    if latest is None or age is None or age > fresh_days:
        return ["Early-warning flag (owner-only): no reading in the last few days — absent. Say so; never infer it."]
    ep = episode(ordered)
    if ep is None:
        n = len(latest.get("markers") or [])
        return [f"Early-warning flag (owner-only): clear as of {_row_day(latest)} ({n} lapse signal(s) active; two together raise it)."]
    lines = [f"Early-warning flag (owner-only): ACTIVE since {ep['start']} (latest reading {ep['latest']}) — you own the response."]
    lines += [f"- {line}" for line in evidence_lines(ep["row"])]
    return lines
