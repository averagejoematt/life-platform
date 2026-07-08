"""
daily_debrief_lambda.py — the daily ~2-minute "state of Matthew" audio debrief (#734, epic #721).

The distribution channel that needs nothing but the engine: every day, the
already-computed daily-brief facts (day grade, recovery/HRV/RHR, training load,
habit completion — all pre-computed before 11 AM PT by daily-metrics-compute /
daily-insight-compute and written to DynamoDB) are assembled into a short spoken
briefing, synthesized with Google Chirp 3: HD, and published as an MP3 under
generated/podcast/debrief/ with a podcast RSS feed. Podcast feeds are crawler-proof
and don't depend on the JS site shell, so the show travels even when nothing else does.

Grounding (ADR-104, the hard rule): every number is computed deterministically
BEFORE the model sees it. The ONE Haiku call writes only the connecting prose from
a pre-computed fact dict; its output is checked against the exact numeric vocabulary
it was handed (grounded_generation.grounding_findings) plus a causal-language check,
and EITHER failure falls back to a deterministic template narrative built directly
from the same fields — which cannot fabricate a number. The audio always ships
(TTS is effectively free), but it never voices an unverified claim. This is the
fail-closed gate: an ungrounded sentence is dropped, not aired.

Budget (ADR-063/087): 1 Haiku call/day (~$0.003) + Chirp 3: HD TTS (a ~300-word
script is ~1.8k chars, well inside the 1M free chars/month) → ~$0.10/month, a
near-zero base even at 7x the old weekly cadence. Narration is budget-gated via
budget_guard's "daily_debrief" feature (Band 2, tier ≥ 2 → template fallback, in
lockstep with state_of_matthew); the show never goes dark for cost, it degrades to
the deterministic narrative at $0 AI spend.

Scheduled daily 19:00 UTC (noon PT / 11 AM PST) — after the morning compute +
daily-brief window, so it narrates the freshest complete day. Idempotent: a day
already rendered is skipped ({"force": true} re-renders; {"dry_run": true} runs the
full decision with no synth/write; {"date": "YYYY-MM-DD"} overrides the target day).
"""

import json
import os
import re
from datetime import datetime, timezone

import boto3
import google_tts
from boto3.dynamodb.conditions import Key
from er03_gate import BANNED_CAUSAL  # the platform's one banned-causal-connective list
from grounded_generation import allowed_numbers, grounding_findings  # ADR-104 gate

try:
    from numeric import decimals_to_float
except ImportError:  # pragma: no cover — numeric is always bundled in prod

    def decimals_to_float(x):
        return x


try:
    from platform_logger import get_logger

    logger = get_logger("daily-debrief")
except ImportError:
    import logging

    logger = logging.getLogger("daily-debrief")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
SITE = "https://averagejoematt.com"
PREFIX = "generated/podcast/debrief"
MAX_EPISODES = 60  # ~2 months of daily episodes in the feed

BUDGET_FEATURE = "daily_debrief"
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
MAX_TOKENS = 520
# A clean, neutral system-narrator voice — deliberately NOT Elena's (Aoede), so the
# daily debrief is audibly distinct from the weekly chronicle podcast.
DEBRIEF_VOICE = os.environ.get("DEBRIEF_VOICE", "en-US-Chirp3-HD-Charon")

s3 = boto3.client("s3", region_name=REGION)
table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Fact gathering — pure DDB reads of already-computed records. Each fails soft.
# ─────────────────────────────────────────────────────────────────────────────


def _latest_computed_date() -> str | None:
    """The newest DATE# on computed_metrics — the freshest fully-computed day.
    Robust + reset-proof: we narrate whatever the last real computed day is,
    with no timezone arithmetic to drift."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(USER_PREFIX + "computed_metrics") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
        )
    except Exception as e:
        logger.warning("[debrief] latest computed_metrics query failed — %s", e)
        return None
    items = resp.get("Items", [])
    if not items:
        return None
    return (items[0].get("date") or items[0].get("sk", "").replace("DATE#", "")) or None


def _fetch(source: str, date_str: str) -> dict:
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return decimals_to_float(r.get("Item") or {})
    except Exception as e:
        logger.warning("[debrief] fetch %s %s failed — %s", source, date_str, e)
        return {}


def gather_facts(date_str: str) -> dict:
    """Assemble the day's already-computed facts into ONE flat dict. No math
    happens here — every value is read verbatim from a compute Lambda's output,
    so the narrative can only ever restate a number the platform already stands
    behind. None-valued fields are dropped (the graceful-degrade contract)."""
    cm = _fetch("computed_metrics", date_str)
    hs = _fetch("habit_scores", date_str)

    facts: dict = {"date": date_str}

    def put(key, val):
        if val is not None:
            facts[key] = val

    put("day_grade", cm.get("day_grade_letter"))
    put("day_grade_score", _num(cm.get("day_grade_score")))
    put("readiness_score", _num(cm.get("readiness_score")))
    put("recovery_pct", _num(cm.get("recovery_pct")))
    put("hrv_ms", _num(cm.get("hrv_ms")))
    put("rhr_bpm", _num(cm.get("rhr_bpm")))
    put("sleep_debt_7d_hrs", _num(cm.get("sleep_debt_7d_hrs")))
    put("tier0_streak_days", _int(cm.get("tier0_streak")))
    # Training load (BS-09 ACWR, merged onto computed_metrics by acwr-compute).
    if cm.get("acwr") is not None:
        put("training_load_acwr", _num(cm.get("acwr")))
        put("training_load_zone", cm.get("zone"))
    # Habit completion — the effort surface.
    if hs.get("tier0_total"):
        put("core_habits_done", _int(hs.get("tier0_done")))
        put("core_habits_total", _int(hs.get("tier0_total")))
    if hs.get("tier1_total"):
        put("stretch_habits_done", _int(hs.get("tier1_done")))
        put("stretch_habits_total", _int(hs.get("tier1_total")))
    return facts


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else round(f, 1)


def _int(v):
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Narration — ONE Haiku call, ADR-104 grounded, deterministic-template fallback.
# ─────────────────────────────────────────────────────────────────────────────


def _causal_language(text: str) -> list:
    low = (text or "").lower()
    return [w for w in BANNED_CAUSAL if re.search(r"\b" + re.escape(w) + r"\b", low)]


def deterministic_fallback_narrative(facts: dict) -> str:
    """A grounded template built only from fields already in `facts` — used when
    Haiku is paused/unavailable/ungrounded. Cannot fabricate a number because it
    only restates values it was handed."""
    parts = []
    if facts.get("day_grade"):
        score = f" ({facts['day_grade_score']} out of 100)" if facts.get("day_grade_score") is not None else ""
        parts.append(f"Yesterday graded out at a {facts['day_grade']}{score}.")
    vit = []
    if facts.get("recovery_pct") is not None:
        vit.append(f"recovery at {facts['recovery_pct']} percent")
    if facts.get("hrv_ms") is not None:
        vit.append(f"HRV {facts['hrv_ms']} milliseconds")
    if facts.get("rhr_bpm") is not None:
        vit.append(f"resting heart rate {facts['rhr_bpm']}")
    if vit:
        parts.append("On the body: " + ", ".join(vit) + ".")
    if facts.get("training_load_zone"):
        parts.append(f"Training load is in the {facts['training_load_zone']} zone.")
    if facts.get("core_habits_total"):
        parts.append(f"Core habits: {facts.get('core_habits_done', 0)} of {facts['core_habits_total']} held.")
    if facts.get("tier0_streak_days"):
        parts.append(f"That's a {facts['tier0_streak_days']}-day core streak.")
    if not parts:
        return "Not enough computed data yet to brief the day."
    return " ".join(parts)


def build_narration_body(facts: dict) -> dict:
    system = (
        "You are the narrator of the 'Daily Debrief,' a roughly two-minute spoken audio briefing on "
        "one person's health-experiment day. His name is Matt. You are given the exact, already-computed "
        "numbers for the day below in JSON. You must NOT calculate, estimate, round, average, extrapolate, "
        "or invent ANY number, percentage, date, or trend that is not explicitly present in that JSON — use "
        "ONLY the facts given. Write in a warm, plain, second-or-third-person spoken voice for the ear "
        "(this is read aloud, so no headings, no lists, no markdown, no emoji). Roughly 230 to 320 words. "
        "Be correlative and non-hyperbolic: never claim causation ('causes', 'because', 'leads to', 'drives', "
        "etc.) and never dramatize. If a fact is absent from the JSON, do not mention it or apologize for it. "
        "Do not open with the word 'Matt' or 'Matthew'. Close on a single grounded, forward-looking sentence "
        "without inventing a plan or a number."
    )
    data_blob = json.dumps(facts, indent=2, default=str)
    user = "Today's pre-computed facts for the debrief:\n\n" + data_blob + "\n\nWrite the spoken debrief now."
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": [{"role": "user", "content": user}]}


def narrate(facts: dict) -> dict:
    """One Haiku call → grounded connecting prose. Budget-gated (tier ≥ 2, matching
    state_of_matthew), fail-soft to the deterministic template on a tier pause, a
    Bedrock error, an empty response, or a failed ADR-104 grounding/causal check.
    Never regenerates — one call per day."""
    try:
        from budget_guard import allow

        if not allow(BUDGET_FEATURE):
            return {"narrative": deterministic_fallback_narrative(facts), "narrated": False, "model": None, "reason": "budget_tier"}
    except ImportError:
        pass  # fail-open: a missing module must never take the debrief down

    try:
        import bedrock_client

        resp = bedrock_client.invoke(build_narration_body(facts), model_name=MODEL)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    except Exception as e:
        logger.warning("[debrief] narration call failed — %s", e)
        return {"narrative": deterministic_fallback_narrative(facts), "narrated": False, "model": None, "reason": "bedrock_error"}

    if not text:
        return {"narrative": deterministic_fallback_narrative(facts), "narrated": False, "model": None, "reason": "empty_response"}

    allowed = allowed_numbers(facts)
    findings = grounding_findings(text, facts=None, allowed=allowed)
    causal_hits = _causal_language(text)
    if findings or causal_hits:
        logger.warning("[debrief] ADR-104 gate failed (findings=%s, causal=%s) — falling back to template", findings, causal_hits)
        return {"narrative": deterministic_fallback_narrative(facts), "narrated": False, "model": MODEL, "reason": "grounding_gate"}

    return {"narrative": text, "narrated": True, "model": MODEL, "reason": None}


# ─────────────────────────────────────────────────────────────────────────────
# Publish — synthesize + write MP3 + rebuild the RSS index.
# ─────────────────────────────────────────────────────────────────────────────


def _friendly_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d")
    except ValueError:
        return date_str


def _spoken_script(date_str: str, narrative: str) -> str:
    """The narrative wrapped in a deterministic intro/outro. The framing is NOT
    AI-generated, so it is not subject to the grounding gate — it's prepended
    after narrate() has already cleared."""
    return f"The daily debrief. Here's where Matt stands, {_friendly_date(date_str)}.\n\n{narrative}\n\nThat's the debrief."


def _episode_key(date_str: str) -> str:
    return f"{PREFIX}/{date_str}.mp3"


def _episode_exists(date_str: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=_episode_key(date_str))
        return True
    except Exception:
        return False


def _xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rfc822(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y 19:00:00 GMT")


def _existing_index() -> list:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX}/episodes.json")
        return json.loads(obj["Body"].read()).get("episodes", [])
    except Exception:
        return []


def _write_indexes(episodes: list) -> None:
    """episodes: [{date, title, url, bytes, excerpt}] newest-first, capped."""
    episodes = sorted(episodes, key=lambda e: e.get("date", ""), reverse=True)[:MAX_EPISODES]
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
    <guid isPermaLink="false">measured-life-debrief-{e["date"]}</guid>
    <pubDate>{_rfc822(e["date"])}</pubDate>
  </item>"""
        for e in episodes
    )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>The Measured Life — the daily debrief</title>
  <link>{SITE}/now/</link>
  <description>A roughly two-minute, AI-voiced state-of-Matthew briefing every day — grade, recovery, training load, and effort, narrated only from numbers the platform computed and stands behind. Grounded generation (ADR-104): the voice connects the data, it never invents it.</description>
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


def _emit_published_metric() -> None:
    """DebriefPublished=1 on each successful publish — for dashboards/observability.
    Deliberately NOT wired to a 'went silent' alarm: a budget-skip day still
    publishes (template narrative), and a broken cron is caught by the daily-brief-
    style no-INVOCATIONS alarm instead, so a legitimately quiet run is never red."""
    try:
        boto3.client("cloudwatch", region_name=REGION).put_metric_data(
            Namespace="LifePlatform/Podcast",
            MetricData=[{"MetricName": "DebriefPublished", "Value": 1, "Unit": "Count"}],
        )
    except Exception as e:
        logger.warning("[debrief] metric emit failed — %s", e)


def _publish(date_str: str, narrative: str, excerpt: str) -> dict:
    script = _spoken_script(date_str, narrative)
    audio = google_tts.synthesize(script, DEBRIEF_VOICE)
    key = _episode_key(date_str)
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=audio, ContentType="audio/mpeg", CacheControl="max-age=86400, public")

    index = [e for e in _existing_index() if e.get("date") != date_str]
    index.append(
        {
            "date": date_str,
            "title": f"Daily debrief — {_friendly_date(date_str)}",
            "url": f"/podcast/debrief/{date_str}.mp3",
            "bytes": len(audio),
            "excerpt": excerpt[:220],
        }
    )
    _write_indexes(index)
    _emit_published_metric()
    logger.info("[debrief] %s PUBLISHED — %d bytes (%d script chars)", date_str, len(audio), len(script))
    return {"statusCode": 200, "body": json.dumps({"date": date_str, "published": True, "bytes": len(audio)})}


def lambda_handler(event, context):
    event = event or {}
    force = bool(event.get("force"))
    dry_run = bool(event.get("dry_run"))

    date_str = event.get("date") or _latest_computed_date()
    if not date_str:
        logger.warning("[debrief] no computed day available — nothing to brief")
        return {"statusCode": 200, "body": json.dumps({"skipped": "no computed_metrics"})}

    if not force and not dry_run and _episode_exists(date_str):
        return {"statusCode": 200, "body": json.dumps({"date": date_str, "already_published": True})}

    facts = gather_facts(date_str)
    # Fail-closed: with no gradable facts there is nothing grounded to voice — skip
    # rather than air an empty episode.
    if len(facts) <= 1:  # only {"date": ...}
        logger.warning("[debrief] %s has no computed facts — skipping", date_str)
        return {"statusCode": 200, "body": json.dumps({"date": date_str, "skipped": "no facts"})}

    narration = narrate(facts)
    if dry_run:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "date": date_str,
                    "dry_run": True,
                    "narrated": narration["narrated"],
                    "reason": narration.get("reason"),
                    "facts": facts,
                    "narrative": narration["narrative"],
                }
            ),
        }

    try:
        return _publish(date_str, narration["narrative"], narration["narrative"])
    except Exception as e:
        logger.error("[debrief] publish failed for %s — %s", date_str, e)
        return {"statusCode": 500, "body": json.dumps({"date": date_str, "error": str(e)[:200]})}
