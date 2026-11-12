"""mcp/exercise_gates_leg.py — the exercise library's weekly gate evaluation: reads, store, announce-once (#5772). OWNER-ONLY.

`training.exercise_gates` is the pure core (library gates -> unlocked / locked from measured inputs); this module does the
sanctioned reads, hands them in, writes the owner-only rows and serves the one announcement line.

WHERE IT RUNS (the #5575 owner ruling: a new weekly evaluator rides an EXISTING weekly job — no new Lambda, schedule or
IAM). It is a third fail-soft leg on the Monday panel grade (`mcp.panel_weekly_grade.lambda_entry`, rule
`PanelWeeklyGrade` on `life-platform-mcp-warmer`), beside the phase evaluator, so the week it evaluates is the
Monday-Sunday week that run grades. The function's role already holds table-wide `dynamodb:GetItem/Query/PutItem/
UpdateItem` and `s3:GetObject` on `config/*` (the library overlay). The leg never changes the grade's status or datapoint.

THE READS (each names its failure; an unread input locks the gates it feeds, said so)
  library   `training.exercise_library.load_library()` (the bundled `config/exercise_library.json`);
  overlay   `training.exercise_library.load_private_overlay()` (owner-private S3; None -> the overlay-fed gates lock);
  charter   `training_charter.load_charter()` (the run gate, the lower-leg-prep carve-out, the power-clean weight);
  weight    the Withings partition -> `phase_evaluator_leg.weight_checkpoints` (the trailing 7-day mean at the Sunday);
  Hevy      ONE `tools_strength._read_hevy_all_phases` read over the chain lookback (sessions, sets, RPE, notes);
  run gate  `phase_evaluator_leg.run_gate_read` — the May tracker's reading, as the phase evaluator reads it.

THE ROWS — `USER#matthew#SOURCE#training_constraints` (Tier 2 owner-only, CROSS_PHASE; docs/SCHEMA.md):
  `EXGATE#EVAL#<monday>`                        one per evaluated week (a re-run overwrites it), written LAST;
  `EXGATE#ANNOUNCE#<movement>#<gate>[+<gate>]`  the claim-once record of a newly unlocked movement: created once
                                                (`attribute_not_exists`), `status` pending -> announced exactly once by
                                                `plan_next_session` stage 1 (a conditional update; the claimant prints it).
Announcement rows are created only while the library is `approved` — a PROPOSED library is evaluated and recorded, but
nothing reaches the drafting path until the owner approves it (#5769's rule). Logs carry gate ids, states and counts —
never a bodyweight, a threshold or a load.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from training import exercise_gates as eg

logger = logging.getLogger("exercise_gates")

SK_EVAL = "EXGATE#EVAL#"
SK_ANNOUNCE = "EXGATE#ANNOUNCE#"
PENDING, ANNOUNCED = "pending", "announced"
APPROVED = "approved"


def _pk(user_id: str = "matthew") -> str:
    from training import phase_evaluator as pe

    return pe.pk(user_id)


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:200]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(table: Any) -> Any:
    if table is not None:
        return table
    from mcp.config import table as _t

    return _t


# ── the reads ───────────────────────────────────────────────────────────────────────────────────────────────────────
def gather(week_start: str, week_end: str) -> tuple[dict[str, Any], dict[str, Any], Optional[dict[str, Any]], dict[str, Any]]:
    """(library, measured, overlay, reads ledger). The library is required (raises); every other read is fail-soft."""
    from training import exercise_library as xl
    from training.training_charter import load_charter

    from mcp import core
    from mcp.phase_evaluator_leg import run_gate_read, weight_checkpoints

    reads: dict[str, Any] = {}

    def _read(name: str, fn, *a):
        try:
            out = fn(*a)
            reads[name] = "ok"
            return out
        except Exception as e:  # noqa: BLE001 — named on the row; the gates it feeds lock as unknown
            logger.warning("[exercise_gates] %s read failed (%s)", name, type(e).__name__)
            reads[name] = f"read_failed: {_err(e)}"
            return None

    library = xl.load_library()
    overlay = xl.load_private_overlay()
    reads["overlay"] = "ok" if isinstance(overlay, dict) else "unread"
    charter = _read("charter", load_charter)
    oldest = eg._shift(week_end, -(eg.CHAIN_LOOKBACK_DAYS - 1))
    wrows = _read("withings", core.query_source, "withings", eg._shift(week_end, -13), week_end)
    hevy = _hevy(_read, oldest, week_end)
    run_gate = _read("run_gate", _run_gate, week_end, wrows, hevy, run_gate_read, _read)
    bw = weight_checkpoints(wrows, [week_end])[0]
    measured = {
        "as_of": week_end,
        "bodyweight": {"mean_lb": bw.get("mean_lbs"), "state": bw.get("state")},
        "hevy_workouts": hevy,
        "run_gate": run_gate,
        "charter": charter or None,
    }
    return library, measured, overlay, reads


def _hevy(_read, oldest: str, week_end: str) -> Optional[list[dict[str, Any]]]:
    from training.run_onramp import history_from

    from mcp.tools_strength import _read_hevy_all_phases

    out = _read("hevy", _read_hevy_all_phases, min(oldest, history_from() or oldest), week_end)
    return None if out is None else list(out[0] or [])


def _run_gate(week_end: str, wrows, hevy, run_gate_read, _read) -> Optional[dict[str, Any]]:
    """The run gate exactly as the phase evaluator reads it (strava + the owner's dismissals when a pain note exists)."""
    from mcp import core
    from mcp.tools_may_tracker import pain_instances
    from mcp.tools_plan import _pain_dismissals

    if hevy is None:
        return None
    strava = _read("strava", core.query_source_range, "strava", eg._shift(week_end, -55), week_end)
    dismissals = _read("pain_dismissals", _pain_dismissals) if pain_instances(hevy) else None
    return run_gate_read(week_end, wrows, None if strava is None else list(strava), hevy, dismissals)


# ── the store ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _put(table: Any, item: dict[str, Any], condition: Optional[str] = None) -> None:
    """The phase evaluator's put (ADR-077 stamp, floats -> Decimal), plus an optional create-once condition."""
    from decimal import Decimal

    from experiment.phase_taxonomy import experiment_stamp_for

    item = {**item, **experiment_stamp_for(item["pk"], item["sk"])}
    kwargs: dict[str, Any] = {"Item": json.loads(json.dumps(item, default=str), parse_float=Decimal)}
    if condition:
        kwargs["ConditionExpression"] = condition
    table.put_item(**kwargs)


def _plain(item: Any) -> Any:
    return json.loads(json.dumps(item, default=float)) if item is not None else None


def previous_eval(table: Any, before_sk: str, user_id: str = "matthew") -> Optional[dict[str, Any]]:
    """The newest EVAL row strictly before `before_sk` (None when this is the first). Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(_pk(user_id)) & Key("sk").between(SK_EVAL, before_sk), ScanIndexForward=False, Limit=2
    )
    for item in resp.get("Items") or []:
        if item.get("sk") != before_sk:
            return _plain(item)
    return None


def announce_sk(movement_id: str, gates: list[str]) -> str:
    """The claim-once key: gate + movement. A different gate set on the same movement is a different unlock."""
    return f"{SK_ANNOUNCE}{movement_id}#{'+'.join(sorted(gates))}"


def announcement_line(title: str, gates: list[str], week_start: str, cues: list[str]) -> str:
    cue = f" Cue: {cues[0]}" if cues else ""
    return f"Newly unlocked: {title} — its gates ({', '.join(sorted(gates))}) are met as of the week of {week_start}.{cue}"


def create_announcements(table: Any, library: dict[str, Any], states: dict[str, Any], fresh: list[dict[str, Any]], week_start: str):
    """Create each pending claim-once row; an existing row (already pending or announced) is left alone. -> created sks."""
    from botocore.exceptions import ClientError

    created = []
    movements = library.get("movements") or {}
    for u in fresh:
        mid, gates = u["movement_id"], u["gates"]
        sk = announce_sk(mid, gates)
        item = {
            "pk": _pk(),
            "sk": sk,
            "movement_id": mid,
            "title": (movements.get(mid) or {}).get("title") or mid,
            "gates": gates,
            "week_start": week_start,
            "line": announcement_line((movements.get(mid) or {}).get("title") or mid, gates, week_start, states[mid]["cues"]),
            "status": PENDING,
            "created_at": _now_iso(),
            "version": eg.VERSION,
            "tier": "owner_only",
        }
        try:
            _put(table, item, condition="attribute_not_exists(sk)")
            created.append(sk)
        except ClientError as e:
            if (e.response.get("Error") or {}).get("Code") != "ConditionalCheckFailedException":
                raise
    return created


def eval_row(week_start: str, week_end: str, library, gates, states, reads, fresh, created, announce_state) -> dict[str, Any]:
    gated = eg.gated_movements(states)
    return {
        "pk": _pk(),
        "sk": SK_EVAL + week_start,
        "week_start": week_start,
        "week_end": week_end,
        "as_of": week_end,
        "library_version": library.get("version"),
        "library_status": library.get("status"),
        "gates": gates,
        "counts": eg.state_counts(gates),
        "movements": {m: {k: s[k] for k in ("state", "own_gates", "own_gates_open", "locked_by")} for m, s in gated.items()},
        "movements_locked": sum(1 for s in states.values() if s["state"] != eg.UNLOCKED),
        "movements_total": len(states),
        "newly_unlocked": fresh,
        "announce": {"state": announce_state, "created": created},
        "reads": reads,
        "version": eg.VERSION,
        "evaluated_at": _now_iso(),
        "tier": "owner_only",
    }


# ── the weekly run ──────────────────────────────────────────────────────────────────────────────────────────────────
def evaluate_week(week_end: Optional[str] = None, *, today: Optional[str] = None, table: Any = None) -> dict[str, Any]:
    """Evaluate the Monday-Sunday week ending `week_end` (default: the newest completed week) and store the rows."""
    from common.pacific_time import pacific_today
    from training.may_tracker import last_completed_monday

    table = _table(table)
    today = today or pacific_today()
    week_start = eg._shift(week_end, -6) if week_end else last_completed_monday(today)
    week_end = week_end or eg._shift(week_start, 6)
    library, measured, overlay, reads = gather(week_start, week_end)
    gates = eg.evaluate_gates(library, overlay, measured)
    states = eg.movement_states(library, gates)
    sk = SK_EVAL + week_start
    prev = previous_eval(table, sk)
    fresh = eg.newly_unlocked((prev or {}).get("movements") if prev else None, states)
    created: list[str] = []
    if library.get("status") != APPROVED:
        announce_state = f"held: library status {library.get('status')}"
    elif prev is None:
        announce_state = "baseline: first evaluation, nothing is new"
    else:
        created = create_announcements(table, library, states, fresh, week_start)
        announce_state = "ok"
    _put(table, eval_row(week_start, week_end, library, gates, states, reads, fresh, created, announce_state))  # LAST
    return {
        "outcome": "written",
        "sk": sk,
        "counts": eg.state_counts(gates),
        "gate_states": eg.log_view(gates),
        "newly_unlocked": [u["movement_id"] for u in fresh],
        "announce": announce_state,
        "reads": {k: ("ok" if v == "ok" else str(v).split(":")[0]) for k, v in reads.items()},
    }


def weekly_leg(week_end: Optional[str] = None) -> dict[str, Any]:
    """The fail-soft leg on the weekly panel grade. Never raises; logs gate ids, states and counts only."""
    try:
        out = evaluate_week(week_end)
    except Exception as e:  # noqa: BLE001 — named on the run's result, never raised into the grade
        logger.warning("[exercise_gates] weekly evaluation failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
    logger.info("[exercise_gates] wrote %s counts=%s states=%s new=%s", out["sk"], out["counts"], out["gate_states"], out["newly_unlocked"])
    return out


# ── the read side: plan_next_session stage 1's announce-once line ───────────────────────────────────────────────────
def pending_announcements(table: Any, user_id: str = "matthew") -> list[dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    resp = table.query(KeyConditionExpression=Key("pk").eq(_pk(user_id)) & Key("sk").begins_with(SK_ANNOUNCE))
    return [_plain(i) for i in resp.get("Items") or [] if i.get("status") == PENDING]


def claim(table: Any, sk: str, user_id: str = "matthew") -> bool:
    """pending -> announced, exactly once: True for the one caller whose conditional update won."""
    from botocore.exceptions import ClientError

    try:
        table.update_item(
            Key={"pk": _pk(user_id), "sk": sk},
            UpdateExpression="SET #s = :a, announced_at = :t",
            ConditionExpression="#s = :p",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":a": ANNOUNCED, ":p": PENDING, ":t": _now_iso()},
        )
        return True
    except ClientError as e:
        if (e.response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def unlock_announcements_field(*, claim_rows: bool = True, table: Any = None) -> dict[str, Any]:
    """`plan_next_session` stage 1's `exercise_unlocks`: the newly unlocked movements not yet announced, each said ONCE.

    `claim_rows=False` (stage 2, a dry run) reads without claiming. A failed read is `read_failed` with its class,
    never "nothing unlocked"."""
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED, error_label, input_status

    try:
        table = _table(table)
        rows = pending_announcements(table)
        said = [r for r in rows if not claim_rows or claim(table, r["sk"])]
    except Exception as e:  # noqa: BLE001 — named on the field
        return {**input_status(READ_FAILED, error=error_label(e)), "lines": []}
    if not said:
        return {**input_status(ABSENT, "no newly unlocked movement waiting to be announced"), "lines": []}
    return {
        **input_status(MEASURED),
        "lines": [r.get("line") for r in said],
        "movements": [r.get("movement_id") for r in said],
        "claimed": bool(claim_rows),
        "how_to_use": "Say each line to Matthew once, in this answer — the record is now marked announced and will not repeat.",
    }
