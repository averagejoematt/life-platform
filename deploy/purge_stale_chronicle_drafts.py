#!/usr/bin/env python3
"""
purge_stale_chronicle_drafts.py — delete unpublished chronicle DRAFTS that leak.

The truth audit (2026-06-27) found pre-#215 chronicle drafts in DynamoDB that name a
real public figure (Dr. Layne Norton, with a fabricated quote) and a vice (marijuana).
They are not live (status=draft), but the weekly publish path could promote one. The
publish path now refuses leaking/stale drafts (privacy_guard), and this one-off clears
the existing offenders.

SAFE BY DESIGN:
  • Dry-run by default — lists offending drafts, deletes nothing.
  • Only ever touches records with status == "draft". Published installments are
    NEVER deleted (a published leak would be a separate, louder problem to handle).
  • `--apply` performs the deletes (a DynamoDB write — run by Matthew).

    python3 deploy/purge_stale_chronicle_drafts.py           # dry run
    python3 deploy/purge_stale_chronicle_drafts.py --apply   # delete the offenders
"""

import argparse
import os
import sys

import boto3
from boto3.dynamodb.conditions import Key

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
import privacy_guard as pg  # noqa: E402

TABLE = os.environ.get("LIFE_PLATFORM_TABLE", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
PK = "USER#matthew#SOURCE#chronicle"

_CONTENT_FIELDS = ("title", "stats_line", "raw_installment", "body_html", "draft_blog_post_html", "draft_journal_post_html")


def main():
    ap = argparse.ArgumentParser(description="Purge leaking unpublished chronicle drafts.")
    ap.add_argument("--apply", action="store_true", help="Delete the offenders (DynamoDB write).")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    resp = table.query(KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with("DATE#"))
    items = resp.get("Items", [])
    print(f"Scanned {len(items)} chronicle records.\n")

    offenders = []
    for it in items:
        status = it.get("status", "published")
        blob = "\n".join(str(it.get(f, "")) for f in _CONTENT_FIELDS)
        violations = pg.find_violations(blob)
        if not violations:
            continue
        kinds = sorted({f"{k}:{t}" for k, t in violations})
        published = status != "draft"
        flag = "PUBLISHED ⚠️ (not auto-deleted — handle manually)" if published else "draft → DELETE"
        offenders.append((it["sk"], published, kinds))
        print(f"  {it['sk']}  [{status}]  {flag}")
        print(f"      violations: {', '.join(kinds)}")

    drafts = [o for o in offenders if not o[1]]
    pubs = [o for o in offenders if o[1]]
    print(f"\n{len(offenders)} offending record(s): {len(drafts)} draft(s) to delete, {len(pubs)} published (manual).")

    if not args.apply:
        print("\nDry run — nothing deleted. Re-run with --apply to delete the drafts.")
        return
    for sk, published, _ in offenders:
        if published:
            continue  # never auto-delete a published installment
        table.delete_item(Key={"pk": PK, "sk": sk})
        print(f"  deleted {sk}")
    print(f"\nDeleted {len(drafts)} leaking draft(s).")


if __name__ == "__main__":
    main()
