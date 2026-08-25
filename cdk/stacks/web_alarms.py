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

## Disposition (#2829 acceptance: "routed or retired, decision recorded" — rescoped
## 2026-08-20 after the adoption-as-CREATE attempt blocked the LifePlatformWeb deploy)

  ROUTE (SHIPPED — the titled bug):
    email-subscriber-errors           CDK-owned; the one `.add_alarm_action()` below.
                                       Live-verified routed 2026-08-21.

  DEFER adoption → #2961 (needs `cdk import`, not a CREATE — declaring an alarm here
  with an existing physical name fails CloudFormation early validation and blocks the
  whole stack deploy; `cdk synth` cannot catch it because synth never reads live state):
    life-platform-dash-5xx-rate       already routed live — deferral costs nothing
    life-platform-dash-total-errors   already routed live. NOTE: its live dimension is
                                       DistributionId=E3S424OXQZ8NBE — the MAIN
                                       averagejoematt.com distribution, not dash's
                                       EM5NPX6NJN095, despite the "dash" name. Tracked
                                       as #2963; the import (#2961) must coordinate so
                                       adoption imports the corrected meaning, not the
                                       lie.
    life-platform-cf-auth-errors      the ONLY genuinely silent one (Lambda@Edge auth
                                       failures lock dash/blog out with no alert) —
                                       #2961 does it first.

  RETIRE → #2962 (decision recorded; NOT executed here — deleting a live alarm is an AWS
  mutation, out of scope for a read-only worktree; the exact owner-run
  `aws cloudwatch delete-alarms` command is recorded in #2962):
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


def add_web_alarms(scope: Construct, subscriber_alarm: cloudwatch.Alarm, og_image_alarm: cloudwatch.Alarm = None) -> None:
    """Wire the us-east-1 alarm estate onto `scope` (WebStack, us-east-1).

    `subscriber_alarm` is the existing OBS-07 `email-subscriber-errors` Alarm construct
    (still defined in web_stack.py — it already existed there; this only supplies the
    `.add_alarm_action()` call it was missing). `og_image_alarm` (#3161) is the new
    `life-platform-og-image-errors` Alarm construct — same missing-action shape, wired
    the same way. Everything else is adopted fresh here.
    """
    topic = sns.Topic.from_topic_arn(scope, "AlertsTopicUsEast1", ALERTS_TOPIC_ARN_US_EAST_1)

    # OBS-07 fix: the literal "fires into the void" bug named in the issue title.
    subscriber_alarm.add_alarm_action(cw_actions.SnsAction(topic))

    # #3161: life-platform-og-image had ZERO alarms of any kind (live-verified via
    # describe-alarms) — route the new error alarm into the same us-east-1 topic.
    if og_image_alarm is not None:
        og_image_alarm.add_alarm_action(cw_actions.SnsAction(topic))

    # ADOPT — CloudFront 5xx rate on the dash distribution. Codified from live config.
    # ── The three orphan adoptions are DEFERRED (#2829, rescoped 2026-08-20) ──
    #
    # `life-platform-dash-5xx-rate`, `life-platform-dash-total-errors` and
    # `life-platform-cf-auth-errors` already EXIST in us-east-1, created outside CDK.
    # Declaring them here with their real names makes CloudFormation attempt a CREATE,
    # and it pre-validates the name is free. It is not:
    #
    #     Early validation failed for change set cdk-deploy-change-set:
    #       Resource of type 'AWS::CloudWatch::Alarm' with identifier
    #       'life-platform-dash-5xx-rate' already exists.
    #
    # That blocked the whole LifePlatformWeb deploy on 2026-08-20. Bringing an existing
    # resource under stack management needs `cdk import`, not synth-and-deploy — and
    # crucially, a green `cdk synth` cannot catch this, because synth renders a template
    # from source and never consults live AWS state.
    #
    # Deferring costs almost nothing: measured live, `dash-5xx-rate` and
    # `dash-total-errors` ALREADY route to this topic. Only `cf-auth-errors` is genuinely
    # silent, and it is tracked on #2829 along with the `cdk import` decision. The issue's
    # "5 of 6 alarms are IaC orphans" is true; the implied "so they fire into the void" is
    # not — only 2 of 6 have no AlarmActions.

    # life-platform-cost-alert and life-platform-ai-cost-soft-alarm are deliberately
    # NOT constructed here — see the module docstring's RETIRE disposition. Adopting an
    # alarm this module intends to help retire next would be net-new IaC churn for
    # nothing; the decision is recorded, not silently dropped.
