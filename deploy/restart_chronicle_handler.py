#!/usr/bin/env python3
"""
restart_chronicle_handler.py — ADR-058: Chronicle hide + archive for the
experiment restart. Reads genesis from lambdas/constants.py.

Per spec §7 + Matthew's D decision:
  - All chronicle DDB records: already tombstoned + hidden=true via §5 wipe
  - This script handles the S3 + frontend side:
      1. Move all chronicle HTML under blog/ to blog/archive/pilot/<key>
         (tombstone-overwrite original since IAM blocks DeleteObject)
      2. Rewrite chronicle index page(s) to show empty Day-1 state
      3. Optionally resurrect 1-2 entries via --resurrect-sk (re-date them
         to a date in the genesis week, untombstone the DDB record, copy
         their S3 HTML to a new key under blog/)

Date-agnostic. Idempotent — re-running won't re-archive already-archived
files (checks existence first).

Usage:
    python3 deploy/restart_chronicle_handler.py            # dry-run
    python3 deploy/restart_chronicle_handler.py --apply    # commit
    python3 deploy/restart_chronicle_handler.py --apply --resurrect-sk DATE#2026-05-16
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"

# Each entry: (prefix, archive_prefix, index_key). index_key=None → no index page
# to rewrite for that prefix (the archive step still runs).
CHRONICLE_PREFIXES = [
    ("blog/", "blog/archive/pilot/", "blog/index.html"),
    ("dashboard/chronicle/posts/", "dashboard/chronicle/archive/pilot/posts/", "dashboard/chronicle/index.html"),
    ("site/chronicle/", "site/chronicle/archive/pilot/", "site/chronicle/index.html"),
    # v4 article pages (wednesday_chronicle_lambda writes generated/journal/posts/
    # week-NN/index.html, served at /journal/posts/week-NN/). Missed by the cycle-4
    # reset — old week pages kept rendering at their public URLs even though the
    # posts.json feed was tombstoned. No hub index lives under this prefix (the
    # chronicle hub is site/story/chronicle/), so index_key is None.
    ("generated/journal/posts/", "generated/journal/archive/pilot/posts/", None),
]

# ── Genesis lead-in chronicles (ADR-077, decided 2026-06-21) ──────────────────
# The hand-written ORIGIN chapters that depict Matthew's actual arc. They are kept
# across EVERY reset as re-dated pre-genesis lead-ins (genesis − N days), so the
# Chronicle door opens on the genuine origin story rather than a blank slate. The
# dormant-period auto-generated drafts are NOT kept — only this curated list.
#
# CRITICAL: each lead-in here MUST be DATE-AGNOSTIC in its prose — no specific
# calendar dates, holidays (e.g. Valentine's Day), or season-specific weather —
# because the reset re-dates them every cycle. (Week 1/2 were edited to this rule
# on 2026-06-21; re-dating chapters that still named February/March surfaced wrong
# timing references.) The reset auto-resurrects these unless --no-default-leadins.
ORIGIN_LEAD_INS = [
    "DATE#2026-02-22",  # "The Body Votes First" — Week 1 (20% recovery, the body's grammar, grief)
    "DATE#2026-03-03",  # "The Empty Journal" — Week 2 (27 programs, the blank page, the real arc)
]


def list_chronicle_html(s3, prefix: str, archive_prefix: str, index_key: str) -> list[str]:
    """List all *.html under prefix excluding archive subtree and the index page."""
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.startswith(archive_prefix):
                continue
            if key == index_key:
                continue
            if not key.endswith(".html"):
                continue
            out.append(key)
    return out


def s3_exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def archive_one(s3, src_key: str, prefix: str, archive_prefix: str, apply: bool, now_iso: str) -> tuple[str, bool]:
    """Archive one chronicle HTML file. Returns (archive_key, did_archive)."""
    base = src_key[len(prefix) :]
    dest_key = f"{archive_prefix}{base}"
    if s3_exists(s3, dest_key):
        return dest_key, False
    if apply:
        s3.copy_object(
            Bucket=S3_BUCKET,
            Key=dest_key,
            CopySource={"Bucket": S3_BUCKET, "Key": src_key},
            MetadataDirective="REPLACE",
            Metadata={"tombstoned_at": now_iso, "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}"},
        )
        # Tombstone-overwrite the original (IAM denies DeleteObject).
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=src_key,
            Body=json.dumps(
                {
                    "tombstone": True,
                    "tombstoned_at": now_iso,
                    "archived_to": dest_key,
                    "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}",
                }
            ).encode(),
            ContentType="application/json",
        )
    return dest_key, True


def _build_chronicle_placeholder() -> str:
    """Render a full-template chronicle index 'first installment publishes Wed'
    placeholder. Uses the same chrome (nav, footer, styles) as the rest of the
    site so it doesn't look like a different page.

    ADR-058 launch-eve fix (2026-05-24): replaces the previous standalone
    527-byte HTML that lacked site styling.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>.nav-overlay{display:none}</style>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="The Measured Life — a weekly chronicle by Elena Voss documenting Matthew's 12-month health experiment.">
  <meta property="og:title" content="The Measured Life — Chronicle">
  <meta property="og:description" content="A weekly narrative journalism chronicle by Elena Voss.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://averagejoematt.com/chronicle/">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="The Measured Life — Chronicle">
  <meta name="twitter:description" content="A weekly narrative chronicle by Elena Voss.">
  <meta name="twitter:image" content="https://averagejoematt.com/assets/images/og-image.png">
  <title>The Measured Life — Chronicle</title>
  <link rel="alternate" type="application/rss+xml" title="The Measured Life" href="/rss.xml">
  <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/icons/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/assets/icons/apple-touch-icon.png">
  <meta name="theme-color" content="#080c0a">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    .chronicle-header {
      padding: var(--space-20) var(--page-padding) var(--space-16);
      border-bottom: 1px solid var(--border);
      max-width: var(--content-width);
      margin: 0 auto;
    }
    .chronicle-header__kicker {
      font-size: var(--text-xs);
      letter-spacing: var(--ls-tag);
      text-transform: uppercase;
      color: var(--accent-dim);
      margin-bottom: var(--space-6);
    }
    .chronicle-header__title {
      font-family: var(--font-display);
      font-size: var(--text-h1);
      line-height: var(--lh-display);
      color: var(--text);
      letter-spacing: var(--ls-display);
      margin-bottom: var(--space-8);
    }
    .chronicle-header__sub {
      font-size: var(--text-lg);
      color: var(--text-muted);
      line-height: var(--lh-body);
      max-width: var(--prose-width);
    }
    .chronicle-empty {
      padding: var(--space-20) var(--page-padding);
      max-width: var(--prose-width);
      margin: 0 auto;
      text-align: center;
    }
    .chronicle-empty__note {
      font-family: var(--font-serif);
      font-size: var(--text-lg);
      color: var(--text-muted);
      line-height: var(--lh-body);
      font-style: italic;
    }
  </style>
  <link rel="canonical" href="https://averagejoematt.com/chronicle/">
</head>
<body class="body-story">

<div id="amj-nav"></div>
<div id="amj-hierarchy-nav"></div>

<header class="chronicle-header animate-in">
  <p class="chronicle-header__kicker">The Measured Life</p>
  <h1 class="chronicle-header__title">Chronicle</h1>
  <p class="chronicle-header__sub">
    A weekly narrative chronicle by Elena Voss — embedded with Matthew, documenting the experiment as it unfolds.
  </p>
</header>

<section class="chronicle-empty animate-in">
  <p class="chronicle-empty__note">
    The first installment publishes Wednesday of the experiment's first full week.
  </p>
</section>

<div id="amj-reading-path"></div>
<div id="amj-footer"></div>

<script src="/assets/js/site_constants.js"></script>
<script src="/assets/js/components.js"></script>
</body>
</html>
"""


def rewrite_index(s3, index_key: str, apply: bool):
    """Replace a chronicle index page with a full-template Day-1 placeholder."""
    placeholder = _build_chronicle_placeholder()
    if apply:
        s3.put_object(
            Bucket=S3_BUCKET, Key=index_key, Body=placeholder.encode(), ContentType="text/html", CacheControl="public, max-age=60"
        )
    return placeholder


def untombstone_and_redate(ddb_table, sk: str, new_date: str, apply: bool):
    """Untombstone a chronicle DDB record, re-date it, and force it VISIBLE.

    The record's content stays — only flags update. ADR-077 fix: the wipe stamped
    phase=pilot on every chronicle (mode "all"); removing the tombstone alone left
    phase=pilot, so the read filter (phase=pilot OR tombstone → hidden) still hid
    the "resurrected" article. We now also SET phase=experiment so a kept issue is
    genuinely visible as a pinned pre-genesis lead-in.
    """
    if apply:
        ddb_table.update_item(
            Key={"pk": "USER#matthew#SOURCE#chronicle", "sk": sk},
            UpdateExpression=(
                "REMOVE tombstone, tombstoned_at, tombstoned_reason, #h " "SET #d = :d, #p = :exp, redated_at = :ts, redated_from_sk = :osk"
            ),
            ExpressionAttributeNames={"#d": "date", "#p": "phase", "#h": "hidden"},
            ExpressionAttributeValues={
                ":d": new_date,
                ":exp": "experiment",
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":osk": sk,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument(
        "--resurrect-sk",
        action="append",
        default=[],
        help="Chronicle DDB sk to keep + re-date as a pre-genesis lead-in (repeatable, max 2)",
    )
    parser.add_argument("--keep-days", type=int, default=5, help="Days before genesis to date the first kept chronicle (default 5)")
    parser.add_argument(
        "--no-default-leadins",
        action="store_true",
        help="Do NOT auto-carry the curated ORIGIN_LEAD_INS chapters (default: carry them)",
    )
    args = parser.parse_args()

    # Default behaviour (ADR-077, 2026-06-21): carry the curated origin chapters as
    # re-dated pre-genesis lead-ins, so every reset opens on the genuine origin story.
    # Explicit --resurrect-sk overrides the default set; --no-default-leadins opts out.
    if not args.resurrect_sk and not args.no_default_leadins:
        args.resurrect_sk = list(ORIGIN_LEAD_INS)

    if len(args.resurrect_sk) > len(ORIGIN_LEAD_INS) + 2:
        print(f"ERROR: at most {len(ORIGIN_LEAD_INS) + 2} chronicles can be kept as lead-ins.")
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] chronicle handler. genesis={EXPERIMENT_START_DATE}")

    s3 = boto3.client("s3", region_name=REGION)
    ddb = boto3.resource("dynamodb", region_name=REGION).Table("life-platform")
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Archive all chronicle HTML across every chronicle prefix ──
    archived_count = 0
    skipped_count = 0
    total_html = 0
    print(f"\n[1/3] Archiving chronicle HTML across {len(CHRONICLE_PREFIXES)} prefix(es):")
    for prefix, archive_prefix, _ in CHRONICLE_PREFIXES:
        html_keys = list_chronicle_html(s3, prefix, archive_prefix, _)
        total_html += len(html_keys)
        if not html_keys:
            print(f"  [{prefix}] no files")
            continue
        print(f"  [{prefix}] {len(html_keys)} file(s):")
        for src in html_keys:
            dest, did = archive_one(s3, src, prefix, archive_prefix, args.apply, now_iso)
            if did:
                archived_count += 1
                print(f"    {('would archive' if not args.apply else 'archived')}: {src} → {dest}")
            else:
                skipped_count += 1

    # ── 2. Rewrite each index (prefixes with index_key=None have no hub page) ──
    print("\n[2/3] Rewriting chronicle index pages:")
    index_keys = [ik for _, _, ik in CHRONICLE_PREFIXES if ik]
    for index_key in index_keys:
        placeholder = rewrite_index(s3, index_key, args.apply)
        print(f"  ({'would write' if not args.apply else 'wrote'}) {index_key}  ({len(placeholder)} bytes, Day-1 placeholder)")

    # ── 3. Resurrect entries ──
    if args.resurrect_sk:
        # ADR-077 dec D: kept issues become pinned pre-genesis lead-ins, re-dated to
        # genesis − N days (default 5), staggered one day earlier per additional
        # keeper so multiple keepers preserve their original chronological order.
        genesis = date.fromisoformat(EXPERIMENT_START_DATE)
        new_dates = [(genesis - timedelta(days=args.keep_days + i)).isoformat() for i in range(len(args.resurrect_sk))]
        print(f"\n[3/3] Keeping {len(args.resurrect_sk)} chronicle(s) as pre-genesis lead-ins:")
        for sk, new_date in zip(args.resurrect_sk, new_dates):
            print(f"  {sk} → re-dated to {new_date} (phase=experiment, visible)")
            if args.apply:
                untombstone_and_redate(ddb, sk, new_date, args.apply)
    else:
        print("\n[3/3] No --resurrect-sk passed: blank chronicle, fresh start on next Wed cycle.")

    # Report
    report_path = REPO_ROOT / "docs" / "restart" / "_chronicle_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"chronicle handler report — mode={mode} — genesis={EXPERIMENT_START_DATE}\n"
        f"generated={now_iso}\n\n"
        f"html_files_total       = {total_html}\n"
        f"html_files_archived    = {archived_count}\n"
        f"html_files_already_archived = {skipped_count}\n"
        f"index_pages_rewritten  = {len(index_keys)}\n"
        f"chronicles_resurrected = {len(args.resurrect_sk)}\n"
    )
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
