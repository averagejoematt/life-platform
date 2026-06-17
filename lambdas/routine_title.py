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
        _ddb_table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(TABLE_NAME)
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
    obj = _s3_client().get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}training_phases.json")
    return json.loads(obj["Body"].read())


# Performed-workout sources to union for the honest counters. workout_uid
# ("hevy:<id>" / the MacroFactor formula) dedupes the same session arriving via
# more than one pipe so it isn't counted twice in N or Y (work order §1.5).
_PERFORMED_SOURCES = ("hevy", "macrofactor_workouts", "macrofactor_export")
# Variants that are paired with / substitute for a real session — excluded from
# the routine index used to resolve a performed workout's type.
_NON_COUNTING_VARIANTS = ("floor", "re_entry")


def _query_performed(start_date: str) -> list[dict[str, Any]]:
    """Performed workout records on/after start_date across all strength sources.
    Returns the raw items (date + workout_uid + archetype sticker if present).
    Paginates each source. SK form: DATE#YYYY-MM-DD#WORKOUT#<id>."""
    rows: list[dict[str, Any]] = []
    for source in _PERFORMED_SOURCES:
        pk = f"USER#{USER_ID}#SOURCE#{source}"
        last_key = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start_date}"),
                "ProjectionExpression": "#d, workout_uid, archetype, hevy_routine_id",
                "ExpressionAttributeNames": {"#d": "date"},
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            try:
                resp = _table().query(**kwargs)
            except Exception:
                break  # a missing source partition is not an error
            rows.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
    return rows


def _load_routine_index(start_date: str) -> list[dict[str, Any]]:
    """Routine-index rows on/after start_date (archetype + target_date + variant),
    sorted by target_date. Used to resolve a performed workout's type by the
    nearest preceding pushed routine."""
    pk = f"USER#{USER_ID}#SOURCE#routine_index"
    resp = _table().query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").gte(f"DATE#{start_date}"))
    rows = [it for it in resp.get("Items", []) if (it.get("variant") or "") not in _NON_COUNTING_VARIANTS]
    return sorted(rows, key=lambda r: str(r.get("target_date") or ""))


def resolve_archetype(workout: dict[str, Any], index_rows: list[dict[str, Any]]) -> str | None:
    """Resolve a performed workout's session type WITHOUT parsing its title.

    Priority:
      1. a stored `archetype` sticker (if a future ingestion path sets one);
      2. the EXACT routine the workout was performed from — match the workout's
         `hevy_routine_id` (preserved by hevy_common.normalize_workout) against the
         routine-index entry's `hevy_routine_id`. This is unambiguous when present;
      3. else the nearest pushed routine whose target_date <= the workout date.
    Returns None when nothing matches (uncounted)."""
    sticker = workout.get("archetype")
    if sticker:
        return str(sticker)
    # 2. Exact link via the Hevy routine the workout came from.
    hrid = workout.get("hevy_routine_id")
    if hrid:
        for r in index_rows:
            if str(r.get("hevy_routine_id") or "") == str(hrid):
                arch = r.get("archetype")
                return str(arch) if arch else None
    # 3. Fallback: nearest preceding pushed routine by date.
    wdate = str(workout.get("date") or "")
    if not wdate:
        return None
    best = None
    for r in index_rows:  # index_rows sorted ascending by target_date
        td = str(r.get("target_date") or "")
        if td and td <= wdate:
            best = r
        elif td > wdate:
            break
    return str(best.get("archetype")) if best else None


def count_performed_of_type(archetype: str, performed: list[dict[str, Any]], index_rows: list[dict[str, Any]]) -> int:
    """Distinct performed workouts whose resolved type == archetype. Dedupes by
    workout_uid so a cross-source duplicate counts once. Pure — no I/O."""
    seen: set[str] = set()
    count = 0
    for w in performed:
        uid = w.get("workout_uid") or w.get("date")
        if uid in seen:
            continue
        seen.add(str(uid))
        if resolve_archetype(w, index_rows) == archetype:
            count += 1
    return count


def count_distinct_performed(performed: list[dict[str, Any]]) -> int:
    """Distinct performed workouts (deduped by workout_uid). Pure — no I/O."""
    return len({str(w.get("workout_uid") or w.get("date")) for w in performed})


def build_title_context(ir: RoutineSpec) -> dict[str, Any]:
    """Compose the title-context dict (work order 2026-06-16 — supersedes the
    2026-05-31 ADR-067 amendment).

    N — performed workouts of THIS type since the current phase started
        (phase_started_date), +1. Resets when the phase advances; a
        planned-but-skipped session never inflates it (we count performed, not
        pushed). Type is resolved via resolve_archetype (no title parsing).
    Y — performed workouts since reset_epoch_date, +1. Honest, reset-relative —
        skipped sessions don't inflate it; the experiment reset zeroes it.
    """
    state = load_phase_state()
    phase = state.get("current") or (state.get("phases") or ["Phase"])[0]
    phase_started = state.get("current_started") or EXPERIMENT_START_DATE
    reset_epoch = state.get("reset_epoch_date") or EXPERIMENT_START_DATE

    # Load the index from the earlier of the two windows so an early performed
    # workout can still resolve to a routine pushed just before the phase began.
    index_floor = min(str(phase_started), str(reset_epoch))
    index_rows = _load_routine_index(index_floor)

    performed_in_phase = _query_performed(str(phase_started))
    n = count_performed_of_type(ir.archetype, performed_in_phase, index_rows) + 1

    performed_since_reset = performed_in_phase if reset_epoch == phase_started else _query_performed(str(reset_epoch))
    y = count_distinct_performed(performed_since_reset) + 1

    return {
        "phase": phase,
        "type_count_in_phase": n,
        "all_time_count": y,
        "phase_started": phase_started,
        "reset_epoch": reset_epoch,
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
    if getattr(ir, "source_action", "") == "draft_custom":
        # Custom-authored session (ADR-069): surface the user's own first note
        # line rather than a generator-flavored rationale that doesn't apply.
        lines = [ln for ln in (ir.notes or "").splitlines() if ln.strip()]
        return lines[0].strip()[:140] if lines else "Custom session — manually programmed."
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
