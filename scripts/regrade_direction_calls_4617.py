#!/usr/bin/env python3
"""scripts/regrade_direction_calls_4617.py — grade every graded direction call again ACROSS ITS
OWN WINDOW, on the record, keeping the old grade and the reason (#4617, epic #4580).

THE DEFECT. Two calls sealed before day one that weight would trend down were graded flat,
and so wrong, on 2026-10-04 while the served weigh-ins fell from 327.3 lb (September 6) to
312.1 lb (October 4). The grader compared its latest readings with the few before them; it
never looked at the start of the call's window. The grader is fixed
(``coach.prediction_direction_window``); this script corrects the rows already written,
through the evaluator's OWN ``_evaluate_directional`` / ``_evaluate_machine`` — there is no
second derivation here.

WHAT IT DOES (dry-run by default; nothing is written without --apply):

  For every graded (right/wrong) direction call of this experiment — a ``directional`` spec
  or a threshold-less ``machine`` spec the grader re-routes to direction (#813) — that was
  NOT graded across its window yet and carries no earlier ``verdict_correction``:

    * regrade    the window grade differs from the stored one: the new grade is written and
                 the old grade, its reason and its "nothing changes" stamp are kept under
                 ``verdict_correction`` (and inside ``outcome_notes``).
    * restate    the window grade agrees with the stored one: the grade is unchanged, the
                 outcome notes gain the window's first/last readings so a page can print a
                 rule a reader can check; the old reason is kept the same way.
    * withdraw   the window has too few readings to grade (or none near an edge): the old
                 grade measured something else, so it is withdrawn to ``inconclusive`` and
                 kept under ``verdict_correction``. Leaves the coach's record.

  --scope sealed (default) touches calls sealed before day one only — the specimen the issue
  names. --scope all also corrects the direction calls read out of in-experiment commentary,
  so the record is graded by one method throughout. The owner picks; the dry run prints both
  counts.

  Every write is conditional on the row still carrying the status the plan read and on it
  not already carrying a correction — a second run changes nothing (IDEMPOTENT).

  NOT rewritten: the coach's ``CONFIDENCE#`` Beta posterior and the ``LEARNING#`` row the first
  grade wrote. A coach's served record is counted from ``PREDICTION#`` rows only
  (``coach.coach_record``), which is what this corrects.

RUN:  python3 scripts/regrade_direction_calls_4617.py                   # dry-run, sealed calls
      python3 scripts/regrade_direction_calls_4617.py --scope all       # dry-run, every direction call
      python3 scripts/regrade_direction_calls_4617.py --json plan.json
      python3 scripts/regrade_direction_calls_4617.py --apply           # writes the corrections

Reads DynamoDB only in dry-run. --apply is a DynamoDB WRITE — an owner/driver act, never a
lane's — and is refused unless explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import coach_baseline, coach_record  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import floats_to_decimal  # noqa: E402
from common.pacific_time import pacific_today  # noqa: E402
from regrade_tomorrow_calls_4618 import partition_rows, record_table, records  # noqa: E402  (the shared read + record tally)

ISSUE = "#4617"
REGRADE = "regrade"
RESTATE = "restate"
WITHDRAW = "withdraw"
WRITES = (REGRADE, RESTATE, WITHDRAW)
SCOPES = ("sealed", "all")

WHY = {
    REGRADE: (
        f"{ISSUE}: graded again on the change from the first to the last reading of the call's own window, against the "
        "metric's own day-to-day swing. The earlier grade compared only the most recent readings with the few before them."
    ),
    RESTATE: (
        f"{ISSUE}: graded again across the call's own window; the grade is unchanged and now carries the window's first and "
        "last readings."
    ),
    WITHDRAW: (
        f"{ISSUE}: the call's own window has too few readings to grade, so the earlier grade (which read other days) is " "withdrawn."
    ),
}


def _evaluator():
    """The grader module — imported lazily so ``plan`` stays testable without AWS."""
    from coach import coach_prediction_evaluator as ev

    return ev


def _coach_ids():
    from web.site_api_coach_ledger import _CALIB_COACH_ID_MAP

    return list(_CALIB_COACH_ID_MAP.values())  # every seat, retired included — their rows are real


def _notes(row):
    try:
        got = json.loads(row.get("outcome_notes") or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def in_scope(row, genesis, scope):
    """A graded direction call of this experiment not yet graded across its window."""
    if row.get("source") == "dispute_docket" or row.get("verdict_correction") or not row.get("created_date"):
        return False
    if not coach_record.counts_this_cycle(row, genesis) or coach_record.graded_status(row) is None:
        return False
    if coach_baseline.rule_kind(row.get("evaluation")) != "direction":
        return False
    if isinstance(_notes(row).get("window"), dict):
        return False  # already graded by the window rule
    return scope == "all" or bool(row.get("pre_registered"))


def regrade_one(row, data_cache, today, ev):
    """The evaluator's own grade for this row today (its window ends where the call's does)."""
    spec = row.get("evaluation") or {}
    if spec.get("type") == "machine":
        return ev._evaluate_machine(row, spec, data_cache, today)  # the #813 re-route, exactly as the daily run does it
    return ev._evaluate_directional(row, spec, data_cache, today)


def plan(rows_by_coach, *, genesis, today, ev, scope="sealed", exclude=()):
    """Every row this correction touches, in a stable order. Pure over its inputs (no write)."""
    out, data_cache = [], {}
    io = (ev._get_source_data, ev._extract_metric_series)
    for coach_id, raw in rows_by_coach.items():
        for row in coach_record.resolved_once(raw or []):
            if row.get("sk") in exclude or not in_scope(row, genesis, scope):
                continue
            old = coach_record.graded_status(row)
            result = regrade_one(row, data_cache, today, ev) or {}
            new = result.get("status")
            if new in coach_record.GRADED_STATUSES:
                action = RESTATE if new == old else REGRADE
                baseline = coach_baseline.stamp_at_grading(
                    row, row.get("evaluation") or {}, result, new, data_cache, io[0], io[1], ev.DIRECTIONAL_NOISE_THRESHOLD
                )
            else:
                action, new, baseline = WITHDRAW, "inconclusive", None
            out.append(
                {
                    "action": action,
                    "coach": coach_id,
                    "pk": row.get("pk") or f"COACH#{coach_id}",
                    "sk": row.get("sk"),
                    "prediction_id": row.get("prediction_id"),
                    "sealed": bool(row.get("pre_registered")),
                    "claim": row.get("claim_natural") or "",
                    "filed": row.get("created_date"),
                    "metric": (row.get("evaluation") or {}).get("metric"),
                    "status": old,
                    "new_status": new,
                    "old_reason": _notes(row).get("reason"),
                    "prior_outcome_notes": row.get("outcome_notes"),
                    "prior_outcome_date": row.get("outcome_date"),
                    "prior_baseline": row.get("baseline"),
                    "result": result,
                    "new_baseline": baseline,
                }
            )
    return sorted(out, key=lambda e: (not e["sealed"], str(e["filed"]), e["coach"], str(e["sk"])))


def after_rows(rows_by_coach, entries):
    """The partitions as they would read once every planned write landed (for the tally)."""
    changes = {(e["pk"], e["sk"]): e for e in entries if e["action"] in WRITES}
    out = {}
    for coach, rows in rows_by_coach.items():
        out[coach] = []
        for row in rows:
            e = changes.get((row.get("pk"), row.get("sk")))
            out[coach].append(dict(row, status=e["new_status"], outcome=e["new_status"]) if e else row)
    return out


def correction(e, now):
    """The audit map: the old grade and its reason, kept on the row (acceptance box 2)."""
    return {
        "issue": ISSUE,
        "action": e["action"],
        "corrected_at": now,
        "reason": WHY[e["action"]],
        "new_status": e["new_status"],
        "prior": {
            "status": e["status"],
            "reason": e.get("old_reason"),
            "outcome_date": e.get("prior_outcome_date"),
            "outcome_notes": e.get("prior_outcome_notes"),
            "baseline": e.get("prior_baseline"),
        },
    }


def update_kwargs(e, now, algo_version):
    """The ONE conditional update for one planned entry (pure — the test reads it)."""
    vc = correction(e, now)
    result = e.get("result") or {}
    notes = {
        "actual_value": result.get("actual_value"),
        "reason": result.get("reason") or vc["reason"],
        "beats_null": bool(result.get("beats_null", False)),
        "bayesian_update": None,  # the Beta posterior is not rewritten by this correction — see the module docstring
        "algo_version": algo_version,
        "verdict_correction": {
            "issue": ISSUE,
            "prior_status": e["status"],
            "prior_reason": e.get("old_reason"),
            "corrected_at": now,
            "correction": vc["reason"],
        },
    }
    if isinstance(result.get("window"), dict):
        notes["window"] = result["window"]
    values = {":prior": e["status"], ":new": e["new_status"], ":notes": json.dumps(notes), ":vc": floats_to_decimal(vc)}
    sets = ["#s = :new", "outcome = :new", "outcome_notes = :notes", "verdict_correction = :vc"]
    if e.get("new_baseline"):
        values[":bl"] = floats_to_decimal(e["new_baseline"])
        sets.append("baseline = :bl")
    return {
        "Key": {"pk": e["pk"], "sk": e["sk"]},
        "UpdateExpression": "SET " + ", ".join(sets),
        "ConditionExpression": "#s = :prior AND attribute_not_exists(verdict_correction)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": values,
    }


def apply(table, entries, algo_version, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    written = 0
    for e in entries:
        if e["action"] not in WRITES:
            continue
        try:
            table.update_item(**update_kwargs(e, now, algo_version))
            written += 1
        except Exception as exc:  # noqa: BLE001 — a refused condition is the idempotent no-op; anything else is printed
            print(f"  NOT WRITTEN {e['coach']} {e['sk']}: {exc}")
    return written


# ── the printed table ────────────────────────────────────────────────────────────────────


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _grade(status):
    return {"confirmed": "right", "refuted": "wrong"}.get(str(status), str(status))


def table_md(entries):
    head = "| coach | sealed | sentence | window | first reading | last reading | change (band) | old grade | new grade | action |"
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        w = (e.get("result") or {}).get("window") or {}
        if w:
            span = f"{w['start']}..{w['end']}"
            first, last = f"{w['first_value']:g} ({w['first_date']})", f"{w['last_value']:g} ({w['last_date']})"
            change = f"{w['change']:+g} (±{w['band']:g})"
        else:
            span, first, last, change = "—", "—", "—", _cell((e.get("result") or {}).get("reason") or "no window")
        lines.append(
            f"| {e['coach']} | {'yes' if e['sealed'] else 'no'} | {_cell(e['claim'][:140])} | {span} | {first} | {last} | {change} "
            f"| {_grade(e['status'])} | {_grade(e['new_status'])} | {e['action']} |"
        )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="WRITE the corrections (a DynamoDB mutation) — default is a dry run")
    ap.add_argument("--scope", choices=SCOPES, default="sealed", help="sealed (default): sealed calls only; all: every direction call")
    ap.add_argument("--exclude", action="append", default=[], help="a row's sk to leave out of the plan (repeatable)")
    ap.add_argument("--json", help="also write the plan to this path")
    args = ap.parse_args(argv)

    ev = _evaluator()
    table = ev.table
    rows_by_coach = {cid: partition_rows(table, cid) for cid in _coach_ids()}
    today = pacific_today()
    entries = plan(rows_by_coach, genesis=EXPERIMENT_START_DATE, today=today, ev=ev, scope=args.scope, exclude=set(args.exclude))
    counts: dict = {}
    for e in entries:
        counts[e["action"]] = counts.get(e["action"], 0) + 1

    print(
        f"{ISSUE} · experiment from {EXPERIMENT_START_DATE} · read {today} (Pacific) · scope {args.scope} · {len(entries)} row(s): {counts}"
    )
    print("\nGraded direction calls, graded again across their own window:\n")
    print(table_md(entries))
    print("\nEach coach's record (counted from PREDICTION# rows, this experiment):\n")
    before = records(rows_by_coach, EXPERIMENT_START_DATE)
    print(record_table(before, records(after_rows(rows_by_coach, entries), EXPERIMENT_START_DATE)))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=1, default=str)
        print(f"\nplan written to {args.json}")

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to write the corrections.")
        return 0
    written = apply(table, entries, ev.ALGO_VERSION)
    planned = sum(1 for e in entries if e["action"] in WRITES)
    print(f"\nAPPLIED: {written} of {planned} correction(s) written (a refused write = already corrected or changed since the read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
