"""tests/test_food_delivery_gate_2233.py — #2233: the food_delivery partition's THIRD
door, and the first one that was actually PUBLISHING rather than merely unguarded.

`lambdas/emails/daily_brief_lambda.py::get_food_delivery_brief_signal` reads the
`food_delivery` STREAK#current record and appends a delivery-derived sentence into
`group_narratives["nutrition"]`, which `lambdas/content/site_writer.py` writes
verbatim into the PUBLIC, unauthenticated `public_stats.json` (served at the site
root, not `/generated/public_stats.json` — the path that made the earlier #2209
sweep miss it). No hop on that path consulted
`web.site_api_common.nutrition_delivery_public()`, the P2.3 private-by-default flag
its two siblings (`site_api_meals.food_delivery_overview`,
`site_api_nutrition`'s reader) already gate behind (#2209/#2210).

Two guards, matching the shape of #2209's own test (and the repo's now-standing
"guard the SET, not the instance" convention — #2203/#2206/#2209/#2211/#2212):

  1. Behavioral / mutation-provable: with the flag off (default), BOTH
     `get_food_delivery_brief_signal` (daily_brief_lambda) and its sibling
     `get_food_delivery_digest_line` (weekly_digest_lambda — found ungated by the
     structural derivation below while writing this test; it has no call site
     today, but the gate lives in the function itself so wiring it up later can't
     reopen this door) never touch the DynamoDB partition and return None. With
     the flag on, both actually query and return the expected narrative — proving
     the branch goes both ways rather than the query being permanently dead code.

  2. Structural / guard-the-SET: every raw reader of the `food_delivery` DDB
     partition across the ENTIRE `lambdas/` tree is derived by an AST walk — not
     hand-enumerated to today's known functions — and each must have a
     `nutrition_delivery_public()` check (directly, or via a module-level name
     assigned from it, e.g. `_DELIVERY_PUBLIC = nutrition_delivery_public()`)
     earlier in its enclosing function than the read. Two files are reviewed and
     explicitly exempted, with the reasoning inline below:
       - `lambdas/ingestion/food_delivery_lambda.py` — the PRODUCER (writes the
         partition via put_item), not a disclosure surface.
       - `lambdas/compute/character_sheet_lambda.py::get_food_delivery_modifier` —
         reads STREAK#current only to compute an internal 0.85-1.10x scoring
         multiplier fed into the character engine as a `raw_score_modifiers`
         ENGINE INPUT (#961); `lambdas/web/site_api_character.py` does not surface
         `raw_score_modifiers` (or any streak_days/last_order_date field derived
         from it) in any public response — verified by grep at review time
         (2026-08-08). If that ever changes, this file must be un-exempted.

     A fourth reader added later anywhere in `lambdas/` without a gate reds this
     test automatically — no allowlist to remember to update.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"

# Reviewed + exempted from the structural guard below — see module docstring.
_EXEMPT = {
    (LAMBDAS / "ingestion" / "food_delivery_lambda.py").resolve(),
    (LAMBDAS / "compute" / "character_sheet_lambda.py").resolve(),
}

_QUERY_SOURCE_READERS = {"_query_source", "_latest_item", "_latest_item_asof"}
_GATE_FN_NAME = "nutrition_delivery_public"


# ---------------------------------------------------------------------------
# Guard 1 — behavioral, mutation-provable
# ---------------------------------------------------------------------------


def _leaking_fake_table():
    """A get_item stub that WOULD leak a real-shaped streak record if the gate
    were bypassed — a false-negative-proof fixture, not an empty stub."""
    fake = MagicMock()
    fake.get_item.return_value = {
        "Item": {
            "streak_days": 3,
            "last_order_date": "2026-03-25",
            "last_order_merchant": "DoorDash",
        }
    }
    return fake


def test_daily_brief_signal_never_queries_partition_when_flag_off(monkeypatch):
    monkeypatch.delenv("NUTRITION_DELIVERY_PUBLIC", raising=False)
    import daily_brief_lambda as m

    fake_table = _leaking_fake_table()
    monkeypatch.setattr(m, "table", fake_table)

    result = m.get_food_delivery_brief_signal()

    fake_table.get_item.assert_not_called()
    assert result is None


def test_daily_brief_signal_queries_partition_when_flag_on(monkeypatch):
    monkeypatch.setenv("NUTRITION_DELIVERY_PUBLIC", "true")
    import daily_brief_lambda as m

    fake_table = _leaking_fake_table()
    monkeypatch.setattr(m, "table", fake_table)

    result = m.get_food_delivery_brief_signal()

    fake_table.get_item.assert_called_once()
    assert result == "Delivery-free streak: 3 days."


def test_weekly_digest_line_never_queries_partition_when_flag_off(monkeypatch):
    monkeypatch.delenv("NUTRITION_DELIVERY_PUBLIC", raising=False)
    import weekly_digest_lambda as m

    fake_table = _leaking_fake_table()
    monkeypatch.setattr(m, "table", fake_table)

    result = m.get_food_delivery_digest_line()

    fake_table.get_item.assert_not_called()
    assert result is None


def test_weekly_digest_line_queries_partition_when_flag_on(monkeypatch):
    monkeypatch.setenv("NUTRITION_DELIVERY_PUBLIC", "true")
    import weekly_digest_lambda as m

    fake_table = _leaking_fake_table()
    monkeypatch.setattr(m, "table", fake_table)

    result = m.get_food_delivery_digest_line()

    fake_table.get_item.assert_called_once()
    assert result == "Delivery-free streak: 3 days"


# ---------------------------------------------------------------------------
# Guard 2 — structural, guard-the-SET
# ---------------------------------------------------------------------------


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _joined_str_contains(node: ast.JoinedStr, marker: str) -> bool:
    return any(isinstance(v, ast.Constant) and isinstance(v.value, str) and marker in v.value for v in node.values)


def _callee_name(call: ast.Call):
    """Resolve a Call's callee to a name for both shapes seen in this repo: a
    bare Name (direct import, or after `x = _g["_query_source"]`), a
    `_g["_query_source"](...)` subscript indirection, or a `table.get_item(...)`
    attribute access."""
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
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


def _get_item_targets_food_delivery(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg != "Key":
            continue
        for sub in ast.walk(kw.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "SOURCE#food_delivery" in sub.value:
                return True
            if isinstance(sub, ast.JoinedStr) and _joined_str_contains(sub, "SOURCE#food_delivery"):
                return True
    return False


def _reads_food_delivery_partition(call: ast.Call) -> bool:
    name = _callee_name(call)
    if name in _QUERY_SOURCE_READERS and _first_arg_is_food_delivery(call):
        return True
    if name == "get_item" and _get_item_targets_food_delivery(call):
        return True
    return False


def _module_gate_aliases(tree: ast.AST) -> set[str]:
    """Names anywhere in the module bound to a call to nutrition_delivery_public
    (e.g. `_DELIVERY_PUBLIC = nutrition_delivery_public()`), so an `if
    _DELIVERY_PUBLIC:` check downstream is recognized as a real gate."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            fn_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if fn_name == _GATE_FN_NAME:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)
    return aliases


def _references_gate(node: ast.AST, aliases: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and (sub.id == _GATE_FN_NAME or sub.id in aliases):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == _GATE_FN_NAME:
            return True
    return False


def _gate_check_linenos(func, aliases: set[str]) -> list[int]:
    out = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if _references_gate(test, aliases):
            out.append(node.lineno)
    return out


def _iter_food_delivery_reader_call_sites():
    """Yield (path, enclosing FunctionDef, call.lineno, aliases) for every static
    call site in lambdas/ (minus the reviewed exemptions) that reads the
    food_delivery DDB partition. Derived by AST walk — NOT a hardcoded module
    list."""
    sites = []
    for path in sorted(LAMBDAS.rglob("*.py")):
        if path.resolve() in _EXEMPT:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        aliases = _module_gate_aliases(tree)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and _reads_food_delivery_partition(node):
                    sites.append((path, func, node.lineno, aliases))
    return sites


def test_food_delivery_reader_derivation_is_non_vacuous():
    """The AST probe itself must find real call sites today — otherwise the
    guard below would pass by finding nothing, which is not a guard at all."""
    sites = _iter_food_delivery_reader_call_sites()
    found = {p.relative_to(ROOT).as_posix() for p, _f, _l, _a in sites}
    expected_subset = {
        "lambdas/web/site_api_nutrition.py",
        "lambdas/web/site_api_meals.py",
        "lambdas/emails/daily_brief_lambda.py",
        "lambdas/emails/weekly_digest_lambda.py",
    }
    missing = expected_subset - found
    assert not missing, f"expected food_delivery readers not found by the AST probe (probe may have broken): {missing}"


def test_every_food_delivery_reader_is_gated():
    """Guard the SET (#2233 AC): every derived reader of the food_delivery
    partition anywhere in lambdas/ must check nutrition_delivery_public()
    (directly or via a module-level alias) before it reads. A reader added
    later without gating reds this test automatically — no allowlist to
    remember to update."""
    call_sites = _iter_food_delivery_reader_call_sites()
    assert call_sites, "derivation found no food_delivery readers in lambdas/ (outside reviewed exemptions) — the probe is broken"

    ungated = []
    for path, func, call_lineno, aliases in call_sites:
        guard_lines = _gate_check_linenos(func, aliases)
        if not any(ln < call_lineno for ln in guard_lines):
            ungated.append(f"{path.relative_to(ROOT).as_posix()}::{func.name} (line {call_lineno})")

    assert not ungated, (
        "the following food_delivery partition readers have no nutrition_delivery_public() "
        f"gate earlier in their function: {ungated} — every reader of this partition must "
        "check web.site_api_common.nutrition_delivery_public() before querying"
    )
