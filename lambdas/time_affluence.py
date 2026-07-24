"""lambdas/time_affluence.py — the Time Affluence Meter proxy (#1408, epic #718).

Time poverty carries an unemployment-scale wellbeing hit (Whillans 2017), and the
platform measured *nothing* about it — the calendar tools that could have measured
it directly were retired (ADR-030) and re-integration is explicitly out of scope.
So this is a **PROXY, not a measurement**: it triangulates three deterministic
behavioural traces that co-vary with time pressure, plus one weekly self-report
anchor, into a single standardised weekly index. It is labelled as a proxy
everywhere it surfaces and it publishes its own construction + limitations
(`docs/methods/TIME_AFFLUENCE_PROXY.md`).

Honest-numbers posture (this module is pure math; it never calls an LLM):

* **ADR-104 (behavioural-absence semantics).** A skipped weekly probe, or a trace
  with no data that week, is a **coverage gap** — it drops out of the blend and out
  of `n`, it is **never scored 0**. Zeroing a missing self-report would fabricate a
  "time-poor" reading out of silence. This mirrors `fulfillment_index` (measured
  absence shrinks the denominator) and is the opposite of the character engine's
  *behavioural* absence (an unlogged habit there IS a miss = 0). A self-report you
  didn't give is not evidence of anything.
* **ADR-105 (the rigor bar).** Every component is standardised against Matthew's
  OWN distribution over the window (personal variance, rule 4 — no hand-set
  cutoffs). The candidate edge (edge-week time-affluence -> next-week adherence)
  is tested deterministically with `stats_core` (Pearson r, autocorrelation-
  corrected effective n, Fisher CI) and BH-FDR-corrected across the lag family
  (rule 1: uncertainty + n on every claim). Below the evidence floor the edge is
  tagged **descriptive only**, never asserted.

Nothing here writes to DynamoDB or reads S3 — the compute host (the weekly
hypothesis engine, `lambdas/compute/hypothesis_engine_lambda.py`) fetches the
partitions, calls these pure functions, and persists the Decimal-cast items.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from decimal import Decimal

import stats_core

# ── Construction constants (documented in docs/methods/TIME_AFFLUENCE_PROXY.md) ──

PROXY_WINDOW_WEEKS = 12  # rolling window: weekly proxies + the lagged edge test
COMPONENT_COVERAGE_FLOOR = 0.5  # a week needs >= half its components to emit a number
TRACE_MIN_WEEKS = 4  # a trace needs >= this many weeks of history to standardise honestly
EDGE_MIN_N_EFF = 6.0  # weeks of effective n below which the edge is descriptive-only
EDGE_CONFIDENCE = 0.95

# The three passive traces + the one self-report anchor. Order is the published
# component order; each is oriented so that HIGHER == MORE time-affluent.
TRACE_OPEN_LOAD = "todoist_open_load"  # rising open task load -> less time affluence (sign flipped)
TRACE_RITUAL_REGULARITY = "evening_regularity"  # steadier evening cadence -> more structured, unhurried time
TRACE_UNSCHEDULED = "unscheduled_days"  # more obligation-free days -> more discretionary time
PROBE_COMPONENT = "felt_time"  # the weekly 1-item self-report (0-4), when present

COMPONENTS = (TRACE_OPEN_LOAD, TRACE_RITUAL_REGULARITY, TRACE_UNSCHEDULED, PROBE_COMPONENT)

TIME_AFFLUENCE_SOURCE = "time_affluence"  # DDB: USER#matthew#SOURCE#time_affluence


# ── Decimal-safe scalar coercion (mirrors vacation_fund._f / digest_utils) ──────


def _f(val) -> float | None:
    """None-preserving float coercion. Returns None (not 0.0) for missing/garbage
    so an absent value can never masquerade as a real 0."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── Week bucketing ──────────────────────────────────────────────────────────────


def week_key(date_str: str) -> str | None:
    """Map a YYYY-MM-DD day to the Sunday (weekday 6) that closes its Mon-Sun week.

    The weekly probe is asked on Sunday ("this week: ..."), so a week is keyed by
    its closing Sunday and every day Mon-Sun folds into it. Returns None on a
    malformed date rather than raising (fail-soft over dirty rows)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    sunday = d + timedelta(days=(6 - d.weekday()) % 7)
    return sunday.isoformat()


def _bucket_by_week(rows: list[dict]) -> dict[str, list[dict]]:
    """Group DATE#-scheme rows by their closing-Sunday week key. Rows must carry a
    `date` field (the query helper stamps it) or a `sk` of the form DATE#YYYY-MM-DD."""
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        ds = r.get("date")
        if not ds:
            sk = r.get("sk", "")
            ds = sk[5:15] if sk.startswith("DATE#") else None
        wk = week_key(ds) if ds else None
        if wk is None:
            continue
        buckets.setdefault(wk, []).append(r)
    return buckets


# ── The three deterministic passive traces (per-week raw signals) ────────────────
# Each returns a float in the trace's native units, or None when that week has no
# usable data for it. Orientation to "higher == more affluent" happens later at
# standardisation (open-load is flipped there).


def week_open_load(todoist_week_rows: list[dict]) -> float | None:
    """Mean daily open task load for the week (active + overdue). Rising open load
    is the time-pressure signal; higher raw value == LESS time affluence (the sign
    is flipped when standardised). None when the week has no Todoist rows."""
    loads = []
    for r in todoist_week_rows:
        active = _f(r.get("active_count"))
        overdue = _f(r.get("overdue_count")) or 0.0
        if active is None:
            continue
        loads.append(active + overdue)
    if not loads:
        return None
    return statistics.fmean(loads)


def _minute_of_day(ts_iso: str) -> float | None:
    """Minutes-past-midnight from an ISO timestamp; None on parse failure."""
    if not ts_iso:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            t = datetime.strptime(ts_iso, fmt)
            return t.hour * 60.0 + t.minute
        except (TypeError, ValueError):
            continue
    return None


def week_evening_regularity(ritual_week_rows: list[dict]) -> float | None:
    """Regularity of the evening ritual's completion time across the week.

    Uses the `connection_logged_at` timestamp (the anchor tap of the daily ritual)
    as a marker of when the evening wound down. A steadier completion time (low
    spread) reads as a more structured, unhurried evening — a behavioural correlate
    of time affluence. Returns the NEGATIVE standard-deviation-in-minutes so that
    HIGHER == MORE regular == more affluent (sign already oriented). Needs >= 3
    timestamped evenings in the week to have a spread at all; else None (coverage
    gap, not 0)."""
    minutes = []
    for r in ritual_week_rows:
        m = _minute_of_day(r.get("connection_logged_at") or r.get("mood_valence_logged_at"))
        if m is not None:
            minutes.append(m)
    if len(minutes) < 3:
        return None
    return -statistics.pstdev(minutes)


def week_unscheduled_days(todoist_week_rows: list[dict]) -> float | None:
    """Fraction of the week's observed days that carried NO scheduled obligation —
    inferred from Todoist's `due_today_count == 0`. An obligation-free day is a day
    with discretionary time; more of them across the week reads as more time
    affluence. Only days we actually observed a Todoist row for count toward the
    denominator (absence of the source is a coverage gap, not a scheduled day).
    None when no day that week had an observable due-count."""
    observed = 0
    unscheduled = 0
    for r in todoist_week_rows:
        due = _f(r.get("due_today_count"))
        if due is None:
            continue
        observed += 1
        if due <= 0:
            unscheduled += 1
    if observed == 0:
        return None
    return unscheduled / observed


def week_probe(probe_week_rows: list[dict]) -> float | None:
    """The weekly 1-item self-report `felt_time` (0-4), if it was answered that
    week. A skipped probe returns None — a coverage gap, NEVER a 0 (ADR-104: a
    self-report you didn't give is not a low reading)."""
    for r in probe_week_rows:
        v = _f(r.get(PROBE_COMPONENT))
        if v is not None:
            return v
    return None


# ── Standardisation against Matthew's own distribution (ADR-105 rule 4) ──────────


def _zscore_series(values: list[float | None]) -> list[float | None]:
    """Standardise a per-week trace against its own non-missing values (personal
    variance). Missing weeks stay None (they never become 0). A trace with fewer
    than TRACE_MIN_WEEKS observed values, or zero variance, is returned as all-None
    — it is not calibratable honestly, so it drops out of every week's blend."""
    present = [v for v in values if v is not None]
    if len(present) < TRACE_MIN_WEEKS:
        return [None] * len(values)
    mu = statistics.fmean(present)
    sigma = statistics.pstdev(present)
    if sigma == 0:
        return [None] * len(values)
    return [None if v is None else (v - mu) / sigma for v in values]


# ── The composite weekly proxy ───────────────────────────────────────────────────


def compute_weekly_proxies(
    todoist_rows: list[dict],
    ritual_rows: list[dict],
    probe_rows: list[dict],
) -> list[dict]:
    """Build the standardised weekly Time-Affluence proxy series over the window.

    Returns one dict per week (chronological), each carrying: the week key, every
    component's standardised value (or None), the blended composite (or None below
    the coverage floor), the coverage fraction, and an honest `state`. Absent
    components DROP from the blend and shrink coverage — they are never 0."""
    td = _bucket_by_week(todoist_rows)
    rt = _bucket_by_week(ritual_rows)
    pr = _bucket_by_week(probe_rows)
    weeks = sorted(set(td) | set(rt) | set(pr))

    # Raw per-week trace values (native units), keyed by component.
    raw: dict[str, list[float | None]] = {
        TRACE_OPEN_LOAD: [week_open_load(td.get(w, [])) for w in weeks],
        TRACE_RITUAL_REGULARITY: [week_evening_regularity(rt.get(w, [])) for w in weeks],
        TRACE_UNSCHEDULED: [week_unscheduled_days(td.get(w, [])) for w in weeks],
        PROBE_COMPONENT: [week_probe(pr.get(w, [])) for w in weeks],
    }
    # Standardise each component against its own window distribution. Open-load's
    # raw value rises with time PRESSURE, so flip it: higher z == more affluent.
    std: dict[str, list[float | None]] = {}
    for comp, series in raw.items():
        z = _zscore_series(series)
        if comp == TRACE_OPEN_LOAD:
            z = [None if v is None else -v for v in z]
        std[comp] = z

    n_components = len(COMPONENTS)
    out = []
    for i, w in enumerate(weeks):
        present = {c: std[c][i] for c in COMPONENTS if std[c][i] is not None}
        coverage = len(present) / n_components
        row = {
            "week": w,
            "components": {c: round(std[c][i], 4) for c in COMPONENTS if std[c][i] is not None},
            "components_absent": [c for c in COMPONENTS if std[c][i] is None],
            "coverage": round(coverage, 3),
            "probe_answered": raw[PROBE_COMPONENT][i] is not None,
        }
        if coverage < COMPONENT_COVERAGE_FLOOR or not present:
            # Not enough signal to state a number honestly — emit NO score.
            row["score"] = None
            row["state"] = "insufficient_signal"
        else:
            row["score"] = round(statistics.fmean(present.values()), 4)
            row["state"] = "scored"
        out.append(row)
    return out


# ── The candidate edge: edge-week time-affluence -> next-week adherence ───────────


def weekly_adherence(habit_rows: list[dict]) -> dict[str, float]:
    """Weekly adherence = mean of daily `habitify.completion_pct` over the week
    (0..1). Weeks with no habit rows are simply absent from the map (coverage gap)."""
    buckets = _bucket_by_week(habit_rows)
    out = {}
    for wk, rows in buckets.items():
        vals = [v for v in (_f(r.get("completion_pct")) for r in rows) if v is not None]
        if vals:
            out[wk] = statistics.fmean(vals)
    return out


def _sunday_offset(week_key_str: str, weeks_ahead: int) -> str:
    d = datetime.strptime(week_key_str, "%Y-%m-%d").date() + timedelta(weeks=weeks_ahead)
    return d.isoformat()


def test_edge(proxy_weeks: list[dict], adherence: dict[str, float], lags=(0, 1)) -> dict:
    """Deterministically test time-affluence -> adherence at each lag (in weeks),
    then BH-FDR-correct the p-values across the lag family (ADR-105 rule 1).

    lag 0 is the contemporaneous control; lag 1 is the pre-registered hypothesis
    (edge-week affluence predicting NEXT week's adherence). Each lag reports r,
    raw n, autocorrelation-corrected n_eff, p (on n_eff), Fisher CI, and a verdict.
    Below EDGE_MIN_N_EFF effective weeks a lag is `descriptive` — reported with its
    uncertainty but never asserted as an effect."""
    scored = {w["week"]: w["score"] for w in proxy_weeks if w.get("score") is not None}
    results = []
    for lag in lags:
        xs, ys = [], []
        for wk, score in scored.items():
            target_week = _sunday_offset(wk, lag)
            if target_week in adherence:
                xs.append(score)
                ys.append(adherence[target_week])
        n = len(xs)
        r = stats_core.pearson_r(xs, ys, min_n=3) if n >= 3 else None
        n_eff = stats_core.effective_sample_size(xs, ys) if n >= 3 else float(n)
        p = stats_core.pearson_p_value(r, n_eff) if r is not None else None
        ci = stats_core.fisher_ci(r, n_eff, confidence=EDGE_CONFIDENCE) if r is not None else None
        results.append(
            {
                "lag_weeks": lag,
                "label": "next_week_adherence" if lag == 1 else "same_week_adherence" if lag == 0 else f"lag{lag}w_adherence",
                "n": n,
                "n_eff": round(n_eff, 3) if n >= 3 else float(n),
                "r": round(r, 4) if r is not None else None,
                "p": p,
                "ci": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            }
        )
    # BH-FDR across the family of lag tests.
    qvals = stats_core.bh_fdr([res["p"] for res in results])
    for res, q in zip(results, qvals):
        res["p_fdr"] = round(q, 4) if q is not None else None
        below_floor = res["n_eff"] < EDGE_MIN_N_EFF
        if below_floor or res["r"] is None:
            res["verdict"] = "descriptive"  # reported with uncertainty, not asserted (ADR-105 rule 1)
        elif res["p_fdr"] is not None and res["p_fdr"] < 0.05:
            res["verdict"] = "supported_positive" if res["r"] > 0 else "supported_negative"
        else:
            res["verdict"] = "no_effect"
    return {
        "edge": "time_affluence -> adherence",
        "lags": results,
        "n_weeks_scored": len(scored),
        "method": "pearson_r on personal-variance z-scores; n_eff via AR(1)/Bartlett; BH-FDR across lags (stats_core, ADR-105)",
        "is_proxy": True,
    }


# ── DDB item builders (the host casts floats->Decimal via numeric.floats_to_decimal) ──


def _dec(val) -> Decimal | None:
    """float -> Decimal via str (the sanctioned path); None-preserving."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def build_proxy_item(week_row: dict, user_id: str = "matthew", computed_at: str | None = None) -> dict:
    """DDB item for one week's proxy: pk USER#<u>#SOURCE#time_affluence, sk PROXY#<sunday>.
    Numbers are pre-cast to Decimal here; None score/absent lists are preserved so
    the absence is legible on read."""
    item = {
        "pk": f"USER#{user_id}#SOURCE#{TIME_AFFLUENCE_SOURCE}",
        "sk": f"PROXY#{week_row['week']}",
        "week": week_row["week"],
        "score": _dec(week_row.get("score")),
        "state": week_row.get("state"),
        "coverage": _dec(week_row.get("coverage")),
        "components": {k: _dec(v) for k, v in (week_row.get("components") or {}).items()},
        "components_absent": list(week_row.get("components_absent") or []),
        "probe_answered": bool(week_row.get("probe_answered")),
        "is_proxy": True,
    }
    if computed_at:
        item["computed_at"] = computed_at
    return item


def build_edge_item(edge_result: dict, week_key_str: str, user_id: str = "matthew", computed_at: str | None = None) -> dict:
    """DDB item for the weekly edge test: sk EDGE#<sunday>. Every reported number
    carries its n/n_eff/CI/FDR-q — an ADR-105 statistical claim, deterministic."""
    lags = []
    for res in edge_result.get("lags", []):
        lags.append(
            {
                "lag_weeks": _dec(res.get("lag_weeks")),
                "label": res.get("label"),
                "n": _dec(res.get("n")),
                "n_eff": _dec(res.get("n_eff")),
                "r": _dec(res.get("r")),
                "p": _dec(res.get("p")),
                "p_fdr": _dec(res.get("p_fdr")),
                "ci": [_dec(res["ci"][0]), _dec(res["ci"][1])] if res.get("ci") else None,
                "verdict": res.get("verdict"),
            }
        )
    item = {
        "pk": f"USER#{user_id}#SOURCE#{TIME_AFFLUENCE_SOURCE}",
        "sk": f"EDGE#{week_key_str}",
        "week": week_key_str,
        "edge": edge_result.get("edge"),
        "lags": lags,
        "n_weeks_scored": _dec(edge_result.get("n_weeks_scored")),
        "method": edge_result.get("method"),
        "is_proxy": True,
    }
    if computed_at:
        item["computed_at"] = computed_at
    return item
