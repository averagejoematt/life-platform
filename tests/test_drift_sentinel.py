"""Tests for the weekly drift sentinel (#394) — deploy/drift_sentinel.py and the
remediation/drift_report.py report seam. All hermetic (no AWS): AWS-touching checks are
monkeypatched or fed fake clients."""

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "remediation")):
    if p not in sys.path:
        sys.path.insert(0, p)

import drift_report  # noqa: E402
import drift_sentinel as ds  # noqa: E402

# ── bucket-policy delete-protection (AC3) ────────────────────────────────────


class _FakeS3:
    def __init__(self, policy):
        self._policy = policy

    def get_bucket_policy(self, Bucket):  # noqa: N803 — boto3 kwarg casing
        if self._policy is None:
            raise RuntimeError("no policy")
        return {"Policy": json.dumps(self._policy)}


def _src_policy():
    with open(os.path.join(_ROOT, "deploy", "bucket_policy.json")) as f:
        return json.load(f)


def test_protect_prefixes_extracts_deny_resources():
    prefixes = ds._protect_prefixes(_src_policy())
    assert any(r.endswith("/raw/*") for r in prefixes)
    assert any(r.endswith("/config/*") for r in prefixes)
    assert len(prefixes) >= 5


def test_bucket_policy_clean_when_live_matches_source(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3(_src_policy()))
    res = ds.check_bucket_policy()
    assert res["status"] == "clean"
    assert res["missing_prefixes"] == []


def test_bucket_policy_drift_when_a_prefix_is_dropped(monkeypatch):
    weakened = json.loads(json.dumps(_src_policy()))
    for st in weakened["Statement"]:
        if st.get("Sid") == "ProtectDataFromDeployScripts":
            st["Resource"] = [r for r in st["Resource"] if not r.endswith("/raw/*")]
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3(weakened))
    res = ds.check_bucket_policy()
    assert res["status"] == "drift"
    assert any(r.endswith("/raw/*") for r in res["missing_prefixes"])


def test_bucket_policy_drift_when_statement_missing(monkeypatch):
    stripped = {
        "Version": "2012-10-17",
        "Statement": [s for s in _src_policy()["Statement"] if s.get("Sid") != "ProtectDataFromDeployScripts"],
    }
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3(stripped))
    res = ds.check_bucket_policy()
    assert res["status"] == "drift"


def test_bucket_policy_error_is_soft(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3(None))
    res = ds.check_bucket_policy()
    assert res["status"] == "error"


# ── orphan allowlist (AC2 — no functions outside IaC) ────────────────────────


def test_orphan_allowlist_excludes_cdk_bootstrap():
    assert "cdk-hnb659fds-assets".startswith(ds._ORPHAN_ALLOW_PREFIXES)
    assert not "life-platform-whoop".startswith(ds._ORPHAN_ALLOW_PREFIXES)


# ── sweep status aggregation + summary (AC1/AC4) ─────────────────────────────


def _patch_all(monkeypatch, cfn, post, orphan, bucket, doc=None):
    monkeypatch.setattr(ds, "check_cfn_drift", lambda *a, **k: cfn)
    monkeypatch.setattr(ds, "check_postflight", lambda: post)
    monkeypatch.setattr(ds, "check_orphan_functions", lambda: orphan)
    monkeypatch.setattr(ds, "check_bucket_policy", lambda: bucket)
    monkeypatch.setattr(ds, "check_doc_literals", lambda: doc or {"status": "clean", "mismatches": []})


def test_sweep_clean(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "clean"
    assert "All clear" in rec["summary"]
    assert set(rec) >= {"date", "generated_at", "status", "summary", "checks"}


def test_sweep_drift_wins(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "drift", "stacks": {"LifePlatformCore": {"status": "drift", "drifted": []}}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "error"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"  # drift outranks an error
    assert "LifePlatformCore" in rec["summary"]


def test_sweep_degraded_when_error_no_drift(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "degraded", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean"},
        bucket={"status": "clean"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "degraded"


def test_sweep_doc_literal_drift(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean"},
        doc={"status": "drift", "mismatches": [{"fact": "alarm_count", "documented": 110, "live": 122, "fix": "…"}]},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "doc-literal" in rec["summary"]


# ── report seam (AC4) ────────────────────────────────────────────────────────


def test_as_signal_only_on_real_drift():
    assert drift_report.as_signal({"status": "clean"}) is None
    assert drift_report.as_signal({"status": "degraded"}) is None
    assert drift_report.as_signal(None) is None
    sig = drift_report.as_signal(
        {
            "status": "drift",
            "date": "2026-07-06",
            "summary": "1 stack drifted",
            "checks": {"cfn_drift": {"status": "drift"}, "bucket_policy": {"status": "clean"}},
        }
    )
    assert sig["class"] == "needs-human"
    assert "cfn_drift" in sig["flagging"]
    assert "bucket_policy" not in sig["flagging"]


def test_status_html_is_loud_for_every_state():
    assert drift_report.status_html(None) == ""
    clean = drift_report.status_html({"status": "clean", "date": "d", "summary": "All clear"})
    assert "in sync" in clean and "All clear" in clean
    drift = drift_report.status_html({"status": "drift", "date": "d", "summary": "x"})
    assert "DRIFT" in drift
    degraded = drift_report.status_html({"status": "degraded", "date": "d", "summary": "y"})
    assert "degraded" in degraded


def test_read_latest_fail_soft():
    class _Boom:
        def get_object(self, **k):
            raise RuntimeError("nope")

    assert drift_report.read_latest(_Boom(), "bucket") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
