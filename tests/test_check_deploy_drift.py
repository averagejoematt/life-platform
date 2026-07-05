"""Tests for deploy/check_deploy_drift.py — the dual-deployment-plane guard (#382).

Two checks, tested two different ways:
  1. Checkout freshness is pure git — exercised against a REAL, ephemeral local
     git repo (no network: the "origin" is a local path) so the documented
     near-miss scenario (a branch forked before a sibling's lambdas/ fix
     merged into origin/main) is reproduced end-to-end, not just mocked.
  2. Live-code drift talks to CloudFormation — exercised with a fake client,
     the same hermetic pattern as tests/test_drift_sentinel.py.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))

import check_deploy_drift as cdd  # noqa: E402

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env=_GIT_ENV, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo_pair(tmp_path):
    """Build a local 'origin' + a 'checkout' cloned from it, forked BEFORE a
    lambdas/ fix lands on origin/main — the exact near-miss scenario from the
    epic (#342): a stack deploy from `checkout` would ship stale code."""
    origin = tmp_path / "origin"
    checkout = tmp_path / "checkout"
    origin.mkdir()

    _git(["init", "-q", "-b", "main"], cwd=origin)
    (origin / "lambdas").mkdir()
    (origin / "lambdas" / "foo.py").write_text("v1\n")
    _git(["add", "-A"], cwd=origin)
    _git(["commit", "-q", "-m", "initial"], cwd=origin)

    _git(["clone", "-q", str(origin), str(checkout)], cwd=tmp_path)
    _git(["checkout", "-q", "-b", "feature"], cwd=checkout)  # forks off main here

    return origin, checkout


def test_stale_checkout_is_blocked_when_origin_gained_a_lambda_fix(repo_pair):
    origin, checkout = repo_pair
    # origin/main advances with a lambdas/ fix the feature branch never saw
    (origin / "lambdas" / "foo.py").write_text("v2 - fixed a bug\n")
    _git(["add", "-A"], cwd=origin)
    _git(["commit", "-q", "-m", "fix: bug in foo"], cwd=origin)

    result = cdd.check_checkout_freshness(paths=("lambdas/",), cwd=str(checkout))
    assert result["status"] == "stale"
    assert result["missing_commits"] == 1


def test_docs_only_upstream_change_does_not_count_as_stale(repo_pair):
    origin, checkout = repo_pair
    (origin / "docs").mkdir()
    (origin / "docs" / "notes.md").write_text("notes\n")
    _git(["add", "-A"], cwd=origin)
    _git(["commit", "-q", "-m", "docs: notes"], cwd=origin)

    # guarded paths don't include docs/, so this should NOT block
    result = cdd.check_checkout_freshness(paths=("lambdas/", "cdk/", "mcp/"), cwd=str(checkout))
    assert result["status"] == "fresh"
    assert result["missing_commits"] == 0


def test_up_to_date_checkout_is_fresh(repo_pair):
    origin, checkout = repo_pair
    (origin / "lambdas" / "foo.py").write_text("v2\n")
    _git(["add", "-A"], cwd=origin)
    _git(["commit", "-q", "-m", "fix"], cwd=origin)
    _git(["checkout", "-q", "main"], cwd=checkout)
    _git(["fetch", "origin", "main", "--quiet"], cwd=checkout)
    _git(["merge", "-q", "origin/main"], cwd=checkout)

    result = cdd.check_checkout_freshness(paths=("lambdas/",), cwd=str(checkout))
    assert result["status"] == "fresh"
    assert result["missing_commits"] == 0


def test_offline_fetch_failure_is_unknown_not_a_crash(tmp_path):
    # A directory that isn't even a git repo — fetch fails, must fail-soft.
    result = cdd.check_checkout_freshness(cwd=str(tmp_path))
    assert result["status"] == "unknown"


def test_no_fetch_mode_uses_stale_local_knowledge_of_origin_main(repo_pair):
    # This documents WHY fetch=True is the default: with fetch=False, the local
    # origin/main tracking ref is whatever it was at clone time — a fix pushed
    # to origin AFTER the clone is invisible until something fetches. Contrast
    # with test_stale_checkout_is_blocked_..., which fetches and catches it.
    origin, checkout = repo_pair
    (origin / "lambdas" / "foo.py").write_text("v2\n")
    _git(["add", "-A"], cwd=origin)
    _git(["commit", "-q", "-m", "fix"], cwd=origin)

    result = cdd.check_checkout_freshness(paths=("lambdas/",), cwd=str(checkout), fetch=False)
    assert result["status"] == "fresh"  # stale local ref, not yet fetched

    fetched = cdd.check_checkout_freshness(paths=("lambdas/",), cwd=str(checkout), fetch=True)
    assert fetched["status"] == "stale"  # the default (fetch=True) catches it


# ── live-code drift (mocked CloudFormation, mirrors test_drift_sentinel.py) ──


class _FakeCfn:
    def __init__(self, drift_status="IN_SYNC", resource_drifts=None, fail_detection=False):
        self._drift_status = drift_status
        self._resource_drifts = resource_drifts or []
        self._fail_detection = fail_detection

    def detect_stack_drift(self, StackName):  # noqa: N803
        return {"StackDriftDetectionId": "det-1"}

    def describe_stack_drift_detection_status(self, StackDriftDetectionId):  # noqa: N803
        if self._fail_detection:
            return {"DetectionStatus": "DETECTION_FAILED", "DetectionStatusReason": "boom"}
        return {"DetectionStatus": "DETECTION_COMPLETE", "StackDriftStatus": self._drift_status}

    def describe_stack_resource_drifts(self, StackName, StackResourceDriftStatusFilters):  # noqa: N803
        return {"StackResourceDrifts": self._resource_drifts}


def _lambda_drift(physical_id, logical_id, prop_paths):
    return {
        "ResourceType": "AWS::Lambda::Function",
        "PhysicalResourceId": physical_id,
        "LogicalResourceId": logical_id,
        "PropertyDifferences": [{"PropertyPath": p} for p in prop_paths],
    }


def test_live_code_drift_clean_when_in_sync(monkeypatch):
    monkeypatch.setattr(cdd, "_cfn_client", lambda *a, **k: _FakeCfn(drift_status="IN_SYNC"))
    result = cdd.check_live_code_drift(["LifePlatformCompute"])
    assert result["status"] == "clean"
    assert result["stacks"]["LifePlatformCompute"]["status"] == "clean"


def test_live_code_drift_flags_a_code_property_change(monkeypatch):
    drifts = [_lambda_drift("daily-brief", "DailyBriefFn", ["/Code/S3Key"])]
    monkeypatch.setattr(cdd, "_cfn_client", lambda *a, **k: _FakeCfn(drift_status="DRIFTED", resource_drifts=drifts))
    result = cdd.check_live_code_drift(["LifePlatformEmail"])
    assert result["status"] == "drift"
    stack = result["stacks"]["LifePlatformEmail"]
    assert stack["status"] == "drift"
    fn = stack["functions"][0]
    assert fn["function"] == "daily-brief"
    assert fn["code_drift"] is True


def test_live_code_drift_config_only_does_not_hard_flag(monkeypatch):
    # A drifted env var / tag (not Code) is real drift but not the clobber risk
    # this guard exists for — reported as config_drift_only, not "drift".
    drifts = [_lambda_drift("some-fn", "SomeFn", ["/Environment/Variables/FOO"])]
    monkeypatch.setattr(cdd, "_cfn_client", lambda *a, **k: _FakeCfn(drift_status="DRIFTED", resource_drifts=drifts))
    result = cdd.check_live_code_drift(["LifePlatformOperational"])
    assert result["status"] == "clean"  # no CODE drift anywhere -> overall clean
    assert result["stacks"]["LifePlatformOperational"]["status"] == "config_drift_only"


def test_live_code_drift_detection_failure_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(cdd, "_cfn_client", lambda *a, **k: _FakeCfn(fail_detection=True))
    result = cdd.check_live_code_drift(["LifePlatformCore"])
    assert result["status"] == "error"
    assert result["stacks"]["LifePlatformCore"]["status"] == "error"


def test_live_code_drift_non_lambda_resources_are_ignored(monkeypatch):
    drifts = [
        {
            "ResourceType": "AWS::DynamoDB::Table",
            "PhysicalResourceId": "life-platform",
            "LogicalResourceId": "Table",
            "PropertyDifferences": [{"PropertyPath": "/BillingMode"}],
        }
    ]
    monkeypatch.setattr(cdd, "_cfn_client", lambda *a, **k: _FakeCfn(drift_status="DRIFTED", resource_drifts=drifts))
    result = cdd.check_live_code_drift(["LifePlatformCore"])
    assert result["status"] == "clean"


# ── CLI wiring (blocked vs override) ─────────────────────────────────────────


def test_main_blocks_on_stale_checkout(monkeypatch, capsys):
    monkeypatch.setattr(cdd, "check_checkout_freshness", lambda **k: {"status": "stale", "missing_commits": 2, "detail": "x"})
    monkeypatch.setattr(sys, "argv", ["check_deploy_drift.py"])
    assert cdd.main() == 1
    assert "BLOCKED" in capsys.readouterr().out


def test_main_override_flag_unblocks_stale_checkout(monkeypatch, capsys):
    monkeypatch.setattr(cdd, "check_checkout_freshness", lambda **k: {"status": "stale", "missing_commits": 2, "detail": "x"})
    monkeypatch.setattr(sys, "argv", ["check_deploy_drift.py", "--allow-stale-checkout"])
    assert cdd.main() == 0
    assert "safe to deploy" in capsys.readouterr().out


def test_main_override_env_var_unblocks_stale_checkout(monkeypatch, capsys):
    monkeypatch.setattr(cdd, "check_checkout_freshness", lambda **k: {"status": "stale", "missing_commits": 2, "detail": "x"})
    monkeypatch.setenv(cdd._ENV_ALLOW_STALE, "1")
    monkeypatch.setattr(sys, "argv", ["check_deploy_drift.py"])
    assert cdd.main() == 0


def test_main_blocks_on_live_code_drift_when_stacks_given(monkeypatch, capsys):
    monkeypatch.setattr(cdd, "check_checkout_freshness", lambda **k: {"status": "fresh", "missing_commits": 0, "detail": "x"})
    monkeypatch.setattr(
        cdd,
        "check_live_code_drift",
        lambda stacks, **k: {"status": "drift", "stacks": {"LifePlatformEmail": {"status": "drift", "functions": []}}},
    )
    monkeypatch.setattr(sys, "argv", ["check_deploy_drift.py", "LifePlatformEmail"])
    assert cdd.main() == 1


def test_main_skip_live_check_flag(monkeypatch):
    monkeypatch.setattr(cdd, "check_checkout_freshness", lambda **k: {"status": "fresh", "missing_commits": 0, "detail": "x"})
    called = []
    monkeypatch.setattr(cdd, "check_live_code_drift", lambda stacks, **k: called.append(stacks) or {"status": "drift", "stacks": {}})
    monkeypatch.setattr(sys, "argv", ["check_deploy_drift.py", "LifePlatformEmail", "--skip-live-check"])
    assert cdd.main() == 0
    assert called == []  # never invoked


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
