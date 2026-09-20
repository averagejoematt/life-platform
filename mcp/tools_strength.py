"""
Strength training tools: exercise history, PRs, volume, progress, frequency, standards.
"""

from datetime import datetime

from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.config import logger, table
from mcp.core import query_source_range
from mcp.strength_helpers import (
    _VOLUME_LANDMARKS,
    assess_volume_completeness,
    classify_exercise,
    extract_hevy_sessions,
    normalize_hevy_items,
    volume_status,
)


def tool_get_muscle_volume(args):
    """Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks."""
    start_date = args.get("start_date", "2000-01-01")
    end_date = args.get("end_date", pacific_now().date().isoformat())
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
            cls = classify_exercise(name, ex.get("template_id"))  # #3770: id override wins over name
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
    completeness = assess_volume_completeness(aggregated_dates, latest_ingested, end_date, start_date)

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


def _summarize_exercise_sessions(template_id: str, sessions: list) -> dict:
    """One movement's series → the summary shape `tool_get_exercise_history` returns.

    Pulled out of the tool body (#3932) so the multi-template-match branch can build one
    of these PER `template_id` instead of folding sessions from different movements into
    a single series — see the docstring on the caller for the incident this fixes.
    """
    classification = classify_exercise(sessions[0]["exercise_name"], template_id)  # #3770: id override wins over name
    pr_weight = 0.0
    pr_1rm = 0.0
    pr_log_weight = []
    pr_log_1rm = []
    for s in sessions:
        if s["best_weight"] > pr_weight:
            pr_weight = s["best_weight"]
            pr_log_weight.append({"date": s["date"], "weight_lbs": s["best_weight"]})
        if s["best_1rm"] and s["best_1rm"] > pr_1rm:
            pr_1rm = s["best_1rm"]
            pr_log_1rm.append({"date": s["date"], "estimated_1rm": s["best_1rm"]})

    first_1rm = sessions[0]["best_1rm"]
    last_1rm = sessions[-1]["best_1rm"]
    gain = round(last_1rm - first_1rm, 1) if first_1rm and last_1rm else None
    rpe_sessions = sum(1 for s in sessions if any(x.get("rpe") is not None for x in s["sets"]))
    noted = sum(1 for s in sessions if s.get("note_raw"))

    return {
        "exercise_name": sessions[0]["exercise_name"],
        "template_id": sessions[0].get("template_id") or template_id or None,
        "muscle_groups": classification["muscle_groups"],
        "movement_pattern": classification["movement_pattern"],
        "date_range": {"start": sessions[0]["date"], "end": sessions[-1]["date"]},
        "n_sessions": len(sessions),
        # ADR-104: this is the MEASURED partition, not the derived note-signal layer. A
        # caller that finds sessions here and zeros in get_exercise_notes has learned that
        # he logged the work and wrote nothing about it — never that the work is absent.
        "source": "raw hevy (measured)",
        "summary": {
            "total_sessions": len(sessions),
            "total_sets": sum(s["set_count"] for s in sessions),
            "best_weight_lbs": pr_weight,
            "best_estimated_1rm": pr_1rm if pr_1rm > 0 else None,
            "first_session_1rm": first_1rm,
            "last_session_1rm": last_1rm,
            "total_1rm_gain": gain,
            "sessions_with_rpe": rpe_sessions,
            "sessions_with_notes": noted,
        },
        "pr_chronology_weight": pr_log_weight,
        "pr_chronology_1rm": pr_log_1rm,
        "sessions": sessions,
    }


def tool_get_exercise_history(args):
    """Every logged set for ONE movement, across all time (#3766).

    RESTORED 2026-09-13. This tool shipped, went unused for the 30 days the #884 prune
    measured, and was removed — while three surfaces kept telling the coach to call it
    (`docs/coaching/COACH_SESSION.md`, `docs/SCHEMA.md`, and the live `get_exercise_notes`
    description, which named it as "a standard pre-flight pull"). On 2026-09-13 the coach
    was asked to program Leg Extension, found no exercise-level tool but the NOTES one,
    read its honest zero, and reported "no history" for a movement with twelve logged
    sessions since 2024-01-13 — working sets to 104 kg × 5. It then prescribed no load.

    Two changes from the pruned original, both from that incident:
      - accepts a `template_id` (the exact, stable Hevy handle) as well as a fuzzy name;
      - every set carries `rpe` and the exercise's `note_raw`, so "how heavy" and "how
        hard" arrive together and a caller never has to infer one from the other.

    #3932: the fuzzy `exercise_name` match is a case-insensitive SUBSTRING match, so
    `exercise_name="bench press"` matches every movement whose name contains that phrase
    — e.g. "Bench Press (Barbell)" AND "Bench Press (Incline Dumbbell)". Those are two
    different `template_id`s and two different 1RM trends; folding their sessions into
    one series produced `total_1rm_gain` figures that described neither movement (the
    reported `-114.5 lb` was PB-barbell-minus-recent-incline-dumbbell, not a real delta on
    any bar). The summary below is now always scoped to ONE `template_id`. When a fuzzy
    name resolves to more than one, this returns the candidate list plus a per-template
    summary for each — never a merged series. Pass `template_id` to pin one movement
    directly and skip the ambiguity check entirely.
    """
    exercise_name = (args.get("exercise_name") or args.get("exercise") or "").strip()
    template_id = (args.get("template_id") or "").strip()
    if not exercise_name and not template_id:
        return {"error": "Provide 'exercise_name' (fuzzy) or 'template_id' (exact)."}

    # No default lookback window. The point of this tool is the whole record — his Hevy
    # history runs to 2021, and a 180d default is exactly how #3708 hid 489 of 537 logged
    # movements from the planner.
    start_date = args.get("start_date", "2000-01-01")
    end_date = args.get("end_date", pacific_now().date().isoformat())
    include_warmups = bool(args.get("include_warmups", False))

    items = query_source_range("hevy", start_date, end_date)
    sessions = extract_hevy_sessions(items, exercise_name, include_warmups, template_id=template_id)

    if not sessions:
        label = f"template_id {template_id!r}" if template_id else f"'{exercise_name}'"
        out = {
            "error": f"No logged sets found for {label} in [{start_date}, {end_date}].",
            "searched": {"exercise_name": exercise_name or None, "template_id": template_id or None},
            "n_sessions": 0,
            "source": "raw hevy (measured)",
        }
        # An empty answer that cannot suggest an alternative is the failure this tool was
        # restored to prevent — say what IS there rather than only what is not.
        seen: dict[str, str] = {}
        for w in normalize_hevy_items(items):
            for ex in w.get("exercises") or []:
                if ex.get("name"):
                    seen.setdefault(ex["name"], ex.get("template_id") or "")
        needle = (exercise_name or "").lower()
        near = [n for n in seen if needle and any(tok in n.lower() for tok in needle.split())]
        if near:
            out["did_you_mean"] = [{"exercise_name": n, "template_id": seen[n]} for n in sorted(near)[:8]]
        return out

    # #3932: an exact template_id already scopes extract_hevy_sessions to one movement, so
    # this only ever triggers on a fuzzy exercise_name. Group by template_id (the empty
    # string groups movements Hevy never tagged with one — treated as their own bucket
    # rather than silently merged with a tagged movement of the same name).
    by_template: dict[str, list] = {}
    for s in sessions:
        by_template.setdefault(s.get("template_id") or "", []).append(s)

    if not template_id and len(by_template) > 1:
        candidates = []
        results = []
        for tid in sorted(by_template, key=lambda t: by_template[t][0]["exercise_name"]):
            tid_sessions = by_template[tid]
            candidates.append(
                {
                    "exercise_name": tid_sessions[0]["exercise_name"],
                    "template_id": tid or None,
                    "n_sessions": len(tid_sessions),
                }
            )
            results.append(_summarize_exercise_sessions(tid, tid_sessions))
        return {
            "ambiguous": True,
            "searched": {"exercise_name": exercise_name or None, "template_id": None},
            "note": (
                f"'{exercise_name}' matched {len(candidates)} distinct movements (template_ids) — one summary "
                "per movement below, never merged into a single series. Pass template_id to pin one."
            ),
            "candidates": candidates,
            "results": results,
        }

    return _summarize_exercise_sessions(template_id, sessions)
