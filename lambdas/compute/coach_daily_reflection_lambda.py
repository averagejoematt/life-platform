"""coach_daily_reflection_lambda.py — CC-08: the one gated new-inference item.

Once a day, on the batch (never on page view), each coach writes a ≤120-word
reflection in its own voice over its OWN recent computed output. Correlative,
confidence-labelled, no fabricated numbers — every line passes the ER-03 gate
before it's published to generated/coach_daily.json (PII-guarded prefix, ADR-046).
The coach pages + popovers serve that cached text; nothing here runs live.

Cost & safety rails:
  * Haiku (cheap) — short snippets don't need Sonnet.
  * Self-skips at budget tier >= 2 (PG-10) — never pushes the monthly ceiling.
  * bedrock_client enforces the tier-3 hard stop too.
  * ER-03 gate is fail-closed: anything that doesn't pass is dropped, not shipped.
  * Honest empty: a coach with no recent output yet is simply skipped.

#2430 — the ER-03 check is no longer the WHOLE gate. ER-03 answers "correlative,
hedged, no number outside the facts"; it says nothing about a fabricated calendar
date or a stale "Day N"/starting-weight framing, and this text is published to
generated/coach_daily.json and rendered on the coach pages. `_grounding_findings`
is the registered surface (tests/grounding_wiring.py) and arms the numbers, dates
and freshness classes; both checks are fail-closed and both must pass.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from ai import grounded_generation
from boto3.dynamodb.conditions import Key
from coach import coach_derived_prose, persona_registry  # #2418: served_summary falls back to gated `content`
from common.constants import EXPERIMENT_START_DATE  # ADR-058/077 — current-cycle genesis anchor (#1691 freshness class)
from experiment import er03_gate
from experiment.phase_filter import with_phase_filter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
OUTPUT_KEY = "generated/coach_daily.json"
SKIP_TIER = 2  # PG-10: at budget tier >= 2 the daily reflection does not run

_SYSTEM_RULES = (
    "You are an AI coach character writing a short daily reflection for a public health-experiment site. "
    "Rules you must obey:\n"
    "- Speak in your own voice; never open with the user's name.\n"
    "- Correlative only — never claim one thing CAUSED another.\n"
    "- Use only numbers that appear in the provided facts; invent no figures and do no arithmetic.\n"
    "- The data is early and small-sample — hedge ('early', 'so far', 'appears', 'trend').\n"
    "- 120 words maximum. One tight paragraph. No preamble, no sign-off."
)


def _gather_facts(table, coach_id):
    """The coach's most recent computed output — the factual basis to re-voice."""
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
    except Exception as e:
        logger.warning("[coach_daily] read %s: %s", coach_id, e)
        items = []
    if not items:
        return None
    it = items[0]
    summary = coach_derived_prose.served_summary(it)
    if not summary:
        return None
    return facts_from(summary, it.get("themes") or [], it.get("word_count"))


def facts_from(summary, themes, word_count):
    """The facts dict, derived from a coach's stored output. Split out of
    `_gather_facts` (#2889) so it is reachable without DynamoDB — the reuse gate is
    judged against exactly this structure, and a test that hand-rolled a lookalike
    would be testing its own fixture rather than the wire."""
    facts = summary + (" " + " ".join(str(t) for t in themes) if themes else "")
    return {
        "summary": summary,
        "themes": list(themes)[:4],
        "numbers": er03_gate.numbers_in(facts),
        # #2430: the grounding allow-lists, derived from the SAME text the model is
        # shown (summary + themes) — literally the vocabulary it was given.
        "allowed": grounded_generation.allowed_numbers(facts),
        "allowed_dates": grounded_generation.allowed_dates(facts),
        "n": int(word_count or 10),  # small-sample → forces a hedge
    }


def _grounding_findings(text, facts, generation_date_iso):
    """#2430: the registered grounding surface for the daily reflection.

    Arms numbers (#ADR-104), dates (#1242) and freshness (#1691/#1897) — every class
    this layer can answer honestly from what it already holds. `behavioral` and `night`
    are exempt with written reasons in tests/grounding_wiring.py::SURFACES.
    """
    return grounded_generation.grounding_findings(
        text,
        allowed=facts["allowed"],
        allowed_dates=facts["allowed_dates"],
        generation_date_iso=generation_date_iso,
        start_date_iso=EXPERIMENT_START_DATE,
    )


def _accepts(text, facts, generation_date_iso):
    """(ok, reasons) — fail-CLOSED: ER-03 *and* the #2430 grounding classes.

    Either check firing holds the reflection; a held reflection is dropped (the coach is
    listed in `skipped`), never shipped, because the published artifact is read by the
    coach pages with no second gate downstream.
    """
    if not (text or "").strip():
        return False, ["empty"]
    ok, reasons = er03_gate.er03_check(text, allowed_numbers=facts["numbers"], n=facts["n"])
    findings = _grounding_findings(text, facts, generation_date_iso)
    return (ok and not findings), list(reasons or []) + [f.get("type", "grounding") for f in findings]


def _voice(s3, coach_config_key):
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"config/coaches/{coach_config_key}.json")
        cfg = json.loads(obj["Body"].read())
        rules = cfg.get("structural_voice_rules") or {}
        ex = (cfg.get("few_shot_examples") or [None])[0]
        if isinstance(ex, dict):
            ex = ex.get("output") or ex.get("text") or next(iter(ex.values()), None)
        return json.dumps(rules)[:1200], (ex if isinstance(ex, str) else "")
    except Exception:
        return "", ""


def _generate(persona, voice_rules, example, facts, stricter=False):
    from ai import bedrock_client

    sys_block = f"{_SYSTEM_RULES}\n\nYour voice rules: {voice_rules}" + (f"\n\nA sample in your voice:\n{example}" if example else "")
    if stricter:
        sys_block += "\n\nSTRICT: output must contain no numbers that are not in the facts, and no causal words."
    user = (
        f"You are {persona.get('name')} ({persona.get('board_role') or persona.get('domain')}). "
        f"Today's facts about your domain:\n{facts['summary']}\n"
        f"Themes: {', '.join(facts['themes']) if facts['themes'] else '(none)'}\n\n"
        "Write your ≤120-word daily reflection."
    )
    body = {
        "model": MODEL,
        "max_tokens": 320,
        "system": sys_block,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        resp = bedrock_client.invoke(body, model_name=MODEL)
        parts = resp.get("content") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        return text or None
    except Exception as e:
        logger.warning("[coach_daily] generate failed: %s", e)
        return None


OUTPUT_TYPE = "daily_reflection"  # #2889: the generation_cache slot for this surface
SURFACE = "daily_reflection"  # #2889: the GenerationSkippedUnchanged metric dimension


def _reuse_or_none(table, cw, coach_id, persona, voice_rules, example, facts, today):
    """#2889 (ADR-126 extended): skip the Haiku call when nothing this coach reflects
    on has changed. Returns `(fingerprint, reused_text_or_None, unchanged_since)`.

    This surface is a textbook fit for the hash-and-reuse seam and was paying for it
    daily: `_gather_facts` reads the coach's LATEST `OUTPUT#` record, so on any day a
    coach did not publish — a quality-gate HOLD (ADR-108), a budget pause, a stalled
    coach — the facts are byte-identical to yesterday's and the model is paid to
    re-say the same 120 words.

    What it is NOT allowed to skip is the gate. `_accepts` arms the #2430 grounding
    classes, two of which (fabricated-date, cycle freshness) are judged against
    TODAY: text that was honest on Day 4 can be a stale-Day-N violation on Day 9 with
    identical inputs. So the stored text is re-gated against `today` before it is
    reused — `generation_cache.reuse_if_still_valid` makes that mandatory rather than
    a convention this call site could quietly drop.

    Entirely fail-soft: any error anywhere degrades to "generate as before".
    """
    try:
        from common import generation_cache as gc

        parts = gc.reflection_parts(persona, voice_rules, example, facts)
        fingerprint, reused, unchanged_since = gc.reuse_if_still_valid(
            table, coach_id, OUTPUT_TYPE, parts, lambda text: _accepts(text, facts, today)[0]
        )
        if reused:
            gc.record_reuse(table, coach_id, OUTPUT_TYPE, today)
            gc.emit_skip_metric(cw, "LifePlatform/AI", coach_id, surface=SURFACE)
            logger.info("[coach_daily] %s unchanged since %s — reusing gated reflection, no generation", coach_id, unchanged_since)
        return fingerprint, reused, unchanged_since
    except Exception as e:
        logger.warning("[coach_daily] generation cache unavailable for %s (non-blocking): %s", coach_id, e)
        return None, None, None


def _store(table, coach_id, fingerprint, persona, voice_rules, example, facts, text, today):
    """Persist a freshly generated, gate-passed reflection under its input fingerprint."""
    if not fingerprint:
        return
    try:
        from common import generation_cache as gc

        gc.store_entry(
            table, coach_id, OUTPUT_TYPE, fingerprint, text, today, parts=gc.reflection_parts(persona, voice_rules, example, facts)
        )
    except Exception as e:
        logger.warning("[coach_daily] generation cache store failed for %s (non-blocking): %s", coach_id, e)


def lambda_handler(event, context):
    # PG-10: budget self-skip — never run when spend is elevated.
    try:
        from ai.budget_guard import current_tier

        tier = current_tier()
        if tier >= SKIP_TIER:
            logger.info("[coach_daily] budget tier %s >= %s — skipping (PG-10)", tier, SKIP_TIER)
            return {"skipped": True, "tier": tier}
    except Exception:
        pass  # fail-open: a budget blip must not break the batch

    s3 = boto3.client("s3", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    reg = persona_registry.load_registry(s3, S3_BUCKET).get("personas", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    reflections, skipped = {}, []
    for coach_id in persona_registry.OPERATIONAL_COACH_IDS:
        persona = reg.get(coach_id) or {}
        facts = _gather_facts(table, coach_id)
        if not facts:
            skipped.append(coach_id)
            continue  # honest empty — nothing to reflect on yet
        voice_rules, example = _voice(s3, persona.get("coach_config_key", coach_id))

        # #2889: hash-and-reuse BEFORE any generation. The reused text was gate-passed
        # when it was written AND has just been re-gated against today (see _reuse_or_none).
        fingerprint, reused, unchanged_since = _reuse_or_none(table, cw, coach_id, persona, voice_rules, example, facts, today)
        if reused:
            reflections[coach_id] = {"text": reused, "date": today, "framing": "correlative", "unchanged_since": unchanged_since}
            continue

        text = _generate(persona, voice_rules, example, facts)
        ok, reasons = _accepts(text, facts, today)
        if not ok:
            logger.info("[coach_daily] %s failed the gate (%s) — retrying stricter", coach_id, reasons)
            text = _generate(persona, voice_rules, example, facts, stricter=True)
            ok, _reasons2 = _accepts(text, facts, today)
        if ok:
            reflections[coach_id] = {"text": text, "date": today, "framing": "correlative"}
            _store(table, coach_id, fingerprint, persona, voice_rules, example, facts, text, today)
        else:
            skipped.append(coach_id)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "reflections": reflections,
        "disclosure": "AI coach reflections — generated once daily, correlative, ER-03-checked. Not medical advice.",
    }
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=OUTPUT_KEY,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=3600",
    )
    logger.info("[coach_daily] wrote %d reflections, skipped %s", len(reflections), skipped)
    return {"written": len(reflections), "skipped": skipped}
