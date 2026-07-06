"""
adherence_calc.py — Phase 2 readback: programmed-vs-performed adherence.

Inputs:
  ir            — the RoutineSpec that was pushed to Hevy (system of record)
  performed     — the Hevy workout as we received it (dict with exercises[]
                  + sets[]). Same shape as /v1/workouts response items.

Output:
  {
    "overall_pct": float,           # 0..100
    "per_muscle": {muscle: pct},
    "movements": [{movement_key, programmed_sets, performed_sets, pct}],
    "missing": [movement_keys],
    "extra":   [exercise_template_ids],
  }

Movement matching: by Hevy exercise_template_id when present; falls back to
title prefix on the catalog title.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from routine_ir import RoutineSpec

logger = logging.getLogger("adherence_calc")

CONFIG_DIR = os.environ.get(
    "TRAINING_CONFIG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "config"),
)
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
    Hint first (authoritative for hinted movements); for ADR-069 title-resolved
    movements (no hint on purpose) fall back to the resolved template cache."""
    hint = catalog.get("movements", {}).get(movement_key, {}).get("hevy_template_id_hint")
    if hint:
        return hint
    return ((cache or {}).get("movements", {}).get(movement_key) or {}).get("hevy_template_id")


def calculate_adherence(ir: RoutineSpec, performed: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog()
    cache = _load_template_cache()
    programmed = []
    template_to_key: dict[str, str] = {}
    for ex in ir.exercises:
        tid = _ir_movement_to_template(catalog, ex.movement_key, cache)
        sets = len(ex.sets)
        programmed.append({"movement_key": ex.movement_key, "template_id": tid, "sets": sets})
        if tid:
            template_to_key[tid] = ex.movement_key

    performed_by_tid: dict[str, int] = {}
    for ex in performed.get("exercises", []):
        tid = ex.get("exercise_template_id")
        if not tid:
            continue
        performed_by_tid[tid] = performed_by_tid.get(tid, 0) + len(ex.get("sets", []))

    movements: list[dict[str, Any]] = []
    per_muscle_programmed: dict[str, int] = {}
    per_muscle_performed: dict[str, int] = {}
    for p in programmed:
        performed_sets = performed_by_tid.get(p["template_id"], 0)
        pct = round(min(1.0, performed_sets / p["sets"]) * 100, 1) if p["sets"] else 0.0
        movements.append(
            {
                "movement_key": p["movement_key"],
                "programmed_sets": p["sets"],
                "performed_sets": performed_sets,
                "pct": pct,
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

    return {
        "overall_pct": overall_pct,
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
        import routine_repo
        from pacific_time import pacific_date_of

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
