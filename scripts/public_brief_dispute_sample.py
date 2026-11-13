#!/usr/bin/env python3
"""scripts/public_brief_dispute_sample.py — pull the brief's settled disputes as a small sample (read-only).

Each row is one ``COACH#<coach> / PUBLIC_BRIEF#<cycle>#DISPUTE#<pair>#<metric>`` record (``coach.public_brief_disputes``)
joined to BOTH sides' ``PREDICTION#`` rows: the rendered claims, the frozen opposition criterion, each side's frozen
evaluation spec and filing window, and each side's ledger grade (status, outcome date, the grader's notes). By default
only disputes whose two sides are BOTH settled (``grade_corrections.is_settled``) are printed — nothing is manufactured,
and a cycle with no settled dispute prints nothing.

    python3 scripts/public_brief_dispute_sample.py                  # every settled dispute, newest cycle first (JSON lines)
    python3 scripts/public_brief_dispute_sample.py --limit 5        # a small sample
    python3 scripts/public_brief_dispute_sample.py --all            # pending ones too (each row says settled true/false)
    python3 scripts/public_brief_dispute_sample.py --cycle 2026-11-16

Reads only (Query + GetItem on the life-platform table); writes nothing. The brief is dark (``PUBLICATION_LIVE`` False):
the output is for the owner's own review, not for publication.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import public_brief as PB, public_brief_disputes as DISP  # noqa: E402
from common import public_brief_policy as POL  # noqa: E402


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def dispute_rows(table, coach_ids, cycle=None) -> list:
    out = []
    for cid in coach_ids:
        prefix = POL.brief_sk(cycle) + POL.DISPUTE_TAG if cycle else POL.BRIEF_SK_PREFIX
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
            "ExpressionAttributeValues": {":pk": f"COACH#{cid}", ":p": prefix},
        }
        while True:
            resp = table.query(**kwargs)
            out.extend(r for r in resp.get("Items", []) if DISP.is_dispute_sk(r.get("sk")))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return out


def sample(table, coach_ids, *, cycle=None, include_pending=False, limit=None) -> list:
    rows = []
    for d in dispute_rows(table, coach_ids, cycle):
        ledger = {}
        for s in d.get("sides") or []:
            pid, cid = s.get("prediction_id"), s.get("coach_id")
            if pid and cid:
                ledger[pid] = table.get_item(Key={"pk": f"COACH#{cid}", "sk": f"PREDICTION#{pid}"}).get("Item") or {}
        row = DISP.sample_row(d, ledger)
        if include_pending or row["settled"]:
            rows.append(_plain(row))
    rows.sort(key=lambda r: (str(r.get("brief_cycle")), str(r.get("generated_at"))), reverse=True)
    return rows[:limit] if limit else rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="include disputes whose sides are not both settled")
    ap.add_argument("--cycle", default=None, help="one cycle (its Monday, YYYY-MM-DD)")
    ap.add_argument("--coach", action="append", help="a coach id (repeatable); default: every brief coach")
    args = ap.parse_args(argv)
    import boto3

    table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
        os.environ.get("TABLE_NAME", "life-platform")
    )
    rows = sample(table, args.coach or PB.brief_coaches(), cycle=args.cycle, include_pending=args.all, limit=args.limit)
    for r in rows:
        print(json.dumps(r, sort_keys=True, default=str))
    print(f"# {len(rows)} dispute(s){'' if args.all else ' with both sides settled'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
