#!/usr/bin/env python3
"""
deploy/sentinel_log_retention.py — security-tier CloudWatch Logs retention, declared vs.
live, in EVERY enabled region (#3278). Own module (same split shape as `sentinel_github.py`
/ `sentinel_quota.py` / `sentinel_replication.py` / `sentinel_cadence.py` /
`sentinel_events.py` — module-size ceiling #1665), imported into `deploy/drift_sentinel.py`
with a one-line registration.

WHY THIS CHECK (#3278)
──────────────────────
`docs/DATA_GOVERNANCE.md` has promised a 90-day security-log tier (canary, key-rotator,
dlq-consumer, cf-auth) since 2026-05-17. Measured 2026-08-30, read-only, across all 17
enabled regions: **no log group anywhere had retention 90.** The three CDK-owned functions
sat at 30 (`lambda_helpers.py` set ONE_MONTH uniformly — CDK never had a security tier);
the two Lambda@Edge auth gates (`cf-auth`, `buddy-auth`) sat at 30 in the two home regions
where someone once hand-set them and at NEVER_EXPIRE in the five replica regions
(eu-west-2, eu-west-1, eu-central-1, us-east-2, us-west-1) nobody had — the never-expiring
groups holding real bytes (2.5 MB in eu-central-1) belong to the public-surface auth gate.
Nothing polices the claim: the governance retention test covers only DDB PII rows,
`check_doc_facts.py` has no retention rule, and this sentinel never read a log group.

WHY EVERY REGION, AND WHY THIS IS NOT A CDK CONSTRUCT
─────────────────────────────────────────────────────
Lambda@Edge creates its log group lazily, in whichever region served the request, named
`/aws/lambda/<home-region>.<function>`. CDK can own a log group only in a stack's own
region; owning 17 would mean 17 stacks for two functions, and a newly-served region would
still arrive at NEVER_EXPIRE until a stack existed there. CloudWatch Logs has no
account-level default-retention policy (its account policies are data-protection,
subscription-filter, field-index, transformer — not retention). So the edge half is an
idempotent writer (`deploy/apply_log_retention.py`) plus THIS check, which reads every
enabled region every week: a region that starts serving arrives at NEVER_EXPIRE and reds
within seven days, with the exact apply command in the finding. That is the mechanism the
acceptance asked to be named, honestly sized — detection-then-apply, not prevention.

THE TWO-HALF BAR (#2578 family 6, #3112)
────────────────────────────────────────
  (a) DETECT — any security-tier group, in any readable region, whose live retention is
      not the declared value (None = never expire, or a wrong number) → `drift`, each
      group named with region + live value.
  (b) CANNOT-OBSERVE — an unlistable region set (`ec2:DescribeRegions` denied), an
      unreadable region, or a sweep that found ZERO groups anywhere (the functions exist
      and log; zero is a blind sweep, the #1189 vacuous-scan shape) → `error`, never
      `clean`. Drift found in readable regions still outranks unreadable ones — an
      actionable finding is not hidden behind a partial-observation caveat.

Region enumeration is `ec2:DescribeRegions` filtered to enabled regions — the one grant
this check added to `github-actions-remediation-role` (same PR, the #2824
grant-with-consumer discipline). It is NOT the SDK's static partition list filtered by
"the call failed": a disabled opt-in region and a broken credential raise the same
error, and skipping on it is exactly the #3156 swallow-and-believe shape.

Cost: one DescribeRegions + (regions × candidate names) DescribeLogGroups reads weekly
(~120 free API calls). Read-only, no new infra.
"""

from __future__ import annotations

import os
import sys

REGION = os.environ.get("AWS_REGION", "us-west-2")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The declared side lives with the CDK constants (the TABLE_TTL_ATTRIBUTE precedent) so
# the stack, this check and the apply script cannot disagree by hand-edit.
sys.path.insert(0, os.path.join(_ROOT, "cdk"))
from stacks.constants import (  # noqa: E402
    LOG_RETENTION_SECURITY_DAYS,
    SECURITY_TIER_LOG_FUNCTIONS,
    security_tier_log_group_names,
)

REGION_ENUMERATION_GRANT = "ec2:DescribeRegions"
APPLY_COMMAND = "python3 deploy/apply_log_retention.py --apply"


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


def list_enabled_regions():
    """Every region the account can call — opt-in-not-required + opted-in. Raises on
    failure; the caller decides how loud to be."""
    ec2 = _client("ec2")
    resp = ec2.describe_regions(
        Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}],
        AllRegions=False,
    )
    return sorted(r["RegionName"] for r in resp.get("Regions", []))


def _describe_exact(logs_client, name):
    """DescribeLogGroups by prefix, matched back to the EXACT name (a prefix read of
    `/aws/lambda/life-platform-canary` would also return `...-canary-v2`)."""
    token = None
    while True:
        kwargs = {"logGroupNamePrefix": name}
        if token:
            kwargs["nextToken"] = token
        resp = logs_client.describe_log_groups(**kwargs)
        for lg in resp.get("logGroups", []):
            if lg.get("logGroupName") == name:
                return lg
        token = resp.get("nextToken")
        if not token:
            return None


def observe(regions=None):
    """The shared observation both the sentinel check and the apply script read.

    Returns {"regions": [...], "groups": [{region, log_group, function, retention_days,
    stored_bytes}], "unreadable": [{region, detail}]} — or raises if the region set
    itself cannot be enumerated (the caller reports that as cannot-observe)."""
    if regions is None:
        regions = list_enabled_regions()
    names = security_tier_log_group_names()
    groups, unreadable = [], []
    for region in regions:
        try:
            logs_client = _client("logs", region)
            for name, fn in names.items():
                lg = _describe_exact(logs_client, name)
                if lg is None:
                    continue
                groups.append(
                    {
                        "region": region,
                        "log_group": name,
                        "function": fn,
                        "retention_days": lg.get("retentionInDays"),
                        "stored_bytes": lg.get("storedBytes", 0),
                    }
                )
        except Exception as e:  # noqa: BLE001
            unreadable.append({"region": region, "detail": f"{type(e).__name__}: {e}"})
    return {"regions": list(regions), "groups": groups, "unreadable": unreadable}


def mismatches(groups, declared=LOG_RETENTION_SECURITY_DAYS):
    """Groups whose live retention is not the declared tier (None = never expires)."""
    return [
        {"region": g["region"], "log_group": g["log_group"], "live": g["retention_days"], "declared": declared}
        for g in groups
        if g.get("retention_days") != declared
    ]


def _fmt_live(v):
    return "NEVER_EXPIRE" if v is None else str(v)


def check_log_retention():
    """Every security-tier log group, in every enabled region, retains for exactly the
    days docs/DATA_GOVERNANCE.md declares (via cdk/stacks/constants.py)."""
    declared = LOG_RETENTION_SECURITY_DAYS
    try:
        obs = observe()
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "declared_days": declared,
            "detail": (
                f"cannot enumerate enabled regions ({type(e).__name__}: {e}) — the sweep needs "
                f"{REGION_ENUMERATION_GRANT} on the sentinel's role (infra/iam/"
                "github-actions-remediation-role.permissions.json, Sid Diagnose); a region-less "
                "sweep would silently miss the Lambda@Edge replica groups"
            ),
        }

    bad = mismatches(obs["groups"], declared)
    result = {
        "status": "clean",
        "declared_days": declared,
        "functions": sorted(SECURITY_TIER_LOG_FUNCTIONS),
        "regions_swept": obs["regions"],
        "groups_found": len(obs["groups"]),
        "groups": obs["groups"],
        "mismatches": bad,
        "unreadable_regions": obs["unreadable"],
    }
    unreadable_note = ""
    if obs["unreadable"]:
        unreadable_note = " (ALSO unreadable: " + ", ".join(f"{u['region']}: {u['detail']}" for u in obs["unreadable"]) + ")"

    if bad:
        result["status"] = "drift"
        named = ", ".join(f"{m['region']} {m['log_group']}={_fmt_live(m['live'])}" for m in bad)
        result["detail"] = (
            f"{len(bad)} security-tier log group(s) not at the declared {declared}d "
            f"(docs/DATA_GOVERNANCE.md): {named}. FIX: {APPLY_COMMAND}{unreadable_note}"
        )
    elif obs["unreadable"]:
        result["status"] = "error"
        result["detail"] = (
            "could not read " + ", ".join(f"{u['region']} ({u['detail']})" for u in obs["unreadable"]) + " — partial sweep is not clean"
        )
    elif not obs["groups"]:
        result["status"] = "error"
        result["detail"] = (
            f"ZERO security-tier log groups found across {len(obs['regions'])} region(s) — the functions exist and log, "
            "so an empty sweep is a blind sweep (candidate names or the region set are wrong), not a pass"
        )
    return result
