#!/usr/bin/env python3
"""perf_trend.py — persist per-page web-vitals from the visual-QA sweep + a weekly
regression trend line (#1435).

The Playwright sweep (tests/visual_qa.py) already MEASURES LCP, CLS and total JS
bytes per page (capture_page's `perf` dict, gated against the #580 budgets), but
those numbers only ever lived in the run-local qa-screenshots/report.json — the
moment the CI job ended they were gone. So a perf regression was only ever visible
as a single-run pass/fail against a fixed budget; slow drift UNDER the budget (LCP
creeping 300ms → 900ms, JS payload 200KB → 500KB) was invisible. This module makes
it a trend you can see:

  1. persist_run() writes one immutable per-run snapshot of every page's vitals to
         generated/qa_archive/perf/runs/{YYYY-MM-DD}/{HHMMSS}--{uuid8}.json
     (S3, ADR-046 generated/ prefix — CloudFront/site sync can never touch it; the
     existing `qa-archive-expire-90d` lifecycle rule already bounds retention to
     ~97 days at the byte level, no new lifecycle rule needed — see
     deploy/apply_s3_lifecycle.sh).

  2. rollup() reads the last window_days of snapshots, medians each page's metrics
     per ISO week, detects a step-change regression against the trailing baseline,
     and writes the weekly trend line to
         generated/qa_archive/perf/trend.json
     plus a Markdown block for the ops/green report (the CI job summary, E3).

Design mirrors lambdas/qa_archive.py: date-first S3 keys (a week's rollup is 7
prefix listings, no per-page fan-out), boto3 lazy-imported so the pure functions
(snapshot_from_results / build_trend / trend_markdown) import and unit-test with
no AWS and no network, and persist_run is FAIL-SOFT — a lost perf snapshot costs
one log line, it must never red the gating visual-qa sweep it rides inside.

The regression thresholds here are ADVISORY (they annotate the trend + the ops
report); the hard pass/fail gate stays the per-page budget in visual_qa.py. This
is deliberate: the budget catches a cliff on one run, the trend catches a slope
across weeks, and only the budget should ever block a deploy.

Writer IAM: the daily standalone visual-qa sweep assumes github-actions-diagnosis-
role; its scoped grant for generated/qa_archive/perf/* (PutObject/GetObject +
prefix-scoped ListBucket) is staged in
infra/iam/github-actions-diagnosis-role.permissions.json (applied out-of-band,
same runbook as the #1441 screenshot grant). Until it lands the workflow step is
continue-on-error and this module's writes fail-soft — the trend simply doesn't
accrue yet.
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timezone

logger = logging.getLogger("perf_trend")

BUCKET = os.environ.get("BUCKET_NAME", "matthew-life-platform")
PERF_PREFIX = "generated/qa_archive/perf/"
RUNS_PREFIX = PERF_PREFIX + "runs/"
TREND_KEY = PERF_PREFIX + "trend.json"

# The three web-vitals the sweep measures. Higher is worse for all three, so a
# regression is always a positive delta — the detector only flags upward drift.
METRICS = ("lcp_ms", "cls", "js_bytes")

# Advisory step-change thresholds (a page-metric regresses when the latest ISO
# week's median is BOTH proportionally and absolutely worse than the trailing
# baseline — the abs floor keeps a jittery small value, e.g. 40ms→60ms LCP, from
# tripping the 30% relative test as a "regression").
DEFAULT_THRESHOLDS = {
    "lcp_ms_pct": 0.30,  # +30% week-over-baseline
    "lcp_ms_abs_floor": 100.0,  # AND at least +100ms
    "cls_abs": 0.05,  # +0.05 absolute CLS (proportional is meaningless near 0)
    "js_bytes_pct": 0.15,  # +15% JS payload
    "js_bytes_abs_floor": 20_480,  # AND at least +20KB
}

DEFAULT_WINDOW_DAYS = 56  # 8 ISO weeks of history for the trend line

_s3 = None


# ══════════════════════════════════════════════════════════════════════════════
# Pure helpers (no AWS, no network — unit-tested offline)
# ══════════════════════════════════════════════════════════════════════════════


def _median(values):
    """Median of a non-empty numeric list; None for an empty list."""
    xs = sorted(v for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2


def iso_week(date_str):
    """ISO-week label 'YYYY-Www' for a 'YYYY-MM-DD' date (Mon-anchored, ISO 8601)."""
    y, m, d = (int(x) for x in date_str.split("-"))
    iso = date(y, m, d).isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def snapshot_from_results(results, *, now=None, git_sha=None, run_id=None, browser="chromium", site_url=None):
    """Build one per-run perf snapshot dict from a visual_qa run's `results` list.

    Pure: results are the capture_page() dicts (each carries `perf`, `path`,
    `page`). Results with no numeric perf (the leak-token synthetic row, or a
    page whose load failed before the perf read) are skipped — the snapshot only
    records pages that actually produced a measurement.
    """
    now = now or datetime.now(timezone.utc)
    pages = []
    for r in results:
        perf = r.get("perf")
        if not isinstance(perf, dict):
            continue
        lcp = perf.get("lcp_ms")
        cls = perf.get("cls")
        js = perf.get("js_bytes")
        # js_bytes is always present (0 for a page with no external JS); LCP/CLS
        # can be None on an odd load. Keep the row if ANY metric is present.
        if lcp is None and cls is None and (js is None or js == 0):
            continue
        pages.append(
            {
                "path": r.get("path"),
                "page": r.get("page"),
                "lcp_ms": lcp,
                "cls": cls,
                "js_bytes": js if js is not None else 0,
            }
        )
    return {
        "captured_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "git_sha": git_sha or os.environ.get("GITHUB_SHA"),
        "run_id": run_id or os.environ.get("GITHUB_RUN_ID"),
        "browser": browser,
        "site_url": site_url,
        "pages": pages,
    }


def run_key(snapshot):
    """S3 key for a run snapshot: date-first, uniqueified by capture time + uuid8."""
    try:
        ts = datetime.fromisoformat(snapshot["captured_at"])
    except Exception:
        ts = datetime.now(timezone.utc)
    return f"{RUNS_PREFIX}{snapshot['date']}/{ts.strftime('%H%M%S')}--{uuid.uuid4().hex[:8]}.json"


def _weekly_series(snapshots, path, metric):
    """Ordered [{week, median, n, runs}] for one page+metric across the snapshots.

    Groups every measured value by ISO week, medians within the week. `n` is the
    number of contributing values (runs×pages), `runs` the number of distinct run
    snapshots that touched the week (for context in the ops report).
    """
    by_week = {}
    for snap in snapshots:
        wk = iso_week(snap["date"])
        for pg in snap.get("pages", []):
            if pg.get("path") != path:
                continue
            val = pg.get(metric)
            if val is None:
                continue
            slot = by_week.setdefault(wk, {"vals": [], "run_ids": set()})
            slot["vals"].append(val)
            slot["run_ids"].add(snap.get("captured_at"))
    out = []
    for wk in sorted(by_week):
        vals = by_week[wk]["vals"]
        med = _median(vals)
        if med is None:
            continue
        out.append({"week": wk, "median": round(med, 4), "n": len(vals), "runs": len(by_week[wk]["run_ids"])})
    return out


def _detect_regression(series, metric, thresholds):
    """Advisory step-change flag for one page+metric weekly series, or None.

    Compares the latest week's median against the trailing baseline (median of the
    prior weeks' medians). Needs >=2 weeks. Only upward (worse) drift flags.
    """
    if len(series) < 2:
        return None
    latest = series[-1]["median"]
    baseline = _median([p["median"] for p in series[:-1]])
    if baseline is None:
        return None
    delta = latest - baseline
    if delta <= 0:
        return None
    pct = (delta / baseline) if baseline else None
    flagged = False
    if metric == "cls":
        flagged = delta >= thresholds["cls_abs"]
    elif metric == "lcp_ms":
        flagged = (pct is not None and pct >= thresholds["lcp_ms_pct"]) and delta >= thresholds["lcp_ms_abs_floor"]
    elif metric == "js_bytes":
        flagged = (pct is not None and pct >= thresholds["js_bytes_pct"]) and delta >= thresholds["js_bytes_abs_floor"]
    if not flagged:
        return None
    return {
        "metric": metric,
        "baseline": round(baseline, 4),
        "latest": round(latest, 4),
        "delta": round(delta, 4),
        "pct": round(pct, 4) if pct is not None else None,
        "baseline_week": series[0]["week"],
        "latest_week": series[-1]["week"],
    }


def build_trend(snapshots, *, now=None, window_days=DEFAULT_WINDOW_DAYS, thresholds=None):
    """Compute the weekly trend line + advisory regressions from run snapshots.

    Pure. `snapshots` is a list of snapshot_from_results() dicts (any order). Only
    snapshots within `window_days` of `now` are used. Returns the trend dict that
    is written to generated/qa_archive/perf/trend.json.
    """
    now = now or datetime.now(timezone.utc)
    thresholds = thresholds or DEFAULT_THRESHOLDS
    cutoff = now.date().toordinal() - window_days

    windowed = []
    for snap in snapshots:
        try:
            d = date(*(int(x) for x in snap["date"].split("-")))
        except Exception:
            continue
        if d.toordinal() >= cutoff:
            windowed.append(snap)

    # Every page path seen anywhere in the window.
    paths = sorted({pg.get("path") for snap in windowed for pg in snap.get("pages", []) if pg.get("path")})
    weeks = sorted({iso_week(snap["date"]) for snap in windowed})

    pages = {}
    regressions = []
    for path in paths:
        entry = {"metrics": {}, "regressions": {}}
        for metric in METRICS:
            series = _weekly_series(windowed, path, metric)
            entry["metrics"][metric] = series
            reg = _detect_regression(series, metric, thresholds)
            entry["regressions"][metric] = reg
            if reg:
                regressions.append({"path": path, **reg})
        pages[path] = entry

    # Site-level series: median across pages of each week's per-page medians.
    site = {}
    for metric in METRICS:
        by_week = {}
        for path in paths:
            for pt in pages[path]["metrics"][metric]:
                by_week.setdefault(pt["week"], []).append(pt["median"])
        site[metric] = [{"week": wk, "median": round(_median(by_week[wk]), 4)} for wk in sorted(by_week) if by_week[wk]]

    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "weeks": weeks,
        "run_count": len(windowed),
        "thresholds": thresholds,
        "site": site,
        "pages": pages,
        "regressions": regressions,
    }


def _fmt(metric, value):
    if value is None:
        return "—"
    if metric == "lcp_ms":
        return f"{value:.0f}ms"
    if metric == "cls":
        return f"{value:.3f}"
    if metric == "js_bytes":
        return f"{value / 1024:.0f}KB"
    return str(value)


def trend_markdown(trend):
    """Render the weekly trend line as a Markdown block for the ops/green report (E3)."""
    weeks = trend.get("weeks", [])
    regs = trend.get("regressions", [])
    lines = ["## Perf trend — LCP / CLS / JS-bytes (#1435)"]
    lines.append(
        f"_{trend.get('run_count', 0)} run(s) across {len(weeks)} ISO week(s); "
        f"advisory — the hard gate stays the per-page budget in visual_qa.py._\n"
    )
    if regs:
        lines.append(f"### ⚠️ {len(regs)} advisory regression(s) vs trailing baseline")
        for r in regs:
            pct = f" ({r['pct'] * 100:+.0f}%)" if r.get("pct") is not None else ""
            lines.append(
                f"- **{r['path']}** · `{r['metric']}` {_fmt(r['metric'], r['baseline'])} → "
                f"{_fmt(r['metric'], r['latest'])}{pct} (baseline {r['baseline_week']} → {r['latest_week']})"
            )
    else:
        lines.append("### ✅ No advisory regressions")
    # Site-level line per metric (latest vs first week in window).
    lines.append("\n### Site median by metric (first → latest week)")
    for metric in METRICS:
        series = trend.get("site", {}).get(metric, [])
        if not series:
            continue
        first, last = series[0], series[-1]
        lines.append(f"- `{metric}`: {_fmt(metric, first['median'])} ({first['week']}) → {_fmt(metric, last['median'])} ({last['week']})")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# S3 side (boto3 lazy-imported; all fail-soft)
# ══════════════════════════════════════════════════════════════════════════════


def _get_s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config

        _s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}))
    return _s3


def persist_run(snapshot, *, bucket=None):
    """Write one run snapshot to S3. FAIL-SOFT — logs + returns a status, never raises.

    Returns {"ok": bool, "key": str|None, "error": str|None, "pages": int}.
    """
    bucket = bucket or BUCKET
    if not snapshot.get("pages"):
        logger.warning("perf_trend.persist_run: snapshot has no measured pages — nothing to persist")
        return {"ok": False, "key": None, "error": "no_pages", "pages": 0}
    key = run_key(snapshot)
    try:
        _get_s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(snapshot, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("perf_trend: persisted %d page(s) → s3://%s/%s", len(snapshot["pages"]), bucket, key)
        return {"ok": True, "key": key, "error": None, "pages": len(snapshot["pages"])}
    except Exception as e:  # noqa: BLE001 — fail-soft by contract
        logger.warning("perf_trend.persist_run: S3 write failed (advisory, non-gating): %s", e)
        return {"ok": False, "key": key, "error": str(e), "pages": len(snapshot["pages"])}


def load_recent_runs(*, bucket=None, window_days=DEFAULT_WINDOW_DAYS, now=None):
    """List + read run snapshots within window_days. FAIL-SOFT — returns [] on error.

    Lists only the date prefixes inside the window (date-first keys), so a 90-day
    archive never lists more than window_days worth of objects.
    """
    bucket = bucket or BUCKET
    now = now or datetime.now(timezone.utc)
    s3 = _get_s3()
    snapshots = []
    try:
        for offset in range(window_days + 1):
            day = date.fromordinal(now.date().toordinal() - offset).strftime("%Y-%m-%d")
            token = None
            while True:
                kwargs = {"Bucket": bucket, "Prefix": f"{RUNS_PREFIX}{day}/"}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = s3.list_objects_v2(**kwargs)
                for obj in resp.get("Contents", []):
                    try:
                        body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                        snapshots.append(json.loads(body))
                    except Exception as e:  # noqa: BLE001
                        logger.warning("perf_trend: skipping unreadable snapshot %s: %s", obj["Key"], e)
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
    except Exception as e:  # noqa: BLE001 — fail-soft
        logger.warning("perf_trend.load_recent_runs: list/read failed (advisory): %s", e)
    return snapshots


def write_trend(trend, *, bucket=None):
    """Write trend.json to S3. FAIL-SOFT."""
    bucket = bucket or BUCKET
    try:
        _get_s3().put_object(
            Bucket=bucket,
            Key=TREND_KEY,
            Body=json.dumps(trend, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("perf_trend: wrote trend line → s3://%s/%s (%d regression(s))", bucket, TREND_KEY, len(trend.get("regressions", [])))
        return {"ok": True, "key": TREND_KEY, "error": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("perf_trend.write_trend: S3 write failed (advisory): %s", e)
        return {"ok": False, "key": TREND_KEY, "error": str(e)}


def rollup(*, bucket=None, window_days=DEFAULT_WINDOW_DAYS, now=None):
    """Load recent runs → build the weekly trend → write trend.json. Returns the trend."""
    snapshots = load_recent_runs(bucket=bucket, window_days=window_days, now=now)
    trend = build_trend(snapshots, now=now, window_days=window_days)
    write_trend(trend, bucket=bucket)
    return trend


def _results_from_report(report_path):
    """Read a visual_qa qa-screenshots/report.json and return (results, browser, site_url)."""
    with open(report_path) as f:
        report = json.load(f)
    return report.get("results", []), report.get("browser", "chromium"), None


# ══════════════════════════════════════════════════════════════════════════════
# CLI — wired into the daily standalone visual-qa workflow (#1435)
# ══════════════════════════════════════════════════════════════════════════════


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Persist visual-QA perf vitals + weekly regression trend (#1435)")
    ap.add_argument("--from-report", help="Path to a visual_qa report.json to persist this run's per-page vitals from")
    ap.add_argument("--persist", action="store_true", help="Write this run's snapshot to S3 (needs --from-report)")
    ap.add_argument("--rollup", action="store_true", help="Rebuild generated/qa_archive/perf/trend.json from recent snapshots")
    ap.add_argument("--bucket", default=BUCKET, help="Override the S3 bucket (default: %(default)s)")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="Trend window (default: %(default)s)")
    args = ap.parse_args(argv)

    if args.persist:
        if not args.from_report:
            print("--persist needs --from-report", file=sys.stderr)
            return 2
        results, browser, site_url = _results_from_report(args.from_report)
        snap = snapshot_from_results(results, browser=browser, site_url=site_url)
        status = persist_run(snap, bucket=args.bucket)
        print(f"persist: ok={status['ok']} pages={status['pages']} key={status['key']} err={status['error']}")

    if args.rollup:
        trend = rollup(bucket=args.bucket, window_days=args.window_days)
        md = trend_markdown(trend)
        print("\n" + md)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            try:
                with open(summary_path, "a") as f:
                    f.write("\n" + md)
            except Exception as e:  # noqa: BLE001
                logger.warning("perf_trend: could not append to GITHUB_STEP_SUMMARY: %s", e)

    if not (args.persist or args.rollup):
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
