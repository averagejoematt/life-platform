"""Unit tests for the privacy-clean traffic digest parser/aggregator (CloudFront logs)."""

import os
import sys

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
        _row("2026-06-28", "1.1.1.1", "GET", "/now/", "200", "-", "Mozilla/5.0 (Mac)"),  # same visitor, 2nd day
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
    assert uris == ["/", "/", "/data/sleep/", "/now/"]  # 4 page hits, no asset/api/bot/404


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
    }
