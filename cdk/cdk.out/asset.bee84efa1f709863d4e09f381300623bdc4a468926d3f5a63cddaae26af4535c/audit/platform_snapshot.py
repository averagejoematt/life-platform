#!/usr/bin/env python3
"""
Platform Snapshot — Data gatherer for weekly reviews.

Runs OUTSIDE the platform (locally or as a scheduled Lambda).
Discovers everything via AWS APIs + filesystem — no hardcoded lists.
Outputs structured JSON to audit/YYYY-MM-DD.json.

Usage:
  python3 audit/platform_snapshot.py                  # writes audit/YYYY-MM-DD.json
  python3 audit/platform_snapshot.py --output /tmp/x  # custom output path
  python3 audit/platform_snapshot.py --dry-run         # print to stdout

Requires: boto3, local AWS credentials with read-only access
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

# ── Config ──
REGION = "us-west-2"
TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
USER_ID = "matthew"
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PLATFORM_ROOT = Path(__file__).parent.parent  # life-platform/
DOCS_DIR = PLATFORM_ROOT / "docs"
MCP_DIR = PLATFORM_ROOT / "mcp"

# AWS clients
lambdac = boto3.client("lambda", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)
logs = boto3.client("logs", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)
ddb_resource = boto3.resource("dynamodb", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
sm = boto3.client("secretsmanager", region_name=REGION)
ce = boto3.client("ce", region_name=REGION)
events = boto3.client("events", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)


def gather_lambdas():
    """Discover all Lambda functions with life-platform-related names."""
    paginator = lambdac.get_paginator("list_functions")
    functions = []
    for page in paginator.paginate():
        for fn in page["Functions"]:
            functions.append({
                "name": fn["FunctionName"],
                "runtime": fn.get("Runtime", "unknown"),
                "memory_mb": fn["MemorySize"],
                "timeout_s": fn["Timeout"],
                "handler": fn["Handler"],
                "code_size_bytes": fn["CodeSize"],
                "last_modified": fn["LastModified"],
                "reserved_concurrency": None,  # filled below
            })

    # Get reserved concurrency for each
    for fn in functions:
        try:
            resp = lambdac.get_function_concurrency(FunctionName=fn["name"])
            fn["reserved_concurrency"] = resp.get("ReservedConcurrentExecutions")
        except lambdac.exceptions.ResourceNotFoundException:
            fn["reserved_concurrency"] = None
        except Exception:
            fn["reserved_concurrency"] = None

    return functions


def gather_alarms():
    """All CloudWatch alarms with state, dimensions, and actions."""
    paginator = cw.get_paginator("describe_alarms")
    alarms = []
    for page in paginator.paginate():
        for a in page.get("MetricAlarms", []):
            dims = {d["Name"]: d["Value"] for d in a.get("Dimensions", [])}
            alarms.append({
                "name": a["AlarmName"],
                "state": a["StateValue"],
                "metric": a["MetricName"],
                "namespace": a["Namespace"],
                "dimensions": dims,
                "period_s": a["Period"],
                "threshold": float(a["Threshold"]),
                "actions": a.get("AlarmActions", []),
            })
    return alarms


def gather_log_groups():
    """All Lambda log groups with retention and size."""
    paginator = logs.get_paginator("describe_log_groups")
    groups = []
    for page in paginator.paginate(logGroupNamePrefix="/aws/lambda/"):
        for lg in page.get("logGroups", []):
            groups.append({
                "name": lg["logGroupName"],
                "retention_days": lg.get("retentionInDays"),  # None = infinite
                "stored_bytes": lg.get("storedBytes", 0),
            })
    return groups


def gather_dlq():
    """DLQ message counts."""
    dlqs = []
    try:
        resp = sqs.list_queues(QueueNamePrefix="life-platform")
        for url in resp.get("QueueUrls", []):
            attrs = sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
            )["Attributes"]
            dlqs.append({
                "queue_url": url,
                "queue_name": url.split("/")[-1],
                "messages_available": int(attrs.get("ApproximateNumberOfMessages", 0)),
                "messages_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            })
    except Exception as e:
        dlqs.append({"error": str(e)})
    return dlqs


def gather_dynamodb():
    """Table-level stats + source partition discovery."""
    desc = ddb.describe_table(TableName=TABLE_NAME)["Table"]
    table_info = {
        "item_count": desc.get("ItemCount", 0),
        "size_bytes": desc.get("TableSizeBytes", 0),
        "billing_mode": desc.get("BillingModeSummary", {}).get("BillingMode", "UNKNOWN"),
        "deletion_protection": desc.get("DeletionProtectionEnabled", False),
        "pitr_enabled": False,
        "gsi_count": len(desc.get("GlobalSecondaryIndexes", [])),
    }

    # PITR status
    try:
        pitr = ddb.describe_continuous_backups(TableName=TABLE_NAME)
        status = pitr["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"]
        table_info["pitr_enabled"] = status == "ENABLED"
    except Exception:
        pass

    # Discover all source partitions — full paginated scan
    table = ddb_resource.Table(TABLE_NAME)
    sources = set()

    try:
        scan_kwargs = {
            "ProjectionExpression": "pk",
            "FilterExpression": "begins_with(pk, :prefix)",
            "ExpressionAttributeValues": {":prefix": USER_PREFIX},
        }
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get("Items", []):
                pk = item.get("pk", "")
                if pk.startswith(USER_PREFIX):
                    source = pk.replace(USER_PREFIX, "")
                    sources.add(source)
            # Paginate until no more pages
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
    except Exception as e:
        sources = {f"error: {e}"}

    # Get record counts per source (sample — just check if data exists)
    source_stats = {}
    for src in sorted(sources):
        try:
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": USER_PREFIX + src,
                    ":prefix": "DATE#",
                },
                Select="COUNT",
            )
            source_stats[src] = resp.get("Count", 0)
        except Exception:
            source_stats[src] = -1

    return {
        "table": table_info,
        "sources_discovered": sorted(sources),
        "source_record_counts": source_stats,
    }


def gather_cost():
    """Current month and last month AWS cost."""
    today = datetime.now(timezone.utc)
    first_of_month = today.replace(day=1)
    last_month_start = (first_of_month - timedelta(days=1)).replace(day=1)

    costs = {}
    for label, start, end in [
        ("current_month", first_of_month.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
        ("last_month", last_month_start.strftime("%Y-%m-%d"), first_of_month.strftime("%Y-%m-%d")),
    ]:
        try:
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            services = {}
            for group in resp.get("ResultsByTime", [{}])[0].get("Groups", []):
                svc = group["Keys"][0]
                amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if amt > 0.001:
                    services[svc] = round(amt, 4)
            costs[label] = {
                "period": f"{start} to {end}",
                "services": services,
                "total": round(sum(services.values()), 4),
            }
        except Exception as e:
            costs[label] = {"error": str(e)}

    return costs


def gather_secrets():
    """Count of Secrets Manager secrets."""
    count = 0
    try:
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate():
            count += len(page.get("SecretList", []))
    except Exception:
        return {"count": -1}
    return {"count": count}


def gather_eventbridge():
    """EventBridge rules related to life-platform."""
    rules = []
    try:
        resp = events.list_rules(NamePrefix="life-platform")
        for r in resp.get("Rules", []):
            rules.append({
                "name": r["Name"],
                "state": r["State"],
                "schedule": r.get("ScheduleExpression", ""),
            })
        # Also check for non-prefixed rules targeting our lambdas
        resp2 = events.list_rules()
        for r in resp2.get("Rules", []):
            if r["Name"] not in [x["name"] for x in rules]:
                # Check if it targets one of our lambdas
                try:
                    targets = events.list_targets_by_rule(Rule=r["Name"]).get("Targets", [])
                    for t in targets:
                        arn = t.get("Arn", "")
                        if "life-platform" in arn or any(
                            kw in arn for kw in [
                                "daily-brief", "weekly-digest", "monthly-digest",
                                "anomaly-detector", "freshness-checker", "whoop",
                                "strava", "garmin", "eightsleep", "habitify",
                                "withings", "todoist", "notion", "macrofactor",
                                "dropbox-poll", "weather", "enrichment", "mcp",
                                "apple-health", "insight-email",
                                "wednesday-chronicle", "weekly-plate",
                                "adaptive-mode-compute", "character-sheet-compute",
                                "nutrition-review", "dashboard-refresh",
                            ]
                        ):
                            rules.append({
                                "name": r["Name"],
                                "state": r["State"],
                                "schedule": r.get("ScheduleExpression", ""),
                            })
                            break
                except Exception:
                    pass
    except Exception as e:
        rules.append({"error": str(e)})
    return rules


def gather_mcp_config():
    """Read MCP config.py for version, SOURCES, SOT."""
    config_path = MCP_DIR / "config.py"
    result = {"file_exists": False}

    if not config_path.exists():
        return result

    result["file_exists"] = True
    content = config_path.read_text()

    # Extract version
    for line in content.splitlines():
        if line.strip().startswith("__version__"):
            result["version"] = line.split("=")[1].strip().strip('"').strip("'")
        if line.strip().startswith("SOURCES"):
            # Parse the list
            try:
                import ast
                idx = content.index("SOURCES")
                # Find the full assignment
                rest = content[idx:]
                eq_idx = rest.index("=")
                bracket_start = rest.index("[", eq_idx)
                bracket_end = rest.index("]", bracket_start)
                sources_str = rest[bracket_start:bracket_end + 1]
                result["sources_list"] = ast.literal_eval(sources_str)
            except Exception:
                result["sources_list"] = "parse_error"

    # Extract SOT keys
    if "_DEFAULT_SOURCE_OF_TRUTH" in content:
        try:
            import ast
            idx = content.index("_DEFAULT_SOURCE_OF_TRUTH")
            rest = content[idx:]
            eq_idx = rest.index("=")
            brace_start = rest.index("{", eq_idx)
            # Find matching closing brace
            depth = 0
            for i, c in enumerate(rest[brace_start:], brace_start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        brace_end = i
                        break
            sot_str = rest[brace_start:brace_end + 1]
            result["sot_domains"] = list(ast.literal_eval(sot_str).keys())
        except Exception:
            result["sot_domains"] = "parse_error"

    # Count tool modules
    if MCP_DIR.exists():
        modules = [f.name for f in MCP_DIR.iterdir() if f.name.startswith("tools_") and f.suffix == ".py"]
        result["tool_modules"] = sorted(modules)
        result["tool_module_count"] = len(modules)

    return result


def gather_docs():
    """Doc inventory with modification times and version detection."""
    docs = []
    if not DOCS_DIR.exists():
        return docs

    for f in sorted(DOCS_DIR.iterdir()):
        if f.is_file() and f.suffix == ".md":
            stat = f.stat()
            content_head = ""
            version_in_doc = None
            try:
                with open(f, "r") as fh:
                    lines = fh.readlines()[:10]
                    content_head = "".join(lines)
                    for line in lines:
                        # Look for version patterns
                        if "v2." in line.lower() or "version" in line.lower():
                            import re
                            match = re.search(r"v?2\.\d+\.\d+", line)
                            if match:
                                version_in_doc = match.group()
                                if not version_in_doc.startswith("v"):
                                    version_in_doc = "v" + version_in_doc
                                break
            except Exception:
                pass

            docs.append({
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "version_detected": version_in_doc,
            })

    return docs


def gather_changelog_version():
    """Extract latest version from CHANGELOG.md."""
    changelog = DOCS_DIR / "CHANGELOG.md"
    if not changelog.exists():
        return None
    try:
        import re
        with open(changelog) as f:
            for line in f:
                match = re.search(r"## v(\d+\.\d+\.\d+)", line)
                if match:
                    return "v" + match.group(1)
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Life Platform snapshot for weekly reviews")
    parser.add_argument("--output", type=str, help="Output file path (default: audit/YYYY-MM-DD.json)")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    snapshot = {
        "snapshot_version": "1.0.0",
        "generated_at": now.isoformat(),
        "generated_date": now.strftime("%Y-%m-%d"),
    }

    sections = [
        ("lambdas", "Lambda inventory", gather_lambdas),
        ("alarms", "CloudWatch alarms", gather_alarms),
        ("log_groups", "CloudWatch log groups", gather_log_groups),
        ("dlq", "Dead letter queues", gather_dlq),
        ("dynamodb", "DynamoDB table + sources", gather_dynamodb),
        ("cost", "AWS cost (current + last month)", gather_cost),
        ("secrets", "Secrets Manager", gather_secrets),
        ("eventbridge", "EventBridge rules", gather_eventbridge),
        ("mcp_config", "MCP config.py state", gather_mcp_config),
        ("docs", "Documentation inventory", gather_docs),
        ("changelog_version", "Latest changelog version", gather_changelog_version),
    ]

    for key, label, fn in sections:
        print(f"  Gathering {label}...", end=" ", flush=True)
        t0 = time.time()
        try:
            snapshot[key] = fn()
            elapsed = time.time() - t0
            print(f"✅ ({elapsed:.1f}s)")
        except Exception as e:
            snapshot[key] = {"error": str(e)}
            print(f"❌ ({e})")

    # Summary stats
    snapshot["summary"] = {
        "lambda_count": len(snapshot.get("lambdas", [])),
        "alarm_count": len(snapshot.get("alarms", [])),
        "log_groups_without_retention": sum(
            1 for lg in snapshot.get("log_groups", []) if lg.get("retention_days") is None
        ),
        "alarms_in_alarm": [a["name"] for a in snapshot.get("alarms", []) if a.get("state") == "ALARM"],
        "dlq_total_messages": sum(d.get("messages_available", 0) for d in snapshot.get("dlq", [])),
        "ddb_sources_discovered": len(snapshot.get("dynamodb", {}).get("sources_discovered", [])),
        "ddb_item_count": snapshot.get("dynamodb", {}).get("table", {}).get("item_count", 0),
        "mcp_config_version": snapshot.get("mcp_config", {}).get("version"),
        "changelog_version": snapshot.get("changelog_version"),
        "docs_count": len(snapshot.get("docs", [])),
        "cost_current_month": snapshot.get("cost", {}).get("current_month", {}).get("total"),
    }

    # Output
    output_json = json.dumps(snapshot, indent=2, default=str)

    if args.dry_run:
        print("\n" + output_json)
        return

    output_path = args.output or str(PLATFORM_ROOT / "audit" / f"{now.strftime('%Y-%m-%d')}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output_json)

    print(f"\n{'=' * 50}")
    print(f"Snapshot written to: {output_path}")
    print(f"Lambdas: {snapshot['summary']['lambda_count']}")
    print(f"Alarms: {snapshot['summary']['alarm_count']} ({len(snapshot['summary']['alarms_in_alarm'])} in ALARM)")
    print(f"Log groups missing retention: {snapshot['summary']['log_groups_without_retention']}")
    print(f"DLQ messages: {snapshot['summary']['dlq_total_messages']}")
    print(f"DDB sources: {snapshot['summary']['ddb_sources_discovered']}")
    print(f"DDB items: {snapshot['summary']['ddb_item_count']}")
    print(f"MCP config version: {snapshot['summary']['mcp_config_version']}")
    print(f"Changelog version: {snapshot['summary']['changelog_version']}")
    print(f"Cost MTD: ${snapshot['summary']['cost_current_month']}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
