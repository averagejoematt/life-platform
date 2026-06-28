"""
tests/test_remediation_agent.py — Phase 4: the agent's eyes on content.

Two things matter here:
  1. The agent reads the Coherence Sentinel's durable findings
     (coherence-log/latest.json) and surfaces them ONLY when they're flagging —
     an OK record is noise, not a signal.
  2. The SAFETY INVARIANT: content/correctness can never auto-merge. The
     auto-merge gate's ALLOWLIST must contain no coach/prompt/grounding/compute
     path, so a coherence-driven content edit always needs a human.
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))

import agent  # noqa: E402
import automerge  # noqa: E402


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


def _patch_s3(monkeypatch, payload):
    import json

    def _get(**kw):
        assert kw["Key"] == "coherence-log/latest.json"
        return {"Body": _Body(json.dumps(payload).encode())}

    monkeypatch.setattr(agent._s3, "get_object", _get)


def test_coherence_ok_record_is_not_a_signal(monkeypatch):
    _patch_s3(monkeypatch, {"status": "ok", "findings": [], "alarms": []})
    assert agent._coherence_findings() is None


def test_coherence_alarm_surfaces_only_flagging_findings(monkeypatch):
    _patch_s3(
        monkeypatch,
        {
            "status": "alarm",
            "date": "2026-06-28",
            "alarms": ["prediction_health"],
            "findings": [
                {"name": "prediction_health", "status": "alarm", "detail": "8 closed, 0 decided"},
                {"name": "facts_agreement", "status": "ok", "detail": "fine"},
                {"name": "endpoint_shape:vitals", "status": "warn", "detail": "thin"},
            ],
            "semantic": {"coherent": False, "issues": ["coach invented a weight number"]},
            "digest": "COHERENCE SENTINEL — ALARM",
        },
    )
    out = agent._coherence_findings()
    assert out is not None
    assert out["status"] == "alarm"
    names = {f["name"] for f in out["findings"]}
    assert names == {"prediction_health", "endpoint_shape:vitals"}  # the OK one is dropped
    assert out["semantic"]["coherent"] is False


def test_coherence_missing_artifact_is_fail_soft(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("NoSuchKey")

    monkeypatch.setattr(agent._s3, "get_object", _boom)
    assert agent._coherence_findings() is None  # no raise


def test_coherence_is_in_the_actionable_signal_set(monkeypatch):
    # A flagging coherence record alone (no alarms/CI/DLQ) must count as actionable.
    _patch_s3(monkeypatch, {"status": "alarm", "findings": [{"name": "x", "status": "alarm"}], "alarms": ["x"]})
    monkeypatch.setattr(agent, "_cw", _Stub())
    monkeypatch.setattr(agent, "_sqs", _Stub())
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _Stub(returncode=1, stdout="[]"))
    signals = agent.gather_signals(None)
    assert signals["coherence"] is not None


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def describe_alarms(self, **kw):
        return {"MetricAlarms": []}

    def get_queue_attributes(self, **kw):
        raise RuntimeError("no dlq in test")


# ── The safety invariant: content can never auto-merge ───────────────────────

_CONTENT_MARKERS = (
    "prompt",
    "coach",
    "bedrock",
    "ai_calls",
    "ai_summaries",
    "ai_expert",
    "canonical_facts",
    "narrative",
    "daily_brief",
    "panelcast",
    "chronicle",
)


def test_automerge_allowlist_has_no_content_paths():
    for entry in automerge.ALLOWLIST:
        low = entry.lower()
        assert not any(m in low for m in _CONTENT_MARKERS), f"content path on auto-merge allowlist: {entry}"


def test_automerge_denylist_blocks_bedrock_and_prompts():
    # Defense in depth: even if a content file were mistakenly allowlisted, these
    # denylist substrings catch the highest-risk content/AI surfaces.
    for sub in ("bedrock_client", "budget_guard"):
        assert sub in automerge.DENYLIST_SUBSTR
