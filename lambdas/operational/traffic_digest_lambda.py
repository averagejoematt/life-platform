"""
traffic_digest_lambda.py — privacy-clean weekly traffic digest.

Reads CloudFront standard access logs (the site's own first-party server logs —
no cookies, no client JS, no third party) from the log bucket, aggregates the
past 7 days, and emails a digest: total page views, unique + returning visitors,
top pages, and where external traffic comes from (e.g. Reddit). This is the
instrument for the returnability goal (docs/PLATFORM_NORTH_STAR.md).

It also carries a "Travel watch" section (#741): per-page views + referrer
domains for the WATCHED_PAGES list (currently the career essay), so a published
artifact's travel is measurable even when it isn't in the site-wide top-15.

PRIVACY (matches the no-tracking ethos):
  • Source is CloudFront access logs — standard infrastructure logging, NOT
    tracking cookies or third-party analytics.
  • IP addresses are hashed in memory ONLY to count distinct/returning visitors,
    then discarded. No raw IP is ever stored, logged, or emailed.
  • Output is aggregate counts only.

Schedule: weekly (Mondays). Reuses the SES email pattern. No external deps.

Also emits the 7-day unique/page-view counts as CloudWatch metrics
(LifePlatform/Traffic::UniqueVisitors7d / PageViews7d) — the cost_governor
Lambda reads the latest UniqueVisitors7d datapoint to decide whether reader
traffic has crossed the surge-mode threshold (ADR-133, #739).
"""

import gzip
import hashlib
import io
import json
import logging
import os
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
LOG_BUCKET = os.environ.get("LOG_BUCKET", "")
LOG_PREFIX = os.environ.get("LOG_PREFIX", "cf/")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")
SITE_HOST = os.environ.get("SITE_HOST", "averagejoematt.com")
DAYS = int(os.environ.get("DIGEST_DAYS", "7"))

# Travel watch (#741): published artifacts whose reach we want measured every week
# regardless of whether they crack the site-wide top-15 — per-page views plus WHERE
# that page's readers came from (external referrer domains), so a submission (e.g.
# Hacker News) is attributable to the artifact itself, not just the site total.
# Comma-separated env override; the default tracks the career essay.
WATCHED_PAGES = [p.strip() for p in os.environ.get("WATCHED_PAGES", "/journal/essays/org-chart-of-one/").split(",") if p.strip()]

# Link-preview + crawler agents — real fetches, but not human visitors.
_BOT_RE = (
    "bot",
    "crawl",
    "spider",
    "slurp",
    "bingpreview",
    "facebookexternalhit",
    "headless",
    "monitor",
    "uptime",
    "curl",
    "wget",
    "python-requests",
    "go-http",
    "okhttp",
    "scrapy",
    "semrush",
    "ahrefs",
    "dataprovider",
    "feedfetcher",
)
# Asset/api/file extensions that aren't "pages a person read".
_NON_PAGE = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".json",
    ".xml",
    ".txt",
    ".webmanifest",
    ".map",
    ".mp3",
    ".wav",
)


def _ipkey(ip: str, ua: str) -> str:
    """One-way visitor key for distinct/returning counts — never stored/emitted."""
    return hashlib.sha256(f"{ip}|{ua}".encode("utf-8", "ignore")).hexdigest()[:16]


def _is_bot(ua: str) -> bool:
    u = ua.lower()
    return any(b in u for b in _BOT_RE)


def _is_page(uri: str) -> bool:
    u = uri.lower()
    if u.startswith("/assets/") or u.startswith("/api/") or u.startswith("/legacy/"):
        return False
    if any(u.endswith(ext) for ext in _NON_PAGE):
        return False
    return True


def _ref_domain(ref: str) -> str:
    if not ref or ref == "-":
        return ""  # direct / no referrer
    try:
        host = urllib.parse.urlparse(ref).netloc.lower()
        host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _norm_page(uri: str) -> str:
    """Canonicalize a page URI for watched-page matching: `/a/b`, `/a/b/`, and
    `/a/b/index.html` all identify the same permalink page."""
    u = uri
    if u.endswith("/index.html"):
        u = u[: -len("index.html")]
    if not u.endswith("/"):
        u += "/"
    return u


def parse_cf_log(text: str):
    """Parse one CloudFront standard log file's text → list of page-request dicts.
    Pure function (no I/O) so it's unit-testable. Header lines (#Version/#Fields)
    define the column order; we key by field name to survive format changes."""
    out = []
    fields = None
    for line in text.splitlines():
        if line.startswith("#Fields:"):
            fields = line.split(":", 1)[1].strip().split()
            continue
        if line.startswith("#") or not line.strip():
            continue
        if not fields:
            continue
        parts = line.split("\t")
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        method = row.get("cs-method", "")
        status = row.get("sc-status", "")
        uri = urllib.parse.unquote(row.get("cs-uri-stem", ""))
        ua = urllib.parse.unquote(row.get("cs(User-Agent)", row.get("cs-user-agent", "")))
        ref = urllib.parse.unquote(row.get("cs(Referer)", row.get("cs-referer", "")))
        ip = row.get("c-ip", "")
        date = row.get("date", "")
        if method != "GET" or status not in ("200", "304"):
            continue
        if not _is_page(uri) or _is_bot(ua):
            continue
        out.append({"date": date, "uri": uri, "ref": ref, "vkey": _ipkey(ip, ua)})
    return out


def aggregate(records):
    """Pure aggregation over parsed page requests → digest dict. No raw IPs retained."""
    pages = Counter()
    referrers = Counter()
    visit_days = {}  # vkey -> set(date)
    watched = {_norm_page(p): {"views": 0, "referrers": Counter()} for p in WATCHED_PAGES}
    for r in records:
        pages[r["uri"]] += 1
        d = _ref_domain(r["ref"])
        if d and d != SITE_HOST:
            referrers[d] += 1
        visit_days.setdefault(r["vkey"], set()).add(r["date"])
        w = watched.get(_norm_page(r["uri"]))
        if w is not None:
            w["views"] += 1
            if d and d != SITE_HOST:
                w["referrers"][d] += 1
    unique = len(visit_days)
    returning = sum(1 for days in visit_days.values() if len(days) >= 2)
    return {
        "page_views": len(records),
        "unique_visitors": unique,
        "returning_visitors": returning,
        "returning_pct": round(100 * returning / unique) if unique else 0,
        "top_pages": pages.most_common(15),
        "top_referrers": referrers.most_common(10),
        # Travel watch (#741): a 0-view week is a valid reading — always report
        # every watched page so "no travel yet" is visible, never silent.
        "watched_pages": [
            {
                "page": p,
                "views": w["views"],
                "referrers": w["referrers"].most_common(10),
                # residual = direct visits + internal navigation (no external referrer)
                "direct_or_internal": w["views"] - sum(w["referrers"].values()),
            }
            for p, w in watched.items()
        ],
    }


def build_html(agg, start_date, end_date, green_html=""):
    def rows(pairs, label):
        if not pairs:
            return f'<tr><td colspan="2" style="color:#888;padding:6px 0">No {label} this week.</td></tr>'
        return "".join(
            f'<tr><td style="padding:4px 0;font-family:monospace">{k}</td>'
            f'<td style="padding:4px 0;text-align:right;font-variant-numeric:tabular-nums">{v}</td></tr>'
            for k, v in pairs
        )

    def watched_block(entries):
        if not entries:
            return ""
        parts = ['<h2 style="font-size:16px;margin-top:24px">Travel watch</h2>']
        for e in entries:
            refs = ", ".join(f"{k} ({v})" for k, v in e["referrers"]) or "no external referrers"
            detail = f"{refs} · {e['direct_or_internal']} direct/internal" if e["views"] else "no views this week"
            parts.append(
                f'<p style="margin:6px 0"><span style="font-family:monospace">{e["page"]}</span> — '
                f'<strong>{e["views"]}</strong> views<br>'
                f'<span style="color:#6e665a;font-size:13px">{detail}</span></p>'
            )
        return "".join(parts)

    return f"""<!DOCTYPE html><html><body style="font-family:-apple-system,sans-serif;color:#221e17;max-width:640px;margin:0 auto;padding:16px">
<p style="font-family:monospace;color:#a34e13;text-transform:uppercase;letter-spacing:.1em;font-size:12px">averagejoematt · weekly traffic</p>
<h1 style="font-weight:500">{start_date} → {end_date}</h1>
<table style="width:100%;margin:16px 0;border-collapse:collapse">
  <tr><td style="font-size:32px;font-weight:600;padding-right:24px">{agg['page_views']}</td>
      <td style="font-size:32px;font-weight:600;padding-right:24px">{agg['unique_visitors']}</td>
      <td style="font-size:32px;font-weight:600">{agg['returning_pct']}%</td></tr>
  <tr style="color:#6e665a;font-size:13px"><td>page views</td><td>unique visitors</td><td>returning</td></tr>
</table>
<h2 style="font-size:16px;margin-top:24px">Top pages</h2>
<table style="width:100%;border-collapse:collapse">{rows(agg['top_pages'], 'pages')}</table>
<h2 style="font-size:16px;margin-top:24px">Where they came from</h2>
<table style="width:100%;border-collapse:collapse">{rows(agg['top_referrers'], 'external referrers')}</table>
{watched_block(agg.get('watched_pages', []))}
{green_html}
<p style="color:#888;font-size:12px;margin-top:24px">From first-party CloudFront access logs — aggregate only, no cookies, no tracking, IPs hashed-then-discarded. {agg['returning_visitors']} of {agg['unique_visitors']} visitors returned on a second day.</p>
</body></html>"""


# ── Weekly green report (#1446) ──────────────────────────────────────────────
# Positive-confirmation QA rollup for the Monday ops email: before this, a green
# week produced ZERO signal, so absence-of-email did double duty for "healthy"
# and "broken reporter". Everything below is deterministic (no LLM), reads only
# what exists, and labels what it cannot read with an honest "not collected"
# line (ADR-104: never fabricate a rollup number). Every fetch is fail-soft —
# a missing data source must never crash the email.

GREEN_REPORT_DAYS = 7
QA_SMOKE_NAMESPACE = "LifePlatform/QaSmoke"  # qa_smoke_lambda.emf_summary_line (#1445)
BUDGET_NAMESPACE = "LifePlatform/Budget"  # cost_governor_lambda._emit_metrics
QA_PAUSE_NAMESPACE = "LifePlatform/QA"  # reader_truth_qa.emit_budget_pause_metric (#1440)
BUDGET_TIER_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
QA_LEVEL_PARAM = os.environ.get("QA_LEVEL_PARAM", "/life-platform/qa-level")

# Honest-absence reasons for the sources this Lambda deliberately cannot read.
# The only GitHub credential in Secrets Manager is the repository_dispatch PAT
# (life-platform/github-dispatch-token, Contents scope only) — it cannot list
# Actions runs (needs Actions:read) or read billing minutes (needs Plan:read),
# so pretending to try would just be a 403 dressed as telemetry.
_VISUAL_QA_ABSENT = (
    "not collected — visual-qa verdicts live in GitHub Actions run history; this Lambda holds no "
    "Actions-scoped token (the dispatch PAT is Contents-only by design, #1446)"
)
_ACTIONS_MINUTES_ABSENT = (
    "not collected — Actions minutes need a billing-scoped GitHub token this Lambda deliberately does not hold (#1446)"
)

_TIER_LABELS = {
    0: "all AI normal",
    1: "internal/dev AI paused",
    2: "internal + reader narratives paused",
    3: "hard cutoff — all AI paused",
}

# #1452: the QA-depth dial (SSM /life-platform/qa-level). Label + report tone per
# level — lean/off must read LOUD (warn/bad): a dialed-down estate can never be
# mistaken for a fully-swept green week. Deploy-gating QA is exempt from the dial
# by construction (tests/test_qa_level_dial.py), so "off" here means only the
# standalone/scheduled sweeps are dark.
_QA_LEVEL_LABELS = {
    "full": ("full — AI-vision on every standalone fire", "ok"),
    "standard": ("standard — daily deterministic + Sunday full AI-vision (the default)", "ok"),
    "lean": ("lean — standalone sweeps run deterministic-only, WebKit weekly skipped", "warn"),
    "off": ("OFF — standalone/scheduled QA sweeps skipped (deploy-gating QA still runs)", "bad"),
}


def load_coverage_stats(path=None):
    """Read the bundle-staged qa_coverage_stats.json (build_bundle.stage_qa_coverage).

    Returns (stats_dict, None) or (None, honest_reason). The file sits at the
    bundle root, one level above this operational/ package — same convention
    as food_vocabulary.json.
    """
    p = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qa_coverage_stats.json")
    try:
        with open(p, encoding="utf-8") as f:
            stats = json.load(f)
        if not isinstance(stats, dict) or not stats.get("pages_total"):
            return None, "coverage snapshot present but malformed — rebuild the bundle (deploy/build_bundle.py)"
        return stats, None
    except FileNotFoundError:
        return None, "coverage snapshot not in this bundle — deployed pre-#1446 or the build-time emitter failed"
    except Exception as e:
        return None, f"coverage snapshot unreadable ({str(e)[:80]})"


def _daily_sums(cw, namespace, metric, stat, start, end):
    """One metric's daily datapoints over the window → list of floats (may be empty)."""
    resp = cw.get_metric_data(
        MetricDataQueries=[
            {
                "Id": "m0",
                "MetricStat": {
                    "Metric": {"Namespace": namespace, "MetricName": metric, "Dimensions": []},
                    "Period": 86400,
                    "Stat": stat,
                },
                "ReturnData": True,
            }
        ],
        StartTime=start,
        EndTime=end,
    )
    results = (resp or {}).get("MetricDataResults") or []
    return [float(v) for v in ((results[0].get("Values") if results else None) or [])]


def collect_green_report(now=None):
    """Gather the rollup inputs. Each source is fetched fail-soft: on any error
    the source's dict carries an `error` string and the section renders an
    honest 'not collected' line instead of a fabricated number (ADR-104)."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=GREEN_REPORT_DAYS)
    report = {"window_days": GREEN_REPORT_DAYS}

    # 1. Nightly qa-smoke sweep verdicts (EMF metrics, #1445)
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        runs = _daily_sums(cw, QA_SMOKE_NAMESPACE, "RunCompleted", "Sum", start, now)
        fails = _daily_sums(cw, QA_SMOKE_NAMESPACE, "FailCount", "Sum", start, now)
        warns = _daily_sums(cw, QA_SMOKE_NAMESPACE, "WarnCount", "Sum", start, now)
        paused = _daily_sums(cw, QA_SMOKE_NAMESPACE, "PausedCount", "Sum", start, now)
        days_with_runs = sum(1 for v in runs if v > 0)
        days_with_failures = sum(1 for v in fails if v > 0)
        report["qa_smoke"] = {
            "days_with_runs": days_with_runs,
            "days_with_failures": days_with_failures,
            "green_days": max(days_with_runs - days_with_failures, 0),
            "failed_checks": int(sum(fails)),
            "warned_checks": int(sum(warns)),
            "paused_checks": int(sum(paused)),
        }
    except Exception as e:
        report["qa_smoke"] = {"error": f"CloudWatch read failed ({str(e)[:120]})"}

    # 2. Coverage stats — derived from tests/qa_manifest.py at bundle time (#1426)
    stats, reason = load_coverage_stats()
    report["coverage"] = stats if stats else {"error": reason}

    # 3. Budget tier + QA budget pauses (ADR-063/125, #1440)
    budget = {}
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        val = ((ssm.get_parameter(Name=BUDGET_TIER_PARAM) or {}).get("Parameter") or {}).get("Value")
        budget["tier"] = int(val) if val is not None else None
    except Exception as e:
        budget["tier_error"] = f"SSM read failed ({str(e)[:120]})"
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        tiers = _daily_sums(cw, BUDGET_NAMESPACE, "BudgetTier", "Maximum", start, now)
        budget["tier_max_7d"] = int(max(tiers)) if tiers else None
        pauses = _daily_sums(cw, QA_PAUSE_NAMESPACE, "QAPausedByBudget", "Sum", start, now)
        budget["qa_pauses_7d"] = int(sum(pauses))
    except Exception as e:
        budget["metrics_error"] = f"CloudWatch read failed ({str(e)[:120]})"
    report["budget"] = budget

    # 4. QA-depth dial (#1452 E3) — fail-soft. An account where the param was never
    # created is level "standard" BY DEFINITION (the workflows fail open to
    # standard), so ParameterNotFound is a reading, not an error.
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        val = ((ssm.get_parameter(Name=QA_LEVEL_PARAM) or {}).get("Parameter") or {}).get("Value")
        report["qa_level"] = {"level": val}
    except Exception as e:
        if "ParameterNotFound" in str(type(e).__name__) or "ParameterNotFound" in str(e):
            report["qa_level"] = {"level": "standard", "note": "param unset — fail-open default"}
        else:
            report["qa_level"] = {"error": f"SSM read failed ({str(e)[:120]})"}

    # 5 + 6. GitHub-side sources — honest absence, never a guess (see constants above).
    report["visual_qa"] = {"error": _VISUAL_QA_ABSENT}
    report["actions_minutes"] = {"error": _ACTIONS_MINUTES_ABSENT}
    return report


def _gr_row(label, text, tone="ok"):
    color = {"ok": "#1a7f37", "warn": "#9a6700", "bad": "#b42318", "muted": "#6e665a"}.get(tone, "#221e17")
    return (
        f'<p style="margin:6px 0"><span style="font-family:monospace;font-size:12px;color:#6e665a">{label}</span><br>'
        f'<span style="color:{color};font-size:13px">{text}</span></p>'
    )


def build_green_report_html(report):
    """Render the green-report section. Must render sanely with partial or
    missing data — every sub-dict may be absent, None, or error-shaped (the
    genesis-week present-None class: keys PRESENT, values None, memory:
    reference_genesis_week_present_none — hence `(d.get(k) or {})` guards
    throughout, never bare indexing). Must never raise: a crash here would
    take the whole Monday ops email down with it."""
    report = report or {}
    window = report.get("window_days") or GREEN_REPORT_DAYS
    parts = [f'<h2 style="font-size:16px;margin-top:28px">Weekly green report — QA estate, last {window} days</h2>']

    # Nightly qa-smoke sweep
    qa = report.get("qa_smoke") or {}
    runs = qa.get("days_with_runs")
    if qa.get("error") or runs is None:
        reason = qa.get("error") or "no qa-smoke rollup in this run"
        parts.append(_gr_row("nightly qa-smoke", f"not collected — {reason}", "muted"))
    else:
        fail_days = qa.get("days_with_failures") or 0
        text = (
            f"{runs}/{window} nightly runs completed · {qa.get('green_days') or 0} green · {fail_days} with failures "
            f"({qa.get('failed_checks') or 0} failing checks) · {qa.get('warned_checks') or 0} warnings · "
            f"{qa.get('paused_checks') or 0} paused checks"
        )
        tone = "bad" if fail_days else ("warn" if runs < window else "ok")
        parts.append(_gr_row("nightly qa-smoke", text, tone))

    # Coverage (derived from the #1426 manifest at bundle time)
    cov = report.get("coverage") or {}
    if cov.get("error") or not cov.get("pages_total"):
        reason = cov.get("error") or "no coverage snapshot in this run"
        parts.append(_gr_row("qa surface coverage", f"not collected — {reason}", "muted"))
    else:
        tiers = ", ".join(f"{k.replace('tier', 'T')}:{v}" for k, v in sorted((cov.get("pages_by_tier") or {}).items()))
        text = (
            f"{cov.get('pages_total')} pages registered ({tiers or 'tiers n/a'}) · visual sweep {cov.get('pages_with_visual') or 0} pages "
            f"({cov.get('visual_defs') or 0} defs) · {cov.get('static_core_pages') or 0} static-core · "
            f"{cov.get('leak_scan_pages') or 0} leak-scan · {cov.get('api_endpoints_declared') or 0} API endpoints declared "
            f"— derived from {cov.get('source') or 'the QA manifest'} at last deploy"
        )
        parts.append(_gr_row("qa surface coverage", text, "ok"))

    # Budget pauses
    b = report.get("budget") or {}
    bits = []
    tier = b.get("tier")
    if tier is not None:
        bits.append(f"tier now {tier} ({_TIER_LABELS.get(tier, 'unknown tier')})")
    else:
        bits.append(f"current tier not collected — {b.get('tier_error') or 'no reading in this run'}")
    tier_max = b.get("tier_max_7d")
    pauses = b.get("qa_pauses_7d")
    if b.get("metrics_error") or (tier_max is None and pauses is None):
        bits.append(f"7-day history not collected — {b.get('metrics_error') or 'no readings in this run'}")
    else:
        bits.append(f"7-day max tier {tier_max if tier_max is not None else 'n/a (no datapoints)'}")
        bits.append(f"{pauses if pauses is not None else 'n/a'} QA budget pause(s)")
    any_pause = (tier or 0) > 0 or (tier_max or 0) > 0 or (pauses or 0) > 0
    tone = "muted" if tier is None else ("warn" if any_pause else "ok")
    parts.append(_gr_row("budget (ADR-063)", " · ".join(bits), tone))

    # QA-depth dial (#1452) — lean/off render loud (warn/bad tone), never buried
    ql = report.get("qa_level") or {}
    level = ql.get("level")
    if level in _QA_LEVEL_LABELS:
        label, tone = _QA_LEVEL_LABELS[level]
        note = f" ({ql.get('note')})" if ql.get("note") else ""
        parts.append(_gr_row("qa depth dial (#1452)", f"{label}{note}", tone))
    elif level:
        parts.append(_gr_row("qa depth dial (#1452)", f"unrecognized level '{level}' — workflows fail open to standard", "warn"))
    else:
        reason = ql.get("error") or "no reading in this run"
        parts.append(_gr_row("qa depth dial (#1452)", f"not collected — {reason}", "muted"))

    # GitHub-side sources — honest absence lines
    parts.append(_gr_row("visual-qa (CI)", (report.get("visual_qa") or {}).get("error") or _VISUAL_QA_ABSENT, "muted"))
    parts.append(_gr_row("actions minutes", (report.get("actions_minutes") or {}).get("error") or _ACTIONS_MINUTES_ABSENT, "muted"))

    parts.append(
        '<p style="color:#888;font-size:12px;margin:8px 0 0">Deterministic rollup — every number read live from '
        "CloudWatch/SSM or derived from the QA manifest; anything unreadable says so instead of guessing (ADR-104).</p>"
    )
    return "".join(parts)


def _load_logs(s3, start_dt):
    """List + read CF log objects modified within the window.

    Returns (texts, object_count) — object_count is the number of log files
    found in the window so the caller can distinguish "no objects" (logging is
    broken/disabled) from "objects found but 0 human views" (genuine quiet week).
    """
    texts = []
    object_count = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=LOG_BUCKET, Prefix=LOG_PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < start_dt:
                continue
            object_count += 1
            body = s3.get_object(Bucket=LOG_BUCKET, Key=obj["Key"])["Body"].read()
            try:
                texts.append(gzip.GzipFile(fileobj=io.BytesIO(body)).read().decode("utf-8", "ignore"))
            except Exception as e:
                logger.warning("skip unreadable log %s: %s", obj["Key"], e)
    return texts, object_count


def _emit_no_logs_alert(s3, cw, start_dt, now, green_html=""):
    """Send a loud email + CloudWatch metric when the log source is empty."""
    cw.put_metric_data(
        Namespace="LifePlatform/Traffic",
        MetricData=[{"MetricName": "LogSourceEmpty", "Value": 1, "Unit": "Count"}],
    )
    subject = "⚠️ Traffic digest: NO log objects this week — CF logging may be off"
    body_html = f"""<html><body>
<h2>Traffic digest: log source empty</h2>
<p>The weekly traffic digest found <strong>zero CloudFront log objects</strong>
in <code>s3://{LOG_BUCKET}/{LOG_PREFIX}</code> for the window
<strong>{start_dt.strftime("%b %d")} – {now.strftime("%b %d")}</strong>.</p>
<p>This likely means CloudFront access logging is disabled on the main distribution
(it may have been reset by a CDK deploy). Check:
<code>aws cloudfront get-distribution-config --id E3S424OXQZ8NBE --query DistributionConfig.Logging</code></p>
<p>If logging is off, re-enable it via CDK (it is now declared in web_stack.py)
and run <code>cdk deploy LifePlatformWeb</code>.</p>
{green_html}
</body></html>"""
    try:
        boto3.client("sesv2", region_name=REGION).send_email(
            FromEmailAddress=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": body_html, "Charset": "UTF-8"}},
                }
            },
        )
        logger.warning("traffic digest: no log objects found — alert email sent")
    except Exception as exc:
        logger.error("traffic digest: no log objects + failed to send alert: %s", exc)


def lambda_handler(event, context):
    try:
        if not LOG_BUCKET:
            logger.error("LOG_BUCKET not set — nothing to do")
            return {"statusCode": 200, "body": "no LOG_BUCKET"}
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=DAYS)
        s3 = boto3.client("s3", region_name=REGION)
        cw = boto3.client("cloudwatch", region_name=REGION)

        texts, object_count = _load_logs(s3, start_dt)

        # #1446: the weekly green report rides this email in ALL branches — a
        # green week must produce positive signal, so the rollup is built
        # fail-soft up front and appended to whichever email goes out.
        try:
            green_html = build_green_report_html(collect_green_report(now))
        except Exception as e:
            logger.warning("green report failed (fail-soft, #1446): %s", e)
            green_html = (
                '<h2 style="font-size:16px;margin-top:28px">Weekly green report</h2>'
                f'<p style="color:#6e665a;font-size:13px">not collected — rollup builder error (fail-soft): {str(e)[:160]}</p>'
            )

        if object_count == 0:
            # No log objects at all — logging is likely disabled, not just a quiet week.
            _emit_no_logs_alert(s3, cw, start_dt, now, green_html)
            return {"statusCode": 200, "body": "no log objects — alert sent"}

        records = []
        for text in texts:
            records.extend(parse_cf_log(text))
        agg = aggregate(records)
        logger.info(
            "traffic digest: %s views, %s unique, %s returning (from %s log files)",
            agg["page_views"],
            agg["unique_visitors"],
            agg["returning_visitors"],
            object_count,
        )

        # Publish even on a genuinely quiet week (0 views) — a real 0 is a valid
        # reading, and cost_governor's surge check needs a fresh datapoint every
        # run to tell "quiet week" apart from "no data yet" (a missing/stale
        # metric fails closed to non-surge, see cost_governor._recent_unique_visitors).
        try:
            cw.put_metric_data(
                Namespace="LifePlatform/Traffic",
                MetricData=[
                    {"MetricName": "UniqueVisitors7d", "Value": agg["unique_visitors"], "Unit": "Count"},
                    {"MetricName": "PageViews7d", "Value": agg["page_views"], "Unit": "Count"},
                ],
            )
        except Exception as e:
            logger.warning("traffic digest: PutMetricData failed (non-fatal): %s", e)

        # #1446: a quiet week no longer suppresses the email — the green report IS
        # the positive confirmation the Monday ops email exists to deliver. The
        # traffic numbers honestly show 0.
        quiet = agg["page_views"] == 0
        if quiet:
            logger.info("no human page views in window (logs present, genuinely quiet) — sending green report anyway (#1446)")

        html = build_html(agg, start_dt.strftime("%b %d"), now.strftime("%b %d"), green_html)
        subject = (
            "Weekly ops — quiet traffic week · QA green report"
            if quiet
            else f"Weekly traffic — {agg['page_views']} views, {agg['unique_visitors']} visitors · green report"
        )
        boto3.client("sesv2", region_name=REGION).send_email(
            FromEmailAddress=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
        )
        return {"statusCode": 200, "body": f"sent: {agg['page_views']} views"}
    except Exception as e:
        logger.error("traffic digest failed: %s", e)
        raise
