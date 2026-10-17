"""tests/test_pure_calculator_registry_4892.py — the registry of PURE CALCULATOR modules, and
the rule that each one carries a Hypothesis property test (#4892; craft review 2026-10-13
finding 18, persisting D8-1).

WHY A REGISTRY
--------------
The property tier (tests/test_prop_*.py, #1664 / epic #1648) was well aimed but nobody kept
a list of WHICH modules belong in it, so the platform's most-served calculator —
lambdas/common/stats_core.py, behind every correlation, interval, p-value and forecast a
reader sees — sat outside it. A module is a pure calculator when its own docstring says it
is pure (no I/O, no clock, no randomness beyond a fixed seed) and its outputs are served as
numbers. Such a module joins `PURE_CALCULATORS` with the property test that proves its
invariants; this file then holds both directions:

  * every registered module exists, and its property test exists, uses Hypothesis
    (`@given`) and actually imports the module it claims to cover;
  * every tests/test_prop_*.py is claimed by a registry entry — a new property file names
    the calculator it covers here, so the registry cannot drift from the tier.

`registry_offenders` is a pure function over (root, registry) so the decision can be
mutation-proved against a synthetic tree (`test_registry_rule_reds_on_*`), never only
watched passing on the real one.

TO ADD A CALCULATOR: write tests/test_prop_<module>.py (Hypothesis, max_examples modest,
deadline=None, database=None; properties read off the module's docstrings, never invented)
and add one line below.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# module path (repo-relative) -> its property test (repo-relative). stats_core first: it is
# the one sanctioned statistics module (ADR-105) and the reason this registry exists.
PURE_CALCULATORS = {
    "lambdas/common/stats_core.py": "tests/test_prop_stats_core.py",
    "lambdas/experiment/bsts_lite.py": "tests/test_prop_bsts_lite.py",
    "lambdas/experiment/er03_gate.py": "tests/test_prop_er03_gate.py",
    "lambdas/health/achievement_rules.py": "tests/test_prop_achievement_rules.py",
    "lambdas/ai/grounded_generation.py": "tests/test_prop_grounded_generation.py",
}


def _imports_module(tree: ast.Module, module_rel: str) -> bool:
    """True when the test imports the module (as `from pkg import mod` or `import pkg.mod`)."""
    parts = Path(module_rel).with_suffix("").parts[1:]  # drop the leading "lambdas"
    dotted = ".".join(parts)
    pkg, leaf = ".".join(parts[:-1]), parts[-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == pkg and any(a.name == leaf for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == dotted:
            return True
        if isinstance(node, ast.Import) and any(a.name == dotted for a in node.names):
            return True
    return False


def _uses_given(tree: ast.Module) -> bool:
    imports_hypothesis = any(isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "hypothesis" for n in ast.walk(tree))
    decorated = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if (isinstance(target, ast.Name) and target.id == "given") or (
                    isinstance(target, ast.Attribute) and target.attr == "given"
                ):
                    decorated = True
    return imports_hypothesis and decorated


def registry_offenders(root: Path, registry: dict[str, str]) -> list[str]:
    """Every way the registry and the property tier disagree, one line each."""
    out: list[str] = []
    for module_rel, test_rel in registry.items():
        if not (root / module_rel).is_file():
            out.append(f"{module_rel}: registered calculator does not exist — repoint or drop the entry")
            continue
        test_path = root / test_rel
        if not test_path.is_file():
            out.append(f"{module_rel}: property test {test_rel} does not exist")
            continue
        tree = ast.parse(test_path.read_text(encoding="utf-8"))
        if not _uses_given(tree):
            out.append(f"{module_rel}: {test_rel} has no Hypothesis @given test — it is not a property test")
        if not _imports_module(tree, module_rel):
            out.append(f"{module_rel}: {test_rel} never imports the module it is registered as covering")
    claimed = set(registry.values())
    for prop_file in sorted((root / "tests").glob("test_prop_*.py")):
        rel = prop_file.relative_to(root).as_posix()
        if rel not in claimed:
            out.append(f"{rel}: property test not claimed by any PURE_CALCULATORS entry — register its calculator")
    return out


def test_every_registered_pure_calculator_has_a_property_test():
    offenders = registry_offenders(REPO, PURE_CALCULATORS)
    assert not offenders, "PURE_CALCULATORS and the property tier disagree:\n  " + "\n  ".join(offenders)


def test_stats_core_is_registered_first():
    assert next(iter(PURE_CALCULATORS)) == "lambdas/common/stats_core.py"


# ── mutation proofs: the rule reds on each failure shape, against a synthetic tree ──

_GOOD_TEST = (
    "from hypothesis import given, strategies as st\nfrom pkg import calc\n\n\n@given(st.integers())\ndef test_x(x):\n    calc.f(x)\n"
)


def _tree(tmp_path: Path, test_src: str | None = _GOOD_TEST, module: bool = True, extra_prop: bool = False) -> Path:
    (tmp_path / "lambdas" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    if module:
        (tmp_path / "lambdas" / "pkg" / "calc.py").write_text("def f(x):\n    return x\n")
    if test_src is not None:
        (tmp_path / "tests" / "test_prop_calc.py").write_text(test_src)
    if extra_prop:
        (tmp_path / "tests" / "test_prop_orphan.py").write_text(_GOOD_TEST)
    return tmp_path


_REG = {"lambdas/pkg/calc.py": "tests/test_prop_calc.py"}


def test_registry_rule_is_green_on_a_well_formed_synthetic_tree(tmp_path):
    assert registry_offenders(_tree(tmp_path), _REG) == []


def test_registry_rule_reds_on_each_failure_shape(tmp_path):
    shapes = {
        "missing module": (dict(module=False), "does not exist"),
        "missing property test": (dict(test_src=None), "does not exist"),
        "no @given": (dict(test_src="from pkg import calc\n\n\ndef test_x():\n    calc.f(1)\n"), "no Hypothesis @given"),
        "does not import module": (dict(test_src=_GOOD_TEST.replace("from pkg import calc\n", "")), "never imports"),
        "unclaimed property file": (dict(extra_prop=True), "not claimed"),
    }
    silent = []
    for i, (label, (kwargs, needle)) in enumerate(shapes.items()):
        offenders = registry_offenders(_tree(tmp_path / str(i), **kwargs), _REG)
        if not any(needle in o for o in offenders):
            silent.append(f"{label}: {offenders}")
    assert not silent, "the registry rule stayed green on a broken shape:\n  " + "\n  ".join(silent)
