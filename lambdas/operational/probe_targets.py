"""probe_targets.py — the functions pipeline-health-check invokes (#5980).

The daily boot probe invokes every function in `pipeline_health_check_lambda.PIPELINES`
and nothing else. That list is the registry-derived ingestion rows (#4643) plus the
compute/serve cascade below. It lives in this boto3-free module so the CDK role policy
(`cdk/stacks/role_policies_serve.py::pipeline_health_check`) can grant
`lambda:InvokeFunction` on exactly these functions, read from the same source as the
Lambda, instead of on every function in the account.
"""

from ingestion.source_registry import health_probe_targets

# The compute/serve cascade is not ingestion and has no registry row; these stay
# named here. Each handles {"healthcheck": true} as a boot check.
COMPUTE_PROBES = [
    ("character-sheet-compute", "Character Sheet", "character_sheet"),
    ("daily-metrics-compute", "Daily Metrics", "computed_metrics"),
    ("daily-insight-compute", "Daily Insights", "insights"),
    ("adaptive-mode-compute", "Adaptive Mode", "adaptive_mode"),
    ("daily-brief", "Daily Brief", "daily_brief"),
    ("anomaly-detector", "Anomaly Detector", "anomaly_detector"),
]


def probe_function_names() -> list[str]:
    """Every function the boot probe may invoke, sorted and de-duplicated. A paused
    source's function is included: the probe skips it at run time by the registry's
    `paused` facet, and the grant must not need a CDK deploy to un-pause one."""
    return sorted({fn for fn, _display, _source in health_probe_targets() + COMPUTE_PROBES})
