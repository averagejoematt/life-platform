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


# ── #1228: orphan_functions triage must be region-aware ──────────────────────


def test_build_prompt_carries_region_aware_orphan_triage_rule():
    """#1228: the agent dismissed a live us-west-2 `orphan_functions` signal
    (email-subscriber) as a FALSE POSITIVE because the function name is
    "defined in web_stack.py" — without checking that web_stack.py deploys to
    us-east-1, a DIFFERENT region than the one the drift sentinel found the
    live orphan in. The assembled triage prompt (prompt.md + the taxonomy doc,
    via the REAL build_prompt code path the agent actually runs) must carry an
    explicit rule forbidding exactly that class of dismissal — grepping a
    function name into ANY stack file is not grounds for Bucket D unless that
    stack's deploy region matches the orphan's region."""
    signals = {
        "alarms": [],
        "ci_failures": [],
        "dlq": {},
        "coherence": None,
        "drift": {
            "status": "drift",
            "flagging": {"orphan_functions": {"status": "drift", "orphans": ["email-subscriber"]}},
        },
        "urgent": None,
    }
    prompt = agent.build_prompt("shadow", signals)
    low = prompt.lower()

    assert "orphan_functions" in prompt  # the signal itself made it into the prompt
    assert "region" in low
    # The rule must name the exact #1228 mistake as forbidden: a cross-region
    # stack definition clearing a same-region live orphan.
    assert "cross-region" in low or "different region" in low
    assert "false positive" in low
    assert "1228" in prompt  # traceable to the incident that motivated the rule


def test_taxonomy_forbids_cross_region_false_positive_dismissal():
    """The rubric doc itself (not just the assembled prompt) states the rule —
    REMEDIATION_TAXONOMY.md is read by a human too, not only fed to the agent."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "docs", "REMEDIATION_TAXONOMY.md")).read()
    assert "orphan_functions" in src
    assert "STACKS" in src  # points at the region mapping the triage must consult
    low = src.lower()
    assert "cross-region" in low or "different region" in low
    assert "never" in low and "bucket d" in low


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


# ── #1204: alarm-aging escalation (deterministic, LLM-independent) ───────────


def _metric_alarm(name, age_hours, now):
    from datetime import timedelta

    return {
        "AlarmName": name,
        "StateReason": "Threshold Crossed",
        "MetricName": "M",
        "Namespace": "NS",
        "StateUpdatedTimestamp": now - timedelta(hours=age_hours),
    }


def test_aged_alarm_over_72h_becomes_named_needs_human_line(monkeypatch):
    # Synthetic describe-alarms: grading-stalled stuck 10 days (the real incident) +
    # a fresh 3h blip. Drive the REAL gather_signals → aged_alarm_escalations path.
    from datetime import datetime, timezone

    now = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        agent._cw,
        "describe_alarms",
        lambda **kw: {"MetricAlarms": [_metric_alarm("grading-stalled", 240, now), _metric_alarm("fresh-blip", 3, now)]},
    )
    monkeypatch.setattr(agent, "_coherence_findings", lambda: None)
    monkeypatch.setattr(agent.drift_report, "read_latest", lambda *a, **k: None)
    monkeypatch.setattr(agent.drift_report, "as_signal", lambda x: None)
    monkeypatch.setattr(agent._sqs, "get_queue_attributes", lambda **kw: (_ for _ in ()).throw(RuntimeError("no dlq")))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: _Stub(returncode=1, stdout="[]"))

    signals = agent.gather_signals(None)
    esc = dict(agent.aged_alarm_escalations(signals, now=now))

    # > 72h escalates with a NAMED line carrying its age; < 72h does NOT.
    assert "grading-stalled" in esc
    assert "fresh-blip" not in esc
    issue = esc["grading-stalled"]["issue"]
    assert "grading-stalled" in issue  # named
    assert "10.0d" in issue and "240h" in issue  # carries age in days + hours


def test_acked_aged_alarm_is_not_re_escalated():
    # An already-acked alarm (a prior run's conclusion carried forward) is the
    # acknowledgement — it must NOT re-escalate until the ack expires.
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    signals = {
        "alarms": [{"name": "grading-stalled", "updated": (now - timedelta(hours=240)).isoformat(), "acked": {"bucket": "needs_human"}}]
    }
    assert agent.aged_alarm_escalations(signals, now=now) == []


def test_aged_alarm_unparseable_timestamp_never_false_fires():
    from datetime import datetime, timezone

    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    assert agent.aged_alarm_escalations({"alarms": [{"name": "x", "updated": ""}]}, now=now) == []
    assert agent.aged_alarm_escalations({"alarms": [{"name": "x", "updated": "not-a-date"}]}, now=now) == []


def test_main_surfaces_aged_alarm_into_needs_human(monkeypatch, tmp_path):
    # End-to-end non-vacuous proof: the agent transcript classifies grading-stalled
    # as STALE (never naming it in needs_human) yet the deterministic backstop lands
    # it in needs_human anyway. Without the #1204 wiring this assertion fails.
    import json as _json
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=240)).isoformat()
    monkeypatch.setenv("REMEDIATION_REPORT_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(agent, "gate", lambda: "shadow")
    monkeypatch.setattr(
        agent,
        "gather_signals",
        lambda ev: {
            "alarms": [{"name": "grading-stalled", "updated": old}],
            "ci_failures": [],
            "dlq": {},
            "coherence": None,
            "drift": None,
            "urgent": None,
        },
    )
    monkeypatch.setattr(agent, "load_ack_ledger", lambda: {})
    monkeypatch.setattr(agent, "build_prompt", lambda mode, signals: "prompt")
    transcript = (
        "Triaged grading-stalled → stale.\n"
        '```json\n{"auto_fixed": [], "prs": [], "needs_human": [], '
        '"stale": [{"summary": "grading-stalled looked cleared"}], "untriaged": []}\n```'
    )

    async def _fake(prompt):
        return transcript

    monkeypatch.setattr(agent, "run_agent", _fake)
    monkeypatch.setattr(agent, "update_ack_ledger", lambda *a, **k: {})
    monkeypatch.setattr(agent, "audit_log", lambda *a, **k: None)
    monkeypatch.setattr(agent, "email_report", lambda *a, **k: None)

    code = agent.main()
    report = _json.load(open(tmp_path / "r.json"))
    nh_text = _json.dumps(report["needs_human"])
    assert "grading-stalled" in nh_text
    assert "240h" in nh_text or "10.0d" in nh_text
    assert code == 0


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
