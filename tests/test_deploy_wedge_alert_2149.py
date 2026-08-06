"""tests/test_deploy_wedge_alert_2149.py — last-mile alerting for a confirmed deploy
wedge (#2149).

#2052 proved DETECTION: `check_deploy_wedge.py` correctly tells a phantom wedge and a
stranded approval apart from the states that look identical to them. What #2052 never
built was the last mile — a red scheduled workflow reaches nobody (the 2026-08-05
incident: 6 red runs over ~9h, zero human notified until a manual run). This file
proves the throttle/dedup/payload logic added in `check_deploy_wedge.py` for that last
mile: `alert_candidate`, `should_fire_alert`, `build_dispatch_payload`,
`build_alert_marker`/`parse_alert_marker`, and the `maybe_alert` orchestrator (I/O calls
monkeypatched — never a real `gh` invocation).

Per the issue's acceptance criteria, the workflow YAML change (permissions + the
`--alert` flag wired into deploy-wedge-watch.yml) is prose-verified in review, not unit
tested here — only the pure Python decision/payload logic is.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_deploy_wedge as cdw  # noqa: E402

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "deploy_wedge")


def load(name):
    with open(os.path.join(_FIXTURES, f"{name}.json"), encoding="utf-8") as f:
        data = json.load(f)
    now = datetime.fromisoformat(data["now"].replace("Z", "+00:00"))
    return data, now


def classify(name, threshold=cdw.DEFAULT_THRESHOLD_MIN):
    data, now = load(name)
    return cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now, threshold_min=threshold)


# --------------------------------------------------------------------------
# alert_candidate — which verdict (if any) should page a human.
# --------------------------------------------------------------------------


def test_alert_candidate_is_none_for_the_two_non_incident_states():
    assert cdw.alert_candidate(classify("queued_behind")) is None
    assert cdw.alert_candidate(classify("awaiting_approval")) is None


def test_alert_candidate_finds_the_phantom_wedge():
    v = cdw.alert_candidate(classify("phantom_wedge"))
    assert v is not None
    assert v["kind"] == cdw.PHANTOM_WEDGE
    assert v["run_id"] == 30769861255


def test_alert_candidate_finds_the_stranded_approval():
    v = cdw.alert_candidate(classify("stranded_approval"))
    assert v is not None
    assert v["kind"] == cdw.STRANDED_APPROVAL


def test_an_empty_fleet_has_no_alert_candidate():
    assert cdw.alert_candidate(cdw.classify_fleet([], {}, {}, now=datetime.now(timezone.utc))) is None


# --------------------------------------------------------------------------
# build_dispatch_payload — the acceptance bullet: run id, gate age, recovery line.
# --------------------------------------------------------------------------


def test_payload_names_the_run_id_age_and_recovery_line_for_a_phantom_wedge():
    verdict = cdw.alert_candidate(classify("phantom_wedge"))
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    payload = cdw.build_dispatch_payload(verdict, now)

    assert payload["run_id"] == verdict["run_id"] == 30769861255
    assert payload["blocked_minutes"] == verdict["blocked_minutes"]  # the gate age
    # The exact recovery text check_deploy_wedge.py already prints, verbatim in `reason`.
    assert "gh run cancel 30769861255" in payload["reason"]
    assert "deploy_all=true" in payload["reason"]
    assert payload["kind"] == cdw.PHANTOM_WEDGE
    assert payload["timestamp"] == "2026-08-05T12:00:00Z"


def test_payload_names_the_approve_deployment_recovery_line_for_a_stranded_approval():
    verdict = cdw.alert_candidate(classify("stranded_approval"))
    payload = cdw.build_dispatch_payload(verdict, datetime.now(timezone.utc))
    assert f"approve_deployment.sh {verdict['run_id']}" in payload["reason"]


def test_payload_shape_matches_what_remediation_dispatcher_lambda_already_sends():
    """remediation/agent.py's signals["urgent"] handling must need zero changes to
    consume this — same top-level keys the CloudWatch-alarm path already uses."""
    verdict = cdw.alert_candidate(classify("phantom_wedge"))
    payload = cdw.build_dispatch_payload(verdict, datetime.now(timezone.utc))
    for key in ("alarm_name", "state", "reason", "timestamp"):
        assert key in payload
    assert payload["state"] == "ALARM"


# --------------------------------------------------------------------------
# build_alert_marker / parse_alert_marker — the throttle state carrier.
# --------------------------------------------------------------------------


def test_marker_roundtrips():
    marker = cdw.build_alert_marker(30769861255, "2026-08-05T10:00:00Z")
    body = f"some issue body text\n\n{marker}\n"
    parsed = cdw.parse_alert_marker(body)
    assert parsed == {"run_id": 30769861255, "alerted_at": "2026-08-05T10:00:00Z"}


def test_parse_alert_marker_handles_absent_or_malformed_body():
    assert cdw.parse_alert_marker(None) is None
    assert cdw.parse_alert_marker("") is None
    assert cdw.parse_alert_marker("no marker here at all") is None
    assert cdw.parse_alert_marker("<!-- deploy-wedge-alert: not-json -->") is None
    assert cdw.parse_alert_marker('<!-- deploy-wedge-alert: {"run_id": 1} -->') is None  # missing alerted_at
    assert cdw.parse_alert_marker("<!-- deploy-wedge-alert: [1,2,3] -->") is None  # not an object


# --------------------------------------------------------------------------
# should_fire_alert — the whole throttle decision. This is the load-bearing
# guarantee: N reds over one episode collapse to exactly 1 alert.
# --------------------------------------------------------------------------


def test_fires_on_first_alert_of_an_episode_no_prior_state():
    assert cdw.should_fire_alert(123, datetime.now(timezone.utc), None) is True


def test_does_not_refire_within_the_same_episode_minutes_later():
    now = datetime(2026, 8, 5, 10, 5, tzinfo=timezone.utc)
    last = {"run_id": 123, "alerted_at": "2026-08-05T10:00:00Z"}
    assert cdw.should_fire_alert(123, now, last) is False


def test_this_is_what_collapses_six_reds_over_nine_hours_to_one_alert():
    """The exact incident shape: repeated ticks of the same episode, same run id,
    well inside the 24h rearm window, must never refire after the first."""
    last = {"run_id": 999, "alerted_at": "2026-08-05T09:00:00Z"}
    for hours_later in (0.25, 1, 3, 6, 9):
        now = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc) + timedelta(hours=hours_later)
        assert cdw.should_fire_alert(999, now, last) is False


def test_fires_again_for_a_new_episode_different_run_id():
    now = datetime(2026, 8, 5, 10, 1, tzinfo=timezone.utc)  # 1 minute after the old alert
    last = {"run_id": 123, "alerted_at": "2026-08-05T10:00:00Z"}
    assert cdw.should_fire_alert(456, now, last) is True


def test_rearms_after_the_long_window_same_run_id():
    last = {"run_id": 123, "alerted_at": "2026-08-04T10:00:00Z"}
    just_under = datetime(2026, 8, 5, 9, 59, tzinfo=timezone.utc)  # 23h59m later
    just_over = datetime(2026, 8, 5, 10, 1, tzinfo=timezone.utc)  # 24h1m later
    assert cdw.should_fire_alert(123, just_under, last) is False
    assert cdw.should_fire_alert(123, just_over, last) is True


def test_a_corrupt_timestamp_fails_toward_alerting_not_silence():
    last = {"run_id": 123, "alerted_at": "not-a-timestamp"}
    assert cdw.should_fire_alert(123, datetime.now(timezone.utc), last) is True


# --------------------------------------------------------------------------
# maybe_alert — the orchestrator. All I/O monkeypatched; no real `gh` call ever
# happens in this test file, matching the "must not exercise the write path
# locally" constraint.
# --------------------------------------------------------------------------


def test_maybe_alert_fires_dispatches_and_writes_the_marker_on_a_fresh_wedge(monkeypatch):
    calls = {}
    monkeypatch.setattr(cdw, "_find_alert_issue", lambda: None)
    monkeypatch.setattr(cdw, "_dispatch_urgent_alarm", lambda payload: calls.setdefault("dispatched", payload))
    monkeypatch.setattr(
        cdw, "_upsert_alert_issue", lambda verdict, now, existing: calls.setdefault("upserted", (verdict["run_id"], existing))
    )
    monkeypatch.setattr(cdw, "_close_alert_issue", lambda existing, now: calls.setdefault("closed", True))

    state = classify("phantom_wedge")
    result = cdw.maybe_alert(state, now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))

    assert "dispatched" in calls
    assert calls["dispatched"]["run_id"] == 30769861255
    assert "upserted" in calls
    assert "closed" not in calls
    assert "alert-fired" in result
    assert "30769861255" in result


def test_maybe_alert_throttles_a_second_call_for_the_same_episode(monkeypatch):
    calls = []
    run_id = cdw.alert_candidate(classify("phantom_wedge"))["run_id"]
    existing_issue = {"number": 1, "body": cdw.build_alert_marker(run_id, "2026-08-05T11:55:00Z")}
    monkeypatch.setattr(cdw, "_find_alert_issue", lambda: existing_issue)
    monkeypatch.setattr(cdw, "_dispatch_urgent_alarm", lambda payload: calls.append("dispatch"))
    monkeypatch.setattr(cdw, "_upsert_alert_issue", lambda *a, **k: calls.append("upsert"))
    monkeypatch.setattr(cdw, "_close_alert_issue", lambda *a, **k: calls.append("close"))

    state = classify("phantom_wedge")
    result = cdw.maybe_alert(state, now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))  # 5 min later

    assert calls == []
    assert "alert-throttled" in result


def test_maybe_alert_rearms_and_closes_the_tracking_issue_once_the_wedge_clears(monkeypatch):
    calls = []
    existing_issue = {"number": 7, "body": cdw.build_alert_marker(123, "2026-08-05T01:00:00Z")}
    monkeypatch.setattr(cdw, "_find_alert_issue", lambda: existing_issue)
    monkeypatch.setattr(cdw, "_dispatch_urgent_alarm", lambda payload: calls.append("dispatch"))
    monkeypatch.setattr(cdw, "_upsert_alert_issue", lambda *a, **k: calls.append("upsert"))
    monkeypatch.setattr(cdw, "_close_alert_issue", lambda existing, now: calls.append(("close", existing["number"])))

    # queued_behind is "the invariant working", not an incident kind — the wedge is clear.
    healthy_state = classify("queued_behind")
    result = cdw.maybe_alert(healthy_state, now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))

    assert calls == [("close", 7)]
    assert "alert-rearmed" in result


def test_maybe_alert_is_a_true_noop_when_healthy_with_no_tracking_issue(monkeypatch):
    monkeypatch.setattr(cdw, "_find_alert_issue", lambda: None)

    def explode(*a, **k):
        raise AssertionError("maybe_alert must not shell out when there is nothing to alert or close")

    monkeypatch.setattr(cdw, "_dispatch_urgent_alarm", explode)
    monkeypatch.setattr(cdw, "_upsert_alert_issue", explode)
    monkeypatch.setattr(cdw, "_close_alert_issue", explode)

    result = cdw.maybe_alert(classify("queued_behind"), now=datetime.now(timezone.utc))
    assert "alert-skip" in result


def test_maybe_alert_never_raises_when_the_tracking_issue_read_fails(monkeypatch):
    def explode():
        raise RuntimeError("gh api timed out")

    monkeypatch.setattr(cdw, "_find_alert_issue", explode)
    result = cdw.maybe_alert(classify("phantom_wedge"), now=datetime.now(timezone.utc))
    assert "alert-skipped" in result


def test_maybe_alert_never_raises_when_dispatch_fails(monkeypatch):
    """A GitHub API hiccup during the alert must not blow up the run — the detector's
    own exit code (already decided by render()) is what must survive, not this."""
    monkeypatch.setattr(cdw, "_find_alert_issue", lambda: None)

    def explode(payload):
        raise RuntimeError("gh api 403")

    monkeypatch.setattr(cdw, "_dispatch_urgent_alarm", explode)
    result = cdw.maybe_alert(classify("phantom_wedge"), now=datetime.now(timezone.utc))
    assert "alert-error" in result


# --------------------------------------------------------------------------
# CLI wiring — --alert must exist and must not change the exit-code contract.
# --------------------------------------------------------------------------


def test_main_calls_maybe_alert_only_when_the_alert_flag_is_passed(monkeypatch):
    """Exercises the real CLI wiring in main(): --alert must reach maybe_alert(); its
    absence must not (no behavior change for the plain #2052 detect-only invocation)."""
    # main() classifies against the REAL wall clock (it has no `--now` override), so
    # this relies on the fixture's 2026-08-02/03 timestamps always being in the past —
    # blocked_minutes is then always far past any small threshold, still PHANTOM_WEDGE.
    data, _fixture_now = load("phantom_wedge")
    monkeypatch.setattr(cdw, "collect", lambda: (data["runs"], data["jobs"], data["pending"]))

    calls = []
    monkeypatch.setattr(cdw, "maybe_alert", lambda state: calls.append(state["kind"]) or "alert-fired: stub")

    monkeypatch.setattr(sys, "argv", ["check_deploy_wedge.py", "--threshold", "4", "--alert"])
    code = cdw.main()
    assert code == 1  # phantom wedge still exits 1 — alerting must not change the contract
    assert calls == [cdw.PHANTOM_WEDGE]

    calls.clear()
    monkeypatch.setattr(sys, "argv", ["check_deploy_wedge.py", "--threshold", "4"])
    code = cdw.main()
    assert code == 1
    assert calls == []  # no --alert flag -> maybe_alert never called
