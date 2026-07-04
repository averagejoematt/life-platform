"""
inter_coach_dialogue_lambda.py — real inter-coach dialogue (#540).

Disagreements were detected post-hoc (one Haiku call over everyone's outputs in
coach_ensemble_digest) and no coach ever answered a colleague. This lambda gives
the ensemble's most persistent dispute an actual exchange, once a week:

  1. DETERMINISTIC selector — no LLM picks the fight. Candidates are the
     ensemble digest's ACTIVE# disagreement topics (unresolved, 2+ coaches with
     recorded positions, not aired in the last AIRING_COOLDOWN_WEEKS). Score =
     cycle_count (how many digest cycles it has persisted) + the influence-graph
     weight of the strongest edge between the two coaches. Ties break by slug.
  2. Two gated turns, Haiku, each coach in their own voice spec: coach B replies
     to coach A's SPECIFIC recorded claim; coach A gets one rejoinder to what B
     actually said. Each turn passes the ADR-104 grounding gate
     (grounded_generation: allow-listed numbers + one corrective regen) —
     ≤2 generations + ≤2 regens = ≤4 Haiku calls/week, hard.
  3. The exchange persists as an inter-coach thread
     (pk ENSEMBLE#dispute, sk THREAD#{iso-week}#{topic_slug}, panelcast-style
     turns array) and surfaces as "The dispute" via /api/coach_team; both
     coaches' state updaters record it (output_type inter_coach_dispute) so the
     exchange lands in each coach's own OUTPUT#/THREAD# history.

Budget: tier >= 1 pauses the whole run (the ensemble's own cutoff). ≤1 dispute
per ISO week — the weekly cap is enforced here (the digest runs daily).

Runs Sunday 18:00 UTC (11 AM PT) — after coach-history-summarizer (17:00), so
the week's disagreement ledger is settled.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("inter-coach-dialogue")
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

DISAGREEMENTS_PK = "ENSEMBLE#disagreements"
DISPUTE_PK = "ENSEMBLE#dispute"
INFLUENCE_PK = "ENSEMBLE#influence_graph"
AIRING_COOLDOWN_WEEKS = 4
MAX_TURN_WORDS = 120

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def iso_week(dt=None):
    d = (dt or datetime.now(timezone.utc)).isocalendar()
    return f"{d[0]}-W{d[1]:02d}"


def load_influence_weights():
    """{'a → b': weight} from DDB (S3 config fallback). Fail-soft to {}."""
    try:
        item = table.get_item(Key={"pk": INFLUENCE_PK, "sk": "CONFIG#v1"}).get("Item")
        if item and item.get("weights"):
            return {k: float(v) for k, v in item["weights"].items()}
    except Exception:
        pass
    try:
        s3 = boto3.client("s3", region_name=REGION)
        obj = s3.get_object(Bucket=S3_BUCKET, Key="config/coaches/influence_graph.json")
        return {k: float(v) for k, v in json.loads(obj["Body"].read()).get("weights", {}).items()}
    except Exception as e:
        logger.warning(f"influence graph unavailable (weights default 0): {e}")
        return {}


def edge_weight(weights, a, b):
    """Strongest directional influence between the pair (either direction)."""
    return max(float(weights.get(f"{a} → {b}", 0) or 0), float(weights.get(f"{b} → {a}", 0) or 0))


def select_dispute(topics, weights, this_week):
    """The deterministic selector. `topics` are ACTIVE# items. Returns the winning
    topic dict (with chosen coach_a/coach_b) or None when nothing qualifies."""
    candidates = []
    for t in topics:
        if t.get("status") not in (None, "unresolved"):
            continue
        aired = t.get("last_aired_week")
        if aired and _weeks_between(aired, this_week) < AIRING_COOLDOWN_WEEKS:
            continue
        coaches = [c for c in (t.get("coaches") or []) if (t.get("positions") or {}).get(c)]
        if len(coaches) < 2:
            continue
        # the pair with the strongest influence edge, deterministically ordered
        best_pair, best_w = None, -1.0
        for i in range(len(coaches)):
            for j in range(i + 1, len(coaches)):
                a, b = sorted((coaches[i], coaches[j]))
                w = edge_weight(weights, a, b)
                if w > best_w or (w == best_w and best_pair and (a, b) < best_pair):
                    best_pair, best_w = (a, b), w
        score = float(t.get("cycle_count") or 1) + best_w
        candidates.append((score, t.get("sk", ""), t, best_pair, best_w))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    _score, _sk, topic, (a, b), w = candidates[0]
    return {"topic": topic, "coach_a": a, "coach_b": b, "influence_weight": w}


def _weeks_between(week_a, week_b):
    """Whole ISO weeks from week_a to week_b ('2026-W23' strings); crude but
    monotone — good enough for a cooldown."""
    try:
        ya, wa = week_a.split("-W")
        yb, wb = week_b.split("-W")
        return (int(yb) - int(ya)) * 52 + (int(wb) - int(wa))
    except Exception:
        return AIRING_COOLDOWN_WEEKS  # unparseable marker → don't block airing


def build_turn_prompt(speaker, other, topic, other_claim, own_position, voice_rules, example, prior_reply=None):
    """(system, user) for one in-voice turn. The colleague's SPECIFIC claim is the
    prompt's centrepiece — that's the whole point of the story."""
    system = (
        f"You are {speaker['name']}, {speaker.get('board_role') or speaker.get('domain', '')} on Matthew's AI coaching board. "
        "A colleague has taken a position you disagree with. Reply to their SPECIFIC claim — quote or paraphrase the part "
        "you dispute, then make your case. Stay in your own voice. "
        f"HARD RULES: {MAX_TURN_WORDS} words maximum; use ONLY numbers that appear in the material below — never invent data, "
        "trends, or citations; disagree with the position, never the person; no greetings, open with substance."
        + (f"\n\nYour voice rules: {voice_rules}" if voice_rules else "")
        + (f"\n\nA sample in your voice:\n{example}" if example else "")
    )
    parts = [
        f"The dispute: {topic}",
        f"{other['name']}'s recorded position: {other_claim}",
        f"Your recorded position: {own_position}",
    ]
    if prior_reply:
        parts.append(f"{other['name']} just replied to you: {prior_reply}")
        parts.append("Write your one rejoinder — concede what's fair, hold what isn't.")
    else:
        parts.append("Write your reply to their claim.")
    return system, "\n\n".join(parts)


def generate_gated_turn(system, user, allowed_sources):
    """One Haiku generation + the ADR-104 grounding gate (one corrective regen).
    Returns (text, findings_left) — text None on hard failure."""
    import bedrock_client
    import grounded_generation as gg

    def _call(extra=""):
        body = {
            "model": MODEL,
            "max_tokens": 400,
            "system": system,
            "messages": [{"role": "user", "content": user + extra}],
        }
        resp = bedrock_client.invoke(body, model_name=MODEL)
        return "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()

    text = _call()
    if not text:
        return None, []
    allowed = gg.allowed_numbers(system, user, *allowed_sources)

    def findings_fn(t):
        return gg.grounding_findings(t, allowed=allowed)

    text, left, _corrected = gg.regen_once(text, findings_fn, lambda corr: _call("\n\n" + corr))
    return text, left


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


def _record_on_coach(lambda_client, coach_id, thread_text, date_str):
    """Both coaches' state updaters record the exchange (fail-soft, async)."""
    try:
        lambda_client.invoke(
            FunctionName="coach-state-updater",
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "coach_id": coach_id,
                    "output_text": thread_text,
                    "output_type": "inter_coach_dispute",
                    "generation_date": date_str,
                }
            ).encode(),
        )
    except Exception as e:
        logger.warning(f"state-updater invoke failed for {coach_id}: {e}")


def lambda_handler(event: dict, context) -> dict:
    # Tier gate: the dispute is a luxury — first thing paused (issue: tier-1).
    try:
        from budget_guard import current_tier

        tier = current_tier()
        if tier >= 1:
            logger.info(f"budget tier {tier} >= 1 — dispute paused")
            return {"skipped": "budget", "tier": tier}
    except Exception:
        pass  # fail-open: a budget blip must not block forever

    this_week = iso_week()
    # ≤1 dispute/week, enforced here (the digest that feeds us runs daily).
    existing = table.query(
        KeyConditionExpression=Key("pk").eq(DISPUTE_PK) & Key("sk").begins_with(f"THREAD#{this_week}"),
        Limit=1,
    ).get("Items", [])
    if existing:
        return {"skipped": "already_aired", "week": this_week}

    topics = table.query(
        KeyConditionExpression=Key("pk").eq(DISAGREEMENTS_PK) & Key("sk").begins_with("ACTIVE#"),
    ).get("Items", [])
    weights = load_influence_weights()
    pick = select_dispute(topics, weights, this_week)
    if not pick:
        return {"skipped": "no_qualifying_dispute", "topics_seen": len(topics)}

    topic = pick["topic"]
    a_id, b_id = pick["coach_a"], pick["coach_b"]
    positions = topic.get("positions") or {}
    topic_text = topic.get("topic", "")

    s3 = boto3.client("s3", region_name=REGION)
    import persona_registry

    reg = persona_registry.load_registry(s3, S3_BUCKET).get("personas", {})
    pa = reg.get(a_id) or {"name": a_id}
    pb = reg.get(b_id) or {"name": b_id}
    va_rules, va_ex = _voice(s3, pa.get("coach_config_key", a_id))
    vb_rules, vb_ex = _voice(s3, pb.get("coach_config_key", b_id))

    # Turn 1 — B answers A's specific claim.
    sys1, user1 = build_turn_prompt(pb, pa, topic_text, positions.get(a_id, ""), positions.get(b_id, ""), vb_rules, vb_ex)
    reply_b, left1 = generate_gated_turn(sys1, user1, [positions.get(a_id, ""), positions.get(b_id, "")])
    if not reply_b:
        return {"skipped": "generation_failed", "turn": 1}

    # Turn 2 — A's one rejoinder to what B actually said.
    sys2, user2 = build_turn_prompt(
        pa, pb, topic_text, positions.get(b_id, ""), positions.get(a_id, ""), va_rules, va_ex, prior_reply=reply_b
    )
    reply_a, left2 = generate_gated_turn(sys2, user2, [positions.get(a_id, ""), positions.get(b_id, ""), reply_b])

    now = datetime.now(timezone.utc)
    turns = [
        {"speaker": a_id, "name": pa.get("name", a_id), "line": positions.get(a_id, ""), "kind": "position"},
        {"speaker": b_id, "name": pb.get("name", b_id), "line": reply_b, "kind": "reply", "gate_findings_left": len(left1)},
    ]
    if reply_a:
        turns.append(
            {"speaker": a_id, "name": pa.get("name", a_id), "line": reply_a, "kind": "rejoinder", "gate_findings_left": len(left2)}
        )

    slug = topic.get("sk", "ACTIVE#dispute").replace("ACTIVE#", "")[:60]
    thread_sk = f"THREAD#{this_week}#{slug}"
    table.put_item(
        Item={
            "pk": DISPUTE_PK,
            "sk": thread_sk,
            "record_type": "inter_coach_thread",
            "week": this_week,
            "topic": topic_text,
            "topic_slug": slug,
            "coach_a": a_id,
            "coach_b": b_id,
            "influence_weight": str(pick["influence_weight"]),
            "cycle_count": int(topic.get("cycle_count") or 1),
            "source_sk": topic.get("sk"),
            "turns": turns,
            "created_at": now.isoformat(),
            "status": "aired",
        }
    )
    # Mark the topic aired so the selector rotates disputes.
    try:
        table.update_item(
            Key={"pk": DISAGREEMENTS_PK, "sk": topic.get("sk")},
            UpdateExpression="SET last_aired_week = :w, dispute_ref = :r",
            ExpressionAttributeValues={":w": this_week, ":r": thread_sk},
        )
    except Exception as e:
        logger.warning(f"could not mark topic aired: {e}")

    # Both coaches remember the exchange.
    lambda_client = boto3.client("lambda", region_name=REGION)
    thread_text = f"Inter-coach dispute — {topic_text}\n\n" + "\n\n".join(f"{t['name']}: {t['line']}" for t in turns)
    date_str = now.strftime("%Y-%m-%d")
    _record_on_coach(lambda_client, a_id, thread_text, date_str)
    _record_on_coach(lambda_client, b_id, thread_text, date_str)

    result = {"week": this_week, "topic": topic_text[:80], "coach_a": a_id, "coach_b": b_id, "turns": len(turns)}
    logger.info(json.dumps(result))
    return result
