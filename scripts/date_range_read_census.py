#!/usr/bin/env python3
"""scripts/date_range_read_census.py — every sk date-range read in lambdas/ + mcp/, and whether
its END bound can see the END day's suffixed rows (#4129).

THE DEFECT CLASS
  A partition that carries suffixed sort keys — Hevy's per-workout rows are
  `DATE#YYYY-MM-DD#WORKOUT#<id>` — sorts every suffixed row of a day AFTER that day's bare
  `DATE#YYYY-MM-DD`. So a read written

      Key("sk").between(f"DATE#{start}", f"DATE#{end}")

  returns the suffixed rows of every day in the window EXCEPT the last one. Nothing errors;
  the window silently loses its END day. `daily-metrics-compute`'s `fetch_range` put every
  lifting session into TSB one day late, and `/api/training_overview` divided a per-muscle
  rate by 18 days while reading 17 days of sessions (#4129). The fix is a suffix on the end
  bound (`DATE#{end}~` — `~` (0x7E) sorts after `#` (0x23) and after every digit, so it
  closes the day without reaching the next one), or a `begins_with` per day.

  Adding the suffix to a read of a partition that has NO suffixed rows changes nothing at all
  (no sk lies strictly between `DATE#d` and `DATE#d~` there), so a suffix is never a risk
  on an unsuffixed partition; its ABSENCE is the risk on a suffixed one.

WHICH PARTITIONS ARE "SUFFIXED" — DERIVED, not typed
  `suffixed_sources()` reads it from the two places the repo already records sk shapes:
    1. docs/SCHEMA.md — the Sort-Key Patterns table, the Key-Family Catalog rows whose sk
       column LEADS with a `DATE#<d>#…` shape, and each per-source `### <source>` field
       reference whose body documents a `DATE#YYYY-MM-DD#…` sk.
    2. deploy/generated/pk_family_census.json — the live-measured representative sk per
       family (`lambdas/experiment/pk_census.py`, refreshed at reset); a `rep_sk` of the form
       `DATE#YYYY-MM-DD<anything>` is a suffixed row observed in the table.
  Leg 1 knows shapes the table has not been sampled for (hevy's census rep_sk happens to be a
  legacy bare daily row); leg 2 knows families nobody wrote down. Neither needs a hand list.

WHICH READS — both spellings, AST-derived
  * the resource form   `<K>("sk").between(lo, hi)` / `<K>("sk").begins_with(p)`  (any K alias)
  * the expression form `KeyConditionExpression="… sk BETWEEN :s AND :e"` with its
    `ExpressionAttributeValues` (plain or low-level `{"S": …}`), wherever the dict lives in
    the same function.
  A bound is rendered to a template: literals verbatim, local/module assignments resolved,
  anything else `{name}`. The pk is rendered the same way and its source read off
  `SOURCE#<x>` / `{USER_PREFIX}<x>`. A pk that is a function PARAMETER makes the read a
  HELPER (`fetch_range`, `site_api_common._query_source`, …): its partition is whatever a
  caller hands it, so it is held to the suffixed rule.

Run it for the member list:  python3 scripts/date_range_read_census.py [--violations]
The guard is tests/test_date_range_end_bound_4129.py.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("lambdas", "mcp")
SCHEMA_MD = REPO_ROOT / "docs" / "SCHEMA.md"
PK_CENSUS = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"

# A suffix that closes a day: anything sorting above '#' and every character a suffixed sk
# uses after the date. All of these are live in this repo — '~' dominant, U+FFFF in whoop /
# vacation_fund / routine_repo, U+00FF in mcp/tools_social, and a `#zzz` run after a
# `#journal#` / `#` sub-prefix in character_sheet / the digest journal readers. New code
# should write '~' (the house spelling); the others are recognised, not recommended.
END_SUFFIXES = ("~", "\uffff", "\u00ff")
_Z_RUN_END = re.compile(r"#z+$")

# The date-keyed family this census is about. Other families (LEARNING#, CHECKIN#, HABITDAY#,
# PRESCRIPTION#…) are date-ordered too, but none is documented with a per-day sub-row, and the
# suffixed-partition derivation below is written for DATE# shapes; they are recorded as
# `non-date-family` so the member list stays complete.
DATE_PREFIX = "DATE#"

# Separates the alternatives of a conditional (IfExp) bound in a rendered template.
ALT_SEP = " || "

_SK_BETWEEN_RE = re.compile(r"\bsk\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", re.IGNORECASE)
_SK_BEGINS_RE = re.compile(r"begins_with\s*\(\s*sk\s*,\s*(:\w+)\s*\)", re.IGNORECASE)
_PK_EQ_RE = re.compile(r"\bpk\s*=\s*(:\w+)", re.IGNORECASE)


# ── the suffixed-partition derivation ────────────────────────────────────────────


def _expand_sources(cell: str) -> list[str]:
    """`…SOURCE#hevy` → ['hevy']; `…SOURCE#{x, instagram, tiktok}` → ['x','instagram','tiktok']."""
    m = re.search(r"SOURCE#\{([^}]*)\}", cell)
    if m:
        return [s.strip().split("#", 1)[0] for s in m.group(1).split(",") if s.strip()]
    m = re.search(r"SOURCE#([a-z0-9_]+)", cell)
    return [m.group(1)] if m else []


_SUFFIXED_DATE_SHAPE = re.compile(r"DATE#(?:YYYY-MM-DD|<d>|<date>|<day>)#")


def schema_suffixed_sources(text: str | None = None) -> dict[str, str]:
    """source -> the SCHEMA.md line that documents a suffixed DATE# sk for it."""
    text = SCHEMA_MD.read_text(encoding="utf-8") if text is None else text
    out: dict[str, str] = {}
    lines = text.splitlines()
    section_source: str | None = None
    in_field_reference = False
    for i, line in enumerate(lines, 1):
        if line.startswith("## "):
            in_field_reference = line.strip().lower().startswith("## field reference by source")
            section_source = None
        elif line.startswith("### "):
            # a per-source field reference heading: `### hevy (strength training)`
            m = re.match(r"### ([a-z0-9_]+)\b", line)
            section_source = m.group(1) if (in_field_reference and m) else None
        # (a) Sort Key Patterns table: `| Hevy workout | `DATE#YYYY-MM-DD#WORKOUT#<id>` | … |`
        m = re.match(r"\|\s*([A-Za-z]+) workout\s*\|\s*`DATE#YYYY-MM-DD#", line)
        if m:
            out.setdefault(m.group(1).lower(), f"docs/SCHEMA.md:{i}")
            continue
        # (b) Key-Family Catalog row: first cell `…SOURCE#<x>` / `<sk>` whose sk LEADS suffixed.
        if line.startswith("| `") and "SOURCE#" in line:
            first = line.split("|")[1]
            if " / " in first:
                pk_cell, sk_cell = first.split(" / ", 1)
                lead = sk_cell.split("(+", 1)[0]  # parenthetical sub-items are per-source → leg (c)
                if _SUFFIXED_DATE_SHAPE.search(lead):
                    for src in _expand_sources(pk_cell):
                        out.setdefault(src, f"docs/SCHEMA.md:{i}")
            continue
        # (c) per-source field reference body documenting a suffixed sk
        if section_source and _SUFFIXED_DATE_SHAPE.search(line) and "source_sk" not in line:
            out.setdefault(section_source, f"docs/SCHEMA.md:{i}")
    return out


def census_suffixed_sources(census: dict | None = None) -> dict[str, str]:
    """source -> the live-measured rep_sk that proves a suffixed DATE# row exists."""
    if census is None:
        if not PK_CENSUS.exists():
            return {}
        census = json.loads(PK_CENSUS.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for family, row in (census.get("families") or {}).items():
        sk = str((row or {}).get("rep_sk") or "")
        if family.startswith("SOURCE#") and re.match(r"^DATE#\d{4}-\d{2}-\d{2}.", sk):
            out[family.split("SOURCE#", 1)[1]] = f"pk_family_census rep_sk {sk}"
    return out


def suffixed_sources() -> dict[str, str]:
    """The union of both legs: source -> first evidence found."""
    out = dict(census_suffixed_sources())
    for src, ev in schema_suffixed_sources().items():
        out.setdefault(src, ev)
    return dict(sorted(out.items()))


# ── rendering expressions to templates ───────────────────────────────────────────


class _Scope:
    """Name resolution for one enclosing function, the functions enclosing IT (a nested
    `def _cs_fetch(s, e)` reads its pk from the outer function's locals), then the module.
    Only the innermost function's parameters count as parameters: an outer function's
    parameter is a closure value, which is still a caller-supplied partition, so it renders
    as `{param:…}` too."""

    def __init__(self, module_assigns: dict[str, ast.expr], funcs: list[ast.AST]):
        self.module = module_assigns
        self.params: set[str] = set()
        self.local: dict[str, list[ast.expr]] = {}
        # innermost first: an inner binding shadows an outer one
        for func in funcs:
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            a = func.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, *([a.vararg] if a.vararg else []), *([a.kwarg] if a.kwarg else [])]:
                if arg.arg not in self.local:
                    self.params.add(arg.arg)
            inner: dict[str, list[ast.expr]] = {}
            for node in ast.walk(func):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            inner.setdefault(t.id, []).append(node.value)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                    inner.setdefault(node.target.id, []).append(node.value)
            for name, vals in inner.items():
                if name not in self.local and name not in self.params:
                    self.local[name] = vals


def render(expr: ast.AST | None, scope: _Scope, depth: int = 0) -> str:
    """A template of the string `expr` builds: literals verbatim, unknowns as `{name}`,
    function parameters as `{param:name}`."""
    if expr is None:
        return "{?}"
    if depth > 6:
        return "{…}"
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        parts = []
        for v in expr.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                inner = v.value
                if isinstance(inner, ast.Name):
                    parts.append(_render_name(inner.id, scope, depth, formatted=True))
                else:
                    parts.append("{" + _short(inner) + "}")
        return "".join(parts)
    if isinstance(expr, ast.IfExp):  # every branch, so a conditional end bound is judged on all of them
        a, b = render(expr.body, scope, depth + 1), render(expr.orelse, scope, depth + 1)
        return a if a == b else a + ALT_SEP + b
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return render(expr.left, scope, depth + 1) + render(expr.right, scope, depth + 1)
    if isinstance(expr, ast.Name):
        return _render_name(expr.id, scope, depth, formatted=False)
    if isinstance(expr, ast.Dict):  # low-level client value {"S": "..."}
        for k, v in zip(expr.keys, expr.values):
            if isinstance(k, ast.Constant) and k.value == "S":
                return render(v, scope, depth + 1)
    return "{" + _short(expr) + "}"


def _render_name(name: str, scope: _Scope, depth: int, formatted: bool) -> str:
    if name in scope.params:
        return "{param:" + name + "}"
    vals = scope.local.get(name)
    if vals and len(vals) == 1:
        return render(vals[0], scope, depth + 1)
    if vals:  # several assignments: resolve only if they all agree
        rendered = {render(v, scope, depth + 1) for v in vals}
        return rendered.pop() if len(rendered) == 1 else "{" + name + "}"
    if name in scope.module:
        return render(scope.module[name], scope, depth + 1)
    return "{" + name + "}"


def _short(node: ast.AST) -> str:
    try:
        s = ast.unparse(node)
    except Exception:  # pragma: no cover — unparse never fails on parsed source
        s = type(node).__name__
    return s if len(s) <= 40 else s[:37] + "..."


# ── the read record + classification ─────────────────────────────────────────────


@dataclass
class Read:
    path: str
    line: int
    func: str
    op: str  # "between" | "begins_with"
    form: str  # "resource" | "expression"
    pk: str
    lo: str
    hi: str

    @property
    def source(self) -> str | None:
        """The literal source a pk names: `…SOURCE#hevy`, or `{USER_PREFIX}hevy` /
        `{param:user_prefix}habit_scores` (a prefix placeholder followed by a literal)."""
        m = re.search(r"SOURCE#([a-z0-9_]+)", self.pk) or re.search(r"\{[^}]*prefix[^}]*\}([a-z0-9_]+)$", self.pk, re.IGNORECASE)
        return m.group(1) if m else None

    @property
    def is_helper(self) -> bool:
        """The partition itself is a caller-supplied parameter (not merely the user prefix)."""
        return self.source is None and "{param:" in self.pk

    @property
    def is_date_range(self) -> bool:
        bounds = [*self.lo.split(ALT_SEP), *self.hi.split(ALT_SEP)]
        return any(b.startswith(DATE_PREFIX) for b in bounds)

    @property
    def end_closed(self) -> bool:
        """True when the END day's suffixed rows are inside the range (every branch of a
        conditional end bound must close)."""
        if self.op == "begins_with":
            return True  # a prefix match includes every suffix of the prefix
        return all(_closes(h) for h in self.hi.split(ALT_SEP))

    def partition_class(self, suffixed: dict[str, str]) -> str:
        if self.is_helper:
            return "helper"  # the partition is supplied by the caller — any partition
        src = self.source
        if src is None:
            return "unknown"
        return "suffixed" if src in suffixed else "unsuffixed"

    def verdict(self, suffixed: dict[str, str]) -> str:
        if not self.is_date_range:
            return "non-date-family"
        if self.end_closed:
            return "ok-begins_with" if self.op == "begins_with" else "ok-suffixed-end"
        cls = self.partition_class(suffixed)
        if cls == "unsuffixed":
            return "ok-partition-has-no-suffixed-sk"
        return f"VIOLATION-{cls}"


def _closes(hi: str) -> bool:
    if hi.endswith(END_SUFFIXES) or _Z_RUN_END.search(hi):
        return True
    # an open/sentinel upper bound (`DATE#9999-12-31`) — there is no END day to close
    return hi == DATE_PREFIX + "9999-12-31"


def _module_assigns(tree: ast.Module) -> dict[str, ast.expr]:
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def _is_sk_key(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "sk"
        and not node.keywords
    )


def _find_pk_eq(expr: ast.AST | None, scope: _Scope) -> str:
    """The `<K>("pk").eq(X)` beside an sk condition in the same `&` expression."""
    if expr is None:
        return "{?}"
    for node in ast.walk(expr):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "eq"
            and isinstance(node.func.value, ast.Call)
            and node.func.value.args
            and isinstance(node.func.value.args[0], ast.Constant)
            and node.func.value.args[0].value == "pk"
            and node.args
        ):
            return render(node.args[0], scope)
    return "{?}"


def _eav_lookup(func_node: ast.AST, anchor: ast.AST, placeholder: str, scope: _Scope) -> str:
    """Resolve `:e` → its value: the nearest dict literal in the function carrying that key."""
    best: tuple[int, ast.expr] | None = None
    for node in ast.walk(func_node):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == placeholder and v is not None:
                    dist = abs(getattr(node, "lineno", 0) - getattr(anchor, "lineno", 0))
                    if best is None or dist < best[0]:
                        best = (dist, v)
        # kwargs["ExpressionAttributeValues"][":e"] = ... / eav[":e"] = ...
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == placeholder:
                dist = abs(node.lineno - getattr(anchor, "lineno", 0))
                if best is None or dist < best[0]:
                    best = (dist, node.value)
    return render(best[1], scope) if best else "{?}"


def _enclosing(parents: dict[ast.AST, ast.AST], node: ast.AST) -> list[ast.AST]:
    """Every enclosing function, innermost first ([] at module level)."""
    out = []
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(cur)
        cur = parents.get(cur)
    return out


def _is_docstring(parents: dict[ast.AST, ast.AST], node: ast.AST) -> bool:
    p = parents.get(node)
    return isinstance(p, ast.Expr)


def scan_file(path: Path, rel: str) -> list[Read]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    parents: dict[ast.AST, ast.AST] = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    mod = _module_assigns(tree)
    reads: list[Read] = []

    for node in ast.walk(tree):
        # resource form: <K>("sk").between(lo, hi) / .begins_with(p)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("between", "begins_with")
            and _is_sk_key(node.func.value)
        ):
            funcs = _enclosing(parents, node)
            func = funcs[0] if funcs else None
            scope = _Scope(mod, funcs)
            # climb the `&` chain to find the pk condition
            top: ast.AST = node
            while isinstance(parents.get(top), ast.BinOp) and isinstance(parents[top].op, ast.BitAnd):
                top = parents[top]
            pk = _find_pk_eq(top, scope)
            if pk == "{?}" and func is not None:
                # `kce = Key("pk").eq(pk)` … `kce & Key("sk")…` / kwargs[...] &= Key("sk")…
                pk = _find_pk_eq(func, scope)
            args = node.args
            lo = render(args[0], scope) if args else "{?}"
            hi = render(args[1], scope) if len(args) > 1 else ""
            reads.append(
                Read(rel, node.lineno, getattr(func, "name", "<module>"), node.func.attr, "resource", pk, lo, hi),
            )
        # expression form: "… sk BETWEEN :s AND :e" / "begins_with(sk, :p)"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and not _is_docstring(parents, node):
            text = node.value
            mb = _SK_BETWEEN_RE.search(text)
            mw = _SK_BEGINS_RE.search(text)
            if not (mb or mw):
                continue
            funcs = _enclosing(parents, node)
            if not funcs:
                continue
            func = funcs[0]
            scope = _Scope(mod, funcs)
            mpk = _PK_EQ_RE.search(text)
            pk = _eav_lookup(func, node, mpk.group(1), scope) if mpk else _eav_lookup(func, node, ":pk", scope)
            if mb:
                lo = _eav_lookup(func, node, mb.group(1), scope)
                hi = _eav_lookup(func, node, mb.group(2), scope)
                reads.append(Read(rel, node.lineno, func.name, "between", "expression", pk, lo, hi))
            if mw:
                lo = _eav_lookup(func, node, mw.group(1), scope)
                reads.append(Read(rel, node.lineno, func.name, "begins_with", "expression", pk, lo, ""))
    return reads


def census(roots: tuple[str, ...] = SCAN_ROOTS, repo_root: Path = REPO_ROOT) -> list[Read]:
    out: list[Read] = []
    for root in roots:
        for path in sorted((repo_root / root).rglob("*.py")):
            rel = path.relative_to(repo_root).as_posix()
            if "/tests/" in rel or "__pycache__" in rel:
                continue
            out.extend(scan_file(path, rel))
    return sorted(out, key=lambda r: (r.path, r.line))


def date_range_reads(reads: list[Read] | None = None) -> list[Read]:
    return [r for r in (census() if reads is None else reads) if r.is_date_range]


def violations(reads: list[Read] | None = None, suffixed: dict[str, str] | None = None) -> list[Read]:
    suffixed = suffixed_sources() if suffixed is None else suffixed
    return [r for r in date_range_reads(reads) if r.verdict(suffixed).startswith("VIOLATION")]


def main(argv: list[str]) -> int:
    suffixed = suffixed_sources()
    rows = date_range_reads()
    only_bad = "--violations" in argv
    print(f"suffixed partitions ({len(suffixed)}): " + ", ".join(f"{k} [{v}]" for k, v in suffixed.items()))
    print(f"date-range reads: {len(rows)}")
    bad = 0
    for r in rows:
        v = r.verdict(suffixed)
        bad += v.startswith("VIOLATION")
        if only_bad and not v.startswith("VIOLATION"):
            continue
        part = "helper(pk=param)" if r.is_helper else (r.source or "?")
        rng = f"{r.lo} .. {r.hi}" if r.op == "between" else f"begins_with {r.lo}"
        print(f"{v:34} {r.path}:{r.line} {r.func} [{r.form}] {part} :: {rng}")
    print(f"violations: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
