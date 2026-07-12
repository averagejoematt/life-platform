"""Unit tests for the privacy-clean traffic digest parser/aggregator (CloudFront logs)."""

import gzip
import io
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import traffic_digest_lambda as td  # noqa: E402

HEADER = "#Version: 1.0\n#Fields: date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent)\n"


def _row(date, ip, method, uri, status, ref, ua):
    return "\t".join([date, "12:00:00", ip, method, "averagejoematt.com", uri, status, ref, ua])


SAMPLE = HEADER + "\n".join(
    [
        _row("2026-06-27", "1.1.1.1", "GET", "/", "200", "https://www.reddit.com/r/qs", "Mozilla/5.0 (Mac)"),
        _row("2026-06-27", "1.1.1.1", "GET", "/data/sleep/", "200", "https://averagejoematt.com/", "Mozilla/5.0 (Mac)"),
        _row("2026-06-28", "1.1.1.1", "GET", "/cockpit/", "200", "-", "Mozilla/5.0 (Mac)"),  # same visitor, 2nd day
        _row("2026-06-27", "2.2.2.2", "GET", "/", "200", "-", "Mozilla/5.0 (iPhone)"),  # 2nd unique
        _row("2026-06-27", "9.9.9.9", "GET", "/", "200", "-", "Googlebot/2.1"),  # bot → excluded
        _row("2026-06-27", "3.3.3.3", "GET", "/assets/css/tokens.css", "200", "-", "Mozilla/5.0"),  # asset
        _row("2026-06-27", "3.3.3.3", "GET", "/api/journey", "200", "-", "Mozilla/5.0"),  # api
        _row("2026-06-27", "4.4.4.4", "POST", "/api/ask", "200", "-", "Mozilla/5.0"),  # POST/api
        _row("2026-06-27", "5.5.5.5", "GET", "/data/sleep/", "404", "-", "Mozilla/5.0"),  # non-200
    ]
)


def test_parse_filters_assets_api_bots_and_non200():
    recs = td.parse_cf_log(SAMPLE)
    uris = sorted(r["uri"] for r in recs)
    assert uris == ["/", "/", "/cockpit/", "/data/sleep/"]  # 4 page hits, no asset/api/bot/404


def test_aggregate_counts_and_returners():
    agg = td.aggregate(td.parse_cf_log(SAMPLE))
    assert agg["page_views"] == 4
    assert agg["unique_visitors"] == 2  # Mac visitor + iPhone visitor
    assert agg["returning_visitors"] == 1  # the Mac visitor came back on a 2nd day
    assert agg["returning_pct"] == 50
    assert dict(agg["top_pages"])["/"] == 2
    # external referrer surfaced; own host excluded
    refs = dict(agg["top_referrers"])
    assert refs.get("reddit.com") == 1
    assert "averagejoematt.com" not in refs


def test_no_raw_ip_retained():
    recs = td.parse_cf_log(SAMPLE)
    blob = repr(recs)
    for ip in ("1.1.1.1", "2.2.2.2", "9.9.9.9"):
        assert ip not in blob  # only hashed visitor keys, never raw IPs


def test_empty_logs_safe():
    assert td.aggregate([]) == {
        "page_views": 0,
        "unique_visitors": 0,
        "returning_visitors": 0,
        "returning_pct": 0,
        "top_pages": [],
        "top_referrers": [],
        # travel watch (#741): a watched page with zero views is still reported
        "watched_pages": [
            {"page": "/journal/essays/org-chart-of-one/", "views": 0, "referrers": [], "direct_or_internal": 0},
        ],
    }


# ── Travel watch (#741): per-page referrer attribution for watched artifacts ──

ESSAY = "/journal/essays/org-chart-of-one/"

SAMPLE_WATCHED = HEADER + "\n".join(
    [
        _row("2026-07-13", "1.1.1.1", "GET", ESSAY, "200", "https://news.ycombinator.com/item?id=1", "Mozilla/5.0 (Mac)"),
        _row("2026-07-13", "2.2.2.2", "GET", ESSAY, "200", "https://news.ycombinator.com/", "Mozilla/5.0 (iPhone)"),
        # index.html + no-trailing-slash variants normalize onto the same permalink
        _row("2026-07-13", "3.3.3.3", "GET", ESSAY + "index.html", "200", "https://t.co/abc", "Mozilla/5.0 (Linux)"),
        _row("2026-07-13", "4.4.4.4", "GET", ESSAY.rstrip("/"), "200", "-", "Mozilla/5.0 (Windows)"),
        # internal navigation → counts as a view, not as an external referrer
        _row("2026-07-13", "5.5.5.5", "GET", ESSAY, "200", "https://averagejoematt.com/method/build/", "Mozilla/5.0 (Mac)"),
        # unrelated page traffic must not pollute the watched entry
        _row("2026-07-13", "6.6.6.6", "GET", "/cockpit/", "200", "https://news.ycombinator.com/", "Mozilla/5.0 (Mac)"),
    ]
)


def test_watched_page_referrer_attribution():
    agg = td.aggregate(td.parse_cf_log(SAMPLE_WATCHED))
    assert len(agg["watched_pages"]) == 1
    w = agg["watched_pages"][0]
    assert w["page"] == ESSAY
    assert w["views"] == 5  # 3 canonical + index.html variant + slashless variant
    refs = dict(w["referrers"])
    assert refs["news.ycombinator.com"] == 2  # attributed to the ESSAY only, not /cockpit/
    assert refs["t.co"] == 1
    assert "averagejoematt.com" not in refs  # own-host navigation is not travel
    assert w["direct_or_internal"] == 2  # the "-" direct hit + the internal-nav hit


def test_watched_block_in_email_html():
    agg = td.aggregate(td.parse_cf_log(SAMPLE_WATCHED))
    html = td.build_html(agg, "Jul 07", "Jul 14")
    assert "Travel watch" in html
    assert ESSAY in html
    assert "news.ycombinator.com (2)" in html


def test_watched_block_zero_views_is_explicit():
    html = td.build_html(td.aggregate([]), "Jul 07", "Jul 14")
    assert "Travel watch" in html
    assert "no views this week" in html


# ── ADR-133 (#739): the digest also emits UniqueVisitors7d / PageViews7d so
# cost_governor_lambda can read the trailing 7-day baseline for the surge-mode
# ceiling rule. lambda_handler pulls its own boto3 clients, so these tests
# fake `td.boto3` wholesale.


class _FakeS3:
    def __init__(self, key, body_text):
        self._key = key
        self._body = gzip.compress(body_text.encode("utf-8"))

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": self._key, "LastModified": datetime.now(timezone.utc)}]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self._body)}


class _FakeCW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


class _FakeSESv2:
    def send_email(self, **kwargs):
        pass


class _FakeBoto3:
    """Stands in for the `boto3` module `td.lambda_handler` calls `.client()` on."""

    def __init__(self, s3, cw, ses):
        self._clients = {"s3": s3, "cloudwatch": cw, "sesv2": ses}

    def client(self, name, region_name=None):
        return self._clients[name]


def _metric_value(cw, metric_name):
    for call in cw.calls:
        for m in call["MetricData"]:
            if m["MetricName"] == metric_name:
                return m["Value"]
    return None


def test_lambda_handler_emits_unique_visitors_metric(monkeypatch):
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    cw = _FakeCW()
    fake = _FakeBoto3(_FakeS3("cf/log1.gz", SAMPLE), cw, _FakeSESv2())
    monkeypatch.setattr(td, "boto3", fake)
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _metric_value(cw, "UniqueVisitors7d") == 2  # matches test_aggregate_counts_and_returners
    assert _metric_value(cw, "PageViews7d") == 4


def test_lambda_handler_emits_zero_on_genuinely_quiet_week(monkeypatch):
    """A real 0-view week still gets a datapoint — cost_governor must be able
    to tell 'quiet week' apart from 'no data yet' (a stale/missing metric
    fails closed to the non-surge ceiling)."""
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    cw = _FakeCW()
    fake = _FakeBoto3(_FakeS3("cf/log1.gz", HEADER), cw, _FakeSESv2())  # header only, no rows → 0 views
    monkeypatch.setattr(td, "boto3", fake)
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _metric_value(cw, "UniqueVisitors7d") == 0
    assert _metric_value(cw, "PageViews7d") == 0
