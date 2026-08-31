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
  life-platform-cost-alert           DELETED 2026-08-31 (#3377) — was: AlarmActions=[],
                                      not in any cdk/stacks file
  life-platform-ai-cost-soft-alarm   DELETED 2026-08-31 (#3377) — was: routed to
                                      life-platform-billing-alerts, not in any
                                      cdk/stacks file

The 5 orphans (2 now deleted, #3377) trace to three archived onetime scripts: deploy/archive/onetime/
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

  DO NOT ADOPT (#2961 RESOLVED 2026-08-27 — this is a settled decision, not a to-do.
  Full evidence, the re-derivation commands and the reopen condition are in
  docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §9a; do not re-attempt the import from this
  file. The original blocker still applies underneath: declaring an alarm here with an
  existing physical name fails CloudFormation early validation and blocks the whole
  stack deploy, and `cdk synth` cannot catch it because synth never reads live state):
    life-platform-dash-5xx-rate       DECIDED NOT TO ADOPT. Already routed live to
                                       life-platform-alerts-us-east-1 (re-verified
                                       2026-08-27). Adoption buys a naming-only benefit
                                       and costs a production CloudFormation mutation on
                                       LifePlatformWeb — the stack whose breakage blocks
                                       the entire web deploy path (PR #2913). Reopen only
                                       if this alarm needs a functional change anyway.
    life-platform-dash-total-errors   DECIDED NOT TO ADOPT, same trade. Its live dimension
                                       is DistributionId=E3S424OXQZ8NBE — the MAIN
                                       averagejoematt.com distribution, not dash's
                                       EM5NPX6NJN095, despite the "dash" name (#2963).
                                       Answered: the NAME is the lie, not the dimension —
                                       main-site total-error coverage is worth keeping and
                                       dash already has dash-5xx-rate. Rename is
                                       RECOMMENDED, not executed: renaming a CloudWatch
                                       alarm is a delete-and-recreate that discards alarm
                                       history.
    life-platform-cf-auth-errors      RETIRE, not adopt — routed to the owner batch
                                       alongside the #2962 deletes. It watches AWS/Lambda
                                       Errors on FunctionName=life-platform-cf-auth, and
                                       that function — though it still exists and is
                                       Active — is associated with ZERO Lambda@Edge cache
                                       behaviours on all four distributions in the account
                                       (counted 2026-08-27 across DefaultCacheBehavior +
                                       every CacheBehaviors.Items entry). No cf-auth
                                       dimension exists in list-metrics in either region,
                                       and the alarm's StateReasonData has been frozen at
                                       2026-03-15 with recentDatapoints:[] for five
                                       months. So the #2829/#2961 framing — "the ONLY
                                       genuinely silent one; Lambda@Edge auth failures
                                       lock dash/blog out with no alert" — was FALSE:
                                       there is no Lambda@Edge in any request path.
                                       Routing it would ship a permanent OK that reads as
                                       coverage and is not, and adopting it here would
                                       make that false green load-bearing IaC (#3200
                                       class). Owner command recorded in §9a.

  RETIRE → #2962 → EXECUTED 2026-08-31 (#3377, owner-authorized): both alarms deleted
  (`aws cloudwatch delete-alarms`, us-east-1; post-delete describe-alarms returns 0) and
  the `life-platform/buddy-auth` secret scheduled-deleted (30-day window, gone
  2026-09-30). No live orphan remains; kept for the record:
    life-platform-cost-alert          AWS/Billing EstimatedCharges >= $5/mo, unrouted.
    life-platform-ai-cost-soft-alarm  Same metric/threshold/period as cost-alert —
                                       an exact duplicate, just routed to a second
                                       billing topic. Both predate ADR-133's cost
                                       governance (the AWS Budget
                                       life-platform-monthly-75, $215 ceiling, covering
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

    # ── The three orphan adoptions are CLOSED: DO NOT ADOPT (#2961, resolved 2026-08-27) ──
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
    # #2961 carried an owner authorization to run that import; its read-only pre-flight
    # falsified the lead item's premise and it was stopped before any AWS mutation. The
    # settled dispositions are in this module's docstring, and the evidence + the
    # re-derivation commands + the reopen condition are in
    # docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §9a. In short: `cf-auth-errors` is on a
    # DETACHED function and must be retired (owner batch), not adopted — routing it would
    # ship a permanent false OK; and the two `dash-*` alarms already route correctly, so
    # adoption is a naming-only benefit not worth a production CloudFormation mutation on
    # the stack that gates the whole web deploy path.
    #
    # This is a decision, not a deferral. Do not re-add these as constructs; the pin in
    # tests/test_web_alarms_2829.py is now permanent, not provisional.

    # life-platform-cost-alert and life-platform-ai-cost-soft-alarm are deliberately
    # NOT constructed here — see the module docstring's RETIRE disposition. Adopting an
    # alarm this module intends to help retire next would be net-new IaC churn for
    # nothing; the decision is recorded, not silently dropped.
