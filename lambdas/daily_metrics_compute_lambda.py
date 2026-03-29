"""
Daily Metrics Compute Lambda — v1.1.0
Scheduled daily at 9:40 AM PT (17:40 UTC via EventBridge).

Pre-computes all derived metrics needed by the Daily Brief so the Brief
becomes a pure read + render operation with zero inline derivation logic.

Computes and stores:
  - Day grade (total score, letter, component scores + details)
  - Readiness (score, colour)
  - Habit streaks (tier0, tier01, vice streaks per-habit)
  - TSB (training stress balance, 60-day Banister model)
  - HRV averages (7d, 30d)
  - Sleep debt (7-day cumulative vs target)
  - Weight (latest, week-ago, avatar fallback)

DynamoDB partitions written:
  1. SOURCE#computed_metrics   — primary; Daily Brief + dashboard refresh reads this
  2. SOURCE#day_grade          — existing schema; MCP tools + regrade backfill compat
  3. SOURCE#habit_scores       — existing schema; habit trending MCP tools compat

Schedule ordering:
  9:30 AM PT  Whoop recovery refresh (ensures today's data exists)
  9:35 AM PT  character-sheet-compute  (no dependency on this Lambda)
  9:40 AM PT  daily-metrics-compute    ← this Lambda
  10:00 AM PT daily-brief              (reads computed_metrics record)

Pattern: follows character-sheet-compute Lambda architecture.

v1.0.0 — 2026-03-07
v1.1.0 — 2026-03-09: Sick day support — grade='sick', streaks preserved
"""

import json
import math
import os
import time
import logging
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import scoring_engine

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("daily-metrics-compute")
except ImportError:
    logger = logging.getLogger("daily-metrics-compute")
    logger.setLevel(logging.INFO)

# ── Configuration ──
_REGION      = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME   = os.environ.get("TABLE_NAME", "life-platform")
USER_ID      = os.environ["USER_ID"]
ALGO_VERSION = "1.1"

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)


# ==============================================================================
# HELPERS
# ==============================================================================

def d2f(obj):
    """Recursively convert DynamoDB Decimal to float."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def safe_float(rec, field, default=None):
    if rec and field in rec:
        try:   return float(rec[field])
        except Exception: return default
    return default


def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))


# ==============================================================================
# DDB FETCH HELPERS
# ==============================================================================

def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception as e:
        logger.warning(f"fetch_date({source}, {date_str}) failed: {e}")
        return None


def fetch_range(source, start, end):
    try:
        records = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {
                ":pk": USER_PREFIX + source,
                ":s": "DATE#" + start,
                ":e": "DATE#" + end,
            },
        }
        while True:
            r = table.query(**kwargs)
            records.extend(d2f(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning(f"fetch_range({source}, {start}→{end}) failed: {e}")
        return []


def fetch_profile():
    try:
        r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error(f"fetch_profile failed: {e}")
        return {}


def fetch_journal_entries(date_str):
    try:
        r = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "notion",
                ":prefix": "DATE#" + date_str + "#journal#",
            })
        return [d2f(i) for i in r.get("Items", [])]
    except Exception as e:
        logger.warning(f"fetch_journal_entries({date_str}) failed: {e}")
        return []


# ==============================================================================
# NORMALIZE WHOOP SLEEP  (mirrors daily_brief_lambda)
# ==============================================================================

def normalize_whoop_sleep(item):
    """Map Whoop field names to common schema used by scoring engine."""
    if not item:
        return item
    out = dict(item)
    if "sleep_quality_score" in out and "sleep_score" not in out:
        out["sleep_score"] = out["sleep_quality_score"]
    if "sleep_efficiency_percentage" in out and "sleep_efficiency_pct" not in out:
        out["sleep_efficiency_pct"] = out["sleep_efficiency_percentage"]
    dur = None
    try:
        dur = float(out.get("sleep_duration_hours", 0)) or None
    except (TypeError, ValueError):
        pass
    if dur and dur > 0:
        for src_field, pct_field in [
            ("slow_wave_sleep_hours", "deep_pct"),
            ("rem_sleep_hours",       "rem_pct"),
            ("light_sleep_hours",     "light_pct"),
        ]:
            try:
                hrs = float(out.get(src_field, 0))
                if pct_field not in out:
                    out[pct_field] = round(hrs / dur * 100, 1)
            except (TypeError, ValueError):
                pass
    if "time_awake_hours"  in out and "waso_hours"     not in out:
        out["waso_hours"]     = out["time_awake_hours"]
    if "disturbance_count" in out and "toss_and_turns" not in out:
        out["toss_and_turns"] = out["disturbance_count"]
    return out


# ==============================================================================
# DEDUP ACTIVITIES  (mirrors daily_brief_lambda)
# ==============================================================================

def dedup_activities(activities):
    """Remove overlapping multi-device Strava activities.

    Overlap = same sport_type AND start times within 15 minutes.
    Keep = richer record (has distance > longer duration > has polyline).
    """
    if len(activities) <= 1:
        return activities
    from datetime import datetime as _dt

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:   return _dt.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError): return None

    def richness(a):
        score = 0
        if float(a.get("distance_meters") or 0) > 0: score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"):                 score += 500
        if a.get("average_cadence") is not None:      score += 100
        return score

    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])
    remove = set()
    for j in range(len(indexed)):
        if j in remove: continue
        i_j, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove: continue
            i_k, a_k, t_k = indexed[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()
            if sport_j != sport_k: continue
            if abs((t_k - t_j).total_seconds()) / 60 > 15: break
            remove.add(k if richness(a_j) >= richness(a_k) else j)
    kept    = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


# ==============================================================================
# TSB COMPUTATION
# ==============================================================================

def compute_tsb(strava_60d, today):
    """Banister model: Training Stress Balance = CTL − ATL over 60-day window."""
    kj = {}
    for r in strava_60d:
        d = str(r.get("date", ""))
        if d:
            kj[d] = sum(float(a.get("kilojoules") or 0) for a in r.get("activities", []))
    ctl = atl = 0.0
    cd = math.exp(-1 / 42)
    ad = math.exp(-1 / 7)
    for i in range(59, -1, -1):
        day  = (today - timedelta(days=i)).isoformat()
        load = kj.get(day, 0)
        ctl  = ctl * cd + load * (1 - cd)
        atl  = atl * ad + load * (1 - ad)
    return round(ctl - atl, 1)


# ==============================================================================
# READINESS COMPUTATION
# ==============================================================================

def compute_readiness(data):
    """Composite readiness: recovery (40%), sleep (30%), HRV trend (20%), TSB (10%)."""
    components = []
    whoop_today = data.get("whoop_today")
    whoop_yest  = data.get("whoop")
    recovery = safe_float(whoop_today, "recovery_score") or safe_float(whoop_yest, "recovery_score")
    if recovery is not None:
        components.append(("recovery", float(recovery), 0.40))
    sleep_score = safe_float(data.get("sleep"), "sleep_score")
    if sleep_score is not None:
        components.append(("sleep", float(sleep_score), 0.30))
    hrv_7d  = data["hrv"].get("hrv_7d")
    hrv_30d = data["hrv"].get("hrv_30d")
    if hrv_7d and hrv_30d and hrv_30d > 0:
        hrv_score = clamp(round((hrv_7d / hrv_30d - 0.75) * 200))
        components.append(("hrv_trend", hrv_score, 0.20))
    tsb = data.get("tsb")
    if tsb is not None:
        components.append(("tsb", clamp(round(60 + tsb * 2)), 0.10))
    if not components:
        return None, "gray"
    tw    = sum(w for _, _, w in components)
    score = round(sum(v * w for _, v, w in components) / tw)
    if score >= 80: return score, "green"
    if score >= 60: return score, "yellow"
    return score, "red"


# ==============================================================================
# HABIT STREAKS
# ==============================================================================

def compute_habit_streaks(profile, yesterday_str):
    """Compute tier0 streak, tier0+1 streak, and per-vice streaks (up to 90-day lookback)."""
    registry  = profile.get("habit_registry", {})
    mvp_list  = profile.get("mvp_habits", [])

    tier0_habits  = []
    tier01_habits = []
    vice_habits   = []
    for name, meta in registry.items():
        if meta.get("status") != "active": continue
        tier = meta.get("tier", 2)
        if tier == 0:
            tier0_habits.append(name)
            tier01_habits.append(name)
        elif tier == 1:
            tier01_habits.append(name)
        if meta.get("vice", False):
            vice_habits.append(name)

    if not tier0_habits:
        tier0_habits  = mvp_list
        tier01_habits = mvp_list

    tier0_streak  = 0
    tier01_streak = 0
    t0_broken     = False
    t01_broken    = False
    vice_streaks  = {v: 0 for v in vice_habits}
    vice_broken   = {v: False for v in vice_habits}

    for i in range(0, 90):
        dt         = datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=i)
        date_str   = dt.strftime("%Y-%m-%d")
        is_weekday = dt.weekday() < 5
        rec        = fetch_date("habitify", date_str)
        if not rec:
            break
        habits_map = rec.get("habits", {})

        if not t0_broken:
            all_t0 = all(
                float(habits_map.get(h, 0) or 0) >= 1
                for h in tier0_habits
                if not (registry.get(h, {}).get("applicable_days") == "weekdays" and not is_weekday)
            )
            if all_t0: tier0_streak += 1
            else:      t0_broken = True

        if not t01_broken:
            all_t01 = all(
                float(habits_map.get(h, 0) or 0) >= 1
                for h in tier01_habits
                if not (registry.get(h, {}).get("applicable_days") == "weekdays" and not is_weekday)
                and registry.get(h, {}).get("applicable_days") != "post_training"
            )
            if all_t01: tier01_streak += 1
            else:       t01_broken = True

        for v in vice_habits:
            if not vice_broken[v]:
                done = habits_map.get(v, 0)
                if done is not None and float(done) >= 1:
                    vice_streaks[v] += 1
                else:
                    vice_broken[v] = True

        if t0_broken and t01_broken and all(vice_broken.values()):
            break

    return {
        "tier0_streak":  tier0_streak,
        "tier01_streak": tier01_streak,
        "vice_streaks":  vice_streaks,
    }


# ==============================================================================
# DECIMAL SERIALIZATION HELPERS
# ==============================================================================

def _to_dec(val):
    if val is None: return None
    return Decimal(str(round(float(val), 4)))


def _deep_dec(obj):
    """Recursively convert floats/ints to Decimal for DynamoDB storage.
    DynamoDB requires all map keys to be strings — int keys (e.g. tier_status {0:, 1:, 2:})
    are coerced to str here.
    """
    if isinstance(obj, list):  return [_deep_dec(i) for i in obj]
    if isinstance(obj, dict):  return {str(k): _deep_dec(v) for k, v in obj.items()}
    if isinstance(obj, bool):  return obj
    if isinstance(obj, float): return Decimal(str(round(obj, 4)))
    if isinstance(obj, int):   return Decimal(str(obj))
    return obj


# ==============================================================================
# STORE HELPERS
# ==============================================================================

def store_computed_metrics(
    date_str, day_grade_score, grade, component_scores, component_details,
    readiness_score, readiness_colour, streak_data,
    tsb, hrv_7d, hrv_30d, sleep_debt_7d_hrs,
    latest_weight, week_ago_weight, avatar_weight,
    source_fingerprints=None,
):
    """Write computed_metrics record — primary output of this Lambda."""
    item = {
        "pk":                 USER_PREFIX + "computed_metrics",
        "sk":                 "DATE#" + date_str,
        "date":               date_str,
        "day_grade_letter":   grade,
        "readiness_colour":   readiness_colour,
        "tier0_streak":       Decimal(str(streak_data.get("tier0_streak",  0))),
        "tier01_streak":      Decimal(str(streak_data.get("tier01_streak", 0))),
        "sleep_debt_7d_hrs":  _to_dec(sleep_debt_7d_hrs) or Decimal("0"),
        "computed_at":        datetime.now(timezone.utc).isoformat(),
        "algo_version":       ALGO_VERSION,
    }
    if day_grade_score is not None:
        item["day_grade_score"] = _to_dec(day_grade_score)
    if readiness_score is not None:
        item["readiness_score"] = _to_dec(readiness_score)
    for field, val in [("tsb", tsb), ("hrv_7d", hrv_7d), ("hrv_30d", hrv_30d),
                        ("latest_weight", latest_weight), ("week_ago_weight", week_ago_weight),
                        ("avatar_weight", avatar_weight)]:
        if val is not None:
            item[field] = _to_dec(val)

    # Component scores
    cs_dec = {k: Decimal(str(v)) for k, v in component_scores.items() if v is not None}
    if cs_dec:
        item["component_scores"] = cs_dec

    # Component details (nested — convert floats to Decimal)
    cd_dec = {k: _deep_dec(v) for k, v in component_details.items() if v}
    if cd_dec:
        item["component_details"] = cd_dec

    # Vice streaks
    vs = streak_data.get("vice_streaks", {})
    if vs:
        item["vice_streaks"] = {k: Decimal(str(v)) for k, v in vs.items()}

    # Source fingerprints — used for data-aware idempotency on subsequent runs
    if source_fingerprints:
        item["source_fingerprints"] = source_fingerprints

    item = {k: v for k, v in item.items() if v is not None}
    # DATA-2: Use validate_item directly (no S3 client — compute partitions don't archive
    # to S3 on failure; they log and skip. validate_and_write requires s3_client != None.)
    try:
        from ingestion_validator import validate_item as _vi
        _vr = _vi("computed_metrics", item, date_str)
        if _vr.should_skip_ddb:
            logger.error("[DATA-2] Skipping computed_metrics write for %s: %s", date_str, _vr.errors)
            return  # critical validation failure — don't write corrupt data
        if _vr.warnings:
            logger.warning("[DATA-2] computed_metrics warnings for %s: %s", date_str, _vr.warnings)
    except ImportError:
        pass  # validator not bundled — proceed without check
    except Exception as ve:
        logger.warning("[DATA-2] validate_item failed (proceeding with write): %s", ve)
    try:
        table.put_item(Item=item)
    except Exception as ddb_err:
        logger.error(f"[ERROR] CRITICAL: computed_metrics DDB write failed: {ddb_err}")
        raise
    logger.info(
        "Stored computed_metrics: %s — grade=%s (%s) readiness=%s (%s) "
        "T0_streak=%s TSB=%s",
        date_str, day_grade_score, grade,
        readiness_score, readiness_colour,
        streak_data.get("tier0_streak", 0), tsb,
    )


def store_day_grade(date_str, total_score, grade, component_scores, weights):
    """Write day_grade record — preserves existing schema for MCP tool compatibility."""
    try:
        item = {
            "pk":                USER_PREFIX + "day_grade",
            "sk":                "DATE#" + date_str,
            "date":              date_str,
            "total_score":       Decimal(str(total_score)),
            "letter_grade":      grade,
            "algorithm_version": ALGO_VERSION,
            "weights_snapshot":  _deep_dec(weights) if weights else {},
            "computed_at":       datetime.now(timezone.utc).isoformat(),
        }
        for comp, score in component_scores.items():
            if score is not None:
                item["component_" + comp] = Decimal(str(score))
        # DATA-2: validate_item directly (no S3 client for compute partitions)
        try:
            from ingestion_validator import validate_item as _vi
            _vr = _vi("day_grade", item, date_str)
            if _vr.should_skip_ddb:
                logger.error("[DATA-2] Skipping day_grade write for %s: %s", date_str, _vr.errors)
                return
            if _vr.warnings:
                logger.warning("[DATA-2] day_grade warnings for %s: %s", date_str, _vr.warnings)
        except ImportError:
            pass
        except Exception as ve:
            logger.warning("[DATA-2] day_grade validate_item failed (proceeding): %s", ve)
        table.put_item(Item=item)
        logger.info(f"Stored day_grade: {date_str} → {total_score} ({grade})")
    except Exception as e:
        logger.warning(f"store_day_grade failed: {e}")


def store_habit_scores(date_str, component_details, component_scores, vice_streaks, profile):
    """Write habit_scores record — preserves existing schema for trending tool compatibility."""
    try:
        hd = component_details.get("habits_mvp", {})
        if not hd or hd.get("composite_method") != "tier_weighted":
            return
        t0    = hd.get("tier0", {})
        t1    = hd.get("tier1", {})
        vices = hd.get("vices", {})
        tier_status = hd.get("tier_status", {})
        missed_t0   = [name for name, done in tier_status.get(0, {}).items() if not done]

        registry = profile.get("habit_registry", {})
        all_status = {}
        for tier_habits in tier_status.values():
            all_status.update(tier_habits)

        synergy_groups = {}
        for h_name, meta in registry.items():
            sg = meta.get("synergy_group")
            if not sg or meta.get("status") != "active": continue
            synergy_groups.setdefault(sg, {"done": 0, "total": 0})
            synergy_groups[sg]["total"] += 1
            if all_status.get(h_name, False):
                synergy_groups[sg]["done"] += 1

        sg_pcts = {
            sg: round(counts["done"] / counts["total"], 3)
            for sg, counts in synergy_groups.items()
            if counts["total"] > 0
        }

        habit_score = component_scores.get("habits_mvp")
        item = {
            "pk":            USER_PREFIX + "habit_scores",
            "sk":            "DATE#" + date_str,
            "date":          date_str,
            "scoring_method": "tier_weighted_v1",
            "tier0_done":    t0.get("done",  0),
            "tier0_total":   t0.get("total", 0),
            "tier1_done":    t1.get("done",  0),
            "tier1_total":   t1.get("total", 0),
            "vices_held":    vices.get("held",  0),
            "vices_total":   vices.get("total", 0),
            "computed_at":   datetime.now(timezone.utc).isoformat(),
        }
        if habit_score is not None:
            item["composite_score"] = Decimal(str(habit_score))
        if t0.get("total"):
            item["tier0_pct"] = Decimal(str(round(t0["done"] / t0["total"], 3)))
        if t1.get("total"):
            item["tier1_pct"] = Decimal(str(round(t1["done"] / t1["total"], 3)))
        if missed_t0:
            item["missed_tier0"] = missed_t0
        if vice_streaks:
            item["vice_streaks"] = _deep_dec(vice_streaks)
        if sg_pcts:
            item["synergy_groups"] = _deep_dec(sg_pcts)
        item = {k: v for k, v in item.items() if v is not None}
        # DATA-2: validate_item for habit_scores (Item 3, R12)
        try:
            from ingestion_validator import validate_item as _vi
            _vr = _vi("habit_scores", item, date_str)
            if _vr.should_skip_ddb:
                logger.error("[DATA-2] Skipping habit_scores write for %s: %s", date_str, _vr.errors)
                return
            if _vr.warnings:
                logger.warning("[DATA-2] habit_scores warnings for %s: %s", date_str, _vr.warnings)
        except ImportError:
            pass
        except Exception as ve:
            logger.warning("[DATA-2] habit_scores validate_item failed (proceeding): %s", ve)
        table.put_item(Item=item)
        logger.info(f"Stored habit_scores: {date_str} T0={t0.get('done', 0)}/{t0.get('total', 0)} T1={t1.get('done', 0)}/{t1.get('total', 0)}")
    except Exception as e:
        logger.warning(f"store_habit_scores failed: {e}")


# ==============================================================================
# DATA ASSEMBLY
# ==============================================================================

def get_source_fingerprints(yesterday_str, sources=None):
    """Return dict of source → ingested_at timestamp for the key daily sources.

    Data-aware idempotency pattern
    ──────────────────────────────
    Rather than using a simple 'skip if computed today' guard (which would
    silently miss late-arriving data), this Lambda records a per-source
    ingestion timestamp fingerprint when it first runs.

    On the *next* invocation for the same date, fingerprints_changed() compares
    the stored timestamps against the current DDB records. If any source has a
    newer ingested_at (e.g. a delayed Whoop sync arriving after the 9:40 AM run),
    the Lambda recomputes from scratch — ensuring the Daily Brief always reflects
    the freshest available data without manual reruns.

    Fingerprint fields checked (in priority order):
      webhook_ingested_at  — Health Auto Export webhook writes
      ingested_at          — Scheduled Lambda writes (Strava, Habitify, etc.)
    """
    if sources is None:
        # TB7-16: When adding a new data source (e.g. google_calendar, monarch_money),
        # add it to this list. If a source is omitted, late-arriving data for that
        # source will NOT trigger a recompute — the Daily Brief may silently reflect
        # stale values. Sources should be included only if they materially affect
        # day grade scoring or the AI coaching context.
        sources = ["whoop", "apple_health", "macrofactor", "strava", "habitify", "withings"]
    fps = {}
    for src in sources:
        rec = fetch_date(src, yesterday_str)
        ts  = (rec or {}).get("webhook_ingested_at") or (rec or {}).get("ingested_at")
        if ts:
            fps[src] = str(ts)
    return fps


def fingerprints_changed(stored_fps, current_fps):
    """Return True if any source in current_fps is newer than stored_fps.

    ISO string comparison is safe for UTC timestamps (lexicographic order matches
    chronological order when the format is consistent). A missing stored timestamp
    for a source that now has data also triggers recompute (new source appeared).
    """
    for src, current_ts in current_fps.items():
        stored_ts = stored_fps.get(src)
        if not stored_ts:
            return True          # new source appeared
        if current_ts > stored_ts:  # ISO string comparison works for UTC timestamps
            return True
    return False


def assemble_data(yesterday_str, profile):
    """Fetch all raw data needed for scoring (not HTML rendering).

    Returns (data_dict, hrv_7d_avg, hrv_30d_avg) so caller can store HRV avgs
    directly without re-deriving from the data dict.
    """
    t0_timer = time.time()
    today = datetime.now(timezone.utc).date()

    # Single-day records
    whoop       = fetch_date("whoop",        yesterday_str)
    sleep       = normalize_whoop_sleep(whoop)
    apple       = fetch_date("apple_health", yesterday_str)
    macrofactor = fetch_date("macrofactor",  yesterday_str)
    strava      = fetch_date("strava",       yesterday_str)
    habitify    = fetch_date("habitify",     yesterday_str)
    whoop_today = fetch_date("whoop",        today.isoformat())
    journal_entries = fetch_journal_entries(yesterday_str)

    # Dedup Strava multi-device activities
    if strava and strava.get("activities"):
        orig  = len(strava["activities"])
        strava["activities"] = dedup_activities(strava["activities"])
        deduped = len(strava["activities"])
        if deduped < orig:
            strava["activity_count"] = deduped
            strava["total_moving_time_seconds"] = sum(
                float(a.get("moving_time_seconds") or 0) for a in strava["activities"])
            logger.info(f"Dedup: {orig} → {deduped} Strava activities")

    # HRV averages
    hrv_7d_recs  = fetch_range("whoop", (today - timedelta(days=7)).isoformat(),  yesterday_str)
    hrv_30d_recs = fetch_range("whoop", (today - timedelta(days=30)).isoformat(), yesterday_str)
    hrv_7d_vals  = [float(r["hrv"]) for r in hrv_7d_recs  if "hrv" in r]
    hrv_30d_vals = [float(r["hrv"]) for r in hrv_30d_recs if "hrv" in r]
    hrv_7d_avg   = avg(hrv_7d_vals)
    hrv_30d_avg  = avg(hrv_30d_vals)

    # TSB (60-day Strava)
    strava_60d = fetch_range("strava", (today - timedelta(days=60)).isoformat(), yesterday_str)
    tsb = compute_tsb(strava_60d, today)

    # Sleep debt (7-day cumulative vs profile target)
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    sleep_7d   = [normalize_whoop_sleep(r)
                  for r in fetch_range("whoop", (today - timedelta(days=7)).isoformat(), yesterday_str)]
    sleep_debt_hrs = sum(
        max(0, target_hrs - (safe_float(s, "sleep_duration_hours") or target_hrs))
        for s in sleep_7d
    )

    # Weight (latest + week-ago + avatar fallback)
    withings_7d    = fetch_range("withings", (today - timedelta(days=7)).isoformat(),  yesterday_str)
    withings_14d   = fetch_range("withings", (today - timedelta(days=14)).isoformat(), yesterday_str)
    latest_weight  = next((safe_float(w, "weight_lbs") for w in reversed(withings_7d)
                           if safe_float(w, "weight_lbs")), None)
    target_7d_date = (today - timedelta(days=7)).isoformat()
    week_ago_weight = next(
        (safe_float(w, "weight_lbs") for w in withings_14d
         if w.get("sk", "").replace("DATE#", "") <= target_7d_date and safe_float(w, "weight_lbs")),
        None,
    )
    avatar_weight = latest_weight
    if not avatar_weight:
        avatar_weight = next((safe_float(w, "weight_lbs") for w in reversed(withings_14d)
                              if safe_float(w, "weight_lbs")), None)
    if not avatar_weight:
        withings_30d  = fetch_range("withings", (today - timedelta(days=30)).isoformat(), yesterday_str)
        avatar_weight = next((safe_float(w, "weight_lbs") for w in reversed(withings_30d)
                              if safe_float(w, "weight_lbs")), None)

    # Habitify 7-day (tier-2 habit frequency scoring)
    habitify_7d = fetch_range("habitify", (today - timedelta(days=7)).isoformat(), yesterday_str)

    elapsed = time.time() - t0_timer
    logger.info(
        "Data assembled for %s in %.1fs — sources: %s",
        yesterday_str, elapsed,
        ", ".join(k for k, v in [
            ("whoop", whoop), ("macrofactor", macrofactor), ("apple", apple),
            ("strava", strava), ("habitify", habitify),
        ] if v),
    )

    data = {
        "date":             yesterday_str,
        "whoop":            whoop,
        "whoop_today":      whoop_today,
        "sleep":            sleep,
        "apple":            apple,
        "macrofactor":      macrofactor,
        "strava":           strava,
        "habitify":         habitify,
        "habitify_7d":      habitify_7d,
        "journal_entries":  journal_entries,
        "hrv": {
            "hrv_7d":       hrv_7d_avg,
            "hrv_30d":      hrv_30d_avg,
            "hrv_yesterday": safe_float(whoop, "hrv"),
        },
        "tsb":              tsb,
        "sleep_debt_7d_hrs": round(sleep_debt_hrs, 1),
        "latest_weight":    latest_weight,
        "week_ago_weight":  week_ago_weight,
        "avatar_weight":    avatar_weight,
    }
    return data, hrv_7d_avg, hrv_30d_avg


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

def lambda_handler(event, context):
    t0 = time.time()
    logger.info("Daily Metrics Compute v1.0.0 starting...")

    # Determine target date (default: yesterday; override via event for backfill/testing)
    if event.get("date"):
        yesterday_str = event["date"]
        logger.info(f"Override date: {yesterday_str}")
    else:
        today         = datetime.now(timezone.utc).date()
        yesterday_str = (today - timedelta(days=1)).isoformat()

    # Idempotency — data-aware: recompute if any source has updated since last run
    if not event.get("force"):
        existing = fetch_date("computed_metrics", yesterday_str)
        if existing:
            stored_fps  = existing.get("source_fingerprints", {})
            current_fps = get_source_fingerprints(yesterday_str)
            if stored_fps and not fingerprints_changed(stored_fps, current_fps):
                logger.info(
                    "Already computed for %s (grade=%s) and inputs unchanged — skipping",
                    yesterday_str, existing.get("day_grade_letter", "?"),
                )
                return {
                    "statusCode":       200,
                    "body":             f"Already computed for {yesterday_str} (inputs unchanged)",
                    "day_grade_letter": existing.get("day_grade_letter"),
                    "skipped":          True,
                }
            if not stored_fps:
                reason = "no fingerprint stored (legacy record)"
            else:
                changed = [s for s, ts in current_fps.items()
                           if ts > stored_fps.get(s, "")]
                reason = f"newer data in: {', '.join(changed)}"
            logger.info(f"Recomputing {yesterday_str} — {reason}")

    # ── Sick day check ─────────────────────────────────────────────────────
    # If the target date is flagged as a sick/rest day, store a minimal record:
    #   - day_grade_letter = "sick" (not scored, excluded from trend charts)
    #   - Streak timers preserved from previous day (not broken, not advanced)
    #   - Anomaly alerts will be suppressed separately by anomaly_detector
    try:
        from sick_day_checker import check_sick_day as _check_sick
        _sick_rec = _check_sick(table, USER_ID, yesterday_str)
    except ImportError:
        _sick_rec = None

    if _sick_rec:
        _sick_reason = _sick_rec.get("reason") or "sick day"
        logger.info(f"Sick day flagged for {yesterday_str} ({_sick_reason}) — storing sick record")

        # Load previous day's computed_metrics to preserve streak values
        _dt_y = datetime.strptime(yesterday_str, "%Y-%m-%d")
        _prev_date = (_dt_y - timedelta(days=1)).strftime("%Y-%m-%d")
        _prev_cm = fetch_date("computed_metrics", _prev_date)
        _t0_streak  = int(float(_prev_cm.get("tier0_streak",  0))) if _prev_cm else 0
        _t01_streak = int(float(_prev_cm.get("tier01_streak", 0))) if _prev_cm else 0
        _vice_streaks = {k: int(float(v)) for k, v in _prev_cm.get("vice_streaks", {}).items()} if _prev_cm else {}

        _sick_item = {
            "pk":               USER_PREFIX + "computed_metrics",
            "sk":               "DATE#" + yesterday_str,
            "date":             yesterday_str,
            "day_grade_letter": "sick",
            "sick_day":         True,
            "sick_day_reason":  _sick_reason,
            "readiness_colour": "gray",
            "tier0_streak":     Decimal(str(_t0_streak)),
            "tier01_streak":    Decimal(str(_t01_streak)),
            "sleep_debt_7d_hrs": Decimal("0"),
            "computed_at":      datetime.now(timezone.utc).isoformat(),
            "algo_version":     ALGO_VERSION,
        }
        if _vice_streaks:
            _sick_item["vice_streaks"] = {k: Decimal(str(v)) for k, v in _vice_streaks.items()}

        try:
            table.put_item(Item=_sick_item)
        except Exception as ddb_err:
            logger.error(f"[ERROR] Sick day record write failed: {ddb_err}")
            raise
        logger.info(f"Sick day record stored for {yesterday_str} — streaks preserved (T0={_t0_streak} T01={_t01_streak})")
        return {
            "statusCode":       200,
            "body":             f"Sick day {yesterday_str}: computed_metrics stored with grade='sick'",
            "day_grade_letter": "sick",
            "sick_day":         True,
            "tier0_streak":     _t0_streak,
            "tier01_streak":    _t01_streak,
        }

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found — aborting")
        return {"statusCode": 500, "body": "No profile found"}

    # ── Capture source fingerprints before assembling (same fetches, cached by DDB) ──
    source_fps = get_source_fingerprints(yesterday_str)
    logger.info(f"Source fingerprints: {source_fps}")

    # ── Assemble raw data ──
    data, hrv_7d_avg, hrv_30d_avg = assemble_data(yesterday_str, profile)

    # ── Day grade ──
    day_grade_score, grade, component_scores, component_details = \
        scoring_engine.compute_day_grade(data, profile)
    logger.info(f"Day grade: {day_grade_score} ({grade})")
    for comp, score in component_scores.items():
        if score is not None:
            logger.info(f"  {comp:<20} {score}")

    # ── Readiness ──
    readiness_score, readiness_colour = compute_readiness(data)
    logger.info(f"Readiness: {readiness_score} ({readiness_colour})")

    # ── Habit streaks ──
    streak_data = compute_habit_streaks(profile, yesterday_str)
    logger.info(
        "Streaks: T0=%s T01=%s vices=%s",
        streak_data["tier0_streak"], streak_data["tier01_streak"],
        {k: v for k, v in streak_data["vice_streaks"].items() if v > 0},
    )

    # ── Store all three partitions ──
    store_computed_metrics(
        yesterday_str, day_grade_score, grade, component_scores, component_details,
        readiness_score, readiness_colour, streak_data,
        data.get("tsb"), hrv_7d_avg, hrv_30d_avg,
        data.get("sleep_debt_7d_hrs", 0),
        data.get("latest_weight"), data.get("week_ago_weight"), data.get("avatar_weight"),
        source_fingerprints=source_fps,
    )

    if day_grade_score is not None:
        store_day_grade(
            yesterday_str, day_grade_score, grade, component_scores,
            profile.get("day_grade_weights", {}),
        )

    store_habit_scores(
        yesterday_str, component_details, component_scores,
        streak_data.get("vice_streaks", {}), profile,
    )

    # CLEANUP-1 complete (v3.7.28): write_composite_scores() removed per ADR-025.
    # All composite fields live in computed_metrics. composite_scores partition
    # retained in DynamoDB for historical records but no longer written to.

    elapsed = time.time() - t0
    logger.info("Done in %.1fs", elapsed)

    return {
        "statusCode":       200,
        "body":             f"Daily metrics computed for {yesterday_str}: {day_grade_score} ({grade})",
        "date":             yesterday_str,
        "day_grade_score":  day_grade_score,
        "day_grade_letter": grade,
        "readiness_score":  readiness_score,
        "readiness_colour": readiness_colour,
        "tier0_streak":     streak_data["tier0_streak"],
        "tier01_streak":    streak_data["tier01_streak"],
        "elapsed_seconds":  round(elapsed, 1),
    }
