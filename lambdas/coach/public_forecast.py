"""public_forecast.py — the platform's forecast rule: one or two public-input forecasts a week (#6156).

WHY. Reader calls went public on 2026-11-17 (#6114) and have had almost nothing to call: the coaches' public calls are
few, often open one day, and every one was written from a context that includes private inputs. The owner's bar
(2026-11-21) for a forecast readers may call beside: public-only input lineage; an identified model and prompt version;
an immutable timestamp; a clear prediction and target; a frozen evaluation method; publication approval through the
existing rules; a meaningful submission window; an outcome unknown at registration; a verifiable final result; and a
comparison with the appropriate baseline. Never a retrospective forecast; never a repurposed private-input coach call.

WHAT IT IS. A DETERMINISTIC RULE, not a language model and not a coach (``common.public_forecast_policy``: the author is
"the platform's forecast rule"). Each rule in ``RULES`` is a named, versioned statistic over one public series:

  * ``weight_trend`` — the least-squares line through the last 14 days of weigh-ins, read on the target day;
  * ``recovery_mean`` / ``sleep_mean`` — the mean of the last 28 days (a night is expected to look like the month).

Each forecast is a NUMBER call (``point`` spec) on the day ``HORIZON_DAYS`` after filing: "Weight will be about 281.4 lb
on 2026-11-30", graded within ±1 SD of the series' own last 30 days — the SAME tolerance rule a coach's number call is
filed with (``prediction_emission.point_tolerance_from_series``), so the grade is the grader's existing one.

THE INPUTS are read ONLY over HTTPS from the public Site API (``/api/series``, the route the data room charts) — the
values any reader sees — and only for a metric that route's own catalogue serves and whose every source the publication
policy classifies public (``common.public_brief_policy.metric_is_eligible``). The row stores the lineage: the URL, the
window, the route's ``as_of``, every value read and a SHA-256 of them, so anyone can re-fetch and check.

THE ROW (``build``) is the canonical ``PREDICTION#`` record (``prediction_emission.build_prediction_record``, filed
through ``filing_rules.validate_filing``) in the forecast partition, plus: ``model`` (rule id + version, ``prompt_version``
null by design), ``lineage``, ``baseline_at_filing`` (the "nothing changes" guess's value, frozen now by the same
``coach_baseline.filed_reading`` the grader stamps with later), ``evaluation_rule`` (the sentence), and
``submission_window`` (when reader calls close, by ``web.reader_call_rules.open_until``, and when the result is due).

THE ORDER, per run (``run``): both switches (a dry run ignores them and writes nothing); the cycle's picks; per pick —
read the public series through the day BEFORE filing, refuse stale or thin inputs, fit, freeze tolerance and baseline,
file through the rules, refuse a reader window under ``MIN_OPEN_DAYS``; write append-only (``attribute_not_exists``),
one key per (cycle, rule), so a re-run never files twice and a written row is never rewritten.

NO BACKFILL. The filing day is always the run day; the data ends the day before it; the target is after it. The Lambda
door (``public_brief.handle_event``) passes only the Pacific run day, and a ``today`` override there is refused without
``dry_run`` — which never reaches this stream; the dry-run CLI's ``--today`` never writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from common import narrative_provenance as NP, public_brief_policy as BPOL, public_forecast_policy as POL
from common.numeric import floats_to_decimal

logger = logging.getLogger(__name__)

PRODUCER = "coach.public_forecast"
RULESET_VERSION = 1
PUBLIC_BASE = "https://averagejoematt.com"
ROUTE = "/api/series"
HORIZON_DAYS = 7  # filed -> target; a 7-day window leaves the reader door open 4 days (midpoint rule)
TOLERANCE_LOOKBACK_DAYS = 30  # the coaches' number-call tolerance window (public_brief.POINT_LOOKBACK_DAYS)
FRESH_DAYS = 3  # the newest reading must be at most this many days before filing
MIN_OPEN_DAYS = 2  # the reader door must stay open at least this many days, or nothing is filed
MAX_PER_CYCLE = 2
HTTP_TIMEOUT_S = 15
#: The runtime kill switch (fail closed; only "on" files). Not created by this change; read with a grant on the
#: coach-orchestrator role (cdk/stacks/role_policies_compute.py ``PublicForecastSwitchRead``).
SWITCH_PARAM = "/life-platform/public-forecast"

#: THE RULES (registry). ``fit_days``: the readings the statistic is computed from; ``min_readings``: below it, no call.
RULES: dict = {
    "weight_trend": {
        "metric": "weight_lbs",
        "method": "linear_trend",
        "fit_days": 14,
        "min_readings": 7,
        "words": "the least-squares line through the last 14 days of weigh-ins, read on the target day",
    },
    "recovery_mean": {
        "metric": "recovery_score",
        "method": "trailing_mean",
        "fit_days": 28,
        "min_readings": 14,
        "words": "the mean of the last 28 days of recovery scores",
    },
    "sleep_mean": {
        "metric": "sleep_duration_hours",
        "method": "trailing_mean",
        "fit_days": 28,
        "min_readings": 14,
        "words": "the mean of the last 28 nights of sleep duration",
    },
}
#: The weekly rotation: weight every cycle, then recovery and sleep on alternate ISO weeks.
ALWAYS = ("weight_trend",)
ALTERNATE = ("recovery_mean", "sleep_mean")


def picks(cycle: str) -> list:
    """The rules filed for ``cycle`` (at most ``MAX_PER_CYCLE``), in order."""
    week = datetime.strptime(cycle, "%Y-%m-%d").isocalendar()[1]
    return (list(ALWAYS) + [ALTERNATE[week % len(ALTERNATE)]])[:MAX_PER_CYCLE]


def _day(s: str, delta: int = 0) -> str:
    return (datetime.strptime(str(s)[:10], "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def _days_between(a: str, b: str) -> int:
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


# ── the public read ─────────────────────────────────────────────────────────────────────────────
def http_get_json(url: str) -> dict:
    """GET a public URL (no credentials) and parse its JSON. Raises on any failure — the caller holds the rule."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "public-forecast-rule/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 — a fixed https base
        return json.loads(resp.read().decode("utf-8"))


def series_url(metric: str, start: str, end: str, base: str = PUBLIC_BASE) -> str:
    return f"{base}{ROUTE}?metric={metric}&from={start}&to={end}"


def served_metrics(fetch_json: Callable, base: str = PUBLIC_BASE) -> set:
    """The keys the public route's own catalogue serves (its bare GET)."""
    body = fetch_json(f"{base}{ROUTE}") or {}
    return {str(m.get("metric")) for m in body.get("metrics") or [] if isinstance(m, dict)}


def readings_of(payload: dict, start: str, end: str) -> list:
    """``[(day, value)]`` — the measured days of a served series inside ``[start, end]``, oldest first."""
    out = []
    for d in (payload or {}).get("days") or []:
        day, v = str((d or {}).get("date") or "")[:10], (d or {}).get("value")
        if not (d or {}).get("present") or isinstance(v, bool) or not (start <= day <= end):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append((day, f))
    return sorted(out)


def values_digest(readings: list) -> str:
    """SHA-256 of the readings as canonical JSON ``[["YYYY-MM-DD", value], ...]`` — reproducible by any reader."""
    return hashlib.sha256(json.dumps([[d, v] for d, v in readings], separators=(",", ":")).encode("utf-8")).hexdigest()


# ── the statistics (pure) ───────────────────────────────────────────────────────────────────────
def fit(method: str, readings: list, target: str) -> Optional[float]:
    """The rule's value for ``target`` from ``readings`` ([(day, value)]); None when it cannot be computed."""
    if not readings:
        return None
    if method == "trailing_mean":
        return sum(v for _d, v in readings) / len(readings)
    if method == "linear_trend":
        x0 = readings[0][0]
        xs = [float(_days_between(x0, d)) for d, _v in readings]
        ys = [v for _d, v in readings]
        n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if n < 2 or sxx <= 0:
            return None
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        return my + slope * (float(_days_between(x0, target)) - mx)
    return None


# ── one forecast ────────────────────────────────────────────────────────────────────────────────
def build(rule_id: str, today: str, payload: dict, url: str, cycle: str, *, phase_stamp: bool = True) -> tuple:
    """``(row, None)`` — the PREDICTION# row this rule would file today from ``payload`` (the served series) — or
    ``(None, reason)``. Pure given its inputs (the clock is ``today`` and the record's instants), except the write-time
    experiment stamp (an SSM read of the cycle), which a dry run skips (``phase_stamp=False``)."""
    from web import reader_call_rules as R

    from coach import coach_baseline, prediction_emission as PE, prediction_windows, public_brief as PB
    from coach.filing_rules import validate_filing

    rule = RULES[rule_id]
    metric, through, target = rule["metric"], _day(today, -1), _day(today, HORIZON_DAYS)
    if not BPOL.metric_is_eligible(metric):
        return None, "metric_not_public"
    span_start = _day(through, -(max(rule["fit_days"], TOLERANCE_LOOKBACK_DAYS) - 1))
    readings = readings_of(payload, span_start, through)  # nothing on or after the filing day is ever read
    if not readings or readings[-1][0] < _day(today, -FRESH_DAYS):
        return None, "inputs_stale"
    fit_rows = [(d, v) for d, v in readings if d >= _day(through, -(rule["fit_days"] - 1))]
    if len(fit_rows) < rule["min_readings"]:
        return None, "too_few_readings"
    level = fit(rule["method"], fit_rows, target)
    places = PB.METRIC_WORDS[metric][2]
    tol_rows = [v for d, v in readings if d >= _day(through, -(TOLERANCE_LOOKBACK_DAYS - 1))]
    tol = PE.point_tolerance_from_series(tol_rows, lookback_days=TOLERANCE_LOOKBACK_DAYS)
    if level is None or tol is None:
        return None, "no_level" if level is None else "no_tolerance"
    level = round(level, places)
    filed_value, filed_on, why = coach_baseline.filed_reading(readings, metric, today)
    if filed_value is None:
        return None, f"baseline_{why}"
    spec = PE.build_point_eval_spec(metric, level, tol[0], tol[1], HORIZON_DAYS, today)
    claim = PB.render_claim({"metric": metric, "kind": "level", "target": level, "window_days": HORIZON_DAYS}, target)
    verdict = validate_filing(claim, spec, today, stated_days=HORIZON_DAYS)
    if not verdict["gradeable"]:
        return None, "not_gradeable:" + str(verdict["filing"].get("reason"))
    row = PE.build_prediction_record("", today, claim, verdict["eval_spec"], None, "observational", filing=verdict["filing"])
    if row.get("status") != "pending":
        return None, "not_pending"
    spec = row["evaluation"]
    due = prediction_windows.due_date(today, spec, row.get("subdomain", ""))
    closes = R.open_until(spec, today, prediction_windows.effective_window_days(spec, row.get("subdomain", "")), due)
    if not closes or _days_between(today, closes) + 1 < MIN_OPEN_DAYS:
        return None, "reader_window_too_short"
    pred_id = f"pred_{cycle.replace('-', '')}_forecast_{rule_id}"
    row.update({"pk": POL.FORECAST_PK, "sk": f"PREDICTION#{pred_id}"})  # the filing-rules writer guard reads this literal
    row.update(
        prediction_id=pred_id,
        coach_id="",
        source=POL.FORECAST_SOURCE,
        author=POL.AUTHOR_ID,
        author_words=POL.AUTHOR_WORDS,
        forecast_cycle=cycle,
        rule_id=rule_id,
        model={
            "id": f"{POL.AUTHOR_ID}.{rule_id}",
            "version": RULESET_VERSION,
            "kind": "deterministic_rule",
            "method": rule["method"],
            "words": rule["words"],
            "prompt_version": None,
            "prompt_version_note": "not applicable by design: a deterministic rule; no language model is called",
        },
        lineage={
            "public_only": True,
            "route": ROUTE,
            "url": url,
            "metric": metric,
            "field": "days[].value",
            "source_id": payload.get("source_id"),
            "unit": payload.get("unit"),
            "served_as_of": payload.get("as_of"),
            "window": {"from": span_start, "to": through},
            "n": len(readings),
            "readings": [[d, v] for d, v in readings],
            "sha256": values_digest(readings),
        },
        baseline_at_filing={
            "rule": coach_baseline.RULE_ID,
            "version": coach_baseline.RULE_VERSION,
            "words": coach_baseline.RULE_WORDS,
            "filed_value": filed_value,
            "filed_on": filed_on,
            "guess": f"the reading on {target} is within {tol[0]:g} of {filed_value:g}",
        },
        evaluation_rule=PB.criteria_rule(spec),
        submission_window={"opens": today, "closes": closes, "result_due": due, "rule": "web.reader_call_rules.open_until"},
    )
    row[NP.PROVENANCE_KEY] = NP.stamp(BPOL.families_for([metric]), producer=PRODUCER)
    if not NP.is_publishable(row):
        return None, "inputs_not_publishable"
    if not phase_stamp:
        return row, None
    try:
        from experiment.phase_taxonomy import experiment_stamp_for

        row.update(experiment_stamp_for(row["pk"], row["sk"]))
    except Exception as e:  # noqa: BLE001 — a stamp is metadata, never a reason to drop the row
        logger.info("[public_forecast] no experiment stamp: %s", e)
    return row, None


# ── the switches ────────────────────────────────────────────────────────────────────────────────
def runtime_switch_on(get_parameter: Optional[Callable] = None) -> bool:
    """True only when SSM ``SWITCH_PARAM`` reads ``on`` (surrounding spaces ignored). Absent, unreadable or anything else is OFF."""
    try:
        if get_parameter is None:
            import boto3

            get_parameter = boto3.client("ssm", region_name="us-west-2").get_parameter
        value = str(((get_parameter(Name=SWITCH_PARAM) or {}).get("Parameter") or {}).get("Value") or "")
        return value.strip() == "on"
    except Exception as e:  # noqa: BLE001 — an unreadable switch is off
        logger.info("[public_forecast] switch unreadable (%s) — off", type(e).__name__)
        return False


def _put_new(table: Any, item: dict) -> bool:
    """Append-only: written once (the creation instant is immutable), never overwritten."""
    try:
        table.put_item(Item=floats_to_decimal(item), ConditionExpression="attribute_not_exists(sk)")
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed (already filed) or a transport error
        logger.info("[public_forecast] not written %s/%s: %s", item.get("pk"), item.get("sk"), e)
        return False


# ── the run ─────────────────────────────────────────────────────────────────────────────────────
def run(
    table: Any,
    *,
    today: str,
    persist: bool = True,
    fetch_json: Callable = http_get_json,
    switch: Callable = runtime_switch_on,
    base: str = PUBLIC_BASE,
) -> dict:
    """The weekly run. Never raises. A dry run (``persist=False``) ignores both switches and writes nothing."""
    try:
        if persist and not POL.STREAM_LIVE:
            return {"status": "off", "reason": "committed_switch_off"}
        if persist and not switch():
            return {"status": "off", "reason": "runtime_switch_off"}
        cycle = BPOL.cycle_of(today)
        served = served_metrics(fetch_json, base)
        results: dict = {}
        rows: list = []
        for rule_id in picks(cycle):
            metric = RULES[rule_id]["metric"]
            if metric not in served:
                results[rule_id] = {"status": "held", "reason": "not_served_publicly"}
                continue
            start = _day(today, -max(RULES[rule_id]["fit_days"], TOLERANCE_LOOKBACK_DAYS))
            url = series_url(metric, start, _day(today, -1), base)
            try:
                payload = fetch_json(url)
            except Exception as e:  # noqa: BLE001 — an unread input is a held rule, never a guess
                results[rule_id] = {"status": "held", "reason": f"input_unreadable:{type(e).__name__}"}
                continue
            row, why = build(rule_id, today, payload, url, cycle, phase_stamp=persist)
            if row is None:
                results[rule_id] = {"status": "held", "reason": why}
                continue
            rows.append(row)
            if not persist:
                results[rule_id] = {"status": "dry_run", "prediction_id": row["prediction_id"]}
            else:
                results[rule_id] = {"status": "written" if _put_new(table, row) else "exists", "prediction_id": row["prediction_id"]}
        out = {"status": "ok", "cycle": cycle, "filed_on": today, "results": results}
        if not persist:
            out["forecasts"] = rows
        logger.info("[public_forecast] cycle %s: %s", cycle, {k: v.get("status") for k, v in results.items()})
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[public_forecast] run failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)[:300]}


#: The outcomes the dead-man accepts for a run while the stream is live (``operational.public_brief_qa``).
SANCTIONED = ("written", "exists")
SANCTIONED_HOLDS = ("inputs_stale", "too_few_readings", "not_served_publicly")


def stamp(table: Any, today: str, result: dict) -> bool:
    """``FORECAST_PK / RUN#<cycle>`` — the run's outcome per rule (overwritten by a re-run of the cycle). Fail-soft: a
    stamp that cannot be written leaves the dead-man to report the gap. A dry run never stamps (the caller's rule)."""
    from datetime import timezone

    cycle = str(result.get("cycle") or BPOL.cycle_of(today))
    row = {
        "pk": POL.FORECAST_PK,
        "sk": POL.run_sk(cycle),
        "forecast_cycle": cycle,
        "run_on": today,
        "status": str(result.get("status") or "unknown"),
        "results": {k: {kk: str(vv) for kk, vv in (v or {}).items()} for k, v in (result.get("results") or {}).items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    for k in ("reason", "error"):
        if result.get(k):
            row[k] = str(result[k])[:300]
    try:
        table.put_item(Item=row)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[public_forecast] run stamp not written for %s: %s", cycle, e)
        return False
