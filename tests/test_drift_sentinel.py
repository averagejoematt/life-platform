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


# ── site/main SHA ancestry (#751) ────────────────────────────────────────────


class _FakeCompleted:
    def __init__(self, returncode):
        self.returncode = returncode


def test_site_sha_ancestry_clean_when_sha_is_ancestor(monkeypatch):
    monkeypatch.setattr(ds, "_fetch_live_version", lambda url: {"build": "abc1234"})
    monkeypatch.setattr(ds, "_git_fetch_main", lambda: None)
    monkeypatch.setattr(ds, "_merge_base_is_ancestor", lambda sha, ref="origin/main": _FakeCompleted(0))
    res = ds.check_site_sha_ancestry()
    assert res == {"status": "clean", "live_sha": "abc1234"}


def test_site_sha_ancestry_drift_when_sha_diverged(monkeypatch):
    monkeypatch.setattr(ds, "_fetch_live_version", lambda url: {"build": "deadbee"})
    monkeypatch.setattr(ds, "_git_fetch_main", lambda: None)
    monkeypatch.setattr(ds, "_merge_base_is_ancestor", lambda sha, ref="origin/main": _FakeCompleted(1))
    res = ds.check_site_sha_ancestry()
    assert res["status"] == "drift"
    assert "diverged" in res["detail"]


def test_site_sha_ancestry_drift_when_sha_unknown(monkeypatch):
    monkeypatch.setattr(ds, "_fetch_live_version", lambda url: {"build": "0000000"})
    monkeypatch.setattr(ds, "_git_fetch_main", lambda: None)
    monkeypatch.setattr(ds, "_merge_base_is_ancestor", lambda sha, ref="origin/main": _FakeCompleted(128))
    res = ds.check_site_sha_ancestry()
    assert res["status"] == "drift"
    assert "not found in git history" in res["detail"]


def test_site_sha_ancestry_error_on_fetch_failure(monkeypatch):
    def _boom(url):
        raise RuntimeError("timed out")

    monkeypatch.setattr(ds, "_fetch_live_version", _boom)
    res = ds.check_site_sha_ancestry()
    assert res["status"] == "error"
    assert "timed out" in res["detail"]


def test_site_sha_ancestry_error_when_build_field_missing(monkeypatch):
    monkeypatch.setattr(ds, "_fetch_live_version", lambda url: {})
    res = ds.check_site_sha_ancestry()
    assert res["status"] == "error"
    assert "build" in res["detail"]


def test_site_sha_ancestry_survives_git_fetch_failure(monkeypatch):
    # A stale local ref is still useful — a `git fetch` failure (offline runner, rate
    # limit) must not turn into a hard error.
    def _boom():
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(ds, "_fetch_live_version", lambda url: {"build": "abc1234"})
    monkeypatch.setattr(ds, "_git_fetch_main", _boom)
    monkeypatch.setattr(ds, "_merge_base_is_ancestor", lambda sha, ref="origin/main": _FakeCompleted(0))
    res = ds.check_site_sha_ancestry()
    assert res["status"] == "clean"


# ── sweep status aggregation + summary (AC1/AC4) ─────────────────────────────


def _patch_all(monkeypatch, cfn, post, orphan, bucket, doc=None, site=None, oidc=None):
    monkeypatch.setattr(ds, "check_cfn_drift", lambda *a, **k: cfn)
    monkeypatch.setattr(ds, "check_postflight", lambda: post)
    monkeypatch.setattr(ds, "check_orphan_functions", lambda: orphan)
    monkeypatch.setattr(ds, "check_bucket_policy", lambda: bucket)
    monkeypatch.setattr(ds, "check_doc_literals", lambda: doc or {"status": "clean", "mismatches": []})
    monkeypatch.setattr(ds, "check_site_sha_ancestry", lambda: site or {"status": "clean", "live_sha": "deadbeef"})
    monkeypatch.setattr(ds, "check_oidc_iam", lambda: oidc or {"status": "clean"})


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


def test_sweep_site_sha_drift(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean"},
        site={"status": "drift", "live_sha": "deadbee", "detail": "live SHA 'deadbee' exists but is not an ancestor of origin/main"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "live site SHA not on main" in rec["summary"]


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


# ── OIDC/IAM identity drift (#687 S-E6-01) ───────────────────────────────────


def test_oidc_iam_clean_on_zero_exit(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _FakeCompleted(0))
    assert ds.check_oidc_iam()["status"] == "clean"


def test_oidc_iam_drift_surfaces_mismatch_lines(monkeypatch):
    out = "DRIFT — 1 target(s) differ:\n  [DRIFT] github-actions-deploy-role:trust-policy\n"
    fake = _FakeCompleted(1)
    fake.stdout = out
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
    res = ds.check_oidc_iam()
    assert res["status"] == "drift"
    assert any("deploy-role" in m for m in res["mismatches"])


# ── #1227 — a dead cfn_drift capability must escalate, not report soft ────────
class _FakeCfn:
    """A CloudFormation client whose detect_stack_drift raises a chosen error —
    stands in for the live AccessDenied the sentinel hit on all 9 stacks (2026-07-13)."""

    def __init__(self, exc):
        self._exc = exc

    def detect_stack_drift(self, StackName):  # noqa: N803 — boto3 kwarg casing
        raise self._exc


def test_cfn_drift_all_access_denied_escalates_to_error(monkeypatch):
    # Every stack's detect_stack_drift fails with AccessDenied (the missing
    # cloudformation:DetectStackResourceDrift action fans out per-resource) — the
    # capability is DEAD, so the whole check must report "error", not "degraded".
    monkeypatch.setattr(
        ds,
        "_client",
        lambda *a, **k: _FakeCfn(Exception("AccessDenied: not authorized to perform: cloudformation:DetectStackResourceDrift")),
    )
    res = ds.check_cfn_drift(per_stack_timeout=1)
    assert res["status"] == "error", f"all-AccessDenied must escalate to error, got {res['status']}"
    assert res.get("dead_capability"), "the dead-capability signal must be set for a first-class needs-human surface"
    # non-vacuous: the PRE-#1227 code returned 'degraded' here (saw_error → degraded).


def test_cfn_drift_partial_or_transient_error_stays_degraded(monkeypatch):
    # A NON-AccessDenied error (e.g. a transient throttle/timeout) is fail-soft, not a
    # dead capability — it must stay "degraded" so we don't cry needs-human on a blip.
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfn(Exception("Throttling: rate exceeded")))
    res = ds.check_cfn_drift(per_stack_timeout=1)
    assert res["status"] == "degraded", f"a transient (non-AccessDenied) error must stay degraded, got {res['status']}"
    assert not res.get("dead_capability")


def test_remediation_role_grants_detect_stack_resource_drift():
    # #1227: the drift op fans out to per-resource detection; without this action the
    # sentinel's flagship check is dead-on-arrival. Guard the grant so it can't regress.
    with open(os.path.join(_ROOT, "infra", "iam", "github-actions-remediation-role.permissions.json")) as f:
        doc = json.load(f)
    actions = set()
    for stmt in doc.get("Statement", []):
        act = stmt.get("Action", [])
        actions.update(act if isinstance(act, list) else [act])
    assert "cloudformation:DetectStackResourceDrift" in actions, "remediation role must grant DetectStackResourceDrift (#1227)"
