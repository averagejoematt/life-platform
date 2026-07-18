"""lambdas/intake_response.py — the private evening-intake dose-response engine (#1405).

Pairs each logged evening's intake count (USER#matthew#SOURCE#private_intake,
one-tap 0–4 from the evening nudge / MCP) with the NEXT morning's physiology —
whoop's DATE#(D+1) record scores the night D→D+1, so intake on evening D lands
on the D+1 record's hrv / recovery_score / rem_sleep_hours.

Statistics per ADR-105 (all via stats_core, the one sanctioned implementation):
  - Pearson r on (count, next-day metric) with raw n AND Pyper–Peterman
    effective n; p-value computed on n_eff, never raw n.
  - Zero-vs-nonzero evenings: moving-block-bootstrap CI for the mean difference
    (autocorrelation-preserving), with per-arm n.
  - A dose-response view (bins 0 / 1 / 2+) arms only once
    DOSE_RESPONSE_MIN_NONZERO nonzero evenings exist — below that the payload
    carries the arming progress instead (never a curve fitted on air).

PRIVACY (#1405 hard gate): consumed by MCP tools + the daily brief ONLY. No
web/ handler, site file, or generated public artifact may import or serve this —
tests/test_intake_privacy_contract.py enforces the boundary in both directions.
"""

import logging
from datetime import datetime, timedelta, timezone

import stats_core
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()

PRIVATE_INTAKE_PK = "USER#matthew#SOURCE#private_intake"
WHOOP_PK = "USER#matthew#SOURCE#whoop"

# The dose-response curve needs real support before it may render (#1405: "a
# personal dose-response curve becomes possible after ~15 non-zero evenings").
DOSE_RESPONSE_MIN_NONZERO = 15
# Floor for any correlation/diff line at all — below this the payload is
# arming-progress only (mirrors stats_core's bootstrap per-arm floor).
MIN_PAIRS = 5

# Next-day metrics the ledger grades against (whoop record fields).
RESPONSE_METRICS = ("hrv", "recovery_score", "rem_sleep_hours")


def _to_float(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def fetch_intake_by_date(table, window_days=180, today=None):
    """{date_str: count} for logged evenings in the trailing window.

    Cross-cycle by design: the physiology of an evening intake does not reset
    with the experiment (raw_timeseries class, ADR-077), so the window spans
    genesis boundaries.
    """
    today = today or datetime.now(timezone.utc).date()
    start = (today - timedelta(days=window_days)).isoformat()
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(PRIVATE_INTAKE_PK) & Key("sk").gte(f"DATE#{start}"),
    )
    out = {}
    for it in resp.get("Items", []):
        d = str(it.get("sk", "")).replace("DATE#", "")[:10]
        c = _to_float(it.get("intake_count"))
        if d and c is not None:
            out[d] = c
    return out


def fetch_next_day_metrics(table, intake_dates):
    """{intake_date: {metric: value}} from each date's NEXT-morning whoop record."""
    out = {}
    for d in intake_dates:
        try:
            nxt = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            continue
        item = table.get_item(Key={"pk": WHOOP_PK, "sk": f"DATE#{nxt}"}).get("Item")
        if not item:
            continue
        vals = {m: _to_float(item.get(m)) for m in RESPONSE_METRICS}
        if any(v is not None for v in vals.values()):
            out[d] = vals
    return out


def pair_series(intake_by_date, metrics_by_date, metric):
    """Chronologically-ordered (count, next-day metric) pairs for one metric.

    Pure — the unit-testable core. Order matters: the block bootstrap and the
    lag-1 autocorrelation correction both assume time order.
    """
    xs, ys = [], []
    for d in sorted(intake_by_date):
        v = (metrics_by_date.get(d) or {}).get(metric)
        if v is None:
            continue
        xs.append(intake_by_date[d])
        ys.append(v)
    return xs, ys


def _metric_block(xs, ys):
    """The per-metric statistics block (ADR-105: r + n + n_eff + p-on-n_eff +
    zero-vs-nonzero bootstrap CI). None when below the MIN_PAIRS floor."""
    if len(xs) < MIN_PAIRS:
        return None
    n = len(xs)
    n_eff = stats_core.effective_sample_size(xs, ys)
    r = stats_core.pearson_r(xs, ys, min_n=MIN_PAIRS)
    p = stats_core.pearson_p_value(r, n_eff) if r is not None else None
    zero = [y for x, y in zip(xs, ys) if x == 0]
    nonzero = [y for x, y in zip(xs, ys) if x > 0]
    diff_ci = stats_core.bootstrap_mean_diff_ci(zero, nonzero)  # nonzero minus zero
    block = {
        "n": n,
        "n_eff": round(n_eff, 1),
        "r": r,
        "p": p,
        "n_zero": len(zero),
        "n_nonzero": len(nonzero),
        "zero_mean": round(sum(zero) / len(zero), 2) if zero else None,
        "nonzero_mean": round(sum(nonzero) / len(nonzero), 2) if nonzero else None,
    }
    if diff_ci is not None:
        lo, hi = diff_ci
        block["diff"] = round(block["nonzero_mean"] - block["zero_mean"], 2)
        block["diff_ci95"] = [round(lo, 2), round(hi, 2)]
        block["ci_excludes_zero"] = bool(lo > 0 or hi < 0)
    return block


def _dose_bins(intake_by_date, metrics_by_date):
    """Mean next-day metrics binned by dose (0 / 1 / 2+), each with its n."""
    bins = {"0": [], "1": [], "2+": []}
    for d, c in intake_by_date.items():
        vals = metrics_by_date.get(d)
        if not vals:
            continue
        key = "0" if c == 0 else ("1" if c == 1 else "2+")
        bins[key].append(vals)
    out = []
    for key in ("0", "1", "2+"):
        rows = bins[key]
        entry = {"dose": key, "n": len(rows)}
        for m in RESPONSE_METRICS:
            vs = [r[m] for r in rows if r.get(m) is not None]
            entry[f"{m}_mean"] = round(sum(vs) / len(vs), 2) if vs else None
        out.append(entry)
    return out


def compute_intake_response(table, window_days=180, today=None):
    """The full private payload for MCP / the daily brief. Never raises on thin
    data — an unarmed instrument reports its arming progress (ADR-104/105)."""
    intake = fetch_intake_by_date(table, window_days=window_days, today=today)
    nonzero_evenings = sum(1 for c in intake.values() if c > 0)
    payload = {
        "window_days": window_days,
        "logged_evenings": len(intake),
        "nonzero_evenings": nonzero_evenings,
        "arming": {
            "min_pairs": MIN_PAIRS,
            "dose_response_min_nonzero": DOSE_RESPONSE_MIN_NONZERO,
            "current_nonzero": nonzero_evenings,
        },
        "metrics": {},
        "dose_response": None,
        "_notice": "Matthew-private (#1405). N=1 observational; lagged association, never causal.",
    }
    if not intake:
        return payload
    metrics_by_date = fetch_next_day_metrics(table, list(intake))
    for m in RESPONSE_METRICS:
        xs, ys = pair_series(intake, metrics_by_date, m)
        block = _metric_block(xs, ys)
        if block is not None:
            payload["metrics"][m] = block
    if nonzero_evenings >= DOSE_RESPONSE_MIN_NONZERO:
        payload["dose_response"] = _dose_bins(intake, metrics_by_date)
    return payload


def brief_line(payload):
    """One private daily-brief line, or None when there is nothing honest to say.

    ADR-105: every rendered claim carries n + CI. Below the floors the line is
    the arming progress, so the brief never fabricates an early verdict.
    """
    if not payload or not payload.get("logged_evenings"):
        return None
    hrv = (payload.get("metrics") or {}).get("hrv")
    if hrv and hrv.get("diff_ci95"):
        lo, hi = hrv["diff_ci95"]
        verdict = "" if hrv.get("ci_excludes_zero") else " — could be nothing yet"
        line = (
            f"Evening-intake ledger: nonzero evenings shift next-day HRV {hrv['diff']:+.1f} ms "
            f"[95% CI {lo:+.1f}, {hi:+.1f}] vs zero evenings (n={hrv['n_zero']}+{hrv['n_nonzero']}, "
            f"n_eff={hrv['n_eff']}){verdict}."
        )
        dr = payload.get("dose_response")
        if dr is None:
            need = payload["arming"]["dose_response_min_nonzero"]
            line += f" Dose-response arms at {need} nonzero evenings — currently {payload['nonzero_evenings']}/{need}."
        return line
    need = max(payload["arming"]["min_pairs"], 1)
    return (
        f"Evening-intake ledger arming: {payload['logged_evenings']} evening(s) logged "
        f"({payload['nonzero_evenings']} nonzero) — first paired read at {need} evenings with next-morning data."
    )
