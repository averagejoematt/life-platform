#!/usr/bin/env python3
"""scripts/classification_review.py — put a SETTLED grade under classification review, or release it (owner ruling 2026-11-03).

The owner's rulings (2026-11-03): "Preserve the existing verdict in the audit history, but flag it as disputed pending
classification. Do not silently re-grade it." and "Keep the original verdict preserved but explicitly disputed and
excluded from any claim that its outcome has been reliably verified, pending classification." What the flag does to
grade writers and to every count is ``lambdas/coach/classification_review.py``; this is the ONE writer of the flag.

PER ROW, IN THIS ORDER (``--apply`` only):

  (a) ``put_item`` of an audit row ``pk=COACH#<id>``, ``sk=CLASSREVIEW#<prediction_id>#<ISO>`` — action set|release,
      reason, actor "owner", ruling_ref, and ``verdict``: the grade exactly as it stands (status, outcome,
      outcome_date, outcome_notes, evaluator_version, quality_flags) — the preserved verdict, in the audit history;
  (b) a conditional ``update_item`` on the PREDICTION# row that touches ONLY ``classification_review``:
        set      SET classification_review = :r
                 IF attribute_exists(sk) AND #s IN (:status) AND attribute_not_exists(classification_review)
        release  REMOVE classification_review  IF attribute_exists(classification_review)

A review is set only on a SETTLED row (``grade_corrections.is_settled``) — an open call is held with
``scripts/evaluation_hold.py`` instead. Audit FIRST: a failure between the two leaves a visible audit row and an
unflagged (or still-flagged) prediction — recoverable; a re-run is idempotent (the pre-read skips a row already in the
target state, the condition refuses one whose verdict changed underneath). status / outcome / outcome_date /
outcome_notes / evaluation / claim_natural are never written.

The ``reason`` is PUBLISHED (``/api/ledger_export`` ``classification_review_reason``) — write it for a public reader.

A review is normally ended by the owner's ruling itself (``grade_corrections.apply_correction(basis="ruling")``, which
records the resolution and removes the flag); ``release`` is for withdrawing the dispute without a ruling.

DRY RUN BY DEFAULT: reads each row (read-only get_item) and prints the exact writes it would make.

    python3 scripts/classification_review.py set --manifest review.json            # dry run
    python3 scripts/classification_review.py set --manifest review.json --apply    # the writes (owner/driver act)
    python3 scripts/classification_review.py release --manifest review.json --reason "withdrawn" --apply

A manifest is a JSON list (or ``{"reviews": [...]}``) of ``{coach_pk, prediction_id, reason?, ruling_ref?, issue?}``;
an entry's ``reason`` / ``ruling_ref`` override ``--reason`` / ``--ruling-ref``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from coach import classification_review, grade_corrections  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"
ACTOR = "owner"
DEFAULT_RULING_REF = "owner ruling 2026-11-03"
PREDICTION_PREFIX = "PREDICTION#"
#: The grade as it stands, copied into the audit row — the preserved verdict.
VERDICT_FIELDS = ("status", "outcome", "outcome_date", "outcome_notes", "evaluator_version", "quality_flags")


def _table():  # pragma: no cover — the live table; tests pass a fake
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_entries(args: argparse.Namespace) -> list[dict]:
    if args.manifest:
        with open(args.manifest, encoding="utf-8") as fh:
            raw = json.load(fh)
        rows = raw.get("reviews") if isinstance(raw, dict) else raw
    else:
        rows = [{"coach_pk": args.coach_pk, "prediction_id": args.prediction_id}]
    out = []
    for r in rows or []:
        coach_pk, pid = str(r.get("coach_pk") or ""), str(r.get("prediction_id") or "")
        if not coach_pk.startswith("COACH#") or not pid:
            raise SystemExit(f"bad entry (need coach_pk COACH#<id> and prediction_id): {r}")
        reason = str(r.get("reason") or args.reason or "").strip()
        if not reason:
            raise SystemExit(f"no reason for {coach_pk} / {pid}: pass --reason or set it in the manifest")
        out.append(
            {
                "coach_pk": coach_pk,
                "prediction_id": pid,
                "reason": reason,
                "ruling_ref": str(r.get("ruling_ref") or args.ruling_ref or DEFAULT_RULING_REF),
                "issue": r.get("issue") or args.issue,
            }
        )
    return out


def verdict_of(row: dict) -> dict:
    return {k: row.get(k) for k in VERDICT_FIELDS if row.get(k) is not None}


def review_map(entry: dict, row: dict, at: str) -> dict:
    r = {"reason": entry["reason"], "set_at": at, "set_by": ACTOR, "ruling_ref": entry["ruling_ref"], "verdict": row.get("status")}
    if entry.get("issue"):
        r["issue"] = str(entry["issue"])
    return r


def plan_writes(action: str, entry: dict, row: dict | None, at: str) -> tuple[str, list[dict]]:
    """``(verdict, writes)`` for one entry — pure. ``writes`` is ``[put_item, update_item]`` as dicts, audit first;
    empty when the row is missing, not settled, or already in the target state."""
    pk, pid = entry["coach_pk"], entry["prediction_id"]
    sk = f"{PREDICTION_PREFIX}{pid}"
    if row is None:
        return "skip: no such PREDICTION# row", []
    status = str(row.get("status") or "")
    prior = classification_review.review_of(row)
    if action == "set":
        if prior is not None:
            return "skip: already under classification review", []
        if not grade_corrections.is_settled(row):
            return f"skip: status {status!r} is not a settled grade (an open call is held with scripts/evaluation_hold.py)", []
    elif prior is None:
        return "skip: not under classification review", []

    from experiment.phase_taxonomy import experiment_stamp_for

    audit_sk = f"{classification_review.AUDIT_SK_PREFIX}{pid}#{at}"
    audit = {
        **experiment_stamp_for(pk, audit_sk),
        "pk": pk,
        "sk": audit_sk,
        "action": action,
        "prediction_id": pid,
        "prediction_sk": sk,
        "reason": entry["reason"],
        "actor": ACTOR,
        "ruling_ref": entry["ruling_ref"],
        "at": at,
        "prior_status": status,
        "verdict": verdict_of(row),  # the verdict preserved, as it stands — never re-graded here
    }
    if entry.get("issue"):
        audit["issue"] = str(entry["issue"])
    if action == "set":
        r = review_map(entry, row, at)
        audit["review"] = r
        update = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": f"SET {classification_review.ATTR} = :r",
            "ConditionExpression": f"attribute_exists(sk) AND #s IN (:status) AND attribute_not_exists({classification_review.ATTR})",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":r": r, ":status": status},
        }
    else:
        audit["released_review"] = prior
        update = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": f"REMOVE {classification_review.ATTR}",
            "ConditionExpression": f"attribute_exists({classification_review.ATTR})",
        }
    return "write", [{"op": "put_item", "kwargs": {"Item": audit}}, {"op": "update_item", "kwargs": update}]


def _conditional_failed(exc: Exception) -> bool:
    return (getattr(exc, "response", None) or {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def run(action: str, entries: list[dict], table: Any, *, apply: bool, now: datetime | None = None, out=sys.stdout) -> dict:
    """Plan (and with ``apply``, perform) every entry. Returns counts ``{written, skipped, refused, failed}``."""
    counts = {"written": 0, "skipped": 0, "refused": 0, "failed": 0}
    mode = "APPLY" if apply else "DRY RUN — nothing is written"
    print(f"classification_review {action} — {mode} — {len(entries)} row(s)", file=out)
    for entry in entries:
        at = now_iso(now)
        sk = f"{PREDICTION_PREFIX}{entry['prediction_id']}"
        try:
            row = table.get_item(Key={"pk": entry["coach_pk"], "sk": sk}).get("Item")
        except Exception as exc:  # noqa: BLE001 — one row's read failure is counted, never fatal
            counts["failed"] += 1
            print(f"  FAILED read {entry['coach_pk']} / {sk}: {exc}", file=out)
            continue
        verdict, writes = plan_writes(action, entry, row, at)
        status = (row or {}).get("status")
        print(f"- {entry['coach_pk']} / {sk}  status={status}  -> {verdict}", file=out)
        if not writes:
            counts["skipped"] += 1
            continue
        for w in writes:
            print(f"    {w['op']}: {json.dumps(w['kwargs'], sort_keys=True, default=str)}", file=out)
        if not apply:
            continue
        try:
            table.put_item(**writes[0]["kwargs"])
            table.update_item(**writes[1]["kwargs"])
            counts["written"] += 1
        except Exception as exc:  # noqa: BLE001
            if _conditional_failed(exc):
                counts["refused"] += 1
                print("    REFUSED by the condition (row changed since the read) — the audit row records the attempt", file=out)
            else:
                counts["failed"] += 1
                print(f"    FAILED: {exc}", file=out)
    print(f"summary: {json.dumps(counts, sort_keys=True)}", file=out)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("set", "release"))
    ap.add_argument("--coach-pk")
    ap.add_argument("--prediction-id")
    ap.add_argument("--reason", default="")
    ap.add_argument("--ruling-ref", default=None)
    ap.add_argument("--issue", default=None)
    ap.add_argument("--manifest")
    ap.add_argument("--apply", action="store_true", help="perform the writes (default: dry run)")
    args = ap.parse_args(argv)
    if not args.manifest and not (args.coach_pk and args.prediction_id):
        ap.error("pass --manifest FILE, or --coach-pk and --prediction-id")
    counts = run(args.action, load_entries(args), _table(), apply=args.apply)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
