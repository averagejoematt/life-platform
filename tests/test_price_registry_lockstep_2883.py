"""tests/test_price_registry_lockstep_2883.py — #2883: ONE Bedrock price table.

`CostMetricDriftRatio` (cost_governor_lambda._emit_metrics) is

    native AWS/Bedrock token metrics x price   <- cost_governor._PRICES
    ----------------------------------------
    LifePlatform/AI::EstimatedCostUSD          <- bedrock_client.PRICES

Two price tables in a ratio means the ratio can move for a reason that has nothing to
do with attribution. It did, for months: the governor's hand-maintained copy carried no
`titan` row, so `_price_for("amazon.titan-embed-text-v2:0")` fell through to
`_DEFAULT_PRICE` (the fable tier, $10/1M input) while `bedrock_client` priced the same
tokens at the published $0.02/1M (#1384). Measured live 2026-08-30: 576,561 Titan input
tokens month-to-date metered as **$5.77** in the numerator against **$0.0115** of real
cost — $5.76 of the month's $22.92 drift gap, and the numerator's largest single error.

The fix is structural, not a re-copy: `cost_governor_lambda` IMPORTS
`ai.bedrock_client.PRICES`, and `site_api_budget` already imports the governor's name,
so the three modules share one object. This file guards both halves of that:

  1. the live path is the SAME OBJECT (identity, not equality — a re-copy would pass an
     equality check on the day it was made and drift the day after);
  2. the packaging-drift fallback literal inside the governor's `except ImportError`
     branch is AST-parsed and compared to the registry, so the degraded path cannot
     quietly become the second hand-maintained table this issue was caused by.

Run:  python3 -m pytest tests/test_price_registry_lockstep_2883.py -v
"""

import ast
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from ai import bedrock_client as bc  # noqa: E402
from operational import cost_governor_lambda as cg  # noqa: E402

_GOVERNOR_SRC = os.path.join(_ROOT, "lambdas", "operational", "cost_governor_lambda.py")

# The four legs every consumer prices with, plus the TTL-split write rate #2883 added.
_REQUIRED_LEGS = {"in", "out", "cache_read", "cache_write", "cache_write_1h"}


# ── 1. The live path is one object ───────────────────────────────────────────


def test_governor_prices_are_the_chokepoints_prices_not_a_copy():
    assert cg._PRICES is bc.PRICES, "the governor must IMPORT the registry, never re-copy it"


def test_titan_is_priced_at_its_published_rate_in_both_halves_of_the_ratio():
    """The regression this issue's numerator error was made of.

    Before the fix `cg._price_for` returned the fable tier for Titan. $10/1M vs
    $0.02/1M is 500x, and it landed entirely in the drift ratio's numerator.
    """
    titan = "amazon.titan-embed-text-v2:0"
    assert cg._price_for(titan)["in"] == 0.02
    assert bc._price_for(titan)["in"] == 0.02
    assert cg._price_for(titan) is not cg._DEFAULT_PRICE


def test_every_family_carries_every_priced_leg():
    for family, price in bc.PRICES.items():
        assert set(price.keys()) >= _REQUIRED_LEGS, f"{family} is missing a priced token leg"


def test_one_hour_cache_write_is_dearer_than_five_minute():
    """A 1h write is billed at 2x base input, a 5m write at 1.25x. Encoding them as the
    same number is a silent 37.5% under-count on any caller that asks for `ttl="1h"`."""
    for family, price in bc.PRICES.items():
        if price["cache_write"] == 0:  # titan: an embedding model has no cache tier at all
            assert price["cache_read"] == 0 and price["cache_write_1h"] == 0
            continue
        assert price["cache_write_1h"] > price["cache_write"] > price["cache_read"]
        assert abs(price["cache_write"] - price["in"] * 1.25) < 1e-9
        assert abs(price["cache_write_1h"] - price["in"] * 2.0) < 1e-9


def test_unknown_model_still_prices_as_the_most_expensive_tier():
    """The conservative default is for models we do not RECOGNISE. Fixing Titan must not
    have loosened it — an unmapped model must still never under-report."""
    assert cg._price_for("some-model-from-2027") is cg._DEFAULT_PRICE
    assert bc._price_for("some-model-from-2027") is bc._DEFAULT_PRICE
    assert cg._DEFAULT_PRICE["in"] == max(p["in"] for p in bc.PRICES.values())


# ── 2. The degraded path cannot become a second table ────────────────────────


def _fallback_literal_from_source() -> dict:
    """AST-parse `_BEDROCK_PRICES = {...}` out of the governor's `except ImportError`
    branch. Read from source rather than from the imported module because the import
    SUCCEEDS in this test process — the fallback is never bound, so there is no runtime
    object to compare. That is exactly why it needs a guard: it is unreachable code that
    goes stale invisibly."""
    with open(_GOVERNOR_SRC, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for stmt in handler.body:
                if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_BEDROCK_PRICES" for t in stmt.targets):
                    return ast.literal_eval(stmt.value)
    raise AssertionError("no `_BEDROCK_PRICES = {...}` fallback found in an except handler")


def test_packaging_drift_fallback_equals_the_registry():
    assert _fallback_literal_from_source() == bc.PRICES
