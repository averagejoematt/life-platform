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


def _patch_all(monkeypatch, cfn, post, orphan, bucket, doc=None, site=None, oidc=None, gh_config=None, gh_push=None):
    monkeypatch.setattr(ds, "check_cfn_drift", lambda *a, **k: cfn)
    monkeypatch.setattr(ds, "check_postflight", lambda: post)
    monkeypatch.setattr(ds, "check_orphan_functions", lambda: orphan)
    monkeypatch.setattr(ds, "check_bucket_policy", lambda: bucket)
    monkeypatch.setattr(ds, "check_doc_literals", lambda: doc or {"status": "clean", "mismatches": []})
    monkeypatch.setattr(ds, "check_site_sha_ancestry", lambda: site or {"status": "clean", "live_sha": "deadbeef"})
    monkeypatch.setattr(ds, "check_oidc_iam", lambda: oidc or {"status": "clean"})
    monkeypatch.setattr(ds, "check_github_config", lambda: gh_config or {"status": "clean", "surfaces": {}})
    monkeypatch.setattr(ds, "check_github_push_runs", lambda *a, **k: gh_push or {"status": "clean", "stalled": [], "gap_commits": []})


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


# ── GitHub config posture (#1320) + main-push run liveness (#1544) ───────────
# Fixtures below marked LIVE-SHAPE are byte-for-byte the relevant fields of the
# real `gh api` responses captured 2026-07-19 — so the drift assertions double as
# the AC4 "assert demonstrably fires on the current documented-but-absent
# controls" regression guard (guard-red pre-#1319/pre-toggle).

_LIVE_ENV_GATELESS = {  # LIVE-SHAPE: the #1319 dropped-gate state
    "name": "production",
    "can_admins_bypass": True,
    "protection_rules": [{"id": 49474931, "node_id": "GA_", "type": "branch_policy"}],
}
_ENV_WITH_REVIEWERS = {
    "name": "production",
    "protection_rules": [{"id": 1, "type": "required_reviewers", "reviewers": [{"type": "User"}]}, {"id": 2, "type": "branch_policy"}],
}
_LIVE_RULESET = {  # LIVE-SHAPE: ruleset 19162901 as documented in CONVENTIONS.md
    "id": 19162901,
    "name": "main-block-force-push-and-deletion",
    "enforcement": "active",
    "conditions": {"ref_name": {"exclude": [], "include": ["refs/heads/main"]}},
    "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
}
_VULN_DISABLED_ERR = {  # LIVE-SHAPE: the semantic 404 for disabled alerts
    "classification": "absent",
    "detail": '{"message":"Vulnerability alerts are disabled.","status":"404"} gh: Vulnerability alerts are disabled. (HTTP 404)',
}
_SCOPE_ERR = {"classification": "scope", "detail": "gh: Resource not accessible by integration (HTTP 403)"}


def _fake_gh(monkeypatch, routes):
    """Route `gh api` paths → (data, err) by substring match; unrouted paths fail loud."""

    def fake(path, timeout=60):
        for frag, resp in routes.items():
            if frag in path:
                return resp
        raise AssertionError(f"unrouted gh api path in test: {path}")

    monkeypatch.setattr(ds, "_gh_api_result", fake)


def _config_routes(env=None, ruleset=None, vuln=None):
    return {
        "environments/production": env or (_LIVE_ENV_GATELESS, None),
        "rulesets/19162901": ruleset or (_LIVE_RULESET, None),
        "vulnerability-alerts": vuln or ({}, None),  # 204 No Content = enabled
    }


def test_github_posture_file_loads_and_declares_all_surfaces():
    posture = ds._load_github_posture()
    assert posture["environment_production"]["required_reviewers"] is True  # ADR-065/CLAUDE.md claim, pending #1319
    assert posture["main_ruleset"]["id"] == 19162901
    assert sorted(posture["main_ruleset"]["rule_types"]) == ["deletion", "non_fast_forward"]
    assert posture["vulnerability_alerts"]["enabled"] is True  # ADR-082 CVE channel claim
    for key in ("environment_production", "main_ruleset", "vulnerability_alerts", "push_run_detector"):
        assert posture[key].get("source"), f"{key} must name the doc that makes the claim"


def test_push_trigger_globs_match_workflows():
    # MAINTAINED-LITERAL parity (the PLATFORM_FACTS pattern): PUSH_TRIGGER_GLOBS must
    # equal the union of every push-to-main workflow's `on.push.paths` filters, or the
    # #1544 detector will mis-classify which commits should have queued runs.
    yaml = pytest.importorskip("yaml")
    wf_dir = os.path.join(_ROOT, ".github", "workflows")
    expected = set()
    for fn in os.listdir(wf_dir):
        if not fn.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(wf_dir, fn)) as f:
            doc = yaml.safe_load(f) or {}
        on = doc.get("on") or doc.get(True) or {}
        push = on.get("push") if isinstance(on, dict) else None
        if not isinstance(push, dict) or "main" not in (push.get("branches") or []):
            continue
        paths = push.get("paths")
        assert (
            paths
        ), f"{fn}: push-to-main with NO path filter breaks the detector's 'every main push queues a run' model — update the detector"
        expected.update(paths)
    assert expected == set(ds.PUSH_TRIGGER_GLOBS), (
        "PUSH_TRIGGER_GLOBS drifted from the live workflow path filters — update the constant in deploy/drift_sentinel.py:\n"
        f"missing from constant: {sorted(expected - set(ds.PUSH_TRIGGER_GLOBS))}\n"
        f"stale in constant: {sorted(set(ds.PUSH_TRIGGER_GLOBS) - expected)}"
    )


def test_matches_push_trigger_semantics():
    assert ds._matches_push_trigger("lambdas/web/site_api_lambda.py")
    assert ds._matches_push_trigger("mcp_server.py")
    assert ds._matches_push_trigger("requirements-dev.txt")
    assert ds._matches_push_trigger("scripts/v4_build_rss.py")
    assert ds._matches_push_trigger("site/index.html")
    assert not ds._matches_push_trigger("handovers/HANDOVER_LATEST.md")
    assert not ds._matches_push_trigger("MEMORY.md")
    assert not ds._matches_push_trigger("deploy/drift_sentinel.py")  # deploy/ is not push-triggered (CONVENTIONS §deploy-from-main)


def test_github_config_fires_on_live_gateless_environment(monkeypatch):
    # THE #1319 guard-red: docs claim the approval gate, live production env has only
    # branch_policy (LIVE-SHAPE fixture) — the assert MUST fire on today's real state.
    _fake_gh(monkeypatch, _config_routes())
    res = ds.check_github_config()
    assert res["status"] == "drift"
    env = res["surfaces"]["environment_production"]
    assert env["status"] == "drift"
    assert env["documented"] == {"required_reviewers": True}
    assert "branch_policy" in env["live_protection_rule_types"]
    # ...while the other two surfaces judged independently:
    assert res["surfaces"]["main_ruleset"]["status"] == "clean"
    assert res["surfaces"]["vulnerability_alerts"]["status"] == "clean"


def test_github_config_clean_when_env_has_reviewers(monkeypatch):
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None)))
    res = ds.check_github_config()
    assert res["surfaces"]["environment_production"]["status"] == "clean"


def test_github_config_vuln_alerts_fire_when_disabled(monkeypatch):
    # The SDLC-review P2-4 guard-red: alerts are disabled live (LIVE-SHAPE semantic
    # 404) while ADR-082/ci-cd.yml document Dependabot as the CVE channel.
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), vuln=(None, _VULN_DISABLED_ERR)))
    res = ds.check_github_config()
    assert res["status"] == "drift"
    va = res["surfaces"]["vulnerability_alerts"]
    assert va["status"] == "drift"
    assert va["documented"] == {"enabled": True} and va["live"] == {"enabled": False}


def test_github_config_ruleset_drift_on_weakening(monkeypatch):
    weakened = dict(_LIVE_RULESET, enforcement="disabled", rules=[{"type": "deletion"}])
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), ruleset=(weakened, None)))
    res = ds.check_github_config()
    rs = res["surfaces"]["main_ruleset"]
    assert rs["status"] == "drift"
    assert "enforcement='disabled'" in rs["detail"] and "non_fast_forward" in rs["detail"]


def test_github_config_ruleset_drift_when_deleted(monkeypatch):
    gone = (None, {"classification": "absent", "detail": "gh: Not Found (HTTP 404)"})
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), ruleset=gone))
    res = ds.check_github_config()
    assert res["surfaces"]["main_ruleset"]["status"] == "drift"
    assert "GONE" in res["surfaces"]["main_ruleset"]["detail"]


def test_github_config_scope_gap_is_needs_owner_not_red(monkeypatch):
    # The realistic CI state without the GH_POSTURE_TOKEN secret: admin-read surfaces
    # 403 for the workflow token → "unavailable" + ONE needs-owner line naming the
    # exact fine-grained-PAT permission; NEVER drift/error for a known scope gap.
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), ruleset=(None, _SCOPE_ERR), vuln=(None, _SCOPE_ERR)))
    res = ds.check_github_config()
    assert res["status"] == "unavailable"
    assert res["surfaces"]["main_ruleset"]["status"] == "unavailable"
    assert res["surfaces"]["vulnerability_alerts"]["status"] == "unavailable"
    assert "Administration:read" in res["needs_owner"]
    assert "GH_POSTURE_TOKEN" in res["needs_owner"]


def _commit(sha, iso_date):
    return {"sha": sha, "commit": {"committer": {"date": iso_date}}}


def _run(head_sha, created):
    return {"head_sha": head_sha, "created_at": created}


def _push_routes(monkeypatch, commits, runs, files_by_sha=None):
    files_by_sha = files_by_sha or {}

    def fake(path, timeout=60):
        if "/commits?" in path:
            return commits, None
        if "/actions/runs" in path:
            return {"workflow_runs": runs}, None
        raise AssertionError(f"unrouted gh api path in test: {path}")

    monkeypatch.setattr(ds, "_gh_api_result", fake)
    monkeypatch.setattr(ds, "_commit_files", lambda repo, sha: files_by_sha.get(sha, ["lambdas/x.py"]))


def _iso_minutes_ago(mins):
    from datetime import datetime as _dt, timedelta, timezone as _tz

    return (_dt.now(_tz.utc) - timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_push_runs_clean_when_head_covered(monkeypatch):
    commits = [_commit("aaa", _iso_minutes_ago(60)), _commit("bbb", _iso_minutes_ago(120))]
    runs = [_run("aaa", _iso_minutes_ago(59)), _run("bbb", _iso_minutes_ago(119))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert res["stalled"] == [] and res["gap_commits"] == []


def test_push_runs_drift_when_head_stalled(monkeypatch):
    # The live #1544 state: a trigger-matching merge sits past the grace window with
    # zero queued runs while an older commit is covered.
    commits = [_commit("dead", _iso_minutes_ago(45)), _commit("bbb", _iso_minutes_ago(300))]
    runs = [_run("bbb", _iso_minutes_ago(299))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "drift"
    assert [s["sha"] for s in res["stalled"]] == ["dead"]
    assert "NOT QUEUING" in res["detail"]


def test_push_runs_drift_on_the_sixmerge_historical_gap(monkeypatch):
    # The exact 2026-07-19 incident shape: runs RESUMED on the newest merge, but six
    # earlier consecutive merges never got any push-event run (their site/docs deploys
    # silently never fired). Must alarm as a historical gap cluster.
    six = ["e1156b57", "48fad430", "0987479a", "65b88eb0", "9d1c5b42", "cec2a3c4"]
    commits = [_commit("5cacecba", _iso_minutes_ago(60))] + [_commit(s, _iso_minutes_ago(90 + 10 * i)) for i, s in enumerate(six)]
    commits += [_commit("85ac4ad7", _iso_minutes_ago(240))]
    runs = [_run("5cacecba", _iso_minutes_ago(59)), _run("85ac4ad7", _iso_minutes_ago(239))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "drift"
    assert [g["sha"] for g in res["gap_commits"]] == six
    assert "historical gap: 6" in res["detail"]
    assert res["stalled"] == []


def test_push_runs_single_gap_is_reported_not_alarmed(monkeypatch):
    # ONE uncovered non-head commit could be the tail of a multi-commit push (only the
    # push head gets runs) — reported honestly, below the cluster threshold, no drift.
    commits = [_commit("head", _iso_minutes_ago(60)), _commit("mid", _iso_minutes_ago(70)), _commit("old", _iso_minutes_ago(200))]
    runs = [_run("head", _iso_minutes_ago(59)), _run("old", _iso_minutes_ago(199))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert [g["sha"] for g in res["gap_commits"]] == ["mid"]
    assert "multi-commit push" in res["note"]


def test_push_runs_ignores_non_trigger_commits(monkeypatch):
    # A wrap commit touching only handovers/ legitimately queues nothing.
    commits = [_commit("wrap", _iso_minutes_ago(90)), _commit("bbb", _iso_minutes_ago(200))]
    runs = [_run("bbb", _iso_minutes_ago(199))]
    _push_routes(monkeypatch, commits, runs, files_by_sha={"wrap": ["handovers/HANDOVER_LATEST.md", "MEMORY.md"]})
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert res["stalled"] == [] and res["gap_commits"] == []


def test_push_runs_grace_window_holds_fire(monkeypatch):
    # A merge 5 minutes old with no run yet is NOT an alarm — runs may still queue.
    commits = [_commit("fresh", _iso_minutes_ago(5)), _commit("bbb", _iso_minutes_ago(120))]
    runs = [_run("bbb", _iso_minutes_ago(119))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"


def test_push_runs_scope_gap_is_needs_owner_not_red(monkeypatch):
    def fake(path, timeout=60):
        if "/commits?" in path:
            return [_commit("aaa", _iso_minutes_ago(60))], None
        return None, _SCOPE_ERR

    monkeypatch.setattr(ds, "_gh_api_result", fake)
    res = ds.check_github_push_runs()
    assert res["status"] == "unavailable"
    assert "Actions:read" in res["needs_owner"]


def test_sweep_github_drift_propagates(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        gh_config={
            "status": "drift",
            "surfaces": {"environment_production": {"status": "drift", "detail": "gate documented, absent live"}},
        },
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "GitHub config diverges from documented posture" in rec["summary"]


def test_sweep_stays_clean_on_github_scope_gaps(monkeypatch):
    # An unreadable surface must never drag a clean week into drift/degraded (#1320
    # fail-soft AC): "unavailable" aggregates as clean, with the needs-owner line
    # carried in the record for the report seam.
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        gh_config={"status": "unavailable", "surfaces": {}, "needs_owner": "GitHub posture surface(s) unreadable… Administration:read…"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "clean"


def test_status_html_carries_needs_owner_once():
    record = {
        "status": "clean",
        "date": "2026-07-20",
        "summary": "All clear",
        "checks": {
            "github_config": {
                "status": "unavailable",
                "needs_owner": "unreadable: rulesets; vulnerability-alerts. fix: PAT Administration:read",
            },
            "github_push_runs": {"status": "clean"},
        },
    }
    html = drift_report.status_html(record)
    assert html.count("needs-owner") == 1
    assert "Administration:read" in html


def test_as_signal_includes_github_checks_in_flagging():
    sig = drift_report.as_signal(
        {
            "status": "drift",
            "date": "2026-07-20",
            "summary": "main-push workflow runs not queuing",
            "checks": {
                "github_push_runs": {"status": "drift", "detail": "push-event runs are NOT QUEUING: 3 …", "stalled": [{"sha": "x"}]},
                "cfn_drift": {"status": "clean", "stacks": {}},
            },
        }
    )
    assert sig is not None and sig["class"] == "needs-human"
    assert "github_push_runs" in sig["flagging"]


def test_push_runs_exempts_bot_reconcile_commits(monkeypatch):
    # Verified live 2026-07-19: reconcile commits (committed by github-actions[bot],
    # pushed with the workflow's GITHUB_TOKEN) NEVER get push-event runs — GitHub's
    # recursive-workflow prevention. They must be exempt or every merge-queue night
    # produces false weekly gaps.
    reconcile = dict(
        _commit("5454259b", _iso_minutes_ago(90)),
        author={"login": "github-actions[bot]"},
        committer={"login": "github-actions[bot]"},
    )
    commits = [_commit("head", _iso_minutes_ago(60)), reconcile, _commit("old", _iso_minutes_ago(200))]
    runs = [_run("head", _iso_minutes_ago(59)), _run("old", _iso_minutes_ago(199))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert res["gap_commits"] == []
    assert res["bot_commits_exempt"] == 1
