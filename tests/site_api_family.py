"""tests/site_api_family.py — resolve a site_api FACADE to its whole source family.

#1654 (god-module breakup) split the largest site_api modules into a thin routed
facade plus cohesive sibling modules. That move breaks a whole class of guard:
a source-text or AST assertion pinned to ONE file keeps passing after the code it
guards has moved one module sideways — it just stops finding anything to object
to. Two of the guards this helper serves are privacy absolutes
(``test_public_genetic_privacy_absolute``), where a silently-vacuous assertion is
the worst possible failure mode.

So: guard the SET, not the instance. And derive the set rather than listing it —
a hand-maintained family list is the same bug one level up, since the next split
would leave it stale with nothing to complain.

The family is the facade plus every ``web.site_api_*`` sibling the facade itself
imports, read straight out of the facade's own import statements. Adding a
sibling in a future split needs no test edit.

``resolve_handler``/``handler_source`` go one step further: given a routed handler
name, they follow the facade's thin delegator (``return _character.character(...)``)
through its module alias to the REAL implementation, so an assertion about a
handler's body still reads the body — not the three-line delegator that replaced
it.
"""

import ast
import pathlib

WEB = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "web"

# The shared base every site_api module imports. It is NOT a split sibling — it
# predates the splits, is shared across unrelated facades, and pulling it in would
# silently widen every guard's scope to code it was never written about.
_SHARED = {"site_api_common"}


def family_paths(facade_stem: str) -> list[pathlib.Path]:
    """[facade, *siblings] — every file the facade's routed surface spans."""
    facade = WEB / f"{facade_stem}.py"
    paths = [facade]
    for node in ast.walk(ast.parse(facade.read_text())):
        if not isinstance(node, ast.ImportFrom):
            continue
        candidates = []
        if node.module == "web":
            candidates = [a.name for a in node.names]
        elif (node.module or "").startswith("web.site_api_"):
            candidates = [node.module.split(".", 1)[1]]
        for name in candidates:
            path = WEB / f"{name}.py"
            if name.startswith("site_api_") and name not in _SHARED and path.exists() and path not in paths:
                paths.append(path)
    return paths


def family_source(facade_stem: str) -> str:
    """The concatenated source of the whole family — a drop-in for a single read_text()."""
    return "\n".join(p.read_text() for p in family_paths(facade_stem))


def _delegate_alias_map(facade_tree) -> dict[str, str]:
    """`_character` -> `site_api_character`, from the facade's own `from web import` block."""
    aliases = {}
    for node in ast.walk(facade_tree):
        if isinstance(node, ast.ImportFrom) and node.module == "web":
            for a in node.names:
                if a.name.startswith("site_api_"):
                    aliases[a.asname or a.name] = a.name
    return aliases


def resolve_handler(facade_stem: str, handler: str) -> tuple[pathlib.Path, str, ast.FunctionDef]:
    """(path, source, FunctionDef) for `handler`'s REAL implementation.

    Follows a one-line delegator `return <alias>.<fn>(...)` into the sibling that
    owns the logic. A handler still implemented on the facade resolves to itself,
    so this is safe to use for facades that have not been split.
    """
    facade = WEB / f"{facade_stem}.py"
    src = facade.read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == handler), None)
    if fn is None:
        raise AssertionError(f"{facade_stem} defines no `{handler}` — was the route renamed or dropped?")

    aliases = _delegate_alias_map(tree)
    for stmt in fn.body:
        if not (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call)):
            continue
        func = stmt.value.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        module = aliases.get(func.value.id)
        if not module:
            continue
        target = WEB / f"{module}.py"
        tsrc = target.read_text()
        impl = next((n for n in ast.walk(ast.parse(tsrc)) if isinstance(n, ast.FunctionDef) and n.name == func.attr), None)
        if impl is None:
            raise AssertionError(f"{facade_stem}.{handler} delegates to {module}.{func.attr}, which does not exist")
        return target, tsrc, impl
    return facade, src, fn


def handler_source(facade_stem: str, handler: str) -> str:
    """Just the source text of `handler`'s real implementation."""
    path, src, fn = resolve_handler(facade_stem, handler)
    return ast.get_source_segment(src, fn) or ""
