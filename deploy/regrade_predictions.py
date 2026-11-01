#!/usr/bin/env python3
"""deploy/regrade_predictions.py — grade again ONLY the rows the #5533 evaluator fixes touch, on
the record, keeping every original grade (owner requirement B, 2026-10-31; epic #5529).

THE FOUR SELECTIONS (a row may match several; each is named in its correction reason):

  (b) retired   a retired coach's sealed / pending call — ``COACH_IDS`` excluded
                ``RETIRED_COACH_IDS``, so its two sealed bets sat pending 34+ days. Graded for
                the FIRST time through the evaluator's own write path (status, Bayesian
                confidence, LEARNING# row) and recorded in the ledger as pending → graded.
  (c) food      a MacroFactor-metric call whose grading window held a zero-entry day — the
                grader read a pre-filled ~80 kcal / ~15 g summary stub as intake (#5519 class).
  (d) aggregate a ``_Nday_avg`` number call — the point grader's aggregate branch returned
                before the ``after_day`` bound, so the mean on the target day was built from
                readings the coach had on the page when the call was filed.
  (e) HR regime an ``hrv* / resting_heart_rate / recovery_score`` call whose window spans the
                2026-10-10 marker (``health.hr_regime``) — grading mixed two HR regimes.

Every selected row is re-graded by the FIXED grader itself — ``coach_prediction_evaluator
._evaluate_all(write=False)`` — never a second derivation here. Then, per row:

  regrade      the verdict changed → ``grade_corrections.apply_correction``: the
               ``CORRECTION#{prediction_id}#{ts}`` ledger row first, then ``corrections[]``,
               ``original_grade`` (once) and the corrected ``status/outcome/outcome_date/
               outcome_notes`` on the prediction row, conditional on the stored status.
  first_grade  a retired coach's open call that is now due → the evaluator's own write, plus
               a ledger entry (``update_grade=False``) so pending → graded is on the record.
  restate      the verdict stands → ``quality_flags`` / ``evaluator_version`` stamped once;
               no ledger entry (a grade that did not change was not corrected).
  open         a retired coach's call not yet due → nothing; the daily grader owns it now.

The run's aggregate impact — the per-coach before/after table and the headline K-of-N delta
— is printed every run and, with --apply, written once as ``CORRECTION#SUMMARY#{ts}`` on the
evaluator's state partition. Selection is idempotent: a row already corrected under this
evaluator version for #5533 is never selected again.

RUN:  python3 deploy/regrade_predictions.py              # dry-run: the tables (post on #5533 BEFORE --apply)
      python3 deploy/regrade_predictions.py --json plan.json
      python3 deploy/regrade_predictions.py --apply      # writes the corrections + the summary row

Reads DynamoDB only in dry-run. --apply is a DynamoDB WRITE — an owner/driver act after the
owner has read the dry run, never a lane's — and is refused unless explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from boto3.dynamodb.conditions import Key  # noqa: E402
from coach import coach_record, grade_corrections, grading_quality  # noqa: E402
from coach.persona_registry import RETIRED_COACH_IDS  # noqa: E402
from coach.prediction_grading import build_outcome_notes  # noqa: E402
from coach.prediction_windows import effective_window_days, is_gradeable  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402
from common.pacific_time import pacific_today  # noqa: E402
from experiment.measurable_metrics import AGG_SUFFIXES, METRIC_SOURCES, base_metric  # noqa: E402
from experiment.phase_filter import singleton_visible  # noqa: E402

ISSUE = "#5533"
OPEN_STATUSES = ("pending", "confirming")
GRADED_STATUSES = ("confirmed", "refuted", "inconclusive", "expired")
STATUS_COLUMNS = ("confirmed", "refuted", "pending", "inconclusive", "expired")

RETIRED, FOOD, AGGREGATE, HR = "retired", "food_gap", "aggregate_after_day", "hr_regime"
REASON_WORDS = {
    RETIRED: f"{ISSUE} (b): a retired coach's sealed/pending call the grader never scanned (COACH_IDS excluded RETIRED_COACH_IDS)",
    FOOD: f"{ISSUE} (c): the grading window held a zero-entry MacroFactor day the grader read as ~80 kcal / ~15 g intake; re-graded with such days missing",
    AGGREGATE: f"{ISSUE} (d): a _Nday_avg number call averaged readings on or before the filing day; re-graded on readings after it only",
    HR: f"{ISSUE} (e): an HR-metric window spanning the 2026-10-10 regime marker (health.hr_regime); re-graded re-baselined after the marker",
}

REGRADE, FIRST_GRADE, RESTATE, OPEN = "regrade", "first_grade", "restate", "open"


def _evaluator():
    """The grader module — imported lazily so ``plan`` stays testable without AWS."""
    from coach import coach_prediction_evaluator as ev

    return ev


def partitions(ev) -> list[str]:
    """Every partition the FIXED grader scans — retired seats and the diary claims included."""
    return [f"COACH#{c}" for c in ev.GRADING_COACH_IDS] + [ev.DIARY_CLAIMS_PK]


def partition_rows(table, pk: str) -> list[dict]:
    """The whole PREDICTION# partition, paginated, unprojected, float-cast."""
    rows, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("PREDICTION#")}
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return [decimals_to_float(r) for r in rows]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def zero_entry_days(ev, start: str, end: str) -> set[str]:
    """The zero-entry MacroFactor days of this cycle, through the evaluator's own read."""
    return set(grading_quality.zero_entry_days(ev._fetch_range("macrofactor", start, end), start, end))


def _coach_of(row: dict) -> str:
    return str(row.get("coach_id") or str(row.get("pk") or "").replace("COACH#", "", 1) or "")


def _window_end(row: dict, spec: dict, today: str) -> str | None:
    days = spec.get("evaluation_window_days") or effective_window_days(spec, row.get("subdomain") or "")
    return grading_quality.window_end(row, spec, days, today)


def reasons_for(row: dict, *, today: str, zero_days: set[str], retired_ids=RETIRED_COACH_IDS, evaluator_version: str) -> list[str]:
    """Which of the four fixes touch this row — empty when none does (the row is left alone)."""
    spec = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
    status = str(row.get("status") or "")
    created = str(row.get("created_date") or "")[:10]
    if not singleton_visible(row) or not created or not is_gradeable(spec) or row.get("source") == "dispute_docket":
        return []
    if grade_corrections.already_corrected(row, evaluator_version=evaluator_version, reason_prefix=ISSUE):
        return []
    out = []
    if _coach_of(row) in retired_ids and status in OPEN_STATUSES:
        out.append(RETIRED)
    if status not in GRADED_STATUSES:
        return out
    metric = str(spec.get("metric") or "")
    end = _window_end(row, spec, today)
    if metric and end:
        if METRIC_SOURCES.get(base_metric(metric)) == "macrofactor" and any(created <= d <= end for d in zero_days):
            out.append(FOOD)
        if spec.get("type") == "point" and metric.endswith(AGG_SUFFIXES):
            out.append(AGGREGATE)
        if grading_quality.is_hr_metric(metric) and grading_quality.regime_split(created, end) is not None:
            out.append(HR)
    return out


def _action(before: str, after: dict | None) -> str:
    if after is None:
        return OPEN if before in OPEN_STATUSES else RESTATE
    if before in OPEN_STATUSES:
        return FIRST_GRADE if after["status"] not in OPEN_STATUSES else OPEN
    return REGRADE if after["status"] != before else RESTATE


def plan(rows_by_pk: dict[str, list[dict]], *, today: str, zero_days: set[str], ev, retired_ids=RETIRED_COACH_IDS) -> list[dict]:
    """One entry per selected row: its reasons, the grade before, the FIXED grader's grade after."""
    selected = []
    for pk, rows in rows_by_pk.items():
        for row in rows:
            reasons = reasons_for(row, today=today, zero_days=zero_days, retired_ids=retired_ids, evaluator_version=ev.ALGO_VERSION)
            if reasons:
                selected.append((row, reasons))
    if not selected:
        return []
    evaluations, _stats = ev._evaluate_all([dict(r) for r, _ in selected], today, write=False)
    by_id = {e["prediction_id"]: e for e in evaluations}
    entries = []
    for row, reasons in selected:
        pid = grade_corrections.prediction_id(row)
        e = by_id.get(pid)
        after = None
        if e is not None:
            after = {
                "status": e["status"],
                "outcome_date": today,
                "outcome_notes": build_outcome_notes(e, ev.ALGO_VERSION),
                "quality_flags": list(e.get("quality_flags") or []),
                "baseline": e.get("baseline"),
                "reason": e.get("reason", ""),
            }
        before = str(row.get("status") or "")
        entries.append(
            {
                "pk": row["pk"],
                "sk": row["sk"],
                "prediction_id": pid,
                "coach_id": _coach_of(row),
                "claim": str(row.get("claim_natural") or "")[:120],
                "metric": (row.get("evaluation") or {}).get("metric"),
                "created_date": row.get("created_date"),
                "reasons": reasons,
                "before": {"status": before, "outcome_date": row.get("outcome_date")},
                "after": after,
                "action": _action(before, after),
                "row": row,
            }
        )
    return entries


def after_rows(rows_by_pk: dict[str, list[dict]], entries: list[dict]) -> dict[str, list[dict]]:
    """The partitions as they will read once the plan is applied (status / outcome_date / flags)."""
    change = {(e["pk"], e["sk"]): e for e in entries if e["action"] in (REGRADE, FIRST_GRADE)}
    out = {}
    for pk, rows in rows_by_pk.items():
        new_rows = []
        for row in rows:
            e = change.get((row["pk"], row["sk"]))
            if e is None:
                new_rows.append(row)
                continue
            new_rows.append(dict(row, status=e["after"]["status"], outcome=e["after"]["status"], outcome_date=e["after"]["outcome_date"]))
        out[pk] = new_rows
    return out


def _counts(rows: list[dict]) -> dict:
    out = {k: 0 for k in STATUS_COLUMNS}
    for row in coach_record.resolved_once(rows):
        if not singleton_visible(row):
            continue
        s = str(row.get("status") or "")
        s = "pending" if s in OPEN_STATUSES else s
        if s in out:
            out[s] += 1
    return out


def coach_table(rows_by_pk: dict[str, list[dict]], entries: list[dict], *, genesis: str, today: str) -> dict:
    """``{coach_id: {before: {...counts, k, n}, after: {...}, selected, changed}}`` — K of N from the
    one record producer (``coach_record.record_from_rows``), as of ``today``."""
    after = after_rows(rows_by_pk, entries)
    out = {}
    for pk, rows in rows_by_pk.items():
        cid = str(pk).replace("COACH#", "", 1) if str(pk).startswith("COACH#") else "diary_claims"
        rb = coach_record.record_from_rows(rows, genesis=genesis, as_of=today)
        ra = coach_record.record_from_rows(after[pk], genesis=genesis, as_of=today)
        out[cid] = {
            "before": {**_counts(rows), "k": rb["confirmed"], "n": rb["n"]},
            "after": {**_counts(after[pk]), "k": ra["confirmed"], "n": ra["n"]},
            "selected": sum(1 for e in entries if e["pk"] == pk),
            "changed": sum(1 for e in entries if e["pk"] == pk and e["action"] in (REGRADE, FIRST_GRADE)),
        }
    return out


def headline(table: dict) -> dict:
    k0 = sum(c["before"]["k"] for c in table.values())
    n0 = sum(c["before"]["n"] for c in table.values())
    k1 = sum(c["after"]["k"] for c in table.values())
    n1 = sum(c["after"]["n"] for c in table.values())
    return {"before": {"k": k0, "n": n0}, "after": {"k": k1, "n": n1}, "delta": {"k": k1 - k0, "n": n1 - n0}}


def summary(entries: list[dict], table: dict, *, today: str, evaluator_version: str) -> dict:
    """The aggregate impact — what the dry run prints and --apply writes as CORRECTION#SUMMARY#."""
    actions = {a: sum(1 for e in entries if e["action"] == a) for a in (REGRADE, FIRST_GRADE, RESTATE, OPEN)}
    reasons = {r: sum(1 for e in entries if r in e["reasons"]) for r in REASON_WORDS}
    return {
        "issue": ISSUE,
        "evaluator_version": evaluator_version,
        "graded_as_of": today,
        "selected": len(entries),
        "actions": actions,
        "reasons": reasons,
        "headline": headline(table),
        "per_coach": table,
        "changes": [
            {k: e[k] for k in ("pk", "sk", "prediction_id", "coach_id", "reasons", "before")} | {"after": e["after"]["status"]}
            for e in entries
            if e["action"] in (REGRADE, FIRST_GRADE)
        ],
    }


# ── the writes ───────────────────────────────────────────────────────────────────────────


def apply(table, entries: list[dict], ev, *, today: str, summ: dict, now: datetime | None = None) -> tuple[dict, dict]:
    """Write the plan, then the one ``CORRECTION#SUMMARY#{ts}`` row carrying ``summ`` plus the
    applied counts. Returns ``({regrade, first_grade, restate, failed}, summary_item)``."""
    done = {REGRADE: 0, FIRST_GRADE: 0, RESTATE: 0, "failed": 0}
    for e in entries:
        row, after = e["row"], e["after"]
        reason = " | ".join(REASON_WORDS[r] for r in e["reasons"])
        try:
            if e["action"] == REGRADE:
                grade_corrections.apply_correction(table, row, after, reason=reason, evaluator_version=ev.ALGO_VERSION, now=now)
                done[REGRADE] += 1
            elif e["action"] == FIRST_GRADE:
                ev._evaluate_all([dict(row)], today)  # the evaluator's own write path: status, Bayesian confidence, LEARNING#
                grade_corrections.apply_correction(
                    table, row, after, reason=reason, evaluator_version=ev.ALGO_VERSION, now=now, update_grade=False
                )
                done[FIRST_GRADE] += 1
            elif e["action"] == RESTATE and after is not None:
                done[RESTATE] += grade_corrections.stamp_quality(table, row, after["quality_flags"], evaluator_version=ev.ALGO_VERSION)
        except Exception as exc:  # noqa: BLE001 — one row's failure must not stop the ledger; it is counted and printed
            done["failed"] += 1
            print(f"  FAILED {e['pk']} / {e['sk']}: {exc}", file=sys.stderr)
    item = grade_corrections.write_summary(table, {**summ, "applied": done}, now=now)
    return done, item


# ── the printed tables ───────────────────────────────────────────────────────────────────


def _cell(text: Any) -> str:
    return str(text if text is not None else "—").replace("|", "/").replace("\n", " ")


def coach_table_md(table: dict) -> str:
    head = "| coach | " + " | ".join(f"{c} before → after" for c in STATUS_COLUMNS) + " | K of N before → after | selected | changed |"
    lines = [head, "|" + "---|" * (len(STATUS_COLUMNS) + 4)]
    for cid, c in sorted(table.items()):
        if not c["selected"] and not c["before"]["n"]:
            continue
        cells = [f"{c['before'][k]} → {c['after'][k]}" for k in STATUS_COLUMNS]
        kn = f"{c['before']['k']} of {c['before']['n']} → {c['after']['k']} of {c['after']['n']}"
        lines.append(f"| {cid} | " + " | ".join(cells) + f" | {kn} | {c['selected']} | {c['changed']} |")
    return "\n".join(lines)


def changes_md(entries: list[dict]) -> str:
    rows = [e for e in entries if e["action"] in (REGRADE, FIRST_GRADE, RESTATE)]
    if not rows:
        return "_no row's grade changes_"
    lines = ["| coach | call | metric | filed | before | after | flags | action | reasons |", "|---|---|---|---|---|---|---|---|---|"]
    for e in sorted(rows, key=lambda e: (e["action"], e["coach_id"], e["sk"])):
        after = e["after"] or {}
        lines.append(
            f"| {_cell(e['coach_id'])} | {_cell(e['claim'][:70])} | {_cell(e['metric'])} | {_cell(e['created_date'])} | "
            f"{_cell(e['before']['status'])} | {_cell(after.get('status'))} | {_cell(','.join(after.get('quality_flags') or []) or 'clean')} | "
            f"{_cell(e['action'])} | {_cell(','.join(e['reasons']))} |"
        )
    return "\n".join(lines)


def report(entries: list[dict], table: dict, summ: dict) -> str:
    h = summ["headline"]
    out = [
        f"## {ISSUE} re-grade — dry run as of {summ['graded_as_of']} (evaluator {summ['evaluator_version']})",
        "",
        f"Selected {summ['selected']} row(s): " + ", ".join(f"{k}={v}" for k, v in summ["reasons"].items()),
        "Actions: " + ", ".join(f"{k}={v}" for k, v in summ["actions"].items()),
        f"Headline K of N: {h['before']['k']} of {h['before']['n']} → {h['after']['k']} of {h['after']['n']} "
        f"(Δk={h['delta']['k']:+d}, Δn={h['delta']['n']:+d})",
        "",
        "### Per coach",
        coach_table_md(table),
        "",
        "### Rows",
        changes_md(entries),
    ]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="WRITE the corrections + the summary row — default is a dry run")
    ap.add_argument("--json", help="also write the plan + summary to this path")
    ap.add_argument("--today", default=None, help="grade as of this Pacific day (default: today) — dry-run reproducibility only")
    args = ap.parse_args(argv)
    if args.apply and args.today:
        print("--today is a dry-run aid; --apply grades as of today", file=sys.stderr)
        return 2

    ev = _evaluator()
    table = ev.table
    today = args.today or pacific_today()
    genesis = EXPERIMENT_START_DATE
    rows_by_pk = {pk: partition_rows(table, pk) for pk in partitions(ev)}
    zero_days = zero_entry_days(ev, genesis, today)
    entries = plan(rows_by_pk, today=today, zero_days=zero_days, ev=ev)
    ctable = coach_table(rows_by_pk, entries, genesis=genesis, today=today)
    summ = summary(entries, ctable, today=today, evaluator_version=ev.ALGO_VERSION)
    print(report(entries, ctable, summ))
    print(f"\nzero-entry MacroFactor days this cycle: {len(zero_days)} ({', '.join(sorted(zero_days)) or 'none'})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(
                {"summary": summ, "entries": [{k: v for k, v in e.items() if k != "row"} for e in entries]}, fh, indent=2, default=str
            )
        print(f"plan written to {args.json}")

    if not args.apply:
        print("\ndry run — nothing written. Post this output on the issue; the owner reads it before --apply.")
        return 0
    done, item = apply(table, entries, ev, today=today, summ=summ, now=datetime.now(timezone.utc))
    print(f"\napplied: {done}\nsummary row: {item['pk']} / {item['sk']}")
    return 1 if done["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
