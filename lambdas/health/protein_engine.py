"""protein_engine.py — THE protein engine (#5098, epic #5091): the charter's protein range, four feedings, one hit.

PURE: no DynamoDB, no clock, no model. The caller hands in the MacroFactor day row it already read (readers are
injected); the only read here is the charter (`config/training_charter.json` `nutrition.protein`, bundled, cached).

ONE HIT DEFINITION. `hit(total_g)` is `health.protein_floor.met_floor(total_g, range low)` — strictly at or above the
charter's range low, no tolerance (#5003 keeps the tolerance an owner ruling). The scoring engine, the macros view, the
critics and the `protein_floor_missed` tripwire (`training.redline_rate.protein_days_missed`) all call it; the
published surfaces that count hit days call `met_floor` with the plan's floor, which a contract test holds equal to
the charter's range low (tests/test_protein_engine_5098.py).

FEEDINGS. MacroFactor food-log rows carry a local `HH:MM`. Rows within `feeding_merge_minutes` of a feeding's first
row are one feeding (the same grouping the ingest's protein-distribution score uses). A day whose rows carry no time
— or no row at all — has an UNKNOWN feeding count (None), never 0 (ADR-104).

THE BREAKFAST NUDGE (`nudge_decide`). Behind = no feeding at or above `feeding_threshold_g` logged at or before the
later of the charter cut-off and the tick. Owner-only, at most once a Pacific day (`PROTEIN_NUDGE#<date>`), sent by
`emails.protein_nudge_runner` on the coach-nudge hourly tick. The copy is information, never a command. NO ROW FOR
TODAY WITHHOLDS (`no_same_day_log`): the only protein source is an end-of-day upload, so an absent row at breakfast
is the upload's lag, not a missed feeding. SAME-DAY SOURCE (#5187): when the day's MacroFactor row is absent the
runner hands in the timed protein entries Health Auto Export delivers intraday (`hae_feeding_rows`); the verdict's
`source` names which read decided it. Only when neither exists does the note withhold.

THE EVENING NUDGE (`evening_decide`, #5793). The same module, ledger and budget silence tier, a distinct slot
(`PROTEIN_NUDGE#<date>#evening`, at most once a Pacific day), on the same hourly tick inside the charter's
`nutrition.protein.evening_nudge` window (a platform default: the steps nudge's evening window, pending an owner ruling).
It sends only when the protein logged so far is below the range low (THE `hit`), and states the grams remaining and
the feedings left in the eating window (`nutrition.eating_window`, opened by the day's first feeding). Fat and fibre ride
the same note as one line each when `health.macro_floors` grades them below their floors; an unknown macro gets no line.
No same-day row, or a row with no protein figure, withholds with the reason recorded (ADR-104): never a nudge on an
unknown.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from common.constants import PLAN_DAILY_PROTEIN_MIN_G
from common.macrofactor_fields import protein_meals_at
from common.pacific_time import PACIFIC, parse_iso_utc
from training import training_charter

from health import macro_floors
from health.protein_floor import met_floor

ENGINE_VERSION = "protein-engine@1.0.0"
NUDGE_VERSION = "protein-nudge@1.2.0"
KEY_PREFIX = "PROTEIN_NUDGE#"
EVENING_NUDGE_VERSION = "protein-evening-nudge@1.0.0"
EVENING_SLOT = "evening"
EVENING_MACROS = ("fat", "fibre")  # the issue's two companions; carbohydrate is not asked for
BUDGET_SILENCE_TIER = 2  # = steps_nudge.BUDGET_SILENCE_TIER: a deterministic owner note, silenced with the coach nudge
_P = "nutrition.protein."


def _cv(path: str, default: Any = None) -> Any:
    return training_charter.charter_value(_P + path, default)


def range_low() -> float:
    """The range's low end — THE floor a day is graded against, as the charter states it (170, not 170.0). Falls
    back to the plan constant only when the bundled charter is unreadable (the contract test holds the two equal)."""
    return _cv("range_g.low", PLAN_DAILY_PROTEIN_MIN_G)


def range_high() -> Optional[float]:
    return _cv("range_g.high")


def hit(total_g: Optional[float], floor: Optional[float] = None) -> Optional[bool]:
    """THE hit: True at or above the range low (strict), None for an unlogged day — never a miss."""
    return met_floor(total_g, range_low() if floor is None else floor)


def _minutes(hhmm: Any) -> Optional[int]:
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def feedings(food_log: Optional[list], merge_minutes: Optional[int] = None) -> Optional[list[dict[str, Any]]]:
    """The day's feedings `[{time, g}]` in time order, or None when no row carries a time and a protein figure."""
    merge = merge_minutes if merge_minutes is not None else _cv("feeding_merge_minutes")
    if merge is None:
        return None  # no charter grouping rule: the feeding count is unknown, never a guessed window
    merge = int(merge)
    timed = []
    for row in food_log or []:
        t, g = _minutes((row or {}).get("time")), (row or {}).get("protein_g")
        if t is not None and g is not None:
            timed.append((t, float(g)))
    if not timed:
        return None
    timed.sort()
    out: list[dict[str, Any]] = []
    start, total = timed[0]
    for t, g in timed[1:]:
        if t - start <= merge:
            total += g
        else:
            out.append({"time": _hhmm(start), "g": round(total, 1)})
            start, total = t, g
    out.append({"time": _hhmm(start), "g": round(total, 1)})
    return out


def hae_feeding_rows(entries: Optional[Mapping[str, Any]], date: str) -> Optional[dict[str, Any]]:
    """A food-log-shaped row `{food_log, row_source}` from the HAE `_rd_protein_hae` map for Pacific `date`, or None.

    Each entry carries its own instant (`t`, ISO with the device offset) and grams (`g`); the Pacific date of the
    instant decides membership, so the UTC-framed row can hold entries of the next Pacific day without leaking."""
    rows = []
    for e in (entries or {}).values():
        try:
            parsed, g = parse_iso_utc(e["t"]), float(e["g"])
        except (KeyError, TypeError, ValueError):
            continue
        if parsed is None:
            continue
        at = parsed.astimezone(PACIFIC)
        if at.date().isoformat() == date:
            rows.append({"time": at.strftime("%H:%M"), "protein_g": g})
    return {"food_log": sorted(rows, key=lambda r: r["time"]), "row_source": "hae_intraday"} if rows else None


def first_feeding_behind(fed: Optional[list], by: Optional[str] = None) -> Optional[bool]:
    """True when no feeding at or above the threshold is logged at or before `by` (default: the charter cut-off).
    None when the feedings are unknown or the charter names no threshold/cut-off."""
    threshold, by = _cv("feeding_threshold_g"), by or _cv("breakfast_nudge.cutoff_pt")
    limit = _minutes(by)
    if fed is None or threshold is None or limit is None:
        return None
    return not any(f["g"] >= float(threshold) and (_minutes(f["time"]) or 0) <= limit for f in fed)


def evaluate_day(row: Optional[Mapping[str, Any]], *, floor: Optional[float] = None) -> dict[str, Any]:
    """One day from its MacroFactor row (None = no row): the total, the range, THE hit and the feedings."""
    row = row or {}
    raw = row.get("total_protein_g")
    try:
        total = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        total = None  # a malformed rollup is unknown (the macros view's `measured()` rule), never a crash
    fed = feedings(row.get("food_log"))
    threshold = _cv("feeding_threshold_g")
    return {
        "date": row.get("date"),
        "total_g": round(total, 1) if total is not None else None,
        "range_low": range_low() if floor is None else floor,
        "range_high": range_high(),
        "hit": hit(total, floor),
        "feedings": fed,
        "feedings_40g": (sum(1 for f in fed if f["g"] >= float(threshold)) if fed is not None and threshold is not None else None),
        "feedings_target": _cv("feedings_per_day"),
        "first_feeding_behind": first_feeding_behind(fed),
        "charter_version": training_charter.charter_version(),
        "version": ENGINE_VERSION,
    }


def feedings_at_threshold(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """Feedings at the charter threshold: the engine's count from the food log; else a legacy ``meals`` list at the
    same threshold; None (unknown, never 0) when neither applies or the charter names no threshold (#5214)."""
    threshold = _cv("feeding_threshold_g")
    if threshold is None:
        return None
    counted = evaluate_day(row)["feedings_40g"]
    return float(counted) if counted is not None else protein_meals_at(dict(row or {}), float(threshold))


def idempotency_key(date: str) -> str:
    return f"{KEY_PREFIX}{date}"


def in_window(now_pt: datetime) -> bool:
    start, end = _minutes(_cv("breakfast_nudge.cutoff_pt")), _minutes(_cv("breakfast_nudge.window_end_pt"))
    now = now_pt.hour * 60 + now_pt.minute
    return start is not None and end is not None and start <= now < end


def copy(verdict: Mapping[str, Any]) -> str:
    return (
        f"No feeding of {verdict['threshold_g']} g or more is logged by {verdict['by']}. The plan's protein is {verdict['feedings_target']} feedings of {verdict['threshold_g']} g or more; "
        "a protein-first breakfast now keeps the other three in reach. Fine to skip; this is just where the morning stands."
    )


def nudge_decide(*, date: str, now_pt: datetime, row: Optional[Mapping[str, Any]], already_sent: bool, budget_tier: int) -> dict[str, Any]:
    """One verdict for the breakfast nudge: `send` plus the reason, with every number that decided it."""
    out: dict[str, Any] = {
        "date": date,
        "send": False,
        "reason": None,
        "key": idempotency_key(date),
        "version": NUDGE_VERSION,
        "charter_version": training_charter.charter_version(),
    }
    if budget_tier >= BUDGET_SILENCE_TIER:
        return {**out, "reason": f"budget_tier_{budget_tier}"}
    if not in_window(now_pt):
        return {**out, "reason": "outside_window"}
    if already_sent:
        return {**out, "reason": "already_sent"}
    cutoff = _cv("breakfast_nudge.cutoff_pt")
    by = max(cutoff, now_pt.strftime("%H:%M"), key=lambda s: _minutes(s) or 0)
    out.update(threshold_g=_cv("feeding_threshold_g"), feedings_target=_cv("feedings_per_day"), cutoff=cutoff, by=by)
    if out["threshold_g"] is None or out["feedings_target"] is None:
        return {**out, "reason": "no_charter_rule"}
    if not row:
        return {**out, "reason": "no_same_day_log"}  # the upload's lag, not a miss: withhold (the EVAL stamp still lands)
    fed = feedings(row.get("food_log"))
    out["feedings"] = fed
    out["source"] = row.get("row_source", "macrofactor_day_row")
    behind = first_feeding_behind(fed, by)
    if behind is None:
        return {**out, "reason": "feedings_unknown"}
    if not behind:
        return {**out, "reason": "on_track"}
    out["send"], out["reason"] = True, "behind_logged_below"
    out["text"] = copy(out)
    return out


# ── the evening nudge (#5793) ───────────────────────────────────────────────────────────────────────────────────
def evening_key(date: str) -> str:
    """The evening slot on the SAME ledger: distinct from the breakfast claim, still one per Pacific day."""
    return f"{KEY_PREFIX}{date}#{EVENING_SLOT}"


def in_evening_window(now_pt: datetime) -> bool:
    start, end = _minutes(_cv("evening_nudge.at_pt")), _minutes(_cv("evening_nudge.window_end_pt"))
    now = now_pt.hour * 60 + now_pt.minute
    return start is not None and end is not None and start <= now < end


def logged_total_g(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """The protein logged so far: the day row's rollup when it carries one, else the sum of its timed food-log rows
    (the HAE intraday shape). None when neither carries a figure: unknown, never 0."""
    if not row:
        return None
    total = evaluate_day(row)["total_g"]
    if total is not None:
        return total
    grams = []
    for r in row.get("food_log") or []:
        try:
            grams.append(float((r or {}).get("protein_g")))
        except (TypeError, ValueError):
            continue
    return round(sum(grams), 1) if grams else None


def eating_window(fed: Optional[list], now_pt: datetime) -> Optional[dict[str, Any]]:
    """The day's eating window `{opened, closes, open}`: it opens at the first feeding and runs the charter's
    `nutrition.eating_window.eating_hours`. None when the feedings or the charter's hours are unknown."""
    hours = training_charter.charter_value("nutrition.eating_window.eating_hours")
    if not fed or hours is None:
        return None
    opened = _minutes(fed[0]["time"])
    if opened is None:
        return None
    closes = opened + int(round(float(hours) * 60))
    return {"opened": fed[0]["time"], "closes": _hhmm(closes % (24 * 60)), "open": now_pt.hour * 60 + now_pt.minute < closes}


def _g(v: Any) -> str:
    return f"{float(v):g}"


def evening_copy(verdict: Mapping[str, Any]) -> str:
    """Information, never a command (the breakfast copy's rule)."""
    parts = [
        f"{_g(verdict['total_g'])} g of protein is logged so far today, {_g(verdict['remaining_g'])} g short of the {_g(verdict['range_low'])} g range low."
    ]
    win, left = verdict.get("window"), verdict.get("feedings_left")
    if win is not None and left is not None:
        logged = f"{verdict['feedings_counted']} of the plan's {verdict['feedings_target']} feedings of {verdict['threshold_g']} g or more are logged"
        if win["open"]:
            parts.append(
                f"{logged}; the eating window that opened at {win['opened']} runs to {win['closes']}, with {left} of them left in it."
            )
        else:
            parts.append(f"{logged}; the eating window that opened at {win['opened']} closed at {win['closes']}.")
    for line in verdict.get("macro_lines") or []:
        parts.append(line[:1].upper() + line[1:] + ".")
    parts.append("Fine to leave as it is; this is just where the day stands.")
    return " ".join(parts)


def evening_decide(
    *, date: str, now_pt: datetime, row: Optional[Mapping[str, Any]], already_sent: bool, budget_tier: int
) -> dict[str, Any]:
    """One verdict for the evening nudge: `send` plus the reason, with every number that decided it."""
    out: dict[str, Any] = {
        "date": date,
        "slot": EVENING_SLOT,
        "send": False,
        "reason": None,
        "key": evening_key(date),
        "version": EVENING_NUDGE_VERSION,
        "charter_version": training_charter.charter_version(),
    }
    if budget_tier >= BUDGET_SILENCE_TIER:
        return {**out, "reason": f"budget_tier_{budget_tier}"}
    if not in_evening_window(now_pt):
        return {**out, "reason": "outside_window"}
    if already_sent:
        return {**out, "reason": "already_sent"}
    out["by"] = now_pt.strftime("%H:%M")
    if not row:
        return {**out, "reason": "no_same_day_log"}  # nothing logged anywhere today: never a nudge on an unknown
    out["source"] = row.get("row_source", "macrofactor_day_row")
    total = logged_total_g(row)
    if total is None:
        return {**out, "reason": "intake_unknown"}
    low = range_low()
    out.update(total_g=total, range_low=low)
    if hit(total, low):
        return {**out, "reason": "floor_met"}
    out["remaining_g"] = round(float(low) - total, 1)
    fed, threshold, target = feedings(row.get("food_log")), _cv("feeding_threshold_g"), _cv("feedings_per_day")
    out.update(threshold_g=threshold, feedings_target=target, feedings=fed)
    if fed is not None and threshold is not None and target is not None:
        counted = sum(1 for f in fed if f["g"] >= float(threshold))
        win = eating_window(fed, now_pt)
        out["feedings_counted"], out["window"] = counted, win
        if win is not None:
            out["feedings_left"] = max(0, int(target) - counted) if win["open"] else 0
    graded = macro_floors.evaluate_day(row)
    out["macro_floors"] = {m: graded[m] for m in EVENING_MACROS}
    out["macro_lines"] = [t for t in (macro_floors.miss_text(m, graded[m]) for m in EVENING_MACROS) if t]
    out["send"], out["reason"] = True, "below_range_low"
    out["text"] = evening_copy(out)
    return out
