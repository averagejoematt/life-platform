"""Tests for the weekly drift sentinel (#394) — deploy/drift_sentinel.py and the
remediation/drift_report.py report seam. All hermetic (no AWS): AWS-touching checks are
monkeypatched or fed fake clients."""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "remediation")):
    if p not in sys.path:
        sys.path.insert(0, p)

import drift_report  # noqa: E402
import drift_sentinel as ds  # noqa: E402
import sentinel_cadence as scad  # noqa: E402  — the cadence dead-man lives here (#3130 split)
import sentinel_github as sg  # noqa: E402  — the GitHub legs live here (#1665 split); a re-export is NOT a patch point
import sentinel_quota as sq  # noqa: E402  — quota internals live here (#1665 split)

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


# ── S3 lifecycle declared-vs-live (DIL-026, #2799) ───────────────────────────


class _FakeS3Lifecycle:
    def __init__(self, cfg):
        self._cfg = cfg

    def get_bucket_lifecycle_configuration(self, Bucket):  # noqa: N803 — boto3 kwarg casing
        if self._cfg is None:
            raise RuntimeError("no lifecycle configuration")
        return self._cfg


def _declared_lifecycle():
    with open(os.path.join(_ROOT, "deploy", "s3_lifecycle.json")) as f:
        return json.load(f)


def test_s3_lifecycle_declared_has_imports_rule():
    # DIL-026: this is the specific coverage gap the finding named.
    rules = {r["ID"]: r for r in _declared_lifecycle()["Rules"]}
    assert "imports-expire-noncurrent-versions-7d" in rules
    r = rules["imports-expire-noncurrent-versions-7d"]
    assert r["Filter"] == {"Prefix": "imports/"}
    assert r["NoncurrentVersionExpiration"]["NoncurrentDays"] == 7


def test_s3_lifecycle_clean_when_live_matches_declared(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3Lifecycle(_declared_lifecycle()))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "clean"
    assert res["missing_rule_ids"] == []
    assert res["extra_rule_ids"] == []
    assert res["changed_rule_ids"] == []


def test_s3_lifecycle_drift_when_declared_rule_missing_live(monkeypatch):
    # Mutation proof for the DIL-026 shape: a declared rule (imports/) that never
    # got applied live must surface as drift, by name.
    live = json.loads(json.dumps(_declared_lifecycle()))
    live["Rules"] = [r for r in live["Rules"] if r["ID"] != "imports-expire-noncurrent-versions-7d"]
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3Lifecycle(live))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "drift"
    assert "imports-expire-noncurrent-versions-7d" in res["missing_rule_ids"]


def test_s3_lifecycle_drift_when_live_rule_weakened(monkeypatch):
    # A rule present both sides but with a dropped/weakened NoncurrentVersionExpiration
    # (e.g. an out-of-band console edit) must also surface — not just wholesale removal.
    live = json.loads(json.dumps(_declared_lifecycle()))
    for r in live["Rules"]:
        if r["ID"] == "imports-expire-noncurrent-versions-7d":
            r["NoncurrentVersionExpiration"] = {"NoncurrentDays": 365}
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3Lifecycle(live))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "drift"
    assert "imports-expire-noncurrent-versions-7d" in res["changed_rule_ids"]


def test_s3_lifecycle_drift_when_live_has_undeclared_rule(monkeypatch):
    # An out-of-band-added live rule (never declared) is exactly as invisible as a
    # missing one on an imported bucket — must also count as drift.
    live = json.loads(json.dumps(_declared_lifecycle()))
    live["Rules"].append({"ID": "console-added-rule", "Status": "Enabled", "Filter": {"Prefix": "oops/"}})
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3Lifecycle(live))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "drift"
    assert "console-added-rule" in res["extra_rule_ids"]


def test_s3_lifecycle_error_is_soft(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeS3Lifecycle(None))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "error"


def test_s3_lifecycle_error_when_declared_file_unreadable(monkeypatch, tmp_path):
    # Point _ROOT at an empty tree so deploy/s3_lifecycle.json doesn't exist —
    # exercises the same fail-soft "error, never crash" contract as the other checks.
    monkeypatch.setattr(ds, "_ROOT", str(tmp_path))
    res = ds.check_s3_lifecycle()
    assert res["status"] == "error"


# ── DynamoDB TTL declared-vs-live (table-config-noop-ttl, #2799 residual) ────
# Before this file, `grep -rn describe_time_to_live` found zero callers anywhere in the
# repo — the #951 shape (a writer keying its expiry to an attribute the table's live TTL
# config was never enabled on) had no assertion that could have caught it, or a
# recurrence of it, short of a manual `aws dynamodb describe-time-to-live` read.


class _FakeDynamoDB:
    def __init__(self, desc):
        self._desc = desc

    def describe_time_to_live(self, TableName):  # noqa: N803 — boto3 kwarg casing
        if self._desc is None:
            raise RuntimeError("describe_time_to_live unavailable")
        return {"TimeToLiveDescription": self._desc}


def test_dynamodb_ttl_clean_when_live_matches_declared(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeDynamoDB({"TimeToLiveStatus": "ENABLED", "AttributeName": "ttl"}))
    res = ds.check_dynamodb_ttl()
    assert res["status"] == "clean"
    assert res["declared_attribute"] == "ttl" == ds.TABLE_TTL_ATTRIBUTE
    assert res["live_attribute"] == "ttl"


def test_dynamodb_ttl_drift_when_live_attribute_is_the_951_mismatch(monkeypatch):
    # Mutation proof for the exact #951 shape: TTL is live-ENABLED, but on a DIFFERENT
    # attribute name than the one writers are supposed to key their expiry to.
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeDynamoDB({"TimeToLiveStatus": "ENABLED", "AttributeName": "expires_at"}))
    res = ds.check_dynamodb_ttl()
    assert res["status"] == "drift"
    assert res["live_attribute"] == "expires_at"
    assert "expires_at" in res["detail"]
    assert "#951" in res["detail"]


def test_dynamodb_ttl_drift_when_live_is_disabled(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeDynamoDB({"TimeToLiveStatus": "DISABLED", "AttributeName": "ttl"}))
    res = ds.check_dynamodb_ttl()
    assert res["status"] == "drift"
    assert "never reaped" in res["detail"]


def test_dynamodb_ttl_error_is_soft(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeDynamoDB(None))
    res = ds.check_dynamodb_ttl()
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


def _patch_all(
    monkeypatch,
    cfn,
    post,
    orphan,
    bucket,
    doc=None,
    site=None,
    oidc=None,
    gh_config=None,
    gh_push=None,
    quota=None,
    codeql=None,
    hae=None,
    raw_replication=None,
    s3_lifecycle=None,
    dynamodb_ttl=None,
    cadence=None,
    events=None,
    log_retention=None,
):
    # DIL-027 (#3042): the raw/ cross-region backup check. Patched here like every
    # other AWS-touching check so the sweep-shape tests stay offline.
    monkeypatch.setattr(ds, "check_raw_replication", lambda *a, **k: raw_replication or {"status": "clean", "objects_confirmed": 2})
    # #3130: the sentinel-cadence dead-man. Patched here too — otherwise every sweep
    # test in this section would fall through to the real check's live S3 client.
    monkeypatch.setattr(
        ds,
        "check_sentinel_cadence",
        lambda *a, **k: cadence or {"status": "clean", "missing_dates": [], "latest_date": "2026-08-22", "days_stale": 2},
    )
    # #3279: the EventBridge-rules check. Patched like every other AWS-touching check
    # so the sweep-shape tests stay offline.
    monkeypatch.setattr(
        ds,
        "check_eventbridge_rules",
        lambda *a, **k: events
        or {"status": "clean", "live_count": 96, "managed_count": 93, "enabled_targetless": [], "out_of_iac": [], "known_out_of_iac": {}},
    )
    # #3278: the security-tier log-retention sweep. Patched like every other AWS-touching
    # check so the sweep-shape tests stay offline.
    monkeypatch.setattr(
        ds,
        "check_log_retention",
        lambda *a, **k: log_retention
        or {"status": "clean", "declared_days": 90, "groups_found": 17, "mismatches": [], "unreadable_regions": []},
    )
    monkeypatch.setattr(ds, "check_codeql_alerts", lambda: codeql or {"status": "clean", "open_count": 0, "sample": []})
    monkeypatch.setattr(
        ds, "check_hae_webhook_ingress", lambda: hae or {"status": "clean", "cdk_api_id": "p6clybdkkc", "invoke_statements": []}
    )
    monkeypatch.setattr(ds, "check_cfn_drift", lambda *a, **k: cfn)
    monkeypatch.setattr(ds, "check_postflight", lambda: post)
    monkeypatch.setattr(ds, "check_orphan_functions", lambda: orphan)
    monkeypatch.setattr(ds, "check_bucket_policy", lambda: bucket)
    monkeypatch.setattr(
        ds,
        "check_s3_lifecycle",
        lambda: s3_lifecycle or {"status": "clean", "missing_rule_ids": [], "extra_rule_ids": [], "changed_rule_ids": []},
    )
    monkeypatch.setattr(
        ds,
        "check_dynamodb_ttl",
        lambda: dynamodb_ttl or {"status": "clean", "declared_attribute": "ttl", "live_attribute": "ttl", "live_status": "ENABLED"},
    )
    monkeypatch.setattr(ds, "check_doc_literals", lambda: doc or {"status": "clean", "mismatches": []})
    monkeypatch.setattr(ds, "check_site_sha_ancestry", lambda: site or {"status": "clean", "live_sha": "deadbeef"})
    monkeypatch.setattr(ds, "check_oidc_iam", lambda: oidc or {"status": "clean"})
    monkeypatch.setattr(ds, "check_github_config", lambda: gh_config or {"status": "clean", "surfaces": {}})
    monkeypatch.setattr(ds, "check_github_push_runs", lambda *a, **k: gh_push or {"status": "clean", "stalled": [], "gap_commits": []})
    monkeypatch.setattr(
        ds,
        "check_github_quota",
        lambda: quota or {"status": "unavailable", "billing_api": {"available": False, "detail": "test"}, "top_workflows_7d": []},
    )


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


def test_sweep_s3_lifecycle_drift(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean"},
        s3_lifecycle={
            "status": "drift",
            "missing_rule_ids": ["imports-expire-noncurrent-versions-7d"],
            "extra_rule_ids": [],
            "changed_rule_ids": [],
            "detail": "declared but missing live: ['imports-expire-noncurrent-versions-7d']",
        },
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "S3 lifecycle configuration diverges from declared rules" in rec["summary"]
    # AC4 / #2578-class check: the drift must actually reach the triage path, not just
    # the sweep record — this is what run_sweep's generic checks-dict → as_signal
    # plumbing (drift_report.py) turns into a needs-human item on the curated report.
    sig = drift_report.as_signal(rec)
    assert sig is not None
    assert "s3_lifecycle" in sig["flagging"]
    assert sig["flagging"]["s3_lifecycle"]["status"] == "drift"


def test_sweep_dynamodb_ttl_drift(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean"},
        dynamodb_ttl={
            "status": "drift",
            "declared_attribute": "ttl",
            "live_attribute": "expires_at",
            "live_status": "ENABLED",
            "detail": "live TTL attribute is 'expires_at', declared is 'ttl' — the #951 shape",
        },
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "DynamoDB TTL config diverges from the declared attribute" in rec["summary"]
    sig = drift_report.as_signal(rec)
    assert sig is not None
    assert "dynamodb_ttl" in sig["flagging"]
    assert sig["flagging"]["dynamodb_ttl"]["status"] == "drift"


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


# ── #3508 box 2: a drift section a later deploy already answered ─────────────
# The 2026-09-04 17:49Z remediation report carried the 09-02 sentinel record verbatim:
# "6 stack(s) drifted: LifePlatformIngestion, LifePlatformCompute, …" — while all six had
# been redeployed at 16:32–16:36Z that morning. Under the Mon-only sentinel guard the
# freshest available record was always up to two days old, so this was structural, not
# bad luck.
_SUPERSEDED_RECORD = {
    "status": "drift",
    "date": "2026-09-02",
    "summary": "6 stack(s) drifted",
    "checks": {
        "cfn_drift": {
            "status": "drift",
            "stacks": {
                "LifePlatformCore": {"status": "clean"},
                "LifePlatformIngestion": {"status": "drift", "drifted": [{"logical_id": "X"}]},
                "LifePlatformCompute": {"status": "drift", "drifted": [{"logical_id": "Y"}]},
            },
        }
    },
}


class _FakeSupersedeCfn:
    """describe_stacks on the wire: LastUpdatedTime is a datetime, and a stack CFN has
    never updated carries only CreationTime."""

    def __init__(self, updated):
        self._updated = updated

    def describe_stacks(self, StackName):  # noqa: N803 — boto3 kwarg casing
        if StackName not in self._updated:
            raise RuntimeError(f"planted: Stack with id {StackName} does not exist")
        return {"Stacks": [{"StackName": StackName, "LastUpdatedTime": self._updated[StackName]}]}


def _sup_at(day, hour=16):
    return datetime(2026, 9, day, hour, 30, tzinfo=timezone.utc)


def test_a_fully_redeployed_cfn_section_is_dropped_from_the_signal():
    cfn = _FakeSupersedeCfn({"LifePlatformIngestion": _sup_at(4), "LifePlatformCompute": _sup_at(4)})
    assert drift_report.superseded_cfn_stacks(_SUPERSEDED_RECORD, cfn) == {
        "LifePlatformIngestion": _sup_at(4).isoformat(),
        "LifePlatformCompute": _sup_at(4).isoformat(),
    }
    sig = drift_report.as_signal(_SUPERSEDED_RECORD, cfn_client=cfn)
    assert sig is None, "a drift record whose only finding was already redeployed is not a needs-human signal"


def test_one_un_redeployed_stack_keeps_the_whole_section():
    """A PARTIALLY answered finding is still a finding — suppressing on 'most of them'
    would be the tolerant-branch shape these issues are about."""
    cfn = _FakeSupersedeCfn({"LifePlatformIngestion": _sup_at(4), "LifePlatformCompute": _sup_at(1)})
    sig = drift_report.as_signal(_SUPERSEDED_RECORD, cfn_client=cfn)
    assert sig is not None and "cfn_drift" in sig["flagging"]
    assert sig["superseded_stacks"] == {"LifePlatformIngestion": _sup_at(4).isoformat()}
    assert sig["record_date"] == "2026-09-02"


def test_an_unreadable_stack_is_never_treated_as_superseded():
    """NEGATIVE CONTROL: describe_stacks raising must not manufacture a suppression —
    'couldn't check' is not 'already fixed'."""
    cfn = _FakeSupersedeCfn({"LifePlatformIngestion": _sup_at(4)})  # Compute raises
    sig = drift_report.as_signal(_SUPERSEDED_RECORD, cfn_client=cfn)
    assert sig is not None and "cfn_drift" in sig["flagging"]
    assert "LifePlatformCompute" not in sig["superseded_stacks"]


def test_a_same_day_redeploy_is_not_counted_as_superseding():
    """Conservative by design: a deploy on the record's own day is not provably after the
    drift read, so it does not silence the finding."""
    cfn = _FakeSupersedeCfn({"LifePlatformIngestion": _sup_at(2), "LifePlatformCompute": _sup_at(2, 23)})
    assert drift_report.superseded_cfn_stacks(_SUPERSEDED_RECORD, cfn) == {}


def test_without_a_cfn_client_the_signal_is_exactly_what_it_always_was():
    """The suppression is opt-in — every existing caller keeps its behaviour."""
    sig = drift_report.as_signal(_SUPERSEDED_RECORD)
    assert sig is not None and "cfn_drift" in sig["flagging"]
    assert sig["superseded_stacks"] == {}


def test_status_html_names_the_superseded_stacks_and_the_record_date():
    cfn = _FakeSupersedeCfn({"LifePlatformIngestion": _sup_at(4), "LifePlatformCompute": _sup_at(4)})
    html = drift_report.status_html(_SUPERSEDED_RECORD, cfn_client=cfn)
    assert "already superseded" in html
    assert "LifePlatformIngestion" in html and "LifePlatformCompute" in html
    assert "2026-09-02" in html


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


# ── #1781 — known CFN drift-detection false positives (access-log ARN wildcard
# suffix + Lambda Function URL CORS header casing) must filter, but ONLY the exact
# documented pattern — never a blanket resource-type or stack-wide suppression.


def test_known_cfn_noise_access_log_wildcard_suffix():
    prop = {
        "PropertyPath": "/AccessLogSettings/DestinationArn",
        "ExpectedValue": "arn:aws:logs:us-west-2:205930651321:log-group:/aws/apigateway/x:*",
        "ActualValue": "arn:aws:logs:us-west-2:205930651321:log-group:/aws/apigateway/x",
    }
    reason = ds._known_cfn_noise_reason("AWS::ApiGatewayV2::Stage", prop)
    assert reason and "wildcard" in reason


def test_known_cfn_noise_rejects_access_log_real_change():
    # A genuinely different destination log group (not just the trailing ':*') must
    # NOT be filtered — that would be a real drift.
    prop = {
        "PropertyPath": "/AccessLogSettings/DestinationArn",
        "ExpectedValue": "arn:aws:logs:us-west-2:205930651321:log-group:/aws/apigateway/x:*",
        "ActualValue": "arn:aws:logs:us-west-2:205930651321:log-group:/aws/apigateway/DIFFERENT",
    }
    assert ds._known_cfn_noise_reason("AWS::ApiGatewayV2::Stage", prop) is None


def test_known_cfn_noise_cors_header_case_only():
    prop = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    reason = ds._known_cfn_noise_reason("AWS::Lambda::Url", prop)
    assert reason and "case" in reason.lower()


def test_known_cfn_noise_rejects_cors_header_real_change():
    # A genuinely different header name (not a case variant) must NOT be filtered.
    prop = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "X-Custom-Header"}
    assert ds._known_cfn_noise_reason("AWS::Lambda::Url", prop) is None


def test_known_cfn_noise_scoped_to_exact_resource_type():
    # The identical property path + case-only diff on an UNRELATED resource type
    # must not match — the allowlist is resource-type-scoped, never path-alone.
    prop = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    assert ds._known_cfn_noise_reason("AWS::IAM::Role", prop) is None


def _resource_drift(logical_id, rtype, diffs, status="MODIFIED", physical_id="phys-1"):
    return {
        "LogicalResourceId": logical_id,
        "PhysicalResourceId": physical_id,
        "ResourceType": rtype,
        "StackResourceDriftStatus": status,
        "PropertyDifferences": diffs,
    }


class _FakeCfnDrift:
    """Full-sweep fake CFN client: detect_stack_drift + poll + resource-drift
    listing, driven by {stack_name: (StackDriftStatus, [resource_drift_dict])}.
    A stack absent from the map defaults to IN_SYNC / no resource drifts."""

    def __init__(self, per_stack):
        self._per_stack = per_stack

    def detect_stack_drift(self, StackName):  # noqa: N803 — boto3 kwarg casing
        return {"StackDriftDetectionId": StackName}

    def describe_stack_drift_detection_status(self, StackDriftDetectionId):  # noqa: N803
        status, _ = self._per_stack.get(StackDriftDetectionId, ("IN_SYNC", []))
        return {"DetectionStatus": "DETECTION_COMPLETE", "StackDriftStatus": status}

    def describe_stack_resource_drifts(self, StackName, StackResourceDriftStatusFilters=None, NextToken=None):  # noqa: N803
        _, resources = self._per_stack.get(StackName, ("IN_SYNC", []))
        return {"StackResourceDrifts": resources}


def test_drifted_resources_filters_pure_noise_resource():
    cors_diff = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    fake = _FakeCfnDrift({"S": ("DRIFTED", [_resource_drift("UrlA", "AWS::Lambda::Url", [cors_diff])])})
    drifted, noise = ds._drifted_resources(fake, "S")
    assert drifted == []
    assert len(noise) == 1 and noise[0]["logical_id"] == "UrlA"


def test_drifted_resources_keeps_resource_with_any_real_diff():
    # A resource with ONE noise diff and ONE real diff must still count as drifted —
    # the filter operates per-difference, never per-resource wholesale.
    cors_diff = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    real_diff = {"PropertyPath": "/Cors/AllowHeaders/1", "ExpectedValue": "X-Foo", "ActualValue": "X-Bar"}
    fake = _FakeCfnDrift({"S": ("DRIFTED", [_resource_drift("UrlA", "AWS::Lambda::Url", [cors_diff, real_diff])])})
    drifted, noise = ds._drifted_resources(fake, "S")
    assert len(drifted) == 1 and drifted[0]["logical_id"] == "UrlA"
    assert noise == []


def test_check_cfn_drift_all_noise_reports_clean_for_that_stack(monkeypatch):
    cors_diff = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    per_stack = {name: ("IN_SYNC", []) for name in ds.STACKS}
    per_stack["LifePlatformServe"] = ("DRIFTED", [_resource_drift("SiteApiLambdaFunctionUrl", "AWS::Lambda::Url", [cors_diff])])
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfnDrift(per_stack))
    res = ds.check_cfn_drift(per_stack_timeout=1)
    assert res["status"] == "clean", res
    serve = res["stacks"]["LifePlatformServe"]
    assert serve["status"] == "clean"
    assert serve["filtered_noise"] and serve["filtered_noise"][0]["logical_id"] == "SiteApiLambdaFunctionUrl"


def test_check_cfn_drift_real_drift_reports_alongside_filtered_noise(monkeypatch):
    cors_diff = {"PropertyPath": "/Cors/AllowHeaders/0", "ExpectedValue": "Content-Type", "ActualValue": "content-type"}
    real_diff = {"PropertyPath": "/Policies/0", "ExpectedValue": "null", "ActualValue": '{"PolicyName": "X"}'}
    per_stack = {name: ("IN_SYNC", []) for name in ds.STACKS}
    per_stack["LifePlatformServe"] = (
        "DRIFTED",
        [
            _resource_drift("SiteApiLambdaFunctionUrl", "AWS::Lambda::Url", [cors_diff]),
            _resource_drift("SiteApiLambdaRole", "AWS::IAM::Role", [real_diff]),
        ],
    )
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfnDrift(per_stack))
    res = ds.check_cfn_drift(per_stack_timeout=1)
    assert res["status"] == "drift"
    serve = res["stacks"]["LifePlatformServe"]
    assert serve["status"] == "drift"
    assert [d["logical_id"] for d in serve["drifted"]] == ["SiteApiLambdaRole"]
    assert [n["logical_id"] for n in serve["filtered_noise"]] == ["SiteApiLambdaFunctionUrl"]


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
_GITHUB_ACTIONS_APP = {"id": 15368, "slug": "github-actions", "name": "GitHub Actions"}  # LIVE-SHAPE: GET /apps/github-actions
_OWNER_USER = {"id": 174924761, "login": "averagejoematt", "type": "User"}  # LIVE-SHAPE: GET /users/averagejoematt
_RC_RULESET_ID = 20000001  # only knowable after the first apply — the sentinel matches this ruleset by NAME
_RC_RULESET = {  # the #1662/ADR-148 fast-lane required-checks ruleset, as scripts/apply_branch_protection.py writes it
    "id": _RC_RULESET_ID,
    "name": "main-required-fast-lane",
    "enforcement": "active",
    "conditions": {"ref_name": {"exclude": [], "include": ["refs/heads/main"]}},
    # #2198: the bypass actor is a `User` (the repo owner) — the `Integration` shape
    # 422s off an org on this personal-account-owned repo (see the ADR-148 amendment).
    "bypass_actors": [{"actor_id": 174924761, "actor_type": "User", "bypass_mode": "always"}],
    "rules": [
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "do_not_enforce_on_create": True,
                "required_status_checks": [
                    {"context": "Collect + deploy-critical + format", "integration_id": 15368},
                    {"context": "gitleaks (PR commit range only, not full history)", "integration_id": 15368},
                ],
            },
        }
    ],
}
_REPO_AUTO_MERGE_ON = {"full_name": "averagejoematt/life-platform", "allow_auto_merge": True}
_REPO_AUTO_MERGE_OFF = {"full_name": "averagejoematt/life-platform", "allow_auto_merge": False}  # LIVE-SHAPE 2026-08-03
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

    # Patch the OWNING module: check_github_config lives in sentinel_github and resolves
    # `_gh_api_result` as one of ITS globals — patching the drift_sentinel re-export alone
    # would bind a name nothing reads and let the test hit real GitHub. Both, deliberately.
    monkeypatch.setattr(sg, "_gh_api_result", fake)
    monkeypatch.setattr(ds, "_gh_api_result", fake)


def _posture_applied(monkeypatch):
    """Flip the #3207 `applied: false` markers to true for one test.

    The shipped `deploy/github_posture.json` marks the ADR-148 required-checks ruleset
    and `repo_settings` as declared-but-NOT-YET-applied (D0.6, blocked on
    RECONCILE_PUSH_TOKEN), so those surfaces report `pending` rather than drift. The
    tests below exercise the POST-apply judging — which is the behaviour `applied: true`
    restores byte-for-byte. Both directions are mutation-proved in
    tests/test_posture_pending_marker.py."""
    posture = json.loads(json.dumps(sg._load_github_posture()))
    posture["main_required_checks_ruleset"]["applied"] = True
    posture["repo_settings"]["applied"] = True
    monkeypatch.setattr(sg, "_load_github_posture", lambda: posture)
    return posture


def _config_routes(env=None, ruleset=None, vuln=None, rc_list=None, rc_full=None, repo=None):
    # ORDER MATTERS: _fake_gh returns the first substring match, so the id-qualified
    # ruleset routes must precede the bare `rulesets` list route, and the bare
    # `repos/<owner>/<repo>` route (which every other path also contains) goes LAST.
    return {
        "environments/production": env or (_LIVE_ENV_GATELESS, None),
        "rulesets/19162901": ruleset or (_LIVE_RULESET, None),
        f"rulesets/{_RC_RULESET_ID}": rc_full or (_RC_RULESET, None),
        "rulesets": rc_list if rc_list is not None else ([_LIVE_RULESET, _RC_RULESET], None),
        "vulnerability-alerts": vuln or ({}, None),  # 204 No Content = enabled
        "/apps/github-actions": (_GITHUB_ACTIONS_APP, None),
        "/users/averagejoematt": (_OWNER_USER, None),
        "repos/": repo or (_REPO_AUTO_MERGE_ON, None),
    }


def test_github_legs_are_owned_by_sentinel_github():
    # The #1665-shaped split moved these into sentinel_github and re-exported them here.
    # A re-export is NOT a patch point (reference_reexport_is_not_a_patch_point): a fake
    # bound only on `ds` would leave the real function reading sentinel_github's globals
    # and quietly hit live GitHub. This pins where they live so _fake_gh keeps patching
    # the module that actually resolves the name.
    assert ds._gh_api_result.__module__ == "sentinel_github"
    assert ds.check_github_config.__module__ == "sentinel_github"
    assert ds.check_github_push_runs.__module__ == "sentinel_github"
    assert ds.check_github_config is sg.check_github_config


def test_github_posture_file_loads_and_declares_all_surfaces():
    posture = ds._load_github_posture()
    assert posture["environment_production"]["required_reviewers"] is True  # ADR-065/CLAUDE.md claim, pending #1319
    assert posture["main_ruleset"]["id"] == 19162901
    assert sorted(posture["main_ruleset"]["rule_types"]) == ["deletion", "non_fast_forward"]
    assert posture["vulnerability_alerts"]["enabled"] is True  # ADR-082 CVE channel claim
    assert posture["repo_settings"]["allow_auto_merge"] is True  # ADR-148 auto-merge posture
    for key in (
        "environment_production",
        "main_ruleset",
        "main_required_checks_ruleset",
        "repo_settings",
        "vulnerability_alerts",
        "push_run_detector",
    ):
        assert posture[key].get("source"), f"{key} must name the doc that makes the claim"


def test_posture_required_checks_never_carry_a_review_rule():
    # ADR-148: solo operator. A `pull_request` rule (required reviews) would make every
    # merge un-landable by its own author. Pinned here as well as in the applier so the
    # spec can't grow one out of band.
    rc = ds._load_github_posture()["main_required_checks_ruleset"]
    assert rc["name"] != "main-block-force-push-and-deletion", "must never manage the #1325 force-push/deletion ruleset"
    assert rc["required_status_checks"], "an empty required set is a silent no-op gate"
    assert rc["strict_required_status_checks_policy"] is False, "strict would force a rebase on every sibling merge"
    for key in ("required_approving_review_count", "require_review", "required_pull_request_reviews"):
        assert key not in rc, f"{key} in the spec would enable required reviews (ADR-148 refuses this)"
    # #2198: the bypass actor is a `User` (the repo owner) — the `Integration` shape
    # 422s off an org on this personal-account-owned repo, measured live 2026-08-07.
    assert any(b.get("actor_type") == "User" and b.get("login") for b in rc["bypass_actors"]), (
        "without a bypass actor the reconcile job's push AUTHENTICATES AS is covered, ci-cd.yml's reconcile job — "
        "which pushes DIRECTLY to main, not via a PR — is rejected by the required-checks rule on every merge day"
    )
    assert rc.get("reconcile_push_secret"), (
        "the spec must name the repo secret ci-cd.yml's reconcile job pushes with to match the User bypass actor "
        "(#2198) — scripts/apply_branch_protection.py refuses --apply until this secret is provisioned"
    )


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
        # #3378: a push-to-main workflow with NO `paths:` filter (ci-cd.yml since
        # 2026-09-01) puts every path in scope. It contributes the universal glob, which
        # `_matches_push_trigger` short-circuits on — the detector's model becomes
        # "every main push should have queued a run", which is stronger than the old
        # one, not broken by it. This used to `assert paths` and tell the reader to
        # update the detector; the detector is updated.
        expected.update(push.get("paths") or ["**"])
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
    # #3378 — these two FLIPPED, and the flip is the point. ci-cd.yml's push-to-main
    # filter is gone, so every path is in scope and every main push should have queued a
    # run. Under the old model a `handovers/`-only wrap commit was an EXPECTED zero-run
    # push, which is exactly the state that let three docs-only wraps inherit a green
    # badge from a commit they never shared code with. There is no longer a path whose
    # absence of a run is ordinary, so a zero-run main push is unambiguously a swallow.
    assert ds._matches_push_trigger("handovers/HANDOVER_LATEST.md")
    assert ds._matches_push_trigger("MEMORY.md")
    # #2881: deploy/ IS push-triggered as of 2026-08-19. It holds smoke_test_site.sh — the
    # gate that can auto-roll-back the public site — so a deploy/-only push earning zero runs
    # was a legitimate path-filter skip indistinguishable from a swallowed push. The prior
    # assertion cited CONVENTIONS §2 (deploy-from-main), which is about packaging the working
    # tree rather than the wrong branch; it never argued deploy/ should skip CI validation.
    assert ds._matches_push_trigger("deploy/drift_sentinel.py")


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


def test_github_config_required_checks_clean_when_applied(monkeypatch):
    # Post-apply steady state: the ADR-148 ruleset exists with the documented contexts,
    # strict off, the github-actions Integration bypass present, auto-merge on.
    _posture_applied(monkeypatch)
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None)))
    res = ds.check_github_config()
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "clean", rc
    assert "Collect + deploy-critical + format" in rc["live_contexts"]
    assert res["surfaces"]["repo_settings"]["status"] == "clean"


def test_github_config_required_checks_drift_when_absent(monkeypatch):
    # The APPLIED-then-deleted shape: the ruleset was live and has since been removed
    # (and auto-merge turned off), so BOTH surfaces must fire.
    #
    # #3207 changed what this fixture means. When the posture entry says `applied:
    # false` — the shipped D0.6 state — the same live shape is the DOCUMENTED desired
    # state and reports `pending`, not drift; before that marker existed, this
    # permanent false alarm recommended an `--apply` that would have wedged the
    # post-merge reconcile push on every merge. `applied: true` is what makes absence a
    # regression, so this test now declares it explicitly rather than inheriting it.
    _posture_applied(monkeypatch)
    _fake_gh(
        monkeypatch,
        _config_routes(
            env=(_ENV_WITH_REVIEWERS, None),
            rc_list=([_LIVE_RULESET], None),
            repo=(_REPO_AUTO_MERGE_OFF, None),
        ),
    )
    res = ds.check_github_config()
    assert res["status"] == "drift"
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift" and "NO required status checks" in rc["detail"]
    assert "apply_branch_protection.py --apply" in rc["detail"]
    settings = res["surfaces"]["repo_settings"]
    assert settings["status"] == "drift" and "allow_auto_merge" in settings["detail"]
    # the pre-existing force-push/deletion ruleset is judged independently and stays clean
    assert res["surfaces"]["main_ruleset"]["status"] == "clean"


def test_github_config_required_checks_drift_when_a_context_is_dropped(monkeypatch):
    weakened = json.loads(json.dumps(_RC_RULESET))
    weakened["rules"][0]["parameters"]["required_status_checks"] = [
        {"context": "Collect + deploy-critical + format", "integration_id": 15368}
    ]
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), rc_full=(weakened, None)))
    res = ds.check_github_config()
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift"
    assert "gitleaks" in rc["detail"]


def test_github_config_required_checks_drift_when_bot_bypass_removed(monkeypatch):
    # Dropping the Integration bypass does not weaken the gate — it WEDGES the reconcile
    # bot's direct push to main. Silent, and only visible on a merge day, so it drifts.
    no_bypass = json.loads(json.dumps(_RC_RULESET))
    no_bypass["bypass_actors"] = []
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), rc_full=(no_bypass, None)))
    res = ds.check_github_config()
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift"
    assert "bypass_actors" in rc["detail"] and "reconcile" in rc["detail"]


def test_github_config_required_checks_drift_on_out_of_band_review_rule(monkeypatch):
    # ADR-148 never applies a `pull_request` rule; if one appears, someone added it in
    # the GitHub UI and every solo merge is about to need an approval that can't come.
    with_review = json.loads(json.dumps(_RC_RULESET))
    with_review["rules"].append({"type": "pull_request", "parameters": {"required_approving_review_count": 1}})
    _fake_gh(monkeypatch, _config_routes(env=(_ENV_WITH_REVIEWERS, None), rc_full=(with_review, None)))
    res = ds.check_github_config()
    rc = res["surfaces"]["main_required_checks_ruleset"]
    assert rc["status"] == "drift"
    assert "approval-shaped" in rc["detail"]


def test_github_config_required_checks_degrades_when_user_lookup_unavailable(monkeypatch):
    # #2198: the checked-in spec's bypass actor is a `User`, resolved via /users/{login}
    # — that lookup down should degrade the comparison to (actor_type, bypass_mode) and
    # SAY so, rather than silently reporting a numeric match that was never made.
    _posture_applied(monkeypatch)
    routes = _config_routes(env=(_ENV_WITH_REVIEWERS, None))
    routes["/users/averagejoematt"] = (None, {"classification": "error", "detail": "gh: timeout"})
    _fake_gh(monkeypatch, routes)
    res = ds.check_github_config()
    assert res["surfaces"]["main_required_checks_ruleset"]["status"] == "clean"


def test_resolve_want_bypass_actor_id_dispatches_and_degrades_by_actor_type(monkeypatch):
    # Unit-level proof _resolve_want_bypass_actor_id routes EITHER actor_type to its own
    # lookup and degrades gracefully on either one going unavailable (guard-the-set: not
    # just the User shape the checked-in spec happens to declare today).
    def fake(path, timeout=60):
        if path == "/users/averagejoematt":
            return _OWNER_USER, None
        if path == "/apps/github-actions":
            return None, {"classification": "error", "detail": "gh: timeout"}
        raise AssertionError(f"unrouted gh api path in test: {path}")

    monkeypatch.setattr(sg, "_gh_api_result", fake)
    pair, degraded = sg._resolve_want_bypass_actor_id({"actor_type": "User", "login": "averagejoematt", "bypass_mode": "always"})
    assert not degraded and pair == (174924761, "User", "always")
    pair, degraded = sg._resolve_want_bypass_actor_id({"actor_type": "Integration", "app": "github-actions", "bypass_mode": "always"})
    assert degraded and pair is None


def test_github_config_scope_gap_is_needs_owner_not_red(monkeypatch):
    # The realistic CI state without the GH_POSTURE_TOKEN secret: admin-read surfaces
    # 403 for the workflow token → "unavailable" + ONE needs-owner line naming the
    # exact fine-grained-PAT permission; NEVER drift/error for a known scope gap.
    #
    # 2026-08-30: the checked-in posture flipped repo_settings to applied:true (D0.6
    # done), so the #3207 pending SHAPE this test also ranks against is synthesized —
    # the fourth fixture tonight that had been silently using reality as its fixture.
    import json as _json

    with open(sg.GITHUB_POSTURE_FILE) as f:
        _pending = _json.load(f)
    _pending["repo_settings"]["applied"] = False
    _pending["repo_settings"].pop("applied_on", None)
    _pending["repo_settings"]["blocked_on"] = "RECONCILE_PUSH_TOKEN (pending-shape fixture; real file applied 2026-08-30)"
    monkeypatch.setattr(sg, "_load_github_posture", lambda: _pending)
    _fake_gh(
        monkeypatch,
        _config_routes(
            env=(_ENV_WITH_REVIEWERS, None),
            ruleset=(None, _SCOPE_ERR),
            rc_list=(None, _SCOPE_ERR),
            vuln=(None, _SCOPE_ERR),
            # auto-merge off + applied:false → repo_settings reports #3207 `pending`:
            # the aggregation must still rank `unavailable` ABOVE pending — a scope gap
            # is "I could not look", which outranks "declared, not yet applied".
            repo=(_REPO_AUTO_MERGE_OFF, None),
        ),
    )
    res = ds.check_github_config()
    assert res["status"] == "unavailable"
    assert res["surfaces"]["repo_settings"]["status"] == "pending"
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

    monkeypatch.setattr(sg, "_gh_api_result", fake)  # owning module (#1665 split)
    monkeypatch.setattr(ds, "_gh_api_result", fake)
    monkeypatch.setattr(sg, "_commit_files", lambda repo, sha: files_by_sha.get(sha, ["lambdas/x.py"]))
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


def test_push_runs_sixmerge_historical_gap_is_clean_not_drift(monkeypatch):
    # #1782: this is the exact false-positive shape flagged 2026-07-26 — a single
    # batch `git push` lands SIX intermediate commits plus its head in one go.
    # GitHub gives exactly one push-event run, at the head (5cacecba); the six
    # predecessors structurally never get their own run. Before the fix this
    # historical-gap cluster (>= gap_cluster_threshold) alarmed as "drift" — a
    # count-based threshold cannot distinguish "6 commits individually missed CI"
    # from "6 commits are the non-head tail of one healthy batch push," and the
    # latter is the overwhelmingly common shape for a solo multi-commit session.
    six = ["e1156b57", "48fad430", "0987479a", "65b88eb0", "9d1c5b42", "cec2a3c4"]
    commits = [_commit("5cacecba", _iso_minutes_ago(60))] + [_commit(s, _iso_minutes_ago(90 + 10 * i)) for i, s in enumerate(six)]
    commits += [_commit("85ac4ad7", _iso_minutes_ago(240))]
    runs = [_run("5cacecba", _iso_minutes_ago(59)), _run("85ac4ad7", _iso_minutes_ago(239))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert [g["sha"] for g in res["gap_commits"]] == six
    assert "6 uncovered historical commit" in res["note"]
    assert res["stalled"] == []
    assert "detail" not in res


def test_push_runs_batch_push_of_eighteen_is_clean(monkeypatch):
    # The literal reported shape (#1782): ONE solo-session push lands 18 commits;
    # only the head gets a run. N commits, 1 run on HEAD = healthy, regardless of N.
    eighteen = [f"c{i:02d}aaaaa" for i in range(18)]
    commits = [_commit("head9999", _iso_minutes_ago(60))]
    commits += [_commit(s, _iso_minutes_ago(65 + 5 * i)) for i, s in enumerate(eighteen)]
    commits += [_commit("prevhead0", _iso_minutes_ago(500))]
    runs = [_run("head9999", _iso_minutes_ago(59)), _run("prevhead0", _iso_minutes_ago(499))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert len(res["gap_commits"]) == 18
    assert res["stalled"] == []


def test_push_runs_single_gap_is_reported_not_alarmed(monkeypatch):
    # ONE uncovered non-head commit could be the tail of a multi-commit push (only the
    # push head gets runs) — reported honestly, never drift (#1782).
    commits = [_commit("head", _iso_minutes_ago(60)), _commit("mid", _iso_minutes_ago(70)), _commit("old", _iso_minutes_ago(200))]
    runs = [_run("head", _iso_minutes_ago(59)), _run("old", _iso_minutes_ago(199))]
    _push_routes(monkeypatch, commits, runs)
    res = ds.check_github_push_runs()
    assert res["status"] == "clean"
    assert [g["sha"] for g in res["gap_commits"]] == ["mid"]
    assert "multi-commit push" in res["note"]


def test_a_handovers_only_commit_with_no_run_is_now_a_swallow(monkeypatch):
    """#3378 — this test INVERTED, and the inversion is the fix.

    It used to read "a wrap commit touching only handovers/ legitimately queues nothing"
    and assert `clean`. That premise was ci-cd.yml's push `paths:` filter, and it is
    exactly the state that let three docs-only wrap commits inherit a green badge from a
    commit they never shared code with — the detector agreed the silence was ordinary.

    With the filter gone every path is in scope, so there is no longer any commit whose
    absence of a run is expected. A 90-minute-old head with no run is a swallow, and the
    sentinel says so."""
    commits = [_commit("wrap", _iso_minutes_ago(90)), _commit("bbb", _iso_minutes_ago(200))]
    runs = [_run("bbb", _iso_minutes_ago(199))]
    _push_routes(monkeypatch, commits, runs, files_by_sha={"wrap": ["handovers/HANDOVER_LATEST.md", "MEMORY.md"]})
    res = ds.check_github_push_runs()
    assert res["status"] == "drift"
    assert [c["sha"] for c in res["stalled"]] == ["wrap"]


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

    monkeypatch.setattr(sg, "_gh_api_result", fake)  # owning module (#1665 split)
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


# ── GitHub quota/billing observability (#1334, #1453) ────────────────────────


def test_run_duration_seconds_parses_iso_timestamps():
    run = {"startedAt": "2026-07-14T10:00:00Z", "updatedAt": "2026-07-14T10:05:30Z"}
    assert ds._run_duration_seconds(run) == 330


def test_run_duration_seconds_soft_fails_on_bad_timestamps():
    assert ds._run_duration_seconds({"startedAt": "not-a-date", "updatedAt": "also-not"}) is None
    assert ds._run_duration_seconds({}) is None


def test_github_quota_billing_unavailable_falls_back_to_proxy(monkeypatch):
    # The realistic case: GITHUB_TOKEN lacks the `user` scope billing needs (confirmed
    # 2026-07-18 live) — must report a clearly-labeled unavailable reason, never crash,
    # and never claim "error"/"degraded" for a structural, known limitation.
    monkeypatch.setattr(sq, "_gh_api_json", lambda path, **k: None)
    monkeypatch.setattr(
        sq,
        "_gh_run_list_trailing",
        lambda **k: [
            {"workflowName": "CI/CD", "startedAt": "2026-07-14T00:00:00Z", "updatedAt": "2026-07-14T00:10:00Z"},
            {"workflowName": "CI/CD", "startedAt": "2026-07-15T00:00:00Z", "updatedAt": "2026-07-15T00:05:00Z"},
            {"workflowName": "Docs CI", "startedAt": "2026-07-14T00:00:00Z", "updatedAt": "2026-07-14T00:02:00Z"},
        ],
    )
    res = ds.check_github_quota()
    assert res["status"] == "unavailable"
    assert res["billing_api"]["available"] is False
    assert "user" in res["billing_api"]["detail"]
    top = {w["workflow"]: w["wall_clock_minutes"] for w in res["top_workflows_7d"]}
    assert top["CI/CD"] == 15.0
    assert top["Docs CI"] == 2.0
    assert "warn" not in res


def _usage_payload(minutes, net_usd=0.0):
    """A new-endpoint (#1613) usage response dated inside the CURRENT month —
    generated at runtime so the month filter matches without wall-clock math."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return {
        "usageItems": [
            {
                "date": f"{now.year:04d}-{now.month:02d}-01T00:00:00Z",
                "product": "actions",
                "sku": "Actions Linux",
                "quantity": float(minutes),
                "unitType": "Minutes",
                "netAmount": float(net_usd),
            }
        ]
    }


def _route_gh_api(usage, private):
    def _fake(path, **k):
        if "settings/billing/usage" in path:
            return usage
        if path.startswith("repos/"):
            return {"private": private} if private is not None else None
        return None

    return _fake


def test_github_quota_billing_available_under_threshold_is_clean(monkeypatch):
    monkeypatch.setattr(sq, "_gh_api_json", _route_gh_api(_usage_payload(900), private=True))
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "clean"
    assert res["billing_api"]["available"] is True
    assert res["billing_api"]["pct_used"] == 30.0
    assert "warn" not in res


def test_github_quota_billing_over_70pct_private_warns_and_drifts(monkeypatch):
    monkeypatch.setattr(sq, "_gh_api_json", _route_gh_api(_usage_payload(2200), private=True))
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "drift"
    assert res["billing_api"]["pct_used"] == pytest.approx(73.3, abs=0.1)
    assert "70%" in res["warn"]


def test_github_quota_over_70pct_public_repo_suppresses_warn(monkeypatch):
    # #1613: public-repo standard-runner minutes are free and don't consume the
    # allowance — the same figure must be REPORTED but never alarmed, or the warn
    # screams permanently while public and trains us to ignore it.
    monkeypatch.setattr(sq, "_gh_api_json", _route_gh_api(_usage_payload(11790), private=False))
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "clean"
    assert "warn" not in res
    assert "PUBLIC" in res["billing_api"]["detail"]
    assert res["billing_api"]["total_minutes_used"] == 11790.0


def test_github_quota_unknown_visibility_at_threshold_warns_conservatively(monkeypatch):
    # Visibility unreadable → assume private (the #1544 failure was a silent
    # private-repo cap; a false alarm beats a dead one).
    monkeypatch.setattr(sq, "_gh_api_json", _route_gh_api(_usage_payload(2500), private=None))
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "drift"
    assert "assuming private" in res["warn"]


def test_github_quota_paid_overage_always_warns(monkeypatch):
    monkeypatch.setattr(sq, "_gh_api_json", _route_gh_api(_usage_payload(3400, net_usd=3.20), private=False))
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "drift"
    assert "$3.20" in res["warn"]


def test_github_quota_warn_reaches_through_the_billing_token_path(monkeypatch):
    """#1613 AC4: the ≥70% warn proven through the REAL token-preference path —
    subprocess-level fake, not a monkeypatched _gh_api_json. Asserts the billing
    call actually carries GH_BILLING_TOKEN as GH_TOKEN."""
    import json as _json
    import subprocess as _sp

    seen_envs = {}

    class _Out:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def _fake_run(cmd, **kwargs):
        path = cmd[2] if len(cmd) > 2 else ""
        seen_envs[path] = (kwargs.get("env") or {}).get("GH_TOKEN")
        if "settings/billing/usage" in path:
            return _Out(_json.dumps(_usage_payload(2900)))
        if path.startswith("repos/"):
            return _Out(_json.dumps({"private": True}))
        return _Out("{}")

    monkeypatch.setenv("GH_BILLING_TOKEN", "github_pat_TESTTOKEN")
    monkeypatch.delenv("GH_POSTURE_TOKEN", raising=False)
    monkeypatch.setattr(_sp, "run", _fake_run)
    monkeypatch.setattr(sq, "_gh_run_list_trailing", lambda **k: [])
    res = ds.check_github_quota()
    assert res["status"] == "drift" and "70%" in res["warn"]
    billing_call = next(p for p in seen_envs if "settings/billing/usage" in p)
    assert seen_envs[billing_call] == "github_pat_TESTTOKEN"


def test_github_quota_top_workflows_proxy_error_is_soft(monkeypatch):
    monkeypatch.setattr(sq, "_gh_api_json", lambda path, **k: None)

    def _boom(**k):
        raise RuntimeError("gh: rate limited")

    monkeypatch.setattr(sq, "_gh_run_list_trailing", _boom)
    res = ds.check_github_quota()
    assert res["status"] == "unavailable"  # still fail-soft, never crashes the sweep
    assert "rate limited" in res["top_workflows_error"]
    assert res["top_workflows_7d"] == []


def test_sweep_stays_clean_when_quota_unavailable(monkeypatch):
    # The common real-world case (no user-scoped PAT wired in): an "unavailable" quota
    # check must NOT drag an otherwise-clean weekly sweep into drift or degraded.
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "clean"
    assert rec["checks"]["github_quota"]["status"] == "unavailable"


def test_sweep_drifts_when_quota_warns(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        quota={
            "status": "drift",
            "warn": "GitHub Actions minutes at 90.0% of the 3000-min allowance (warn threshold 70%)",
            "billing_api": {"available": True, "pct_used": 90.0, "total_minutes_used": 2700, "included_minutes": 3000},
            "top_workflows_7d": [],
        },
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "90.0%" in rec["summary"]


def test_quota_html_renders_unavailable_reason():
    record = {
        "checks": {
            "github_quota": {
                "status": "unavailable",
                "billing_api": {"available": False, "detail": "billing API unavailable: needs the user scope"},
                "top_workflows_7d": [{"workflow": "CI/CD", "wall_clock_minutes": 42.0}],
            }
        }
    }
    html = drift_report.quota_html(record)
    assert "unavailable" in html
    assert "needs the user scope" in html
    assert "CI/CD" in html and "42.0" in html


def test_quota_html_renders_warn_bold_when_over_threshold():
    record = {
        "checks": {
            "github_quota": {
                "status": "drift",
                "warn": "GitHub Actions minutes at 85.0% of the 3000-min allowance (warn threshold 70%)",
                "billing_api": {"available": True, "pct_used": 85.0, "total_minutes_used": 2550, "included_minutes": 3000},
                "top_workflows_7d": [],
            }
        }
    }
    html = drift_report.quota_html(record)
    assert "<b>" in html and "85.0%" in html


def test_quota_html_empty_when_no_record_or_no_quota_check():
    assert drift_report.quota_html(None) == ""
    assert drift_report.quota_html({"checks": {}}) == ""


# ── codeql_alerts regrowth check (#1902) + its can-it-fail proof (#2578) ─────
#
# `check_codeql_alerts` is DEFINED in drift_sentinel, so `ds._gh_api_result` /
# `ds._codeql_api` ARE its patch points (unlike the sentinel_github-defined checks
# above, where the re-export is not). Patched at two depths on purpose:
#   * `ds._gh_api_result` — exercises the real `_codeql_api` (credential choice,
#     the scope-gapped retry, the fail-closed branch).
#   * `ds._codeql_api`    — exercises the real `check_codeql_alerts` end-to-end
#     through run_sweep into the triage path.

_PLANTED_ALERT = {
    "rule": {"id": "py/clear-text-logging-sensitive-data"},
    "most_recent_instance": {"location": {"path": "setup/x.py", "start_line": 7}},
}


def test_codeql_alerts_clean_at_zero(monkeypatch):
    monkeypatch.setattr(ds, "_codeql_api", lambda path, timeout=60: ([], None))
    res = ds.check_codeql_alerts()
    assert res["status"] == "clean"
    assert res["open_count"] == 0
    assert res["reason"] == "triaged"


def test_codeql_alerts_drift_on_any_open_alert(monkeypatch):
    monkeypatch.setattr(ds, "_codeql_api", lambda path, timeout=60: ([_PLANTED_ALERT], None))
    res = ds.check_codeql_alerts()
    assert res["status"] == "drift"
    assert res["reason"] == "regrowth"
    assert res["open_count"] == 1
    assert "py/clear-text-logging-sensitive-data @ setup/x.py:7" in res["sample"]
    assert "triage" in res["detail"]


def test_codeql_alerts_fails_closed_when_the_list_is_unreadable(monkeypatch):
    """#2578 root cause (c). This returned `status: "error"` for its whole life —
    3/3 persisted sentinel records since #1902 shipped it — and `error` never reaches
    drift_report.as_signal. An unreadable alert list is indistinguishable from an
    un-triaged one, so it must be DRIFT."""
    err = {"classification": "scope", "detail": "HTTP 403: Resource not accessible by integration"}
    monkeypatch.setattr(ds, "_codeql_api", lambda path, timeout=60: (None, err))
    res = ds.check_codeql_alerts()
    assert res["status"] == "drift"
    assert res["reason"] == "unreadable"
    assert res["open_count"] is None
    assert "UNREADABLE" in res["detail"]
    # The finding names its own remedy rather than shrugging "auth/scope?".
    assert "security-events: read" in res["detail"]
    assert "Code scanning alerts: read" in res["detail"]


def test_codeql_alerts_fails_closed_on_a_non_list_body(monkeypatch):
    monkeypatch.setattr(ds, "_codeql_api", lambda path, timeout=60: ({"message": "Not Found"}, None))
    res = ds.check_codeql_alerts()
    assert res["status"] == "drift"
    assert res["reason"] == "unreadable"


def test_codeql_read_never_goes_through_the_billing_token_helper(monkeypatch):
    """#2578 root cause (a). The check called `sentinel_quota._gh_api_json`, whose
    #1613 contract swaps GH_TOKEN for GH_BILLING_TOKEN when that is set — and it IS
    set live (repo secret since 2026-07-26), so every code-scanning GET went out on a
    billing-scoped user PAT and 403'd. Regression guard: touching that helper reds."""

    def _forbidden(*a, **k):
        raise AssertionError("check_codeql_alerts must not read code-scanning through the billing-token helper (#2578)")

    monkeypatch.setattr(ds, "_gh_api_json", _forbidden)
    monkeypatch.setattr(ds, "_gh_api_result", lambda path, timeout=60: ([], None))
    assert ds.check_codeql_alerts()["status"] == "clean"


def test_codeql_api_retries_on_the_ambient_token_when_the_pat_is_scope_gapped(monkeypatch):
    """A PAT that overrides GITHUB_TOKEN but lacks `Code scanning alerts: read` must
    not be able to re-dark this check the way GH_BILLING_TOKEN did (#2578)."""
    monkeypatch.setenv("GH_POSTURE_TOKEN", "pat-without-code-scanning")
    seen = []

    def _fake(path, timeout=60):
        seen.append(os.environ.get("GH_POSTURE_TOKEN"))
        if len(seen) == 1:
            return None, {"classification": "scope", "detail": "HTTP 403"}
        return [_PLANTED_ALERT], None

    monkeypatch.setattr(ds, "_gh_api_result", _fake)
    data, err = ds._codeql_api("repos/{owner}/{repo}/code-scanning/alerts?state=open")
    assert err is None and data == [_PLANTED_ALERT]
    # First attempt carried the PAT; the retry deliberately did not — and the env is restored.
    assert seen == ["pat-without-code-scanning", None]
    assert os.environ.get("GH_POSTURE_TOKEN") == "pat-without-code-scanning"


def _sweep_with_real_codeql(monkeypatch, codeql_api):
    """run_sweep with every OTHER check stubbed clean and the REAL check_codeql_alerts
    running against a planted code-scanning response."""
    real = ds.check_codeql_alerts
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
    )
    monkeypatch.setattr(ds, "check_codeql_alerts", real)  # undo _patch_all's stub
    monkeypatch.setattr(ds, "_codeql_api", codeql_api)
    return ds.run_sweep()


def test_planted_open_alert_reaches_the_triage_path(capsys, monkeypatch):
    """#2578 can-it-fail proof, regrowth leg: a planted OPEN alert must BOTH appear in
    the report AND reach a triage path. Surfacing that lands nowhere is the same as
    not firing — so the assert runs all the way through drift_report.as_signal, which
    is what remediation/agent.py feeds into `signals["drift"]`."""
    rec = _sweep_with_real_codeql(monkeypatch, lambda path, timeout=60: ([_PLANTED_ALERT], None))

    # (1) it appears in the report
    assert rec["status"] == "drift"
    assert rec["checks"]["codeql_alerts"]["status"] == "drift"
    assert "1 un-triaged open CodeQL alert(s)" in rec["summary"]
    ds.print_summary(rec)
    printed = capsys.readouterr().out
    assert "codeql_alerts: drift" in printed
    assert "open CodeQL alert(s) on main" in printed  # the detail, not a bare status word

    # (2) it reaches the triage path
    sig = drift_report.as_signal(rec)
    assert sig is not None, "an open CodeQL alert produced no triage signal"
    assert sig["class"] == "needs-human"
    assert "codeql_alerts" in sig["flagging"]
    assert drift_report.status_html(rec).count("CodeQL") >= 1


def test_unreadable_alert_list_also_reaches_the_triage_path(monkeypatch):
    """The fail-closed leg of the same proof — the shape that actually occurred. Under
    the old `error` status this record was `degraded`, as_signal returned None, and the
    only trace was a summary tail-clause behind six drifted stacks."""
    err = {"classification": "scope", "detail": "HTTP 403: Resource not accessible by integration"}
    rec = _sweep_with_real_codeql(monkeypatch, lambda path, timeout=60: (None, err))

    assert rec["status"] == "drift"  # not "degraded"
    assert "CodeQL alert list UNREADABLE (fail-closed)" in rec["summary"]
    sig = drift_report.as_signal(rec)
    assert sig is not None, "an unreadable CodeQL alert list produced no triage signal (#2578)"
    assert "codeql_alerts" in sig["flagging"]


def test_remediation_workflow_grants_security_events_read():
    """#2578 root cause (b): the workflow declares an explicit `permissions:` block,
    which zeroes every unlisted scope. Without `security-events: read` the built-in
    GITHUB_TOKEN cannot GET /code-scanning/alerts, so the check is dark no matter what
    the code does. Asserted against the live YAML, not a fixture."""
    yaml = pytest.importorskip("yaml")  # same guard as test_push_trigger_globs_match_workflows (#3100)

    path = os.path.join(_ROOT, ".github", "workflows", "remediation-agent.yml")
    with open(path) as f:
        wf = yaml.safe_load(f)
    assert wf["permissions"].get("security-events") == "read", (
        "remediation-agent.yml must grant `security-events: read` — drift_sentinel."
        "check_codeql_alerts reads GET /code-scanning/alerts (#2578)"
    )


def test_sweep_surfaces_codeql_drift_in_summary(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        codeql={"status": "drift", "open_count": 3, "sample": [], "detail": "3 open CodeQL alert(s)"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "un-triaged open CodeQL alert(s)" in rec["summary"]


# ── HAE webhook ingress parity (#1946) ───────────────────────────────────────


class _FakeCfnHaeApis:
    """Fake cloudformation client: list_stack_resources returns the given
    AWS::ApiGatewayV2::Api physical ids for LifePlatformIngestion."""

    def __init__(self, api_ids):
        self._api_ids = api_ids

    def list_stack_resources(self, StackName, NextToken=None):  # noqa: N803 — boto3 kwarg casing
        assert StackName == ds.HAE_INGESTION_STACK
        return {"StackResourceSummaries": [{"ResourceType": "AWS::ApiGatewayV2::Api", "PhysicalResourceId": aid} for aid in self._api_ids]}


class _FakeLambdaHaePolicy:
    """Fake lambda client: get_policy returns the given Statement list."""

    def __init__(self, statements):
        self._policy = {"Version": "2012-10-17", "Id": "default", "Statement": statements}

    def get_policy(self, FunctionName):  # noqa: N803 — boto3 kwarg casing
        assert FunctionName == ds.HAE_WEBHOOK_FUNCTION
        return {"Policy": json.dumps(self._policy)}


def _hae_client(monkeypatch, api_ids, statements):
    """Dispatch ds._client("lambda"/"cloudformation") to the two fakes above."""
    fake_lambda = _FakeLambdaHaePolicy(statements)
    fake_cfn = _FakeCfnHaeApis(api_ids)

    def _dispatch(service, region=ds.REGION):
        return {"lambda": fake_lambda, "cloudformation": fake_cfn}[service]

    monkeypatch.setattr(ds, "_client", _dispatch)


def _cdk_stmt(api_id, sid="LifePlatformIngestion-HaeWebhookApiPOSTingestHaeWebhookIntegrationPermission"):
    return {
        "Sid": sid,
        "Effect": "Allow",
        "Principal": {"Service": "apigateway.amazonaws.com"},
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:health-auto-export-webhook",
        "Condition": {"ArnLike": {"AWS:SourceArn": f"arn:aws:execute-api:us-west-2:205930651321:{api_id}/*/*/ingest"}},
    }


def _orphan_stmt(api_id, sid="ApiGatewayInvoke"):
    return {
        "Sid": sid,
        "Effect": "Allow",
        "Principal": {"Service": "apigateway.amazonaws.com"},
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:health-auto-export-webhook",
        "Condition": {"ArnLike": {"AWS:SourceArn": f"arn:aws:execute-api:us-west-2:205930651321:{api_id}/*/*"}},
    }


def test_get_cdk_managed_hae_api_id_returns_the_single_resource(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfnHaeApis(["p6clybdkkc"]))
    api_id, err = ds.get_cdk_managed_hae_api_id()
    assert api_id == "p6clybdkkc"
    assert err is None


def test_get_cdk_managed_hae_api_id_errors_on_zero_resources(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfnHaeApis([]))
    api_id, err = ds.get_cdk_managed_hae_api_id()
    assert api_id is None
    assert "found 0" in err


def test_get_cdk_managed_hae_api_id_errors_on_multiple_resources(monkeypatch):
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCfnHaeApis(["a1", "a2"]))
    api_id, err = ds.get_cdk_managed_hae_api_id()
    assert api_id is None
    assert "found 2" in err


def test_hae_webhook_ingress_clean_when_single_grant_matches_cdk_api(monkeypatch):
    _hae_client(monkeypatch, api_ids=["p6clybdkkc"], statements=[_cdk_stmt("p6clybdkkc")])
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "clean"
    assert res["cdk_api_id"] == "p6clybdkkc"
    assert len(res["invoke_statements"]) == 1


def test_hae_webhook_ingress_drift_when_orphan_grant_also_present(monkeypatch):
    # Reproduces the #1946 live shape: the CDK grant AND the pre-IaC orphan's
    # wildcard grant both on the resource policy at once.
    _hae_client(
        monkeypatch,
        api_ids=["p6clybdkkc"],
        statements=[_cdk_stmt("p6clybdkkc"), _orphan_stmt("a76xwxt2wa")],
    )
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "drift"
    assert "found 2" in res["detail"]
    assert len(res["invoke_statements"]) == 2


def test_hae_webhook_ingress_drift_when_grant_is_wildcard_scoped(monkeypatch):
    # A single statement, but scoped to the CDK api's id with the WIDER wildcard
    # suffix instead of the declared /*/*/ingest route — a re-widened grant.
    _hae_client(monkeypatch, api_ids=["p6clybdkkc"], statements=[_orphan_stmt("p6clybdkkc")])
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "drift"
    assert "wider-than-declared" in res["detail"]


def test_hae_webhook_ingress_drift_when_zero_invoke_statements(monkeypatch):
    _hae_client(monkeypatch, api_ids=["p6clybdkkc"], statements=[])
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "drift"
    assert "found 0" in res["detail"]


def test_hae_webhook_ingress_ignores_non_apigateway_principals(monkeypatch):
    other_principal_stmt = {
        "Sid": "SomeOtherGrant",
        "Effect": "Allow",
        "Principal": {"Service": "events.amazonaws.com"},
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:health-auto-export-webhook",
    }
    _hae_client(monkeypatch, api_ids=["p6clybdkkc"], statements=[_cdk_stmt("p6clybdkkc"), other_principal_stmt])
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "clean"
    assert len(res["invoke_statements"]) == 1


def test_hae_webhook_ingress_error_when_cdk_api_derivation_fails(monkeypatch):
    _hae_client(monkeypatch, api_ids=[], statements=[_cdk_stmt("p6clybdkkc")])
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "error"


def test_hae_webhook_ingress_error_soft_on_get_policy_failure(monkeypatch):
    class _BoomLambda:
        def get_policy(self, FunctionName):  # noqa: N803
            raise RuntimeError("Throttling")

    def _dispatch(service, region=ds.REGION):
        return {"lambda": _BoomLambda(), "cloudformation": _FakeCfnHaeApis(["p6clybdkkc"])}[service]

    monkeypatch.setattr(ds, "_client", _dispatch)
    res = ds.check_hae_webhook_ingress()
    assert res["status"] == "error"
    assert "Throttling" in res["detail"]


def test_sweep_surfaces_hae_webhook_ingress_drift_in_summary(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        hae={"status": "drift", "cdk_api_id": "p6clybdkkc", "invoke_statements": [], "detail": "an out-of-IaC ingress grant"},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "HAE webhook ingress grant drift" in rec["summary"]


# ── sentinel cadence dead-man (#3130) ────────────────────────────────────────
#
# Mirrors #2578's discipline: a genuine gap and an unreadable log must BOTH be
# `status: "drift"` (never a silent clean, never a soft `error` that
# drift_report.as_signal ignores), and a clean cadence must not false-positive.


class _FakeCadenceS3:
    """Fake S3 client for check_sentinel_cadence — list_objects_v2 only, paginated."""

    def __init__(self, dates=None, pages=None, boom=None):
        # `dates`: list of "YYYY-MM-DD" strings present as drift-log/{date}.json.
        # `pages`: optional pre-built list of raw list_objects_v2 responses, for the
        # pagination test. `boom`: an exception to raise instead of listing.
        self._boom = boom
        if pages is not None:
            self._pages = pages
        else:
            dates = dates or []
            contents = [{"Key": f"drift-log/{d}.json"} for d in dates] + [{"Key": "drift-log/latest.json"}]
            self._pages = [{"Contents": contents, "IsTruncated": False}]
        self._calls = 0

    def list_objects_v2(self, **kwargs):
        if self._boom is not None:
            raise self._boom
        page = self._pages[min(self._calls, len(self._pages) - 1)]
        self._calls += 1
        return page


def _cadence_factory(fake):
    return lambda service, region=None: fake


def test_sentinel_cadence_clean_on_fully_populated_fresh_cadence():
    # Anchor "now" on a Thursday (weekday 3) so yesterday (Wed) is the most recent
    # expected date, and populate every Mon/Wed/Fri in the lookback window.
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)  # Thursday
    assert now.weekday() == 3
    expected = scad._expected_dates(now)
    assert expected, "fixture bug: expected at least one Mon/Wed/Fri in the lookback window"
    fake = _FakeCadenceS3(dates=[d.isoformat() for d in expected])
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=now)
    assert res["status"] == "clean"
    assert res["missing_dates"] == []
    assert res["days_stale"] <= scad.STALE_AFTER_DAYS


def test_sentinel_cadence_drift_on_a_planted_gap():
    # Same fresh Thursday anchor, but drop ONE expected date (a Monday) from the
    # populated set — the classic #3112 shape: everything else ran, one didn't.
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    expected = scad._expected_dates(now)
    gap_date = expected[0]  # the oldest expected date in the window, not the freshness edge
    present = [d.isoformat() for d in expected if d != gap_date]
    fake = _FakeCadenceS3(dates=present)
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=now)
    assert res["status"] == "drift"
    assert gap_date.isoformat() in res["missing_dates"]
    assert gap_date.isoformat() in res["detail"]


def test_sentinel_cadence_drift_on_staleness_even_with_no_named_gap():
    # No missing dates in the (short) window, but the newest record is stale beyond
    # the 4-day cadence allowance — the "half-wrote and stalled" shape the missing-
    # dates diff alone wouldn't catch on its own.
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    stale_date = "2026-08-10"  # far beyond STALE_AFTER_DAYS from 2026-08-27
    fake = _FakeCadenceS3(dates=[stale_date])
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=now)
    assert res["status"] == "drift"
    assert res["days_stale"] > scad.STALE_AFTER_DAYS
    assert "stale" in res["detail"]


def test_sentinel_cadence_fails_closed_when_the_log_is_unreadable():
    # #2578/#3112 mutation proof: an S3 error must be drift, NEVER a silent clean and
    # NEVER a soft "error" (as_signal only escalates on status == "drift").
    fake = _FakeCadenceS3(boom=RuntimeError("AccessDenied"))
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    assert res["status"] == "drift"
    assert res["status"] != "error"
    assert "UNREADABLE" in res["detail"]
    assert "AccessDenied" in res["detail"]


def test_sentinel_cadence_drift_on_a_truly_empty_log():
    # A successfully-queried but entirely empty drift-log/ is itself a finding (the
    # sentinel has run since #394), distinct from — but still — drift, not clean.
    fake = _FakeCadenceS3(dates=[])
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    assert res["status"] == "drift"
    assert res["reason"] == "empty"


def test_sentinel_cadence_paginates_list_objects_v2():
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    expected = scad._expected_dates(now)
    page1 = {"Contents": [{"Key": f"drift-log/{expected[0].isoformat()}.json"}], "IsTruncated": True, "NextContinuationToken": "tok"}
    page2 = {"Contents": [{"Key": f"drift-log/{d.isoformat()}.json"} for d in expected[1:]], "IsTruncated": False}
    fake = _FakeCadenceS3(pages=[page1, page2])
    res = scad.check_sentinel_cadence(client_factory=_cadence_factory(fake), now=now)
    assert res["status"] == "clean"
    assert fake._calls == 2


# ── #3508: the cadence fact has ONE writer ────────────────────────────────────
# The old version of this test asserted the literal string `cron: "45 14 * * 1,3,5"` and
# `EXPECTED_WEEKDAYS == {0, 2, 4}` — and passed for weeks while the workflow's own run
# guard said `date -u +%u == 1` (Mondays only). It pinned two of the three encodings and
# was blind to the one that decided behaviour. These tests derive instead of pinning.
_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "remediation-agent.yml")


def _workflow_text():
    with open(_WORKFLOW, encoding="utf-8") as f:
        return f.read()


def test_expected_weekdays_is_derived_from_the_workflow_cron():
    """The module PARSES the schedule cron rather than mirroring it by hand."""
    assert scad.CADENCE_SOURCE_ERROR is None, f"the workflow schedule could not be parsed: {scad.CADENCE_SOURCE_ERROR}"
    assert scad.EXPECTED_WEEKDAYS == scad.workflow_cron_weekdays(_WORKFLOW)
    assert scad.EXPECTED_WEEKDAYS == frozenset({0, 2, 4}), "today's cron is 1,3,5 = Mon/Wed/Fri; this is a sanity anchor, not the source"


def test_changing_the_cron_moves_the_expectation(tmp_path):
    """NEGATIVE CONTROL: mutate the cron and the derived set MUST move. A test that only
    asserted the constant would pass unchanged here — which is how #3508 survived."""
    text = _workflow_text()
    assert 'cron: "45 14 * * 1,3,5"' in text, "the cron literal moved — re-point this control"
    mondays_only = tmp_path / "mondays.yml"
    mondays_only.write_text(text.replace('cron: "45 14 * * 1,3,5"', 'cron: "45 14 * * 1"'), encoding="utf-8")
    assert scad.workflow_cron_weekdays(str(mondays_only)) == frozenset({0})
    assert scad.workflow_cron_weekdays(str(mondays_only)) != scad.EXPECTED_WEEKDAYS

    weekdays = tmp_path / "weekdays.yml"
    weekdays.write_text(text.replace('cron: "45 14 * * 1,3,5"', 'cron: "45 14 * * 1-5"'), encoding="utf-8")
    assert scad.workflow_cron_weekdays(str(weekdays)) == frozenset({0, 1, 2, 3, 4})


def test_cron_sunday_is_both_zero_and_seven():
    """cron's day-of-week is 0=Sun..6=Sat with 7 also Sunday; Python's is 0=Mon..6=Sun.
    Getting this conversion wrong by one is precisely the kind of silent mirror #3508 is
    about, so it is asserted rather than assumed."""
    assert scad._cron_dow_to_python("0") == frozenset({6})
    assert scad._cron_dow_to_python("7") == frozenset({6})
    assert scad._cron_dow_to_python("1") == frozenset({0})
    assert scad._cron_dow_to_python("*") == frozenset(range(7))


def test_the_workflow_guard_asks_the_module_and_carries_no_weekday_literal():
    """The workflow's run guard reads the SAME source. The hardcoded `date -u +%u = 1`
    Monday test is gone — with it present, the declared cadence and the real one could
    (and did) disagree permanently."""
    text = _workflow_text()
    assert "deploy/sentinel_cadence.py --should-run-today" in text, "the workflow no longer derives its run day from the cadence module"
    # Comments are stripped first: the prose ABOVE the guard quotes the old `date -u +%u`
    # literal to explain why it is gone, and a phrase-matched guard would red on its own
    # explanation. The rule is about what EXECUTES.
    executable = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "date -u +%u" not in executable, "the workflow still hardcodes a weekday — that is the #3508 defect, restored"
    assert "not Monday" not in executable


def test_the_workflow_step_gate_does_not_re_state_the_cron():
    """A THIRD copy of the cadence. The step's `if:` used to read
    `github.event.schedule == '45 14 * * 1,3,5'` — editing the cron would have silently
    disabled the sentinel step entirely, with no test and no log line to say so."""
    text = _workflow_text()
    step = text[text.index("- name: Infra drift sentinel") :]
    step = step[: step.index("- name: Run remediation agent")]
    executable = "\n".join(ln for ln in step.splitlines() if not ln.lstrip().startswith("#"))
    assert "github.event.schedule" not in executable, "the step gate re-states the cron literal (#3508)"
    assert "if: github.event_name != 'repository_dispatch'" in executable


def test_the_remediation_role_can_read_the_stacks_it_now_checks():
    """#3508's supersession check calls `cloudformation:DescribeStacks`. Without the grant
    it would fail on every stack, log a warning and suppress nothing — a feature that is
    dark by construction, which is the class this batch is about."""
    policy_path = os.path.join(_ROOT, "infra", "iam", "github-actions-remediation-role.permissions.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    actions = set()
    for stmt in policy.get("Statement", []):
        act = stmt.get("Action")
        actions.update([act] if isinstance(act, str) else act or [])
    assert "cloudformation:DescribeStacks" in actions, (
        "drift_report.superseded_cfn_stacks needs cloudformation:DescribeStacks on "
        "github-actions-remediation-role; without it the suppression can never fire (#3508)"
    )


def test_should_run_today_agrees_with_the_expectation():
    """The predicate the workflow calls and the set the check grades against are the same
    fact, evaluated on every day of one week."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    for day in range(31, 38):  # 2026-08-31 (Mon) .. 2026-09-06 (Sun)
        d = _dt(2026, 8, 1, 12, tzinfo=_tz.utc) + _td(days=day - 1)
        assert scad.should_run_today(d) == (d.weekday() in scad.EXPECTED_WEEKDAYS)


def test_an_unparseable_schedule_is_drift_not_a_silent_guess(monkeypatch):
    """FAIL CLOSED: if the cadence source cannot be read, grading a cadence against the
    fallback would be "verified nothing wrong" wearing "couldn't verify"'s clothes."""
    monkeypatch.setattr(scad, "CADENCE_SOURCE_ERROR", "ValueError: no `- cron:` schedule found")
    res = scad.check_sentinel_cadence(client_factory=lambda *a, **k: pytest.fail("must not reach S3"))
    assert res["status"] == "drift"
    assert res["reason"] == "unknown_cadence"
    assert "cannot read the sentinel's own schedule" in res["detail"]


def test_sweep_surfaces_sentinel_cadence_drift_in_summary(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        cadence={
            "status": "drift",
            "reason": "gap",
            "missing_dates": ["2026-08-17"],
            "latest_date": "2026-08-24",
            "days_stale": 0,
            "detail": "sentinel cadence gap — missing expected run date(s): 2026-08-17",
        },
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "sentinel cadence gap" in rec["summary"]
    sig = drift_report.as_signal(rec)
    assert sig is not None
    assert "sentinel_cadence" in sig["flagging"]
    assert sig["flagging"]["sentinel_cadence"]["status"] == "drift"


def test_sweep_stays_clean_when_cadence_is_clean(monkeypatch):
    _patch_all(
        monkeypatch,
        cfn={"status": "clean", "stacks": {}},
        post={"config_drift": {"status": "clean"}, "layer_uniformity": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
        orphan={"status": "clean", "orphans": []},
        bucket={"status": "clean", "missing_prefixes": []},
        cadence={"status": "clean", "missing_dates": [], "latest_date": "2026-08-24", "days_stale": 0},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "clean"
