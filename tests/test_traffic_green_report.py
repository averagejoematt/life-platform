"""tests/test_traffic_green_report.py — #1446: the weekly green report section
in the Monday ops email (traffic_digest_lambda).

Before #1446, a green week produced ZERO signal — absence-of-email did double
duty for "healthy" and "broken reporter". These tests pin the new contract:

  1. build_green_report_html() renders sanely with partial/missing data —
     including the genesis-week present-None class (keys present, values None,
     memory: reference_genesis_week_present_none) and fully error-shaped
     sources. It must NEVER raise (the email fires Monday; a crash here would
     kill the whole ops email).
  2. Honest absence (ADR-104): unreadable sources say "not collected" with a
     reason — never a fabricated number. The GitHub-side sources (visual-qa
     run outcomes, Actions minutes) are honest-absence BY DESIGN because the
     Lambda holds no Actions/billing-scoped token.
  3. collect_green_report() is fail-soft per source (a broken boto3 client
     yields error dicts, not an exception).
  4. lambda_handler sends the Monday email even on a quiet-traffic week — the
     green report IS the positive confirmation.
  5. Coverage numbers derive live from tests/qa_manifest.py via
     build_bundle.stage_qa_coverage() — never hand-maintained — and the staged
     payload is deterministic (no timestamps: a churning payload would flip
     the CDK asset hash every synth and force spurious full-fleet updates).

The crash-shape tests (class 1) were proven RED against the unguarded builder
before the `(d.get(k) or {})` guards were added.
"""

import gzip
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))

import traffic_digest_lambda as td  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────────

FULL_REPORT = {
    "window_days": 7,
    "qa_smoke": {
        "days_with_runs": 7,
        "days_with_failures": 1,
        "green_days": 6,
        "failed_checks": 2,
        "warned_checks": 3,
        "paused_checks": 1,
    },
    "coverage": {
        "source": "tests/qa_manifest.py (#1426)",
        "pages_total": 80,
        "pages_by_tier": {"tier1": 6, "tier2": 53, "tier3": 17, "tier4": 4},
        "visual_defs": 79,
        "pages_with_visual": 77,
        "static_core_pages": 6,
        "leak_scan_pages": 77,
        "smoke_pages": 80,
        "api_endpoints_declared": 48,
    },
    "budget": {"tier": 0, "tier_max_7d": 0, "qa_pauses_7d": 0},
    "qa_level": {"level": "standard"},  # #1452: the QA-depth dial rides the report
    "visual_qa": {"error": td._VISUAL_QA_ABSENT},
    "actions_minutes": {"error": td._ACTIONS_MINUTES_ABSENT},
}


# ── 1. Crash shapes — the builder must never raise ───────────────────────────
# Proven RED pre-guard: every shape below crashed the naive builder
# (TypeError on `"error" in None` / KeyError on missing keys).

CRASH_SHAPES = [
    None,  # whole report absent
    {},  # empty report
    {"window_days": 7},  # sources missing entirely
    # the genesis-week present-None class: keys PRESENT, values None
    {"window_days": 7, "qa_smoke": None, "coverage": None, "budget": None, "visual_qa": None, "actions_minutes": None},
    # present-None INNER fields (tier read returned nothing, no error string)
    {"window_days": 7, "qa_smoke": {}, "coverage": {}, "budget": {"tier": None, "tier_max_7d": None, "qa_pauses_7d": None}},
    # error-shaped everything
    {
        "window_days": 7,
        "qa_smoke": {"error": "CloudWatch read failed (boom)"},
        "coverage": {"error": "coverage snapshot not in this bundle"},
        "budget": {"tier_error": "SSM read failed (boom)", "metrics_error": "CloudWatch read failed (boom)"},
        "visual_qa": {"error": "x"},
        "actions_minutes": {"error": "y"},
    },
]


def test_builder_never_raises_on_crash_shapes():
    for shape in CRASH_SHAPES:
        html = td.build_green_report_html(shape)  # must not raise
        assert "Weekly green report" in html


def test_builder_missing_sources_render_honest_absence_not_numbers():
    html = td.build_green_report_html({"window_days": 7})
    assert "not collected" in html
    # ADR-104: no fabricated tallies for the unreadable sources
    assert "None/7" not in html and "None green" not in html


def test_present_none_budget_renders_sanely():
    html = td.build_green_report_html(
        {"window_days": 7, "budget": {"tier": None, "tier_max_7d": None, "qa_pauses_7d": None}},
    )
    assert "Weekly green report" in html
    assert "not collected" in html  # a None tier with no error string is still an honest absence


# ── 2. Happy path + honest GitHub absence ────────────────────────────────────


def test_full_report_renders_all_sections():
    html = td.build_green_report_html(FULL_REPORT)
    assert "7/7 nightly runs completed" in html
    assert "6 green" in html and "1 with failures" in html and "2 failing checks" in html
    assert "80 pages registered" in html and "T1:6" in html
    assert "48 API endpoints declared" in html
    assert "tier now 0 (all AI normal)" in html and "0 QA budget pause(s)" in html
    # the two GitHub-side sources are honest-absence by design (no token)
    assert html.count("not collected") == 2
    assert "Actions-scoped token" in html and "billing-scoped GitHub token" in html


def test_budget_pause_week_is_flagged():
    report = dict(FULL_REPORT)
    report["budget"] = {"tier": 2, "tier_max_7d": 3, "qa_pauses_7d": 4}
    html = td.build_green_report_html(report)
    assert "tier now 2 (internal + reader narratives paused)" in html
    assert "7-day max tier 3" in html
    assert "4 QA budget pause(s)" in html


def test_report_is_deterministic():
    assert td.build_green_report_html(FULL_REPORT) == td.build_green_report_html(FULL_REPORT)


# ── 3. Collector is fail-soft per source ─────────────────────────────────────


class _BrokenBoto3:
    def client(self, name, region_name=None):
        raise RuntimeError(f"no {name} client in this test")


def test_collect_green_report_survives_broken_boto3(monkeypatch, tmp_path):
    monkeypatch.setattr(td, "boto3", _BrokenBoto3())
    report = td.collect_green_report(datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert "error" in report["qa_smoke"]
    assert "tier_error" in report["budget"] and "metrics_error" in report["budget"]
    # and the result still renders
    html = td.build_green_report_html(report)
    assert "not collected" in html


def test_load_coverage_stats_missing_file_is_honest(tmp_path):
    stats, reason = td.load_coverage_stats(str(tmp_path / "nope.json"))
    assert stats is None and "not in this bundle" in reason


def test_load_coverage_stats_malformed_is_honest(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[1,2,3]")
    stats, reason = td.load_coverage_stats(str(p))
    assert stats is None and "malformed" in reason


# ── 4. Handler: the quiet-week Monday email now SENDS, with the section ──────

HEADER = "#Version: 1.0\n#Fields: date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent)\n"


class _FakeS3:
    def __init__(self, body_text):
        self._body = gzip.compress(body_text.encode("utf-8"))

    def get_paginator(self, name):
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": "cf/log1.gz", "LastModified": datetime.now(timezone.utc)}]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self._body)}


class _FakeCW:
    def put_metric_data(self, **kwargs):
        pass

    # deliberately NO get_metric_data — exercises the fail-soft path


class _FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)


class _FakeBoto3:
    """s3/cloudwatch/sesv2 only — client("ssm") raises, exercising fail-soft."""

    def __init__(self, s3, cw, ses):
        self._clients = {"s3": s3, "cloudwatch": cw, "sesv2": ses}

    def client(self, name, region_name=None):
        return self._clients[name]


def test_quiet_week_still_sends_green_report_email(monkeypatch):
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    ses = _FakeSES()
    monkeypatch.setattr(td, "boto3", _FakeBoto3(_FakeS3(HEADER), _FakeCW(), ses))  # header only → 0 views
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(ses.sent) == 1, "quiet week must still send the Monday ops email (#1446)"
    subject = ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]
    body = ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "green report" in subject.lower()
    assert "Weekly green report" in body
    assert "not collected" in body  # fake clients can't serve metrics → honest lines, not a crash


def test_normal_week_email_carries_green_report(monkeypatch):
    rows = HEADER + "\t".join(["2026-07-19", "12:00:00", "1.1.1.1", "GET", "averagejoematt.com", "/", "200", "-", "Mozilla/5.0 (Mac)"])
    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    ses = _FakeSES()
    monkeypatch.setattr(td, "boto3", _FakeBoto3(_FakeS3(rows), _FakeCW(), ses))
    resp = td.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    body = ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Weekly green report" in body
    assert "Travel watch" in body  # existing sections intact


# ── 5. Coverage derivation: bundle staging == the live manifest, no drift ────


def test_stage_qa_coverage_matches_manifest_live(tmp_path):
    import build_bundle as bb

    bb.stage_qa_coverage(str(tmp_path))
    staged = json.loads((tmp_path / "qa_coverage_stats.json").read_text())

    sys.path.insert(0, os.path.dirname(__file__))
    import qa_manifest

    live = qa_manifest.coverage_stats()
    assert staged == live, "staged coverage snapshot must be exactly the manifest-derived stats — never hand-maintained"
    assert staged["pages_total"] > 0

    # and the Lambda-side loader accepts the staged payload
    stats, reason = td.load_coverage_stats(str(tmp_path / "qa_coverage_stats.json"))
    assert reason is None and stats == live


def test_coverage_payload_is_timestamp_free():
    """A timestamp in the payload would churn the CDK asset hash every synth →
    spurious full-fleet redeploys. The payload must be pure repo-derived."""
    sys.path.insert(0, os.path.dirname(__file__))
    import qa_manifest

    stats = qa_manifest.coverage_stats()
    forbidden = ("time", "date", "generated", "built", "now")
    for k in stats:
        assert not any(t in k.lower() for t in forbidden), f"coverage_stats key {k!r} looks timestamp-shaped"
    assert stats == qa_manifest.coverage_stats()  # call-to-call deterministic
