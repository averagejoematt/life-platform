"""coach_memoir_lambda.py — #553: quarterly in-voice coach retrospectives.

Once a quarter, each coach writes a first-person memoir reckoning with its
OWN graded track record: what it got right (confirmed LEARNING#), what it got
wrong (refuted LEARNING#), and how its read of Matthew changed (STANCE#
bookends). Grounded strictly in real data — never fabricated calls or
outcomes — and gated so a memoir that only lists wins never publishes
(memoir_gate.cites_a_miss, #553's "misses must outnumber humblebrags" bar).

Cost & safety rails:
  * Sonnet (narrative tier, per CLAUDE.md's model-tiering rule) — this is
    long-form first-person prose, not a structured extraction.
  * budget_guard.allow("coach_narrative") — tier-1 pause, same cutoff as
    every other coach narrative surface (coach_narrative_orchestrator,
    elena_state_updater).
  * Fires AT MOST once per coach per calendar quarter: a MEMOIR#{quarter}
    DynamoDB sentinel is checked before generating and written after a
    successful publish — the quarterly cron can safely retry a partial run
    without ever regenerating (and re-billing) a quarter that already shipped.
    8 operational coaches x <=2 calls (one retry on a failed gate) = a hard
    ceiling of 16 Sonnet calls/quarter, budgeted around #553's "8 Sonnet-class
    calls/quarter" framing (1 call/coach in the common case).
  * ADR-104 grounded generation: every number in the output must appear in
    the coach's real facts (grounded_generation.fabricated_numbers); a
    memoir that dodges every real miss is rejected (memoir_gate.cites_a_miss).
    Fail-closed — anything that doesn't pass is dropped, not published.
  * Honest empty: a coach with no graded LEARNING# this quarter is skipped —
    there is nothing real to reckon with yet.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
import calibration_core
import grounded_generation
import memoir_gate
import persona_registry
import quarter_utils
from boto3.dynamodb.conditions import Key
from numeric import decimals_to_float, floats_to_decimal
from phase_filter import with_phase_filter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")  # narrative tier (CLAUDE.md model-tiering rule)
OUTPUT_KEY = "generated/coach_memoirs.json"
FEATURE = "coach_narrative"  # budget_guard cutoff: paused at tier 1, same as every other coach narrative

_SYSTEM_RULES = (
    "You are an AI coach character writing your own quarterly memoir for a public "
    "health-experiment site — a first-person reckoning with your own track record, not "
    "a status update. Rules you must obey:\n"
    "- First person, reflective, in your own voice. This is YOU thinking about YOUR OWN calls.\n"
    "- Use only the numbers given in your quarterly facts below; invent no figures and do no arithmetic.\n"
    "- If the facts list any REFUTED (wrong) calls this quarter, you MUST name at least one "
    "specifically and reckon with why you got it wrong — a memoir that only lists wins reads as "
    "dishonest and will be rejected before publication.\n"
    "- Correlative language only — never claim one thing CAUSED another.\n"
    "- 350 words maximum, prose only. No preamble, no sign-off, no bullet points."
)


def _learning_summary(item):
    return {
        "date": item.get("date"),
        "subdomain": item.get("subdomain"),
        "metric": item.get("metric"),
        "status": item.get("status"),
        "reason": item.get("reason"),
    }


def _stance_summary(item):
    if not item:
        return None
    return {
        "as_of": item.get("as_of") or (item.get("sk") or "").replace("STANCE#", ""),
        "headline_read": item.get("headline_read", ""),
        "how_my_read_changed": item.get("how_my_read_changed", ""),
    }


def already_generated(table, coach_id: str, quarter: str) -> bool:
    """True if a MEMOIR#{quarter} sentinel already exists for this coach —
    the quarterly regen-once gate. Pure DDB read, no Bedrock involved, so
    this is cheap to check (and to unit-test) before any inference runs."""
    try:
        item = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"MEMOIR#{quarter}"}).get("Item")
        return item is not None
    except Exception as e:
        logger.warning("[coach_memoir] gate-check %s/%s: %s", coach_id, quarter, e)
        return False  # fail-open on a transient read error — worst case is one extra call, never silent data loss


def _gather_facts(table, coach_id: str, quarter: str):
    """The coach's real quarterly record: LEARNING# within the quarter window,
    career-to-date PREDICTION# calibration (same numbers as every other
    calibration surface, #538), and the quarter's STANCE# bookends. Returns
    None when there's nothing graded yet this quarter — honest empty."""
    start_iso, end_iso = quarter_utils.quarter_bounds(quarter)
    coach_pk = f"COACH#{coach_id}"

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").between(f"LEARNING#{start_iso}", f"LEARNING#{end_iso}"),
                    "ScanIndexForward": True,
                }
            )
        )
        learnings = [decimals_to_float(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning("[coach_memoir] learnings %s: %s", coach_id, e)
        learnings = []

    if not learnings:
        return None  # nothing graded this quarter yet — nothing real to reckon with

    by_outcome = {}
    for item in learnings:
        status = item.get("status", "unknown")
        by_outcome[status] = by_outcome.get(status, 0) + 1
    decided = by_outcome.get("confirmed", 0) + by_outcome.get("refuted", 0)
    hit_rate_pct = round(100 * by_outcome.get("confirmed", 0) / decided, 1) if decided else None

    misses = [_learning_summary(i) for i in learnings if i.get("status") == "refuted"][:5]
    hits = [_learning_summary(i) for i in learnings if i.get("status") == "confirmed"][:5]

    calibration = calibration_core.score_pairs([])
    try:
        pred_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("PREDICTION#"),
                    "ScanIndexForward": False,
                    "Limit": 500,
                }
            )
        )
        pred_recs = [decimals_to_float(i) for i in pred_resp.get("Items", [])]
        calibration = calibration_core.score_pairs(calibration_core.pairs_from_prediction_records(pred_recs))
    except Exception as e:
        logger.warning("[coach_memoir] calibration %s: %s", coach_id, e)

    stance_start, stance_end = None, None
    try:
        sresp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").between(f"STANCE#{start_iso}", f"STANCE#{end_iso}"),
                    "ScanIndexForward": True,
                }
            )
        )
        stances = [decimals_to_float(i) for i in sresp.get("Items", [])]
        if stances:
            stance_start, stance_end = _stance_summary(stances[0]), _stance_summary(stances[-1])
    except Exception as e:
        logger.warning("[coach_memoir] stances %s: %s", coach_id, e)

    return {
        "quarter": quarter,
        "total_evaluations": len(learnings),
        "by_outcome": by_outcome,
        "decided_count": decided,
        "hit_rate_pct": hit_rate_pct,
        "calibration": {
            "brier": calibration.get("brier"),
            "calibration": calibration.get("calibration"),
            "scored_n": calibration.get("n"),
        },
        "misses": misses,
        "hits": hits,
        "stance_start": stance_start,
        "stance_end": stance_end,
        # raw evaluations kept for the gate (memoir_gate needs status/metric/subdomain
        # across ALL of them, not just the truncated misses[:5] shown to the model).
        "learnings_raw": learnings,
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


def _render_facts_for_prompt(facts):
    lines = [
        f"Quarter: {facts['quarter']}",
        f"Graded calls this quarter: {facts['total_evaluations']} "
        f"(confirmed={facts['by_outcome'].get('confirmed', 0)}, refuted={facts['by_outcome'].get('refuted', 0)})",
    ]
    if facts["hit_rate_pct"] is not None:
        lines.append(f"Hit rate this quarter: {facts['hit_rate_pct']}% (n={facts['decided_count']})")
    cal = facts.get("calibration") or {}
    if cal.get("scored_n"):
        lines.append(f"Career-to-date calibration: Brier {cal.get('brier')}, verdict '{cal.get('calibration')}' (n={cal.get('scored_n')})")
    if facts["misses"]:
        lines.append("Calls that were REFUTED (wrong) this quarter:")
        for m in facts["misses"]:
            lines.append(f"  - {m['date']}: {m['subdomain']}/{m['metric']} — {m['reason']}")
    if facts["hits"]:
        lines.append("Calls that were CONFIRMED (right) this quarter:")
        for h in facts["hits"]:
            lines.append(f"  - {h['date']}: {h['subdomain']}/{h['metric']} — {h['reason']}")
    if facts.get("stance_start") and facts.get("stance_end"):
        lines.append(f"Your read at the start of the quarter: {facts['stance_start'].get('headline_read')}")
        lines.append(f"Your read at the end of the quarter: {facts['stance_end'].get('headline_read')}")
        if facts["stance_end"].get("how_my_read_changed"):
            lines.append(f"How your read changed: {facts['stance_end']['how_my_read_changed']}")
    return "\n".join(lines)


def _call_model(persona, voice_rules, example, facts_text, quarter, extra_system=""):
    import bedrock_client

    sys_block = f"{_SYSTEM_RULES}\n\nYour voice rules: {voice_rules}"
    if example:
        sys_block += f"\n\nA sample of your voice:\n{example}"
    if extra_system:
        sys_block += f"\n\n{extra_system}"
    user = (
        f"You are {persona.get('name')} ({persona.get('board_role') or persona.get('domain')}). "
        f"Here is your real, graded track record for {quarter}:\n{facts_text}\n\n"
        "Write your first-person quarterly memoir — a reckoning with your own record."
    )
    body = {
        "model": MODEL,
        "max_tokens": 900,
        "system": sys_block,
        "messages": [{"role": "user", "content": user}],
    }
    resp = bedrock_client.invoke(body, model_name=MODEL)
    parts = resp.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    return text or None


def gate_check(text, facts):
    """(ok, reasons) — ADR-104 checks: no fabricated numbers, and if a real
    miss exists this quarter, the memoir must engage with at least one."""
    reasons = []
    if not (text or "").strip():
        return False, ["empty"]
    allowed = grounded_generation.allowed_numbers(facts)
    fabricated = grounded_generation.fabricated_numbers(text, allowed)
    if fabricated:
        reasons.append(f"fabricated numbers: {fabricated}")
    ok_miss, why = memoir_gate.cites_a_miss(text, facts.get("learnings_raw"))
    if not ok_miss:
        reasons.append(why)
    return (len(reasons) == 0), reasons


def _generate_memoir(persona, voice_rules, example, facts, quarter):
    """One generation + one corrective retry on gate failure. Never publishes
    a memoir that fails the gate twice — dropped, not shipped (fail-closed)."""
    facts_text = _render_facts_for_prompt(facts)
    try:
        text = _call_model(persona, voice_rules, example, facts_text, quarter)
    except Exception as e:
        logger.warning("[coach_memoir] generate failed: %s", e)
        return None, ["generation_error"]

    ok, reasons = gate_check(text, facts)
    if ok:
        return text, []

    _draft = text  # #812/#744: keep the flagged draft for retention
    logger.info("[coach_memoir] gate failed (%s) — retrying stricter", reasons)
    stricter = (
        "STRICT REWRITE REQUIRED — your previous draft failed a fact-check: "
        + "; ".join(reasons)
        + ". Use ONLY the numbers listed in your facts above, and if the facts list a REFUTED "
        "call this quarter, name that specific call and reckon with it directly."
    )
    try:
        text = _call_model(persona, voice_rules, example, facts_text, quarter, extra_system=stricter)
    except Exception as e:
        logger.warning("[coach_memoir] retry generate failed: %s", e)
        return None, reasons

    ok, reasons2 = gate_check(text, facts)
    try:  # #812/#744: a fired memoir gate is labeled eval data — retain the pair (fail-soft)
        import eval_retention

        eval_retention.retain(
            "memoir",
            "flagged_corrected" if ok else "flagged_dropped",
            draft=_draft,
            final=text if ok else "",
            findings=[{"type": "memoir_gate", "detail": r} for r in reasons],
            allowed=grounded_generation.allowed_numbers(facts),
            facts={k: v for k, v in facts.items() if k != "learnings_raw"},
            extra={"persona": persona.get("id") or persona.get("name"), "quarter": quarter},
        )
    except Exception:  # noqa: BLE001 — retention is never load-bearing
        pass
    return (text, []) if ok else (None, reasons2)


def _write_memoir_record(table, coach_id, quarter, text, facts):
    """MEMOIR#{quarter} — the idempotency sentinel AND the durable record,
    same COACH# partition as LEARNING#/PREDICTION#/STANCE# (ADR-047)."""
    item = floats_to_decimal(
        {
            "pk": f"COACH#{coach_id}",
            "sk": f"MEMOIR#{quarter}",
            "quarter": quarter,
            "text": text,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_evaluations": facts["total_evaluations"],
            "hit_rate_pct": facts["hit_rate_pct"],
            "calibration": facts["calibration"],
        }
    )
    table.put_item(Item=item)
    # #1441: generation-time archive — the gate-passed memoir text that the site
    # artifact publishes, to generated/qa_archive/. Fail-soft inside the module.
    try:
        import qa_archive

        qa_archive.archive_text("memoir", text, variant=coach_id, meta={"quarter": quarter})
    except Exception as qa_e:  # noqa: BLE001 — the archive is never load-bearing
        logger.warning("[coach_memoir] qa_archive failed (non-fatal): %s", qa_e)


def _latest_memoir(table, coach_id):
    """The most recent MEMOIR# for a coach, regardless of which run wrote it —
    used to assemble the site artifact so a partial batch run still serves a
    complete, correct payload for every coach that has ever published one."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("MEMOIR#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return decimals_to_float(items[0]) if items else None
    except Exception as e:
        logger.warning("[coach_memoir] latest lookup %s: %s", coach_id, e)
        return None


def lambda_handler(event: dict, context) -> dict:
    try:
        from budget_guard import allow as _budget_allow

        if not _budget_allow(FEATURE):
            logger.info("[coach_memoir] budget tier pauses %s — skipping", FEATURE)
            return {"skipped": True, "reason": "budget_tier"}
    except Exception:
        pass  # fail-open: a budget blip must not break the quarterly batch

    quarter = quarter_utils.previous_quarter_key(datetime.now(timezone.utc).date().isoformat())

    s3 = boto3.client("s3", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    reg = persona_registry.load_registry(s3, S3_BUCKET).get("personas", {})

    written, already, skipped, failed = [], [], [], []
    for coach_id in persona_registry.OPERATIONAL_COACH_IDS:
        if already_generated(table, coach_id, quarter):
            already.append(coach_id)
            continue

        facts = _gather_facts(table, coach_id, quarter)
        if not facts:
            skipped.append(coach_id)  # honest empty — nothing graded this quarter yet
            continue

        persona = reg.get(coach_id) or {}
        voice_rules, example = _voice(s3, persona.get("coach_config_key", coach_id))
        text, reasons = _generate_memoir(persona, voice_rules, example, facts, quarter)
        if text:
            _write_memoir_record(table, coach_id, quarter, text, facts)
            written.append(coach_id)
        else:
            logger.warning("[coach_memoir] %s dropped for %s: %s", coach_id, quarter, reasons)
            failed.append(coach_id)

    # Assemble the site artifact from the latest MEMOIR# per coach — a
    # partial run still serves a complete, coherent payload.
    memoirs = {}
    for coach_id in persona_registry.OPERATIONAL_COACH_IDS:
        latest = _latest_memoir(table, coach_id)
        if latest:
            memoirs[coach_id] = {
                "text": latest.get("text"),
                "quarter": latest.get("quarter"),
                "generated_at": latest.get("generated_at"),
            }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quarter": quarter,
        "memoirs": memoirs,
        "disclosure": (
            "AI coach quarterly memoirs — generated once per quarter from each coach's real, " "graded track record. Not medical advice."
        ),
    }
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=OUTPUT_KEY,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=3600",
    )
    logger.info("[coach_memoir] quarter=%s written=%s already=%s skipped=%s failed=%s", quarter, written, already, skipped, failed)
    return {"quarter": quarter, "written": written, "already": already, "skipped": skipped, "failed": failed}
