"""cdk/stacks/web_alarms.py — the us-east-1 alarm estate for WebStack (#2829).

Extracted as a sibling module rather than grown inline into web_stack.py (1078 lines,
unbaselined in tests/test_module_size_guard.py — the ~75-100 lines this reconciliation
needs would have left it at zero headroom with no grandfathered baseline, the same class
of mistake role_policies.py/monitoring_stack.py were extracted out of, #2604/#2610).

## Why this exists

ADR-116/#411's 2026-07 orphan-adoption pass reconciled the CloudWatch alarm estate
against CDK — but only in us-west-2 (its audit doc, docs/reviews/CLOUDWATCH_AUDIT_2026-07.md,
has zero us-east-1 mentions). WebStack is the only stack that deploys to us-east-1
(CloudFront/Lambda@Edge/ACM requirement), and it was never run through that pass. Live
`aws cloudwatch describe-alarms --region us-east-1` (2026-08-20) found exactly 6 alarms:

  email-subscriber-errors            CDK-owned (web_stack.py), AlarmActions=[] — fires
                                      into the void. The literal "no-action alarm" bug
                                      the issue is titled after.
  life-platform-dash-5xx-rate        orphan — routed live, not in any cdk/stacks file
  life-platform-dash-total-errors    orphan — routed live, not in any cdk/stacks file
  life-platform-cf-auth-errors       orphan — AlarmActions=[], not in any cdk/stacks file
  life-platform-cost-alert           orphan — AlarmActions=[], not in any cdk/stacks file
  life-platform-ai-cost-soft-alarm   orphan — routed live (to a DIFFERENT topic,
                                      life-platform-billing-alerts), not in any
                                      cdk/stacks file

The 5 orphans trace to three archived onetime scripts: deploy/archive/onetime/
create_cloudfront_5xx_alarm.sh (dash-5xx-rate + dash-total-errors + the
life-platform-alerts-us-east-1 topic itself), deploy/archive/onetime/
create_lambda_edge_alarm.sh (cf-auth-errors, deliberately created with NO action per its
own comment — "SNS topic in us-east-1 required, main topic is us-west-2 and cross-region
alarm actions are unsupported... create a dedicated topic if email alerting is needed"),
and deploy/archive/20260314/create_ai_cost_alarm.sh (ai-cost-soft-alarm + a SECOND,
still-live billing topic life-platform-billing-alerts). life-platform-cost-alert predates
even that script and duplicates its metric/threshold exactly with no action at all.

## Disposition (#2829 acceptance: "routed or retired, decision recorded")

  ADOPT + ROUTE  life-platform-dash-5xx-rate
  ADOPT + ROUTE  life-platform-dash-total-errors  (NOTE: live dimension is
                 DistributionId=E3S424OXQZ8NBE — the MAIN averagejoematt.com
                 distribution, not dash's EM5NPX6NJN095, despite the "dash" name. A
                 pre-existing naming/coverage mismatch from the March 2026 script, out
                 of scope for this reconciliation — codified byte-for-byte against live
                 config so adoption changes zero observable behavior.)
  ADOPT + ROUTE  life-platform-cf-auth-errors — a real functional signal (Lambda@Edge
                 auth failures lock dash/blog out entirely) that was created with no
                 action purely because no us-east-1 SNS topic existed yet at the time.
                 One now does (see below) — wire it.

  RETIRE (decision recorded; NOT executed here — deleting a live alarm is an AWS
  mutation, out of scope for a read-only worktree; see the PR body for the owner's
  post-merge `aws cloudwatch delete-alarms` command):
    life-platform-cost-alert          AWS/Billing EstimatedCharges >= $5/mo, unrouted.
    life-platform-ai-cost-soft-alarm  Same metric/threshold/period as cost-alert —
                                       an exact duplicate, just routed to a second
                                       billing topic. Both predate ADR-133's cost
                                       governance (the AWS Budget
                                       life-platform-monthly-75, $150 ceiling, covering
                                       ALL spend + cost_governor_lambda's SSM
                                       budget-tier system) by months; a flat $5
                                       total-AWS-spend threshold is not a meaningful
                                       signal once steady-state spend is >$100/mo — it
                                       would either have been permanently tripped or
                                       (more likely, per the March-dated
                                       StateReasonData never refreshing) never actually
                                       evaluating because the account's "Receive
                                       Billing Alerts" console preference isn't on.
                                       Neither is adopted into CDK; adopting a signal
                                       only to delete it next PR would be pure churn.

## Where the alarm set gets derived, not hand-listed (charter primitives 1/2)

Putting these in cdk/stacks/*.py (rather than a hand-maintained doc row or a one-off
script) is what makes them derivable: deploy/sync_doc_metadata.py's
`_auto_discover_alarm_count`/`_auto_discover_alarm_names_by_stack` AST-walk EVERY file
under cdk/stacks/*.py, not a fixed list of stack names — this module is picked up for
free, and docs/MONITORING.md's generated alarm-inventory block and the alarm count both
update from `python3 deploy/sync_doc_metadata.py --apply` with no code change to the
discovery machinery itself. A future 7th us-east-1 alarm that lands here is documented
automatically; one that lands as a bare `aws cloudwatch put-metric-alarm` again is
exactly the orphan class this file exists to close.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
)
from constructs import Construct

from stacks.constants import ACCT

REGION_US_EAST_1 = "us-east-1"

# Imported, not created (#2829 create-vs-import call): this topic already exists live
# with a confirmed email subscription (awsdev@mattsusername.com, subscribed by
# deploy/archive/onetime/create_cloudfront_5xx_alarm.sh) and is already the action on
# the two live dash alarms below. Creating a second us-east-1 topic would fragment
# subscribers across two topics for no benefit — the whole point is ONE place a human
# hears from.
ALERTS_TOPIC_ARN_US_EAST_1 = f"arn:aws:sns:{REGION_US_EAST_1}:{ACCT}:life-platform-alerts-us-east-1"

GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD
GT = cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
NOT_BREACHING = cloudwatch.TreatMissingData.NOT_BREACHING


def add_web_alarms(scope: Construct, subscriber_alarm: cloudwatch.Alarm) -> None:
    """Wire the us-east-1 alarm estate onto `scope` (WebStack, us-east-1).

    `subscriber_alarm` is the existing OBS-07 `email-subscriber-errors` Alarm construct
    (still defined in web_stack.py — it already existed there; this only supplies the
    `.add_alarm_action()` call it was missing). Everything else is adopted fresh here.
    """
    topic = sns.Topic.from_topic_arn(scope, "AlertsTopicUsEast1", ALERTS_TOPIC_ARN_US_EAST_1)

    # OBS-07 fix: the literal "fires into the void" bug named in the issue title.
    subscriber_alarm.add_alarm_action(cw_actions.SnsAction(topic))

    # ADOPT — CloudFront 5xx rate on the dash distribution. Codified from live config.
    dash_5xx_rate = cloudwatch.Alarm(
        scope,
        "DashCf5xxRate",
        alarm_name="life-platform-dash-5xx-rate",
        alarm_description=(
            "CloudFront dash.averagejoematt.com 5xx error rate >5% — dashboard may be "
            "broken. Check: CloudFront distribution EM5NPX6NJN095 error pages + "
            "Lambda@Edge logs."
        ),
        metric=cloudwatch.Metric(
            namespace="AWS/CloudFront",
            metric_name="5xxErrorRate",
            dimensions_map={"DistributionId": "EM5NPX6NJN095", "Region": "Global"},
            period=Duration.minutes(5),
            statistic="Average",
        ),
        threshold=5,
        evaluation_periods=2,
        comparison_operator=GTE,
        treat_missing_data=NOT_BREACHING,
    )
    dash_5xx_rate.add_alarm_action(cw_actions.SnsAction(topic))

    # ADOPT — CloudFront TotalErrorRate. Live dimension is E3S424OXQZ8NBE (the main
    # averagejoematt.com distribution) — see the module docstring's naming-mismatch
    # note. Codified byte-for-byte against live config, mismatch and all.
    dash_total_errors = cloudwatch.Alarm(
        scope,
        "DashCfTotalErrors",
        alarm_name="life-platform-dash-total-errors",
        alarm_description=(
            "ADR-058 (2026-05-24): threshold 10%->25%, eval 1->3 periods (15 min "
            "sustained). Was flapping on bot 404s on low-traffic site."
        ),
        metric=cloudwatch.Metric(
            namespace="AWS/CloudFront",
            metric_name="TotalErrorRate",
            dimensions_map={"DistributionId": "E3S424OXQZ8NBE"},
            period=Duration.minutes(5),
            statistic="Average",
        ),
        threshold=25,
        evaluation_periods=3,
        datapoints_to_alarm=3,
        comparison_operator=GT,
        treat_missing_data=NOT_BREACHING,
    )
    dash_total_errors.add_alarm_action(cw_actions.SnsAction(topic))

    # ADOPT + ROUTE — Lambda@Edge cf-auth invocation errors. A real functional signal
    # (auth failures lock dashboard/blog out entirely) that was born action-less only
    # because no us-east-1 topic existed at the time (see module docstring). One does
    # now — wire it, closing the second "no-action alarm" the issue's live evidence
    # named (life-platform-cf-auth-errors, AlarmActions=[]).
    cf_auth_errors = cloudwatch.Alarm(
        scope,
        "CfAuthErrors",
        alarm_name="life-platform-cf-auth-errors",
        alarm_description=(
            "Lambda@Edge cf-auth invocation errors — dashboard/blog may be "
            "inaccessible. Check: aws logs tail /aws/lambda/us-east-1.life-platform-cf-auth "
            "--region us-east-1"
        ),
        metric=cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": "life-platform-cf-auth"},
            period=Duration.minutes(5),
            statistic="Sum",
        ),
        threshold=5,
        evaluation_periods=2,
        comparison_operator=GTE,
        treat_missing_data=NOT_BREACHING,
    )
    cf_auth_errors.add_alarm_action(cw_actions.SnsAction(topic))

    # life-platform-cost-alert and life-platform-ai-cost-soft-alarm are deliberately
    # NOT constructed here — see the module docstring's RETIRE disposition. Adopting an
    # alarm this module intends to help retire next would be net-new IaC churn for
    # nothing; the decision is recorded, not silently dropped.
