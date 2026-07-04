"""tests/test_macrofactor_unknown_csv.py — #469 (B-5, epic #459).

An unknown-format MacroFactor CSV must never 200-skip: by the time the
ingester runs, dropbox_poll has already hash-marked the file processed and
moved it, so a silent skip means an export-format change kills the pipe with
zero retry and zero signal (the 22-day May incident). The handler must archive
the file for forensics and RAISE so the error-alarm path fires.
"""

import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")


@pytest.fixture(autouse=True)
def _stub_aws(monkeypatch):
    fake_boto3 = types.ModuleType("boto3")

    class _FakeTable:
        def put_item(self, **kw):
            pass

        def get_item(self, **kw):
            return {}

    class _FakeDDBResource:
        def Table(self, name):
            return _FakeTable()

    fake_boto3.client = lambda *a, **k: types.SimpleNamespace()
    fake_boto3.resource = lambda *a, **k: _FakeDDBResource()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)


UNKNOWN_CSV = b"Totally,New,Export,Shape\n1,2,3,4\n"


def test_unknown_csv_archives_and_raises(monkeypatch):
    import macrofactor_lambda as mf

    monkeypatch.setattr(
        mf,
        "s3_client",
        types.SimpleNamespace(get_object=lambda Bucket, Key: {"Body": types.SimpleNamespace(read=lambda: UNKNOWN_CSV)}),
    )
    archived = []
    monkeypatch.setattr(mf, "archive_raw", lambda bucket, key, content, subfolder=None: archived.append(subfolder))

    with pytest.raises(ValueError, match="Unknown MacroFactor CSV format"):
        mf.lambda_handler({"bucket": "test-bucket", "key": "uploads/macrofactor/new-shape.csv"}, None)

    assert archived == ["unknown"]


def test_empty_csv_still_skips_quietly(monkeypatch):
    """An empty file is not a format change — the benign 200 skip stays."""
    import macrofactor_lambda as mf

    monkeypatch.setattr(
        mf,
        "s3_client",
        types.SimpleNamespace(get_object=lambda Bucket, Key: {"Body": types.SimpleNamespace(read=lambda: b"")}),
    )
    out = mf.lambda_handler({"bucket": "test-bucket", "key": "uploads/macrofactor/empty.csv"}, None)
    assert out["statusCode"] == 200
