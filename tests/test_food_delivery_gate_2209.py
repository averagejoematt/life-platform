"""tests/test_food_delivery_gate_2209.py — #2209: privacy gate parity between the two
readers of the `food_delivery` DDB partition.

Two modules query `USER#matthew#SOURCE#food_delivery`. `site_api_nutrition.py` gated
it behind `NUTRITION_DELIVERY_PUBLIC` (default OFF — "the delivery source is never
queried and nothing private enters the response"). `site_api_meals.food_delivery_overview`
queried the same partition with NO flag check at all and published
`total_spend_30d` / `avg_spend` / `binge_days_30d` / a per-platform breakdown on a
public route. Both readers now share ONE parsing helper,
`web.site_api_common.nutrition_delivery_public()`, and both check it BEFORE querying.

Two guards, matching the two ways this class of bug has shipped before in this repo
(#2203, #2206, and this issue — "guard the SET, not the instance"):

  1. Behavioral / mutation-provable (AC2): with the flag off, `food_delivery_overview`
     never calls the query helper for "food_delivery" and returns the honest-null
     shape `{"food_delivery": None}` — matching the sibling's documented promise
     byte-for-byte. Proven by deliberately deleting the gate and confirming this test
     goes RED (see the PR body for the exact mutation-proof transcript).

  2. Structural / guard-the-SET (AC3): every call site in `lambdas/web/` that reads
     the food_delivery partition (via `_query_source`, `_latest_item`, or
     `_latest_item_asof` — the three source-reading helpers `site_api_common`
     exposes, called either directly or through the `_g["<helper>"]`
     handler-injection indirection used throughout this package) is DERIVED by an
     AST walk over the source tree, NOT hardcoded to today's two known modules. Each
     derived call site must sit inside a function that also checks the shared
     `_DELIVERY_PUBLIC` flag (directly or via `not`) on a line BEFORE the query call.
     A third module added later that reads this partition without gating reds this
     test the moment it's written — it does not depend on anyone remembering to
     update an allowlist.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from web import site_api_meals  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "lambdas" / "web"

# The source-reading helpers site_api_common exposes to every split handler module,
# either imported directly or received through the `_g["<name>"]` indirection.
_SOURCE_READERS = {"_query_source", "_latest_item", "_latest_item_asof"}

# The shared gate flag name both readers bind their module-level constant to
# (`_DELIVERY_PUBLIC = nutrition_delivery_public()`).
_FLAG_NAME = "_DELIVERY_PUBLIC"


# ---------------------------------------------------------------------------
# Guard 1 — behavioral, mutation-provable (AC2)
# ---------------------------------------------------------------------------


def test_food_delivery_overview_never_queries_partition_when_flag_off(monkeypatch):
    monkeypatch.setattr(site_api_meals, "_DELIVERY_PUBLIC", False)

    queried_sources = []

    def _tracking_query_source(source, start, end, *a, **kw):
        queried_sources.append(source)
        # Deliberately return something that WOULD leak private fields if the gate
        # were bypassed — a false-negative-proof fixture, not an empty stub.
        return [{"amount": 1, "platform": "DoorDash", "binge": True, "date": "2026-08-01"}]

    _g = {
        "_query_source": _tracking_query_source,
        "_experiment_date": lambda days_back=30: "2026-07-01",
    }

    result = site_api_meals.food_delivery_overview(_g=_g)
    body = json.loads(result["body"])

    assert "food_delivery" not in queried_sources, (
        "food_delivery_overview queried the food_delivery partition with "
        "NUTRITION_DELIVERY_PUBLIC off — the gate must sit BEFORE the query"
    )
    assert body["food_delivery"] is None
    assert "platform_breakdown" not in body
    assert "weekly_trend" not in body


def test_food_delivery_overview_queries_partition_when_flag_on(monkeypatch):
    """Sanity companion: the flag actually re-enables the query — proves the branch
    goes both ways rather than the query being permanently dead code."""
    monkeypatch.setattr(site_api_meals, "_DELIVERY_PUBLIC", True)

    queried_sources = []

    def _tracking_query_source(source, start, end, *a, **kw):
        queried_sources.append(source)
        return []

    _g = {
        "_query_source": _tracking_query_source,
        "_experiment_date": lambda days_back=30: "2026-07-01",
    }

    result = site_api_meals.food_delivery_overview(_g=_g)
    body = json.loads(result["body"])

    assert "food_delivery" in queried_sources
    assert body["food_delivery"] is None  # no items in the fixture — honest empty, not an error


# ---------------------------------------------------------------------------
# Guard 2 — structural, guard-the-SET (AC3)
# ---------------------------------------------------------------------------


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _callee_name(call: ast.Call) -> str | None:
    """Resolve the callee of a Call node to one of _SOURCE_READERS for both call
    shapes seen in lambdas/web/: a bare Name (after `x = _g["_query_source"]`) or the
    direct subscript-call indirection `_g["_query_source"](...)`."""
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Subscript):
        key = fn.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    return None


def _first_arg_is_food_delivery(call: ast.Call) -> bool:
    if not call.args:
        return False
    first = call.args[0]
    return isinstance(first, ast.Constant) and first.value == "food_delivery"


def _iter_food_delivery_reader_call_sites():
    """Yield (path, enclosing FunctionDef, call.lineno) for every static call site in
    lambdas/web/ that reads the food_delivery DDB partition. Derived by AST walk —
    NOT a hardcoded module list."""
    sites = []
    for path in sorted(WEB.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                if _callee_name(node) not in _SOURCE_READERS:
                    continue
                if _first_arg_is_food_delivery(node):
                    sites.append((path, func, node.lineno))
    return sites


def _flag_guard_linenos(func: ast.AST) -> list[int]:
    """Linenos of every `if` statement inside `func` whose test references the
    shared _DELIVERY_PUBLIC flag, directly or negated (`if _DELIVERY_PUBLIC:` /
    `if not _DELIVERY_PUBLIC:`)."""
    out = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if isinstance(test, ast.Name) and test.id == _FLAG_NAME:
            out.append(node.lineno)
    return out


def test_food_delivery_reader_derivation_is_non_vacuous():
    """The AST probe itself must find real call sites today — otherwise the guard
    below would pass by finding nothing, which is not a guard at all."""
    sites = _iter_food_delivery_reader_call_sites()
    found_modules = {p.name for p, _f, _l in sites}
    assert found_modules == {"site_api_nutrition.py", "site_api_meals.py"}, (
        f"expected the derivation to find exactly the two known food_delivery readers, got {found_modules} — "
        "either the AST probe broke or a reader was added/removed and this test's expectation needs an update"
    )


def test_every_food_delivery_reader_is_gated():
    """Guard the SET (#2209 AC3): every derived reader must check the shared
    _DELIVERY_PUBLIC flag before querying. A third reader added later without
    gating reds this test automatically — no allowlist to remember to update."""
    call_sites = _iter_food_delivery_reader_call_sites()
    assert call_sites, "derivation found no food_delivery readers in lambdas/web/ — the probe is broken"

    ungated = []
    for path, func, call_lineno in call_sites:
        guard_lines = _flag_guard_linenos(func)
        if not any(ln < call_lineno for ln in guard_lines):
            ungated.append(f"{path.relative_to(ROOT)}::{func.name} (line {call_lineno})")

    assert not ungated, (
        "the following food_delivery partition readers have no _DELIVERY_PUBLIC gate "
        f"earlier in their function: {ungated} — every reader of this partition must "
        "check the shared flag (web.site_api_common.nutrition_delivery_public()) before querying"
    )
