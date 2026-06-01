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
import os
from typing import Any

from routine_ir import RoutineSpec

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


def _ir_movement_to_template(catalog: dict[str, Any], movement_key: str) -> str | None:
    mv = catalog.get("movements", {}).get(movement_key, {})
    return mv.get("hevy_template_id_hint")


def calculate_adherence(ir: RoutineSpec, performed: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog()
    programmed = []
    template_to_key: dict[str, str] = {}
    for ex in ir.exercises:
        tid = _ir_movement_to_template(catalog, ex.movement_key)
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
        movements.append({
            "movement_key": p["movement_key"],
            "programmed_sets": p["sets"],
            "performed_sets": performed_sets,
            "pct": pct,
        })
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
    total_performed = sum(min(per_muscle_programmed[m], per_muscle_performed.get(m, 0))
                          for m in per_muscle_programmed)
    overall_pct = round((total_performed / total_programmed) * 100, 1) if total_programmed else 0.0

    return {
        "overall_pct": overall_pct,
        "per_muscle": per_muscle,
        "movements": movements,
        "missing": missing,
        "extra": extra,
    }
