"""
chronicle_podcast_lambda.py — Elena's chronicle as an auto-published podcast (2026-06-13).

Every published chronicle installment becomes an audio episode: the DDB
record's content_markdown is stripped to narration text, synthesized with
Amazon Polly (neural, chunked at sentence boundaries under the per-request
char limit, MP3 frames concatenated), and written to
s3://{bucket}/generated/podcast/wk{N}.mp3. The run then rebuilds
generated/podcast/episodes.json (consumed by the story page player) and
generated/podcast/feed.xml (a podcast RSS with enclosures).

Served publicly at /podcast/* via the S3GeneratedOrigin CloudFront behavior.

Idempotent: weeks that already have an MP3 are skipped (event {"force": true}
re-renders everything). Scheduled Wed 15:40 UTC — after the chronicle
publishes (15:00) and the email sends (15:10).

Cost: Polly neural ≈ $16/1M chars → a 9k-char installment ≈ $0.15. Not
Bedrock, so outside the AI budget tiers — but cheap enough not to matter.
"""

import json
import os
import re
from datetime import datetime, timezone

import boto3

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
VOICE_ID = os.environ.get("PODCAST_VOICE_ID", "Ruth")
SITE = "https://averagejoematt.com"
PREFIX = "generated/podcast"
CHUNK_CHARS = 2700  # Polly synthesize_speech limit is 3000 billed chars

s3 = boto3.client("s3", region_name=REGION)
polly = boto3.client("polly", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


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


def _chunks(text: str):
    """Split at sentence boundaries, each under CHUNK_CHARS."""
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(sent) + 1 > CHUNK_CHARS and cur:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _synthesize(text: str) -> bytes:
    """Polly neural MP3 — chunked and concatenated (same voice/bitrate, so
    raw MP3 frame concatenation is valid)."""
    audio = b""
    for chunk in _chunks(text):
        resp = polly.synthesize_speech(Engine="neural", OutputFormat="mp3", VoiceId=VOICE_ID, Text=chunk)
        audio += resp["AudioStream"].read()
    return audio


def _published_posts() -> list:
    obj = s3.get_object(Bucket=S3_BUCKET, Key="site/chronicle/posts.json")
    return json.loads(obj["Body"].read()).get("posts", [])


def _content_for(date_str: str) -> str | None:
    """posts.json carries the ISSUE date; the DDB record is keyed by the
    GENERATION date — usually the same day, sometimes ±1-3 days. Search out."""
    from datetime import timedelta as _td

    base = datetime.strptime(date_str, "%Y-%m-%d")
    for off in (0, 1, -1, 2, -2, 3, -3):
        d = (base + _td(days=off)).strftime("%Y-%m-%d")
        r = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"DATE#{d}"})
        md = (r.get("Item") or {}).get("content_markdown")
        if md:
            return md
    return None


def _episode_exists(week) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.mp3")
        return True
    except Exception:
        return False


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 15:00:00 GMT")


def _write_indexes(episodes: list) -> None:
    """episodes: [{week, title, date, url, bytes, excerpt}] newest-first."""
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
    <guid isPermaLink="false">measured-life-wk{e["week"]}</guid>
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

    for p in sorted(posts, key=lambda x: x.get("week", 0), reverse=True):
        week, date_str, title = p.get("week"), p.get("date"), p.get("title", f"Week {p.get('week')}")
        if week is None or not date_str:
            continue
        # Per-episode isolation: one Polly/S3 failure must not abort the others
        # or skip the index rebuild (this runs weekly, unattended).
        try:
            key = f"{PREFIX}/wk{week}.mp3"
            if force or not _episode_exists(week):
                md = _content_for(date_str)
                if not md:
                    logger.warning(f"wk{week}: no content_markdown for {date_str} — skipped")
                    continue
                narration = (
                    f"The Measured Life, issue {week}: {title}. "
                    f"Written by Elena Voss — a language model embedded with the experiment — "
                    f"and read by a synthetic voice.\n\n" + _markdown_to_narration(md)
                )
                audio = _synthesize(narration)
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=audio, ContentType="audio/mpeg", CacheControl="max-age=86400, public")
                rendered += 1
                logger.info(f"wk{week}: rendered {len(audio)} bytes ({len(narration)} chars)")
            size = s3.head_object(Bucket=S3_BUCKET, Key=key)["ContentLength"]
            episodes.append(
                {"week": week, "title": title, "date": date_str, "url": f"/podcast/wk{week}.mp3", "bytes": size, "excerpt": p.get("excerpt", "")}
            )
        except Exception as e:
            errors += 1
            logger.error(f"wk{week}: episode failed (non-fatal) — {e}")

    try:
        _write_indexes(episodes)
    except Exception as e:
        logger.error(f"podcast: index rebuild failed — {e}")
        return {"statusCode": 500, "body": json.dumps({"rendered": rendered, "errors": errors, "index": "failed"})}

    logger.info(f"podcast: {rendered} rendered, {len(episodes)} indexed, {errors} errors")
    return {"statusCode": 200, "body": json.dumps({"rendered": rendered, "episodes": len(episodes), "errors": errors})}
