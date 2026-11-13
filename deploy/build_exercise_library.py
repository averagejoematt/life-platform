#!/usr/bin/env python3
"""build_exercise_library.py — build `config/exercise_library.json` from the full Hevy history + curation (#5769).

WHAT IT READS (all read-only)

  1. Every per-workout Hevy row (`pk=USER#matthew#SOURCE#hevy`), all years and phases, through
     `build_movement_catalog.fetch_workout_rows` — the one paged Query the catalog builder already
     uses. EXCLUDED, the way the existing readers exclude them: the legacy daily aggregates
     (`tombstoned_reason=legacy_daily_aggregate_superseded_by_per_workout`, skipped by
     `build_movement_catalog.summarize_history` and `exercise_history.load_history_indexes`), every
     non-`DATE#…#WORKOUT#` key, and any workout whose id still has an unconsumed
     `DELETE#WORKOUT#<id>` marker (`hevy_common.resolve_tombstones` deletes the record once it
     consumes the marker; until then the marker is the tombstone).
  2. `config/movement_catalog.json` — Hevy's own metadata per logged template (muscles, equipment,
     type, skill tier), already fetched read-only by the catalog builder.
  3. `deploy/exercise_library_curation.py` — the hand-authored half (vocabulary, verified
     citations, gates, per-template overrides, expansion candidates).
  4. `deploy/exercise_library_reviews.json` — the accepted evidence-review ledger (#5778): citations,
     evidence changes and candidates the owner merged from `scripts/library_evidence_review.py`, re-applied
     on top of the curation so a rebuild keeps them.

WHAT IT WRITES

The PUBLIC library only: per movement its template id, first/last date and exposure count
(distinct workouts), and the attribute set. Never a load, a bodyweight or a word of his notes —
those go to the owner-private overlay (`deploy/write_exercise_library_overlay.py`). Every movement
is keyed by RAW template id — the alias registry is not folded here, so an alias id (B5EFBF9C,
Overhead Triceps Extension (Cable)) stays its own movement and records `alias_of`.

Attributes a rule cannot know are `unknown` and each hypertrophy row's evidence is `none_reviewed`, unless the
curation module says otherwise. Each row's QUALITY tier (S-D) is derived last, by the written rubric
(`training.quality_rubric`, #5857) from the final attributes, moved at most one band by a recorded direct-trial
adjustment — never authored. `version`, `change_log` and `status` are preserved from the file
on disk, so an owner approval is never overwritten by a rebuild.

    python3 deploy/build_exercise_library.py                       # dry-run summary, writes nothing
    python3 deploy/build_exercise_library.py --write               # overwrite config/exercise_library.json
    python3 deploy/build_exercise_library.py --save-inputs F       # snapshot the history summary
    python3 deploy/build_exercise_library.py --inputs F --write    # rebuild offline
    ... --template-index F   # check every expansion template id against a copy of Hevy's template index
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any, Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO_ROOT, "lambdas"), REPO_ROOT, os.path.dirname(os.path.abspath(__file__))]

import exercise_library_curation as cur  # noqa: E402
import exercise_library_input_review as input_review  # noqa: E402
import exercise_library_objectives as objectives  # noqa: E402
import exercise_library_reviews as reviews  # noqa: E402
import exercise_library_targets as targets  # noqa: E402
from exercise_library_changelog import BUILDER_CHANGE_LOG  # noqa: E402
from training import (
    exercise_library as lib_rules,  # noqa: E402
    quality_rubric,  # noqa: E402
)

LIBRARY_PATH = os.path.join(REPO_ROOT, "config", "exercise_library.json")
CATALOG_PATH = os.path.join(REPO_ROOT, "config", "movement_catalog.json")
ALIASES_PATH = os.path.join(REPO_ROOT, "config", "hevy_template_aliases.json")
GENERATED_BY = "deploy/build_exercise_library.py"
LEGACY_TOMBSTONE = "legacy_daily_aggregate_superseded_by_per_workout"
_WORKOUT_SK = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})#WORKOUT#(.+)$")
_DELETE_SK = re.compile(r"^DELETE#WORKOUT#(.+)$")

INITIAL_HEADER = {
    "version": "0.1.0",
    "status": "proposed",
    "change_log": [
        {
            "version": "0.1.0",
            "date": "2026-11-11",
            "by": "#5769 (owner spec 2026-11-11)",
            "what": "First library: every Hevy template he has logged (full history, tombstones excluded), expansion candidates, "
            "attributes, verified-citation hypertrophy tiers, gates defined (evaluated in #5772), gym inventory unconfirmed.",
            "rule": "proposed until the owner approves; any change after approval needs an owner ruling — bump `version`, add a line",
        }
    ],
}

# Change-log lines the BUILDER owns: deploy/exercise_library_changelog.py (#5861 FIX4: extracted on the module-size seam).

# #5861 FIX2-DATA: the programming lane's library-carried settings (`training.live_program.SETTINGS_DEFAULTS` reads them).
# OWNER DECISIONS PENDING — these are the defaults, written once; a value on disk (an owner's ruling) is kept by every rebuild.
PROGRAMMING_SETTINGS_DEFAULTS: dict[str, Any] = {
    "session_cap_includes_cardio": False,
    "symptom_line": "Chest, breathing, dizzy? Stop, log it.",
    "short_week_rule": "skip_shoulders_arms",
    "behind_schedule_week": False,
}
# #5861 FIX6: THE OWNER'S RULINGS of 2026-11-13 on the decision register (configuration, NOT activation — `status` stays
# `proposed`). Written over any earlier on-disk default by every rebuild: a ruling lives here, in the generator, and a later
# ruling edits this dict. Each key is read only under `selection_engine.mode() == "live"` (`training.live_program.settings`,
# whose code defaults equal these — tests/test_owner_rulings_5861.py holds the two to each other).
OWNER_RULED_SETTINGS: dict[str, Any] = {
    "session_cap_includes_cardio": True,  # ruling 1: lifting + gym cardio share the 75-min cap
    "adherence_response": "short_week",  # ruling 2: a 4-session week after missed sessions, no make-up sets
    "short_week_rule": "skip_shoulders_arms",  # ruling 3: the 4-day week drops shoulders+arms (arms/shoulders held at MEV)
    "cardio_purpose_only": True,  # ruling 4: a gym cardio block only for a named purpose (the week's conditioning dose)
    "heavy_day_deadlift_shape": "top_plus_backoff",  # ruling 5: top set + one back-off
    "lead_lift_rule": "alternate_weekly",  # ruling 5: one of squat / deadlift leads the heavy day, the other a band lower
    "press_sets": 3,  # ruling 6: overhead press 2-3 weekly working sets, from redundant lateral-delt sets
    "kb_slot_under_strain": "drop",  # ruling 7: no KB hinge on a strained week, no make-up
    "priority_muscles": ["chest", "quadriceps"],  # ruling 9
    "priority_add_rule": "stimulus_and_performance",  # ruling 9: an added slot only when stimulus AND performance say so
    "rate_band_mode": "advisory",  # ruling 11: advisory upper reference, never applied
    "rate_ceiling_pct_bw": 1.0,  # ruling 11: ~1 % of current bodyweight a week, the advisory upper planning reference
    "symptom_line": "",  # ruling 10 (follow-up): no symptom warning line on any session
    "symptom_line_on_lifting_days": False,  # ruling 10
    "hard_conditioning_doses": 1,  # owner ruling 2026-11-13 (FIX7 follow-up): one hard conditioning dose a week; kept a setting
    "abs_direct_sets_per_week": 4,  # owner ruling #8 (fix round 8): ~4 challenging DIRECT ab sets a week, spread; indirect never
}
"""#5861 FIX7 also records the owner's 2026-11-13 clarification of ruling 17 (no setting: the rubric itself, quality_rubric 3.5.0):
glute stretch credit only for genuinely lengthened loading, the same standard as every muscle — short-range glute lifts (kickbacks,
hip thrust variants) earn no stretch credit (`quality_rubric.STRETCH_CAPS` empty)."""


def with_builder_changes(head: dict[str, Any]) -> dict[str, Any]:
    """The header with every builder-owned change-log line present once (a line with the builder's version AND `by` is the
    builder's own, so it is rewritten to the current text; any other line is never touched) and `version` at the highest."""
    own = {(x["version"], x["by"]): x for x in BUILDER_CHANGE_LOG}
    log = [dict(own.get((str(x.get("version")), str(x.get("by"))), x)) for x in head.get("change_log") or []]
    have = {str(x.get("version")) for x in log}
    log += [dict(x) for x in BUILDER_CHANGE_LOG if x["version"] not in have]

    def _v(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in str(v).split("."))

    top = max([str(head.get("version") or "0.0.0")] + [str(x["version"]) for x in log], key=_v)
    return head | {"change_log": log, "version": top}


# ── history ──────────────────────────────────────────────────────────────────────────────────────────────────────


def summarize_history(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pure. Hevy partition rows -> per RAW template id {exposures, first_done, last_done, names}."""
    rows = list(rows)
    deleted = {m.group(1) for r in rows if (m := _DELETE_SK.match(str(r.get("sk") or "")))}
    templates: dict[str, dict[str, Any]] = {}
    days: list[str] = []
    skipped = Counter()
    untagged = 0
    for r in rows:
        sk = str(r.get("sk") or "")
        m = _WORKOUT_SK.match(sk)
        if not m:
            skipped["non_workout_key"] += 1
            continue
        if r.get("tombstoned_reason") == LEGACY_TOMBSTONE:
            skipped["legacy_aggregate"] += 1
            continue
        if m.group(2) in deleted or str(r.get("source_workout_id") or "") in deleted:
            skipped["delete_marker"] += 1
            continue
        day = m.group(1)
        days.append(day)
        seen: set[str] = set()
        for ex in r.get("exercises") or []:
            tid = str(ex.get("template_id") or "").strip().upper()
            if not tid:
                untagged += 1
                continue
            rec = templates.setdefault(tid, {"exposures": 0, "first_done": day, "last_done": day, "names": Counter()})
            rec["names"][str(ex.get("name") or "").strip()] += 1
            if tid in seen:
                continue
            seen.add(tid)
            rec["exposures"] += 1
            rec["first_done"] = min(rec["first_done"], day)
            rec["last_done"] = max(rec["last_done"], day)
    return {
        "workouts": len(days),
        "first": min(days) if days else None,
        "last": max(days) if days else None,
        "untagged_exercises": untagged,
        "skipped": dict(sorted(skipped.items())),
        "delete_markers": len(deleted),
        "templates": {k: {**v, "names": dict(v["names"])} for k, v in sorted(templates.items())},
    }


# ── derivation rules (each stated where it is applied) ───────────────────────────────────────────────────────────

_REGION = {
    "chest": "upper",
    "back": "upper",
    "shoulders": "upper",
    "triceps": "upper",
    "biceps": "upper",
    "forearms": "upper",
    "quadriceps": "lower",
    "hamstrings": "lower",
    "glutes": "lower",
    "calves": "lower",
    "abs": "core",
    "cardio": "cardio",
}
_CARDIO_RE = re.compile(
    r"\b(treadmill|cycling|bike|elliptical|rowing machine|stair|walking|walk|hiking|swim\w*|jump rope|spinning)\b", re.I
)
_OLY_RE = re.compile(r"\b(clean|snatch|jerk|high pulls?)\b", re.I)
_CARRY_RE = re.compile(r"\b(carry|carries|farmers?|suitcase|sled|prowler|yoke|swing)\b", re.I)
_ANTI_RE = re.compile(r"\b(plank|pallof|dead bug|bird dog|hollow|anti[- ]rotation|side plank|ab wheel|rollout|stir the pot)\b", re.I)
_CORRECTIVE_RE = re.compile(
    r"\b(stretch\w*|mobility|band pull ?aparts?|face pulls?|external rotation|wall slides?|t spine|scap\w*|y raise|w raise|"
    r"angels and devils|leg swings|inchworms?|hip band|tibialis|rotator cuff|ucv|scarecrow|bridge and reach)\b",
    re.I,
)
_ANCHOR_RE = re.compile(r"^(bench press|squat|deadlift|overhead press|front squat|incline bench press) \((barbell|trap bar)\)$", re.I)
_COMPOUND_RE = re.compile(r"\b(squat|deadlift|press|row|lunge|split|step up|thrust|pull ?up|chin ?up|dip|clean|snatch)\b", re.I)

# Ordered: the first matching rule wins. Shortened rules that share a word with a lengthened rule come first.
_LENGTH_RULES: list[tuple[str, str]] = [
    (
        r"reverse fly|rear delt|lateral raise|front raise|upright row|shrug|kickback|spider curl|concentration curl|pushdown|push ?away",
        "shortened",
    ),
    (r"seated calf|hip thrust|glute bridge|crunch|sit up|v up|leg raise|knee raise|face pull|overhead curl", "shortened"),
    (
        r"overhead (?:tricep|triceps) extension|overhead extension|french press|skull ?crusher|incline (?:dumbbell )?curl|incline curl",
        "lengthened",
    ),
    (r"preacher|bayesian|behind the back curl|seated leg curl|romanian|\brdl\b|stiff leg|straight leg deadlift|good morning", "lengthened"),
    (r"deficit|split squat|bulgarian|lunge|cossack|\bfly\b|flyes?|crossover|pullover|standing calf|sissy|nordic", "lengthened"),
    (r"pec deck|butterfly", "lengthened"),  # #5857: the pec deck is a fly (it read `unknown` before)
    (r"hyperextension|back extension|pull ?up|chin ?up|pulldown|\bdips?\b|jefferson|zercher|goblet|front squat|\bsquat\b", "lengthened"),
    (r"bench press|chest press|shoulder press|overhead press|military press|\brow\b|rows\b|leg press|leg extension|curl\b|deadlift", "mid"),
    (r"push ?ups?|pushups?|step ?ups?|stepup", "mid"),  # #5861: a push-up is a press; a step-up a knee-dominant squat (mid)
]


def _length_bias(title: str, family: str) -> str:
    if family in ("carry_conditioning", "core_anti_movement", "corrective", "skill_athletic") and not re.search(r"swing", title, re.I):
        return "not_applicable"
    for pat, val in _LENGTH_RULES:
        if re.search(pat, title, re.I):
            return val
    return "unknown"


_NOT_CARDIO_RE = re.compile(r"lunge|squat|hip circles?|carry|carries|farmers", re.I)


def _is_cardio(title: str) -> bool:
    """A cardio word, unless the title is a strength movement that happens to say "walking" (#5861: the walking lunge)."""
    return bool(_CARDIO_RE.search(title)) and not _NOT_CARDIO_RE.search(title)


def _family(title: str, meta: dict[str, Any]) -> str:
    if (meta.get("primary_muscle") == "cardio") or _is_cardio(title):
        return "carry_conditioning"
    if lib_rules.requires_impact_gate({"title": title}) or _OLY_RE.search(title) or re.search(r"\b(slams?|throws?|toss)\b", title, re.I):
        return "skill_athletic"
    if _CARRY_RE.search(title):
        return "carry_conditioning"
    if _ANTI_RE.search(title):
        return "core_anti_movement"
    if _CORRECTIVE_RE.search(title):
        return "corrective"
    if _ANCHOR_RE.match(title.strip()):
        return "strength_anchor"
    return "hypertrophy"


def _equipment(title: str, hevy_eq: str | None, family: str) -> list[str]:
    t = title.lower()
    out: list[str] = []

    def add(*ids: str) -> None:
        for i in ids:
            if i not in out:
                out.append(i)

    if family == "carry_conditioning" and _is_cardio(title):
        for pat, eid in (
            (r"treadmill", "treadmill"),
            (r"cycling|bike|spinning", "stationary_bike"),
            (r"elliptical", "elliptical"),
            (r"rowing", "rower"),
            (r"stair", "stair_climber"),
            (r"jump rope", "jump_rope"),
        ):
            if re.search(pat, t):
                add(eid)
        return out or ["bodyweight"]
    if "smith" in t:
        add("smith_machine")
    if "landmine" in t:
        add("barbell", "landmine")
    if "trap bar" in t:
        add("trap_bar")
    if "ez bar" in t or "ez-bar" in t:
        add("ez_bar")
    if re.search(r"\bsled\b", t) or re.search(r"\bprowler (?:push|pull|drag)\b(?!\s*-?\s*ups?)", t):
        add("sled")
    if "kettlebell" in t or re.search(r"\bkb\b", t) or hevy_eq == "kettlebell":
        add("kettlebell")
    if re.search(r"\bdb\b|dumbbell", t) or hevy_eq == "dumbbell":
        add("dumbbell")
    if hevy_eq == "barbell" and not out:
        add("barbell")
    if "cable" in t or "pulldown" in t or "pushdown" in t or "face pull" in t or "pallof" in t or "crossover" in t:
        add("lat_pulldown_station" if "pulldown" in t and "straight arm" not in t else "cable_stack")
    if hevy_eq == "resistance_band" or re.search(r"\bband(ed)?\b", t):
        add("resistance_band")
    if hevy_eq == "plate":
        add("weight_plate")
    # benches and racks a free-weight lift needs
    if out and set(out) & {"barbell", "dumbbell", "ez_bar", "kettlebell"}:
        if "decline" in t:
            add("bench_decline")
        elif "incline" in t or ("seated" in t and "press" in t):
            add("bench_adjustable")
        elif re.search(
            r"bench press|floor press" if False else r"bench press|skull|lying|chest supported|tripod|\bdumbbell row\b|hip thrust", t
        ):
            add("bench_flat")
        if "preacher" in t:
            add("preacher_bench")
        if "barbell" in out and re.search(r"\bsquat\b|overhead press|military press|bench press", t) and "zercher" not in t:
            add("squat_rack")
    machine_map = (
        (r"leg press|calf press", "leg_press_machine"),
        (r"hack squat", "hack_squat_machine"),
        (r"pendulum", "pendulum_squat_machine"),
        (r"belt squat", "belt_squat_machine"),
        (r"leg extension", "leg_extension_machine"),
        (r"seated leg curl", "leg_curl_seated"),
        (r"lying leg curl|prone leg curl", "leg_curl_lying"),
        (r"standing calf raise", "calf_raise_standing_machine"),
        (r"seated calf", "calf_raise_seated_machine"),
        (r"hip thrust", "hip_thrust_machine"),
        (r"kickback|rear kick", "glute_kickback_machine"),
        (r"abduction", "hip_abduction_machine"),
        (r"adduction", "hip_adduction_machine"),
        (r"incline chest press", "incline_press_machine"),
        (r"decline", "decline_press_machine"),
        (r"chest press|iso-lateral chest", "chest_press_machine"),
        (r"chest fly|pec deck", "pec_deck"),
        (r"shoulder press", "shoulder_press_machine"),
        (r"lateral raise", "lateral_raise_machine"),
        (r"rear delt|reverse fly", "rear_delt_machine"),
        (r"t bar", "t_bar_row_machine"),
        (r"\brow\b", "seated_row_machine"),
        (r"pullover", "pullover_machine"),
        (r"preacher", "preacher_machine"),
        (r"curl", "biceps_curl_machine"),
        (r"tricep|dip", "triceps_machine"),
        (r"crunch", "ab_crunch_machine"),
        (r"torso rotation", "torso_rotation_machine"),
        (r"back extension", "back_extension_machine"),
        (r"assisted", "assisted_pullup_dip_machine"),
    )
    if (hevy_eq == "machine" or "(machine)" in t) and not out:
        for pat, eid in machine_map:
            if re.search(pat, t):
                add(eid)
                break
        else:
            add("machine_unspecified")
    if re.search(r"pull ?up|chin ?up|hanging|dead hang|muscle ?up", t) and "assisted" not in t:
        add("pullup_bar")
    if re.search(r"\bdips?\b", t) and "bench dip" not in t and "assisted" not in t and "machine" not in t:
        add("dip_station")
    if "bench dip" in t:
        add("bench_flat")
    if re.search(r"box jump|step ?ups?", t):
        add("plyo_box")
    if "ab wheel" in t:
        add("ab_wheel")
    if "hyperextension" in t:
        add("back_extension_45")
    if re.search(r"medicine ball|med ball|slam", t):
        add("medicine_ball")
    if re.search(r"trx|suspension|ring", t):
        add("suspension_trainer")
    if not out:
        add("bodyweight" if hevy_eq in ("none", None) else "other_unspecified")
    return out


# A named pin-stack (or unspecified-loading) machine: selectorized unless the curation says plate-loaded. `machine_unspecified`
# stays `unknown` — the rule cannot say what it is.
_SELECTORIZED = {
    "leg_extension_machine",
    "leg_curl_seated",
    "leg_curl_lying",
    "calf_raise_standing_machine",
    "calf_raise_seated_machine",
    "hip_thrust_machine",
    "glute_kickback_machine",
    "hip_abduction_machine",
    "hip_adduction_machine",
    "incline_press_machine",
    "decline_press_machine",
    "chest_press_machine",
    "pec_deck",
    "shoulder_press_machine",
    "lateral_raise_machine",
    "rear_delt_machine",
    "seated_row_machine",
    "pullover_machine",
    "preacher_machine",
    "biceps_curl_machine",
    "triceps_machine",
    "ab_crunch_machine",
    "torso_rotation_machine",
    "back_extension_machine",
    "assisted_pullup_dip_machine",
}


def _resistance(equipment: list[str], hevy_eq: str | None, family: str, title: str) -> str:
    eq = set(equipment)
    if family == "carry_conditioning" and _is_cardio(title):
        return "cardio_machine" if eq - {"bodyweight"} else "not_applicable"
    if "sled" in eq:
        return "sled"
    if "cable_stack" in eq or "lat_pulldown_station" in eq:
        return "cable"
    if "resistance_band" in eq:
        return "band"
    if eq & {"barbell", "dumbbell", "kettlebell", "ez_bar", "trap_bar", "weight_plate"}:
        return "free_weight"
    if "smith_machine" in eq or eq & {
        "leg_press_machine",
        "hack_squat_machine",
        "pendulum_squat_machine",
        "belt_squat_machine",
        "t_bar_row_machine",
    }:
        return "machine_plate_loaded"
    if eq & _SELECTORIZED:
        return "machine_selectorized"  # #5857: a named machine read `unknown` before, so the rubric scored it as nothing
    if eq & {"bodyweight", "pullup_bar", "dip_station", "plyo_box", "ab_wheel", "back_extension_45"}:
        return "bodyweight"
    return "unknown"


def _stability(equipment: list[str], resistance: str, title: str) -> str:
    t = title.lower()
    if resistance in ("machine_selectorized", "machine_plate_loaded") or "smith_machine" in equipment:
        return "high"
    if re.search(r"seated|lying|chest supported|preacher|incline bench|bench press|prone", t):
        return "high" if resistance in ("cable", "unknown") else "moderate"
    if re.search(r"single leg|one leg|1 leg|pistol|standing|walking|bulgarian|split|lunge|step", t):
        return "low"
    if resistance == "cable":
        return "moderate"
    if resistance == "free_weight":
        return "low"
    if resistance == "bodyweight":
        return "moderate"
    return "unknown"


def _skill(title: str, family: str, tier: int | None) -> str:
    if _OLY_RE.search(title) and not re.search(r"high pulls?", title, re.I):
        return "high"
    if re.search(r"turkish|muscle ?up|pistol|handstand|nordic|dragon flag|\bflag\b|lever", title, re.I):
        return "high"
    if family == "skill_athletic":
        return "moderate"
    if tier == 3:
        return "moderate"
    if tier == 2 and _COMPOUND_RE.search(title):
        return "moderate"
    return "low"


def _spinal(title: str, equipment: list[str], resistance: str) -> str:
    t = title.lower()
    if "barbell" in equipment and re.search(
        r"squat|deadlift|good morning|bent over row|overhead press|military press|clean|snatch|lunge", t
    ):
        return "high"
    if resistance in ("machine_selectorized", "machine_plate_loaded") or re.search(r"seated|lying|chest supported|prone", t):
        return "low"
    return "unknown"


def _slug(title: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", title.lower())).strip("_") or "movement"


_PATTERN_TARGET = {
    "calf": "calves",
    "leg_curl": "hamstrings",
    "leg_extension": "quadriceps",
    "hip_extension": "glutes",
    "hinge": "glutes",
    "squat": "quadriceps",
    "vertical_pull": "back",
    "horizontal_pull": "back",
    "triceps_extension": "triceps",
    "curl": "biceps",
    "vertical_press": "shoulders",
    "lateral_raise": "shoulders",
    "rear_delt": "shoulders",
    "chest_fly": "chest",
    "horizontal_press": "chest",
    "carry": "abs",
    "core_anti": "abs",
    "core_flexion": "abs",
    "cardio": "cardio",
    "shrug": "back",
    "olympic": "glutes",
}


def derive(tid: str, title: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Rule-derived attributes for one movement. `meta` is its movement-catalog entry (or {})."""
    family = _family(title, meta)
    equipment = _equipment(title, meta.get("equipment"), family)
    resistance = _resistance(equipment, meta.get("equipment"), family, title)
    primary = meta.get("primary_muscle") or "unknown"
    if primary in ("unknown", "other"):
        # Hevy files many custom templates under "other"; the movement pattern names the target honestly enough to
        # find a same-stimulus fallback. Still `none_reviewed` — this is a label, not an evidence claim.
        primary = _PATTERN_TARGET.get(lib_rules.movement_pattern(title), primary)
    return {
        "title": title,
        "target": {
            "primary": primary,
            "secondary": list(meta.get("secondary_muscles") or []),
            "region": "cardio" if family == "carry_conditioning" and _is_cardio(title) else _REGION.get(primary, "full_body"),
        },
        "family": family,
        "length_bias": _length_bias(title, family),
        "resistance_profile": resistance,
        "stability": _stability(equipment, resistance, title),
        "joint_stress": {
            "spinal_load": _spinal(title, equipment, resistance),
            "shear": "unknown",
            "wrist": "unknown",
            "elbow": "unknown",
            "shoulder": "unknown",
        },
        "skill_complexity": _skill(title, family, meta.get("skill_tier")),
        "equipment": equipment,
        "hypertrophy": [cur.hyp(primary)],
    }


def auto_gates(entry: dict[str, Any]) -> list[str]:
    """The gates the rules in `training.exercise_library` require, by title/family/skill."""
    t = str(entry.get("title") or "")
    g: list[str] = []
    if lib_rules.requires_bodyweight_gate(entry):
        if re.search(r"muscle[\s-]?up|lever", t, re.I):
            g += ["bw_pull", "chain_pull", "bw_advanced", "owner_confirmation_skill"]
        elif re.search(r"pull[\s-]?ups?|chin[\s-]?ups?", t, re.I):
            g += ["bw_pull", "chain_pull"]
        elif re.search(r"\bdips?\b", t, re.I):
            g += ["bw_dip", "chain_dip"]
        elif re.search(r"nordic", t, re.I):
            g += ["bw_nordic", "chain_nordic"]
        elif re.search(r"hanging|toes to bar|l[\s-]?sit", t, re.I):
            g += ["bw_hanging", "chain_hanging"]
        elif re.search(r"handstand|pistol|dragon flag", t, re.I):
            g += ["bw_advanced", "owner_confirmation_skill"]
        else:
            g += ["bw_pushup", "chain_pushup"]
    if lib_rules.requires_impact_gate(entry):
        g.append("charter_running" if re.search(r"\b(run|running|jog|jogging|sprint\w*|shuttle)\b", t, re.I) else "charter_plyometric")
    if lib_rules.requires_skill_gate(entry) and not {"chain_prerequisite", "owner_confirmation", "charter_gate"} & {
        cur.GATES[x]["kind"] for x in g + list(entry.get("gates") or [])
    }:
        g.append("owner_confirmation_skill")
    if entry.get("family") in (
        "strength_anchor",
        "core_anti_movement",
        "carry_conditioning",
        "skill_athletic",
    ) or lib_rules.requires_bodyweight_gate(entry):
        if not (entry.get("family") == "carry_conditioning" and _is_cardio(t)):
            g.append("clinical_cue_breathing")
    return g


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if k in ("key", "gates"):
            continue
        out[k] = v
    return out


_LEDGER: dict[str, Any] | None = None


def _ledger() -> dict[str, Any]:
    """The accepted evidence-review ledger (#5778), read once per process."""
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = reviews.load_ledger()
    return _LEDGER


ADDITIONS_MODULE = "exercise_library_additions"  # deploy/exercise_library_additions.py (epic #5861 lane L2), optional


def library_additions() -> list[dict[str, Any]]:
    """THE library-expansion hook (#5861): new canonical movements from `deploy/exercise_library_additions.py`.

    Contract: that module exposes `ADDITIONS: list[dict]`, each entry in the curation's `EXPANSION` shape (built the way
    `exercise_library_curation._x` builds one: `key`, `title`, `template_id` or None + `template_note`, and any attribute
    the rules cannot know — `target`, `family`, `length_bias`, `resistance_profile`, `stability`, `joint_stress`,
    `skill_complexity`, `equipment`, `gates`), plus the #5861 evaluation fields the objective rubrics read when present:
    `category`, `trunk_function`, `functions`, `canonical`, `variant`, `objective_inputs` (see
    `training.quality_rubric.OBJECTIVE_INPUTS`). An absent module is no additions. A key that is already a curated
    candidate is a hard stop — an addition never silently replaces a reviewed entry."""
    import importlib.util

    if importlib.util.find_spec(ADDITIONS_MODULE) is None:
        return []
    mod = importlib.import_module(ADDITIONS_MODULE)
    adds = [dict(x) for x in getattr(mod, "ADDITIONS", [])]
    clash = sorted({x["key"] for x in adds} & {x["key"] for x in cur.EXPANSION})
    if clash:
        raise SystemExit(f"library additions: keys already curated in EXPANSION: {clash}")
    return adds


def _expansion_list() -> list[dict[str, Any]]:
    """The curation's candidates, then the #5861 additions, then the ledger's accepted ones (a ledger key already listed
    is a replacement)."""
    extra = reviews.ledger_candidates(_ledger())
    keys = {x["key"] for x in extra}
    return [x for x in cur.EXPANSION + library_additions() if x["key"] not in keys] + extra


def library_citations() -> dict[str, dict[str, Any]]:
    """The curation's verified citations plus the ledger's (a ledger id already curated is a correction and wins)."""
    return {**cur.CITATIONS, **reviews.ledger_citations(_ledger())}


def _history_entries(
    history: dict[str, Any], catalog: dict[str, Any], aliases: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """tid -> history entry (derived, then expansion-candidate attributes, then curation); and the merged candidate keys."""
    cat_mv = catalog.get("movements") or {}
    by_tid = {str(v.get("hevy_template_id_hint") or "").upper(): v for v in cat_mv.values() if v.get("hevy_template_id_hint")}
    by_title = {str(v.get("title") or "").strip().lower(): v for v in cat_mv.values()}
    expansion_by_tid = {str(x["template_id"]).upper(): x for x in _expansion_list() if x.get("template_id")}
    entries: dict[str, dict[str, Any]] = {}
    merged_into_history: list[str] = []
    for tid, h in history["templates"].items():
        names = Counter(h.get("names") or {})
        logged = names.most_common(1)[0][0] if names else tid
        meta = by_tid.get(tid) or by_title.get(logged.lower()) or {}
        title = cur.CURATED.get(tid, {}).get("title") or meta.get("title") or logged
        e = derive(tid, title, meta)
        e.update(
            {
                "source": "history",
                "template_id": tid,
                "history": {"first_done": h["first_done"], "last_done": h["last_done"], "exposures": int(h["exposures"])},
            }
        )
        if tid in aliases:
            e["alias_of"] = aliases[tid]
        gates = list((cur.CURATED.get(tid) or {}).get("gates") or [])
        if tid in expansion_by_tid:
            x = expansion_by_tid[tid]
            e = _merge(e, {k: v for k, v in x.items() if k not in ("title", "template_id")})
            gates += list(x.get("gates") or [])
            e["_key"] = x["key"]
            merged_into_history.append(x["key"])
        e = _merge(e, cur.CURATED.get(tid) or {})
        e["gates"] = gates
        entries[tid] = e
    return entries, merged_into_history


def _catalog_only_entries(catalog: dict[str, Any], entries: dict[str, dict[str, Any]]) -> list[str]:
    """Every catalog movement is in the library: one not in the current history enters as an expansion entry."""
    catalog_only: list[str] = []
    for k, v in (catalog.get("movements") or {}).items():
        tid = str(v.get("hevy_template_id_hint") or "").upper()
        if not tid or tid in entries:
            continue
        e = derive(tid, v.get("title") or k, v)
        e.update({"source": "expansion", "template_id": tid, "expansion_origin": f"movement_catalog:{k}"})
        e = _merge(e, cur.CURATED.get(tid) or {})
        e["gates"] = list((cur.CURATED.get(tid) or {}).get("gates") or [])
        e["_key"] = k
        entries[tid] = e
        catalog_only.append(k)
    return catalog_only


def _expansion_entries(entries: dict[str, dict[str, Any]], merged_into_history: list[str]) -> list[dict[str, Any]]:
    """Adds template-bearing candidates to `entries`; returns the candidates with no Hevy template."""
    no_template: list[dict[str, Any]] = []
    for x in _expansion_list():
        tid = str(x.get("template_id") or "").upper()
        twin = tid in entries and str(entries[tid].get("expansion_origin") or "").startswith("movement_catalog:")
        if tid and tid in entries and not (twin and x.get("expansion_profile")):  # #5861 L6: an addition owns its catalog twin
            if entries[tid]["source"] == "expansion" and x["key"] not in merged_into_history:
                entries[tid] = _merge(entries[tid], x)
                entries[tid]["gates"] = list(entries[tid].get("gates") or []) + list(x.get("gates") or [])
                entries[tid]["_key"] = x["key"]
            continue
        base = derive(tid, x["title"], {"primary_muscle": (x.get("target") or {}).get("primary")})
        e = _merge(base, x)
        e.update({"source": "expansion", "template_id": x.get("template_id")})
        e = _merge(e, cur.CURATED.get(tid) or {}) if tid else e
        e["gates"] = list(x.get("gates") or []) + list((cur.CURATED.get(tid) or {}).get("gates") or [])
        e["_key"] = x["key"]
        if tid:
            entries[tid] = e
        else:
            no_template.append(e)
    return no_template


def _keyed_movements(
    entries: dict[str, dict[str, Any]], no_template: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Stable keys (history by exposures first), the gate union (curated + rule), and tid -> key."""
    movements: dict[str, dict[str, Any]] = {}
    all_entries = sorted(
        entries.values(), key=lambda e: (e["source"] != "history", -(e.get("history") or {}).get("exposures", 0), e["title"])
    )
    all_entries += sorted(no_template, key=lambda e: e["_key"])
    used: set[str] = set()
    tid_to_key: dict[str, str] = {}
    for e in all_entries:
        key = e.pop("_key", None) or _slug(e["title"])
        if key in used:
            key = f"{key}_{str(e.get('template_id') or 'x')[:8].lower()}"
        used.add(key)
        if e.get("template_id"):
            tid_to_key[str(e["template_id"]).upper()] = key
        gates = list(dict.fromkeys(list(e.get("gates") or []) + auto_gates(e)))
        e["gates"] = [g for g in gates if g in cur.GATES and cur.GATES[g].get("applies_to") != "all"]
        e.setdefault("not_for_you_now", None)
        movements[key] = e
    return movements, tid_to_key


def _resolved_gates(movements: dict[str, dict[str, Any]], tid_to_key: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The curation's gates with every `tid:` / `key:` chain prerequisite resolved to a library key (or a hard stop)."""
    gates_out: dict[str, dict[str, Any]] = {}
    for gid, g in cur.GATES.items():
        g2 = dict(g)
        pres = []
        for p in g.get("chain_prerequisites") or []:
            kind, _, val = p.partition(":")
            if kind == "tid":
                if val.upper() not in tid_to_key:
                    raise SystemExit(f"gate {gid}: prerequisite template {val} is not in the library")
                pres.append(tid_to_key[val.upper()])
            else:
                if val not in movements:
                    raise SystemExit(f"gate {gid}: prerequisite key {val} is not in the library")
                pres.append(val)
        g2["chain_prerequisites"] = pres
        gates_out[gid] = g2
    return gates_out


COMPOUND_PATTERNS = ("horizontal_press", "vertical_press", "squat", "hinge", "vertical_pull", "horizontal_pull", "olympic", "carry")
_ISOLATION_TITLE = re.compile(r"pullover|straight arm|press ?outs?|calf|pallof", re.I)  # a pullover / straight-arm pull is single-joint
_PRESS_TITLE = re.compile(r"\bpress(es)?\b|\bdips?\b|thruster|push ?ups?|pushups?", re.I)


def job_and_pattern(e: dict[str, Any]) -> tuple[str, str]:
    """The movement's JOB (compound | isolation) and pattern, by what it does (owner ruling 2026-11-12, board rec 1):
    `exercise_library.movement_pattern` over the title; a press, dip, push-up or thruster whose title the pattern table
    misses is a compound `press`; a pullover or straight-arm pull is isolation. Never by muscle name."""
    title = str(e.get("title") or "")
    pattern = lib_rules.movement_pattern(title)
    if _ISOLATION_TITLE.search(title):
        return "isolation", pattern
    if pattern in COMPOUND_PATTERNS:
        return "compound", pattern
    if _PRESS_TITLE.search(title):
        return "compound", pattern if pattern in ("horizontal_press", "vertical_press") else "press"
    return "isolation", pattern


def apply_attribute_audit(movements: dict[str, dict[str, Any]]) -> None:
    """The reviewed attribute audit (`deploy/exercise_library_targets.py`, owner ruling 2026-11-12, board rec 5), in place:
    each `ATTRIBUTE_OVERRIDES` row replaces the named attributes (a joint_stress map merges joint by joint); then every
    joint still `unknown` on a movement whose pattern has a reviewed `JOINT_RATINGS_BY_PATTERN` row takes that rating — a
    rated joint is never overwritten. Each change is recorded on the entry as `attribute_audit`. A missing key is a hard stop."""
    missing = sorted(k for k in targets.ATTRIBUTE_OVERRIDES if k not in movements)
    if missing:
        raise SystemExit(f"attribute audit: overrides for movements not in the library: {missing}")
    for key, (attrs, reason) in targets.ATTRIBUTE_OVERRIDES.items():
        e = movements[key]
        for field, value in attrs.items():
            e[field] = {**(e.get(field) or {}), **value} if field == "joint_stress" else value
        e["attribute_audit"] = {"fields": sorted(attrs), "reason": reason}
    input_review.apply_attributes(movements)  # #5861 FIX2-DATA: the reviewed-input pass (attributes half)
    for e in movements.values():
        rule = targets.joint_rating(e, lib_rules.movement_pattern(str(e.get("title") or "")))
        if not rule:
            continue
        js = dict(e.get("joint_stress") or {})
        filled = sorted(j for j, v in js.items() if v == "unknown" and j in rule[0])
        if filled:
            e["joint_stress"] = {j: (rule[0][j] if j in filled else v) for j, v in js.items()}
            e.setdefault("attribute_audit", {"fields": [], "reason": ""})
            e["attribute_audit"]["joints_rated"] = {"joints": filled, "rule": rule[1]}


def apply_press_family(movements: dict[str, dict[str, Any]]) -> None:
    """#5861 FIX7: the press family rated by implement, consistently (input_review.PRESS_FAMILY_JOINTS), after the class rules — a
    rated joint the family rule names is overwritten (and recorded on `attribute_audit.press_family`)."""
    for e in movements.values():
        fam = input_review.press_family_joints(e)
        js = dict(e.get("joint_stress") or {})
        changed = sorted(j for j, v in (fam or ({}, ""))[0].items() if js.get(j) != v)
        if fam and changed:
            e["joint_stress"] = {**js, **{j: fam[0][j] for j in changed}}
            e.setdefault("attribute_audit", {"fields": [], "reason": ""})
            e["attribute_audit"]["press_family"] = {"joints": changed, "rule": fam[1]}
    for key, e in movements.items():  # an alias (variant.duplicate_of) carries its head's ratings — the schema's alias rule
        head = movements.get(str((e.get("variant") or {}).get("duplicate_of") or ""))
        rated = (head or {}).get("attribute_audit", {}).get("press_family")
        if rated and e.get("joint_stress") != head["joint_stress"]:
            e["joint_stress"] = dict(head["joint_stress"])
            e.setdefault("attribute_audit", {"fields": [], "reason": ""})
            e["attribute_audit"]["press_family"] = {"joints": rated["joints"], "rule": f"an alias of {e['variant']['duplicate_of']}"}


def apply_target_audit(movements: dict[str, dict[str, Any]], overrides: dict[str, tuple[str, str]] | None = None) -> None:
    """The reviewed target-label audit (`deploy/exercise_library_targets.py`, #5857), in place: the audited primary and its
    region, every hypertrophy row whose target was the old primary moved with it (a sub-target row is left alone), and
    `target.audit` {from, reason} recorded. A key not in the library is a hard stop — an override never vanishes silently."""
    table = targets.TARGET_OVERRIDES if overrides is None else overrides
    missing = sorted(k for k in table if k not in movements)
    if missing:
        raise SystemExit(f"target audit: overrides for movements not in the library: {missing}")
    for key, (primary, reason) in table.items():
        e = movements[key]
        old = str((e.get("target") or {}).get("primary") or "unknown")
        region = _REGION.get(primary) or targets.AUDIT_REGIONS.get(primary, "full_body")
        e["target"] = {**(e.get("target") or {}), "primary": primary, "region": region, "audit": {"from": old, "reason": reason}}
        e["hypertrophy"] = [r | {"target": primary} if r.get("target") == old else r for r in e.get("hypertrophy") or []]


def apply_evaluation_layer(movements: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """#5861, in place, before any tier is derived: the reviewed pattern fixes, category / trunk function / functions, the
    objective inputs, the reviewed secondary target rows, then the canonical layer (aliases take their canonical's
    attributes). Returns the canonical-family index (`canonical_families`)."""
    return objectives.apply(movements, cur.hyp)


def rating_counts(movements: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per objective, how many movements sit in each tier (and how many it does not apply to)."""
    out: dict[str, dict[str, int]] = {}
    for o in quality_rubric.OBJECTIVES:
        c = Counter(str(e["ratings"][o]["tier"] or "not_applicable") for e in movements.values())
        out[o] = {t: c.get(t, 0) for t in quality_rubric.QUALITY_TIERS + ("not_applicable",)}
    return out


def build_library(
    current: dict[str, Any] | None, history: dict[str, Any], catalog: dict[str, Any], aliases: dict[str, str]
) -> dict[str, Any]:
    entries, merged_into_history = _history_entries(history, catalog, aliases)
    catalog_only = _catalog_only_entries(catalog, entries)
    no_template = _expansion_entries(entries, merged_into_history)
    movements, tid_to_key = _keyed_movements(entries, no_template)
    gates_out = _resolved_gates(movements, tid_to_key)
    apply_target_audit(movements)  # #5857: Hevy's raw muscle label -> the reviewed target, before any tier is derived
    apply_attribute_audit(movements)  # #5857 rubric v2 (board rec 5): reviewed attribute fixes + joint ratings
    for e in movements.values():
        e["job"], e["pattern"] = job_and_pattern(e)
    families = apply_evaluation_layer(movements)  # #5861: category, objective inputs, secondary rows, canonical layer
    input_review.apply_class_rules(movements)  # #5861 FIX3: shoulder-provoking work >= moderate; one spine-loading class
    apply_press_family(movements)  # #5861 FIX7: elbow / wrist by implement across the press family (pain outcomes consistent)
    missing = reviews.apply_evidence_changes(movements, reviews.ledger_evidence_changes(_ledger()))
    if missing:
        raise SystemExit(f"evidence-review ledger: evidence change for a movement not in the library: {missing}")
    reviews.finalize_tiers(movements)  # #5857 + #5861: every row's tier (+ at most one recorded band) and every objective rating

    used_eq = sorted({x for e in movements.values() for x in e["equipment"]})
    inventory, cutoff = home_gym_inventory(movements, history, used_eq)
    for e in movements.values():
        e["availability"] = {lib_rules.LOCATION_ID: movement_availability(e, inventory, cutoff)}
    proto = {"gates": gates_out, "movements": movements}
    fidx = lib_rules.fallback_index(proto)
    for key, e in movements.items():
        fbs = lib_rules.fallback_candidates(proto, key, fidx)[:MAX_FALLBACKS]
        e["fallbacks"] = [{"movement_id": k, "reason": r} for k, r in fbs]
    for key in list(movements):
        movements[key] = _ordered(movements[key])
    head = with_builder_changes({k: (current or {}).get(k, v) for k, v in INITIAL_HEADER.items()})
    tiers = Counter(r["tier"] or "not_applicable" for e in movements.values() for r in e["hypertrophy"])
    confidence = Counter(r["evidence_confidence"] for e in movements.values() for r in e["hypertrophy"])
    src = Counter(e["source"] for e in movements.values())
    return {
        "_README": (
            "The owner's exercise library (#5769). PROPOSED — nothing in the drafting path reads it until the owner approves "
            "it. Public half only: no bodyweight, no loads, no note text — the N=1 half (best set per bodyweight band, coded "
            "note signals, gate threshold values) is the owner-private overlay s3://matthew-life-platform/config/coaching/"
            "exercise_library.private.json, joined at selection time by lambdas/training/exercise_library.py (fail-closed). "
            "Built by deploy/build_exercise_library.py from the full Hevy history + deploy/exercise_library_curation.py. "
            "Doc: docs/coaching/EXERCISE_LIBRARY.md."
        ),
        **head,
        "_provenance": {
            "generated_by": GENERATED_BY,
            "history_source": "DynamoDB life-platform pk=USER#matthew#SOURCE#hevy per-workout rows, every phase (read-only query)",
            "history_first": history.get("first"),
            "history_through": history.get("last"),
            "workouts": history.get("workouts"),
            "excluded": {**history.get("skipped", {}), "delete_markers_present": history.get("delete_markers", 0)},
            "untagged_exercises": history.get("untagged_exercises", 0),
            "distinct_template_ids": len(history["templates"]),
            "movements": len(movements),
            "by_source": dict(sorted(src.items())),
            "hypertrophy_rows_by_tier": {t: tiers.get(t, 0) for t in quality_rubric.QUALITY_TIERS + ("not_applicable",)},
            "ratings_by_objective": rating_counts(movements),
            "s_census": quality_rubric.s_census(movements),
            "canonical": {
                "families": len(families),
                "aliases": sum(len(f["aliases"]) for f in families.values()),
                "variants": sum(len(f["variants"]) for f in families.values()),
            },
            "hypertrophy_rows_by_evidence_confidence": {c: confidence.get(c, 0) for c in quality_rubric.EVIDENCE_CONFIDENCE},
            "expansion_candidates_already_in_history": sorted(merged_into_history),
            "catalog_movements_not_in_current_history": sorted(catalog_only),
            "attribute_rule": "derived by rule unless deploy/exercise_library_curation.py overrides; `unknown` = the rule cannot say",
        },
        "quality_rubric": quality_rubric.rubric_doc(),
        "equipment_vocabulary": cur.EQUIPMENT_VOCABULARY,
        "gym_inventory": {
            "location_id": lib_rules.LOCATION_ID,
            "rule": "owner ruling 2026-11-11: equipment used by any movement logged in the last "
            f"{lib_rules.AVAILABLE_LOOKBACK_YEARS} years of Hevy history (on or after {cutoff}) is `available` at home_gym; equipment seen "
            "only in older history or only in expansion candidates is `unknown`; a 'gym doesn't have X' note makes X `unavailable` "
            "(owner-confirmable); contention ('X was taken', 'no bench free') never changes a state. The gym is never named.",
            "items": inventory,
        },
        "citations": library_citations(),
        "gate_schema": {
            "kinds": list(lib_rules.LIBRARY_GATE_KINDS),
            "fields": {
                "kind": "one of `kinds`",
                "locks": "true for every kind except clinical_cue (a cue never caps intensity)",
                "measured_input": "what the evaluator reads",
                "unlock_condition": "the condition that opens the gate",
                "chain_prerequisites": "library movement keys that must meet the stated standard first",
                "threshold": "bodyweight_threshold only: {ref: overlay:gate_thresholds.<key>} or {charter_ref: <charter path>} — never a value",
                "charter_ref": "charter_gate only: the charter path that owns the gate",
                "unknown_input": "always `locked`",
                "applies_to": "`all` = a global gate on every movement; else listed on the movement",
            },
            "evaluated_by": "#5772 (next story); v0.1 only defines gates",
        },
        "gates": gates_out,
        "programming_settings": PROGRAMMING_SETTINGS_DEFAULTS
        | dict((current or {}).get("programming_settings") or {})
        | OWNER_RULED_SETTINGS,
        "canonical_families": families,
        "movements": movements,
    }


_ORDER = (
    "title",
    "source",
    "template_id",
    "template_note",
    "alias_of",
    "expansion_origin",
    "history",
    "target",
    "family",
    "job",
    "pattern",
    "length_bias",
    "resistance_profile",
    "stability",
    "joint_stress",
    "skill_complexity",
    "equipment",
    "category",
    "trunk_function",
    "functions",
    "canonical",
    "variant",
    "hypertrophy",
    "ratings",
    "objective_inputs",
    "other_evidence",
    "gates",
    "not_for_you_now",
    "availability",
    "fallbacks",
    "curation_note",
)


def _ordered(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: e[k] for k in _ORDER if k in e}
    for k in sorted(e):
        if k not in out:
            out[k] = e[k]
    return out


MAX_FALLBACKS = 3


def _years_before(day: str, years: int) -> str:
    y, m, d = (int(x) for x in day.split("-"))
    if m == 2 and d == 29:
        d = 28
    return f"{y - years:04d}-{m:02d}-{d:02d}"


def home_gym_inventory(movements: dict[str, dict[str, Any]], history: dict[str, Any], used_eq: list[str]) -> tuple[dict[str, Any], str]:
    """Equipment id -> {home_gym: {state, source}} by the owner's 2026-11-11 rule. Deterministic: the 5-year window is
    anchored on the history's own last date, never the wall clock."""
    cutoff = _years_before(history.get("last") or "1970-01-01", lib_rules.AVAILABLE_LOOKBACK_YEARS)
    recent = {x for e in movements.values() if (e.get("history") or {}).get("last_done", "") >= cutoff for x in e["equipment"]}
    older = {x for e in movements.values() if e.get("history") for x in e["equipment"]}
    out: dict[str, Any] = {}
    for eid in used_eq:
        if eid in cur.SEEDED_AVAILABILITY:
            st = dict(cur.SEEDED_AVAILABILITY[eid])
        elif eid in recent:
            st = {"state": "available", "source": f"rule: used by a movement logged on or after {cutoff}"}
        elif eid in older:
            st = {"state": "unknown", "source": f"rule: seen only in history before {cutoff}"}
        else:
            st = {"state": "unknown", "source": "rule: seen only in expansion candidates"}
        out[eid] = {lib_rules.LOCATION_ID: st}
    return out, cutoff


def movement_availability(e: dict[str, Any], inventory: dict[str, Any], cutoff: str) -> dict[str, Any]:
    states = {x: inventory[x][lib_rules.LOCATION_ID] for x in e["equipment"]}
    bad = sorted(x for x, st in states.items() if st["state"] == "unavailable")
    if bad:
        return {"state": "unavailable", "source": "equipment unavailable at home_gym: " + ", ".join(bad)}
    if (e.get("history") or {}).get("last_done", "") >= cutoff:
        return {"state": "available", "source": f"rule: logged on or after {cutoff}"}
    if all(st["state"] == "available" for st in states.values()):
        return {"state": "available", "source": "rule: every equipment id available at home_gym"}
    return {"state": "unknown", "source": "rule: not logged in the window and some equipment unknown"}


def check_template_index(lib: dict[str, Any], index_path: str) -> list[str]:
    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)
    ids = {str(t.get("id") or "").upper() for t in (idx.get("templates") or {}).values()}
    return [
        f"{k}: {e['template_id']} not in the Hevy template index"
        for k, e in lib["movements"].items()
        if e["source"] == "expansion" and e.get("template_id") and str(e["template_id"]).upper() not in ids
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--inputs")
    ap.add_argument("--save-inputs")
    ap.add_argument("--template-index", help="a copy of s3://matthew-life-platform/config/hevy_template_index.json (read-only)")
    args = ap.parse_args(argv)

    current = None
    if os.path.exists(LIBRARY_PATH):
        with open(LIBRARY_PATH, encoding="utf-8") as f:
            current = json.load(f)
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    with open(ALIASES_PATH, encoding="utf-8") as f:
        aliases = {str(a).upper(): str(c).split(":", 1)[-1].upper() for a, c in (json.load(f).get("aliases") or {}).items()}
    if args.inputs:
        with open(args.inputs, encoding="utf-8") as f:
            history = json.load(f)["history"]
    else:
        from build_movement_catalog import fetch_workout_rows

        history = summarize_history(fetch_workout_rows())
    if args.save_inputs:
        with open(args.save_inputs, "w", encoding="utf-8") as f:
            json.dump({"history": history}, f, indent=1, sort_keys=True)

    lib = build_library(current, history, catalog, aliases)
    errors = lib_rules.validate(lib)
    if args.template_index:
        errors += check_template_index(lib, args.template_index)
    print(json.dumps(lib["_provenance"], indent=2))
    print(f"gates: {len(lib['gates'])}; not_for_you_now: {sum(1 for e in lib['movements'].values() if e.get('not_for_you_now'))}")
    if errors:
        print(f"{len(errors)} schema errors:")
        for e in errors[:40]:
            print("  " + e)
        return 1
    if not args.write:
        print("dry-run — nothing written (pass --write)")
        return 0
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.relpath(LIBRARY_PATH, REPO_ROOT)} ({len(lib['movements'])} movements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
