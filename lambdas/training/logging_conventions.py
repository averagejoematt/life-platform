"""logging_conventions.py — the owner's two Hevy logging conventions, as data every engine reads (#5373).

THE TWO CONVENTIONS (owner, 2026-10-25, attended — verbatim on #5373)

  * DISTANCE ON A CARRY IS A STEP COUNT. The gym has no distance markings, so on a carry he counts steps and types the
    count into Hevy's yards field. Hevy passes the number through unconverted as `distance_meters`; the platform stores it
    as `distance_m`. On an exercise whose catalog entry says `distance_unit_convention: steps` that number is a step
    count — never metres, never yards — so no reader may sum it into miles or call it a distance.
  * LOAD: TOTAL ON A CARRY, PER HAND ON EVERY OTHER DUMBBELL EXERCISE. On a carry he logs the TOTAL carried (one
    dumbbell in each hand: the sum). On every other dumbbell exercise he logs ONE dumbbell's weight ("2x [n] lb shoulder
    press, I log [n] lb"). `load_convention: total_carried | per_hand` on the catalog entry says which; an entry with no
    field is `as_logged` — the logged number is the whole load moved (a barbell, a machine, one dumbbell held in both
    hands).

WHERE THE FIELDS LIVE
  `config/movement_catalog.json`, per entry. `deploy/build_movement_catalog.py` writes them from `derive_conventions`
  (below) — onto every generated entry, and onto a curated / coach_added entry only where the field is ABSENT, so a value a
  human writes wins. `tests/test_logging_conventions_5373.py` holds every stored value equal to the derivation.

  The derivation, each rule with its reason:
    * `distance_unit_convention: steps` on every Hevy `short_distance_weight` entry (a loaded distance: the farmers walk,
      the suitcase carry, the dumbbell walking lunge). That type is the one where he types a distance under a load, and
      with no markings in the gym every one of those numbers is counted steps.
    * `load_convention: total_carried` on a carry by title (carry / farmer / suitcase).
    * `load_convention: per_hand` on a BILATERAL dumbbell exercise — Hevy equipment `dumbbell` or a dumbbell word in the
      title — unless the title names one implement (`_ONE_IMPLEMENT`: goblet, pullover, single-arm, concentration, ...),
      whose logged weight is already the whole load.

HOW A READER RESOLVES LOAD
  `total_load(weight, convention)`: per_hand x 2 (both dumbbells) when a TOTAL is needed — tonnage, volume; a
  total_carried or as_logged load as it is. A load the engine compares or progresses within ONE exercise stays in the
  logged unit (Hevy takes the per-hand number back) and is LABELLED with `load_label` so no coach reads a per-hand 50 as a
  50-lb total.

THE ESTIMATED DISTANCE (an estimate, labelled as one)
  steps x his stride: the MEDIAN of the apple_health `walking_step_length_in` day values over the 14 completed days before
  the day in question (`trailing_stride`). That is his UNLOADED walking stride, measured by the watch; a loaded carry
  stride is shorter, so the yards are an over-estimate and are rendered "N steps (~X yd, est. from unloaded stride)" —
  never compared to a true distance (ADR-105: the threshold comes from his own history, not a population stride). Fewer
  than `STRIDE_MIN_DAYS` stride days in the window, or a failed read: steps only.

Pure except `catalog_movements()` (the catalog read: local `config/`, else S3 `config/`, fail-soft and cached) and
`load_stride_failsoft()` (one DynamoDB query of the apple_health rows, fail-soft).
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
from typing import Any, Iterable, Optional

from common.hevy_schema import STEP_COUNT_HEVY_TYPES, loaded_distance_shape  # noqa: F401 — re-exported; pure, shared with health.tdee
from common.pacific_time import shift_day_key
from common.repo_config import config_path

logger = logging.getLogger("logging_conventions")

DISTANCE_UNIT_FIELD = "distance_unit_convention"
LOAD_CONVENTION_FIELD = "load_convention"

STEPS = "steps"
TOTAL_CARRIED = "total_carried"
PER_HAND = "per_hand"
AS_LOGGED = "as_logged"
LOAD_CONVENTIONS = (TOTAL_CARRIED, PER_HAND)
"""The two values a catalog entry may carry. `as_logged` is the resolver's answer for an entry with no field; it is never
written into the catalog."""

_CARRY_TITLE = re.compile(r"carry|carries|farmer|suitcase", re.IGNORECASE)
_DUMBBELL_TITLE = re.compile(r"\b(?:dumbbells?|db)\b", re.IGNORECASE)
_ONE_IMPLEMENT = re.compile(
    r"\b(?:single[- ]arm|one[- ]arm|single[- ]hand(?:ed)?|one[- ]hand(?:ed)?|single db|single dumbbell|goblet|pullovers?|"
    r"concentration|side bend|sumo squat)\b",
    re.IGNORECASE,
)
_ONE_IMPLEMENT_TITLES = frozenset({"dumbbell row"})
"""Hevy's standard 'Dumbbell Row' is the one-arm bench row: one dumbbell, its weight the whole load."""

CONVENTIONS_LINE = (
    "Logging conventions (owner): on a carry (the farmers walk) the Hevy 'yards' number is his STEP COUNT (no distance "
    "markings in the gym) and the weight is the TOTAL carried, both hands; every other dumbbell exercise is logged PER HAND "
    "(one dumbbell's weight) — never ask what is in each hand."
)
"""The one line the coach-session skill and the coach context state (#5373 box 4)."""

ROUTINE_NOTE_RULE = "count steps, type the count in yards"
"""The owner's own rule, written back into the carry block's Hevy note (#5373 box 5)."""

STRIDE_FIELD = "walking_step_length_in"
STRIDE_WINDOW_DAYS = 14
STRIDE_MIN_DAYS = 5
"""A median of fewer than five day values is too thin to call his stride — the n >= 5 floor the stored hypothesis bars use
(`prereg_effect.derive_stored_bar`). Below it the line is steps only."""

STRIDE_LABEL = "est. from unloaded stride"
_IN_PER_YD = 36.0


# ── the derivation (the builder writes it; the guard test holds the catalog to it) ──────────────────────────────────────


def _one_implement(title: str) -> bool:
    t = (title or "").strip().lower()
    return t in _ONE_IMPLEMENT_TITLES or bool(_ONE_IMPLEMENT.search(t))


def derive_distance_unit(entry: dict[str, Any]) -> Optional[str]:
    """`steps` for a loaded-distance Hevy type, else None (a distance on any other type is a real distance)."""
    return STEPS if entry.get("hevy_type") in STEP_COUNT_HEVY_TYPES else None


def derive_load_convention(entry: dict[str, Any]) -> Optional[str]:
    """`total_carried` for a carry, `per_hand` for a bilateral dumbbell exercise, else None (as logged)."""
    title = str(entry.get("title") or "")
    if _CARRY_TITLE.search(title):
        return TOTAL_CARRIED
    if (entry.get("equipment") == "dumbbell" or _DUMBBELL_TITLE.search(title)) and not _one_implement(title):
        return PER_HAND
    return None


def derive_conventions(entry: dict[str, Any]) -> dict[str, str]:
    """The convention fields an entry carries — only the ones that apply (an absent field is the default)."""
    out: dict[str, str] = {}
    unit = derive_distance_unit(entry)
    if unit:
        out[DISTANCE_UNIT_FIELD] = unit
    load = derive_load_convention(entry)
    if load:
        out[LOAD_CONVENTION_FIELD] = load
    return out


def distance_unit_of(entry: dict[str, Any]) -> Optional[str]:
    """The entry's stated distance unit, else the derivation's."""
    return entry[DISTANCE_UNIT_FIELD] if DISTANCE_UNIT_FIELD in entry else derive_distance_unit(entry)


def load_convention_of(entry: dict[str, Any]) -> str:
    """The entry's stated load convention, else the derivation's, else `as_logged`."""
    stated = entry.get(LOAD_CONVENTION_FIELD) if LOAD_CONVENTION_FIELD in entry else derive_load_convention(entry)
    return stated if stated in LOAD_CONVENTIONS else AS_LOGGED


# ── the runtime resolver (a stored workout names an exercise by title + template id) ─────────────────────────────────────

_CATALOG: Optional[dict[str, Any]] = None
_BY_TID: dict[str, dict[str, Any]] = {}
_BY_TITLE: dict[str, dict[str, Any]] = {}


def catalog_movements() -> dict[str, Any]:
    """The catalog's movements: the local `config/` copy (tests, scripts), else S3 `config/` (the Lambda runtime — the
    catalog is not staged in the bundle). Cached per process; a failed read is {} with one warning, and every resolver
    then falls back to the derivation over the title and the set shape."""
    if _CATALOG is not None:
        return _CATALOG
    movements: dict[str, Any] = {}
    try:
        local = config_path("movement_catalog.json")
        if os.path.exists(local):
            with open(local, encoding="utf-8") as f:
                movements = dict(json.load(f).get("movements") or {})
        else:
            import boto3  # noqa: PLC0415 — the Lambda path only

            s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
            key = f"{os.environ.get('TRAINING_CONFIG_S3_PREFIX', 'config/')}movement_catalog.json"
            obj = s3.get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key=key)
            movements = dict(json.loads(obj["Body"].read()).get("movements") or {})
    except Exception as e:  # noqa: BLE001 — fail-soft: the derivation still answers
        logger.warning(f"logging_conventions: movement catalog not read ({type(e).__name__}: {e}) — resolving by title and set shape")
    set_catalog(movements)
    return movements


def set_catalog(movements: Optional[dict[str, Any]]) -> None:
    """Install a catalog (a caller that already read it, or a test); None clears the cache so the next read reloads."""
    global _CATALOG
    _BY_TID.clear()
    _BY_TITLE.clear()
    if movements is None:
        _CATALOG = None
        return
    _CATALOG = movements
    for entry in movements.values():
        if not isinstance(entry, dict):
            continue
        tid = str(entry.get("hevy_template_id_hint") or "").strip().upper()
        if tid:
            _BY_TID.setdefault(tid, entry)
        title = str(entry.get("title") or "").strip().lower()
        if title:
            _BY_TITLE.setdefault(title, entry)


def entry_for(name: Any, template_id: Any = None) -> Optional[dict[str, Any]]:
    """The catalog entry for a logged exercise: by template id first, then by exact title."""
    catalog_movements()
    tid = str(template_id or "").strip().upper()
    if tid and tid in _BY_TID:
        return _BY_TID[tid]
    return _BY_TITLE.get(str(name or "").strip().lower())


def _num(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _resolved_entry(name: Any, template_id: Any, sets: Any) -> dict[str, Any]:
    entry = entry_for(name, template_id)
    if entry is not None:
        return entry
    # Not catalogued (an exercise newer than the last catalog build): the derivation over what the log itself shows
    return {"title": str(name or ""), "hevy_type": "short_distance_weight" if loaded_distance_shape(sets) else None}


def distance_unit_for(name: Any, template_id: Any = None, sets: Any = None) -> Optional[str]:
    """`steps` when this logged exercise's distance field is his step count, else None (a real distance)."""
    return distance_unit_of(_resolved_entry(name, template_id, sets))


def is_step_count(name: Any, template_id: Any = None, sets: Any = None) -> bool:
    return distance_unit_for(name, template_id, sets) == STEPS


def load_convention_for(name: Any, template_id: Any = None, sets: Any = None) -> str:
    """`total_carried`, `per_hand` or `as_logged` for this logged exercise."""
    return load_convention_of(_resolved_entry(name, template_id, sets))


def total_load(weight: Any, convention: str) -> float:
    """The TOTAL load moved for a logged weight: a per-hand dumbbell weight counts both hands (x 2); a total-carried or
    as-logged weight is already the total."""
    w = _num(weight) or 0.0
    return w * 2.0 if convention == PER_HAND else w


def load_label(convention: str) -> str:
    """' per hand' / ' total carried' / '' — the suffix after a load figure."""
    return {PER_HAND: " per hand", TOTAL_CARRIED: " total carried"}.get(convention, "")


# ── the stride and the estimated distance ───────────────────────────────────────────────────────────────────────────


def stride_window(day: str) -> tuple[str, str]:
    """The 14 completed days BEFORE `day` (`day` itself excluded: today's watch row is still filling in)."""
    return shift_day_key(day, -STRIDE_WINDOW_DAYS), shift_day_key(day, -1)


def _row_day(row: dict[str, Any]) -> str:
    sk = str(row.get("sk") or "")
    if sk.startswith("DATE#"):
        return sk[5:15]
    return str(row.get("date") or "")[:10]


def trailing_stride(rows: Optional[Iterable[dict[str, Any]]], day: str) -> dict[str, Any]:
    """His stride for `day`: the median `walking_step_length_in` over `stride_window(day)` from apple_health DATE rows.

    `{state, stride_in, n_days, window, field, label, basis}`. `state` is `measured` (a median of >= STRIDE_MIN_DAYS day
    values), `insufficient` (fewer) or `read_failed` (`rows` is None). Only `measured` carries a `stride_in`."""
    start, end = stride_window(day)
    out: dict[str, Any] = {
        "field": STRIDE_FIELD,
        "window": {"start": start, "end": end},
        "label": STRIDE_LABEL,
        "basis": (
            f"median of the watch's daily walking step length over the {STRIDE_WINDOW_DAYS} completed days before {day} — an "
            "UNLOADED stride, so a loaded carry's true distance is likely shorter; an estimate, never a measured distance"
        ),
        "stride_in": None,
        "n_days": 0,
    }
    if rows is None:
        return {**out, "state": "read_failed"}
    by_day: dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = _row_day(r)
        v = _num(r.get(STRIDE_FIELD))
        if d and start <= d <= end and v and v > 0:
            by_day[d] = v
    out["n_days"] = len(by_day)
    if len(by_day) < STRIDE_MIN_DAYS:
        return {**out, "state": "insufficient"}
    return {**out, "state": "measured", "stride_in": round(statistics.median(by_day.values()), 1)}


def estimated_yards(steps: Any, stride: Optional[dict[str, Any]]) -> Optional[int]:
    """steps x stride in whole yards, or None when there is no measured stride."""
    n = _num(steps)
    s = (stride or {}).get("stride_in") if (stride or {}).get("state") == "measured" else None
    if not n or not s:
        return None
    return int(round(n * float(s) / _IN_PER_YD))


def render_steps(steps: Any, stride: Optional[dict[str, Any]]) -> str:
    """'N steps (~X yd, est. from unloaded stride)', or 'N steps' when no stride is measured."""
    n = int(round(_num(steps) or 0))
    yd = estimated_yards(n, stride)
    return f"{n} steps (~{yd} yd, {STRIDE_LABEL})" if yd else f"{n} steps"


def load_stride_failsoft(day: str, table: Any = None) -> dict[str, Any]:
    """`trailing_stride` over one DynamoDB query of the apple_health DATE rows in `stride_window(day)`; a failed read is
    `read_failed` (steps only), never an invented stride."""
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415

        if table is None:
            from training import exercise_history  # noqa: PLC0415 — the training read's one table handle

            table = exercise_history._table()
        user = os.environ.get("USER_ID", "matthew")
        start, end = stride_window(day)
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(f"USER#{user}#SOURCE#apple_health") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
            "ProjectionExpression": "sk, #f",
            "ExpressionAttributeNames": {"#f": STRIDE_FIELD},
        }
        rows: list[dict[str, Any]] = []
        while True:
            resp = table.query(**kwargs)
            rows.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return trailing_stride([r for r in rows if len(str(r.get("sk") or "")) == len("DATE#YYYY-MM-DD")], day)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"logging_conventions: stride read failed ({type(e).__name__}: {e}) — steps only")
        return trailing_stride(None, day)
