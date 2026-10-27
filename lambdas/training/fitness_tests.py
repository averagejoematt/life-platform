"""fitness_tests.py — the fitness test battery: protocol, record, trend, cadence and the test day (#5078, epic #5051).

WHY THIS EXISTS
  Before #5078 the calibration loop measured the scale only: nothing stored or read a fitness test, so
  "is he fitter" was inferred. The owner's direction (2026-10-18, the elite-panel review) is a battery
  on a fixed cadence: a 6-minute walk for distance, a 20-minute bike at RPE 6 for distance, a dead
  hang for time and the assistance an assisted pull-up needs. The tests feed the May tracker (#5073)
  and the coach packet.

EVERY RULE IS CHARTER DATA (`calibration.fitness_tests`, read through `charter_value`): the cadence
(`every_weeks`), each test's machine (`catalog_key`), unit, better direction, duration and how it is
read from Hevy, the protocol version, the grace before a due battery is missed, the order of the test
day and the role that carries it. This module arranges and compares; it never restates a number.

THREE PURE PIECES (the DDB read and write take an injected table; the MCP side is mcp/tools_fitness_tests.py):

  1. THE RECORD — `USER#matthew#SOURCE#fitness_tests / BATTERY#<date>`, one item per battery holding
     one row per test (`value`, `unit`, `protocol_version`, `notes`, `source: explicit`). Owner-only,
     CROSS_PHASE. A battery can be logged a test at a time: a second write on the same date merges.
     Hevy is the second reader (`from_hevy`): a workout titled with `BATTERY_TITLE`, or one that logs
     at least `HEVY_MIN_TESTS` of the tests, is read as a battery; the explicit record wins per test.
  2. TREND + CADENCE — `trend()` gives each test's latest and previous value and the delta in the
     test's better direction. `due()` answers upcoming / due / overdue / missed from the PROGRAM's
     week, never a calendar projection: the due week is the program week that closes each block
     (`block_model`: week_in_block == `rotation.anchors_fixed_weeks`, which `every_weeks` must equal),
     and the state counts program weeks — a week advances only when its session cycle is complete
     AND the floor has passed (`session_sequence`'s week rule), so a stalled program (travel, a
     disruption, a missed week) keeps the battery `upcoming` and never runs it `overdue`. The due
     date is a fact (the ledger's opening day) once the program reaches the week, else the EARLIEST
     day it can (`due_on_is_estimate`). `missed` is the dead-man state (the nightly pre-draft run
     carries the named check). Without a position the date is a calendar estimate that can say
     `upcoming` but never `due`/`overdue`; with nothing, the state is `unknown`, never `upcoming`.
  3. THE TEST DAY — on the due week the charter's `test_day.role` (the lightest day, never a lower
     day) carries the battery: the generator's ideal session cut to the minimum shape (anchors only,
     `split.minimum_session.sets_per_movement` working sets) with the tests placed in `order`.
     A battery already on file for the due week leaves the usual session alone.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

from common.pacific_time import pacific_weekday, parse_day_key, shift_day_key

logger = logging.getLogger(__name__)

ISSUE = "#5078"
VERSION = "fitness-tests@1.0.0"
SOURCE = "fitness_tests"
PK = f"USER#matthew#SOURCE#{SOURCE}"
SK_PREFIX = "BATTERY#"
STORE = f"{PK} / {SK_PREFIX}<YYYY-MM-DD> — CROSS_PHASE (ADR-077), Tier owner-only"

UPCOMING, DUE, OVERDUE, MISSED, UNKNOWN = "upcoming", "due", "overdue", "missed", "unknown"
MEASURED, ABSENT, READ_FAILED = "measured", "absent", "read_failed"
EXPLICIT, HEVY = "explicit", "hevy"

BATTERY_TITLE = "FITNESS TESTS"
"""The title prefix of the drafted test-day routine — and the marker that makes a Hevy workout a battery."""

HEVY_MIN_TESTS = 3
"""An untitled Hevy workout is read as a battery only when it logs at least this many of the tests: a
20-minute ride on its own is cardio, not a test (platform-chosen, #5078)."""

DURATION_TOLERANCE = 0.1
"""A timed test's Hevy set counts when its duration is within ±10 % of the protocol's (platform-chosen)."""

_KG_TO_LB = 2.20462
_NOTE_CHARS = 150  # Hevy cuts a session note at about this many characters


# ── the protocol (charter) ───────────────────────────────────────────────────────────────
def protocol() -> dict[str, Any]:
    """The charter's `calibration.fitness_tests` block ({} when the charter cannot be read)."""
    from training.training_charter import charter_value

    return dict(charter_value("calibration.fitness_tests", {}) or {})


def tests_spec(proto: Optional[Mapping[str, Any]] = None) -> dict[str, dict[str, Any]]:
    """test id -> its protocol row, in the charter's order."""
    p = protocol() if proto is None else proto
    return {k: dict(v) for k, v in (p.get("tests") or {}).items()}


def every_weeks(proto: Optional[Mapping[str, Any]] = None) -> int:
    """The cadence in weeks. Raises when the charter cannot say — a cadence is never guessed."""
    p = protocol() if proto is None else proto
    n = p.get("every_weeks")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"fitness_tests: charter calibration.fitness_tests.every_weeks is {n!r}")
    return n


def _day(s: Any) -> Optional[str]:
    d = parse_day_key(str(s or "")[:10])
    return d.isoformat() if d else None


def _days(a: str, b: str) -> int:
    da, db = parse_day_key(a), parse_day_key(b)
    if da is None or db is None:
        raise ValueError(f"not day keys: {a!r}, {b!r}")
    return (db - da).days


# ── the record ───────────────────────────────────────────────────────────────────────────
def battery_sk(date: str) -> str:
    d = _day(date)
    if d is None:
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    return SK_PREFIX + d


def _value(test_id: str, raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{test_id}: the value must be a number, got {raw!r}") from None
    if v < 0 or v != v:
        raise ValueError(f"{test_id}: the value must be zero or more, got {raw!r}")
    return v


def build_battery_record(
    *,
    date: str,
    results: Mapping[str, Any],
    recorded_at: str,
    notes: Optional[Mapping[str, Any]] = None,
    existing: Optional[Mapping[str, Any]] = None,
    proto: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """One battery item (no `pk`), merged over `existing` (the same date's item, if any). Raises ValueError on
    an unknown test, a non-number, an empty result set or a bad date — the caller refuses, never half-writes."""
    from training.training_charter import charter_version

    p = protocol() if proto is None else proto
    spec = tests_spec(p)
    if not spec:
        raise ValueError("the charter carries no calibration.fitness_tests.tests — nothing to record against")
    sk = battery_sk(date)
    if not results:
        raise ValueError(f"no results given; the tests are {', '.join(spec)}")
    unknown = sorted(set(results) - set(spec))
    if unknown:
        raise ValueError(f"unknown test(s) {unknown}; the tests are {', '.join(spec)}")
    tests: dict[str, Any] = {k: dict(v) for k, v in ((existing or {}).get("tests") or {}).items()}
    for tid, raw in results.items():
        row = {"value": _value(tid, raw), "unit": spec[tid].get("unit"), "protocol_version": p.get("protocol_version"), "source": EXPLICIT}
        note = str((notes or {}).get(tid) or "").strip()
        if note:
            row["notes"] = note[:500]
        tests[tid] = row
    return {
        "sk": sk,
        "date": sk[len(SK_PREFIX) :],
        "tests": tests,
        "protocol_version": p.get("protocol_version"),
        "charter_version": charter_version(),
        "recorded_at": recorded_at,
        "tier": "owner_only",
        "version": VERSION,
    }


# ── Hevy, the second reader ──────────────────────────────────────────────────────────────
def template_ids(movements: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None) -> dict[str, tuple[set[str], str]]:
    """test id -> ({Hevy template ids}, catalog title) from each test's catalog entry."""
    out: dict[str, tuple[set[str], str]] = {}
    for tid, row in tests_spec(proto).items():
        m = movements.get(str(row.get("catalog_key"))) or {}
        ids = {str(m["hevy_template_id_hint"])} if m.get("hevy_template_id_hint") else set()
        out[tid] = (ids, str(m.get("title") or "").strip().lower())
    return out


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _working(sets: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [s for s in sets or [] if str(s.get("type") or s.get("set_type") or "normal").lower() != "warmup"]


def _dur(s: Mapping[str, Any]) -> Optional[float]:
    return _f(s.get("duration_sec") or s.get("duration_seconds"))


def _hevy_value(row: Mapping[str, Any], sets: list[Mapping[str, Any]]) -> Optional[float]:
    """One test's value from one exercise's working sets, by the charter's `hevy_field`."""
    field = row.get("hevy_field")
    hits: list[float] = []
    if field == "distance_m":
        want = _f(row.get("duration_s")) or 0.0
        for s in sets:
            dur, dist = _dur(s), _f(s.get("distance_m") or s.get("distance_meters"))
            if want and dur and dist and abs(dur - want) <= want * DURATION_TOLERANCE:
                hits.append(dist)
        return max(hits) if hits else None
    if field == "duration_sec":
        hits = [d for d in (_dur(s) for s in sets) if d]
        return max(hits) if hits else None
    if field == "weight_lb":
        reps = int(row.get("reps") or 1)
        for s in sets:
            kg = _f(s.get("weight_kg"))
            lb = _f(s.get("weight_lbs")) if kg is None else kg * _KG_TO_LB
            if lb is not None and int(_f(s.get("reps")) or 0) >= reps:
                hits.append(round(lb, 1))
        return min(hits) if hits else None
    return None


def _exercise_test(ex: Mapping[str, Any], ids: Mapping[str, tuple[set[str], str]]) -> Optional[str]:
    tid_ = str(ex.get("template_id") or "")  # the stored shape (hevy_common._normalize_exercise); the wire's key stays in the compiler
    name = str(ex.get("name") or ex.get("title") or "").strip().lower()
    for test_id, (tids, title) in ids.items():
        if (tid_ and tid_ in tids) or (title and name == title):
            return test_id
    return None


def from_hevy(
    items: Iterable[Mapping[str, Any]], movements: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None
) -> dict[str, dict[str, Any]]:
    """{date: {test id: row}} read from Hevy per-workout rows (the stored shape: `exercises[].sets[]` with
    `distance_m`, `duration_sec`, `weight_kg`, `reps`). A workout is a battery when its title carries
    `BATTERY_TITLE` or it logs at least `HEVY_MIN_TESTS` tests; anything else is ordinary training."""
    p = protocol() if proto is None else proto
    spec, ids = tests_spec(p), template_ids(movements, p)
    out: dict[str, dict[str, Any]] = {}
    for it in items or []:
        date = _day(it.get("date") or str(it.get("sk") or "").replace("DATE#", ""))
        if date is None:
            continue
        found: dict[str, Any] = {}
        for ex in it.get("exercises") or []:
            test_id = _exercise_test(ex, ids)
            if test_id is None:
                continue
            v = _hevy_value(spec[test_id], _working(ex.get("sets") or []))
            if v is not None and (test_id not in found or _better(spec[test_id], v, found[test_id]["value"])):
                found[test_id] = {"value": v, "unit": spec[test_id].get("unit"), "protocol_version": None, "source": HEVY}
        titled = BATTERY_TITLE.lower() in str(it.get("workout_name") or it.get("title") or "").lower()
        if found and (titled or len(found) >= HEVY_MIN_TESTS):
            out.setdefault(date, {}).update(found)
    return out


def _better(row: Mapping[str, Any], a: float, b: float) -> bool:
    return a < b if row.get("better") == "lower" else a > b


def batteries(records: Iterable[Mapping[str, Any]] | None, hevy: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every battery, oldest first: `{date, tests, sources}`. The explicit record wins per test; Hevy fills a
    test the record does not carry (and is a battery on its own on a date with no record)."""
    by_date: dict[str, dict[str, Any]] = {}
    for date, tests in (hevy or {}).items():
        by_date.setdefault(date, {}).update({k: dict(v) for k, v in tests.items()})
    for r in records or []:
        date = _day(r.get("date") or str(r.get("sk") or "").replace(SK_PREFIX, ""))
        if date:
            by_date.setdefault(date, {}).update({k: dict(v) for k, v in (r.get("tests") or {}).items()})
    return [
        {"date": d, "tests": t, "sources": sorted({str(row.get("source")) for row in t.values()})} for d, t in sorted(by_date.items()) if t
    ]


# ── trend ────────────────────────────────────────────────────────────────────────────────
def trend(batts: list[Mapping[str, Any]], proto: Optional[Mapping[str, Any]] = None, as_of: Optional[str] = None) -> dict[str, Any]:
    """Per test: latest, previous, delta and whether it moved the better way. A test never logged is `absent`."""
    spec = tests_spec(proto)
    rows = [b for b in batts if as_of is None or str(b.get("date")) <= as_of]
    out: dict[str, Any] = {}
    for tid, row in spec.items():
        hist = [(b["date"], b["tests"][tid]) for b in rows if tid in (b.get("tests") or {})]
        base = {"label": row.get("label"), "unit": row.get("unit"), "better": row.get("better")}
        if not hist:
            out[tid] = {"state": ABSENT, **base, "detail": "never logged"}
            continue
        (ld, lr), prev = hist[-1], (hist[-2] if len(hist) > 1 else None)
        cell: dict[str, Any] = {
            "state": MEASURED,
            **base,
            "latest": {"date": ld, "weekday": pacific_weekday(ld), "value": lr.get("value"), "source": lr.get("source")},
        }
        if prev is None:
            cell.update(previous=None, delta=None, direction="first")
        else:
            pv, lv = float(prev[1]["value"]), float(lr["value"])
            delta = round(lv - pv, 1)
            direction = "same" if delta == 0 else ("better" if _better(row, lv, pv) else "worse")
            cell.update(
                previous={"date": prev[0], "weekday": pacific_weekday(prev[0]), "value": pv, "source": prev[1].get("source")},
                delta=delta,
                direction=direction,
            )
        out[tid] = cell
    return out


# ── cadence ──────────────────────────────────────────────────────────────────────────────
def block_weeks(proto: Optional[Mapping[str, Any]] = None) -> int:
    """The block's length (`block_model.block_weeks()`, the charter's `rotation.anchors_fixed_weeks`) — the battery
    closes each block, so the charter's `every_weeks` must name the same span. Raises when they disagree or either
    is unreadable: a due week is never placed on a guessed block."""
    from training import block_model

    n, every = block_model.block_weeks(), every_weeks(proto)
    if n != every:
        raise ValueError(
            f"fitness_tests: calibration.fitness_tests.every_weeks is {every} but a block is {n} weeks (rotation.anchors_fixed_weeks) "
            "— the battery closes a block, so the charter must name one span"
        )
    return n


def position_from(entry: Optional[Mapping[str, Any]], completed: Optional[Iterable[Mapping[str, Any]]] = None) -> Optional[dict[str, Any]]:
    """The program position the cadence reads, from the session sequence's own ledger: `entry` is
    `session_sequence.next_session(day, rows)`, `completed` its `completed_positions(rows, day)`. Each program
    week's ACTUAL opening day is taken from the ledger (`week_basis.week_opened_on`), never projected."""
    if not entry:
        return None
    basis = entry.get("week_basis") or {}
    openings: dict[int, str] = {}
    for pos in [*(completed or []), entry]:
        w, o = pos.get("week"), _day((pos.get("week_basis") or {}).get("week_opened_on"))
        if isinstance(w, int) and not isinstance(w, bool) and o:
            openings.setdefault(w, o)
    return {
        "week": entry.get("week"),
        "week_opened_on": basis.get("week_opened_on"),
        "floor_days": basis.get("floor_days"),
        "week_openings": openings,
    }


def _earliest_opening(position: Mapping[str, Any], weeks_ahead: int, today: Optional[str]) -> Optional[str]:
    """The EARLIEST day program week `week + weeks_ahead` can open under the week rule (a week advances only when its
    cycle is complete AND >= `floor_days` after the previous advance): a lower bound, never a promise — a stalled
    week moves it later. The next advance is after `today` (today's session belongs to this week)."""
    opened, floor = _day(position.get("week_opened_on")), position.get("floor_days")
    if opened is None or not isinstance(floor, int) or isinstance(floor, bool) or floor < 1 or weeks_ahead < 1:
        return None
    first = shift_day_key(opened, floor)
    if today and _day(today) and first <= today:
        first = shift_day_key(today, 1)
    return shift_day_key(first, floor * (weeks_ahead - 1))


def due_on(
    position: Optional[Mapping[str, Any]],
    battery_dates: Iterable[str],
    proto: Optional[Mapping[str, Any]] = None,
    today: Optional[str] = None,
) -> dict[str, Any]:
    """Which program week the battery is due in, from the PROGRAM's week (never a calendar projection).

    With a position (`position_from`: `{week, week_opened_on, floor_days, week_openings}`): the due weeks are the
    weeks that close a block (`block_model`: week_in_block == block_weeks). A battery dated on/after a due week's
    actual opening minus `early_days_credited` covers it. The answer is the PREVIOUS block's due week when it is
    uncovered (a missed battery stays missed until one is logged), else this week when it closes the block and is
    uncovered, else the next block's. `due_on` is the due week's opening day: a FACT (`due_on_is_estimate` False)
    for a week the program has reached, else the EARLIEST day the program can reach it (an estimate).
    Without a position: the latest battery + `every_weeks` weeks, an estimate; with neither: None."""
    p = protocol() if proto is None else proto
    n = block_weeks(p)
    early = int(p.get("early_days_credited") or 0)
    dates = sorted(d for d in (_day(x) for x in battery_dates) if d)
    latest = dates[-1] if dates else None
    pos = position or {}
    week, opened = pos.get("week"), _day(pos.get("week_opened_on"))
    if isinstance(week, int) and not isinstance(week, bool) and week >= 1 and opened:
        openings = {int(k): v for k, v in ((pos.get("week_openings") or {}).items()) if _day(v)}
        openings.setdefault(week, opened)
        base = {
            "basis": "program_week",
            "latest": latest,
            "program_week": week,
            "block": (week - 1) // n + 1,
            "week_in_block": (week - 1) % n + 1,
            "block_weeks": n,
        }

        def covered(opening: str) -> bool:
            return latest is not None and latest >= shift_day_key(opening, -early)

        this_due = -(-week // n) * n  # the week that closes this block
        prev_due = this_due - n
        if prev_due >= n:
            prev_open = openings.get(prev_due)
            if prev_open is None:
                return {**base, "due_program_week": prev_due, "due_on": None, "due_on_is_estimate": None, "unplaced": prev_due}
            if not covered(prev_open):
                return {**base, "due_program_week": prev_due, "due_on": prev_open, "due_on_is_estimate": False}
        if this_due == week and not covered(opened):
            return {**base, "due_program_week": week, "due_on": opened, "due_on_is_estimate": False}
        target = this_due + (n if this_due == week else 0)
        return {**base, "due_program_week": target, "due_on": _earliest_opening(pos, target - week, today), "due_on_is_estimate": True}
    if latest:
        return {
            "basis": "calendar",
            "latest": latest,
            "due_program_week": None,
            "due_on": shift_day_key(latest, 7 * n),
            "due_on_is_estimate": True,
        }
    return {"basis": "none", "latest": None, "due_program_week": None, "due_on": None, "due_on_is_estimate": None}


def _state(d: Mapping[str, Any], today: str, grace_weeks: int) -> tuple[str, Optional[str]]:
    """(state, detail). On the program basis the state counts PROGRAM weeks: before the due week upcoming, in it due,
    `grace_weeks` program weeks past it overdue, beyond that missed — a stalled program never runs past its due week."""
    if d["basis"] == "program_week":
        if d.get("unplaced") is not None:
            return (
                UNKNOWN,
                f"program week {d['unplaced']}'s opening day is not on the session ledger — the battery cannot be credited to it",
            )
        past = int(d["program_week"]) - int(d["due_program_week"])
        return (UPCOMING if past < 0 else DUE if past == 0 else OVERDUE if past <= grace_weeks else MISSED), None
    if d["basis"] == "calendar" and d.get("due_on") and _days(str(d["due_on"]), today) < 0:
        return UPCOMING, "no program position: the date is the latest battery plus the cadence, an estimate"
    if d["basis"] == "calendar":
        return UNKNOWN, "no program position and the calendar estimate has passed — due/overdue is never claimed without the program's week"
    return UNKNOWN, "no session position and no battery on file — the due week cannot be placed"


def due(
    today: str, position: Optional[Mapping[str, Any]], battery_dates: Iterable[str], proto: Optional[Mapping[str, Any]] = None
) -> dict[str, Any]:
    """`{state upcoming|due|overdue|missed|unknown, due_program_week, due_on, due_on_is_estimate, prompt, ...}` for
    `today` — the prompt and the dead-man read this. The state follows the program's week (`due_on`, `_state`);
    `unknown` when nothing can place the due week or the charter's cadence and block disagree."""
    p = protocol() if proto is None else proto
    day = _day(today)
    try:
        d = due_on(position, battery_dates, p, day)
    except ValueError as e:
        return {"state": UNKNOWN, "prompt": None, "detail": str(e), "due_on": None, "basis": "none", "issue": ISSUE}
    grace = int(p.get("grace_weeks") or 0)
    out = {**d, "every_weeks": every_weeks(p), "grace_weeks": grace, "issue": ISSUE}
    if day is None:
        return {**out, "state": UNKNOWN, "prompt": None, "detail": f"today {today!r} is not a day key"}
    state, detail = _state(d, day, grace)
    labels = ", ".join(str(t.get("label")) for t in tests_spec(p).values())
    prompt = None
    if state in (DUE, OVERDUE, MISSED):
        prompt = (
            f"Fitness battery {state} (program week {d['due_program_week']} closes block {int(d['due_program_week']) // int(d['block_weeks'])}, "
            f"opened {d['due_on']}): {labels}. The test-day draft carries it; log each result with get_exercise_notes action='fitness_test'."
        )
    return {**out, "state": state, "detail": detail, "prompt": prompt}


# ── the owner-channel prompt (#5061's calibration cadence carries it) ────────────────────
CALIBRATION_KIND = "fitness_battery"
"""The battery's row in `training.calibration_cadence`'s block — the ONE prompt path to the owner (the Telegram
event sweep's `detect_calibration`, keyed `CALIB_PROMPT#fitness_battery#<due week opening>`, once per due week)."""

_CALIBRATION_STATE = {UPCOMING: "ok", DUE: "due", OVERDUE: "overdue", MISSED: MISSED, UNKNOWN: UNKNOWN}
"""This module's states in the calibration block's vocabulary. `missed` stays `missed` (NOT the block's `missed_2`):
the battery's dead-man is its own alarm (`fitness-battery-missed`), so the calibration sweep prompts a due or
overdue battery and never raises a second dead-man for it."""


def calibration_row(today: str, cadence: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """`due()`'s answer as a `calibration_cadence` row: `kind`, `state`, `due_on`, `last_logged`, `cycle_start` (the due
    week's ACTUAL opening — the prompt's idempotency stamp; None until the program reaches the week) and `prompt` (due /
    overdue only). Dates and states only, no test value. Pure."""
    from training import calibration_cadence as cc

    p = protocol() if proto is None else proto
    state = str(cadence.get("state") or UNKNOWN)
    fact = cadence.get("due_on_is_estimate") is False and state in (DUE, OVERDUE, MISSED)
    row: dict[str, Any] = {
        "kind": CALIBRATION_KIND,
        "state": _CALIBRATION_STATE.get(state, UNKNOWN),
        "battery_state": state,
        "due_on": cadence.get("due_on"),
        "due_on_is_estimate": cadence.get("due_on_is_estimate"),
        "due_program_week": cadence.get("due_program_week"),
        "last_logged": cadence.get("latest"),
        "cycle_start": cadence.get("due_on") if fact else None,
        "detail": cadence.get("detail"),
        "source": STORE,
        "issue": ISSUE,
        "prompt": None,
    }
    if state in (DUE, OVERDUE) and fact:
        labels = ", ".join(str(t.get("label")) for t in tests_spec(p).values())
        row["prompt"] = (
            f"Fitness tests are {state} (program week {cadence.get('due_program_week')} closes the block, opened {cadence.get('due_on')}): "
            f"{labels}. The test-day draft carries them; log each result with your coach. Last battery {cadence.get('latest') or 'never'}."
        )
        row["prompt_key"] = cc.prompt_key(CALIBRATION_KIND, str(row["cycle_start"]))
    return row


def calibration_row_from_table(table: Any, today: str) -> dict[str, Any]:
    """The battery's calibration row from the lambdas-side reads (no MCP import, so the Telegram sweep can carry it):
    the BATTERY# record on `table`, the block record through `session_sequence.load_block_workouts` and the movement
    catalog. Never raises — a failed read is a `read_failed` row with no prompt (never an empty history)."""
    from training import calibration_cadence as cc

    try:
        from training import session_sequence
        from training.routine_generator import _load_json

        records = load_records(table)
        rows = session_sequence.load_block_workouts(today)
        movements = (_load_json("movement_catalog.json") or {}).get("movements") or {}
        entry = session_sequence.next_session(today, rows)
        position = position_from(entry, session_sequence.completed_positions(rows, today) if entry else None)
        batts = batteries(records, from_hevy(rows, movements))
        return calibration_row(today, due(today, position, [b["date"] for b in batts]))
    except Exception as e:  # noqa: BLE001 — named on the row; the other calibration kinds still answer
        logger.warning(f"fitness_tests: the calibration row read failed ({type(e).__name__})")
        return {"kind": CALIBRATION_KIND, "state": cc.READ_FAILED, "error": type(e).__name__, "prompt": None, "issue": ISSUE}


# ── the test day ─────────────────────────────────────────────────────────────────────────
def test_day_role(proto: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """The engine's role id for the charter's `test_day.role` (program_structure.role_id spelling)."""
    from training import program_structure

    name = ((protocol() if proto is None else proto).get("test_day") or {}).get("role")
    return program_structure.role_id(name) if name else None


def never_on_roles(proto: Optional[Mapping[str, Any]] = None) -> set[str]:
    from training import program_structure

    names = ((protocol() if proto is None else proto).get("test_day") or {}).get("never_on") or []
    return {program_structure.role_id(n) for n in names}


def is_test_day(day_entry: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None) -> bool:
    """True when the served session is the test-day role in a due program week (before any record read)."""
    p = protocol() if proto is None else proto
    role, week = day_entry.get("session_role"), day_entry.get("week")
    try:
        n = block_weeks(p)
    except ValueError:
        return False
    if not role or role != test_day_role(p) or role in never_on_roles(p):
        return False
    return isinstance(week, int) and week >= 1 and week % n == 0  # the week that closes a block (block_model's week_in_block == n)


def test_note(row: Mapping[str, Any]) -> str:
    """A test block's Hevy note (#5428, HEVY_NOTE_STANDARD §3.8): line 1 `Test · ‹the test›`, then the charter's protocol —
    no issue number, no version id (those stay on the rationale tag and the stored battery record)."""
    head = f"Test · {row.get('label')}"
    proto = str(row.get("protocol") or "").strip()
    return f"{head}\n{proto}" if proto else head


def _test_block(test_id: str, row: Mapping[str, Any], movements: Mapping[str, Any]) -> Any:
    from training.routine_ir import ExerciseBlock, Set

    key = str(row.get("catalog_key"))
    m = movements.get(key) or {}
    if row.get("duration_s"):
        sets = [Set(duration_seconds=int(row["duration_s"]))]
    elif row.get("reps"):
        sets = [Set(rep_range_start=int(row["reps"]), rep_range_end=int(row["reps"]))]
    else:
        sets = [Set()]
    return ExerciseBlock(
        movement_key=key,
        sets=sets,
        rest_seconds=120,
        notes=test_note(row),
        joint_friendly_score=int(m.get("joint_friendly_score", 3)),
        skill_tier=int(m.get("skill_tier", 1)),
        rationale_tag=f"fitness_test:{test_id}",
    )


def minimum_shape() -> tuple[int, int]:
    """The charter's minimum session (`split.minimum_session`): (sets_per_movement, max_movements).
    Raises when the charter cannot say — the test day then stays the usual session, never a guessed shape."""
    from training.training_charter import charter_value

    shape = charter_value("split.minimum_session", None)
    sets = shape.get("sets_per_movement") if isinstance(shape, Mapping) else None
    most = shape.get("max_movements") if isinstance(shape, Mapping) else None
    if not (isinstance(sets, int) and isinstance(most, int)) or isinstance(sets, bool) or isinstance(most, bool) or min(sets, most) < 1:
        raise ValueError(f"fitness_tests: charter split.minimum_session is {shape!r}")
    return sets, most


MINIMUM_CUT_REASON = "the tests are the session"


def _minimum_blocks(blocks: list[Any], per_movement: int, max_movements: int) -> list[Any]:
    """The ideal's anchors cut to the minimum shape: warm-ups kept, the first `per_movement` working sets."""
    from training import session_block, warmup_sets

    out: list[Any] = []
    for b in blocks:
        if not str(getattr(b, "rationale_tag", "")).startswith("anchor:") or len(out) >= max_movements:
            continue
        kept, n = [], 0
        for s in b.sets:
            if warmup_sets.is_warmup(s):
                kept.append(s)
            elif n < per_movement:
                kept.append(s)
                n += 1
        b.sets = kept
        # #5428: the cut is the lift's one reason line (standard §3.8), after its effort line; the why stays in the rationale
        b.notes = session_block.add_reason(b.notes, session_block.applied_clause("set_count", working_sets=n, reason=MINIMUM_CUT_REASON))
        out.append(b)
    return out


def session_note(due_info: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None) -> str:
    """The routine's session note (Hevy cuts at ~150 chars) — what the day is and why."""
    p = protocol() if proto is None else proto
    note = f"Fitness tests today, then a short lift. Why: the battery is due this week (every {every_weeks(p)} wk, block end). Log each result."
    return note[:_NOTE_CHARS]


def apply_battery(ideal: Any, movements: Mapping[str, Any], due_info: Mapping[str, Any], proto: Optional[Mapping[str, Any]] = None) -> Any:
    """Turn the test-day role's ideal routine into the battery session, in place: the minimum session plus the
    tests in the charter's `order`. Loads on the kept anchor sets are the ideal's (the load floors hold)."""
    from training import warmup_sets
    from training.training_charter import charter_version

    p = protocol() if proto is None else proto
    lift = _minimum_blocks(list(ideal.exercises), *minimum_shape())
    spec = tests_spec(p)
    order = list(p.get("order") or [*spec, "minimum_session"])
    blocks, unresolved = [], []
    for step in order:
        if step == "minimum_session":
            blocks.extend(lift)
        elif step in spec:
            if str(spec[step].get("catalog_key")) not in movements:
                unresolved.append(f"{step}: catalog key {spec[step].get('catalog_key')!r} not in the movement catalog")
                continue
            blocks.append(_test_block(step, spec[step], movements))
    ideal.exercises = blocks
    ideal.title = f"{BATTERY_TITLE} — {ideal.title}"
    ideal.notes = session_note(due_info, p)
    n_sets = sum(warmup_sets.working_set_count(b.sets) for b in blocks)
    ideal.caps = {**(ideal.caps or {}), "total_sets": max(n_sets, 1)}
    ideal.budget_used = {b.movement_key: warmup_sets.working_set_count(b.sets) for b in blocks}
    ideal.inputs_snapshot = {
        **(ideal.inputs_snapshot or {}),
        "fitness_battery": {
            "tests": [s for s in order if s in spec],
            "protocol_version": p.get("protocol_version"),
            "due": {k: due_info.get(k) for k in ("state", "due_on", "due_on_is_estimate", "due_program_week", "basis")},
            "unresolved": unresolved,
            "charter_version": charter_version(),
            "issue": ISSUE,
        },
    }
    ideal.rationale = [
        f"fitness battery ({ISSUE}): program week {due_info.get('due_program_week')} closes the block, so the test-day role carries "
        "the tests on its minimum session (anchors only) — the lightest day, never a lower day",
        *[f"UNRESOLVED — {u}" for u in unresolved],
        *list(ideal.rationale or []),
    ]
    return ideal


def place_battery(
    routines: list[Any],
    day_entry: Mapping[str, Any],
    records: Optional[list[Mapping[str, Any]]],
    block_workouts: Optional[list[Mapping[str, Any]]],
    movements: Mapping[str, Any],
    proto: Optional[Mapping[str, Any]] = None,
) -> list[Any]:
    """The generator's hook: on a test day whose due week is not yet covered, the ideal becomes the battery.

    `records` None = the explicit record could not be read: the usual session is served and the rationale
    says why (an unknown is never read as 'due')."""
    p = protocol() if proto is None else proto
    if not is_test_day(day_entry, p):
        return routines
    ideal = next((r for r in routines if getattr(r, "variant", None) == "ideal"), None)
    if ideal is None:
        return routines
    if records is None:
        ideal.rationale = [f"fitness battery ({ISSUE}): due week, but the battery record could not be read — the usual session"] + list(
            ideal.rationale or []
        )
        return routines
    dates = [b["date"] for b in batteries(records, from_hevy(block_workouts or [], movements, p))]
    opened = _day((day_entry.get("week_basis") or {}).get("week_opened_on"))
    latest = dates[-1] if dates else None
    if opened is None:
        ideal.rationale = [f"fitness battery ({ISSUE}): due week, but the week's opening day is unknown — the usual session"] + list(
            ideal.rationale or []
        )
        return routines
    if latest is not None and latest >= shift_day_key(opened, -int(p.get("early_days_credited") or 0)):
        ideal.rationale = [f"fitness battery ({ISSUE}): already logged for this block ({latest}) — the usual session"] + list(
            ideal.rationale or []
        )
        return routines
    try:
        minimum_shape()
    except ValueError:
        ideal.rationale = [
            f"fitness battery ({ISSUE}): due week, but UNRESOLVED split.minimum_session in the charter — the usual session"
        ] + list(ideal.rationale or [])
        return routines
    basis = day_entry.get("week_basis") or {}
    position = {"week": day_entry.get("week"), "week_opened_on": opened, "floor_days": basis.get("floor_days")}
    info = due(str(getattr(ideal, "target_date", "")), position, dates, p)
    # this session IS the due week (is_test_day): its opening is a fact, whatever an earlier block's state says
    apply_battery(
        ideal,
        movements,
        {**info, "state": DUE, "due_program_week": day_entry.get("week"), "due_on": opened, "due_on_is_estimate": False},
        p,
    )
    return routines


# ── the store (table injected) ───────────────────────────────────────────────────────────
def load_records(table: Any) -> list[dict[str, Any]]:
    """Every battery record, oldest first. Raises on a failed read — a broken read is never 'no battery'."""
    from common.numeric import decimals_to_float

    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :pfx)",
        "ExpressionAttributeValues": {":pk": PK, ":pfx": SK_PREFIX},
        "ScanIndexForward": True,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(decimals_to_float(i) for i in resp.get("Items") or [])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def load_records_failsoft(table: Any = None) -> Optional[list[dict[str, Any]]]:
    """`load_records` on the generator's table, or None when the read fails (the caller states it)."""
    try:
        if table is None:
            from training import exercise_history

            table = exercise_history._table()
        return load_records(table)
    except Exception as e:  # noqa: BLE001 — None is the stated 'unreadable', never an empty history
        logger.warning(f"fitness_tests: the battery record read failed ({type(e).__name__}: {e})")
        return None


def write_record(table: Any, record: Mapping[str, Any]) -> dict[str, str]:
    """Put one battery item (idempotent per date: a re-write of the date replaces it). Raises on a failed write."""
    from common.numeric import floats_to_decimal

    if not str(record.get("sk") or "").startswith(SK_PREFIX):
        raise ValueError("not a fitness_tests battery record")
    # literal (orphan-gate greppable); == PK
    table.put_item(Item=floats_to_decimal({"pk": "USER#matthew#SOURCE#fitness_tests", **dict(record)}))
    return {"pk": PK, "sk": str(record["sk"])}
