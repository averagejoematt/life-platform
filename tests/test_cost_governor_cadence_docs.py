"""
Guard for #1254: the cost-governor's documented cadence must match the live
EventBridge rule, which is cron(0 0/8 * * ? *) — every 8 hours, NOT hourly.

Ground truth (the discoverer): cdk/stacks/operational_stack.py sets the
CostGovernor schedule to cron(0 0/8 * * ? *). This test asserts the three
prose surfaces that describe the cadence agree with it:

  1. lambdas/operational/cost_governor_lambda.py — module docstring
  2. lambdas/budget_guard.py                     — the cache-TTL comment
  3. site/method/cost/index.html                 — the /method/build editorial
     (generator output of scripts/v4_build_evidence.py)

Files are read as TEXT (no imports of budget_guard / cost_governor — those pull
in boto3, a layer-only dep that would red collection). Assertions are targeted
string checks so a false "hourly" cadence claim fails loudly, while unrelated
uses of the word "hour" (e.g. datetime .replace(hour=0)) do not trip it.
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

_GOVERNOR = REPO_ROOT / "lambdas" / "operational" / "cost_governor_lambda.py"
_BUDGET_GUARD = REPO_ROOT / "lambdas" / "budget_guard.py"
_COST_PAGE = REPO_ROOT / "site" / "method" / "cost" / "index.html"

# The stale cadence phrasings this issue eradicated — none may reappear.
_GOVERNOR_STALE = ("Runs hourly", "Schedule: hourly")
_BUDGET_GUARD_STALE = ("hourly cadence", "governor's hourly")
_COST_PAGE_STALE = ("projects month-end spend every hour",)


def _read(path: pathlib.Path) -> str:
    assert path.exists(), f"expected file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_cdk_schedule_is_still_8h():
    """The discoverer / ground truth: the live cron is every 8h, not hourly."""
    stack = _read(REPO_ROOT / "cdk" / "stacks" / "operational_stack.py")
    assert "cron(0 0/8 * * ? *)" in stack, "CostGovernor schedule is no longer the 8h cron this guard assumes"


def test_governor_docstring_says_8h_not_hourly():
    text = _read(_GOVERNOR)
    for stale in _GOVERNOR_STALE:
        assert stale not in text, f"cost_governor_lambda.py still claims hourly cadence: {stale!r}"
    assert "every 8h" in text, "cost_governor_lambda.py must state the true every-8h cadence"


def test_budget_guard_comment_says_8h_not_hourly():
    text = _read(_BUDGET_GUARD)
    for stale in _BUDGET_GUARD_STALE:
        assert stale not in text, f"budget_guard.py still claims the governor runs hourly: {stale!r}"
    assert "every-8h" in text or "every 8h" in text, "budget_guard.py must state the true every-8h cadence"


def test_cost_page_editorial_says_8h_not_hourly():
    text = _read(_COST_PAGE)
    for stale in _COST_PAGE_STALE:
        assert stale not in text, f"/method/build editorial still says the governor runs every hour: {stale!r}"
    assert "projects month-end spend every 8 hours" in text, "cost page editorial must state the true every-8h cadence"
