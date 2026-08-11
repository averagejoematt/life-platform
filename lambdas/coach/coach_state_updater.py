"""
coach_state_updater.py — Coach Intelligence Phase 2: Post-Generation State Updater

Runs after a coach generates content. Uses Haiku to extract structured metadata
from the coach's output text (themes, structural fingerprint, threads, predictions,
decision classes, anti-pattern violations), then writes results to DynamoDB:

  - OUTPUT# record with full content + extracted metadata
  - VOICE#state update with latest opening type and overused pattern flags
  - New THREAD# records for threads opened
  - Updated THREAD# records for threads referenced (bump reference_count)
  - TRACE# reasoning trace record (returned to caller)
  - RELATIONSHIP#state update — deterministic rapport arc, no LLM (#536)

Phase 2 target: sleep_coach (Dr. Lisa Park).

v1.0.0 — 2026-04-06 (Coach Intelligence Phase 2)
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from common.record_text import COACH_OUTPUT_FIELD  # #2569: the ONE name for an OUTPUT# record's narrative
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946 / #1969

from coach import coach_derived_prose  # #2418: the derived reader-prose SET — blob / regen / hold / read
from coach.reading_date_fidelity import guard_derived_summary  # #2343
from coach.relationship_engine import compute_relationship_update  # #536
from coach.voice_register_guard import sanitize_summary  # #1987: deterministic voice-register check

# Structured logger
try:
    from common.platform_logger import get_logger

    logger = get_logger("coach-state-updater")
except ImportError:
    logger = logging.getLogger("coach-state-updater")
    logger.setLevel(logging.INFO)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# CloudWatch metrics
_cw = boto3.client("cloudwatch", region_name=REGION)
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "coach-state-updater")
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
# Measurable-metric allowlist for prediction extraction
# ══════════════════════════════════════════════════════════════════════════════
# CONSOLIDATED 2026-06-28 (Coherence Program Phase 2): the allowlist, the metric-
# hint normalizer, AND coach_prediction_evaluator's METRIC_SOURCES used to be three
# hand-synced copies — when they drifted, predictions silently dropped to qualitative
# and never graded (the v7.15.0 504-inconclusive bug; the Coherence Sentinel's
# prediction_health invariant exists for exactly this). They now live in ONE place,
# DERIVED so they cannot diverge. See lambdas/measurable_metrics.py.
# (#2418: the only USE of MEASURABLE_METRICS here moved with the extraction prompt to
# coach_extraction_prompt.py. It stays imported deliberately — `updater.MEASURABLE_METRICS
# is measurable_metrics.MEASURABLE_METRICS` is the identity assertion #813's drift guard
# makes on this module, and a re-export is what keeps that guard meaningful.)
from experiment.measurable_metrics import (  # noqa: E402,F401
    MEASURABLE_METRICS,
    METRIC_SOURCES,  # noqa: E402
    infer_direction as _infer_direction,  # noqa: E402  (#813: shared with the evaluator)
    normalize_metric_hint as _normalize_metric_hint,  # noqa: E402
)


def _parse_confidence(raw) -> float:
    """V2 P1.3 (2026-05-17): defensively parse Haiku-returned confidence.

    Haiku often returns "40%" or "0.4" or "high" / "medium" / "low". Prior code
    did naked float(raw) which crashed on "%" suffix → 17% error rate.
    Returns 0.5 on parse failure (neutral default).
    """
    if raw is None or raw == "":
        return 0.5
    s = str(raw).strip().lower()
    word_map = {"high": 0.85, "medium": 0.5, "med": 0.5, "low": 0.2, "very high": 0.95, "very low": 0.1, "unknown": 0.5}
    if s in word_map:
        return word_map[s]
    try:
        has_pct = s.endswith("%")
        val = float(s.rstrip("%").strip())
        if has_pct:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return 0.5


# Direction inference (Scorecard / C-3) moved to measurable_metrics.infer_direction
# (#813) so the writer and the evaluator's legacy-backlog rescue share ONE keyword
# map — imported above as _infer_direction.


def _build_prediction_eval_spec(metric_hint, direction, window_days):
    """Build the PREDICTION# `evaluation` block, choosing the gradable type.

    metric + direction → directional (EWMA trend, no threshold needed) — this is
    the path that lets the daily evaluator actually confirm/refute. Without a
    resolvable direction (or metric) we stay qualitative rather than writing a
    machine spec with threshold=None that can only ever go inconclusive.
    """
    if metric_hint and direction in ("up", "down"):
        return {
            "type": "directional",
            "metric": metric_hint,
            "condition": direction,  # the directional evaluator reads 'up'/'down'
            "threshold": None,
            "evaluation_window_days": window_days,
            "null_hypothesis": None,
            "beats_null_if": None,
        }
    return {
        "type": "qualitative",
        "metric": metric_hint or None,
        "condition": None,
        "threshold": None,
        "evaluation_window_days": window_days,
        "null_hypothesis": None,
        "beats_null_if": None,
    }


# ── #813: write-time data-liveness gate ──────────────────────────────────────
# A prediction is only machine-gradable if its metric's source is actually
# producing data — the #813 triage found whole metric families (blood_glucose_*
# with the CGM sensor inactive, body_fat_pct with no DEXA scan in the window)
# whose predictions could only ever expire inconclusive. Emitting them as
# gradable inflates the pending count and stalls the public scorecard, so a
# metric with fewer than _LIVENESS_MIN_POINTS values over the last
# _LIVENESS_LOOKBACK_DAYS days falls back to qualitative at write time.
# _LIVENESS_MIN_POINTS matches the evaluator's EWMA minimum (a directional
# grade needs >= 5 points). Fail-OPEN on read errors: an AWS hiccup must never
# silently downgrade a whole run's predictions to qualitative.
#
# #2023: the liveness read is CROSS-PHASE (include_pilot=True) — a #1203-class fix.
# Every source in METRIC_SOURCES is classed RAW_TIMESERIES or CROSS_PHASE by
# phase_taxonomy ("Kept forever; current-experiment views are GENESIS-ANCHORED …
# not hidden. Phase tags are harmless/optional"), so those rows survive a reset by
# design — but the reset tags every pre-genesis row phase=pilot, and a phase-filtered
# 30-day lookback therefore sees only the days elapsed since genesis. In the opening
# week of a cycle that is 0-6 points, so essentially every metric fell under the
# 5-point bar and correctly-extracted metric predictions were downgraded to
# qualitative (cycle-11 gradable share ~1.4% vs the ~9% pilot baseline) — precisely
# when a reader is watching a fresh cycle start. Liveness asks "is this pipe
# producing data", which is a question about the sensor, not about the experiment
# generation; the 30-day window is the whole answer. Guarded by
# tests/test_gradability_liveness_cross_phase_2023.py.
_LIVENESS_LOOKBACK_DAYS = 30
_LIVENESS_MIN_POINTS = 5


def _metric_has_recent_data(metric_key, liveness_cache):
    """True when metric_key's mapped source shows >= _LIVENESS_MIN_POINTS numeric
    values in the last _LIVENESS_LOOKBACK_DAYS days (or liveness can't be read)."""
    base = metric_key or ""
    for suffix in ("_7day_avg", "_14day_avg", "_30day_avg"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    source = METRIC_SOURCES.get(base)
    if not source:
        return False  # unmapped is ungradable by definition
    if base in liveness_cache:
        return liveness_cache[base]
    try:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=_LIVENESS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": f"USER#{USER_ID}#SOURCE#{source}",
                ":s": "DATE#" + start,
                ":e": "DATE#" + end,
            },
        }
        n = 0
        while True:
            resp = table.query(**with_phase_filter(kwargs, include_pilot=True))  # #2023: cross-phase liveness
            for item in resp.get("Items", []):
                val = item.get(base)
                if val is not None:
                    try:
                        float(val)
                        n += 1
                    except (TypeError, ValueError):
                        pass
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        alive = n >= _LIVENESS_MIN_POINTS
    except Exception as e:
        logger.warning("Metric liveness check failed for %s (%s) — failing open: %s", metric_key, source, e)
        alive = True
    liveness_cache[base] = alive
    return alive


# Maximum opening history to keep in voice state
MAX_RECENT_OPENINGS = 10

# Staleness threshold — flag pattern if it appears in 3+ of last 5 outputs
STALENESS_WINDOW = 5
STALENESS_THRESHOLD = 3

# ══════════════════════════════════════════════════════════════════════════════
# SECRET CACHING
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from common.numeric import (
    decimals_to_float as _decimal_to_float,  # noqa: E402,F401
    floats_to_decimal,  # noqa: E402  # canonical float->Decimal (#1207)
)

# Canonical emitter lives in the layer — local copy removed 2026-06-12.
from common.retry_utils import _emit_token_metrics  # noqa: E402,F401


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


def _emit_prediction_gradability(gradable: int, qualitative: int) -> None:
    """SS-06: emit the write-time gradability of this run's predictions.

    The C-3 fix routes metric+direction claims to the gradable `directional`
    evaluator; everything else falls to `qualitative` (ungradable — it expires
    inconclusive and never fills the track record). The Coherence Sentinel watches
    the *accumulated board* qualitative share daily, but it needs ≥8 CLOSED
    predictions to judge — so a coach run that suddenly emits all-qualitative output
    isn't visible until its windows elapse (weeks later). This metric is the leading
    indicator: it catches a gradability regression the same day, at the source.
    Emits counts + a 0-1 gradable share (only when predictions were written, so an
    empty run doesn't drag the share to 0). Non-fatal.
    """
    total = gradable + qualitative
    if total == 0:
        return
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/Predictions",
            MetricData=[
                {"MetricName": "PredictionsGradable", "Value": float(gradable), "Unit": "Count"},
                {"MetricName": "PredictionsQualitative", "Value": float(qualitative), "Unit": "Count"},
                {"MetricName": "PredictionGradableShare", "Value": gradable / total, "Unit": "None"},
            ],
        )
        logger.info(
            "Prediction gradability this run: %d gradable / %d qualitative (%.0f%% gradable)",
            gradable,
            qualitative,
            100.0 * gradable / total,
        )
    except Exception as e:
        logger.warning("Prediction gradability metric emit failed (non-fatal): %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC API CALL
# ══════════════════════════════════════════════════════════════════════════════


def _call_haiku(system, user_message, max_tokens=3000, temperature=0.1):
    """Call Anthropic Haiku with exponential backoff + CloudWatch metrics.

    Returns parsed JSON dict if the response is valid JSON, otherwise raw text.
    Raises on final failure after all retry attempts.

    2026-05-03: bumped default max_tokens 1500 → 3000. Was hitting truncation
    on 5-coach state extraction; truncation → invalid JSON → fallback to default.
    """
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
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        method="POST",
    )

    # ADR-062 (2026-05-27): route through retry_utils.call_anthropic_raw (Bedrock).
    from common.retry_utils import call_anthropic_raw

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
# DYNAMODB OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════


def _get_item(pk, sk):
    """Get a single DynamoDB item. Returns None if not found, hidden, or on error.

    #1969 (#946 class): get_item bypasses the query-level phase filter, so a
    restart's tombstoned singletons (VOICE#state, RELATIONSHIP#state) would
    seed the fresh cycle's evolved state from the wiped cycle instead of the
    honest fresh-start defaults. singleton_visible mirrors the filter
    (orchestrator pattern); records with no phase attribute pass through."""
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if not singleton_visible(item):
            return None
        return _decimal_to_float(item)
    except Exception as e:
        logger.warning("get_item(%s, %s) failed: %s", pk, sk, e)
        return None


def _put_item(item):
    """Write an item to DynamoDB with float-to-Decimal conversion.

    All COACH#* rows written here are EXPERIMENT_SCOPED intelligence — stamp them
    with write-time provenance (phase + cycle, #1233) so they're self-describing on
    this tagger-blind partition. experiment_stamp() is fail-soft and cached, and the
    item's own keys win, so it never clobbers or breaks the write.
    """
    from experiment.phase_taxonomy import experiment_stamp

    try:
        table.put_item(Item=floats_to_decimal({**experiment_stamp(), **item}))
        return True
    except Exception as e:
        logger.error("put_item failed for %s/%s: %s", item.get("pk"), item.get("sk"), e)
        return False


def _query_begins_with(pk, sk_prefix, scan_forward=True):
    """Query DynamoDB for items with SK beginning with a prefix. ADR-058: phase-filtered."""
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                    "ScanIndexForward": scan_forward,
                }
            )
        )
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:
        logger.warning("query_begins_with(%s, %s) failed: %s", pk, sk_prefix, e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# VOICE SPEC LOADER
# ══════════════════════════════════════════════════════════════════════════════


def _load_voice_spec(coach_id):
    """Load the coach's voice specification from S3 for anti-pattern checking.

    Falls back to an empty spec if the file doesn't exist yet.
    """
    try:
        obj = s3.get_object(
            Bucket=S3_BUCKET,
            Key=f"config/coaches/{coach_id}.json",
        )
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        logger.info("No voice spec found for %s in S3 — using empty default", coach_id)
        return {}
    except Exception as e:
        logger.warning("Failed to load voice spec for %s: %s — using empty default", coach_id, e)
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION PROMPT — lifted to coach/coach_extraction_prompt.py (#2418, the #2221
# shape: pay for the grounding gate below by moving a cohesive block out of a file at
# its #1665 ratchet, never by raising the number). Re-exported under the original
# names; nothing monkeypatches them.
# ══════════════════════════════════════════════════════════════════════════════

from coach.coach_extraction_prompt import (  # noqa: E402,F401
    _METRIC_ALLOWLIST_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_message as _build_extraction_message,  # noqa: E402
)

# ══════════════════════════════════════════════════════════════════════════════
# THE ADR-104 GROUNDING GATE ON THE DERIVED READER PROSE (#2418)
# ══════════════════════════════════════════════════════════════════════════════
# The three condensations this module writes — observatory_summary,
# key_recommendation, elena_quote — are what six serving paths actually publish, in
# preference to the coach's own gated `content`. They had two deterministic guards
# (#1987 voice register, #2343/#2390 reading-date + fabricated-number) and no
# registered grounding surface at all, so the numeric/date/night/freshness class never
# looked at them: a preferred, ungated derived text could contradict the gated one it
# was condensed from. That is the Webb-card mechanism the #2390 census landed on.
#
# Fail-open on a missing shared module, exactly as the digest and compression gates do.
# A gate is not allowed to be the thing that stops coach state being written.
try:
    from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings, regen_once
    from ai.grounding_gate_params import cycle_gate_params  # #1967 — the cycle anchors, one provider
    from ai.night_scope import nightly_vitals_from_narrative  # #1968 arming, from the source's own dated claims
except ImportError:  # pragma: no cover — environment-dependent
    allowed_dates = allowed_numbers = grounding_findings = regen_once = nightly_vitals_from_narrative = None

    def cycle_gate_params(generation_date_iso=None):  # type: ignore[misc]
        return {}


def _gate_derived_prose(coach_id, date, output_text, extraction):
    """Ground the derived condensations against the narrative they condense (#2418).

    The allow-list is `output_text` — the coach's own narrative, which is exactly what
    the extractor was shown and which already passed its generation-time gate. So this
    asks the one question a condensation gate can answer without a lookup: did the
    shorter text stay inside what the longer one actually said? Four classes arm:

      * numbers  — a figure the narrative never contained (#2390 / ADR-104);
      * dates    — a calendar date the narrative never contained (#1242);
      * night    — a vitals figure that names no night, or names a different night (or
                   a different value for the named night) than the narrative did. The
                   map comes from the SOURCE's dated claims, not from a fact snapshot:
                   see `night_scope.nightly_vitals_from_narrative` for why that is the
                   right authority for a derived text (#1968/#2343);
      * freshness — a stale "Day N" / baseline framing carried into the card (#1691/
                   #1897), anchored on the record's own date rather than on today.

    ONE corrective regeneration through the shared `regen_once` harness, then the
    caller HOLDS. Returns `(extraction, findings)` and raises nothing: `regen_once`
    swallows a failing regen, and every read site has a `content` fallback, so a
    finding costs a condensation and never the record, the run, or the lane.
    """
    if grounding_findings is None or regen_once is None or allowed_numbers is None:
        return extraction, []  # shared module unavailable — fail-open, matches its own design
    text = coach_derived_prose.prose_blob(extraction)
    if not text:
        return extraction, []  # nothing derived to grade
    allowed = allowed_numbers(output_text)
    _dates = allowed_dates(output_text) if allowed_dates is not None else None
    _nights = nightly_vitals_from_narrative(output_text, date) if nightly_vitals_from_narrative is not None else None
    holder = {"latest": extraction}

    def _findings_fn(candidate):
        return grounding_findings(
            candidate,
            facts=None,
            allowed=allowed,
            allowed_dates=_dates,
            nightly_vitals=_nights,
            **cycle_gate_params(date),
        )

    def _regen_fn(correction):
        holder["latest"] = coach_derived_prose.recondense(coach_id, output_text, extraction, correction, _call_haiku)
        return coach_derived_prose.prose_blob(holder["latest"])

    _best, findings, corrected = regen_once(text, _findings_fn, _regen_fn)
    return (holder["latest"] if corrected else extraction), findings


# ══════════════════════════════════════════════════════════════════════════════
# STATE WRITES
# ══════════════════════════════════════════════════════════════════════════════


def _write_output_record(coach_id, date, output_type, output_text, extraction):
    """Write the OUTPUT# record with full content and extracted metadata."""
    word_count = len(output_text.split())
    now_iso = datetime.now(timezone.utc).isoformat()

    # #2418: regenerate-or-hold. A finding that survives the one regen HOLDS the whole
    # derived-prose set (nulled), and every serving path falls back to `content` — the
    # narrative that passed its own gate. The record itself still ships.
    extraction, _gate_findings = _gate_derived_prose(coach_id, date, output_text, extraction)
    if _gate_findings:
        logger.warning(
            "Derived coach prose failed the ADR-104 grounding gate after one regen for %s (%d finding(s): %s) — "
            "holding the condensations; the read sites serve `content`",
            coach_id,
            len(_gate_findings),
            [f.get("type") for f in _gate_findings][:3],
        )
        extraction = coach_derived_prose.hold(extraction)

    # #1987: deterministic voice-register check (zero AI cost) — sibling to the item-7
    # anti_pattern_violations check above. Strips markdown emphasis unconditionally; if
    # what's left is still third-person coach register ("the coach", "the {domain}
    # coach"), reject it (write None). The read site (site_api_coach.py) already falls
    # back to `content` when `observatory_summary` is falsy — reusing that existing
    # fallback rather than inventing a new one here.
    observatory_summary, register_rejected = sanitize_summary(extraction.get("observatory_summary"))
    if register_rejected:
        logger.warning("observatory_summary rejected for %s (third-person coach register) — falling back to content at read time", coach_id)
    # #2343: same rejection seam, for the night the CONDENSATION dropped (see the module).
    observatory_summary = guard_derived_summary(observatory_summary, output_text, "observatory_summary", coach_id, logger)
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": f"OUTPUT#{date}#{output_type}",
        # #2569: named from the shared constant so a reader (the recall backfill) reads the
        # attribute this writer actually puts, instead of guessing `output_text`/`text`.
        COACH_OUTPUT_FIELD: output_text,
        "themes": extraction.get("themes", []),
        "structural_fingerprint": extraction.get("structural_fingerprint", {}),
        "predictions_made": extraction.get("predictions_made", []),
        "threads_referenced": [t.get("topic", "") for t in extraction.get("threads_referenced", [])],
        "threads_opened": [t.get("thread_slug", "") for t in extraction.get("threads_opened", [])],
        "decision_classes": extraction.get("decision_classes_used", []),
        "anti_pattern_violations": extraction.get("anti_pattern_violations", []),
        "observatory_summary": observatory_summary,
        "key_recommendation": extraction.get("key_recommendation"),
        "elena_quote": extraction.get("elena_quote"),
        "word_count": word_count,
        "created_at": now_iso,
    }
    if extraction.get("derived_prose_held"):
        item["derived_prose_held"] = True  # #2418: a grounding HOLD, not an empty extraction

    success = _put_item(item)
    if success:
        logger.info(
            "Wrote OUTPUT# for %s — %d words, %d themes, %d threads opened",
            coach_id,
            word_count,
            len(extraction.get("themes", [])),
            len(extraction.get("threads_opened", [])),
        )
    return success


def _update_voice_state(coach_id, extraction):
    """Update VOICE#state with latest opening type and flag overused patterns."""
    coach_pk = f"COACH#{coach_id}"
    current = _get_item(coach_pk, "VOICE#state")

    fingerprint = extraction.get("structural_fingerprint", {})
    opening_type = fingerprint.get("opening_type", "other")

    if current:
        recent_openings = current.get("recent_openings", [])
    else:
        recent_openings = []

    # Append latest opening and trim to max
    recent_openings.append(opening_type)
    recent_openings = recent_openings[-MAX_RECENT_OPENINGS:]

    # Detect overused patterns — check last STALENESS_WINDOW entries
    overused_patterns = []
    recent_window = recent_openings[-STALENESS_WINDOW:]
    if len(recent_window) >= STALENESS_THRESHOLD:
        from collections import Counter

        counts = Counter(recent_window)
        for pattern, count in counts.items():
            if count >= STALENESS_THRESHOLD:
                overused_patterns.append(f"opening_with_{pattern}")

    # Preserve existing signature patterns and anti-patterns
    signature_patterns = current.get("signature_patterns_to_reinforce", []) if current else []
    anti_patterns = current.get("anti_patterns", []) if current else []

    # Add any new anti-pattern violations detected
    violations = extraction.get("anti_pattern_violations", [])
    if violations:
        logger.warning("Anti-pattern violations detected for %s: %s", coach_id, violations)

    item = {
        "pk": coach_pk,
        "sk": "VOICE#state",
        "recent_openings": recent_openings,
        "overused_patterns": overused_patterns,
        "signature_patterns_to_reinforce": signature_patterns,
        "anti_patterns": anti_patterns,
        "last_violations": violations,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    success = _put_item(item)
    if success:
        logger.info(
            "Updated VOICE#state for %s — opening: %s, overused: %s",
            coach_id,
            opening_type,
            overused_patterns,
        )
    return success


def _create_thread_records(coach_id, date, threads_opened):
    """Create new THREAD# records for threads the coach opened."""
    now_iso = datetime.now(timezone.utc).isoformat()
    created = 0

    for thread in threads_opened:
        slug = thread.get("thread_slug", "unnamed")
        # Sanitize slug — lowercase, underscores only
        slug = slug.lower().replace(" ", "_").replace("-", "_")

        item = {
            "pk": f"COACH#{coach_id}",
            "sk": f"THREAD#{date}#{slug}",
            "status": "open",
            "type": thread.get("type", "observation"),
            "summary": thread.get("summary", ""),
            "opened_date": date,
            "last_referenced": date,
            "reference_count": 1,
            "related_predictions": [],
            "expected_resolution": "Data-dependent",
            "tags": thread.get("tags", []),
            "created_at": now_iso,
        }

        if _put_item(item):
            created += 1

    logger.info("Created %d new THREAD# records for %s", created, coach_id)
    return created


def _update_referenced_threads(coach_id, date, threads_referenced):
    """Update existing THREAD# records for threads the coach referenced.

    Bumps reference_count and updates last_referenced. Uses a best-effort
    topic match — queries all threads and matches by topic keyword.
    """
    if not threads_referenced:
        return 0

    coach_pk = f"COACH#{coach_id}"
    all_threads = _query_begins_with(coach_pk, "THREAD#")
    updated = 0

    for ref in threads_referenced:
        topic = ref.get("topic", "").lower()
        if not topic:
            continue

        # Find matching thread by keyword overlap
        for thread in all_threads:
            thread_summary = thread.get("summary", "").lower()
            thread_slug = thread.get("sk", "").lower()
            thread_tags = [t.lower() for t in thread.get("tags", [])]

            # Match if topic keywords appear in the thread's summary, slug, or tags
            topic_words = set(topic.split())
            match = False
            for word in topic_words:
                if len(word) < 3:
                    continue
                if word in thread_summary or word in thread_slug:
                    match = True
                    break
                if any(word in tag for tag in thread_tags):
                    match = True
                    break

            if match:
                # Update via DynamoDB update expression
                try:
                    table.update_item(
                        Key={"pk": coach_pk, "sk": thread["sk"]},
                        UpdateExpression=("SET last_referenced = :lr, " "reference_count = if_not_exists(reference_count, :zero) + :one"),
                        ExpressionAttributeValues=floats_to_decimal(
                            {
                                ":lr": date,
                                ":zero": 0,
                                ":one": 1,
                            }
                        ),
                    )
                    updated += 1
                    logger.debug("Updated thread %s for reference to '%s'", thread["sk"], topic)
                except Exception as e:
                    logger.warning("Failed to update thread %s: %s", thread.get("sk"), e)
                break  # Only update the first matching thread per reference

    logger.info("Updated %d existing THREAD# records for %s", updated, coach_id)
    return updated


def _build_reasoning_trace(coach_id, date, output_type, extraction):
    """Build a reasoning trace record from the extraction results."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build recommendations from threads opened + predictions
    recommendations = []
    for thread in extraction.get("threads_opened", []):
        if thread.get("type") in ("recommendation_pending", "concern"):
            recommendations.append(thread.get("summary", ""))

    # Primary drivers from themes
    themes = extraction.get("themes", [])

    # Predictions
    predictions = [p.get("claim_natural", "") for p in extraction.get("predictions_made", [])]

    cross_coach_inputs = []  # from threads_referenced that mention other coaches
    for ref in extraction.get("threads_referenced", []):
        topic = ref.get("topic", "")
        context = ref.get("context", "")
        # #2334 roster-copy waiver: a free-text keyword sniff, not a roster.
        if any(kw in topic.lower() or kw in context.lower() for kw in ["coach", "training", "nutrition", "mind", "glucose", "labs"]):
            cross_coach_inputs.append(f"{topic}: {context}")

    # Thread status summary
    threads_status = []
    for t in extraction.get("threads_opened", []):
        threads_status.append(
            {
                "thread": t.get("thread_slug", ""),
                "action": "opened",
                "type": t.get("type", "observation"),
            }
        )
    for t in extraction.get("threads_referenced", []):
        threads_status.append(
            {
                "thread": t.get("topic", ""),
                "action": "referenced",
            }
        )

    trace = {
        "pk": f"COACH#{coach_id}",
        "sk": f"TRACE#{date}#{output_type}",
        "recommendations_made": recommendations,
        "primary_drivers": themes[:5],  # Top 5 themes as primary drivers
        "counterfactuals_considered": [],  # Populated if extraction detects them
        "decision_classes_used": extraction.get("decision_classes_used", []),
        "cross_coach_inputs_used": cross_coach_inputs,
        "predictions_made": predictions,
        "threads_status": threads_status,
        "anti_pattern_violations": extraction.get("anti_pattern_violations", []),
        "created_at": now_iso,
    }

    return trace


# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════


def _build_default_extraction(output_text):
    """Build a minimal extraction when the LLM call fails.

    Better than nothing — captures basic structural info without AI analysis.
    """
    paragraphs = [p.strip() for p in output_text.split("\n\n") if p.strip()]

    return {
        "themes": [],
        "structural_fingerprint": {
            "opening_type": "other",
            "paragraph_count": len(paragraphs),
            "uses_analogy": False,
            "analogy_domain": None,
        },
        "threads_opened": [],
        "threads_referenced": [],
        "predictions_made": [],
        "commitments_made": [],
        "decision_classes_used": ["observational"],
        "anti_pattern_violations": [],
        "_fallback": True,
    }


def _timeframe_to_window_days(timeframe_hint, default=7):
    """Map a natural timeframe hint to a revisit window in days (commitments, #532)."""
    import re

    if not timeframe_hint:
        return default
    tf = str(timeframe_hint).lower()
    m = re.search(r"(\d+)", tf)
    n = int(m.group(1)) if m else None
    if "week" in tf:
        return (n or 1) * 7
    if "month" in tf:
        return (n or 1) * 30
    if "day" in tf:
        return n or default
    return default


def _create_commitment_records(coach_id, generation_date, commitments_made):
    """Create COMMITMENT# records — recommendations the coach must revisit (#532).

    A commitment is a concrete action the coach pushed the subject to take (distinct
    from a PREDICTION#, which is a claim about how data will move). Each carries a
    due window and, where the action maps to an allowlisted metric, a deterministic
    follow-through check (action_check: {metric, direction}) the evaluator grades as
    kept/broken. Metric-less commitments stay pending until the coach asks directly.
    Returns (created_count, checkable_count).
    """
    import re

    created = 0
    checkable = 0
    for c in commitments_made or []:
        text = (c.get("commitment_natural") or "").strip()
        if not text:
            continue
        raw_metric = c.get("action_check") or ""
        metric = _normalize_metric_hint(raw_metric) or "" if raw_metric else ""
        direction = None
        action_check = None
        if metric:
            direction = _infer_direction(c.get("direction"), text)
            if direction in ("up", "down"):
                action_check = {"metric": metric, "direction": direction}
                checkable += 1

        window_days = _timeframe_to_window_days(c.get("timeframe_hint"))
        try:
            due_date = (datetime.strptime(generation_date, "%Y-%m-%d") + timedelta(days=window_days)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            due_date = None

        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()[:40]).strip("_")
        commitment_id = f"commit_{generation_date.replace('-', '')}_{slug}"

        record = {
            "pk": f"COACH#{coach_id}",
            "sk": f"COMMITMENT#{commitment_id}",
            "commitment_id": commitment_id,
            "coach_id": coach_id,
            "created_date": generation_date,
            "commitment_natural": text,
            "action_check": action_check,  # {metric, direction} or None (qualitative)
            "window_days": window_days,
            "due_date": due_date,
            "status": "pending",  # pending -> kept | broken | unresolved
            "outcome": None,
            "outcome_date": None,
            "outcome_notes": None,
            "surfaced_to_subject": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if _put_item(record):
            created += 1
            logger.info("Created COMMITMENT# %s for %s (checkable=%s, due=%s)", commitment_id, coach_id, bool(action_check), due_date)
    return created, checkable


def _gather_relationship_signals(coach_id, since_date):
    """Query episodic records newer than `since_date` (YYYY-MM-DD, the previous
    RELATIONSHIP#state's last_interaction_date) for the #536 rapport writer:
    newly-graded COMMITMENT#/PREDICTION# outcomes and new board INTERACTION#s.

    Deterministic and fail-soft — a query error yields a zero signal for that
    category rather than blocking the run. `since_date` of None (first-ever
    cycle for this coach) returns all-zero signals; there's nothing to diff against.
    """
    signals = {
        "kept_commitments": 0,
        "broken_commitments": 0,
        "confirmed_predictions": 0,
        "refuted_predictions": 0,
        "board_interactions": 0,
    }
    if not since_date:
        return signals

    coach_pk = f"COACH#{coach_id}"

    try:
        for c in _query_begins_with(coach_pk, "COMMITMENT#"):
            outcome_date = c.get("outcome_date")
            if not outcome_date or outcome_date <= since_date:
                continue
            status = c.get("status")
            if status == "kept":
                signals["kept_commitments"] += 1
            elif status == "broken":
                signals["broken_commitments"] += 1
    except Exception as e:
        logger.warning("Relationship signal gather (commitments) failed for %s: %s", coach_id, e)

    try:
        for p in _query_begins_with(coach_pk, "PREDICTION#"):
            outcome_date = p.get("outcome_date")
            if not outcome_date or outcome_date <= since_date:
                continue
            status = p.get("status")
            if status == "confirmed":
                signals["confirmed_predictions"] += 1
            elif status == "refuted":
                signals["refuted_predictions"] += 1
    except Exception as e:
        logger.warning("Relationship signal gather (predictions) failed for %s: %s", coach_id, e)

    try:
        for i in _query_begins_with(coach_pk, "INTERACTION#"):
            created_date = str(i.get("created_at") or "")[:10]
            if created_date and created_date > since_date:
                signals["board_interactions"] += 1
    except Exception as e:
        logger.warning("Relationship signal gather (interactions) failed for %s: %s", coach_id, e)

    return signals


def _update_relationship_state(coach_id, generation_date):
    """Deterministically update RELATIONSHIP#state (#536) — no LLM involved.

    Reads the current record + episodic signals already written elsewhere
    (COMMITMENT#/PREDICTION# grading, INTERACTION# board Q&A), applies the
    rule-based rapport/phase update in relationship_engine.py, and writes the
    record read by coach_history_summarizer.py and coach_observatory_renderer.py.
    """
    coach_pk = f"COACH#{coach_id}"
    current = _get_item(coach_pk, "RELATIONSHIP#state")
    since_date = (current or {}).get("last_interaction_date")
    signals = _gather_relationship_signals(coach_id, since_date)

    updated = compute_relationship_update(
        current,
        coach_id,
        generation_date,
        signals,
        datetime.now(timezone.utc).isoformat(),
    )
    updated["pk"] = coach_pk
    updated["sk"] = "RELATIONSHIP#state"

    if _put_item(updated):
        logger.info(
            "Updated RELATIONSHIP#state for %s — phase=%s rapport=%.3f interactions=%d",
            coach_id,
            updated["journey_phase"],
            updated["rapport_level"],
            updated["interaction_count"],
        )
    return updated


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def lambda_handler(event, context):
    """Extract metadata from a coach's generated output and update state.

    Required event fields:
      - coach_id: str — e.g. "sleep_coach"
      - output_text: str — the full generated output text
      - output_type: str — e.g. "weekly_email", "daily_brief_section"
      - generation_date: str — YYYY-MM-DD format

    Returns the reasoning trace record.
    """
    # Validate required fields
    coach_id = event.get("coach_id")
    output_text = event.get("output_text")
    output_type = event.get("output_type", "weekly_email")
    generation_date = event.get("generation_date")

    if not coach_id:
        raise ValueError("Missing required field: coach_id")
    if not output_text:
        raise ValueError("Missing required field: output_text")
    if not generation_date:
        generation_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.warning("No generation_date provided — defaulting to %s", generation_date)

    logger.info(
        "Starting state update for %s — output_type: %s, date: %s, text_length: %d",
        coach_id,
        output_type,
        generation_date,
        len(output_text),
    )

    # Load voice spec from S3 for anti-pattern checking
    voice_spec = _load_voice_spec(coach_id)

    # Call Haiku to extract metadata
    user_message = _build_extraction_message(coach_id, output_text, output_type, voice_spec)

    try:
        extraction = _call_haiku(
            system=EXTRACTION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1500,
            temperature=0.1,
        )

        # Validate we got a dict
        if not isinstance(extraction, dict):
            logger.warning("LLM returned non-dict extraction for %s — using default", coach_id)
            extraction = _build_default_extraction(output_text)
    except Exception as e:
        logger.error("LLM extraction failed for %s: %s — using default", coach_id, e)
        extraction = _build_default_extraction(output_text)

    logger.info(
        "Extraction complete for %s — %d themes, %d threads opened, %d predictions",
        coach_id,
        len(extraction.get("themes", [])),
        len(extraction.get("threads_opened", [])),
        len(extraction.get("predictions_made", [])),
    )

    # Write state updates
    # 1. OUTPUT# record
    _write_output_record(coach_id, generation_date, output_type, output_text, extraction)

    # 2. VOICE#state update
    _update_voice_state(coach_id, extraction)

    # 3. New THREAD# records
    threads_opened = extraction.get("threads_opened", [])
    if threads_opened:
        _create_thread_records(coach_id, generation_date, threads_opened)

    # 4. Update referenced THREAD# records
    threads_referenced = extraction.get("threads_referenced", [])
    if threads_referenced:
        _update_referenced_threads(coach_id, generation_date, threads_referenced)

    # 5. Build and write reasoning trace
    trace = _build_reasoning_trace(coach_id, generation_date, output_type, extraction)
    _put_item(trace)
    logger.info("Wrote TRACE# record for %s/%s/%s", coach_id, generation_date, output_type)

    # 6. Create formal PREDICTION# records (Phase 4B)
    predictions_made = extraction.get("predictions_made", [])
    _gradable_n = 0  # SS-06: track directional (gradable) vs qualitative for the run metric
    _qualitative_n = 0
    _liveness_cache = {}  # #813: one data-liveness read per source per run
    for pred in predictions_made:
        claim = pred.get("claim_natural", "")
        if not claim:
            continue
        raw_metric_hint = pred.get("metric_hint", "") or ""
        # P5.7 part 2 (v7.16.0): normalize against MEASURABLE_METRICS. The
        # extractor's updated system prompt asks for allowlisted keys, but
        # prior coach outputs + LLM drift still produce prose. Normalize once
        # at the write boundary so the evaluator can resolve them — or fall
        # back to qualitative to avoid daily "no data" inconclusive churn.
        metric_hint = _normalize_metric_hint(raw_metric_hint) or ""
        if raw_metric_hint and not metric_hint:
            logger.info(
                "Prediction metric_hint %r did not normalize to MEASURABLE_METRICS — " "marking qualitative for coach=%s",
                raw_metric_hint,
                coach_id,
            )
        # #813: reject metrics whose source has no recent data — a gradable spec
        # over a dead source can only ever expire inconclusive and stalls the
        # public scorecard. Qualitative is the honest classification.
        if metric_hint and not _metric_has_recent_data(metric_hint, _liveness_cache):
            logger.info(
                "Prediction metric %r has <%d values in the last %d days — marking qualitative for coach=%s",
                metric_hint,
                _LIVENESS_MIN_POINTS,
                _LIVENESS_LOOKBACK_DAYS,
                coach_id,
            )
            metric_hint = ""
        timeframe_hint = pred.get("timeframe_hint", "")
        confidence_stated = pred.get("confidence_stated")
        # C-3 gradability: resolve the expected direction so a metric-backed claim
        # routes to the directional (EWMA) evaluator instead of a dead machine spec.
        direction = _infer_direction(pred.get("direction"), claim) if metric_hint else None

        # Build a slug-based prediction ID
        import re

        slug = re.sub(r"[^a-z0-9]+", "_", claim.lower()[:40]).strip("_")
        pred_id = f"pred_{generation_date.replace('-', '')}_{slug}"

        # Map timeframe hint to evaluation window days
        window_days = 14  # default
        if timeframe_hint:
            tf = timeframe_hint.lower()
            if "week" in tf:
                try:
                    n = int(re.search(r"(\d+)", tf).group(1))
                    window_days = n * 7
                except (AttributeError, ValueError):
                    window_days = 14
            elif "month" in tf:
                window_days = 30
            elif "day" in tf:
                try:
                    n = int(re.search(r"(\d+)", tf).group(1))
                    window_days = n
                except (AttributeError, ValueError):
                    window_days = 14

        # Determine subdomain from metric hint
        subdomain = "general"
        if metric_hint:
            mh = metric_hint.lower()
            for sd_key in ["sleep", "hrv", "recovery", "weight", "calories", "protein", "glucose", "training", "mood", "stress"]:
                if sd_key in mh:
                    subdomain = sd_key
                    break

        eval_spec = _build_prediction_eval_spec(metric_hint, direction, window_days)
        if eval_spec.get("type") == "directional":
            _gradable_n += 1
        else:
            _qualitative_n += 1

        pred_record = {
            "pk": f"COACH#{coach_id}",
            "sk": f"PREDICTION#{pred_id}",
            "prediction_id": pred_id,
            "coach_id": coach_id,
            "created_date": generation_date,
            "claim_natural": claim,
            "evaluation": eval_spec,
            "confidence": _parse_confidence(confidence_stated),
            "subdomain": subdomain,
            "confounders_noted": [],
            "status": "pending",
            "outcome": None,
            "outcome_date": None,
            "outcome_notes": None,
            "decision_class": (
                extraction.get("decision_classes_used", ["observational"])[0]
                if extraction.get("decision_classes_used")
                else "observational"
            ),
            "surfaced_to_subject": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _put_item(pred_record)
        logger.info("Created PREDICTION# %s for %s", pred_id, coach_id)

    # SS-06: surface the write-time gradable share so an extraction regression is
    # visible the same day, not weeks later when windows close (see the helper).
    _emit_prediction_gradability(_gradable_n, _qualitative_n)

    # 7. Create COMMITMENT# records (#532) — the recommendations the coach must
    # revisit. The evaluator grades the metric-backed ones kept/broken; the
    # orchestrator injects the due ones so the coach follows through on its own advice.
    commitments_made = extraction.get("commitments_made", [])
    if commitments_made:
        _c_created, _c_checkable = _create_commitment_records(coach_id, generation_date, commitments_made)
        logger.info("Commitments for %s: %d created (%d machine-checkable)", coach_id, _c_created, _c_checkable)

    # 8. Deterministically update RELATIONSHIP#state (#536) — rule-based rapport
    # arc read by coach_history_summarizer.py and coach_observatory_renderer.py.
    # Non-fatal: a failure here must never block the rest of the state update.
    try:
        _update_relationship_state(coach_id, generation_date)
    except Exception as e:
        logger.warning("RELATIONSHIP#state update failed for %s (non-fatal): %s", coach_id, e)

    # Return the trace (with Decimals converted for JSON serialization)
    return _decimal_to_float(trace)
