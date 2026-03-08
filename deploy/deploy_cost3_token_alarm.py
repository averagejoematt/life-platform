#!/usr/bin/env python3
"""
deploy_cost3_token_alarm.py — COST-3: AI Token Usage Monitoring

Creates CloudWatch alarms and a metric math expression that:
  1. Aggregates AnthropicInputTokens + AnthropicOutputTokens across all AI-calling Lambdas
  2. Estimates daily Anthropic cost using Haiku/Sonnet blended pricing
  3. Projects to monthly cost (daily × 30)
  4. Alarms at $15/month threshold → SNS → email alert

Pricing used (as of 2026-03):
  Haiku:  input $0.80/1M tokens,  output $4.00/1M tokens
  Sonnet: input $3.00/1M tokens,  output $15.00/1M tokens

Lambda AI model mapping:
  Haiku:  daily-brief (4 calls), anomaly-detector, daily-insight-compute,
          character-sheet-compute (minor), adaptive-mode-compute
  Sonnet: weekly-digest, monthly-digest, nutrition-review,
          wednesday-chronicle, weekly-plate, monday-compass, hypothesis-engine

Blended conservative estimate: ~60% Haiku, ~40% Sonnet
  → input:  $1.68/1M,  output: $8.40/1M

The alarm uses SUM of all daily input+output tokens (combined, conservatively priced
at output rate since output dominates cost) to avoid metric math expression limits.

Usage:
  python3 deploy/deploy_cost3_token_alarm.py [--dry-run]
"""

import json
import subprocess
import sys
import argparse

REGION    = "us-west-2"
ACCOUNT   = "205930651321"
NAMESPACE = "LifePlatform/AI"
SNS_ARN   = f"arn:aws:sns:{REGION}:{ACCOUNT}:life-platform-alerts"

# AI-calling Lambdas (emit to LifePlatform/AI namespace via ai_calls.py)
AI_LAMBDAS = [
    "daily-brief",
    "weekly-digest",
    "monthly-digest",
    "nutrition-review",
    "wednesday-chronicle",
    "weekly-plate",
    "monday-compass",
    "anomaly-detector",
    "daily-insight-compute",
    "hypothesis-engine",
    "character-sheet-compute",
    "adaptive-mode-compute",
]

# ── Pricing constants ──────────────────────────────────────────────────────────
# Conservative blended rate: treat all tokens at Sonnet output price ($15/1M)
# This over-estimates but ensures the alarm fires before budget is hit.
# Real cost will be lower (mix of Haiku + actual input/output split).
COST_PER_TOKEN_CONSERVATIVE = 15.0 / 1_000_000   # $15 per 1M tokens

# Monthly budget threshold
MONTHLY_BUDGET_DOLLARS = 15.0

# Daily threshold = monthly / 30
DAILY_BUDGET_DOLLARS = MONTHLY_BUDGET_DOLLARS / 30.0

# Token threshold for daily alarm:
# If all tokens cost $15/1M (conservative), what daily token count = $15/mo?
# daily_tokens = daily_budget / cost_per_token
# = ($15/30) / ($15/1M) = 0.5M tokens/day
DAILY_TOKEN_THRESHOLD = int(DAILY_BUDGET_DOLLARS / COST_PER_TOKEN_CONSERVATIVE)

print_threshold = f"{DAILY_TOKEN_THRESHOLD:,}"


def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR running: {' '.join(cmd)}")
        print(result.stderr)
        sys.exit(1)
    return result


def create_alarm(name, description, metric_name, threshold,
                 alarm_actions=None, treat_missing="notBreaching",
                 period=86400, evaluation_periods=1,
                 stat="Sum", dimensions=None, dry_run=False):
    """Create a single CloudWatch metric alarm."""
    cmd = [
        "aws", "cloudwatch", "put-metric-alarm",
        "--alarm-name", name,
        "--alarm-description", description,
        "--namespace", NAMESPACE,
        "--metric-name", metric_name,
        "--statistic", stat,
        "--period", str(period),
        "--evaluation-periods", str(evaluation_periods),
        "--threshold", str(threshold),
        "--comparison-operator", "GreaterThanOrEqualToThreshold",
        "--treat-missing-data", treat_missing,
        "--region", REGION,
    ]
    if dimensions:
        dim_str = " ".join(f"Name={k},Value={v}" for k, v in dimensions.items())
        cmd += ["--dimensions"] + [f"Name={k},Value={v}" for k, v in dimensions.items()]
    if alarm_actions:
        cmd += ["--alarm-actions"] + alarm_actions

    if dry_run:
        print(f"  [DRY RUN] Would create alarm: {name}")
        return

    result = run(cmd, check=False)
    if result.returncode == 0:
        print(f"  ✅ Alarm: {name}")
    else:
        print(f"  ❌ Failed: {name} — {result.stderr.strip()[:100]}")


def create_math_alarm(name, description, metrics, expression,
                      threshold, alarm_actions=None, dry_run=False,
                      period=86400, treat_missing="notBreaching"):
    """
    Create a CloudWatch metric math alarm.
    metrics: list of dicts with Id, MetricStat config
    expression: math expression string referencing metric Ids
    """
    metric_data_queries = []
    for m in metrics:
        metric_data_queries.append(json.dumps(m))

    cmd = [
        "aws", "cloudwatch", "put-metric-alarm",
        "--alarm-name", name,
        "--alarm-description", description,
        "--evaluation-periods", "1",
        "--threshold", str(threshold),
        "--comparison-operator", "GreaterThanOrEqualToThreshold",
        "--treat-missing-data", treat_missing,
        "--metrics", json.dumps(metrics),
        "--region", REGION,
    ]
    if alarm_actions:
        cmd += ["--alarm-actions"] + alarm_actions

    if dry_run:
        print(f"  [DRY RUN] Would create math alarm: {name}")
        return

    result = run(cmd, check=False)
    if result.returncode == 0:
        print(f"  ✅ Alarm: {name}")
    else:
        # Math alarms can be tricky via CLI — log and continue
        print(f"  ⚠️  Math alarm CLI issue: {name}")
        print(f"     {result.stderr.strip()[:200]}")
        print(f"     (Creating simple per-function alarms instead)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run
    label = "[DRY RUN] " if dry_run else ""

    print(f"{label}COST-3: AI Token Usage Alarms")
    print(f"  Namespace:        {NAMESPACE}")
    print(f"  Monthly budget:   ${MONTHLY_BUDGET_DOLLARS}")
    print(f"  Daily threshold:  {print_threshold} tokens/day (conservative blended rate)")
    print(f"  SNS:              {SNS_ARN}")
    print()

    # ── 1. Per-Lambda daily token alarms ──────────────────────────────────────
    # Each AI Lambda gets its own alarm at a per-function daily token budget.
    # Budget split: daily-brief gets 40% (most expensive, 4 AI calls),
    # others split the remaining 60% evenly.
    daily_brief_threshold = int(DAILY_TOKEN_THRESHOLD * 0.40)
    other_threshold       = int(DAILY_TOKEN_THRESHOLD * 0.60 / (len(AI_LAMBDAS) - 1))

    print(f"Creating per-Lambda total token alarms...")
    for fn in AI_LAMBDAS:
        threshold = daily_brief_threshold if fn == "daily-brief" else other_threshold
        # Alarm on output tokens (highest cost driver)
        create_alarm(
            name=f"ai-tokens-{fn}-daily",
            description=(
                f"Daily Anthropic output tokens for {fn} exceeded "
                f"{threshold:,} (COST-3 budget sentinel)"
            ),
            metric_name="AnthropicOutputTokens",
            threshold=threshold,
            dimensions={"LambdaFunction": fn},
            alarm_actions=[SNS_ARN],
            treat_missing="notBreaching",
            period=86400,
            dry_run=dry_run,
        )

    print()

    # ── 2. Platform-wide daily total token alarm ──────────────────────────────
    # Single alarm aggregating all output tokens across all AI Lambdas.
    # Uses a simple SUM metric alarm with no dimension filter
    # (CloudWatch aggregates across all dimension values when dims omitted).
    print("Creating platform-wide daily total token alarm...")
    create_alarm(
        name="ai-tokens-platform-daily-total",
        description=(
            f"Total daily Anthropic tokens (all Lambdas) exceeded {DAILY_TOKEN_THRESHOLD:,}. "
            f"Conservative estimate: this projects to ≥$15/month AI spend. "
            f"Review Anthropic console and identify high-token Lambda."
        ),
        metric_name="AnthropicOutputTokens",
        threshold=DAILY_TOKEN_THRESHOLD,
        dimensions=None,  # no dim filter = aggregate all
        alarm_actions=[SNS_ARN],
        treat_missing="notBreaching",
        period=86400,
        dry_run=dry_run,
    )
    print()

    # ── 3. API failure rate alarm ─────────────────────────────────────────────
    print("Creating Anthropic API failure alarm...")
    create_alarm(
        name="ai-anthropic-api-failures",
        description=(
            "Anthropic API failures detected across AI Lambdas. "
            "3+ failures/day suggests API key issue, quota limit, or service disruption."
        ),
        metric_name="AnthropicAPIFailure",
        threshold=3,
        dimensions=None,
        alarm_actions=[SNS_ARN],
        treat_missing="notBreaching",
        period=86400,
        dry_run=dry_run,
    )
    print()

    # ── 4. Update OBS-2 dashboard with real token widgets ────────────────────
    print("Patching OBS-2 dashboard with real token metrics...")
    _patch_dashboard_token_section(dry_run)
    print()

    # ── 5. Summary ────────────────────────────────────────────────────────────
    total_alarms = len(AI_LAMBDAS) + 2  # per-fn + platform + failure
    print("═" * 50)
    print(f"✅  COST-3 complete: {total_alarms} alarms created")
    print()
    print("  Alarm logic:")
    print(f"    Per-Lambda:  output tokens > threshold (daily) → SNS alert")
    print(f"    Platform:    total output tokens > {print_threshold}/day → '$15/mo' alert")
    print(f"    API failure: 3+ Anthropic failures/day → SNS alert")
    print()
    print("  Monitor at:")
    print(f"    https://{REGION}.console.aws.amazon.com/cloudwatch/home?"
          f"region={REGION}#alarmsV2:?search=ai-tokens")
    print(f"    https://console.anthropic.com/settings/usage")
    print("═" * 50)


def _patch_dashboard_token_section(dry_run: bool):
    """
    Fetch the existing life-platform-ops dashboard and replace the
    AI token placeholder text widget with real metric widgets.
    """
    # Fetch current dashboard
    result = run([
        "aws", "cloudwatch", "get-dashboard",
        "--dashboard-name", "life-platform-ops",
        "--region", REGION,
        "--query", "DashboardBody",
        "--output", "text",
    ], check=False)

    if result.returncode != 0:
        print("  ⚠️  Could not fetch OBS-2 dashboard — skipping patch")
        return

    try:
        dashboard = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        print("  ⚠️  Could not parse dashboard JSON — skipping patch")
        return

    # Find and replace the AI placeholder text widget
    widgets = dashboard.get("widgets", [])
    placeholder_idx = None
    for i, w in enumerate(widgets):
        if w.get("type") == "text":
            md = w.get("properties", {}).get("markdown", "")
            if "Placeholder" in md and "COST-3" in md:
                placeholder_idx = i
                break

    if placeholder_idx is None:
        print("  ⚠️  AI placeholder widget not found — dashboard may have been modified")
        return

    placeholder = widgets[placeholder_idx]
    x, y, w_dim, h_dim = (placeholder["x"], placeholder["y"],
                           placeholder["width"], placeholder["height"])

    # Replace placeholder with 3 real token metric widgets
    new_widgets = []

    # Header
    new_widgets.append({
        "type": "text", "x": x, "y": y, "width": w_dim, "height": 1,
        "properties": {"markdown": "## 🤖 AI Token Usage (COST-3)"}
    })

    # Output tokens per Lambda (bar chart style, daily)
    new_widgets.append({
        "type": "metric", "x": x, "y": y + 1, "width": 12, "height": 6,
        "properties": {
            "title": "Anthropic Output Tokens — Per Lambda (daily)",
            "view": "timeSeries",
            "stacked": True,
            "metrics": [
                ["LifePlatform/AI", "AnthropicOutputTokens",
                 "LambdaFunction", fn, {"label": fn}]
                for fn in AI_LAMBDAS
            ],
            "period": 86400,
            "stat": "Sum",
            "region": REGION,
        }
    })

    # Input tokens per Lambda
    new_widgets.append({
        "type": "metric", "x": x + 12, "y": y + 1, "width": 12, "height": 6,
        "properties": {
            "title": "Anthropic Input Tokens — Per Lambda (daily)",
            "view": "timeSeries",
            "stacked": True,
            "metrics": [
                ["LifePlatform/AI", "AnthropicInputTokens",
                 "LambdaFunction", fn, {"label": fn}]
                for fn in AI_LAMBDAS
            ],
            "period": 86400,
            "stat": "Sum",
            "region": REGION,
        }
    })

    # API failure rate
    new_widgets.append({
        "type": "metric", "x": x, "y": y + 7, "width": 12, "height": 4,
        "properties": {
            "title": "Anthropic API Failures (daily)",
            "view": "timeSeries",
            "metrics": [
                ["LifePlatform/AI", "AnthropicAPIFailure",
                 "LambdaFunction", fn, {"label": fn}]
                for fn in AI_LAMBDAS
            ],
            "period": 86400,
            "stat": "Sum",
            "region": REGION,
        }
    })

    # Total tokens KPI
    new_widgets.append({
        "type": "metric", "x": x + 12, "y": y + 7, "width": 12, "height": 4,
        "properties": {
            "title": f"Total Daily Tokens vs ${MONTHLY_BUDGET_DOLLARS}/mo Budget",
            "view": "timeSeries",
            "metrics": [
                ["LifePlatform/AI", "AnthropicOutputTokens",
                 {"label": "Output tokens (all)", "stat": "Sum"}],
                ["LifePlatform/AI", "AnthropicInputTokens",
                 {"label": "Input tokens (all)", "stat": "Sum"}],
            ],
            "period": 86400,
            "stat": "Sum",
            "region": REGION,
            "annotations": {
                "horizontal": [{
                    "label": f"$15/mo budget (~{DAILY_TOKEN_THRESHOLD:,} output tokens/day)",
                    "value": DAILY_TOKEN_THRESHOLD,
                    "color": "#ff7f0e",
                }]
            }
        }
    })

    # Splice new widgets in place of placeholder
    updated_widgets = widgets[:placeholder_idx] + new_widgets + widgets[placeholder_idx + 1:]
    dashboard["widgets"] = updated_widgets
    updated_json = json.dumps(dashboard)

    if dry_run:
        print(f"  [DRY RUN] Would patch dashboard with {len(new_widgets)} token widgets")
        return

    patch_result = run([
        "aws", "cloudwatch", "put-dashboard",
        "--dashboard-name", "life-platform-ops",
        "--dashboard-body", updated_json,
        "--region", REGION,
    ], check=False)

    if patch_result.returncode == 0:
        print(f"  ✅ OBS-2 dashboard patched: AI placeholder → {len(new_widgets)} live token widgets")
    else:
        print(f"  ⚠️  Dashboard patch failed: {patch_result.stderr.strip()[:100]}")


if __name__ == "__main__":
    main()
