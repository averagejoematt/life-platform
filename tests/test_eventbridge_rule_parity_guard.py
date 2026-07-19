"""tests/test_eventbridge_rule_parity_guard.py — offline proof for the #1257
EventBridge rule-parity regression guard (I24 in tests/test_integration_aws.py).

I24 itself needs live AWS credentials (it lists real EventBridge rules), so it
can't run in the main CI "Unit Tests" job — that job `--ignore`s the whole
test_integration_aws.py file (it's manual/post-deploy-only, see that file's
module docstring). This file pins the DETERMINISTIC half — the static CDK-side
discovery (`_cdk_scheduled_lambda_names`) — so the guard's logic is proven
correct on every PR, not just after a deploy with live creds.

Every test here FAILS on the pre-#1257-guard tree (the function doesn't exist
yet — AttributeError), same convention as tests/test_unred_main_1327.py.
"""

import importlib.util
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_test_integration_aws():
    path = os.path.join(_REPO, "tests", "test_integration_aws.py")
    spec = importlib.util.spec_from_file_location("ia_1257_guard", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_cdk_scheduled_lambda_names_finds_schedule_kwarg_lambdas():
    """Pattern 1: create_platform_lambda(function_name=..., schedule=...)."""
    ia = _load_test_integration_aws()
    names = ia._cdk_scheduled_lambda_names()
    # subscriber-onboarding: CDK's SubscriberOnboardingSchedule, cron(5 17) —
    # the exact lambda #1257 flags as double-scheduled by the orphan rule.
    assert "subscriber-onboarding" in names
    # pipeline-health-check: CDK's PipelineHealthCheckSchedule, 5x/day —
    # the other #1257 offender.
    assert "pipeline-health-check" in names
    # A plain-string schedule elsewhere in the fleet, for sanity.
    assert "daily-metrics-compute" in names


def test_cdk_scheduled_lambda_names_resolves_fstring_schedule():
    """schedule=f"cron(0 {INGEST_HOURLY} ...)" (ingestion_stack.py's Whoop
    ingestion) is not a plain string Constant — the discovery must still count
    it as scheduled (presence, not the literal cron text, is what matters)."""
    ia = _load_test_integration_aws()
    names = ia._cdk_scheduled_lambda_names()
    assert "whoop-data-ingestion" in names


def test_cdk_scheduled_lambda_names_finds_manual_rule_escape_hatch():
    """Pattern 2: a manual events.Rule(...) + add_target(targets.LambdaFunction(var))
    where var was assigned by an earlier create_platform_lambda(function_name=...)
    call in the same file — operational_stack.py's documented "manual events.Rule
    escape hatch" (used because create_platform_lambda's schedule= shortcut
    auto-ENABLES the rule, and ADR-066 ships hevy-routine-cron disabled)."""
    ia = _load_test_integration_aws()
    names = ia._cdk_scheduled_lambda_names()
    assert "hevy-routine-cron" in names  # ships disabled but still CDK-governed
    assert "hevy-restamp" in names
    assert "site-stats-refresh" in names
    assert "dashboard-refresh" in names  # has both its own schedule= AND a 2nd manual rule


def test_cdk_scheduled_lambda_names_resolves_module_level_constant_function_name():
    """mcp_stack.py's warmer uses function_name=WARMER_FUNCTION_NAME (a module
    constant), not a string literal — the discovery must resolve it, not skip
    the call silently just because function_name isn't a bare string."""
    ia = _load_test_integration_aws()
    names = ia._cdk_scheduled_lambda_names()
    assert "life-platform-mcp-warmer" in names
    # The MCP server itself has NO schedule= — must NOT be misreported as scheduled.
    assert "life-platform-mcp" not in names


def test_eventbridge_exemptions_list_exists_and_is_a_set():
    """The exemption list the guard checks against must exist and be a set —
    a plain list would silently make `in` checks correct-but-slow at worst, but
    the guard's whole design intent is "explicit exemption list", so pin the type."""
    ia = _load_test_integration_aws()
    assert isinstance(ia.EVENTBRIDGE_RULE_EXEMPTIONS, set)
