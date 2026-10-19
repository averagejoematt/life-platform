"""mcp/tools_fitness_tests.py — the fitness test battery's reads, its owner write and its dead-man (#5078).

OWNER-ONLY. `training.fitness_tests` is the pure core; this module does the sanctioned reads and hands
them in:

  record     `USER#matthew#SOURCE#fitness_tests / BATTERY#<date>` (`fitness_tests.load_records`);
  Hevy       the program's block record (`plan_hevy_windows._block_workouts`, the ONE sanctioned Hevy
             read via `tools_strength._read_hevy_all_phases`) — a battery logged in Hevy is read from it;
  position   `session_sequence.next_session` over the same rows — the program week the due week is
             projected from (the block alignment);
  catalog    the movement catalog (`routine_generator._load_json`) — each test's Hevy template id.

THE WRITE rides `get_exercise_notes` (`action='fitness_test'`, a new action on the owner's training-record
tool, like `deload` and `disruption`), so no tool is minted. `action='fitness_tests'` reads the batteries,
the per-test trend and the cadence state with its prompt.

THE DEAD-MAN is a named check on an existing schedule: `nightly_leg()` runs on the nightly pre-draft
(`mcp.nightly_predraft.lambda_entry`, 02:00Z) and emits `LifePlatform/HevyRoutine::FitnessBatteryMissed`
(1 when the cadence state is `missed`, else 0; nothing when the state could not be computed — the run's
own result names that). The alarm on that series is `fitness-battery-missed` (cdk/stacks/mcp_stack.py,
Maximum >= 1 over one day, missing = not breaching, digest); its liveness is the pre-draft's dead-man.

THE PROMPT: `due()['prompt']` is on the read, on the May tracker's fitness section and on the coach
packet's `fitness_tests` field. #5061's owner-channel calibration prompt has not landed; it carries the
instruction (Refs #5078 comment on #5061) to read `cadence()` here rather than a second computation.

NEVER on a published surface: the battery is Tier owner-only (`field_tiers.SOURCE_TIERS`).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from common.pacific_time import pacific_today
from training import fitness_tests as ft

logger = logging.getLogger("fitness_tests")

METRIC_NAMESPACE = "LifePlatform/HevyRoutine"  # the pre-draft's own namespace — no new namespace
METRIC_NAME = "FitnessBatteryMissed"
METRIC_DIMENSIONS = {"Job": "fitness_battery"}


def _movements() -> dict[str, Any]:
    from training.routine_generator import _load_json

    return (_load_json("movement_catalog.json") or {}).get("movements") or {}


def _records() -> list[dict[str, Any]]:
    from mcp.config import table

    return ft.load_records(table)


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:200]


def read_view(today: Optional[str] = None) -> dict[str, Any]:
    """`{batteries, trend, due, states}` as of `today` — every read's state named; a failed record read is
    `read_failed` and NO cadence state is claimed from Hevy alone."""
    from training import session_sequence

    from mcp.plan_hevy_windows import _block_workouts

    day = str(today or pacific_today())[:10]
    states: dict[str, Any] = {}
    try:
        records: Optional[list[dict[str, Any]]] = _records()
        states["record"] = ft.MEASURED if records else ft.ABSENT
    except Exception as e:  # noqa: BLE001 — named below; never an empty history
        records, states["record"] = None, {"state": ft.READ_FAILED, "error": _err(e)}
    position: Optional[dict[str, Any]] = None
    rows: list[dict[str, Any]] = []
    try:
        rows = list(_block_workouts(day) or [])
        entry = session_sequence.next_session(day, rows)
        if entry:
            position = {"week": entry.get("week"), "week_opened_on": (entry.get("week_basis") or {}).get("week_opened_on")}
        states["hevy"] = ft.MEASURED
    except Exception as e:  # noqa: BLE001 — the calendar then places the due week, and says so
        states["hevy"] = {"state": ft.READ_FAILED, "error": _err(e)}
    hevy = ft.from_hevy(rows, _movements())
    batts = ft.batteries(records or [], hevy)
    if records is None:
        cadence = {"state": ft.UNKNOWN, "detail": "the battery record could not be read — no cadence state is claimed"}
    else:
        cadence = ft.due(day, position, [b["date"] for b in batts])
    return {
        "as_of": day,
        "batteries": batts,
        "trend": ft.trend(batts),
        "due": cadence,
        "position": position,
        "reads": states,
        "store": ft.STORE,
        "version": ft.VERSION,
    }


def cadence(today: Optional[str] = None) -> dict[str, Any]:
    """The due state alone — the seam #5061's owner-channel prompt reads."""
    return read_view(today)["due"]


# ── get_exercise_notes actions ───────────────────────────────────────────────────────────
def action_list(args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """action='fitness_tests' — every battery, the per-test trend and the cadence state (OWNER-ONLY)."""
    view = read_view((args or {}).get("today"))
    view["protocol"] = {k: ft.protocol().get(k) for k in ("every_weeks", "protocol_version", "order", "tests", "test_day")}
    view["privacy"] = "owner-only: fitness numbers stay off the site and out of email"
    return view


def _results(args: dict[str, Any]) -> dict[str, Any]:
    results = args.get("results")
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except ValueError:
            results = None
    out = dict(results) if isinstance(results, dict) else {}
    if args.get("test") is not None and args.get("value") is not None:
        out[str(args["test"]).strip()] = args["value"]
    return out


def _existing(date: str) -> Optional[dict[str, Any]]:
    """The same date's battery, read by its exact key (a Query, the store's own reader shape)."""
    from common.numeric import decimals_to_float

    from mcp.config import table

    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk = :sk",
        ExpressionAttributeValues={":pk": ft.PK, ":sk": ft.battery_sk(date)},
    )
    items = resp.get("Items") or []
    return decimals_to_float(items[0]) if items else None


def action_log(args: dict[str, Any]) -> dict[str, Any]:
    """action='fitness_test' — record one or more results for the battery on `date` (default today, Pacific).
    `results` = {test id: value} (or `test` + `value`); `notes` = {test id: text}. A second call on the same
    date merges. Refused, never half-written, on an unknown test or a non-number."""
    from datetime import datetime, timezone

    from mcp.config import table

    date = str(args.get("date") or pacific_today())[:10]
    notes = args.get("notes") if isinstance(args.get("notes"), dict) else None
    try:
        record = ft.build_battery_record(
            date=date,
            results=_results(args),
            notes=notes,
            recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            existing=_existing(date),
        )
    except ValueError as e:
        return {"error": f"refused: {e}", "wrote": False, "tests": list(ft.tests_spec())}
    key = ft.write_record(table, record)
    return {"status": "recorded", "wrote": True, **key, "record": record, "next": "action='fitness_tests' shows the trend and the cadence."}


# ── the dead-man (a named check on the nightly pre-draft run) ────────────────────────────
def emf_line(missed: bool) -> str:
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": METRIC_NAMESPACE,
                        "Dimensions": [sorted(METRIC_DIMENSIONS)],
                        "Metrics": [{"Name": METRIC_NAME, "Unit": "Count"}],
                    }
                ],
            },
            **METRIC_DIMENSIONS,
            METRIC_NAME: 1 if missed else 0,
        }
    )


def nightly_leg(today: Optional[str] = None) -> dict[str, Any]:
    """The fail-soft leg on the nightly pre-draft: the cadence state, logged; the datapoint when it is known.
    Never raises; never changes the pre-draft's outcome. Logs states and dates only (no test values)."""
    try:
        cad = cadence(today)
    except Exception as e:  # noqa: BLE001 — named on the run's result
        logger.warning("[fitness_tests] nightly check failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
    state = cad.get("state")
    if state in (ft.OK, ft.DUE, ft.OVERDUE, ft.MISSED):
        print(emf_line(state == ft.MISSED))
    if state == ft.MISSED:
        logger.warning("[fitness_tests] FITNESS_BATTERY_MISSED due_on=%s", cad.get("due_on"))
    return {"outcome": "checked", "state": state, "due_on": cad.get("due_on"), "basis": cad.get("basis")}


# ── the coach packet's field ─────────────────────────────────────────────────────────────
def packet_value(target_date: str) -> dict[str, Any]:
    """The coach packet's `fitness_tests` field: the trend and the cadence with its prompt (no history list)."""
    view = read_view(target_date)
    return {k: view[k] for k in ("trend", "due", "reads")} | {"batteries_on_file": len(view["batteries"])}
