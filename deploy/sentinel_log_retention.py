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

THE SECOND LEG (#3507): THE WHOLE ESTATE, NOT FIVE DECLARED NAMES
─────────────────────────────────────────────────────────────────
The leg above reads five hand-declared function names. That is exactly right for the
security TIER (those five have a stricter promise than everything else), and exactly
wrong as the sweep's whole reach: a log group that belongs to no declared name is
invisible to it, so the check that exists to catch a region-stray group could not catch
one. Measured 2026-09-05: `/aws/lambda/life-platform-site-api` in **us-east-1** — created
2026-03-16, last event 2026-03-21, 128,854 stored bytes, `retentionInDays` absent, and
`aws lambda get-function --region us-east-1 life-platform-site-api` →
ResourceNotFoundException. An orphan of a March deployment attempt, retained forever,
while `drift-log/latest.json` recorded `log_retention: {status: clean, groups_found: 17}`.
It is 128 KB; the CLASS is that a sweep scoped to a hand-typed list reports clean about a
population it never looked at.

So `observe()` now enumerates the FULL log-group estate in every swept region (one
paginated `DescribeLogGroups` per region, no prefix — fewer API calls than the 5×17
prefix reads it replaces) and the check reports TWO legs:

  (a) SECURITY TIER — declared-vs-live on the five names, unchanged.
  (b) ESTATE RETENTION — any group anywhere with `retentionInDays == null`, minus
      `UNBOUNDED_RETENTION_ALLOWLIST`, which requires a reason and a date per entry. An
      allowlist entry is an argued position; being absent from a list is not.

Live baseline 2026-09-05, 17 enabled regions: 137 groups total (us-west-2 121, us-east-1 6,
and 2 each in eu-central-1/eu-west-1/eu-west-2/us-east-2/us-west-1), of which exactly one
is unbounded — the us-east-1 orphan above.

Cost: one DescribeRegions + one paginated DescribeLogGroups per region weekly
(~20 free API calls, down from ~85). Read-only, no new infra.
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

# #3507: log groups that are DELIBERATELY unbounded. Every entry carries a reason and a
# date, because the defect this leg fixes is precisely "it wasn't in the list" — an
# exemption has to be an argued position with an author, not an omission nobody chose.
# Empty is the correct steady state: the platform's declared posture is that every log
# group has a retention policy. The one live unbounded group (the us-east-1
# `/aws/lambda/life-platform-site-api` orphan) is deliberately NOT here — it is a finding.
UNBOUNDED_RETENTION_ALLOWLIST: dict[str, dict] = {}

ESTATE_FIX_HINT = (
    "delete the group if it is an orphan (`aws logs delete-log-group --region <r> --log-group-name <n>`) "
    "or give it a policy (`aws logs put-retention-policy --region <r> --log-group-name <n> "
    "--retention-in-days 30`); if it is deliberately unbounded, add it to "
    "sentinel_log_retention.UNBOUNDED_RETENTION_ALLOWLIST with a reason and a date"
)


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


def _describe_all(logs_client):
    """Every log group in one region, paginated. #3507: the sweep enumerates the estate
    rather than asking about five names it already knows — a prefix read can only ever
    confirm what the caller already suspected exists."""
    out = []
    token = None
    while True:
        kwargs = {"nextToken": token} if token else {}
        resp = logs_client.describe_log_groups(**kwargs)
        out.extend(resp.get("logGroups", []) or [])
        token = resp.get("nextToken")
        if not token:
            return out


def observe(regions=None):
    """The shared observation both the sentinel check and the apply script read.

    Returns {"regions": [...], "groups": [...security-tier only...], "all_groups":
    [{region, log_group, retention_days, stored_bytes}] for the FULL estate,
    "unreadable": [{region, detail}]} — or raises if the region set itself cannot be
    enumerated (the caller reports that as cannot-observe).

    `groups` keeps the security-tier shape (with `function`) because
    `deploy/apply_log_retention.py` writes exactly that set; `all_groups` is the #3507
    estate the second leg judges."""
    if regions is None:
        regions = list_enabled_regions()
    names = security_tier_log_group_names()
    groups, all_groups, unreadable = [], [], []
    for region in regions:
        try:
            live = _describe_all(_client("logs", region))
        except Exception as e:  # noqa: BLE001
            unreadable.append({"region": region, "detail": f"{type(e).__name__}: {e}"})
            continue
        for lg in live:
            name = lg.get("logGroupName") or ""
            row = {
                "region": region,
                "log_group": name,
                "retention_days": lg.get("retentionInDays"),
                "stored_bytes": lg.get("storedBytes", 0),
            }
            all_groups.append(row)
            if name in names:  # EXACT match: `...-canary-v2` is not `...-canary`
                groups.append({**row, "function": names[name]})
    return {"regions": list(regions), "groups": groups, "all_groups": all_groups, "unreadable": unreadable}


def unbounded_groups(all_groups, allowlist=None):
    """Every estate group with no retention policy, minus the allowlist (#3507).

    Pure, so the positive control can plant one unbounded group in a second region and
    watch the leg red without touching AWS."""
    allowed = UNBOUNDED_RETENTION_ALLOWLIST if allowlist is None else allowlist
    return [g for g in all_groups if g.get("retention_days") is None and g.get("log_group") not in allowed]


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
    unbounded = unbounded_groups(obs["all_groups"])
    result = {
        "status": "clean",
        "declared_days": declared,
        "functions": sorted(SECURITY_TIER_LOG_FUNCTIONS),
        "regions_swept": obs["regions"],
        # #3507: `groups_found` is now what the sweep ACTUALLY looked at — the whole
        # estate. The old value (the five declared names) is kept beside it, named for
        # what it is, so a record can never again report "clean, 17 groups" about a
        # population of 137.
        "groups_found": len(obs["all_groups"]),
        "security_tier_groups_found": len(obs["groups"]),
        "groups": obs["groups"],
        "mismatches": bad,
        "unbounded_groups": unbounded,
        "allowlisted_unbounded": sorted(UNBOUNDED_RETENTION_ALLOWLIST),
        "unreadable_regions": obs["unreadable"],
    }
    unreadable_note = ""
    if obs["unreadable"]:
        unreadable_note = " (ALSO unreadable: " + ", ".join(f"{u['region']}: {u['detail']}" for u in obs["unreadable"]) + ")"

    details = []
    if bad:
        named = ", ".join(f"{m['region']} {m['log_group']}={_fmt_live(m['live'])}" for m in bad)
        details.append(
            f"{len(bad)} security-tier log group(s) not at the declared {declared}d "
            f"(docs/DATA_GOVERNANCE.md): {named}. FIX: {APPLY_COMMAND}"
        )
    if unbounded:
        named = ", ".join(f"{g['region']} {g['log_group']} ({g['stored_bytes']} bytes)" for g in unbounded[:10])
        more = "" if len(unbounded) <= 10 else f" (+{len(unbounded) - 10} more)"
        details.append(
            f"{len(unbounded)} log group(s) of {len(obs['all_groups'])} have NO retention policy "
            f"(retained forever): {named}{more}. FIX: {ESTATE_FIX_HINT}"
        )

    if details:
        result["status"] = "drift"
        result["detail"] = " | ".join(details) + unreadable_note
    elif obs["unreadable"]:
        result["status"] = "error"
        result["detail"] = (
            "could not read " + ", ".join(f"{u['region']} ({u['detail']})" for u in obs["unreadable"]) + " — partial sweep is not clean"
        )
    elif not obs["all_groups"]:
        result["status"] = "error"
        result["detail"] = (
            f"ZERO log groups found across {len(obs['regions'])} region(s) — every Lambda on the platform logs, "
            "so an empty sweep is a blind sweep (the region set or the read is wrong), not a pass"
        )
    elif not obs["groups"]:
        result["status"] = "error"
        result["detail"] = (
            f"ZERO security-tier log groups found across {len(obs['regions'])} region(s) (of "
            f"{len(obs['all_groups'])} groups seen) — the functions exist and log, "
            "so an empty tier sweep is a blind sweep (candidate names are wrong), not a pass"
        )
    return result
