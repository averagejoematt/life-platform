"""
Strength training tools: exercise history, PRs, volume, progress, frequency, standards.
"""

from datetime import date, datetime

from mcp.config import logger, table
from mcp.core import query_source_range
from mcp.strength_helpers import _VOLUME_LANDMARKS, assess_volume_completeness, classify_exercise, normalize_hevy_items, volume_status


def tool_get_muscle_volume(args):
    """Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks."""
    start_date = args.get("start_date", "2000-01-01")
    end_date = args.get("end_date", date.today().isoformat())
    period = args.get("period", "week")  # "week" or "month"

    items = query_source_range("hevy", start_date, end_date)

    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
    total_days = max((end_dt - start_dt).days, 1)
    num_periods = total_days / 7 if period == "week" else total_days / 30.44

    muscle_sets: dict[str, int] = {}
    muscle_volume: dict[str, float] = {}
    push_sets = pull_sets = leg_sets = core_sets = 0
    aggregated_dates: list[str] = []  # B2a: workout dates actually folded in

    # #110: normalize_hevy_items handles both schemas.
    for workout in normalize_hevy_items(items):
        wd = (workout.get("date") or "")[:10]
        if wd:
            aggregated_dates.append(wd)
        for ex in workout["exercises"]:
            name = ex["name"]
            cls = classify_exercise(name)
            normal_sets = [s for s in ex["sets"] if s["set_type"] != "warmup"]
            n = len(normal_sets)
            vol = sum(s["weight_lbs"] * s["reps"] for s in normal_sets)
            for m in cls["muscle_groups"]:
                muscle_sets[m] = muscle_sets.get(m, 0) + n
                muscle_volume[m] = muscle_volume.get(m, 0.0) + vol
            pattern = cls["movement_pattern"]
            if pattern == "Push":
                push_sets += n
            elif pattern == "Pull":
                pull_sets += n
            elif pattern == "Legs":
                leg_sets += n
            elif pattern == "Core":
                core_sets += n

    period_label = "week" if period == "week" else "month"
    volume_report = {}
    for muscle in sorted(muscle_sets):
        total_sets = muscle_sets[muscle]
        avg = total_sets / num_periods if num_periods > 0 else 0
        lm = _VOLUME_LANDMARKS.get(muscle, _VOLUME_LANDMARKS["Other"])
        volume_report[muscle] = {
            "total_sets": total_sets,
            f"avg_sets_per_{period_label}": round(avg, 1),
            "total_volume_lbs": round(muscle_volume.get(muscle, 0), 0),
            "volume_landmark_status": volume_status(muscle, avg),
            "landmarks": {
                "MV": lm["MV"],
                "MEV": lm["MEV"],
                "MAV": f"{lm['MAV_lo']}–{lm['MAV_hi']}",
                "MRV": lm["MRV"],
            },
        }

    push_pull_ratio = round(push_sets / pull_sets, 2) if pull_sets > 0 else None

    # B2a: completeness — did we fold in the latest ingested Hevy session? A read
    # that silently trails the high-water mark poisons night-before authoring.
    latest_ingested = None
    try:
        from boto3.dynamodb.conditions import Key as _HWKey

        _hw = table.query(
            KeyConditionExpression=_HWKey("pk").eq("USER#matthew#SOURCE#hevy") & _HWKey("sk").begins_with("DATE#"),
            Limit=1,
            ScanIndexForward=False,
            ProjectionExpression="sk",
        )
        _hw_items = _hw.get("Items", [])
        if _hw_items:
            latest_ingested = _hw_items[0]["sk"].split("DATE#", 1)[1][:10]
    except Exception as _e:  # noqa: BLE001
        logger.warning("muscle_volume completeness high-water query failed: %s", _e)
    completeness = assess_volume_completeness(aggregated_dates, latest_ingested, end_date)

    return {
        "date_range": {"start": start_date, "end": end_date},
        "analysis_period": period_label,
        "num_periods_analyzed": round(num_periods, 1),
        "completeness": completeness,
        "muscle_volume": volume_report,
        "movement_balance": {
            "push_sets": push_sets,
            "pull_sets": pull_sets,
            "leg_sets": leg_sets,
            "core_sets": core_sets,
            "push_pull_ratio": push_pull_ratio,
            "push_pull_note": (
                "Balanced"
                if push_pull_ratio and 0.8 <= push_pull_ratio <= 1.2
                else (
                    "Push-dominant – add more pulling"
                    if push_pull_ratio and push_pull_ratio > 1.2
                    else "Pull-dominant" if push_pull_ratio else "No data"
                )
            ),
        },
    }
