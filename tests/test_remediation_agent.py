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


# ── #396: report-first skeleton, ack ledger, earn-or-shadow ─────────────────


def test_skeleton_report_lists_every_signal(tmp_path):
    signals = {
        "alarms": [{"name": "slo-source-freshness"}, {"name": "coherence-overall", "acked": {"bucket": "stale"}}],
        "ci_failures": [{"databaseId": 123, "displayTitle": "CI red on main"}],
        "dlq": {"depth": 2},
        "coherence": {"date": "2026-07-04"},
        "drift": {"status": "drift"},
        "urgent": None,
    }
    path = str(tmp_path / "report.json")
    skeleton = agent.write_skeleton_report(path, signals)
    import json as _json

    on_disk = _json.load(open(path))
    assert on_disk == skeleton
    assert on_disk["_skeleton"] is True
    kinds = [(d["kind"], d["id"]) for d in on_disk["untriaged"]]
    assert ("alarm", "slo-source-freshness") in kinds
    assert ("alarm", "coherence-overall") in kinds
    assert ("ci_failure", "123") in kinds
    assert ("dlq", "ingestion-dlq") in kinds
    assert ("coherence", "2026-07-04") in kinds
    assert ("drift", "weekly-drift") in kinds
    # A burned turn budget now yields THIS file — valid, buckets empty,
    # everything honestly listed as untriaged.
    assert on_disk["auto_fixed"] == [] and on_disk["needs_human"] == []


def test_annotate_acked_marks_unexpired_only():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    ledger = {
        "slo-source-freshness": {
            "acked_at": (now - timedelta(days=2)).isoformat(),
            "expires": (now + timedelta(days=5)).isoformat(),
            "bucket": "needs_human",
            "conclusion": "behavioral quiet stretch — re-auth not needed",
        },
        "old-alarm": {
            "acked_at": (now - timedelta(days=20)).isoformat(),
            "expires": (now - timedelta(days=13)).isoformat(),
            "bucket": "stale",
            "conclusion": "expired ack",
        },
    }
    signals = {"alarms": [{"name": "slo-source-freshness"}, {"name": "old-alarm"}, {"name": "fresh-alarm"}]}
    agent.annotate_acked(signals, ledger, now=now)
    by_name = {a["name"]: a for a in signals["alarms"]}
    assert by_name["slo-source-freshness"]["acked"]["bucket"] == "needs_human"
    assert "acked" not in by_name["old-alarm"]  # expired — re-triage from scratch
    assert "acked" not in by_name["fresh-alarm"]


def test_update_ack_ledger_acks_needs_human_and_stale(monkeypatch):
    from datetime import datetime, timezone

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    puts = {}
    monkeypatch.setattr(agent._s3, "put_object", lambda **kw: puts.update(kw))
    signals = {"alarms": [{"name": "slo-source-freshness"}, {"name": "ingest-liveness-unhealthy"}]}
    report = {
        "needs_human": [{"issue": "slo-source-freshness red", "action": "log a weigh-in"}],
        "stale": [{"summary": "ingest-liveness-unhealthy cleared after the 09:00 run"}],
        "auto_fixed": [],
        "prs": [],
    }
    ledger = agent.update_ack_ledger({}, report, signals, now=now)
    assert ledger["slo-source-freshness"]["bucket"] == "needs_human"
    assert ledger["ingest-liveness-unhealthy"]["bucket"] == "stale"
    assert puts.get("Key") == agent.ACK_LEDGER_KEY  # persisted


def test_update_ack_ledger_expires_old_entries(monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(agent._s3, "put_object", lambda **kw: None)
    ledger = {"dead": {"expires": (now - timedelta(days=1)).isoformat(), "bucket": "stale", "conclusion": ""}}
    out = agent.update_ack_ledger(ledger, {"needs_human": [], "stale": []}, {"alarms": []}, now=now)
    assert "dead" not in out


def test_earn_check_noop_outside_auto():
    assert agent.earn_or_shadow_check("shadow") is None


def test_earn_check_flags_dialback_after_window(monkeypatch):
    import json as _json
    from datetime import datetime, timezone

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    marker = {"window_started": "2026-06-01T00:00:00+00:00"}  # 33 days elapsed

    def _get(**kw):
        assert kw["Key"] == agent.EARN_MARKER_KEY
        return {"Body": _Body(_json.dumps(marker).encode())}

    monkeypatch.setattr(agent._s3, "get_object", _get)

    class _Out:
        returncode = 0
        stdout = "[]"  # zero merged auto-fix-safe PRs

    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _Out())
    item = agent.earn_or_shadow_check("auto", now=now)
    assert item is not None
    assert "NOT earned auto mode" in item["issue"]
    assert "remediation-mode" in item["action"] and "shadow" in item["action"]


def test_earn_check_resets_window_when_earned(monkeypatch):
    import json as _json
    from datetime import datetime, timezone

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)
    marker = {"window_started": "2026-06-01T00:00:00+00:00"}
    puts = {}

    def _get(**kw):
        return {"Body": _Body(_json.dumps(marker).encode())}

    monkeypatch.setattr(agent._s3, "get_object", _get)
    monkeypatch.setattr(agent._s3, "put_object", lambda **kw: puts.update(kw))

    class _Out:
        returncode = 0
        stdout = '[{"number": 460}]'

    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _Out())
    assert agent.earn_or_shadow_check("auto", now=now) is None
    body = _json.loads(puts["Body"])
    assert body["merged_prs"] == [460]
    assert body["window_started"] == now.isoformat()  # window restarts — keeps being re-tested


def test_prompt_instructs_incremental_report_and_ack_skip():
    src = open(os.path.join(os.path.dirname(__file__), "..", "remediation", "prompt.md")).read()
    assert "untriaged" in src
    assert "Report-first workflow" in src
    assert "Acked signals" in src
    assert "exact alarm name" in src


# ── #1201: the loop must fail loudly when triage doesn't complete ────────────


def test_triage_incomplete_flags_truncated_untriaged_run():
    # The exact #1201 failure mode: signals left untriaged + a truncated _raw tail.
    report = {
        "auto_fixed": [],
        "prs": [],
        "needs_human": [],
        "stale": [],
        "untriaged": [{"kind": "alarm", "id": "grading-stalled"}],
        "_raw": "Now let me create a branch and push this fix:",  # cut mid-sentence
    }
    assert agent.triage_incomplete(report) is True


def test_triage_complete_run_is_not_flagged():
    # All signals bucketed, no _raw → the loop closed; must NOT red the step.
    assert agent.triage_incomplete({"auto_fixed": [{"pr": "#9"}], "untriaged": []}) is False
    # Untriaged left over but the agent produced a parseable REPORT (no _raw) is an
    # honest partial, not the truncated-transcript failure — also not flagged.
    assert agent.triage_incomplete({"untriaged": [{"kind": "alarm", "id": "x"}]}) is False
    # A bare _raw with nothing untriaged (nothing left to close) is not flagged either.
    assert agent.triage_incomplete({"untriaged": [], "_raw": "..."}) is False


def test_triage_incomplete_non_dict_is_flagged():
    assert agent.triage_incomplete(None) is True


def _run_main_with_transcript(monkeypatch, tmp_path, transcript):
    """Drive agent.main() end-to-end with a canned agent transcript, stubbing the
    boto3/SES/gh side-effects, and return main()'s exit code. Exercises the real
    skeleton → parse → exit-code path, so this test fails if the guard is removed."""
    monkeypatch.setenv("REMEDIATION_REPORT_PATH", str(tmp_path / "report.json"))
    monkeypatch.setattr(agent, "gate", lambda: "shadow")
    monkeypatch.setattr(
        agent,
        "gather_signals",
        lambda ev: {
            "alarms": [{"name": "grading-stalled"}],
            "ci_failures": [],
            "dlq": {},
            "coherence": None,
            "drift": None,
            "urgent": None,
        },
    )
    monkeypatch.setattr(agent, "load_ack_ledger", lambda: {})
    monkeypatch.setattr(agent, "build_prompt", lambda mode, signals: "prompt")

    async def _fake_run_agent(prompt):
        return transcript

    monkeypatch.setattr(agent, "run_agent", _fake_run_agent)
    monkeypatch.setattr(agent, "update_ack_ledger", lambda *a, **k: {})
    monkeypatch.setattr(agent, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(agent, "email_report", lambda *a, **k: None)
    return agent.main()


def test_main_reds_on_truncated_transcript(monkeypatch, tmp_path):
    # A mid-sentence transcript with no ```json fence → skeleton keeps the signal
    # untriaged, _raw is attached → main() must exit non-zero (a failed run).
    code = _run_main_with_transcript(monkeypatch, tmp_path, "Investigating grading-stalled. Now let me create a branch and push this fix:")
    assert code == 1


def test_main_green_on_completed_transcript(monkeypatch, tmp_path):
    # A well-formed REPORT with everything triaged → main() exits 0.
    transcript = (
        "Triaged grading-stalled → stale.\n"
        '```json\n{"auto_fixed": [], "prs": [], "needs_human": [], '
        '"stale": [{"summary": "grading-stalled cleared"}], "untriaged": []}\n```'
    )
    code = _run_main_with_transcript(monkeypatch, tmp_path, transcript)
    assert code == 0
