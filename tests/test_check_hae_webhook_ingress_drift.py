"""Tests for deploy/check_hae_webhook_ingress_drift.py — the standalone gate CLI
(#1946). Thin wrapper around drift_sentinel.check_hae_webhook_ingress; these tests
only cover the CLI's own behavior (exit codes, --json shape) since the check logic
itself is covered by tests/test_drift_sentinel.py."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))

import check_hae_webhook_ingress_drift as cli  # noqa: E402


def test_strict_exits_zero_on_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_hae_webhook_ingress", lambda: {"status": "clean", "cdk_api_id": "p6clybdkkc", "invoke_statements": []})
    monkeypatch.setattr(sys, "argv", ["check_hae_webhook_ingress_drift.py", "--strict"])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "clean" in out


def test_strict_exits_nonzero_on_drift(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "check_hae_webhook_ingress",
        lambda: {"status": "drift", "cdk_api_id": "p6clybdkkc", "invoke_statements": [], "detail": "an out-of-IaC ingress grant"},
    )
    monkeypatch.setattr(sys, "argv", ["check_hae_webhook_ingress_drift.py", "--strict"])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "drift" in out
    assert "teardown_hae_orphan_api.py --apply" in out


def test_non_strict_exits_zero_even_on_drift(monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_hae_webhook_ingress", lambda: {"status": "drift", "cdk_api_id": "p6clybdkkc", "invoke_statements": []})
    monkeypatch.setattr(sys, "argv", ["check_hae_webhook_ingress_drift.py"])
    rc = cli.main()
    assert rc == 0


def test_json_output_is_valid_json(monkeypatch, capsys):
    result = {"status": "clean", "cdk_api_id": "p6clybdkkc", "invoke_statements": [{"sid": "x", "source_arn": "y"}]}
    monkeypatch.setattr(cli, "check_hae_webhook_ingress", lambda: result)
    monkeypatch.setattr(sys, "argv", ["check_hae_webhook_ingress_drift.py", "--json"])
    cli.main()
    out = capsys.readouterr().out
    assert json.loads(out) == result
