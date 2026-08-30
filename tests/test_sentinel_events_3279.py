"""tests/test_sentinel_events_3279.py — can-it-fail proofs for the EventBridge rule
drift check (#3279) and the orphan monthly-export teardown script.

The live condition this closes, measured 2026-08-29 read-only: 96 EventBridge rules in
us-west-2; `life-platform-monthly-export` ENABLED with `cron(0 11 1 * ? *)` and ZERO
targets, no CloudFormation owner, no tags — while its `lambda:InvokeFunction` grant
(`Sid: monthly-export-eventbridge`) stayed live on `life-platform-data-export`, whose
own docstring cited that exact cron as its schedule. `drift_sentinel.py` had no
`events` client at all, so nothing could ever have reported it.

Held to the family-6 two-half bar (#2578/#3112, tests/test_sentinel_canfail_2578.py):
  (a) DETECT — plant the condition, watch `drift` with the rule NAMED;
  (b) CANNOT-OBSERVE — plant each unreadable state, watch `error`, never `clean`.

All offline: fakes are built to the real boto3 call shapes (fixture-must-be-the-wire);
the grant fixture is byte-for-byte the live resource policy captured 2026-08-29.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "remediation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drift_report  # noqa: E402
import drift_sentinel as ds  # noqa: E402
import sentinel_events as se  # noqa: E402  — the OWNING module; a re-export is NOT a patch point
import teardown_orphan_export_rule as teardown  # noqa: E402

# ── LIVE-SHAPE fixtures (captured read-only 2026-08-29) ──────────────────────

_LIVE_ORPHAN_RULE = {  # aws events list-rules — the #3279 condition, verbatim fields
    "Name": "life-platform-monthly-export",
    "Arn": "arn:aws:events:us-west-2:205930651321:rule/life-platform-monthly-export",
    "State": "ENABLED",
    "Description": "Monthly full data export to S3",
    "ScheduleExpression": "cron(0 11 1 * ? *)",
    "EventBusName": "default",
}

_LIVE_GRANT_POLICY = {  # aws lambda get-policy on life-platform-data-export, verbatim
    "Version": "2012-10-17",
    "Id": "default",
    "Statement": [
        {
            "Sid": "monthly-export-eventbridge",
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": "lambda:InvokeFunction",
            "Resource": "arn:aws:lambda:us-west-2:205930651321:function:life-platform-data-export",
            "Condition": {"ArnLike": {"AWS:SourceArn": "arn:aws:events:us-west-2:205930651321:rule/life-platform-monthly-export"}},
        }
    ],
}


def _rule(name, state="ENABLED", schedule="rate(1 day)"):
    return {"Name": name, "State": state, "ScheduleExpression": schedule, "EventBusName": "default"}


class _FakeEvents:
    """list_rules (paginated) + list_targets_by_rule on the real call shapes."""

    def __init__(self, rule_pages, targets, rules_raise=None, targets_raise=None):
        self._pages = rule_pages  # list of lists of rule dicts
        self._targets = targets  # {rule_name: [target, ...]}
        self._rules_raise = rules_raise
        self._targets_raise = targets_raise

    def list_rules(self, **kw):
        if self._rules_raise:
            raise self._rules_raise
        idx = int(kw.get("NextToken") or 0)
        out = {"Rules": self._pages[idx]}
        if idx + 1 < len(self._pages):
            out["NextToken"] = str(idx + 1)
        return out

    def list_targets_by_rule(self, Rule):  # noqa: N803 — boto3 kwarg casing
        if self._targets_raise:
            raise self._targets_raise
        return {"Targets": self._targets.get(Rule, [])}


class _FakeCfnRules:
    """list_stack_resources returning AWS::Events::Rule physical ids per stack."""

    def __init__(self, by_stack, raises=None):
        self._by_stack = by_stack
        self._raises = raises

    def list_stack_resources(self, **kw):  # noqa: N803
        if self._raises:
            raise self._raises
        return {
            "StackResourceSummaries": [
                {"ResourceType": "AWS::Events::Rule", "PhysicalResourceId": p} for p in self._by_stack.get(kw["StackName"], [])
            ]
        }


def _wire(monkeypatch, *, rules, targets, managed, stacks=("LifePlatformCompute",), rules_raise=None, targets_raise=None, cfn_raise=None):
    """Patch sentinel_events' OWN client factory and stack registry (never the
    drift_sentinel re-export — reference_reexport_is_not_a_patch_point)."""
    pages = rules if rules and isinstance(rules[0], list) else [rules]
    fake_ev = _FakeEvents(pages, targets, rules_raise, targets_raise)
    fake_cfn = _FakeCfnRules(managed, cfn_raise)

    def _factory(service, region=None):
        if service == "events":
            return fake_ev
        if service == "cloudformation":
            return fake_cfn
        raise AssertionError(f"unexpected client in test: {service}")

    monkeypatch.setattr(se, "_client", _factory)
    monkeypatch.setattr(se, "_region_local_stacks", lambda: list(stacks))
    return fake_ev, fake_cfn


# ── the single stack registry ────────────────────────────────────────────────


def test_region_local_stacks_derive_from_drift_sentinel_registry():
    """Guard-the-SET: the events check walks the SAME stack registry as everything
    else (drift_sentinel.STACKS), filtered to region-local — never a second hand list
    that could drift when a stack is added (#1816/#1817 region-map class)."""
    expected = [name for name, region in ds.STACKS.items() if region == se.REGION]
    assert se._region_local_stacks() == expected
    assert len(expected) == 8  # the eight us-west-2 stacks; Web/Backup are other-region


# ── baseline (the drift assertions below are meaningless without it) ─────────


def test_clean_when_every_rule_is_managed_and_targeted(monkeypatch):
    _wire(
        monkeypatch,
        rules=[_rule("cdk-rule-a"), _rule("named-rule-b")],
        targets={"cdk-rule-a": [{"Id": "t"}], "named-rule-b": [{"Id": "t"}]},
        managed={"LifePlatformCompute": ["cdk-rule-a", "arn:aws:events:us-west-2:205930651321:rule/named-rule-b"]},
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "clean", res
    assert res["enabled_targetless"] == [] and res["out_of_iac"] == []
    assert res["live_count"] == 2 and res["managed_count"] == 2


def test_arn_shaped_physical_id_matches_its_live_bare_name():
    """The false-positive mutation this check shipped WITHOUT: 10 of the 93 live
    managed rules resolve their PhysicalResourceId as the full ARN (explicit
    `rule_name=` rules, ADR-021), the other 83 as the bare name. An un-normalized
    comparison reported all ten as orphans on the first live run of this code."""
    assert se._rule_name("arn:aws:events:us-west-2:205930651321:rule/anomaly-detector-daily") == "anomaly-detector-daily"
    assert (
        se._rule_name("LifePlatformCompute-ACWRComputeSchedule8A50DC3E-zna66onGxNhQ")
        == "LifePlatformCompute-ACWRComputeSchedule8A50DC3E-zna66onGxNhQ"
    )


def test_list_rules_pagination_counts_every_page(monkeypatch):
    _wire(
        monkeypatch,
        rules=[[_rule("page1-rule")], [_rule("page2-rule")]],
        targets={"page1-rule": [{"Id": "t"}], "page2-rule": [{"Id": "t"}]},
        managed={"LifePlatformCompute": ["page1-rule", "page2-rule"]},
    )
    res = se.check_eventbridge_rules()
    assert res["live_count"] == 2, "a check that read only page 1 under-counts forever"
    assert res["status"] == "clean"


# ── (a) DETECT ───────────────────────────────────────────────────────────────


def test_detects_the_live_orphan_shape_enabled_targetless_rule(monkeypatch):
    """The exact #3279 condition, on the LIVE-SHAPE rule dict: ENABLED, cron
    matching the stale docstring, zero targets, no stack owns it."""
    _wire(
        monkeypatch,
        rules=[_rule("cdk-rule-a"), dict(_LIVE_ORPHAN_RULE)],
        targets={"cdk-rule-a": [{"Id": "t"}]},  # the orphan resolves to zero targets
        managed={"LifePlatformCompute": ["cdk-rule-a"]},
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "drift"
    assert res["enabled_targetless"] == ["life-platform-monthly-export"]
    assert res["out_of_iac"] == ["life-platform-monthly-export"]
    assert "zero targets" in res["detail"]
    assert "teardown_orphan_export_rule.py" in res["detail"], "a drift finding nobody can act on is half a finding"


def test_detects_a_planted_out_of_iac_rule_even_with_a_live_target(monkeypatch):
    """The other half of the class: a console-created rule that WORKS (has a target)
    is still unreviewed infrastructure — out-of-IaC alone must drift."""
    _wire(
        monkeypatch,
        rules=[_rule("console-made-cron")],
        targets={"console-made-cron": [{"Id": "t", "Arn": "arn:aws:lambda:us-west-2:1:function:x"}]},
        managed={"LifePlatformCompute": []},
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "drift"
    assert res["out_of_iac"] == ["console-made-cron"]
    assert res["enabled_targetless"] == []


def test_allowlisted_rules_are_visible_but_not_drift(monkeypatch):
    """The two DECLARED out-of-IaC rules (script-managed canary, deprecated warmer)
    report in `known_out_of_iac` with their reasons — the #1781 filtered_noise idiom:
    suppressed from drift, never silently dropped."""
    _wire(
        monkeypatch,
        rules=[
            _rule("life-platform-mcp-canary-15min", schedule="rate(15 minutes)"),
            _rule("life-platform-nightly-warmer", state="DISABLED"),
        ],
        targets={"life-platform-mcp-canary-15min": [{"Id": "t"}], "life-platform-nightly-warmer": [{"Id": "t"}]},
        managed={"LifePlatformCompute": []},
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "clean", res
    assert set(res["known_out_of_iac"]) == {"life-platform-mcp-canary-15min", "life-platform-nightly-warmer"}
    for reason in res["known_out_of_iac"].values():
        assert len(reason) > 40, "an allowlist entry without a reviewable reason is the drift"


def test_an_allowlisted_rule_that_dangles_still_drifts(monkeypatch):
    """Guard the SET: the allowlist answers 'who owns this rule', never 'may it fire
    into nothing'. An allowlisted rule gone enabled-targetless must still report."""
    _wire(
        monkeypatch,
        rules=[_rule("life-platform-mcp-canary-15min")],
        targets={},  # its target was deleted out of band
        managed={"LifePlatformCompute": []},
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "drift"
    assert res["enabled_targetless"] == ["life-platform-mcp-canary-15min"]
    assert res["out_of_iac"] == []


def test_disabled_targetless_rule_is_not_targetless_drift(monkeypatch):
    """SCOPE pin: a DISABLED rule fires nothing, so dangling is not the defect —
    but a disabled UNDECLARED rule still drifts on the out-of-IaC half."""
    _wire(monkeypatch, rules=[_rule("dead-rule", state="DISABLED")], targets={}, managed={"LifePlatformCompute": []})
    res = se.check_eventbridge_rules()
    assert res["enabled_targetless"] == []
    assert res["out_of_iac"] == ["dead-rule"]


# ── (b) CANNOT-OBSERVE ───────────────────────────────────────────────────────


def test_cannot_list_rules_is_error_not_clean(monkeypatch):
    """An empty live set would compute zero drift and read CLEAN — the vacuous pass
    this half rules out."""
    _wire(monkeypatch, rules=[], targets={}, managed={}, rules_raise=RuntimeError("AccessDenied: events:ListRules"))
    res = se.check_eventbridge_rules()
    assert res["status"] == "error"
    assert "list_rules" in res["detail"] and "AccessDenied" in res["detail"]


def test_cannot_list_stack_resources_is_error_and_publishes_no_orphan_list(monkeypatch):
    """The OPPOSITE vacuum: an unread IaC side would make all 96 live rules look like
    orphans and page for dozens of false positives."""
    _wire(
        monkeypatch,
        rules=[_rule("cdk-rule-a")],
        targets={"cdk-rule-a": [{"Id": "t"}]},
        managed={},
        cfn_raise=RuntimeError("AccessDenied: cloudformation:ListStackResources"),
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "error"
    assert "list_stack_resources" in res["detail"]
    assert "out_of_iac" not in res, "a check that could not read IaC must not publish an orphan list"


def test_cannot_list_targets_is_error_not_clean(monkeypatch):
    _wire(
        monkeypatch,
        rules=[_rule("cdk-rule-a")],
        targets={},
        managed={"LifePlatformCompute": ["cdk-rule-a"]},
        targets_raise=RuntimeError("Throttling: rate exceeded"),
    )
    res = se.check_eventbridge_rules()
    assert res["status"] == "error"
    assert "list_targets_by_rule" in res["detail"]


# ── the sweep seam: drift must reach the triage path, not just the record ────

_SWEEP_STUBS = {
    "check_cfn_drift": {"status": "clean", "stacks": {}},
    "check_orphan_functions": {"status": "clean", "orphans": []},
    "check_bucket_policy": {"status": "clean", "missing_prefixes": []},
    "check_s3_lifecycle": {"status": "clean", "missing_rule_ids": [], "extra_rule_ids": [], "changed_rule_ids": []},
    "check_dynamodb_ttl": {"status": "clean", "declared_attribute": "ttl", "live_attribute": "ttl", "live_status": "ENABLED"},
    "check_oidc_iam": {"status": "clean"},
    "check_doc_literals": {"status": "clean", "mismatches": []},
    "check_site_sha_ancestry": {"status": "clean", "live_sha": "deadbeef"},
    "check_github_config": {"status": "clean", "surfaces": {}},
    "check_github_push_runs": {"status": "clean", "stalled": [], "gap_commits": []},
    "check_github_quota": {"status": "unavailable", "billing_api": {"available": False, "detail": "test"}, "top_workflows_7d": []},
    "check_codeql_alerts": {"status": "clean", "open_count": 0, "sample": []},
    "check_hae_webhook_ingress": {"status": "clean", "cdk_api_id": "x", "invoke_statements": []},
    "check_raw_replication": {"status": "clean", "objects_confirmed": 2},
    "check_sentinel_cadence": {"status": "clean", "missing_dates": [], "latest_date": "2026-08-28", "days_stale": 1},
}


def test_sweep_eventbridge_drift_reaches_the_triage_path(monkeypatch):
    """run_sweep with every OTHER check stubbed clean and the REAL events check on the
    planted live shape: the drift must reach drift_report.as_signal's flagging map —
    the #2578 lesson that a finding landing only in the record reaches nobody."""
    for name, value in _SWEEP_STUBS.items():
        monkeypatch.setattr(ds, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(
        ds,
        "check_postflight",
        lambda: {"layer_uniformity": {"status": "clean"}, "config_drift": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
    )
    _wire(
        monkeypatch,
        rules=[dict(_LIVE_ORPHAN_RULE)],
        targets={},
        managed={"LifePlatformCompute": []},
    )
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "EventBridge rule drift" in rec["summary"]
    sig = drift_report.as_signal(rec)
    assert sig is not None
    assert "eventbridge_rules" in sig["flagging"]
    assert sig["flagging"]["eventbridge_rules"]["status"] == "drift"


# ── teardown script (#3279 — driver-run; these prove the dry-run/apply seam) ─


class _RNFException(Exception):
    pass


_RNFException.__name__ = "ResourceNotFoundException"


class _FakeTeardownEvents:
    def __init__(self, rule=None, targets=()):
        self._rule = rule
        self._targets = list(targets)
        self.deleted_rules = []
        self.removed_targets = []

    def describe_rule(self, Name):  # noqa: N803
        if self._rule is None:
            raise _RNFException(f"Rule {Name} does not exist")
        return dict(self._rule)

    def list_targets_by_rule(self, Rule):  # noqa: N803
        return {"Targets": list(self._targets)}

    def remove_targets(self, Rule, Ids):  # noqa: N803
        self.removed_targets.append((Rule, list(Ids)))

    def delete_rule(self, Name):  # noqa: N803
        self.deleted_rules.append(Name)


class _FakeTeardownLambda:
    def __init__(self, policy=None):
        self._policy = policy
        self.revoked = []

    def get_policy(self, FunctionName):  # noqa: N803
        if self._policy is None:
            raise _RNFException("The resource you requested does not exist")
        return {"Policy": json.dumps(self._policy)}

    def remove_permission(self, FunctionName, StatementId):  # noqa: N803
        self.revoked.append(StatementId)


def _run_teardown(monkeypatch, ev, lam, argv):
    def _factory(service, region=None):
        return {"events": ev, "lambda": lam}[service]

    monkeypatch.setattr(teardown, "_client", _factory)
    monkeypatch.setattr(sys, "argv", ["teardown_orphan_export_rule.py", *argv])
    return teardown.main()


def test_teardown_dry_run_deletes_nothing(monkeypatch):
    ev = _FakeTeardownEvents(rule=dict(_LIVE_ORPHAN_RULE))
    lam = _FakeTeardownLambda(policy=_LIVE_GRANT_POLICY)
    assert _run_teardown(monkeypatch, ev, lam, []) == 0
    assert ev.deleted_rules == [] and ev.removed_targets == [] and lam.revoked == []


def test_teardown_apply_deletes_rule_and_revokes_the_live_grant(monkeypatch):
    ev = _FakeTeardownEvents(rule=dict(_LIVE_ORPHAN_RULE))
    lam = _FakeTeardownLambda(policy=_LIVE_GRANT_POLICY)
    assert _run_teardown(monkeypatch, ev, lam, ["--apply"]) == 0
    assert ev.deleted_rules == ["life-platform-monthly-export"]
    assert lam.revoked == ["monthly-export-eventbridge"]


def test_teardown_refuses_when_the_rule_regrew_a_target(monkeypatch):
    """The premise check: #3279 ruled DELETE against a TARGETLESS rule. A target
    re-added since means someone re-armed it — refuse without --force, delete nothing."""
    ev = _FakeTeardownEvents(rule=dict(_LIVE_ORPHAN_RULE), targets=[{"Id": "t1", "Arn": "arn:aws:lambda:us-west-2:1:function:x"}])
    lam = _FakeTeardownLambda(policy=_LIVE_GRANT_POLICY)
    assert _run_teardown(monkeypatch, ev, lam, ["--apply"]) == 1
    assert ev.deleted_rules == [] and lam.revoked == []


def test_teardown_idempotent_when_both_halves_already_gone(monkeypatch):
    ev = _FakeTeardownEvents(rule=None)
    lam = _FakeTeardownLambda(policy=None)
    assert _run_teardown(monkeypatch, ev, lam, ["--apply"]) == 0
    assert ev.deleted_rules == [] and lam.revoked == []


def test_grant_matcher_catches_arn_matched_statement_with_an_unknown_sid(monkeypatch):
    """Guard-the-SET: a second grant added later under a different Sid but conditioned
    on the same rule ARN must also be found — never only the known Sid literal."""
    policy = json.loads(json.dumps(_LIVE_GRANT_POLICY))
    policy["Statement"][0]["Sid"] = "someone-readded-this"
    lam = _FakeTeardownLambda(policy=policy)
    monkeypatch.setattr(teardown, "_client", lambda service, region=None: lam)
    grants = teardown.find_orphan_invoke_grants(lam)
    assert grants == [
        {"sid": "someone-readded-this", "source_arn": "arn:aws:events:us-west-2:205930651321:rule/life-platform-monthly-export"}
    ]


def test_grant_matcher_ignores_unrelated_principals_and_rules(monkeypatch):
    policy = {
        "Statement": [
            {
                "Sid": "other-service",
                "Principal": {"Service": "apigateway.amazonaws.com"},
                "Condition": {"ArnLike": {"AWS:SourceArn": "arn:aws:events:us-west-2:1:rule/life-platform-monthly-export"}},
            },
            {
                "Sid": "other-rule",
                "Principal": {"Service": "events.amazonaws.com"},
                "Condition": {"ArnLike": {"AWS:SourceArn": "arn:aws:events:us-west-2:1:rule/some-other-rule"}},
            },
        ]
    }
    lam = _FakeTeardownLambda(policy=policy)
    assert teardown.find_orphan_invoke_grants(lam) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
