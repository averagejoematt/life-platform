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
        gain = _INTRO_VOLUME_GAIN.get(t["speaker"], 0.0) if "_INTRO_VOLUME_GAIN" in globals() else 0.0
        audio += google_tts.synthesize(t["line"], _voice(t["speaker"]), volume_gain_db=gain)
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


# ── Episode 0 + series creative spine (event {"intro": true}) ─────────────────

BIBLE_KEY = "config/podcast_series_bible.json"  # durable config/ prefix (reset-safe)
SERIES_STATE_KEY = f"{PREFIX}/series_state.json"  # continuity state across episodes

# Day-Zero hallucination guard: Episode 0 is recorded at the starting line, so a
# line must NOT fabricate elapsed time, results, a back-catalogue, or a weight.
_HALLUCINATION_PATTERNS = [
    r"\b(weeks?|days?|months?)\s+(in|into)\b",
    r"\b(two|three|four|five|several|a few|a couple|couple of)\s+(weeks?|days?|months?)\b",
    r"\bweek\s+\d+\b",
    r"\bso far\b",
    r"\blast (episode|time|week)\b",
    r"\bprevious(ly)?\b",
    r"\b(the )?(data|numbers|results|trends?) (show|are showing|already|so far)\b",
    r"\b\d{2,3}\s*(lbs?|pounds?|kg|kilograms?)\b",
    r"\bstarting weight\b",
    r"\bempty (journal|chronicle)\b",
]
_HALLUCINATION_RE = re.compile("|".join(_HALLUCINATION_PATTERNS), re.IGNORECASE)


def _load_bible() -> dict:
    try:
        return json.loads(s3.get_object(Bucket=S3_BUCKET, Key=BIBLE_KEY)["Body"].read())
    except Exception as e:
        logger.warning("[panel] series bible unavailable — %s", e)
        return {}


INTRO_GUEST_ID = "eli_marsh"  # Dr. Eli Marsh — Principal Investigator (the lead)
# Per-voice loudness trim (dB) — only used by the legacy Chirp stitch path.
_INTRO_VOLUME_GAIN = {ELENA: 0.0, INTRO_GUEST_ID: 0.0}
# Episode 0 is synthesized single-pass via Gemini (genuine conversation). Map the
# two speakers to Gemini prebuilt voices; Elena = host (breezy), Eli = guest (informative).
INTRO_GEMINI_VOICES = {"Elena": "Aoede", "Eli": "Charon"}
INTRO_STYLE = (
    "Read the following as a warm, lively two-person podcast interview — natural, conversational, "
    "like two people talking in a studio, with genuine back-and-forth. Elena is the host; Eli is the guest."
)


def _intro_guest() -> dict:
    p = persona_registry.resolve(INTRO_GUEST_ID, s3, S3_BUCKET) or {}
    return {
        "name": p.get("name", "Dr. Eli Marsh"),
        "role": p.get("board_role", "Principal Investigator"),
        "bio": p.get("short_bio", ""),
        "philosophy": p.get("philosophy", ""),
        "expertise": p.get("expertise", []),
    }


def _build_intro_script(bible: dict) -> list:
    """Episode 0 as a two-person interview, driven by the series bible."""
    import bedrock_client

    g = _intro_guest()
    ch = bible.get("characters", {})
    sc = bible.get("site_concepts", {})
    arc = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(bible.get("episode0_arc", [])))
    guards = "\n".join(f"  - {x}" for x in bible.get("guardrails", []))
    site = "\n".join(f"  - {k.title()}: {v}" for k, v in sc.items())

    system = (
        f'You are the head writer for "{bible.get("show_name", "The Measured Life")}", a narrative podcast. Write EPISODE 0: a '
        "warm, intriguing, genuinely human two-person interview that introduces the show to a COMPLETE STRANGER (someone who has "
        "never heard of Matthew) and makes them want to follow the series. Energy of a great narrative-podcast trailer: hook fast, "
        "raise a real and slightly philosophical question, be honest rather than hypey, leave them wanting episode one. "
        f"HOST is Elena Voss; GUEST is {g['name']}, {g['role']}. A REAL conversation — Elena asks what a curious skeptic would ask "
        "and reacts; the guest answers like a person, warm and plain-spoken with the occasional vivid line. They build on each "
        "other, vary turn length, and use a little wry humor.\n\n"
        f"THE BIG QUESTION (the emotional hook — land it, don't rush past it):\n{bible.get('thesis', '')}\n\n"
        f"WHAT'S ACTUALLY BEING MEASURED:\n{bible.get('what_we_measure', '')}\n\n"
        f"TONE: {bible.get('tone', '')}\n\n"
        f"FOLLOW THIS ARC:\n{arc}\n\n"
        f"HARD GUARDRAILS (breaking any of these ruins the episode):\n{guards}\n\n"
        'OUTPUT: ONLY a JSON array of turns [{"speaker":"elena"|"eli","line":"..."}], 18–26 turns. '
        "No preamble, no stage directions, no JSON fences."
    )
    user = (
        f"ELENA (host): {ch.get('elena', '')}\n\n"
        f"MATTHEW (the subject — NEVER a weight or body number): {ch.get('matthew', '')}\n\n"
        f"ELI (guest): {ch.get('eli', '')}\nHis philosophy: {g['philosophy']}\nHis expertise: {', '.join(g['expertise'])}\n\n"
        f"WHAT A LISTENER CAN EXPLORE (weave these in naturally, do NOT list them robotically):\n{site}\n\n"
        "Write Episode 0 now."
    )
    body = {"model": MODEL, "max_tokens": 3500, "system": system, "messages": [{"role": "user", "content": user}]}
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
    """Resolve the two speakers + ER-03 + the Day-Zero hallucination guard (drop any
    line fabricating elapsed time, results, a back-catalogue, or a starting weight)."""
    eli_aliases = {"eli", "eli_marsh", "dr. eli marsh", "eli marsh", "marsh", "guest", "principal investigator", "pi"}
    clean, dropped = [], 0
    for t in turns:
        if not isinstance(t, dict):
            continue
        raw = (t.get("speaker") or "").strip().lower()
        if raw in ("elena", "host", "elena_voss"):
            spk = ELENA
        elif raw in eli_aliases:
            spk = INTRO_GUEST_ID
        else:
            continue
        line = (t.get("line") or "").strip()
        if not line:
            continue
        if _HALLUCINATION_RE.search(line):
            dropped += 1
            logger.info("[panel] intro: dropped Day-Zero-guard line — %s", line[:90])
            continue
        ok, _r = er03_gate.er03_check(line, allowed_numbers=allowed_numbers, n=None)
        if ok:
            clean.append({"speaker": spk, "line": line})
    if dropped:
        logger.info("[panel] intro: hallucination guard dropped %d line(s)", dropped)
    return clean


def _seed_series_state(bible: dict, ep: dict) -> None:
    """Seed continuity state so the weekly Panel can pick up where the series left off."""
    state = {
        "episode_count": 1,
        "last_episode": {
            "week": 0,
            "title": ep.get("title"),
            "summary": (
                "Episode 0 introduced the show — who Elena and Matthew are, the eight-coach AI team Dr. Eli Marsh runs, "
                "and the central bet: can technology and a person's own data genuinely improve a whole life, or is it just "
                "over-optimization theater?"
            ),
            "hook": "The experiment begins now; the weekly Panel tracks the question with real data as it comes in.",
        },
        "running_threads": bible.get("through_lines", []),
        "recurring_bits": bible.get("recurring_bits", []),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=SERIES_STATE_KEY,
        Body=json.dumps(state, indent=2).encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=300, public",
    )


def _run_intro() -> dict:
    bible = _load_bible()
    # Numbers allowed by ER-03 = only those in the bible (it has essentially none →
    # this enforces "no invented numbers"). No elapsed-time/results context is fed.
    allowed = er03_gate.numbers_in(json.dumps(bible))
    turns = _gate_intro(_build_intro_script(bible), allowed)
    if len(turns) < 8:
        logger.warning("[panel] intro: too few clean turns (%d)", len(turns))
        return {"statusCode": 500, "body": json.dumps({"intro": "too few turns", "turns": len(turns)})}
    # Single-pass conversation via Gemini (Elena + Eli genuinely talking).
    import gemini_tts

    label_of = {ELENA: "Elena", INTRO_GUEST_ID: "Eli"}
    label_turns = [{"speaker": label_of.get(t["speaker"], "Elena"), "line": t["line"]} for t in turns]
    audio = gemini_tts.synthesize_dialogue(label_turns, INTRO_GEMINI_VOICES, INTRO_STYLE)
    s3.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk0.wav", Body=audio, ContentType="audio/wav", CacheControl="max-age=86400, public")
    # Transcript alongside the audio — for review and to verify the guardrails held.
    transcript = "\n\n".join(f"{label_of.get(t['speaker'], 'Elena')}: {t['line']}" for t in turns)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX}/wk0.transcript.txt",
        Body=transcript.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
        CacheControl="max-age=300, public",
    )
    try:
        existing = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read()).get("episodes", [])
    except Exception:
        existing = []
    ep = {
        "week": 0,
        "title": "Episode 0 — Welcome to The Measured Life",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "url": "/panelcast/wk0.wav",
        "bytes": len(audio),
        "excerpt": "Meet Elena, meet Matthew, and meet the question this whole experiment is built to answer: can AI and your own data actually make a life better — or is it just over-optimization? The starting line.",
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
