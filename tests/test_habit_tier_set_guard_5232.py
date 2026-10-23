"""#5232 - guard the SET: no raw `tier` read from a registry meta is compared as a number.

A habit_registry row can store `tier` as a string (2026-10-20); `meta.get("tier", 2) > 1` then
raises. The reads go through `common.habit_registry.habit_tier`. This sweeps lambdas/ + mcp/
for a `.get("tier"...)` / `["tier"]` read that is compared with an int literal or with an
ordering operator. Character/budget/evidence tiers are strings or already int()-wrapped, so
they never match; a genuine new numeric tier compare must use the accessor or be allowlisted
with a reason.
"""

# premerge-gate: sweeps every lambdas/ and mcp/ module with ast.parse; a new raw tier compare must red the merge
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST: dict[tuple[str, int], str] = {}  # (relative path, line) -> why the tier there is not a registry value
ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _is_tier_read(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == "tier"
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "tier"
    return False


def _numeric(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def offenders(source: str):
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        if not any(_is_tier_read(s) for s in sides):
            continue
        if any(_numeric(s) for s in sides) or any(isinstance(op, ORDERING) for op in node.ops):
            out.append(node.lineno)
    return out


def test_no_raw_registry_tier_compare_in_lambdas():
    found = []
    for base in ("lambdas", "mcp"):
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "lambdas/common/habit_registry.py":
                continue
            for line in offenders(path.read_text()):
                if (rel, line) not in ALLOWLIST:
                    found.append(f"{rel}:{line}")
    assert not found, "raw tier compare - route through common.habit_registry.habit_tier: " + ", ".join(found)


def test_guard_can_fail():
    assert offenders('x = meta.get("tier", 2) > 1') == [1]
    assert offenders('x = m["tier"] == 0') == [1]
    assert offenders("x = habit_tier(m) > 1") == []
    assert offenders('x = ch.get("tier") == "Foundation"') == []
