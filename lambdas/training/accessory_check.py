"""accessory_check.py — the computed check: is the accessory layer holding still? (#3755)

Split out of `training.program_structure` (#5069 — the five-day split pushed that module past the
1000-line ceiling, #1665); `program_structure` re-exports `accessory_rotation`, `classify_movement` and
`CARDIO_NAME_HINTS`, so every caller reads them where it always did. The program's own data
(`ANCHORS`, `ROTATION_RULE`, `ACTIVE`, `ISSUE`, `PROGRAM_VERSION`) is read from `program_structure`
at CALL time, never copied — a test that flips `program_structure.ACTIVE` still flips this check.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any


def _ps():
    from training import program_structure

    return program_structure


# ── the computed check: is the accessory layer holding still? ────────────────
# Cardio blocks logged inside a Hevy session are not lifting accessories, and counting
# them would report "diversity" that is really the same treadmill every day. This list is
# deliberately NOT `walking_volume.HEVY_COUNTED_NAMES`: that one answers "does this count
# toward the walking floor" (walking/cycling only, rowing and elliptical excluded on
# purpose), which is a DIFFERENT question from "is this a lifting accessory". Sharing one
# list would create a must-agree seam between two questions that legitimately disagree.
CARDIO_NAME_HINTS: tuple[str, ...] = (
    "treadmill",
    "walking",
    "rucking",
    "running",
    "cycling",
    "stationary bike",
    "air bike",
    "echo bike",
    "assault bike",
    "rowing",
    "elliptical",
    "stair",
    "stretching",
    "mobility",
    "foam roll",
)


def _lower(name: Any) -> str:
    return str(name or "").strip().lower()


def classify_movement(name: str) -> str:
    """`anchor:<family>` | `cardio` | `accessory` for one performed Hevy exercise name.

    Cardio is checked FIRST: the `row` anchor's hint is a substring of 'rowing machine'.
    """
    nl = _lower(name)
    if not nl:
        return "cardio"  # an unnamed block is not evidence of accessory diversity
    if any(hint in nl for hint in CARDIO_NAME_HINTS):
        return "cardio"
    for family, anchor in _ps().ANCHORS.items():
        if any(hint in nl for hint in anchor["hevy_title_hints"]):
            return f"anchor:{family}"
    return "accessory"


def _shift_day(day: str, delta_days: int) -> str:
    """Shift a DATE# day key by whole days — through THE calendar-day parse (#3609: the ISO-parse
    registry is shrink-only, so a day key is never parsed with `date.fromisoformat` here)."""
    from common.pacific_time import parse_day_key

    parsed = parse_day_key(day)
    if parsed is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return (parsed + _dt.timedelta(days=delta_days)).isoformat()


def _boundary_honesty(window_start: str, window_end: str, block_boundaries: list[str] | None) -> str:
    """The honesty line about block boundaries — the days a block's first session was COMPLETED
    (`session_sequence.block_boundaries`, #4110). None = the sequence was not read."""
    lead = f"the {_ps().ROTATION_RULE['window_days']}-day window is {_ps().ROTATION_RULE['window_provenance']}"
    if block_boundaries is None:
        return f"{lead}; the session sequence was not read, so a block boundary inside it is unknown and an addition is reported as drift"
    inside = [d for d in block_boundaries if window_start < d <= window_end]
    if inside:
        return (
            f"{lead}; the session sequence opened a new block on {inside[0]} inside it, so an accessory added from that day "
            "is legitimate, not drift"
        )
    return f"{lead}; the session sequence opened no new block inside it, so an addition here is drift"


def accessory_rotation(
    *,
    window_start: str,
    window_end: str,
    hevy_workouts: list[dict[str, Any]] | None,
    block_boundaries: list[str] | None = None,
) -> dict[str, Any]:
    """The accessory layer over a trailing window, computed from the Hevy record.

    v0.3/v0.4 fix accessories for the block, so the computed verdict is DRIFT: accessories
    performed in the window's trailing 7 days that its earlier days did not carry. `ok`
    is True when nothing was added ("fixed") and False when something was ("drifting").
    Repeats are still counted and reported — as a measurement, not a defect.

    ADR-105: the answer carries its `n` and its window. It is a measurement of what was
    PERFORMED, not a claim about what was programmed.

    `hevy_workouts` is the DDB `USER#matthew#SOURCE#hevy` row shape the MCP readers
    already return: `{"date": "YYYY-MM-DD", "exercises": [{"name": ..., "sets": [...]}]}`.
    Passed in, never fetched here — this module has no I/O, same contract as `plan_engine`.

    `None` means the read RAISED and the verdict is `unknown`. An empty list means the
    window genuinely holds no lifting sessions, which is ALSO `unknown` — a rule over zero
    sessions is vacuously satisfied, and reporting that as `ok` is the #3767 failure
    wearing gym clothes. A window whose earlier half holds no session is `unknown` too:
    there is no prior week to have added anything to.
    """
    window = {"start": window_start, "end": window_end, "days": _ps().ROTATION_RULE["window_days"]}
    base: dict[str, Any] = {
        "rule": _ps().ROTATION_RULE["rule"],
        "rule_provenance": _ps().ROTATION_RULE["provenance"],
        "window": window,
        "program_version": _ps().PROGRAM_VERSION,
        "program_active": _ps().ACTIVE,
    }
    if hevy_workouts is None:
        return {
            **base,
            "ok": None,
            "state": "unknown",
            "n_sessions": None,
            "detail": "the Hevy record could not be read for this window — the accessory layer is unmeasured, not clear",
            "honesty": ["the accessory layer is UNKNOWN: the read failed. Never report an unreadable rule as satisfied."],
        }

    try:
        split_day = _shift_day(window_end, -6)  # the trailing 7 days start here
    except ValueError:
        split_day = window_end
    days_by_movement: dict[str, set[str]] = {}
    anchor_days: dict[str, set[str]] = {}
    cardio_names: set[str] = set()
    sessions = 0
    session_days: set[str] = set()
    early_session_days: set[str] = set()
    for row in hevy_workouts:
        exercises = row.get("exercises") or []
        if not exercises:
            continue
        day = str(row.get("date") or "")[:10]
        if not (window_start <= day <= window_end):
            continue
        sessions += 1
        session_days.add(day)
        if day < split_day:
            early_session_days.add(day)
        for ex in exercises:
            name = _lower(ex.get("name"))
            if not name:
                continue
            kind = classify_movement(name)
            if kind.startswith("anchor:"):
                anchor_days.setdefault(kind.split(":", 1)[1], set()).add(day)
            elif kind == "cardio":
                cardio_names.add(name)
            else:
                days_by_movement.setdefault(name, set()).add(day)

    if sessions == 0:
        return {
            **base,
            "ok": None,
            "state": "unknown",
            "n_sessions": 0,
            "n_session_days": 0,
            "detail": "no lifting sessions in the window — the accessory rule is vacuous here, which is not the same as satisfied",
            "honesty": ["the accessory layer is UNKNOWN: n=0 sessions in the window. A rule with nothing to check is not a pass."],
        }

    repeats = sorted(
        ({"movement": name, "n_days": len(days), "days": sorted(days)} for name, days in days_by_movement.items() if len(days) > 1),
        key=lambda r: (-r["n_days"], r["movement"]),
    )
    added = sorted(name for name, days in days_by_movement.items() if all(d >= split_day for d in days))
    distinct_accessories = len(days_by_movement)
    measurable = bool(early_session_days)
    ok: bool | None = (not added) if measurable else None
    state = "unknown" if not measurable else ("fixed" if ok else "drifting")
    return {
        **base,
        "ok": ok,
        "state": state,
        "n_sessions": sessions,
        "n_session_days": len(session_days),
        "n_early_session_days": len(early_session_days),
        "split_day": split_day,
        "distinct_accessories": distinct_accessories,
        "distinct_movements_total": distinct_accessories + len(anchor_days) + len(cardio_names),
        "anchors_trained": {family: {"n_days": len(days), "days": sorted(days)} for family, days in sorted(anchor_days.items())},
        "anchor_families_missing": sorted(set(_ps().ANCHORS) - set(anchor_days)),
        "added_in_trailing_7d": added,
        "repeats_within_window": repeats,
        "cardio_blocks_excluded": sorted(cardio_names),
        "detail": (
            f"{distinct_accessories} distinct accessory movement(s) over n={sessions} session(s) ({window_start}..{window_end}); "
            + (
                f"{len(added)} added in the trailing 7 days that the prior days did not carry; {len(repeats)} repeated (by design — accessories are fixed for the block)"
                if measurable
                else "no session before the trailing 7 days, so 'added' cannot be measured"
            )
        ),
        "honesty": [
            s
            for s in [
                (
                    None
                    if _ps().ACTIVE
                    else f"the accessory rule is PROPOSED ({_ps().ISSUE}, gate:owner) — this is a measurement of what happened, not a compliance verdict against an approved program"
                ),
                _boundary_honesty(window_start, window_end, block_boundaries),
                (
                    "anchor repeats are EXEMPT by design (progressive overload) — they are reported separately under anchors_trained"
                    if anchor_days
                    else "no anchor pattern was trained in this window at all"
                ),
            ]
            if s
        ],
    }
