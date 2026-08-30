#!/usr/bin/env python3
"""
deploy/sentinel_events.py — EventBridge rule drift: enabled-targetless and out-of-IaC
rules (#3279). Own module (same split shape as `sentinel_github.py` / `sentinel_quota.py`
/ `sentinel_replication.py` / `sentinel_cadence.py` — module-size ceiling #1665),
imported into `deploy/drift_sentinel.py` with a one-line registration.

WHY THIS CHECK (#3279)
──────────────────────
`drift_sentinel.py` had NO `events` client at all — against 96 live EventBridge rules,
zero drift coverage. The measured consequence: `life-platform-monthly-export`
(`cron(0 11 1 * ? *)`, ENABLED, **zero targets**, no CloudFormation owner, no tags)
survived 5.5 months past the review that had already seen it
(`docs/reviews/REVIEW_2026-03-10_full.md:43` — "intentionally unmanaged"), while its
`lambda:InvokeFunction` grant (`Sid: monthly-export-eventbridge`) stayed live on
`life-platform-data-export` — so anyone re-adding a target in the console would have
re-armed a monthly export CDK knows nothing about, with no review. Worse, the Lambda's
own docstring cited the rule's exact cron as its schedule, so the stale doc was
corroborated by the very artifact that made it false. Two drift classes close here:

  1. ENABLED + ZERO TARGETS — a schedule that fires into nothing. Every rule CDK
     manages gets its target in the same construct; a targetless enabled rule is
     either abandoned (delete it) or half-adopted (finish the adoption). Checked for
     EVERY live rule, allowlisted or not (guard-the-SET: the allowlist below only
     answers "who owns this rule", never "may it dangle").
  2. ABSENT FROM CDK — a live rule that is no CloudFormation stack's resource and not
     in the declared `KNOWN_OUT_OF_IAC_RULES` registry below. The same shape as
     `check_orphan_functions` (a console-created resource with no IaC record), applied
     to the resource type that decides when code RUNS.

THE PHYSICAL-ID SHAPE THAT WOULD HAVE FALSE-POSITIVED 10 RULES
──────────────────────────────────────────────────────────────
`list_stack_resources` reports an `AWS::Events::Rule`'s PhysicalResourceId as the BARE
NAME for CDK-auto-named rules but as the FULL ARN (`arn:aws:events:…:rule/<name>`) for
rules carrying an explicit `rule_name=` (the manual→CDK migration exception, ADR-021).
Both shapes are live today — measured 2026-08-29: 83 names + 10 ARNs across the eight
us-west-2 stacks. `_rule_name()` normalizes; without it this check would have reported
ten CFN-managed rules as orphans on its first run.

Scope: default event bus, REGION only — mirrors `check_orphan_functions`' scoping.
Measured 2026-08-29: zero `AWS::Events::Rule` resources in the non-default-region
stacks (LifePlatformWeb us-east-1, LifePlatformBackup us-east-2), so a region-local
sweep sees the whole managed set.

Cost: one paginated ListRules + one ListStackResources sweep (already paid by other
checks) + one ListTargetsByRule per ENABLED rule (~94/week). Read-only, no new infra.
"""

from __future__ import annotations

import os

REGION = os.environ.get("AWS_REGION", "us-west-2")

# Live rules that are legitimately not any CloudFormation stack's resource, each with
# the reason a reviewer needs. Presence here suppresses ONLY the out-of-IaC half; an
# allowlisted rule that is ENABLED with zero targets still reports drift. Every entry
# must name its writer or its retirement path — an entry without one is the drift.
KNOWN_OUT_OF_IAC_RULES = {
    "life-platform-mcp-canary-15min": (
        "script-managed: deploy/create_mcp_canary_15min.sh (R13-F14 MCP canary) — "
        "deliberate single-writer out-of-IaC, live target verified 2026-08-29"
    ),
    "life-platform-nightly-warmer": (
        "deprecated legacy warmer, DISABLED live (ADR-021 exception; superseded by the "
        "CDK-managed LifePlatformMcp warmer rule in v3.7.22) — deletion candidate, kept "
        "visible here rather than silently tolerated"
    ),
}

# The #3279 orphan — shared with deploy/teardown_orphan_export_rule.py so the check and
# the teardown agree on what they are talking about (the get_cdk_managed_hae_api_id
# precedent, #1946). Deliberately NOT in KNOWN_OUT_OF_IAC_RULES: until the driver runs
# the teardown, this rule must keep reporting as drift.
ORPHAN_EXPORT_RULE = "life-platform-monthly-export"
ORPHAN_EXPORT_SID = "monthly-export-eventbridge"
DATA_EXPORT_FUNCTION = "life-platform-data-export"


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


def _rule_name(physical_id):
    """Normalize a CFN PhysicalResourceId to a bare rule name (see module docstring —
    both the bare-name and full-ARN shapes are live today)."""
    if physical_id.startswith("arn:"):
        return physical_id.rsplit("/", 1)[-1]
    return physical_id


def _region_local_stacks():
    """The region-local slice of drift_sentinel's STACKS registry — imported lazily at
    call time (drift_sentinel imports THIS module at load, so a module-level import
    back would be circular), so there is exactly one stack registry to maintain."""
    import drift_sentinel

    return [name for name, region in drift_sentinel.STACKS.items() if region == REGION]


def check_eventbridge_rules():
    """Every live EventBridge rule (default bus, REGION) must (1) have at least one
    target if ENABLED and (2) be a resource of one of our CFN stacks or a documented
    entry in KNOWN_OUT_OF_IAC_RULES. Fail-soft: any state this check cannot observe
    reports `error` with the failing call named — never clean (#2578 two-half bar)."""
    try:
        stacks = _region_local_stacks()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"resolve stack registry: {e}"}

    try:
        ev = _client("events")
        live = {}
        token = None
        while True:
            kw = {"Limit": 100}
            if token:
                kw["NextToken"] = token
            resp = ev.list_rules(**kw)
            for rule in resp.get("Rules", []):
                live[rule["Name"]] = rule
            token = resp.get("NextToken")
            if not token:
                break
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_rules: {e}"}

    try:
        cfn = _client("cloudformation")
        managed = set()
        for name in stacks:
            token = None
            while True:
                kw = {"StackName": name}
                if token:
                    kw["NextToken"] = token
                resp = cfn.list_stack_resources(**kw)
                for r in resp.get("StackResourceSummaries", []):
                    if r.get("ResourceType") == "AWS::Events::Rule" and r.get("PhysicalResourceId"):
                        managed.add(_rule_name(r["PhysicalResourceId"]))
                token = resp.get("NextToken")
                if not token:
                    break
    except Exception as e:  # noqa: BLE001
        # The vacuum here would red EVERY rule as an orphan — `error` is the honest
        # verdict, and no orphan list is published from an unread IaC side.
        return {"status": "error", "detail": f"list_stack_resources: {e}"}

    enabled_targetless = []
    try:
        for name, rule in sorted(live.items()):
            if rule.get("State") != "ENABLED":
                continue
            if not ev.list_targets_by_rule(Rule=name).get("Targets", []):
                enabled_targetless.append(name)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_targets_by_rule: {e}"}

    unmanaged = set(live) - managed
    out_of_iac = sorted(unmanaged - set(KNOWN_OUT_OF_IAC_RULES))
    # Allowlisted rules stay VISIBLE in the record (the #1781 filtered_noise idiom:
    # suppressed from drift, never silently dropped).
    known_out_of_iac = {name: KNOWN_OUT_OF_IAC_RULES[name] for name in sorted(unmanaged & set(KNOWN_OUT_OF_IAC_RULES))}

    result = {
        "status": "drift" if (enabled_targetless or out_of_iac) else "clean",
        "live_count": len(live),
        "managed_count": len(managed),
        "enabled_targetless": enabled_targetless,
        "out_of_iac": out_of_iac,
        "known_out_of_iac": known_out_of_iac,
    }
    if result["status"] == "drift":
        parts = []
        if enabled_targetless:
            parts.append(f"ENABLED rule(s) with zero targets — a schedule firing into nothing: {enabled_targetless}")
        if out_of_iac:
            parts.append(
                f"live rule(s) absent from every CDK stack and undeclared in KNOWN_OUT_OF_IAC_RULES: {out_of_iac} — "
                "adopt into CDK with a real target, or delete (the #3279 export rule: deploy/teardown_orphan_export_rule.py)"
            )
        result["detail"] = "; ".join(parts)
    return result
