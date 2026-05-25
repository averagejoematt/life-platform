#!/usr/bin/env python3
"""
pause_wednesday_chronicle_2026_05_03.py
========================================

Pauses the Wednesday-chronicle Lambda by disabling its EventBridge schedule
rule. Without this, the Lambda would fire again at 7am PT on Wednesday May 6
and generate yet another draft from minimal data.

Discovery-first: lists candidate EventBridge rules whose name contains
"chronicle" or "wednesday" and shows their target Lambdas. Pass --apply to
disable them.

To re-enable later (when Matthew is ready to resume the weekly cadence):
    aws events enable-rule --name <RULE_NAME> --region us-west-2

Usage:
    python3 deploy/pause_wednesday_chronicle_2026_05_03.py            # dry-run / discovery
    python3 deploy/pause_wednesday_chronicle_2026_05_03.py --apply    # disable matching rules
"""
import argparse
import sys

import boto3

REGION = "us-west-2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Disable matching rules. Without this, just lists candidates.")
    parser.add_argument("--name", default=None,
                        help="Disable a specific rule by exact name (overrides discovery).")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Pause Wednesday Chronicle [{mode}] ===\n")

    events = boto3.client("events", region_name=REGION)

    # ── Discovery: find matching rules ──────────────────────────────────────
    candidates = []

    if args.name:
        # Specific rule mode
        try:
            r = events.describe_rule(Name=args.name)
            candidates.append(r)
        except Exception as e:
            print(f"ERROR: rule '{args.name}' not found: {e}")
            return 1
    else:
        # Discovery mode: list all rules and filter by name keywords
        print("Discovery: scanning EventBridge rules...")
        paginator = events.get_paginator("list_rules")
        for page in paginator.paginate():
            for rule in page.get("Rules", []):
                name = rule.get("Name", "").lower()
                if "chronicle" in name or "wednesday" in name:
                    candidates.append(rule)

        if not candidates:
            print("  No EventBridge rules matched 'chronicle' or 'wednesday'.")
            print()
            print("  Try listing all schedule rules manually:")
            print("    aws events list-rules --region us-west-2 \\")
            print("      --query 'Rules[?ScheduleExpression!=null].[Name, ScheduleExpression, State]'")
            print()
            print("  Then re-run with: --name <RULE_NAME>")
            return 0

    # ── Show candidates with their targets ──────────────────────────────────
    print(f"Found {len(candidates)} candidate rule(s):\n")
    actionable = []
    for r in candidates:
        name     = r.get("Name", "?")
        state    = r.get("State", "?")
        schedule = r.get("ScheduleExpression", "(no schedule)")
        arn      = r.get("Arn", "?")

        print(f"  • {name}")
        print(f"      State:    {state}")
        print(f"      Schedule: {schedule}")
        print(f"      ARN:      {arn}")

        # List targets
        try:
            tresp = events.list_targets_by_rule(Rule=name)
            targets = tresp.get("Targets", [])
            for t in targets:
                t_arn = t.get("Arn", "")
                print(f"      Target:   {t_arn}")
        except Exception as e:
            print(f"      Target query failed: {e}")

        if state == "ENABLED":
            actionable.append(name)
        print()

    if not actionable:
        print("✓ No ENABLED rules to pause. Nothing to do.")
        return 0

    print(f"Will disable {len(actionable)} rule(s): {', '.join(actionable)}")
    print()

    if not args.apply:
        print("DRY-RUN — pass --apply to disable the rules above.")
        return 0

    # ── Execute ─────────────────────────────────────────────────────────────
    print("=" * 60)
    print("DISABLING...")
    print()
    failures = 0
    for name in actionable:
        try:
            events.disable_rule(Name=name)
            print(f"  ✓ Disabled: {name}")
        except Exception as e:
            print(f"  ✗ Failed to disable {name}: {e}")
            failures += 1

    print()
    print("=" * 60)
    if failures:
        print(f"DONE WITH ERRORS ({failures} failure(s))")
        return 4
    print("DONE")
    print()
    print("To resume later:")
    for name in actionable:
        print(f"  aws events enable-rule --name {name} --region {REGION}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
