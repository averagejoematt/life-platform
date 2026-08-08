"""tests/test_canary_lane_split.py — #2051: a stale data row must not revert a
correct deploy, and a broken round-trip still must.

The incident (2026-08-02, production): the canary's DDB, S3, MCP and Bedrock
round-trips ALL passed. One synthetic `source='canary'` subscriber row, written
twelve days earlier, had survived cleanup — #1954's postcondition — and that
alone made the canary return 500, made `smoke-test` red, and fired
`rollback-on-smoke-failure`, which stripped out a verified-correct fleet
deploy. While that row existed, no deploy on the platform could survive.

So the guard has to be a PAIR — a lane split you can only trust if you have
watched it fire both ways:

  * healthy infra + non-zero residue  → NOT gating (this file's core assertion,
                                        and the exact 2026-08-02 payload shape)
  * failing infra                     → gating, unchanged

Everything here is offline: scripted fakes, no MagicMock (a MagicMock feeding
the residue pagination loop returns truthy LastEvaluatedKeys forever).
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lambdas"))
sys.path.insert(0, str(_ROOT / "lambdas" / "operational"))

import canary_lambda as canary  # noqa: E402
from operational import canary_lanes  # noqa: E402

# The oracle is a script, not a package module — load it the way the workflow does.
_SCRIPT = _ROOT / "deploy" / "lib" / "smoke_oracle_decision.py"
_spec = importlib.util.spec_from_file_location("smoke_oracle_decision", _SCRIPT)
sod = importlib.util.module_from_spec(_spec)
sys.modules["smoke_oracle_decision"] = sod
_spec.loader.exec_module(sod)


# ── The registry ──────────────────────────────────────────────────────────────


def test_every_infra_round_trip_gates():
    """The four live round-trips plus the subscribe flow itself are gating —
    a rollback is a plausible fix for each."""
    for key in ("dynamodb", "s3", "mcp", "anthropic", "subscribe"):
        assert canary_lanes.lane_for(key) == canary_lanes.LANE_INFRA, key


def test_postconditions_about_stored_state_do_not_gate():
    for key in ("subscribe_residue", "subscribe_cleanup"):
        assert canary_lanes.lane_for(key) == canary_lanes.LANE_STORED_STATE, key


def test_unregistered_check_defaults_to_gating():
    """The conservative direction: a new check keeps gating until someone
    classifies it. The other default would let a real outage land silently in
    the non-gating lane — worse than the false rollback this module prevents."""
    assert canary_lanes.lane_for("some_future_check") == canary_lanes.LANE_INFRA


def test_lane_counts_ignore_skipped_checks():
    """`ok is None` = skipped (unresolved MCP URL, no Bedrock client). A skip
    must not be laundered into either lane's failure count."""
    counts = canary_lanes.lane_counts(
        {
            "dynamodb": {"ok": True},
            "mcp": {"ok": None},
            "anthropic": {"ok": False},
            "subscribe_residue": {"ok": False},
        }
    )
    assert counts[canary_lanes.LANE_INFRA] == 1
    assert counts[canary_lanes.LANE_STORED_STATE] == 1


def test_lane_summary_names_the_failing_checks():
    summary = canary_lanes.lane_summary({"s3": {"ok": False}, "subscribe_residue": {"ok": False}, "mcp": {"ok": True}})
    assert summary[canary_lanes.LANE_INFRA]["failed_checks"] == ["s3"]
    assert summary[canary_lanes.LANE_STORED_STATE]["failed_checks"] == ["subscribe_residue"]


# ── The handler: what the canary actually returns ─────────────────────────────


class _StateDDB:
    """Scripted client for the consecutive-failure state row."""

    def __init__(self):
        self.put_items = []

    def get_item(self, **kwargs):
        return {}

    def put_item(self, **kwargs):
        self.put_items.append(kwargs)
        return {}


def _run_handler(monkeypatch, *, infra_ok=True, residue_rows=0, cleanup_ok=True):
    """Invoke the real handler with every probe stubbed."""
    monkeypatch.setattr(canary, "check_dynamodb", lambda ts, p: (infra_ok, "ddb msg", 10.0))
    monkeypatch.setattr(canary, "check_s3", lambda ts, p: (True, "s3 msg", 10.0))
    monkeypatch.setattr(canary, "check_mcp", lambda ts: (True, "76 tools listed", 10.0))
    monkeypatch.setattr(canary, "check_anthropic", lambda ts: (True, "Bedrock OK", 10.0))

    extras = {
        "subscribe_cleanup": {"ok": cleanup_ok, "message": "cleanup" if cleanup_ok else "cleanup delete failed"},
        "subscribe_residue": {
            "ok": residue_rows == 0,
            "message": f"{residue_rows} synthetic canary row(s) survived cleanup (#1954)",
            "residue_rows": residue_rows,
        },
    }
    monkeypatch.setattr(canary, "check_subscribe_flow", lambda ts: (True, "subscribe flow OK", 10.0, extras))
    monkeypatch.setattr(canary, "emit", lambda *a, **k: None)

    alerts = []
    # #2222: send_alert now takes the dry_run suppressor flag the handler derives
    # from the invoke event; the stub has to accept it or the handler's call raises.
    monkeypatch.setattr(canary, "send_alert", lambda failures, ts, dry_run=False: alerts.append(failures))

    class _FakeBoto3:
        def client(self, name, region_name=None):
            return _StateDDB()

    monkeypatch.setattr(canary, "boto3", _FakeBoto3())

    resp = canary.lambda_handler({}, None)
    return resp, json.loads(resp["body"]), alerts


def test_healthy_infra_plus_stale_row_does_not_gate(monkeypatch):
    """THE regression guard — the literal 2026-08-02 shape.

    Every round-trip green, one leftover row. The gating counter must be 0 and
    the statusCode must be 200, or `rollback-on-smoke-failure` fires again and
    strips another correct deploy.
    """
    resp, body, _alerts = _run_handler(monkeypatch, infra_ok=True, residue_rows=1)

    assert body["failed_deploy_health"] == 0, "a leftover row must not read as deploy health"
    assert resp["statusCode"] == 200, "statusCode is the infra verdict; 500 here re-arms the rollback"

    # ...and it is not silently swallowed either: still counted, still honest.
    assert body["failed_stored_state"] == 1
    assert body["all_pass"] is False
    assert body["failures"] == 1
    assert body["lanes"]["stored_state"]["failed_checks"] == ["subscribe_residue"]
    assert body["results"]["subscribe_residue"]["residue_rows"] == 1


def test_infra_failure_still_gates(monkeypatch):
    """The other half of the pair: a broken round-trip must keep firing the
    rollback. A lane split that only ever suppresses is not a split."""
    resp, body, _alerts = _run_handler(monkeypatch, infra_ok=False)

    assert body["failed_deploy_health"] == 1
    assert resp["statusCode"] == 500
    assert body["lanes"]["infra"]["failed_checks"] == ["dynamodb"]


def test_both_lanes_failing_gates_on_the_infra_half(monkeypatch):
    resp, body, _alerts = _run_handler(monkeypatch, infra_ok=False, residue_rows=2)
    assert body["failed_deploy_health"] == 1
    assert body["failed_stored_state"] == 1
    assert resp["statusCode"] == 500


def test_clean_run_reports_both_lanes_zero(monkeypatch):
    resp, body, alerts = _run_handler(monkeypatch)
    assert resp["statusCode"] == 200
    assert body["all_pass"] is True
    assert body["failed_deploy_health"] == 0 and body["failed_stored_state"] == 0
    assert alerts == []


def test_stored_state_failure_alerts_on_the_FIRST_occurrence(monkeypatch):
    """De-gating is only defensible if it is not also a mute. The row that
    caused the incident sat for twelve days: the two-consecutive-runs
    suppression is right for a transient round-trip and wrong for a fact that
    persists until someone deletes it."""
    _resp, _body, alerts = _run_handler(monkeypatch, residue_rows=1)
    assert alerts, "a stored-state failure must email on the day it appears"
    assert [f["check_key"] for f in alerts[0]] == ["subscribe_residue"]


def test_cleanup_failure_is_reported_as_its_own_check(monkeypatch):
    """The root cause, not just the aftermath: the silent cleanup `pass` is how
    the stray row went unseen. It is now a check with its own metric+alarm."""
    _resp, body, alerts = _run_handler(monkeypatch, cleanup_ok=False)
    assert body["results"]["subscribe_cleanup"]["ok"] is False
    assert body["failed_stored_state"] == 1
    assert body["failed_deploy_health"] == 0
    assert [f["check_key"] for f in alerts[0]] == ["subscribe_cleanup"]


def test_first_occurrence_infra_failure_is_still_suppressed(monkeypatch):
    """Unchanged behaviour for the infra lane — transient blips still wait for
    a repeat before emailing (they already gate the pipeline loudly)."""
    _resp, _body, alerts = _run_handler(monkeypatch, infra_ok=False)
    assert alerts == []


# ── The oracle: what CI does with that response ───────────────────────────────


def _canary_payload(tmp_path, **body):
    payload = {"statusCode": body.pop("statusCode", 200), "body": json.dumps(body)}
    p = tmp_path / "canary.json"
    p.write_text(json.dumps(payload))
    return str(p)


def test_oracle_passes_healthy_infra_with_residue(tmp_path):
    """End of the chain: the 2026-08-02 body must exit 0, so smoke-test stays
    green and the rollback job's `if` never becomes true."""
    path = _canary_payload(
        tmp_path,
        statusCode=200,
        canary_ts="2026-08-02T00:00:00Z",
        all_pass=False,
        failures=1,
        failed_deploy_health=0,
        failed_stored_state=1,
    )
    verdict, _detail = sod.decide(path, ok_extra=["healthy"])
    assert verdict == "PASS"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) == 0


def test_oracle_still_names_the_residue_it_refuses_to_gate_on(tmp_path):
    path = _canary_payload(tmp_path, statusCode=200, all_pass=False, failures=1, failed_deploy_health=0, failed_stored_state=3)
    assert sod.stored_state_count(path) == 3


def test_oracle_fails_on_infra_lane(tmp_path):
    path = _canary_payload(tmp_path, statusCode=500, all_pass=False, failures=1, failed_deploy_health=1, failed_stored_state=0)
    verdict, detail = sod.decide(path, ok_extra=["healthy"])
    assert verdict == "FAIL"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) != 0
    assert "500" in detail or "failed_deploy_health" in detail


def test_oracle_fails_on_infra_lane_even_when_statuscode_is_200(tmp_path):
    """Belt and braces: the body is authoritative on its own, so a lane-aware
    body cannot pass by dressing itself in a 200."""
    path = _canary_payload(tmp_path, statusCode=200, all_pass=False, failures=1, failed_deploy_health=2, failed_stored_state=0)
    verdict, detail = sod.decide(path, ok_extra=["healthy"])
    assert verdict == "FAIL"
    assert "failed_deploy_health" in detail


def test_legacy_canary_body_without_lanes_still_gates_on_all_pass(tmp_path):
    """Back-compat: an older canary zip (no lane keys) keeps the pre-#2051
    contract — every failure gates. The oracle never fails open on a missing
    key; de-gating is opt-in by publishing lanes."""
    path = _canary_payload(tmp_path, statusCode=200, canary_ts="2026-07-26T00:00:00Z", all_pass=False, failures=2)
    verdict, detail = sod.decide(path, ok_extra=["healthy"])
    assert verdict == "FAIL"
    assert "all_pass" in detail
