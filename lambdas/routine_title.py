"""
routine_title.py — Title + WHY-note formatting for Hevy routines (ADR-067).

Title format:  "<Phase> - <Type> - <N> - <Y>"
  Phase  — current phase from config/training_phases.json
  Type   — ir.archetype title-cased (Upper, Lower, Full, Aerobic, Mobility…)
  N      — count of *pushed* routines of THIS type within CURRENT phase + 1.
           Resets at phase boundary (config.current_started). 1-based.
  Y      — total *performed* Hevy workouts to date + 1. Honest + self-
           correcting per the spec (skipped sessions never inflate Y).

Variant overrides:
  variant=re_entry → "Welcome back · <Type>" (no counters surfaced — kind
                     framing; Y/N still computed for IR analytics but kept
                     out of the title).
  variant=floor    → main title formula; WHY-note flags floor framing.

Kept in its own module so hevy_compiler stays I/O-free. The compiler
imports format_title lazily and only when a title_context is supplied.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from routine_ir import RoutineSpec

CONFIG_DIR = os.environ.get(
    "TRAINING_CONFIG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "config"),
)
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
S3_CONFIG_PREFIX = os.environ.get("TRAINING_CONFIG_S3_PREFIX", "config/")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
MAX_TITLE_CHARS = 60

_s3 = None
_ddb_table = None


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    return _s3


def _table():
    global _ddb_table
    if _ddb_table is None:
        _ddb_table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")
        ).Table(TABLE_NAME)
    return _ddb_table


def load_phase_state() -> dict[str, Any]:
    """Read training_phases.json. Local CONFIG_DIR first (tests), then S3.

    Returns the parsed JSON; `current` defaults to the first phase if absent,
    `current_started` defaults to today (no historical counter then).
    """
    local = os.path.join(CONFIG_DIR, "training_phases.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    obj = _s3_client().get_object(
        Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}training_phases.json"
    )
    return json.loads(obj["Body"].read())


def count_total_performed_workouts() -> int:
    """All Hevy workouts ever recorded in DDB for matthew. Paginates via Query."""
    pk = f"USER#{USER_ID}#SOURCE#hevy"
    total = 0
    last_key = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
            "Select": "COUNT",
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table().query(**kwargs)
        total += int(resp.get("Count", 0))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return total


def count_phase_archetype_routines(
    phase_start: str, archetype: str, target_date_exclusive: str
) -> int:
    """Count ROUTINE_INDEX entries with this archetype since phase_start,
    excluding any with target_date >= target_date_exclusive (the routine
    being committed now). Skips floor/re_entry variants so paired sessions
    don't double-count.
    """
    pk = f"USER#{USER_ID}#SOURCE#routine_index"
    resp = _table().query(
        KeyConditionExpression=Key("pk").eq(pk)
        & Key("sk").between(
            f"DATE#{phase_start}", f"DATE#{target_date_exclusive}"
        ),
    )
    seen_routine_ids: set[str] = set()
    count = 0
    for it in resp.get("Items", []):
        if it.get("archetype") != archetype:
            continue
        if (it.get("variant") or "") in ("floor", "re_entry"):
            continue
        td = it.get("target_date") or ""
        if td >= target_date_exclusive:
            continue
        rid = it.get("routine_id")
        if rid and rid in seen_routine_ids:
            continue
        if rid:
            seen_routine_ids.add(rid)
        count += 1
    return count


def build_title_context(ir: RoutineSpec) -> dict[str, Any]:
    """Compose the full context dict the compiler needs. Pure read-side."""
    state = load_phase_state()
    phase = state.get("current") or (state.get("phases") or ["Phase"])[0]
    phase_start = state.get("current_started") or ir.target_date
    in_phase = count_phase_archetype_routines(phase_start, ir.archetype, ir.target_date)
    total = count_total_performed_workouts()
    return {
        "phase": phase,
        "type_count_in_phase": in_phase + 1,
        "all_time_count": total + 1,
        "phase_started": phase_start,
    }


def format_title(ir: RoutineSpec, ctx: dict[str, Any]) -> str:
    """Render the title from IR + context. Re-entry uses the gentle form."""
    type_label = (ir.archetype or "Session").title()
    if ir.variant == "re_entry":
        title = f"Welcome back · {type_label}"
    else:
        phase = ctx.get("phase", "Phase")
        n = ctx.get("type_count_in_phase", 1)
        y = ctx.get("all_time_count", 1)
        title = f"{phase} - {type_label} - {n} - {y}"
    return title[:MAX_TITLE_CHARS]


def format_why_note(ir: RoutineSpec) -> str:
    """One short plain-language line. No raw metrics, no guilt framing."""
    if ir.variant == "re_entry":
        return "Easing back in after a gap. Take it gently today."
    if ir.variant == "floor":
        return "Floor session — minimum effective dose for a low-energy day."
    rationale_blob = " ".join(ir.rationale).lower()
    if "recovery=red" in rationale_blob or "autoreg=0.6" in rationale_blob:
        return "Recovery red. Deloading today; protect joints."
    if "portfolio guard active" in rationale_blob:
        return "Aerobic base low. Holding strength flat to protect Zone 2."
    if "recovery=yellow" in rationale_blob:
        return "Readiness yellow. Holding steady."
    if "recovery=green" in rationale_blob:
        return "Readiness green. Programmed against weekly volume targets."
    return "Programmed against your recovery and weekly volume."


def _reset_for_tests() -> None:
    global _s3, _ddb_table
    _s3 = None
    _ddb_table = None
