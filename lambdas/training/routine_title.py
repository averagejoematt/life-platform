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
           + 1, DERIVED from constants (#3671) — never read from config, so a
           reset zeroes it with no second edit. Pre-experiment Hevy history is
           preserved in DDB but excluded from these counters. (N still anchors
           on `current_started`, which the owner advances by hand: a phase may
           deliberately span cycles.)

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
from common.constants import EXPERIMENT_START_DATE
from common.repo_config import config_dir

from training.legacy_workouts import LEGACY_WORKOUTS_PARTITION  # #4636: the retired partition, named once
from training.routine_ir import RoutineSpec

# Depth-independent default — see common.repo_config (#1653). The literal
# `dirname(__file__)/../config` assumed this module sat directly under the repo root.
CONFIG_DIR = os.environ.get("TRAINING_CONFIG_DIR", config_dir())
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


# #4312: how far before a window the routine index is read so a performed workout can be
# matched to the routine it was STARTED from (`resolve_archetype`, priority 2) — a Hevy routine
# keeps its id across re-runs, so the index row that names its archetype may predate the window.
# One value; `mcp.tools_coach_packet` and the two block-read seams read it from here.
ROUTINE_INDEX_LOOKBACK_DAYS = 90
# The resolution `annotate_routine_archetypes` stores on a read row, and the two `via` values
# that mean the routine is KNOWN (a stored sticker, or the exact Hevy routine the workout was
# started from). The date fallback is a guess about a freestyle log and never counts as exact.
ROUTINE_ARCHETYPE_KEY = "_routine_archetype"
EXACT_ARCHETYPE_SOURCES = ("sticker", "hevy_routine_id")

# Performed-workout sources to union for the honest counters. workout_uid
# ("hevy:<id>" / the MacroFactor formula) dedupes the same session arriving via
# more than one pipe so it isn't counted twice in N or Y (work order §1.5).
_PERFORMED_SOURCES = ("hevy", LEGACY_WORKOUTS_PARTITION, "macrofactor_export")
# Variants that are paired with / substitute for a real session — excluded from
# the routine index used to resolve a performed workout's type.
_NON_COUNTING_VARIANTS = ("floor", "re_entry")
# Upper bound of every `DATE#YYYY-MM-DD…` sort key: '~' (0x7E) sorts after every digit and
# '#', and before nothing a date key can contain — but BELOW `DELETE#`/`QUARANTINE#` (#4643).
_DATE_SK_CEILING = "DATE#~"


def _query_performed(start_date: str) -> list[dict[str, Any]]:
    """Performed workout records on/after start_date across all strength sources.
    Returns the raw items (date + workout_uid + archetype sticker if present).
    Paginates each source. SK form: DATE#YYYY-MM-DD#WORKOUT#<id>.

    The sk range is CLOSED at `DATE#~` (#4643): an open `sk >= DATE#…` also returned every
    non-workout row that sorts after DATE# in the same partition — the hevy DELETE#WORKOUT#
    tombstones ('E' > 'A') — and the projection turned each into an empty item that
    count_distinct_performed counted as one more session (key "None")."""
    rows: list[dict[str, Any]] = []
    for source in _PERFORMED_SOURCES:
        pk = f"USER#{USER_ID}#SOURCE#{source}"
        last_key = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", _DATE_SK_CEILING),
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


def resolve_archetype_source(workout: dict[str, Any], index_rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """(archetype, via) for a performed workout, WITHOUT parsing its title — the one resolver.

    Priority (`via`):
      1. `"sticker"` — a stored `archetype` sticker (if a future ingestion path sets one);
      2. `"hevy_routine_id"` — the EXACT routine the workout was performed from — match the
         workout's `hevy_routine_id` (preserved by hevy_common.normalize_workout) against the
         routine-index entry's `hevy_routine_id`. This is unambiguous when present;
      3. `"nearest_routine_by_date"` — else the nearest pushed routine whose target_date <= the
         workout date (a guess about a freestyle log; #4312 never un-credits a session on it).
    (None, None) when nothing matches (uncounted)."""
    sticker = workout.get("archetype")
    if sticker:
        return str(sticker), "sticker"
    # 2. Exact link via the Hevy routine the workout came from.
    hrid = workout.get("hevy_routine_id")
    if hrid:
        for r in index_rows:
            if str(r.get("hevy_routine_id") or "") == str(hrid):
                arch = r.get("archetype")
                return (str(arch) if arch else None), "hevy_routine_id"
    # 3. Fallback: nearest preceding pushed routine by date.
    wdate = str(workout.get("date") or "")
    if not wdate:
        return None, None
    best = None
    for r in index_rows:  # index_rows sorted ascending by target_date
        td = str(r.get("target_date") or "")
        if td and td <= wdate:
            best = r
        elif td > wdate:
            break
    return (str(best.get("archetype")), "nearest_routine_by_date") if best else (None, None)


def resolve_archetype(workout: dict[str, Any], index_rows: list[dict[str, Any]]) -> str | None:
    """The archetype half of `resolve_archetype_source` (the title counters' read)."""
    return resolve_archetype_source(workout, index_rows)[0]


def annotate_routine_archetypes(rows: list[dict[str, Any]] | None, index_rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Copies of `rows`, each carrying its `resolve_archetype_source` result under
    `ROUTINE_ARCHETYPE_KEY` (`{"archetype", "via"}`), so a pure reader downstream
    (`session_sequence`, `self_added_volume`) can tell an off-program complement from a program
    session without a second resolver or a second index read (#4312). Pure; None passes through."""
    if rows is None:
        return None
    out = []
    for r in rows:
        arch, via = resolve_archetype_source(r, index_rows)
        out.append({**r, ROUTINE_ARCHETYPE_KEY: {"archetype": arch, "via": via}})
    return out


def routine_archetype(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """(archetype, via) an annotated row carries; (None, None) when the routine index was not read."""
    ann = row.get(ROUTINE_ARCHETYPE_KEY) if isinstance(row, dict) else None
    if not isinstance(ann, dict):
        return None, None
    return ann.get("archetype"), ann.get("via")


def annotate_with_routine_index(rows: list[dict[str, Any]] | None, window_start: str) -> list[dict[str, Any]] | None:
    """The I/O seam: read the routine index from `ROUTINE_INDEX_LOOKBACK_DAYS` before
    `window_start` and annotate `rows` (#4312). Raises on a failed index read — a caller that
    cannot tell a Flex complement from a program session must say so, never credit it."""
    from common.pacific_time import shift_day_key

    if rows is None:
        return None
    return annotate_routine_archetypes(rows, _load_routine_index(shift_day_key(window_start, -ROUTINE_INDEX_LOOKBACK_DAYS)))


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
    Y — performed workouts since EXPERIMENT_START_DATE, +1. Honest,
        reset-relative — skipped sessions don't inflate it, and the experiment
        reset zeroes it *by construction* rather than by a second edit (#3671).

    The Y anchor is DERIVED, never read from config (#3671). It used to be a
    hand-maintained `reset_epoch_date` in training_phases.json, which the reset
    pipeline does not own — ADR-077's phase taxonomy classifies DynamoDB
    partitions and has no jurisdiction over config files. That copy therefore
    survived ELEVEN resets stuck at 2026-06-16, and because the file is not
    staged into the Lambda bundle (build_bundle stages only food_vocabulary /
    personas / coaches), the copy the runtime actually read was the one in S3 —
    so re-anchoring the repo copy by hand did not move the live counter either.
    Deriving from EXPERIMENT_START_DATE, which every reset already regenerates
    and which ships in every bundle (#781), removes the second copy instead of
    scheduling a second thing to remember.
    """
    state = load_phase_state()
    phase = state.get("current") or (state.get("phases") or ["Phase"])[0]
    # N's window is the config's `current_started`, DELIBERATELY not floored at
    # genesis: the owner's ruling recorded on #3671 is that a phase advances only
    # when he says so, so a pre-genesis anchor is the real start of a phase he has
    # not advanced — "Pull #3 of Foundation" is the answer he asked N for, even
    # where Foundation spans two cycles. Only Y is reset-relative (#3671).
    phase_started = state.get("current_started") or EXPERIMENT_START_DATE
    reset_epoch = EXPERIMENT_START_DATE

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


# #4064: v0.3's archetype is `full`; the reader-facing type is "Full Body" (the Hevy folder
# name too). Every other archetype keeps its title-cased form.
_TYPE_LABELS = {"full": "Full Body", "full_body": "Full Body"}


def format_title(ir: RoutineSpec, ctx: dict[str, Any]) -> str:
    """Render the title from IR + context. Re-entry uses the gentle form."""
    type_label = _TYPE_LABELS.get((ir.archetype or "").lower()) or (ir.archetype or "Session").title()
    if ir.variant == "re_entry":
        title = f"Welcome back · {type_label}"
    else:
        phase = ctx.get("phase", "Phase")
        n = ctx.get("type_count_in_phase", 1)
        y = ctx.get("all_time_count", 1)
        title = f"{phase} - {type_label} - {n} - {y}"
    return title[:MAX_TITLE_CHARS]


_ROLE_WHY = {
    # v0.4 (#4147) — upper/lower, in order
    "upper_heavy": "Upper heavy: one top set at RPE 7-8 on bench and row, back-offs 10% lighter. Loads hold.",
    "lower_heavy": "Lower heavy: one top set at RPE 7-8 on the squat, back-offs 10% lighter. Loads hold.",
    "upper_volume": "Upper volume: steady sets of 8-12, a few left in the tank. Loads hold.",
    "lower_volume": "Lower volume: steady sets of 8-12, a few left in the tank. Loads hold.",
    # v0.3 (superseded 2026-09-24) — kept so a v0.3 routine still reads right
    "heavy": "Full-body heavy: one top set at RPE 7-8, back-offs 10% lighter. Loads hold.",
    "moderate": "Full-body moderate: steady working sets, 2-3 left in the tank. Loads hold.",
    "heavy_moderate": "Full-body heavy-moderate: two anchors heavy, two moderate. Loads hold.",
    "optional_fourth": "Optional session: only after two green recovery days. Skipping it costs nothing.",
}


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
    # #4064: a program session (v0.4 upper/lower, #4147) says what KIND of day it is before anything else.
    cal = (getattr(ir, "inputs_snapshot", None) or {}).get("calendar") or {}
    if cal.get("deload"):
        return "Deload week: fewer sets, same loads. Leave feeling fresh."
    role_line = _ROLE_WHY.get(str(cal.get("session_role") or ""))
    if role_line:
        return role_line
    if "recovery=yellow" in rationale_blob:
        return "Readiness yellow. Holding steady."
    if "recovery=green" in rationale_blob:
        return "Readiness green. Programmed against weekly volume targets."
    return "Programmed against your recovery and weekly volume."


def _reset_for_tests() -> None:
    global _s3, _ddb_table
    _s3 = None
    _ddb_table = None
