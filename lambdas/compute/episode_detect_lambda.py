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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

try:
    from common.platform_logger import get_logger

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

# #3709 — corrupt-set guards. Six sets in the live corpus fail these
# (one at weight_kg=5443, five at reps=200); a single one distorts a weekly
# tonnage aggregate by more than an order of magnitude.
CORRUPT_SET_MAX_KG = 300.0
CORRUPT_SET_MAX_REPS = 100.0
LB_PER_KG = 2.20462

# A band whose dwell is shorter than this cannot carry a weekly rate honestly:
# dividing by window_days/7 on a 6-day window extrapolates, it does not measure.
# The 300-309 band — the one nearest Matthew's current weight — spans 6 days.
MIN_BAND_DWELL_DAYS = 14

# ...and a band standing on one or two weigh-ins is not evidence either.
MIN_BAND_WEIGHINS = 3

# resolve_band widens by this many 10-lb bands before giving up.
MAX_BAND_WIDENING = 2

# A weigh-in's band is carried forward at most this many days. Beyond it the
# weight is stale and the days belong to no band rather than to a guess.
BAND_CARRY_DAYS = 14


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


def weekly_covariates(
    activities: list,
    start_date: str,
    end_date: str,
    lift_sets: float = None,
    hevy_by_date: dict | None = None,
    whoop_hr_by_date: dict | None = None,
    day_set: set | None = None,
) -> dict:
    """activities = [{date, kind, hours, miles, hr}]; count per kind over [start,end],
    normalize per week by window_days/7. lift_sets is total Hevy sets in-window.

    #3709 adds the covariates a prescription is actually written in — miles,
    walking heart rate, session heart rate, sets and tonnage — plus `n_days`,
    the dwell the rates were divided by. A rate without its window is not a
    measurement (ADR-105): the band nearest Matthew's current weight rests on
    6 days, and nothing in the v1 record said so.
    """
    # #3709 — two modes, and the difference is load-bearing.
    #   range mode   (day_set=None): a contiguous window, used for episodes and
    #                the proven curve where the period genuinely is contiguous.
    #   day-set mode (day_set given): the exact days that qualify. A weight band
    #                is NOT contiguous — he crosses 250-259 on the way down and
    #                again on the way up, years apart. Taking min..max of those
    #                dates would make the "window" his whole history and divide
    #                14 years of activity by 14 years of weeks, which produces a
    #                lifetime average wearing a band's name. Every band must be
    #                summed over the days he was actually in it.
    if day_set is not None:
        _member = day_set.__contains__
        days = max(1, len(day_set))
    else:
        _member = lambda d: start_date <= d <= end_date  # noqa: E731
        days = max(1, (_d(end_date) - _d(start_date)).days)
    weeks = days / 7.0
    walks = walk_hr = runs = lifts = walk_mi = 0.0
    walk_bpm: list = []
    for a in activities:
        if not _member(a["date"][:10]):
            continue
        k = a.get("kind")
        if k == "walk":
            walks += 1
            walk_hr += float(a.get("hours") or 0.0)
            walk_mi += float(a.get("miles") or 0.0)
            if a.get("hr"):
                walk_bpm.append(float(a["hr"]))
        elif k == "run":
            runs += 1
        elif k == "lift":
            lifts += 1

    sets = tonnage = 0.0
    top_kg: dict = {}
    for d, bucket in (hevy_by_date or {}).items():
        if not _member(d[:10]):
            continue
        sets += bucket.get("sets", 0.0)
        tonnage += bucket.get("tonnage_lb", 0.0)
        for name, kg in (bucket.get("top_kg") or {}).items():
            if kg > top_kg.get(name, 0.0):
                top_kg[name] = kg

    sess_bpm = [hr for d, lst in (whoop_hr_by_date or {}).items() if _member(d[:10]) for hr in lst]

    cov = {
        "walks_wk": round(walks / weeks, 2),
        "walk_hr_wk": round(walk_hr / weeks, 2),
        "walk_mi_wk": round(walk_mi / weeks, 2),
        "runs_wk": round(runs / weeks, 2),
        "lift_sessions_wk": round(lifts / weeks, 2),
        "sets_wk": round(sets / weeks, 1),
        "tonnage_lb_wk": round(tonnage / weeks),
        "n_days": days,
        # Absence is reported as absence, never as 0 bpm (ADR-104).
        "walk_bpm": round(sum(walk_bpm) / len(walk_bpm)) if walk_bpm else None,
        "n_walk_bpm": len(walk_bpm),
        "sess_bpm": round(sum(sess_bpm) / len(sess_bpm)) if sess_bpm else None,
        "n_sess_bpm": len(sess_bpm),
    }
    if top_kg:
        cov["top_kg_by_movement"] = {k: round(v, 1) for k, v in sorted(top_kg.items(), key=lambda x: -x[1])[:40]}
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


def _n_eff_for_days(day_set: set, activities: list) -> float:
    """Effective sample size of the daily activity-hours series over `day_set`.

    Uses the one sanctioned implementation (`common.stats_core`), per ADR-105 —
    a parallel copy would need its own ADR. Fails soft to the raw day count so a
    stats import problem degrades the tier rather than the whole weekly run.
    """
    try:
        from common.stats_core import effective_sample_size

        by_day: dict = {}
        for a in activities:
            d = a["date"][:10]
            if d in day_set:
                by_day[d] = by_day.get(d, 0.0) + float(a.get("hours") or 0.0)
        # Autocorrelation is only meaningful WITHIN a contiguous visit. A band
        # is visited repeatedly across years, and running lag-1 over the sorted
        # union would treat the jump from 2020 to 2026 as a one-day lag — which
        # both invents autocorrelation that is not there and hides the fact
        # that separate visits ARE more independent than consecutive days.
        # So: correct each contiguous run on its own, then sum.
        days = sorted(day_set)
        runs: list[list[str]] = []
        for d in days:
            if runs and (_d(d) - _d(runs[-1][-1])).days == 1:
                runs[-1].append(d)
            else:
                runs.append([d])
        total = 0.0
        for run in runs:
            series = [by_day.get(d, 0.0) for d in run]
            total += float(len(series)) if len(series) < 3 else float(effective_sample_size(series))
        return round(min(total, float(len(days))), 1)
    except Exception as e:  # noqa: BLE001 - never fail the weekly run on a stats import
        logger.warning("n_eff unavailable, falling back to raw dwell: %s", e)
        return float(len(day_set))


def build_reference(
    idx,
    vals,
    episodes,
    activities,
    hevy_sets_by_date: dict,
    hevy_by_date: dict | None = None,
    whoop_hr_by_date: dict | None = None,
) -> dict:
    """Build the training_reference singleton: by-band volumes + the proven curve.
    Cross-phase, confidence low.

    #3709 — bands are built over ALL weight history, not only the reference
    window. v1 bucketed the 2024-25 window alone, so the table stopped at
    300-309 and a lookup at 327 lb (above his entire 14-year record) returned
    nothing at all rather than "the nearest period is 22 lb lighter". Every
    band now carries `n_days` and `n_weighins` so a caller can see what the
    rate rests on.
    """
    rstart, rend = REFERENCE_WINDOW
    pos = {d: i for i, d in enumerate(idx)}

    def _cov(d0, d1, day_set=None):
        return weekly_covariates(
            activities,
            d0,
            d1,
            hevy_by_date=hevy_by_date,
            whoop_hr_by_date=whoop_hr_by_date,
            day_set=day_set,
        )

    # By-band covariates over ALL history (10-lb bands), summed over the days
    # he was ACTUALLY in each band. Every calendar day inherits the band of its
    # most recent weigh-in, carried at most BAND_CARRY_DAYS forward so a gap in
    # weighing does not attribute months of activity to a stale weight.
    bands = {}
    band_days: dict[str, set] = {}
    band_weighin_dates: dict[str, set] = {}
    band_span: dict[str, list] = {}
    for i, dd in enumerate(idx):
        band = f"{int(vals[i] // 10) * 10}-{int(vals[i] // 10) * 10 + 9}"
        band_weighin_dates.setdefault(band, set()).add(dd)
        span = band_span.setdefault(band, [dd, dd])
        span[0], span[1] = min(span[0], dd), max(span[1], dd)
        nxt = idx[i + 1] if i + 1 < len(idx) else None
        carry = min((_d(nxt) - _d(dd)).days, BAND_CARRY_DAYS) if nxt else 1
        day = _d(dd)
        for k in range(max(1, carry)):
            band_days.setdefault(band, set()).add((day + timedelta(days=k)).isoformat())

    def _finish(band, dset, restrict=None):
        d0, d1 = band_span[band]
        use = dset if restrict is None else (dset & restrict)
        if not use:
            return None
        cov = _cov(min(use), max(use), day_set=use)
        # Counted INSIDE the restriction — a proven band must not borrow the
        # evidence of the all-history band it shares a key with.
        cov["n_weighins"] = len(band_weighin_dates.get(band, set()) & use)
        # #3709 — autocorrelation-corrected evidence. Consecutive days of
        # walking are heavily autocorrelated, so a raw 24-day dwell is nowhere
        # near 24 independent observations (ADR-105's statistical floor). The
        # consumer's evidence tiers apply their floors to THIS, not to n_days.
        cov["n_eff"] = _n_eff_for_days(use, activities)
        cov["window"] = f"{min(use)}..{max(use)}"
        # A dwell or an n under the floor cannot carry a weekly rate honestly —
        # the rates stay, but the caller is told they are extrapolated (ADR-105).
        thin = cov["n_days"] < MIN_BAND_DWELL_DAYS or cov["n_weighins"] < MIN_BAND_WEIGHINS
        cov["confidence"] = "low" if thin else "moderate"
        cov["in_reference_window"] = bool(rstart <= d0 <= rend or rstart <= d1 <= rend)
        return cov

    for band, dset in band_days.items():
        cov = _finish(band, dset)
        if cov:
            bands[band] = cov

    # #3709 — the SECOND table, and the one a prescription should cite.
    # `bands` above is descriptive: it answers "what has he typically done at
    # this weight", and at his current weight the answer is drawn from the very
    # weeks he is trying to escape — prescribing from it would hand back his own
    # inactivity as a target. `proven_bands` restricts the same computation to
    # days inside a detected LOSS episode: what he was doing at this weight
    # WHEN IT WAS WORKING. Above the top proven band there is no such period,
    # and resolve_band is required to say so rather than fall back silently.
    losing_days: set = set()
    for ep in episodes:
        if ep.get("type") != "loss":
            continue
        d0, d1 = ep.get("start_date"), ep.get("end_date")
        if not (d0 and d1):
            continue
        day, end = _d(d0), _d(d1)
        while day <= end:
            losing_days.add(day.isoformat())
            day += timedelta(days=1)
    proven_bands = {}
    for band, dset in band_days.items():
        cov = _finish(band, dset, restrict=losing_days)
        if cov:
            proven_bands[band] = cov
    # Proven curve: weekly samples along the reference window.
    # #3711 — the boundary need not BE a weigh-in day. `pos.get(rstart)` is an
    # exact-match lookup, so a window edge that falls on a day he did not weigh
    # yields si=None and a SILENTLY EMPTY curve — no error, just no proven
    # trajectory for anything downstream to compare against. Snap to the nearest
    # index inside the window instead.
    si = pos.get(rstart)
    if si is None:
        si = next((i for i, d in enumerate(idx) if d >= rstart), None)
    ei = pos.get(rend)
    if ei is None:
        ei = next((i for i in range(len(idx) - 1, -1, -1) if idx[i] <= rend), None)
    proven_curve = []
    if si is not None and ei is not None and ei > si:
        w0 = vals[si]
        for i in range(si, ei + 1, 7):
            proven_curve.append(
                {
                    "weight": round(vals[i], 1),
                    "days_from_start": i - si,
                    "cum_lost": round(w0 - vals[i], 1),
                    "walks_wk": _cov(idx[max(si, i - 7)], idx[i])["walks_wk"],
                }
            )
    n_cov = sum(1 for e in episodes if e.get("covariates_reliable") or (e["start_date"] >= COVARIATE_RELIABLE_FROM))
    return {
        # #3710 — consumers MUST be able to tell a v1 record (no proven table,
        # no per-band n) from a v2 record that genuinely found no comparable
        # period. Without this the prescription view reports "nothing to
        # prescribe from" for a stale reference, which reads as a finding about
        # his history when it is a deploy problem.
        "reference_schema": 2,
        "bands": bands,
        "proven_bands": proven_bands,
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
    end = end or pacific_today()
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
                activities.append(
                    {
                        "date": d,
                        "kind": kind,
                        "hours": (_f(a.get("moving_time_seconds")) or 0.0) / 3600.0,
                        # #3709 — miles and heart rate are what a prescription is
                        # actually written in. `has_heartrate` is absent on older
                        # rows, so we key off the value itself.
                        "miles": _f(a.get("distance_miles")) or 0.0,
                        "hr": _f(a.get("average_heartrate")),
                    }
                )

    hevy_sets_by_date: dict[str, float] = {}
    hevy_by_date: dict[str, dict] = {}
    for it in _read_all_history("hevy"):
        d = _sk_date(it)
        sets = _f(it.get("set_count")) or _f(it.get("total_sets")) or 0.0
        if sets:
            hevy_sets_by_date[d] = hevy_sets_by_date.get(d, 0.0) + sets
        bucket = hevy_by_date.setdefault(d, {"sets": 0.0, "tonnage_lb": 0.0, "top_kg": {}})
        for ex in it.get("exercises") or []:
            name = ex.get("name") or ex.get("title")
            for st in ex.get("sets") or []:
                kg, reps = _f(st.get("weight_kg")) or 0.0, _f(st.get("reps")) or 0.0
                if kg > CORRUPT_SET_MAX_KG or reps > CORRUPT_SET_MAX_REPS:
                    continue  # #3709 — 6 such sets exist; one distorts a weekly aggregate
                bucket["sets"] += 1
                bucket["tonnage_lb"] += kg * LB_PER_KG * reps
                if name and kg > bucket["top_kg"].get(name, 0.0):
                    bucket["top_kg"][name] = kg

    # #3709 — session heart rate. Whoop `sport_name` is largely unmapped
    # (Sport_128 / Sport_242 / None), so Whoop is used ONLY for session-level HR;
    # walk-specific HR comes from Strava, where the sport type is trustworthy.
    # Whoop zone minutes are deliberately NOT read — present on 2,167 of 4,822
    # records and zero on every one (verified 2026-09-08).
    whoop_hr_by_date: dict[str, list] = {}
    for it in _read_all_history("whoop"):
        hr = _f(it.get("average_heart_rate"))
        if hr:
            whoop_hr_by_date.setdefault(_sk_date(it), []).append(hr)

    return weigh_ins, activities, hevy_sets_by_date, hevy_by_date, whoop_hr_by_date


def lambda_handler(event, context):
    """Weekly (Sun) + manual. Detects weight episodes + writes the training reference."""
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        weigh_ins, activities, hevy_sets_by_date, hevy_by_date, whoop_hr_by_date = _load_inputs()
        idx, vals = smooth_weight(weigh_ins)
        if not idx:
            logger.warning("episode-detect: insufficient weight history (%d weigh-ins)", len(weigh_ins))
            return {"statusCode": 200, "body": "insufficient weight history", "weigh_ins": len(weigh_ins)}

        episodes = enrich_episodes(idx, vals, detect_episodes(idx, vals), activities, hevy_sets_by_date)
        for ep in episodes:
            table.put_item(Item=build_episode_record(ep))

        ref = build_reference(idx, vals, episodes, activities, hevy_sets_by_date, hevy_by_date, whoop_hr_by_date)
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
