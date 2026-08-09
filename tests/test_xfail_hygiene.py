"""xfail marker hygiene (#2375).

A `strict=False` xfail on a DETERMINISTIC defect rots: when the defect is fixed
incidentally, the test XPASSes silently and the marker outlives its reason
(the class #2299 left behind — two implementers independently misattributed the
stale XPASS that commit 6044752d finally killed). The rule enforced here makes
the residue self-burning:

- Every `pytest.mark.xfail` marker states `strict=` explicitly, as a literal.
- `strict=True` is the default posture: a deterministic defect's marker fails
  the suite the moment its defect is fixed (`[XPASS(strict)]`), so it can only
  be removed truthfully, together with the fix.
- `strict=False` is reserved for genuinely nondeterministic outcomes (live
  AWS state, budget tier, wall-clock coupling that cannot be frozen) and MUST
  name the nondeterminism: its reason string must contain the tag
  ``NONDETERMINISTIC:`` followed by why the outcome varies.

Imperative ``pytest.xfail(...)`` calls (the D3/D4/W1-W3 known-gap registries in
test_ddb_patterns.py / test_wiring_coverage.py) are exempt by construction:
they halt the test unconditionally, so they cannot XPASS and cannot rot the
same way — their honesty is policed by their gap lists shrinking.

AST-based, so prose mentions of "strict=False" in docstrings never trip it.
"""

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

NONDETERMINISM_TAG = "NONDETERMINISTIC:"


def _is_mark_xfail(node: ast.AST) -> bool:
    """True for an attribute chain ending in ``.mark.xfail`` (pytest.mark.xfail)."""
    return isinstance(node, ast.Attribute) and node.attr == "xfail" and isinstance(node.value, ast.Attribute) and node.value.attr == "mark"


def _literal_reason(call: ast.Call) -> str | None:
    """The reason kwarg's literal string, or None if absent/non-literal.

    Adjacent string literals are folded into one ``ast.Constant`` by the
    parser, so the house style (parenthesised multi-line reasons) lands here.
    """
    for kw in call.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _iter_xfail_marks(tree: ast.AST):
    """Yield (node, kind) for every xfail MARK usage.

    kind is "call" for ``pytest.mark.xfail(...)`` (decorator or ``marks=``),
    "bare" for a decorator ``@pytest.mark.xfail`` with no argument list.
    Imperative ``pytest.xfail(...)`` never matches: its func is
    ``pytest.xfail``, not ``pytest.mark.xfail``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_mark_xfail(node.func):
            yield node, "call"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if _is_mark_xfail(dec):
                    yield dec, "bare"


def _collect_violations():
    violations = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node, kind in _iter_xfail_marks(tree):
            where = f"{path.relative_to(TESTS_DIR.parent)}:{node.lineno}"
            if kind == "bare":
                violations.append(f"{where}: bare @pytest.mark.xfail — state strict= explicitly (strict=True for a deterministic defect)")
                continue
            strict_kw = next((kw for kw in node.keywords if kw.arg == "strict"), None)
            if strict_kw is None or not isinstance(strict_kw.value, ast.Constant) or not isinstance(strict_kw.value.value, bool):
                violations.append(f"{where}: xfail without a literal strict= — state strict=True/False explicitly")
                continue
            if strict_kw.value.value is False:
                reason = _literal_reason(node)
                if reason is None:
                    violations.append(f"{where}: strict=False xfail needs a literal reason string naming the nondeterminism")
                elif NONDETERMINISM_TAG not in reason:
                    violations.append(
                        f"{where}: strict=False is reserved for nondeterministic outcomes — the reason must carry "
                        f"'{NONDETERMINISM_TAG} <why the outcome varies>'; a deterministic defect takes strict=True "
                        f"so a fix burns the marker"
                    )
    return violations


def test_every_xfail_marker_is_strict_or_names_its_nondeterminism():
    violations = _collect_violations()
    assert not violations, "xfail hygiene (#2375):\n" + "\n".join(violations)
