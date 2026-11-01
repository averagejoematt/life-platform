#!/usr/bin/env python3
"""deploy/revert_regrade.py — restore the exact pre-#5533 grading state, on the record (owner ask, 2026-11-01).

The inverse of ``deploy/regrade_predictions.py --apply``. For every PREDICTION# row that run touched:

  revert    a row carrying ``original_grade`` with a #5533 correction under evaluator 1.1 → every field
            the snapshot holds is set back to its snapshotted value and every field the snapshot did not
            carry is REMOVED (``grade_corrections.revert_correction``): status, outcome, outcome_date,
            outcome_notes, baseline, quality_flags, evaluator_version. The ledger gains a
            ``CORRECTION#{prediction_id}#{ts}`` row marked ``reverts: true`` FIRST, and ``corrections[]``
            the same entry — the trail reads correction → reversal; nothing is deleted and
            ``original_grade`` stays as the proof.
  unstamp   a row the run only annotated (``restate``: ``quality_flags`` + ``evaluator_version`` 1.1, no
            ``original_grade``) → the two attributes are removed (``grade_corrections.unstamp_quality``).

Safety: selection is idempotent (``reverted_already``; the unstamp is conditional on the version that
stamped it); every write is conditional on the row still carrying the status being reverted; a second
run selects nothing. After a revert, ``already_corrected`` still sees the #5533 entry, so a re-run of
``regrade_predictions.py`` selects nothing either — re-applying is a deliberate new decision, not a
drift back. The ``CONFIDENCE#`` posterior and ``LEARNING#`` rows the first grade wrote are not touched by
the correction and not touched here (the same residual the correction names).

RUN:  python3 deploy/revert_regrade.py              # dry-run: the table of what would be restored
      python3 deploy/revert_regrade.py --json plan.json
      python3 deploy/revert_regrade.py --apply      # WRITE — owner-authorised only
      python3 deploy/revert_regrade.py --plan plan.json --pre pre.json [--apply]
                                                    # scoped to the run that plan describes: un-stamps only
                                                    # the rows it restated (owner condition 6, 2026-11-01)
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
sys.path.insert(0, os.path.join(ROOT, "deploy"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import grade_corrections  # noqa: E402

ISSUE = "#5533"
EVALUATOR_VERSION = "1.1"
REVERT, UNSTAMP = "revert", "unstamp"


def stamped_by_the_run(plan: dict | None, pre: dict | None) -> set[tuple[str, str]] | None:
    """The restate rows the correction run itself stamped: in the plan as `restate` AND carrying no
    `quality_flags` in the pre-change snapshot. None when no plan was given (every 1.1 stamp is eligible).

    Owner condition 6 (2026-11-01): the scheduled evaluator writes the same `evaluator_version` and
    `quality_flags` on rows it grades itself (the retired coach's two bets, an inconclusive HR-window call,
    graded 2026-11-01 before the correction ran). Those are legitimate and not ours to undo; the data
    cannot tell them apart from a restate stamp, so the plan + the pre-change snapshot are the scope."""
    if plan is None:
        return None
    pre_rows = {(r["pk"], r["sk"]): r for r in ((pre or {}).get("rows") or [])}
    out: set[tuple[str, str]] = set()
    for e in plan.get("entries") or []:
        if e.get("action") != "restate":
            continue
        key = (e["pk"], e["sk"])
        if pre is not None and "quality_flags" in (pre_rows.get(key) or {}):
            continue  # already stamped before the run → the run's stamp was a no-op → nothing to undo
        out.add(key)
    return out


def select(
    rows_by_pk: dict[str, list[dict]],
    *,
    evaluator_version: str = EVALUATOR_VERSION,
    issue: str = ISSUE,
    plan: dict | None = None,
    pre: dict | None = None,
) -> list[dict]:
    """The rows the #5533 run touched and this run would restore — pure. With `plan` (the run's --json file)
    and `pre` (the pre-change snapshot), an un-stamp is offered ONLY for rows that run stamped."""
    scope = stamped_by_the_run(plan, pre)
    out: list[dict] = []
    for pk, rows in rows_by_pk.items():
        for row in rows:
            if not isinstance(row, dict):
                continue
            og = row.get("original_grade")
            if isinstance(og, dict) and og:
                if grade_corrections.already_corrected(
                    row, evaluator_version=evaluator_version, reason_prefix=issue
                ) and not grade_corrections.reverted_already(row):
                    out.append(
                        {
                            "pk": pk,
                            "sk": row.get("sk"),
                            "action": REVERT,
                            "row": row,
                            "now": row.get("status"),
                            "restored": og.get("status"),
                        }
                    )
            elif str(row.get("evaluator_version") or "") == evaluator_version and "quality_flags" in row:
                if scope is not None and (pk, row.get("sk")) not in scope:
                    continue  # the evaluator's own stamp, not the correction run's
                out.append(
                    {"pk": pk, "sk": row.get("sk"), "action": UNSTAMP, "row": row, "now": row.get("status"), "restored": row.get("status")}
                )
    return out


def apply(table: Any, entries: list[dict], *, now: datetime | None = None) -> dict:
    done = {REVERT: 0, UNSTAMP: 0, "skipped": 0, "failed": 0}
    for e in entries:
        try:
            if e["action"] == REVERT:
                res = grade_corrections.revert_correction(
                    table,
                    e["row"],
                    reason=f"{grade_corrections.REVERT_REASON_PREFIX} {ISSUE} — owner-authorised restore of the pre-correction grade",
                    now=now,
                )
                done[REVERT if res else "skipped"] += 1
            else:
                ok = grade_corrections.unstamp_quality(table, e["row"], evaluator_version=EVALUATOR_VERSION)
                done[UNSTAMP if ok else "skipped"] += 1
        except Exception as exc:  # noqa: BLE001 — one row's failure is counted and printed, never hidden
            done["failed"] += 1
            print(f"  FAILED {e['pk']} / {e['sk']}: {exc}", file=sys.stderr)
    grade_corrections.write_summary(
        table, {"kind": "revert", "issue": ISSUE, "evaluator_version": EVALUATOR_VERSION, "applied": done}, now=now
    )
    return done


def report(entries: list[dict]) -> str:
    lines = [
        f"## {ISSUE} revert — {'dry run' if entries is not None else ''}",
        "",
        f"Selected {len(entries)} row(s): " + ", ".join(f"{k}={sum(1 for e in entries if e['action'] == k)}" for k in (REVERT, UNSTAMP)),
        "",
        "| coach | call | action | now → restored |",
        "|---|---|---|---|",
    ]
    for e in entries:
        row = e["row"]
        claim = str(row.get("claim_natural") or "")[:70].replace("|", "/")
        lines.append(f"| {str(e['pk']).replace('COACH#', '')} | {claim} | {e['action']} | {e['now']} → {e['restored']} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="WRITE the reversals + a revert summary row — default is a dry run")
    ap.add_argument("--json", help="also write the plan as JSON")
    ap.add_argument("--plan", help="the correction run's --json plan file: scope the un-stamps to the rows that run restated")
    ap.add_argument("--pre", help="the pre-change snapshot (rows[] with pk/sk): a row already stamped before the run is left alone")
    args = ap.parse_args(argv)
    plan = json.load(open(args.plan, encoding="utf-8")) if args.plan else None
    pre = json.load(open(args.pre, encoding="utf-8")) if args.pre else None
    import boto3  # noqa: E402
    import regrade_predictions as regrade  # noqa: E402 — the same partition reader the correction used

    ev = regrade._evaluator()
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    rows_by_pk = {pk: regrade.partition_rows(table, pk) for pk in regrade.partitions(ev)}
    entries = select(rows_by_pk, plan=plan, pre=pre)
    print(report(entries))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([{k: v for k, v in e.items() if k != "row"} for e in entries], fh, indent=2, default=str)
    if not args.apply:
        print("\ndry run — nothing written.")
        return 0
    done = apply(table, entries, now=datetime.now(timezone.utc))
    print(f"\napplied: {done}")
    return 1 if done["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
