"""metric_namespaces.py — canonical CloudWatch namespace literals (#3002).

CloudWatch namespaces are case-sensitive, so a casing variant is a WHOLE OTHER
namespace: `lambdas/web/site_api_common.py` wrote the canonical spelling at one
line and a lowercase-i `SiteApi` twin 424 lines apart, and both went live (322
series vs 5). Every alarm and dashboard read the capital spelling, so
`ContentFilterFallback` — the privacy content filter degrading to its
fail-closed fallback — was emitted where nothing looked. A real 9-day fallback
episode (2026-03-21 → 29, 62 datapoints, peak 16/day) passed unwatched.

The fix is structural, not a grep-and-sweep (a sweep is how the twin appeared):
every site-API emitter imports THIS constant, `lambdas/web/` may not contain
the namespace as a string literal at all, and
`tests/test_site_api_namespace_guard_3002.py` asserts the set — one spelling
across emitters and CDK consumers, and no case-insensitive namespace twins
anywhere in the repo.

CDK stacks keep the literal spelling (they are synth-time, not bundled, and do
not import lambda modules — see `reference_cdk_synth_python_resolution`); the
guard test pins their literals to this constant by AST instead.
"""

# The site-API serving Lambdas' custom-metric namespace (Handled5xx #2819,
# DurationMs/ColdStart #2876, RateLimitHit OBS-03, ContentFilterFallback
# BUG-05/#3002). Consumed by cdk/stacks/serve_stack.py alarms and
# cdk/stacks/monitoring_dashboards.py widgets.
SITE_API_METRIC_NAMESPACE: str = "LifePlatform/SiteAPI"
