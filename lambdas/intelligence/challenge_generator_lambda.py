"""
challenge_generator_lambda.py — AI-Powered Challenge Generation Pipeline

Runs weekly (Sunday 3 PM PT, after hypothesis engine + weekly correlations).
Generates 0-5 challenge candidates from 5 sources:

  1. journal_mining   — Scans enriched journal for recurring avoidance flags / themes
  2. data_signal      — Reads character sheet for weak pillars, habit scores for broken streaks
  3. hypothesis_graduate — Confirmed hypotheses that should become behavioural challenges
  4. science_scan     — AI suggests evidence-based challenges from current research context
  5. (manual/community — handled via MCP tools, not this Lambda)

Pipeline:
  1. Gather context: 14d journal entries, character sheet, habit scores, active challenges
  2. Build structured prompt with all context
  3. Call Claude Sonnet → JSON response with 0-5 challenge candidates
  4. Dedup against existing challenges
  5. Write candidates to DDB SOURCE#challenges partition (status='candidate')
  6. Matthew reviews and activates via MCP tool or website

DDB pattern:
  pk = USER#matthew#SOURCE#challenges
  sk = CHALLENGE#<slug>_<date>

EventBridge: cron(0 22 ? * SUN *)  → 3 PM PT / 10 PM UTC on Sundays

Cost: ~$0.05/week (one Sonnet call + DDB reads/writes)
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from common import digest_utils  # shared query_range implementations (#970)
from common.numeric import floats_to_decimal  # bundled shared module: canonical float->Decimal (#1207)
from experiment.phase_filter import singleton_visible, source_reads_cross_phase, with_phase_filter  # ADR-058 (#2109/#2221)

try:
    from common.platform_logger import get_logger

    logger = get_logger("challenge-generator")
except ImportError:
    logger = logging.getLogger("challenge-generator")
    logger.setLevel(logging.INFO)

try:
    from ai.ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
S3_BUCKET = os.environ["S3_BUCKET"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")

CHALLENGES_PK = f"USER#{USER_ID}#SOURCE#challenges"
HYPOTHESES_PK = f"USER#{USER_ID}#SOURCE#hypotheses"
CHARACTER_PK = f"USER#{USER_ID}#SOURCE#character_sheet"
HABIT_SCORES_PK = f"USER#{USER_ID}#SOURCE#habit_scores"

MAX_NEW_CHALLENGES = 5
LOOKBACK_DAYS = 14

# SYSTEM_PROMPT states the contract as "Duration: 7-30 days". These are that
# sentence, in code, so the writer cannot ship a horizon the platform never
# agreed to (#2221) — the same guard domain/difficulty/source already have.
MIN_DURATION_DAYS = 7
MAX_DURATION_DAYS = 30


class MalformedCandidate(ValueError):
    """A model-supplied candidate the writer cannot honestly store (#2221).

    Distinct from an infrastructure failure on purpose: the handler skips a
    malformed candidate and keeps the rest of the batch, while a DynamoDB or
    Bedrock error still surfaces as ``status='error'`` rather than being
    swallowed into a partial success.
    """


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from common.digest_utils import d2f  # shared bundled helpers (#970)


def query_range(source, start_date, end_date):
    """Query DynamoDB for a source's data in a date range, as a list.

    #970: consolidated onto the shared paginated implementation — the old local
    copy did not paginate (1MB-page truncation) and did not apply the ADR-058
    phase filter (every platform DDB read must be phase-scoped); both fixed by
    consolidation. Fail-soft ([] on error) preserved.

    #2221 (#2109 class): the phase filter is derived per source rather than
    applied unconditionally. notion / whoop / withings are RAW_TIMESERIES — kept
    across resets and tagged ``phase=pilot`` for every pre-genesis day — so a
    blanket filter truncated this reader's 14-day windows to the CYCLE'S AGE
    (genesis 2026-08-03 meant a 4-day "fourteen day" HRV/journal/weight window)
    while the prompt still called them fourteen days. habit_scores stays filtered:
    it is EXPERIMENT_SCOPED derived intelligence the reset tombstones on purpose.
    """
    try:
        return digest_utils.query_range_list(
            table,
            source,
            start_date,
            end_date,
            user_id=USER_ID,
            include_pilot=source_reads_cross_phase(source, user_id=USER_ID),
        )
    except Exception as e:
        logger.warning(f"query_range({source}) failed: {e}")
        return []


def slug(name):
    """A key-safe slug that is never empty.

    The trailing fallback covers both halves of the old divergence (#2221): a
    falsy name AND a name that slugs away entirely ("!!!"), either of which
    produced ``CHALLENGE#_<date>`` — a keyless row on the reader-facing
    challenges surface that a second such candidate silently collides with.
    """
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:50] or "challenge"


# ══════════════════════════════════════════════════════════════════════════════
# DATA GATHERING
# ══════════════════════════════════════════════════════════════════════════════


def gather_context():
    """Gather all context needed for challenge generation."""
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=LOOKBACK_DAYS - 1)).strftime("%Y-%m-%d")

    context = {}

    # 1. Journal entries (enriched fields only — themes, avoidance, emotions)
    journal_entries = query_range("notion", start_date, end_date)
    if journal_entries:
        journal_summary = []
        for entry in journal_entries:
            j = {
                "date": entry.get("sk", "").replace("DATE#", "").split("#")[0],
                "template": entry.get("template", ""),
            }
            # Enriched fields — the gold for challenge mining
            for field in [
                "enriched_themes",
                "enriched_avoidance_flags",
                "enriched_growth_signals",
                "enriched_emotions",
                "enriched_cognitive_patterns",
                "enriched_stress",
                "enriched_mood",
                "enriched_energy",
                "enriched_primary_defense",
                # #505 v2: behaviors + author-asserted causal hints replace the
                # retired defense_context as the challenge-mining gold.
                "enriched_behaviors",
                "enriched_causal_hints",
            ]:
                val = entry.get(field)
                if val:
                    j[field] = val
            # Raw text snippets for context (truncated)
            for field in ["win_of_the_day", "what_drained_me", "todays_intention", "biggest_challenge", "what_would_i_change"]:
                val = entry.get(field, "")
                if val:
                    j[field] = val[:200]
            journal_summary.append(j)
        context["journal_14d"] = journal_summary
        logger.info(f"Journal: {len(journal_summary)} entries")

    # 2. Character sheet — latest pillar scores
    from boto3.dynamodb.conditions import Key

    try:
        # ADR-058 (#2221): character_sheet is EXPERIMENT_SCOPED, so the wiped prior
        # cycle's rows must not read as live. Limit=1 is safe alongside the filter
        # here — DynamoDB applies Limit before the FilterExpression, but this scan
        # is descending over DATE# keys and every pilot row predates genesis, so
        # the newest row is current-cycle whenever a current-cycle row exists at
        # all. Before the first character-sheet run of a fresh cycle the read
        # honestly returns nothing rather than the previous cycle's level.
        cs_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(CHARACTER_PK) & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        cs_items = d2f(cs_resp.get("Items", []))
        if cs_items:
            cs = cs_items[0]
            pillars = {}
            for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                pdata = cs.get(f"pillar_{p}", {})
                if pdata:
                    pillars[p] = {
                        "level": pdata.get("level"),
                        "tier": pdata.get("tier"),
                        "raw_score": pdata.get("raw_score"),
                        "level_score": pdata.get("level_score"),
                    }
            context["character"] = {
                "overall_level": cs.get("character_level"),
                "overall_tier": cs.get("character_tier"),
                "pillars": pillars,
            }
            logger.info(f"Character: level {cs.get('character_level')}")
    except Exception as e:
        logger.warning(f"Character sheet load failed: {e}")

    # 3. Habit scores — recent tier completion + missed T0 habits
    habit_items = query_range("habit_scores", start_date, end_date)
    if habit_items:
        missed_t0_freq = {}
        avg_t0_pct = []
        for h in habit_items:
            t0_pct = h.get("tier0_pct")
            if t0_pct is not None:
                avg_t0_pct.append(float(t0_pct))
            for missed in h.get("missed_tier0") or []:
                missed_t0_freq[missed] = missed_t0_freq.get(missed, 0) + 1

        context["habits"] = {
            "avg_tier0_completion": round(sum(avg_t0_pct) / len(avg_t0_pct) * 100) if avg_t0_pct else None,
            "most_missed_tier0": sorted(missed_t0_freq.items(), key=lambda x: -x[1])[:5],
            "days_with_data": len(habit_items),
        }

        # Vice streaks
        latest_habit = habit_items[-1] if habit_items else {}
        vice_streaks = latest_habit.get("vice_streaks", {})
        if vice_streaks:
            context["habits"]["vice_streaks"] = vice_streaks
        logger.info(f"Habits: {len(habit_items)} days, T0 avg={context['habits'].get('avg_tier0_completion')}%")

    # 4. Confirmed hypotheses — candidates for challenge graduation
    try:
        # ADR-058 (#2221): hypotheses is EXPERIMENT_SCOPED — the wipe tombstones and
        # phase-tags the prior cycle's bets, which must not graduate into this
        # cycle's challenges.
        hyp_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "ScanIndexForward": False,
                }
            )
        )
        # #2221: 'confirming' means SUPPORTED BUT STILL UNDER TEST — the engine
        # itself classifies it as an OPEN bet (hypothesis_engine_lambda L1140,
        # phase_taxonomy.OPEN_BET_STATUSES). Handing it to the writer under the
        # prompt header "CONFIRMED HYPOTHESES" made the challenge assert a finding
        # the data has not yet supported (ADR-104/105).
        confirmed = [d2f(h) for h in hyp_resp.get("Items", []) if h.get("status") == "confirmed" and h.get("check_count", 0) >= 2]
        if confirmed:
            context["confirmed_hypotheses"] = [
                {
                    "hypothesis": h.get("hypothesis"),
                    "domains": h.get("domains"),
                    "actionable_if_confirmed": h.get("actionable_if_confirmed"),
                }
                for h in confirmed[:5]
            ]
            logger.info(f"Confirmed hypotheses: {len(confirmed)}")
    except Exception as e:
        logger.warning(f"Hypothesis load failed: {e}")

    # 5. Existing challenges — for dedup
    try:
        # ADR-058 (#2221): challenges is EXPERIMENT_SCOPED. The query filter hides
        # phase-tagged rows; singleton_visible on top also drops TOMBSTONED ones,
        # which is what makes the two halves of this Lambda agree — store_challenge
        # already treats a tombstoned collision as ABSENT (#1969, "the fresh cycle
        # may legitimately re-issue the challenge"). Without it the prompt forbade
        # the model to propose exactly what the writer would then re-issue.
        ch_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(CHALLENGES_PK) & Key("sk").begins_with("CHALLENGE#"),
                    "ScanIndexForward": False,
                }
            )
        )
        existing = [d2f(c) for c in ch_resp.get("Items", []) if singleton_visible(c)]
        context["existing_challenges"] = [{"name": c.get("name"), "status": c.get("status"), "domain": c.get("domain")} for c in existing]
        logger.info(f"Existing challenges: {len(existing)}")
    except Exception as e:
        logger.warning(f"Challenge load failed: {e}")

    # 6. Basic health metrics for science scan context
    whoop_data = query_range("whoop", start_date, end_date)
    if whoop_data:
        avg_hrv = [w.get("hrv") for w in whoop_data if w.get("hrv")]
        avg_recovery = [w.get("recovery_score") for w in whoop_data if w.get("recovery_score")]
        context["health_snapshot"] = {
            "avg_hrv": round(sum(avg_hrv) / len(avg_hrv), 1) if avg_hrv else None,
            "avg_recovery": round(sum(avg_recovery) / len(avg_recovery), 1) if avg_recovery else None,
        }

    withings_data = query_range("withings", start_date, end_date)
    if withings_data:
        weights = [w.get("weight_lbs") for w in withings_data if w.get("weight_lbs")]
        if weights:
            context.setdefault("health_snapshot", {})["latest_weight"] = weights[-1]

    return context


# ══════════════════════════════════════════════════════════════════════════════
# AI GENERATION
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a challenge generation engine for a personal health platform.
Your job is to create 1-5 short-term challenge candidates based on the data provided.

CHALLENGE PHILOSOPHY:
- Challenges are ACTION, not science. No hypothesis required.
- Duration: 7-30 days (prefer 7 or 14 for first-timers)
- Each challenge targets a SPECIFIC weakness revealed by the data
- Challenges should be achievable but uncomfortable
- Every challenge must have a clear daily action and success criteria

SOURCES YOU CAN DRAW FROM:
1. JOURNAL MINING: Look for recurring avoidance flags, themes, defense mechanisms.
   If "late-night snacking" appears 4+ times → create a "No eating after 8pm" challenge.
   If "skipped workout" appears 3+ times → create a daily movement challenge.

2. DATA SIGNALS: Look at character sheet pillar scores.
   If a pillar is below level 30 or in "Foundation" tier → challenge for that domain.
   If Tier 0 habits are being missed → create a challenge around the most-missed habit.
   If vice streaks are short → create a streak extension challenge.

3. HYPOTHESIS GRADUATES: If a confirmed hypothesis has an actionable recommendation,
   convert it into a behavioural challenge.

4. SCIENCE SCAN: Based on the person's current health snapshot (weight, HRV, recovery),
   suggest 1 evidence-based challenge from sports science, nutrition, or longevity research.
   Cite the research basis briefly.

RULES:
- Do NOT create challenges that duplicate existing active/candidate challenges
- Each challenge must specify: name, description, source, source_detail, domain, difficulty, duration_days, protocol, success_criteria, hoped_outcome
- hoped_outcome states the falsifiable expected result if the challenge works — what should visibly
  change by the end of the run, in one honest sentence. Modest is fine; "no visible signal is the
  likely outcome" is a valid expectation. Never promise a number the duration can't produce.
- Domain must be one of: sleep, movement, nutrition, supplements, mental, social, discipline, metabolic, general
- Difficulty: easy (habit reinforcement), moderate (behaviour change), hard (significant discomfort)
- Return 0 challenges if there's insufficient data or no clear signal. Quality over quantity.

Respond ONLY with valid JSON:
{
  "challenges": [
    {
      "name": "Short punchy name",
      "description": "Why this challenge exists — the motivation from data",
      "source": "journal_mining|data_signal|hypothesis_graduate|science_scan",
      "source_detail": "Specific data trigger (e.g. 'avoidance_flag: late_night_snacking ×6 in 14d')",
      "domain": "movement",
      "difficulty": "moderate",
      "duration_days": 7,
      "protocol": "Exactly what to do each day",
      "success_criteria": "How to know you succeeded",
      "hoped_outcome": "The falsifiable expected result if it works — honest, duration-sized",
      "tags": ["tag1", "tag2"],
      "verification_method": "self_report|metric_auto|hybrid",
      "metric_targets": {}
    }
  ],
  "reasoning": "Brief explanation of why these challenges were chosen"
}"""


def _phase_context_block():
    """#1138/#1118: the ONE mandatory experiment-phase grounding block for the
    generation prompt — hoped_outcome is AI-written narrative, so the writer must
    know what day/phase it is (a Day-2 challenge can't hope for a 30-day trend).
    No-arg build reads EXPERIMENT_START_DATE + today (PT). Fail-soft to "" only
    on an import/runtime error — the bundle always ships ai_context, and
    tests/test_phase_context_coverage.py pins the block's presence."""
    try:
        from ai.ai_context import build_experiment_phase_context, format_experiment_phase_context

        return format_experiment_phase_context(build_experiment_phase_context())
    except Exception as e:  # noqa: BLE001 — grounding must never hard-fail generation
        logger.warning("phase-context block unavailable (non-blocking): %s", e)
        return ""


def build_generation_prompt(context):
    """Build the user message for challenge generation — extracted pure so the
    #1138 phase-context coverage suite can drive it offline."""
    phase_block = _phase_context_block()
    return f"""Here is the current platform data for challenge generation.
Today is {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ({datetime.now(timezone.utc).strftime('%A')}).
{phase_block}
JOURNAL ENTRIES (14 days, enriched fields):
{json.dumps(context.get('journal_14d', []), indent=2, default=str)[:4000]}

CHARACTER SHEET:
{json.dumps(context.get('character', {}), indent=2, default=str)}

HABIT DATA:
{json.dumps(context.get('habits', {}), indent=2, default=str)}

CONFIRMED HYPOTHESES:
{json.dumps(context.get('confirmed_hypotheses', []), indent=2, default=str)}

HEALTH SNAPSHOT:
{json.dumps(context.get('health_snapshot', {}), indent=2, default=str)}

EXISTING CHALLENGES (do NOT duplicate):
{json.dumps(context.get('existing_challenges', []), indent=2, default=str)}

Generate 1-5 challenge candidates based on the strongest signals in this data.
If no clear signal exists, return 0 challenges. Quality over quantity."""


def generate_challenges(context):
    """Call Claude Sonnet to generate challenge candidates."""
    # COST-OPT-2: the daily-changing phase block rides the USER message — the
    # cache_control-wrapped SYSTEM_PROMPT must stay byte-stable.
    user_message = build_generation_prompt(context)

    payload = json.dumps(
        {
            "model": AI_MODEL,
            "max_tokens": 2000,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_message}],
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw (Bedrock).
    try:
        from common.retry_utils import call_anthropic_raw

        resp = call_anthropic_raw(req)
        raw = resp["content"][0]["text"].strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        # AI-3 validation
        if _HAS_AI_VALIDATOR:
            val_result = validate_ai_output(raw, AIOutputType.GENERIC)
            if val_result.blocked:
                logger.error("[AI-3] challenge generation blocked: %s", val_result.block_reason)
                return None
        return json.loads(raw.strip())
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Challenge parse error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE
# ══════════════════════════════════════════════════════════════════════════════


def _coerce_duration(challenge: dict) -> int:
    """The model's duration_days, bounded to the window SYSTEM_PROMPT promises.

    #2221: this was a bare ``int(challenge.get("duration_days", 7))`` — the only
    model-supplied enum-ish field with no allowlist. An out-of-range NUMBER is
    clamped (the model asserted a horizon; the platform bounds it), but a
    non-numeric one is MalformedCandidate rather than silently defaulted: a
    hoped_outcome written against "seven" was written against an unknown horizon,
    and inventing 7 for it would publish a claim the model never made.
    """
    if "duration_days" not in challenge:
        return MIN_DURATION_DAYS
    try:
        days = int(challenge["duration_days"])
    except (TypeError, ValueError) as e:
        raise MalformedCandidate(f"duration_days is not a number: {challenge['duration_days']!r}") from e
    clamped = max(MIN_DURATION_DAYS, min(MAX_DURATION_DAYS, days))
    if clamped != days:
        logger.warning(
            "duration_days %s outside the documented %s-%s window; clamped to %s", days, MIN_DURATION_DAYS, MAX_DURATION_DAYS, clamped
        )
    return clamped


def store_challenge(challenge: dict):
    """Write a challenge candidate to DynamoDB."""
    now = datetime.now(timezone.utc)
    # #2221: `.get("name", ...)` only defaults on an ABSENT key — a model returning
    # name="" kept the empty string and slugged to a keyless CHALLENGE#_<date>.
    name = (challenge.get("name") or "").strip() or "Unnamed Challenge"
    date_str = now.strftime("%Y-%m-%d")
    duration_days = _coerce_duration(challenge)
    ch_slug = slug(name)  # the module's own guarded helper, not a second inline copy
    challenge_id = f"{ch_slug}_{date_str}"
    sk = f"CHALLENGE#{challenge_id}"

    # Dedup check. #1969 (#946 class): challenges is EXPERIMENT_SCOPED — a
    # TOMBSTONED colliding row is the wiped prior cycle's archive (only possible
    # when a reset landed the same day), treated as absent: the fresh cycle may
    # legitimately re-issue the challenge, and the put below restamps the record.
    existing = table.get_item(Key={"pk": CHALLENGES_PK, "sk": sk}).get("Item")
    if singleton_visible(existing):
        logger.info(f"Skipping duplicate challenge: {challenge_id}")
        return None

    # Valid domains
    valid_domains = ["sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline", "metabolic", "general"]
    domain = challenge.get("domain", "general")
    if domain not in valid_domains:
        domain = "general"

    valid_diff = ["easy", "moderate", "hard"]
    difficulty = challenge.get("difficulty", "moderate")
    if difficulty not in valid_diff:
        difficulty = "moderate"

    valid_sources = ["journal_mining", "data_signal", "hypothesis_graduate", "science_scan"]
    source = challenge.get("source", "science_scan")
    if source not in valid_sources:
        source = "science_scan"

    item = {
        "pk": CHALLENGES_PK,
        "sk": sk,
        "challenge_id": challenge_id,
        "name": name,
        "description": challenge.get("description", ""),
        "source": source,
        "source_detail": challenge.get("source_detail", ""),
        "domain": domain,
        "difficulty": difficulty,
        "duration_days": duration_days,
        "protocol": challenge.get("protocol", ""),
        "success_criteria": challenge.get("success_criteria", ""),
        # #1118 — the protocols-grammar hypothesis: what should visibly change if
        # the challenge works. Honest-empty ("") if the model omitted it — the
        # render shows nothing rather than placeholder prose (ADR-104).
        "hoped_outcome": challenge.get("hoped_outcome", ""),
        "metric_targets": challenge.get("metric_targets", {}),
        "status": "candidate",
        "verification_method": challenge.get("verification_method", "self_report"),
        "tags": challenge.get("tags", []),
        "daily_checkins": [],
        "outcome": "",
        "character_xp_awarded": 0,
        "badge_earned": "",
        "related_experiment_id": "",
        "generated_by": "challenge-generator",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "activated_at": "",
        "completed_at": "",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    table.put_item(Item=floats_to_decimal(item))
    logger.info(f"Stored challenge candidate: {challenge_id} (source={source})")
    return challenge_id


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def lambda_handler(event, context):
    """Weekly challenge generation pipeline."""
    logger.info("Challenge generator starting")
    start_time = time.time()

    try:
        # 1. Gather context
        ctx = gather_context()
        if not ctx:
            logger.warning("No context gathered — skipping generation")
            return {"status": "skipped", "reason": "no_data"}

        # Check minimum data availability
        journal_count = len(ctx.get("journal_14d", []))
        has_character = bool(ctx.get("character"))
        has_habits = bool(ctx.get("habits"))

        if journal_count < 3 and not has_character and not has_habits:
            logger.warning(f"Insufficient data: journal={journal_count}, character={has_character}, habits={has_habits}")
            return {"status": "skipped", "reason": "insufficient_data"}

        logger.info(f"Context gathered: journal={journal_count}, character={has_character}, habits={has_habits}")

        # 2. Generate challenges
        result = generate_challenges(ctx)
        if not result or "challenges" not in result:
            # #2221 (ADR-104): generate_challenges returns None for an AI-3 BLOCK and
            # for a parse failure alike, and this used to publish either one to the
            # caller, the logs and CloudWatch as {'status':'completed',
            # 'reason':'no_signal'} — indistinguishable from the model honestly
            # finding nothing. An AI failure is not a data finding. A genuinely
            # quiet week is a PARSED {"challenges": []} and still completes below
            # with generated=0 and no reason at all.
            logger.error("Challenge generation failed or returned an invalid envelope")
            return {"status": "error", "generated": 0, "reason": "generation_failed"}

        challenges = result["challenges"]
        reasoning = result.get("reasoning", "")
        logger.info(f"AI generated {len(challenges)} candidates. Reasoning: {reasoning[:200]}")

        # 4. Store candidates (with dedup)
        stored = 0
        stored_ids = []
        rejected = 0
        for ch in challenges[:MAX_NEW_CHALLENGES]:
            # #2221: per-candidate isolation for MODEL-shaped failures only. One
            # malformed candidate used to raise out of this loop into the blanket
            # except, so the run reported neither the rows it had already written
            # nor the ones it never reached. Infrastructure failures (a DDB write
            # error, a Bedrock outage) deliberately still propagate — a partial
            # write must not be reported as a completed week.
            try:
                challenge_id = store_challenge(ch)
            except MalformedCandidate as e:
                rejected += 1
                logger.warning("Discarding malformed candidate %r: %s", ch.get("name"), e)
                continue
            if challenge_id:
                stored += 1
                stored_ids.append(challenge_id)

        elapsed = round(time.time() - start_time, 1)
        logger.info(f"Challenge generator complete: {stored}/{len(challenges)} stored ({rejected} malformed) in {elapsed}s")

        return {
            "status": "completed",
            "generated": len(challenges),
            "stored": stored,
            "rejected": rejected,
            "challenge_ids": stored_ids,
            "reasoning": reasoning[:500],
            "elapsed_seconds": elapsed,
        }

    except Exception as e:
        logger.error(f"Challenge generator failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
