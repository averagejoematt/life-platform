"""coach_panel_podcast_lambda.py — "The Panel": a weekly two-host show (2026-06-14).

Each week Elena Voss hosts and a rotating coach co-reviews the week — the
chronicle plus that coach's recent reads. Bedrock (Haiku) writes a short
conversational script as a list of {speaker, line}; every line passes the ER-03
gate (correlative, no fabricated numbers, no Matthew-prefix) before it's voiced;
each line is synthesized in that persona's persistent Chirp 3: HD voice
(persona_registry.tts_voice) and the turns are concatenated into one MP3.

Outputs generated/panelcast/{wk<N>.mp3, episodes.json, feed.xml} → served at
/panelcast/* via the S3GeneratedOrigin CloudFront behavior. Self-skips at budget
tier >= 2 (PG-10). Idempotent: existing weeks skipped unless {"force": true}.

This is the only NEW-inference podcast; the chronicle read-aloud stays a straight
single-voice narration. Cost: Chirp 3: HD is free under 1M chars/mo; Bedrock
Haiku script-gen is pennies.
"""

import json
import os
import re
from datetime import datetime, timezone

import boto3
import er03_gate
import google_tts
import persona_registry
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

try:
    from platform_logger import get_logger

    logger = get_logger("coach-panel-podcast")
except ImportError:
    import logging

    logger = logging.getLogger("coach-panel-podcast")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
SITE = "https://averagejoematt.com"
PREFIX = "generated/panelcast"
SKIP_TIER = 2  # PG-10
ELENA = "elena_voss"
ELENA_VOICE_FALLBACK = "en-US-Chirp3-HD-Aoede"

s3 = boto3.client("s3", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


# ── inputs ───────────────────────────────────────────────────────────────────


def _published_posts() -> list:
    obj = s3.get_object(Bucket=S3_BUCKET, Key="site/chronicle/posts.json")
    return json.loads(obj["Body"].read()).get("posts", [])


def _strip_md(md: str) -> str:
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md or "")
    t = re.sub(r"[*_#`>]", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _chronicle_md(date_str: str) -> str | None:
    from datetime import timedelta as _td

    base = datetime.strptime(date_str, "%Y-%m-%d")
    for off in (0, 1, -1, 2, -2, 3, -3):
        d = (base + _td(days=off)).strftime("%Y-%m-%d")
        r = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"DATE#{d}"})
        md = (r.get("Item") or {}).get("content_markdown")
        if md:
            return md
    return None


def _coach_latest(coach_id: str) -> dict | None:
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = resp.get("Items", [])
    except Exception:
        items = []
    if not items:
        return None
    it = items[0]
    summary = it.get("key_recommendation") or it.get("observatory_summary") or ""
    return {"summary": summary, "themes": (it.get("themes") or [])[:4]} if summary else None


def _pick_coach(week: int) -> tuple:
    """Rotating co-host: prefer coaches that have material this week, rotate among
    them deterministically by week; fall back to a plain round-robin."""
    ids = persona_registry.OPERATIONAL_COACH_IDS
    with_material = [(c, _coach_latest(c)) for c in ids]
    have = [(c, o) for c, o in with_material if o]
    if have:
        return have[week % len(have)]
    cid = ids[week % len(ids)]
    return cid, None


# ── script generation (Bedrock) + ER-03 gate ─────────────────────────────────


def _voice(speaker: str) -> str:
    return persona_registry.tts_voice(speaker, s3, S3_BUCKET) or (ELENA_VOICE_FALLBACK if speaker == ELENA else "en-US-Chirp3-HD-Charon")


def _build_script(week, title, chronicle_text, coach_id, coach_out, coach_name) -> list:
    import bedrock_client

    coach_block = ""
    if coach_out:
        coach_block = f"\n{coach_name}'s recent read: {coach_out['summary']}\nThemes: {', '.join(coach_out['themes']) or '(none)'}"
    system = (
        "You write a short two-host podcast script reviewing one week of a public health experiment. "
        f"HOST is Elena Voss (embedded journalist). CO-HOST is {coach_name}, an AI coach. "
        'Output ONLY a JSON array of turns: [{"speaker":"elena"|"coach","line":"..."}]. '
        "8–14 turns, conversational and warm, Elena frames topics and asks, the coach reviews findings. "
        "Hard rules: correlative only (never claim causation); use only numbers present in the source; "
        "hedge — the data is early/small-sample; never open a line with 'Matthew'; no preamble or JSON fences."
    )
    user = f"Week {week}: {title}.\n\nThis week's chronicle:\n{chronicle_text[:4000]}{coach_block}\n\n" "Write the JSON dialogue array now."
    body = {"model": MODEL, "max_tokens": 1600, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = bedrock_client.invoke(body, model_name=MODEL)
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        turns = json.loads(text)
    except Exception as e:
        logger.warning("wk%s: script JSON parse failed — %s", week, e)
        return []
    return turns if isinstance(turns, list) else []


def _gate_turns(turns: list, allowed_numbers, coach_id: str) -> list:
    """Keep only ER-03-clean turns; map speaker → persona id. Fail-closed."""
    clean = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        raw = (t.get("speaker") or "").lower()
        speaker = ELENA if raw in ("elena", "host", "elena_voss") else coach_id
        line = (t.get("line") or "").strip()
        if not line:
            continue
        ok, _reasons = er03_gate.er03_check(line, allowed_numbers=allowed_numbers, n=None)
        if ok:
            clean.append({"speaker": speaker, "line": line})
        else:
            logger.info("wk-gate: dropped a %s line — %s", speaker, _reasons)
    return clean


# ── synthesis + publish ──────────────────────────────────────────────────────


def _synthesize_dialogue(turns: list) -> bytes:
    audio = b""
    for t in turns:
        audio += google_tts.synthesize(t["line"], _voice(t["speaker"]))
    return audio


def _episode_exists(week) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.mp3")
        return True
    except Exception:
        return False


def _xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 16:00:00 GMT")


def _write_indexes(episodes: list) -> None:
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
    <guid isPermaLink="false">measured-life-panel-wk{e["week"]}</guid>
    <pubDate>{_rfc822(e["date"])}</pubDate>
  </item>"""
        for e in episodes
    )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>The Measured Life — The Panel</title>
  <link>{SITE}/story/panel/</link>
  <description>A weekly two-host show: Elena Voss and a rotating AI coach review the week's data, findings, and themes. AI voices, correlative, fact-anchored.</description>
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


# ── Episode 0: the full welcome/trailer (event {"intro": true}) ──────────────

MISSION_BRIEF = (
    "The Measured Life is an honest, public documentary of one ordinary person — Matthew — rebuilding his health with AI. "
    "He starts at roughly 311 pounds; the goal is about 185. It is an N=1 experiment: every claim is correlative, never causal, "
    "and the down weeks are shown too. The website has three doors: the Cockpit (today's live data), the Story (the weekly "
    "chronicle, the AI lab notes, and this podcast), and the Evidence (the full data archive). Elena Voss writes the chronicle. "
    "A board of eight AI coaches reads the data and argues about it — that's the team you're about to meet."
)


def _intro_roster() -> list:
    out = [("elena_voss", "Elena Voss", "host — embedded journalist")]
    for cid in persona_registry.OPERATIONAL_COACH_IDS:
        p = persona_registry.resolve(cid, s3, S3_BUCKET) or {}
        out.append((cid, p.get("name") or cid, f"{p.get('board_role') or p.get('domain')}: {p.get('short_bio', '')}"))
    return out


def _build_intro_script(prequel_text: str) -> list:
    import bedrock_client

    roster = "\n".join(f"- {cid}: {name} — {desc}" for cid, name, desc in _intro_roster())
    system = (
        "You write Episode 0 — a warm, lively TRAILER introducing a public health-experiment website and its podcast. "
        "HOST is Elena Voss. Structure: (1) Elena welcomes listeners and introduces the project and Matthew; (2) she walks "
        "through the website's three doors — the Cockpit, the Story, the Evidence — and the chronicle + this podcast; "
        "(3) MEET THE TEAM: each coach gets one short turn, in their own voice, to say who they are and what they watch; "
        "(4) Elena closes on the overarching goal. "
        'Output ONLY a JSON array [{"speaker":"<id>","line":"..."}] where <id> is "elena_voss" or a coach id from the roster. '
        "18–28 turns. Conversational and warm. Rules: correlative only (never causal); use only numbers present in the brief; "
        "hedge that the journey is just beginning; never open a line with 'Matthew'; no preamble or JSON fences."
    )
    user = (
        f"MISSION BRIEF:\n{MISSION_BRIEF}\n\nPREQUEL (Elena's own words):\n{prequel_text[:2500]}\n\n"
        f"ROSTER (use these exact speaker ids):\n{roster}\n\nWrite the JSON dialogue now."
    )
    body = {"model": MODEL, "max_tokens": 3000, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = bedrock_client.invoke(body, model_name=MODEL)
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        turns = json.loads(text)
    except Exception as e:
        logger.warning("[panel] intro JSON parse failed — %s", e)
        return []
    return turns if isinstance(turns, list) else []


def _gate_intro(turns: list, allowed_numbers) -> list:
    """ER-03 gate + resolve any speaker (elena or any coach) to a persona id."""
    valid = set(persona_registry.OPERATIONAL_COACH_IDS) | {ELENA}
    name_to_id = {}
    for cid in persona_registry.OPERATIONAL_COACH_IDS:
        nm = persona_registry.display_name(cid, s3, S3_BUCKET)
        if nm:
            name_to_id[nm.lower()] = cid
    clean = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        raw = (t.get("speaker") or "").strip().lower()
        if raw in ("elena", "host", "elena_voss"):
            spk = ELENA
        elif raw in valid:
            spk = raw
        elif raw in name_to_id:
            spk = name_to_id[raw]
        else:
            continue
        line = (t.get("line") or "").strip()
        if not line:
            continue
        ok, _r = er03_gate.er03_check(line, allowed_numbers=allowed_numbers, n=None)
        if ok:
            clean.append({"speaker": spk, "line": line})
    return clean


def _run_intro() -> dict:
    posts = _published_posts()
    prequel = ""
    for p in sorted(posts, key=lambda x: x.get("week", 0)):  # earliest chronicle first
        md = _chronicle_md(p.get("date", ""))
        if md:
            prequel = _strip_md(md)
            break
    allowed = er03_gate.numbers_in(MISSION_BRIEF + " " + prequel)
    turns = _gate_intro(_build_intro_script(prequel), allowed)
    if len(turns) < 6:
        logger.warning("[panel] intro: too few clean turns (%d)", len(turns))
        return {"statusCode": 500, "body": json.dumps({"intro": "too few turns", "turns": len(turns)})}
    audio = _synthesize_dialogue(turns)
    s3.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk0.mp3", Body=audio, ContentType="audio/mpeg", CacheControl="max-age=86400, public")
    try:
        existing = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read()).get("episodes", [])
    except Exception:
        existing = []
    ep = {
        "week": 0,
        "title": "Episode 0 — Welcome to The Measured Life",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "url": "/panelcast/wk0.mp3",
        "bytes": len(audio),
        "excerpt": "Meet Matthew, the mission, and the whole team — a full introduction to the site, the chronicle, and this podcast.",
    }
    existing = [e for e in existing if e.get("week") != 0] + [ep]
    existing.sort(key=lambda e: e.get("week", 0), reverse=True)
    _write_indexes(existing)
    logger.info("[panel] intro wk0: %d turns, %d bytes", len(turns), len(audio))
    return {"statusCode": 200, "body": json.dumps({"intro": True, "turns": len(turns), "bytes": len(audio)})}


def lambda_handler(event, context):
    event = event or {}
    force = bool(event.get("force"))

    try:
        from budget_guard import current_tier

        tier = current_tier()
        if tier >= SKIP_TIER:
            logger.info("[panel] budget tier %s >= %s — skipping (PG-10)", tier, SKIP_TIER)
            return {"skipped": True, "tier": tier}
    except Exception:
        pass

    # Episode 0 — the full welcome/trailer (all coaches + Elena). One-off / manual.
    if event.get("intro"):
        try:
            return _run_intro()
        except Exception as e:
            logger.error("[panel] intro failed — %s", e)
            return {"statusCode": 500, "body": json.dumps({"intro": "failed", "error": str(e)[:200]})}

    try:
        posts = _published_posts()
    except Exception as e:
        logger.error("[panel] posts.json unavailable — %s", e)
        return {"statusCode": 503, "body": json.dumps({"error": "posts.json unavailable"})}

    episodes, rendered, errors = [], 0, 0
    for p in sorted(posts, key=lambda x: x.get("week", 0), reverse=True):
        week, date_str = p.get("week"), p.get("date")
        if week is None or not date_str:
            continue
        try:
            key = f"{PREFIX}/wk{week}.mp3"
            if force or not _episode_exists(week):
                md = _chronicle_md(date_str)
                if not md:
                    logger.warning("[panel] wk%s: no chronicle for %s — skipped", week, date_str)
                    continue
                coach_id, coach_out = _pick_coach(week)
                coach_name = persona_registry.display_name(coach_id, s3, S3_BUCKET)
                chronicle_text = _strip_md(md)
                allowed = er03_gate.numbers_in(chronicle_text + " " + (coach_out["summary"] if coach_out else ""))
                turns = _gate_turns(
                    _build_script(week, p.get("title", f"Week {week}"), chronicle_text, coach_id, coach_out, coach_name), allowed, coach_id
                )
                if len(turns) < 4:
                    logger.warning("[panel] wk%s: too few clean turns (%d) — skipped", week, len(turns))
                    continue
                audio = _synthesize_dialogue(turns)
                s3.put_object(Bucket=S3_BUCKET, Key=key, Body=audio, ContentType="audio/mpeg", CacheControl="max-age=86400, public")
                rendered += 1
                logger.info("[panel] wk%s: %d turns, %d bytes, co-host %s", week, len(turns), len(audio), coach_id)
                ep_title = f"Week {week}: Elena & {coach_name} review the week"
            else:
                ep_title = f"Week {week}: The Panel"
            size = s3.head_object(Bucket=S3_BUCKET, Key=key)["ContentLength"]
            episodes.append(
                {
                    "week": week,
                    "title": ep_title,
                    "date": date_str,
                    "url": f"/panelcast/wk{week}.mp3",
                    "bytes": size,
                    "excerpt": p.get("excerpt", ""),
                }
            )
        except Exception as e:
            errors += 1
            logger.error("[panel] wk%s: failed (non-fatal) — %s", week, e)

    try:
        _write_indexes(episodes)
    except Exception as e:
        logger.error("[panel] index rebuild failed — %s", e)
        return {"statusCode": 500, "body": json.dumps({"rendered": rendered, "errors": errors, "index": "failed"})}

    logger.info("[panel] %d rendered, %d indexed, %d errors", rendered, len(episodes), errors)
    return {"statusCode": 200, "body": json.dumps({"rendered": rendered, "episodes": len(episodes), "errors": errors})}
