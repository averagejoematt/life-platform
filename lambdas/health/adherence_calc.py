"""
adherence_calc.py — Phase 2 readback: programmed-vs-performed adherence.

Inputs:
  ir            — the RoutineSpec that was pushed to Hevy (system of record)
  performed     — the Hevy workout as we received it (dict with exercises[]
                  + sets[]). Same shape as /v1/workouts response items.

Output:
  {
    "overall_pct": float,           # 0..100 — SET COMPLETION ONLY (see below)
    "overall_pct_dimension": "sets_only",
    "per_muscle": {muscle: pct},
    "movements": [{movement_key, programmed_sets, performed_sets, pct, intensity}],
    "missing": [movement_keys],
    "extra":   [exercise_template_ids],
    "sets_adherence":      {...},   # #3714 — the set-count dimension, named
    "intensity_adherence": {...},   # #3714 — the RPE-ceiling dimension
    "as_prescribed":       {...},   # #3714 — the AND of the two, never their average
  }

TWO DIMENSIONS, NEVER ONE NUMBER (#3714). Adherence used to be set-count overlap
alone, so the 2026-09-07 push session read `overall_pct: 100.0` while its incline DB
press was logged at RPE 10 — trained to failure on a day whose own plan said "No
failure sets today". `intensity_adherence` is the missing half, graded against the
ceiling the routine ITSELF named (see `training.intensity_prescription` — nothing
there invents a cutoff). The two are reported SEPARATELY on purpose: averaging "he did
every set" with "he blew the ceiling on five of them" back into one percentage would
reproduce the same defect one level up, hiding which half failed. `as_prescribed` is
the composite the story asks for, and it is an AND of two verdicts with its reasons
named — not a blend of two percentages.

`overall_pct` deliberately KEEPS its set-completion meaning: it is already stored on
every pre-#3714 workout record, and silently redefining a number that is written down
is its own lie. It gains `overall_pct_dimension` so no reader can mistake it for the
whole story, and `sets_adherence.pct` is its named twin.

Movement matching: by Hevy exercise_template_id when present; falls back to
title prefix on the catalog title.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from common.repo_config import config_dir
from training.intensity_prescription import grade_sets, resolve_ceiling
from training.routine_ir import RoutineSpec

logger = logging.getLogger("adherence_calc")

# Depth-independent default — see common.repo_config (#1653). The literal
# `dirname(__file__)/../config` assumed this module sat directly under the repo root.
CONFIG_DIR = os.environ.get("TRAINING_CONFIG_DIR", config_dir())
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
S3_CONFIG_PREFIX = os.environ.get("TRAINING_CONFIG_S3_PREFIX", "config/")

_s3_loader_client = None


def _load_catalog() -> dict[str, Any]:
    local = os.path.join(CONFIG_DIR, "movement_catalog.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}movement_catalog.json")
    return json.loads(obj["Body"].read())


def _load_template_cache() -> dict[str, Any]:
    """The resolved movement→Hevy-template map the compiler actually pushed
    (`config/hevy_template_cache.json`). Enrichment over the catalog hints, used only
    for ADR-069 title-resolved movements that deliberately carry NO hint — their real
    id lives here. Absent cache is non-fatal: we fall back to hints (empty → {})."""
    local = os.path.join(CONFIG_DIR, "hevy_template_cache.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    try:
        obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}hevy_template_cache.json")
        return json.loads(obj["Body"].read())
    except Exception as e:  # noqa: BLE001 — enrichment only; hints still resolve most movements
        logger.warning("template cache load failed (non-fatal, hints still apply): %s", e)
        return {}


def _ir_movement_to_template(catalog: dict[str, Any], movement_key: str, cache: dict[str, Any] | None = None) -> str | None:
    """Resolve a programmed movement_key to the Hevy template id it was pushed as.
    Three tiers: (1) ADR-069 template-index keys of the form "tmpl:<id>" already carry
    the resolved id in the suffix (a movement added by raw template, not a catalog entry
    — mirrors tools_hevy_routine.py); resolve it directly or it would be counted "missing"
    even when performed, deflating adherence. (2) catalog hint (authoritative for hinted
    movements). (3) resolved template cache for title-resolved movements (no hint on purpose)."""
    if movement_key and movement_key.startswith("tmpl:"):
        return movement_key[len("tmpl:") :]
    hint = catalog.get("movements", {}).get(movement_key, {}).get("hevy_template_id_hint")
    if hint:
        return hint
    return ((cache or {}).get("movements", {}).get(movement_key) or {}).get("hevy_template_id")


def _intensity_rollup(movements: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll the per-movement intensity grades into the session's intensity dimension.

    The denominator is GRADED working sets only — sets that carried both a prescribed
    ceiling and a logged RPE. Sets with no logged RPE are reported in `sets_rpe_absent`
    and never counted as within-ceiling (ADR-104: absence is absence, not compliance).

    `status`:
      graded       — at least one working set had a ceiling AND an RPE
      unreadable   — a ceiling was prescribed but no working set carried an RPE
      unprescribed — the routine named no intensity anywhere (pct is None, never 100)
    """
    grades = [m["intensity"] for m in movements if m.get("intensity")]
    # Only movements that were actually PRESCRIBED an intensity contribute to the
    # rollup. A movement with no ceiling has nothing to be compliant or non-compliant
    # with; counting its sets as "graded" would silently manufacture a denominator.
    prescribed = [g for g in grades if g["ceiling_rpe"] is not None]
    graded = sum(g["sets_graded"] for g in prescribed)
    over = sum(g["sets_over_ceiling"] for g in prescribed)
    absent = sum(g["sets_rpe_absent"] for g in prescribed)
    overages = [g["max_overage"] for g in prescribed if g.get("max_overage")]

    if graded:
        status = "graded"
        pct: float | None = round((graded - over) / graded * 100, 1)
    elif prescribed:
        status, pct = "unreadable", None
    else:
        status, pct = "unprescribed", None

    return {
        "status": status,
        "pct": pct,
        "sets_graded": graded,
        "sets_over_ceiling": over,
        "sets_rpe_absent": absent,
        "movements_with_ceiling": len(prescribed),
        "max_overage": max(overages) if overages else (0.0 if graded else None),
        "over_ceiling_movements": sorted(m["movement_key"] for m in movements if (m.get("intensity") or {}).get("sets_over_ceiling")),
    }


def _as_prescribed(sets_pct: float, intensity: dict[str, Any], movements: list[dict[str, Any]]) -> dict[str, Any]:
    """ "Did he train the session as prescribed?" — an AND of the two dimensions.

    Never an average. `no` names which dimension failed; `unknown` is returned rather
    than `yes` whenever the intensity half could not be read, because "we couldn't tell"
    has never been the same claim as "he complied" (ADR-104).
    """
    reasons: list[str] = []
    if sets_pct < 100.0:
        reasons.append(f"sets: {sets_pct}% of programmed sets completed")
    if intensity["sets_over_ceiling"]:
        names = ", ".join(intensity["over_ceiling_movements"])
        reasons.append(f"intensity: {intensity['sets_over_ceiling']} set(s) above the prescribed RPE ceiling ({names})")
    if reasons:
        return {"verdict": "no", "reasons": reasons}

    if intensity["status"] != "graded":
        return {"verdict": "unknown", "reasons": [f"intensity: {intensity['status']} — no RPE-vs-ceiling comparison was possible"]}
    blind = sorted(
        m["movement_key"]
        for m in movements
        if (m.get("intensity") or {}).get("sets_rpe_absent") and str((m["intensity"] or {}).get("basis") or "").startswith("exercise")
    )
    if blind:
        return {
            "verdict": "unknown",
            "reasons": [f"intensity: RPE not logged on movements that carried their own ceiling ({', '.join(blind)})"],
        }
    return {"verdict": "yes", "reasons": []}


def calculate_adherence(ir: RoutineSpec, performed: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog()
    cache = _load_template_cache()
    routine_notes = getattr(ir, "notes", "") or ""
    recovery_branches = ((getattr(ir, "inputs_snapshot", None) or {}) or {}).get("recovery_branches")
    programmed: list[dict[str, Any]] = []
    template_to_key: dict[str, str] = {}
    for ex in ir.exercises:
        tid = _ir_movement_to_template(catalog, ex.movement_key, cache)
        sets = len(ex.sets)
        ceiling = resolve_ceiling(ex.movement_key, getattr(ex, "notes", "") or "", routine_notes, recovery_branches)
        programmed.append({"movement_key": ex.movement_key, "template_id": tid, "sets": sets, "ceiling": ceiling})
        if tid:
            template_to_key[tid] = ex.movement_key

    performed_by_tid: dict[str, int] = {}
    performed_sets_by_tid: dict[str, list[dict[str, Any]]] = {}
    for ex in performed.get("exercises", []):
        tid = ex.get("exercise_template_id")
        if not tid:
            continue
        ex_sets = ex.get("sets", []) or []
        performed_by_tid[tid] = performed_by_tid.get(tid, 0) + len(ex_sets)
        performed_sets_by_tid.setdefault(tid, []).extend(ex_sets)

    movements: list[dict[str, Any]] = []
    per_muscle_programmed: dict[str, int] = {}
    per_muscle_performed: dict[str, int] = {}
    for p in programmed:
        performed_sets = performed_by_tid.get(p["template_id"], 0)
        pct = round(min(1.0, performed_sets / p["sets"]) * 100, 1) if p["sets"] else 0.0
        intensity = grade_sets(p["ceiling"]["rpe"], performed_sets_by_tid.get(p["template_id"], []))
        intensity["basis"] = p["ceiling"]["basis"]
        movements.append(
            {
                "movement_key": p["movement_key"],
                "programmed_sets": p["sets"],
                "performed_sets": performed_sets,
                "pct": pct,
                "intensity": intensity,
            }
        )
        muscle = catalog["movements"].get(p["movement_key"], {}).get("primary_muscle", "unknown")
        per_muscle_programmed[muscle] = per_muscle_programmed.get(muscle, 0) + p["sets"]
        per_muscle_performed[muscle] = per_muscle_performed.get(muscle, 0) + performed_sets

    missing = [m["movement_key"] for m in movements if m["performed_sets"] == 0]
    programmed_tids = {p["template_id"] for p in programmed if p["template_id"]}
    extra = [tid for tid in performed_by_tid if tid not in programmed_tids]

    per_muscle = {
        muscle: round(min(1.0, per_muscle_performed.get(muscle, 0) / max(1, sets)) * 100, 1)
        for muscle, sets in per_muscle_programmed.items()
    }
    total_programmed = sum(per_muscle_programmed.values())
    total_performed = sum(min(per_muscle_programmed[m], per_muscle_performed.get(m, 0)) for m in per_muscle_programmed)
    overall_pct = round((total_performed / total_programmed) * 100, 1) if total_programmed else 0.0

    intensity_adherence = _intensity_rollup(movements)

    return {
        "overall_pct": overall_pct,
        # #3714: name the dimension on the number so nothing can read set completion
        # as "trained as prescribed". The two dimensions below are never averaged.
        "overall_pct_dimension": "sets_only",
        "sets_adherence": {
            "pct": overall_pct,
            "programmed_sets": total_programmed,
            "performed_sets": total_performed,
        },
        "intensity_adherence": intensity_adherence,
        "as_prescribed": _as_prescribed(overall_pct, intensity_adherence, movements),
        "per_muscle": per_muscle,
        "movements": movements,
        "missing": missing,
        "extra": extra,
    }


def _best_by_overlap(candidates: list[RoutineSpec], performed: dict[str, Any]) -> tuple[RoutineSpec | None, str | None]:
    """When several routines were pushed for one day (ideal/floor/re-entry siblings),
    pick the one whose programmed template-ids best overlap what was actually performed.
    Returns (ir, "date_overlap") or (None, None) on a zero-overlap or a tie — we do not
    guess between equally-plausible plans (ADR-104)."""
    catalog = _load_catalog()
    cache = _load_template_cache()
    performed_tids = {ex.get("exercise_template_id") for ex in performed.get("exercises", []) if ex.get("exercise_template_id")}
    scored: list[tuple[int, RoutineSpec]] = []
    for c in candidates:
        prog_tids = {t for t in (_ir_movement_to_template(catalog, ex.movement_key, cache) for ex in c.exercises) if t}
        scored.append((len(prog_tids & performed_tids), c))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored or scored[0][0] == 0:
        return None, None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, None  # a genuine tie — don't fabricate a match
    return scored[0][1], "date_overlap"


def derive_adherence(raw_workout: dict[str, Any]) -> dict[str, Any] | None:
    """On-ingest deviation readback (#412): match a performed Hevy workout to the plan
    that was pushed for it, and compute programmed-vs-performed adherence.

    `raw_workout` is the RAW Hevy /v1/workouts item — it carries `routine_id`,
    `start_time`, and `exercises[].exercise_template_id` + `sets[]`. Do NOT pass the
    normalized record: normalization renames `exercise_template_id` → `template_id`,
    which would break the template match.

    Returns exactly one of (never raises — a projection must never break ingestion):
      • {"status": "matched",   "matched_routine_id", "match_method", "routine_target_date",
         "workout_pacific_date", "computed_at", **calculate_adherence(...)}
      • {"status": "ad_hoc",    "matched_routine_id": None, ...}      — no pushed plan
      • {"status": "ambiguous", "candidate_routine_ids": [...], ...}  — plans existed, none matched confidently
      • None                                                          — unexpected error (logged, non-fatal)

    ad_hoc / ambiguous deliberately omit every pct / movement field so nothing downstream
    can render a fabricated number (ADR-104)."""
    try:
        from common.pacific_time import pacific_date_of
        from training import routine_repo

        performed = raw_workout or {}
        pac_date = pacific_date_of(performed.get("start_time"))
        base = {
            "workout_pacific_date": pac_date,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        ir: RoutineSpec | None = None
        match_method: str | None = None
        candidates: list[RoutineSpec] = []

        # 1) Exact — the workout carries the Hevy routine id it was started from;
        #    reverse the id-map to our routine_id. Immune to the UTC-date keying bug.
        hevy_rid = str(performed.get("routine_id") or "").strip()
        if hevy_rid:
            rid = routine_repo.lookup_routine_id(hevy_rid)
            if rid:
                ir = routine_repo.get_current(rid)
                if ir:
                    match_method = "hevy_routine_id"

        # 2) Fallback — the routine(s) pushed for this Pacific calendar day.
        if ir is None and pac_date:
            candidates = routine_repo.list_by_date_range(pac_date, pac_date)
            if len(candidates) == 1:
                ir, match_method = candidates[0], "date_single"
            elif len(candidates) > 1:
                ir, match_method = _best_by_overlap(candidates, performed)

        if ir is None:
            if candidates:  # plans existed but none matched confidently → say so, don't guess
                return {
                    **base,
                    "status": "ambiguous",
                    "matched_routine_id": None,
                    "candidate_routine_ids": [getattr(c, "routine_id", None) for c in candidates],
                }
            return {**base, "status": "ad_hoc", "matched_routine_id": None}

        return {
            **base,
            "status": "matched",
            "matched_routine_id": getattr(ir, "routine_id", None),
            "match_method": match_method,
            "routine_target_date": getattr(ir, "target_date", None),
            **calculate_adherence(ir, performed),
        }
    except Exception as e:  # noqa: BLE001 — deviation is a projection; never break ingestion
        logger.warning("adherence derive failed (non-fatal): %s", e)
        return None
