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

Pre-launch content calendar (2026-07-11): after the sweep, PRELAUNCH_CALENDAR
"podcast" entries (defined in restart_chronicle_handler.py — the single source
for the whole pre-launch arc) are RESURRECTED — archive/pilot/<asset>.* copied
back over the tombstoned live keys and episodes.json/feed.xml rewritten with
the prequel episode dated genesis − days_before. An entry with skip_reason is
skipped (audio can't be edited, so a vet-failing episode stays archived).

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
sys.path.insert(0, str(REPO_ROOT / "deploy"))

from restart_chronicle_handler import resolve_calendar  # noqa: E402 — the pre-launch calendar (single source)

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
  <link>{SITE}/cockpit/</link>
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


# ── Podcast prequel resurrection (pre-launch content calendar, 2026-07-11) ────
# PRELAUNCH_CALENDAR "podcast" entries survive every reset: after the archive
# sweep above tombstones the live media, this phase copies the archived
# archive/pilot/<asset>.* objects BACK over the tombstoned live keys
# (copy-over-tombstone — we NEVER delete) and writes episodes.json + feed.xml
# carrying the prequel episode dated genesis − days_before. Entries carrying a
# "skip_reason" are reported and skipped — the escape hatch for content that
# fails vetting (audio can't be edited, so a violating episode stays archived).
# The next real weekly publish (coach_panel_podcast_lambda._write_indexes)
# rewrites both indexes and simply keeps the prequel entry alongside wk1+.

PANEL_PREFIX = "generated/panelcast/"
PANEL_ARCHIVE_PREFIX = "generated/panelcast/archive/pilot/"
GEMINI_SAMPLE_RATE = 24000  # lambdas/gemini_tts.SAMPLE_RATE — wkN.wav is 16-bit mono PCM
MP3_EST_KBPS = 80  # lambdas/audio_encode.DEFAULT_KBPS (#1018) — duration estimate for an mp3-only archive
COVER_URL = f"{SITE}/panelcast/cover.jpg"  # series art survives resets (KEEP_BASENAMES)

_RESTORE_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _xml_esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 16:00:00 GMT")


def _hms(seconds) -> str:
    s = max(0, int(seconds or 0))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def build_prequel_episode(entry: dict, wav_bytes: int = None, mp3_bytes: int = None) -> dict:
    """The episodes.json entry for a resurrected prequel. Schema matches the wk0
    intro publisher in lambdas/emails/coach_panel_podcast_lambda.py EXACTLY
    (week/title/date/url/bytes/duration_sec/byline/excerpt/transcript_url) so the
    Panel page + next weekly publish treat it as a first-class episode.

    Since #1018 episodes publish compressed (.mp3, ~80 kbps mono; .wav only as
    the fail-open fallback), so the archive can hold either or both. Serve the
    .mp3 whenever it exists — never re-point readers at a 16 MB WAV. Duration
    comes from the WAV when archived alongside (exact: 16-bit mono PCM), else
    it's a bitrate estimate at MP3_EST_KBPS."""
    asset = entry["asset"]
    week = int(entry.get("week", 0))
    if mp3_bytes:
        url, nbytes = f"/panelcast/{asset}.mp3", int(mp3_bytes)
    else:
        url, nbytes = f"/panelcast/{asset}.wav", int(wav_bytes)
    duration = (
        max(1, (int(wav_bytes) - 44) // (GEMINI_SAMPLE_RATE * 2))  # WAV: 16-bit mono PCM
        if wav_bytes
        else max(1, int(mp3_bytes) * 8 // (MP3_EST_KBPS * 1000))
    )
    return {
        "week": week,
        "title": entry.get("title") or f"EP{week}",
        "date": entry["date"],
        "url": url,
        "bytes": nbytes,
        "duration_sec": duration,
        "byline": entry.get("byline", "Elena + Dr. Eli Marsh"),
        "excerpt": entry.get(
            "excerpt",
            "Meet Elena, meet Matt, and meet the question this whole experiment is built to answer: "
            "can AI and your own data actually make a life better — or is it just over-optimization? The starting line.",
        ),
        "transcript_url": f"/panelcast/{asset}.transcript.json",
    }


def _panel_feed_with_items(episodes: list[dict]) -> str:
    """feed.xml with episode items — item schema mirrors coach_panel_podcast_lambda.
    _write_indexes (guid measured-life-panel-wk{N}, RFC822 pubDate, itunes fields);
    the next real weekly publish overwrites this with its own full render."""
    items = "\n".join(
        f"""  <item>
    <title>{_xml_esc(e["title"])}</title>
    <description>{_xml_esc(e.get("excerpt") or e["title"])}</description>
    <itunes:summary>{_xml_esc(e.get("excerpt") or e["title"])}</itunes:summary>
    <enclosure url="{SITE}{e["url"]}" length="{e.get("bytes", 0)}" type="{'audio/mpeg' if e["url"].endswith('.mp3') else 'audio/wav'}"/>
    <guid isPermaLink="false">measured-life-panel-wk{e["week"]}</guid>
    <pubDate>{_rfc822(e["date"])}</pubDate>
    <itunes:duration>{_hms(e.get("duration_sec"))}</itunes:duration>
    <itunes:episode>{int(e["week"])}</itunes:episode>
    <itunes:episodeType>full</itunes:episodeType>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{COVER_URL}"/>
  </item>"""
        for e in episodes
    )
    empty = _empty_panel_feed()
    return empty.replace("</channel>", f"{items}\n</channel>") if items else empty


def _list_archive_assets(s3, asset: str) -> list[str]:
    """All archived generated/panelcast/archive/pilot/<asset>.* keys."""
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"{PANEL_ARCHIVE_PREFIX}{asset}."):
        out.extend(obj["Key"] for obj in page.get("Contents", []))
    return out


def resurrect_podcast_prequels(s3, apply: bool, now_iso: str, manual: list[str]) -> list[str]:
    """Restore PRELAUNCH_CALENDAR podcast entries after the archive sweep.

    For each non-skipped podcast entry: copy archive/pilot/<asset>.* back over the
    tombstoned live keys, then write episodes.json ({"episodes": [...]}, the exact
    lambda schema) + feed.xml with the prequel dated genesis − days_before.
    Returns human-readable status lines (also fed to the report).
    """
    lines: list[str] = []
    entries = [e for e in resolve_calendar(EXPERIMENT_START_DATE) if e.get("kind") == "podcast"]
    if not entries:
        return ["(no podcast entries on the pre-launch calendar)"]
    episodes: list[dict] = []
    for e in entries:
        desc = e.get("title") or e.get("asset", "?")
        if e.get("skip_reason"):
            lines.append(f"SKIP {e.get('asset', '?')} \"{desc}\" — {e['skip_reason']}")
            continue
        asset = e["asset"]
        archived = _list_archive_assets(s3, asset)
        if not archived:
            lines.append(f"WARN {asset}: nothing under {PANEL_ARCHIVE_PREFIX}{asset}.* — cannot resurrect")
            continue
        wav_bytes = None
        mp3_bytes = None
        for src in archived:
            basename = src[len(PANEL_ARCHIVE_PREFIX) :]
            live_key = f"{PANEL_PREFIX}{basename}"
            head = s3.head_object(Bucket=S3_BUCKET, Key=src)
            if basename == f"{asset}.wav":
                wav_bytes = head["ContentLength"]
            elif basename == f"{asset}.mp3":
                mp3_bytes = head["ContentLength"]
            if not apply:
                lines.append(f"would-restore: {src} → {live_key} ({head['ContentLength']} bytes)")
                continue
            try:
                if s3_exists(s3, live_key) and not already_tombstoned(s3, live_key):
                    lines.append(f"already-restored: {live_key}")
                    continue
                ext = "." + basename.rsplit(".", 1)[-1]
                s3.copy_object(
                    Bucket=S3_BUCKET,
                    Key=live_key,
                    CopySource={"Bucket": S3_BUCKET, "Key": src},
                    MetadataDirective="REPLACE",
                    ContentType=_RESTORE_CONTENT_TYPES.get(ext, "application/octet-stream"),
                    CacheControl="max-age=86400, public" if ext in (".mp3", ".wav") else "max-age=300, public",
                    Metadata={"resurrected_at": now_iso, "resurrected_reason": f"prelaunch_calendar_{EXPERIMENT_START_DATE}"},
                )
                lines.append(f"restored: {src} → {live_key}")
            except ClientError as ce:
                if _is_access_denied(ce):
                    manual.append(f"aws s3 cp s3://{S3_BUCKET}/{src} s3://{S3_BUCKET}/{live_key}  # prequel restore was denied")
                    lines.append(f"MANUAL (access denied): {live_key}")
                else:
                    raise
        if wav_bytes is None and mp3_bytes is None:
            lines.append(f"WARN {asset}: no {asset}.mp3/.wav in the archive — episode entry NOT written")
            continue
        ep = build_prequel_episode(e, wav_bytes=wav_bytes, mp3_bytes=mp3_bytes)
        episodes.append(ep)
        lines.append(f"episode: wk{ep['week']} \"{ep['title']}\" dated {ep['date']} ({ep['duration_sec']}s, {ep['bytes']} bytes)")

    if episodes:
        episodes.sort(key=lambda x: x.get("week", 0), reverse=True)
        index_body = json.dumps({"episodes": episodes}, indent=1)
        feed_body = _panel_feed_with_items(episodes)
        for key, body, ctype in (
            (f"{PANEL_PREFIX}episodes.json", index_body, "application/json"),
            (f"{PANEL_PREFIX}feed.xml", feed_body, "application/rss+xml; charset=utf-8"),
        ):
            if not apply:
                lines.append(f"would-write: {key} ({len(episodes)} episode(s))")
                continue
            try:
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body.encode(), ContentType=ctype, CacheControl="max-age=300, public")
                lines.append(f"wrote: {key} ({len(episodes)} episode(s))")
            except ClientError as ce:
                if _is_access_denied(ce):
                    manual.append(f"# rewrite s3://{S3_BUCKET}/{key} with the prequel episode by hand (PutObject was denied)")
                    lines.append(f"MANUAL (access denied): {key}")
                else:
                    raise
    return lines


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

    # Pre-launch calendar: resurrect the podcast prequel(s) AFTER the sweep, so the
    # end state of one full run is archive-everything + prequels restored + indexes
    # carrying exactly the calendar episodes. Re-runs are idempotent (the sweep
    # re-tombstones, this phase re-restores — the archive copy never changes).
    print("\n[prequel resurrection] pre-launch calendar podcast entries:")
    report_lines.append("\nPREQUEL RESURRECTION:")
    for line in resurrect_podcast_prequels(s3, args.apply, now_iso, manual):
        print(f"    {line}")
        report_lines.append(f"  {line}")

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
