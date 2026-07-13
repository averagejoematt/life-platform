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
from ai_context import build_experiment_phase_context, format_experiment_phase_context  # #1086: mandatory phase block
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


def _elena_host_state() -> str:
    """#537: the host reads from the same PERSONA#elena memory the chronicle
    writes — her editorial stance (receipts-gated) + a couple of open threads
    she may call back to on-air. Volatile → user turn. Fail-soft ""."""
    try:
        from boto3.dynamodb.conditions import Key as _Key

        bits = []
        st = table.get_item(Key={"pk": "PERSONA#elena", "sk": "STANCE#latest"}).get("Item") or {}
        if st.get("headline_stance") and not st.get("grounding_flag"):
            bits.append(f"Elena's current editorial read (her own, persistent): {str(st['headline_stance'])[:300]}")
        resp = table.query(
            KeyConditionExpression=_Key("pk").eq("PERSONA#elena") & _Key("sk").begins_with("THREAD#"),
            ScanIndexForward=False,
            Limit=20,
        )
        open_threads = [t for t in resp.get("Items", []) if t.get("status") == "open"][:2]
        if open_threads:
            bits.append(
                "Story threads Elena is carrying (she may call back to one): "
                + "; ".join(str(t.get("summary") or "")[:120] for t in open_threads)
            )
        return "\n".join(bits)
    except Exception as e:
        logger.warning("elena host state skipped: %s", e)
        return ""


def _build_script(week, title, chronicle_text, coach_id, coach_out, coach_name) -> list:
    import bedrock_client

    coach_block = ""
    if coach_out:
        coach_block = f"\n{coach_name}'s recent read: {coach_out['summary']}\nThemes: {', '.join(coach_out['themes']) or '(none)'}"
    # #537: the host carries her own memory — stance + threads from PERSONA#elena.
    elena_block = _elena_host_state()
    if elena_block:
        elena_block = f"\n{elena_block}"
    system = (
        "You write a short two-host podcast script reviewing one week of a public health experiment. "
        f"HOST is Elena Voss (embedded journalist). CO-HOST is {coach_name}, an AI coach. "
        'Output ONLY a JSON array of turns: [{"speaker":"elena"|"coach","line":"..."}]. '
        "8–14 turns, conversational and warm, Elena frames topics and asks, the coach reviews findings. "
        "If Elena's own editorial read or story threads are provided, let her voice them naturally — "
        "they are HER opinions and callbacks, never the coach's. "
        "Hard rules: correlative only (never claim causation); use only numbers present in the source; "
        "hedge — the data is early/small-sample; never open a line with 'Matt'; no preamble or JSON fences."
    )
    user = (
        f"Week {week}: {title}.\n\nThis week's chronicle:\n{chronicle_text[:4000]}{coach_block}{elena_block}\n\n"
        "Write the JSON dialogue array now."
    )
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


def _publish_episode_audio(week, wav_audio: bytes) -> dict:
    """Compress + PUT the episode audio (#1018): the Gemini WAV (24 kHz PCM) is encoded
    to spoken-word MP3 via audio_encode (lameenc-layer), fail-open to the raw WAV. Before
    encoding, the synthesized audio ident (intro jingle + fade-under + outro reprise,
    #1179/#1082) is mixed in at the raw-PCM stage — the ONE hook covering both episode 0
    and the weekly path. duration comes from the WAV header AFTER the mix (ident adds ~9s)."""
    import audio_encode

    try:  # #1179: mix the audio ident; mix_into_wav is fully fail-open (speech-only on error)
        from emails import panelcast_ident
    except ImportError:
        import panelcast_ident
    wav_audio = panelcast_ident.mix_into_wav(wav_audio)
    duration = max(1, audio_encode.wav_duration_sec(wav_audio))
    body, ext, mime = audio_encode.compress_wav(wav_audio)
    s3.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.{ext}", Body=body, ContentType=mime, CacheControl="max-age=86400, public")
    return {"url": f"/panelcast/wk{week}.{ext}", "bytes": len(body), "duration_sec": duration}


def _episode_exists(week) -> bool:
    # The weekly publisher writes wk{n}.mp3 (compressed since #1018; .wav before
    # that, and still the fail-open fallback). Check every extension ever
    # published so "already published" is never a false negative that
    # re-synthesizes a week (the .mp3-only check silently missed every .wav episode).
    for ext in ("mp3", "wav", "m4a"):
        try:
            s3.head_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/wk{week}.{ext}")
            return True
        except Exception:
            continue
    return False


def _xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 16:00:00 GMT")


# Podcast-standard feed metadata (#374). The feed is served at the stable viewer
# URL {SITE}/panelcast/feed.xml (S3 key generated/panelcast/feed.xml → CloudFront
# S3GeneratedOrigin). Cover art must be a square 1400–3000px image that resolves,
# or Apple/Spotify reject the feed — generated once to {PREFIX}/cover.jpg.
FEED_URL = f"{SITE}/panelcast/feed.xml"
COVER_URL = os.environ.get("PANELCAST_COVER_URL", f"{SITE}/panelcast/cover.jpg")
OWNER_NAME = "The Measured Life"
OWNER_EMAIL = os.environ.get("PANELCAST_OWNER_EMAIL", SENDER)
FEED_CATEGORY = "Health & Fitness"


def _hms(seconds) -> str:
    """iTunes duration as HH:MM:SS (the widest-compatible form)."""
    s = max(0, int(seconds or 0))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _enclosure_type(url: str) -> str:
    """MIME from the audio extension — episodes are .mp3 (compressed, #1018) with
    .wav as the fail-open fallback and in pre-#1018 history; a hardcoded
    audio/mpeg on a .wav enclosure is a validator failure."""
    u = (url or "").lower()
    if u.endswith(".mp3"):
        return "audio/mpeg"
    if u.endswith(".m4a") or u.endswith(".mp4"):
        return "audio/mp4"
    return "audio/wav"


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
    <itunes:summary>{_xml(e.get("excerpt") or e["title"])}</itunes:summary>
    <enclosure url="{SITE}{e["url"]}" length="{e.get("bytes", 0)}" type="{_enclosure_type(e["url"])}"/>
    <guid isPermaLink="false">measured-life-panel-wk{e["week"]}</guid>
    <pubDate>{_rfc822(e["date"])}</pubDate>
    <itunes:duration>{_hms(e.get("duration_sec"))}</itunes:duration>
    <itunes:episode>{int(e["week"])}</itunes:episode>
    <itunes:episodeType>full</itunes:episodeType>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{_xml(e.get("image_url") or COVER_URL)}"/>
  </item>"""
        for e in episodes
    )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>The Measured Life — The Panel</title>
  <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>
  <link>{SITE}/story/panel/</link>
  <description>A weekly two-host show: Elena Voss and a rotating AI coach review the week's data, findings, and themes from a public N=1 health experiment. AI voices, correlative, fact-anchored.</description>
  <language>en-us</language>
  <copyright>© averagejoematt</copyright>
  <itunes:author>The Measured Life</itunes:author>
  <itunes:summary>A weekly two-host show reviewing the week's data from a public N=1 health experiment. AI voices, correlative, fact-anchored.</itunes:summary>
  <itunes:type>episodic</itunes:type>
  <itunes:explicit>false</itunes:explicit>
  <itunes:owner>
    <itunes:name>{_xml(OWNER_NAME)}</itunes:name>
    <itunes:email>{_xml(OWNER_EMAIL)}</itunes:email>
  </itunes:owner>
  <itunes:image href="{_xml(COVER_URL)}"/>
  <itunes:category text="{_xml(FEED_CATEGORY)}"/>
  <image>
    <url>{_xml(COVER_URL)}</url>
    <title>The Measured Life — The Panel</title>
    <link>{SITE}/story/panel/</link>
  </image>
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
    wk*.mp3/.wav carries a 24h cache header, so without this the CDN serves the prior cut
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
# CONVO_DIRECTIVE (the shared conversational writer directive) moved to panelcast_scripts.py
# with the two builders that are its only consumers (#1182).
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


def _build_intro_script(bible: dict, zeitgeist: list | None = None) -> list:
    """Episode 0 as a two-person interview (builder in panelcast_scripts.py, #1182).
    `zeitgeist` (#1178): optional real headlines — an OPTIONAL TOPICAL COLOR block, omitted
    when empty. Episode 0 is EVERGREEN (#1182): _run_intro always passes an empty list."""
    return _pscripts.build_intro_script(bible, zeitgeist, _pscripts_deps())


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


# ── QA rigor — extracted to emails/panelcast_qa.py (god-module gate, 2026-07-12) ──
try:
    from emails.panelcast_qa import (  # noqa: F401 — re-exported for callers/tests
        _CHALLENGE_RE,
        _INTERROGATIVE_RE,
        _INTRO_RUBRIC,
        _QA_MAX_ATTEMPTS,
        _QA_MAX_CONSECUTIVE,
        _QA_MAX_CONSECUTIVE_INTRO,
        _QA_MAX_WORDS_PER_TURN,
        _WEEKLY_RUBRIC,
        _continuity_check,
        _craft_check,
        _qa_gate,
        _qa_review,
    )
except ImportError:  # bundle stages lambdas/ at the zip root
    from panelcast_qa import (  # noqa: F401
        _CHALLENGE_RE,
        _INTERROGATIVE_RE,
        _INTRO_RUBRIC,
        _QA_MAX_ATTEMPTS,
        _QA_MAX_CONSECUTIVE,
        _QA_MAX_CONSECUTIVE_INTRO,
        _QA_MAX_WORDS_PER_TURN,
        _WEEKLY_RUBRIC,
        _continuity_check,
        _craft_check,
        _qa_gate,
        _qa_review,
    )

# #1170/#1171/#1172 (ADR-135): the no-touch contract mechanics — deterministic seam
# repair, convergent revision, per-attempt ledger, bounded escalation email.
try:
    from emails import panelcast_repair as _repair
except ImportError:  # bundle stages lambdas/ at the zip root
    import panelcast_repair as _repair

# #1178: free RSS zeitgeist — optional topical color, fetched ONCE per run; the
# same list feeds the judge's ground truth (details in panelcast_zeitgeist.py).
try:
    from emails import panelcast_zeitgeist as _zeitgeist
except ImportError:  # bundle stages lambdas/ at the zip root
    import panelcast_zeitgeist as _zeitgeist

# #1182 (prep for #1180): the two big Sonnet prompt-builders live in panelcast_scripts.py
# (ADR-080 size gate). The thin wrappers below inject this lambda's clients + helpers,
# mirroring podcast_script_v2 (#547).
try:
    from emails import panelcast_scripts as _pscripts
except ImportError:  # bundle stages lambdas/ at the zip root
    import panelcast_scripts as _pscripts


def _pscripts_deps() -> dict:
    """Clients + helpers the extracted script builders need (resolved at call time so
    monkeypatched globals — e.g. panel._intro_guest / bedrock_client.invoke — take effect)."""
    return {
        "invoke": __import__("bedrock_client").invoke,
        "logger": logger,
        "intro_guest": _intro_guest,
        "episode_angle": _episode_angle,
        "extract_json": _extract_json,
        "zeitgeist": _zeitgeist,
        "intro_model": INTRO_MODEL,
        "writer_model": WRITER_MODEL,
    }


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


def _run_intro(dry_run: bool = False) -> dict:
    bible = _load_bible()
    # Numbers allowed by ER-03 = only those in the bible (it has essentially none →
    # this enforces "no invented numbers"). No elapsed-time/results context is fed.
    allowed = er03_gate.numbers_in(json.dumps(bible))
    _chars = bible.get("characters", {}) or {}
    # #1182: Episode 0 is EVERGREEN by design — it carries NO dated content, so a reset
    # can resurrect the wk0 prologue from archive without it going stale. So the intro
    # path never fetches the zeitgeist (weeklies keep topical color; ep0 must not) and
    # never appends the zeitgeist ground-truth block. Always the empty list.
    zeitgeist: list = []
    bio_truth = (
        "MATT — the experiment's SUBJECT, the ONLY person whose biographical facts are constrained:\n"
        + _chars.get("matthew", "")
        + "\n\nESTABLISHED show personas (NOT Matt, NOT inventions — never flag their names/roles): "
        "Elena Voss (host, embedded journalist); Dr. Eli Marsh (guest, the head coach Matt cast to lead the AI coach "
        "team — Matt himself designed and built the experiment and the platform)."
    )

    def _prep(raw):
        """Gate a raw script — a fresh generation OR a #1171 revision — identically:
        speaker mapping + Day-Zero + ER-03 line gates, then the launch locks (enforce
        "Matt"; prepend the fixed cold-open if the LLM didn't name Elena in line 1)."""
        ts = _gate_intro(raw or [], allowed)
        if len(ts) < 8:
            return None
        for t in ts:
            t["line"] = re.sub(r"\bMatthew\b", "Matt", t["line"])
        # #1123: name Elena in her own hook (or fall back to the cold-open) — turn 0 stays ONE solo hook, no t0/t1 seam.
        return _repair.name_the_opener(ts, ELENA, INTRO_COLD_OPEN)

    def _line_ok(line):
        # The intro path's per-line gates, applied to #1170 repair-generated lines too.
        return not _HALLUCINATION_RE.search(line) and er03_gate.er03_check(line, allowed_numbers=allowed, n=None)[0]

    import bedrock_client

    # #1170/#1171/#1172 bounded convergence: _QA_MAX_ATTEMPTS generations, each with a
    # deterministic seam-repair pass + up to MAX_REVISIONS judge-feedback revisions (the
    # weekly path's self-correcting mechanism, ported here — today's 15 blind re-rolls
    # never told the writer WHY it failed). After every repair/revision the FULL
    # unchanged gate (deterministic craft + Haiku judge, the same composition as
    # _qa_gate) re-judges — the gate stays the sole fail-closed arbiter.
    ledger = []
    turns, qa_fails = None, ["no candidate generated"]
    for attempt in range(_QA_MAX_ATTEMPTS):
        cand = _prep(_build_intro_script(bible, zeitgeist=zeitgeist))
        for rev in range(_repair.MAX_REVISIONS + 1):
            if not cand:
                ledger.append(_repair.ledger_entry(attempt + 1, rev, ["no usable candidate (parse/too-few-turns)"], []))
                break
            mc = _QA_MAX_CONSECUTIVE_INTRO  # #1123: strict alternation after the solo hook (gate + repair share this bound)
            cand, _seams, _fixed = _repair.repair_structure(
                cand, {ELENA, INTRO_GUEST_ID}, bedrock_client.invoke, INTRO_MODEL, _extract_json, logger, _line_ok, max_consecutive=mc
            )
            det = _craft_check(cand, mc)
            judge = _qa_review(cand, _INTRO_RUBRIC, bio_truth)[1]
            fails = det + judge  # same composition as _qa_gate; split only for the ledger
            ledger.append(_repair.ledger_entry(attempt + 1, rev, det, judge, _fixed))
            if turns is None or len(fails) < len(qa_fails):
                turns, qa_fails = cand, fails
            if not fails:
                logger.info("[panel] intro: clean QA on attempt %d rev %d (%d turns)", attempt + 1, rev, len(cand))
                break
            logger.info("[panel] intro QA attempt %d/%d rev %d failed: %s", attempt + 1, _QA_MAX_ATTEMPTS, rev, fails)
            if rev < _repair.MAX_REVISIONS:
                cand = _prep(_repair.revise_intro(cand, fails, bedrock_client.invoke, INTRO_MODEL, _extract_json, logger))
        if not qa_fails:
            break
    _repair.log_ledger(logger, "intro", 0, ledger)

    if turns is None:
        logger.warning("[panel] intro: no usable candidate after %d attempts", _QA_MAX_ATTEMPTS)
        return {"statusCode": 500, "body": json.dumps({"intro": "too few turns"})}
    if qa_fails:
        # HARD gate (#1122): QA fails after the whole attempt budget make the episode
        # structurally unpublishable (ADR-087 fail-closed posture — regenerate-or-hold,
        # matching the weekly path). #1172: exhaustion is loud — ONE needs-human email
        # carries the verdict ledger; never a silent miss, never a bad publish. Dry-run
        # still writes the draft transcript below so the failing script stays reviewable.
        logger.warning("[panel] intro: best candidate still has %d QA flag(s): %s", len(qa_fails), qa_fails)
        if not dry_run:
            _repair.send_exhaustion_email(
                ses,
                SENDER,
                os.environ.get("EMAIL_RECIPIENT", ""),
                0,
                "intro",
                ledger,
                logger,
                hold_uri=f"s3://{S3_BUCKET}/{HOLD_PREFIX}/wk0.json",
            )
            return _hold_and_alert(
                0,
                ["intro-qa: " + "; ".join(str(f) for f in qa_fails)[:300]],
                {"turns": turns, "qa_fails": qa_fails, "qa_ledger": ledger},
                hold_class="quality",
            )

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
    published = _publish_episode_audio(0, audio)
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
        **published,  # url/bytes/duration_sec from the compressed publish (#1018)
        "byline": "Elena + Dr. Eli Marsh",
        "excerpt": "Meet Elena, meet Matt, and meet the question this whole experiment is built to answer: can AI and your own data actually make a life better — or is it just over-optimization? The starting line.",
        "transcript_url": "/panelcast/wk0.transcript.json",
    }
    existing = [e for e in existing if e.get("week") != 0] + [ep]
    existing.sort(key=lambda e: e.get("week", 0), reverse=True)
    _write_indexes(existing)
    logger.info("[panel] intro wk0: %d turns, %d bytes at %s", len(turns), published["bytes"], published["url"])
    return {"statusCode": 200, "body": json.dumps({"intro": True, "turns": len(turns), "bytes": published["bytes"]})}


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
    # #914: the ONE shared presence block — if Matthew's own logging has gone
    # quiet, the panel must not review a normal week over an incomplete window.
    presence_note = ""
    try:
        from engagement_core import presence_prompt_block

        sig = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#engagement_state", "sk": "STATE#current"}).get("Item") or {}
        presence_note = presence_prompt_block(sig)
    except Exception as e:
        logger.warning("[panel] presence block skipped (non-fatal): %s", e)
    return {
        "week": post.get("week"),
        "date": post.get("date"),
        "title": post.get("title", f"Week {post.get('week')}"),
        "chronicle": chronicle,
        "coach_reads": coach_reads,
        "guest": guest,
        "presence_note": presence_note,
        # #1086: the ONE shared experiment-phase block, anchored to the reviewed
        # week's date. Part of the writer's source material, so its day/week
        # numbers join the ER-03 allowed set. (Deliberately the CORE block —
        # no body-weight numbers; the safety gate bans any spoken weight.)
        "phase_block": format_experiment_phase_context(build_experiment_phase_context(None, post.get("date"))),
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
    """Sonnet writes the Elena + guest-coach episode in the bet/Split/scoreboard format
    (builder in panelcast_scripts.py, #1182)."""
    return _pscripts.build_weekly_script(beats, bible, _pscripts_deps())


# ── #547: podcast v2 — the two-pass engine lives in podcast_script_v2.py (the
# *_lambda size gate); these wrappers inject this lambda's clients + helpers.
try:
    from emails import podcast_script_v2 as _psv2  # package import at runtime
except ImportError:  # flat import under the test harness
    import podcast_script_v2 as _psv2


def _psv2_deps() -> dict:
    return {
        "table": table,
        "s3": s3,
        "bucket": S3_BUCKET,
        "user_id": USER_ID,
        "writer_model": WRITER_MODEL,
        "invoke": __import__("bedrock_client").invoke,
        "extract_json": _extract_json,
        "elena_host_state": _elena_host_state,
        "episode_angle": _episode_angle,
        "logger": logger,
    }


def _build_weekly_script_v2(beats: dict, bible: dict) -> dict:
    try:
        return _psv2.build_weekly_script_v2(beats, bible, _psv2_deps())
    except Exception as e:  # any v2 failure → v1 keeps the show alive
        logger.warning("[panel] v2 script engine failed (%s) — falling back to v1", e)
        return {}


def _write_show_memory(week, title, pull_quote, guest_id, guest_name, open_bet) -> None:
    _psv2.write_show_memory(table, USER_ID, logger, week, title, pull_quote, guest_id, guest_name, open_bet)


# NB: the weekly targeted-revision writer (_revise_weekly_script) moved to
# panelcast_repair.revise_weekly (#1171 — the same mechanism now serves both paths).


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
    # Reason code (#374): a quality HOLD is auto-retriable; a safety HOLD is not.
    _emit_outcome("held-safety" if (hold_class if hold_class in ("safety", "quality") else "safety") == "safety" else "held-quality")
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


# The distinct outcomes every real (non-dry) run resolves to. Each run emits
# exactly one so the no-episode alarm can say WHY the show is silent instead of
# reading a bare metric gap (#374). "published" also keeps the legacy
# PanelcastPublished metric alive for the existing >8d-silence alarm.
_OUTCOME_REASONS = ("published", "held-quality", "held-safety", "no-input", "already-published", "budget-skip", "error")


def _emit_outcome(reason: str) -> None:
    """One reason code per run → CloudWatch (LifePlatform/Podcast / PanelcastRun,
    dimension Reason). Lets an alarm/dashboard distinguish a deliberate editorial
    or safety HOLD from a genuine breakage or a no-material week. Fail-open — a
    telemetry hiccup must never change the pipeline's decision."""
    if reason not in _OUTCOME_REASONS:
        reason = "error"
    try:
        boto3.client("cloudwatch", region_name=REGION).put_metric_data(
            Namespace="LifePlatform/Podcast",
            MetricData=[
                {
                    "MetricName": "PanelcastRun",
                    "Dimensions": [{"Name": "Reason", "Value": reason}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        logger.warning("[panel] outcome-metric emit failed (%s) — %s", reason, e)


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
        _emit_outcome("already-published")
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
            _emit_outcome("no-input")
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
    import bedrock_client

    # #914: the presence note is part of the writer's source material, so its real
    # gap-day count is an allowed number (a spoken "eleven days quiet" must pass).
    # #1086: likewise the phase block — a spoken "day three, week one" must pass.
    allowed = er03_gate.numbers_in(
        beats["chronicle"]
        + " "
        + " ".join(c["summary"] for c in beats["coach_reads"])
        + " "
        + beats.get("presence_note", "")
        + " "
        + beats.get("phase_block", "")
    )
    # #1178: ONE fetch per run — attempts/revisions reuse the same list (via beats)
    # so writer prompt + judge ground truth stay consistent. Fail-soft: [] = no block.
    beats["zeitgeist"] = _zeitgeist.fetch_zeitgeist()
    _gt = (beats.get("chronicle", "")[:1500] + "\n" + "\n".join(f"{c['name']}: {c['summary']}" for c in beats.get("coach_reads", [])))[
        :4000
    ] + _zeitgeist.zeitgeist_truth_block(beats["zeitgeist"])

    def _valid(ts):
        return [t for t in ts if isinstance(t, dict) and (t.get("line") or "").strip()]

    def _line_ok(line):
        # The weekly path's per-line safety gate, applied to #1170 repair-generated lines too.
        return not _safety_gate(line)

    # #1170/#1171/#1172 (ADR-135): the bounded no-touch loop — up to _QA_MAX_ATTEMPTS
    # generations (dry_run: one, no extra spend on a pre-flight), each with a
    # deterministic seam-repair pass + up to MAX_REVISIONS judge-feedback revisions
    # (the existing self-correcting mechanism, now inside a fixed budget). SAFETY
    # failures stay immediate-hold and never consume budget or retry; quality failures
    # consume an attempt; exhaustion HOLDs + escalates with ONE needs-human email.
    # After every repair/revision the FULL unchanged gate (deterministic craft + Haiku
    # judge, the same composition as _qa_gate) re-judges — sole fail-closed arbiter.
    ledger, ready, draft_turns = [], None, None
    last_fails = ["no candidate generated"]
    for attempt in range(1 if dry_run else _QA_MAX_ATTEMPTS):
        # #547: two-pass first (each speaker in-voice, real disputes, show memory);
        # v1 single-call stays as the fail-soft fallback so an upgrade bug can't
        # kill the show.
        script = _build_weekly_script_v2(beats, bible) or _build_weekly_script(beats, bible)
        turns = script.get("turns") or []
        if len(_valid(turns)) < 6:
            last_fails = ["writer produced too few turns"]
            ledger.append(_repair.ledger_entry(attempt + 1, 0, last_fails, []))
            continue
        review = _editor_review(turns, bible)
        if review.get("verdict") == "hold":
            # An editor hold is a quality failure mode — it consumes an attempt (the
            # SS-02 sweep already regenerates quality holds; #1172 does it in-budget).
            last_fails = ["editor: " + "; ".join(review.get("issues", []))[:300]]
            ledger.append(_repair.ledger_entry(attempt + 1, 0, [], last_fails))
            continue
        for rev in range(_repair.MAX_REVISIONS + 1):
            for t in turns:
                t["line"] = re.sub(r"\bMatthew\b", "Matt", t.get("line", ""))
            clean, hold = _weekly_gate(turns, allowed, guest_id)
            if hold:
                # Safety fails CLOSED immediately, exactly as before #1172 — a
                # sensitivity/compassion hit is never "retried away".
                if dry_run:
                    return _dry(week, "HOLD", stage="safety-gate", reasons=hold)
                return _hold_and_alert(week, hold, {"turns": turns, "qa_ledger": ledger}, hold_class="safety")
            if len(clean) < len(_valid(turns)) or len(clean) < 6:
                # A turn DROPPED by the ER-03/empty gate leaves a hole mid-conversation —
                # never voice a holey transcript (#1122); it costs the attempt instead.
                last_fails = ["gate dropped turns (holey transcript)"]
                ledger.append(_repair.ledger_entry(attempt + 1, rev, last_fails, []))
                break
            draft_turns = clean
            # #1170: deterministic seam repair (zero-cost when the script already
            # alternates), then the FULL unchanged gate on the repaired script.
            clean, _seams, _fixed = _repair.repair_structure(
                clean, {ELENA, guest_id}, bedrock_client.invoke, WRITER_MODEL, _extract_json, logger, line_ok=_line_ok
            )
            det = _craft_check(clean)
            judge = _qa_review(clean, _WEEKLY_RUBRIC, _gt)[1]
            fails = det + judge  # same composition as _qa_gate; split only for the ledger
            ledger.append(_repair.ledger_entry(attempt + 1, rev, det, judge, _fixed))
            last_fails, draft_turns = fails, clean
            if not fails:
                ready = (script, clean, review)
                break
            logger.info("[panel] wk%s: QA fails (attempt %d rev %d) — %s", week, attempt + 1, rev, fails)
            if rev < _repair.MAX_REVISIONS:
                revised = _repair.revise_weekly(
                    clean,
                    fails,
                    guest_name,
                    bible.get("show_name", "The Measured Life"),
                    bedrock_client.invoke,
                    WRITER_MODEL,
                    _extract_json,
                    logger,
                )
                if not (revised.get("turns") or []):
                    break  # revision failed/parse-broke — spend the next generation instead
                script, turns = revised, revised["turns"]
        if ready:
            break
    _repair.log_ledger(logger, "weekly", week, ledger)
    if not ready:
        logger.info("[panel] wk%s: weekly QA HOLD — budget exhausted (%d ledger rows) — %s", week, len(ledger), last_fails)
        if dry_run:
            return _dry(week, "HOLD", stage="weekly-qa", reasons=last_fails, qa_ledger=ledger)
        # #1172: exhaustion is loud — publish NOTHING (the HOLD below, unchanged) and
        # send ONE needs-human email carrying the per-attempt verdict ledger.
        _repair.send_exhaustion_email(
            ses,
            SENDER,
            os.environ.get("EMAIL_RECIPIENT", ""),
            week,
            "weekly",
            ledger,
            logger,
            hold_uri=f"s3://{S3_BUCKET}/{HOLD_PREFIX}/wk{week}.json",
        )
        return _hold_and_alert(
            week,
            ["weekly-qa: " + "; ".join(str(f) for f in last_fails)[:300]],
            {"turns": draft_turns or [], "qa_ledger": ledger},
            hold_class="quality",
        )
    script, clean, review = ready

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
    published = _publish_episode_audio(week, audio)
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
        **published,  # url/bytes/duration_sec from the compressed publish (#1018)
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
    # #547: the show remembers itself — callbacks + guest history, real records only.
    _write_show_memory(
        week, ep.get("title") or _hook, script.get("pull_quote"), guest_id, (beats.get("guest") or {}).get("name"), script.get("open_bet")
    )
    _emit_published_metric()  # safety-net: a CloudWatch alarm fires if this metric goes absent (no episode > 8d)
    _emit_outcome("published")  # reason code (#374) — the positive outcome in the same vocabulary as the holds
    _notify_new_episode(ep)  # operator SNS ping (best-effort; never blocks publish)
    # Confirmed-subscriber email blast — OFF by default (PANELCAST_NOTIFY_SUBSCRIBERS).
    # Flip on only after a {"notify_test": "<addr>"} dry-run looks right, so the very
    # first real episodes never blind-blast the list. Best-effort; never blocks publish.
    if os.environ.get("PANELCAST_NOTIFY_SUBSCRIBERS", "false").lower() == "true":
        try:
            _email_subscribers(ep)
        except Exception as e:
            logger.warning("[panel] subscriber blast failed — %s", e)
    logger.info(
        "[panel] wk%s PUBLISHED — %d turns, %d bytes at %s, guest %s", week, len(clean), published["bytes"], published["url"], guest_id
    )
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
            if not dry_run:
                _emit_outcome("budget-skip")
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
        if not dry_run:
            _emit_outcome("error")  # a live pipeline error is distinct from a deliberate HOLD (#374)
        return {"statusCode": 500, "body": json.dumps({"weekly": "failed", "error": str(e)[:200]})}
