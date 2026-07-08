"""tests/test_experiment_prereg_728.py — the public pre-registration artifact (#728, epic #715).

create_experiment must freeze the declared design to a PUBLIC, timestamped S3 artifact
(generated/experiments/prereg/{id}.json) at creation — before any results exist — and
carry the public URL on the DDB record so the experiment page can link the proof.
Fail-soft: an S3 hiccup must not block the experiment, but the response says so.
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_lifestyle as tl  # noqa: E402

STOP = "run the full 21 days regardless of interim trend; abort only if recovery < 40% for 3 consecutive days"
DESIGN = {
    "baseline_days": 14,
    "washout_days": 3,
    "stopping_rule": STOP,
    "criterion": {"metric": "deep_pct", "direction": "higher", "min_effect": 2},
}


class _FakeS3:
    def __init__(self, fail=False):
        self.fail = fail
        self.puts = []

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("S3 down")
        self.puts.append(kw)


def _run(monkeypatch, design, s3):
    table = FakeDdbTable()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "s3_client", s3)
    args = {"name": "Prereg Test", "hypothesis": "deep sleep rises", "start_date": "2026-07-10"}
    if design is not None:
        args["design"] = design
    return tl.tool_create_experiment(args), table


def test_artifact_written_with_design(monkeypatch):
    s3 = _FakeS3()
    resp, table = _run(monkeypatch, DESIGN, s3)

    # One artifact, at the contract key, valid JSON, carrying the frozen promise.
    assert len(s3.puts) == 1
    put = s3.puts[0]
    assert put["Key"] == "generated/experiments/prereg/prereg-test_2026-07-10.json"
    assert put["ContentType"] == "application/json"
    body = json.loads(put["Body"])
    assert body["experiment_id"] == "prereg-test_2026-07-10"
    assert body["design"]["stopping_rule"] == STOP
    assert body["design"]["criterion"]["metric"] == "deep_pct"
    assert body["registered_at"].endswith("Z")
    assert "before any results existed" in body["contract"]

    # The DDB record carries the key + public URL; the response returns the URL.
    item = table.puts[0]
    assert item["prereg_key"] == put["Key"]
    assert item["prereg_url"] == "https://averagejoematt.com/experiments/prereg/prereg-test_2026-07-10.json"
    assert resp["pre_registration_url"] == item["prereg_url"]
    assert "pre_registration_warning" not in resp


def test_no_design_means_no_artifact(monkeypatch):
    s3 = _FakeS3()
    resp, table = _run(monkeypatch, None, s3)
    assert s3.puts == []
    assert resp["pre_registration_url"] is None
    assert "prereg_key" not in table.puts[0]


def test_s3_failure_is_failsoft_and_honest(monkeypatch):
    s3 = _FakeS3(fail=True)
    resp, table = _run(monkeypatch, DESIGN, s3)
    # Experiment still exists...
    assert len(table.puts) == 1
    assert resp["created"] is True
    # ...but nothing pretends there is a public proof.
    assert resp["pre_registration_url"] is None
    assert "could NOT be written" in resp["pre_registration_warning"]
    assert "prereg_key" not in table.puts[0]
    assert "prereg_url" not in table.puts[0]


def test_design_without_stopping_rule_rejected(monkeypatch):
    s3 = _FakeS3()
    d = {k: v for k, v in DESIGN.items() if k != "stopping_rule"}
    try:
        _run(monkeypatch, d, s3)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "stopping_rule" in str(e)
    assert s3.puts == []  # rejected before any write
