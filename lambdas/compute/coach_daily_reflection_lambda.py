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
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
import er03_gate
import persona_registry
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

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
    summary = it.get("key_recommendation") or it.get("observatory_summary") or ""
    if not summary:
        return None
    themes = it.get("themes") or []
    facts = summary + (" " + " ".join(str(t) for t in themes) if themes else "")
    return {
        "summary": summary,
        "themes": themes[:4],
        "numbers": er03_gate.numbers_in(facts),
        "n": int(it.get("word_count") or 10),  # small-sample → forces a hedge
    }


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
    import bedrock_client

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


def lambda_handler(event, context):
    # PG-10: budget self-skip — never run when spend is elevated.
    try:
        from budget_guard import current_tier

        tier = current_tier()
        if tier >= SKIP_TIER:
            logger.info("[coach_daily] budget tier %s >= %s — skipping (PG-10)", tier, SKIP_TIER)
            return {"skipped": True, "tier": tier}
    except Exception:
        pass  # fail-open: a budget blip must not break the batch

    s3 = boto3.client("s3", region_name=REGION)
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
        text = _generate(persona, voice_rules, example, facts)
        ok = False
        if text:
            ok, reasons = er03_gate.er03_check(text, allowed_numbers=facts["numbers"], n=facts["n"])
            if not ok:
                logger.info("[coach_daily] %s failed ER-03 (%s) — retrying stricter", coach_id, reasons)
                text = _generate(persona, voice_rules, example, facts, stricter=True)
                ok = bool(text) and er03_gate.er03_check(text, allowed_numbers=facts["numbers"], n=facts["n"])[0]
        if ok:
            reflections[coach_id] = {"text": text, "date": today, "framing": "correlative"}
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
