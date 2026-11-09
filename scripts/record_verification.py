#!/usr/bin/env python3
"""scripts/record_verification.py — write the append-only verification record for each call in a manifest (owner 2026-11-09).

The record's shape, its outcome rules and its one writer are ``lambdas/coach/verification_record.py``. Per call:

  1. read the PREDICTION# row (``get_item``, read-only);
  2. re-run the CURRENT evaluator on it, purely — ``coach_prediction_evaluator._evaluate_all([row], today, write=False)``
     over the frozen spec and the readings in the table (reads only; the evaluator's write path is never reached);
  3. read the evidence the verdict rests on (the evaluator's own ``_fetch_range``), per metric the spec names;
  4. build the ``VERIFY#<prediction_id>#<ISO>`` row and the ``latest_verification`` pointer, and PRINT both writes.

DRY RUN BY DEFAULT: nothing is written. ``--apply`` performs the writes through
``verification_record.write_verification`` — an owner/driver act, run only after the owner has approved the
classifications and read the dry run. Never a lane's.

The classification is the OWNER'S: a manifest entry validates a classification only when it carries
``approved_classification`` AND ``classification_ruling_ref``. ``proposed_classification`` (the manifest v3 field) is
recorded as proposed and validates nothing, so a dry run over an unapproved manifest marks every call
``classification_validated: false`` whatever its outcome.

    python3 scripts/record_verification.py --manifest manifest_v3.json             # dry run
    python3 scripts/record_verification.py --manifest approved.json --json plan.json
    python3 scripts/record_verification.py --manifest approved.json --apply        # owner/driver only

A manifest is a JSON list, or ``{"rows": [...]}`` / ``{"verifications": [...]}``, of entries naming a call by
``coach_pk`` (``COACH#<id>``) or ``coach`` / ``key`` (``<coach_id>|<prediction_id>``, the manifest v3 form) plus
``prediction_id``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import grade_corrections, verification_record as vr  # noqa: E402
from coach.prediction_windows import is_gradeable  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"
PREDICTION_PREFIX = "PREDICTION#"


def _table():  # pragma: no cover — the live table; tests pass a fake
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def _evaluator():  # pragma: no cover — imported lazily so the planner stays testable without AWS
    from coach import coach_prediction_evaluator as ev

    return ev


def now_iso(now: datetime | None = None) -> str:
    return grade_corrections.now_iso(now)


def load_entries(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    rows = raw if isinstance(raw, list) else (raw.get("verifications") or raw.get("rows") or [])
    out = []
    for r in rows:
        key_coach, _, key_pid = str(r.get("key") or "").partition("|")
        coach = str(r.get("coach_pk") or "").replace("COACH#", "", 1) or key_coach
        if not coach and r.get("coach"):
            coach = str(r["coach"]) if str(r["coach"]).endswith("_coach") else f"{r['coach']}_coach"
        pid = str(r.get("prediction_id") or key_pid)
        if not coach or not pid:
            raise SystemExit(f"bad entry (need coach_pk / coach / key and prediction_id): {r}")
        out.append({**r, "coach_pk": f"COACH#{coach}", "prediction_id": pid})
    return out


def rerun(ev, row: dict, today: str) -> dict | None:
    """The current evaluator's grade of this call, pure — None when it gives none (held, ungradeable, a docket bet)."""
    spec = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
    if row.get("source") == "dispute_docket" or not spec or not is_gradeable(spec):
        return None
    evaluations, _stats = ev._evaluate_all([dict(row)], today, write=False)
    pid = grade_corrections.prediction_id(row)
    return next((e for e in evaluations if e.get("prediction_id") == pid), None)


def series_reader(ev) -> Callable[[str, str, str, str], list]:
    """The evidence read: the evaluator's own ``_fetch_range`` + ``_extract_metric_series`` (reads only)."""
    return lambda source, base, lo, hi: ev._extract_metric_series(ev._fetch_range(source, lo, hi), base)


def plan_entry(entry: dict, row: dict | None, *, ev, today: str, at: str) -> tuple[str, dict | None, list[dict]]:
    """``(verdict, record, writes)`` for one entry. ``writes`` is ``[put_item, update_item]``, empty when skipped."""
    if row is None:
        return "skip: no such PREDICTION# row", None, []
    if str(row.get("status") or "") not in grade_corrections.TERMINAL_STATUSES:
        return f"skip: status {row.get('status')!r} is not a graded verdict", None, []
    graded = rerun(ev, row, today)
    record = vr.build_record(
        row,
        graded,
        evidence_entries=vr.evidence(row, graded, today, series_reader(ev)),
        classification=vr.classification_of(entry),
        ruleset_version=str(ev.ALGO_VERSION),
        verified_at=at,
    )
    return "write", record, vr.plan_writes(row, record)


def run(entries: list[dict], table: Any, *, ev, today: str, apply: bool, now: datetime | None = None, out=sys.stdout) -> dict:
    """Plan (and with ``apply``, perform) every entry. Returns counts by outcome plus skipped / failed / written."""
    counts: dict = {o: 0 for o in vr.OUTCOMES} | {"classification_validated": 0, "skipped": 0, "failed": 0, "written": 0}
    plans: list = []
    print(f"record_verification — {'APPLY' if apply else 'DRY RUN — nothing is written'} — {len(entries)} call(s), as of {today}", file=out)
    for entry in entries:
        sk = f"{PREDICTION_PREFIX}{entry['prediction_id']}"
        try:
            row = table.get_item(Key={"pk": entry["coach_pk"], "sk": sk}).get("Item")
        except Exception as exc:  # noqa: BLE001 — one row's read failure is counted, never fatal
            counts["failed"] += 1
            print(f"  FAILED read {entry['coach_pk']} / {sk}: {exc}", file=out)
            continue
        row = decimals_to_float(row) if row else None
        verdict, record, writes = plan_entry(entry, row, ev=ev, today=today, at=now_iso(now))
        print(f"- {entry['coach_pk']} / {sk} -> {verdict}", file=out)
        if not writes:
            counts["skipped"] += 1
            continue
        counts[record["outcome"]] += 1
        counts["classification_validated"] += int(bool(record["classification_validated"]))
        plans.append(record)
        for w in writes:
            print(f"    {w['op']}: {json.dumps(w['kwargs'], sort_keys=True, default=str)}", file=out)
        if not apply:
            continue
        try:
            vr.write_verification(table, row, record)
            counts["written"] += 1
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            print(f"    FAILED: {exc}", file=out)
    print(f"summary: {json.dumps(counts, sort_keys=True)}", file=out)
    counts["records"] = plans
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--today", default=None, help="the evaluator's as-of day (default: Pacific today)")
    ap.add_argument("--json", default=None, help="also write the planned records here")
    ap.add_argument("--apply", action="store_true", help="perform the writes (default: dry run) — owner/driver only")
    args = ap.parse_args(argv)
    from common.pacific_time import pacific_today

    today = args.today or pacific_today()
    counts = run(load_entries(args.manifest), _table(), ev=_evaluator(), today=today, apply=args.apply, now=datetime.now(timezone.utc))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(counts["records"], fh, indent=1, sort_keys=True, default=str)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
