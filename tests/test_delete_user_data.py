"""tests/test_delete_user_data.py — Phase 7.3 delete-account flow.

Covers:
  - Protected users refused (403)
  - Missing user_id → 400
  - Missing confirm + no dry_run → 400
  - Dry run returns plan without deleting
  - Real run requires confirm='DELETE'
  - Audit record written on real deletion
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


def _import(env):
    sys.modules.pop("delete_user_data_lambda", None)
    with patch("boto3.resource") as mr, patch("boto3.client") as mc:
        mr.return_value = MagicMock()
        mc.return_value = MagicMock()
        import delete_user_data_lambda as m

        m._table_mock = m.table
        m._s3_mock = m.s3
        m._secrets_mock = m.secrets
    return m


def test_missing_user_id_returns_400(env):
    m = _import(env)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 400


def test_protected_user_refused(env):
    m = _import(env)
    for protected in ["matthew", "admin", "system"]:
        resp = m.lambda_handler({"user_id": protected, "confirm": "DELETE"}, None)
        assert resp["statusCode"] == 403, f"Protected user {protected!r} not refused"


def test_missing_confirm_or_dryrun_returns_400(env):
    m = _import(env)
    resp = m.lambda_handler({"user_id": "test_user"}, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "dry_run" in body["error"] or "confirm" in body["error"]


def test_dry_run_returns_plan_without_deleting(env):
    m = _import(env)
    # Stub scan/list helpers
    with patch.object(m, "_scan_user_pks", return_value=[{"pk": "USER#x#SOURCE#y", "sk": "DATE#1"}]):
        with patch.object(m, "_list_user_s3_objects", return_value=["raw/x/a.json", "raw/x/b.json"]):
            with patch.object(m, "_list_user_secrets", return_value=["life-platform/x/whoop"]):
                resp = m.lambda_handler({"user_id": "test_user", "dry_run": True}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    plan = body["plan"]
    assert plan["dry_run"] is True
    assert plan["ddb_items"] == 1
    assert plan["s3_objects"] == 2
    assert plan["secrets"] == 1
    # No actual delete calls should have happened
    assert not m._table_mock.batch_writer.called
    assert not m._s3_mock.delete_objects.called


def test_real_run_requires_explicit_confirm(env):
    m = _import(env)
    # Without confirm
    resp = m.lambda_handler({"user_id": "test_user"}, None)
    assert resp["statusCode"] == 400
    # With wrong confirm string
    resp = m.lambda_handler({"user_id": "test_user", "confirm": "yes"}, None)
    assert resp["statusCode"] == 400


def test_real_run_invokes_batch_delete_and_audit(env):
    m = _import(env)
    with patch.object(m, "_scan_user_pks", return_value=[{"pk": "USER#x#SOURCE#y", "sk": "DATE#1"}]):
        with patch.object(m, "_list_user_s3_objects", return_value=[]):
            with patch.object(m, "_list_user_secrets", return_value=[]):
                with patch.object(m, "_batch_delete_ddb", return_value=1) as bd_ddb:
                    with patch.object(m, "_batch_delete_s3", return_value=0):
                        with patch.object(m, "_delete_secrets", return_value=[]):
                            with patch.object(m, "_write_audit_record") as audit:
                                resp = m.lambda_handler(
                                    {"user_id": "test_user", "confirm": "DELETE"},
                                    None,
                                )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ddb_items_deleted"] == 1
    bd_ddb.assert_called_once()
    audit.assert_called_once()
