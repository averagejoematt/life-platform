"""
chronicle_podcast_lambda.py — Elena's chronicle as an auto-published podcast (2026-06-13).

Every published chronicle installment becomes an audio episode: the DDB
record's content_markdown is stripped to narration text, synthesized with
Google Cloud Text-to-Speech (Chirp 3: HD — Elena's persistent voice from the
persona registry; far more natural than the old Polly neural), and written to
s3://{bucket}/generated/podcast/ep-{date}.mp3. The run then rebuilds
generated/podcast/episodes.json (consumed by the story page's per-article
"listen" join — site/assets/js/read_aloud.js) and generated/podcast/feed.xml
(a podcast RSS with enclosures).

Reset-safe keying (#1121, the ADR-077 key-invalidation class): episodes are
keyed by the article's publication DATE, never by week number. Week numbers
repeat across experiment resets, and the old wk{N}.mp3 keys let a new cycle's
Week N find the PRIOR cycle's MP3 already present, skip the render, and index
last cycle's voice under the new article. Dates are globally unique across
cycles, so a stale object can never be mistaken for a new article's audio.

Served publicly at /podcast/* via the S3GeneratedOrigin CloudFront behavior.

Idempotent: articles that already have an MP3 (by date key) are skipped
(event {"force": true} re-renders everything — use this once after a voice
swap to re-render the back catalogue). Scheduled Wed 15:40 UTC — after the
chronicle publishes (15:00) and the email sends (15:10).

Cost: Chirp 3: HD ≈ $30/1M chars with 1M chars/month free → effectively $0.
"""

import json
import os
import re
from datetime import datetime, timezone

import boto3
import google_tts
import persona_registry

try:
    from platform_logger import get_logger

    logger = get_logger("chronicle-podcast")
except ImportError:
    import logging

    logger = logging.getLogger("chronicle-podcast")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SITE = "https://averagejoematt.com"
PREFIX = "generated/podcast"
# Fallback voice if the persona registry can't be read (Elena's assigned voice).
ELENA_VOICE_FALLBACK = "en-US-Chirp3-HD-Aoede"

s3 = boto3.client("s3", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def _elena_voice() -> str:
    return persona_registry.tts_voice("elena_voss", s3, S3_BUCKET) or ELENA_VOICE_FALLBACK


def _markdown_to_narration(md: str) -> str:
    """Strip chronicle markdown down to clean spoken prose."""
    t = md
    t = re.sub(r"^\[Weight:.*?\]\s*$", "", t, flags=re.M)  # stats header line
    t = re.sub(r"^---\s*$", "", t, flags=re.M)
    t = re.sub(r"^\*Week \d+ of The Measured Life\*\s*$", "", t, flags=re.M)
    t = re.sub(r"^>\s?", "", t, flags=re.M)  # blockquote (board interviews)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)  # links → text
    t = re.sub(r"[*_#`]", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _synthesize(text: str) -> bytes:
    """Google Chirp 3: HD MP3 in Elena's persistent voice (chunked + concatenated
    inside google_tts; same voice/bitrate, so MP3 frame concatenation is valid)."""
    return google_tts.synthesize(text, _elena_voice())


def _published_posts() -> list:
    """#1121: the CURRENT chronicle manifest (phase-filtered, current-cycle only) —
    the same feed the story page renders. site/chronicle/posts.json is the DEAD
    pre-v4 feed (season-1 posts, Feb–May dates); reading it kept this show frozen
    on the pre-reset back catalogue. Deliberately NO fallback to the dead feed:
    if the live manifest can't be read, fail loud (the handler 503s) rather than
    voice another cycle's articles."""
    obj = s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")
    return json.loads(obj["Body"].read()).get("posts", [])


def _episode_slug(date_str: str) -> str:
    """Reset-safe per-article key (#1121): the article's publication date, the
    same globally-unique id the story reader routes by. Never the week number —
    weeks repeat across experiment resets (ADR-077), and a week key lets a new
    cycle's Week N inherit the prior cycle's MP3 via the idempotency check."""
    return f"ep-{date_str}"


def _content_for(date_str: str, title: str) -> str | None:
    """posts.json carries the ISSUE date; the DDB record is keyed by the
    GENERATION date — usually the same day, sometimes ±1-3 days. Search out,
    but verify identity by title (#1121): the date-window search alone once
    landed on a NEIGHBORING record (an unpublished pilot draft) and would have
    voiced it under this article's name. A near-date record that isn't THIS
    article is a miss, not a match — skip honestly (no episode) instead."""
    from datetime import timedelta as _td

    base = datetime.strptime(date_str, "%Y-%m-%d")
    for off in (0, 1, -1, 2, -2, 3, -3):
        d = (base + _td(days=off)).strftime("%Y-%m-%d")
        r = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"DATE#{d}"})
        item = r.get("Item") or {}
        md = item.get("content_markdown")
        if not md:
            continue
        rec_title = str(item.get("title") or "").strip().lower()
        if rec_title and title and rec_title != title.strip().lower():
            continue  # a different article that happens to sit nearby — keep looking
        return md
    return None


def _episode_exists(slug: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/{slug}.mp3")
        return True
    except Exception:
        return False


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 15:00:00 GMT")


def _write_indexes(episodes: list) -> None:
    """episodes: [{week, title, date, url, bytes, excerpt}] newest-first.
    `date` is the join key the front-end matches articles on (#1121); `week`
    is informational only — it repeats across resets and must never key."""
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX}/episodes.json",
        Body=json.dumps({"episodes": episodes}, indent=1),
        ContentType="application/json",
        CacheControl="max-age=3600, public",
    )
    items = "\n".join(
        f"""  <item>
    <title>{_xml(e["title"])}</title>
    <description>{_xml(e.get("excerpt") or e["title"])}</description>
    <enclosure url="{SITE}{e["url"]}" length="{e["bytes"]}" type="audio/mpeg"/>
    <guid isPermaLink="false">measured-life-{e["date"]}</guid>
    <pubDate>{_rfc822(e["date"])}</pubDate>
  </item>"""
        for e in episodes
    )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>The Measured Life — the chronicle, read aloud</title>
  <link>{SITE}/story/chronicle/</link>
  <description>An AI-written, AI-voiced weekly documentary of one ordinary life rebuilt with AI. Written by Elena Voss (a model), narrated by a synthetic voice, fact-anchored to real data.</description>
  <language>en-us</language>
  <itunes:author>averagejoematt</itunes:author>
  <itunes:explicit>false</itunes:explicit>
{items}
</channel>
</rss>
"""
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX}/feed.xml",
        Body=feed,
        ContentType="application/rss+xml; charset=utf-8",
        CacheControl="max-age=3600, public",
    )


def _xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lambda_handler(event, context):
    event = event or {}
    force = bool(event.get("force"))
    episodes, rendered, errors = [], 0, 0

    try:
        posts = _published_posts()
    except Exception as e:
        logger.error(f"podcast: could not load posts.json — {e}")
        return {"statusCode": 503, "body": json.dumps({"error": "posts.json unavailable"})}

    # Sort by DATE, newest first — the per-article identity (#1121). The old
    # week-number sort collides when week labels repeat (two curated prologues
    # both carry week 0; weeks also restart every cycle).
    for p in sorted(posts, key=lambda x: x.get("date") or "", reverse=True):
        date_str, title = p.get("date"), str(p.get("title") or "")
        if not date_str:
            continue
        slug = _episode_slug(date_str)
        # Per-episode isolation: one TTS/S3 failure must not abort the others
        # or skip the index rebuild (this runs weekly, unattended).
        try:
            key = f"{PREFIX}/{slug}.mp3"
            if force or not _episode_exists(slug):
                md = _content_for(date_str, title)
                if not md:
                    # Honest-empty: no verified content for THIS article → no episode.
                    logger.warning(f"{slug}: no content_markdown matching '{title}' near {date_str} — skipped")
                    continue
                # No week number in the permanent audio (weeks repeat across cycles);
                # the article's own title is its identity.
                narration = (
                    f"The Measured Life: {title}. "
                    f"Written by Elena Voss — a language model embedded with the experiment — "
                    f"and read by a synthetic voice.\n\n" + _markdown_to_narration(md)
                )
                audio = _synthesize(narration)
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=audio, ContentType="audio/mpeg", CacheControl="max-age=86400, public")
                rendered += 1
                logger.info(f"{slug}: rendered {len(audio)} bytes ({len(narration)} chars)")
            size = s3.head_object(Bucket=S3_BUCKET, Key=key)["ContentLength"]
            episodes.append(
                {
                    "week": p.get("week"),  # informational only — never a join key
                    "title": title or date_str,
                    "date": date_str,
                    "url": f"/podcast/{slug}.mp3",
                    "bytes": size,
                    "excerpt": p.get("excerpt", ""),
                }
            )
        except Exception as e:
            errors += 1
            logger.error(f"{slug}: episode failed (non-fatal) — {e}")

    try:
        _write_indexes(episodes)
    except Exception as e:
        logger.error(f"podcast: index rebuild failed — {e}")
        return {"statusCode": 500, "body": json.dumps({"rendered": rendered, "errors": errors, "index": "failed"})}

    logger.info(f"podcast: {rendered} rendered, {len(episodes)} indexed, {errors} errors")
    return {"statusCode": 200, "body": json.dumps({"rendered": rendered, "episodes": len(episodes), "errors": errors})}
