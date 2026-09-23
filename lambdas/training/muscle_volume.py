"""muscle_volume.py — THE per-muscle working-set computation (#4071).

WHY THIS EXISTS

`get_muscle_volume` fed the planner (`plan_next_session`) and the owner's `volume_ceiling`
redline with numbers that were wrong four independent ways, each measured read-only against
the live Hevy partition for 2026-09-15..09-21:

1. **Over-attribution.** Every set counted as a FULL set for every muscle in a keyword row:
   one Romanian Deadlift set was one Back + one Hamstrings + one Glutes + one Quads set; one
   Leg Extension set was one Quads + one Hamstrings set. That is how Quads and Hamstrings came
   out IDENTICAL (10 and 10) on a week whose direct hamstring work was 4 RDL + 3 leg-curl sets.
2. **Warm-ups counted.** The live per-workout rows carry the set type as `type`
   (`{'normal': 599, 'warmup': 23, 'dropset': 1}` over 2026-05-26..09-22); the normalizer read
   `set_type`, found nothing, and defaulted every set to "normal". The `!= "warmup"` filter
   downstream never had a warm-up to drop.
3. **Keyword collisions.** "Seated Leg Curl" hit the biceps row ("curl") before the leg-curl
   row; "Lat Pulldown - Close Grip" hit the triceps row ("close grip"); "Rear Delt Reverse Fly"
   hit the chest row ("fly"); Face Pulls and Lateral Raises matched nothing at all.
4. **A window one day short.** `(end - start).days` over an INCLUSIVE `[start, end]` read:
   09-15..09-21 is seven calendar days and was divided by 6/7 = 0.857 weeks.

WHAT THIS MODULE IS

* `EXERCISE_TAXONOMY` — one ordered table. Each row names ONE primary muscle and, only where it
  says so, secondary muscles at a stated fraction (`SECONDARY_FRACTION`). A set credits its
  primary with 1.0 and each named secondary with its fraction; nothing else.
* `attribute_exercise` — name/template-id -> that row (the #3770 id-keyed override still wins).
* `is_working_set` — the set-type rule (warm-ups out; normal / failure / dropset in).
* `working_sets_by_muscle` — the ONE per-muscle computation. `mcp/tools_strength.py::
  tool_get_muscle_volume` calls it; `plan_next_session` reads that tool; the `volume_ceiling`
  redline reads the planner's `muscle_volume` block. `tests/test_muscle_volume_working_sets_4071.py`
  holds an AST derivation guard that no second per-muscle set computation exists in `mcp/` or
  `lambdas/training/`.
* `window_days` / `window_weeks` — whole-day, inclusive window arithmetic (7 days = 1.0 week).

Pure: no AWS, no clock. Input workouts are `mcp.strength_helpers.normalize_hevy_items` shape.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from common.pacific_time import parse_day_key

from training.template_muscle_overrides import muscle_override_for

#: The stated fraction a named secondary muscle is credited per working set. 0.5 is the
#: conventional fractional-set count for a synergist (a bench-press set is a full chest set
#: and half a triceps set). Population-derived; it applies ONLY where a row names a secondary.
SECONDARY_FRACTION = 0.5

#: Set types that are NOT working sets. Hevy's set types are normal / warmup / failure /
#: dropset; a failure set and a drop set are both hard sets, a warm-up is not.
NON_WORKING_SET_TYPES = frozenset({"warmup", "warm_up", "warm-up"})

#: The muscle vocabulary (matches `_VOLUME_LANDMARKS` in mcp/strength_helpers.py and the
#: `template_muscle_overrides` labels).
MUSCLES = ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Quads", "Hamstrings", "Glutes", "Calves", "Core")

#: Movement-pattern label for an id-override muscle (#3770 carries a muscle, not a pattern).
MUSCLE_TO_PATTERN = {
    "Chest": "Push",
    "Shoulders": "Push",
    "Triceps": "Push",
    "Back": "Pull",
    "Biceps": "Pull",
    "Quads": "Legs",
    "Glutes": "Legs",
    "Hamstrings": "Legs",
    "Calves": "Legs",
    "Core": "Core",
}

_HALF = SECONDARY_FRACTION

#: (keywords, primary, {secondary: fraction}, movement_pattern) — FIRST MATCH WINS, so the
#: specific rows sit above the generic ones they would otherwise lose to ("leg curl" above
#: "curl", "calf" above "leg press", "lat pulldown" above "close grip", "rear delt"/"face pull"
#: above "fly"). `primary=None` is a non-resistance row: cardio and mobility carry no muscle
#: volume and are reported as excluded, never silently folded into "Other".
EXERCISE_TAXONOMY: list[tuple[list[str], str | None, dict[str, float], str]] = [
    # ── non-resistance: no muscle volume ────────────────────────────────────────────────
    (
        ["cycling", "treadmill", "elliptical", "rowing machine", "stretch", "running", "stair", "yoga", "foam roll", "bike"],
        None,
        {},
        "Cardio/Mobility",
    ),
    # ── lower body, most specific first ────────────────────────────────────────────────
    (["calf", "calves"], "Calves", {}, "Legs"),
    (["leg curl", "hamstring curl", "nordic"], "Hamstrings", {}, "Legs"),
    (["leg extension"], "Quads", {}, "Legs"),
    (["romanian", "rdl", "stiff leg", "stiff-leg", "good morning"], "Hamstrings", {"Glutes": _HALF}, "Legs"),
    (["back extension", "hyperextension"], "Hamstrings", {"Glutes": _HALF}, "Pull"),
    (["deadlift"], "Glutes", {"Hamstrings": _HALF, "Back": _HALF}, "Pull"),
    (["kettlebell swing"], "Glutes", {"Hamstrings": _HALF}, "Legs"),
    (
        ["squat", "goblet", "leg press", "hack", "lunge", "step up", "step-up", "bulgarian"],
        "Quads",
        {"Glutes": _HALF},
        "Legs",
    ),
    # ── triceps above anything a triceps name also contains ("kickback", "extension") ──
    (["tricep", "skull crusher", "skullcrusher", "pushdown", "push down"], "Triceps", {}, "Push"),
    (["close grip bench", "close-grip bench", "dip"], "Triceps", {"Chest": _HALF}, "Push"),
    (["hip thrust", "glute", "rear kick", "kickback", "hip abduct"], "Glutes", {}, "Legs"),
    # ── upper-body pulls ────────────────────────────────────────────────────────────────
    (["face pull", "rear delt", "reverse fly", "high pull", "upright row"], "Shoulders", {}, "Pull"),
    (["straight arm", "straight-arm", "pullover"], "Back", {}, "Pull"),
    (
        ["pulldown", "pull-down", "pull down", "pull up", "pullup", "pull-up", "chin up", "chinup", "chin-up"],
        "Back",
        {"Biceps": _HALF},
        "Pull",
    ),
    (["row", "t-bar"], "Back", {"Biceps": _HALF}, "Pull"),
    (["shrug"], "Back", {}, "Pull"),
    (["leg raise", "knee raise"], "Core", {}, "Core"),
    (["bicep", "curl"], "Biceps", {}, "Pull"),
    # ── shoulders ──────────────────────────────────────────────────────────────────────
    (["lateral raise", "front raise", "side raise", "lateral"], "Shoulders", {}, "Push"),
    (
        ["overhead press", "ohp", "shoulder press", "military press", "dumbbell press", "arnold", "landmine press"],
        "Shoulders",
        {"Triceps": _HALF},
        "Push",
    ),
    # ── chest ──────────────────────────────────────────────────────────────────────────
    (["pec deck", "fly", "flye", "butterfly", "crossover"], "Chest", {}, "Push"),
    (["bench press", "chest press", "push up", "pushup", "push-up"], "Chest", {"Triceps": _HALF}, "Push"),
    # ── core: direct flexion/oblique work PLUS anti-rotation and loaded carries (B2b) ──
    (
        [
            "plank",
            "crunch",
            "ab ",
            "abs ",
            "core",
            "oblique",
            "sit up",
            "situp",
            "hanging leg",
            "windshield",
            "russian twist",
            "hollow",
            "rollout",
            "ab wheel",
            "pallof",
            "anti-rotation",
            "anti rotation",
            "dead bug",
            "deadbug",
            "bird dog",
            "carry",
            "carries",
            "farmer",
            "suitcase",
            "woodchop",
            "wood chop",
            "side bend",
        ],
        "Core",
        {},
        "Core",
    ),
    # Walking sits LAST among the non-resistance names so "Farmers Walk" (a carry) is Core above.
    (["walking", "walk"], None, {}, "Cardio/Mobility"),
]


def _matches(keyword: str, name_lower: str) -> bool:
    """A keyword matches at the START of a word, never mid-word — "row" is in "Dumbbell Row"
    but not in "Narrow Grip Bench Press" or "Medicine Ball Throw"."""
    return re.search(r"(?<![a-z])" + re.escape(keyword), name_lower) is not None


def attribute_exercise(name: str, template_id: str | None = None) -> dict[str, Any]:
    """One exercise -> `{primary, secondary: {muscle: fraction}, movement_pattern, matched}`.

    `primary` is None for a non-resistance movement (cardio/mobility) AND for a name no row
    matches; `matched` tells the two apart (`"non_resistance"` / `"unattributed"`), because
    "no muscle volume by design" and "this taxonomy does not know the movement" are different
    facts and only the second is a gap.

    #3770: a template id with an id-keyed override wins over any name match.
    """
    override = muscle_override_for(template_id)
    if override:
        return {"primary": override, "secondary": {}, "movement_pattern": MUSCLE_TO_PATTERN.get(override, "Other"), "matched": "override"}
    nl = (name or "").lower()
    for keywords, primary, secondary, pattern in EXERCISE_TAXONOMY:
        if any(_matches(kw, nl) for kw in keywords):
            return {
                "primary": primary,
                "secondary": dict(secondary),
                "movement_pattern": pattern if primary else "Other",
                "matched": "taxonomy" if primary else "non_resistance",
            }
    return {"primary": None, "secondary": {}, "movement_pattern": "Other", "matched": "unattributed"}


def is_working_set(s: dict[str, Any]) -> bool:
    """A set is a working set unless its type is a warm-up. Reads the normalized `set_type`."""
    return str(s.get("set_type") or "normal").strip().lower() not in NON_WORKING_SET_TYPES


def window_days(start_date: str, end_date: str) -> int:
    """Calendar days in the INCLUSIVE window [start_date, end_date]. 09-15..09-21 -> 7.

    Raises ValueError on an unparseable or inverted window: a rate with no honest divisor is
    refused, never defaulted.
    """
    s, e = parse_day_key(start_date), parse_day_key(end_date)
    if s is None or e is None:
        raise ValueError(f"window needs two YYYY-MM-DD day keys, got {start_date!r}..{end_date!r}")
    days = (e - s).days + 1
    if days < 1:
        raise ValueError(f"inverted window {start_date}..{end_date}")
    return days


def window_weeks(start_date: str, end_date: str) -> float:
    """Whole days / 7 over the inclusive window — 7 days is exactly 1.0 week, 28 is 4.0."""
    return window_days(start_date, end_date) / 7


def window_start(end_date: str, days: int) -> str:
    """The first day of the inclusive `days`-day window ending on `end_date` (7 -> end - 6)."""
    from common.pacific_time import shift_day_key

    return shift_day_key(end_date, -(days - 1))


def working_sets_by_muscle(
    workouts: Iterable[dict[str, Any]], start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """THE per-muscle working-set count (#4071). Every per-muscle number in mcp/ and
    lambdas/training/ is this function's output — see the derivation guard in
    tests/test_muscle_volume_working_sets_4071.py.

    `workouts` is `normalize_hevy_items` shape. When `start_date`/`end_date` are given, only
    workouts whose day key falls in the inclusive window are counted (so one read can serve a
    28-day and a 7-day window).

    Per working set of an exercise: the row's primary muscle gets 1.0, each secondary it
    NAMES gets its stated fraction. Returns:
      muscles[m] = {direct_sets (int), secondary_sets (float), total_sets (float), volume_lbs}
        `volume_lbs` is PRIMARY-attributed tonnage only, so it is never double-counted.
      pattern_sets, warmup_sets_excluded, working_sets_counted, dates_counted,
      non_resistance (names excluded by design), unattributed (names this taxonomy does not know).
    """
    muscles: dict[str, dict[str, float]] = {}
    pattern_sets: dict[str, int] = {}
    warmups = 0
    counted = 0
    dates: set[str] = set()
    non_resistance: dict[str, int] = {}
    unattributed: dict[tuple[str, str], int] = {}

    def _row(m: str) -> dict[str, float]:
        return muscles.setdefault(m, {"direct_sets": 0, "secondary_sets": 0.0, "volume_lbs": 0.0})

    for workout in workouts:
        day = str(workout.get("date") or "")[:10]
        if start_date and day < start_date:
            continue
        if end_date and day > end_date:
            continue
        for ex in workout.get("exercises") or []:
            sets = ex.get("sets") or []
            working = [s for s in sets if is_working_set(s)]
            warmups += len(sets) - len(working)
            n = len(working)
            if not n:
                continue
            attr = attribute_exercise(ex.get("name") or "", ex.get("template_id"))
            if attr["primary"] is None:
                if attr["matched"] == "non_resistance":
                    non_resistance[ex.get("name") or ""] = non_resistance.get(ex.get("name") or "", 0) + n
                else:
                    key = (ex.get("name") or "", str(ex.get("template_id") or ""))
                    unattributed[key] = unattributed.get(key, 0) + n
                continue
            if day:
                dates.add(day)
            counted += n
            primary = _row(attr["primary"])
            primary["direct_sets"] += n
            primary["volume_lbs"] += sum(float(s.get("weight_lbs") or 0) * int(s.get("reps") or 0) for s in working)
            for m, frac in attr["secondary"].items():
                _row(m)["secondary_sets"] += n * frac
            pattern_sets[attr["movement_pattern"]] = pattern_sets.get(attr["movement_pattern"], 0) + n

    out_muscles = {}
    for m in sorted(muscles):
        r = muscles[m]
        out_muscles[m] = {
            "direct_sets": int(r["direct_sets"]),
            "secondary_sets": round(r["secondary_sets"], 2),
            "total_sets": round(r["direct_sets"] + r["secondary_sets"], 2),
            "volume_lbs": round(r["volume_lbs"], 0),
        }
    return {
        "muscles": out_muscles,
        "pattern_sets": pattern_sets,
        "warmup_sets_excluded": warmups,
        "working_sets_counted": counted,
        "dates_counted": sorted(dates),
        "non_resistance": [{"name": k, "sets": v} for k, v in sorted(non_resistance.items())],
        "unattributed": [{"name": k[0], "template_id": k[1] or None, "working_sets": v} for k, v in sorted(unattributed.items())],
    }


METHOD = {
    "unit": "working sets (warm-ups excluded by the Hevy set type)",
    "attribution": (
        f"one primary muscle per set (1.0); a secondary only where the taxonomy names it, at {SECONDARY_FRACTION} per set; "
        "total_sets = direct_sets + secondary_sets"
    ),
    "window": "inclusive whole days; sets_per_week = total_sets / (days / 7) — 7 days is 1.0 week",
    "source": "lambdas/training/muscle_volume.py::working_sets_by_muscle (#4071) — the one per-muscle computation",
}
