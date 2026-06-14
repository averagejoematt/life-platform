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
# (the LLM keeps preferring a punchy hook over literally naming herself).
INTRO_COLD_OPEN = (
    "I'm Elena Voss. I'm the journalist embedded in this experiment — equal parts skeptical and hopeful, "
    "here to document, honestly and from the inside, whether all this technology can actually change one real life."
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
        "  - Elena's VERY FIRST line must include the words \"I'm Elena Voss\" and a sentence on who she is and why she's drawn "
        "to this — she speaks first, alone, before the guest is introduced or speaks.\n"
        "  - Before any hardship, Elena must establish WHO Matt is and why a complete STRANGER should care about him — an "
        "ordinary person who has done this before and genuinely succeeded (the high), so the fall lands. Meet the person and "
        "the stakes FIRST; do NOT open his section on the grief.\n"
        "  - THEN his honest story, IN THIS episode: the weight was the symptom not the problem, the coping mechanism, and "
        "'can a system catch what willpower can't?'. Do NOT defer it to a future episode.\n"
        "  - Elena must mention that she writes a WEEKLY chronicle and that this podcast runs alongside it.\n"
        "  - Work in the platform doors (Cockpit / Story / Evidence / Sources / Character) naturally.\n\n"
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


def _run_intro() -> dict:
    bible = _load_bible()
    # Numbers allowed by ER-03 = only those in the bible (it has essentially none →
    # this enforces "no invented numbers"). No elapsed-time/results context is fed.
    allowed = er03_gate.numbers_in(json.dumps(bible))
    turns = _gate_intro(_build_intro_script(bible), allowed)
    if len(turns) < 8:
        logger.warning("[panel] intro: too few clean turns (%d)", len(turns))
        return {"statusCode": 500, "body": json.dumps({"intro": "too few turns", "turns": len(turns)})}
    # Launch lock: the LLM won't reliably name Elena in line 1 — prepend a fixed,
    # warm cold-open so every cut opens with her named self-intro. And enforce "Matt"
    # (the model occasionally reverts to "Matthew").
    for t in turns:
        t["line"] = re.sub(r"\bMatthew\b", "Matt", t["line"])
    first = (turns[0]["line"] if turns else "").lower()
    if not ("i'm elena" in first or "i am elena" in first or "elena voss" in first):
        turns.insert(0, {"speaker": ELENA, "line": INTRO_COLD_OPEN})
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
        "duration_sec": max(1, (len(audio) - 44) // (gemini_tts.SAMPLE_RATE * 2)),  # WAV: 16-bit mono PCM
        "byline": "Elena + Dr. Eli Marsh",
        "excerpt": "Meet Elena, meet Matt, and meet the question this whole experiment is built to answer: can AI and your own data actually make a life better — or is it just over-optimization? The starting line.",
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
    return GEMINI_VOICE.get(persona_id, "Charon")


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
    }


def _sensitivity_hold_reasons(beats: dict) -> list:
    """Personal Board asymmetry: hard/sensitive weeks route to a human, never auto-publish."""
    reasons = []
    if _SENSITIVE_WEEK_RE.search(beats.get("chronicle", "")):
        reasons.append("sensitive-week (grief/low-mood/relapse signal in chronicle) — human review")
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
        f"{CONVO_DIRECTIVE} "
        'OUTPUT ONLY JSON: {"turns":[{"speaker":"elena"|"coach","line":"..."}], "open_bet":"<the one new falsifiable bet for next week>", '
        '"pull_quote":"<one shareable line>"}. 14–22 turns. No fences.'
    )
    user = (
        f"WEEK {beats.get('week')}: {beats.get('title')}.\n\nCHRONICLE (the human week):\n{beats.get('chronicle', '')[:3500]}\n\n"
        f"GUEST COACH {guest.get('name')} — recent read: {guest.get('summary', '')}\nThemes: {', '.join(guest.get('themes', []))}\n\n"
        f"OTHER COACHES (for THE SPLIT — find a genuine disagreement):\n{split_material}\n\n"
        f"LAST WEEK'S OPEN BET (score it in RECEIPTS, honestly): {beats.get('last_open_bet') or '(none — this is the first weekly)'}\n\n"
        f"RECENT TOPICS (avoid repeating): {beats.get('recent_topics')}\n\nWrite the JSON now."
    )
    body = {"model": WRITER_MODEL, "max_tokens": 3500, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = bedrock_client.invoke(body, model_name=WRITER_MODEL)
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        logger.warning("[panel] weekly script parse failed")
        return {}
    return parsed


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
    try:
        resp = bedrock_client.invoke(body, model_name=JUDGE_MODEL)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        parsed = _extract_json(text)
        if isinstance(parsed, dict) and parsed.get("verdict"):
            return parsed
        raise ValueError("editor returned unparseable verdict")
    except Exception as e:
        logger.warning("[panel] editor review failed (treat as hold) — %s", e)
        return {"verdict": "hold", "issues": [f"editor error: {e}"], "pull_quote": ""}


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
        # Hard checks only (no fabricated numbers, no causal, no Matt-prefix). The
        # small-n hedge can't be a per-line rule — it over-drops conversational lines;
        # the editor (LLM judge) enforces hedging-on-findings with full context.
        ok, _r = er03_gate.er03_check(line, allowed_numbers=allowed_numbers, n=None)
        if ok:
            clean.append({"speaker": spk, "line": line})
    return clean, sorted(set(hold))


def _hold_and_alert(week, reasons: list, draft: dict) -> dict:
    """Loud HOLD: stash the draft on a NON-public prefix + SNS alert. Never publishes."""
    body = json.dumps({"week": week, "reasons": reasons, "draft": draft, "held_at": _today()}, indent=1)
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
    logger.warning("[panel] wk%s HELD — %s", week, reasons)
    return {"statusCode": 200, "body": json.dumps({"week": week, "held": True, "reasons": reasons})}


def _run_weekly(force: bool) -> dict:
    """Produce the latest week's episode autonomously, publish-or-HOLD."""
    import gemini_tts

    posts = _published_posts()
    weekly = [p for p in posts if p.get("week") and p.get("week") > 0 and p.get("date")]
    if not weekly:
        return {"statusCode": 200, "body": json.dumps({"weekly": "no published weeks yet"})}
    post = max(weekly, key=lambda x: x["week"])
    week = post["week"]
    if not force and _episode_exists(week):
        return {"statusCode": 200, "body": json.dumps({"week": week, "already_published": True})}

    bible = _load_bible()
    state = _state_read()
    beats = _gather_week(post, state)
    if not beats.get("chronicle"):
        return {"statusCode": 200, "body": json.dumps({"week": week, "skipped": "no chronicle yet"})}

    # Personal Board asymmetry — hard/sensitive week → human, never auto-publish.
    sens = _sensitivity_hold_reasons(beats)
    if sens:
        return _hold_and_alert(week, sens, {"note": "sensitivity routing pre-write"})

    guest_id = (beats.get("guest") or {}).get("id") or persona_registry.OPERATIONAL_COACH_IDS[0]
    script = _build_weekly_script(beats, bible)
    turns = script.get("turns") or []
    if len(turns) < 6:
        return _hold_and_alert(week, ["writer produced too few turns"], script)

    review = _editor_review(turns, bible)
    if review.get("verdict") == "hold":
        return _hold_and_alert(week, ["editor: " + "; ".join(review.get("issues", []))[:300]], {"turns": turns, "review": review})

    for t in turns:
        t["line"] = re.sub(r"\bMatthew\b", "Matt", t.get("line", ""))
    allowed = er03_gate.numbers_in(beats["chronicle"] + " " + " ".join(c["summary"] for c in beats["coach_reads"]))
    clean, hold = _weekly_gate(turns, allowed, guest_id)
    if hold:
        return _hold_and_alert(week, hold, {"turns": turns})
    if len(clean) < 6:
        return _hold_and_alert(week, ["too few clean turns after gate"], {"turns": turns})

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
    ep = {
        "week": week,
        "title": f"Week {week}: {script.get('pull_quote') or review.get('pull_quote') or beats['title']}"[:120],
        "date": beats["date"],
        "url": f"/panelcast/wk{week}.wav",
        "bytes": len(audio),
        "duration_sec": max(1, (len(audio) - 44) // (gemini_tts.SAMPLE_RATE * 2)),
        "byline": f"Elena + {label_of[guest_id]}",
        "excerpt": (script.get("pull_quote") or post.get("excerpt") or "")[:240],
    }
    existing = [e for e in existing if e.get("week") != week] + [ep]
    existing.sort(key=lambda e: e.get("week", 0), reverse=True)
    # series_state + RSS committed LAST (atomic-ish: audio already durable).
    recent = ([beats["title"]] + beats.get("recent_topics", []))[:5]
    _state_write(
        {
            "episode_count": state.get("episode_count", 1) + 1,
            "last_episode": ep,
            "open_bet": script.get("open_bet"),
            "recent_topics": recent,
        }
    )
    _write_indexes(existing)
    logger.info("[panel] wk%s PUBLISHED — %d turns, %d bytes, guest %s", week, len(clean), len(audio), guest_id)
    return {
        "statusCode": 200,
        "body": json.dumps({"week": week, "published": True, "turns": len(clean), "open_bet": bool(script.get("open_bet"))}),
    }


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

    # Weekly autonomous run (the board-reviewed pipeline). Latest week, publish-or-HOLD.
    try:
        return _run_weekly(force)
    except Exception as e:
        logger.error("[panel] weekly run failed — %s", e)
        return {"statusCode": 500, "body": json.dumps({"weekly": "failed", "error": str(e)[:200]})}
