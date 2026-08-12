#!/usr/bin/env python3
"""paste_social_post.py — the low-tech input path for the closed platforms (#1677, epic #1668).

X, Instagram and TikTok cannot be polled: the paid X API tier and the Instagram/TikTok
Graph tokens are deliberately not provisioned (owner decision, 2026-08-12 — his money,
his accounts, app review). So the capture path is a paste, and this is where the paste
goes in.

    # stage a post (writes the PASTE# staging row, no ingestion yet)
    python3 scripts/paste_social_post.py --channel x \\
        --url https://x.com/averagejoematt/status/1234567890 \\
        --text "Day 4. The scale finally moved." --published 2026-08-11T17:04:00Z

    # stage it AND run the real framework ingestion for that day
    python3 scripts/paste_social_post.py --channel tiktok --url ... --text ... --ingest

    # ingest whatever is already staged for a day (no new paste)
    python3 scripts/paste_social_post.py --channel instagram --date 2026-08-11 --ingest-only

``--ingest`` runs ``closed_social_paste_lambda.ingest_pasted_day``, i.e. the same
``run_ingestion()`` framework path a Bluesky post takes: the pasted post gets the same
``#{post_id}``-suffixed write, the same S2 provenance membrane, the same sensitivity
gate. Without ``--ingest`` the paste just sits staged until something ingests it.

Needs ordinary AWS credentials (the DDB table + the raw/ archive prefix). It reads no
secret and makes no platform API call, because there is nothing to call.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ingestion import social_paste_inbox as inbox  # noqa: E402


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
        os.environ.get("TABLE_NAME", "life-platform")
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", required=True, choices=list(inbox.PASTE_ONLY_CHANNELS))
    ap.add_argument("--url", default="", help="the post's permalink — the post id is derived from it")
    ap.add_argument("--text", default="", help="the post's own words (paste them verbatim)")
    ap.add_argument("--published", default="", help="ISO timestamp of the post; defaults to today (Pacific)")
    ap.add_argument("--author", default="", help="the account handle, if it isn't obvious from the URL")
    ap.add_argument("--date", default="", help="override the Pacific day the post belongs to")
    ap.add_argument("--ingest", action="store_true", help="after staging, run the framework ingestion for that day")
    ap.add_argument("--ingest-only", action="store_true", help="ingest an already-staged day; stage nothing new")
    args = ap.parse_args(argv)

    date_str = args.date
    if not args.ingest_only:
        if not (args.text or args.url):
            ap.error("a paste needs at least --text or --url")
        item = inbox.stage_paste(
            _table(),
            args.channel,
            url=args.url,
            text=args.text,
            published_at=args.published,
            author=args.author,
            date_str=args.date,
        )
        date_str = item["date"]
        print(f"staged {args.channel} post {item['post_id']} for {date_str}")
        if inbox.is_synthetic_post_id(item["post_id"]):
            print("  note: no permalink recognised — the post id was hashed from the content")

    if args.ingest or args.ingest_only:
        if not date_str:
            ap.error("--ingest-only needs --date")
        from ingestion import closed_social_paste_lambda as paste_lambda

        result = paste_lambda.ingest_pasted_day(args.channel, {"date_override": date_str})
        print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
