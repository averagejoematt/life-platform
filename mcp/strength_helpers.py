"""
Strength training helpers: exercise classification, 1RM estimation, volume tracking.
"""

from training.muscle_volume import attribute_exercise

# #4071: the exercise -> muscle taxonomy lives in ONE place,
# `lambdas/training/muscle_volume.py::EXERCISE_TAXONOMY` (one primary muscle per row, a
# secondary only where the row names it, at a stated fraction). The keyword table that used
# to live here credited every set to every muscle in its row — Quads and Hamstrings came out
# identical — and let "curl" swallow "Seated Leg Curl". It is gone, not kept beside the new one.

_BODYWEIGHT_EXERCISES = [
    "pull up",
    "pullup",
    "pull-up",
    "chin up",
    "chinup",
    "chin-up",
    "dip",
    "push up",
    "pushup",
    "push-up",
    "bodyweight squat",
]


def classify_exercise(name: str, template_id: str | None = None) -> dict:
    """Return {muscle_groups, movement_pattern, primary_muscle, secondary_muscles} for an exercise.

    A LABEL, not a count: `muscle_groups` is the primary followed by any named secondaries, for
    callers that ask "which muscles does this movement touch" (exercise-history labels, muscle
    recency). Per-muscle SET counts come only from `training.muscle_volume.working_sets_by_muscle`
    (#4071), which weights secondaries by their stated fraction.

    #3770: a Hevy template id with an id-keyed override wins over any name match.
    """
    attr = attribute_exercise(name, template_id)
    if attr["primary"] is None:
        return {"muscle_groups": ["Other"], "movement_pattern": "Other", "primary_muscle": None, "secondary_muscles": {}}
    return {
        "muscle_groups": [attr["primary"], *attr["secondary"]],
        "movement_pattern": attr["movement_pattern"],
        "primary_muscle": attr["primary"],
        "secondary_muscles": dict(attr["secondary"]),
    }


def is_bodyweight(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in _BODYWEIGHT_EXERCISES)


def assess_volume_completeness(aggregated_dates, latest_ingested_date, end_date, start_date=None):
    """Did the volume aggregation include the latest ingested Hevy session?

    The night-before authoring bug (B2a, 2026-06-21): get_muscle_volume read a
    high-water-mark that hadn't caught the latest session, so it undercounted
    (calves 10/'lagging' when they were 14/'optimal'). This is the same
    completeness-vs-recency class as the Strava high-water-mark blindness.

    Pure function — no AWS. Inputs are 'YYYY-MM-DD' strings (or None):
      aggregated_dates      — workout dates actually folded into the volume math
      latest_ingested_date  — newest DATE# in the Hevy partition (high-water mark)
      end_date              — the analysis window end
      start_date            — the analysis window start (#2664; None = unbounded)

    Returns a dict the tool surfaces as `completeness`. `includes_latest` is True
    when the aggregation reached the newest in-window ingested session; when False,
    a session exists that the analysis didn't fold in → `stale` True, and the
    authoring gate (Stage 2) must block or flag rather than prescribe off it.
    """
    dates = sorted(d for d in (aggregated_dates or []) if d)
    data_current_through = dates[-1] if dates else None

    if not latest_ingested_date:
        return {
            "data_current_through": data_current_through,
            "latest_ingested": None,
            "includes_latest": data_current_through is None,
            "stale": False,
            "note": "No Hevy sessions ingested.",
        }

    # Only the high-water mark *inside* the requested window is a completeness signal.
    # A session newer than end_date is simply out of scope (not a gap), and rest days
    # at the tail of the window are legitimate — never flag those as stale. The genuine
    # bug is: the partition's newest session falls in-window yet the aggregation missed
    # it (the night-before undercount).
    #
    # #2664: "within window" tested only the END. A window that starts AFTER the last
    # session (`2026-08-01..2026-08-15` against a partition whose newest session is
    # 2026-06-25) therefore took the in-window branch, reported `stale: true`, and told
    # the caller "a more recent IN-WINDOW session is ingested (2026-06-25) … do not
    # author off this read until it clears" — about a date six weeks before the window
    # opened. Nothing was missing; there was simply no training in August. That is a
    # false gate on a true statement, and it never clears.
    #
    # When the high-water mark predates the window, every ingested session does, so the
    # window provably contains zero sessions and an empty aggregation is exactly right
    # (ADR-104: absence is data, not a defect). Only the >end case stays conservative —
    # there the newest session says nothing about whether the window itself had any.
    before_window = start_date is not None and latest_ingested_date < start_date
    within_window = not before_window and (end_date is None or latest_ingested_date <= end_date)

    if before_window:
        return {
            "data_current_through": data_current_through,
            "latest_ingested": latest_ingested_date,
            "includes_latest": True,
            "stale": False,
            "note": (
                f"No Hevy sessions in the requested window — the most recent session on file "
                f"({latest_ingested_date}) predates it. Zero volume here is real, not missing data."
            ),
        }

    if within_window:
        includes_latest = data_current_through is not None and data_current_through >= latest_ingested_date
    else:
        includes_latest = data_current_through is not None
    stale = not includes_latest

    if stale and within_window:
        note = (
            f"Aggregation current through {data_current_through or 'none'} but a more recent "
            f"in-window session is ingested ({latest_ingested_date}). Volume may undercount the "
            "latest training — do not author off this read until it clears."
        )
    elif stale:
        note = "No in-window sessions aggregated."
    else:
        note = f"Includes the latest in-window session ({data_current_through})."

    return {
        "data_current_through": data_current_through,
        "latest_ingested": latest_ingested_date,
        "includes_latest": includes_latest,
        "stale": stale,
        "note": note,
    }


def estimate_1rm(weight: float, reps: int) -> float | None:
    """Epley formula. Valid for reps 1-10."""
    if weight <= 0 or reps < 1 or reps > 10:
        return None
    if reps == 1:
        return round(weight, 1)
    return round(weight * (1 + reps / 30), 1)


_KG_TO_LBS = 2.20462


def normalize_hevy_items(hevy_items: list) -> list[dict]:
    """Returns a flat, schema-agnostic list of workouts.

    The Hevy partition has lived in two shapes:
      Old (≤ 2026-05): one DDB item per day, sk = DATE#YYYY-MM-DD,
        item['data']['workouts'][n].exercises[n].sets[n].weight_lbs.
      New (≥ 2026-05): one DDB item per workout, sk = DATE#YYYY-MM-DD#WORKOUT#<uuid>,
        exercises at top level, set weights in weight_kg (Hevy's native unit).

    All readers downstream want: a flat list of workouts, each with
    {date, workout_name, exercises:[{name, sets:[{set_type, weight_lbs, reps}]}]}.
    Weights normalized to lbs; we keep weight_kg as well for any caller that
    wants it.

    Burned in 2026-05-30: tool_get_workout_frequency was filtering on
    item['data']['workouts'], which never matched the new shape — every
    new-shape workout was invisible to the read tools.
    """

    def _set(s: dict) -> dict:
        w_kg = s.get("weight_kg")
        w_lbs = s.get("weight_lbs")
        if w_kg is not None and w_lbs is None:
            w_lbs = float(w_kg) * _KG_TO_LBS
        elif w_lbs is not None and w_kg is None:
            w_kg = float(w_lbs) / _KG_TO_LBS
        out = {
            # #4071: the live per-workout rows carry the type as `type`; only the legacy daily
            # aggregates used `set_type`. Reading `set_type` alone defaulted every live warm-up
            # to "normal", so every warm-up filter downstream had nothing to drop.
            "set_type": s.get("set_type") or s.get("type") or "normal",
            "weight_lbs": float(w_lbs or 0),
            "weight_kg": float(w_kg or 0),
            "reps": int(s.get("reps") or 0),
        }
        # #3766: RPE carried through, additively. The normalizer used to drop it, so every
        # consumer downstream could say how heavy a set was and none could say how hard it
        # felt — the distinction `get_exercise_history` exists to serve. Absent stays absent
        # (None, never 0): most of the 2024 corpus predates RPE logging (ADR-104).
        rpe = s.get("rpe")
        out["rpe"] = float(rpe) if rpe not in (None, "") else None
        return out

    def _exercise(ex: dict) -> dict:
        return {
            "name": ex.get("name") or ex.get("exercise_name") or "",
            # #3766: the stable Hevy template id and the freeform note, both additive. The
            # id is what lets a caller ask by template rather than by a fuzzy name; the note
            # is the raw text the derived signal layer is built FROM, and stays sovereign.
            "template_id": str(ex.get("template_id") or ""),
            "notes": (ex.get("notes") or "").strip(),
            "sets": [_set(s) for s in (ex.get("sets") or [])],
        }

    out = []
    for item in hevy_items:
        sk = item.get("sk", "")
        # New per-workout shape: sk contains #WORKOUT#, exercises at top.
        if "#WORKOUT#" in sk and item.get("exercises") is not None:
            date_str = item.get("date") or (sk.split("DATE#", 1)[1].split("#", 1)[0] if "DATE#" in sk else "")
            out.append(
                {
                    "date": date_str,
                    "workout_name": item.get("workout_name") or item.get("title") or "",
                    "exercises": [_exercise(ex) for ex in item.get("exercises", [])],
                }
            )
            continue
        # Legacy per-day shape: workouts nested under data.workouts (or top-level workouts).
        date_str = item.get("date") or sk[5:15]
        workouts = item.get("data", {}).get("workouts") or item.get("workouts") or []
        for w in workouts:
            out.append(
                {
                    "date": date_str,
                    "workout_name": w.get("name") or w.get("workout_name") or "",
                    "exercises": [_exercise(ex) for ex in (w.get("exercises") or [])],
                }
            )
    return out


def exercise_identity(template_id: str | None, name: str | None, alias_map: dict[str, str] | None = None) -> str:
    """The ONE identity a performed exercise is keyed by in a history / anchor series (#4069).

    A Hevy `template_id` (upper-cased), mapped through the confirmed alias registry
    (`config/hevy_template_aliases.json`, #3929 — alias id -> canonical id) when one is
    supplied. A name never enters this key when an id exists: "Bench Press (Barbell)" and
    "Incline Bench Press (Dumbbell)" share a substring and are two identities. An exercise
    Hevy never tagged with an id gets `untagged:<exact title>` — its own bucket, never
    merged with a tagged movement or with a different untagged title.
    """
    tid = (template_id or "").strip().upper()
    if tid:
        return (alias_map or {}).get(tid, tid)
    return "untagged:" + " ".join((name or "").strip().lower().split())


def resolve_exercise_templates(hevy_items: list, exercise_name: str, alias_map: dict[str, str] | None = None) -> list[dict]:
    """A user-facing NAME -> the set of template identities it matched (#4069).

    The name is a SEARCH, never an identity: it is matched (case-insensitive substring) against
    the titles actually logged, and the answer is the list of template ids those titles carry —
    one row per canonical identity, naming every raw template id and title folded into it (only
    the alias registry folds two ids together). Every series is then built from these ids, so the
    substring decides WHICH movements are candidates and never which sets belong to a movement.
    """
    needle = " ".join((exercise_name or "").strip().lower().split())
    if not needle:
        return []
    rows: dict[str, dict] = {}
    for workout in normalize_hevy_items(hevy_items):
        for ex in workout["exercises"]:
            title = ex["name"] or ""
            if needle not in " ".join(title.lower().split()):
                continue
            ident = exercise_identity(ex.get("template_id"), title, alias_map)
            row = rows.setdefault(ident, {"identity": ident, "template_ids": set(), "titles": set(), "n_sessions": 0})
            raw = (ex.get("template_id") or "").strip().upper()
            if raw:
                row["template_ids"].add(raw)
            row["titles"].add(title)
            row["n_sessions"] += 1
    out = []
    for ident in sorted(rows, key=lambda i: (-rows[i]["n_sessions"], i)):
        r = rows[ident]
        out.append({**r, "template_ids": sorted(r["template_ids"]), "titles": sorted(r["titles"])})
    return out


def extract_hevy_sessions(
    hevy_items: list,
    exercise_name: str,
    include_warmups: bool = False,
    template_id: str = "",
    alias_map: dict[str, str] | None = None,
) -> list:
    """
    Given raw DynamoDB hevy items and a target exercise name (fuzzy) OR an exact Hevy
    `template_id`, return a list of session dicts sorted by date.
    Each session: {date, sets: [{set_type, weight_lbs, reps, estimated_1rm}], best_1rm, best_weight, volume,
    template_id, identity}

    #4069: sets are selected by template IDENTITY only (`exercise_identity`). A `template_id`
    selects its canonical identity — so a confirmed alias id is the same movement, and nothing
    else is. A fuzzy name is first RESOLVED to the identities whose logged titles contain it
    (`resolve_exercise_templates`); the substring never gates a set directly. Each session
    carries its `identity`, so a caller can never fold two identities into one series without
    seeing that it did.
    """
    # #3766: a Hevy template id is the exact, stable handle for a movement; a name is a
    # fuzzy one. "75A4F6C4" as a substring of a NAME matches nothing, so accept it as an id.
    target_tid = (template_id or "").strip().upper()
    if target_tid:
        wanted = {exercise_identity(target_tid, "", alias_map)}
    else:
        wanted = {r["identity"] for r in resolve_exercise_templates(hevy_items, exercise_name, alias_map)}
    sessions: list[dict] = []
    if not wanted:
        return sessions
    for workout in normalize_hevy_items(hevy_items):
        date_str = workout["date"]
        for ex in workout["exercises"]:
            ex_name = ex["name"]
            identity = exercise_identity(ex.get("template_id"), ex_name, alias_map)
            if identity not in wanted:
                continue
            sets_out = []
            for s in ex["sets"]:
                st = s["set_type"]
                if not include_warmups and st == "warmup":
                    continue
                w = s["weight_lbs"]
                r = s["reps"]
                e1rm = None if is_bodyweight(ex_name) else estimate_1rm(w, r)
                sets_out.append(
                    {"set_type": st, "weight_lbs": w, "weight_kg": s["weight_kg"], "reps": r, "rpe": s["rpe"], "estimated_1rm": e1rm}
                )
            if not sets_out:
                continue
            best_1rm = max((s["estimated_1rm"] for s in sets_out if s["estimated_1rm"]), default=None)
            best_weight = max((s["weight_lbs"] for s in sets_out), default=0)
            volume = sum(s["weight_lbs"] * s["reps"] for s in sets_out)
            sessions.append(
                {
                    "date": date_str,
                    "exercise_name": ex_name,
                    "template_id": ex.get("template_id") or "",
                    "identity": identity,
                    "note_raw": ex.get("notes") or "",
                    "sets": sets_out,
                    "best_1rm": best_1rm,
                    "best_weight": best_weight,
                    "volume_lbs": round(volume, 1),
                    "set_count": len(sets_out),
                }
            )
    sessions.sort(key=lambda x: x["date"])
    return sessions


_VOLUME_LANDMARKS = {
    "Chest": {"MV": 4, "MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Back": {"MV": 6, "MEV": 10, "MAV_lo": 14, "MAV_hi": 20, "MRV": 25},
    "Shoulders": {"MV": 4, "MEV": 8, "MAV_lo": 12, "MAV_hi": 20, "MRV": 25},
    "Quads": {"MV": 4, "MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Hamstrings": {"MV": 2, "MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Glutes": {"MV": 2, "MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Biceps": {"MV": 2, "MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Triceps": {"MV": 2, "MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Calves": {"MV": 4, "MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Core": {"MV": 0, "MEV": 4, "MAV_lo": 6, "MAV_hi": 16, "MRV": 25},
    "Other": {"MV": 0, "MEV": 0, "MAV_lo": 0, "MAV_hi": 0, "MRV": 99},
}


def volume_status(muscle: str, sets_per_week: float) -> str:
    lm = _VOLUME_LANDMARKS.get(muscle, _VOLUME_LANDMARKS["Other"])
    if sets_per_week < lm["MV"]:
        return "below maintenance"
    if sets_per_week < lm["MEV"]:
        return "maintenance only"
    if sets_per_week <= lm["MAV_lo"]:
        return "approaching MEV / low optimal"
    if sets_per_week <= lm["MAV_hi"]:
        return "optimal (MEV–MAV)"
    if sets_per_week <= lm["MRV"]:
        return "approaching MRV – high volume"
    return "exceeding MRV – overtraining risk"


_STRENGTH_STANDARDS = {
    "bench press": {"Untrained": 0.50, "Novice": 0.75, "Intermediate": 1.00, "Advanced": 1.50, "Elite": 2.00},
    "squat": {"Untrained": 0.75, "Novice": 1.00, "Intermediate": 1.50, "Advanced": 2.00, "Elite": 2.75},
    "deadlift": {"Untrained": 1.00, "Novice": 1.25, "Intermediate": 1.75, "Advanced": 2.50, "Elite": 3.25},
    "overhead press": {"Untrained": 0.35, "Novice": 0.50, "Intermediate": 0.75, "Advanced": 1.00, "Elite": 1.50},
}
_STANDARD_LEVELS = ["Untrained", "Novice", "Intermediate", "Advanced", "Elite"]


# ── Attia Centenarian Decathlon — Strength Benchmarks ─────────────────────────
# Source: Peter Attia "Outlive" + training frameworks.
# Premise: to be functionally strong at 80, you need these ratios now (age 35-55).
# Each muscle takes ~8-12% decline per decade from ~40; compound interest of decline
# means a 50-year-old needs 1.75x BW deadlift now to maintain 1.0x BW at 85.
# Ratios are bodyweight multipliers for estimated 1RM.

_ATTIA_TARGETS = {
    "deadlift": {
        "description": "Full-body posterior chain. Foundation of functional independence.",
        "target_ratio": 2.0,  # goal: 2× BW 1RM now to have 1× BW at ~85
        "minimum_ratio": 1.5,  # minimum acceptable for longevity protection
        "elite_ratio": 2.5,
        "centenarian_projection": 1.0,  # target at age ~85
    },
    "squat": {
        "description": "Quad-dominant compound. Sit-to-stand independence at old age.",
        "target_ratio": 1.75,
        "minimum_ratio": 1.25,
        "elite_ratio": 2.25,
        "centenarian_projection": 0.9,
    },
    "bench press": {
        "description": "Upper body push. Ability to push off floor or furniture.",
        "target_ratio": 1.5,
        "minimum_ratio": 1.0,
        "elite_ratio": 2.0,
        "centenarian_projection": 0.75,
    },
    "overhead press": {
        "description": "Overhead pressing. Reach overhead without assistance.",
        "target_ratio": 1.0,
        "minimum_ratio": 0.65,
        "elite_ratio": 1.35,
        "centenarian_projection": 0.5,
    },
}

# Status tiers relative to target_ratio
_ATTIA_STATUS_TIERS = [
    (1.10, "exceeds_target", "Exceeds Attia target"),
    (1.00, "at_target", "At Attia target"),
    (0.85, "approaching", "Approaching target (within 15%)"),
    (0.65, "progressing", "Progressing — solid base"),
    (0.00, "below_minimum", "Below minimum threshold"),
]


def attia_benchmark_status(lift_key: str, bw_ratio: float) -> dict:
    """Return Attia centenarian benchmark status for a lift.

    Args:
        lift_key:  Normalised lift name (e.g. 'deadlift', 'squat').
        bw_ratio:  Current best estimated 1RM ÷ bodyweight.

    Returns:
        Dict with status, pct_of_target, gap_ratio, and interpretation.
    """
    target = _ATTIA_TARGETS.get(lift_key)
    if not target:
        return {"error": f"No Attia benchmark defined for '{lift_key}'"}

    t_ratio = target["target_ratio"]
    min_ratio = target["minimum_ratio"]
    pct_of_target = round(bw_ratio / t_ratio * 100, 1)
    gap_ratio = round(t_ratio - bw_ratio, 3)
    gap_pct_of_target = round(gap_ratio / t_ratio * 100, 1)

    status = "below_minimum"
    label = "Below minimum threshold"
    for threshold, code, text in _ATTIA_STATUS_TIERS:
        if pct_of_target / 100 >= threshold:
            status = code
            label = text
            break

    above_minimum = bw_ratio >= min_ratio

    return {
        "lift": lift_key,
        "current_bw_ratio": bw_ratio,
        "attia_target_ratio": t_ratio,
        "attia_minimum_ratio": min_ratio,
        "attia_elite_ratio": target["elite_ratio"],
        "centenarian_projection": target["centenarian_projection"],
        "pct_of_target": pct_of_target,
        "gap_to_target_bw_ratio": gap_ratio if gap_ratio > 0 else 0.0,
        "gap_pct_of_target": gap_pct_of_target if gap_pct_of_target > 0 else 0.0,
        "status": status,
        "status_label": label,
        "above_minimum": above_minimum,
        "description": target["description"],
    }


def classify_standard(lift_key: str, bw_ratio: float) -> tuple[str, str | None, float | None]:
    """Return (level, next_level, ratio_needed_for_next)."""
    stds = _STRENGTH_STANDARDS[lift_key]
    current = "Untrained"
    for lvl in _STANDARD_LEVELS:
        if bw_ratio >= stds[lvl]:
            current = lvl
    idx = _STANDARD_LEVELS.index(current)
    if idx < len(_STANDARD_LEVELS) - 1:
        next_lvl = _STANDARD_LEVELS[idx + 1]
        next_ratio = stds[next_lvl]
    else:
        next_lvl = None
        next_ratio = None
    return current, next_lvl, next_ratio
