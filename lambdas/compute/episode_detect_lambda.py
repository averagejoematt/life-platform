"""
Episode Detect Lambda — BENCH-1 (Cut Benchmarking & Regain Firewall).

Scheduled WEEKLY (not nightly — Viktor's cadence call, ADR pending) plus manual
invoke. Reads full `withings` history (+ `strava`/`hevy` for co-variates), runs a
pure-Python turning-point / episode-detection pass, and writes two thin derived
computed sources to the existing single table:

DynamoDB partitions written (read via query_source(...) exactly like computed_metrics):
  1. SOURCE#weight_episodes    — one item per detected loss/regain episode
  2. SOURCE#training_reference — singleton: proven by-band prescription + proven curve

Keying convention (matches computed_metrics — PK USER#{user}#SOURCE#{source}, SK DATE#...):
  - weight_episodes:    SK = "DATE#{end_date}"   (trough date for loss, peak for regain)
  - training_reference: SK = "DATE#{derived_date}" — singleton-in-effect; readers take
    the newest in-range record, exactly like computed_metrics' newest-record read.

Phase (ADR-058): these are CROSS-PHASE reference data (14-year history, not
experiment-scoped) — written WITHOUT a `phase` attribute so query_source's default
filter (`attribute_not_exists(#phase)`) returns them and a reset never wipes them.

Reference data: no TTL. Omar's note: thin derived views over withings/strava/hevy —
do NOT duplicate raw activity rows.

BENCH-1.1 — data model + record builders (this commit).
BENCH-1.2 — detection algorithm + handler + CDK wiring (next commit).
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("episode-detect")
except ImportError:
    logger = logging.getLogger("episode-detect")
    logger.setLevel(logging.INFO)

# ── Configuration ──
_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# Source names — used verbatim by query_source() in the MCP get_benchmark tool.
WEIGHT_EPISODES_SOURCE = "weight_episodes"
TRAINING_REFERENCE_SOURCE = "training_reference"

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


# ==============================================================================
# SERIALISATION (Decimal for DynamoDB — boto3 rejects float)
# ==============================================================================


def _to_dec(val):
    """float/int → Decimal (4dp), passing through None."""
    if val is None:
        return None
    return Decimal(str(round(float(val), 4)))


def _deep_dec(obj):
    """Recursively convert floats/ints to Decimal; preserve bool and str; map keys → str."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, list):
        return [_deep_dec(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): _deep_dec(v) for k, v in obj.items()}
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, int):
        return Decimal(str(obj))
    return obj


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# DATA MODEL — record builders (BENCH-1.1)
# ==============================================================================


def build_episode_record(ep: dict) -> dict:
    """Build a `weight_episodes` DynamoDB item from a plain-Python episode dict.

    Keyed SK="DATE#{end_date}" so query_source returns episodes in date order. No
    `phase` attribute → cross-phase reference data (survives resets, passes the
    ADR-058 default filter). loss-only fields (post_trough_8wk / regain_180d_lb /
    outcome) are written only when present.
    """
    item = {
        "pk": USER_PREFIX + WEIGHT_EPISODES_SOURCE,
        "sk": "DATE#" + ep["end_date"],
        "episode_id": ep["episode_id"],
        "type": ep["type"],
        "start_date": ep["start_date"],
        "end_date": ep["end_date"],
        "w_start": _to_dec(ep["w_start"]),
        "w_end": _to_dec(ep["w_end"]),
        "magnitude_lb": _to_dec(ep["magnitude_lb"]),
        "duration_wk": _to_dec(ep["duration_wk"]),
        "rate_lb_wk": _to_dec(ep["rate_lb_wk"]),
        "peak_rate_lb_wk": _to_dec(ep.get("peak_rate_lb_wk")),
        "covariates_during": _deep_dec(ep.get("covariates_during") or {}),
        "covariates_reliable": bool(ep.get("covariates_reliable", False)),
        "confidence": ep.get("confidence", "low"),
        "computed_at": _now_iso(),
    }
    # Loss-only fields
    if ep.get("post_trough_8wk") is not None:
        item["post_trough_8wk"] = _deep_dec(ep["post_trough_8wk"])
    if ep.get("regain_180d_lb") is not None:
        item["regain_180d_lb"] = _to_dec(ep["regain_180d_lb"])
    if ep.get("outcome") is not None:
        item["outcome"] = ep["outcome"]
    return {k: v for k, v in item.items() if v is not None}


# ==============================================================================
# REFERENCE ALGORITHM (BENCH-1.2) — pure Python, no scipy. Ported verbatim from
# the workorder so the synthetic + datadrops fixture tests can pin it offline.
# Inputs are normalized lists so the SAME functions run over DDB (handler) and the
# datadrop CSVs (the real-validation test).
# ==============================================================================

from datetime import (
    date as _date,  # noqa: E402
    timedelta as _timedelta,  # noqa: E402
)

MIN_SWING_LB = 12.0
MIN_EPISODE_LB = 15.0
SMOOTH_WINDOW_DAYS = 21
OUTCOME_LOOKAHEAD_DAYS = 200
POST_TROUGH_DAYS = 56
COVARIATE_RELIABLE_FROM = "2020-01-01"
REFERENCE_WINDOW = ("2024-09-05", "2025-04-30")


def _d(s: str) -> _date:
    return _date.fromisoformat(s[:10])


def smooth_weight(weigh_ins: list) -> tuple:
    """weigh_ins = [(date_str, weight_lb), ...]. Daily-resample + linear-interpolate +
    21-day centered rolling mean. Returns (idx_dates[str], smoothed_vals[float])."""
    by_day = {}
    for ds, w in weigh_ins:
        if w is None:
            continue
        by_day[_d(ds)] = float(w)  # last weigh-in of a day wins
    if len(by_day) < 2:
        return [], []
    days = sorted(by_day)
    start, end = days[0], days[-1]
    # Daily series with linear interpolation between known points.
    idx, raw = [], []
    known = days
    ki = 0
    cur = start
    while cur <= end:
        if cur in by_day:
            raw.append(by_day[cur])
            while ki < len(known) and known[ki] <= cur:
                ki += 1
        else:
            prev_day = known[ki - 1]
            next_day = known[ki]
            span = (next_day - prev_day).days
            frac = (cur - prev_day).days / span
            raw.append(by_day[prev_day] + frac * (by_day[next_day] - by_day[prev_day]))
        idx.append(cur.isoformat())
        cur += _timedelta(days=1)
    # 21-day centered rolling mean.
    half = SMOOTH_WINDOW_DAYS // 2
    n = len(raw)
    smoothed = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        window = raw[lo:hi]
        smoothed.append(sum(window) / len(window))
    return idx, smoothed


def turning_points(vals, idx, min_swing=MIN_SWING_LB):
    """Swing/ZigZag turning-point detector.

    NB: the workorder pasted a single-`ext_v` variant that is provably broken at the
    `direction=0` start — its first block pulls ext_v to the current value on every
    tick, so an extreme is never locked and ZERO pivots are ever recorded (verified:
    0 episodes on the real 14-year series). This is the corrected standard ZigZag —
    track the running high AND low since the last pivot; confirm a Peak when price
    retraces `min_swing` off the running high (then hunt a trough from there), and vice
    versa. Reproduces the workorder's validated values exactly (16 loss / 15 regain;
    reference cut 116.4 lb / 33.6 wk over 2024-09→2025-04)."""
    tps = []
    hi = lo = vals[0]
    hi_i = lo_i = 0
    direction = 0  # 0 unknown, +1 up (seeking a peak), -1 down (seeking a trough)
    for i in range(1, len(vals)):
        v = vals[i]
        if v > hi:
            hi, hi_i = v, i
        if v < lo:
            lo, lo_i = v, i
        if direction >= 0 and v <= hi - min_swing:
            tps.append((idx[hi_i], "P", hi))
            direction = -1
            lo, lo_i = v, i  # reset the trough tracker from the confirmed peak
        elif direction <= 0 and v >= lo + min_swing:
            tps.append((idx[lo_i], "T", lo))
            direction = 1
            hi, hi_i = v, i  # reset the peak tracker from the confirmed trough
    return tps


def _peak_weekly_rate(idx, vals, start_date, end_date, sign):
    """Max single-week |Δ| in the smoothed series over [start,end] (lb/wk), signed by
    direction (sign=+1 loss, -1 regain). Returns lb/wk magnitude."""
    pos = {d: i for i, d in enumerate(idx)}
    si, ei = pos.get(start_date), pos.get(end_date)
    if si is None or ei is None or ei - si < 7:
        return None
    peak = 0.0
    for i in range(si, ei - 6):
        delta = (vals[i] - vals[i + 7]) * sign  # loss → positive when weight falling
        if delta > peak:
            peak = delta
    return round(peak, 3)


def detect_episodes(idx, vals, min_episode=MIN_EPISODE_LB):
    """Loss = P→next T with (w_start - w_end) >= min_episode. Regain = T→next P >= min_episode.
    Returns episode dicts WITHOUT covariates/outcome (added by the handler/caller)."""
    tps = turning_points(vals, idx)
    episodes = []
    for a, b in zip(tps, tps[1:]):
        (da, ka, va), (db, kb, vb) = a, b
        if ka == "P" and kb == "T" and (va - vb) >= min_episode:
            etype, w_start, w_end = "loss", va, vb
        elif ka == "T" and kb == "P" and (vb - va) >= min_episode:
            etype, w_start, w_end = "regain", va, vb
        else:
            continue
        dur_days = max(1, (_d(db) - _d(da)).days)
        dur_wk = dur_days / 7.0
        magnitude = abs(w_end - w_start)
        episodes.append(
            {
                "episode_id": f"{da}_{etype}",
                "type": etype,
                "start_date": da,
                "end_date": db,
                "w_start": round(w_start, 2),
                "w_end": round(w_end, 2),
                "magnitude_lb": round(magnitude, 2),
                "duration_wk": round(dur_wk, 2),
                "rate_lb_wk": round(magnitude / dur_wk, 3) if dur_wk else None,
                "peak_rate_lb_wk": _peak_weekly_rate(idx, vals, da, db, 1 if etype == "loss" else -1),
            }
        )
    return episodes


def classify_loss_outcome(idx, vals, trough_date, w_end, magnitude):
    """regain_180d = max(smoothed[trough .. trough+200d]) - w_end; held if < magnitude/3."""
    pos = {d: i for i, d in enumerate(idx)}
    ti = pos.get(trough_date)
    if ti is None:
        return None, None
    end_d = _d(trough_date) + _timedelta(days=OUTCOME_LOOKAHEAD_DAYS)
    window = [vals[i] for i, dd in enumerate(idx) if i >= ti and _d(dd) <= end_d]
    if not window:
        return None, None
    regain_180d = max(window) - w_end
    outcome = "held" if regain_180d < (magnitude / 3.0) else "reversed"
    return round(regain_180d, 2), outcome


def classify_activity(sport_type: str):
    """Strava sport_type / CSV Activity Type → normalized kind, or None to ignore."""
    s = (sport_type or "").lower().replace(" ", "").replace("_", "")
    if s in ("walk", "hike", "walking", "hiking"):
        return "walk"
    if "run" in s:
        return "run"
    if "weighttraining" in s or s in ("workout", "weightlifting"):
        return "lift"
    return None


def weekly_covariates(activities: list, start_date: str, end_date: str, lift_sets: float = None) -> dict:
    """activities = [{date, kind, hours}]; count per kind over [start,end], normalize per
    week by window_days/7. lift_sets is total Hevy sets in-window (optional)."""
    days = max(1, (_d(end_date) - _d(start_date)).days)
    weeks = days / 7.0
    walks = walk_hr = runs = lifts = 0.0
    for a in activities:
        if not (start_date <= a["date"][:10] <= end_date):
            continue
        k = a.get("kind")
        if k == "walk":
            walks += 1
            walk_hr += float(a.get("hours") or 0.0)
        elif k == "run":
            runs += 1
        elif k == "lift":
            lifts += 1
    cov = {
        "walks_wk": round(walks / weeks, 2),
        "walk_hr_wk": round(walk_hr / weeks, 2),
        "runs_wk": round(runs / weeks, 2),
        "lift_sessions_wk": round(lifts / weeks, 2),
    }
    if lift_sets is not None:
        cov["lift_sets_wk"] = round(float(lift_sets) / weeks, 2)
    return cov


def enrich_episodes(idx, vals, episodes, activities, hevy_sets_by_date: dict) -> list:
    """Attach covariates_during / covariates_reliable, and (loss only) post_trough_8wk +
    regain_180d_lb + outcome. Pure — operates on already-normalized inputs."""
    out = []
    for ep in episodes:
        sets_in = sum(v for d, v in hevy_sets_by_date.items() if ep["start_date"] <= d[:10] <= ep["end_date"])
        ep = dict(ep)
        ep["covariates_during"] = weekly_covariates(activities, ep["start_date"], ep["end_date"], lift_sets=sets_in or None)
        ep["covariates_reliable"] = ep["start_date"] >= COVARIATE_RELIABLE_FROM
        ep["confidence"] = "low"
        if ep["type"] == "loss":
            trough = ep["end_date"]
            pt_end = (_d(trough) + _timedelta(days=POST_TROUGH_DAYS)).isoformat()
            pt = weekly_covariates(activities, trough, pt_end)
            ep["post_trough_8wk"] = {"walks_wk": pt["walks_wk"], "walk_hr_wk": pt["walk_hr_wk"]}
            regain, outcome = classify_loss_outcome(idx, vals, trough, ep["w_end"], ep["magnitude_lb"])
            ep["regain_180d_lb"] = regain
            ep["outcome"] = outcome
        out.append(ep)
    return out


def build_reference(idx, vals, episodes, activities, hevy_sets_by_date: dict) -> dict:
    """Build the training_reference singleton: by-band proven volumes (averaged over the
    reference loss window) + the proven trajectory curve. Cross-phase, confidence low."""
    rstart, rend = REFERENCE_WINDOW
    pos = {d: i for i, d in enumerate(idx)}
    # By-band covariates over the reference window (10-lb bands).
    bands = {}
    band_acts = {}
    for i, dd in enumerate(idx):
        if not (rstart <= dd <= rend):
            continue
        band = f"{int(vals[i] // 10) * 10}-{int(vals[i] // 10) * 10 + 9}"
        band_acts.setdefault(band, []).append(dd)
    for band, dlist in band_acts.items():
        d0, d1 = min(dlist), max(dlist)
        bands[band] = weekly_covariates(activities, d0, d1)
    # Proven curve: weekly samples along the reference window.
    si, ei = pos.get(rstart), pos.get(rend)
    proven_curve = []
    if si is not None and ei is not None and ei > si:
        w0 = vals[si]
        for i in range(si, ei + 1, 7):
            proven_curve.append(
                {
                    "weight": round(vals[i], 1),
                    "days_from_start": i - si,
                    "cum_lost": round(w0 - vals[i], 1),
                    "walks_wk": weekly_covariates(activities, idx[max(si, i - 7)], idx[i])["walks_wk"],
                }
            )
    n_cov = sum(1 for e in episodes if e.get("covariates_reliable") or (e["start_date"] >= COVARIATE_RELIABLE_FROM))
    return {
        "bands": bands,
        "proven_curve": proven_curve,
        "source_window": f"{rstart}..{rend}",
        "derived_at": _now_iso(),
        "confidence": "low",
        "n_episodes_with_covariates": n_cov,
    }


def build_training_reference_record(ref: dict) -> dict:
    """Build the singleton `training_reference` DynamoDB item from a plain-Python dict.

    Keyed SK="DATE#{derived_date}"; readers take the newest in-range record (the
    computed_metrics read pattern). No `phase` attribute → cross-phase reference data.
    """
    derived_at = ref["derived_at"]
    derived_date = derived_at[:10]
    item = {
        "pk": USER_PREFIX + TRAINING_REFERENCE_SOURCE,
        "sk": "DATE#" + derived_date,
        "bands": _deep_dec(ref["bands"]),
        "proven_curve": _deep_dec(ref["proven_curve"]),
        "source_window": ref["source_window"],
        "derived_at": derived_at,
        "confidence": ref.get("confidence", "low"),
        "n_episodes_with_covariates": _to_dec(ref.get("n_episodes_with_covariates", 0)),
    }
    return {k: v for k, v in item.items() if v is not None}


# ==============================================================================
# SOURCE READS + HANDLER (BENCH-1.2)
# ==============================================================================


def _read_all_history(source: str, start: str = "2010-01-01", end: str = None) -> list:
    """Paginate a source's full DATE# range. NOTE: deliberately does NOT apply the
    ADR-058 phase filter — episode detection spans 14 years, so it MUST include
    pre-genesis (phase=pilot) records, unlike the nightly compute path."""
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": USER_PREFIX + source, ":s": "DATE#" + start, ":e": "DATE#" + end + "~"},
    }
    while True:
        r = table.query(**kwargs)
        items.extend(r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return items


def _sk_date(item: dict) -> str:
    return item.get("date") or str(item.get("sk", "")).replace("DATE#", "")[:10]


def _f(v):
    return float(v) if v is not None else None


def _load_inputs() -> tuple:
    """Adapt DDB withings/strava/hevy → normalized algorithm inputs.

    Documented field assumptions (SCHEMA.md): withings.weight_lbs; strava per-activity
    sport_type + moving_time_seconds (falls back to a daily record's own sport_type, or
    an embedded `activities` list); hevy set_count/total_sets per workout. Defensive —
    Matthew validates the real numbers via the datadrops fixture + the backfill smoke."""
    weigh_ins = []
    for it in _read_all_history("withings"):
        w = _f(it.get("weight_lbs"))
        if w:
            weigh_ins.append((_sk_date(it), w))

    activities = []
    for it in _read_all_history("strava"):
        d = _sk_date(it)
        rows = it.get("activities") if isinstance(it.get("activities"), list) else [it]
        for a in rows:
            kind = classify_activity(a.get("sport_type") or a.get("type"))
            if kind:
                activities.append({"date": d, "kind": kind, "hours": (_f(a.get("moving_time_seconds")) or 0.0) / 3600.0})

    hevy_sets_by_date = {}
    for it in _read_all_history("hevy"):
        d = _sk_date(it)
        sets = _f(it.get("set_count")) or _f(it.get("total_sets")) or 0.0
        if sets:
            hevy_sets_by_date[d] = hevy_sets_by_date.get(d, 0.0) + sets
    return weigh_ins, activities, hevy_sets_by_date


def lambda_handler(event, context):
    """Weekly (Sun) + manual. Detects weight episodes + writes the training reference."""
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        weigh_ins, activities, hevy_sets_by_date = _load_inputs()
        idx, vals = smooth_weight(weigh_ins)
        if not idx:
            logger.warning("episode-detect: insufficient weight history (%d weigh-ins)", len(weigh_ins))
            return {"statusCode": 200, "body": "insufficient weight history", "weigh_ins": len(weigh_ins)}

        episodes = enrich_episodes(idx, vals, detect_episodes(idx, vals), activities, hevy_sets_by_date)
        for ep in episodes:
            table.put_item(Item=build_episode_record(ep))

        ref = build_reference(idx, vals, episodes, activities, hevy_sets_by_date)
        table.put_item(Item=build_training_reference_record(ref))

        n_loss = sum(1 for e in episodes if e["type"] == "loss")
        n_held = sum(1 for e in episodes if e.get("outcome") == "held")
        logger.info(
            "episode-detect: wrote %d episodes (%d loss, %d regain), %d held; reference bands=%d",
            len(episodes),
            n_loss,
            len(episodes) - n_loss,
            n_held,
            len(ref["bands"]),
        )
        return {
            "statusCode": 200,
            "episodes": len(episodes),
            "loss": n_loss,
            "regain": len(episodes) - n_loss,
            "held": n_held,
        }
    except Exception as e:
        logger.error("episode-detect FAILED: %s", e)
        raise
