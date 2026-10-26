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

Pure: no clock; the one read is the movement catalog behind `logging_conventions.load_convention_for` (#5373 — local
`config/`, else its S3 twin; cached, fail-soft). Input workouts are `mcp.strength_helpers.normalize_hevy_items` shape.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from common.pacific_time import parse_day_key

from training.legacy_workouts import day_workouts  # #4636: the ONE reader of the retired per-day shape
from training.logging_conventions import AS_LOGGED, load_convention_for, total_load  # #5373: per-hand vs total-carried load
from training.template_muscle_overrides import muscle_override_for

#: The stated fraction a named secondary muscle is credited per working set. 0.5 is the
#: conventional fractional-set count for a synergist (a bench-press set is a full chest set
#: and half a triceps set). Population-derived; it applies ONLY where a row names a secondary.
SECONDARY_FRACTION = 0.5

#: Set types that are NOT working sets. Hevy's set types are normal / warmup / failure /
#: dropset; a failure set and a drop set are both hard sets, a warm-up is not.
NON_WORKING_SET_TYPES = frozenset({"warmup", "warm_up", "warm-up"})

#: What `volume_lbs` sums (#5373), echoed on every result so no reader takes it for the logged per-hand number.
VOLUME_BASIS = (
    "load x reps over working sets, as the TOTAL moved: a per-hand dumbbell load counts both hands (x 2); a carry's load is the "
    "total carried and it has no reps, so it adds nothing (training.logging_conventions)"
)

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

#: #4108 — THE one table from Hevy's own `primary_muscle_group` / `secondary_muscle_groups`
#: enum onto this module's vocabulary. Each row carries two columns of ONE mapping, so there is
#: no second table to drift:
#:   [0] the `MUSCLES` label this module credits (None = no muscle volume: cardio, neck,
#:       full-body, "other", and forearms/adductors, which `MUSCLES` does not carry), and
#:   [1] the planner key the movement catalog's `primary_muscle` / `secondary_muscles` use —
#:       `config/training_landmarks.json`'s `muscles` keys (`quadriceps`, `abs`, …), which is
#:       what `routine_generator._select_movements_for_muscle` matches on. "cardio" is the
#:       curated cardio entries' own value; "other" is never a landmark, so an entry that maps
#:       there is catalogued but never selected by muscle.
#: Every Hevy group in `mcp/tools_hevy_routine._HEVY_MUSCLE_GROUPS` has a row
#: (`tests/test_movement_catalog_4108.py` holds both columns to their vocabularies).
HEVY_MUSCLE_GROUP: dict[str, tuple[str | None, str]] = {
    "chest": ("Chest", "chest"),
    "lats": ("Back", "back"),
    "upper_back": ("Back", "back"),
    "lower_back": ("Back", "back"),
    "traps": ("Back", "back"),  # the taxonomy's own "shrug" row credits Back
    "shoulders": ("Shoulders", "shoulders"),
    "biceps": ("Biceps", "biceps"),
    "triceps": ("Triceps", "triceps"),
    "forearms": (None, "forearms"),
    "quadriceps": ("Quads", "quadriceps"),
    "hamstrings": ("Hamstrings", "hamstrings"),
    "glutes": ("Glutes", "glutes"),
    "abductors": ("Glutes", "glutes"),  # hip abduction is glute medius/minimus — the "hip abduct" row
    "adductors": (None, "other"),
    "calves": ("Calves", "calves"),
    "abdominals": ("Core", "abs"),
    "cardio": (None, "cardio"),
    "neck": (None, "other"),
    "full_body": (None, "other"),
    "other": (None, "other"),
}

#: The `MUSCLES` label -> planner/landmark key (`quadriceps`, `abs`, ...), DERIVED from `HEVY_MUSCLE_GROUP` (no second table).
#: A label several Hevy groups credit ("Back") takes the first group's key. #5073: the may-tracker keys `by_muscle` by
#: label while `volume_floors.BAND_MEMBERS` reads landmark keys; this is the one bridge between the two vocabularies.
LABEL_TO_LANDMARK_KEY: dict[str, str] = {}
for _label, _key in HEVY_MUSCLE_GROUP.values():
    if _label:
        LABEL_TO_LANDMARK_KEY.setdefault(_label, _key)

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


#: #4095: moved here from `mcp/strength_helpers.py` (which re-exports it for backward
#: compatibility) so `lambdas/web/site_api_training.py` can normalize raw Hevy DDB items
#: without importing `mcp/` — the site-api bundle only stages `lambdas/` + `config/`
#: (`deploy/build_bundle.py::stage_tree`); `mcp/` is staged ONLY into the MCP bundle
#: (`stage_mcp`). `working_sets_by_muscle` below consumes exactly this shape.
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

    def _set(s: dict, carry: bool = False) -> dict:
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
        # #5372: a distance or timed set kept its distance and time on the wire and lost both here — the coach packet's session rows
        # (this normalizer's reader) showed the farmers walk as `reps 0` with nothing else, and the chat reported no distance.
        # Additive, only when present. On a carry the distance field is his STEP COUNT (owner, 2026-10-25), so it is named
        # `steps` there and never `distance_m`: the reader must not call a step count metres.
        dist = s.get("distance_m") if s.get("distance_m") is not None else s.get("distance_meters")
        if dist not in (None, "", 0):
            out["steps" if carry else "distance_m"] = float(dist)
        dur = s.get("duration_sec") if s.get("duration_sec") is not None else s.get("duration_seconds")
        if dur not in (None, "", 0):
            out["duration_sec"] = float(dur)
        return out

    def _exercise(ex: dict) -> dict:
        from training.carry_line import carry_line

        name = ex.get("name") or ex.get("exercise_name") or ""
        tid = ex.get("template_id")
        line = carry_line(name, ex.get("sets"), template_id=tid)  # #5372: a carry's own line — load and steps, outside the rep tonnage
        # #5373: how the load was logged — `per_hand` (one dumbbell of two) or `total_carried` (a carry's sum) — so a reader
        # never reads a per-hand 50 as a 50-lb total; absent when the logged load is the whole load (`as_logged`)
        convention = load_convention_for(name, tid, ex.get("sets"))
        return {
            **({"carry": line} if line else {}),
            **({"load_convention": convention} if convention != AS_LOGGED else {}),
            "name": name,
            # #3766: the stable Hevy template id and the freeform note, both additive. The
            # id is what lets a caller ask by template rather than by a fuzzy name; the note
            # is the raw text the derived signal layer is built FROM, and stays sovereign.
            "template_id": str(ex.get("template_id") or ""),
            "notes": (ex.get("notes") or "").strip(),
            "sets": [_set(s, carry=bool(line)) for s in (ex.get("sets") or [])],
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
        for w in day_workouts(item):
            out.append(
                {
                    "date": date_str,
                    "workout_name": w.get("name") or w.get("workout_name") or "",
                    "exercises": [_exercise(ex) for ex in (w.get("exercises") or [])],
                }
            )
    return out


def session_tonnage_lbs(workout: dict[str, Any]) -> float:
    """One normalised session's tonnage — every logged set's load x reps, in lb — as the TOTAL moved (#5373): a per-hand
    dumbbell load counts both hands (the exercise's `load_convention` from `normalize_hevy_items`); a carry has no reps, so 0."""
    return sum(
        total_load(s.get("weight_lbs"), ex.get("load_convention") or AS_LOGGED) * int(s.get("reps") or 0)
        for ex in workout.get("exercises") or []
        for s in ex.get("sets") or []
    )


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
        `volume_lbs` is PRIMARY-attributed tonnage only, so it is never double-counted. It is the TOTAL load moved
        (#5373): a per-hand dumbbell load counts both hands (`logging_conventions.total_load`).
      pattern_sets, warmup_sets_excluded, working_sets_counted, dates_counted,
      non_resistance (names excluded by design), unattributed (names this taxonomy does not know),
      exercise_sets (#5164: the counted working sets per logged exercise — name + template id).
    """
    muscles: dict[str, dict[str, float]] = {}
    pattern_sets: dict[str, int] = {}
    warmups = 0
    counted = 0
    dates: set[str] = set()
    non_resistance: dict[str, int] = {}
    unattributed: dict[tuple[str, str], int] = {}
    exercise_sets: dict[tuple[str, str], int] = {}

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
            ex_key = (ex.get("name") or "", str(ex.get("template_id") or ""))
            exercise_sets[ex_key] = exercise_sets.get(ex_key, 0) + n
            primary = _row(attr["primary"])
            primary["direct_sets"] += n
            # #5373: tonnage is a TOTAL — a per-hand dumbbell load counts both hands (x 2), a carry's total as logged (it has no
            # reps, so it adds 0 here by construction)
            convention = load_convention_for(ex.get("name") or "", ex.get("template_id"), sets)
            primary["volume_lbs"] += sum(total_load(s.get("weight_lbs"), convention) * int(s.get("reps") or 0) for s in working)
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
        "volume_basis": VOLUME_BASIS,
        # #5164: the same working sets, per logged exercise — what a movement-counted floor (side/rear delts) is summed
        # from (`volume_floors.logged_movement_sets`), so pressing cannot stand in for lateral/rear-delt work. Not a
        # second count: each entry is this loop's own `n`, keyed by exercise instead of credited to a muscle.
        "exercise_sets": [{"name": k[0], "template_id": k[1] or None, "working_sets": v} for k, v in sorted(exercise_sets.items())],
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
