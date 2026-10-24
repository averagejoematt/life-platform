"""core_habits.py — THE core-12 calculation set (#5124, M4, epic #5120): pure, no DynamoDB, no clock, no model.

Owner ruling 2026-10-18: the core twelve are the CALCULATION set — the habit score, the character sheet and the
coaches read them — and EVERY other habit is retained (tracked, streaked, visible, never archived or deleted).

The set is the charter's (`config/training_charter.json` `habits.core`, read through `training_charter.charter_value`):
twelve ids, each with a label and a BASIS saying how a day is graded —

  * ``habitify``         the Habitify check-in of the registry entries whose ``core`` flag is the id (the habit
                         registry is owner data in the PROFILE#v1 row, so the charter never names an entry; the
                         owner flags them with scripts/apply_habit_core_flags.py). Done when every member is done,
                         missed when any member is observed not done, unknown otherwise.
  * ``steps``            the day's resolved steps (the caller's `common.metric_truth` read) against the charter value
                         `rule_ref` names (`steps.floor`).
  * ``evening_checkin``  the day's evening check-in row: present is done, absent on an evening the prompt went out is a
                         miss, absent with no prompt is unknown.
  * ``wake_consistency`` `health.wake_consistency.grade_day` against `sleep.wake_time` (#5133) — the ONE grader, never
                         a second definition: on_time is done, off is missed, unknown is unknown.

UNKNOWN, never a miss (ADR-104): an unknown core habit is left out of the score. A day with no known core habit has no
score. ARMED: the set drives the score only once at least one active registry entry carries a ``core`` flag — before
that, the caller keeps the tier-weighted read and this module says so (``armed: False``), so a deploy ahead of the
owner's flagging never scores a day on three derived habits.

The caller owns every read (the day's Habitify reading through `scoring_engine.habitify_reading`, the steps count, the
wake times, the check-in state) and passes it in, which keeps this module importable from the scorer without a cycle.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from training import training_charter

MODULE_VERSION = "core-habits@1.0.0"
DONE, MISSED, UNKNOWN = "done", "missed", "unknown"
BASES = ("habitify", "steps", "evening_checkin", "wake_consistency")
FLAG = "core"  # the habit_registry entry field that names the core id it belongs to

# reading(registry_key, meta) -> the day's value (>= 1 done, < 1 not done) or None when unobserved / not scheduled
Reading = Callable[[str, Mapping[str, Any]], Optional[float]]


def core_spec() -> list[dict[str, Any]]:
    """The charter's core set: one dict per habit (`id`, `label`, `basis`, optional `rule_ref`), in charter order.
    An entry with no id or an unknown basis is dropped; an unreadable charter is an empty list, never a guessed set."""
    raw = training_charter.charter_value("habits.core", default=[]) or []
    out = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e.get("basis") in BASES:
            out.append({k: e[k] for k in ("id", "label", "basis", "rule_ref") if k in e})
    return out


def core_ids(spec: Optional[list[dict[str, Any]]] = None) -> list[str]:
    return [e["id"] for e in (spec if spec is not None else core_spec())]


def flag_of(meta: Any) -> Optional[str]:
    """The registry entry's `core` flag (a core id string), or None."""
    if not isinstance(meta, Mapping):
        return None
    v = meta.get(FLAG)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _active(meta: Any) -> bool:
    return isinstance(meta, Mapping) and meta.get("status") == "active"


def members(registry: Any, spec: Optional[list[dict[str, Any]]] = None) -> dict[str, list[str]]:
    """`{core_id: [registry_key, ...]}` for every HABITIFY-basis core id (an id with no flagged entry maps to [])."""
    spec = spec if spec is not None else core_spec()
    out: dict[str, list[str]] = {e["id"]: [] for e in spec if e["basis"] == "habitify"}
    for key, meta in (registry or {}).items() if isinstance(registry, Mapping) else ():
        f = flag_of(meta)
        if f in out and _active(meta):
            out[f].append(key)
    return out


def is_armed(registry: Any) -> bool:
    """True once any active registry entry carries a `core` flag."""
    return isinstance(registry, Mapping) and any(flag_of(m) and _active(m) for m in registry.values())


def core_keys(registry: Any, spec: Optional[list[dict[str, Any]]] = None) -> set[str]:
    """The registry keys that are members of a habitify-basis core habit (empty when unarmed)."""
    return {k for ks in members(registry, spec).values() for k in ks}


def flag_drift(registry: Any, spec: Optional[list[dict[str, Any]]] = None) -> dict[str, int]:
    """COUNTS only (habit names are owner data): the drift `check_habit_registry_drift.py` reports for the flag.

    core_ids_unflagged   a habitify-basis core id no active registry entry carries
    core_flag_unknown    an entry flagged with an id the charter does not carry, or with a non-habitify id
    core_flag_inactive   an entry flagged core whose status is not active (it can never be read)
    """
    spec = spec if spec is not None else core_spec()
    habitify_ids = {e["id"] for e in spec if e["basis"] == "habitify"}
    reg = registry if isinstance(registry, Mapping) else {}
    flagged = [(flag_of(m), _active(m)) for m in reg.values() if flag_of(m)]
    carried = {f for f, active in flagged if active and f in habitify_ids}
    return {
        "core_ids": len(spec),
        "core_flagged_entries": len(flagged),
        "core_ids_unflagged": len(habitify_ids - carried),
        "core_flag_unknown": sum(1 for f, _ in flagged if f not in habitify_ids),
        "core_flag_inactive": sum(1 for f, active in flagged if not active and f in habitify_ids),
    }


def wakes_from_sleep_rows(rows: Any) -> dict[str, str]:
    """`{YYYY-MM-DD: "HH:MM"}` — each wake-date-keyed sleep row's main-sleep end (`sleep_end`, nap=false is the
    ingest's main sleep) as a PACIFIC clock time, the input `health.wake_consistency` grades. A row whose sk is not a
    bare `DATE#<day>` (an interleaved `#WORKOUT#` sub-record) or whose `sleep_end` does not parse is left out."""
    from common.pacific_time import PACIFIC, parse_iso_utc  # noqa: PLC0415

    out: dict[str, str] = {}
    for r in rows or []:
        if not isinstance(r, Mapping):
            continue
        sk = str(r.get("sk") or "")
        day = sk[5:] if sk.startswith("DATE#") else ""
        if len(day) != 10:
            continue
        ts = parse_iso_utc(r.get("sleep_end"))
        if ts is not None:
            out[day] = ts.astimezone(PACIFIC).strftime("%H:%M")
    return out


def checkin_state(row: Any, prompt_row: Any) -> Optional[bool]:
    """The evening check-in core habit's input: True when the day's row carries every rating, False when it does not
    but the prompt went out that evening (`status == "sent"`), None (unknown) otherwise — a dark channel is no miss."""
    from coach.evening_checkin import FIELDS  # noqa: PLC0415 — the check-in's own field set

    if isinstance(row, Mapping) and all(row.get(f) is not None for f in FIELDS):
        return True
    if isinstance(prompt_row, Mapping) and str(prompt_row.get("status")) == "sent":
        return False
    return None


def read_inputs(day: str, whoop: Any, apple: Any, whoop_window: Any, *, fetch_date: Callable, get_item: Callable) -> dict[str, Any]:
    """The inputs the non-Habitify core habits are graded on, for the scorer's `data["core_inputs"]` — each fail-soft
    to None (unknown), never a miss. The caller owns the reads (`fetch_date(source, day)`, `get_item(Key=...)`).

    steps — THE steps resolver (`common.metric_truth`) over the day's rows; wakes — the wake-date-keyed whoop rows'
    main-sleep ends (the trailing window `health.wake_consistency` anchors on, plus the day); checkin — the day's
    evening check-in row and its prompt ledger row (presence only; no rating leaves this function)."""
    import logging  # noqa: PLC0415

    log = logging.getLogger(__name__)
    out: dict[str, Any] = {"steps": None, "wakes": None, "checkin": None}
    try:
        from common import metric_truth  # noqa: PLC0415

        out["steps"] = metric_truth.resolve_steps({"whoop": whoop, "apple_health": apple}).count
    except Exception as e:  # noqa: BLE001 — an unreadable count is unknown, never a miss
        log.warning("[core-habits] steps unresolved: %s", type(e).__name__)
    try:
        out["wakes"] = wakes_from_sleep_rows(list(whoop_window or []) + ([whoop] if whoop else []))
    except Exception as e:  # noqa: BLE001
        log.warning("[core-habits] wake times unread: %s", type(e).__name__)
    try:
        from coach import evening_checkin as ec  # noqa: PLC0415

        row = fetch_date(ec.SOURCE, day)
        prompt = None if row else (get_item(Key={"pk": ec.LEDGER_PK, "sk": ec.PROMPT_PREFIX + day}) or {}).get("Item")
        out["checkin"] = checkin_state(row, prompt)
    except Exception as e:  # noqa: BLE001
        log.warning("[core-habits] check-in state unread: %s", type(e).__name__)
    return out


def _habitify_state(keys: list[str], registry: Mapping[str, Any], reading: Optional[Reading]) -> str:
    if not keys or reading is None:
        return UNKNOWN
    vals = [reading(k, registry.get(k) or {}) for k in keys]
    if any(v is not None and v < 1 for v in vals):
        return MISSED
    if all(v is not None and v >= 1 for v in vals):
        return DONE
    return UNKNOWN


def _steps_state(entry: Mapping[str, Any], steps: Optional[float]) -> str:
    floor = training_charter.charter_value(str(entry.get("rule_ref") or "steps.floor"))
    if steps is None or isinstance(floor, bool) or not isinstance(floor, (int, float)) or floor <= 0:
        return UNKNOWN
    return DONE if float(steps) >= float(floor) else MISSED


def _checkin_state(checkin: Optional[bool]) -> str:
    return UNKNOWN if checkin is None else (DONE if checkin else MISSED)


def _wake_state(day: Optional[str], wakes: Optional[Mapping[str, Any]]) -> str:
    if not day or wakes is None:
        return UNKNOWN
    from health import wake_consistency  # noqa: PLC0415 — the ONE wake grader (#5133)

    st = wake_consistency.grade_day(day, wakes).get("state")
    return DONE if st == wake_consistency.ON_TIME else MISSED if st == wake_consistency.OFF else UNKNOWN


def grade_day(
    registry: Any,
    *,
    day: Optional[str] = None,
    reading: Optional[Reading] = None,
    steps: Optional[float] = None,
    wakes: Optional[Mapping[str, Any]] = None,
    checkin: Optional[bool] = None,
    spec: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """One day's core-set verdict: each core habit's state, the counts and the score (done / known, 0-100).

    `checkin`: True (answered), False (prompted, not answered), None (unknown). `wakes`: `{YYYY-MM-DD: "HH:MM"}` Pacific
    main-sleep ends, covering the graded day and the anchor window before it. Every input absent reads unknown."""
    spec = spec if spec is not None else core_spec()
    reg = registry if isinstance(registry, Mapping) else {}
    mem = members(reg, spec)
    rows = []
    for e in spec:
        basis = e["basis"]
        if basis == "habitify":
            state = _habitify_state(mem.get(e["id"], []), reg, reading)
        elif basis == "steps":
            state = _steps_state(e, steps)
        elif basis == "evening_checkin":
            state = _checkin_state(checkin)
        else:
            state = _wake_state(day, wakes)
        rows.append({"id": e["id"], "label": e.get("label", e["id"]), "basis": basis, "state": state})
    done = sum(r["state"] == DONE for r in rows)
    missed = sum(r["state"] == MISSED for r in rows)
    known = done + missed
    return {
        "version": MODULE_VERSION,
        "charter_version": training_charter.charter_version(),
        "armed": is_armed(reg),
        "date": day,
        "habits": rows,
        "done": done,
        "missed": missed,
        "known": known,
        "unknown": len(rows) - known,
        "total": len(rows),
        "score": round(done / known * 100) if known else None,
        "missed_labels": [r["label"] for r in rows if r["state"] == MISSED],
    }


def habit_scores_fields(core: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """The `habit_scores` row fields a scored core day carries (plain numbers; the writer casts to Decimal):
    `core_done`, `core_known`, `core_total`, `core_pct` (0..1 over KNOWN, absent when none known), `core_status`
    (`{id: state}`), `missed_core` (labels). Empty when the set is not armed."""
    if not isinstance(core, Mapping) or not core.get("armed"):
        return {}
    out: dict[str, Any] = {
        "core_done": int(core.get("done") or 0),
        "core_known": int(core.get("known") or 0),
        "core_total": int(core.get("total") or 0),
        "core_status": {r["id"]: r["state"] for r in core.get("habits") or [] if isinstance(r, Mapping)},
        "core_charter_version": core.get("charter_version"),
    }
    if out["core_known"]:
        out["core_pct"] = round(out["core_done"] / out["core_known"], 3)
    if core.get("missed_labels"):
        out["missed_core"] = list(core["missed_labels"])
    return {k: v for k, v in out.items() if v is not None}
