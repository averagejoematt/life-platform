"""tests/test_site_api_agents.py — the Agents Showcase feed (#399).

Proves the read-only /api/agent_activity endpoint:
  • renders the roster + a dated weekly feed purely from existing artifacts,
  • surfaces the famous case (the canary catching an ungrounded served answer),
  • NEVER leaks the remediation agent's raw model scratch (report["_raw"]),
  • passes every fragment through the public content filter (blocked vice → dropped),
  • honest empty state for a week with no activity.

Offline: the S3 client is monkeypatched with an in-memory fake. No AWS.
"""

from __future__ import annotations

import io
import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from web import site_api_agents as A  # noqa: E402


class _FakeS3:
    def __init__(self, objs):
        self.objs = objs

    def get_object(self, Bucket, Key):
        if Key in self.objs:
            return {"Body": io.BytesIO(json.dumps(self.objs[Key]).encode())}
        raise Exception("NoSuchKey")

    def list_objects_v2(self, **kw):
        prefix = kw["Prefix"]
        keys = [k for k in self.objs if k.startswith(prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


@pytest.fixture
def objs():
    return {}


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch, objs):
    monkeypatch.setattr(A, "_s3_client", lambda: _FakeS3(objs))
    return objs


def _body(resp):
    return json.loads(resp["body"])


def _call(week="2026-06-30"):
    return _body(A.handle_agent_activity({"queryStringParameters": {"week": week}}))


def test_empty_week_is_honest(objs):
    body = _call()
    assert body["has_activity"] is False
    assert body["events"] == []
    # roster still renders (it's editorial, not data)
    assert {r["id"] for r in body["roster"]} == {
        "coherence_sentinel",
        "ai_quality_canary",
        "remediation_agent",
        "automerge_gate",
    }


def test_week_boundaries_anchor_to_monday(objs):
    body = _call(week="2026-07-02")  # a Wednesday
    assert body["week_start"] == "2026-06-29"
    assert body["week_end"] == "2026-07-05"


def test_coherence_alarm_surfaces(objs):
    objs["coherence-log/2026-07-05.json"] = {
        "date": "2026-07-05",
        "status": "alarm",
        "findings": [
            {"name": "count_agreement", "status": "alarm", "detail": "3 vs 4"},
            {"name": "facts_agreement", "status": "ok", "detail": "agree"},
        ],
    }
    body = _call()
    ev = [e for e in body["events"] if e["agent_id"] == "coherence_sentinel"]
    assert len(ev) == 1 and ev[0]["status"] == "alarm"
    assert any("count_agreement" in d for d in ev[0]["details"])
    # the ok finding is not surfaced as a detail line
    assert not any("facts_agreement" in d for d in ev[0]["details"])
    assert body["summary"]["coherence_sentinel"] == {"runs": 1, "flags": 1}


def test_famous_case_grounding_catch(objs):
    """The canary catching a served AI answer citing a figure not in the facts."""
    objs["ai-canary-log/2026-07-03.json"] = {
        "date": "2026-07-03",
        "status": "ALARM",
        "findings": [
            {"name": "ask_factual:grounded", "status": "ALARM", "detail": "ungrounded numbers {'answer': [64.0]}"},
            {"name": "ask_factual:status", "status": "OK", "detail": "200"},
        ],
    }
    body = _call()
    ev = [e for e in body["events"] if e["agent_id"] == "ai_quality_canary"]
    assert len(ev) == 1 and ev[0]["status"] == "alarm"
    assert "ungrounded" in ev[0]["headline"].lower()


def test_canary_budget_skip_is_info(objs):
    objs["ai-canary-log/2026-07-03.json"] = {"date": "2026-07-03", "status": "OK", "skipped": "budget-paused", "findings": []}
    body = _call()
    ev = [e for e in body["events"] if e["agent_id"] == "ai_quality_canary"][0]
    assert ev["status"] == "info" and "budget" in ev["headline"].lower()


def test_remediation_raw_never_leaks(objs):
    objs["remediation-log/2026/07/03/161615.json"] = {
        "mode": "auto",
        "signals": {"alarms": [{"name": "panelcast-no-episode-7d"}], "ci_failures": [1, 2], "dlq": {"depth": 0}},
        "report": {"auto_fixed": [], "prs": [], "needs_human": [], "_raw": "SECRET model scratch narrative"},
    }
    resp = A.handle_agent_activity({"queryStringParameters": {"week": "2026-06-30"}})
    assert "SECRET model scratch" not in resp["body"]
    assert "_raw" not in resp["body"]
    body = _body(resp)
    ev = [e for e in body["events"] if e["agent_id"] == "remediation_agent"][0]
    assert any("panelcast" in d for d in ev["details"])


def test_automerge_decision_renders(objs):
    objs["remediation-log/automerge/2026/07/03/pr123-101010.merged.json"] = {
        "pr": 123,
        "title": "fix: freshness threshold",
        "action": "merged",
        "reason": "auto-merged (allowlist + lint/tests green)",
        "infra": False,
    }
    body = _call()
    ev = [e for e in body["events"] if e["agent_id"] == "automerge_gate"][0]
    assert ev["status"] == "ok" and "#123" in ev["headline"]


def test_blocked_content_is_filtered(objs):
    """A finding detail that quotes a blocked vice must not appear verbatim."""
    objs["coherence-log/2026-07-05.json"] = {
        "date": "2026-07-05",
        "status": "warn",
        "findings": [{"name": "narrative_scan", "status": "warn", "detail": "coach mentioned marijuana in a draft"}],
    }
    resp = A.handle_agent_activity({"queryStringParameters": {"week": "2026-06-30"}})
    assert "marijuana" not in resp["body"].lower()


def test_bad_week_param_defaults_gracefully(objs):
    resp = A.handle_agent_activity({"queryStringParameters": {"week": "not-a-date"}})
    assert resp["statusCode"] == 200


def test_no_query_params_returns_current_week(objs):
    resp = A.handle_agent_activity({})
    assert resp["statusCode"] == 200
    body = _body(resp)
    assert "week_start" in body and "roster" in body
