"""cdk/stacks/monitoring_dashboards.py — the CloudWatch **dashboards** of MonitoringStack.

Extracted from ``monitoring_stack.py`` by #2610. That module sat at exactly its recorded
size baseline (1,623 of 1,623 lines, zero headroom), so adding one alarm — the single most
routine change this stack ever takes — could not land without an unrelated refactor first.

The seam is the one the module already draws with its own section banners: **alarms are
the contract, dashboards are the view.** Nothing here creates an ``AWS::CloudWatch::Alarm``,
subscribes an SNS topic, or writes a metric filter; both dashboards are pure composition
over metrics that other code already emits. Keeping the extraction alarm-free is deliberate
— a refactor that silently drops an alarm is a monitoring hole nobody sees until an incident
goes unalarmed, and it also keeps ``deploy/sync_doc_metadata.py``'s AST alarm census (which
walks ``cdk/stacks/*.py`` and recognises the ``_alarm``/``_heartbeat_alarm`` closures by
their shape) reading exactly the same number.

Proof of equivalence for the move: the synthesized ``LifePlatformMonitoring`` CloudFormation
template is byte-identical before and after — 63 alarms, 2 dashboards, 71 resources, every
logical id and every property unchanged. Not a text diff (see #2608 for the precedent).

Contract: ``add_dashboards(stack)`` is called once, last, from ``MonitoringStack.__init__``.
Resources are created in the same order under the same scope, so the logical ids are stable
and no deployed resource is replaced.
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
)


def add_dashboards(stack) -> None:
    """Attach the SiteAPI EMF dashboard and the ops dashboard to ``stack``."""
    # ══════════════════════════════════════════════════════════════
    # SiteAPI EMF dashboard (BACKLOG.md:252 — closes P3.4 observability loop)
    # ══════════════════════════════════════════════════════════════
    # site_api_lambda.py emits a per-request structured log line:
    #   {"_aws": {...}, "Route": "/api/...", "Method": "GET", "DurationMs": N, "ColdStart": 0/1}
    #
    # #2876 cost amendment (2026-08-18): `Route`/`Method` used to ALSO be
    # listed as EMF `Dimensions`, which mints one BILLED CloudWatch custom
    # metric per unique (Route, Method) pair — $0.30/metric/month each.
    # Measured live on 2026-08-18: 158 already-active billable streams from
    # this alone, and #2882's coverage fix (every route now reaches the
    # emitter, not just the 93 that used to) would have added ~88 more —
    # net-new cost was priced at +$12-13/month for that PR as shipped.
    # `_emit_route_log` (lambdas/web/site_api_lambda.py) now ships ONE
    # dimensionless metric variant only (`Dimensions: [[]]`), for every
    # route uniformly — no per-route allowlist, that would be the
    # hand-enumeration the charter's standing rule 1 forbids. Expected
    # effect: roughly -$20 to -$25/month vs. leaving Route+Method dimensioned
    # for all ~137 routes.
    #
    # `Route` and `Method` are STILL plain top-level JSON fields on every log
    # line (EMF *properties*, never billed) — per-route latency stays fully
    # queryable via CloudWatch Logs Insights, just not auto-graphable by
    # metric name+dimensions anymore. The 6 hardcoded `TOP_ROUTES` panels
    # this dashboard used to read (Route+Method dimensioned Metric objects)
    # would have rendered EMPTY post-#2876 without this rewrite — a
    # dashboard silently reporting nothing is the "reports clean while
    # measuring nothing" defect class this repo keeps re-finding, so the
    # panels below are LogQueryWidgets (live Logs Insights queries over the
    # same log group) instead. They also fix a smaller pre-existing issue:
    # the old 6-route list was itself a hand-typed enumeration that silently
    # missed every other route; a `stats ... by Route, Method` query finds
    # whatever is actually hot or slow, dynamically, with no list to drift.
    #
    # The Lambda runs in us-west-2 (R17-09 move) so same-region dashboards work.
    SITE_API_LOG_GROUP = "/aws/lambda/life-platform-site-api"

    def _aggregate_metric(metric_name: str, stat: str, label: str):
        """The ONE dimensionless LifePlatform/SiteAPI custom metric #2876
        kept — flat ~$0.30/metric/month regardless of route count, giving a
        fleet-wide latency/cold-start signal without enumerating any route."""
        return cloudwatch.Metric(
            namespace="LifePlatform/SiteAPI",
            metric_name=metric_name,
            statistic=stat,
            period=Duration.minutes(5),
            label=label,
        )

    def _route_log_query(title: str, sort_expr: str):
        """A live Logs Insights table over the route_metric log lines.
        Route/Method are plain JSON properties on every line (never billed
        dimensions post-#2876), so per-route breakdown stays available here
        without minting a metric per route. See the #2876 PR body for the
        equivalent query run ad hoc in the console."""
        return cloudwatch.LogQueryWidget(
            log_group_names=[SITE_API_LOG_GROUP],
            title=title,
            width=12,
            height=6,
            view=cloudwatch.LogQueryVisualizationType.TABLE,
            query_lines=[
                "fields Route, Method, DurationMs, ColdStart",
                'filter _type = "route_metric"',
                "stats count(*) as requests, "
                "pct(DurationMs, 50) as p50_ms, "
                "pct(DurationMs, 95) as p95_ms, "
                "avg(ColdStart) * 100 as cold_start_pct "
                "by Route, Method",
                f"sort {sort_expr}",
                "limit 20",
            ],
        )

    site_api_dash = cloudwatch.Dashboard(
        stack,
        "SiteApiDashboard",
        dashboard_name="life-platform-site-api-dashboard",
        period_override=cloudwatch.PeriodOverride.AUTO,
        start="-PT1H",
    )

    # Row 1: live per-route latency (Logs Insights) — two views of the same
    # underlying query, by traffic (what's hot) and by p95 (what's slow).
    # Replaces the old hardcoded-6-route p50/p95 metric panels.
    site_api_dash.add_widgets(
        _route_log_query("Per-route latency — top 20 by traffic (Logs Insights, live)", "requests desc"),
        _route_log_query("Per-route latency — slowest 20 by p95 (Logs Insights, live)", "p95_ms desc"),
    )

    # Row 2: cold starts by route (Logs Insights) + the unchanged AWS/Lambda
    # function-wide panel (that one was never on our custom dimensions —
    # AWS/Lambda's own Invocations/Errors/Duration — so #2876 doesn't touch it).
    site_api_dash.add_widgets(
        _route_log_query("Cold starts by route — top 20 by rate (Logs Insights, live)", "cold_start_pct desc"),
        cloudwatch.GraphWidget(
            title="site-api Lambda — Errors + Invocations + Duration",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": "life-platform-site-api"},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label="Invocations",
                ),
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": "life-platform-site-api"},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label="Errors",
                    color=cloudwatch.Color.RED,
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": "life-platform-site-api"},
                    statistic="p99",
                    period=Duration.minutes(5),
                    label="Duration p99 (ms)",
                ),
            ],
            right_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
        ),
    )

    # Row 3: the ONE flat-cost dimensionless aggregate #2876 kept — fleet-wide
    # latency + cold-start rate, ~$0.60/month total (2 metrics x 1 dimension
    # set) regardless of how many routes exist or how much traffic they get.
    site_api_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="Fleet-wide latency p50/p95 — all routes, aggregate metric (~$0.30/mo flat)",
            width=12,
            height=6,
            left=[
                _aggregate_metric("DurationMs", "p50", "p50 (ms)"),
                _aggregate_metric("DurationMs", "p95", "p95 (ms)"),
            ],
            left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
        ),
        cloudwatch.GraphWidget(
            title="Fleet-wide cold starts — all routes, aggregate metric (~$0.30/mo flat)",
            width=12,
            height=6,
            left=[_aggregate_metric("ColdStart", "Sum", "cold starts")],
        ),
    )

    # ══════════════════════════════════════════════════════════════
    # OPS-DASH (2026-06-09, Tier-2): the CDK-managed `life-platform-ops`
    # dashboard — replaces the hand-built console one (which was the headline
    # ops view but lived nowhere in code). The row that matters most is
    # ingestion health: the 2026 Garmin 44-day outage was caught by a MANUAL
    # audit, not an alarm — this surfaces a source that stops or starts erroring
    # on day 1. All metrics here are already emitted; this just composes them.
    # ══════════════════════════════════════════════════════════════
    COMPUTE_FNS = ["character-sheet-compute", "adaptive-mode-compute", "daily-metrics-compute", "daily-insight-compute", "daily-brief"]
    # SEARCH auto-discovers every ingestion Lambda (all 13 names contain "ingestion")
    # and graphs one line each — no hardcoded list to drift.
    _ingest_errors = cloudwatch.MathExpression(
        expression="SEARCH('{AWS/Lambda,FunctionName} MetricName=\"Errors\" ingestion', 'Sum', 300)",
        period=Duration.minutes(5),
        using_metrics={},
    )
    _ingest_invocations = cloudwatch.MathExpression(
        expression="SEARCH('{AWS/Lambda,FunctionName} MetricName=\"Invocations\" ingestion', 'Sum', 300)",
        period=Duration.minutes(5),
        using_metrics={},
    )

    def _lambda_metric(fn, metric_name, statistic="Sum", period_min=5):
        return cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name=metric_name,
            dimensions_map={"FunctionName": fn},
            statistic=statistic,
            period=Duration.minutes(period_min),
            label=fn,
        )

    def _freshness_metric(metric_name, label, color):
        return cloudwatch.Metric(
            namespace="LifePlatform/Freshness",
            metric_name=metric_name,
            statistic="Maximum",
            period=Duration.hours(1),
            label=label,
            color=color,
        )

    ops_dash = cloudwatch.Dashboard(
        stack,
        "OpsDashboard",
        dashboard_name="life-platform-ops",
        period_override=cloudwatch.PeriodOverride.AUTO,
        start="-PT24H",
    )

    # Row 1 — Ingestion freshness (aggregate source-health counts)
    ops_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="Ingestion freshness — source counts (stale / warning / partial)",
            width=16,
            height=6,
            left=[
                _freshness_metric("StaleSourceCount", "Stale (actionable)", cloudwatch.Color.RED),
                _freshness_metric("WarningSourceCount", "Warning", cloudwatch.Color.ORANGE),
                _freshness_metric("PartialCompletenessCount", "Partial fields", cloudwatch.Color.BLUE),
            ],
        ),
        cloudwatch.SingleValueWidget(
            title="Stale sources (now)",
            width=8,
            height=6,
            metrics=[_freshness_metric("StaleSourceCount", "stale", cloudwatch.Color.RED)],
        ),
    )

    # Row 2 — Per-source ingestion Lambda health (SEARCH-discovered, one line per source)
    ops_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="Ingestion Lambda errors per source (Sum 5min) — a source going dark shows here",
            width=12,
            height=6,
            left=[_ingest_errors],
        ),
        cloudwatch.GraphWidget(
            title="Ingestion Lambda invocations per source (Sum 5min)",
            width=12,
            height=6,
            left=[_ingest_invocations],
        ),
    )

    # Row 3 — Compute pipeline (the daily-brief dependency chain)
    ops_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="Compute pipeline — duration p99 (ms)",
            width=12,
            height=6,
            left=[_lambda_metric(fn, "Duration", "p99") for fn in COMPUTE_FNS],
            left_y_axis=cloudwatch.YAxisProps(label="ms", show_units=False),
        ),
        cloudwatch.GraphWidget(
            title="Compute pipeline — errors (Sum 1h)",
            width=12,
            height=6,
            left=[_lambda_metric(fn, "Errors", "Sum", period_min=60) for fn in COMPUTE_FNS],
        ),
    )

    # Row 4 — AI spend + budget tier (cost-governor)
    ops_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="AI output tokens (Sum 1h) + projected month-end spend ($)",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="LifePlatform/AI",
                    metric_name="AnthropicOutputTokens",
                    statistic="Sum",
                    period=Duration.hours(1),
                    label="output tokens",
                )
            ],
            right=[
                cloudwatch.Metric(
                    namespace="LifePlatform/Budget",
                    metric_name="ProjectedMonthlySpend",
                    statistic="Maximum",
                    period=Duration.hours(1),
                    label="projected $/mo",
                    color=cloudwatch.Color.ORANGE,
                )
            ],
            right_y_axis=cloudwatch.YAxisProps(label="USD", show_units=False),
        ),
        cloudwatch.GraphWidget(
            title="Budget tier (0 normal → 3 hard cutoff)",
            width=12,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="LifePlatform/Budget",
                    metric_name="BudgetTier",
                    statistic="Maximum",
                    period=Duration.hours(1),
                    label="tier",
                    color=cloudwatch.Color.ORANGE,
                )
            ],
            left_y_axis=cloudwatch.YAxisProps(min=0, max=3, show_units=False),
        ),
    )

    # Row 5 — Ingestion DLQ depth + consumer health
    ops_dash.add_widgets(
        cloudwatch.GraphWidget(
            title="Ingestion DLQ — depth + consumer health",
            width=24,
            height=6,
            left=[
                cloudwatch.Metric(
                    namespace="AWS/SQS",
                    metric_name="ApproximateNumberOfMessagesVisible",
                    dimensions_map={"QueueName": "life-platform-ingestion-dlq"},
                    statistic="Maximum",
                    period=Duration.minutes(5),
                    label="DLQ depth",
                    color=cloudwatch.Color.RED,
                )
            ],
            right=[
                _lambda_metric("life-platform-dlq-consumer", "Errors", "Sum"),
                _lambda_metric("life-platform-dlq-consumer", "Invocations", "Sum"),
            ],
        ),
    )
