#!/usr/bin/env python3
"""One-shot supervised re-baseline of the MILESTONE# ledger (#1807).

The cycle-11 reset re-tagged every source partition to phase=pilot BEFORE the
first milestone sweep ran, so ledger genesis (2026-07-26) consumed ZERO rungs —
leaving every historically-crossed lifetime rung (weight_sub_340/330/320/310,
streak_*, days_tracked_*, level_*, window milestones) poised to announce as a
FRESH crossing in a write-once partition the moment cycle-11 data satisfies it
(~2026-08-02 for weight). Both genesis markers already exist live, so no code
path will ever baseline again on its own: this script is that path, once.

What it does: reads the FULL archive UNFILTERED (lifetime — pilot rows
included; the ledger is CROSS_PHASE, so its baseline is a lifetime question),
evaluates every rung/window candidate over the whole history (per-date
iteration, the same pure functions the sweep uses), and writes ORIGIN_BASELINE
rows (announce=False, event_date=None — no honest event date exists) for every
rung ever satisfied. Write-once conditional puts: already-consumed rungs are
untouched, re-running is a no-op.

Usage:
    python3 deploy/rebaseline_milestone_ledger_1807.py            # dry-run
    python3 deploy/rebaseline_milestone_ledger_1807.py --apply
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))

import milestone_ledger as ml  # noqa: E402
import process_milestones as pm  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402

REGION = "us-west-2"
TABLE = "life-platform"
USER_PREFIX = "USER#matthew#SOURCE#"

# Full-history floor — the platform's first ingested data is 2026-01; a fixed
# early floor keeps the scan bounded without risking a truncated lifetime view.
HISTORY_START = "2025-06-01"


def _query_all(table, source: str) -> list[dict]:
    """Whole partition, DATE#-prefixed, NO phase filter (lifetime read)."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk)",
        "ExpressionAttributeValues": {":pk": USER_PREFIX + source, ":sk": "DATE#"},
    }
    items: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs = dict(kwargs, ExclusiveStartKey=last)


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def collect_lifetime_signals(table) -> dict:
    """collect_signals' derivations, but over the WHOLE archive (no lookback caps)."""
    weights = _query_all(table, "withings")
    habits = _query_all(table, "habit_scores")
    chars = _query_all(table, "character_sheet")
    hevy = _query_all(table, "hevy")
    strava = _query_all(table, "strava")
    garmin = _query_all(table, "garmin")
    whoop = _query_all(table, "whoop")
    macro = _query_all(table, "macrofactor")
    measurements = _query_all(table, "measurements")

    weight_series = []
    for w in sorted(weights, key=lambda i: str(i.get("sk") or "")):
        sk = str(w.get("sk") or "")
        val = _f(w.get("weight_lbs"))
        if sk.startswith("DATE#") and len(sk) == 15 and val is not None:
            weight_series.append((sk[5:], val))

    habits_sorted = sorted(habits, key=lambda i: str(i.get("sk") or ""))
    # Historic MAX streak — every daily row carries the streak as of that day,
    # so the lifetime answer is the max over rows (the sweep's point-in-time
    # read can only see the streak at the END of history).
    max_streak = 0
    habit_days: list[str] = []
    for h in habits_sorted:
        sk = str(h.get("sk") or "")
        if not (sk.startswith("DATE#") and len(sk) == 15):
            continue
        habit_days.append(sk[5:])
        s = _f(h.get("t0_perfect_streak")) or _f(h.get("t0_aggregate_streak")) or 0
        max_streak = max(max_streak, int(s))

    # Historic MAX days-tracked inside any 365-day window (the rule's window).
    max_days_tracked = 0
    days = sorted(set(habit_days))
    lo = 0
    for hi in range(len(days)):
        while (datetime.strptime(days[hi], "%Y-%m-%d") - datetime.strptime(days[lo], "%Y-%m-%d")).days > 364:
            lo += 1
        max_days_tracked = max(max_days_tracked, hi - lo + 1)

    max_level = 1
    for c in chars:
        max_level = max(max_level, int(_f(c.get("character_level")) or 1))

    training_days: set[str] = set()
    strength_volume_by_day: dict[str, float] = {}
    for item in hevy:
        sk = str(item.get("sk") or "")
        if sk.startswith("DATE#") and "#WORKOUT#" in sk:
            day = sk[5:15]
            training_days.add(day)
            vol = _f(item.get("total_volume_kg"))
            if vol is not None:
                strength_volume_by_day[day] = strength_volume_by_day.get(day, 0.0) + vol

    garmin_z2_by_day: dict[str, float] = {}
    strava_z2_by_day: dict[str, float] = {}
    for item in garmin:
        sk = str(item.get("sk") or "")
        z2 = _f(item.get("zone2_minutes")) or _f(item.get("time_in_zone_2_minutes"))
        if sk.startswith("DATE#") and len(sk) == 15 and z2 is not None:
            garmin_z2_by_day[sk[5:15]] = garmin_z2_by_day.get(sk[5:15], 0.0) + z2
    for item in strava:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#"):
            continue
        day = sk[5:15]
        training_days.add(day)
        z2s = _f(item.get("total_zone2_seconds"))
        if z2s is not None:
            strava_z2_by_day[day] = strava_z2_by_day.get(day, 0.0) + z2s / 60.0
    zone2_by_day = {
        day: max(garmin_z2_by_day.get(day, 0.0), strava_z2_by_day.get(day, 0.0)) for day in set(garmin_z2_by_day) | set(strava_z2_by_day)
    }

    rhr_by_day: dict[str, float] = {}
    hrv_by_day: dict[str, float] = {}
    for item in whoop:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#") or "#WORKOUT#" in sk:
            continue
        rhr = _f(item.get("resting_heart_rate"))
        hrv = _f(item.get("hrv"))
        if rhr is not None:
            rhr_by_day[sk[5:15]] = rhr
        if hrv is not None:
            hrv_by_day[sk[5:15]] = hrv

    calories_by_day: dict[str, float] = {}
    expenditure_by_day: dict[str, float] = {}
    for item in macro:
        sk = str(item.get("sk") or "")
        if not sk.startswith("DATE#") or len(sk) != 15:
            continue
        cal = _f(item.get("total_calories_kcal"))
        exp = _f(item.get("expenditure_kcal")) or _f(item.get("tdee_kcal"))
        if cal is not None:
            calories_by_day[sk[5:15]] = cal
        if exp is not None:
            expenditure_by_day[sk[5:15]] = exp

    waist_by_day: dict[str, float] = {}
    for item in measurements:
        sk = str(item.get("sk") or "")
        waist = _f(item.get("waist_navel_in"))
        if sk.startswith("DATE#") and len(sk) == 15 and waist is not None:
            waist_by_day[sk[5:15]] = waist

    return {
        "weight_series": weight_series,
        "tier0_streak": max_streak,
        "days_tracked": max_days_tracked,
        "character_level": max_level,
        "training_dates": sorted(training_days),
        "strength_volume_by_day": strength_volume_by_day,
        "zone2_minutes_by_day": zone2_by_day,
        "rhr_by_day": rhr_by_day,
        "hrv_by_day": hrv_by_day,
        "calories_by_day": calories_by_day,
        "expenditure_by_day": expenditure_by_day,
        "waist_by_day": waist_by_day,
    }


def _all_data_dates(signals: dict) -> list[str]:
    dates: set[str] = set(d for d, _ in signals["weight_series"])
    dates |= set(signals["training_dates"])
    for key in ("zone2_minutes_by_day", "rhr_by_day", "waist_by_day", "calories_by_day"):
        dates |= set(signals[key])
    if not dates:
        return []
    lo = max(min(dates), HISTORY_START)
    hi = max(dates)
    d0 = datetime.strptime(lo, "%Y-%m-%d")
    n = (datetime.strptime(hi, "%Y-%m-%d") - d0).days + 1
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def historically_satisfied(signals: dict, today: str) -> dict[str, dict]:
    """{rule_id: first-satisfying measurement} across the whole archive."""
    out: dict[str, dict] = {}

    # Point-in-time count rules use the historic-max signals computed above.
    for rule in ml.MILESTONE_RULES:
        if rule.kind == ml.KIND_COUNT_GTE:
            ok, meas = ml._satisfied(rule, signals, today)
            if ok:
                out[rule.id] = meas

    # Weight rungs + window candidates: iterate every archive date.
    for d in _all_data_dates(signals):
        for rule in ml.MILESTONE_RULES:
            if rule.kind != ml.KIND_WEIGHT_MEAN_UNDER or rule.id in out:
                continue
            ok, meas = ml._satisfied(rule, signals, d)
            if ok:
                out[rule.id] = meas
        for cand, meas in pm.candidates(signals, d):
            if cand.id not in out:
                out[cand.id] = meas
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    ledger = ml.read_ledger(table, USER_PREFIX)
    if not ledger["has_genesis"]:
        print("❌ No genesis marker — this script repairs a completed-but-empty genesis; run the normal sweep instead.")
        return 1

    print("Reading the full archive UNFILTERED (lifetime)…")
    signals = collect_lifetime_signals(table)
    print(
        f"  weigh-ins={len(signals['weight_series'])} habit_days≈{signals['days_tracked']}(max-365d-window) "
        f"max_streak={signals['tier0_streak']} max_level={signals['character_level']} "
        f"training_days={len(signals['training_dates'])} waist_days={len(signals['waist_by_day'])}"
    )
    if not signals["weight_series"] and not signals["training_dates"]:
        print("❌ Lifetime read came back empty — refusing (#1807's own trap).")
        return 1

    satisfied = historically_satisfied(signals, today)
    to_write = {rid: meas for rid, meas in satisfied.items() if rid not in ledger["existing_ids"]}

    print(
        f"\nHistorically satisfied: {len(satisfied)} rung(s); already consumed: {len(satisfied) - len(to_write)}; TO BASELINE: {len(to_write)}"
    )
    all_rules = dict(ml.RULES_BY_ID)
    for rid in sorted(to_write):
        rule = all_rules.get(rid)
        label = rule.label if rule else rid
        print(f"  + {rid:<28} ({label})  evidence: {to_write[rid]}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    stamp = phase_taxonomy.experiment_stamp(include_phase=False)
    written = 0
    for rid, meas in sorted(to_write.items()):
        rule = all_rules.get(rid)
        if rule is None:
            # Window candidates aren't in RULES_BY_ID — rebuild the entry from
            # the candidate the same way the sweep's windows-genesis leg does.
            cand = next((c for c, _ in pm.candidates(signals, today) if c.id == rid), None)
            if cand is None:
                # Candidate satisfied only at a historical date — re-find it.
                for d in _all_data_dates(signals):
                    cand = next((c for c, _ in pm.candidates(signals, d) if c.id == rid), None)
                    if cand is not None:
                        break
            if cand is None:
                print(f"  !! {rid}: could not rebuild candidate — SKIPPED (investigate)")
                continue
            entry = ml._entry(cand, meas, today, announce=False, origin=ml.ORIGIN_BASELINE)
        else:
            entry = ml._entry(rule, meas, today, announce=False, origin=ml.ORIGIN_BASELINE)
        entry["rebaseline"] = "#1807"
        if ml._put_once(table, USER_PREFIX, entry, stamp):
            written += 1
            print(f"  ✅ baselined {rid}")
        else:
            print(f"  ⏭️  {rid} already consumed")
    print(f"\nDone: {written} baseline row(s) written (announce=False, event_date=None, rebaseline=#1807).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
