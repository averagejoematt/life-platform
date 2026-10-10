"""tests/test_invoke_model_names_resolve_4769.py — every statically-known `model_name=` resolves (#4769).

Since #4306 (#4275), `bedrock_client.resolve_model_id` raises `UnknownModelError` for any
name outside `_MODEL_MAP` instead of silently falling back to Haiku 4.5. Two callers still
passed bare tier names ("sonnet" in `reading/horizons_retrospective.py`, "haiku" in
`privacy/broadcast_sensitivity_gate.py`), so both failed closed on every call and no unit
test noticed, because each one injects its invoker.

This is the SET guard for that class: it walks every module under `lambdas/` and `mcp/`,
finds every call that passes a `model_name=` keyword, statically resolves the value where it
can, and runs each resolved name through the real `resolve_model_id`. One test reports every
offender at once.

What "statically resolves" covers:
  * a string literal — `invoke(body, model_name="sonnet")`;
  * a module-level name bound to a literal — `MODEL = "claude-haiku-4-5-20251001"`;
  * a module-level `os.environ.get("X", <default>)` / `os.getenv("X", <default>)` — the
    DEFAULT is checked, because that default is the production model wherever the env var is
    unset (`ai/model_defaults.py` records that only `AI_MODEL_HAIKU` is set, on 8 functions);
  * a name imported from another module under `lambdas/` or `mcp/` (e.g. `NARRATIVE_MODEL`),
    followed to its binding there;
  * `a or B` — each operand that resolves is checked.

KNOWN GAP (stated, not hidden): a value that is a function parameter, a function-local
variable, a subscript (`deps["writer_model"]`) or `body["model"]` is only known at run time
and is not checked here. The registry story on epic #4768 (#4770) removes that residual by
routing every caller through one feature → model table.

Run:  python3 -m pytest tests/test_invoke_model_names_resolve_4769.py -v
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from ai import bedrock_client as bc  # noqa: E402

_SWEEP_ROOTS = ("lambdas", "mcp")

# The two specimens #4769 was filed on. Each must be RESOLVED by the sweep (not skipped as
# dynamic), otherwise the guard could pass by no longer seeing them.
_SPECIMENS = {"lambdas/reading/horizons_retrospective.py", "lambdas/privacy/broadcast_sensitivity_gate.py"}

# Vacuity floor: on 2026-10-10 the sweep resolved 18 call-site values. A refactor of the
# resolver that silently stops following names would drop well below this.
_MIN_RESOLVED = 15


def _module_file(root: pathlib.Path, dotted: str) -> pathlib.Path | None:
    parts = dotted.split(".")
    for base in (root / "lambdas", root):
        cand = base.joinpath(*parts)
        if cand.with_suffix(".py").is_file():
            return cand.with_suffix(".py")
        if (cand / "__init__.py").is_file():
            return cand / "__init__.py"
    return None


class _Resolver:
    """Resolve a model-name expression to the string literal(s) it carries at import time."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self._cache: dict[pathlib.Path, tuple[dict, dict]] = {}

    def _bindings(self, path: pathlib.Path) -> tuple[dict, dict]:
        """(module-level name -> value expr, imported name -> (source module path, source name))."""
        if path in self._cache:
            return self._cache[path]
        tree = ast.parse(path.read_text())
        assigns: dict[str, ast.expr] = {}
        imports: dict[str, tuple[pathlib.Path, str]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        assigns[tgt.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                assigns[node.target.id] = node.value
            elif isinstance(node, ast.ImportFrom):
                src = self._import_source(path, node)
                if src is not None:
                    for alias in node.names:
                        imports[alias.asname or alias.name] = (src, alias.name)
        self._cache[path] = (assigns, imports)
        return assigns, imports

    def _import_source(self, path: pathlib.Path, node: ast.ImportFrom) -> pathlib.Path | None:
        if node.level:
            base = path.parent
            for _ in range(node.level - 1):
                base = base.parent
            if not node.module:
                return None
            cand = base.joinpath(*node.module.split("."))
            return cand.with_suffix(".py") if cand.with_suffix(".py").is_file() else None
        return _module_file(self.root, node.module) if node.module else None

    def resolve(self, expr: ast.expr, path: pathlib.Path, local_imports: dict, depth: int = 0) -> list[str] | None:
        """The literal(s) `expr` evaluates to, or None when it is only known at run time."""
        if depth > 6:
            return None
        if isinstance(expr, ast.Constant):
            return [expr.value] if isinstance(expr.value, str) else None
        if isinstance(expr, ast.BoolOp):
            out = [v for part in expr.values for v in (self.resolve(part, path, local_imports, depth + 1) or [])]
            return out or None
        if isinstance(expr, ast.Call) and _is_env_get(expr) and len(expr.args) >= 2:
            return self.resolve(expr.args[1], path, local_imports, depth + 1)
        if isinstance(expr, ast.Name):
            assigns, imports = self._bindings(path)
            if expr.id in local_imports:
                src, name = local_imports[expr.id]
                return self.resolve(ast.Name(id=name), src, {}, depth + 1)
            if expr.id in assigns:
                return self.resolve(assigns[expr.id], path, {}, depth + 1)
            if expr.id in imports:
                src, name = imports[expr.id]
                return self.resolve(ast.Name(id=name), src, {}, depth + 1)
        return None


def _is_env_get(call: ast.Call) -> bool:
    f = call.func
    if not isinstance(f, ast.Attribute):
        return False
    # os.environ.get(...)
    if f.attr == "get" and isinstance(f.value, ast.Attribute) and f.value.attr == "environ":
        return True
    # os.getenv(...)
    return f.attr == "getenv" and isinstance(f.value, ast.Name) and f.value.id == "os"


def _function_local_imports(resolver: _Resolver, path: pathlib.Path, tree: ast.AST) -> dict[ast.AST, dict]:
    """Map each function node to the `from X import Y` bindings made inside it (lazy imports)."""
    out: dict[ast.AST, dict] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local: dict = {}
            for node in ast.walk(fn):
                if isinstance(node, ast.ImportFrom):
                    src = resolver._import_source(path, node)
                    if src is not None:
                        for alias in node.names:
                            local[alias.asname or alias.name] = (src, alias.name)
            out[fn] = local
    return out


def sweep(root: pathlib.Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (offenders, resolved) over every `model_name=` keyword under lambdas/ and mcp/.

    offenders: "rel:line 'name' -> error" for each resolved name `resolve_model_id` rejects.
    resolved:  (rel, name) for each resolved name, offender or not.
    """
    root = pathlib.Path(root)
    resolver = _Resolver(root)
    offenders: list[str] = []
    resolved: list[tuple[str, str]] = []
    files = sorted(p for sub in _SWEEP_ROOTS for p in (root / sub).glob("**/*.py") if (root / sub).is_dir())
    for path in files:
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text())
        per_fn = _function_local_imports(resolver, path, tree)
        # innermost enclosing function's lazy imports, for each call
        enclosing: dict[ast.AST, dict] = {}
        for fn, local in per_fn.items():
            for node in ast.walk(fn):
                enclosing[node] = {**enclosing.get(node, {}), **local}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "model_name":
                    continue
                names = resolver.resolve(kw.value, path, enclosing.get(node, {}))
                for name in names or []:
                    resolved.append((rel, name))
                    try:
                        bc.resolve_model_id(name)
                    except bc.UnknownModelError as exc:
                        offenders.append(f"{rel}:{node.lineno} {name!r} -> {type(exc).__name__}")
    return offenders, resolved


def test_every_statically_known_model_name_resolves_at_the_chokepoint():
    offenders, resolved = sweep(ROOT)
    assert offenders == [], (
        "model_name= values that bedrock_client.resolve_model_id rejects with UnknownModelError "
        "(every call through them fails closed — #4769). Use a _MODEL_MAP name, e.g. "
        "ai.model_defaults.NARRATIVE_MODEL for the narrative tier:\n  " + "\n  ".join(offenders)
    )
    # Non-vacuity: the resolver actually followed literals, constants, env defaults and imports.
    assert len(resolved) >= _MIN_RESOLVED, f"only {len(resolved)} model_name= values resolved — the sweep has gone blind"
    seen_files = {rel for rel, _ in resolved}
    assert _SPECIMENS <= seen_files, f"the #4769 specimens are no longer resolved by the sweep: {sorted(_SPECIMENS - seen_files)}"


def test_the_two_specimens_now_pass_mapped_names():
    _, resolved = sweep(ROOT)
    by_file = {}
    for rel, name in resolved:
        by_file.setdefault(rel, set()).add(name)
    from ai.model_defaults import NARRATIVE_MODEL

    assert by_file["lambdas/reading/horizons_retrospective.py"] == {NARRATIVE_MODEL}  # narrative tier, unchanged
    assert by_file["lambdas/privacy/broadcast_sensitivity_gate.py"] == {"claude-haiku-4-5-20251001"}  # what "haiku" fell back to pre-#4306


# ── Mutation controls: each resolution path reds on a planted bad name ─────────────────────


def _plant(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src)


def test_MUTATION_a_bare_tier_literal_reds(tmp_path):
    _plant(tmp_path, "lambdas/reading/x.py", 'def f(bc, b):\n    return bc.invoke(b, model_name="sonnet")\n')
    offenders, _ = sweep(tmp_path)
    assert offenders == ["lambdas/reading/x.py:2 'sonnet' -> UnknownModelError"]


def test_MUTATION_a_module_constant_and_an_env_default_red(tmp_path):
    _plant(
        tmp_path,
        "lambdas/privacy/y.py",
        'import os\nM = "haiku"\nN = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-9")\n'
        "def f(bc, b):\n    bc.invoke(b, model_name=M)\n    bc.invoke(b, model_name=N)\n",
    )
    offenders, _ = sweep(tmp_path)
    assert offenders == [
        "lambdas/privacy/y.py:5 'haiku' -> UnknownModelError",
        "lambdas/privacy/y.py:6 'claude-haiku-9' -> UnknownModelError",
    ]


def test_MUTATION_a_lazily_imported_constant_is_followed(tmp_path):
    _plant(tmp_path, "lambdas/ai/defaults_x.py", 'NARR = "sonnet-ish"\n')
    _plant(
        tmp_path,
        "mcp/z.py",
        "def f(bc, b, m=None):\n    from ai.defaults_x import NARR\n    return bc.invoke(b, model_name=m or NARR)\n",
    )
    offenders, _ = sweep(tmp_path)
    assert offenders == ["mcp/z.py:3 'sonnet-ish' -> UnknownModelError"]


def test_mapped_names_profile_ids_and_runtime_values_do_not_red(tmp_path):
    _plant(
        tmp_path,
        "lambdas/emails/ok.py",
        'import os\nM = os.getenv("AI_MODEL", "claude-sonnet-4-6")\n'
        "def f(bc, b, deps):\n"
        '    bc.invoke(b, model_name="us.anthropic.claude-haiku-4-5-20251001-v1:0")\n'
        "    bc.invoke(b, model_name=M)\n"
        '    bc.invoke(b, model_name=deps["writer_model"])\n',
    )
    offenders, resolved = sweep(tmp_path)
    assert offenders == []
    assert sorted(n for _, n in resolved) == ["claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0"]


if __name__ == "__main__":  # pragma: no cover
    off, res = sweep(ROOT)
    print(f"{len(res)} resolved, {len(off)} offenders", *off, sep=os.linesep)
