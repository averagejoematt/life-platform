#!/usr/bin/env python3
"""scripts/check_test_clock_literals.py -- #4848: a test that pins a literal through an unfrozen clock.

THE CLASS (incident 2026-10-12T00:00Z)
  ``tests/test_energy_budget_cross_phase_4032.py`` asserted ``tdee == 2426`` while
  ``health.tdee.resolve_age`` measures a fractional age against the wall clock; the BMR's
  ``-5 * age`` term stepped one kcal at the instant the subject's age crossed a rounding
  edge and main went red with no code change.  The expected number was a function of "now".

WHAT THIS SWEEP DECIDES (an AST walk, no phrase grep -- #2959)
  1. CLOCK-SCALED PRODUCERS.  A function under ``lambdas/`` or ``mcp/`` that reads the wall
     clock (``datetime.now/utcnow/today``, ``date.today``, ``time.time``, ``pacific_now``...)
     AND scales an elapsed span to a unit (``<x>.days / 365.25``, ``.total_seconds() / 3600``):
     an AGE, a number of hours since, a week index.  These move a pinned literal slowly and
     silently, which is exactly why they hide for months.  Callers of a producer (one hop)
     are producers too: ``_get_energy_expenditure`` reaches ``resolve_age`` that way.
  2. A TEST MODULE is a MEMBER when it asserts a numeric literal (``== 2426``,
     ``== pytest.approx(3.5)``), makes a call that statically resolves to a producer, and
     passes none of the producer's injectable clock arguments (``now``/``ref``/``today``...).
  3. A member is CLEARED by a freeze: ``freezegun``/``freeze_time``, or a
     ``monkeypatch.setattr`` / ``patch`` whose target names the clock or the producer, or a
     ``# clock-literal-ok: <reason>`` comment saying why the literal is independent of "now".

NOT COVERED (stated, not hidden): a producer reached through importlib/``sys.modules`` loading
or two or more hops away, a clock read that never scales an elapsed span (a pure timestamp),
and a literal derived from the clock in the test body itself.  Also not recognised: a pin
written as a named constant (``== EXPECTED``), ``assertEqual`` or ``abs(x - k) < tol``; a freeze
or a ``# clock-literal-ok:`` marker is MODULE-wide, so one anywhere clears every pin in that
module (a freeze is read from the patch target only, never the replacement value).  This is a lead-finder with a
named recall bound; widening it is a new issue, not a silent claim.

USAGE
    python3 scripts/check_test_clock_literals.py          # print members, exit 1 if any
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

REPO = pathlib.Path(__file__).resolve().parents[1]

PROD_GLOBS = ("lambdas/**/*.py", "mcp/**/*.py")
INJECTABLE = {
    "now", "ref", "today", "as_of", "now_dt", "ref_date", "reference_date",
    "today_dt", "current_date", "now_utc", "ref_dt", "as_of_date",
}  # fmt: skip
CLOCK_ATTRS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("dt", "now"),
    ("dt", "utcnow"),
}
CLOCK_NAMES = {"pacific_now", "utcnow", "now_pt", "pacific_today", "today_pt"}
# identifiers that, as a monkeypatch/patch target, mean "the clock is controlled here"
FREEZE_TOKENS = {
    "datetime",
    "date",
    "time",
    "pacific_now",
    "pacific_today",
    "utcnow",
    "now",
    "_now",
    "today",
    "_today",
    "now_pt",
    "pt_now",
    "clock",
}
MARKER = re.compile(r"#\s*clock-literal-ok:\s*(\S.{6,})")

Key = Tuple[str, str]  # (module stem, function name)


def _is_clock(n: ast.AST) -> bool:
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    if isinstance(f, ast.Name):
        return f.id in CLOCK_NAMES
    if isinstance(f, ast.Attribute):
        v = f.value
        owner = v.id if isinstance(v, ast.Name) else (v.attr if isinstance(v, ast.Attribute) else None)
        return (owner, f.attr) in CLOCK_ATTRS or f.attr in ("pacific_now", "pacific_today")
    return False


def _is_elapsed(n: ast.AST) -> bool:
    return (isinstance(n, ast.Attribute) and n.attr == "days") or (
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "total_seconds"
    )


def _is_scaled_elapsed(n: ast.AST) -> bool:
    return (
        isinstance(n, ast.BinOp)
        and isinstance(n.op, (ast.Div, ast.FloorDiv))
        and isinstance(n.right, ast.Constant)
        and isinstance(n.right.value, (int, float))
        and n.right.value > 1
        and any(_is_elapsed(m) for m in ast.walk(n.left))
    )


def _stem(p: pathlib.Path) -> str:
    return p.stem if p.stem != "__init__" else p.parent.name


def _imports(tree: ast.AST) -> Dict[str, Tuple[str, Optional[str]]]:
    m: Dict[str, Tuple[str, Optional[str]]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                m[a.asname or a.name] = (n.module.split(".")[-1], a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                m[a.asname or a.name.split(".")[0]] = (a.name.split(".")[-1], None)
    return m


def _resolve(call: ast.Call, imp: Dict[str, Tuple[str, Optional[str]]], own: str) -> Optional[Key]:
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in imp and imp[f.id][1]:
            return (imp[f.id][0], imp[f.id][1])  # type: ignore[return-value]
        return (own, f.id)
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in imp:
        mod, name = imp[f.value.id]
        return (name or mod, f.attr)
    return None


def build_producers(repo: pathlib.Path = REPO) -> Tuple[Set[Key], Dict[Key, List[Tuple[str, int]]], Set[str]]:
    """(producers, injectables): the clock-scaled functions and each base one's injectable params."""
    funcs: Dict[Key, Tuple[bool, List[Key], List[Tuple[str, int]]]] = {}
    for pat in PROD_GLOBS:
        for p in repo.glob(pat):
            try:
                tree = ast.parse(p.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            imp, own = _imports(tree), _stem(p)
            for f in ast.walk(tree):
                if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                a = f.args
                names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
                clock = scaled = False
                calls: List[Key] = []
                for n in ast.walk(f):
                    clock = clock or _is_clock(n)
                    scaled = scaled or _is_scaled_elapsed(n)
                    if isinstance(n, ast.Call):
                        r = _resolve(n, imp, own)
                        if r:
                            calls.append(r)
                funcs[(own, f.name)] = (clock and scaled, calls, [(x, names.index(x)) for x in names if x in INJECTABLE])
    base = {k for k, v in funcs.items() if v[0]}
    producers = set(base)
    producers |= {k for k, v in funcs.items() if k not in base and any(c in base for c in v[1])}
    return producers, {k: funcs[k][2] for k in producers}, {k[1] for k in base}


def _lit(n: ast.AST) -> bool:
    if isinstance(n, ast.Constant):
        return isinstance(n.value, (int, float)) and not isinstance(n.value, bool)
    if isinstance(n, ast.UnaryOp):
        return _lit(n.operand)
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "approx" and bool(n.args) and _lit(n.args[0])


_NOT_A_VALUE = {"statusCode", "status_code"}  # an HTTP verdict is not a clock-scaled number


def _side_is_value(side: ast.AST) -> bool:
    """False for ``len(...)`` counts and ``["statusCode"]`` verdicts -- not a number the clock scales."""
    for n in ast.walk(side):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "len":
            return False
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value in _NOT_A_VALUE:
            return False
    return True


def _literal_asserts(fn: ast.AST) -> List[Tuple[ast.AST, ast.Compare]]:
    out = []
    for a in ast.walk(fn):
        if isinstance(a, ast.Assert):
            for c in ast.walk(a.test):
                if isinstance(c, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in c.ops):
                    sides = [c.left] + c.comparators
                    if any(_lit(x) for x in sides):
                        out.append((a, c))
    return out


def _uninjected_hits(fn: ast.AST, imp, own: str, producers: Set[Key], inj, local_helpers: Set[str]) -> Set[Key]:
    hit: Set[Key] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            r = _resolve(n, imp, own)
            if r in producers:
                params = inj.get(r, [])
                if not any(any(k.arg == pn for k in n.keywords) or len(n.args) > ix for pn, ix in params):
                    hit.add(r)  # type: ignore[arg-type]
            elif isinstance(n.func, ast.Name) and n.func.id in local_helpers:
                hit.add((own, n.func.id))
    return hit


def _tokens(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.update(re.split(r"[.:/\s]+", n.value))
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _is_frozen(tree: ast.AST, src: str, producer_names: Set[str]) -> bool:
    if "freezegun" in src or "freeze_time" in src:
        return True
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name)):
            fn = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
            if fn in ("setattr", "patch", "object", "setitem", "freeze"):
                toks = set()
                # the patch TARGET only, never the replacement value: a dotted-string target
                # ("a.b.c", value) is args[0] alone; (obj, "attr", value) is args[0..1]
                first = n.args[0] if n.args else None
                dotted = isinstance(first, ast.Constant) and isinstance(first.value, str)
                for arg in n.args[: 1 if dotted else 2]:
                    toks |= _tokens(arg)
                if toks & (FREEZE_TOKENS | producer_names):
                    return True
    return False


def scan_source(src: str, name: str, producers: Set[Key], inj: Dict[Key, List[Tuple[str, int]]], base_names: Set[str] = frozenset()) -> Optional[List[Key]]:  # type: ignore[assignment]
    """The producer calls whose RESULT a literal assert pins, or None when the module is not a member."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    if MARKER.search(src):
        return None
    imp, own = _imports(tree), pathlib.Path(name).stem
    funcs = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    # one hop inside the test module: a helper that calls a producer is a producer to its callers
    helpers = {f.name for f in funcs if not f.name.startswith("test") and _uninjected_hits(f, imp, own, producers, inj, set())}
    member: Set[Key] = set()
    for fn in funcs:
        asserts = _literal_asserts(fn)
        if not asserts:
            continue
        tainted: Set[str] = set()
        for _ in range(2):
            for st in ast.walk(fn):
                if isinstance(st, ast.Assign) and (
                    _uninjected_hits(st.value, imp, own, producers, inj, helpers)
                    or any(isinstance(x, ast.Name) and x.id in tainted for x in ast.walk(st.value))
                ):
                    for t in st.targets:
                        tainted |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
        for _a, c in asserts:
            for side in [c.left] + c.comparators:
                if _lit(side) or not _side_is_value(side):
                    continue
                member |= _uninjected_hits(side, imp, own, producers, inj, helpers)
                if any(isinstance(x, ast.Name) and x.id in tainted for x in ast.walk(side)):
                    member |= _uninjected_hits(fn, imp, own, producers, inj, helpers)
    if not member or _is_frozen(tree, src, {k[1] for k in member} | set(base_names)):
        return None
    return sorted(member)


def sweep(repo: pathlib.Path = REPO, world=None) -> Dict[str, List[Key]]:
    producers, inj, base_names = world if world is not None else build_producers(repo)
    out: Dict[str, List[Key]] = {}
    for p in sorted((repo / "tests").rglob("*.py")):
        r = scan_source(p.read_text(), p.name, producers, inj, base_names)
        if r:
            out[str(p.relative_to(repo))] = r
    return out


def main() -> int:
    members = sweep()
    for path, keys in members.items():
        print(f"{path}: {', '.join(f'{m}.{f}' for m, f in keys)}")
    print(f"clock-literal members: {len(members)}")
    return 1 if members else 0


if __name__ == "__main__":
    sys.exit(main())
