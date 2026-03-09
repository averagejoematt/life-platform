#!/usr/bin/env python3
"""
p1_migrate_eventbridge_scheduler.py — P1.6: EventBridge Rules → EventBridge Scheduler

Migrates all Lambda schedules to EventBridge Scheduler with America/Los_Angeles
timezone so DST transitions are handled automatically.

Usage: cd ~/Documents/Claude/life-platform && python3 deploy/p1_migrate_eventbridge_scheduler.py
"""

import boto3
import json
import sys
import time

REGION = "us-west-2"
ACCOUNT = "205930651321"
TZ = "America/Los_Angeles"
GROUP = "life-platform"
LAMBDA_PREFIX = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function"
SCHEDULER_ROLE = "life-platform-scheduler-role"
SCHEDULER_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{SCHEDULER_ROLE}"

iam = boto3.client("iam", region_name=REGION)
scheduler = boto3.client("scheduler", region_name=REGION)
events = boto3.client("events", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)

# ---------------------------------------------------------------------------
# Schedules: (name, cron, function_name, payload_dict_or_None)
# cron format for Scheduler: minute hour dom month dow year
# ---------------------------------------------------------------------------
SCHEDULES = [
    # Ingestion — daily
    ("whoop-ingestion",           "0 6 * * ? *",   "whoop-data-ingestion",           None),
    ("garmin-ingestion",          "0 6 * * ? *",   "garmin-data-ingestion",           None),
    ("notion-journal-ingestion",  "0 6 * * ? *",   "notion-journal-ingestion",        None),
    ("withings-ingestion",        "15 6 * * ? *",  "withings-data-ingestion",         None),
    ("habitify-ingestion",        "15 6 * * ? *",  "habitify-data-ingestion",         None),
    ("strava-ingestion",          "30 6 * * ? *",  "strava-data-ingestion",           None),
    ("journal-enrichment",        "30 6 * * ? *",  "journal-enrichment",              None),
    ("todoist-ingestion",         "45 6 * * ? *",  "todoist-data-ingestion",          None),
    ("eightsleep-ingestion",      "0 7 * * ? *",   "eightsleep-data-ingestion",       None),
    ("activity-enrichment",       "30 7 * * ? *",  "activity-enrichment",             None),
    ("macrofactor-ingestion",     "0 8 * * ? *",   "macrofactor-data-ingestion",      None),
    ("anomaly-detector",          "5 8 * * ? *",   "anomaly-detector",                None),
    ("mcp-cache-warmer",          "0 9 * * ? *",   "life-platform-mcp",               {"action": "warm_cache"}),
    ("whoop-recovery-refresh",    "30 9 * * ? *",  "whoop-data-ingestion",            {"date_override": "today"}),
    ("character-sheet-compute",   "35 9 * * ? *",  "character-sheet-compute",         None),
    ("freshness-checker",         "45 9 * * ? *",  "life-platform-freshness-checker", None),
    ("daily-brief",               "0 10 * * ? *",  "daily-brief",                     None),
    # Dashboard refresh
    ("dashboard-refresh-afternoon", "0 14 * * ? *", "dashboard-refresh",             None),
    ("dashboard-refresh-evening",   "0 18 * * ? *", "dashboard-refresh",             None),
    # Weekly emails
    ("monday-compass",            "0 8 ? * MON *", "monday-compass",                  None),
    ("wednesday-chronicle",       "0 7 ? * WED *", "wednesday-chronicle",             None),
    ("weekly-plate",              "0 19 ? * FRI *", "weekly-plate",                   None),
    ("nutrition-review",          "0 9 ? * SAT *", "nutrition-review",                None),
    ("weekly-digest",             "0 8 ? * SUN *", "weekly-digest",                   None),
    # Monthly digest — 1st of month; Lambda guards for Monday
    ("monthly-digest",            "0 9 1 * ? *",   "monthly-digest",                  None),
    # Dropbox poll — every 30 min
    ("dropbox-poll",              "0/30 * * * ? *", "dropbox-poll",                   None),
]


def banner(msg):
    print(f"\n── {msg} ──")


def step1_ensure_role():
    banner("Step 1: Scheduler IAM role")
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}},
        }]
    }
    invoke = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "InvokeLambda",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:*",
        }]
    }
    try:
        iam.get_role(RoleName=SCHEDULER_ROLE)
        iam.update_assume_role_policy(
            RoleName=SCHEDULER_ROLE,
            PolicyDocument=json.dumps(trust),
        )
        print(f"  ✅ Role exists — trust policy refreshed")
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(
            RoleName=SCHEDULER_ROLE,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="EventBridge Scheduler role for Life Platform Lambda invocations",
        )
        iam.put_role_policy(
            RoleName=SCHEDULER_ROLE,
            PolicyName="invoke-lambda",
            PolicyDocument=json.dumps(invoke),
        )
        print(f"  ✅ Role created")
        print("  Waiting 10s for IAM propagation...")
        time.sleep(10)


def step2_ensure_group():
    banner("Step 2: Scheduler group")
    try:
        scheduler.create_schedule_group(Name=GROUP)
        print(f"  ✅ Group created: {GROUP}")
    except scheduler.exceptions.ConflictException:
        print(f"  ✅ Group already exists: {GROUP}")


def upsert_schedule(name, cron, fn_name, payload):
    fn_arn = f"{LAMBDA_PREFIX}:{fn_name}"
    input_str = json.dumps(payload) if payload is not None else "{}"
    target = {
        "Arn": fn_arn,
        "RoleArn": SCHEDULER_ROLE_ARN,
        "Input": input_str,
    }
    kwargs = dict(
        GroupName=GROUP,
        Name=name,
        ScheduleExpression=f"cron({cron})",
        ScheduleExpressionTimezone=TZ,
        FlexibleTimeWindow={"Mode": "OFF"},
        Target=target,
        State="ENABLED",
    )
    try:
        scheduler.get_schedule(GroupName=GROUP, Name=name)
        scheduler.update_schedule(**kwargs)
        print(f"  {name} ({fn_name} @ {cron}) ... updated ✅")
    except scheduler.exceptions.ResourceNotFoundException:
        scheduler.create_schedule(**kwargs)
        print(f"  {name} ({fn_name} @ {cron}) ... created ✅")


def step3_create_schedules():
    banner("Step 3: Creating schedules (America/Los_Angeles)")
    print()
    sections = [
        ("Ingestion — daily", SCHEDULES[:17]),
        ("Dashboard refresh", SCHEDULES[17:19]),
        ("Weekly emails", SCHEDULES[19:24]),
        ("Monthly digest", SCHEDULES[24:25]),
        ("Dropbox poll", SCHEDULES[25:]),
    ]
    for section_name, items in sections:
        print(f"  [{section_name}]")
        for name, cron, fn, payload in items:
            upsert_schedule(name, cron, fn, payload)
        print()


def step4_disable_old_rules():
    banner("Step 4: Disabling old EventBridge rules (not deleting)")
    paginator = events.get_paginator("list_rules")
    disabled = 0
    for page in paginator.paginate():
        for rule in page["Rules"]:
            rule_name = rule["Name"]
            try:
                targets = events.list_targets_by_rule(Rule=rule_name)["Targets"]
                for t in targets:
                    if f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:" in t.get("Arn", ""):
                        print(f"  Disabling: {rule_name} ... ", end="", flush=True)
                        events.disable_rule(Name=rule_name)
                        print("✅")
                        disabled += 1
                        break
            except Exception as e:
                print(f"  ⚠️  {rule_name}: {e}")
    if disabled == 0:
        print("  No Lambda-targeting rules found (already migrated or none exist)")


def step5_verify():
    banner("Step 5: Verification")
    resp = scheduler.list_schedules(GroupName=GROUP)
    schedules = resp.get("Schedules", [])
    print(f"  Schedules in group '{GROUP}': {len(schedules)}")


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  P1.6: EventBridge → Scheduler (IANA timezone, DST-safe)   ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    step1_ensure_role()
    step2_ensure_group()
    step3_create_schedules()
    step4_disable_old_rules()
    step5_verify()

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  ✅ P1.6 Migration Complete                                 ║")
    print("║                                                              ║")
    print("║  All schedules now run on America/Los_Angeles timezone       ║")
    print("║  DST transitions handled automatically — no manual scripts  ║")
    print("║                                                              ║")
    print("║  Rollback: aws events enable-rule --name <rule>             ║")
    print("╚══════════════════════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
