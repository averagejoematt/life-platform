"""
routine_generator.py — Deterministic routine generator.

Implements PREREQS §B. No per-day LLM. Inputs are pulled from configs +
caller-supplied state (volume snapshot, recovery, ACWR, z2). Outputs are
RoutineSpec IR records (ideal + floor; re-entry when triggered).

Invariants:
  - Asymmetric autoregulation: red recovery / high ACWR may only SUBTRACT
    load. Add-load is gated by autoreg_add_load_enabled (default false)
    and never increases beyond the MEV baseline anyway.
  - Bounded outputs: session_set_ceiling, session_minutes_ceiling,
    weekly_volume_cap_per_muscle. Hard asserts.
  - Joint-friendly bias: catalog skill_ceiling filter; selection sorts by
    joint_friendly_score then recency.

All randomness is seeded by (target_date + variant) so the same inputs
yield the same routine. Tested via golden + property + cap tests.
"""

from __future__ import annotations

import json
import logging
import os
import random
import uuid
from datetime import date
from typing import Any

from routine_ir import ExerciseBlock, RoutineSpec, Set

logger = logging.getLogger("routine_generator")

CONFIG_DIR = os.environ.get(
    "TRAINING_CONFIG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "config"),
)
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
S3_CONFIG_PREFIX = os.environ.get("TRAINING_CONFIG_S3_PREFIX", "config/")

_s3_loader_client = None


def _load_json(name: str) -> dict[str, Any]:
    """Load a config JSON. Tries local CONFIG_DIR first (tests + bundled
    Lambdas), then falls back to S3 (s3://${S3_BUCKET}/config/<name>) which
    is the Lambda runtime path. Result is not cached here — Lambda warm
    containers naturally cache the parsed dict via the generator caller.
    """
    local = os.path.join(CONFIG_DIR, name)
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}{name}")
    return json.loads(obj["Body"].read())


def _config_hash(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:10]


class GeneratorInputs:
    """Caller-supplied runtime inputs. Keep this thin; everything else is config."""

    def __init__(
        self,
        target_date: str,
        recovery_tier: str = "yellow",  # green | yellow | red
        acwr_flag: str = "safe",  # safe | caution | high | very_high
        volume_7d: dict[str, int] | None = None,  # muscle -> sets completed in last 7d
        z2_minutes_7d: float = 0.0,
        days_since_last_workout: int = 1,
        history_last_dates: dict[str, str] | None = None,  # movement_key -> last YYYY-MM-DD
        add_load_enabled: bool = False,  # SSM gate — default false until N>=30
    ) -> None:
        self.target_date = target_date
        self.recovery_tier = recovery_tier
        self.acwr_flag = acwr_flag
        self.volume_7d = volume_7d or {}
        self.z2_minutes_7d = z2_minutes_7d
        self.days_since_last_workout = days_since_last_workout
        self.history_last_dates = history_last_dates or {}
        self.add_load_enabled = add_load_enabled


def _archetype_for_date(target_date: str, week_cfg: dict[str, Any]) -> str:
    dow = date.fromisoformat(target_date).weekday()
    return week_cfg["schedule"][str(dow)]["archetype"]


def _seeded_random(target_date: str, variant: str) -> random.Random:
    return random.Random(f"{target_date}:{variant}")


def _autoreg_multiplier(recovery: str, acwr_flag: str) -> float:
    if recovery == "red" or acwr_flag in ("high", "very_high"):
        return 0.6
    if recovery == "yellow" or acwr_flag == "caution":
        return 0.85
    return 1.0


def _muscle_budget(
    muscle: str,
    landmarks: dict[str, Any],
    week_cfg: dict[str, Any],
    volume_7d: dict[str, int],
    autoreg: float,
    add_load_enabled: bool,
) -> int:
    mv = landmarks["muscles"][muscle]
    weekly_target = mv["MEV"]
    completed = volume_7d.get(muscle, 0)
    remaining = max(0, weekly_target - completed)
    session_share = remaining // 1 if remaining < weekly_target else weekly_target // 2
    session_share = max(mv["MIN_PER_SESSION"], min(session_share, mv["MAX_PER_SESSION"]))
    capped = min(session_share, week_cfg["weekly_volume_cap_per_muscle"])
    adjusted = int(round(capped * autoreg))
    # add_load_enabled does NOT permit increase past the baseline above; reserved
    # for the validation-pass branch (PREREQS §C). Today this is identity.
    if add_load_enabled:
        adjusted = adjusted  # no-op until validation passes
    return max(0, adjusted)


def _select_movements_for_muscle(
    muscle: str,
    set_count: int,
    catalog: dict[str, Any],
    skill_ceiling: int,
    history_last_dates: dict[str, str],
    rng: random.Random,
    chosen_so_far: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(movement_key, movement_def)] picks for this muscle.

    Selection bias: higher joint_friendly_score first, then least-recently-used,
    then a seeded tiebreaker. Rotation prevents picking the same movement twice
    in the same session.
    """
    if set_count <= 0:
        return []
    candidates = [
        (k, v)
        for k, v in catalog["movements"].items()
        if v.get("primary_muscle") == muscle and v.get("skill_tier", 99) <= skill_ceiling and k not in chosen_so_far
    ]
    if not candidates:
        return []

    def _sort_key(item):
        k, v = item
        last_date = history_last_dates.get(k, "0000-00-00")
        return (-v.get("joint_friendly_score", 0), last_date, rng.random())

    candidates.sort(key=_sort_key)
    # Two-block split when there's room; otherwise one block.
    if set_count >= 6 and len(candidates) >= 2:
        first, second = candidates[0], candidates[1]
        first_sets = (set_count + 1) // 2
        second_sets = set_count - first_sets
        return [(first[0], first[1] | {"_sets": first_sets}), (second[0], second[1] | {"_sets": second_sets})]
    chosen = candidates[0]
    return [(chosen[0], chosen[1] | {"_sets": set_count})]


def _block_from_pick(
    movement_key: str,
    movement_def: dict[str, Any],
    rationale_tag: str,
    note: str = "",
) -> ExerciseBlock:
    set_count = movement_def["_sets"]
    rep_range = movement_def.get("default_rep_range") or {"start": 8, "end": 12}
    sets = [
        Set(
            type="normal",
            rep_range_start=rep_range["start"],
            rep_range_end=rep_range["end"],
        )
        for _ in range(set_count)
    ]
    return ExerciseBlock(
        movement_key=movement_key,
        sets=sets,
        rest_seconds=120,
        notes=note,
        joint_friendly_score=movement_def.get("joint_friendly_score", 3),
        skill_tier=movement_def.get("skill_tier", 1),
        rationale_tag=rationale_tag,
    )


def _build_exercise_note(
    movement_key: str,
    catalog: dict[str, Any],
    history_index: dict[str, list],
    notes_mode: str,
) -> str:
    """ADR-068: deterministic per-exercise note from real workout records.

    No LLM, no math. The hevy_template_id_hint is the lookup key into the
    pre-loaded history_index; render_history_cue formats the facts. AI
    comment hook is wired but currently always None — see ADR-068.
    """
    from exercise_history import history_facts, pick_note, render_history_cue

    template_id = catalog.get("movements", {}).get(movement_key, {}).get("hevy_template_id_hint")
    facts = history_facts(template_id, history_index)
    history_cue = render_history_cue(facts)
    return pick_note(history_cue, ai_comment=None, mode=notes_mode)


def _portfolio_guard(z2_minutes_7d: float, z2_floor: float) -> bool:
    """Returns True if aerobic base is healthy; False means cap strength budget."""
    return z2_minutes_7d >= z2_floor


def _new_routine_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _build_inputs_snapshot(inputs: GeneratorInputs, landmarks: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "volume_7d": dict(inputs.volume_7d),
        "recovery_tier": inputs.recovery_tier,
        "acwr_flag": inputs.acwr_flag,
        "z2_minutes_7d": inputs.z2_minutes_7d,
        "days_since_last_workout": inputs.days_since_last_workout,
        "add_load_enabled": inputs.add_load_enabled,
        "landmarks_hash": _config_hash(landmarks),
        "catalog_hash": _config_hash(catalog),
    }


def generate_routines(inputs: GeneratorInputs) -> list[RoutineSpec]:
    """Returns 1-3 RoutineSpec IR records (ideal, floor, optional re-entry).

    The caller persists, compiles, and pushes. This function is pure (apart from
    config reads) — no DDB, no Hevy.
    """
    landmarks = _load_json("training_landmarks.json")
    catalog = _load_json("movement_catalog.json")
    week_cfg = _load_json("training_week.json")

    archetype = _archetype_for_date(inputs.target_date, week_cfg)
    targets = week_cfg["archetype_targets"].get(archetype, [])
    if archetype in ("rest", "aerobic", "mobility"):
        # Non-lifting day — return a minimal placeholder ideal + floor.
        return _non_lifting_pair(inputs, archetype, week_cfg, landmarks, catalog)

    autoreg = _autoreg_multiplier(inputs.recovery_tier, inputs.acwr_flag)
    z2_ok = _portfolio_guard(inputs.z2_minutes_7d, week_cfg.get("z2_floor_minutes", 90))
    rationale: list[str] = []
    rationale.append(f"archetype={archetype}; autoreg={autoreg:.2f} (recovery={inputs.recovery_tier}, acwr={inputs.acwr_flag})")
    if not z2_ok:
        rationale.append(f"z2 7d={inputs.z2_minutes_7d:.0f} < floor {week_cfg['z2_floor_minutes']}; portfolio guard active")

    skill_ceiling = week_cfg.get("skill_ceiling", 2)
    notes_mode = week_cfg.get("exercise_notes_mode", "one_best_line")
    rng = _seeded_random(inputs.target_date, "ideal")
    budget_used: dict[str, int] = {}
    exercises: list[ExerciseBlock] = []

    # ADR-068: pre-load exercise history once per generation. Pure data;
    # downstream renderers can quote but cannot invent.
    history_index: dict[str, list] = {}
    if notes_mode != "off":
        try:
            from exercise_history import load_recent_history

            history_index = load_recent_history(
                lookback_days=int(week_cfg.get("exercise_notes_lookback_days", 180)),
            )
        except Exception as e:
            logger.warning(f"exercise_history load failed (notes will be empty): {e}")

    for muscle in targets:
        budget = _muscle_budget(muscle, landmarks, week_cfg, inputs.volume_7d, autoreg, inputs.add_load_enabled)
        if not z2_ok:
            budget = min(budget, landmarks["muscles"][muscle]["MEV"] // 2)
        if budget <= 0:
            continue
        picks = _select_movements_for_muscle(
            muscle,
            budget,
            catalog,
            skill_ceiling,
            inputs.history_last_dates,
            rng,
            [b.movement_key for b in exercises],
        )
        muscle_sets = 0
        for movement_key, mdef in picks:
            tag = f"{muscle}_MEV_{landmarks['muscles'][muscle]['MEV']}_remaining_{max(0, landmarks['muscles'][muscle]['MEV'] - inputs.volume_7d.get(muscle, 0))}"
            note = _build_exercise_note(movement_key, catalog, history_index, notes_mode)
            exercises.append(_block_from_pick(movement_key, mdef, tag, note=note))
            muscle_sets += mdef["_sets"]
        budget_used[muscle] = muscle_sets
        rationale.append(f"{muscle}: {muscle_sets} sets ({len(picks)} movements)")

    caps = {
        "total_sets": week_cfg["session_set_ceiling"],
        "session_minutes": week_cfg["session_minutes_ceiling"],
        "weekly_volume_per_muscle": week_cfg["weekly_volume_cap_per_muscle"],
    }
    total_sets = sum(len(e.sets) for e in exercises)
    assert total_sets <= caps["total_sets"], f"BUG: total_sets {total_sets} > cap {caps['total_sets']}"
    est_minutes = total_sets * 3 + len(exercises) * 2
    assert est_minutes <= caps["session_minutes"], f"BUG: est_minutes {est_minutes} > cap {caps['session_minutes']}"

    ideal = RoutineSpec(
        routine_id=_new_routine_id(),
        target_date=inputs.target_date,
        archetype=archetype,
        variant="ideal",
        title=f"{archetype.title()} — {inputs.target_date}",
        notes="\n".join(rationale[:6]),
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="cron_generated",
        status="draft",
        exercises=exercises,
        budget_used=budget_used,
        inputs_snapshot=_build_inputs_snapshot(inputs, landmarks, catalog),
        rationale=rationale,
        caps=caps,
    )

    floor = _make_floor(inputs, archetype, targets, catalog, week_cfg, ideal.routine_id)
    ideal.sibling_routine_id = floor.routine_id
    floor.sibling_routine_id = ideal.routine_id

    result = [ideal, floor]
    if inputs.days_since_last_workout >= week_cfg.get("re_entry_days_threshold", 7):
        result.append(_make_re_entry(inputs, archetype, targets, catalog, week_cfg, ideal.routine_id))
    return result


def _make_floor(
    inputs: GeneratorInputs,
    archetype: str,
    targets: list[str],
    catalog: dict[str, Any],
    week_cfg: dict[str, Any],
    sibling_id: str,
) -> RoutineSpec:
    """≈20-min minimum-effective-dose. One movement per major muscle, machine/DB only."""
    rng = _seeded_random(inputs.target_date, "floor")
    exercises: list[ExerciseBlock] = []
    floor_count = week_cfg.get("floor_session_set_count", 6)
    per_muscle = max(1, floor_count // max(1, len(targets)))
    for muscle in targets[:floor_count]:
        picks = _select_movements_for_muscle(
            muscle,
            per_muscle,
            catalog,
            skill_ceiling=1,
            history_last_dates=inputs.history_last_dates,
            rng=rng,
            chosen_so_far=[b.movement_key for b in exercises],
        )
        for mk, mdef in picks[:1]:  # always one movement per muscle in the floor variant
            tag = f"floor_{muscle}"
            exercises.append(_block_from_pick(mk, mdef, tag))
    return RoutineSpec(
        routine_id=_new_routine_id(),
        target_date=inputs.target_date,
        archetype=archetype,
        variant="floor",
        title=f"Floor — {inputs.target_date}",
        notes="Minimum effective dose, machine/DB only.",
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="floor",
        status="draft",
        sibling_routine_id=sibling_id,
        exercises=exercises,
        budget_used={m: 1 for m in targets[:floor_count]},
        inputs_snapshot={"variant": "floor", "target_minutes": week_cfg.get("floor_session_minutes", 20)},
        rationale=["floor session — programmed for the version of Matthew who shows up tired."],
        caps={"total_sets": floor_count + 2, "session_minutes": week_cfg.get("floor_session_minutes", 20) + 5},
    )


def _make_re_entry(
    inputs: GeneratorInputs,
    archetype: str,
    targets: list[str],
    catalog: dict[str, Any],
    week_cfg: dict[str, Any],
    sibling_id: str,
) -> RoutineSpec:
    """Re-entry after ≥7 days: half the volume, skill_tier 1 only, no make-up volume."""
    rng = _seeded_random(inputs.target_date, "re_entry")
    exercises: list[ExerciseBlock] = []
    for muscle in targets:
        budget = max(1, week_cfg.get("floor_session_set_count", 6) // max(1, len(targets)))
        picks = _select_movements_for_muscle(
            muscle,
            budget,
            catalog,
            skill_ceiling=1,
            history_last_dates=inputs.history_last_dates,
            rng=rng,
            chosen_so_far=[b.movement_key for b in exercises],
        )
        for mk, mdef in picks:
            exercises.append(_block_from_pick(mk, mdef, f"re_entry_{muscle}"))
    return RoutineSpec(
        routine_id=_new_routine_id(),
        target_date=inputs.target_date,
        archetype=archetype,
        variant="re_entry",
        title=f"Re-entry — {inputs.target_date}",
        notes="Re-entry after a break. Deliberately easy. No accumulated guilt-debt.",
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="re_entry",
        status="draft",
        sibling_routine_id=sibling_id,
        exercises=exercises,
        budget_used={m: 1 for m in targets},
        inputs_snapshot={"variant": "re_entry", "days_since_last_workout": inputs.days_since_last_workout},
        rationale=["re-entry mode — Pause-Mode principle applied to programming."],
        caps={"total_sets": 15, "session_minutes": 40},
    )


def _non_lifting_pair(
    inputs: GeneratorInputs,
    archetype: str,
    week_cfg: dict[str, Any],
    landmarks: dict[str, Any],
    catalog: dict[str, Any],
) -> list[RoutineSpec]:
    ideal = RoutineSpec(
        routine_id=_new_routine_id(),
        target_date=inputs.target_date,
        archetype=archetype,
        variant="ideal",
        title=f"{archetype.title()} day — {inputs.target_date}",
        notes={
            "rest": "Full rest day.",
            "aerobic": "Zone 2 work — 45-60 min easy.",
            "mobility": "Mobility / movement quality. Hips, T-spine, ankles.",
        }.get(archetype, ""),
        version=1,
        created_at=_now_iso(),
        created_by="cron",
        source_action="cron_generated",
        status="draft",
        exercises=[],
        budget_used={},
        inputs_snapshot=_build_inputs_snapshot(inputs, landmarks, catalog),
        rationale=[f"non-lifting day: archetype={archetype}"],
        caps={"total_sets": 0, "session_minutes": 60},
    )
    return [ideal]
