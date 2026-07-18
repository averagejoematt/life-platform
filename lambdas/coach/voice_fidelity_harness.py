"""
voice_fidelity_harness.py — the blind voice-fidelity harness (#545, epic #526).

Coach output claims to be "the voice of a distinct persona," but nothing had ever
measured whether that's actually true — the Turing-test property the coaching
program's north star names explicitly. This runs monthly:

  1. Sample a couple of each operational coach's most recent real COACH#{id}
     OUTPUT# records (an actual board-answer / brief-narrative passage, not a
     synthetic foil — cheaper and avoids ever generating extra content just to
     measure content).
  2. Strip attribution and hand each raw passage to a panel of 3 Haiku judges
     (varied temperature so the panel isn't 3 copies of one guess), each of whom
     picks which of the 8 operational coaches most likely wrote it.
  3. Majority-vote the panel (voice_fidelity_core.majority_guess) and score the
     accumulated judgment set against ground truth (voice_fidelity_core.score_run)
     — deterministic math on the classifier's accuracy, never an LLM's subjective
     opinion of "does this sound right."
  4. Persist this run's judgments (so next month's scoreboard is a growing
     cumulative sample, like the calibration ledger, not a fresh coin flip every
     time) and the recomputed scoreboard — confusion matrix, per-coach
     distinguishability, worst-confused pair — at VOICEFIDELITY#scoreboard/latest.

Budget: tier >= 1 pauses the whole run (a monthly luxury metric — same cutoff as
the inter-coach dispute in inter_coach_dialogue_lambda.py). At most 8 coaches ×
2 samples × 3-judge panel = 48 Haiku calls/month, matching the epic's guardrail.

Public surface: /api/voice_fidelity (site-api) -> /method/voice-fidelity/.

Cross-phase (ADR-077): this measures the COACHING ENGINE's design, not a run of
the experiment, so — like the calibration scoreboard — it must survive a reset.
phase_taxonomy classifies the "VOICEFIDELITY#" pk prefix as CROSS_PHASE, even
though the COACH#.../OUTPUT# records it samples FROM are experiment-scoped.

Runs 1st of the month, 15:00 UTC (8:00 AM PT) — fixed UTC, no DST drift.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
import persona_registry
import voice_fidelity_core as vfc
from boto3.dynamodb.conditions import Key
from numeric import floats_to_decimal  # bundled shared module: canonical float->Decimal (#1207)
from phase_filter import with_phase_filter  # ADR-058 (harmless no-op here: these records never set `phase`)

logger = logging.getLogger("voice-fidelity-harness")
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

SCOREBOARD_PK = "VOICEFIDELITY#scoreboard"
SAMPLES_PER_COACH = 2
PANEL_TEMPERATURES = (0.1, 0.4, 0.7)  # panel diversity — not 3 copies of one guess
MIN_PASSAGE_CHARS = 200  # skip near-empty outputs — nothing there to judge
PASSAGE_TRUNCATE_CHARS = 1400  # bounds prompt cost; ~2-3 paragraphs is plenty of voice signal

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def _run_month(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m")


def _sample_recent_outputs(coach_id, n=SAMPLES_PER_COACH, lookback=8):
    """Most recent OUTPUT# records for a coach with enough text to judge.

    Reads a few more than `n` (lookback) so short/empty outputs can be skipped
    without an extra round trip. Returns at most `n` dicts:
      {"coach_id", "sample_date", "passage"} (passage truncated for prompt cost).
    """
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#"),
                    "ScanIndexForward": False,
                    "Limit": lookback,
                }
            )
        )
        items = resp.get("Items", [])
    except Exception as e:
        logger.warning("sample fetch failed for %s: %s", coach_id, e)
        return []

    picked = []
    for item in items:
        content = str(item.get("content") or "").strip()
        if len(content) < MIN_PASSAGE_CHARS:
            continue
        picked.append(
            {
                "coach_id": coach_id,
                "sample_date": str(item.get("sk", "")).replace("OUTPUT#", "").split("#")[0] or "unknown",
                "passage": content[:PASSAGE_TRUNCATE_CHARS],
            }
        )
        if len(picked) >= n:
            break
    return picked


_JUDGE_SYSTEM = (
    "You are a linguistic-forensics judge for a personal health-coaching platform. It runs 8 AI "
    "coach personas, each meant to have a genuinely distinct written voice (vocabulary, sentence "
    "rhythm, structural habits, and domain framing). You will read ONE passage with every "
    "identifying label stripped. Guess which coach most likely wrote it. You may use domain cues "
    "(the topic a coach usually covers) as evidence, but say so plainly in your reasoning when "
    "that's what's driving the guess — a coach who is identifiable only by TOPIC, not by HOW they "
    "write, is exactly the failure mode this test exists to catch.\n\n"
    'Return ONLY valid JSON: {"guess": "<coach_id from the roster>", "confidence": 0.0-1.0, '
    '"reasoning": "<one sentence>"}'
)


def _build_user_message(candidates, passage):
    roster = "\n".join(f"- {c['coach_id']}: {c.get('name', c['coach_id'])} — {c.get('domain', '')}" for c in candidates)
    return f"## Roster\n{roster}\n\n## Blinded passage\n---\n{passage}\n---\n\nWho wrote it?"


def _parse_vote(text, valid_ids):
    """Best-effort JSON extraction (mirrors the platform's ```json-fence tolerance
    used elsewhere, e.g. coach_quality_gate._call_haiku). Returns {} on anything
    that doesn't parse to a valid-roster guess — a malformed panelist response
    must never crash the run or count as a phantom vote."""
    raw = (text or "").strip()
    if "```" in raw:
        fence = "```json" if "```json" in raw else "```"
        start = raw.find(fence) + len(fence)
        end = raw.find("```", start)
        if end > start:
            raw = raw[start:end].strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    guess = parsed.get("guess")
    if guess not in valid_ids:
        return {}
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return {"guess": guess, "confidence": confidence}


def _classify_once(candidates, passage, temperature):
    import bedrock_client

    valid_ids = {c["coach_id"] for c in candidates}
    body = {
        "model": MODEL,
        "max_tokens": 200,
        "temperature": temperature,
        "system": _JUDGE_SYSTEM,
        "messages": [{"role": "user", "content": _build_user_message(candidates, passage)}],
    }
    resp = bedrock_client.invoke(body, model_name=MODEL)
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict))
    return _parse_vote(text, valid_ids)


def _run_panel(candidates, passage):
    """3-judge Haiku panel over one blinded passage. A single panelist's failure
    (throttle, malformed JSON) just shrinks the panel — never aborts the sample."""
    votes = []
    for temperature in PANEL_TEMPERATURES:
        try:
            vote = _classify_once(candidates, passage, temperature)
        except Exception as e:
            logger.warning("panel call failed (temp=%s): %s", temperature, e)
            vote = {}
        if vote:
            votes.append(vote)
    return votes


def _load_candidates():
    """The 8 operational coaches — id, display name, domain. persona_registry
    falls back to the local config/personas.json if S3 is unavailable, same
    defensive pattern used across the rest of the coach-intelligence tier."""
    s3 = boto3.client("s3", region_name=REGION)
    people = persona_registry.personas(s3, S3_BUCKET)
    return [
        {"coach_id": coach_id, "name": people.get(coach_id, {}).get("name", coach_id), "domain": people.get(coach_id, {}).get("domain", "")}
        for coach_id in persona_registry.OPERATIONAL_COACH_IDS
    ]


def _load_cumulative_judgments(coach_ids):
    """All persisted JUDGMENT# rows across every coach — the scoreboard is
    cumulative (like the calibration ledger), not a single month's tiny sample.
    Strongly consistent so a run's own just-written judgments are counted in the
    same invocation (cf. #468's strongly-consistent sentinel read — the same
    read-your-writes gap, one commit ago in this repo)."""
    judgments = []
    for coach_id in coach_ids:
        try:
            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"VOICEFIDELITY#{coach_id}") & Key("sk").begins_with("JUDGMENT#"),
                        "ConsistentRead": True,
                        "Limit": 500,
                    }
                )
            )
            for item in resp.get("Items", []):
                judgments.append({"actual_coach_id": item.get("actual_coach_id"), "predicted_coach_id": item.get("predicted_coach_id")})
        except Exception as e:
            logger.warning("judgment fetch failed for %s: %s", coach_id, e)
    return judgments


def lambda_handler(event, context=None):
    event = event or {}

    # Tier gate: a monthly luxury metric — first thing paused (same cutoff as the
    # inter-coach dispute). Fail-open: an SSM blip must not silently starve the run.
    try:
        from budget_guard import current_tier

        tier = current_tier()
        if tier >= 1:
            logger.info("budget tier %s >= 1 — voice-fidelity harness paused", tier)
            return {"skipped": "budget", "tier": tier}
    except Exception:
        pass

    run_month = _run_month()
    if not event.get("force"):
        try:
            already = table.get_item(Key={"pk": SCOREBOARD_PK, "sk": f"RUN#{run_month}"}).get("Item")
        except Exception as e:
            logger.warning("run-marker read failed (proceeding): %s", e)
            already = None
        if already:
            return {"skipped": "already_ran_this_month", "run_month": run_month}

    candidates = _load_candidates()
    if len(candidates) < 2:
        return {"skipped": "roster_unavailable"}
    candidate_ids = [c["coach_id"] for c in candidates]

    now = datetime.now(timezone.utc)
    new_samples = 0
    for candidate in candidates:
        coach_id = candidate["coach_id"]
        for idx, sample in enumerate(_sample_recent_outputs(coach_id)):
            votes = _run_panel(candidates, sample["passage"])
            predicted, agreement, mean_confidence = vfc.majority_guess(votes)
            if predicted is None:
                continue  # every panelist failed to return a usable guess — no judgment to record
            judgment = {
                "pk": f"VOICEFIDELITY#{coach_id}",
                "sk": f"JUDGMENT#{run_month}#{idx}",
                "actual_coach_id": coach_id,
                "predicted_coach_id": predicted,
                "sample_date": sample["sample_date"],
                "panel_size": len(votes),
                "agreement": agreement,
                "mean_confidence": mean_confidence,
                "created_at": now.isoformat(),
            }
            try:
                table.put_item(Item=floats_to_decimal(judgment))
                new_samples += 1
            except Exception as e:
                logger.warning("judgment write failed for %s: %s", coach_id, e)

    all_judgments = _load_cumulative_judgments(candidate_ids)
    scoreboard = vfc.score_run(all_judgments, candidate_pool_size=len(candidates))
    scoreboard["run_month"] = run_month
    scoreboard["updated_at"] = now.isoformat()
    scoreboard["new_samples_this_run"] = new_samples

    try:
        table.put_item(Item=floats_to_decimal({"pk": SCOREBOARD_PK, "sk": "latest", **scoreboard}))
        table.put_item(
            Item=floats_to_decimal(
                {
                    "pk": SCOREBOARD_PK,
                    "sk": f"RUN#{run_month}",
                    "new_samples": new_samples,
                    "cumulative_n": scoreboard["n"],
                    "accuracy_pct": scoreboard["accuracy_pct"],
                    "created_at": now.isoformat(),
                }
            )
        )
    except Exception as e:
        logger.error("scoreboard persist failed: %s", e)

    result = {
        "run_month": run_month,
        "new_samples": new_samples,
        "cumulative_n": scoreboard["n"],
        "accuracy_pct": scoreboard["accuracy_pct"],
        "verdict": scoreboard["verdict"],
    }
    logger.info(json.dumps(result))
    return result
