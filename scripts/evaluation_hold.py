#!/usr/bin/env python3
"""scripts/evaluation_hold.py — set or release an owner evaluation hold on PREDICTION# rows (#5607).

The owner's 2026-11-03 ruling (item 2): "Authorize a targeted, logged evaluation hold on the identified
pending calls while their rulings are reviewed ... Leave unaffected evaluation running." What a hold does
to grading is ``lambdas/coach/evaluation_hold.py``; this is the ONE writer of the hold.

PER ROW, IN THIS ORDER (``--apply`` only):

  (a) ``put_item`` of an audit row ``pk=COACH#<id>``, ``sk=EVALHOLD#<prediction_id>#<ISO>`` — action
      set|release, reason, actor "owner", the row's prior status (and, on release, the hold released);
  (b) a conditional ``update_item`` on the PREDICTION# row that touches ONLY ``evaluation_hold``:
        set      SET evaluation_hold = :h
                 IF attribute_exists(sk) AND #s IN (:pending, :confirming) AND attribute_not_exists(evaluation_hold)
        release  REMOVE evaluation_hold  IF attribute_exists(evaluation_hold)

Audit FIRST: a failure between the two leaves a visible audit row and an unheld (or still-held) prediction —
recoverable, and a re-run is idempotent (the pre-read skips a row already in the target state, and the
condition refuses one that changed underneath). status / outcome / outcome_notes are never written.

DRY RUN BY DEFAULT: reads each row (read-only get_item) and prints the exact writes it would make.

    python3 scripts/evaluation_hold.py set --coach-pk COACH#labs_coach --prediction-id pred_x --reason "..."
    python3 scripts/evaluation_hold.py set --manifest holds.json            # dry run
    python3 scripts/evaluation_hold.py set --manifest holds.json --apply    # the writes (owner/driver act)
    python3 scripts/evaluation_hold.py release --manifest holds.json --reason "ruled on" --apply

A manifest is a JSON list (or ``{"holds": [...]}``) of ``{coach_pk, prediction_id, reason?, issue?}``;
an entry's ``reason`` overrides ``--reason``.
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

from coach import evaluation_hold  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"
ACTOR = "owner"
RULING_REF = "#5607"
PREDICTION_PREFIX = "PREDICTION#"


def _table():  # pragma: no cover — the live table; tests pass a fake
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_entries(args: argparse.Namespace) -> list[dict]:
    if args.manifest:
        with open(args.manifest, encoding="utf-8") as fh:
            raw = json.load(fh)
        rows = raw.get("holds") if isinstance(raw, dict) else raw
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
        out.append({"coach_pk": coach_pk, "prediction_id": pid, "reason": reason, "issue": r.get("issue") or args.issue})
    return out


def hold_map(entry: dict, at: str) -> dict:
    h = {"reason": entry["reason"], "set_at": at, "set_by": ACTOR, "ruling_ref": RULING_REF}
    if entry.get("issue"):
        h["issue"] = str(entry["issue"])
    return h


def plan_writes(action: str, entry: dict, row: dict | None, at: str) -> tuple[str, list[dict]]:
    """``(verdict, writes)`` for one entry — pure. ``writes`` is ``[("put_item", kwargs), ("update_item", kwargs)]``
    as dicts, audit first; empty when the row is missing or already in the target state."""
    pk, pid = entry["coach_pk"], entry["prediction_id"]
    sk = f"{PREDICTION_PREFIX}{pid}"
    if row is None:
        return "skip: no such PREDICTION# row", []
    status = str(row.get("status") or "")
    prior_hold = evaluation_hold.hold_of(row)
    if action == "set":
        if prior_hold is not None:
            return "skip: already held", []
        if status not in evaluation_hold.HOLDABLE_STATUSES:
            return f"skip: status {status!r} is not pending/confirming", []
    elif prior_hold is None:
        return "skip: not held", []

    from experiment.phase_taxonomy import experiment_stamp_for

    audit_sk = f"{evaluation_hold.AUDIT_SK_PREFIX}{pid}#{at}"
    audit = {
        **experiment_stamp_for(pk, audit_sk),
        "pk": pk,
        "sk": audit_sk,
        "action": action,
        "prediction_id": pid,
        "prediction_sk": sk,
        "reason": entry["reason"],
        "actor": ACTOR,
        "ruling_ref": RULING_REF,
        "at": at,
        "prior_status": status,
    }
    if entry.get("issue"):
        audit["issue"] = str(entry["issue"])
    if action == "set":
        h = hold_map(entry, at)
        audit["hold"] = h
        update = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": f"SET {evaluation_hold.ATTR} = :h",
            "ConditionExpression": f"attribute_exists(sk) AND #s IN (:pending, :confirming) AND attribute_not_exists({evaluation_hold.ATTR})",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":h": h, ":pending": "pending", ":confirming": "confirming"},
        }
    else:
        audit["released_hold"] = prior_hold
        update = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": f"REMOVE {evaluation_hold.ATTR}",
            "ConditionExpression": f"attribute_exists({evaluation_hold.ATTR})",
        }
    return "write", [{"op": "put_item", "kwargs": {"Item": audit}}, {"op": "update_item", "kwargs": update}]


def _conditional_failed(exc: Exception) -> bool:
    return (getattr(exc, "response", None) or {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def run(action: str, entries: list[dict], table: Any, *, apply: bool, now: datetime | None = None, out=sys.stdout) -> dict:
    """Plan (and with ``apply``, perform) every entry. Returns counts ``{written, skipped, refused, failed}``."""
    counts = {"written": 0, "skipped": 0, "refused": 0, "failed": 0}
    mode = "APPLY" if apply else "DRY RUN — nothing is written"
    print(f"evaluation_hold {action} — {mode} — {len(entries)} row(s)", file=out)
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
