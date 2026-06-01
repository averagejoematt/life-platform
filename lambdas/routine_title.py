"""
routine_title.py — Title + WHY-note formatting for Hevy routines
(ADR-067, amended 2026-05-31 — see Commit-A handover for the per-phase ->
all-time-since-experiment-start flip).

Title format:  "<Phase> - <Type> - <N> - <Y>"
  Phase  — current phase name from config/training_phases.json. Decorative
           context only — does NOT bound N anymore.
  Type   — ir.archetype title-cased (Upper, Lower, Full, Aerobic, Mobility…)
  N      — count of *pushed* routines of THIS type since EXPERIMENT_START_DATE
           + 1. Does NOT reset on phase change. 1-based. Phases are now
           narrative markers; the experiment is the anchor.
  Y      — count of *performed* Hevy workouts since EXPERIMENT_START_DATE
           + 1. Same anchor — both counters measure progress within the
           current experiment, not lifetime. Pre-experiment Hevy history
           is preserved in DDB but excluded from these counters.

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

from constants import EXPERIMENT_START_DATE
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


def count_performed_workouts_since(start_date: str) -> int:
    """Performed Hevy workouts in DDB on or after start_date. Paginates."""
    pk = f"USER#{USER_ID}#SOURCE#hevy"
    total = 0
    last_key = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start_date}"),
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


def count_experiment_archetype_routines(
    archetype: str, target_date_exclusive: str
) -> int:
    """Count ROUTINE_INDEX entries with this archetype since EXPERIMENT_START_DATE,
    excluding any with target_date >= target_date_exclusive (the routine being
    committed now). Skips floor/re_entry variants so paired sessions don't
    double-count. ADR-067 amendment: no longer bounded by phase boundary.
    """
    pk = f"USER#{USER_ID}#SOURCE#routine_index"
    resp = _table().query(
        KeyConditionExpression=Key("pk").eq(pk)
        & Key("sk").between(
            f"DATE#{EXPERIMENT_START_DATE}", f"DATE#{target_date_exclusive}"
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
    """Compose the title-context dict.

    Both N and Y are counted since EXPERIMENT_START_DATE (the user's anchor).
    Phase is decorative — it goes into the title for narrative context but
    doesn't reset N. Phase advancement leaves N untouched; users see Push
    sequence continue across Foundation -> Build -> ... .
    """
    state = load_phase_state()
    phase = state.get("current") or (state.get("phases") or ["Phase"])[0]
    in_experiment = count_experiment_archetype_routines(ir.archetype, ir.target_date)
    total = count_performed_workouts_since(EXPERIMENT_START_DATE)
    return {
        "phase": phase,
        "type_count_in_phase": in_experiment + 1,
        "all_time_count": total + 1,
        "experiment_started": EXPERIMENT_START_DATE,
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
