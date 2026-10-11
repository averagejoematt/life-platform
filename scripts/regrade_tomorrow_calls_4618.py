#!/usr/bin/env python3
"""scripts/regrade_tomorrow_calls_4618.py — settle every number call on the day its own
sentence names, ON THE RECORD, and bring every pending call's due date back inside a year
(#4618, epic #4580).

THE DEFECT. "Recovery will soften to roughly 59% tomorrow", filed September 14, was stored
with a target fourteen days out and graded right on September 28's reading. The writer is
fixed (``coach.prediction_windows.sentence_target_day``); this script corrects the rows
already written. It reads each row's OWN sentence with that same function — there is no
second derivation here.

WHAT IT DOES (dry-run by default; nothing is written without --apply):

  GRADED number calls whose stored target is not the day after filing (eleven on
  2026-10-04), one of four outcomes each:

    * regrade                 the sentence names a day ("tomorrow", "tonight", or a date
                              after filing) other than the one it was graded on, and that
                              day HAS a reading: graded again with the evaluator's own
                              point check against that reading. The spec's target day is
                              corrected; the old verdict, its reason, the old target and
                              the old "nothing changes" stamp are kept under
                              ``verdict_correction`` and inside ``outcome_notes``.
    * withdraw:no-reading     the sentence names a day and that day has NO reading. No
                              reading is borrowed from a neighbouring day and none is
                              invented: the old verdict (it measured another day) is
                              withdrawn to ``inconclusive``, kept under
                              ``verdict_correction``. Leaves the coach's record.
    * withdraw:not-a-forecast the number is stated FOR a day on or before the filing day
                              ("…would land around 59.3% on the night of 2026-09-15",
                              filed the 17th). The reading already existed when the
                              sentence was written, so nothing can settle it: withdrawn
                              to ``observation``, old verdict kept. Leaves the record.
    * unchanged:no-day-named  the sentence names no day. The stated 14-day window is the
                              writer's documented default and stands; nothing is written.
                              (Six of these are conditionals graded with the condition
                              never checked — that is #4617's question, not this one's.)

  PENDING calls:

    * respecify               a number call whose sentence names a day other than its
                              stored target (six "tomorrow" calls due in 2032, one due a
                              month out), or ANY pending call due more than a year out
                              (direction calls due 2029, 2032 and 2065 — the window was
                              a gram figure or the year of a date). The target/window is
                              re-derived from the sentence — "tomorrow" is one day, a
                              sentence with no time phrase is the writer's 14-day default
                              — and the old spec is kept under ``respecified_from``. The
                              daily evaluator then grades the row; this script does not.
    * withdraw:not-a-forecast a pending number stated for a day already past when filed
                              ("…expected to hold around 90.9% on 2026-09-20", filed the
                              21st): withdrawn to ``observation``, old spec kept.

  Every write is conditional on the row still being in the state the plan read, and on it
  not already carrying this correction — a second run changes nothing (IDEMPOTENT).

  NOT rewritten: the coach's ``CONFIDENCE#`` Beta posterior and the ``LEARNING#`` row the
  first grade wrote. A coach's served record is counted from ``PREDICTION#`` rows only
  (``coach.coach_record``), which is what this corrects.

RUN:  python3 scripts/regrade_tomorrow_calls_4618.py                 # dry-run: the tables
      python3 scripts/regrade_tomorrow_calls_4618.py --json plan.json
      python3 scripts/regrade_tomorrow_calls_4618.py --exclude PREDICTION#pred_…   # leave one row out
      python3 scripts/regrade_tomorrow_calls_4618.py --apply         # writes the corrections

Reads DynamoDB only in dry-run. --apply is a DynamoDB WRITE — an owner/driver act, never a
lane's — and is refused unless explicitly passed.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from boto3.dynamodb.conditions import Key  # noqa: E402
from coach import (  # noqa: E402
    coach_baseline,
    coach_record,
    prediction_emission as pe,
    prediction_point_grader as point_grader,
    prediction_windows as pw,
)
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import decimals_to_float, floats_to_decimal  # noqa: E402
from common.pacific_time import pacific_today, parse_day_key, shift_day_key  # noqa: E402

ISSUE = "#4618"
PENDING = ("pending", "confirming")
DEFAULT_WINDOW_DAYS = 14  # prediction_emission.prediction_window_days' default for a sentence with no time phrase

REGRADE = "regrade"
WITHDRAW_NO_READING = "withdraw:no-reading"
WITHDRAW_NOT_A_FORECAST = "withdraw:not-a-forecast"
UNCHANGED = "unchanged:no-day-named"
RESPECIFY = "respecify"
WRITES = (REGRADE, WITHDRAW_NO_READING, WITHDRAW_NOT_A_FORECAST, RESPECIFY)

WHY_REGRADE = (
    f"{ISSUE}: the sentence names its own day; the call was stored with a target that many days out and graded on a day "
    "the sentence does not name. Graded again on the reading for the day it named."
)
WHY_NO_READING = (
    f"{ISSUE}: the sentence names its own day and that day has no reading. The earlier verdict measured a different day, "
    "so it is withdrawn; no reading is borrowed from another day."
)
WHY_NOT_A_FORECAST = (
    f"{ISSUE}: the number is stated for a day on or before the day the call was filed, so the reading already existed. "
    "It is a recollection of a forecast, not a forecast, and nothing can settle it."
)
WHY_RESPECIFY = f"{ISSUE}: the stored target day or window was not the one the sentence states; re-derived from the sentence."


def _evaluator():
    """The grader module — imported lazily so ``plan`` stays testable without AWS."""
    from coach import coach_prediction_evaluator as ev

    return ev


def _coach_ids():
    from web.site_api_coach_ledger import _CALIB_COACH_ID_MAP

    return list(_CALIB_COACH_ID_MAP.values())  # every seat, retired included — their rows are real


def partition_rows(table, coach_id):
    """The coach's whole PREDICTION# partition, paginated, unprojected."""
    rows, kwargs = [], {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#")}
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return [decimals_to_float(r) for r in rows]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _notes(row):
    try:
        got = json.loads(row.get("outcome_notes") or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _days_between(start, end):
    a, b = parse_day_key(start), parse_day_key(end)
    return (b - a).days if a and b else None


def reading_on(metric, day, data_cache, today, io):
    """The reading for ``metric`` ON ``day`` exactly — None when that day has none. The
    evaluator's own cached, phase-filtered read; the grace look-back is closed off by
    refusing anything on or before the day before (``after_day``)."""
    get_source_data, extract_metric_series = io
    value, on = point_grader.metric_value_on(
        metric,
        data_cache,
        today,
        day,
        get_source_data=get_source_data,
        extract_metric_series=extract_metric_series,
        after_day=shift_day_key(day, -1),
    )
    return value if on == day else None


def _entry(coach_id, row, action, **extra):
    spec = row.get("evaluation") or {}
    notes = _notes(row)
    return {
        "action": action,
        "coach": coach_id,
        "pk": row.get("pk") or f"COACH#{coach_id}",
        "sk": row.get("sk"),
        "prediction_id": row.get("prediction_id"),
        "claim": row.get("claim_natural") or "",
        "filed": row.get("created_date"),
        "kind": spec.get("type"),
        "metric": spec.get("metric"),
        "status": row.get("status"),
        "old_target": spec.get("target_date") or pw.due_date(row.get("created_date"), spec, row.get("subdomain", "")),
        "old_window_days": spec.get("evaluation_window_days"),
        "old_reading": notes.get("actual_value"),
        "old_spec": spec,
        "prior_outcome_notes": row.get("outcome_notes"),
        "prior_outcome_date": row.get("outcome_date"),
        "prior_baseline": row.get("baseline"),
        "new_status": row.get("status"),
        **extra,
    }


def _plan_graded_number(coach_id, row, data_cache, today, io, noise_band):
    spec = row.get("evaluation") or {}
    filed, stored = row.get("created_date"), spec.get("target_date")
    claim, metric = row.get("claim_natural") or "", spec.get("metric")
    day, basis = pw.sentence_target_day(claim, filed)
    if stored == shift_day_key(str(filed), 1) and (not day or day == stored):
        return None  # graded on the day after filing, the day it named: nothing to correct
    if day and day == stored:
        return None  # a named date, graded on that date
    if day:
        new_spec = dict(spec, target_date=day, evaluation_window_days=_days_between(filed, day))
        value = reading_on(metric, day, data_cache, today, io)
        if value is None:
            return _entry(
                coach_id,
                row,
                WITHDRAW_NO_READING,
                named_day=day,
                basis=basis,
                new_reading=None,
                new_spec=new_spec,
                new_status="inconclusive",
            )
        result = point_grader.evaluate_point(row, new_spec, data_cache, today, get_source_data=io[0], extract_metric_series=io[1])
        if not result or result.get("status") not in coach_record.GRADED_STATUSES:
            return _entry(
                coach_id,
                row,
                WITHDRAW_NO_READING,
                named_day=day,
                basis=basis,
                new_reading=None,
                new_spec=new_spec,
                new_status="inconclusive",
            )
        baseline = coach_baseline.stamp_at_grading(row, new_spec, result, result["status"], data_cache, io[0], io[1], noise_band)
        return _entry(
            coach_id,
            row,
            REGRADE,
            named_day=day,
            basis=basis,
            new_reading=result.get("actual_value"),
            new_spec=new_spec,
            new_status=result["status"],
            regrade=result,
            new_baseline=baseline,
        )
    named = pe.classify_claim_shape(claim, metric).get("named_day")
    if pw.names_day_already_past(named, filed):
        return _entry(coach_id, row, WITHDRAW_NOT_A_FORECAST, named_day=named, basis="named_date_already_past", new_status="observation")
    return _entry(coach_id, row, UNCHANGED, named_day=None, basis=None)


def _plan_pending(coach_id, row):
    spec = row.get("evaluation") or {}
    filed, claim = row.get("created_date"), row.get("claim_natural") or ""
    day, basis = pw.sentence_target_day(claim, filed)
    too_far = pw.refuse_due(filed, spec, row.get("subdomain", ""))
    if spec.get("type") == pw.POINT_TYPE:
        if day and day != spec.get("target_date"):
            new_spec = dict(spec, target_date=day, evaluation_window_days=_days_between(filed, day))
            return _entry(coach_id, row, RESPECIFY, named_day=day, basis=basis, new_spec=new_spec, too_far=too_far)
        if not day:
            named = pe.classify_claim_shape(claim, spec.get("metric")).get("named_day")
            if pw.names_day_already_past(named, filed):
                return _entry(
                    coach_id, row, WITHDRAW_NOT_A_FORECAST, named_day=named, basis="named_date_already_past", new_status="observation"
                )
    if not too_far:
        return None
    window = _days_between(filed, day) if day else DEFAULT_WINDOW_DAYS
    new_spec = dict(spec, evaluation_window_days=window)
    if spec.get("type") == pw.POINT_TYPE:
        new_spec["target_date"] = day or shift_day_key(str(filed), window)
    return _entry(
        coach_id, row, RESPECIFY, named_day=day, basis=basis or "no time phrase: the 14-day default", new_spec=new_spec, too_far=too_far
    )


def plan(rows_by_coach, *, genesis, today, io, noise_band, exclude=()):
    """Every row this correction touches or deliberately leaves, in a stable order.

    ``rows_by_coach`` is ``{coach_id: [PREDICTION# rows]}`` (floats, not Decimals);
    ``io`` is the evaluator's ``(_get_source_data, _extract_metric_series)``. Pure over
    those: no clock, no write."""
    out, data_cache = [], {}
    for coach_id, raw in rows_by_coach.items():
        for row in coach_record.resolved_once(raw or []):
            if row.get("sk") in exclude or row.get("source") == "dispute_docket":
                continue
            if not coach_record.counts_this_cycle(row, genesis) or not row.get("created_date"):
                continue  # an archived phase's rows are not this experiment's record
            spec = row.get("evaluation") or {}
            status = str(row.get("status") or "")
            entry = None
            if status in PENDING and pw.is_gradeable(spec):
                if not row.get("respecified_at"):
                    entry = _plan_pending(coach_id, row)
            elif coach_record.graded_status(row) and spec.get("type") == pw.POINT_TYPE and not row.get("verdict_correction"):
                entry = _plan_graded_number(coach_id, row, data_cache, today, io, noise_band)
            if entry:
                out.append(entry)
    return sorted(out, key=lambda e: (e["status"] in PENDING, str(e["filed"]), e["coach"], str(e["sk"])))


def after_rows(rows_by_coach, entries):
    """The partitions as they would read once every planned write landed (for the tally)."""
    changes = {(e["pk"], e["sk"]): e for e in entries if e["action"] in WRITES}
    out = copy.deepcopy(rows_by_coach)
    for rows in out.values():
        for row in rows:
            e = changes.get((row.get("pk"), row.get("sk")))
            if not e:
                continue
            row["status"] = e["new_status"]
            if e["status"] not in PENDING:
                row["outcome"] = e["new_status"]
            if e.get("new_spec"):
                row["evaluation"] = e["new_spec"]
    return out


def records(rows_by_coach, genesis):
    return {c: coach_record.record_from_rows(rows, genesis=genesis) for c, rows in rows_by_coach.items()}


def _correction(e, now):
    return {
        "issue": ISSUE,
        "action": e["action"],
        "corrected_at": now,
        "reason": {REGRADE: WHY_REGRADE, WITHDRAW_NO_READING: WHY_NO_READING, WITHDRAW_NOT_A_FORECAST: WHY_NOT_A_FORECAST}[e["action"]],
        "new_status": e["new_status"],
        "named_day": e.get("named_day"),
        "prior": {
            "status": e["status"],
            "outcome_date": e.get("prior_outcome_date"),
            "outcome_notes": e.get("prior_outcome_notes"),
            "target_date": e.get("old_target"),
            "evaluation_window_days": e.get("old_window_days"),
            "reading": e.get("old_reading"),
            "baseline": e.get("prior_baseline"),
        },
    }


def _write(table, e, now, algo_version):
    """One conditional update for one planned entry. Returns True when it landed."""
    key = {"pk": e["pk"], "sk": e["sk"]}
    names = {"#s": "status"}
    if e["status"] in PENDING:
        values = {":prior": e["status"], ":old": floats_to_decimal({"status": e["status"], "evaluation": e["old_spec"]}), ":at": now}
        sets = ["respecified_from = :old", "respecified_at = :at", "respecified_reason = :why"]
        if e["action"] == RESPECIFY:
            values[":why"], values[":spec"] = WHY_RESPECIFY, floats_to_decimal(e["new_spec"])
            sets.append("evaluation = :spec")
        else:
            values[":why"], values[":new"], values[":none"] = WHY_NOT_A_FORECAST, e["new_status"], pe.GRADEABLE_BY_NONE
            sets += ["#s = :new", "gradeable_by = :none"]
        condition = "#s = :prior AND attribute_not_exists(respecified_at)"
    else:
        correction = _correction(e, now)
        result = e.get("regrade") or {}
        notes = {
            "actual_value": result.get("actual_value"),
            "reason": result.get("reason") or correction["reason"],
            "beats_null": bool(result.get("beats_null", False)),
            "bayesian_update": None,  # the Beta posterior is not rewritten by this correction — see the module docstring
            "algo_version": algo_version,
            "verdict_correction": {
                "issue": ISSUE,
                "prior_status": e["status"],
                "prior_reason": _notes({"outcome_notes": e.get("prior_outcome_notes")}).get("reason"),
                "prior_target_date": e.get("old_target"),
                "corrected_at": now,
                "correction": correction["reason"],
            },
        }
        values = {":prior": e["status"], ":new": e["new_status"], ":notes": json.dumps(notes), ":vc": floats_to_decimal(correction)}
        sets = ["#s = :new", "outcome = :new", "outcome_notes = :notes", "verdict_correction = :vc"]
        if e.get("new_spec"):
            values[":spec"] = floats_to_decimal(e["new_spec"])
            sets.append("evaluation = :spec")
        if e["action"] == REGRADE and e.get("new_baseline"):
            values[":bl"] = floats_to_decimal(e["new_baseline"])
            sets.append("baseline = :bl")
        if e["action"] == WITHDRAW_NOT_A_FORECAST:
            values[":none"] = pe.GRADEABLE_BY_NONE
            sets.append("gradeable_by = :none")
        condition = "#s = :prior AND attribute_not_exists(verdict_correction)"
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — a refused condition is the idempotent no-op; anything else is printed
        print(f"  NOT WRITTEN {e['coach']} {e['sk']}: {exc}")
        return False


def apply(table, entries, algo_version, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    return sum(1 for e in entries if e["action"] in WRITES and _write(table, e, now, algo_version))


# ── the printed tables ───────────────────────────────────────────────────────────────────


def _call_id(e):
    from web.site_api_calls import call_id

    return call_id(str(e["coach"]).removesuffix("_coach"), {"prediction_id": e["prediction_id"], "created_date": e["filed"]}) or "(no id)"


def _num(v):
    return "—" if v is None else f"{float(v):g}"


def _grade(status, reading=None):
    words = {"confirmed": "right", "refuted": "wrong"}.get(str(status), str(status))
    return f"{words} ({_num(reading)})" if reading is not None else words


def _cell(text):
    return str(text).replace("|", "\\|")


def graded_table(entries):
    head = "| call id | coach | sentence | filed | old target | old grade (reading) | day the sentence names | that day's reading | new grade | action |"
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        named = f"{e['named_day']} ({e['basis']})" if e.get("named_day") else "none"
        if e["action"] == REGRADE:
            reading, new = _num(e.get("new_reading")), _grade(e["new_status"])
        elif e["action"] == WITHDRAW_NO_READING:
            reading, new = "no reading that day", "withdrawn: inconclusive"
        elif e["action"] == WITHDRAW_NOT_A_FORECAST:
            reading, new = "not read: the day was already past when filed", "withdrawn: observation"
        else:
            reading, new = "n/a", f"{_grade(e['status'])} (unchanged)"
        lines.append(
            f"| `{_call_id(e)}` | {e['coach']} | {_cell(e['claim'])} | {e['filed']} | {e['old_target']} | {_grade(e['status'], e.get('old_reading'))} "
            f"| {named} | {reading} | {new} | {e['action']} |"
        )
    return "\n".join(lines)


def pending_table(entries):
    head = "| call id | coach | kind | sentence | filed | old due / target | old window (days) | new target / window | basis | action |"
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        spec = e.get("new_spec") or {}
        new = (
            "withdrawn: observation"
            if e["action"] == WITHDRAW_NOT_A_FORECAST
            else f"{spec.get('target_date') or 'window'} / {_num(spec.get('evaluation_window_days'))} d"
        )
        lines.append(
            f"| `{_call_id(e)}` | {e['coach']} | {e['kind']} | {_cell(e['claim'])} | {e['filed']} | {e['old_target']} | {_num(e['old_window_days'])} "
            f"| {new} | {e.get('basis') or ''}{' (named ' + str(e['named_day']) + ')' if e['action'] == WITHDRAW_NOT_A_FORECAST else ''} | {e['action']} |"
        )
    return "\n".join(lines)


def record_table(before, after):
    lines = ["| coach | right / checked before | right / checked after |", "|---|---|---|"]
    for coach in sorted(before):
        b, a = before[coach], after[coach]
        mark = "" if (b["confirmed"], b["n"]) == (a["confirmed"], a["n"]) else "  **changed**"
        lines.append(f"| {coach} | {b['confirmed']} of {b['n']} | {a['confirmed']} of {a['n']}{mark} |")
    tb = (sum(r["confirmed"] for r in before.values()), sum(r["n"] for r in before.values()))
    ta = (sum(r["confirmed"] for r in after.values()), sum(r["n"] for r in after.values()))
    lines.append(f"| **all coaches** | {tb[0]} of {tb[1]} | {ta[0]} of {ta[1]} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="WRITE the corrections (a DynamoDB mutation) — default is a dry run")
    ap.add_argument("--exclude", action="append", default=[], help="a row's sk to leave out of the plan (repeatable)")
    ap.add_argument("--json", help="also write the plan to this path")
    args = ap.parse_args(argv)

    ev = _evaluator()
    table = ev.table
    rows_by_coach = {cid: partition_rows(table, cid) for cid in _coach_ids()}
    today = pacific_today()
    entries = plan(
        rows_by_coach,
        genesis=EXPERIMENT_START_DATE,
        today=today,
        io=(ev._get_source_data, ev._extract_metric_series),
        noise_band=ev.DIRECTIONAL_NOISE_THRESHOLD,
        exclude=set(args.exclude),
    )
    graded = [e for e in entries if e["status"] not in PENDING]
    pending = [e for e in entries if e["status"] in PENDING]
    counts: dict = {}
    for e in entries:
        counts[e["action"]] = counts.get(e["action"], 0) + 1

    print(f"{ISSUE} · experiment from {EXPERIMENT_START_DATE} · read {today} (Pacific) · {len(entries)} row(s): {counts}")
    print(f"\nGRADED number calls whose stored target is not the day after filing ({len(graded)}):\n")
    print(graded_table(graded))
    print(f"\nPENDING calls re-specified or withdrawn ({len(pending)}):\n")
    print(pending_table(pending))
    print("\nEach coach's record (counted from PREDICTION# rows, this experiment):\n")
    print(record_table(records(rows_by_coach, EXPERIMENT_START_DATE), records(after_rows(rows_by_coach, entries), EXPERIMENT_START_DATE)))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=1, default=str)
        print(f"\nplan written to {args.json}")

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to write the corrections.")
        return 0
    written = apply(table, entries, ev.ALGO_VERSION)
    planned = sum(1 for e in entries if e["action"] in WRITES)
    print(
        f"\nAPPLIED: {written} of {planned} correction(s) written (a refused write = already corrected or changed since the read — idempotent)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
