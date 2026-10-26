"""tests/test_hevy_cardio_never_summed_5369.py — no module adds Hevy cardio minutes to wearable minutes (#5369 box 3).

A Hevy cycling block and the watch's (or WHOOP's) recording of the same ride are the SAME minutes.
`training.zone2_minutes` reports the Hevy block as `hevy_cardio_minutes` beside the wearable sessions
(`session_minutes`, served as `total_exercise_min`), and the owner ruled 2026-10-25/26 that Hevy is the
one routine source whose echoes count once. On main 2019fab3e no consumer summed the two buckets —
but nothing pinned it. This guards the SET, not an instance: every module under `lambdas/` and
`mcp/`, parsed, so a new consumer that writes `session_minutes + hevy_cardio_minutes` (or `+=` one
into the other, or builds a `total_exercise_min` from a Hevy cardio figure) reds CI wherever it is.

The detector reads the AST (comments and docstrings cannot trip it) and flags:
  * `a + b` where one operand names a Hevy cardio quantity and the other a wearable one;
  * an assignment / augmented assignment whose TARGET names a wearable quantity and whose VALUE
    names a Hevy cardio one;
  * a dict entry or keyword argument keyed by a wearable quantity whose VALUE names a Hevy cardio one.
Mutation controls run the detector over planted snippets of each shape.
"""

# premerge-gate: sweeps every module under lambdas/ and mcp/ — a repo-shape ratchet whose verdict depends only on the tree

from __future__ import annotations

import ast
import functools
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("lambdas", "mcp")
HEVY_CARDIO = frozenset({"hevy_cardio_min", "hevy_cardio_minutes"})
WEARABLE = frozenset({"total_exercise_min", "session_minutes"})


def _names(node: ast.AST) -> set[str]:
    """Every identifier, attribute or string constant inside `node`."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
    return out


def _mentions(node: ast.AST | None, vocab: frozenset[str]) -> bool:
    return node is not None and bool(_names(node) & vocab)


def offenders(source: str | ast.AST, rel: str = "<snippet>") -> list[str]:
    """`rel:line` for every place `source` (text or a parsed tree) adds a Hevy cardio quantity to a wearable one."""
    try:
        tree = ast.parse(source) if isinstance(source, str) else source
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        bad = False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left_h, right_h = _mentions(node.left, HEVY_CARDIO), _mentions(node.right, HEVY_CARDIO)
            left_w, right_w = _mentions(node.left, WEARABLE), _mentions(node.right, WEARABLE)
            bad = (left_h and right_w) or (right_h and left_w)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bad = any(_mentions(t, WEARABLE) for t in targets) and _mentions(node.value, HEVY_CARDIO)
        elif isinstance(node, ast.Dict):
            bad = any(
                isinstance(k, ast.Constant) and k.value in WEARABLE and _mentions(v, HEVY_CARDIO) for k, v in zip(node.keys, node.values)
            )
        elif isinstance(node, ast.keyword):
            bad = node.arg in WEARABLE and _mentions(node.value, HEVY_CARDIO)
        if bad:
            hits.append(f"{rel}:{getattr(node, 'lineno', '?')}")
    return hits


@functools.lru_cache(maxsize=1)
def _parsed() -> tuple[int, tuple[tuple[str, ast.AST], ...]]:
    """(modules swept, (rel path, tree) for every module whose text names a Hevy cardio quantity) —
    a module that never names one cannot add it to anything, so only those are parsed."""
    swept = 0
    out = []
    for top in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache", "node_modules"}]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                swept += 1
                with open(full, encoding="utf-8") as fh:
                    text = fh.read()
                if "hevy_cardio_min" not in text:
                    continue
                try:
                    out.append((os.path.relpath(full, ROOT).replace(os.sep, "/"), ast.parse(text)))
                except SyntaxError:
                    continue
    return swept, tuple(out)


def test_no_module_adds_hevy_cardio_minutes_to_wearable_minutes():
    swept, modules = _parsed()
    assert swept > 200, f"the sweep read only {swept} modules — the scan root moved"
    found = [hit for rel, tree in modules for hit in offenders(tree, rel)]
    assert not found, (
        "Hevy cardio minutes added to wearable minutes — a Hevy block and the wearable's record of it are the "
        f"same minutes (#5369; report them side by side): {found}"
    )


def test_the_population_is_live():
    """The guard is not vacuous: both vocabularies exist in the swept tree (a rename would empty it)."""
    seen: set[str] = set()
    for _rel, tree in _parsed()[1]:
        seen |= _names(tree)
    assert HEVY_CARDIO & seen and WEARABLE & seen, (HEVY_CARDIO & seen, WEARABLE & seen)


def test_every_shape_of_the_sum_is_caught():
    """Mutation controls: each planted shape reds; the side-by-side report that is the rule does not."""
    planted = {
        "binop": "x = w['session_minutes'] + b['hevy_cardio_minutes']\n",
        "binop_reversed": "x = hevy_cardio_min + total_exercise_min\n",
        "augassign": "w['session_minutes'] += b['hevy_cardio_minutes']\n",
        "assign": "total_exercise_min = round(z2 + hevy_cardio_min, 1)\n",
        "dict": "out = {'total_exercise_min': w['session_minutes'] + w['hevy_cardio_minutes']}\n",
        "keyword": "f(total_exercise_min=week.hevy_cardio_minutes)\n",
    }
    for shape, src in planted.items():
        assert offenders(src), f"the {shape} shape was not caught: {src!r}"
    clean = (
        "out = {'total_exercise_min': w['session_minutes'], 'hevy_cardio_min': w['hevy_cardio_minutes']}\n"
        "w['hevy_cardio_minutes'] += b['minutes']\n"
        "# session_minutes + hevy_cardio_minutes in a comment is not code\n"
    )
    assert offenders(clean) == []
