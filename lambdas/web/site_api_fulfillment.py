"""lambdas/web/site_api_fulfillment.py — the C-floor wellbeing surface split out of
site_api_data.py (#1654): fulfillment_ritual / fulfillment_index / character_calibration.
Reads facade state via `_g`."""

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

from web.site_api_common import PT, USER_PREFIX, _decimal_to_float, _ok, logger


def fulfillment_ritual(*, _g) -> dict:
    """
    GET /api/fulfillment_ritual
    ADR-124 (#769) publish surface for the C-floor two-scalar evening ritual
    (connection today 0-4, mood valence 0-4 — captured via the evening-nudge
    one-tap links, see lambdas/web/site_api_social.py::_handle_ritual_log).

    Aggregate-only per the ADR-124 publication posture:
      1. The aggregate always publishes, bad weeks included.
      2. A dark day renders as honest absence (null), never a fabricated neutral
         (ADR-104) — the 7-day trend below is null-filled, not zero-filled.
      3. No labels, no free text — there are none in this record to begin with.
    This endpoint is the ONLY read surface for the evening_ritual partition —
    individual full daily history is never otherwise exposed publicly.
    Cache: 900s (15 min).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _experiment_date = _g["_experiment_date"]
    table = _g["table"]
    today = datetime.now(PT).strftime("%Y-%m-%d")
    window_start = _experiment_date(90)

    pk = f"{USER_PREFIX}evening_ritual"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot-phase ritual records
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{window_start}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    by_date = {}
    for it in items:
        d = it.get("date") or str(it.get("sk", "")).replace("DATE#", "")
        if d:
            by_date[d] = it

    # 7-day trend — the last 7 calendar days ending today. A day with no record
    # (or a record missing one of the two scalars) renders that field as null —
    # honest absence, never a fabricated neutral (ADR-104).
    trend = []
    for i in range(6, -1, -1):
        d = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = by_date.get(d) or {}
        trend.append(
            {
                "date": d,
                "connection": rec.get("connection"),
                "mood_valence": rec.get("mood_valence"),
            }
        )

    # Check-in count — any queried-window day with at least one scalar logged.
    logged_dates = sorted(d for d, rec in by_date.items() if rec.get("connection") is not None or rec.get("mood_valence") is not None)
    logged_set = set(logged_dates)
    check_in_count = len(logged_dates)

    # Current streak — the contiguous run of logged days ending at the most
    # recent one (not necessarily today — the evening nudge hasn't always fired
    # yet when this is read). A day with no log breaks the run; nothing is
    # backfilled or assumed.
    streak = 0
    if logged_dates:
        cursor = datetime.strptime(logged_dates[-1], "%Y-%m-%d")
        while cursor.strftime("%Y-%m-%d") in logged_set:
            streak += 1
            cursor -= timedelta(days=1)

    return _ok(
        {
            "trend_7d": trend,
            "check_in_count": check_in_count,
            "streak_days": streak,
            "as_of_date": today,
        },
        cache_seconds=900,
    )


def fulfillment_index(*, _g) -> dict:
    """
    GET /api/fulfillment_index — the asymmetric-channel fulfillment index
    (#1404, epic #718). All composition rules live in
    lambdas/fulfillment_index.py (pure, unit-tested); this handler only
    fetches rows and serves the result.

    Publication posture mirrors /api/fulfillment_ritual (ADR-124): aggregates
    only, bad weeks included, absence honest (insufficient_signal state / null
    means), never a fabricated number. Cache: 900s.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _experiment_date = _g["_experiment_date"]
    table = _g["table"]
    import fulfillment_index as fi

    today = datetime.now(PT).strftime("%Y-%m-%d")
    window_start = _experiment_date(90)
    trend_start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")

    def _window(source, projection=None):
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}{source}") & Key("sk").between(f"DATE#{window_start}", f"DATE#{today}~"),
            "ScanIndexForward": True,
        }
        try:
            resp = table.query(**with_phase_filter(kwargs))  # ADR-058: current-cycle reads
            return _decimal_to_float(resp.get("Items", []))
        except Exception as _e:
            logger.warning(f"[fulfillment_index] {source}: {_e}")
            return []

    def _adoption_date(source):
        """First row EVER (cross-cycle, deliberately unfiltered — adoption is a
        capability fact about the instrumentation, not a cycle datum). None ⇒
        the channel has never produced a row."""
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source}") & Key("sk").begins_with("DATE#"),
                ScanIndexForward=True,
                Limit=1,
            )
            items = resp.get("Items", [])
            if not items:
                return None
            return str(items[0].get("sk", "")).replace("DATE#", "")[:10] or None
        except Exception:
            return None

    def _date_of(it):
        return (it.get("date") or str(it.get("sk", "")).replace("DATE#", ""))[:10]

    ritual_by_date = {_date_of(it): it for it in _window("evening_ritual")}
    interactions_by_date: dict = {}
    for it in _window("interactions"):
        interactions_by_date.setdefault(_date_of(it), []).append(it)
    journal_dates = {_date_of(it) for it in _window("notion")}
    todoist_by_date = {_date_of(it): it for it in _window("todoist")}
    flourishing_by_date = {_date_of(it): it for it in _window("flourishing")}

    adoption = {
        "connection_tap": _adoption_date("evening_ritual"),
        "interactions": _adoption_date("interactions"),
        "journal_presence": _adoption_date("notion"),
        # values_todoist adoption is detected within the fetched window (there is
        # no cheap first-tagged-ever query). A convention adopted >90d ago and
        # untouched since reads as not-adopted — the FORGIVING direction: the
        # channel freezes out of coverage rather than zeroing the index.
        "values_todoist": next(
            (d for d in sorted(todoist_by_date) if fi.values_tagged_completions(todoist_by_date[d]) > 0),
            None,
        ),
    }

    days = []
    cursor = datetime.strptime(trend_start, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    while cursor <= end:
        d = cursor.strftime("%Y-%m-%d")
        adopted = {name: bool(adoption[name] and adoption[name] <= d) for name in fi.CHANNEL_NAMES}
        scores = {
            "connection_tap": fi.score_connection_tap(ritual_by_date.get(d)),
            "interactions": fi.score_interactions(interactions_by_date.get(d)),
            "journal_presence": fi.score_journal_presence(d in journal_dates),
            "values_todoist": fi.score_values_todoist(todoist_by_date.get(d)),
        }
        day = fi.compose_day(d, adopted, scores)
        fi.attach_resolution(day, flourishing_by_date.get(d))
        days.append(day)
        cursor += timedelta(days=1)

    mean_7d, n_7d = fi.window_mean(days[-7:])
    mean_30d, n_30d = fi.window_mean(days)

    return _ok(
        {
            "today": days[-1] if days else None,
            "trend_7d": days[-7:],
            "mean_7d": mean_7d,
            "n_scored_7d": n_7d,
            "mean_30d": mean_30d,
            "n_scored_30d": n_30d,
            "channels_adopted": adoption,
            "coverage_floor": fi.COVERAGE_FLOOR,
            "disclosure": fi.DISCLOSURE,
            "as_of_date": today,
        },
        cache_seconds=900,
    )


def character_calibration(*, _g) -> dict:
    """
    GET /api/character_calibration — the felt-reality calibration ledger (#1409).

    Pairs each weekly felt-reality probe (Sunday one-tap, SOURCE#felt_probe,
    0-4 ordinal) with the probed pillar's mean level_score over the 7 days
    ending that Sunday (SOURCE#character_sheet), and serves per-pillar
    calibration: pearson r + Fisher CI + Pyper–Peterman n_eff — all
    deterministic stats_core computation, no LLM anywhere (ADR-105).

    Publication posture (ADR-124 C-floor, like /api/fulfillment_ritual):
    AGGREGATES ONLY — r/CI/n/n_eff/coverage per pillar; individual weekly probe
    values are never served. Confidence grammar (ADR-105): below
    FELT_CALIBRATION_MIN_WEEKS a pillar renders "uncalibrated (n=X)" with the
    arming trigger and NO r; between MIN and CI_MIN weeks r is a point estimate
    with NO band (never fabricated); the band appears only when n can carry it.
    A skipped Sunday is a coverage gap (n doesn't accrue), never a zero.
    Cache: 3600s (recomputes at most weekly by nature).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _query_source = _g["_query_source"]
    from experiment_gates import FELT_CALIBRATION_CI_MIN_WEEKS, FELT_CALIBRATION_MIN_WEEKS, felt_calibration_gates
    from ritual_link import PROBE_PILLAR_MAP
    from stats_core import effective_sample_size, fisher_ci, pearson_r

    today = datetime.now(PT).strftime("%Y-%m-%d")
    probes = _query_source("felt_probe", EXPERIMENT_START, today)
    sheets = _query_source("character_sheet", EXPERIMENT_START, today)

    # pillar level_score by date (fall back raw_score; skip absent — never zero-fill)
    level_by_date: dict[str, dict[str, float]] = {}
    for rec in sheets:
        d = rec.get("date") or str(rec.get("sk", "")).replace("DATE#", "")
        if not d:
            continue
        per = {}
        for pillar in set(PROBE_PILLAR_MAP.values()):
            pdata = rec.get(f"pillar_{pillar}") or {}
            v = pdata.get("level_score", pdata.get("raw_score"))
            if v is not None:
                per[pillar] = float(v)
        level_by_date[d] = per

    # Sundays with at least one probe item — the ledger's coverage spine.
    probe_by_date: dict[str, dict] = {}
    for rec in probes:
        d = rec.get("date") or str(rec.get("sk", "")).replace("DATE#", "")
        if d:
            probe_by_date[d] = rec

    pillars_out = []
    for metric, pillar in sorted(PROBE_PILLAR_MAP.items()):
        felt_vals, level_means, weeks = [], [], []
        for d in sorted(probe_by_date):
            v = probe_by_date[d].get(metric)
            if v is None:
                continue  # skipped item that Sunday — coverage gap, not a zero
            d_obj = datetime.strptime(d, "%Y-%m-%d")
            window = [(d_obj - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
            levels = [level_by_date[w][pillar] for w in window if w in level_by_date and pillar in level_by_date[w]]
            if not levels:
                continue  # no sheet coverage that week — the pair can't form
            felt_vals.append(float(v))
            level_means.append(sum(levels) / len(levels))
            weeks.append(d)
        n = len(felt_vals)
        entry = {
            "pillar": pillar,
            "probe_metric": metric,
            "n_weeks": n,
            "latest_week": weeks[-1] if weeks else None,
            "gates": felt_calibration_gates(current_n=n),
        }
        if n >= FELT_CALIBRATION_MIN_WEEKS:
            r = pearson_r(felt_vals, level_means, min_n=FELT_CALIBRATION_MIN_WEEKS)
            if r is None:
                entry["state"] = "uncalibrated"
                entry["why"] = "no variance yet — every probe or level identical"
            else:
                n_eff = effective_sample_size(felt_vals, level_means)
                entry["state"] = "calibrated"
                entry["r"] = round(r, 3)
                entry["n_eff"] = round(n_eff, 1)
                if n >= FELT_CALIBRATION_CI_MIN_WEEKS:
                    lo, hi = fisher_ci(r, max(4.0, n_eff))
                    entry["ci95"] = [round(lo, 3), round(hi, 3)]
                else:
                    # ADR-105: point estimate only — the band would be fabricated at this n
                    entry["ci95"] = None
        else:
            entry["state"] = "uncalibrated"
        pillars_out.append(entry)

    probed = set(PROBE_PILLAR_MAP.values())
    for pillar in ("nutrition", "metabolic", "mind", "consistency"):
        if pillar not in probed:
            pillars_out.append({"pillar": pillar, "state": "unprobed", "why": "no felt-reality instrument maps to this pillar yet"})

    covered = len(probe_by_date)
    return _ok(
        {
            "pillars": pillars_out,
            "probe_weeks_covered": covered,
            "as_of_date": today,
            "cadence": "weekly (Sunday evening one-tap, 3 items)",
            "method": "pearson r of felt (0-4) vs 7-day mean pillar level_score; Fisher 95% CI on Pyper-Peterman n_eff",
        },
        cache_seconds=3600,
    )
