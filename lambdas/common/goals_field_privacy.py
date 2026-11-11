"""Field-level privacy of ``config/user_goals.json`` (owner ruling 2026-11-10, item 6).

THE RULING. "config/user_goals.json — private by default. Field-level privacy + provenance review. Public-safe goals
may be eligible; sensitive personal details, private plans, restricted-source-derived info stay private. Until
established, keep the 14 dependent sealed calls withheld if their text could reveal restricted inputs ... don't
retroactively claim different inputs."

WHAT THIS IS. The review's verdict per field PATH (never a value: the repo is public). The evidence for each verdict
(what the field is, its git provenance, where it is already published and under what approval) is in the owner's
private review record, not here. ``classify`` fails closed: a path this module does not name is private, so a field
added to the goals file later is private until a review names it.

WHO READS IT. ``narrative_allowlist.record_for``: a historical coach text whose generation read goals-file fields is
published only while EVERY field it read is public-safe. ``goals_inputs_for`` names those fields per record, from the
producing code at the producing commit — the inputs the text actually had, never a cleaned-up projection.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Iterable

REVIEWED_AT = "2026-11-10"
PUBLIC_SAFE = "public_safe"
PRIVATE = "private"

#: Public-safe paths. ``[*]`` stands for any list index; ``.*`` for every key below a node.
_PUBLIC_SAFE: tuple = (
    "version",
    "last_updated",
    "updated_by",
    "timeline.*",
    "targets.weight.*",
    "targets.body_composition.*",
    "targets.training.*",
    "targets.nutrition.daily_calories_target",
    "targets.nutrition.daily_protein_min_g",
    "targets.nutrition.protein_note",
    "targets.nutrition.daily_fiber_min_g",  # removed 2026-10-20 (496fd9e36); read by the 2026-09-06 freeze
    "targets.nutrition.fiber_note",
    "targets.nutrition.eating_window.*",
    "targets.sleep.*",
    "targets.biomarkers.resting_hr_target_bpm",
    "targets.biomarkers.hrv_target_ms",
    # A bare target for a biomarker whose measured values are owner-consented public (ADR-155). The clinical and
    # genetic context sits in targets.biomarkers.note, which is private. The owner may reclassify this one.
    "targets.biomarkers.ldl_target_mg_dl",
    "targets.behavioral.habit_adherence_target_pct",
    "targets.behavioral.note",
    "athlete_profile.type",
    "athlete_profile.athletic_background",
    "athlete_profile.prior_transformation.start_weight",
    "athlete_profile.prior_transformation.end_weight",
    "athlete_profile.prior_transformation.duration_months",
    "athlete_profile.prior_transformation.approximate_dates",
    "athlete_profile.prior_transformation.method",
    "failure_mode.response_owner",
    "failure_mode.what_was_missing_last_time",
    "coach_communication.tone",
    "coach_communication.audience",
)

#: Named private paths (anything not public-safe is private anyway; these are listed so the review is explicit).
_PRIVATE: tuple = (
    "mission",
    "philosophy",
    "targets.nutrition.calorie_approach",
    "targets.biomarkers.note",
    "targets.behavioral.journal_entries_per_week",
    "athlete_profile.prior_transformation.outcome",
    "athlete_profile.weight_cycling_history",
    "athlete_profile.binge_eating_pattern",
    "mental_health_context.*",
    "failure_mode.pattern",
    "failure_mode.last_trigger",
    "failure_mode.early_warning_signals",
    "failure_mode.coach_response",
    "coach_communication.do_not",
    "known_constraints",
)


def _norm(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", str(path or ""))


def _hit(path: str, patterns: Iterable[str]) -> bool:
    p = _norm(path)
    for pat in patterns:
        if p == pat:
            return True
        if pat.endswith(".*") and (p.startswith(pat[:-1]) or p == pat[:-2]):
            return True
        if "[*]" in pat and fnmatch.fnmatchcase(p, pat.replace("[*]", "[[]*[]]")):
            return True
    return False


def classify(path: str) -> str:
    """``public_safe`` or ``private``. Private wins a tie, and an unnamed path is private (fail closed)."""
    if _hit(path, _PRIVATE):
        return PRIVATE
    return PUBLIC_SAFE if _hit(path, _PUBLIC_SAFE) else PRIVATE


def is_named(path: str) -> bool:
    """True when the review named this path (either way) — the guard that a new goals field gets reviewed."""
    return _hit(path, _PUBLIC_SAFE) or _hit(path, _PRIVATE)


#: The goals fields the sealed day-one calls' generation read: ``goals_digest()`` in
#: ``deploy/seed_genesis_preregistration.py`` at 17de015f0, the commit that froze the 2026-09-06 pre-registration
#: (deploy/generated/genesis_preregistration.json, generated_at 2026-09-06T02:13:38Z). The digest was the prompt's
#: only goals content; the rest of the prompt was static text, the coach's name and domain, and the metric list.
SEALED_CALL_DIGEST_FIELDS: tuple = (
    "timeline.start_date",
    "timeline.start_weight_lbs",
    "targets.weight.goal_lbs",
    "targets.weight.interim_milestones[*].lbs",
    "targets.weight.interim_milestones[*].label",
    "targets.nutrition.daily_calories_target",
    "targets.nutrition.daily_protein_min_g",
    "targets.nutrition.daily_fiber_min_g",
    "targets.nutrition.eating_window.window",
    "targets.training.phases[0].phase",
    "targets.training.phases[0].gym_days_per_week",
    "targets.training.phases[0].structure",
    "targets.training.zone2_minutes_per_week_target",
    "targets.training.daily_movement_target",
    "targets.sleep.target_bedtime",
    "targets.sleep.target_wake",
    "targets.sleep.target_hours",
    "targets.biomarkers.resting_hr_target_bpm",
    "targets.biomarkers.hrv_target_ms",
    "targets.biomarkers.ldl_target_mg_dl",
)
SEALED_FREEZE_SK_PREFIX = "PREDICTION#pred_20260906_"


def goals_inputs_for(pk: str, sk: str) -> tuple:
    """The goals fields a historical record's generation read. A sealed call of the 2026-09-06 freeze read the whole
    digest; a lead read reads the DynamoDB profile row, never this file, so it reads none."""
    if str(sk or "").startswith(SEALED_FREEZE_SK_PREFIX):
        return SEALED_CALL_DIGEST_FIELDS
    return ()


def inputs_public(paths: Iterable[str]) -> bool:
    return all(classify(p) == PUBLIC_SAFE for p in paths)
