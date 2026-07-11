#!/usr/bin/env python3
"""
restart_media_reset.py — clean-sweep reset for the generated audio surfaces.

The 2026-07-10 audit found the reset pipeline never touched the podcast media:
after a reset, /panelcast/episodes.json + feed.xml + the wkN mp3s/transcripts
and /podcast/debrief/* kept serving the whole prior cycle. This script archives
and blanks them, mirroring restart_chronicle_handler's copy-then-tombstone
pattern (S3 safety, ADR-032/033/046: DeleteObject on generated/* is blocked for
matthew-admin, and `aws s3 sync --delete` is banned — so we NEVER delete; we
copy each object to an archive/pilot/ key, tombstone-overwrite the original,
and rewrite the two feed indexes to honest empty structures).

If the bucket policy blocks a needed PutObject/CopyObject, the failure is
collected and printed as a MANUAL RUNBOOK step at the end instead of failing
the pipeline (exit stays 0 for access-denied; any other error exits 1).

Wired into restart_pipeline.py between restart_chronicle_handler and
restart_site_copy_sync. Dry-run default; idempotent (archive copies are
skipped when the destination exists; already-tombstoned originals are skipped).

Usage:
    python3 deploy/restart_media_reset.py            # dry-run
    python3 deploy/restart_media_reset.py --apply    # commit
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CLOUDFRONT_DIST = "E3S424OXQZ8NBE"
SITE = "https://averagejoematt.com"

TOMBSTONE_REASON = f"experiment_restart_{EXPERIMENT_START_DATE}"

# Each surface: (prefix, archive_prefix, index_basenames, empty_feed_builder).
# index_basenames are rewritten to empty structures (NOT archived-then-
# tombstoned like the media objects — the front-end keeps reading them).


def _empty_panel_feed() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>The Measured Life — The Panel</title>
  <atom:link href="{SITE}/panelcast/feed.xml" rel="self" type="application/rss+xml"/>
  <link>{SITE}/story/panel/</link>
  <description>A weekly two-host show reviewing the week's data from a public N=1 health experiment. AI voices, correlative, fact-anchored. A new season starts with the current experiment cycle.</description>
  <language>en-us</language>
  <itunes:author>The Measured Life</itunes:author>
  <itunes:explicit>false</itunes:explicit>
</channel>
</rss>
"""


def _empty_debrief_feed() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>The Measured Life — the daily debrief</title>
  <link>{SITE}/now/</link>
  <description>A roughly two-minute, AI-voiced state-of-Matthew briefing every day. A new season starts with the current experiment cycle.</description>
  <language>en-us</language>
  <itunes:author>averagejoematt</itunes:author>
  <itunes:explicit>false</itunes:explicit>
</channel>
</rss>
"""


SURFACES = [
    ("generated/panelcast/", "generated/panelcast/archive/pilot/", _empty_panel_feed),
    ("generated/podcast/debrief/", "generated/podcast/debrief/archive/pilot/", _empty_debrief_feed),
]

INDEX_BASENAMES = {"episodes.json", "feed.xml"}

# Series-level branding that survives every reset (referenced by the show page +
# future episodes' <itunes:image>) — never episode content.
KEEP_BASENAMES = {"cover.jpg", "cover.png", "cover.webp"}


def _is_access_denied(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in ("AccessDenied", "AccessDeniedException", "403")


def list_objects(s3, prefix: str, archive_prefix: str) -> list[str]:
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.startswith(archive_prefix):
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


def already_tombstoned(s3, key: str) -> bool:
    """True if the ORIGINAL object is already our tombstone JSON (idempotent re-runs)."""
    try:
        head = s3.head_object(Bucket=S3_BUCKET, Key=key)
        if head.get("ContentLength", 0) > 4096:
            return False
        body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read(4096)
        doc = json.loads(body)
        return bool(doc.get("tombstone"))
    except Exception:
        return False


def archive_and_tombstone(s3, key: str, prefix: str, archive_prefix: str, apply: bool, now_iso: str, manual: list[str]) -> str:
    """Copy key → archive, tombstone-overwrite original. Returns a status word."""
    dest = archive_prefix + key[len(prefix) :]
    if already_tombstoned(s3, key):
        return "already-tombstoned"
    if not apply:
        return "would-archive"
    try:
        if not s3_exists(s3, dest):
            s3.copy_object(
                Bucket=S3_BUCKET,
                Key=dest,
                CopySource={"Bucket": S3_BUCKET, "Key": key},
                MetadataDirective="REPLACE",
                Metadata={"tombstoned_at": now_iso, "tombstoned_reason": TOMBSTONE_REASON},
            )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(
                {
                    "tombstone": True,
                    "tombstoned_at": now_iso,
                    "archived_to": dest,
                    "tombstoned_reason": TOMBSTONE_REASON,
                }
            ).encode(),
            ContentType="application/json",
        )
        return "archived"
    except ClientError as e:
        if _is_access_denied(e):
            manual.append(f"aws s3 cp s3://{S3_BUCKET}/{key} s3://{S3_BUCKET}/{dest}  # then tombstone-overwrite the original")
            return "MANUAL (access denied)"
        raise


def rewrite_indexes(s3, prefix: str, feed_builder, apply: bool, now_iso: str, manual: list[str]) -> list[tuple[str, str]]:
    """Rewrite episodes.json → empty list + feed.xml → empty channel."""
    results = []
    empty_index = json.dumps(
        {
            "episodes": [],
            "reset_at": now_iso,
            "reset_reason": TOMBSTONE_REASON,
            "note": "Prior-cycle episodes are archived under archive/pilot/; a new season starts with the current cycle.",
        },
        indent=1,
    )
    for basename, body, ctype in (
        ("episodes.json", empty_index, "application/json"),
        ("feed.xml", feed_builder(), "application/rss+xml; charset=utf-8"),
    ):
        key = f"{prefix}{basename}"
        if not apply:
            results.append((key, "would-rewrite"))
            continue
        try:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=body.encode(),
                ContentType=ctype,
                CacheControl="max-age=300, public",
            )
            results.append((key, "rewritten"))
        except ClientError as e:
            if _is_access_denied(e):
                manual.append(f"# rewrite s3://{S3_BUCKET}/{key} to an empty {basename} by hand (PutObject was denied)")
                results.append((key, "MANUAL (access denied)"))
            else:
                raise
    return results


def invalidate(apply: bool) -> list[str]:
    """generated/ is stripped at the CloudFront edge — invalidate VIEWER paths
    (the CloudFront-path bug, 2026-06-18), not S3 keys."""
    paths = ["/panelcast/*", "/podcast/debrief/*"]
    if apply:
        cf = boto3.client("cloudfront")
        cf.create_invalidation(
            DistributionId=CLOUDFRONT_DIST,
            InvalidationBatch={
                "Paths": {"Quantity": len(paths), "Items": paths},
                "CallerReference": f"media-reset-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            },
        )
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument("--skip-cloudfront", action="store_true", help="Skip CloudFront invalidation step")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] media reset. genesis={EXPERIMENT_START_DATE} reason={TOMBSTONE_REASON}")

    s3 = boto3.client("s3", region_name=REGION)
    now_iso = datetime.now(timezone.utc).isoformat()
    manual: list[str] = []
    report_lines = [f"media reset report — mode={mode} — genesis={EXPERIMENT_START_DATE}", f"generated={now_iso}", ""]

    archived = 0
    skipped = 0
    for prefix, archive_prefix, feed_builder in SURFACES:
        keys = list_objects(s3, prefix, archive_prefix)
        # Everything except the prefix's own episodes.json / feed.xml (rewritten in
        # place below) and the series cover art (kept) is media — mp3s, wavs,
        # transcripts, per-episode pages — and gets archived-then-tombstoned.
        media_keys = [k for k in keys if k[len(prefix) :] not in INDEX_BASENAMES | KEEP_BASENAMES]
        print(f"\n[{prefix}] {len(keys)} object(s) ({len(media_keys)} media to archive):")
        for key in media_keys:
            status = archive_and_tombstone(s3, key, prefix, archive_prefix, args.apply, now_iso, manual)
            if status in ("archived", "would-archive"):
                archived += 1
            else:
                skipped += 1
            print(f"    {status}: {key}")
            report_lines.append(f"{status}: {key}")
        for key, status in rewrite_indexes(s3, prefix, feed_builder, args.apply, now_iso, manual):
            print(f"    {status}: {key}")
            report_lines.append(f"{status}: {key}")

    if not args.skip_cloudfront:
        paths = invalidate(args.apply)
        print(f"\nCloudFront invalidation: {paths}{' (would invalidate)' if not args.apply else ''}")

    if manual:
        print("\n══ MANUAL RUNBOOK STEPS (bucket policy denied these ops — run as a principal that can) ══")
        for m in manual:
            print(f"  {m}")
        report_lines.append("\nMANUAL STEPS:")
        report_lines.extend(f"  {m}" for m in manual)

    report_path = REPO_ROOT / "docs" / "restart" / "_media_reset_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_lines.append(f"\narchived={archived} skipped={skipped} manual={len(manual)}")
    report_path.write_text("\n".join(report_lines))
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
