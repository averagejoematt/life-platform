"""health/illness_triad.py — the early-illness / overload triad (#4978, epic #4967).

THE DEFECT. Readiness was rebuilt without Body Battery (#4976/#5023), but nothing watched the pattern that most
often comes before he feels unwell: the overnight resting heart rate, skin temperature and respiratory rate all
rising above his own baseline on the same night. The anomaly detector flagged single metrics on a z-score; it had
no rule for the three together, and its `anomalies` row feeds the chronicle and the daily brief, so it is the
wrong home for an owner-only body signal anyway.

THE CONTRACT.
  * Three legs, each the night's value against the mean of HIS OWN preceding nights from the SAME source:
    ``rhr_up`` (resting heart rate, read through the ``rhr_bpm`` METRIC_TRUTH facet), ``temp_up`` (Whoop skin
    temperature) and ``resp_up`` (Whoop respiratory rate). Thresholds are the charter's ``illness_triad`` block
    (``config/training_charter.json``); a threshold the charter does not carry leaves its leg UNEVALUATED, never a
    literal fallback. ``min_legs`` legs up together raise ONE flag; one alone never does.
  * The HR regime is respected (``health.hr_regime``, #4999): resting heart rate is HR-derived, so inside a
    marker's re-baselining window the RHR leg reports ``re-baselining`` and is not evaluated, and after it the
    RHR baseline is cut at the marker and drops the excluded (rhythm) days — a night is never compared with a
    baseline from another HR regime. Skin temperature and respiratory rate are not HR-derived components there.
  * The Apple Watch's twins (wrist temperature, respiratory rate) are computed the same way against the watch's
    own baseline and REPORTED beside the Whoop leg, never counted and never averaged with it: whether the watch
    becomes a backup or joins a mean is the owner's ruling after the agreement study (#4974/#4975).
  * Rigor (ADR-105): a HEURISTIC flag, not a diagnosis. The cut-offs are platform defaults pending an owner
    ruling; the literature gives the direction (a rise in all three precedes symptoms of infection), not these
    numbers. The same pattern also follows hard training, alcohol, heat or a late meal, so it is named
    "illness or overload" and the reader is told to weigh it against the training load.
  * Owner-only (``privacy.field_tiers``: ``illness_triad_flag`` TIER_OWNER_ONLY). The row is
    ``USER#matthew#SOURCE#illness_triad_flag`` / ``DATE#<night>``, written by the anomaly detector each morning
    and never added to its ``anomalies`` row or its mail. Its one reader is the Performance coach's own Telegram
    thread (``coach.coach_domain_facts``) — ``tests/test_illness_triad_4978.py`` holds the reader set.

Shape: a pure core (``evaluate`` — no I/O, no clock) and a thin I/O half (``gather`` over an injected range reader,
``store``, ``run``, ``read_recent``). Fail-soft everywhere: an unreadable family is absent, never zero.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from common.digest_utils import filter_day_rows  # #3442: the day-row predicate

from health import hr_regime

logger = logging.getLogger(__name__)

SOURCE = "illness_triad_flag"
VERSION = "illness-triad@1.0.0"
CHARTER_PATH = "illness_triad"
TIER = "owner_only"
RIGOR = "heuristic flag — not a diagnosis; platform-default cut-offs pending an owner ruling (ADR-105)"
RHR_METRIC = "rhr_bpm"  # the METRIC_TRUTH facet (ingestion.source_registry) — the RHR leg follows its ruling

LEGS = ("rhr_up", "temp_up", "resp_up")
# leg -> (field on the primary rows, label, unit, HR-derived?). The RHR leg reads the resolved rows.
_PRIMARY = {
    "rhr_up": (RHR_METRIC, "resting heart rate", "bpm", True),
    "temp_up": ("skin_temp_celsius", "skin temperature", "°C", False),
    "resp_up": ("respiratory_rate", "respiratory rate", "breaths/min", False),
}
# The Apple Watch twin of each leg: reported against the watch's own baseline, never counted (#4974/#4975).
_WATCH = {"temp_up": "wrist_temp_sleep_c_apple", "resp_up": "respiratory_rate_apple", "rhr_up": "resting_heart_rate_apple"}

STATE_UP, STATE_NORMAL, STATE_UNEVALUATED = "up", "normal", "unevaluated"
_RECENT_ROWS_DAYS = 14


# ── small pure helpers ───────────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(v: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _row_day(row: Mapping[str, Any]) -> Optional[str]:
    """The DATE# day of a day row; a sub-row (``DATE#d#WORKOUT#id``) is not a day row."""
    sk = str(row.get("sk", ""))
    if sk.startswith("DATE#") and len(sk) > 15:
        return None
    d = row.get("date") or sk[len("DATE#") :][:10]
    return str(d)[:10] if _day(d) else None


def _fmt(x: float) -> str:
    return f"{x:+.1f}" if abs(x) >= 1 else f"{x:+.2f}"


# ── thresholds: the charter block, read — never a fallback literal ───────────────────────


def _default_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def settings(charter_reader: Optional[Callable[[str], Any]] = None) -> dict:
    """``{min_legs, baseline_days, min_baseline_n, fresh_days, legs{id: {min_rise}}, charter_version}``.
    A missing block gives ``min_legs`` None (the flag cannot be raised); a missing leg is an empty dict."""
    read = charter_reader or _default_reader
    try:
        block, version = read(CHARTER_PATH), read("version")
    except Exception as e:  # noqa: BLE001
        logger.warning("[illness-triad] charter unreadable: %s", type(e).__name__)
        block, version = None, None
    block = block if isinstance(block, dict) else {}
    raw_legs: dict = block["legs"] if isinstance(block.get("legs"), dict) else {}
    ints = {k: _num(block.get(k)) for k in ("min_legs", "baseline_days", "min_baseline_n", "fresh_days")}
    return {
        **{k: (int(v) if v is not None else None) for k, v in ints.items()},
        "legs": {k: (raw_legs.get(k) if isinstance(raw_legs.get(k), dict) else {}) for k in LEGS},
        "charter_version": version if isinstance(version, str) else None,
    }


# ── the pure core ────────────────────────────────────────────────────────────────────────


def _by_day(rows: Any, field: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows or ():
        d, v = _row_day(r), _num(r.get(field))
        if d and v is not None:
            out[d] = v
    return out


def _deviation(series: Mapping[str, float], night: str, field: str, s: Mapping[str, Any], hr: bool, excluded: set) -> dict:
    """The night's value against the mean of the ``baseline_days`` nights before it (never including it).
    An HR-derived series goes through ``hr_regime.baseline_values`` (cut at a marker, excluded days out)."""
    value = series.get(night)
    if value is None:
        return {"status": "no reading"}
    if hr and night in excluded:
        return {"status": "night excluded from heart-rate baselines"}
    nd = _day(night)
    if nd is None:
        return {"status": "no reading"}
    start = (nd - timedelta(days=int(s["baseline_days"]))).isoformat()
    end = (nd - timedelta(days=1)).isoformat()
    rows = [{"date": d, field: v} for d, v in series.items()]
    if hr:
        base, basis = hr_regime.baseline_values(rows, field, start, end, excluded)
    else:
        base = [v for d, v in series.items() if start <= d <= end]
        basis = {"since": start, "through": end, "n": len(base)}
    if len(base) < int(s["min_baseline_n"]):
        return {"status": f"baseline too thin (n={len(base)} < {s['min_baseline_n']})", "basis": basis}
    mean = sum(base) / len(base)
    return {"status": "scored", "value": value, "baseline": mean, "deviation": value - mean, "basis": basis}


def _leg(leg: str, inputs: Mapping[str, Any], night: str, s: Mapping[str, Any]) -> dict:
    field, label, unit, hr = _PRIMARY[leg]
    rise = _num((s.get("legs") or {}).get(leg, {}).get("min_rise"))
    out: dict[str, Any] = {"label": label, "unit": unit, "source": "whoop" if leg != "rhr_up" else f"metric_truth:{RHR_METRIC}"}
    if hr and hr_regime.is_rebaselining(night):
        return {**out, "state": hr_regime.REBASELINING, "line": f"{label}: re-baselining after an HR regime marker — not evaluated."}
    if rise is None or not s.get("baseline_days") or not s.get("min_baseline_n"):
        return {**out, "state": STATE_UNEVALUATED, "line": f"{label}: no charter threshold — not evaluated."}
    if hr and inputs.get("excluded_unreadable"):
        return {**out, "state": STATE_UNEVALUATED, "line": f"{label}: the excluded-day list was unreadable — not evaluated."}
    dev = _deviation(inputs.get(leg) or {}, night, field, s, hr, set(inputs.get("excluded") or ()))
    out["basis"] = dev.get("basis")
    if dev["status"] != "scored":
        return {**out, "state": STATE_UNEVALUATED, "line": f"{label}: {dev['status']} — not evaluated."}
    up = dev["deviation"] >= rise
    out.update({"value": dev["value"], "baseline": dev["baseline"], "deviation": dev["deviation"], "min_rise": rise})
    out["state"] = STATE_UP if up else STATE_NORMAL
    out["line"] = (
        f"{label} {_fmt(dev['deviation'])} {unit} against his {dev['basis']['n']}-night baseline "
        f"({out['source']}; the line is +{rise:g} {unit}) — {'UP' if up else 'within range'}."
    )
    return out


def _watch(leg: str, inputs: Mapping[str, Any], night: str, s: Mapping[str, Any]) -> Optional[str]:
    """The Apple Watch twin, against the watch's own baseline: a reported line, never a counted leg."""
    if not s.get("baseline_days") or not s.get("min_baseline_n"):
        return None
    hr = _PRIMARY[leg][3]
    if hr and (hr_regime.is_rebaselining(night) or inputs.get("excluded_unreadable")):
        return None
    dev = _deviation(inputs.get("watch_" + leg) or {}, night, "v", s, hr, set(inputs.get("excluded") or ()))
    if dev["status"] != "scored":
        return None
    return (
        f"Apple Watch {_PRIMARY[leg][1]} {_fmt(dev['deviation'])} {_PRIMARY[leg][2]} against the watch's own "
        f"{dev['basis']['n']}-night baseline (reported, not counted — #4975 pending)."
    )


def evaluate(inputs: Mapping[str, Any], night: Optional[str], s: Optional[Mapping[str, Any]] = None) -> dict:
    """Every leg, the ``min_legs`` rule and the evidence. ``inputs`` is ``gather``'s output: per-leg
    ``{day: value}`` series (``rhr_up``/``temp_up``/``resp_up`` and their ``watch_*`` twins) and ``excluded``."""
    s = settings() if s is None else s
    if not night or _day(night) is None:
        return {"active": False, "night": None, "legs": {}, "up": [], "evidence": {}, "min_legs": s.get("min_legs"), "rigor": RIGOR}
    legs = {leg: _leg(leg, inputs, night, s) for leg in LEGS}
    up = [leg for leg in LEGS if legs[leg]["state"] == STATE_UP]
    min_legs = s.get("min_legs")
    corroboration = {leg: line for leg in LEGS if (line := _watch(leg, inputs, night, s))}
    return {
        "active": bool(min_legs) and len(up) >= int(min_legs or 0),
        "night": night,
        "legs": legs,
        "up": up,
        "evidence": {leg: legs[leg]["line"] for leg in LEGS},
        "corroboration": corroboration,
        "min_legs": min_legs,
        "rigor": RIGOR,
        "charter_version": s.get("charter_version"),
    }


# ── I/O half ─────────────────────────────────────────────────────────────────────────────


def pick_night(whoop_rows: Any, as_of: str, fresh_days: Optional[int]) -> Optional[str]:
    """The newest Whoop night dated on/before ``as_of`` and within ``fresh_days`` of it carrying any triad field."""
    end = _day(as_of)
    if end is None or fresh_days is None:
        return None
    lo = (end - timedelta(days=int(fresh_days))).isoformat()
    fields = [f for leg, (f, *_rest) in _PRIMARY.items() if leg != "rhr_up"] + ["resting_heart_rate"]
    days = sorted(
        d for r in whoop_rows or () if (d := _row_day(r)) and lo <= d <= as_of and any(_num(r.get(f)) is not None for f in fields)
    )
    return days[-1] if days else None


def gather(fetch_range: Callable[[str, str, str], list], as_of: str, s: Mapping[str, Any]) -> tuple[Optional[str], dict]:
    """(night, inputs) through the caller's per-source range reader. A family that fails is left out (its leg is
    then unevaluated, never zero)."""
    end = _day(as_of)
    if end is None or not s.get("baseline_days"):
        return None, {}
    start = (end - timedelta(days=int(s["baseline_days"]) + int(s.get("fresh_days") or 0))).isoformat()
    inputs: dict[str, Any] = {}
    whoop: list = []
    try:
        whoop = filter_day_rows(fetch_range("whoop", start, as_of))  # #3442: workout sub-rows are not nights
        inputs["temp_up"] = _by_day(whoop, _PRIMARY["temp_up"][0])
        inputs["resp_up"] = _by_day(whoop, _PRIMARY["resp_up"][0])
    except Exception as e:  # noqa: BLE001
        logger.warning("[illness-triad] whoop read failed: %s", type(e).__name__)
    night = pick_night(whoop, as_of, s.get("fresh_days"))
    for name, fn in (("rhr", lambda: _rhr(fetch_range, whoop, start, as_of)), ("watch", lambda: _watch_series(fetch_range, start, as_of))):
        try:
            inputs.update(fn())
        except Exception as e:  # noqa: BLE001
            logger.warning("[illness-triad] %s read failed: %s", name, type(e).__name__)
    try:
        inputs["excluded"] = hr_regime.af_days_from(fetch_range, _day(night or as_of), as_of)
    except Exception as e:  # noqa: BLE001 — no exclusion list: the RHR leg cannot be trusted, so it is not scored
        logger.warning("[illness-triad] excluded-day read failed: %s", type(e).__name__)
        inputs["excluded_unreadable"] = True
    return night, inputs


def _rhr(fetch_range: Callable, whoop: list, start: str, end: str) -> dict:
    """The RHR series through the ``rhr_bpm`` METRIC_TRUTH facet (whoop rows reused, any other source fetched)."""
    from common import metric_truth  # noqa: PLC0415

    rows = {src: (whoop if src == "whoop" else fetch_range(src, start, end)) for src in metric_truth.sources_for(RHR_METRIC)}
    return {"rhr_up": _by_day(metric_truth.resolved_rows(RHR_METRIC, rows), RHR_METRIC)}


def _watch_series(fetch_range: Callable, start: str, end: str) -> dict:
    rows = fetch_range("apple_health", start, end)
    return {"watch_" + leg: _by_day(rows, field) for leg, field in _WATCH.items()}


def _dec(x: Any) -> Decimal:
    return Decimal(str(round(float(x), 3)))


def item(result: Mapping[str, Any], user_prefix: str = "USER#matthew#SOURCE#") -> dict:
    """The owner-only row for the evaluated night: strings, bools, ints and Decimals only (DynamoDB rejects float)."""
    night = str(result["night"])
    legs = {}
    for leg, v in (result.get("legs") or {}).items():
        entry: dict[str, Any] = {"state": str(v.get("state")), "source": str(v.get("source"))}
        for k in ("value", "baseline", "deviation", "min_rise"):
            if v.get(k) is not None:
                entry[k] = _dec(v[k])
        if (v.get("basis") or {}).get("n") is not None:
            entry["baseline_n"] = int(v["basis"]["n"])
        legs[leg] = entry
    row = {
        "pk": user_prefix + SOURCE,
        "sk": "DATE#" + night,
        "date": night,
        "active": bool(result.get("active")),
        "up": [str(x) for x in result.get("up") or []],
        "legs": legs,
        "evidence": {k: str(v) for k, v in (result.get("evidence") or {}).items()},
        "corroboration": {k: str(v) for k, v in (result.get("corroboration") or {}).items()},
        "rigor": RIGOR,
        "tier": TIER,
        "version": VERSION,
    }
    if result.get("min_legs"):
        row["min_legs"] = int(result["min_legs"])
    if result.get("charter_version"):
        row["charter_version"] = str(result["charter_version"])
    return row


def store(table: Any, result: Mapping[str, Any], user_prefix: str = "USER#matthew#SOURCE#") -> bool:
    """Write the night's row (overwritten on a re-run). Fail-soft: False on any trouble or with no night."""
    if not result.get("night"):
        return False
    try:
        row = item(result, user_prefix)
        try:
            from common.compute_metadata import tag_record  # noqa: PLC0415

            row = tag_record(row, source_id=SOURCE)
        except ImportError:
            pass
        table.put_item(Item=row)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[illness-triad] store failed for %s: %s", result.get("night"), type(e).__name__)
        return False


def run(table: Any, fetch_range: Callable, as_of: str, dry_run: bool = False) -> dict:
    """The anomaly detector's entry: settings -> gather -> evaluate -> store. Returns ``{active, night, up}``;
    never raises. A dry run evaluates and logs but writes nothing."""
    try:
        s = settings()
        night, inputs = gather(fetch_range, as_of, s)
        result = evaluate(inputs, night, s)
        stored = False if dry_run else store(table, result)
        (logger.warning if result["active"] else logger.info)(
            "illness triad %s: night=%s up=%s states=%s stored=%s",
            "ACTIVE" if result["active"] else "clear",
            result["night"],
            result["up"],
            {k: v.get("state") for k, v in result["legs"].items()},
            stored,
        )
        return {"active": result["active"], "night": result["night"], "up": result["up"]}
    except Exception as e:  # noqa: BLE001 — the anomaly run never dies on the triad
        logger.warning("illness triad failed (non-fatal): %s", e)
        return {"active": False, "night": None, "up": []}


# ── read side (the owner's Performance thread) ───────────────────────────────────────────


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
        logger.warning("[illness-triad] flag read failed: %s", type(e).__name__)
        return []
    return sorted((r for r in rows if _row_day(r)), key=lambda r: str(_row_day(r)))


def owner_lines(rows: list, today: str, fresh_days: int = 2) -> list:
    """The Performance coach's thread lines: the active flag and its legs, a clear reading, or an honest absence."""
    ordered = sorted((r for r in rows or [] if _row_day(r)), key=lambda r: str(_row_day(r)))
    latest = ordered[-1] if ordered else None
    t, d = _day(today), _day(_row_day(latest)) if latest else None
    if latest is None or t is None or d is None or (t - d).days > fresh_days:
        return ["Illness/overload triad (owner-only): no reading in the last few days — absent. Say so; never infer it."]
    night, ev = _row_day(latest), latest.get("evidence") or {}
    n_min = latest.get("min_legs")
    if not latest.get("active"):
        return [
            f"Illness/overload triad (owner-only): clear for the night of {night} ({len(latest.get('up') or [])} leg(s) up; {n_min} together raise it)."
        ]
    lines = [
        f"Illness/overload triad (owner-only): RAISED for the night of {night} — resting heart rate, skin temperature and "
        f"respiratory rate: {len(latest.get('up') or [])} of 3 up against his own baseline. A heuristic flag, not a diagnosis: "
        "the same pattern follows hard training, alcohol, heat or a late meal, so weigh it against the training load and ask "
        "how he feels before changing the session."
    ]
    lines += [f"- {ev[leg]}" for leg in LEGS if ev.get(leg)]
    lines += [f"- {v}" for v in (latest.get("corroboration") or {}).values()]
    return lines
