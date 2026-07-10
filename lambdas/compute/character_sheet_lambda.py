"""
Character Sheet Compute Lambda — v1.1.0
Scheduled daily at 9:35 AM PT (17:35 UTC via EventBridge).

Computes the character sheet for yesterday by:
  1. Querying all source data from DynamoDB (with rolling windows)
  2. Loading previous day's character sheet for level continuity
  3. Rebuilding 21-day raw_score histories from stored records
  4. Loading config from S3 via character_engine
  5. Calling compute_character_sheet()
  6. Storing the result to DynamoDB (SOURCE#character_sheet)

Separate from Daily Brief so any future consumer (gamification digest,
push notifications, Chronicle, buddy page) can read the pre-computed
record without re-engineering.

Must run AFTER:
  - Whoop refresh (9:30 AM PT) — ensures today's recovery data exists
  - Cache warmer (9:00 AM PT) — not a hard dependency but good ordering

Must run BEFORE:
  - Daily Brief (10:00 AM PT) — reads the stored record

v1.0.0 — 2026-03-02
v1.1.0 — 2026-03-09: Sick day freeze — EMA frozen, no penalty on sick days
v1.2.0 — 2026-03-26: Phase D — Challenge bonus XP wired into pillar xp_total
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import character_engine
from constants import EXPERIMENT_START_DATE  # ADR-058
from phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("character-sheet-compute")
except ImportError:
    logger = logging.getLogger("character-sheet-compute")
    logger.setLevel(logging.INFO)

# ── Configuration from environment variables ──
_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=_REGION)


# ==============================================================================
# DDB QUERY HELPERS
# ==============================================================================


def d2f(obj):
    """Convert DynamoDB Decimal to float recursively."""
    if isinstance(obj, list):
        return [d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def fetch_date(source, date_str):
    """Fetch a single record for a source on a given date.

    ADR-058: returns None if the record is tombstoned (preserves clean-slate
    semantics during/after the experiment restart wipe).
    """
    try:
        resp = table.get_item(
            Key={
                "pk": USER_PREFIX + source,
                "sk": "DATE#" + date_str,
            }
        )
        item = resp.get("Item")
        if item and item.get("tombstone"):
            return None
        return d2f(item) if item else None
    except Exception as e:
        logger.warning(f"[character] fetch_date({source}, {date_str}) failed: {e}")
        return None


def fetch_range(source, start_date, end_date):
    """Fetch all records for a source within a date range."""
    try:
        records = []
        kwargs = with_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                "ExpressionAttributeValues": {
                    ":pk": USER_PREFIX + source,
                    ":s": "DATE#" + start_date,
                    ":e": "DATE#" + end_date,
                },
            }
        )
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                records.append(d2f(item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning(f"[character] fetch_range({source}, {start_date}→{end_date}) failed: {e}")
        return []


def fetch_journal_entries(date_str):
    """Fetch journal entries for a specific date."""
    try:
        pk = f"USER#{USER_ID}#SOURCE#notion"
        entries = []
        kwargs = with_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                "ExpressionAttributeValues": {
                    ":pk": pk,
                    ":s": f"DATE#{date_str}#journal#",
                    ":e": f"DATE#{date_str}#journal#zzz",
                },
            }
        )
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                entries.append(d2f(item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return entries
    except Exception as e:
        logger.warning(f"[character] fetch_journal_entries({date_str}) failed: {e}")
        return []


def _enriched_mood_to_10(raw_1to5):
    """Map an enriched_mood value from its native 1–5 domain onto the 0–10
    scale that `character_engine` consumes for `mood_avg`.

    #902: `journal_enrichment_lambda` synthesizes `enriched_mood` as a 1–5 score
    (1 = worst, 5 = best; see its prompt schema `mood_score: <1-5 ...>`), but the
    `social_mood_correlation` consumer in `character_engine.compute_relationships_raw`
    reads `journal.get("mood_avg")` and computes `(mood / 10) * 100`, i.e. it
    treats 10 as the maximal mood (100%). Handing it a raw 1–5 value would
    silently under-score every day (a perfect 5 would read as 50%).

    We use a linear min–max map, `(m - 1) / 4 * 10`, so the full 1–5 domain
    covers the full 0–10 range: 1→0, 3→5, 5→10. This puts a *neutral* mood (3) at
    the midpoint the consumer turns into 50%, consistent with the platform's
    established "3 = neutral" convention on the 1–5 scale (e.g. the partner-email
    mood thresholds `>= 3.5` good / `>= 2.5` neutral). Returns None on bad input.
    """
    try:
        m = float(raw_1to5)
    except (ValueError, TypeError):
        return None
    return (m - 1) / 4 * 10


def merge_journal_view(entries):
    """Collapse a day's templated journal entries into the single dict shape
    character_engine expects (`journal.get("themes")` in interaction_quality,
    `journal.get("mood_avg")` in social_mood_correlation).

    #890: notion journal rows are stored per-template under
    `DATE#{date}#journal#{template}` sort keys — the flat `DATE#{date}` record
    that `fetch_date("notion", ...)` used to look up never exists, so the
    engine's themes path was permanently dead. Themes come from the enrichment
    pipeline (`enriched_themes`; a plain `themes` field is accepted as a
    fallback), deduped across the day's entries with first-seen order kept.

    #902: the same key mismatch also meant `mood_avg` was never populated on this
    view, so `social_mood_correlation` stayed dead. We now average the day's
    `enriched_mood` values (native 1–5) and map them onto the engine's 0–10 scale
    via `_enriched_mood_to_10` (see its docstring for the scale decision).

    Returns None when the day has no themed *and* no mood signal, matching the
    old "no journal record" falsy contract (the engine does
    `data.get("journal") or {}`).
    """
    themes = []
    seen = set()
    moods = []
    for entry in entries or []:
        for theme in entry.get("enriched_themes") or entry.get("themes") or []:
            if isinstance(theme, str) and theme not in seen:
                seen.add(theme)
                themes.append(theme)
        mapped = _enriched_mood_to_10(entry.get("enriched_mood"))
        if mapped is not None:
            moods.append(mapped)

    view = {}
    if themes:
        view["themes"] = themes
    if moods:
        view["mood_avg"] = round(sum(moods) / len(moods), 1)
    return view or None


def _safe_float(rec, field):
    """Extract a float from a record, returning None on failure."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except (ValueError, TypeError):
            return None
    return None


# ==============================================================================
# DATA ASSEMBLY — mirrors retrocompute_character_sheet.assemble_data_for_date
# ==============================================================================


def assemble_data(yesterday_str):
    """Build the data dict that character_engine.compute_character_sheet() expects.

    Queries DDB directly for each source + rolling windows.
    """
    t0 = time.time()
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    data = {"date": yesterday_str}

    # ── Primary source records (yesterday) ──
    whoop = fetch_date("whoop", yesterday_str)
    data["sleep"] = whoop  # Whoop is SOT for sleep
    data["whoop"] = whoop
    data["macrofactor"] = fetch_date("macrofactor", yesterday_str)
    data["apple"] = fetch_date("apple_health", yesterday_str)
    # #890: notion journal rows live only under templated sort keys
    # (DATE#{date}#journal#{template}) — the flat DATE#{date} lookup that
    # fetch_date("notion", ...) performs can never match one, so derive the
    # dict-shaped journal view from the day's entries instead.
    data["journal_entries"] = fetch_journal_entries(yesterday_str)
    data["journal"] = merge_journal_view(data["journal_entries"])
    data["habit_scores"] = fetch_date("habit_scores", yesterday_str)
    # SoM daily aggregates (som_avg_valence) live on the apple_health record, not a
    # separate state_of_mind partition — reuse the already-fetched apple record.
    data["state_of_mind"] = data.get("apple") or {}

    # ── Rolling windows (batch queries for efficiency) ──

    # Sleep 14d (for onset consistency)
    sleep_14d_start = (dt - timedelta(days=13)).strftime("%Y-%m-%d")
    data["sleep_14d"] = fetch_range("whoop", sleep_14d_start, yesterday_str)

    # Strava 7d (training frequency, zone2, diversity)
    strava_7d_start = (dt - timedelta(days=6)).strftime("%Y-%m-%d")
    data["strava_7d"] = fetch_range("strava", strava_7d_start, yesterday_str)

    # Strava 42d (progressive overload / CTL trend)
    strava_42d_start = (dt - timedelta(days=41)).strftime("%Y-%m-%d")
    data["strava_42d"] = fetch_range("strava", strava_42d_start, yesterday_str)

    # MacroFactor 14d (nutrition consistency)
    mf_14d_start = (dt - timedelta(days=13)).strftime("%Y-%m-%d")
    data["macrofactor_14d"] = fetch_range("macrofactor", mf_14d_start, yesterday_str)

    # Withings 30d (body fat trajectory)
    withings_30d_start = (dt - timedelta(days=29)).strftime("%Y-%m-%d")
    data["withings_30d"] = fetch_range("withings", withings_30d_start, yesterday_str)

    # Latest weight — the ONE shared resolution (#491/M-6): Withings backscan +
    # a 7-day apple_health window, via the weight_trend layer module (the same
    # helper vitals/journey use, so no surface can disagree on "current weight").
    try:
        import weight_trend

        _ah_7d_start = (dt - timedelta(days=6)).strftime("%Y-%m-%d")
        _ah_7d = fetch_range("apple_health", _ah_7d_start, yesterday_str)
        data["latest_weight"] = weight_trend.latest_weight(data["withings_30d"], _ah_7d)["weight_lbs"]
    except ImportError:
        # layer module missing (local test without layer) — withings-only backscan
        data["latest_weight"] = next(
            (_safe_float(rec, "weight_lbs") for rec in reversed(data["withings_30d"]) if _safe_float(rec, "weight_lbs") is not None),
            None,
        )

    # Latest labs — search backwards from yesterday
    labs_all = fetch_range("labs", "2020-01-01", yesterday_str)
    data["labs_latest"] = d2f(labs_all[-1]) if labs_all else None

    # Blood pressure
    apple = data.get("apple") or {}
    bp_sys = _safe_float(apple, "blood_pressure_systolic")
    bp_dia = _safe_float(apple, "blood_pressure_diastolic")
    data["bp_data"] = {"systolic": bp_sys, "diastolic": bp_dia} if bp_sys and bp_dia else None

    # Journal 14d count — lightweight existence checks
    j14d_count = 0
    for i in range(14):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            pk = f"USER#{USER_ID}#SOURCE#notion"
            _j14_kwargs = with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": pk,
                        ":s": f"DATE#{d}#journal#",
                        ":e": f"DATE#{d}#journal#zzz",
                    },
                    "Select": "COUNT",
                }
            )
            resp = table.query(**_j14_kwargs)
            if resp.get("Count", 0) > 0:
                j14d_count += 1
        except Exception:
            pass
    data["journal_14d_count"] = j14d_count

    # Data completeness — use already-fetched data where possible
    expected_count = 5  # whoop, macrofactor, apple_health, strava, habitify
    present = 0
    if data["whoop"]:
        present += 1
    if data["macrofactor"]:
        present += 1
    if data["apple"]:
        present += 1
    # Strava: check if yesterday is in our 7d window (avoids re-fetch)
    strava_dates = {r.get("date") or r.get("sk", "").replace("DATE#", "") for r in data["strava_7d"]}
    if yesterday_str in strava_dates:
        present += 1
    # Habitify: need a separate fetch (not queried elsewhere)
    if fetch_date("habitify", yesterday_str):
        present += 1
    data["data_completeness_pct"] = round((present / expected_count) * 100, 1)

    elapsed = time.time() - t0
    logger.info(
        f"[character] Data assembled for {yesterday_str} in {elapsed:.1f}s — sources: "
        + ", ".join(k for k in ["whoop", "macrofactor", "apple", "habit_scores", "state_of_mind", "journal_entries"] if data.get(k))
    )
    return data


# ==============================================================================
# HISTORY LOADING — fetch prior character sheet records for continuity
# ==============================================================================


def load_previous_state(yesterday_str):
    """Load the most recent character sheet record, scanning back up to 7 days.

    Previously only looked back 1 day, which caused level resets when the
    compute Lambda skipped a day (e.g., missing env var, Lambda failure).
    Now scans backwards to find the last valid state, preserving level continuity.
    """
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    for days_back in range(1, 8):
        check_date = (dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
        state = fetch_date("character_sheet", check_date)
        if state and state.get("character_level") is not None:
            if days_back > 1:
                logger.info(f"[character] Previous state found {days_back} days back ({check_date})")
            return state
    return None


def load_raw_score_histories(yesterday_str, window=21):
    """Load up to `window` days of raw_score histories from stored character sheets.

    Returns dict of pillar_name -> list of raw_scores (oldest first).
    The engine uses these for EMA smoothing.
    """
    dt = datetime.strptime(yesterday_str, "%Y-%m-%d")
    start = (dt - timedelta(days=window)).strftime("%Y-%m-%d")
    end = (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    records = fetch_range("character_sheet", start, end)

    histories = {p: [] for p in PILLAR_ORDER}
    # Records come back sorted by sk (DATE#...) which is chronological
    for rec in records:
        for p in PILLAR_ORDER:
            pdata = rec.get(f"pillar_{p}") or {}
            raw = pdata.get("raw_score")
            histories[p].append(float(raw) if raw is not None else 40.0)

    return histories


# ==============================================================================
# FOOD DELIVERY MODIFIER — adjusts Nutrition pillar based on delivery streak
# ==============================================================================


def get_food_delivery_modifier():
    """Returns a multiplier (0.85-1.10) for the Nutrition pillar based on delivery streak."""
    try:
        resp = table.get_item(Key={"pk": "USER#matthew#SOURCE#food_delivery", "sk": "STREAK#current"})
        streak = resp.get("Item", {})
        if not streak:
            return 1.0
        streak_days = int(streak.get("streak_days", 0))
        last_order = streak.get("last_order_date", "")
        from datetime import datetime

        # 15% penalty for ordering delivery; graduated bonus at 7/14/30 clean days
        if last_order == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            return 0.85
        if streak_days >= 30:
            return 1.10
        if streak_days >= 14:
            return 1.05
        if streak_days >= 7:
            return 1.02
        return 1.0
    except Exception:
        return 1.0


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================


def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    t0 = time.time()
    logger.info("[character] Character Sheet Compute v1.1.0 starting...")

    # ── Determine target date ──
    # Default: yesterday. Can override via event for backfill/testing.
    if event.get("date"):
        yesterday_str = event["date"]
        logger.info(f"[character] Override date: {yesterday_str}")
    else:
        today = datetime.now(timezone.utc).date()
        yesterday_str = (today - timedelta(days=1)).isoformat()

    # ── Check if already computed (idempotency) ──
    if not event.get("force"):
        existing = fetch_date("character_sheet", yesterday_str)
        if existing:
            logger.info(f"[character] Already computed for {yesterday_str} — skipping")
            return {
                "statusCode": 200,
                "body": f"Already computed for {yesterday_str}",
                "character_level": existing.get("character_level"),
                "character_tier": existing.get("character_tier"),
            }

    # ── Sick day check ─────────────────────────────────────────────────────
    # If the target date is flagged as a sick/rest day, freeze the EMA:
    # copy the previous day's character sheet record verbatim (no gain, no
    # penalty), mark it sick_day=True, and return early.
    try:
        from sick_day_checker import check_sick_day as _check_sick

        _sick_rec = _check_sick(table, USER_ID, yesterday_str)
    except ImportError:
        _sick_rec = None

    if _sick_rec:
        _sick_reason = _sick_rec.get("reason") or "sick day"
        logger.info(f"[character] Sick day flagged for {yesterday_str} ({_sick_reason}) — freezing EMA")
        _prev = load_previous_state(yesterday_str)
        if _prev:
            # Build a frozen record: copy previous EMA state, update date fields
            _frozen = {k: v for k, v in _prev.items()}
            _frozen["pk"] = USER_PREFIX + "character_sheet"
            _frozen["sk"] = "DATE#" + yesterday_str
            _frozen["date"] = yesterday_str
            _frozen["sick_day"] = True
            _frozen["sick_day_reason"] = _sick_reason
            _frozen["frozen_from"] = _prev.get("date", "")
            _frozen["computed_at"] = datetime.now(timezone.utc).isoformat()

            # Convert floats → Decimal for DynamoDB
            def _dec(obj):
                if isinstance(obj, list):
                    return [_dec(i) for i in obj]
                if isinstance(obj, dict):
                    return {k: _dec(v) for k, v in obj.items()}
                if isinstance(obj, bool):
                    return obj
                if isinstance(obj, float):
                    return Decimal(str(obj))
                if isinstance(obj, int):
                    return Decimal(str(obj))
                return obj

            # Phase 3.3 (2026-05-16): tag with run_id + computed_at for double-run observability.
            from compute_metadata import tag_record

            _tagged = tag_record({k: _dec(v) for k, v in _frozen.items() if v is not None}, source_id="character_sheet")
            table.put_item(Item=_tagged)
            logger.info(f"[character] Frozen record stored for {yesterday_str} (from {_frozen.get('frozen_from', '?')})")
            return {
                "statusCode": 200,
                "body": f"Sick day {yesterday_str}: character sheet EMA frozen (no change)",
                "sick_day": True,
                "frozen_from": _frozen.get("frozen_from", ""),
                "character_level": _prev.get("character_level"),
                "character_tier": _prev.get("character_tier"),
            }
        else:
            logger.info("[character] Sick day but no previous state — skipping compute entirely")
            return {
                "statusCode": 200,
                "body": f"Sick day {yesterday_str}: no previous state to freeze from, skipped",
                "sick_day": True,
            }

    # ── Load config from S3 ──
    config = character_engine.load_character_config(s3, S3_BUCKET)
    if not config:
        # RAISE so the async failure is visible (DLQ + Errors metric + alarm) instead
        # of a returned dict that reads as success. (Elite review 2026-06-15)
        raise RuntimeError("character-sheet: failed to load config from S3 — aborting")

    logger.info(f"[character] Config loaded — {len(config.get('pillars', {}))} pillars")

    # ── Assemble data ──
    data = assemble_data(yesterday_str)

    # ── Load continuity state ──
    previous_state = load_previous_state(yesterday_str)
    if previous_state:
        logger.info(
            f"[character] Previous state loaded — Level {previous_state.get('character_level', '?')} ({previous_state.get('character_tier_emoji', '')} {previous_state.get('character_tier', '?')})"
        )
    else:
        logger.info("[character] No previous state — starting from baseline")

    raw_score_histories = load_raw_score_histories(yesterday_str)
    history_depth = max(len(v) for v in raw_score_histories.values()) if raw_score_histories else 0
    logger.info(f"[character] Raw score histories loaded — {history_depth} days of history")

    # ── Compute ──
    try:
        record = character_engine.compute_character_sheet(data, previous_state, raw_score_histories, config)
    except Exception as e:
        logger.error(f"[character] compute_character_sheet failed: {e}")
        raise  # surface the failure (DLQ + alarm) — a returned 500 reads as success

    # ── Food delivery modifier — adjust Nutrition pillar raw_score ──
    fd_modifier = get_food_delivery_modifier()
    if fd_modifier != 1.0 and "pillar_nutrition" in record:
        _nut = record["pillar_nutrition"]
        _orig = float(_nut.get("raw_score", 0))
        _nut["raw_score"] = round(max(0, min(100, _orig * fd_modifier)), 1)
        _nut["food_delivery_modifier"] = fd_modifier
        logger.info(f"[character] Food delivery modifier {fd_modifier} applied to nutrition: {_orig} → {_nut['raw_score']}")

    char_level = record.get("character_level", 1)
    char_tier = record.get("character_tier", "Foundation")
    char_emoji = record.get("character_tier_emoji", "🔨")
    events = record.get("level_events", [])

    # Log pillar summary
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        logger.info(
            f"[character]   {p}: raw={pd.get('raw_score', '?')} level={pd.get('level', '?')} tier={pd.get('tier', '?')} ({pd.get('tier_emoji', '?')})"
        )

    # Log events
    if events:
        for ev in events:
            logger.info(f"[character]   EVENT: {json.dumps(ev, default=str)}")

    # Log active effects
    effects = record.get("active_effects", [])
    if effects:
        for eff in effects:
            logger.info(f"[character]   EFFECT: {eff.get('emoji', '')} {eff.get('name', '')}")

    # ── Phase D: Challenge bonus XP ──────────────────────────────────────
    # Query challenges completed on the target date that haven't been
    # XP-consumed yet. Add bonus XP to the relevant pillar.
    CHALLENGE_DOMAIN_TO_PILLAR = {
        "sleep": "sleep",
        "movement": "movement",
        "nutrition": "nutrition",
        "supplements": "nutrition",
        "mental": "mind",
        "social": "relationships",
        "discipline": "consistency",
        "metabolic": "metabolic",
        "general": "consistency",
    }
    challenge_bonus_xp = {}  # pillar → total bonus XP
    try:
        from boto3.dynamodb.conditions import Key as _Key

        _ch_pk = USER_PREFIX + "challenges"
        _ch_kwargs = with_phase_filter(
            {
                "KeyConditionExpression": _Key("pk").eq(_ch_pk) & _Key("sk").begins_with("CHALLENGE#"),
            }
        )
        _ch_resp = table.query(**_ch_kwargs)
        _completed_today = [
            c
            for c in _ch_resp.get("Items", [])
            if c.get("status") in ("completed", "failed")
            and (c.get("completed_at", "") or "").startswith(yesterday_str)
            and not c.get("xp_consumed_at")
            and int(d2f(c.get("character_xp_awarded", 0))) > 0
        ]
        for ch in _completed_today:
            xp = int(d2f(ch.get("character_xp_awarded", 0)))
            domain = ch.get("domain", "general")
            pillar = CHALLENGE_DOMAIN_TO_PILLAR.get(domain, "consistency")
            challenge_bonus_xp[pillar] = challenge_bonus_xp.get(pillar, 0) + xp

            # Apply bonus to pillar in record
            pillar_key = f"pillar_{pillar}"
            if pillar_key in record:
                record[pillar_key]["xp_total"] = record[pillar_key].get("xp_total", 0) + xp
                record[pillar_key]["challenge_bonus_xp"] = record[pillar_key].get("challenge_bonus_xp", 0) + xp
                logger.info(f"[character]   CHALLENGE XP: +{xp} to {pillar} from '{ch.get('name', '?')}' ({domain})")

            # Mark challenge as XP-consumed (prevent double-counting)
            table.update_item(
                Key={"pk": _ch_pk, "sk": ch["sk"]},
                UpdateExpression="SET xp_consumed_at = :ts",
                ExpressionAttributeValues={":ts": datetime.now(timezone.utc).isoformat()},
            )

        if challenge_bonus_xp:
            # Recalculate total character XP with bonuses
            record["character_xp"] = sum(record.get(f"pillar_{p}", {}).get("xp_total", 0) for p in PILLAR_ORDER)
            record["challenge_bonus_xp"] = challenge_bonus_xp
            logger.info(f"[character] Challenge bonus XP applied: {challenge_bonus_xp}")
    except Exception as _ch_err:
        logger.warning(f"[character] Challenge XP bonus failed (non-fatal): {_ch_err}")

    # ── Store (with DATA-2 validation — Item 3, R12) ──
    # validate_item before store_character_sheet, which adds pk/sk and Decimal-converts.
    # We validate a lightweight proxy item — only the fields the schema checks.
    try:
        from ingestion_validator import validate_item as _vi

        _val_proxy = {
            "pk": USER_PREFIX + "character_sheet",
            "sk": "DATE#" + yesterday_str,
            "date": yesterday_str,
            "character_level": record.get("character_level"),
            "character_tier": record.get("character_tier"),
            "computed_at": record.get("computed_at", ""),
        }
        _vr = _vi("character_sheet", _val_proxy, yesterday_str)
        if _vr.should_skip_ddb:
            logger.error("[character][DATA-2] Skipping character_sheet write: %s", _vr.errors)
            return {"statusCode": 500, "body": f"Validation failed: {_vr.errors}"}
        if _vr.warnings:
            logger.warning("[character][DATA-2] character_sheet warnings: %s", _vr.warnings)
    except ImportError:
        pass  # validator not bundled
    except Exception as ve:
        logger.warning("[character][DATA-2] validate_item failed (proceeding): %s", ve)

    try:
        character_engine.store_character_sheet(table, USER_PREFIX, record)
        logger.info(f"[character] Stored: {yesterday_str} — Level {char_level} ({char_emoji} {char_tier}) — {len(events)} events")
    except Exception as e:
        logger.error(f"[character] store_character_sheet failed: {e}")
        raise  # surface the failure (DLQ + alarm) — a returned 500 reads as success

    elapsed = time.time() - t0
    logger.info("[character] Done in %.1fs", elapsed)

    # site_writer: write character_stats.json to S3 for averagejoematt.com
    # Non-fatal — failure here never breaks character sheet compute
    try:
        from site_writer import write_character_stats

        PILLAR_EMOJI_MAP = {
            "sleep": "😴",
            "movement": "🏋️",
            "nutrition": "🥗",
            "metabolic": "📊",
            "mind": "🧠",
            "relationships": "💬",
            "consistency": "🎯",
        }
        pillars_for_site = [
            {
                "name": p,
                "emoji": PILLAR_EMOJI_MAP.get(p, ""),
                "level": float(record.get(f"pillar_{p}", {}).get("level", 1)),
                "raw_score": float(record.get(f"pillar_{p}", {}).get("raw_score", 0)),
                "tier": record.get(f"pillar_{p}", {}).get("tier", "Foundation"),
                "xp_delta": float(record.get(f"pillar_{p}", {}).get("xp_delta", 0)),
                "challenge_bonus_xp": float(record.get(f"pillar_{p}", {}).get("challenge_bonus_xp", 0)),
                "trend": "up" if float(record.get(f"pillar_{p}", {}).get("xp_delta", 0)) > 0 else "neutral",
            }
            for p in PILLAR_ORDER
        ]

        def _build_event_description(ev):
            pillar = (ev.get("pillar") or "overall").title()
            etype = ev.get("type", "")
            ev.get("old_level", "?")
            new_lv = ev.get("new_level", "?")
            base = f"{pillar} \u2192 Level {new_lv}"
            if "tier" in etype:
                base = f"{pillar} tier {'up' if 'up' in etype else 'down'}: {ev.get('new_tier', '?')}"
            # Add "why" context if available
            parts = []
            if ev.get("top_driver"):
                parts.append(f"{ev['top_driver']}")
                if ev.get("top_driver_value"):
                    parts[-1] += f" at {ev['top_driver_value']}"
            if ev.get("streak_days") and ev["streak_days"] > 1:
                parts.append(f"{ev['streak_days']}-day streak")
            if ev.get("xp_earned") and ev["xp_earned"] > 0:
                parts.append(f"+{ev['xp_earned']} XP")
            if parts:
                base += f" \u2014 {', '.join(parts)}"
            return base

        timeline_events = [
            {
                "date": ev.get("date", yesterday_str),
                "character_level": float(ev.get("new_level", char_level)),
                "event": _build_event_description(ev),
            }
            for ev in (events or [])
        ]

        # CHAR-4: Build weekly pillar history for heatmap
        _pillar_history = []
        try:
            from collections import defaultdict as _dd

            _hist_start = (datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=49)).strftime("%Y-%m-%d")
            _hist_recs = fetch_range("character_sheet", _hist_start, yesterday_str)
            _weeks = _dd(list)
            for _rec in _hist_recs:
                _d = _rec.get("date") or _rec.get("sk", "").replace("DATE#", "")
                if not _d:
                    continue
                _dt = datetime.strptime(_d, "%Y-%m-%d")
                _wk = _dt.strftime("%G-W%V")  # ISO year-week
                _weeks[_wk].append((_d, _rec))
            for _wk in sorted(_weeks.keys()):
                _last_date, _last_rec = _weeks[_wk][-1]
                _scores = {}
                for _p in PILLAR_ORDER:
                    _pdata = _last_rec.get(f"pillar_{_p}") or {}
                    _scores[_p] = round(float(_pdata.get("level_score") or _pdata.get("raw_score") or 0), 1)
                _wk_dt = datetime.strptime(_last_date, "%Y-%m-%d")
                _mon_dt = _wk_dt - timedelta(days=_wk_dt.weekday())
                _pillar_history.append(
                    {
                        "week_label": f"Wk {_wk.split('-W')[1]}",
                        "week_end": _last_date,
                        "week_start": _mon_dt.strftime("%Y-%m-%d"),
                        "pillars": _scores,
                    }
                )
        except Exception as _phe:
            logger.warning(f"[character] pillar_history build failed (non-fatal): {_phe}")

        write_character_stats(
            s3_client=boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2")),
            character={
                "level": float(char_level),
                "tier": char_tier,
                "tier_emoji": char_emoji,
                "xp_total": float(record.get("character_xp", 0)),
                "days_active": int(history_depth),
                "level_events_count": len(events),
                "next_tier": "Momentum",
                "next_tier_level": 21,
                "started_date": EXPERIMENT_START_DATE,
                "challenge_bonus_xp": {k: v for k, v in (record.get("challenge_bonus_xp") or {}).items()},
            },
            pillars=pillars_for_site,
            timeline=timeline_events,
            pillar_history=_pillar_history,
        )
        logger.info("[character] site_writer: character_stats.json written")
    except Exception as _sw_e:
        logger.warning(f"[character] site_writer failed (non-fatal): {_sw_e}")

    return {
        "statusCode": 200,
        "body": f"Character sheet computed for {yesterday_str}: Level {char_level} ({char_emoji} {char_tier})",
        "date": yesterday_str,
        "character_level": char_level,
        "character_tier": char_tier,
        "events": events,
        "elapsed_seconds": round(elapsed, 1),
    }
