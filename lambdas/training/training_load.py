"""One TSS-like training-load scale for every Banister consumer (#490 / C-5, C-6, M-3).

Before this module, daily loads were raw Strava kilojoules with a 25 kJ/min Hevy
duration stand-in — ~1,500 kJ/h — while every form band downstream (readiness
``60 + tsb*2``, character ``_in_range_score(-10, 25)``, MCP ``70 + tsb*2.5``) assumed
the classic TSS scale. The TSB component sat permanently saturated and eight rest
days read as maximal fatigue. Walks contributed zero load because Strava only
populates ``kilojoules`` for power-device activities (C-6).

The unit here is a **TSS-like point: 100 ≈ one hour at functional threshold.**
Everything is a proxy — there is no power meter or lab FTP — and the basis dict
says so (``unit``, ``confidence``, ``proxy_share``); surfaces that render TSB are
expected to surface that provenance (M-3).

Per-activity model, first match wins (#4075 moved HR ahead of every duration proxy):
  1. Real kilojoules present  → ``kJ / KJ_PER_TSS_POINT`` (~200 W FTP ⇒ 720 kJ/h
     at threshold ⇒ 100 TSS ⇒ 7.2 kJ per point).                 basis "kj"
  2. Average HR present       → Banister TRIMP measured ABOVE the owner's Zone-1
     ceiling, normalised so 1 h at ``THRESHOLD_HR`` = 100 (see ``hr_load``).
     Any sport — a walk with HR is scored by its HR, not by its sport. basis "hr"
  3. Walk-like sport, no HR   → ``WALK_TSS_PER_HOUR`` × moving hours.   basis "duration"
  4. Otherwise, no HR         → ``DEFAULT_CARDIO_TSS_PER_HOUR`` × moving hours. basis "duration"

**Why HR first (#4075).** Before #4075 the walk branch ran BEFORE the HR branch, so a
walk carrying a measured average HR of 113 bpm still scored the flat 25 points/h, and
the HR branch clamped intensity at IF ≥ 0.4, so no HR-bearing activity could ever
score below 16 points/h. Zone-1 walking — which the owner's programme prescribes
every day as recovery locomotion — read as training stress, and TSB sat at −75 over a
fortnight of easy walks and lifting. Recovery-intensity work now contributes ~0.

**Hevy is charged on WORKED-SET TIME, not session duration (#4075, owner ruling
2026-09-24, decision 4A).** #4075's first half moved Strava onto HR and left the Hevy
term at 50 points/h × the whole logged session — rest between sets, a 45–60 min
cardio block and 15 min of stretching included — which was 92–97 % of the window's
load and held TSB near −61. Each Hevy set is now charged by what it is
(``hevy_session_load``):

  * **working rep set** (``type`` != ``warmup``, ``reps`` > 0) → ``reps ×
    SECONDS_PER_REP`` of work × ``LIFT_TSS_PER_HOUR``. Hevy stores no per-set
    timestamps and no duration on a rep set (every one of 327 rep sets 2026-09-03 →
    09-23 carries ``duration_sec: null``), so the per-rep time is a stated,
    population-derived constant — see ``SECONDS_PER_REP``. The owner's own logged
    ``reps`` scale it.                                               basis "worked_set"
  * **timed set with no distance** (a hold: plank, hang) → its MEASURED
    ``duration_sec`` × ``LIFT_TSS_PER_HOUR``.                       basis "worked_set"
  * **timed set with distance** (Hevy-logged Cycling / Treadmill / Walking) → a cardio
    block: its MEASURED ``duration_sec`` at the same no-HR rates a Strava activity gets
    (walk-pace → ``WALK_TSS_PER_HOUR``, else ``DEFAULT_CARDIO_TSS_PER_HOUR``) —
    **discounted by every second an HR-bearing Strava activity overlaps the session**,
    because that activity already scored the same minutes by HR.     basis "duration"
  * **mobility** (Stretching, …) and **warm-up sets** → 0. Excluded by the ruling
    (warm-ups, by Hevy set type) and by definition (stretching is not training stress).
  * **a workout with no set log at all** → ``duration_sec × LIFTING_WORK_FRACTION`` —
    the same stated 1:3 work:rest fraction ``health.tdee`` uses (one constant, read
    from there).                                                      basis "duration"

**HR vs worked-set time — which governs (no double counting).** For LIFTING,
worked-set time governs: an HR-bearing Strava weight-training copy of the session
(WHOOP records one) is skipped as an echo exactly as before, because average HR over
a lifting session is dominated by the rest between sets and systematically
under-reads resistance work (the reason session-RPE was introduced: Foster et al.
2001, J Strength Cond Res 15(1):109–115). For a CARDIO block logged inside Hevy, HR
governs wherever an HR-bearing (non-echo) Strava activity overlaps the session in
time; only the uncovered remainder takes the duration proxy.

Strava and Hevy loads are **additive** on the same day (a walk and a lift both
count), except a Strava echo of the Hevy session is skipped whenever Hevy has records
for that day. An echo is a weight-training sport OR any activity whose
``device_name`` is Hevy — #4075 found Hevy's conditioning ("Engine") sessions arrive
in Strava as ``sport_type: Workout`` from device "Hevy" with no HR. A Strava
weight-training activity with no HR and no Hevy record behind it (the digests read
Strava only) takes the same ``LIFTING_WORK_FRACTION`` of its duration, so no path
charges a whole lifting session as work any more.
"""

import math
from datetime import timedelta

from common import activity_overlap  # #4158: the ONE HR-covered-interval / overlap derivation
from common.hevy_schema import SET_DURATION_FIELD  # #4158: the ONE stored-set duration key
from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive == UTC)

# ~200 W FTP → 720 kJ/h at threshold = 100 TSS-like points.
KJ_PER_TSS_POINT = 7.2
# Low-intensity locomotion (IF ≈ 0.5 → 25 points/h). The walk fallback that fixes C-6.
WALK_TSS_PER_HOUR = 25.0
# Unknown-intensity aerobic work without HR (IF ≈ 0.7).
DEFAULT_CARDIO_TSS_PER_HOUR = 50.0
# Points per hour of WORKED-SET time (#4075 4A). The rate is unchanged from #490's
# session proxy (IF ≈ 0.7); what changed is the denominator — worked time, not session
# time — the same "same rate, correct denominator" move #3931 made on the energy side.
# Stated limitation: a set taken to RPE 8 is harder per minute than IF 0.7, so this
# rate likely UNDER-states per-minute lifting stress; it is kept because no personal
# or population calibration of a per-minute lifting intensity exists on the platform.
LIFT_TSS_PER_HOUR = 50.0
# ~0.9 × max HR. The normalisation anchor (1 h here = 100 points), not a lab LTHR.
THRESHOLD_HR = 165.0

# ── HR model (#4075) ──────────────────────────────────────────────────────────
# The owner's MEASURED max HR: `USER#matthew / PROFILE#v1 .max_heart_rate` = 183
# (read 2026-09-23). The load model is pure and has no profile access, so the value is
# carried here and cited, not invented; if the profile moves, move this with it.
MAX_HR = 183.0
# Zone 1's upper bound as a fraction of max HR — the platform's ONE zone table
# (`mcp/helpers.HR_ZONE_BOUNDS`, #2221; mirrored by `web/site_api_autonomic._ZONE_BOUNDS`).
# `tests/test_training_load.py` asserts the three agree, so this cannot drift silently.
Z1_CEILING_FRACTION_OF_MAX = 0.60
# 0.60 × 183 = 109.8 bpm. At or below this average HR an activity contributes 0.
# The programme's own walking cap (`owner_redlines.REDLINES["walking_floor_hr_wk"]
# ["hr_ceiling_bpm"]` = 105) sits under it, so a redline-compliant walk scores exactly 0.
Z1_CEILING_HR = round(MAX_HR * Z1_CEILING_FRACTION_OF_MAX, 1)
# Banister's TRIMP weighting (Banister 1991, "Modeling elite athletic performance",
# in MacDougall, Wenger & Green (eds.), Physiological Testing of the High-Performance
# Athlete, 2nd ed.; Morton, Fitz-Clarke & Banister 1990,
# J Appl Physiol 69:1171): TRIMP = minutes × HRr × 0.64·e^(1.92·HRr), male coefficients.
TRIMP_A = 0.64
TRIMP_B = 1.92
# The label of the Strava HR half of #4075.
HR_MODEL = "banister_trimp_above_z1_ceiling_v1"

# ── Hevy worked-set model (#4075, owner ruling 2026-09-24, decision 4A) ────────
# Seconds of work per repetition. **Population-derived, not measured** — Hevy records
# no per-set timestamps and no duration on a rep set (all 327 rep sets logged
# 2026-09-03 → 09-23 carry `duration_sec: null`; read-only DDB query 2026-09-23). The
# ACSM position stand on resistance-training progression (Ratamess et al. 2009, Med Sci
# Sports Exerc 41(3):687–708) defines "moderate" velocity as 1–2 s concentric + 1–2 s
# eccentric = 2–4 s per repetition; 3.0 s is the midpoint. Sensitivity, stated: at the
# 4 s end the worked-set lifting term is 33 % higher, at the 2 s end 33 % lower.
# `health.tdee.WORK_SECONDS_PER_REP_SET` (a flat 40 s per set, warm-ups INCLUDED) is
# the energy model's own assumption and is deliberately not this number — see the
# #4075 PR for why the two are not yet unified.
SECONDS_PER_REP = 3.0
# Where the per-rep time came from — carried on every stored basis (ADR-105).
SECONDS_PER_REP_SOURCE = "acsm_2009_moderate_tempo_midpoint_1-2s_concentric_1-2s_eccentric"
# A logged cardio block at or below this average speed is walking pace (7.2 km/h).
WALK_PACE_MAX_MS = 2.0
# Hevy exercise-name fragments that mark MOBILITY work: charged 0.
_MOBILITY_NAMES = ("stretch", "mobility", "yoga", "foam", "massage", "breath", "meditat")
# Hevy exercise-name fragments that mark walking-type locomotion.
_WALK_NAMES = ("walk", "treadmill", "hike", "stair")
# The Hevy set type the ruling excludes.
_WARMUP_SET_TYPES = {"warmup", "warm_up", "warm-up"}
# The label of the Hevy half of #4075.
LIFT_MODEL = "hevy_worked_set_time_v1"
# THE label every stored basis carries (`tsb_load_basis.model`), so a TSB computed
# under this model is tellable from one computed under #4113's (HR_MODEL alone) or
# #490's (no label).
LOAD_MODEL = "trimp_above_z1_plus_hevy_worked_set_v2"

# Strava sports scored at the walk rate.
_WALK_SPORTS = {"walk", "hike"}
# Strava sports that duplicate a Hevy session when one exists that day (#4075), and the
# Strava `device_name` of an activity Hevy itself pushed to Strava — both moved to
# `common.activity_overlap` (#4158) so `health.tdee` shares the ONE echo/overlap
# derivation without importing the `training` package; re-bound here under their
# original names so this module's own callers (and `tl._LIFT_SPORTS`/`tl._HEVY_DEVICE`
# in tests) are unaffected.
_LIFT_SPORTS = activity_overlap.LIFT_SPORTS
_HEVY_DEVICE = activity_overlap.HEVY_DEVICE

# Banister time constants (fitness 42 d, fatigue 7 d) over a 60-day window —
# identical to every implementation this module replaces.
CTL_DAYS = 42
ATL_DAYS = 7
WINDOW_DAYS = 60


#: Moved to `common.activity_overlap` (#4158) so `health.tdee` shares the ONE
#: sport/echo classification without importing `training`. Re-bound under the
#: original name for this module's own callers (`activity_load`) and for tests.
_sport = activity_overlap._sport


def day_key(rec):
    """The YYYY-MM-DD day a Strava/Hevy record belongs to (``date``, else its ``sk``)."""
    return str(rec.get("date") or "") or str(rec.get("sk") or "").replace("DATE#", "")[:10]


_day_key = day_key  # historical private name


def _trimp_weight(hrr):
    """Banister's per-minute TRIMP weight for a fractional HR reserve."""
    return hrr * TRIMP_A * math.exp(TRIMP_B * hrr)


def _hrr_above_z1(avg_hr):
    """Fraction of the Z1-ceiling→max range an average HR sits at, in [0, 1]."""
    span = MAX_HR - Z1_CEILING_HR
    if span <= 0:
        return 0.0
    return min(max((float(avg_hr) - Z1_CEILING_HR) / span, 0.0), 1.0)


def hr_load(hours, avg_hr):
    """TSS-like points from duration and average HR (#4075).

    Banister's TRIMP (``minutes × HRr × 0.64·e^(1.92·HRr)``) with ONE stated deviation:
    the HR reserve is measured above the owner's Zone-1 ceiling (``Z1_CEILING_HR``)
    instead of above resting HR, so recovery-intensity work contributes 0 — the
    #4075 acceptance. The result is normalised the way hrTSS normalises TRIMP: one
    hour at ``THRESHOLD_HR`` = 100 points, which keeps every downstream TSB band on
    the scale it already assumes.
    """
    if hours <= 0 or not avg_hr or avg_hr <= 0:
        return 0.0
    ref = _trimp_weight(_hrr_above_z1(THRESHOLD_HR))
    if ref <= 0:
        return 0.0
    return hours * _trimp_weight(_hrr_above_z1(avg_hr)) / ref * 100.0


def activity_load(act):
    """TSS-like load for one Strava activity. Returns (points, basis) where basis
    is "kj" for power-backed load, "hr" for heart-rate load, and "duration" for a
    duration-only proxy (no power, no HR)."""
    kj = float(act.get("kilojoules") or 0)
    if kj > 0:
        return kj / KJ_PER_TSS_POINT, "kj"
    hours = float(act.get("moving_time_seconds") or act.get("elapsed_time_seconds") or 0) / 3600.0
    if hours <= 0:
        return 0.0, "duration"
    avg_hr = float(act.get("average_heartrate") or 0)
    if avg_hr > 0:
        return hr_load(hours, avg_hr), "hr"
    sport = _sport(act)
    if sport in _WALK_SPORTS:
        return hours * WALK_TSS_PER_HOUR, "duration"
    if sport in _LIFT_SPORTS:
        # #4075 4A: no set log behind this lifting session — charge the stated work
        # fraction of it, never the whole session (rest included) as work.
        return hours * _lifting_work_fraction() * LIFT_TSS_PER_HOUR, "duration"
    return hours * DEFAULT_CARDIO_TSS_PER_HOUR, "duration"


#: Moved to `common.activity_overlap` (#4158) — see the module-level note above
#: `_sport`. Re-bound under the original name; `daily_training_load`'s own echo skip
#: and `hr_intervals` below both still call it as `is_hevy_echo(act)`.
is_hevy_echo = activity_overlap.is_hevy_echo


def _lifting_work_fraction():
    """The stated work:rest fraction for a lifting session with no set log.

    ONE constant, owned by ``health.tdee`` (#3931: "a hypertrophy session runs roughly
    1:3 work:rest, so ~0.25"). Imported lazily so this module keeps no import-time
    dependency beyond the stdlib.
    """
    from health.tdee import LIFTING_WORK_FRACTION_FALLBACK

    return LIFTING_WORK_FRACTION_FALLBACK


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN → None


#: Moved to `common.activity_overlap` (#4158) — `health.tdee.worked_set_seconds` needs
#: the identical merged-interval derivation to discount a Hevy cardio block already
#: scored by an HR-bearing Strava/Whoop activity, and cannot import `training` to get
#: it (ADR-152 / the boundary this doc note's own module docstring cites). Re-bound
#: under the original names so `hevy_session_load` and every caller/test in this
#: module (`tl.hr_intervals`, `tl._overlap_seconds`) are unaffected.
hr_intervals = activity_overlap.hr_intervals
_overlap_seconds = activity_overlap.overlap_seconds


def _is_mobility(name):
    n = str(name or "").lower()
    return any(k in n for k in _MOBILITY_NAMES)


def _cardio_rate(name, secs, distance_m):
    n = str(name or "").lower()
    speed = (distance_m / secs) if secs > 0 else 0.0
    if any(k in n for k in _WALK_NAMES) and speed <= WALK_PACE_MAX_MS:
        return WALK_TSS_PER_HOUR
    return DEFAULT_CARDIO_TSS_PER_HOUR


def hevy_session_load(workout, intervals=None):
    """TSS-like load for ONE Hevy workout, charged on worked-set time (#4075 4A).

    See the module docstring for the per-set rules. ``intervals`` are the merged
    HR-covered spans (``hr_intervals``); a cardio block's charge is scaled by the share
    of the session those spans do NOT cover.

    Returns a breakdown dict — every number a surface would need to check the charge:
    ``{"points", "lift_points", "cardio_points", "worked_seconds", "measured_hold_seconds",
    "rep_seconds_assumed", "working_rep_sets", "warmup_sets", "cardio_seconds",
    "cardio_hr_covered_seconds", "mobility_seconds", "basis"}``. ``basis`` is
    ``worked_set`` (a set log was read), ``no_set_log_work_fraction`` (fallback) or
    ``empty``.
    """
    out = {
        "points": 0.0,
        "lift_points": 0.0,
        "cardio_points": 0.0,
        "worked_seconds": 0.0,
        "measured_hold_seconds": 0.0,
        "rep_seconds_assumed": 0.0,
        "working_rep_sets": 0,
        "warmup_sets": 0,
        "cardio_seconds": 0.0,
        "cardio_hr_covered_seconds": 0.0,
        "mobility_seconds": 0.0,
        "basis": "empty",
    }
    exercises = workout.get("exercises") or workout.get("workout_exercises") or []
    has_sets = any((ex.get("sets") or []) for ex in exercises if isinstance(ex, dict))
    if not has_sets:
        secs = _num(workout.get("duration_sec")) or 0.0
        if secs > 0:
            out["worked_seconds"] = secs * _lifting_work_fraction()
            out["lift_points"] = out["points"] = out["worked_seconds"] / 3600.0 * LIFT_TSS_PER_HOUR
            out["basis"] = "no_set_log_work_fraction"
        return out

    out["basis"] = "worked_set"
    cardio_blocks = []  # (seconds, rate)
    for ex in exercises:
        if not isinstance(ex, dict):
            continue
        name = ex.get("name") or ex.get("title") or ""
        for st in ex.get("sets") or []:
            if str(st.get("type") or st.get("set_type") or "").strip().lower() in _WARMUP_SET_TYPES:
                out["warmup_sets"] += 1
                continue
            dur = _num(st.get(SET_DURATION_FIELD))
            if dur is None:
                dur = _num(st.get("duration_seconds"))  # the Hevy API wire name
            reps = _num(st.get("reps")) or 0.0
            if dur and dur > 0:
                if _is_mobility(name):
                    out["mobility_seconds"] += dur
                elif (_num(st.get("distance_m")) or 0) > 0:
                    cardio_blocks.append((dur, _cardio_rate(name, dur, _num(st.get("distance_m")) or 0.0)))
                else:
                    out["measured_hold_seconds"] += dur
            elif reps > 0:
                if _is_mobility(name):
                    continue
                out["working_rep_sets"] += 1
                out["rep_seconds_assumed"] += reps * SECONDS_PER_REP

    out["worked_seconds"] = out["measured_hold_seconds"] + out["rep_seconds_assumed"]
    out["lift_points"] = out["worked_seconds"] / 3600.0 * LIFT_TSS_PER_HOUR

    cardio_secs = sum(sec for sec, _r in cardio_blocks)
    out["cardio_seconds"] = cardio_secs
    if cardio_secs > 0:
        covered = _overlap_seconds(parse_iso_utc(workout.get("start_time")), parse_iso_utc(workout.get("end_time")), intervals)
        covered = min(covered, cardio_secs)
        out["cardio_hr_covered_seconds"] = covered
        uncovered_share = 1.0 - covered / cardio_secs
        out["cardio_points"] = sum(sec / 3600.0 * rate for sec, rate in cardio_blocks) * uncovered_share
    out["points"] = out["lift_points"] + out["cardio_points"]
    return out


def daily_training_load(strava_60d, hevy_60d, today=None):
    """Per-day TSS-like load for the Banister window, plus a provenance summary.

    Strava and Hevy are additive per day; a Strava echo of a Hevy session is skipped
    when Hevy has records for that day (same session, richer record). Hevy is charged
    on worked-set time (``hevy_session_load``, #4075 4A). Returns (load_by_day, basis).
    """
    # Multi-device duplicates were harmless on the kJ scale (walks carried 0 kJ);
    # under the duration proxy they would double-count, so dedup here for every
    # caller. Lazy import: digest_utils imports this module at top level.
    from common.digest_utils import dedup_activities

    strava_by_day = {}
    for r in strava_60d or []:
        d = _day_key(r)
        if d:
            strava_by_day.setdefault(d, []).extend(r.get("activities") or [])
    for d in strava_by_day:
        strava_by_day[d] = dedup_activities(strava_by_day[d])
    hevy_by_day = {}
    for r in hevy_60d or []:
        # A tombstoned row is a superseded legacy daily aggregate whose sessions are
        # also present as per-workout rows (#4030) — counting it would double them.
        if r.get("tombstone"):
            continue
        d = _day_key(r)
        if d:
            hevy_by_day.setdefault(d, []).append(r)
    # The minutes an HR record already scored, across the whole window (a session can
    # cross midnight UTC), so a Hevy-logged cardio block is never charged twice.
    covered = hr_intervals([a for acts in strava_by_day.values() for a in acts])

    load_by_day = {}
    kj_days = set()
    hr_days = set()
    duration_days = set()
    hevy_days = set()
    worked_set_days = set()
    kj_load = hr_load_total = proxy_load = worked_set_load = 0.0
    hevy_totals = {
        "worked_seconds": 0.0,
        "rep_seconds_assumed": 0.0,
        "measured_hold_seconds": 0.0,
        "working_rep_sets": 0,
        "warmup_sets": 0,
        "cardio_seconds": 0.0,
        "cardio_hr_covered_seconds": 0.0,
        "mobility_seconds": 0.0,
        "no_set_log_workouts": 0,
    }
    for d in set(strava_by_day) | set(hevy_by_day):
        day_load = 0.0
        for act in strava_by_day.get(d, []):
            if d in hevy_by_day and is_hevy_echo(act):
                continue  # Hevy carries this session
            pts, basis = activity_load(act)
            if basis == "hr":
                # An HR-scored activity is MEASURED even when it scores ~0 (a Zone-1
                # walk) — count the day so the basis can say so.
                hr_days.add(d)
            if pts <= 0:
                continue
            day_load += pts
            if basis == "kj":
                kj_days.add(d)
                kj_load += pts
            elif basis == "hr":
                hr_load_total += pts
            else:
                duration_days.add(d)
                proxy_load += pts
        for w in hevy_by_day.get(d, []):
            sess = hevy_session_load(w, covered)
            for k in hevy_totals:
                if k in sess:
                    hevy_totals[k] += sess[k]
            if sess["basis"] == "no_set_log_work_fraction":
                hevy_totals["no_set_log_workouts"] += 1
                # A work FRACTION of logged duration is a duration proxy, labelled so.
                proxy_load += sess["points"]
            else:
                worked_set_load += sess["lift_points"]
                proxy_load += sess["cardio_points"]  # un-HR-covered cardio: duration proxy
                if sess["lift_points"] > 0:
                    worked_set_days.add(d)
            if sess["points"] > 0:
                day_load += sess["points"]
                hevy_days.add(d)
        if day_load > 0:
            load_by_day[d] = round(day_load, 1)

    total = kj_load + hr_load_total + proxy_load + worked_set_load
    present = [
        name
        for name, v in (("power", kj_load), ("hr", hr_load_total), ("worked_set", worked_set_load), ("duration_proxy", proxy_load))
        if v > 0
    ]
    if total <= 0:
        confidence = "none"
    elif len(present) == 1:
        confidence = present[0]
    else:
        confidence = "mixed"
    basis = {
        "unit": "tss_proxy",
        # THE model label (#4075 4A). `hr_model` / `lift_model` name its two halves.
        "model": LOAD_MODEL,
        "hr_model": HR_MODEL,
        "lift_model": LIFT_MODEL,
        "z1_ceiling_bpm": Z1_CEILING_HR,
        "strava_days": len(kj_days | hr_days | duration_days),
        "strava_kj_days": len(kj_days),
        "strava_hr_days": len(hr_days),
        "strava_duration_days": len(duration_days),
        "hevy_fallback_days": len(hevy_days),
        "hevy_worked_set_days": len(worked_set_days),
        # proxy_share = the DURATION-ONLY share (no power, no HR, no set log).
        "proxy_share": round(proxy_load / total, 3) if total > 0 else None,
        "hr_share": round(hr_load_total / total, 3) if total > 0 else None,
        "worked_set_share": round(worked_set_load / total, 3) if total > 0 else None,
        # ADR-105: the per-rep time is an ASSUMPTION — say so, with its source and how
        # much of the worked time rests on it versus on a measured Hevy duration.
        "worked_set": {
            "seconds_per_rep": SECONDS_PER_REP,
            "seconds_per_rep_source": SECONDS_PER_REP_SOURCE,
            "worked_seconds": round(hevy_totals["worked_seconds"], 1),
            "assumed_seconds": round(hevy_totals["rep_seconds_assumed"], 1),
            "measured_seconds": round(hevy_totals["measured_hold_seconds"], 1),
            "working_rep_sets": int(hevy_totals["working_rep_sets"]),
            "warmup_sets_excluded": int(hevy_totals["warmup_sets"]),
            "cardio_seconds": round(hevy_totals["cardio_seconds"], 1),
            "cardio_hr_covered_seconds": round(hevy_totals["cardio_hr_covered_seconds"], 1),
            "mobility_seconds_excluded": round(hevy_totals["mobility_seconds"], 1),
            "no_set_log_workouts": int(hevy_totals["no_set_log_workouts"]),
        },
        "confidence": confidence,
    }
    return load_by_day, basis


def banister(load_by_day, today):
    """CTL (42 d fitness), ATL (7 d fatigue), TSB = CTL − ATL over the 60-day window.

    CTL/ATL are exponentially-weighted loads and mathematically non-negative —
    clamped so a degenerate input can never surface a negative fitness/fatigue.
    """
    ctl = atl = 0.0
    cd = math.exp(-1 / CTL_DAYS)
    ad = math.exp(-1 / ATL_DAYS)
    for i in range(WINDOW_DAYS - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        load = load_by_day.get(day, 0)
        ctl = ctl * cd + load * (1 - cd)
        atl = atl * ad + load * (1 - ad)
    ctl = max(0.0, round(ctl, 1))
    atl = max(0.0, round(atl, 1))
    return ctl, atl, round(ctl - atl, 1)


def compute_ctl_atl_tsb(strava_60d, today, hevy_60d=None):
    """CTL/ATL/TSB straight from day records — the one call sites should use."""
    load_by_day, _ = daily_training_load(strava_60d, hevy_60d, today)
    return banister(load_by_day, today)


def is_duration_proxy(basis):
    """True when at least half the window's load is duration-derived (no power, no HR).

    The ONE predicate every surface uses to decide whether its TSB carries a
    "duration-proxy" label (#4075: an HR-scored window is measured, not proxied, so
    ``confidence != "power"`` is no longer the right test). A pre-#490 stored basis
    without ``proxy_share`` falls back to its confidence string.
    """
    if not basis:
        return False
    share = basis.get("proxy_share")
    try:
        share = float(share) if share is not None else None
    except (TypeError, ValueError):
        share = None
    if share is not None:
        return share >= 0.5
    return basis.get("confidence") in ("duration_proxy", "hevy_fallback")


def basis_description(basis):
    """One honest sentence naming what drove the window's load, or None (#4075 4A).

    Derived from the stored basis's shares, never from ``confidence`` alone: under the
    worked-set model a non-proxy window can be driven by Hevy worked-set time, by HR, or
    by a mix, and a sentence keyed on "not power" would call a lifting window "heart-rate".
    A power-only window, or no basis at all, returns None (nothing to qualify).
    """
    if not basis:
        return None
    conf = str(basis.get("confidence") or "")
    if is_duration_proxy(basis):
        return "duration-proxy basis — at least half the load is a duration estimate (no HR, no power)"
    if conf in ("", "none", "power"):
        return None

    def _share(key):
        try:
            v = basis.get(key)
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    labels = (
        ("worked_set_share", "Hevy worked-set time (working sets x reps x the stated per-rep tempo, warm-ups excluded)"),
        ("hr_share", "heart rate (Banister TRIMP above the Zone-1 ceiling)"),
        ("proxy_share", "duration estimates (no HR, no power)"),
    )
    parts = [(_share(k), text) for k, text in labels if _share(k) > 0]
    if not parts:
        # A pre-#4075-4A basis carries no worked_set_share; say only what it does carry.
        if conf == "hr":
            return "heart-rate basis — loads are Banister TRIMP above the Zone-1 ceiling, not power-meter data"
        return None
    parts.sort(key=lambda p: -p[0])
    head = f"{parts[0][1].split(' (')[0]} basis"
    detail = "; ".join(f"{round(sh * 100)}% {text}" for sh, text in parts)
    return f"{head} — {detail}; not power-meter data"


def basis_note(basis):
    """Human-readable provenance suffix for anywhere TSB renders (M-3).

    Returns " (duration-proxy basis)" when at least half the window's load is
    duration-derived, "" when power/HR-backed or when there is no basis to judge.
    """
    return " (duration-proxy basis)" if is_duration_proxy(basis) else ""
