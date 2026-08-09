"""
AI Expert Analyzer Lambda — Observatory Intelligence Pipeline

Generates AI coach analyses for 8 observatory pages on averagejoematt.com.
This is the PRIMARY observatory content generator. NOT deprecated.

Two content pipelines exist in the platform:
  1. THIS Lambda → observatory pages (averagejoematt.com/sleep, /glucose, etc.)
     Reads: DynamoDB data partitions → generates with Intelligence Layer V2 preamble
     Writes: USER#matthew#SOURCE#ai_analysis EXPERT#{key} + EXPERT#integrator
     Served via: /api/ai_analysis and /api/coach_analysis endpoints

  2. Coach Intelligence pipeline (ai_calls.py) → daily brief email
     Reads: daily brief data dict → generates with voice specs + generation briefs
     Writes: COACH#{coach_id} OUTPUT# records

Both pipelines share intelligence_common.py utilities (data inventory, maturity,
goals, coach preamble, threads, validator) AND — since #531 — a shared persona
core: build_prompt() renders the SAME voice-spec fields (config/coaches/*.json
via persona_core) the daily-brief self writes from, so an expert here is the
same person as its brief + public-board selves. EXPERT_PERSONAS keeps only the
observatory-specific framing (title/focus/epistemology).

Features (V2.1):
  - Intelligence preamble: goals, data inventory, data maturity, first-person voice
  - Thread persistence: position summaries, predictions, surprises, emotional investment
  - Validator Mode B: inline correction on factual errors
  - Integrator synthesis: the board lead's weekly priority + cross-domain notes + disagreements
  - Builder's Paradox: injected into mind coach prompt

Trigger: EventBridge cron — weekly, Monday 6am PT (14:00 UTC)
Can also be invoked manually with {"expert": "mind"} for a single expert.

v3.0.0 — 2026-04-07 (Intelligence Layer V2.1)
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import boto3
from boto3.dynamodb.conditions import Key

# #1993: labs fact extraction against the real draw-record schema (SCHEMA.md).
from intelligence.labs_facts import build_labs_fact_block

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Intelligence Layer V2: shared preamble utilities
try:
    from intelligence.intelligence_common import (
        apply_movement_honesty_guard,
        build_coach_preamble,
        build_data_inventory,
        build_data_maturity,
        build_thread_prompt_block,
        extract_thread_from_narrative,
        load_goals_config,
        movement_assessability,
        write_coach_thread,
    )

    _HAS_INTELLIGENCE_COMMON = True
except ImportError:
    _HAS_INTELLIGENCE_COMMON = False
    logger.warning("intelligence_common not available — preamble injection disabled")

# Phase-3 grounding backstop: deviation + HRV-unit checks against the shared facts.
try:
    from ai import ai_output_validator as _aiv

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# #531: shared persona core — one voice-spec rendering across brief/board/observatory.
try:
    from coach import persona_core as _persona_core
except ImportError:  # pragma: no cover — environment-dependent
    _persona_core = None
    logger.warning("persona_core not available — expert prompts keep persona-dict voice only")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
CACHE_PK = f"{USER_PREFIX}ai_analysis"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")

# #2334: derived from the persona registry; EXPERT_PERSONAS coverage asserted in the set guard.
from coach.persona_registry import OPERATIONAL_SHORT_IDS

from intelligence.expert_personas import BANNED_OPENER_SCAFFOLDS, EXPERT_PERSONAS  # noqa: F401  (re-export, #1654)

EXPERTS = list(OPERATIONAL_SHORT_IDS)

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)
# #531: voice specs live at S3 config/coaches/ (role already has config/* read).
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
s3 = boto3.client("s3", region_name="us-west-2")

_api_key_cache = None


def _get_api_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
    secret = resp["SecretString"]
    # Handle JSON-wrapped secret (life-platform/ai-keys has {"anthropic_api_key": "..."})
    try:
        parsed = json.loads(secret)
        _api_key_cache = parsed.get("anthropic_api_key", secret)
    except (json.JSONDecodeError, TypeError):
        _api_key_cache = secret
    return _api_key_cache


from common.numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401
from experiment import phase_taxonomy as _phase_taxonomy  # noqa: E402 — #2113: ADR-077 read bound


def _query_source(source, start_date, end_date):
    pk = f"{USER_PREFIX}{source}"
    start_date = _phase_taxonomy.cycle_read_floor(pk, start_date)  # #2113: genesis floor, EXPERIMENT_SCOPED only
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"))
    return _decimal_to_float(resp.get("Items", []))


def _latest_item(source):
    pk = f"{USER_PREFIX}{source}"
    kce = Key("pk").eq(pk)
    floor = _phase_taxonomy.cycle_read_floor(pk)  # #2113: None unless EXPERIMENT_SCOPED
    if floor:
        kce = kce & Key("sk").between(f"DATE#{floor}", "DATE#9999-12-31")
    resp = table.query(KeyConditionExpression=kce, ScanIndexForward=False, Limit=1)
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


from common.constants import EXPERIMENT_START_DATE as EXPERIMENT_START  # ADR-058

_CANON_FACTS_CACHE: dict[str, Any] = {}


def _load_canonical_facts():
    """The ONE authoritative set of cross-cutting daily numbers every coach shares.

    Read from the latest `computed_metrics` record (Phase-3: daily_metrics_compute is
    the single computer of these). Every coach prompt cites these exact figures and the
    grounding pass checks against them, so the same metric can't appear as 140/170/190
    across coaches or 30-vs-86 across a page. Returns floats (or None when absent);
    cached per warm container per run.
    """
    if _CANON_FACTS_CACHE.get("_loaded"):
        return _CANON_FACTS_CACHE["facts"]
    facts = {}
    try:
        # Phase 2 (Coherence Program): the field list + units + rounding now live in
        # ONE schema (canonical_facts.build_canonical_facts) that the Coherence Sentinel
        # also reads — so the value a coach is grounded on is exactly the value the
        # Sentinel checks the narrative against. No more per-site dict construction.
        from experiment.canonical_facts import build_canonical_facts

        _cm = _latest_item("computed_metrics") or {}
        facts = build_canonical_facts(_cm)
        # #914-B: weight-rate honesty riders. The live incident: "maintained a
        # 7.3 lb/week trajectory" cited 14 days after the last weigh-in (the rate's
        # 12-day span ENDED 2026-06-26 — nothing was being "maintained"). Carry the
        # producer's provisional flag + the real scale recency so the facts block
        # (grounded_generation.authoritative_facts_block) can force past-tense,
        # dated rate language once the scale goes dark.
        facts["rate_provisional"] = bool(_cm.get("rate_provisional"))
        _w = _latest_item("withings") or {}
        _w_date = str(_w.get("sk", ""))[5:15] if str(_w.get("sk", "")).startswith("DATE#") else None
        if _w_date:
            facts["last_weighin_date"] = _w_date
            try:
                facts["days_since_weighin"] = max(
                    0, (datetime.now(timezone.utc).date() - datetime.strptime(_w_date, "%Y-%m-%d").date()).days
                )
            except ValueError:
                pass
    except Exception as _e:
        logger.warning("canonical facts load failed: %s", _e)
    _CANON_FACTS_CACHE["facts"] = facts
    _CANON_FACTS_CACHE["_loaded"] = True
    return facts


# SS-10 (2026-07-02): the tight contradiction detector moved VERBATIM to the shared
# bundled module grounding_guard.py so the field note (public Third Wall, previously
# ungated) uses the same proven guard instead of a drifting copy. The private name is
# kept as an alias — every internal call site and test stays untouched. Dual-style
# import: package path in prod (handler intelligence.*), flat path in tests.
try:
    from intelligence.grounding_guard import hard_canonical_contradictions as _hard_canonical_contradictions
except ImportError:  # pragma: no cover — flat sys.path (tests)
    if not TYPE_CHECKING:  # one canonical module name for mypy; runtime unchanged (#1656)
        from grounding_guard import hard_canonical_contradictions as _hard_canonical_contradictions  # noqa: F401

# ADR-104: the shared grounded-generation harness — the regen-once keep-if-improved
# flow moved there (one implementation for every surface), plus the allow-list
# number gate that catches fabricated trends ("from 58 to 64" with no 58 anywhere).
from ai import grounded_generation as _gg
from ai.behavior_logs import available_logs_from_recency as _avail_logs  # #2056 — the #1699 map
from ai.night_scope import nightly_vitals_from_facts as _night_map  # #1968

from intelligence import weight_recency

# #2056 (ADR-080 §2): the DATE#-recency helpers moved to intelligence/item_recency.py so
# this handler stays under its 2,000-line cap while the grounding wiring lands. Private
# aliases preserved — every internal call site and test reads `_recency_stats` unchanged.
from intelligence.item_recency import item_dates as _item_dates, latest_date as _latest_date, recency_stats as _recency_stats


def _read_movement_ingest_health(sources=("strava", "garmin")):
    """C-4 (#494): read the INGEST_HEALTH sentinels for the movement sources and return
    their infra-liveness status ({source: 'ok'|'stale'|'failing'|'unknown'}).

    This is the signal that lets the honesty guard tell behavioral rest (pipe ran, fetched,
    returned nothing) from pipe breakage (auth/throttle/cron down). Read-only — the sentinel
    is *written* by the ingestion framework; we only consult it. Best-effort: any failure
    yields {} so movement_assessability falls back to the conservative records-only read.
    """
    out = {}
    try:
        from ingestion.ingest_health import SYSTEM_PK, evaluate_source_health, ingest_health_sk
    except Exception as e:  # ingest_health absent from the bundle → conservative fallback
        logger.warning("ingest_health unavailable; movement guard falls back to records-only: %s", e)
        return out
    now = datetime.now(timezone.utc)
    for src in sources:
        try:
            resp = table.get_item(Key={"pk": SYSTEM_PK, "sk": ingest_health_sk(src)})
            verdict = evaluate_source_health(resp.get("Item"), now=now, source=src)
            out[src] = verdict.get("status", "unknown")
        except Exception as e:
            logger.warning("INGEST_HEALTH read failed for %s: %s", src, e)
    return out


def gather_data_for_expert(expert_key):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Clamp lookback to experiment start — data before April 1 is pre-experiment
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    days_in_experiment = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)

    if expert_key == "mind":
        # Journal analysis + mood + vice streaks
        ja_items = _query_source("journal_analysis", d30, today)
        # SoM daily aggregates live on the apple_health partition (som_avg_valence),
        # not a separate state_of_mind partition.
        som_items = [s for s in _query_source("apple_health", d30, today) if s.get("som_avg_valence") is not None]
        avg_sentiment = 0
        if ja_items:
            scores = [float(i.get("sentiment_score", 0)) for i in ja_items]
            avg_sentiment = round(sum(scores) / len(scores), 2) if scores else 0
        # Top themes
        theme_counts = {}
        for item in ja_items:
            for t in item.get("themes", []):
                theme_counts[t] = theme_counts.get(t, 0) + 1
        top_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        avg_valence = 0
        if som_items:
            vals = [float(s.get("som_avg_valence", 0)) for s in som_items if s.get("som_avg_valence") is not None]
            avg_valence = round(sum(vals) / len(vals), 2) if vals else 0

        # #914 anti-dilution: recency alongside the whole-window totals.
        _j_since, _j_14 = _recency_stats(_item_dates(ja_items), today)
        return {
            "expert_key": "mind",
            "period": f"experiment days 1-{days_in_experiment}",
            "journal_entry_count": len(ja_items),
            "days_since_last_journal": _j_since,
            "journal_entries_last_14d": _j_14,
            "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
            "avg_sentiment": avg_sentiment,
            "mood_readings": len(som_items),
            "avg_valence": avg_valence,
        }

    elif expert_key == "nutrition":
        items = _query_source("macrofactor", d30, today)
        # Nutrition is a manual end-of-day upload — structurally ~24h behind. The latest
        # COMPLETE day (normally yesterday) is the live state; an absent current day is
        # EXPECTED and is never a logging failure. Surfaced so the coach never says so.
        _recency_note = "Nutrition logs at end of day (manual upload), so data runs through the latest complete day; an absent current day is expected pipeline lag, never a logging failure — do not frame it as one."
        if not items:
            return {
                "expert_key": "nutrition",
                "period": f"experiment days 1-{days_in_experiment}",
                "note": "No nutrition data available",
                "days_since_last_food_log": None,
                "food_logs_last_14d": 0,
                "recency_note": _recency_note,
            }
        cal_vals = [float(i["total_calories_kcal"]) for i in items if i.get("total_calories_kcal")]
        pro_vals = [float(i["total_protein_g"]) for i in items if i.get("total_protein_g")]
        fiber_vals = [float(i["total_fiber_g"]) for i in items if i.get("total_fiber_g")]
        avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else 0
        avg_pro = round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else 0
        avg_fiber = round(sum(fiber_vals) / len(fiber_vals), 1) if fiber_vals else None
        # Phase-3: target from the canonical facts (computed_metrics), not a hardcoded 190
        # that drifts from scoring_engine/profile. avg_pro is the real intake (~140).
        _facts = _load_canonical_facts()
        protein_target = int(_facts.get("protein_g_target") or 190)
        adherence = sum(1 for v in pro_vals if v >= protein_target) / max(len(pro_vals), 1) * 100
        zero_cal_days = sum(1 for i in items if i.get("total_calories_kcal") is not None and float(i.get("total_calories_kcal", 0)) == 0)
        # #914 anti-dilution: recency alongside the whole-window averages.
        _f_since, _f_14 = _recency_stats(_item_dates(items), today)
        return {
            "expert_key": "nutrition",
            "period": f"experiment days 1-{days_in_experiment}",
            "days_since_last_food_log": _f_since,
            "food_logs_last_14d": _f_14,
            "avg_calories": avg_cal,
            "avg_protein_g": avg_pro,
            "avg_fiber_g": avg_fiber,
            "protein_target_g": protein_target,
            "protein_adherence_pct": round(adherence),
            "days_tracked": len(items),
            "zero_calorie_days": zero_cal_days,
            "recency_note": _recency_note,
        }

    elif expert_key == "training":
        # DI-1.3: Hevy is the PRIMARY "did he train" signal (TRAINING_CALIBRATION §4a) —
        # the training-stimulus read is built off Hevy first, then Strava for aerobic/NEAT,
        # never off steps. Strava is paused (402) and Garmin rate-limited, so a Strava-only
        # read collapses to "all rest days" and produces a false under-training verdict.
        from ingestion.source_state import has_rate_limit_marker, resolve_source_state

        hevy_items = _query_source("hevy", d30, today)
        activities = _query_source("strava", d30, today)
        garmin_items = _query_source("garmin", d30, today)
        whoop_items = _query_source("whoop", d30, today)
        steps_items = _query_source("apple_health", d30, today)

        _garmin_rl = has_rate_limit_marker(table, USER_ID, "garmin")
        _garmin_state = resolve_source_state("garmin", _latest_date(garmin_items), today, rate_limited=_garmin_rl)

        # DI-1.4: state-aware step precedence. The watch (via Garmin) is the better step
        # counter WHEN live, but a rate-limited/stale Garmin emits sparse partial readings
        # (e.g. 298 steps on 6/15) that misrepresent movement — averaging those was the
        # "phantom 298" bug. Use Garmin steps only when Garmin is live; else Apple Health.
        if _garmin_state == "live":
            step_vals = [float(g["steps"]) for g in garmin_items if g.get("steps")]
            step_source = "garmin"
        else:
            step_vals = [float(s["steps"]) for s in steps_items if s.get("steps") and float(s["steps"]) > 0]
            step_source = "apple_health"
        avg_steps = round(sum(step_vals) / len(step_vals)) if step_vals else 0
        # Step completeness = days with a usable step value / experiment days (DI-1.4 flag).
        step_completeness_pct = round(len(step_vals) / max(1, days_in_experiment) * 100)

        # Hevy (lifting) — primary training-stimulus signal.
        hevy_dates = set(str(h.get("sk", ""))[5:15] for h in hevy_items if str(h.get("sk", "")).startswith("DATE#"))
        hevy_sessions = len(hevy_items)
        hevy_sets = sum(int(float(h.get("set_count") or 0)) for h in hevy_items)
        hevy_min = round(sum(float(h.get("duration_sec") or 0) / 60 for h in hevy_items))

        # Strava (aerobic/NEAT) — secondary; only counted when live.
        strava_min = sum(float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0) / 60 for a in activities)
        strava_dates = set(a.get("sk", "")[:15].replace("DATE#", "") for a in activities if a.get("sk"))
        recovery_vals = [float(w["recovery_score"]) for w in whoop_items if w.get("recovery_score")]
        avg_recovery = round(sum(recovery_vals) / len(recovery_vals), 1) if recovery_vals else None

        modalities = {}
        if hevy_sessions:
            modalities["strength"] = hevy_sessions
        for a in activities:
            t = a.get("type", "unknown")
            modalities[t] = modalities.get(t, 0) + 1

        # A training day = a day with ANY logged workout (Hevy OR Strava).
        training_dates = hevy_dates | strava_dates
        rest_days = max(0, days_in_experiment - len(training_dates))

        # Movement-source state for the honesty guard (DI-1.1 source-state resolver):
        # live / paused / rate_limited / stale. Freshness wins for 'live' — so when Strava
        # re-ingests, strava flips paused→live and the guard stops withholding.
        source_state = {
            "hevy": resolve_source_state("hevy", _latest_date(hevy_items), today),
            "strava": resolve_source_state("strava", _latest_date(activities), today),
            "garmin": _garmin_state,
            "steps": "live" if step_vals else "missing",
        }
        # C-4 (#494): the INGEST_HEALTH sentinel disambiguates behavioral rest (pipe live,
        # no records → assessable-as-rest) from pipe breakage (not assessable → stay honest).
        movement_ingest_health = _read_movement_ingest_health()
        hevy_summary = (
            f"{hevy_sessions} Hevy session(s), {hevy_sets} sets, {hevy_min} min over {len(hevy_dates)} day(s)" if hevy_sessions else ""
        )
        # #914 anti-dilution: recency alongside the whole-window totals — so
        # "9 sessions across 4 weeks" can't mask "0 in the last 15 days".
        _lift_since, _ = _recency_stats(hevy_dates, today)
        _, _sessions_14 = _recency_stats(training_dates, today)
        return {
            "expert_key": "training",
            "period": f"experiment days 1-{days_in_experiment}",
            "training_days": len(training_dates),
            "days_since_last_lift": _lift_since,
            "sessions_last_14d": _sessions_14,
            "hevy_sessions": hevy_sessions,
            "hevy_sets": hevy_sets,
            "hevy_active_min": hevy_min,
            "strava_sessions": len(activities),
            "strava_active_min": round(strava_min),
            "total_active_min": round(hevy_min + strava_min),
            "avg_daily_steps": avg_steps,
            "step_source": step_source,
            "step_completeness_pct": step_completeness_pct,
            "avg_recovery": avg_recovery,
            "rest_days": rest_days,
            "modality_breakdown": modalities,
            "movement_source_state": source_state,
            "movement_ingest_health": movement_ingest_health,
            "hevy_summary": hevy_summary,
        }

    elif expert_key == "physical":
        # DEXA + measurements + weight
        dexa = _latest_item("dexa")
        meas = _latest_item("measurements")
        weight_items = _query_source("withings", d30, today)

        data = {
            "expert_key": "physical",
            "period": f"experiment days 1-{days_in_experiment}",
            # #1894: each weight fact carries its own reading date + staleness, so a
            # stale weigh-in can't be narrated as today's. See intelligence/weight_recency.
            **weight_recency.summarize_weight_readings(weight_items, today),
        }
        if dexa:
            bc = dexa.get("body_composition", {})
            data["body_fat_pct"] = float(bc.get("body_fat_pct", 0)) if bc.get("body_fat_pct") else None
            data["lean_mass_lb"] = float(bc.get("lean_mass_lb", 0)) if bc.get("lean_mass_lb") else None
            data["visceral_fat_lb"] = float(bc.get("visceral_fat_lb", 0)) if bc.get("visceral_fat_lb") else None
            data["days_since_dexa"] = (
                datetime.now(timezone.utc) - datetime.strptime(dexa.get("scan_date", today), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ).days
        if meas:
            whr = meas.get("waist_height_ratio")
            if whr:
                data["waist_height_ratio"] = float(whr)
        return data

    elif expert_key == "explorer":
        # Cross-domain correlations + high-level experiment status
        # Query weekly correlations if they exist
        corr_items = _query_source("weekly_correlations", d30, today)
        sig_pairs = []
        for c in corr_items:
            pairs = c.get("pairs") or c.get("significant_pairs") or []
            if isinstance(pairs, list):
                sig_pairs.extend(pairs)
        # Active experiments
        exp_pk = f"{USER_PREFIX}experiments"
        try:
            exp_resp = table.query(
                KeyConditionExpression=Key("pk").eq(exp_pk),
                ScanIndexForward=False,
                Limit=10,
            )
            experiments = _decimal_to_float(exp_resp.get("Items", []))
            active_exps = [e for e in experiments if e.get("status") == "active"]
        except Exception:
            active_exps = []

        return {
            "expert_key": "explorer",
            "period": f"experiment days 1-{days_in_experiment}",
            "significant_correlations": len(sig_pairs),
            "top_pairs": sig_pairs[:5] if sig_pairs else [],
            "active_experiments": len(active_exps),
            "experiment_names": [e.get("name", "") for e in active_exps[:3]],
        }

    elif expert_key == "glucose":
        # CGM data is stored under apple_health with pre-aggregated blood_glucose_* fields
        cgm_items = _query_source("apple_health", d30, today)
        glucose_days = [i for i in cgm_items if i.get("blood_glucose_avg") is not None]
        avg_vals = [float(i["blood_glucose_avg"]) for i in glucose_days]
        avg_glucose = round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else None
        tir_vals = [
            float(i["blood_glucose_time_in_range_pct"]) for i in glucose_days if i.get("blood_glucose_time_in_range_pct") is not None
        ]
        tir_pct = round(sum(tir_vals) / len(tir_vals), 1) if tir_vals else None
        sd_vals = [float(i["blood_glucose_std_dev"]) for i in glucose_days if i.get("blood_glucose_std_dev") is not None]
        std_dev = round(sum(sd_vals) / len(sd_vals), 1) if sd_vals else None
        total_readings = sum(int(float(i.get("blood_glucose_readings_count", 0))) for i in glucose_days)
        return {
            "expert_key": "glucose",
            "period": f"experiment days 1-{days_in_experiment}",
            "total_readings": total_readings,
            "days_with_data": len(glucose_days),
            "avg_glucose_mg_dl": avg_glucose,
            "time_in_range_pct": tir_pct,
            "std_dev": std_dev,
        }

    elif expert_key == "labs":
        # Labs data spans all-time (not limited to experiment window — draws are periodic).
        # #1993: extraction reads the REAL draw-record schema (nested `biomarkers` map +
        # `out_of_range` list — SCHEMA.md) via labs_facts. The old top-level *_flag hunt
        # matched a schema that never existed, so flagged_count was 0 against every real
        # draw and the coach narrated the empty extraction as a sync failure (ADR-104).
        lab_items = _query_source("labs", "2019-01-01", today)
        return build_labs_fact_block(lab_items)

    elif expert_key == "sleep":
        whoop_items = _query_source("whoop", d30, today)
        eight_items = _query_source("eightsleep", d30, today)
        sleep_hours = [float(w["sleep_duration_hours"]) for w in whoop_items if w.get("sleep_duration_hours")]
        recovery_vals = [float(w["recovery_score"]) for w in whoop_items if w.get("recovery_score")]
        hrv_vals = [float(w["hrv"]) for w in whoop_items if w.get("hrv")]
        score_vals = [float(e["sleep_score"]) for e in eight_items if e.get("sleep_score")]
        deep_pcts = [float(e["deep_pct"]) for e in eight_items if e.get("deep_pct")]
        rem_pcts = [float(e["rem_pct"]) for e in eight_items if e.get("rem_pct")]
        # bed_temp retired (ADR-118, #489): Eight Sleep temp pipeline is dead.
        sleep_starts = [w.get("sleep_start") for w in whoop_items if w.get("sleep_start")]
        avg = lambda lst: round(sum(lst) / len(lst), 1) if lst else None
        return {
            "expert_key": "sleep",
            "period": f"experiment days 1-{days_in_experiment}",
            "nights_tracked": len(whoop_items),
            "avg_sleep_hours": avg(sleep_hours),
            "avg_sleep_score": avg(score_vals),
            "avg_recovery": avg(recovery_vals),
            "avg_hrv": avg(hrv_vals),
            "avg_deep_pct": avg(deep_pcts),
            "avg_rem_pct": avg(rem_pcts),
            "sleep_onset_times": sleep_starts[-7:],
        }

    return {"expert_key": expert_key, "note": "Unknown expert"}


def build_prompt(expert_key, data, days_in_experiment=None, week_number=None):
    p = EXPERT_PERSONAS[expert_key]
    if days_in_experiment is None:
        days_in_experiment = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
    week_num = week_number or max(1, days_in_experiment // 7 + 1)

    prior_summary = data.pop("_prior_analysis_summary", "")
    prior_recommendation = data.pop("_prior_recommendation", "")
    data_json = json.dumps(data, indent=2, default=str)

    # Rotating analytical lens — prevents repetitive framing
    lenses = [
        "Focus on the most surprising or counterintuitive finding in this data.",
        "Focus on what changed since last week and whether the direction matters.",
        "Focus on what the data does NOT show — the gaps, the missing signal, the dog that didn't bark.",
        "Focus on one specific number and explain why it matters more than it appears.",
        "Focus on the interaction between two metrics that tells a story neither tells alone.",
        "Focus on whether Matthew's current trajectory is sustainable for 3 more months.",
        "Focus on what a clinician would flag if this were a patient chart review.",
    ]
    lens = lenses[(week_num - 1) % len(lenses)]

    prior_block = ""
    if prior_summary:
        prior_block = f"""
Your PREVIOUS analysis said: "{prior_summary[:300]}..."
Your PREVIOUS recommendation was: "{prior_recommendation[:200]}..."

CRITICAL: Do NOT repeat the same observation, angle, or recommendation. Find a genuinely
different insight. If you previously discussed deep sleep percentage, discuss something else
this week — consistency, efficiency, HRV trend, or a cross-domain connection. The reader
has already read your last analysis and will notice repetition immediately.
"""

    # DI-1.3: movement-integrity constraint — when the aerobic/NEAT sources can't see
    # activity, instruct the coach to withhold the under-training verdict (the deterministic
    # guard at write-time is the backstop; this keeps the narrative itself honest).
    movement_context = ""
    if expert_key == "training" and _HAS_INTELLIGENCE_COMMON:
        try:
            _assess = movement_assessability(data.get("movement_source_state"), data.get("movement_ingest_health"))
            if not _assess["assessable"]:
                movement_context = f"""
MOVEMENT DATA INTEGRITY — READ BEFORE ASSESSING TRAINING:
{_assess['note']}. These are NOT live ingest paths right now, so NEAT/aerobic volume
is NOT ASSESSABLE this period. Hevy (strength) IS the authoritative training-stimulus
signal and is present in the data above — reason about training load from Hevy, never
from steps or from the absence of Strava/Garmin. Do NOT call this under-training,
sedentary, or low-stimulus. State plainly that aerobic/NEAT volume can't be assessed
until those sources are live, and assess what Hevy shows.
"""
            elif _assess.get("assessable_as_rest"):
                # C-4 (#494): no fresh movement records, but the ingestion pipe is CONFIRMED
                # LIVE — this is genuine behavioral rest, not a data gap. The verdict is
                # available; frame it honestly ("no activity logged, pipe confirmed live").
                movement_context = f"""
MOVEMENT DATA INTEGRITY — READ BEFORE ASSESSING TRAINING:
{_assess['rest_note']}. Because the ingestion pipe is confirmed live and returned no
activity, you MAY honestly characterize this as rest / low aerobic volume — but frame it
as a behavioral choice ("no activity logged, pipe confirmed live"), NOT as a data gap and
NOT as an alarm. Hevy (strength) remains the authoritative training-stimulus signal — read
training load from Hevy first, then note the confirmed-empty aerobic/NEAT picture.
"""
        except Exception as _me:
            logger.warning("movement assessability failed: %s", _me)

    labs_context = ""
    if expert_key == "labs":
        labs_context = f"""
IMPORTANT: Lab data spans Matthew's full history, not just the current experiment.
The data shows {data.get('total_draws', 0)} total blood draws, with the most recent
on {data.get('draw_date', 'unknown')}. Do NOT describe this as "draws during the
experiment" — these are periodic lab draws over time.
DATA-INTEGRITY GROUND RULES (ADR-104, #1993): you may describe the labs store as
empty ("zero results", "no draws", "a sync failure") ONLY when store_empty is true
in the data above. When draws exist, flagged_count of 0 means every extracted
biomarker was in range — an unremarkable panel, never a data failure. If
extraction_incomplete appears, name it as a platform extraction gap on real draws,
not as missing labs.
"""

    # #1894: forbid day-labelling a stale weigh-in (silent when fresh).
    weight_context = weight_recency.weight_recency_prompt_block(data) if expert_key == "physical" else ""

    # Build intelligence preamble (goals, data inventory, data maturity, first-person voice)
    preamble_block = ""
    if _HAS_INTELLIGENCE_COMMON:
        try:
            _inventory = build_data_inventory()
            _maturity = build_data_maturity(_inventory)
            _goals = load_goals_config()
            preamble_block = build_coach_preamble(
                coach_name=p["name"],
                domain=expert_key,
                goals=_goals,
                inventory=_inventory,
                maturity=_maturity,
            )
            # Builder's Paradox: inject into mind coach prompt
            if expert_key == "mind":
                try:
                    from intelligence.intelligence_common import compute_builders_paradox_score

                    bp = compute_builders_paradox_score(days=7)
                    if bp.get("label") == "insufficient_data":
                        # #1658 (ADR-104): no platform AND no health observations in the
                        # window — there is no ratio, so inject nothing rather than a
                        # midpoint verdict derived from an absence.
                        logger.info("Builder's Paradox unscored this window: %s", bp["interpretation"])
                    else:
                        bp_block = (
                            f"\nBUILDER'S PARADOX CHECK:\n"
                            f"This week's score: {bp['score']}/100 ({bp['label']})\n"
                            f"Platform tasks completed: {bp['platform_tasks']}\n"
                            f"Workouts: {bp['workouts']}\n"
                            f"Journal entries: {bp['journal_entries']}\n"
                            f"Habit adherence: {bp['habit_adherence_pct']}% (n={bp['habit_days']} days)\n"
                            f"Avg daily steps: {bp['avg_steps']} (n={bp['step_days']} days)\n"
                            f"\n{bp['interpretation']}\n"
                            f"\nIf score > 50: You MUST address this directly. Not as a side note — "
                            f'as the lead finding. The question to ask: "Is the building serving '
                            f'the transformation, or replacing it?" Be direct. Matthew respects '
                            f"honesty over comfort.\n"
                        )
                        preamble_block += bp_block
                except Exception as _bp_e:
                    logger.warning("Builder's Paradox computation failed: %s", _bp_e)
            # V2.1: Thread injection — persistent memory for each coach
            try:
                _personality = p.get("personality", {})
                _thread_block = build_thread_prompt_block(expert_key, personality=_personality)
                if _thread_block:
                    preamble_block += "\n" + _thread_block
            except Exception as _th_e:
                logger.warning("Thread injection failed for %s: %s", expert_key, _th_e)
        except Exception as _e:
            logger.warning("Preamble generation failed: %s — proceeding without", _e)
            preamble_block = (
                f"VOICE: Write in FIRST PERSON. You ARE {p['name']}. Say \"I\" not \"{p['name']}\". Address Matthew directly as \"you\".\n"
            )
    else:
        preamble_block = (
            f"VOICE: Write in FIRST PERSON. You ARE {p['name']}. Say \"I\" not \"{p['name']}\". Address Matthew directly as \"you\".\n"
        )

    # #531: the shared persona core — the same voice-spec fields the daily-brief
    # and public-board selves write from. Fail-soft: "" keeps the pre-#531 prompt.
    voice_core = ""
    if _persona_core is not None:
        try:
            voice_core = _persona_core.persona_block(f"{expert_key}_coach", s3_client=s3, bucket=S3_BUCKET)
        except Exception as _vc_e:
            logger.warning("persona core unavailable for %s (fail-soft): %s", expert_key, _vc_e)

    # #821 (R22 CONTENT-05): per-coach opening register + anti-template constraint.
    # Voice guidance only — the grounding gate reads the whole prompt for allowed
    # numbers, so this block deliberately contains NO digits.
    banned_openers = "; ".join(f'"{s}"' for s in BANNED_OPENER_SCAFFOLDS)
    opening_register_block = f"""YOUR OPENING REGISTER (anti-template — eight minds, not one voice in hats):
- {p['opening_register']}
- Lead with YOUR domain's read. A platform-wide event (a logging gap, a return, a milestone)
  is never your opening line — when every coach opens on the same event, the eight of you
  read as one templated voice. If such an event genuinely matters to your analysis,
  acknowledge it later, in your own domain's terms.
- NEVER open with any of these shared-scaffold phrases, or a close paraphrase of them:
  {banned_openers}.
- Ground any figure you open with in your data or the AUTHORITATIVE FACTS — never invent
  a number to fit the register.
- The test: if your first sentence could plausibly appear under another coach's byline,
  rewrite it until it couldn't."""

    return f"""You are {p['name']}, {p['title']}.

Your communication style: {p['style']}.
Your analytical focus: {p['focus']}.
{p.get('epistemology', '')}

{voice_core}

{preamble_block}

You are writing your weekly analysis for Matthew's public health experiment (averagejoematt.com).
This is Week {week_num} of the experiment (started {EXPERIMENT_START}, now day {days_in_experiment}).
Your analysis is the CENTERPIECE of the observatory page — it appears at position 2,
immediately after the key metrics. Returning readers come back specifically to read
what you have to say this week. This is a weekly appointment, not a generic report.

ANALYTICAL LENS FOR THIS WEEK: {lens}
{labs_context}
{movement_context}
{weight_context}

Here is Matthew's current data:
{data_json}

{prior_block}

Write a 2-3 paragraph analysis (200-300 words). Requirements:

STRUCTURE:
- Paragraph 1: Open with ONE specific, concrete observation from YOUR OWN domain,
  in your opening register (below) — vary your opening each week.
- Paragraph 2: Interpret the pattern. What does it mean clinically/practically?
  Connect to another domain if relevant (sleep affects glucose, training affects
  recovery, etc.). Use your expertise to say something a dashboard cannot.
- Paragraph 3: One specific, actionable suggestion for the coming week. Be concrete
  enough that Matthew can do it tomorrow. Not "sleep more" but "try anchoring sleep
  onset to within a 30-minute window each night."

VOICE:
- First person as yourself. You are a real expert having a weekly conversation.
- Reference specific numbers naturally — don't list them, weave them into insight.
- Be honest. If the data is concerning, say so. If it's encouraging, explain why
  without being sycophantic. If it's too early to draw conclusions, say that.
- Write as if Matthew and 500 subscribers are reading this on Wednesday morning
  with their coffee. Be worth their time.
- Do NOT use bullet points, headers, or formatting. Flowing prose only.
- Vary sentence length. Mix short declarative sentences with longer analytical ones.

{opening_register_block}

FRESHNESS REQUIREMENTS:
- Never open with "Looking at the data..." or "This week's data shows..." — these
  are the equivalent of "Dear Sir/Madam" in a letter. Be specific immediately.
- Each weekly analysis should feel like a different chapter, not a form letter.
- If you find yourself writing a sentence that could appear in any week's analysis,
  delete it and write something specific to THIS week.

After your analysis, on separate lines write exactly:
KEY RECOMMENDATION: [One specific behavioral action for this week. 1-2 sentences max. Concrete enough to act on tomorrow.]
ELENA QUOTE: [One sentence in Elena Voss's voice — third person, literary journalist. Elena sees what YOUR discipline blinds you to. If you focused on sleep architecture, she notices the journal entry about late-night screen time. If you talked macros, she sees the emotional eating pattern. She names the cross-domain observation you would make if you could see outside your own expertise. Example: "Five nights of data and his body is already telling a quieter story than the hours suggest." Never aspirational — just the observation the expert missed.]
{"JOURNALING PROMPT: [A single reflective question for Matthew — something he can sit with before writing. Make it specific to what the data revealed this week. If the Builder's Paradox score is above 50, the prompt MUST address the building-vs-doing tension: e.g., 'Is the building serving the transformation this week, or the other way around?']" if expert_key == "mind" else ""}

Write only the analysis — no preamble, no "Here is my analysis:", just paragraphs followed by the tagged lines."""


def _load_engagement_signal():
    """Read the presence / quiet-stretch state (engagement_state STATE#current),
    written by adaptive_mode via engagement_core. Fail-soft → {}.

    #946: honors the restart tombstone — get_item bypasses the query-level phase
    filter, so a wiped (tombstone=true / phase=pilot) singleton would otherwise
    keep injecting the OLD cycle's presence severity into every expert prompt
    until adaptive_mode's next daily run rewrites it."""
    try:
        from experiment.phase_filter import singleton_visible

        resp = table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#engagement_state", "sk": "STATE#current"})
        item = resp.get("Item")
        if not singleton_visible(item):
            return {}
        return item
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("engagement signal read failed: %s", e)
        return {}


def _presence_block():
    """A steering block for when Matthew's OWN logging has gone quiet (or he just
    returned). Empty string when he's present. This is what stops the observatory
    coaches + integrator from claiming perfect adherence / an unbroken streak /
    'zero missed targets' over a window that actually contains a logging gap — the
    exact incoherence the presence feature exists to kill. The REASON for the gap
    is never included (the coach names the silence and invites the story).

    #914: the block itself moved verbatim to engagement_core.presence_prompt_block
    (pure, shared by every narrative surface) — this wrapper keeps the
    STATE#current read local and the two injection points below unchanged."""
    try:
        from content.engagement_core import presence_prompt_block
    except ImportError:  # pragma: no cover — bundle always ships engagement_core
        return ""
    return presence_prompt_block(_load_engagement_signal())


# #1115 / ADR-080: the integrator's three narrative prompt builders (weekly
# synthesis, month rollup, experiment arc) live in the sibling module
# integrator_prompts.py — pure builders, each carrying the mandatory #1086
# phase-context block. Dual import path per the grounding_guard convention.
try:
    from intelligence.integrator_prompts import build_arc_prompt, build_month_rollup_prompt, build_synthesis_prompt
except ImportError:  # pragma: no cover — flat-staged runtime layout
    if not TYPE_CHECKING:  # one canonical module name for mypy; runtime unchanged (#1656)
        from integrator_prompts import build_arc_prompt, build_month_rollup_prompt, build_synthesis_prompt  # noqa: F401


def _build_shared_system_prompt():
    """Build the cacheable system prompt shared across all 8 expert calls.

    Contains: goals, data inventory, format instructions — identical per invocation.
    COST-OPT: Cached by Anthropic across sequential calls (90% discount on cache hits).
    """
    parts = []

    # Goals + inventory (shared context for all coaches)
    if _HAS_INTELLIGENCE_COMMON:
        try:
            _goals = load_goals_config()
            _inventory = build_data_inventory()

            mission = _goals.get("mission", "")
            if mission:
                parts.append(f"MATTHEW'S MISSION: {mission}")
            philosophy = _goals.get("philosophy", "")
            if philosophy:
                parts.append(f"PHILOSOPHY: {philosophy}")

            targets = _goals.get("targets", {})
            _target_map = {
                "weight.goal_lbs": "Weight goal",
                "body_composition.goal_body_fat_pct": "Body fat goal",
                "nutrition.daily_calories_target": "Calorie target",
                "nutrition.daily_protein_min_g": "Protein minimum",
                "sleep.target_hours": "Sleep target",
            }
            target_lines = []
            for path, label in _target_map.items():
                keys = path.split(".")
                val = targets
                for k in keys:
                    val = val.get(k) if isinstance(val, dict) else None
                    if val is None:
                        break
                target_lines.append(f"  - {label}: {val if val is not None else 'not set'}")
            parts.append("TARGETS:\n" + "\n".join(target_lines))

            constraints = _goals.get("known_constraints", [])
            if constraints:
                parts.append("CONSTRAINTS:\n" + "\n".join(f"  - {c}" for c in constraints))

            inv_lines = []
            for src, info in sorted(_inventory.items()):
                if info.get("exists"):
                    inv_lines.append(f"  - {src}: {info.get('records', 0)} records (latest: {info.get('latest', '?')})")
            parts.append("DATA SOURCES AVAILABLE:\n" + "\n".join(inv_lines))
        except Exception as _e:
            logger.warning("Shared system prompt generation failed: %s", _e)

    # Phase-3 AUTHORITATIVE FACTS — the single shared snapshot every coach must cite from.
    # Prevents the cross-coach number drift the truth audit found (protein 140/170/190,
    # recovery 30-vs-86): if you mention one of these metrics, use THIS number, verbatim.
    # ADR-104: rendered by grounded_generation.authoritative_facts_block — the one
    # wording every surface injects (this block's original text moved there verbatim).
    try:
        _facts_block = _gg.authoritative_facts_block(_load_canonical_facts())
        if _facts_block:
            parts.append(_facts_block)
    except Exception as _fe:
        logger.warning("Authoritative facts injection failed: %s", _fe)

    # Presence / quiet-stretch — if Matthew's own logging has gone quiet, every expert
    # must notice it rather than narrate a flawless week over an incomplete window.
    try:
        _pb = _presence_block()
        if _pb:
            parts.append(_pb)
    except Exception as _pe:  # pragma: no cover — defensive
        logger.warning("Presence block injection failed: %s", _pe)

    # Format instructions (identical for all experts)
    parts.append("""OBSERVATORY ANALYSIS FORMAT:
Write a 2-3 paragraph analysis (200-300 words).

STRUCTURE:
- Paragraph 1: Open with ONE specific, concrete observation. Lead with a number ONLY if it is one of your data points or an AUTHORITATIVE FACT — otherwise lead with the pattern.
- Paragraph 2: Interpret the pattern. Connect to another domain if relevant.
- Paragraph 3: One specific, actionable suggestion for the coming week.

VOICE:
- First person as yourself. Cite specific numbers ONLY when they are in your data or the AUTHORITATIVE FACTS — never invent a figure, trend, range, or multi-day value to sound precise. A described pattern with no number beats a fabricated number.
- Do NOT use bullet points, headers, or formatting. Flowing prose only.
- Vary sentence length.

FRESHNESS: Never open with "Looking at the data..." — be specific immediately.
Your first sentence must sound like YOU and no other coach: open in your own
opening register (defined in your persona prompt), lead with your own domain's
read, and never lead with the same platform-wide event every other coach would
open on.

After your analysis, on separate lines write:
KEY RECOMMENDATION: [One specific action for this week. 1-2 sentences.]
ELENA QUOTE: [One sentence in Elena Voss's voice — third person, literary journalist. She names the cross-domain observation the expert missed.]

Write only the analysis — no preamble, just paragraphs followed by tagged lines.""")

    return "\n\n".join(parts)


def _load_prior_analysis(expert_key):
    """Prior EXPERT#<key> analysis + recommendation for anti-repetition context;
    (summary, recommendation), fail-soft ("", "").

    #1969 (#946 class, live vector for #1897): the restart wipe tombstones
    ai_analysis IN PLACE and get_item bypasses the query-level phase filter, so
    on Day 1 this read fed the wiped cycle-10 text into the live prompt. A
    tombstoned/wrong-phase prior reads as ABSENT (honest absence, ADR-104)."""
    try:
        from experiment.phase_filter import singleton_visible

        prior = table.get_item(Key={"pk": CACHE_PK, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if not singleton_visible(prior):
            return "", ""
        summary = str(prior["analysis"])[:300] if prior.get("analysis") else ""
        recommendation = str(prior["key_recommendation"])[:200] if prior.get("key_recommendation") else ""
        return summary, recommendation
    except Exception:
        return "", ""


def _anthropic_req(prompt, api_key, max_tokens=2048):
    """The one shaped messages-API POST this module's non-cached calls share (#2421)."""
    return urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": AI_MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )


def _lenient_json(text, key, partial):
    """Lenient parse of a model's structured response — the shape all three JSON-shaped
    generators (synthesis / experiment arc / month rollup) shared verbatim before #2421
    folded the three copies into one.

    B4: subtly-malformed JSON (a trailing comma, an empty nested value) threw on
    json.loads and fail-closed to yesterday's stale record (the /cockpit/ "collapsed to
    one session/week" bug). Strip fences, take the outermost object, drop trailing
    commas; if even that fails, regex-extract `key` so a FRESH record still lands
    (`partial` supplies what the fallback cannot recover). None = no usable response."""
    import re

    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    a, b = s.find("{"), s.rfind("}")
    core = s[a : b + 1] if (a != -1 and b > a) else s  # noqa: E203
    for cand in (core, re.sub(r",(\s*[}\]])", r"\1", core)):
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            pass
    m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', core, re.DOTALL)
    if not m:
        return None
    try:
        value = json.loads(f'"{m.group(1)}"')  # unescape
    except Exception:  # noqa: BLE001
        value = m.group(1)
    logger.warning("Full-JSON parse failed — used %s regex fallback", key)
    return {key: value, "_partial": True, **partial}


def _presence_logs(gen_date_iso):
    """#1699 availability for `gen_date_iso` from engagement_state (fail-soft to none()).
    The #2195 shape: `available_logs_from_presence` refuses to answer from a signal older
    than the day asked about, so a stale read disarms the class honestly rather than
    grading a same-day claim against yesterday's logs."""
    try:
        from ai.behavior_logs import LogAvailability, available_logs_from_presence

        sig = _load_engagement_signal()
        return available_logs_from_presence(sig, gen_date_iso) if sig else LogAvailability.none()
    except Exception as _e:  # pragma: no cover — defensive
        logger.warning("presence log-availability derivation failed: %s", _e)
        return None


def _gate_prose(label, text, prompt, api_key, *, shared_system=None, extra_sources=(), available_logs=None, extract=None):
    """The module's ONE grounding chokepoint (#2421) — every model call routes here.

    Before #2421 only the two `generate_and_cache` calls were gated: the Mode-B
    correction rewrote the text AFTER the gate had run, and the weekly-priority
    synthesis, the experiment arc and the month rollup never entered a gate at all —
    four reader-bound paths (the #2390 census counted them). They now share this
    function, so the registry sees ONE surface and a new call cannot fork the idiom.

    Posture is #2391's, unchanged: allow-list numbers + canonical facts + the cycle
    anchors + night scope + the #1699 behavioral map, ONE corrective rewrite via
    `regen_once`, then **regenerate-or-HOLD** — residual findings return "" and the caller
    keeps the prior cached record serving. Gate-INFRA failure still publishes.

    `extract` maps a raw rewrite back to reader text for the JSON-shaped callers, which
    also use it to capture the re-parsed record. Returns grounded text, or "" to hold.
    """
    facts = _load_canonical_facts()
    allowed = _gg.allowed_numbers(prompt, shared_system, facts, *extra_sources)
    gen_date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if available_logs is None:
        available_logs = _presence_logs(gen_date_iso)

    def _findings_fn(_t):
        return _gg.grounding_findings(
            _t,
            facts=facts,
            allowed=allowed,
            generation_date_iso=gen_date_iso,
            start_date_iso=EXPERIMENT_START,
            nightly_vitals=_night_map(facts),  # #1968: the unlabeled "7.5-hour sleep"
            available_logs=available_logs,  # #2056/#1699
        )

    def _regen(_correction):
        from common.retry_utils import call_anthropic_raw

        _req = _anthropic_req(prompt + "\n\n" + _correction, api_key)
        _raw = "".join(b["text"] for b in call_anthropic_raw(_req, timeout=60).get("content", []) if b.get("type") == "text")
        if extract is not None:
            return extract(_raw)
        return _raw.rsplit("KEY RECOMMENDATION:", 1)[0].rstrip() if "KEY RECOMMENDATION:" in _raw else _raw

    _pre = _findings_fn(text)
    if _pre:
        logger.warning("[grounding] %s finding(s): %s", label, [f["detail"] for f in _pre][:6])
    _new_text, _left, _corrected = _gg.regen_once(text, _findings_fn, _regen)
    if _corrected:
        text = _new_text
        logger.info("[grounding] %s self-corrected: %d→%d finding(s)", label, len(_pre), len(_left))
    if _left:
        logger.warning(
            "[grounding] %s HELD — %d residual finding(s); prior cached record preserved (#2391): %s",
            label,
            len(_left),
            [f["detail"] for f in _left][:4],
        )
        return ""
    return text


def _gate_json_record(label, parsed, key, partial, prompt, api_key):
    """#2421: gate the reader-bound field of a JSON-shaped generator (the weekly-priority
    synthesis, the experiment arc, the month rollup — none of which was gated before).
    `_gate_prose`'s rewrite comes back as raw JSON, so the extractor re-parses it and keeps
    the WHOLE rewritten record: publishing a corrected headline beside the uncorrected
    chapters/notes it was generated with would be the post-gate-mutation bug in another
    costume. Returns the grounded record, or None to hold (prior record keeps serving)."""
    fresh: dict = {}

    def _extract(_raw):
        _p = _lenient_json(_raw, key, partial)
        if _p and _p.get(key):
            fresh["parsed"] = _p
            return _p[key]
        return ""

    text = _gate_prose(label, parsed[key], prompt, api_key, extract=_extract)
    if not text:
        logger.warning("%s HELD by the grounding gate (#2421/#2391) — prior cached record keeps serving", label)
        return None
    out = fresh.get("parsed", parsed)
    out[key] = text
    return out


def generate_and_cache(expert_key, shared_system=None):
    logger.info(f"Generating analysis for expert: {expert_key}")
    data = gather_data_for_expert(expert_key)

    # Read prior analysis + recommendation to prevent repetition (#1969: tombstone-guarded)
    prior_summary, prior_recommendation = _load_prior_analysis(expert_key)
    if prior_summary:
        data["_prior_analysis_summary"] = prior_summary
    if prior_recommendation:
        data["_prior_recommendation"] = prior_recommendation

    days_in = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
    week_number = max(1, days_in // 7 + 1)
    prompt = build_prompt(expert_key, data, days_in, week_number)
    api_key = _get_api_key()

    # COST-OPT: Use system message with prompt caching for shared context
    body = {
        "model": AI_MODEL,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    if shared_system:
        body["system"] = [{"type": "text", "text": shared_system, "cache_control": {"type": "ephemeral"}}]
        headers["anthropic-beta"] = "prompt-caching-2024-07-31"

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers=headers,
    )

    # Phase 3.4 (2026-05-16): retry via retry_utils (4 attempts, 5/15/45s).
    try:
        from common.retry_utils import call_anthropic_raw

        result = call_anthropic_raw(req, timeout=60)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error("Anthropic API %s: %s", e.code, error_body)
        raise

    analysis_text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

    # V3.1: Extract tagged fields — split from bottom up to avoid capture leaks
    key_recommendation = ""
    journaling_prompt = ""
    elena_quote = ""
    # ELENA QUOTE is last in the output
    if "ELENA QUOTE:" in analysis_text:
        parts = analysis_text.rsplit("ELENA QUOTE:", 1)
        analysis_text = parts[0].rstrip()
        elena_quote = parts[1].strip().strip('"').strip("\u201c").strip("\u201d")
        # Extract any JOURNALING PROMPT that leaked into elena_quote
        if "JOURNALING PROMPT:" in elena_quote:
            eq_parts = elena_quote.split("JOURNALING PROMPT:", 1)
            elena_quote = eq_parts[0].strip().strip('"').strip("\u201c").strip("\u201d")
            if not journaling_prompt:
                journaling_prompt = eq_parts[1].strip()
    # JOURNALING PROMPT comes before ELENA QUOTE (Mind page only)
    if "JOURNALING PROMPT:" in analysis_text:
        parts = analysis_text.rsplit("JOURNALING PROMPT:", 1)
        analysis_text = parts[0].rstrip()
        journaling_prompt = parts[1].strip()
    if "KEY RECOMMENDATION:" in analysis_text:
        parts = analysis_text.rsplit("KEY RECOMMENDATION:", 1)
        analysis_text = parts[0].rstrip()
        key_recommendation = parts[1].strip()

    # #2218: an empty/refusal-shaped (or tag-extraction-consumed) response must never
    # overwrite a good cached analysis — bail before touching the DDB record at all.
    if not analysis_text.strip():
        logger.warning("generate_and_cache: empty response for %s — cached record preserved (#2218)", expert_key)
        return ""

    # Phase-4 SELF-CORRECTION (ADR-104/ADR-108, #2391) — BEFORE the cache write:
    # it used to run AFTER put_item with keep-if-better semantics, so the ungrounded
    # original published first and a merely-improved rewrite shipped over it.
    # Log-only wasn't enough — coaches kept serving a wrong RHR (53 vs the canonical
    # 64) that the Coherence Sentinel caught daily. Findings = hard canonical
    # contradictions PLUS the allow-list number gate (any number not present in the
    # prompt/system/facts is a fabrication — catches invented trend endpoints).
    # One corrective rewrite, kept only if strictly better (never regress).
    # #2056: the #1699 map comes from the snapshot's own `days_since_last_*` fields —
    # computed by `_recency_stats` from the rows THIS render already queried, so zero
    # extra I/O. Coverage is per-expert and declared: the nutrition snapshot answers for
    # food and stays silent about training. A category the expert cannot see is left
    # UNKNOWN, never reported absent — what makes arming honest on partial visibility.
    if analysis_text:
        try:
            _gated = _gate_prose(expert_key, analysis_text, prompt, api_key, shared_system=shared_system, available_logs=_avail_logs(data))
            if not _gated:
                return ""  # #2391 hold — prior cached analysis keeps serving
            analysis_text = _gated
        except Exception as _sc:
            logger.warning("grounding self-correction failed for %s: %s", expert_key, _sc)

    now = datetime.now(timezone.utc)
    ttl = int((now + timedelta(days=8)).timestamp())

    item = {
        "pk": CACHE_PK,
        "sk": f"EXPERT#{expert_key}",
        "expert_key": expert_key,
        "analysis": analysis_text,
        "generated_at": now.isoformat(),
        "data_snapshot": json.dumps(data, default=str)[:5000],
        "week_number": week_number,
        "days_in_experiment": days_in,
        "ttl": ttl,
    }
    if key_recommendation:
        item["key_recommendation"] = key_recommendation
    if journaling_prompt:
        item["journaling_prompt"] = journaling_prompt
    if elena_quote:
        item["elena_quote"] = elena_quote
    table.put_item(Item=item)

    # Intelligence Validator V2.1 Mode B: post-generation quality check with inline correction
    if _HAS_INTELLIGENCE_COMMON:
        try:
            from intelligence.intelligence_common import validate_coach_output, write_quality_results

            _inventory = build_data_inventory()
            _maturity = build_data_maturity(_inventory)
            _flags = validate_coach_output(
                coach_id=expert_key,
                domain=expert_key,
                narrative=analysis_text,
                inventory=_inventory,
                maturity=_maturity,
            )
            today_str = now.strftime("%Y-%m-%d")
            errors = [f for f in _flags if f["severity"] == "error"]

            # Mode B: inline correction for error-severity flags (max 1 correction pass)
            if errors and len(errors) <= 3:
                logger.info("Mode B correction triggered for %s: %d errors", expert_key, len(errors))
                correction_parts = ["CORRECTION REQUIRED — the following factual errors were found in your draft:\n"]
                for i, err in enumerate(errors, 1):
                    correction_parts.append(f"{i}. {err['detail']}")
                    if err.get("source_text"):
                        correction_parts.append(f"   You wrote: \"{err['source_text']}\"")
                correction_parts.append(
                    "\nRewrite your analysis incorporating these corrections. "
                    "Maintain your voice and analytical approach but fix the factual errors. "
                    "Do not mention that a correction was made."
                )
                correction_prompt = prompt + "\n\n" + "\n".join(correction_parts)

                try:
                    corr_req = _anthropic_req(correction_prompt, api_key, max_tokens=1200)
                    # Phase 3.4 + CRIT-AI-01 (2026-05-16): correction call now retries via
                    # retry_utils (was raw urlopen, no retry — caused silent quality failures
                    # when Anthropic was briefly unavailable mid-observatory).
                    from common.retry_utils import call_anthropic_raw

                    corr_result = call_anthropic_raw(corr_req, timeout=60)
                    corrected_text = "".join(b["text"] for b in corr_result.get("content", []) if b.get("type") == "text")
                    # Re-parse tagged fields from corrected text
                    if "KEY RECOMMENDATION:" in corrected_text:
                        _cparts = corrected_text.rsplit("KEY RECOMMENDATION:", 1)
                        corrected_text = _cparts[0].rstrip()
                    # Re-validate (don't recurse further)
                    _new_flags = validate_coach_output(
                        coach_id=expert_key,
                        domain=expert_key,
                        narrative=corrected_text,
                        inventory=_inventory,
                        maturity=_maturity,
                    )
                    new_errors = sum(1 for f in _new_flags if f["severity"] == "error")
                    # #2421: the Mode-B rewrite happens AFTER the grounding gate ran, so it
                    # used to publish a post-gate mutation on the one path that WAS gated.
                    # RE-GATE the rewritten text; a held rewrite is discarded and the already
                    # gated draft (written above) keeps serving — never a downgrade.
                    _regated = ""
                    if new_errors < len(errors):
                        _regated = _gate_prose(
                            f"{expert_key}/mode-b", corrected_text, correction_prompt, api_key, available_logs=_avail_logs(data)
                        )
                        if not _regated:
                            logger.warning("Mode B rewrite for %s failed re-grounding (#2421) — gated draft preserved", expert_key)
                    if _regated:
                        analysis_text = _regated
                        # Update cached item
                        table.update_item(
                            Key={"pk": CACHE_PK, "sk": f"EXPERT#{expert_key}"},
                            UpdateExpression="SET analysis = :a",
                            ExpressionAttributeValues={":a": analysis_text},
                        )
                        logger.info("Mode B correction applied for %s: %d→%d errors", expert_key, len(errors), new_errors)
                        _flags = _new_flags
                except Exception as _ce:
                    logger.warning("Mode B correction call failed for %s: %s", expert_key, _ce)

            write_quality_results(today_str, expert_key, expert_key, _flags)
            if _flags:
                err_count = sum(1 for f in _flags if f["severity"] == "error")
                warn_count = sum(1 for f in _flags if f["severity"] == "warning")
                if err_count > 0 or warn_count > 0:
                    logger.warning(
                        "Quality flags for %s: %d errors, %d warnings",
                        expert_key,
                        err_count,
                        warn_count,
                    )
        except Exception as _ve:
            logger.warning("Intelligence validator failed for %s: %s", expert_key, _ve)

    # Phase-3 grounding backstop: cross-ref the coach's cited recovery/HRV/RHR/weight
    # against the shared canonical facts (>25% deviation WARNs) and catch HRV-in-bpm.
    # The protein 140/170/190 split is solved structurally by the AUTHORITATIVE FACTS
    # block (avg/target/floor are all legitimate numbers, so they're not deviation-checked).
    if _HAS_AI_VALIDATOR and analysis_text:
        try:
            _f = _load_canonical_facts()
            _ground_ctx = {
                "recovery_score": _f.get("recovery_pct"),
                "hrv": _f.get("hrv_ms"),
                "resting_heart_rate": _f.get("rhr_bpm"),
                "latest_weight": _f.get("latest_weight"),
            }
            _ground_ctx = {k: v for k, v in _ground_ctx.items() if v is not None}
            if _ground_ctx:
                _gr = _aiv.validate_ai_output(analysis_text, _aiv.AIOutputType.GENERIC, health_context=_ground_ctx, max_length=10_000)
                if _gr.warnings:
                    logger.warning("[grounding] %s: %s", expert_key, _gr.warnings[:5])
        except Exception as _ge2:
            logger.warning("grounding backstop failed for %s: %s", expert_key, _ge2)

    # V2.1: Thread extraction — extract and write coach thread entry
    if _HAS_INTELLIGENCE_COMMON and analysis_text:
        try:
            thread_data = extract_thread_from_narrative(expert_key, analysis_text, api_key)
            thread_data["generation_context"] = "observatory"
            # DI-1.3: deterministic backstop — if movement isn't assessable, withhold any
            # under-training/sedentary verdict that slipped into the position_summary and
            # replace it with an honest, Hevy-aware statement naming the unavailable sources.
            if expert_key == "training":
                try:
                    _td = data  # already gathered in generate_and_cache (no re-query)
                    _assess = movement_assessability(_td.get("movement_source_state"), _td.get("movement_ingest_health"))
                    thread_data["position_summary"] = apply_movement_honesty_guard(
                        thread_data.get("position_summary", ""),
                        _assess,
                        hevy_present=bool(_td.get("hevy_sessions")),
                        hevy_summary=_td.get("hevy_summary", ""),
                    )
                except Exception as _ge:
                    logger.warning("movement honesty guard failed for training: %s", _ge)
            write_coach_thread(expert_key, thread_data)
            logger.info(
                "Thread entry written for %s: investment=%s, %d predictions",
                expert_key,
                thread_data.get("emotional_investment", "?"),
                len(thread_data.get("predictions", [])),
            )
        except Exception as _te:
            logger.warning("Thread extraction/write failed for %s: %s", expert_key, _te)

    logger.info(f"Cached analysis for {expert_key}: {len(analysis_text)} chars")
    return analysis_text


def generate_synthesis(all_coach_outputs):
    """
    Second-pass synthesis: the board lead (persona registry's single lead:true persona,
    #1986) reads all coach outputs and produces
    a single weekly priority + cross-domain context notes for each observatory page.
    """
    if not all_coach_outputs or len(all_coach_outputs) < 2:
        logger.info("Synthesis skipped — fewer than 2 coach outputs")
        return None

    try:
        goals = load_goals_config() if _HAS_INTELLIGENCE_COMMON else {}
    except Exception:
        goals = {}

    coach_sections = "\n\n".join(f"--- {domain.upper()} COACH ---\n{text[:800]}" for domain, text in all_coach_outputs.items() if text)

    goals_json = json.dumps(
        {
            "mission": goals.get("mission", ""),
            "targets": goals.get("targets", {}),
            "philosophy": goals.get("philosophy", ""),
        },
        indent=2,
        default=str,
    )

    # Phase-3: the integrator gets the same AUTHORITATIVE FACTS as the coaches, so it
    # can't invent figures (the audit caught it citing "HRV 42, lowest in 41 nights").
    _f = _load_canonical_facts()
    _fact_bits = []
    if _f.get("protein_g_avg") is not None:
        _fact_bits.append(f"protein intake avg {_f['protein_g_avg']:g} g (target {int(_f.get('protein_g_target') or 190)} g)")
    if _f.get("recovery_pct") is not None:
        _fact_bits.append(f"recovery {_f['recovery_pct']:g}%")
    if _f.get("hrv_ms") is not None:
        _fact_bits.append(f"HRV {_f['hrv_ms']:g} ms")
    if _f.get("latest_weight") is not None:
        _fact_bits.append(f"weight {_f['latest_weight']:g} lb")
    facts_block = (
        ("\nAUTHORITATIVE FACTS (cite these exact numbers; do not invent any others): " + "; ".join(_fact_bits) + "\n")
        if _fact_bits
        else ""
    )

    # #914-C: exact deterministic counts. The live integrator conflated numbers —
    # "I don't know what you actually ate on seventeen of those days" in a sentence
    # about a 14-day silence, and "ten training sessions" vs the payload's 9. Give
    # it the labeled counts with a no-arithmetic rule so it cites, never re-derives.
    _count_bits = []
    try:
        _now = datetime.now(timezone.utc)
        _today_str = _now.strftime("%Y-%m-%d")
        _day_n = max(1, (_now.date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
        _count_bits.append(f"experiment day_n = {_day_n}")
        _d30 = max((_now - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)
        _n_sessions = len(_query_source("hevy", _d30, _today_str)) + len(_query_source("strava", _d30, _today_str))
        _count_bits.append(f"logged training sessions (last 30d, Hevy + Strava) = {_n_sessions}")
        _count_bits.append(f"food-log days (last 30d) = {len(_item_dates(_query_source('macrofactor', _d30, _today_str)))}")
        _sig = _load_engagement_signal()
        for _src, _det in sorted((_sig.get("channel_detail") or {}).items()):
            if not isinstance(_det, dict):
                continue
            _lbl = _det.get("label") or _src
            _g = _det.get("gap_days")
            _count_bits.append(
                f"{_lbl} gap_days = {int(_g)}" if _g is not None else f"{_lbl} gap_days = unknown (nothing logged in window)"
            )
    except Exception as _ce:  # noqa: BLE001 — counts are additive, never break synthesis
        logger.warning("synthesis deterministic counts failed (non-blocking): %s", _ce)
    if _count_bits:
        facts_block += (
            "\nDETERMINISTIC COUNTS (authoritative — cite EXACTLY as given; do NOT re-derive, add, subtract, "
            "or arithmetic these into any other number, in digits or in words): " + "; ".join(_count_bits) + "\n"
        )

    # Presence / quiet-stretch: the Chair's cross-pillar synthesis is the cockpit's
    # headline verdict, so it MUST notice a real logging gap — otherwise it crowns a
    # flawless week over days Matthew logged nothing (the exact incoherence caught).
    _pb = _presence_block()
    presence_block = ("\n" + _pb + "\n") if _pb else ""

    prompt = build_synthesis_prompt(coach_sections, goals_json, facts_block, presence_block)

    api_key = _get_api_key()

    # _anthropic_req's max_tokens default is 2048 on purpose: 1200 truncated the JSON
    # mid-string → json.loads threw and the whole synthesis fail-closed to the previous
    # day's (stale) record (the /cockpit/ "collapsed to one session/week" bug).
    # Phase 3.4: retry via retry_utils; lenient parse per _lenient_json (B4).
    from common.retry_utils import call_anthropic_raw

    synthesis = None
    last_err = None
    for attempt in (1, 2):
        try:
            result = call_anthropic_raw(_anthropic_req(prompt, api_key), timeout=60)
            text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
            synthesis = _lenient_json(text, "weekly_priority", {"cross_domain_notes": {}, "disagreements": []})
            if synthesis and synthesis.get("weekly_priority"):
                break
            last_err = f"no weekly_priority parsed (attempt {attempt})"
            logger.warning("Synthesis parse yielded no weekly_priority (attempt %d/2)", attempt)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.error("Synthesis call failed (attempt %d/2): %s", attempt, e)
    if not synthesis or not synthesis.get("weekly_priority"):
        logger.error("Synthesis generation failed after retries: %s", last_err)
        return None

    # #2421: the Chair's weekly priority is the /cockpit/ headline verdict — gate it.
    synthesis = _gate_json_record(
        "weekly_priority", synthesis, "weekly_priority", {"cross_domain_notes": {}, "disagreements": []}, prompt, api_key
    )
    if synthesis is None:
        return None

    try:
        # Cache synthesis to DDB
        now = datetime.now(timezone.utc)
        ttl = int((now + timedelta(days=8)).timestamp())
        item = {
            "pk": CACHE_PK,
            "sk": "EXPERT#integrator",
            "expert_key": "integrator",
            "analysis": synthesis.get("weekly_priority", ""),
            "cross_domain_notes": synthesis.get("cross_domain_notes", {}),
            "disagreements": synthesis.get("disagreements", []),
            "generated_at": now.isoformat(),
            "week_number": max(1, (now.date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days // 7 + 1),
            "ttl": ttl,
        }
        table.put_item(Item=item)
        logger.info(
            "Synthesis generated and cached: %d chars priority, %d domain notes",
            len(synthesis.get("weekly_priority", "")),
            len(synthesis.get("cross_domain_notes", {})),
        )
        return synthesis

    except Exception as e:
        logger.error("Synthesis generation failed: %s", e)
        return None


def _week_behavioral_presence(iso_week):
    """#914-A (ADR-105 deterministic-before-verdict): per-week behavioral presence,
    computed from the raw logs BEFORE any prompting. The regenerated week-4 arc
    celebrated a fully-dark week ('the weight data gap that week is a minor logging
    problem... best HRV of the entire arc') — HRV was rest-inflated and every
    behavioral stream was dead. Returns {start, end, lift_days, weigh_ins,
    habit_completion_days, food_log_days, absence_week} or None on a bad week key.
    habitify uses the same completion predicate as the presence detector (a record
    at total_completed=0 is not behavior)."""
    try:
        year, wk = int(str(iso_week)[:4]), int(str(iso_week)[6:])
        monday = datetime.fromisocalendar(year, wk, 1).strftime("%Y-%m-%d")
        sunday = datetime.fromisocalendar(year, wk, 7).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    try:
        from content.engagement_core import channel_counts_as_logged as _cal
    except ImportError:  # pragma: no cover — bundle always ships engagement_core

        def _cal(_src, _it):
            return True

    try:
        lift_days = len(_item_dates(_query_source("hevy", monday, sunday)))
        weigh_ins = len(_item_dates(_query_source("withings", monday, sunday)))
        habit_days = len(_item_dates([i for i in _query_source("habitify", monday, sunday) if _cal("habitify", i)]))
        food_days = len(_item_dates(_query_source("macrofactor", monday, sunday)))
    except Exception as e:  # noqa: BLE001 — presence is additive, never breaks the arc
        logger.warning("arc week-presence query failed for %s: %s", iso_week, e)
        return None
    return {
        "start": monday,
        "end": sunday,
        "lift_days": lift_days,
        "weigh_ins": weigh_ins,
        "habit_completion_days": habit_days,
        "food_log_days": food_days,
        "absence_week": (lift_days + weigh_ins + habit_days + food_days) == 0,
    }


def generate_experiment_arc():
    """
    Cross-week synthesis (C-1): the board lead reads the board's weekly lab notes
    across the WHOLE run so far and writes the experiment's arc — where it started,
    the turns, where it stands, the throughline. Richer than the per-week tone list
    the Experiment view shows today. Reads field_notes WEEK# (chronological), writes
    EXPERT#experiment_arc. Honest-skip when fewer than 2 weeks exist.
    """
    fn_pk = f"{USER_PREFIX}field_notes"
    # ADR-058: hide pre-genesis pilot weeks (phase=pilot) so the arc only synthesizes
    # the CURRENT experiment's run — matching what the Experiment view's week list shows.
    from experiment.phase_filter import with_phase_filter

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(fn_pk) & Key("sk").begins_with("WEEK#"),
                    "ScanIndexForward": True,  # oldest → newest, so the arc reads in order
                    "Limit": 52,
                }
            )
        )
        weeks = _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # noqa: BLE001
        logger.error("Experiment-arc: field_notes query failed: %s", e)
        return None

    if len(weeks) < 2:
        logger.info("Experiment-arc skipped — only %d week(s) of lab notes (need >=2)", len(weeks))
        return None

    # Compose the week-by-week material the board has already written — each week
    # stapled to its DETERMINISTIC behavioral-presence counts (#914-A) so a dark
    # week cannot be narrated as triumph off rest-inflated recovery numbers.
    blocks = []
    for w in weeks:
        label = w.get("week_label") or w.get("week") or "Week"
        tone = w.get("ai_tone", "mixed")
        present = (w.get("ai_present") or "").strip()
        bits = [f"[{label}] tone={tone}"]
        pres = _week_behavioral_presence(w.get("week"))
        if pres is not None:
            bits.append(
                f"BEHAVIORAL PRESENCE ({pres['start']}..{pres['end']}, deterministic counts from the raw logs — AUTHORITATIVE): "
                f"lifting days {pres['lift_days']}, weigh-ins {pres['weigh_ins']}, "
                f"habit-completion days {pres['habit_completion_days']}, food-log days {pres['food_log_days']}"
                + (" — AN ABSENCE WEEK (no behavioral data at all)" if pres["absence_week"] else "")
            )
        if present:
            bits.append(present[:600])
        if w.get("ai_affirming"):
            bits.append(f"AFFIRMING: {str(w['ai_affirming'])[:200]}")
        if w.get("ai_cautionary"):
            bits.append(f"CAUTIONARY: {str(w['ai_cautionary'])[:200]}")
        blocks.append("\n".join(bits))
    weeks_text = "\n\n".join(blocks)

    try:
        goals = load_goals_config() if _HAS_INTELLIGENCE_COMMON else {}
    except Exception:  # noqa: BLE001
        goals = {}
    goals_json = json.dumps(
        {"mission": goals.get("mission", ""), "targets": goals.get("targets", {}), "philosophy": goals.get("philosophy", "")},
        indent=2,
        default=str,
    )
    _f = _load_canonical_facts()
    _fact_bits = []
    if _f.get("latest_weight") is not None:
        _fact_bits.append(f"current weight {_f['latest_weight']:g} lb")
    if _f.get("recovery_pct") is not None:
        _fact_bits.append(f"recovery {_f['recovery_pct']:g}%")
    facts_block = (
        ("\nAUTHORITATIVE FACTS (cite these exact numbers; invent no others): " + "; ".join(_fact_bits) + "\n") if _fact_bits else ""
    )

    prompt = build_arc_prompt(weeks_text, goals_json, facts_block, len(weeks))

    api_key = _get_api_key()

    from common.retry_utils import call_anthropic_raw

    parsed = None
    last_err = None
    for attempt in (1, 2):
        try:
            result = call_anthropic_raw(_anthropic_req(prompt, api_key), timeout=60)
            text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
            parsed = _lenient_json(text, "arc", {"throughline": "", "chapters": []})
            if parsed and parsed.get("arc"):
                break
            last_err = f"no arc parsed (attempt {attempt})"
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.error("Experiment-arc call failed (attempt %d/2): %s", attempt, e)
    if not parsed or not parsed.get("arc"):
        logger.error("Experiment-arc generation failed after retries: %s", last_err)
        return None

    # #2421: EXPERT#experiment_arc is read straight onto the story surface — gate it.
    parsed = _gate_json_record("experiment_arc", parsed, "arc", {"throughline": "", "chapters": []}, prompt, api_key)
    if parsed is None:
        return None

    try:
        now = datetime.now(timezone.utc)
        item = {
            "pk": CACHE_PK,
            "sk": "EXPERT#experiment_arc",
            "expert_key": "experiment_arc",
            "arc": parsed.get("arc", ""),
            "throughline": parsed.get("throughline", ""),
            "chapters": parsed.get("chapters", []),
            "week_count": len(weeks),
            "generated_at": now.isoformat(),
            "ttl": int((now + timedelta(days=10)).timestamp()),
        }
        table.put_item(Item=item)
        logger.info("Experiment-arc cached: %d weeks, %d chars, %d chapters", len(weeks), len(item["arc"]), len(item["chapters"]))
        return parsed
    except Exception as e:  # noqa: BLE001
        logger.error("Experiment-arc cache write failed: %s", e)
        return None


def generate_month_rollup():
    """
    #1115: the integrator's month rollup — the board lead reads the most recent
    ~4 weekly lab notes and names the month's pattern, so the site's Month lens has
    a narrative at its own altitude instead of reusing the weekly priority. Writes
    EXPERT#integrator_month. Honest-skip when fewer than 2 week notes exist in the
    window (early-cycle: the API serves null and the front-end renders the designed
    empty state — ADR-104, never a fabricated rollup).
    """
    fn_pk = f"{USER_PREFIX}field_notes"
    from experiment.phase_filter import with_phase_filter

    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(fn_pk) & Key("sk").begins_with("WEEK#"),
                    "ScanIndexForward": False,  # newest first — we want the trailing month
                    "Limit": 5,
                }
            )
        )
        weeks = list(reversed(_decimal_to_float(resp.get("Items", []))))[-4:]
    except Exception as e:  # noqa: BLE001
        logger.error("Month-rollup: field_notes query failed: %s", e)
        return None

    if len(weeks) < 2:
        logger.info("Month-rollup skipped — only %d week note(s) in the trailing window (need >=2)", len(weeks))
        return None

    blocks = []
    window_dates = []
    for w in weeks:
        label = w.get("week_label") or w.get("week") or "Week"
        tone = w.get("ai_tone", "mixed")
        present = (w.get("ai_present") or "").strip()
        bits = [f"[{label}] tone={tone}"]
        pres = _week_behavioral_presence(w.get("week"))
        if pres is not None:
            window_dates.extend([pres["start"], pres["end"]])
            bits.append(
                f"BEHAVIORAL PRESENCE ({pres['start']}..{pres['end']}, deterministic counts from the raw logs — AUTHORITATIVE): "
                f"lifting days {pres['lift_days']}, weigh-ins {pres['weigh_ins']}, "
                f"habit-completion days {pres['habit_completion_days']}, food-log days {pres['food_log_days']}"
                + (" — AN ABSENCE WEEK (no behavioral data at all)" if pres["absence_week"] else "")
            )
        if present:
            bits.append(present[:600])
        blocks.append("\n".join(bits))
    weeks_text = "\n\n".join(blocks)
    window_label = f"{min(window_dates)} to {max(window_dates)}" if window_dates else ""

    try:
        goals = load_goals_config() if _HAS_INTELLIGENCE_COMMON else {}
    except Exception:  # noqa: BLE001
        goals = {}
    goals_json = json.dumps(
        {"mission": goals.get("mission", ""), "targets": goals.get("targets", {}), "philosophy": goals.get("philosophy", "")},
        indent=2,
        default=str,
    )
    _f = _load_canonical_facts()
    _fact_bits = []
    if _f.get("latest_weight") is not None:
        _fact_bits.append(f"current weight {_f['latest_weight']:g} lb")
    if _f.get("recovery_pct") is not None:
        _fact_bits.append(f"recovery {_f['recovery_pct']:g}%")
    facts_block = (
        ("\nAUTHORITATIVE FACTS (cite these exact numbers; invent no others): " + "; ".join(_fact_bits) + "\n") if _fact_bits else ""
    )

    prompt = build_month_rollup_prompt(weeks_text, goals_json, facts_block, len(weeks), window_label)

    api_key = _get_api_key()

    from common.retry_utils import call_anthropic_raw

    parsed = None
    last_err = None
    for attempt in (1, 2):
        try:
            result = call_anthropic_raw(_anthropic_req(prompt, api_key, max_tokens=1024), timeout=60)
            text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
            parsed = _lenient_json(text, "narrative", {"headline": ""})
            if parsed and parsed.get("narrative"):
                break
            last_err = f"no narrative parsed (attempt {attempt})"
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.error("Month-rollup call failed (attempt %d/2): %s", attempt, e)
    if not parsed or not parsed.get("narrative"):
        logger.error("Month-rollup generation failed after retries: %s", last_err)
        return None

    # #2421: EXPERT#integrator_month feeds the site's Month lens — gate it.
    parsed = _gate_json_record("integrator_month", parsed, "narrative", {"headline": ""}, prompt, api_key)
    if parsed is None:
        return None

    try:
        now = datetime.now(timezone.utc)
        day_n = max(1, (now.date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1)
        item = {
            "pk": CACHE_PK,
            "sk": "EXPERT#integrator_month",
            "expert_key": "integrator_month",
            "narrative": parsed.get("narrative", ""),
            "headline": parsed.get("headline", ""),
            "week_count": len(weeks),
            "window_label": window_label,
            "days_in_experiment": day_n,
            "generated_at": now.isoformat(),
            "ttl": int((now + timedelta(days=10)).timestamp()),
        }
        table.put_item(Item=item)
        logger.info("Month-rollup cached: %d weeks, %d chars", len(weeks), len(item["narrative"]))
        parsed["week_count"] = len(weeks)
        return parsed
    except Exception as e:  # noqa: BLE001
        logger.error("Month-rollup cache write failed: %s", e)
        return None


def lambda_handler(event, context):
    try:
        # C-1: refresh just the cross-week arc without re-running the 8 narratives
        # (manual/test repopulate). The daily 'all' pass also regenerates it.
        if event.get("arc_only"):
            arc = generate_experiment_arc()
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"experiment_arc": {"status": "ok", "weeks": arc.get("week_count")} if arc else {"status": "skipped"}},
                    default=str,
                ),
            }
        # #1115: refresh just the month rollup (manual/test repopulate).
        if event.get("month_only"):
            rollup = generate_month_rollup()
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"month_rollup": {"status": "ok", "weeks": rollup.get("week_count")} if rollup else {"status": "skipped"}},
                    default=str,
                ),
            }
        target = event.get("expert", "all")
        experts_to_run = EXPERTS if target == "all" else [target]
        results = {}
        all_outputs = {}

        # COST-OPT: Build shared system prompt once — cached across all expert calls
        shared_system = _build_shared_system_prompt()
        logger.info("Shared system prompt built: %d chars", len(shared_system))

        for expert_key in experts_to_run:
            if expert_key not in EXPERTS:
                logger.warning(f"Unknown expert: {expert_key}")
                continue
            try:
                text = generate_and_cache(expert_key, shared_system=shared_system)
                if text and text.strip():
                    results[expert_key] = {"status": "ok", "chars": len(text)}
                    all_outputs[expert_key] = text
                else:
                    # #2218: empty generation — never "ok" (chars: 0 reads as success); excluded from synthesis.
                    results[expert_key] = {"status": "skipped_empty", "chars": 0}
            except Exception as e:
                logger.error(f"Failed to generate {expert_key}: {e}")
                results[expert_key] = {"status": "error", "error": str(e)}

        # Synthesis pass — only when running all experts
        if target == "all" and len(all_outputs) >= 3:
            try:
                synthesis = generate_synthesis(all_outputs)
                if synthesis:
                    results["integrator"] = {"status": "ok", "chars": len(str(synthesis))}
            except Exception as e:
                logger.error(f"Synthesis failed: {e}")
                results["integrator"] = {"status": "error", "error": str(e)}

            # C-1: cross-week experiment arc — the whole-run synthesis for the
            # Experiment view (honest-skips when <2 weeks of lab notes exist).
            try:
                arc = generate_experiment_arc()
                if arc:
                    results["experiment_arc"] = {"status": "ok", "weeks": arc.get("week_count") or len(arc.get("chapters", []))}
            except Exception as e:
                logger.error(f"Experiment-arc failed: {e}")
                results["experiment_arc"] = {"status": "error", "error": str(e)}

            # #1115: month rollup — the trailing ~4 weeks as one pattern, so the
            # Month lens speaks at its own altitude (honest-skips when <2 week
            # notes exist in the window).
            try:
                rollup = generate_month_rollup()
                if rollup:
                    results["month_rollup"] = {"status": "ok", "weeks": rollup.get("week_count")}
                else:
                    results["month_rollup"] = {"status": "skipped"}
            except Exception as e:
                logger.error(f"Month-rollup failed: {e}")
                results["month_rollup"] = {"status": "error", "error": str(e)}

        return {
            "statusCode": 200,
            "body": json.dumps(results, default=str),
        }
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
