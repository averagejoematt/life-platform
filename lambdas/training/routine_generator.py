"""
routine_generator.py — Deterministic routine generator.

Implements PREREQS §B. No per-day LLM. Inputs are pulled from configs +
caller-supplied state (volume snapshot, recovery, ACWR, z2). Outputs are
RoutineSpec IR records (ideal + floor; re-entry when triggered).

Invariants:
  - Asymmetric autoregulation: red recovery / high ACWR may only SUBTRACT
    load. Add-load is gated by autoreg_add_load_enabled (default false)
    and never increases beyond the MEV baseline anyway.
  - Subtract-only has a FLOOR as well as a ceiling (#3927): the prescribed
    load for a movement is never below the best load already achieved for it
    at the current bodyweight band, unless a documented layoff applies the
    detraining discount. `prescription_floor` derives it, `_enforce_load_floors`
    applies it, and `inputs_snapshot["load_floors"]` records what it did —
    including every movement that got no floor, and why.
  - Bounded outputs: session_set_ceiling, session_minutes_ceiling,
    weekly_volume_cap_per_muscle. Hard asserts.
  - Joint-friendly bias: catalog skill_ceiling filter; selection sorts by
    joint_friendly_score then recency.

All randomness is seeded by (target_date + variant) so the same inputs
yield the same routine. Tested via golden + property + cap tests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from datetime import date
from typing import Any

from common.repo_config import config_dir

from training.band_reference import band_key  # #3927: ONE definition of a bodyweight band
from training.routine_ir import ExerciseBlock, RoutineBranch, RoutineSpec, Set

logger = logging.getLogger("routine_generator")

# Depth-independent default — see common.repo_config (#1653). The literal
# `dirname(__file__)/../config` assumed this module sat directly under the repo root.
CONFIG_DIR = os.environ.get("TRAINING_CONFIG_DIR", config_dir())
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


# ══════════════════════════════════════════════════════════════════════════════
# SUBTRACT-ONLY AUTOREGULATION — the prescription FLOOR (#3927)
# ══════════════════════════════════════════════════════════════════════════════
# Owner ruling, 2026-09-19 (§7 of the owner-private TRAINING_CALIBRATION.md at the
# S3 coaching home): autoregulation subtracts, it never adds. The athlete may take a
# prescribed load DOWN on the day; he is never handed the job of triggering his own
# progression ("if set 1 is <=7.5 go 80" — the live 2026-09-19 incline cue, against a
# 80x8 @RPE9 he had already put on the board on 09-11). A prescription below a load
# already achieved at the CURRENT bodyweight band, with no layoff, is a bug.
#
# The three numbers below are the whole rule, and each says where it comes from:
#   • the band is `band_reference.band_key` — the platform's ONE definition of a
#     bodyweight band (10 lb), reused rather than redefined so the planner and the
#     weight-matched reference cannot drift apart;
#   • the layoff threshold is the platform's OWN re-entry threshold
#     (`training_week.re_entry_days_threshold`, 7d) — the same gap that already makes
#     the generator emit a re-entry variant. Nothing new is invented here;
#   • the detraining discount is the owner's documented 10-15% band. The FLOOR takes
#     the deepest end (15%), because a floor is the lowest load the rule permits — a
#     post-layoff prescription anywhere in 85-100% of best is legal, below 85% is not.
#
# ABSENCE IS ABSENCE (ADR-104). A session whose bodyweight cannot be resolved from a
# real weigh-in inside `BODYWEIGHT_TOLERANCE_DAYS` is not band-matched and does not
# raise the floor; no bodyweight is ever interpolated to make a session countable, and
# a movement with no band-matched history yields NO floor rather than a guessed one.
SUBTRACT_ONLY_RULE = (
    "Autoregulation is subtract-only. The prescribed load IS the floor: take it down on the day if you have to, "
    "never up, and never wait to be asked to progress. A load below one already achieved at this bodyweight band, "
    "with no layoff, is a bug — not conservatism."
)

# The exact international definition, not an approximation — the same factor
# `hevy_common._lbs_to_kg` puts on the wire, so a floor round-trips to the pound
# Matthew actually reads on the dumbbell.
LB_IN_KG = 0.45359237

# The owner's documented detraining band. The floor takes the deepest end.
DETRAINING_DISCOUNT_PCT_RANGE = (10, 15)

# Fallback only — `generate_routines` passes `training_week.re_entry_days_threshold`.
LAYOFF_DAYS_DEFAULT = 7


def _kg_to_lb(kg: float) -> float:
    return kg / LB_IN_KG


def _floor_half_kg(kg: float) -> float:
    """Round DOWN to the nearest 0.5 kg — the precision `exercise_history` already
    renders at. Down, because rounding a floor up would invent load the rule does not
    license; 0.5 kg rather than a plate/dumbbell increment, because equipment
    granularity is an assumption this module has no evidence for."""
    return int(kg * 2) / 2


def _fmt_load(kg: float) -> str:
    lb = _kg_to_lb(kg)
    return f"{lb:.0f} lb" if abs(lb - round(lb)) < 0.05 else f"{lb:.1f} lb"


def band_matched_best(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    as_of: str | None = None,
    tolerance_days: int | None = None,
) -> dict[str, Any]:
    """Best load this movement has ACTUALLY carried at the current bodyweight band.

    Pure: every input is a value the caller already loaded (`load_recent_history`,
    `load_bodyweight_index`). `as_of` excludes sessions on or after the target date —
    a routine authored the night before cannot cite a session that has not happened.

    Returns a dict that always carries `status`, so "no floor" is legible as WHICH
    absence it is (`no_history`, `no_band_matched_history`, `no_current_bodyweight`)
    and never as "no floor needed".
    """
    from training.exercise_history import BODYWEIGHT_TOLERANCE_DAYS, nearest_bodyweight

    tol = BODYWEIGHT_TOLERANCE_DAYS if tolerance_days is None else tolerance_days
    out: dict[str, Any] = {
        "template_id": template_id,
        "band": None,
        "best_kg": None,
        "basis": None,
        "sessions_in_band": 0,
        "sessions_other_band": 0,
        "sessions_unweighed": 0,
        "status": "",
    }
    if not template_id:
        out["status"] = "no_template_id"
        return out
    if not current_weight_lb:
        out["status"] = "no_current_bodyweight"
        return out

    band = band_key(float(current_weight_lb))
    out["band"] = band
    sessions = list((history_index or {}).get(template_id) or [])
    if as_of:
        sessions = [s for s in sessions if str(s.get("date") or "") < as_of]
    if not sessions:
        out["status"] = "no_history"
        return out

    best: dict[str, Any] | None = None
    for s in sessions:
        lbs = nearest_bodyweight(str(s.get("date") or ""), weight_index, tol)
        if lbs is None:
            out["sessions_unweighed"] += 1
            continue
        if band_key(lbs) != band:
            out["sessions_other_band"] += 1
            continue
        out["sessions_in_band"] += 1
        top = float(s.get("top_weight_kg") or 0)
        if top <= 0:
            continue
        if best is None or top > best["weight_kg"]:
            best = {
                "date": str(s.get("date") or ""),
                "weight_kg": top,
                "reps": [int(x.get("reps") or 0) for x in (s.get("sets") or []) if float(x.get("weight_kg") or 0) >= top - 1e-9],
                "bodyweight_lb": round(float(lbs), 1),
            }

    if best is None:
        out["status"] = "no_band_matched_history"
        return out
    out["best_kg"] = best["weight_kg"]
    out["basis"] = best
    out["status"] = "ok"
    return out


def prescription_floor(
    template_id: str | None,
    history_index: dict[str, list],
    weight_index: dict[str, float] | None,
    current_weight_lb: float | None,
    days_since_last_workout: int | None = 1,
    layoff_days: int = LAYOFF_DAYS_DEFAULT,
    as_of: str | None = None,
    tolerance_days: int | None = None,
) -> dict[str, Any]:
    """`band_matched_best` plus the ONE sanctioned subtraction: the layoff discount.

    Without a layoff the floor IS the best achieved load. With one, the floor drops by
    the deepest documented detraining percentage and carries `layoff_reason` — the
    "documented layoff reason" acceptance box 1 requires. There is no other path to a
    floor below an achieved load.
    """
    out = band_matched_best(template_id, history_index, weight_index, current_weight_lb, as_of=as_of, tolerance_days=tolerance_days)
    out.update({"floor_kg": None, "discount_pct": 0, "days_since_last_workout": days_since_last_workout, "layoff_reason": None})
    if out["status"] != "ok":
        return out

    floor = float(out["best_kg"])
    if days_since_last_workout is not None and int(days_since_last_workout) >= int(layoff_days):
        low, deep = DETRAINING_DISCOUNT_PCT_RANGE
        out["discount_pct"] = deep
        out["layoff_reason"] = (
            f"{int(days_since_last_workout)}d since the last logged session (>= the {int(layoff_days)}d re-entry "
            f"threshold) — the documented {low}-{deep}% detraining discount applies, and the floor takes the deepest end."
        )
        # ONLY the discounted floor is rounded. The undiscounted floor is an achieved
        # load and is passed through EXACTLY: a 80 lb dumbbell reaches DDB as
        # 36.28743275485118 kg, and rounding that down to 36.0 would land at 79.4 lb —
        # a floor below the very set it was derived from, which is the defect.
        out["floor_kg"] = _floor_half_kg(floor * (100 - deep) / 100.0)
        return out
    out["floor_kg"] = floor
    return out


def render_floor_cue(floor: dict[str, Any]) -> str:
    """The reader-facing line. Factual only — a load, a date, a bodyweight band.

    Never a conditional: the whole defect is a cue that makes the athlete decide
    whether to 'go for' a number the platform already watched him hit.
    """
    if not floor or floor.get("status") != "ok" or not floor.get("floor_kg"):
        return ""
    basis = floor.get("basis") or {}
    reps = "/".join(str(r) for r in (basis.get("reps") or []))
    got = f"{_fmt_load(float(basis.get('weight_kg') or 0))}"
    if reps:
        got += f" x {reps}"
    cue = f"Floor {_fmt_load(float(floor['floor_kg']))} — you did {got} on {basis.get('date')} at {basis.get('bodyweight_lb')} lb."
    if floor.get("layoff_reason"):
        cue += f" Discounted {floor['discount_pct']}% for the layoff."
    return cue + " Down on the day if you must, never up."


def _set_field(s: Any, name: str, value: Any) -> None:
    if isinstance(s, dict):
        s[name] = value
    else:
        setattr(s, name, value)


def _get_field(s: Any, name: str, default: Any = None) -> Any:
    return s.get(name, default) if isinstance(s, dict) else getattr(s, name, default)


def apply_prescription_floor(sets: list[Any], floor: dict[str, Any]) -> list[str]:
    """Raise every working set to the floor, IN PLACE. Returns one line per correction.

    Works on IR `Set` dataclasses and on plain dicts (the wire/replay shape), because
    the two specimens this exists for are stored routines, not freshly generated ones.
    Warm-ups and non-load sets (distance/duration) are untouched — a floor is a claim
    about working load, and stamping it on a warm-up would be a different lie.
    """
    corrections: list[str] = []
    floor_kg = (floor or {}).get("floor_kg")
    if not floor_kg:
        return corrections
    floor_kg = float(floor_kg)
    for i, s in enumerate(sets or []):
        if str(_get_field(s, "type", "normal") or "normal").lower() == "warmup":
            continue
        if _get_field(s, "distance_meters") or _get_field(s, "duration_seconds"):
            continue
        current = _get_field(s, "weight_kg")
        if current is None:
            _set_field(s, "weight_kg", floor_kg)
            corrections.append(f"set {i + 1}: no load prescribed -> {_fmt_load(floor_kg)} (the floor)")
        elif float(current) < floor_kg - 1e-6:
            corrections.append(f"set {i + 1}: {_fmt_load(float(current))} -> {_fmt_load(floor_kg)} (below the floor)")
            _set_field(s, "weight_kg", floor_kg)
    return corrections


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
    weight_index: dict[str, float] | None = None,
    cardio_index: dict[str, list] | None = None,
    whoop_index: dict[str, list] | None = None,
) -> str:
    """ADR-068: deterministic per-exercise note from real workout records.

    No LLM, no math. The hevy_template_id_hint is the lookup key into the
    pre-loaded history_index; render_history_cue formats the facts. AI
    comment hook is wired but currently always None — see ADR-068.

    #3700: the SAME path now carries cardio. `history_facts` falls through to the cardio
    arm when a template has rides and no weighted sessions, so a cycling block reaches the
    generated routine through this one function rather than a parallel one.
    """
    from training.exercise_history import history_facts, pick_note, render_history_cue

    template_id = catalog.get("movements", {}).get(movement_key, {}).get("hevy_template_id_hint")
    facts = history_facts(template_id, history_index, cardio_index=cardio_index, whoop_index=whoop_index)
    history_cue = render_history_cue(facts, weight_index=weight_index)
    return pick_note(history_cue, ai_comment=None, mode=notes_mode)


def attach_cardio_cues(
    spec: Any,
    catalog: dict[str, Any] | None = None,
    cardio_index: dict[str, list] | None = None,
    whoop_index: dict[str, list] | None = None,
) -> int:
    """Stamp the deterministic cardio cue onto every cardio block of a RoutineSpec (#3700).

    Returns how many blocks were stamped. Idempotent: a block whose note already opens
    with "Last:" is left alone, so re-drafting a routine never stacks cues.

    WHY THIS EXISTS SEPARATELY from `_build_exercise_note`. That function is the ADR-068
    path and now carries cardio too — but `generate_routines`'s selector budgets by
    LANDMARK MUSCLE (`config/training_landmarks.json` names eleven, none of them cardio),
    so it never picks a bike. Matthew's real routines get their `cycling` block through
    `draft_custom`, which builds its blocks from arguments and never reaches
    `_build_exercise_note`. This is the one call that path needs — it loads its own
    indexes, fails soft, and takes no plumbing.

    Indexes are loaded here only when not supplied; a failed load leaves every note
    untouched rather than emptying one.
    """
    exercises = list(getattr(spec, "exercises", None) or [])
    if not exercises:
        return 0
    if catalog is None:
        try:
            catalog = _load_json("movement_catalog.json")
        except Exception as e:  # pragma: no cover - config read
            logger.warning(f"cardio cue: catalog load failed ({e}); notes untouched")
            return 0
    if cardio_index is None:
        try:
            from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_history_indexes

            cardio_index = load_history_indexes(lookback_days=max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS))[1]
        except Exception as e:
            logger.warning(f"cardio cue: history load failed ({e}); notes untouched")
            return 0
    if whoop_index is None:
        try:
            from training.exercise_history import load_whoop_workout_index

            whoop_index = load_whoop_workout_index()
        except Exception as e:
            logger.warning(f"cardio cue: whoop load failed ({e}); cue renders without HR-at-level: {e}")
            whoop_index = {}

    from training.cardio_progression import cardio_cue

    movements = (catalog or {}).get("movements", {})
    stamped = 0
    for ex in exercises:
        key = str(getattr(ex, "movement_key", "") or "")
        tid = movements.get(key, {}).get("hevy_template_id_hint") or (key[5:] if key.startswith("tmpl:") else None)
        if not tid or not (cardio_index or {}).get(tid):
            continue
        cue = cardio_cue(tid, cardio_index, whoop_index)
        if not cue:
            continue
        existing = (getattr(ex, "notes", "") or "").strip()
        if existing.startswith("Last:"):
            continue  # already carries a cue — never stack
        ex.notes = f"{cue} — {existing}" if existing else cue
        stamped += 1
    return stamped


def _enforce_load_floors(
    exercises: list[ExerciseBlock],
    catalog: dict[str, Any],
    history_index: dict[str, list],
    weight_index: dict[str, float],
    target_date: str,
    days_since_last_workout: int | None,
    layoff_days: int,
    rationale: list[str],
) -> dict[str, Any]:
    """Derive and APPLY the prescription floor for every block. Returns the audit dict.

    This is acceptance box 1's enforcement point: one place where a prescribed load is
    compared against what he has already done at this bodyweight, and raised if it is
    lower. It is deliberately the LAST thing that touches load, so nothing downstream
    of it can undercut the floor without going through it.

    The audit dict lands in `inputs_snapshot["load_floors"]` — with the `status` of
    every block, including the ones that got NO floor and why. A silent absence would
    read as "the rule was satisfied"; it usually means the bodyweight or the history
    was missing.
    """
    from training.exercise_history import nearest_bodyweight

    current_lb = nearest_bodyweight(target_date, weight_index)
    audit: dict[str, Any] = {
        "rule": SUBTRACT_ONLY_RULE,
        "current_bodyweight_lb": round(float(current_lb), 1) if current_lb else None,
        "band": band_key(float(current_lb)) if current_lb else None,
        "movements": {},
    }
    if not current_lb:
        audit["status"] = "no_current_bodyweight"
        rationale.append("load floors UNAVAILABLE: no weigh-in within tolerance of the target date — no floor was asserted (#3927)")
        return audit
    audit["status"] = "applied"

    for block in exercises:
        template_id = catalog.get("movements", {}).get(block.movement_key, {}).get("hevy_template_id_hint")
        floor = prescription_floor(
            template_id,
            history_index,
            weight_index,
            current_lb,
            days_since_last_workout=days_since_last_workout,
            layoff_days=layoff_days,
            as_of=target_date,
        )
        corrections = apply_prescription_floor(block.sets, floor)
        cue = render_floor_cue(floor)
        if cue:
            block.notes = f"{block.notes} {cue}".strip() if block.notes else cue
        audit["movements"][block.movement_key] = {
            "status": floor["status"],
            "template_id": template_id,
            "floor_kg": floor.get("floor_kg"),
            "best_kg": floor.get("best_kg"),
            "basis": floor.get("basis"),
            "discount_pct": floor.get("discount_pct"),
            "layoff_reason": floor.get("layoff_reason"),
            "corrections": corrections,
        }
        if corrections:
            rationale.append(f"{block.movement_key}: floor applied — " + "; ".join(corrections))
    return audit


def _portfolio_guard(z2_minutes_7d: float, z2_floor: float) -> bool:
    """Returns True if aerobic base is healthy; False means cap strength budget."""
    return z2_minutes_7d >= z2_floor


def _new_routine_id(*identity: object) -> str:
    """The routine's SEMANTIC id — 32 hex, the shape `uuid4().hex` had (#3115).

    It WAS `uuid.uuid4().hex`, and that is the whole bug: every draft minted a fresh
    `ROUTINE#` partition, so a re-run of the authoring cron or a retried `manage_hevy_
    routine draft` left two independent routines for the same session, and committing
    each POSTed a second routine to Hevy that Matthew had to delete by hand. Nothing
    anywhere deduped on `(target_date, archetype, variant)` — which is what actually
    identifies a programmed session.

    Callers pass the fields that make two drafts the SAME draft: the generator passes
    that triple; `draft_custom` passes the triple plus its hand-authored blocks, because
    two different custom sessions on one day are genuinely two routines.

    A collision is the POINT, not a hazard: `routine_repo.draft_versioned` turns a
    re-draft into a new VERSION of the existing routine and carries its Hevy link
    forward, so the following commit UPDATES the remote routine instead of re-creating it.
    """
    canonical = json.dumps([str(part) for part in identity], separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


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
    weight_index: dict[str, float] = {}
    cardio_index: dict[str, list] = {}
    whoop_index: dict[str, list] = {}
    if notes_mode != "off":
        try:
            from training.exercise_history import (
                DEFAULT_LOOKBACK_DAYS,
                FLOOR_LOOKBACK_DAYS,
                load_history_indexes,
            )

            # #3708 — the floor is enforced HERE, not in the config file.
            # training_week.json is NOT staged into the bundle (build_bundle
            # stages only food_vocabulary/personas/coaches), so the runtime
            # reads the S3 copy — and a stale S3 copy still saying 180 would
            # silently reinstate the defect this issue fixes. Same shape as
            # #3671: derive the guarantee from code that ships in every
            # bundle, and let config widen the window but never narrow it
            # below the floor.
            configured = int(week_cfg.get("exercise_notes_lookback_days", DEFAULT_LOOKBACK_DAYS))
            # #3700 — ONE Query returns both indexes. The cardio one is separate rather
            # than merged so the load-floor pass below cannot start counting zero-weight
            # cycling blocks among a movement's sessions.
            history_index, cardio_index = load_history_indexes(lookback_days=max(configured, FLOOR_LOOKBACK_DAYS))
        except Exception as e:
            logger.warning(f"exercise_history load failed (notes will be empty): {e}")
        # #3708 — bodyweight context for historical cues. Failing this load
        # degrades the cue to a bare date; it never blocks generation and never
        # substitutes a guessed weight.
        try:
            from training.exercise_history import load_bodyweight_index

            weight_index = load_bodyweight_index()
        except Exception as e:
            logger.warning(f"bodyweight index load failed (cues lose the 'at X lb' clause): {e}")
        # #3700 — HR-at-level. Fail-soft in the same shape: without it the cardio cue
        # still renders speed-at-level, and the verdict reports the HR arm as absent by
        # name rather than substituting the day-level (24h) average heart rate.
        try:
            from training.exercise_history import load_whoop_workout_index

            whoop_index = load_whoop_workout_index()
        except Exception as e:
            logger.warning(f"whoop workout index load failed (cardio cue loses HR-at-level): {e}")

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
            note = _build_exercise_note(
                movement_key,
                catalog,
                history_index,
                notes_mode,
                weight_index=weight_index,
                cardio_index=cardio_index,
                whoop_index=whoop_index,
            )
            exercises.append(_block_from_pick(movement_key, mdef, tag, note=note))
            muscle_sets += mdef["_sets"]
        budget_used[muscle] = muscle_sets
        rationale.append(f"{muscle}: {muscle_sets} sets ({len(picks)} movements)")

    # #3927 — the subtract-only pass. Runs AFTER selection, over the same history the
    # notes were rendered from, so the load a block carries and the load its cue quotes
    # cannot disagree. Ideal variant only: `floor`/`re_entry` prescribe no load at all,
    # and a floor stamped on a deliberately-easy variant would be the opposite rule.
    load_floors = _enforce_load_floors(
        exercises,
        catalog,
        history_index,
        weight_index,
        target_date=inputs.target_date,
        days_since_last_workout=inputs.days_since_last_workout,
        layoff_days=int(week_cfg.get("re_entry_days_threshold", LAYOFF_DAYS_DEFAULT)),
        rationale=rationale,
    )

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
        routine_id=_new_routine_id(inputs.target_date, archetype, "ideal"),
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
        inputs_snapshot=_build_inputs_snapshot(inputs, landmarks, catalog) | {"load_floors": load_floors},
        rationale=rationale,
        caps=caps,
    )

    # #3700 — any cardio block in the generated routine carries the deterministic cue.
    # Today the selector above never picks one (it budgets by landmark muscle and none of
    # the eleven is cardio), so this is a no-op on a pure lifting day; it is the SAME call
    # the `draft_custom` path needs, wired here so the generator path can never diverge
    # from it.
    attach_cardio_cues(ideal, catalog=catalog, cardio_index=cardio_index, whoop_index=whoop_index)

    floor = _make_floor(inputs, archetype, targets, catalog, week_cfg, ideal.routine_id)
    ideal.sibling_routine_id = floor.routine_id
    floor.sibling_routine_id = ideal.routine_id

    result = [ideal, floor]
    if inputs.days_since_last_workout >= week_cfg.get("re_entry_days_threshold", 7):
        result.append(_make_re_entry(inputs, archetype, targets, catalog, week_cfg, ideal.routine_id))
    return result


# ── Branch model (#417 / TR-04) ──────────────────────────────────────────────
# The legacy output is a list of separate RoutineSpecs (ideal + floor + optional
# re-entry). emit_branch_model folds that list into ONE primary routine carrying
# first-class `branches`, so the scheduled authoring path pushes a single routine
# whose morning selection is a branch choice rather than three separate routines.
_BRANCH_LABELS = {
    # variant -> (label, recommended, order)
    "ideal": ("as-written", True, 0),
    "floor": ("easier", False, 1),
    "re_entry": ("re-entry", False, 2),
}


def _branch_cue(ir: RoutineSpec) -> str:
    """One-line cue for a branch, taken from the variant's own rationale/notes.

    No invention — the cue quotes the deterministic rationale the generator
    already produced for that variant.
    """
    if ir.rationale:
        return ir.rationale[0]
    if ir.notes:
        return ir.notes.splitlines()[0]
    return ""


def build_branches(routines: list[RoutineSpec]) -> list[RoutineBranch]:
    """Fold generated variant RoutineSpecs into an ordered list of RoutineBranch.

    Each variant becomes one branch carrying its own exercise content; the
    `ideal` variant is the recommended default. Never drops a variant — every
    generated option becomes a visible, choosable branch (self-selection).
    """
    branches: list[RoutineBranch] = []
    for ir in routines:
        label, recommended, order = _BRANCH_LABELS.get(ir.variant, (ir.variant, False, 9))
        branches.append(
            RoutineBranch(
                label=label,
                cue=_branch_cue(ir),
                recommended=recommended,
                order=order,
                rationale=ir.variant,
                exercises=list(ir.exercises),
            )
        )
    return branches


def emit_branch_model(routines: list[RoutineSpec]) -> RoutineSpec | None:
    """Return the primary (ideal) RoutineSpec with its `branches` field populated.

    The scheduled authoring path persists every variant (for the record) but
    pushes only this primary — one routine that carries the full branch menu.
    Returns None when the generator produced nothing. If more than one variant
    exists, the primary's `branches` folds them all in; a lone routine (e.g. a
    non-lifting day) still gets a single as-written branch so the model is
    uniform, but a routine with no siblings and no exercises stays branch-light.
    """
    if not routines:
        return None
    primary = next((r for r in routines if r.variant == "ideal"), routines[0])
    # Only attach branches when there is a genuine choice OR real content to
    # branch — a bare non-lifting placeholder (no exercises, no siblings) keeps
    # backward-compatible behaviour (no branch menu, pushes exactly as before).
    if len(routines) > 1 or primary.exercises:
        primary.branches = build_branches(routines)
    return primary


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
        routine_id=_new_routine_id(inputs.target_date, archetype, "floor"),
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
        routine_id=_new_routine_id(inputs.target_date, archetype, "re_entry"),
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
        routine_id=_new_routine_id(inputs.target_date, archetype, "ideal"),
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
