#!/usr/bin/env python3
"""republish_panelcast_wk0_compressed.py — one-off driver step for #1018.

The live /panelcast/wk0.wav is 16.6 MB of uncompressed WAV for a 5:46 episode,
served to cellular readers. This script republishes the locally-encoded MP3
(lambdas/audio_encode.py at 80 kbps mono → ~3.5 MB) without re-synthesizing:

  1. uploads <--file> → generated/panelcast/wk0.mp3 (live) AND
     generated/panelcast/archive/pilot/wk0.mp3 — the archive copy matters:
     restart_media_reset.py resurrects the wk0 prequel from archive/pilot/ on
     every experiment reset, and (since #1018) prefers the .mp3 when present;
     without it the next reset would regress readers to the 16.6 MB WAV.
  2. re-points the wk0 entry in episodes.json (url + bytes only — title, date,
     duration_sec, transcript_url and the rest are preserved).
  3. regenerates feed.xml + episodes.json through the production renderer
     (coach_panel_podcast_lambda._write_indexes), which also invalidates the
     CloudFront VIEWER path /panelcast/* (never the S3 key path).

wk0.wav is intentionally left in place (generated/* is delete-protected, and
anything still holding the old URL — a cached page, a podcast app that pulled
the old feed — keeps playing until it refreshes). Safe order: this script only
flips references AFTER the .mp3 is durable in S3.

Usage:
    python3 scripts/republish_panelcast_wk0_compressed.py --file wk0.mp3            # dry-run
    python3 scripts/republish_panelcast_wk0_compressed.py --file wk0.mp3 --apply    # commit
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

BUCKET = "matthew-life-platform"
PREFIX = "generated/panelcast"
ARCHIVE_PREFIX = f"{PREFIX}/archive/pilot"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, help="path to the locally-encoded wk0.mp3")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry-run)")
    args = ap.parse_args()

    body = Path(args.file).read_bytes()
    # MP3 sanity: ID3 tag or an MPEG frame sync — refuse to publish a mislabeled WAV.
    if not (body[:3] == b"ID3" or (len(body) > 1 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0)):
        print(f"ERROR: {args.file} does not look like MP3 (no ID3 tag / frame sync)")
        return 1

    from emails import coach_panel_podcast_lambda as panel  # noqa: E402 — the production renderer

    s3 = panel.s3
    doc = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read())
    episodes = doc.get("episodes", [])
    pending = doc.get("pending")  # _write_indexes drops the marker; preserve it (it's forward-looking, not wk0's)
    wk0 = next((e for e in episodes if e.get("week") == 0), None)
    if not wk0:
        print("ERROR: no wk0 entry in episodes.json — nothing to re-point")
        return 1

    print(f"wk0 today : {wk0['url']} ({wk0.get('bytes', '?')} bytes, {wk0.get('duration_sec', '?')}s)")
    print(f"wk0 after : /panelcast/wk0.mp3 ({len(body)} bytes, duration preserved)")
    if not args.apply:
        print("(dry-run — nothing written; pass --apply to commit)")
        return 0

    for key in (f"{PREFIX}/wk0.mp3", f"{ARCHIVE_PREFIX}/wk0.mp3"):
        s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="audio/mpeg", CacheControl="max-age=86400, public")
        print(f"uploaded s3://{BUCKET}/{key}")

    wk0["url"] = "/panelcast/wk0.mp3"
    wk0["bytes"] = len(body)
    panel._write_indexes(episodes)  # episodes.json + feed.xml + /panelcast/* viewer-path invalidation
    print("indexes rewritten via coach_panel_podcast_lambda._write_indexes (+ CDN invalidation)")
    if pending:
        doc2 = {"episodes": episodes, "pending": pending}
        s3.put_object(
            Bucket=BUCKET,
            Key=f"{PREFIX}/episodes.json",
            Body=json.dumps(doc2, indent=1),
            ContentType="application/json",
            CacheControl="max-age=3600, public",
        )
        print("pending marker preserved on episodes.json")
    print("done — verify: curl -sI https://averagejoematt.com/panelcast/wk0.mp3 | head -5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
