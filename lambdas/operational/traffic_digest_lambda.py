"""
traffic_digest_lambda.py — privacy-clean weekly traffic digest.

Reads CloudFront standard access logs (the site's own first-party server logs —
no cookies, no client JS, no third party) from the log bucket, aggregates the
past 7 days, and emails a digest: total page views, unique + returning visitors,
top pages, and where external traffic comes from (e.g. Reddit). This is the
instrument for the returnability goal (docs/PLATFORM_NORTH_STAR.md).

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
    for r in records:
        pages[r["uri"]] += 1
        d = _ref_domain(r["ref"])
        if d and d != SITE_HOST:
            referrers[d] += 1
        visit_days.setdefault(r["vkey"], set()).add(r["date"])
    unique = len(visit_days)
    returning = sum(1 for days in visit_days.values() if len(days) >= 2)
    return {
        "page_views": len(records),
        "unique_visitors": unique,
        "returning_visitors": returning,
        "returning_pct": round(100 * returning / unique) if unique else 0,
        "top_pages": pages.most_common(15),
        "top_referrers": referrers.most_common(10),
    }


def build_html(agg, start_date, end_date):
    def rows(pairs, label):
        if not pairs:
            return f'<tr><td colspan="2" style="color:#888;padding:6px 0">No {label} this week.</td></tr>'
        return "".join(
            f'<tr><td style="padding:4px 0;font-family:monospace">{k}</td>'
            f'<td style="padding:4px 0;text-align:right;font-variant-numeric:tabular-nums">{v}</td></tr>'
            for k, v in pairs
        )

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
<p style="color:#888;font-size:12px;margin-top:24px">From first-party CloudFront access logs — aggregate only, no cookies, no tracking, IPs hashed-then-discarded. {agg['returning_visitors']} of {agg['unique_visitors']} visitors returned on a second day.</p>
</body></html>"""


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


def _emit_no_logs_alert(s3, cw, start_dt, now):
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

        if object_count == 0:
            # No log objects at all — logging is likely disabled, not just a quiet week.
            _emit_no_logs_alert(s3, cw, start_dt, now)
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

        if agg["page_views"] == 0:
            logger.info("no human page views in window (logs present, genuinely quiet) — skipping email")
            return {"statusCode": 200, "body": "quiet week — no email"}

        html = build_html(agg, start_dt.strftime("%b %d"), now.strftime("%b %d"))
        boto3.client("sesv2", region_name=REGION).send_email(
            FromEmailAddress=EMAIL_SENDER,
            Destination={"ToAddresses": [EMAIL_RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {
                        "Data": f"Weekly traffic — {agg['page_views']} views, {agg['unique_visitors']} visitors",
                        "Charset": "UTF-8",
                    },
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
        )
        return {"statusCode": 200, "body": f"sent: {agg['page_views']} views"}
    except Exception as e:
        logger.error("traffic digest failed: %s", e)
        raise
