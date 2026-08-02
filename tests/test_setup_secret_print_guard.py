"""#1902 regression guard — setup/ scripts never print/log a credential VALUE.

The `setup/*.py` interactive auth helpers legitimately print the Secrets Manager
secret NAME ("Updated secret: life-platform/whoop") and flow guidance, but must
never print the value of a token/secret/password variable — that was the ~30-alert
`py/clear-text-logging-sensitive-data` cluster CodeQL carried on main. Masked forms
(presence + length, e.g. `f"(set, {len(client_id)} chars)"`) are the sanctioned
replacement.

Guard the SET, not the instance: the file list is derived by glob over `setup/`,
and the sensitive-identifier rule is segment-based, so a renamed or newly added
script stays covered without editing this test.

Rules (AST, not grep — comments/strings of the right shape can't false-positive):
- Sinks: `print(...)` and `<anything>.info/warning/error/debug/critical/exception(...)`.
- An identifier is credential-valued when any `_`-separated segment is in
  SENSITIVE_SEGMENTS — unless another segment marks it as a *reference* (name/id/
  url/count/...), which is the allowed "print the secret's name" class.
- Wrapping in a numeric/len sanitizer (`len`, `int`, `float`, `bool`) is the
  masked form and is allowed.
"""

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
SETUP_DIR = REPO / "setup"

SENSITIVE_SEGMENTS = {
    "token",
    "tokens",
    "secret",
    "secrets",
    "password",
    "passwd",
    "credential",
    "credentials",
    "bearer",
    "apikey",
}
# Segments that mark the identifier as a REFERENCE to a credential (its name/id/
# location), not the credential itself. `SECRET_NAME`, `secret_id`, `token_url`
# are fine to print; `client_secret`, `access_token` are not.
REFERENCE_SEGMENTS = {"name", "names", "id", "ids", "arn", "url", "uri", "count", "path", "prefix", "key"}
MASK_WRAPPERS = {"len", "int", "float", "bool"}
LOG_METHODS = {"info", "warning", "error", "debug", "critical", "exception"}

_SEG_RE = re.compile(r"[^a-z0-9]+")


def _is_credential_valued(identifier: str) -> bool:
    segs = [s for s in _SEG_RE.split(identifier.lower()) if s]
    if not any(s in SENSITIVE_SEGMENTS for s in segs):
        return False
    return not any(s in REFERENCE_SEGMENTS for s in segs)


def _violations(source: str, filename: str = "<test>"):
    """(lineno, expression) for every credential-valued identifier reaching a print/log sink unmasked."""
    tree = ast.parse(source, filename=filename)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _masked(node, sink):
        cur = parents.get(node)
        while cur is not None and cur is not sink:
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) and cur.func.id in MASK_WRAPPERS:
                return True
            cur = parents.get(cur)
        return False

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        is_sink = (isinstance(f, ast.Name) and f.id == "print") or (isinstance(f, ast.Attribute) and f.attr in LOG_METHODS)
        if not is_sink:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                ident = None
                if isinstance(sub, ast.Name):
                    ident = sub.id
                elif isinstance(sub, ast.Attribute):
                    ident = sub.attr
                elif isinstance(sub, ast.Subscript):
                    sl = sub.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        ident = sl.value
                if ident is None or not _is_credential_valued(ident):
                    continue
                if _masked(sub, node):
                    continue
                out.append((sub.lineno, ast.unparse(sub)))
    return out


def test_setup_scripts_never_print_credential_values():
    scripts = sorted(SETUP_DIR.glob("*.py"))
    assert scripts, "setup/*.py glob came back empty — the guard would be vacuous"
    failures = []
    for path in scripts:
        for lineno, expr in _violations(path.read_text(encoding="utf-8"), str(path)):
            failures.append(f"{path.relative_to(REPO)}:{lineno} prints credential-valued expression `{expr}`")
    assert not failures, (
        'setup/ scripts must print masked forms (e.g. f"(set, {len(v)} chars)") or the secret\'s NAME, '
        "never a credential value (#1902):\n  " + "\n  ".join(failures)
    )


# ── The guard itself must fire (guard-the-guard, per the review discipline) ──


def test_guard_fires_on_fstring_token_print():
    assert _violations('print(f"token: {access_token}")')


def test_guard_fires_on_subscript_and_slice_forms():
    assert _violations("print(saved['refresh_token'][:20])")
    assert _violations('logger.info("t=%s" % client_secret)')


def test_guard_allows_masked_and_reference_forms():
    assert not _violations("print(f\"access_token: received ({len(saved['access_token'])} chars)\")")
    assert not _violations('print(f"Updated secret: {SECRET_NAME}")')
    assert not _violations('logger.debug("Secret %s fetched", secret_id)')
