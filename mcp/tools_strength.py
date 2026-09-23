"""
Strength training tools: exercise history, PRs, volume, progress, frequency, standards.
"""

from datetime import datetime, timedelta

from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.config import logger, table
from mcp.core import phases_of, query_source_cross_phase
from mcp.strength_helpers import (
    _VOLUME_LANDMARKS,
    assess_volume_completeness,
    classify_exercise,
    extract_hevy_sessions,
    normalize_hevy_items,
    resolve_exercise_templates,
    volume_status,
)


def _read_hevy_all_phases(start_date: str, end_date: str) -> tuple[list, list[str]]:
    """Every Hevy workout in [start_date, end_date] — ALL phases — plus the phases read (#4030).

    Returns `(items, phases_read)`. Two corrections to the plain `query_source_range("hevy", …)`
    this replaces, both measured against live DynamoDB on 2026-09-21:

    1. **The phase filter comes off.** `query_source` defaults `include_pilot=False`, which applies
       the ADR-058 filter. `SOURCE#hevy` is `raw_timeseries` in `phase_taxonomy` — kept forever,
       genesis-ANCHORED on read (bounded by the caller's DATE window), never HIDDEN — and the
       taxonomy's own decision helper `phase_filter.source_reads_cross_phase("hevy")` already
       returns True. Nothing asked it. With the filter on, an all-time read of the partition
       returned 15 of 499 workouts (`{'pilot': 484, 'experiment': 15}`) and
       `get_exercise_history(template_id="2B4B7310")` reported the Romanian Deadlift's history as
       three September sessions with a `-31.2 lb` "1RM decline" — the 2026-06-21 session at
       83.91 kg x 8 x 3 was simply not there. The bypass is DERIVED, not hard-coded: if the
       taxonomy ever reclassifies hevy, this read follows it.

    2. **The superseded generation stays out.** The partition holds two shapes: 499 per-workout
       rows (`DATE#…#WORKOUT#<uuid>`) and 421 legacy daily aggregates (`DATE#…`) superseded in
       place on 2026-05-26 — every one of the 421 carries `tombstone=true,
       tombstoned_reason="legacy_daily_aggregate_superseded_by_per_workout"`, and every one of
       their dates is also covered by a per-workout row. `normalize_hevy_items` parses BOTH
       shapes, so lifting the phase filter alone would have returned each pre-2025-11-08 session
       TWICE on the fuzzy-name path (`exercise_name="squat"`: 486 sessions vs 250 real ones;
       `"bench press"`: 655 vs 344). Dropping `tombstone=true` is the item-level rule
       `phase_filter.singleton_visible` already encodes for key reads. Nothing is lost.

    #4032 moved both corrections down into `mcp.core.query_source_cross_phase`, which is
    now the ONE implementation of them. The energy-budget surface reads the same Hevy set
    log through THIS helper (`tools_health._get_energy_expenditure`,
    `tools_nutrition._hevy_workouts`) and its sibling raw_timeseries partitions through
    that core helper directly — so there is a single read path, not a second one that can
    drift from this docstring.
    """
    items = query_source_cross_phase("hevy", start_date, end_date)
    return items, phases_of(items)


def template_alias_map() -> tuple[dict[str, str], dict]:
    """(alias id -> canonical id, registry status) — the ONE alias table (#3929), read for #4069.

    The table is `config/hevy_template_aliases.json`, resolved by the adherence scorer's own
    `canonical_template_ids` — this module keeps no pairing of its own. An unreadable registry
    yields an EMPTY map (every id is its own identity, the pre-#3929 behaviour) and a status that
    says so; it is never reported as "no aliases exist".
    """
    try:
        from health.adherence_calc import canonical_template_ids

        amap = canonical_template_ids()
        return amap, {"status": "read", "source": "config/hevy_template_aliases.json", "aliases": len(amap)}
    except Exception as e:  # noqa: BLE001 — identity degrades to raw template ids, and says so
        logger.warning("template alias registry unreadable (#4069): %s", e)
        return {}, {
            "status": "unreadable",
            "source": "config/hevy_template_aliases.json",
            "reason": f"{type(e).__name__}: raw template ids used without alias resolution",
        }


def _matched_templates(sessions: list) -> list[dict]:
    """Which template identities a series was built from, with every raw id and title (#4069)."""
    rows: dict[str, dict] = {}
    for s in sessions:
        ident = s.get("identity") or s.get("template_id") or ""
        r = rows.setdefault(ident, {"identity": ident, "template_ids": set(), "titles": set(), "n_sessions": 0})
        if s.get("template_id"):
            r["template_ids"].add(str(s["template_id"]).upper())
        r["titles"].add(s.get("exercise_name") or "")
        r["n_sessions"] += 1
    return [{**r, "template_ids": sorted(r["template_ids"]), "titles": sorted(r["titles"])} for r in rows.values()]


def _searched_block(exercise_name: str, template_id: str, start_date: str, end_date: str, items: list, phases_read: list[str]) -> dict:
    """The provenance every answer carries (#4030) — what was asked, over what window, across which phases.

    An empty answer that does not name its window and its phases is indistinguishable from
    "never done"; that read is the whole reason this issue exists.
    """
    block = {
        "window": {"start": start_date, "end": end_date},
        "phases": phases_read,
        "phase_filter": "none — SOURCE#hevy is raw_timeseries (ADR-077/#2109), read across every phase",
        "workouts_read": len(items),
    }
    # #4031: `tool_get_muscle_volume` reuses this block and asks about no single movement.
    # Two null movement keys there would read as "asked for a movement and found nothing",
    # which is the same misreading this block exists to prevent. Only a read that names a
    # movement carries the movement keys; `tool_get_exercise_history` refuses the call
    # unless one of them is set, so its block is unchanged.
    if exercise_name or template_id:
        return {"exercise_name": exercise_name or None, "template_id": template_id or None, **block}
    return block


# #4031: a RATE needs a window it can plausibly be a rate over. The old default was
# `2000-01-01`, which `avg_sets_per_period` then divided by — ~1,380 weeks, so the default
# call reported ~0.0 sets/week for every muscle and "below maintenance" across the board
# (measured live 2026-09-21: num_periods_analyzed 1394.3, Chest 72 sets -> 0.1/wk). The
# all-time default is right for `get_exercise_history` (a RECORD) and wrong here.
# 28 days = four whole weeks, the RP mesocycle unit the landmarks are defined over; the
# month view takes 90 days ≈ 2.96 months for the same reason.
_DEFAULT_LOOKBACK_DAYS = {"week": 28, "month": 90}


def tool_get_muscle_volume(args):
    """Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks — cross-phase (#4031).

    Two read defects fixed here, both found by #4030's consumer audit and both measured
    read-only against live DynamoDB on 2026-09-21. Neither touches the prescription logic:
    `volume_status`, `classify_exercise` and `_VOLUME_LANDMARKS` are untouched. What changes
    is what gets COUNTED and what it is divided BY — which does move the verdict, and that
    is the point of the issue.

    1. **The phase filter comes off.** This read `query_source_range("hevy", …)` — an alias
       for `query_source(..., include_pilot=False)`, the ADR-058 filter — over a partition
       `phase_taxonomy` classifies `raw_timeseries`, i.e. cross-phase by design. Every
       pre-genesis row is stamped `phase=pilot` by the restart tagger, so every trailing
       window silently truncated to the CYCLE'S AGE: a 30-day window 15 days after genesis
       counted 15 days of work and divided by 4.3 weeks. Measured, 30d (2026-08-22..09-21):
       Chest 72 -> 84 sets, Triceps 87 -> 99, Shoulders 56 -> 66. The error is a function of
       days-since-genesis, so it is smallest exactly when anyone looks for it and TOTAL on
       day 1 of a cycle. The bypass is derived from `source_reads_cross_phase("hevy")` via
       `_read_hevy_all_phases` (#4030), never hard-coded here, and that helper also drops the
       421 superseded `tombstone=true` legacy daily aggregates so nothing is double-counted.

    2. **The default window is a rate window.** See `_DEFAULT_LOOKBACK_DAYS`.

    The answer echoes what it actually did in `searched`: the window, whether that window
    was the caller's or the default, and the phases read.
    """
    end_date = args.get("end_date", pacific_now().date().isoformat())
    period = args.get("period", "week")  # "week" or "month"
    # Same "anything not 'week' is a month" rule the period label and divisor below use —
    # the enum itself is validated at the handler boundary (#2660).
    lookback_days = _DEFAULT_LOOKBACK_DAYS["week" if period == "week" else "month"]

    caller_start = args.get("start_date")
    if caller_start:
        start_date = caller_start
    else:
        start_date = (datetime.fromisoformat(end_date) - timedelta(days=lookback_days)).date().isoformat()

    # #4031: cross-phase by the taxonomy's own ruling, minus the superseded legacy generation.
    items, phases_read = _read_hevy_all_phases(start_date, end_date)

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

    searched = {
        **_searched_block("", "", start_date, end_date, items, phases_read),
        # #4031: which window this rate is actually over, and whose window it was. A
        # divisor the caller did not choose must never be invisible in the answer.
        "window_source": ("caller" if caller_start else f"default trailing {lookback_days}d ({period_label} view)"),
        "default_lookback_days": lookback_days,
    }

    return {
        "date_range": {"start": start_date, "end": end_date},
        "analysis_period": period_label,
        "num_periods_analyzed": round(num_periods, 1),
        "searched": searched,
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
        # #4069: the identity this ONE series is keyed on, and every raw template id / title
        # folded into it (only a confirmed alias folds two ids — never a shared substring).
        "identity": sessions[0].get("identity") or sessions[0].get("template_id") or template_id or None,
        "matched_templates": _matched_templates(sessions),
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
    """Every logged set for ONE movement, across all time and EVERY experiment phase (#3766, #4030).

    The guarantee, stated precisely: this reads the whole `SOURCE#hevy` partition inside
    `[start_date, end_date]` — default `2000-01-01` → today (Pacific) — with **no phase filter**,
    so a pre-genesis session counts exactly as much as one logged this morning. The superseded
    legacy daily-aggregate generation (`tombstone=true`) is excluded so nothing is double-counted.
    Every answer, empty or not, carries a `searched` block naming the window, the phases actually
    read and how many workouts were read, so "no data" can never be misread as "never done".

    #4030 — why that paragraph had to be written. `query_source_range` is an alias for
    `query_source(..., include_pilot=False)`, which applies the ADR-058 phase filter. The reset
    stamps every pre-genesis row `phase=pilot`, so this tool — whose entire purpose is the whole
    record — was answering from the CURRENT CYCLE ONLY. Measured live 2026-09-21: 15 of 499
    workouts visible, 26 of 557 distinct movements; `template_id="2B4B7310"` returned
    `2026-09-09..2026-09-17, n_sessions 3` and a `total_1rm_gain` of `-31.2 lb` computed over
    eight days of a five-year record, with the owner's 2026-06-21 Romanian Deadlift (83.91 kg x 8
    x 3) absent; `exercise_name="squat", start_date="2021-01-01"` returned "No logged sets found"
    against 250 real squat-matching sessions. `get_workout_detail` reads by key and applies no
    filter, which is why the two tools disagreed. `phase_taxonomy.classify` rules the partition
    `raw_timeseries` — CROSS-PHASE by design — and `phase_filter.source_reads_cross_phase("hevy")`
    already returned True; the read simply never asked. Same defect class as #3615 box 4 (the
    voice sampler) and #2109 (the compute layer's generic readers). See `_read_hevy_all_phases`.

    ---

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

    #4069: the substring now only RESOLVES a name to template identities (reported as
    `searched.name_resolved_to`); sets are selected and grouped by identity
    (`strength_helpers.exercise_identity` — the raw id through the ONE alias registry,
    `config/hevy_template_aliases.json`, #3929), never by name. So a confirmed alias pair
    reads as one movement, a variant is never another variant's history, and every series
    carries `matched_templates` naming the ids and titles it was built from. The
    `anchor_lift_strength_drop` input (`tools_plan._anchor_trend`) reads through this path.
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

    # #4030: cross-phase by the taxonomy's own ruling, minus the superseded legacy generation.
    items, phases_read = _read_hevy_all_phases(start_date, end_date)
    searched = _searched_block(exercise_name, template_id, start_date, end_date, items, phases_read)
    # #4069: every series keys on template IDENTITY (raw id through the #3929 alias registry).
    # A name is resolved to the identities it matched FIRST, and the answer names them.
    alias_map, alias_status = template_alias_map()
    searched["alias_registry"] = alias_status
    if not template_id:
        searched["name_resolved_to"] = resolve_exercise_templates(items, exercise_name, alias_map)
    sessions = extract_hevy_sessions(items, exercise_name, include_warmups, template_id=template_id, alias_map=alias_map)

    if not sessions:
        label = f"template_id {template_id!r}" if template_id else f"'{exercise_name}'"
        phases_txt = ", ".join(phases_read) if phases_read else "none (no workouts in this window)"
        out = {
            # #4030: the window AND the phases, in the sentence itself — a caller that reads only
            # the `error` string must still be unable to mistake this for "never done".
            "error": (
                f"No logged sets found for {label} in [{start_date}, {end_date}] "
                f"across {len(items)} workouts spanning phases: {phases_txt}. "
                "No phase filter was applied — this searched every experiment cycle in that window."
            ),
            "searched": searched,
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
    #
    # #4069: grouped by IDENTITY, not raw id — a confirmed alias (#3929) is one movement, and an
    # untagged title is its own `untagged:<title>` bucket (see `exercise_identity`).
    by_template: dict[str, list] = {}
    for s in sessions:
        by_template.setdefault(s.get("identity") or s.get("template_id") or "", []).append(s)

    if not template_id and len(by_template) > 1:
        candidates = []
        results = []
        for tid in sorted(by_template, key=lambda t: by_template[t][0]["exercise_name"]):
            tid_sessions = by_template[tid]
            candidates.append(
                {
                    "exercise_name": tid_sessions[0]["exercise_name"],
                    "template_id": tid_sessions[0].get("template_id") or None,
                    "identity": tid or None,
                    "template_ids": sorted({str(x["template_id"]).upper() for x in tid_sessions if x.get("template_id")}),
                    "n_sessions": len(tid_sessions),
                }
            )
            results.append(_summarize_exercise_sessions(tid_sessions[0].get("template_id") or "", tid_sessions))
        return {
            "ambiguous": True,
            "searched": searched,
            "note": (
                f"'{exercise_name}' matched {len(candidates)} distinct movements (template_ids) — one summary "
                "per movement below, never merged into a single series. Pass template_id to pin one."
            ),
            "candidates": candidates,
            "results": results,
        }

    # #4030: the window and the phases ride on the answer, not just on the failure.
    return {**_summarize_exercise_sessions(template_id, sessions), "searched": searched}
