"""health/checkin_intake_pairs.py — does stress move what he eats? (#5106, epic #5093)

The evening check-in (``coach.evening_checkin``: hunger, stress, cravings 0-4 and one word) joined with
the same day's intake, and tested weekly by the correlation engine with its ADR-105 rigor.

WHY THE JOIN IS READ-SIDE (computed inside the weekly run, not a row written each night). The check-in
lands at about 20:00 PT, before the day's food log is finished — MacroFactor keeps logging to bedtime and
arrives by an end-of-day upload — and the day's calorie target can still move with the week's titration
record. A pair row written at check-in time would freeze an unfinished day, and fixing that would need a
second scheduled writer. The weekly run reads the settled days instead, writes every joined pair it used
into its record (``pairs``), and that record is the daily pair table for the window: the pairs ARE written,
once a week, over final data.

ONE JOINED DAY (``join_day``):
  * ``kcal_over_target`` — logged kcal minus THE calorie target for that day (``health.calorie_target.resolve``,
    titration > charter). A day under the titration rule's complete-log line (``titration.settings()``'s
    ``complete_log_kcal``, a redline) is an unfinished log: its intake fields are None, never a low day.
  * ``protein_hit`` — THE protein hit (``health.protein_engine.hit``) as 1/0, None when unlogged.
  * ``last_meal_min`` — minutes after midnight of the last timed food-log row (late eating), None untimed.
  * ``mood_valence`` — the State-of-Mind daily valence when he logged one (``apple_health.som_avg_valence``).

THE TEST (``PAIRS``) runs through the weekly engine's OWN ``compute_correlations`` (injected): Pearson r,
the Pyper-Peterman effective n, the moving-block bootstrap CI, p on n_eff, Benjamini-Hochberg across THIS
family, the n-gated interpretation. ``verdict`` adds the plain words: below the engine's minimum n, or with
no variation yet, it is "too early to say" — never an early verdict (ADR-105). Correlational, never causal.

THE NEXT-MORNING DAY ROW (#5211, the "pairs are written daily" box of #5106). The paragraph above is why no row is
written at check-in time; the settled day IS written the next morning, by ``write_day``, which the nightly
``scenario-explorer`` run (12:10Z, after 04:00 PT) calls over the previous Pacific day: ``DATE#<day>`` beside the
weekly ``WEEK#`` record, one row per day, idempotent overwrite (the same sk every run). It is the SAME join, not a
second one: ``write_day`` calls ``join_day`` and ``build_series`` calls it too, and ``tests/test_checkin_intake_day_5211.py``
proves a stored day row equals the weekly series row for the same inputs. A day with NO check-in still gets a row
(``has_checkin`` false, the check-in fields None, the settled intake beside it) — an explicit absent marker rather than
no row, because the row's existence is what the ``checkin_pair:day_row_liveness`` dead-man in ``nudge_ledger_qa`` reads: a
completed day with no row means the writer stopped, which a missing check-in must never be confused with. The weekly run
keeps joining the window itself (it must, to cover days older than the writer and to re-settle a late food upload).

PRIVACY. Owner-only, stored apart from the public ``weekly_correlations`` record (which the site serves):
``USER#matthew#SOURCE#checkin_intake_pairs`` / ``WEEK#<iso-week>``. No web or email module imports this. The ONE
owner-ruled projection of the ``DATE#`` rows a third party may see is ``health.checkin_partner_view`` (#5125 R5: the
partner letter — check-in keys only, never the intake columns).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

ENGINE_VERSION = "checkin-intake-pairs@1.0.0"
SOURCE = "checkin_intake_pairs"
PK = f"USER#matthew#SOURCE#{SOURCE}"
SK_PREFIX = "WEEK#"
DAY_SK_PREFIX = "DATE#"

# (x, y, label, lag_days) — the weekly engine's own pair shape. Same-day unless lagged.
PAIRS = [
    ("stress", "kcal_over_target", "stress_vs_kcal_over_target", 0),
    ("hunger", "kcal_over_target", "hunger_vs_kcal_over_target", 0),
    ("cravings", "kcal_over_target", "cravings_vs_kcal_over_target", 0),
    ("stress", "protein_hit", "stress_vs_protein_hit", 0),
    ("stress", "last_meal_min", "stress_vs_last_meal_time", 0),
    ("stress", "kcal_over_target", "stress_predicts_next_day_kcal_over_target", 1),
    ("mood_valence", "kcal_over_target", "mood_vs_kcal_over_target", 0),
]
CHECKIN_FIELDS = ("hunger", "stress", "cravings")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is an absence


def _minutes(hhmm: Any) -> Optional[int]:
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def join_day(
    checkin: Optional[Mapping[str, Any]],
    food: Optional[Mapping[str, Any]],
    apple: Optional[Mapping[str, Any]],
    target_kcal: Optional[float],
    complete_log_kcal: Optional[float],
    protein_hit: Callable[[Optional[float]], Optional[bool]],
) -> dict[str, Any]:
    """One day's pair row. Every absent input is None (ADR-104) — an unlogged day is never a zero."""
    ci, food, apple = checkin or {}, food or {}, apple or {}
    row: dict[str, Any] = {f: _num(ci.get(f)) for f in CHECKIN_FIELDS}
    row["mood_valence"] = _num(apple.get("som_avg_valence"))
    kcal = _num(food.get("total_calories_kcal"))
    complete = kcal is not None and (complete_log_kcal is None or kcal >= complete_log_kcal)
    row["kcal"] = kcal if complete else None
    row["target_kcal"] = target_kcal
    row["kcal_over_target"] = round(kcal - target_kcal, 1) if complete and kcal is not None and target_kcal is not None else None
    hit = protein_hit(_num(food.get("total_protein_g"))) if complete else None
    row["protein_hit"] = None if hit is None else (1.0 if hit else 0.0)
    times = [t for t in (_minutes((r or {}).get("time")) for r in food.get("food_log") or []) if t is not None]
    row["last_meal_min"] = float(max(times)) if complete and times else None
    return row


def _by_date(records: list) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for r in records or []:
        sk = str(r.get("sk") or "")
        if r.get("tombstone") or (sk and sk.count("#") > 1):  # a sub-record (DATE#<d>#...) is not the day row
            continue
        d = str(r.get("date") or sk.replace("DATE#", ""))[:10]
        if d:
            out[d] = r
    return out


def build_series(
    checkins: list, foods: list, apples: list, target_for: Callable[[str], Optional[float]], complete_log_kcal, protein_hit
) -> dict[str, dict[str, Any]]:
    """{date: joined row} over every day with a check-in or a mood reading."""
    ci, fo, ap = _by_date(checkins), _by_date(foods), _by_date(apples)
    days = sorted(set(ci) | {d for d, r in ap.items() if _num(r.get("som_avg_valence")) is not None})
    return {d: join_day(ci.get(d), fo.get(d), ap.get(d), target_for(d), complete_log_kcal, protein_hit) for d in days}


def day_item(
    day: str,
    checkin: Optional[Mapping[str, Any]],
    food: Optional[Mapping[str, Any]],
    apple: Optional[Mapping[str, Any]],
    target_kcal: Optional[float],
    complete_log_kcal: Optional[float],
    protein_hit: Callable[[Optional[float]], Optional[bool]],
    computed_at: str,
) -> dict[str, Any]:
    """The stored ``DATE#<day>`` row: ``join_day``'s row plus the marker that says whether a check-in existed."""
    row = join_day(checkin, food, apple, target_kcal, complete_log_kcal, protein_hit)
    has_checkin = any(row.get(f) is not None for f in CHECKIN_FIELDS)
    return {
        "pk": PK,
        "sk": DAY_SK_PREFIX + day,
        "date": day,
        **row,
        "has_checkin": has_checkin,
        "state": "checkin" if has_checkin else "no_checkin",
        "complete_log_kcal": complete_log_kcal,
        "engine_version": ENGINE_VERSION,
        "computed_at": computed_at,
        "tier": "owner_only",
    }


def write_day(
    day: str,
    *,
    fetch: Callable[[str, str, str], list],
    put_item: Callable[..., Any],
    computed_at: str,
    target_for: Optional[Callable[[str], Optional[float]]] = None,
) -> dict[str, Any]:
    """Join the settled ``day`` (a Pacific date) and overwrite its one owner-only row. Returns the item (floats)."""
    from common.numeric import floats_to_decimal

    from health import protein_engine, titration

    if target_for is None:
        from health.calorie_target import target_kcal

        target_for = target_kcal  # THE target, titration > charter
    ci = _by_date(fetch("evening_checkin", day, day)).get(day)  # the same three reads as run_week, one per source
    fo = _by_date(fetch("macrofactor", day, day)).get(day)
    ap = _by_date(fetch("apple_health", day, day)).get(day)
    item = day_item(day, ci, fo, ap, target_for(day), titration.settings().get("complete_log_kcal"), protein_engine.hit, computed_at)
    put_item(Item=floats_to_decimal(dict(item)))
    return item


def verdict(result: Mapping[str, Any], min_n: int) -> str:
    """Plain words for one tested pair (ADR-105): n, the effect, the confidence — or 'too early to say'."""
    n, r = int(result.get("n_days") or 0), result.get("pearson_r")
    if n < min_n:
        return f"too early to say: {n} paired day(s), {min_n} needed"
    if r is None:
        return f"too early to say: {n} paired days but no variation in one side yet"
    lo, hi = result.get("ci95_low"), result.get("ci95_high")
    ci = f", 95% CI {lo:+.2f} to {hi:+.2f}" if lo is not None and hi is not None else ""
    stats = f"r {r:+.2f}, n {n}, effective n {result.get('n_eff')}{ci}"
    label = str(result.get("interpretation") or "")
    if not result.get("fdr_significant") or label in ("insufficient_data", "negligible"):
        return f"no reliable link yet ({stats}); could be nothing"
    return f"{label} {result.get('direction')} association ({stats}, survives the family's FDR correction); correlational, not a cause"


def evaluate_family(series: Mapping[str, Mapping[str, Any]], correlate: Callable[..., dict], min_n: int) -> dict[str, dict[str, Any]]:
    """The family through the engine's own correlate(series, pairs=...), each result given its verdict."""
    results = correlate(dict(series), pairs=PAIRS) if series else {}
    for label, res in results.items():
        res["verdict"] = verdict(res, min_n)
        res["family"] = SOURCE
    for _x, _y, label, _lag in PAIRS:  # an empty window still names every pair, honestly
        results.setdefault(label, {"n_days": 0, "pearson_r": None, "verdict": verdict({"n_days": 0}, min_n), "family": SOURCE})
    return results


def run(
    *,
    fetch: Callable[[str, str, str], list],
    correlate: Callable[..., dict],
    put_item: Callable[..., Any],
    week_key: str,
    start_date: str,
    end_date: str,
    computed_at: str,
    target_for: Optional[Callable[[str], Optional[float]]] = None,
) -> dict[str, Any]:
    """Read the window, join, test, store the owner-only record. Returns the stored item (floats, not Decimals)."""
    from common.numeric import floats_to_decimal
    from experiment.experiment_gates import CORRELATION_MIN_N
    from training.training_charter import charter_version

    from health import protein_engine, titration

    if target_for is None:
        from health.calorie_target import target_kcal

        target_for = target_kcal  # THE target, titration > charter
    complete_log_kcal = titration.settings().get("complete_log_kcal")
    series = build_series(
        fetch("evening_checkin", start_date, end_date),
        fetch("macrofactor", start_date, end_date),
        fetch("apple_health", start_date, end_date),
        target_for,
        complete_log_kcal,
        protein_engine.hit,
    )
    results = evaluate_family(series, correlate, CORRELATION_MIN_N)
    item = {
        "pk": PK,
        "sk": SK_PREFIX + week_key,
        "week": week_key,
        "start_date": start_date,
        "end_date": end_date,
        "n_checkin_days": sum(1 for r in series.values() if any(r.get(f) is not None for f in CHECKIN_FIELDS)),
        "complete_log_kcal": complete_log_kcal,
        "pairs": [{"date": d, **row} for d, row in sorted(series.items())],
        "correlations": results,
        "charter_version": charter_version(),
        "engine_version": ENGINE_VERSION,
        "computed_at": computed_at,
        "tier": "owner_only",
    }
    put_item(Item=floats_to_decimal({k: v for k, v in item.items()}))
    return item


def latest_summary(table) -> Optional[dict[str, Any]]:
    """The newest stored week as {week, n_checkin_days, verdicts} for the owner's MCP read, or None."""
    from boto3.dynamodb.conditions import Key

    items = table.query(KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with(SK_PREFIX), ScanIndexForward=False, Limit=1).get(
        "Items"
    )
    if not items:
        return None
    it = items[0]
    verdicts = {k: (v or {}).get("verdict") for k, v in (it.get("correlations") or {}).items()}
    return {"week": it.get("week"), "n_checkin_days": int(it.get("n_checkin_days") or 0), "verdicts": verdicts}
