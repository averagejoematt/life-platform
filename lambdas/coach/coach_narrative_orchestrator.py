"""
coach_narrative_orchestrator.py — Coach Intelligence Phase 2: Narrative Orchestrator

The "showrunner" — an LLM planning step (Haiku) that runs before a coach generates
content. Reads all coach state, ensemble context, computation results, and narrative
arc, then produces a structured generation brief for the target coach.

Phase 2 target: sleep_coach (Dr. Lisa Park) — highest cross-domain influence.

Inputs (all DynamoDB + S3):
  - Target coach compressed state (COACH#sleep_coach / COMPRESSED#latest)
  - All other coaches' compressed states
  - Ensemble digest (ENSEMBLE#digest / most recent CYCLE#)
  - Influence graph (ENSEMBLE#influence_graph / CONFIG#v1)
  - Computation results (COACH#computation / most recent RESULTS#)
  - Narrative arc state (NARRATIVE#arc / STATE#current)
  - Target coach voice state (COACH#sleep_coach / VOICE#state)
  - Target coach open threads (COACH#sleep_coach / THREAD# where status=open)
  - Target coach active predictions (COACH#sleep_coach / PREDICTION# where status in pending/confirming)
  - Journal mood/connection signal (#549 — USER#matthew#SOURCE#notion journal entries,
    aggregated from #505's extraction; surfaced only to coaches whose domain covers
    Matthew's inner state, e.g. mind_coach)

Output:
  - Generation brief JSON (returned + cached to COACH#sleep_coach / BRIEF#{date})

Schedule: Invoked by email generation pipeline, pre-generation step.

v1.0.0 — 2026-04-06 (Coach Intelligence Phase 2)
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from constants import EXPERIMENT_START_DATE  # ADR-058
from phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

# Structured logger
try:
    from platform_logger import get_logger

    logger = get_logger("coach-narrative-orchestrator")
except ImportError:
    logger = logging.getLogger("coach-narrative-orchestrator")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# Phase 2 target coach — will be parameterized in Phase 3
TARGET_COACH = os.environ.get("TARGET_COACH", "sleep_coach")

# All coach IDs in the system
ALL_COACH_IDS = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]

# Owner — challenges/experiments are keyed USER#{USER_ID}#SOURCE#... (mcp/config.py).
USER_ID = os.environ.get("USER_ID", "matthew")

# Phase 2 (2026-06-29) — the coaches-review-the-site loop: which site-protocol
# pillars each coach reacts to. Keys are the challenge `domain` / experiment `tags`
# vocab (sleep/movement/nutrition/supplements/mental/social/discipline/metabolic/
# general). Deterministic config routing — NOT inference — so a sleep coach never
# sees a nutrition challenge. explorer_coach is the cross-domain coach → None = all.
COACH_DOMAINS = {
    "sleep_coach": {"sleep"},
    "training_coach": {"movement"},
    "nutrition_coach": {"nutrition", "metabolic"},
    "mind_coach": {"mental", "mind", "social", "discipline"},
    "physical_coach": {"movement", "general"},
    "glucose_coach": {"metabolic", "nutrition"},
    "labs_coach": {"supplements", "metabolic"},
    "explorer_coach": None,
}

# #549: journal mood/connection signal is scoped to the coach(es) whose domain covers
# Matthew's inner state — today that's mind_coach only, but this routes off
# COACH_DOMAINS (same pattern as _gather_site_protocols) rather than a hardcoded
# coach-id check, so a future domain add doesn't need a second gate rewritten here.
_JOURNAL_MOOD_DOMAINS = {"mental", "mind"}

# Below this many scored entries in the window, a trajectory read is too thin to be
# honest — the signal is omitted entirely rather than asserting a trend off 2 days.
JOURNAL_MOOD_MIN_ENTRIES = 5
JOURNAL_MOOD_WINDOW_DAYS = 21


def _coach_wants_journal_mood(coach_id: str) -> bool:
    """True if this coach's domain covers Matthew's inner state (deterministic routing,
    not inference). explorer_coach (domains=None) is cross-domain — sees everything,
    matching how _gather_site_protocols treats a None domain set."""
    domains = COACH_DOMAINS.get(coach_id)
    if domains is None:
        return True
    return bool(domains & _JOURNAL_MOOD_DOMAINS)


# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-narrative-orchestrator")
_CW_NAMESPACE = "LifePlatform/AI"

# Backoff delays between retry attempts (seconds)
_BACKOFF_DELAYS = [5, 15, 45]
_MAX_ATTEMPTS = len(_BACKOFF_DELAYS) + 1
_RETRYABLE_CODES = frozenset([429, 500, 502, 503, 504, 529])

# AWS clients
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# ══════════════════════════════════════════════════════════════════════════════
# SECRET CACHING
# ══════════════════════════════════════════════════════════════════════════════

_api_key_cache = {"key": None, "ts": 0}
_API_KEY_TTL = 900  # 15 minutes


def _get_api_key():
    """ADR-062: Bedrock IAM auth — sentinel; see task #90 for full plumbing removal."""
    return "_BEDROCK_IAM_"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401


def _float_to_decimal(obj):
    """Recursively convert floats to Decimal for DynamoDB writes."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(v) for v in obj]
    return obj


# Canonical emitter lives in the layer — local copy removed 2026-06-12.
from retry_utils import _emit_token_metrics  # noqa: E402,F401


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (non-fatal)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicAPIFailure",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:
        logger.warning("CloudWatch failure metric emit failed (non-fatal): %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC API CALL
# ══════════════════════════════════════════════════════════════════════════════


def _track_record_block(coach_id: str) -> str:
    """Summarize this coach's resolved LEARNING# verdicts for prompt injection.

    Counts by outcome + the two most recent resolved calls verbatim. Returns a
    plain statement when nothing has resolved yet (post-reset normal). Failure
    here must never block the narrative run.
    """
    try:
        from datetime import timedelta as _td

        from boto3.dynamodb.conditions import Key as _Key

        cutoff = (datetime.now(timezone.utc) - _td(days=60)).strftime("%Y-%m-%d")
        r = table.query(
            KeyConditionExpression=_Key("pk").eq(f"COACH#{coach_id}") & _Key("sk").gt(f"LEARNING#{cutoff}"),
        )
        recs = [x for x in r.get("Items", []) if not x.get("tombstone")]
        if not recs:
            return "Nothing resolved yet this cycle. Make calls; they will be scored."
        counts = {}
        for x in recs:
            st = str(x.get("status", "unknown"))
            counts[st] = counts.get(st, 0) + 1
        lines = [", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))]
        resolved = [x for x in recs if x.get("status") in ("confirmed", "refuted")]
        resolved.sort(key=lambda x: str(x.get("date", "")), reverse=True)
        for x in resolved[:2]:
            lines.append(f"- {x.get('date', '?')}: {x.get('status')} — {str(x.get('condition') or x.get('reason') or '')[:160]}")
        lines.append(
            "When relevant, reference your own past calls in your narrative — "
            "own the misses plainly; credibility here comes from being scored, not from being right."
        )
        return "\n".join(lines)
    except Exception as _e:
        return "Track record unavailable this run."


def _call_haiku(system, user_message, max_tokens=6000, temperature=0.3):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.
    """
    api_key = _get_api_key()

    body = {
        "model": AI_MODEL_HAIKU,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw (Bedrock).
    from retry_utils import call_anthropic_raw

    resp = call_anthropic_raw(req)
    text = resp["content"][0]["text"].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# DYNAMODB READS
# ══════════════════════════════════════════════════════════════════════════════


def _get_item(pk, sk):
    """Get a single DynamoDB item. Returns None if not found, hidden, or on error.

    #946: get_item bypasses the query-level phase filter, so post-reset the wiped
    cycle's singletons (COMPRESSED#latest, STANCE#latest, VOICE#state, NARRATIVE#arc
    STATE#current, engagement STATE#current — tombstone=true / phase=pilot) kept
    steering fresh-cycle briefs. Mirror the filter here so the honest fresh-start
    defaults in _gather_all_state engage instead. Static config with no phase
    attribute (e.g. ENSEMBLE#influence_graph CONFIG#v1) passes through unchanged."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if not singleton_visible(item):
            return None
        return _decimal_to_float(item)
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _narrative_arc_state():
    """NARRATIVE#arc STATE#current — read raw, NOT via _get_item (#946).

    This record reuses the attribute name `phase` for its NARRATIVE phase
    (early_baseline / setback / ...), so the generic experiment-phase guard in
    _get_item would hide every legitimate arc state. Guard on tombstone + cycle
    instead: an arc entered before the current genesis is the PREVIOUS cycle's
    story (mirror of coach_computation_engine._detect_arc_transition's
    staleness guard), and returning None here engages _gather_all_state's
    honest fresh-start default (early_baseline, journey_day 1)."""
    try:
        item = table.get_item(Key={"pk": "NARRATIVE#arc", "sk": "STATE#current"}).get("Item")
        if not item:
            return None
        item = _decimal_to_float(item)
        if item.get("tombstone") or str(item.get("entered_date") or "") < EXPERIMENT_START_DATE:
            return None
        return item
    except Exception as e:
        logger.warning("narrative arc read failed: %s", e)
        return None


def _query_begins_with(pk, sk_prefix, scan_forward=True, limit=None):
    """Query DynamoDB for items with SK beginning with a prefix. ADR-058: phase-filtered.

    D-03 follow-up (2026-06-06): callers pass `limit` to bound prompt growth —
    THREAD#/PREDICTION# accumulate daily forever, and unbounded reads fed an
    ever-growing orchestrator prompt (input creep). Pair with
    scan_forward=False to keep the most RECENT N.
    """
    from boto3.dynamodb.conditions import Key

    try:
        params = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
            "ScanIndexForward": scan_forward,
        }
        if limit:
            params["Limit"] = limit
        resp = table.query(**with_phase_filter(params))
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


def _query_latest(pk, sk_prefix):
    """Query for the most recent item matching a SK prefix. ADR-058: phase-filtered."""
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = resp.get("Items", [])
        return _decimal_to_float(items[0]) if items else None
    except Exception as e:
        logger.warning("query_latest(%s, %s) failed: %s", pk, sk_prefix, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STATE GATHERING
# ══════════════════════════════════════════════════════════════════════════════


def _gather_all_state(coach_id):
    """Gather all state needed for the orchestrator's generation brief.

    Returns a dict of context components, with sensible defaults for missing state.
    Designed to be resilient — early in the experiment, most state will be empty.
    """
    logger.info("Gathering state for coach: %s", coach_id)
    coach_pk = f"COACH#{coach_id}"

    # 1. Target coach compressed state
    target_compressed = _get_item(coach_pk, "COMPRESSED#latest")
    if not target_compressed:
        logger.info("No compressed state for %s — using empty default", coach_id)
        target_compressed = {
            "coach_id": coach_id,
            "summary": "No prior outputs yet. This is the coach's first generation cycle.",
            "key_themes": [],
            "open_threads": [],
            "active_predictions": [],
            "confidence_state": {},
        }

    # 2. All other coaches' compressed states (for cross-coach context)
    other_compressed = {}
    for cid in ALL_COACH_IDS:
        if cid == coach_id:
            continue
        state = _get_item(f"COACH#{cid}", "COMPRESSED#latest")
        if state:
            other_compressed[cid] = state

    # 3. Ensemble digest (most recent CYCLE#)
    ensemble_digest = _query_latest("ENSEMBLE#digest", "CYCLE#")
    if not ensemble_digest:
        logger.info("No ensemble digest found — using empty default")
        ensemble_digest = {
            "coach_summaries": [],
            "active_disagreements": [],
            "note": "No ensemble digest yet — first generation cycle.",
        }

    # 4. Influence graph
    influence_graph = _get_item("ENSEMBLE#influence_graph", "CONFIG#v1")
    if not influence_graph:
        logger.info("No influence graph in DynamoDB — attempting S3 fallback")
        try:
            obj = s3.get_object(
                Bucket=S3_BUCKET,
                Key="config/coaches/influence_graph.json",
            )
            influence_graph = json.loads(obj["Body"].read())
        except Exception as e:
            logger.warning("Influence graph S3 fallback failed: %s", e)
            influence_graph = {"weights": {}, "notes": "Influence graph not yet loaded."}

    # 5. Computation results (most recent RESULTS#)
    computation_results = _query_latest("COACH#computation", "RESULTS#")
    if not computation_results:
        logger.info("No computation results found — using empty default")
        computation_results = {
            "trends": {},
            "regression_to_mean_warnings": [],
            "seasonal_flags": [],
            "statistical_notes": [],
            "note": "No computation results yet — deterministic engine has not run.",
        }

    # 6. Narrative arc state (#946: cycle-aware reader — see _narrative_arc_state)
    narrative_arc = _narrative_arc_state()
    if not narrative_arc:
        logger.info("No narrative arc state — defaulting to early_baseline")
        narrative_arc = {
            "current_phase": "early_baseline",
            "phase_started": EXPERIMENT_START_DATE,
            "journey_day": 1,
            "arc_history": [],
            "note": "Early baseline phase — experiment just begun.",
        }

    # 7. Target coach voice state
    voice_state = _get_item(coach_pk, "VOICE#state")
    if not voice_state:
        logger.info("No voice state for %s — using empty default", coach_id)
        voice_state = {
            "recent_openings": [],
            "overused_patterns": [],
            "signature_patterns_to_reinforce": [],
            "anti_patterns": [],
            "note": "No voice history yet — first generation.",
        }

    # 8. Open threads (filter status=open; most recent 50 — D-03 input-creep bound)
    all_threads = _query_begins_with(coach_pk, "THREAD#", scan_forward=False, limit=50)
    open_threads = [t for t in all_threads if t.get("status") == "open"]
    if not open_threads:
        logger.info("No open threads for %s", coach_id)

    # 9. Active predictions (filter status in pending/confirming; most recent 50)
    all_predictions = _query_begins_with(coach_pk, "PREDICTION#", scan_forward=False, limit=50)
    active_predictions = [p for p in all_predictions if p.get("status") in ("pending", "confirming")]
    if not active_predictions:
        logger.info("No active predictions for %s", coach_id)

    # 9b. Commitments (#532) — the concrete actions this coach pushed. Due/overdue
    # pending ones get injected so the coach MUST revisit its own advice; recently
    # resolved kept/broken ones frame follow-through. Bounded read (most recent 50).
    _today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_commitments = _query_begins_with(coach_pk, "COMMITMENT#", scan_forward=False, limit=50)
    due_commitments = [c for c in all_commitments if c.get("status") == "pending" and str(c.get("due_date") or "9999") <= _today_str]
    resolved_commitments = [c for c in all_commitments if c.get("status") in ("kept", "broken")][:5]
    # Follow-through tally — the coach's own kept/broken record (feeds the track record).
    commitment_record = {"kept": 0, "broken": 0, "unresolved": 0}
    for c in all_commitments:
        st = c.get("status")
        if st in commitment_record:
            commitment_record[st] += 1
    if not due_commitments:
        logger.info("No due commitments for %s", coach_id)

    # 10. Current stance — the coach-opinion engine's evolving read of Matthew
    # (coach_history_summarizer writes STANCE#latest). Absent pre-data; when
    # present it leads the generation framing over the static goal block.
    current_stance = _get_item(coach_pk, "STANCE#latest")
    if not current_stance:
        logger.info("No stance yet for %s — first cycles", coach_id)

    # 11. Active site protocols — the challenges/experiments Matthew has actually
    # committed to in this coach's domain, so the coach reacts to them by name
    # (Phase 2). Read-only, domain-routed, fail-soft; {} when nothing is active.
    site_protocols = _gather_site_protocols(coach_id)

    # 12. Presence / quiet-stretch state — whether Matthew is actively logging or
    # has fallen off routine (engagement_core, written by adaptive_mode). Shared by
    # all coaches (not per-coach) — it's about the human, not the domain. Absent /
    # 'present' ⇒ the coach says nothing about it. Fail-soft, like stance.
    engagement_signal = _get_item(f"USER#{USER_ID}#SOURCE#engagement_state", "STATE#current")

    # 13. Journal-derived mood/connection signal (#549) — deterministic trajectory
    # from #505's extraction. Gathered once (same 21-day window for every coach);
    # exposure into the message/brief is gated per-coach at the seam below, not here.
    journal_mood = _gather_journal_mood_signal()

    return {
        "target_compressed": target_compressed,
        "other_compressed": other_compressed,
        "ensemble_digest": ensemble_digest,
        "influence_graph": influence_graph,
        "computation_results": computation_results,
        "narrative_arc": narrative_arc,
        "voice_state": voice_state,
        "open_threads": open_threads,
        "active_predictions": active_predictions,
        "due_commitments": due_commitments,
        "resolved_commitments": resolved_commitments,
        "commitment_record": commitment_record,
        "current_stance": current_stance,
        "site_protocols": site_protocols,
        "engagement_signal": engagement_signal,
        "journal_mood": journal_mood,
    }


def _gather_site_protocols(coach_id):
    """Active challenges + experiments in this coach's domain — the site 'protocols'
    Matthew has committed to, so the coach can react to real commitments by name.

    Read-only and fail-soft (matches the gather contract — `_query_begins_with`
    returns [] on error). Routing is deterministic config (COACH_DOMAINS): a coach
    sees only its pillars; explorer_coach (domains=None) sees all. Experiments whose
    tags match no domain fall through to explorer only — never mis-attributed, never
    silently dropped to nowhere. Returns {} when nothing is active."""
    domains = COACH_DOMAINS.get(coach_id)  # None ⇒ all (explorer)

    def _in_domain(item_domains):
        if domains is None:
            return True
        return bool(domains & {d.lower() for d in item_domains if d})

    # Reads go through _query_begins_with → ADR-058 phase-filtered, so the coach
    # sees exactly the active set the site/MCP surface (same _apply_phase_filter).
    # The whole body is wrapped fail-soft: this gather must never abort the daily
    # orchestrator run for any coach.
    try:
        challenges = []
        for c in _query_begins_with(f"USER#{USER_ID}#SOURCE#challenges", "CHALLENGE#", limit=100):
            if c.get("status") != "active":
                continue
            if not _in_domain([c.get("domain", "")]):
                continue
            challenges.append(
                {
                    "name": c.get("name"),
                    "domain": c.get("domain"),
                    "duration_days": c.get("duration_days"),
                    "progress": c.get("progress"),  # writer-computed; trimmed if null
                }
            )

        experiments = []
        for e in _query_begins_with(f"USER#{USER_ID}#SOURCE#experiments", "EXP#", limit=100):
            if e.get("status") != "active":
                continue
            if not _in_domain(e.get("tags") or []):
                continue
            experiments.append(
                {
                    "name": e.get("name"),
                    "hypothesis": e.get("hypothesis"),
                    "tags": e.get("tags") or [],
                    "start_date": e.get("start_date"),
                }
            )
    except Exception as exc:  # pragma: no cover — defensive; reads already fail-soft
        logger.warning("site-protocols gather failed for %s: %s", coach_id, exc)
        return {}

    out = {}
    if challenges:
        out["challenges"] = challenges
    if experiments:
        out["experiments"] = experiments
    return out


def _gather_journal_mood_signal():
    """#549: journal-derived mood/connection signal — the trajectory and texture
    behind 'how Matthew feels', built from #505's extraction (enriched_mood/stress/
    sentiment/social_quality/themes/emotions). Consumes #505's output; does not
    duplicate its Haiku call — no new AI call here, this is a deterministic read
    + aggregate of already-enriched journal records.

    Cross-phase by design, like mcp.tools_journal._query_journal — journal is the
    longitudinal/clinical archive (ADR-058 owner decision 2026-06-06), so a mood
    trajectory should not silently truncate at a reset boundary.

    Fail-soft (matches the gather contract — a read error must never abort the
    daily orchestrator run) and returns None when there isn't enough recent
    journal data to say anything honest about a trajectory.
    """
    try:
        from boto3.dynamodb.conditions import Key as _Key

        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=JOURNAL_MOOD_WINDOW_DAYS)).strftime("%Y-%m-%d")
        pk = f"USER#{USER_ID}#SOURCE#notion"
        kwargs = with_phase_filter(
            {
                "KeyConditionExpression": _Key("pk").eq(pk) & _Key("sk").between(f"DATE#{start}#journal", f"DATE#{end}#journal#~"),
                "ScanIndexForward": True,
            },
            include_pilot=True,
        )
        items = []
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        entries = _decimal_to_float([i for i in items if "#journal#" in i.get("sk", "")])
    except Exception as e:
        logger.warning("journal mood gather failed: %s", e)
        return None

    if not entries:
        return None

    def _entry_date(e):
        d = e.get("date")
        if d:
            return d
        sk = e.get("sk", "")
        return sk.split("DATE#")[1][:10] if "DATE#" in sk else ""

    entries.sort(key=_entry_date)

    moods, stresses = [], []
    emotions_all, themes_all = [], []
    social_qualities = []
    quote, quote_date = None, None
    for e in entries:
        mood = e.get("enriched_mood")
        if mood is not None:
            moods.append(float(mood))
        stress = e.get("enriched_stress")
        if stress is not None:
            stresses.append(float(stress))
        emotions_all.extend(e.get("enriched_emotions") or [])
        themes_all.extend(e.get("enriched_themes") or [])
        social_quality = e.get("enriched_social_quality")
        if social_quality:
            social_qualities.append(social_quality)
        # Latest notable quote wins — most recent texture, not a historical one.
        notable = e.get("enriched_notable_quote")
        if notable:
            quote, quote_date = notable, _entry_date(e)

    if len(moods) < JOURNAL_MOOD_MIN_ENTRIES and len(stresses) < JOURNAL_MOOD_MIN_ENTRIES:
        return None

    def _trend(vals):
        """First-half vs second-half average — same lightweight technique
        mcp.tools_journal.tool_get_mood_trend uses for its half_delta."""
        if len(vals) < 4:
            return {"direction": "insufficient_data", "avg": round(sum(vals) / len(vals), 2) if vals else None, "n": len(vals)}
        mid = len(vals) // 2
        first_avg = sum(vals[:mid]) / mid
        second_avg = sum(vals[mid:]) / (len(vals) - mid)
        delta = round(second_avg - first_avg, 2)
        direction = "rising" if delta > 0.3 else "falling" if delta < -0.3 else "stable"
        return {"direction": direction, "avg": round(sum(vals) / len(vals), 2), "delta": delta, "n": len(vals)}

    def _top(values, n=4):
        counts: dict = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]

    social_dist: dict = {}
    for sq in social_qualities:
        social_dist[sq] = social_dist.get(sq, 0) + 1

    return {
        "window_days": JOURNAL_MOOD_WINDOW_DAYS,
        "entries_analyzed": len(entries),
        "mood_trend": _trend(moods),
        "stress_trend": _trend(stresses),
        "dominant_emotions": _top(emotions_all),
        "dominant_themes": _top(themes_all),
        "social_quality_distribution": social_dist,
        "alone_ratio": round(social_dist.get("alone", 0) / len(social_qualities), 2) if social_qualities else None,
        "notable_quote": quote,
        "notable_quote_date": quote_date,
    }


def _journal_mood_for_brief(signal):
    """Trim the journal mood signal to what the brief needs — and privacy-gate the
    one piece of raw text in it (#549). The brief is stored to DDB (BRIEF#{date})
    and flows verbatim into the coach's generation prompt, which can reach surfaces
    beyond this private planning step, so `notable_quote` passes through the same
    fail-closed vice/real-name gate the chronicle/podcast publish paths use
    (`privacy_guard.find_violations`) — a hit drops the quote rather than redacting
    it, since there is no upside to keeping a vice-adjacent fragment in an AI's
    planning input at all."""
    if not isinstance(signal, dict):
        return None
    out = {
        "window_days": signal.get("window_days"),
        "entries_analyzed": signal.get("entries_analyzed"),
        "mood_trend": signal.get("mood_trend"),
        "stress_trend": signal.get("stress_trend"),
        "dominant_emotions": signal.get("dominant_emotions") or [],
        "dominant_themes": signal.get("dominant_themes") or [],
    }
    social_dist = signal.get("social_quality_distribution") or {}
    if social_dist:
        out["social_quality_distribution"] = social_dist
    if signal.get("alone_ratio") is not None:
        out["alone_ratio"] = signal["alone_ratio"]

    quote = signal.get("notable_quote")
    if quote:
        from privacy_guard import find_violations

        if not find_violations(quote):
            out["notable_quote"] = quote
            out["notable_quote_date"] = signal.get("notable_quote_date")
        else:
            logger.info("journal mood: notable_quote dropped by privacy gate")

    return out


def _stance_for_brief(stance):
    """Trim a STANCE#latest record to the fields that steer generation (drop the
    internal bookkeeping — grounding_flag, generated_at, evidence_basis)."""
    if not isinstance(stance, dict):
        return None
    return {
        "headline_read": stance.get("headline_read", ""),
        "focused_on_now": stance.get("focused_on_now", []),
        "set_aside_for_now": stance.get("set_aside_for_now", []),
        "stage": stance.get("stage", {}),
        "how_my_read_changed": stance.get("how_my_read_changed", ""),
        "as_of": stance.get("as_of"),
    }


def _protocols_for_brief(protocols):
    """Trim active-protocol context for the brief: cap each surface at 5 items
    (D-03 input-creep bound, newest-first as queried) and drop null/empty fields
    so the coach reacts to real commitments without prompt bloat. Returns {} when
    nothing is active (the key is then omitted from the brief entirely)."""
    if not isinstance(protocols, dict):
        return {}
    out = {}
    for surface in ("challenges", "experiments"):
        items = protocols.get(surface) or []
        trimmed = [{k: v for k, v in it.items() if v not in (None, "", [], {})} for it in items[:5]]
        if trimmed:
            out[surface] = trimmed
    return out


# Presence classes that warrant the coach saying something. 'present' is silence.
_ENGAGEMENT_LOUD = {"light", "quiet", "dark"}


def _engagement_for_brief(signal):
    """Trim the engagement_state STATE#current record to the fields a coach needs
    to VOICE the gap — and nothing that would let it fabricate the CAUSE. Returns
    None when Matthew is present (or a returned-flag is the only news), so the key
    is omitted from the brief entirely and the coach stays quiet on it.

    Carries only: presence class, the real gap day-count, which channels went
    quiet, whether the wearables are still flowing, the planned-pause flag, and —
    on a return — how many days he was gone plus any real weight regain and the
    real passive read. The REASON for the gap is never here (the coach must invite
    the story, not invent it)."""
    if not isinstance(signal, dict):
        return None
    presence = signal.get("presence_class")
    returned = bool(signal.get("returned"))
    # #914: severity travels with the signal (derived for pre-ladder records) so
    # generation + the acknowledgment gate key off one field.
    try:
        from engagement_core import severity_of as _severity_of

        severity = _severity_of(signal)
    except ImportError:  # pragma: no cover — bundle always ships engagement_core
        severity = signal.get("severity")
    if presence not in _ENGAGEMENT_LOUD and not returned and severity not in ("loud", "alarm"):
        return None  # present + no return → nothing to say
    out = {
        "presence_class": presence,
        "severity": severity,
        "gap_days": signal.get("gap_days"),
        "last_food_log_date": signal.get("last_food_log_date"),
        "channels_quiet": signal.get("channels_quiet") or [],
        "passive_still_flowing": signal.get("passive_still_flowing"),
        "planned_pause": bool(signal.get("planned_pause")),
        "planned_pause_reason": signal.get("planned_pause_reason") or "",
        "returned": returned,
    }
    if returned:
        out["resumed_after_days"] = signal.get("resumed_after_days")
        if signal.get("weight_delta_over_gap") is not None:
            out["weight_delta_over_gap_lbs"] = signal.get("weight_delta_over_gap")
    if signal.get("passive_read"):
        out["passive_read"] = signal.get("passive_read")
    return {k: v for k, v in out.items() if v not in (None, "", [])}


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "You are the Narrative Orchestrator — the 'showrunner' for a team of "
    "AI health coaches. Your job is to produce a structured generation brief "
    "that will guide one specific coach's next output.\n\n"
    "You are NOT the coach. You do not write the coaching content. You plan "
    "what the coach should write about, which threads to reference, what "
    "cross-coach context to incorporate, and what voice/structural guidance "
    "to follow.\n\n"
    "## Your Responsibilities\n\n"
    "1. **Thread management**: Identify which open threads the coach should "
    "address, which to leave dormant, and whether new threads should be "
    "opened based on computation results.\n\n"
    "2. **Cross-coach context**: Determine which other coaches' concerns, "
    "recommendations, or disagreements are relevant to this coach's domain. "
    "Weight by influence graph.\n\n"
    "3. **Prediction accountability**: Flag predictions that need addressing "
    "— confirmed, refuted, or approaching their evaluation window.\n\n"
    "4. **Narrative beat**: Set the narrative tone for this output based on "
    "the journey phase, recent arc history, and current data state.\n\n"
    "5. **Voice guidance**: Based on the coach's voice state, recommend "
    "opening types (avoiding overused patterns), structural approaches, and "
    "any anti-patterns to watch for.\n\n"
    "6. **Decision class ceiling**: Based on available evidence and data "
    "maturity, set the maximum decision class "
    "(observational/directional/interventional) the coach should use.\n\n"
    "7. **Computation context**: Package relevant trend data, statistical "
    "flags, and regression-to-mean warnings for the coach.\n\n"
    "## Statistical Guardrails (ENFORCE THESE)\n\n"
    '- <7 days of data: "Observational only — no directional claims"\n'
    '- <14 days of data: "Use preliminary framing"\n'
    '- Regression-to-mean warnings: "Do not claim intervention effect"\n'
    '- Autocorrelation flags: "Likely autocorrelation, not independent signal"\n'
    '- N=1 constraint: Always. "Unusual for you" only, never "unusual."\n\n'
    "## Output Format\n\n"
    "Return ONLY valid JSON matching the generation_brief schema. "
    "No markdown, no explanation, no preamble."
)


def _build_user_message(state, coach_id, today):
    """Build the orchestrator user message as two content blocks for prompt caching.

    ADR-062 follow-up (2026-05-28): the orchestrator runs once per coach (8/day),
    and the GLOBAL context blocks — `ensemble_digest`, `influence_graph`,
    `computation_results`, `narrative_arc` — are byte-identical across all 8
    invocations in a run, so they go in a `cache_control: ephemeral` block
    (serialized deterministically with sort_keys so the cached prefix matches
    exactly). Call 1 writes the cache, calls 2-8 read it at ~0.1x. The shared
    block is also what pushes the cached prefix over Haiku's minimum cacheable
    length (the old system-only block was too small to cache at all).

    D-03 follow-up (2026-06-06): ALL 8 coaches' compressed states now live in
    the shared block too. Previously the target's state + the 7 others were in
    the per-coach (uncached) suffix; because the 7-of-8 subset differs per
    target, those bytes never matched the cache and were billed full price on
    every call (~31K uncached in/call measured June 1-6, the platform's largest
    AI input line). The full 8-state set IS byte-identical across calls, so it
    caches; the suffix just names the target. Same information, ~50% less
    billed input.

    Returns a list of Anthropic content blocks (not a string).
    """
    # ── Shared prefix (identical across all coaches this run → cacheable) ──
    shared_parts = [
        "## Ensemble Digest (Most Recent Cycle)",
        json.dumps(state["ensemble_digest"], indent=2, sort_keys=True, default=str),
        "",
        "## Cross-Coach Influence Graph",
        json.dumps(state["influence_graph"], indent=2, sort_keys=True, default=str),
        "",
        "## Computation Results Package",
        json.dumps(state["computation_results"], indent=2, sort_keys=True, default=str),
        "",
        "## Narrative Arc State",
        json.dumps(state["narrative_arc"], indent=2, sort_keys=True, default=str),
        "",
        "## All Coach Compressed States",
        "(One entry per coach. The per-call instructions below name the target "
        "coach — read its state here; the rest provide cross-coach context.)",
    ]
    all_compressed = dict(state["other_compressed"])
    all_compressed[coach_id] = state["target_compressed"]
    for cid in sorted(all_compressed):  # sorted → byte-identical across all 8 calls
        shared_parts.append(f"### {cid}")
        shared_parts.append(json.dumps(all_compressed[cid], indent=2, sort_keys=True, default=str))

    # ── Per-coach suffix (varies per invocation → not cached) ──
    parts = [
        f"## Target Coach: {coach_id}",
        f"## Date: {today}",
        "",
        f"(The target coach's compressed state is the `{coach_id}` entry in " "'All Coach Compressed States' above.)",
        "",
    ]

    parts.append("## Coach Voice State")
    parts.append(json.dumps(state["voice_state"], indent=2, default=str))
    parts.append("")

    parts.append("## Open Threads")
    if state["open_threads"]:
        parts.append(json.dumps(state["open_threads"], indent=2, default=str))
    else:
        parts.append("No open threads — this is the coach's first cycle or all threads are resolved.")
    parts.append("")

    parts.append("## Active Predictions")
    if state["active_predictions"]:
        parts.append(json.dumps(state["active_predictions"], indent=2, default=str))
    else:
        parts.append("No active predictions — coach has not yet made formal predictions.")
    parts.append("")

    # Commitments to revisit (#532): the recommendations THIS coach pushed that are now
    # due. Following through on your own advice — "did the 9:30 wind-down I pushed happen?
    # the data says no" — is the single strongest 'real coach' signal. A due commitment
    # with a graded outcome MUST be addressed; a due one still pending MUST be asked about.
    due = state.get("due_commitments") or []
    resolved = state.get("resolved_commitments") or []
    if due or resolved:
        parts.append("## Commitments To Revisit (your own past recommendations, now due)")
        if due:
            parts.append("These are DUE — you asked Matthew to do these; revisit each one explicitly this cycle:")
            parts.append(
                json.dumps(
                    [
                        {
                            "commitment": c.get("commitment_natural"),
                            "made_on": c.get("created_date"),
                            "machine_checkable": bool(c.get("action_check")),
                        }
                        for c in due
                    ],
                    indent=2,
                    default=str,
                )
            )
        if resolved:
            parts.append("Recently graded (own the outcome — a kept call earns trust, a broken one earns candor):")
            parts.append(
                json.dumps(
                    [{"commitment": c.get("commitment_natural"), "outcome": c.get("status")} for c in resolved],
                    indent=2,
                    default=str,
                )
            )
        _cr = state.get("commitment_record") or {}
        if any(_cr.values()):
            parts.append(
                "Follow-through record so far — "
                f"kept: {_cr.get('kept', 0)}, broken: {_cr.get('broken', 0)}, unresolved: {_cr.get('unresolved', 0)}."
            )
        parts.append("")

    # Coach memory (2026-06-13): the coach's own resolved track record, so it
    # can reference past calls — and acknowledge misses — in its own voice.
    # Empty right after a reset; fills as the evaluator resolves predictions.
    parts.append("## Your Track Record (resolved predictions, last 60 days)")
    parts.append(_track_record_block(coach_id))
    parts.append("")

    # Current stance (2026-06-29): the coach's evolving, evidence-derived read of
    # Matthew. Steers the narrative beat/focus so generation follows the opinion
    # the coach has actually formed — not a static weight goal. Injected into the
    # brief deterministically downstream; surfaced here so PLANNING is stance-aware.
    parts.append("## Current Stance (your evolving read of Matthew)")
    if state.get("current_stance"):
        parts.append(json.dumps(_stance_for_brief(state["current_stance"]), indent=2, default=str))
        parts.append("Align the narrative beat and focus with this stance. If the data now contradicts it, that tension is the story.")
    else:
        parts.append("No stance yet — first cycles. Establish the read.")
    parts.append("")

    # Active site protocols (Phase 2, 2026-06-29): the challenges/experiments Matthew
    # has committed to in this coach's domain. Surfaced here so PLANNING accounts for
    # them; injected into the brief deterministically downstream (like the stance).
    protocols = _protocols_for_brief(state.get("site_protocols"))
    if protocols:
        parts.append("## Active Site Protocols (Matthew's current commitments in your domain)")
        parts.append(json.dumps(protocols, indent=2, default=str))
        parts.append(
            "Plan the coach to acknowledge the relevant ones by name and give an honest read — "
            "grounded in the data already in this context, never invented progress."
        )
        parts.append("")

    # Presence / quiet-stretch signal: surface here so PLANNING makes the lull (or
    # the return) the beat when it matters; injected into the brief deterministically
    # downstream (like the stance/protocols).
    engagement = _engagement_for_brief(state.get("engagement_signal"))
    if engagement:
        parts.append("## Presence signal (Matthew's own logging)")
        parts.append(json.dumps(engagement, indent=2, default=str))
        parts.append(
            "If this shows a real gap (or a return), make NOTICING it the narrative beat — in "
            "this coach's own voice. Ground the day-count in the real numbers; never invent the "
            "reason for the silence — name it, note what the wearables caught, and invite the story."
        )
        parts.append("")

    # Journal mood/connection signal (#549): deterministic, from #505's extraction —
    # only surfaced to coach(es) whose domain covers Matthew's inner state, so the
    # other 7 coaches' prompts (and the cached shared block) never carry it.
    if _coach_wants_journal_mood(coach_id):
        journal_mood = _journal_mood_for_brief(state.get("journal_mood"))
        if journal_mood:
            parts.append("## Journal Mood Signal (#549 — how Matthew feels, from his own journal)")
            parts.append(json.dumps(journal_mood, indent=2, default=str))
            parts.append(
                "This is deterministic — a trajectory/aggregate computed from #505's journal "
                "extraction, not your interpretation. Use it to plan how this coach reads Matthew's "
                "inner state this cycle (mood/stress trajectory, dominant emotions/themes, how "
                "connected vs. alone he's been) alongside what the behavioral data already shows. "
                "Never plan a clinical diagnosis. If a notable_quote is present, it already passed "
                "a privacy check, but it is for THIS coach's private reading only — plan to "
                "paraphrase the substance rather than quote it verbatim if this content could ever "
                "reach a public surface."
            )
            parts.append("")

    parts.append("## Instructions")
    parts.append(
        f"Produce a generation brief for {coach_id}. Return ONLY the JSON object "
        "with the schema: {coach_id, generation_brief: {open_threads, cross_coach_context, "
        "predictions_to_address, narrative_beat, journey_phase, periodization_note, "
        "voice_guidance: {avoid_openings, suggested_opening, structural_note}, "
        "decision_class_ceiling, evidence_note, seasonal_flags, computation_outputs}}.\n"
        # D-03 (2026-06-06): output tokens are the orchestrator's largest cost
        # line; un-tightened briefs ran 1800-3000 tokens of repeated prose.
        "Be CONCISE — this brief is machine-consumed planning, not coaching "
        "prose: every free-text field at most 2 sentences; do not restate data "
        "already in the context (reference it); include only the most relevant "
        "items — at most 5 open_threads, 5 cross_coach_context entries, and 5 "
        "predictions_to_address (drop the rest, lowest-priority first)."
    )

    return [
        {"type": "text", "text": "\n".join(shared_parts), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "\n".join(parts)},
    ]


# ══════════════════════════════════════════════════════════════════════════════
# BRIEF CACHING
# ══════════════════════════════════════════════════════════════════════════════


def _cache_brief(coach_id, brief, today):
    """Cache the generation brief to DynamoDB for fallback use."""
    try:
        item = _float_to_decimal(
            {
                "pk": f"COACH#{coach_id}",
                "sk": f"BRIEF#{today}",
                "brief": brief,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        table.put_item(Item=item)
        logger.info("Cached generation brief for %s at BRIEF#%s", coach_id, today)
    except Exception as e:
        logger.error("Failed to cache brief for %s: %s", coach_id, e)


def _load_fallback_brief(coach_id):
    """Load the most recent cached brief if the LLM call fails."""
    brief = _query_latest(f"COACH#{coach_id}", "BRIEF#")
    if brief:
        logger.info("Loaded fallback brief for %s from %s", coach_id, brief.get("sk", "unknown"))
        return brief.get("brief")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT BRIEF
# ══════════════════════════════════════════════════════════════════════════════


def _build_default_brief(coach_id, today):
    """Build a safe default brief when LLM and fallback both fail.

    Conservative — observational only, no bold claims.
    """
    return {
        "coach_id": coach_id,
        "generation_brief": {
            "open_threads": [],
            "cross_coach_context": [],
            "predictions_to_address": [],
            "narrative_beat": "early_baseline",
            "journey_phase": "early_baseline",
            "periodization_note": (
                "Month 1 — building baseline. Conservative observation appropriate. "
                "Insufficient data history for trend analysis or directional claims."
            ),
            "voice_guidance": {
                "avoid_openings": [],
                "suggested_opening": "lead_with_data",
                "structural_note": ("First generation — establish voice and begin observing. " "No prior outputs to callback to."),
            },
            "decision_class_ceiling": "observational",
            "evidence_note": (
                "Very early in data collection (<14 days). " "All observations are preliminary. No directional claims warranted."
            ),
            "seasonal_flags": [],
            "computation_outputs": {
                "trends": {},
                "regression_to_mean_warnings": [],
            },
            "_fallback": True,
            "_generated_at": today,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def lambda_handler(event, context):
    """Produce a generation brief for the target coach.

    Event fields (all optional — defaults to TARGET_COACH env var):
      - coach_id: Override target coach ID
      - date: Override date (YYYY-MM-DD format, for testing/backfill)

    Returns the generation brief JSON.
    """
    coach_id = event.get("coach_id", TARGET_COACH)
    today = event.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    logger.info("Starting narrative orchestrator for %s on %s", coach_id, today)

    # Gather all state
    state = _gather_all_state(coach_id)

    # Build the orchestrator prompt
    user_message = _build_user_message(state, coach_id, today)

    # Call Haiku to produce the generation brief
    try:
        # Budget guardrail: at Tier ≥ 1 skip the LLM and fall back to the cached/
        # default brief, so the coach pipeline keeps running with zero Bedrock spend.
        from budget_guard import allow as _budget_allow

        if not _budget_allow("coach_narrative"):
            raise RuntimeError("coach narrative AI paused by budget tier — using fallback")
        result = _call_haiku(
            system=SYSTEM_PROMPT,
            user_message=user_message,
            # 2026-05-28: was 2000 — too small. A full generation brief is
            # ~1800-3000 output tokens, so it truncated mid-JSON (stop_reason
            # max_tokens), failed to parse, and EVERY coach silently fell back
            # to the canned default brief while still paying for the wasted call.
            # 6000 gives headroom; you only pay for tokens actually generated.
            max_tokens=6000,
            temperature=0.3,
        )

        # Validate that we got a dict with the expected structure
        if isinstance(result, dict):
            # Ensure coach_id is set
            if "coach_id" not in result:
                result["coach_id"] = coach_id
            # Ensure generation_brief wrapper exists
            if "generation_brief" not in result:
                # The LLM might have returned the brief contents directly
                result = {"coach_id": coach_id, "generation_brief": result}

            brief = result
            logger.info(
                "Generation brief produced for %s — narrative_beat: %s, ceiling: %s",
                coach_id,
                brief.get("generation_brief", {}).get("narrative_beat", "unknown"),
                brief.get("generation_brief", {}).get("decision_class_ceiling", "unknown"),
            )
        else:
            logger.warning("LLM returned non-dict response for %s — attempting fallback", coach_id)
            brief = _load_fallback_brief(coach_id)
            if not brief:
                brief = _build_default_brief(coach_id, today)

    except Exception as e:
        logger.error("LLM call failed for %s: %s — attempting fallback", coach_id, e)
        brief = _load_fallback_brief(coach_id)
        if not brief:
            logger.warning("No fallback brief available — using default for %s", coach_id)
            brief = _build_default_brief(coach_id, today)

    # Inject the coach's current stance into the brief DETERMINISTICALLY (not via
    # the LLM) so its evolving read of Matthew reaches generation verbatim, on every
    # path including fallback/default. Absent pre-data — the coach then leans on its
    # goal framing as before (ai_calls.py). The brief flows verbatim into the coach
    # prompt, so this is the seam that closes the stance→generation loop.
    stance = state.get("current_stance")
    if stance and isinstance(brief.get("generation_brief"), dict):
        brief["generation_brief"]["current_stance"] = _stance_for_brief(stance)

    # Inject active site protocols DETERMINISTICALLY (same seam as the stance) so the
    # coach reacts to Matthew's real challenge/experiment commitments on every path,
    # including fallback/default. Omitted when nothing is active (Phase 2).
    protocols = _protocols_for_brief(state.get("site_protocols"))
    if protocols and isinstance(brief.get("generation_brief"), dict):
        brief["generation_brief"]["site_protocols"] = protocols

    # Inject the presence / quiet-stretch signal DETERMINISTICALLY (same seam) so a
    # real logging gap reaches the coach on every path — it can then notice the
    # silence in its own voice (and note the return). Omitted when Matthew is
    # present (nothing to say). The REASON for the gap is never in the payload.
    engagement = _engagement_for_brief(state.get("engagement_signal"))
    if engagement and isinstance(brief.get("generation_brief"), dict):
        brief["generation_brief"]["engagement_signal"] = engagement

    # Inject the journal mood/connection signal DETERMINISTICALLY (same seam, #549) so
    # it reaches generation on every path including fallback/default — but only for the
    # coach(es) whose domain covers Matthew's inner state. Omitted for every other coach
    # and whenever the journal window is too thin to say anything honest.
    if _coach_wants_journal_mood(coach_id):
        journal_mood = _journal_mood_for_brief(state.get("journal_mood"))
        if journal_mood and isinstance(brief.get("generation_brief"), dict):
            brief["generation_brief"]["journal_mood"] = journal_mood

    # Cache the brief for fallback use
    _cache_brief(coach_id, brief, today)

    logger.info("Narrative orchestrator complete for %s", coach_id)
    return brief
