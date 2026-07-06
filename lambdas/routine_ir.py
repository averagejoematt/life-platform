"""
routine_ir.py — Routine-spec Intermediate Representation.

The IR is the system of record for the Hevy routine write-loop. Both front
doors (chat-path authoring and Phase 3 cron) stop at this IR. The Hevy
compiler is the only thing that converts an IR into a Hevy wire payload.

Persisted to DynamoDB as the ROUTINE# partition; serialize() emits a
Decimal-safe dict suitable for boto3.

Schema version is pinned via IR_SCHEMA_VERSION. Bumps require a write-side
migration plan; do not change the integer without updating routine_repo.py.

Per SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31 §3 + PREREQS §B.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

IR_SCHEMA_VERSION = 1


@dataclass
class Set:
    type: str = "normal"
    weight_kg: float | None = None
    reps: int | None = None
    rep_range_start: int | None = None
    rep_range_end: int | None = None
    distance_meters: int | None = None
    duration_seconds: int | None = None
    custom_metric: float | None = None


@dataclass
class ExerciseBlock:
    movement_key: str
    sets: list[Set] = field(default_factory=list)
    superset_id: int | None = None
    rest_seconds: int | None = None
    notes: str = ""
    joint_friendly_score: int = 3
    skill_tier: int = 1
    rationale_tag: str = ""


@dataclass
class RoutineBranch:
    """A first-class branch of a routine (#417 / TR-04).

    A routine can carry an ordered list of branches — e.g. "as-written",
    "easier", "harder" (or the recovery-band GREEN/YELLOW/RED model). Exactly
    one branch is `recommended` (the highlighted default the morning starts on);
    the overnight re-stamp (TR-05) may RE-ORDER or re-flag which branch is
    recommended, but it must never add or remove a branch — every branch stays
    visible and choosable (self-selection is preserved by construction).

    `cue` is a one-line session cue rendered by the compiler into the pushed
    routine's notes (Hevy holds one exercise list per routine, so the branch
    menu lives in the notes field — the only place the write client can carry
    alternatives). `exercises` optionally carries a branch's own set/rep
    content for the front-end / future per-branch push; the wire push renders
    the shared base `RoutineSpec.exercises` plus the annotated branch menu.
    """

    label: str
    cue: str = ""
    recommended: bool = False
    order: int = 0
    rationale: str = ""
    exercises: list[ExerciseBlock] = field(default_factory=list)


@dataclass
class RoutineSpec:
    routine_id: str
    target_date: str
    archetype: str
    variant: str = "ideal"
    title: str = ""
    notes: str = ""
    version: int = 1
    parent_version: int | None = None
    created_at: str = ""
    created_by: str = "chat"
    source_action: str = "draft"
    status: str = "draft"
    sibling_routine_id: str | None = None
    exercises: list[ExerciseBlock] = field(default_factory=list)
    branches: list[RoutineBranch] = field(default_factory=list)
    budget_used: dict[str, int] = field(default_factory=dict)
    inputs_snapshot: dict[str, Any] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    caps: dict[str, int] = field(default_factory=dict)
    hevy_routine_id: str | None = None
    hevy_folder_id: int | None = None
    hevy_updated_at: str | None = None
    hevy_pushed_at: str | None = None
    schema_version: int = IR_SCHEMA_VERSION


def _floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_floats_to_decimal(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    return obj


from numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401


def serialize(ir: RoutineSpec) -> dict[str, Any]:
    """IR -> dict (Decimal-safe; ready for DDB put_item)."""
    return _floats_to_decimal(asdict(ir))


def _exercise_from_raw(raw_ex: dict[str, Any]) -> ExerciseBlock:
    sets = [Set(**s) for s in raw_ex.get("sets", [])]
    ex_data = {k: v for k, v in raw_ex.items() if k != "sets"}
    return ExerciseBlock(sets=sets, **ex_data)


def _branch_from_raw(raw_branch: dict[str, Any]) -> RoutineBranch:
    exercises = [_exercise_from_raw(e) for e in raw_branch.get("exercises", [])]
    b_data = {k: v for k, v in raw_branch.items() if k != "exercises"}
    return RoutineBranch(exercises=exercises, **b_data)


def deserialize(item: dict[str, Any]) -> RoutineSpec:
    """DDB item -> IR. Strips DDB-internal keys (pk/sk/ttl). Decimal-safe."""
    if not item:
        raise ValueError("deserialize() called with empty item")
    data = _decimal_to_float({k: v for k, v in item.items() if k not in ("pk", "sk", "ttl")})
    exercises = [_exercise_from_raw(raw_ex) for raw_ex in data.get("exercises", [])]
    branches = [_branch_from_raw(raw_branch) for raw_branch in data.get("branches", [])]
    base = {k: v for k, v in data.items() if k not in ("exercises", "branches")}
    return RoutineSpec(exercises=exercises, branches=branches, **base)
