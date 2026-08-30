#!/usr/bin/env python3
"""
deploy/teardown_orphan_export_rule.py — retire the orphan monthly-export rule (#3279).

`life-platform-monthly-export` (`cron(0 11 1 * ? *)`, ENABLED, ZERO targets, no
CloudFormation owner, no tags — measured live 2026-08-29) asserts a data-export
schedule that three sources of truth agree should not exist:
`cdk/stacks/operational_stack.py` ("life-platform-data-export  (on-demand only)"),
`docs/DATA_GOVERNANCE.md` §Export, and — since #3279 — the Lambda's own docstring.
Its `lambda:InvokeFunction` resource-policy statement (`Sid: monthly-export-eventbridge`)
is still live on `life-platform-data-export`, so a console-re-added target would fire a
monthly export with no review. The recorded decision (#3279): DELETE, not adopt —
the on-demand design was affirmed and the data-loss framing refuted in the issue body.

This script (mirrors deploy/teardown_hae_orphan_api.py, #1946):
  1. Describes the rule and lists its targets. A rule that has GROWN a target since
     the 2026-08-29 measurement means the premise changed — it refuses without
     --force rather than deleting something that now does work.
  2. Deletes the rule (`--apply` only; remove_targets first if --force'd past 1).
  3. Revokes every `events.amazonaws.com` invoke statement on
     `life-platform-data-export` whose SourceArn references the rule (matched by
     ARN, not only the known Sid — guard-the-SET), plus the known
     `monthly-export-eventbridge` Sid if present.

Idempotent: after a successful --apply (or if someone already cleaned up), re-running
reports "already gone" for each half and exits 0.

Usage:
    python3 deploy/teardown_orphan_export_rule.py           # dry-run (default): prints, deletes nothing
    python3 deploy/teardown_orphan_export_rule.py --apply   # actually delete
    python3 deploy/teardown_orphan_export_rule.py --apply --force  # delete even if targets exist (NOT recommended)

Verification after --apply:
    python3 deploy/drift_sentinel.py --no-write   # eventbridge_rules must report clean

This is an AWS-mutating script — run it attended, by the driver, from main after merge
(CLAUDE.md: "Deploys happen from main, by the driver, after merge"), never from a
worktree branch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sentinel_events import DATA_EXPORT_FUNCTION, ORPHAN_EXPORT_RULE, ORPHAN_EXPORT_SID  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


def _is_not_found(e):
    return "ResourceNotFoundException" in type(e).__name__ or "ResourceNotFoundException" in str(e)


def describe_orphan_rule(ev=None):
    """The live rule dict, or None if already gone (idempotent half 1)."""
    ev = ev or _client("events")
    try:
        return ev.describe_rule(Name=ORPHAN_EXPORT_RULE)
    except Exception as e:  # noqa: BLE001
        if _is_not_found(e):
            return None
        raise


def find_orphan_invoke_grants(lam=None):
    """Every events.amazonaws.com invoke statement on the export Lambda that names the
    orphan rule in its SourceArn OR carries the known Sid. Fail-soft to [] when the
    function has no resource policy at all (nothing to revoke)."""
    lam = lam or _client("lambda")
    try:
        policy = json.loads(lam.get_policy(FunctionName=DATA_EXPORT_FUNCTION)["Policy"])
    except Exception as e:  # noqa: BLE001
        if _is_not_found(e):
            return []
        raise
    hits = []
    for stmt in policy.get("Statement", []):
        principal = stmt.get("Principal") or {}
        if principal.get("Service") != "events.amazonaws.com":
            continue
        source_arn = ((stmt.get("Condition") or {}).get("ArnLike") or {}).get("AWS:SourceArn", "")
        if stmt.get("Sid") == ORPHAN_EXPORT_SID or source_arn.endswith(f":rule/{ORPHAN_EXPORT_RULE}"):
            hits.append({"sid": stmt.get("Sid"), "source_arn": source_arn})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run, deletes nothing)")
    ap.add_argument("--force", action="store_true", help="delete even if the rule has grown targets (NOT recommended)")
    args = ap.parse_args()

    print("life-platform orphan monthly-export rule teardown (#3279)")
    print(f"region={REGION}  mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    ev = _client("events")
    exit_code = 0

    rule = describe_orphan_rule(ev)
    if rule is None:
        print(f"rule {ORPHAN_EXPORT_RULE}: already gone (idempotent no-op)")
    else:
        print(f"rule {ORPHAN_EXPORT_RULE}: state={rule.get('State')} schedule={rule.get('ScheduleExpression')}")
        targets = ev.list_targets_by_rule(Rule=ORPHAN_EXPORT_RULE).get("Targets", [])
        print(f"  targets: {len(targets)}")
        if targets and not args.force:
            print("  REFUSE: the rule has target(s) now — it was targetless when #3279 ruled DELETE.")
            print("          Someone re-armed it; re-decide (adopt into CDK, or --force) before deleting.")
            return 1
        if not args.apply:
            print(f"  (dry-run) would delete rule {ORPHAN_EXPORT_RULE}")
        else:
            try:
                if targets:
                    ev.remove_targets(Rule=ORPHAN_EXPORT_RULE, Ids=[t["Id"] for t in targets])
                    print(f"  removed {len(targets)} target(s)")
                ev.delete_rule(Name=ORPHAN_EXPORT_RULE)
                print(f"  deleted rule {ORPHAN_EXPORT_RULE}")
            except Exception as e:  # noqa: BLE001
                if _is_not_found(e):
                    print(f"  rule {ORPHAN_EXPORT_RULE} already gone (idempotent no-op)")
                else:
                    print(f"  ERROR deleting rule: {e}")
                    exit_code = 1

    grants = find_orphan_invoke_grants()
    if not grants:
        print(f"invoke grant on {DATA_EXPORT_FUNCTION}: none referencing the rule (idempotent no-op)")
    else:
        for g in grants:
            print(f"invoke grant on {DATA_EXPORT_FUNCTION}: sid={g['sid']} source_arn={g['source_arn']}")
            if not args.apply:
                print("  (dry-run) would revoke")
                continue
            lam = _client("lambda")
            try:
                lam.remove_permission(FunctionName=DATA_EXPORT_FUNCTION, StatementId=g["sid"])
                print(f"  revoked {g['sid']}")
            except Exception as e:  # noqa: BLE001
                if _is_not_found(e):
                    print(f"  {g['sid']} already gone (idempotent no-op)")
                else:
                    print(f"  ERROR revoking {g['sid']}: {e}")
                    exit_code = 1

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to execute.")
    print("NEXT after --apply: python3 deploy/drift_sentinel.py --no-write   (eventbridge_rules must report clean)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
