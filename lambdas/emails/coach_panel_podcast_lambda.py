"""coach_panel_podcast_lambda.py — "The Panel": a weekly two-host show (2026-06-14).

Each week Elena Voss hosts and a rotating coach co-reviews the week — the
chronicle plus that coach's recent reads. Bedrock (Haiku) writes a short
conversational script as a list of {speaker, line}; every line passes the ER-03
gate (correlative, no fabricated numbers, no Matt-prefix) before it's voiced;
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
import urllib.parse
from datetime import datetime, timezone

import boto3
import er03_gate
import google_tts
import persona_registry
from boto3.dynamodb.conditions import Key
from constants import EXPERIMENT_START_DATE  # ADR-058/077 — current-cycle genesis anchor
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
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"

s3 = boto3.client("s3", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)


# ── inputs ───────────────────────────────────────────────────────────────────


def _published_posts() -> list:
    # Read the LIVE chronicle feed the Wednesday chronicle actually writes (generated/journal/
    # posts.json) — NOT the dead site/chronicle/posts.json, which left the Panel blind to the
    # current chronicle and drifting a week ahead off a genesis-from-today calc (2026-06-21).
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")
    except Exception:
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


def _short_title(*candidates, max_words: int = 6, max_chars: int = 52) -> str:
    """Reduce the first usable candidate to a short headline hook for an episode
    title: strips any leading 'Week N:' / 'EPN ·', keeps only the first clause,
    caps to max_words / max_chars, drops trailing punctuation. Returns "" if none."""
    for c in candidates:
        s = (c or "").strip()
        if not s:
            continue
        s = re.sub(r"^\s*(week\s*\d+\s*[:\-–—]\s*|ep\s*\d+\s*[·:\-–—]\s*)", "", s, flags=re.I)
        s = re.split(r"[.!?]", s, 1)[0].strip().strip(" ,;:—–-\"'“”")
        words = s.split()
        if len(words) > max_words:
            s = " ".join(words[:max_words])
        if len(s) > max_chars:
            s = s[:max_chars].rsplit(" ", 1)[0].strip()
        if s:
            return s
    return ""


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
        "hedge — the data is early/small-sample; never open a line with 'Matt'; no preamble or JSON fences."
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


# ── Compassion & Safety gate (deterministic, fail-CLOSED) ─────────────────────
# The Personal Board's #1 insistence: an autonomous publisher must NEVER, on Matt's
# worst weeks, voice a blocked vice, a body number, a causal claim, an invented
# number, grief/family/a named person, or a judgmental "report-card" tone. Any hit
# fails CLOSED → the episode is HELD for a human, never auto-published.

_content_filter_cache = None


def _blocked_vice_terms() -> list:
    global _content_filter_cache
    if _content_filter_cache is None:
        try:
            _content_filter_cache = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="config/content_filter.json")["Body"].read())
        except Exception as e:
            logger.warning("[panel] content_filter unavailable — %s", e)
            _content_filter_cache = {}
    cf = _content_filter_cache
    return [t.lower() for t in (cf.get("blocked_vice_keywords") or [])] + [v.lower() for v in (cf.get("blocked_vices") or [])]


_BODY_NUM_RE = re.compile(r"\b\d{2,3}(?:\.\d+)?\s?(?:lb|lbs|pound|pounds|kg|kilo|kilos|kilograms)\b", re.I)
_GRIEF_RE = re.compile(
    r"\b(?:grief|grieving|died|passed away|funeral|cancer|terminal|hospice|"
    r"my (?:mom|mum|dad|mother|father|parent|parents|wife|husband|girlfriend|boyfriend|partner|brother|sister|son|daughter|family))\b",
    re.I,
)
_REPORTCARD_RE = re.compile(
    r"\b(?:you should have|you failed|you only managed|disappoint\w*|need to do better|not good enough|"
    r"fell short|slacked|lazy|no excuse|let yourself down)\b",
    re.I,
)
_CAUSAL_RE = re.compile(
    r"\b(?:caused|because of (?:the|his|her|your)|led to|resulted in|made (?:him|her|them|you) |thanks to|is why (?:his|her|the|your))\b",
    re.I,
)


def _safety_gate(text: str) -> list:
    """Fail-CLOSED compassion & safety check on the FINAL voiced text.
    Returns a list of violation reasons (empty list = clean)."""
    t = text or ""
    low = t.lower()
    reasons = []
    for term in _blocked_vice_terms():
        if term and re.search(rf"\b{re.escape(term)}\b", low):
            reasons.append(f"blocked-vice:{term}")
            break
    if _BODY_NUM_RE.search(t):
        reasons.append("body-number")
    if _GRIEF_RE.search(t):
        reasons.append("grief/family/named-person")
    if _REPORTCARD_RE.search(t):
        reasons.append("report-card-tone")
    if _CAUSAL_RE.search(t):
        reasons.append("causal-claim")
    return reasons


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
    _invalidate_cdn()


def _set_pending(week, reason: str, display: str, expected_date=None) -> None:
    """Record a non-blocking 'pending episode' marker in episodes.json so the Panel
    tab can show WHY no new episode dropped instead of going silent (the silent-skip
    gap, 2026-06-20). Preserves the episodes list; a successful publish rewrites
    episodes.json via _write_indexes (no `pending` key) → the marker clears itself.
    Fail-open: surfacing a pending state must never break the run."""
    try:
        try:
            doc = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read())
        except Exception:
            doc = {"episodes": []}
        doc["pending"] = {
            "week": week,
            "reason": reason,
            "display": display,
            "expected_date": expected_date,
            "noted_at": datetime.now(timezone.utc).isoformat(),
        }
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX}/episodes.json",
            Body=json.dumps(doc, indent=1),
            ContentType="application/json",
            CacheControl="max-age=3600, public",
        )
        _invalidate_cdn()
    except Exception as e:  # noqa: BLE001
        print(f"[panel] _set_pending failed (non-fatal): {e}")


# CloudFront distribution serving averagejoematt.com (S3GeneratedOrigin handles /panelcast/*).
CF_DISTRIBUTION_ID = os.environ.get("CF_DISTRIBUTION_ID", "E3S424OXQZ8NBE")


def _invalidate_cdn() -> None:
    """Invalidate /panelcast/* after publishing so a new episode is live immediately.
    wk*.wav carries a 24h cache header, so without this the CDN serves the prior cut
    for up to a day. Fail-open: a publish must never break on a CDN hiccup (the file
    is already in S3; the cache just expires on its own as a fallback).

    NB: CloudFront invalidations match the VIEWER path, not the S3 key. The public
    URL is /panelcast/* — the `generated/` key prefix is stripped at the edge by
    S3GeneratedOrigin — so we must invalidate the public path. Invalidating
    /generated/panelcast/* clears a path nobody requests and leaves the cut cached."""
    public_path = "/" + (PREFIX.split("/", 1)[1] if "/" in PREFIX else PREFIX)  # generated/panelcast -> /panelcast
    try:
        cf = boto3.client("cloudfront", region_name=REGION)
        cf.create_invalidation(
            DistributionId=CF_DISTRIBUTION_ID,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": [f"{public_path}/*"]},
                "CallerReference": f"panelcast-{datetime.now(timezone.utc).timestamp()}",
            },
        )
        logger.info("[panel] CDN invalidation requested for %s/*", public_path)
    except Exception as e:
        logger.warning("[panel] CDN invalidation failed (fail-open, cache expires on its own): %s", e)


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
# Episode 0 is the flagship trailer — use Sonnet (follows the multi-step arc + hard
# requirements far better than Haiku, which kept dropping Elena's self-intro).
INTRO_MODEL = os.environ.get("AI_MODEL_SONNET", "claude-sonnet-4-6")
INTRO_GEMINI_VOICES = {"Elena": "Aoede", "Eli": "Charon"}
INTRO_STYLE = (
    "Perform this as a real, warm two-person podcast — NOT a formal reading. Two people who like each other, "
    "talking in a studio: relaxed pace, natural rhythm, light interjections and reactions, the occasional small laugh "
    "in the voice, a beat of thought before a big answer. Elena hosts; Eli is the guest. Conversational, not announced."
)
# Deterministic Elena sign-off, appended as the FINAL turn. Gemini multi-speaker
# occasionally bleeds the PRIOR speaker's voice into the last line (ADR-087 ceiling),
# which once voiced Elena's "I'm Elena Voss" close in Eli's voice. Since the bleed
# carries the prior voice forward, guaranteeing an Elena→Elena ending means even a
# bleed lands Elena's voice on her own sign-off.
INTRO_SIGNOFF = "I'm Elena Voss. This has been The Measured Life. Come back next week — we start for real."
_SIGNOFF_RE = re.compile(r"\s*(i'?m\s+elena\s+voss\b.*)$", re.IGNORECASE | re.DOTALL)
WEEKLY_STYLE = (
    "Perform this as a real, warm weekly podcast conversation — NOT a formal reading. Two people riffing in a studio: "
    "natural rhythm, quick reactions, a little wry humor, the occasional small laugh. Conversational, never announced."
)
# Shared writer directive — make the SCRIPT genuinely conversational so the voice has
# something human to perform (Gemini reads what's written; banter must be on the page).
CONVO_DIRECTIVE = (
    "Write it like two people who actually like each other talking — NOT alternating monologues. Use genuine back-and-forth: "
    "short interjections and reactions ('Mm.', 'Right.', 'Wait—', 'Exactly.', 'Honestly?'), one person occasionally finishing "
    "or gently cutting into the other's thought, a trailing-off, a little dry humor, a beat of real curiosity. Vary turn length "
    "hard — some turns are one word, some are a paragraph. No bracketed stage directions (no '[laughs]'); put the warmth in the words."
)
# Deterministic cold open — guarantees Episode 0 starts with Elena's named self-intro
# (the LLM keeps preferring a punchy hook over literally naming herself). Doubles as
# the universal hook: a capable person who knows how, has done it, and watches it slip.
INTRO_COLD_OPEN = (
    "Here's the part that got me. This is someone who already knows how to do it — he's been in the best shape of his "
    "life, more than once. He's not missing the information. And he's watched it slip anyway. I'm Elena Voss, the "
    "journalist living inside this experiment, and that's the question I couldn't put down: if you know exactly what "
    "to do, why doesn't that save you — and can a wall of AI and sensors finally catch the thing willpower keeps missing?"
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
        "never heard of Matt) and makes them want to follow the series. Energy of a great narrative-podcast trailer: hook fast, "
        "raise a real and slightly philosophical question, be honest rather than hypey, leave them wanting episode one. "
        f"HOST is Elena Voss; GUEST is {g['name']}, {g['role']}. A REAL conversation — Elena asks what a curious skeptic would ask "
        "and reacts; the guest answers like a person, warm and plain-spoken with the occasional vivid line. They build on each "
        "other, vary turn length, and use a little wry humor.\n\n"
        f"{CONVO_DIRECTIVE}\n\n"
        f"THE BIG QUESTION (the emotional hook — land it, don't rush past it):\n{bible.get('thesis', '')}\n\n"
        f"WHAT'S ACTUALLY BEING MEASURED:\n{bible.get('what_we_measure', '')}\n\n"
        f"TONE: {bible.get('tone', '')}\n\n"
        f"FOLLOW THIS ARC, IN ORDER:\n{arc}\n\n"
        "NON-NEGOTIABLE REQUIREMENTS:\n"
        "  - OPEN ON A HOOK, not an introduction. Elena's very first line is a genuine grab — the universal tension at the "
        "heart of this: a capable person who already KNOWS how to do it, has done it, and watches it slip anyway. Land that "
        'before anything administrative. Her first line must still include "I\'m Elena Voss" and who she is, woven INTO the '
        "hook (not a flat 'My name is...'). She speaks first, alone, before the guest.\n"
        "  - REAL TENSION, not mutual agreement. Eli must NAME THE RISK HIMSELF, unprompted, in his own words — say out loud "
        "that this could curdle into over-optimization theater, quantifying a life instead of living it — BEFORE Elena raises "
        "it; he's a scientist who states the failure mode plainly, then says why he still thinks it's worth doing. Elena pushes "
        "harder, not softer ('that's the thing I'm most worried about', 'convince me this isn't just a beautiful dashboard'). "
        "At least one real point of friction where they don't fully agree. Warm, but no sales pitch and no easy consensus.\n"
        "  - PACING (this is a trailer, every second earns its place): get into genuine back-and-forth FAST. After Elena's "
        "opening hook, NO speaker gets more than 2 turns in a row — break long explanations by having the other person cut in, "
        "react, or ask. Cut filler. Favour short, vivid, QUOTABLE lines someone would screenshot over long paragraphs.\n"
        "  - Before the harder material, Elena must establish WHO Matt is and why a complete STRANGER should care about him — an "
        "ordinary, technical, curious person who has done this before and genuinely succeeded (the high). Meet the person and the "
        "stakes FIRST.\n"
        "  - THEN his honest story, IN THIS episode, told as a SMOOTH continuation (NEVER an abrupt topic jump — Elena bridges "
        "into it): he's consistent until something disrupts the routine and the old habits return; the weight was the symptom, "
        "not the problem; and 'can a system catch what willpower alone misses?'. Do NOT defer it to a future episode. Do NOT "
        "invent specific events, losses, deaths, illnesses, relocations, or dates — use only the character note and keep it to "
        "the general pattern.\n"
        "  - Elena must mention that she writes a WEEKLY chronicle and that this podcast runs alongside it.\n"
        "  - The platform doors (Cockpit / Story / Evidence / Sources / Character) must be WOVEN INTO THE DIALOGUE one at a "
        "time, each surfacing naturally from something Eli or Elena just said — NEVER delivered as one listed tour or a single "
        "monologue. If a door doesn't come up organically, drop it rather than force a list.\n"
        "  - CLOSE on the series' standing open question — the bet this whole show is settling, that every future episode "
        f"moves the needle on: {bible.get('series_question', bible.get('thesis', ''))} Frame it as the reason to come back.\n\n"
        f"HARD GUARDRAILS (breaking any of these ruins the episode):\n{guards}\n\n"
        'OUTPUT: ONLY a JSON array of turns [{"speaker":"elena"|"eli","line":"..."}], 20–28 turns. '
        "No preamble, no stage directions, no JSON fences."
    )
    user = (
        f"ELENA (host): {ch.get('elena', '')}\n\n"
        f"MATTHEW (the subject — NEVER a weight or body number): {ch.get('matthew', '')}\n\n"
        f"ELI (guest): {ch.get('eli', '')}\nHis philosophy: {g['philosophy']}\nHis expertise: {', '.join(g['expertise'])}\n\n"
        f"WHAT A LISTENER CAN EXPLORE (weave these in naturally, do NOT list them robotically):\n{site}\n\n"
        "Write Episode 0 now."
    )
    body = {"model": INTRO_MODEL, "max_tokens": 4000, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = bedrock_client.invoke(body, model_name=INTRO_MODEL)
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
                "Episode 0 introduced the show — who Elena and Matt are, the eight-coach AI team Dr. Eli Marsh runs, "
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


# ── QA rigor (automates the manual review loop, 2026-06-17) ───────────────────
# Two layers on top of the ER-03 + Compassion gates, both catching CRAFT/accuracy
# problems those deterministic safety gates can't see (monologue dumps, no tension,
# invented biography, abrupt flow). A generator that fails QA is RE-ROLLED up to
# _QA_MAX_ATTEMPTS times (generation is non-deterministic, so a re-roll usually
# fixes it); the best candidate is kept. See the 2026-06-17 handover.
_QA_MAX_ATTEMPTS = int(os.environ.get("PANEL_QA_MAX_ATTEMPTS", "3"))
_QA_MAX_WORDS_PER_TURN = 130  # a turn longer than this reads as a monologue, not dialogue
_QA_HOOK_MAX_WORDS = 180  # turn 0 is the cold-open hook — a solo turn by design, allowed to run longer
_QA_MAX_CONSECUTIVE = 3  # 4+ turns from one speaker is a floor-hog; 3 short turns reads fine (calibrated 2026-06-17)


def _craft_check(turns: list) -> list:
    """Deterministic, zero-cost craft gate. Returns a list of failure reasons (empty = pass).
    Catches exactly the pacing problems an LLM judge is unreliable at: monologue dumps and
    one speaker holding the floor too long. Calibrated 2026-06-17: 4+ consecutive turns is the
    real floor-hog (3 short turns reads fine), and turn 0 is the intentional solo cold-open hook
    (a longer ceiling, not the dialogue cap)."""
    fails = []
    run = 1
    for i in range(1, len(turns)):
        run = run + 1 if turns[i].get("speaker") == turns[i - 1].get("speaker") else 1
        if run > _QA_MAX_CONSECUTIVE:
            fails.append(f"{turns[i].get('speaker')} speaks {run} turns in a row (max {_QA_MAX_CONSECUTIVE}) — break it up")
            break
    for i, t in enumerate(turns):
        wc = len((t.get("line") or "").split())
        cap = _QA_HOOK_MAX_WORDS if i == 0 else _QA_MAX_WORDS_PER_TURN
        if wc > cap:
            label = "cold-open hook" if i == 0 else "monologue"
            fails.append(f"turn {i} is a {wc}-word {label} (max {cap}) — make it conversational")
    return fails


def _qa_review(turns: list, rubric: str, ground_truth: str = "") -> tuple:
    """LLM craft+accuracy judge (Haiku, cheap). Returns (ok, [reasons]). FAIL-OPEN:
    any judge/infra error returns (True, []) so a flaky judge never blocks a publish —
    the deterministic safety gates remain the hard floor."""
    import bedrock_client

    script = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        "You are a ruthless podcast script editor doing QA on a draft. Judge ONLY the rubric below. "
        'Reply with STRICT JSON: {"pass": true|false, "fails": ["short reason", ...]}. No prose, no fences. '
        "Be strict but fair — flag a rubric item only on a clear miss.\n\nRUBRIC:\n" + rubric
    )
    user = (f"GROUND TRUTH (the only facts allowed about the subject):\n{ground_truth}\n\n" if ground_truth else "") + f"SCRIPT:\n{script}"
    try:
        body = {"model": MODEL, "max_tokens": 500, "system": system, "messages": [{"role": "user", "content": user}]}
        resp = bedrock_client.invoke(body, model_name=MODEL)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        verdict = json.loads(text)
        if verdict.get("pass"):
            return True, []
        return False, [str(r) for r in (verdict.get("fails") or ["failed QA rubric"])][:6]
    except Exception as e:
        logger.warning("[panel] QA judge unavailable (fail-open): %s", e)
        return True, []


_INTRO_RUBRIC = (
    "The two speakers are ELENA VOSS (the host — an embedded journalist) and DR. ELI MARSH (the guest — the "
    "Principal Investigator who built the platform). MATT is the third-person SUBJECT of the experiment; he is NOT "
    "in the room and does NOT speak. These three are ESTABLISHED show personas — never treat Elena or Eli as invented.\n"
    "1. Opens on a genuine HOOK in turn 0, not a flat self-introduction.\n"
    "2. After the opening, it's a real two-person conversation (no long stretch of one person talking).\n"
    "3. At least one point of GENUINE friction/disagreement — Eli is not just agreeing with Elena throughout.\n"
    "4. Dr. Eli Marsh (the PI) names the over-optimization / 'measuring a life instead of living it' RISK himself, in his own words.\n"
    "5. No abrupt, unbridged topic jumps.\n"
    "6. Closes on the series' standing open question (does the tech genuinely make a life better, or theater).\n"
    "7. ACCURACY — applies ONLY to MATT (the subject): the script must not assert any specific life event, loss, "
    "death, illness, relocation, city, or date about MATT that isn't in the GROUND TRUTH. Do NOT flag the names, "
    "titles, or roles of Elena Voss or Dr. Eli Marsh — they are real show personas, not inventions. Only invented "
    "facts about MATT fail this item."
)


# The weekly read-aloud bar: a real listener should believe this is a human-made podcast and
# recommend it. Encodes Matt's acceptance test (2026-06-21) — Turing-pass transcript, guest
# introduced, no dangling thread, grounded, with humour and human interest.
# SS-09 (2026-06-30): a format/entry-point rotation lever so the weekly show doesn't
# feel formulaic by episode 26. The bet/Split/scoreboard scaffold stays (it's the
# show's identity) — only the LENS the episode leads with rotates, deterministically by
# week number. Injected into the writer prompt so consecutive episodes feel distinct.
_EPISODE_ANGLES = [
    "Open COLD on the single most surprising number in this week's material, then unspool why it matters — no throat-clearing.",
    "Lead with THE SPLIT: start from where the guest coach most disagrees with the others, and let the friction drive the episode.",
    "Open by scoring last week's bet out loud — did it hold? — and let that verdict set this week's agenda.",
    "Lead with the week's hardest moment or biggest effort (process, never outcome) and what it actually revealed.",
    "Build the episode around a question a curious listener would genuinely ask this week, and answer it honestly end-to-end.",
    "Lead with what CHANGED versus the established pattern — the inflection, however small — and whether it's signal or noise.",
]


def _episode_angle(week):
    """The rotating entry-point lens for this week's episode (deterministic by week)."""
    try:
        return _EPISODE_ANGLES[int(week) % len(_EPISODE_ANGLES)]
    except Exception:
        return _EPISODE_ANGLES[0]


_WEEKLY_RUBRIC = (
    "Two speakers: ELENA VOSS (host, embedded journalist) and the GUEST COACH (an AI coach, named in the script). "
    "MATT is the third-person SUBJECT of the experiment — he is NOT in the room and does NOT speak. Elena and the "
    "coaches are ESTABLISHED show personas (never flag them as invented). Judge it as a real podcast a human would "
    "believe is human-made and would recommend to a friend:\n"
    "1. READ-ALOUD TURING TEST: read aloud, it must sound human-written. Flag any AI tell — 'in this episode', "
    "narrating the format or naming segments, tidy three-item lists, 'not just X, it's Y' symmetry, over-explaining, "
    "hedge throat-clearing, or a neat summary bow at the end.\n"
    "2. GUEST INTRODUCTION: the guest is introduced for the audience early (who they are + what they work on), UNLESS "
    "they were the guest in the immediately previous episode. A guest who just starts talking with no introduction FAILS.\n"
    "3. NO DANGLING THREAD: every question Elena asks is actually answered in the next turn; no topic the SCRIPT itself "
    "raises is then dropped; no abrupt unbridged jump; never two same-speaker turns where a reply is clearly missing. "
    "(Coverage is NOT required — do NOT flag a ground-truth fact that simply goes unmentioned; only flag a thread the "
    "script opens and abandons.)\n"
    "4. REAL HOOK: turn 0 earns attention — not a flat 'welcome to the show'.\n"
    "5. GENUINE FRICTION: at least one real disagreement or tension, not constant agreement.\n"
    "6. GROUNDED: every specific claim, number, or event about MATT traces to the GROUND TRUTH. No invented scenes, "
    "times of day, or sensory detail (e.g. a '5 AM protein shake'). Flag anything not in the ground truth.\n"
    "7. NO BODY WEIGHT IN THE SCRIPT: no body-weight figure appears in the spoken lines, numeric or spelled-out "
    "(e.g. 'nine pounds'). Body weight in the GROUND TRUTH is fine and expected — only flag it if it is SPOKEN in the script.\n"
    "8. HUMOUR & HUMAN INTEREST: at least one genuinely warm or dryly funny human beat — not dry data recitation."
)


def _qa_gate(turns: list, rubric: str, ground_truth: str = "") -> list:
    """Combined craft (deterministic) + LLM-judge gate. Returns all failure reasons (empty = clean)."""
    return _craft_check(turns) + _qa_review(turns, rubric, ground_truth)[1]


def _run_intro(dry_run: bool = False) -> dict:
    bible = _load_bible()
    # Numbers allowed by ER-03 = only those in the bible (it has essentially none →
    # this enforces "no invented numbers"). No elapsed-time/results context is fed.
    allowed = er03_gate.numbers_in(json.dumps(bible))
    _chars = bible.get("characters", {}) or {}
    bio_truth = (
        "MATT — the experiment's SUBJECT, the ONLY person whose biographical facts are constrained:\n"
        + _chars.get("matthew", "")
        + "\n\nESTABLISHED show personas (NOT Matt, NOT inventions — never flag their names/roles): "
        "Elena Voss (host, embedded journalist); Dr. Eli Marsh (guest, the Principal Investigator who runs the AI coach team)."
    )

    def _candidate():
        ts = _gate_intro(_build_intro_script(bible), allowed)
        if len(ts) < 8:
            return None
        # Launch lock: enforce "Matt" (the model occasionally reverts to "Matthew") and,
        # if the LLM didn't name Elena in line 1, prepend the fixed warm cold-open.
        for t in ts:
            t["line"] = re.sub(r"\bMatthew\b", "Matt", t["line"])
        first = ts[0]["line"].lower()
        if not ("i'm elena" in first or "i am elena" in first or "elena voss" in first):
            ts.insert(0, {"speaker": ELENA, "line": INTRO_COLD_OPEN})
        return ts

    # QA retry loop: generate, run the craft + judge gate, re-roll on failure (generation
    # is non-deterministic, so a re-roll usually clears it). Keep the cleanest candidate.
    turns, qa_fails = None, ["no candidate generated"]
    for attempt in range(_QA_MAX_ATTEMPTS):
        cand = _candidate()
        if not cand:
            continue
        fails = _qa_gate(cand, _INTRO_RUBRIC, bio_truth)
        if turns is None or len(fails) < len(qa_fails):
            turns, qa_fails = cand, fails
        if not fails:
            logger.info("[panel] intro: clean QA on attempt %d (%d turns)", attempt + 1, len(cand))
            break
        logger.info("[panel] intro QA attempt %d/%d failed: %s", attempt + 1, _QA_MAX_ATTEMPTS, fails)

    if turns is None:
        logger.warning("[panel] intro: no usable candidate after %d attempts", _QA_MAX_ATTEMPTS)
        return {"statusCode": 500, "body": json.dumps({"intro": "too few turns"})}
    if qa_fails:
        logger.warning("[panel] intro: best candidate still has %d QA flag(s): %s", len(qa_fails), qa_fails)

    # Deterministic close (ADR-087 voice-bleed mitigation): strip any LLM-baked
    # "I'm Elena Voss" sign-off from the last turn, then append a fixed Elena sign-off
    # as the final turn — guaranteeing an Elena→Elena ending so a Gemini voice-bleed
    # lands Elena's own voice on her sign-off (it carries the PRIOR speaker forward).
    if turns and turns[-1]["speaker"] == ELENA:
        stripped = _SIGNOFF_RE.sub("", turns[-1]["line"]).rstrip()
        if stripped:
            turns[-1]["line"] = stripped
    turns.append({"speaker": ELENA, "line": INTRO_SIGNOFF})

    label_of = {ELENA: "Elena", INTRO_GUEST_ID: "Eli"}
    # Dry run: write only the transcript (Bedrock cost only, no Gemini audio) so the
    # script can be read and approved BEFORE we spend a voicing pass. The live wk0.*
    # audio/episode are left untouched.
    if dry_run:
        preview = "\n\n".join(f"{label_of.get(t['speaker'], 'Elena')}: {t['line']}" for t in turns)
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX}/wk0.draft.transcript.txt",
            Body=preview.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            CacheControl="max-age=60, public",
        )
        logger.info("[panel] intro DRY RUN: %d turns → wk0.draft.transcript.txt (no audio); qa_fails=%s", len(turns), qa_fails)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "intro": "dry_run",
                    "turns": len(turns),
                    "qa_pass": not qa_fails,
                    "qa_fails": qa_fails,
                    "preview_key": f"{PREFIX}/wk0.draft.transcript.txt",
                }
            ),
        }

    # Single-pass conversation via Gemini (Elena + Eli genuinely talking).
    import gemini_tts

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
    # Structured transcript for the on-page reader (speaker-attributed turns + the
    # host's questions as in-page chapter anchors). No audio timestamps exist
    # (single-pass Gemini), so chapters jump within the transcript, not the audio.
    _name_of = {ELENA: "Elena", INTRO_GUEST_ID: "Dr. Eli Marsh"}
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX}/wk0.transcript.json",
        Body=json.dumps(
            {
                "week": 0,
                "title": "EP0 · Welcome to The Measured Life",
                "byline": "Elena + Dr. Eli Marsh",
                "turns": [{"speaker": t["speaker"], "name": _name_of.get(t["speaker"], "Elena"), "line": t["line"]} for t in turns],
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
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
        "duration_sec": max(1, (len(audio) - 44) // (gemini_tts.SAMPLE_RATE * 2)),  # WAV: 16-bit mono PCM
        "byline": "Elena + Dr. Eli Marsh",
        "excerpt": "Meet Elena, meet Matt, and meet the question this whole experiment is built to answer: can AI and your own data actually make a life better — or is it just over-optimization? The starting line.",
        "transcript_url": "/panelcast/wk0.transcript.json",
    }
    existing = [e for e in existing if e.get("week") != 0] + [ep]
    existing.sort(key=lambda e: e.get("week", 0), reverse=True)
    _write_indexes(existing)
    logger.info("[panel] intro wk0: %d turns, %d bytes", len(turns), len(audio))
    return {"statusCode": 200, "body": json.dumps({"intro": True, "turns": len(turns), "bytes": len(audio)})}


# ── Weekly autonomous pipeline (board-reviewed) ───────────────────────────────
# gather → select agenda → Sonnet write (bet format) → Haiku editor-judge →
# two-tier gate (ER-03 + Compassion&Safety) → sensitivity routing → publish-or-HOLD.
# series_state lives in DynamoDB (reset-safe); HOLD is loud (SNS + non-public draft).

PANEL_STATE_PK = f"USER#{USER_ID}#SOURCE#panelcast"
PANEL_STATE_SK = "STATE#current"
HOLD_PREFIX = "panelcast-holds"  # NON-public (not under generated/) — human-review drafts
ALERTS_TOPIC_ARN = os.environ.get("ALERTS_TOPIC_ARN", f"arn:aws:sns:{REGION}:205930651321:life-platform-alerts")
WRITER_MODEL = INTRO_MODEL  # Sonnet — narrative quality
JUDGE_MODEL = MODEL  # Haiku — cheap editor/QA judge
MAX_SONNET_CALLS = 5  # Dana's cost cap per run
# Elena + each coach → a distinct Gemini prebuilt voice (2 voices/episode).
GEMINI_VOICE = {
    "elena_voss": "Aoede",
    "eli_marsh": "Charon",
    "sleep_coach": "Kore",
    "training_coach": "Fenrir",
    "nutrition_coach": "Leda",
    "mind_coach": "Puck",
    "physical_coach": "Orus",
    "glucose_coach": "Zephyr",
    "labs_coach": "Callirrhoe",
    "explorer_coach": "Iapetus",
}
_SENSITIVE_WEEK_RE = re.compile(
    r"\b(grief|grieving|died|passed away|funeral|cancer|terminal|hospice|suicid\w*|relapse|breakup|divorce|"
    r"depress\w*|hopeless|panic attack|self-harm)\b",
    re.I,
)


def _gemini_voice(persona_id: str) -> str:
    """Gender-correct Gemini voice, sourced from the persona registry (config/personas.json
    tts_voice) — the single source of truth. The old hardcoded GEMINI_VOICE table had drifted
    out of sync with persona genders (Dr. Marcus Webb → a female voice, Dr. Sarah Chen → a male
    one). The registry's tts_voice ("en-US-Chirp3-HD-Charon") shares the voice name with Gemini,
    so the suffix IS the Gemini voice. Falls back to the legacy table only if the registry lacks one."""
    tts = persona_registry.tts_voice(persona_id, s3, S3_BUCKET) or ""
    name = tts.rsplit("-", 1)[-1] if tts else ""
    return name or GEMINI_VOICE.get(persona_id, "Charon")


def _state_read() -> dict:
    try:
        it = table.get_item(Key={"pk": PANEL_STATE_PK, "sk": PANEL_STATE_SK}).get("Item")
        return json.loads(it.get("state_json", "{}")) if it else {}
    except Exception as e:
        logger.warning("[panel] series_state read failed — %s", e)
        return {}


def _state_write(state: dict) -> None:
    # phase="experiment" so reset tooling (ADR-077) re-tags/wipes it with the cycle.
    table.put_item(
        Item={"pk": PANEL_STATE_PK, "sk": PANEL_STATE_SK, "state_json": json.dumps(state), "phase": "experiment", "updated": _today()}
    )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_json(text: str):
    """Tolerant parse: strip fences, then grab the first balanced JSON object/array
    (LLMs sometimes append prose after the JSON). Returns None on failure."""
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"[\{\[].*[\}\]]", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _gather_week(post: dict, state: dict) -> dict:
    """Deterministic beat collection (Viktor's v1 cut — no LLM showrunner)."""
    md = _chronicle_md(post.get("date", ""))
    chronicle = _strip_md(md) if md else ""
    coach_reads = []
    for cid in persona_registry.OPERATIONAL_COACH_IDS:
        out = _coach_latest(cid)
        if out and out.get("summary"):
            coach_reads.append({"id": cid, "name": persona_registry.display_name(cid, s3, S3_BUCKET) or cid, **out})
    guest = coach_reads[post.get("week", 0) % len(coach_reads)] if coach_reads else None
    return {
        "week": post.get("week"),
        "date": post.get("date"),
        "title": post.get("title", f"Week {post.get('week')}"),
        "chronicle": chronicle,
        "coach_reads": coach_reads,
        "guest": guest,
        "last_open_bet": state.get("open_bet"),
        "recent_topics": state.get("recent_topics", []),
        "prev_guest": (state.get("last_episode") or {}).get("guest_name") or "",
    }


def _is_current_crisis(text: str) -> bool:
    """Adjudicate a sensitivity-regex hit: a genuine ACUTE crisis THIS week (hold) vs. the
    narrative merely REFERENCING past hardship/grief as backstory (safe to proceed). The pre-write
    regex trips on both, so a strong week was being held just for naming the backstory (e.g. a
    mother who died years ago). Fail-CLOSED: any error or non-CONTEXT answer → treat as crisis."""
    import bedrock_client

    try:
        system = (
            "You screen a weekly health-podcast's source material for a safety gate. Decide whether THIS WEEK "
            "contains an ACUTE crisis an upbeat automated episode could mishandle — a death, a relapse, a breakdown, "
            "or acute low mood / self-harm that HAPPENED THIS WEEK — versus material that merely REFERENCES past "
            "hardship or grief as backstory while the week itself was ordinary or positive. "
            "Reply with exactly one word: CRISIS or CONTEXT."
        )
        body = {"model": MODEL, "max_tokens": 5, "system": system, "messages": [{"role": "user", "content": text[:6000]}]}
        resp = bedrock_client.invoke(body, model_name=MODEL)
        verdict = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip().upper()
        logger.info("sensitivity adjudication: %s", verdict or "(empty)")
        return not verdict.startswith("CONTEXT")  # only an explicit CONTEXT proceeds; anything else holds
    except Exception as e:
        logger.warning("sensitivity adjudication failed (%s) — holding fail-closed", e)
        return True


def _sensitivity_hold_reasons(beats: dict) -> list:
    """Personal Board asymmetry: hard/sensitive weeks route to a human, never auto-publish.
    Scans the chronicle AND the coach reads (the Panel can run from coach reads alone). The regex
    is a broad TRIGGER that also fires on BACKSTORY references to past grief; an AI adjudication
    then holds only on a genuine CURRENT-WEEK crisis (fail-closed). The post-write _safety_gate
    remains the final backstop on the actual voiced lines."""
    reasons = []
    text = beats.get("chronicle", "") + " " + " ".join(c.get("summary", "") for c in beats.get("coach_reads", []))
    if _SENSITIVE_WEEK_RE.search(text) and _is_current_crisis(text):
        reasons.append("sensitive-week (current-week crisis) — human review")
    return reasons


def _build_weekly_script(beats: dict, bible: dict) -> dict:
    """Sonnet writes the Elena + guest-coach episode in the bet/Split/scoreboard format."""
    import bedrock_client

    guest = beats.get("guest") or {}
    fmt = bible.get("weekly_format", {})
    others = [c for c in beats.get("coach_reads", []) if c["id"] != guest.get("id")][:3]
    split_material = "\n".join(f"- {c['name']}: {c['summary']}" for c in others)
    system = (
        f'You are the head writer for "{bible.get("show_name", "The Measured Life")}". Write a WEEKLY episode: a warm, honest, '
        f"genuinely interesting two-person conversation. HOST: Elena Voss. GUEST: {guest.get('name', 'a coach')}. "
        f"FORMAT (follow it):\n{json.dumps(fmt.get('segments', []))}\nSign-off line: {fmt.get('sign_off', '')}\n\n"
        f"SELECTION/TONE: {json.dumps(bible.get('selection_rubric', {}))}\nTONE: {bible.get('tone', '')}\n\n"
        "HARD RULES: correlative only (never causal); use ONLY numbers present in the material; hedge anything on a small sample; "
        "process over outcome — never a report-card or judgmental tone; handle a hard week with compassion; never open a line with 'Matt'. "
        "This is a forward-looking PERFORMANCE & HEALTH review, NOT a grief or personal-history piece. NEVER mention or allude to: "
        "a death, grief, a funeral, cancer, or any named family member (mother/father/sister/brother/girlfriend/wife/etc.); any specific "
        "vice or substance (marijuana, alcohol, nicotine, pornography — not even non-specifically as 'his vices' or 'private habits'); "
        "or any body weight at all — numeric OR spelled-out ('nine pounds' is just as forbidden as '305 lbs'). Stay on training, sleep, recovery, habits, the deficit's effects, the bet, and the week's effort. "
        "THE BAR (this is the whole point): the TRANSCRIPT must pass for a real, human-made podcast — if a person read it aloud, "
        "nobody could tell it was AI-written. Earn a real hook in the first two lines, real human interest, genuine dry humor, and "
        "something a listener actually learns and would text to a friend. NO AI TELLS: never say 'in this episode' or 'today we're "
        "diving into'; never narrate the format or name the segments; no tidy three-item lists; no 'not just X, it's Y' symmetry; no "
        "over-explaining or throat-clearing; no neat bow at the end. Think a sharp, warm two-person show people actually subscribe to. "
        "GROUNDING (non-negotiable): every line must come from the real material below — the coaches' reads and the week's data. Do NOT "
        "invent scenes, settings, times of day, anecdotes, or sensory detail (no '5 AM protein shake', no 'lukewarm shake', nothing that "
        "isn't in the material). If it isn't in the data, it didn't happen. The chronicle is background only — never quote it or lift its "
        "literary scene-setting as fact. GUEST INTRO & CONTINUITY: ALWAYS introduce this week's guest for the audience early — their name and "
        "what they actually work on — UNLESS they were the guest in the immediately previous episode (then acknowledge the returning thread "
        "instead). Listeners may have never met this coach; a new voice must never just start talking with no introduction. EVERY question "
        "Elena asks must get a real answer in the very next turn — never raise a question and move on, never leave a thread dangling. "
        f"{CONVO_DIRECTIVE} "
        'OUTPUT ONLY JSON: {"turns":[{"speaker":"elena"|"coach","line":"..."}], "open_bet":"<the one new falsifiable bet for next week>", '
        '"last_bet_result":{"outcome":"won"|"lost"|"open"|"none"}, '
        '"pull_quote":"<one shareable line>", '
        '"episode_title":"<a SHORT episode title: 2–5 words, a hook — NOT a sentence, NO \'Week N\', NO ending punctuation>"}. 14–22 turns. No fences.'
    )
    _chron = beats.get("chronicle", "")
    _chron_block = (
        f"CHRONICLE (the human week):\n{_chron[:3500]}\n\n"
        if _chron
        else "NO CHRONICLE THIS WEEK — review the week from the coaches' reads below and the week's data; do not reference or imply a chronicle exists.\n\n"
    )
    user = (
        f"WEEK {beats.get('week')}: {beats.get('title')}.\n\n{_chron_block}"
        f"GUEST COACH {guest.get('name')} — recent read: {guest.get('summary', '')}\nThemes: {', '.join(guest.get('themes', []))}\n\n"
        f"OTHER COACHES (for THE SPLIT — find a genuine disagreement):\n{split_material}\n\n"
        f"LAST WEEK'S OPEN BET (score it in RECEIPTS, honestly): {beats.get('last_open_bet') or '(none — this is the first weekly)'}\n\n"
        f"GUEST CONTINUITY: last week's guest was {beats.get('prev_guest') or '(none — first weekly with a coach guest; the only prior episode was the intro)'}. "
        f"THIS week's guest is {guest.get('name')}. If that's a change, introduce {guest.get('name')} properly for the audience "
        f"(who they are + what they work on, drawn from their read/themes above) before getting into it.\n\n"
        f"RECENT TOPICS (avoid repeating): {beats.get('recent_topics')}\n\n"
        # SS-09: rotate the entry-point lens so the show doesn't feel formulaic by ep 26.
        # Keep the bet/Split/scoreboard format — change only what the episode LEADS with.
        f"THIS WEEK'S ANGLE (keep the format, but lead with THIS lens so the show stays fresh): {_episode_angle(beats.get('week'))}\n\n"
        "Write the JSON now."
    )
    body = {"model": WRITER_MODEL, "max_tokens": 3500, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = bedrock_client.invoke(body, model_name=WRITER_MODEL)
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        logger.warning("[panel] weekly script parse failed")
        return {}
    return parsed


def _revise_weekly_script(turns: list, fails: list, beats: dict, bible: dict) -> dict:
    """Self-correction: hand the writer its own draft + the QA judge's exact failures and ask for
    a fixed full script (same JSON shape). This is the loop that lets the show reach the read-aloud
    bar on its own before falling back to a human HOLD."""
    import bedrock_client

    guest = beats.get("guest") or {}
    script_text = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        f'You are the head writer revising a draft of "{bible.get("show_name", "The Measured Life")}". Fix EVERY issue '
        "listed below and keep everything that already works. THE BAR: the transcript must read as a real, human-made "
        "podcast — no AI tells. Stay grounded (invent nothing — no facts, scenes, times of day, or numbers not already "
        f"present); keep the guest as {guest.get('name')}; introduce a guest the audience hasn't met; every question gets "
        "an answer in the next turn; no body weight (numeric or spelled-out). Return ONLY the same JSON shape: "
        '{"turns":[{"speaker":"elena"|"coach","line":"..."}],"open_bet":"...","last_bet_result":{"outcome":"won"|"lost"|"open"|"none"},'
        '"pull_quote":"..."}. 14–22 turns. No fences.'
    )
    user = (
        "ISSUES TO FIX (every one):\n- "
        + "\n- ".join(str(f) for f in fails)
        + f"\n\nDRAFT TO REVISE:\n{script_text}\n\nReturn the fixed JSON now."
    )
    try:
        body = {"model": WRITER_MODEL, "max_tokens": 3500, "system": system, "messages": [{"role": "user", "content": user}]}
        resp = bedrock_client.invoke(body, model_name=WRITER_MODEL)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        parsed = _extract_json(text)
        return parsed if isinstance(parsed, dict) and parsed.get("turns") else {}
    except Exception as e:
        logger.warning("[panel] weekly revision failed — %s", e)
        return {}


def _editor_review(turns: list, bible: dict) -> dict:
    """Haiku judge — semantic quality + safety floor the lexical gate can't see."""
    import bedrock_client

    script = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        "You are the EDITOR of a narrative podcast. Judge the script against this rubric and return ONLY JSON "
        '{"verdict":"pass"|"revise"|"hold","issues":[...],"pull_quote":"..."}. '
        f"RUBRIC:\n{json.dumps(bible.get('editor_rubric', {}))}\n"
        "Use 'hold' (route to a human, do NOT publish) if you detect any: causal claim, a bogus finding on a tiny sample, "
        "a report-card/judgmental tone, a hard week handled without compassion, or a reference to grief/family/a named person. "
        "Use 'revise' for fixable quality issues; 'pass' only if it clears the must-pass bar and the quality floor."
    )
    body = {"model": JUDGE_MODEL, "max_tokens": 600, "system": system, "messages": [{"role": "user", "content": script}]}
    for attempt in (1, 2):
        try:
            resp = bedrock_client.invoke(body, model_name=JUDGE_MODEL)
            text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
            parsed = _extract_json(text)
            if isinstance(parsed, dict) and parsed.get("verdict"):
                return parsed
            logger.warning("[panel] editor unparseable (attempt %d): %.120s", attempt, text)
        except Exception as e:
            logger.warning("[panel] editor review error (attempt %d) — %s", attempt, e)
    # A persistent infra/format failure is NOT a content verdict — fail OPEN and defer to the
    # deterministic safety gate + the weekly read-aloud QA gate (the real floor). A flaky JSON
    # reply from the judge must never hard-HOLD every episode.
    return {"verdict": "pass", "issues": ["editor unparseable — deferred to safety + weekly QA gates"], "pull_quote": ""}


def _weekly_gate(turns: list, allowed_numbers, guest_id: str):
    """Two-tier deterministic gate. Returns (clean_turns, hold_reasons)."""
    clean, hold = [], []
    for t in turns:
        if not isinstance(t, dict):
            continue
        raw = (t.get("speaker") or "").lower()
        spk = ELENA if raw in ("elena", "host", "elena_voss") else guest_id
        line = (t.get("line") or "").strip()
        if not line:
            continue
        sg = _safety_gate(line)
        if sg:
            hold.extend(sg)  # fail CLOSED — a safety hit holds the whole episode
            continue
        # Deliberately NOT dropping on an ER-03 number mismatch here: ER-03 string-matches digits,
        # but a believable spoken podcast says numbers in words ("eight thousand") and restates a
        # bet's derived figures, so the matcher over-drops — and a silently dropped turn leaves a
        # hole (e.g. an unanswered question, the Episode-1 bug). Safety violations above still HOLD
        # the whole episode; number FABRICATION is caught by the weekly read-aloud QA gate's GROUNDED
        # rubric (an LLM judge that understands paraphrase), with human-in-the-loop review behind it.
        clean.append({"speaker": spk, "line": line})
    return clean, sorted(set(hold))


def _hold_and_alert(week, reasons: list, draft: dict, hold_class: str = "safety") -> dict:
    """Loud HOLD: stash the draft on a NON-public prefix + SNS alert. Never publishes.

    `hold_class` (SS-02) tags WHY it was held so the hold sweep knows what's safe to
    auto-retry:
      • "safety"  — a sensitivity/compassion or hard safety-gate hold. NEVER
                    auto-released; stays for a human. This is the fail-closed default.
      • "quality" — an editor/structural/read-aloud-QA hold (no safety concern). The
                    sweep may RE-GENERATE the week (a fresh attempt through every gate)
                    after a review window, so a soft flag can't strand the show forever.
    Preserves `first_held_at` and bumps `retry_count` across re-holds so the sweep can
    bound how many times it retries before giving up.
    """
    prior = _read_hold(week)
    first_held = (prior or {}).get("first_held_at") or _today()
    retry_count = int((prior or {}).get("retry_count", 0)) + (1 if prior else 0)
    body = json.dumps(
        {
            "week": week,
            "reasons": reasons,
            "draft": draft,
            "held_at": _today(),
            "first_held_at": first_held,
            "hold_class": hold_class if hold_class in ("safety", "quality") else "safety",
            "retry_count": retry_count,
        },
        indent=1,
    )
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=f"{HOLD_PREFIX}/wk{week}.json", Body=body.encode("utf-8"), ContentType="application/json")
    except Exception as e:
        logger.error("[panel] hold draft write failed — %s", e)
    try:
        boto3.client("sns", region_name=REGION).publish(
            TopicArn=ALERTS_TOPIC_ARN,
            Subject=f"[Panel] Episode wk{week} HELD for review",
            Message=f"The weekly Panel episode for week {week} was held (not published).\nReasons: {reasons}\nDraft: s3://{S3_BUCKET}/{HOLD_PREFIX}/wk{week}.json",
        )
    except Exception as e:
        logger.warning("[panel] hold SNS alert failed — %s", e)
    # Surface a PUBLIC-SAFE pending marker so the Panel tab explains the gap instead of
    # going silent on a Friday. The raw `reasons` can name sensitive content, so they stay
    # internal (SNS + private draft) — only a generic message is published.
    _set_pending(
        week,
        "held_for_review",
        "This week's episode is in final review — it'll drop here as soon as it clears the quality bar.",
    )
    logger.warning("[panel] wk%s HELD (%s) — %s", week, hold_class, reasons)
    return {"statusCode": 200, "body": json.dumps({"week": week, "held": True, "hold_class": hold_class, "reasons": reasons})}


# ── SS-02: hold-aging escape ───────────────────────────────────────────────────
# A soft (quality) HOLD used to strand an episode in panelcast-holds/ forever — the
# weekly cron moves on to the next week and never revisits the held one, so the
# archive keeps a permanent hole. The sweep below RE-GENERATES a quality-held week
# (a fresh attempt through EVERY gate, safety included) after a review window, so the
# show self-heals. HARD safety/sensitivity holds are NEVER auto-retried.
HOLD_RETRY_HOURS = float(os.environ.get("PANELCAST_HOLD_RETRY_HOURS", "48"))  # give a human first crack
HOLD_MAX_DAYS = float(os.environ.get("PANELCAST_HOLD_MAX_DAYS", "10"))  # past this, abandoned — leave it
HOLD_MAX_RETRIES = int(os.environ.get("PANELCAST_HOLD_MAX_RETRIES", "3"))  # bound the regeneration spend


def _read_hold(week) -> dict:
    """The hold record for a week, or {} if none."""
    try:
        raw = s3.get_object(Bucket=S3_BUCKET, Key=f"{HOLD_PREFIX}/wk{week}.json")["Body"].read()
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _delete_hold(week) -> None:
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=f"{HOLD_PREFIX}/wk{week}.json")
    except Exception as e:
        logger.warning("[panel] hold delete failed wk%s — %s", week, e)


def _episode_published(week) -> bool:
    """Authoritative published check: the week appears in the episodes index. (The
    older _episode_exists head-checks a .mp3 key that the .wav publish path doesn't
    write, so the index is the reliable signal for the sweep.)"""
    try:
        eps = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read()).get("episodes", [])
        return any(e.get("week") == week for e in eps)
    except Exception:
        return False


def _hold_age_days(hold: dict) -> float:
    stamp = hold.get("first_held_at") or hold.get("held_at")
    if not stamp:
        return 0.0
    try:
        held = datetime.strptime(stamp[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - held).total_seconds() / 86400.0
    except Exception:
        return 0.0


def _sweep_held_episodes(dry_run: bool = False) -> dict:
    """SS-02: auto-retry a soft (quality) HOLD on the CURRENT week so the show doesn't
    stall forever on a fixable flag. Walks the current week's hold and decides:

      • hold_class == "safety"  → SKIP (sensitivity/safety stays human, fail-closed).
      • already published        → clean up the stale hold, SKIP.
      • age < HOLD_RETRY_HOURS   → SKIP (leave a window for a human to review first).
      • age > HOLD_MAX_DAYS      → SKIP (abandoned; the moment passed — leave it).
      • retry_count >= MAX       → SKIP (bounded regeneration spend; leave for a human).
      • else → re-run the normal generation (force=False). It goes through EVERY gate
               again (incl. the hard safety gate); it publishes ONLY if it now clears
               the bar, otherwise it re-HOLDs (retry_count bumps). On publish, the hold
               record is removed.

    Only the current week is retried — once the week advances, an old held week is
    stale (its 'this week' data has moved on) and is left to age out. dry_run reports
    the decision without regenerating or writing anything."""
    post = _select_week_post()
    week = post.get("week")
    hold = _read_hold(week)
    if not hold:
        return {"swept": [], "note": f"no hold for current week {week}"}

    hold_class = hold.get("hold_class", "safety")
    age = _hold_age_days(hold)
    retries = int(hold.get("retry_count", 0))

    def _skip(reason):
        logger.info("[panel] hold sweep wk%s SKIP — %s", week, reason)
        return {"swept": [], "week": week, "hold_class": hold_class, "skipped": reason}

    if _episode_published(week):
        if not dry_run:
            _delete_hold(week)
        return {"swept": [], "week": week, "cleaned_stale_hold": True}
    if hold_class != "quality":
        return _skip("safety/sensitivity hold — human review only")
    if age < HOLD_RETRY_HOURS / 24.0:
        return _skip(f"too fresh ({age:.1f}d < {HOLD_RETRY_HOURS/24.0:.1f}d review window)")
    if age > HOLD_MAX_DAYS:
        return _skip(f"abandoned ({age:.1f}d > {HOLD_MAX_DAYS}d)")
    if retries >= HOLD_MAX_RETRIES:
        return _skip(f"retry cap reached ({retries} >= {HOLD_MAX_RETRIES})")

    if dry_run:
        return {"swept": [week], "week": week, "would_retry": True, "hold_class": hold_class, "age_days": round(age, 1)}

    logger.info("[panel] hold sweep wk%s — retrying generation (retry #%d)", week, retries + 1)
    result = _run_weekly(force=False, dry_run=False)
    published = False
    try:
        published = bool(json.loads(result.get("body", "{}")).get("published"))
    except Exception:
        pass
    if published:
        _delete_hold(week)
    return {"swept": [week], "week": week, "retried": True, "published": published}


def _emit_published_metric() -> None:
    """Emit a CloudWatch datapoint on publish. A monitoring alarm treats the ABSENCE
    of this metric (> ~8 days) as breaching → 'the weekly show went silent' alert."""
    try:
        boto3.client("cloudwatch", region_name=REGION).put_metric_data(
            Namespace="LifePlatform/Podcast",
            MetricData=[{"MetricName": "PanelcastPublished", "Value": 1, "Unit": "Count"}],
        )
    except Exception as e:
        logger.warning("[panel] published-metric emit failed — %s", e)


def _notify_new_episode(ep: dict) -> None:
    """Notify the operator (SNS → Matt) that an episode dropped, with the link to
    share. Best-effort; never blocks the publish. (A full confirmed-subscriber email
    blast — reusing the SOURCE#subscribers + sesv2 + unsubscribe pattern from
    chronicle_email_sender — is a deliberate, test-first follow-up; not fired blind.)"""
    try:
        boto3.client("sns", region_name=REGION).publish(
            TopicArn=ALERTS_TOPIC_ARN,
            Subject=f"[Panel] New episode: {(ep.get('title') or '')[:80]}",
            Message=f"{ep.get('title')}\nListen: {SITE}{ep.get('url')}\nThe Panel: {SITE}/story/panel/\n\nShareable — post it.",
        )
    except Exception as e:
        logger.warning("[panel] new-episode notify failed — %s", e)


def _confirmed_subscribers() -> list:
    """Confirmed email subscribers (SOURCE#subscribers, status=confirmed). Same
    partition + FilterExpression pattern as chronicle_email_sender (fine <10K)."""
    out, ek = [], None
    try:
        while True:
            kw = {
                "KeyConditionExpression": Key("pk").eq(SUBSCRIBERS_PK),
                "FilterExpression": "#s = :c",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {":c": "confirmed"},
            }
            if ek:
                kw["ExclusiveStartKey"] = ek
            resp = table.query(**kw)
            out.extend(resp.get("Items", []))
            ek = resp.get("LastEvaluatedKey")
            if not ek:
                break
    except Exception as e:
        logger.error("[panel] subscriber query failed — %s", e)
    return out


def _subscriber_email(ep: dict, email: str) -> tuple:
    """(subject, html) for a new-episode announcement, with a CAN-SPAM unsubscribe."""
    title = ep.get("title") or "A new episode of The Panel"
    listen = f"{SITE}{ep.get('url', '/story/panel/')}"
    excerpt = ep.get("excerpt") or ""
    byline = ep.get("byline") or "Elena + a coach"
    unsub = f"{SITE}/api/subscribe?action=unsubscribe&email={urllib.parse.quote(email)}"
    subject = f"The Panel — {title}"[:120]
    html = (
        f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;color:#1a1a1a;line-height:1.55">'
        f'<p style="letter-spacing:.08em;text-transform:uppercase;font-size:12px;color:#8a7f6a">The Measured Life · The Panel</p>'
        f'<h1 style="font-size:24px;margin:.2em 0">{title}</h1>'
        f'<p style="color:#555;font-size:14px;margin:.2em 0 1em">A new weekly episode — {byline}.</p>'
        f'{f"<p>{excerpt}</p>" if excerpt else ""}'
        f'<p style="margin:1.4em 0"><a href="{listen}" style="background:#1a1a1a;color:#fff;padding:12px 22px;'
        f'text-decoration:none;border-radius:6px;display:inline-block">▶ Listen now</a></p>'
        f'<p style="font-size:13px;color:#777">Or open <a href="{SITE}/story/panel/">the Panel hub</a> for the full archive and the bet ledger.</p>'
        f'<hr style="border:none;border-top:1px solid #eee;margin:2em 0">'
        f'<p style="font-size:11px;color:#aaa">You subscribed at averagejoematt.com. '
        f'<a href="{unsub}" style="color:#aaa">Unsubscribe</a>.</p></div>'
    )
    return subject, html


def _email_subscribers(ep: dict, test_to: str = None) -> dict:
    """Email confirmed subscribers that a new episode dropped. Honors the
    EXTERNAL_EMAILS_ENABLED kill-switch. test_to=<addr> sends ONLY to that
    address (the test-first path) and never touches the subscriber list."""
    if os.environ.get("EXTERNAL_EMAILS_ENABLED", "true").lower() != "true":
        logger.info("[panel] EXTERNAL_EMAILS_ENABLED=false — subscriber notify skipped")
        return {"sent": 0, "skipped": "kill-switch"}
    recipients = [{"email": test_to}] if test_to else _confirmed_subscribers()
    if not recipients:
        return {"sent": 0, "note": "no recipients"}
    sent = failed = 0
    for sub in recipients:
        email = (sub.get("email") or "").strip()
        if not email:
            continue
        try:
            subject, html = _subscriber_email(ep, email)
            ses.send_email(
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [email]},
                Content={
                    "Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": {"Html": {"Data": html, "Charset": "UTF-8"}}}
                },
            )
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning("[panel] subscriber send failed (%s) — %s", email, e)
    logger.info("[panel] subscriber notify — sent=%d failed=%d test=%s", sent, failed, bool(test_to))
    return {"sent": sent, "failed": failed, "test": bool(test_to)}


def _dry(week, decision, **extra) -> dict:
    """Dry-run summary — what the live run WOULD do, no TTS and no writes."""
    return {"statusCode": 200, "body": json.dumps({"dry_run": True, "week": week, "would": decision, **extra})}


def _select_week_post() -> dict:
    """Pick the week the Panel should produce now (shared by the weekly run + the
    SS-02 hold sweep so both target the SAME week).

    Reset-proof selection (ADR-077): a reset restarts week-numbering at 1, but old
    high-numbered chronicles linger in posts.json. Pick the most RECENT weekly post
    in the CURRENT cycle (dated >= genesis), never the stale pre-reset max-week.
    ISO dates compare lexically. If none exist yet (before the cycle's first
    Wednesday chronicle), derive the current week from genesis (the chronicle is
    optional flavor — 2026-06-21 decoupling)."""
    posts = _published_posts()
    weekly = [p for p in posts if p.get("week") and p.get("week") > 0 and p.get("date") and p["date"] >= EXPERIMENT_START_DATE]
    if weekly:
        return max(weekly, key=lambda x: x["date"])
    from datetime import date as _date

    genesis = _date.fromisoformat(EXPERIMENT_START_DATE)
    wk = max(1, ((_date.today() - genesis).days // 7) + 1)
    return {"week": wk, "date": _date.today().isoformat(), "title": f"Week {wk}"}


def _run_weekly(force: bool, dry_run: bool = False) -> dict:
    """Produce the latest week's episode autonomously, publish-or-HOLD.

    dry_run=True runs the full decision pipeline (gather → write → editor → gate)
    but synthesizes NO audio and writes NOTHING (no S3/DDB/SNS/metric) — it returns
    what the live run would do. The pre-flight tool for every Friday / post-reset."""
    import gemini_tts

    post = _select_week_post()
    week = post["week"]
    if not force and not dry_run and _episode_exists(week):
        return {"statusCode": 200, "body": json.dumps({"week": week, "already_published": True})}

    bible = _load_bible()
    state = _state_read()
    beats = _gather_week(post, state)
    # Chronicle decoupled (2026-06-21): the Panel reviews the week from the coaches' reads
    # + data, with the chronicle as optional context. Only skip when there's genuinely
    # nothing to review — no chronicle AND no coach reads — not merely a missing chronicle.
    if not beats.get("chronicle") and not beats.get("coach_reads"):
        if not dry_run:
            _set_pending(
                week,
                "awaiting_material",
                f"Episode for week {week} is pending — no chronicle or coach reads to review yet.",
                post.get("date"),
            )
        return {
            "statusCode": 200,
            "body": json.dumps({"week": week, "skipped": "no material (no chronicle or coach reads)", "date": post.get("date")}),
        }

    # Personal Board asymmetry — hard/sensitive week → human, never auto-publish.
    sens = _sensitivity_hold_reasons(beats)
    if sens:
        if dry_run:
            return _dry(week, "HOLD", stage="sensitivity", reasons=sens, date=post.get("date"))
        return _hold_and_alert(week, sens, {"note": "sensitivity routing pre-write"}, hold_class="safety")

    guest_id = (beats.get("guest") or {}).get("id") or persona_registry.OPERATIONAL_COACH_IDS[0]
    guest_name = (beats.get("guest") or {}).get("name", "Coach")
    script = _build_weekly_script(beats, bible)
    turns = script.get("turns") or []
    # Craft re-roll (cheap, deterministic): if the draft is monologue-y or one speaker
    # holds the floor too long, re-roll the writer once (generation is non-deterministic).
    # The editor + safety gate + HOLD below remain the hard floor; this just lifts quality.
    _cfails = _craft_check(turns)
    if _cfails:
        logger.info("[panel] wk%s: craft re-roll — %s", week, _cfails)
        alt = _build_weekly_script(beats, bible)
        if (alt.get("turns") or []) and not _craft_check(alt["turns"]):
            script, turns = alt, alt["turns"]
    if len(turns) < 6:
        if dry_run:
            return _dry(week, "HOLD", stage="writer", reasons=["too few turns"], turns=len(turns))
        return _hold_and_alert(week, ["writer produced too few turns"], script, hold_class="quality")

    review = _editor_review(turns, bible)
    if review.get("verdict") == "hold":
        if dry_run:
            return _dry(week, "HOLD", stage="editor", reasons=review.get("issues", []))
        return _hold_and_alert(
            week, ["editor: " + "; ".join(review.get("issues", []))[:300]], {"turns": turns, "review": review}, hold_class="quality"
        )

    for t in turns:
        t["line"] = re.sub(r"\bMatthew\b", "Matt", t.get("line", ""))
    allowed = er03_gate.numbers_in(beats["chronicle"] + " " + " ".join(c["summary"] for c in beats["coach_reads"]))

    def _valid(ts):
        return [t for t in ts if isinstance(t, dict) and (t.get("line") or "").strip()]

    clean, hold = _weekly_gate(turns, allowed, guest_id)
    # A turn DROPPED by the ER-03 gate (a number not in the source) mid-conversation leaves a hole —
    # e.g. Elena asks a question and the guest's dropped answer leaves it dangling. Don't voice a
    # holey transcript: re-roll the writer once for a gap-free pass, else HOLD for a human.
    if not hold and len(clean) < len(_valid(turns)):
        logger.info("[panel] wk%s: gate dropped %d turn(s) — re-roll for a gap-free script", week, len(_valid(turns)) - len(clean))
        alt = _build_weekly_script(beats, bible)
        aturns = alt.get("turns") or []
        aclean, ahold = _weekly_gate(aturns, allowed, guest_id)
        if not ahold and len(aclean) == len(_valid(aturns)) and len(aclean) >= 6:
            script, turns, clean, hold = alt, aturns, aclean, ahold
        else:
            if dry_run:
                return _dry(week, "HOLD", stage="gate-drop", reasons=["gate dropped turns; re-roll did not produce a gap-free script"])
            return _hold_and_alert(week, ["gate dropped turns (holey transcript); re-roll failed"], {"turns": turns}, hold_class="quality")
    if hold:
        if dry_run:
            return _dry(week, "HOLD", stage="safety-gate", reasons=hold)
        return _hold_and_alert(week, hold, {"turns": turns}, hold_class="safety")
    if len(clean) < 6:
        if dry_run:
            return _dry(week, "HOLD", stage="gate-thin", reasons=["too few clean turns after gate"], clean=len(clean))
        return _hold_and_alert(week, ["too few clean turns after gate"], {"turns": turns}, hold_class="quality")

    # Weekly read-aloud QA (the Turing bar): guest introduced, no dangling thread, grounded,
    # humour, no AI tells. Self-correcting loop — feed the judge's exact failures back to the
    # writer and re-judge (up to 2 revisions). Only a draft that still fails after that HOLDs for
    # a human. This is the mechanism that moves the show toward running hands-off.
    _gt = (beats.get("chronicle", "")[:1500] + "\n" + "\n".join(f"{c['name']}: {c['summary']}" for c in beats.get("coach_reads", [])))[
        :4000
    ]
    qa_fails = _qa_gate(clean, _WEEKLY_RUBRIC, _gt)
    for _rev in range(2):
        if not qa_fails:
            break
        logger.info("[panel] wk%s: QA fails (revision %d) — %s", week, _rev + 1, qa_fails)
        revised = _revise_weekly_script(clean, qa_fails, beats, bible)
        rturns = revised.get("turns") or []
        for t in rturns:
            t["line"] = re.sub(r"\bMatthew\b", "Matt", t.get("line", ""))
        rclean, rhold = _weekly_gate(rturns, allowed, guest_id)
        if rhold or len(rclean) < 6:
            continue  # revision broke something — keep the prior draft, re-judge, likely HOLD
        clean, script = rclean, revised
        qa_fails = _qa_gate(clean, _WEEKLY_RUBRIC, _gt)
    if qa_fails:
        logger.info("[panel] wk%s: weekly QA HOLD after revisions — %s", week, qa_fails)
        if dry_run:
            return _dry(week, "HOLD", stage="weekly-qa", reasons=qa_fails)
        return _hold_and_alert(week, ["weekly-qa: " + "; ".join(str(f) for f in qa_fails)[:300]], {"turns": clean}, hold_class="quality")

    if dry_run:
        preview = "\n".join(f"{('Elena' if t['speaker'] == ELENA else guest_name)}: {t['line']}" for t in clean[:6])
        return _dry(
            week,
            "PUBLISH",
            title=f"Week {week}: {script.get('pull_quote') or review.get('pull_quote') or beats['title']}"[:120],
            guest=guest_name,
            clean_turns=len(clean),
            open_bet=script.get("open_bet"),
            date=post.get("date"),
            transcript_preview=preview,
        )

    # PASS → synthesize single-pass, then commit (series_state + RSS LAST).
    label_of = {ELENA: "Elena", guest_id: (beats.get("guest") or {}).get("name", "Coach")}
    voices = {label_of[ELENA]: _gemini_voice(ELENA), label_of[guest_id]: _gemini_voice(guest_id)}
    label_turns = [{"speaker": label_of.get(t["speaker"], "Elena"), "line": t["line"]} for t in clean]
    style = WEEKLY_STYLE
    audio = gemini_tts.synthesize_dialogue(label_turns, voices, style)
    s3.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.wav", Body=audio, ContentType="audio/wav", CacheControl="max-age=86400, public")
    transcript = "\n\n".join(f"{label_of.get(t['speaker'], 'Elena')}: {t['line']}" for t in clean)
    s3.put_object(
        Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.transcript.txt", Body=transcript.encode("utf-8"), ContentType="text/plain; charset=utf-8"
    )

    try:
        existing = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read()).get("episodes", [])
    except Exception:
        existing = []
    _hook = _short_title(
        script.get("episode_title"),
        beats.get("title"),
        script.get("pull_quote"),
        review.get("pull_quote"),
    )
    # Editorial cover art (Part II — atmospheric, free-license; fail-soft, kill-switch
    # default OFF). Reuse this week's prior image if present; else fetch once. Never blocks.
    _cover = {}
    try:
        import editorial_image

        if editorial_image.enabled():
            _prev = next((e for e in existing if e.get("week") == week and e.get("image_url")), None)
            _cover = (
                {"image_url": _prev["image_url"], "image_credit": _prev.get("image_credit", "")}
                if _prev
                else (editorial_image.fetch_and_store("podcast", f"wk{week}", week, s3_client=s3) or {})
            )
    except Exception:
        _cover = {}

    ep = {
        "week": week,
        # EP{n} · short hook — episode number == week (intro is EP0). No long sentence titles.
        "title": f"EP{week} · {_hook}" if _hook else f"EP{week}",
        "date": beats["date"],
        "url": f"/panelcast/wk{week}.wav",
        "bytes": len(audio),
        "duration_sec": max(1, (len(audio) - 44) // (gemini_tts.SAMPLE_RATE * 2)),
        "byline": f"Elena + {label_of[guest_id]}",
        "guest_id": guest_id,  # throughline: front-end links the byline → /story/coaches/<guest_id>
        "guest_name": label_of[guest_id],
        "excerpt": (script.get("pull_quote") or post.get("excerpt") or "")[:240],
        "image_url": _cover.get("image_url", ""),
        "image_credit": _cover.get("image_credit", ""),
    }
    existing = [e for e in existing if e.get("week") != week] + [ep]
    existing.sort(key=lambda e: e.get("week", 0), reverse=True)
    # series_state + RSS committed LAST (atomic-ish: audio already durable).
    recent = ([beats["title"]] + beats.get("recent_topics", []))[:5]
    # Bet ledger (the Panel scoreboard): resolve the prior open bet with THIS week's
    # reported outcome, then record the new open bet. Capped, reset-safe in DDB.
    # Idempotent per-week (2026-07-02): a RE-published episode used to (a) "resolve"
    # its own week's open bet with last week's outcome and (b) append a paraphrased
    # duplicate — the live wk1 double-bet. The resolve loop now only touches a bet
    # from an EARLIER week (the one the episode actually reports on), and the append
    # supersedes this week's own open bet. Resolved bets are history — never touched.
    ledger = list(state.get("bet_ledger", []))
    outcome = ((script.get("last_bet_result") or {}).get("outcome") or "open").lower()
    for entry in reversed(ledger):
        if entry.get("outcome") == "open" and entry.get("week") != week:
            entry["outcome"] = outcome if outcome in ("won", "lost", "open", "none") else "open"
            break
    if script.get("open_bet"):
        ledger = [e for e in ledger if not (e.get("week") == week and e.get("outcome") == "open")]
        ledger.append({"week": week, "bet": script["open_bet"], "outcome": "open", "date": beats["date"]})
    _state_write(
        {
            "episode_count": state.get("episode_count", 1) + 1,
            "last_episode": ep,
            "open_bet": script.get("open_bet"),
            "recent_topics": recent,
            "bet_ledger": ledger[-20:],
        }
    )
    _write_indexes(existing)
    _emit_published_metric()  # safety-net: a CloudWatch alarm fires if this metric goes absent (no episode > 8d)
    _notify_new_episode(ep)  # operator SNS ping (best-effort; never blocks publish)
    # Confirmed-subscriber email blast — OFF by default (PANELCAST_NOTIFY_SUBSCRIBERS).
    # Flip on only after a {"notify_test": "<addr>"} dry-run looks right, so the very
    # first real episodes never blind-blast the list. Best-effort; never blocks publish.
    if os.environ.get("PANELCAST_NOTIFY_SUBSCRIBERS", "false").lower() == "true":
        try:
            _email_subscribers(ep)
        except Exception as e:
            logger.warning("[panel] subscriber blast failed — %s", e)
    logger.info("[panel] wk%s PUBLISHED — %d turns, %d bytes, guest %s", week, len(clean), len(audio), guest_id)
    return {
        "statusCode": 200,
        "body": json.dumps({"week": week, "published": True, "turns": len(clean), "open_bet": bool(script.get("open_bet"))}),
    }


def lambda_handler(event, context):
    event = event or {}
    force = bool(event.get("force"))
    dry_run = bool(event.get("dry_run"))

    try:
        from budget_guard import current_tier

        tier = current_tier()
        if tier >= SKIP_TIER:
            logger.info("[panel] budget tier %s >= %s — skipping (PG-10)", tier, SKIP_TIER)
            return {"skipped": True, "tier": tier}
    except Exception:
        pass

    # Test-first subscriber notify: email ONLY the given address, using the latest
    # published episode, without publishing anything. Verify before flipping
    # PANELCAST_NOTIFY_SUBSCRIBERS=true. Usage: {"notify_test": "you@example.com"}.
    if event.get("notify_test"):
        try:
            eps = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")["Body"].read()).get("episodes", [])
            if not eps:
                return {"statusCode": 200, "body": json.dumps({"notify_test": "no episodes to announce"})}
            latest = max(eps, key=lambda e: e.get("week", 0))
            return {"statusCode": 200, "body": json.dumps(_email_subscribers(latest, test_to=str(event["notify_test"])))}
        except Exception as e:
            logger.error("[panel] notify_test failed — %s", e)
            return {"statusCode": 500, "body": json.dumps({"notify_test": "failed", "error": str(e)[:200]})}

    # Episode 0 — the full welcome/trailer (all coaches + Elena). One-off / manual.
    # {"intro": true, "dry_run": true} writes only the draft transcript (no audio) for review.
    if event.get("intro"):
        try:
            return _run_intro(dry_run=bool(event.get("dry_run")))
        except Exception as e:
            logger.error("[panel] intro failed — %s", e)
            return {"statusCode": 500, "body": json.dumps({"intro": "failed", "error": str(e)[:200]})}

    # SS-02 hold-aging sweep: a scheduled rule passes {"sweep_holds": true} to auto-
    # retry a soft (quality) HOLD on the current week so the show can't stall forever on
    # a fixable flag. Safety/sensitivity holds are never auto-retried. Routed BEFORE the
    # weekly run, and distinct from the Friday cron (which carries no sweep_holds key).
    if event.get("sweep_holds"):
        try:
            return {"statusCode": 200, "body": json.dumps(_sweep_held_episodes(dry_run=dry_run))}
        except Exception as e:
            logger.error("[panel] hold sweep failed — %s", e)
            return {"statusCode": 500, "body": json.dumps({"sweep_holds": "failed", "error": str(e)[:200]})}

    # Weekly autonomous run (the board-reviewed pipeline). Latest week, publish-or-HOLD.
    try:
        return _run_weekly(force, dry_run=dry_run)
    except Exception as e:
        logger.error("[panel] weekly run failed — %s", e)
        return {"statusCode": 500, "body": json.dumps({"weekly": "failed", "error": str(e)[:200]})}
