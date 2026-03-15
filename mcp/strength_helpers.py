"""
Strength training helpers: exercise classification, 1RM estimation, volume tracking.
"""

from mcp.config import logger


_EXERCISE_MUSCLE_MAP = [
    # (keywords, muscle_groups, movement_pattern)
    (["bench press", "chest press", "pec deck", "fly", "flye", "push up", "pushup"],
     ["Chest", "Triceps", "Shoulders"], "Push"),
    (["overhead press", "ohp", "shoulder press", "military press", "dumbbell press", "arnold"],
     ["Shoulders", "Triceps"], "Push"),
    (["tricep", "triceps", "skull crusher", "pushdown", "push down", "close grip", "dip"],
     ["Triceps", "Chest"], "Push"),
    (["pull up", "pullup", "chin up", "chinup", "lat pulldown", "pull-up", "pull-down"],
     ["Back", "Biceps"], "Pull"),
    (["row", "rowing", "cable row", "t-bar", "seated row"],
     ["Back", "Biceps"], "Pull"),
    (["deadlift"],
     ["Back", "Hamstrings", "Glutes", "Quads"], "Pull"),
    (["back extension", "hyperextension", "good morning"],
     ["Back", "Hamstrings", "Glutes"], "Pull"),
    (["bicep", "biceps", "curl", "hammer curl"],
     ["Biceps"], "Pull"),
    (["squat", "goblet"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["leg press"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["lunge", "step up", "bulgarian"],
     ["Quads", "Glutes", "Hamstrings"], "Legs"),
    (["leg extension", "leg curl", "hamstring curl", "nordic"],
     ["Quads", "Hamstrings"], "Legs"),
    (["hip thrust", "glute bridge", "hip abduct", "hip adduct"],
     ["Glutes", "Hamstrings"], "Legs"),
    (["calf", "calves", "standing calf", "seated calf"],
     ["Calves"], "Legs"),
    (["plank", "crunch", "ab ", "abs ", "core", "oblique", "sit up", "situp", "hanging leg", "windshield"],
     ["Core"], "Core"),
]

_BODYWEIGHT_EXERCISES = [
    "pull up", "pullup", "pull-up", "chin up", "chinup", "chin-up",
    "dip", "push up", "pushup", "push-up", "bodyweight squat",
]


def classify_exercise(name: str) -> dict:
    """Return {muscle_groups, movement_pattern} for an exercise name."""
    nl = name.lower()
    for keywords, muscles, pattern in _EXERCISE_MUSCLE_MAP:
        if any(kw in nl for kw in keywords):
            return {"muscle_groups": muscles, "movement_pattern": pattern}
    return {"muscle_groups": ["Other"], "movement_pattern": "Other"}


def is_bodyweight(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in _BODYWEIGHT_EXERCISES)


def estimate_1rm(weight: float, reps: int) -> float | None:
    """Epley formula. Valid for reps 1-10."""
    if weight <= 0 or reps < 1 or reps > 10:
        return None
    if reps == 1:
        return round(weight, 1)
    return round(weight * (1 + reps / 30), 1)


def extract_hevy_sessions(hevy_items: list, exercise_name: str, include_warmups: bool = False) -> list:
    """
    Given raw DynamoDB hevy items and a target exercise name (fuzzy),
    return a list of session dicts sorted by date.
    Each session: {date, sets: [{set_type, weight_lbs, reps, estimated_1rm}], best_1rm, best_weight, volume}
    """
    target = exercise_name.lower()
    sessions = []
    for item in hevy_items:
        day_data = item.get("data", {})
        workouts = day_data.get("workouts", [])
        date_str = item.get("date") or item.get("sk", "")[:10]
        for workout in workouts:
            for ex in workout.get("exercises", []):
                ex_name = ex.get("name", "")
                if target not in ex_name.lower():
                    continue
                sets_out = []
                for s in ex.get("sets", []):
                    st = s.get("set_type", "normal")
                    if not include_warmups and st == "warmup":
                        continue
                    w = float(s.get("weight_lbs", 0) or 0)
                    r = int(s.get("reps", 0) or 0)
                    e1rm = None if is_bodyweight(ex_name) else estimate_1rm(w, r)
                    sets_out.append({"set_type": st, "weight_lbs": w, "reps": r, "estimated_1rm": e1rm})
                if not sets_out:
                    continue
                best_1rm = max((s["estimated_1rm"] for s in sets_out if s["estimated_1rm"]), default=None)
                best_weight = max((s["weight_lbs"] for s in sets_out), default=0)
                volume = sum(s["weight_lbs"] * s["reps"] for s in sets_out)
                sessions.append({
                    "date": date_str,
                    "exercise_name": ex_name,
                    "sets": sets_out,
                    "best_1rm": best_1rm,
                    "best_weight": best_weight,
                    "volume_lbs": round(volume, 1),
                    "set_count": len(sets_out),
                })
    sessions.sort(key=lambda x: x["date"])
    return sessions



_VOLUME_LANDMARKS = {
    "Chest":       {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Back":        {"MV": 6,  "MEV": 10, "MAV_lo": 14, "MAV_hi": 20, "MRV": 25},
    "Shoulders":   {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 20, "MRV": 25},
    "Quads":       {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Hamstrings":  {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Glutes":      {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Biceps":      {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Triceps":     {"MV": 2,  "MEV": 6,  "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Calves":      {"MV": 4,  "MEV": 8,  "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Core":        {"MV": 0,  "MEV": 4,  "MAV_lo": 6,  "MAV_hi": 16, "MRV": 25},
    "Other":       {"MV": 0,  "MEV": 0,  "MAV_lo": 0,  "MAV_hi": 0,  "MRV": 99},
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
    "bench press":     {"Untrained": 0.50, "Novice": 0.75, "Intermediate": 1.00, "Advanced": 1.50, "Elite": 2.00},
    "squat":           {"Untrained": 0.75, "Novice": 1.00, "Intermediate": 1.50, "Advanced": 2.00, "Elite": 2.75},
    "deadlift":        {"Untrained": 1.00, "Novice": 1.25, "Intermediate": 1.75, "Advanced": 2.50, "Elite": 3.25},
    "overhead press":  {"Untrained": 0.35, "Novice": 0.50, "Intermediate": 0.75, "Advanced": 1.00, "Elite": 1.50},
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
        "target_ratio": 2.0,      # goal: 2× BW 1RM now to have 1× BW at ~85
        "minimum_ratio": 1.5,    # minimum acceptable for longevity protection
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
    (1.10, "exceeds_target",  "Exceeds Attia target"),
    (1.00, "at_target",       "At Attia target"),
    (0.85, "approaching",     "Approaching target (within 15%)"),
    (0.65, "progressing",     "Progressing — solid base"),
    (0.00, "below_minimum",   "Below minimum threshold"),
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

    t_ratio  = target["target_ratio"]
    min_ratio = target["minimum_ratio"]
    pct_of_target = round(bw_ratio / t_ratio * 100, 1)
    gap_ratio = round(t_ratio - bw_ratio, 3)
    gap_pct_of_target = round(gap_ratio / t_ratio * 100, 1)

    status = "below_minimum"
    label  = "Below minimum threshold"
    for threshold, code, text in _ATTIA_STATUS_TIERS:
        if pct_of_target / 100 >= threshold:
            status = code
            label  = text
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
