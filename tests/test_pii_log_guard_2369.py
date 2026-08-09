#!/usr/bin/env python3
"""tests/test_pii_log_guard_2369.py — the standing PII-in-logs gate (#2369).

#2354 fixed one site (a raw date_of_birth logged by mcp/tools_health.py) and ran
a ONE-SHOT, dob-scoped AST sweep to confirm it was alone. #2369 found the class
the sweep's scope excluded: three log sites writing full raw subscriber email
addresses to CloudWatch — third-party PII under docs/DATA_GOVERNANCE.md ("Email
addresses (subscribers, recipients)" is on the PII definition list, and
CloudWatch logs are Tier 3), while every sibling send-loop follows the
truncation convention (`email_hash[:8]` / `email[:6]…`).

This file makes that sweep STANDING and widens it from dob to the
DATA_GOVERNANCE PII field set (emails, dob/birth-date, phone number). It does
not carry a hand list of the three fixed files — a hand list rots at the fourth
site. It **derives** the scanned surface (every `*.py` under `lambdas/` and
`mcp/`, recursively) and AST-walks every logging call (`*log*.debug/info/
warning/error/exception/critical` and `print`) for a PII-named value
interpolated raw:

- as a direct argument                       logger.warning("... %s", email, e)
- inside an f-string                         logger.info(f"sent to {email}")
- via %-formatting                           logger.info("sent to %s" % email)
- via .format()                              logger.info("{}".format(email))
- as an attribute or string subscript        sub.email / sub["email"] / sub.get("email")

Sanctioned forms are allowlisted structurally, per the issue:
- hashes: any identifier with a `_hash*` suffix (`email_hash`, `email_hash[:8]`)
- explicit truncation: any slice (`email[:6]`) — slicing IS the convention
- wrapped values: an expression nested inside another call (`len(email)`,
  `hash_email(email)`) is not a raw interpolation and is not flagged

Non-vacuity is proved here, not assumed (the guard-the-SET discipline: three
privacy screens shipped in this repo whose full suite passed with the screen
deleted). `scan_tree` is parameterised by root, and the mutation tests below
build synthetic trees containing each raw-interpolation shape and assert the
scanner flags it — and the sanctioned shapes, and assert it stays quiet.

Everything is offline: files are parsed, never imported; no AWS, no network.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("lambdas", "mcp")  # the derived surface — every *.py, recursively

# ── The PII field set (docs/DATA_GOVERNANCE.md "PII Definition"), as identifier
# tokens. Matched against whole `_`-delimited tokens so `email`, `to_email`,
# `subscriber_email`, `date_of_birth`, `birth_date` all hit, while `mailer`,
# `mail_body`, `emailed_at` do not.
_PII_NAME_RE = re.compile(
    r"(?:^|_)(?:e?_?mail|emails|dob|date_of_birth|birth_?date|phone_?number)(?:_|$)",
    re.IGNORECASE,
)

# Derived/sanitized forms of a PII-named value that are safe to log.
_SAFE_SUFFIX_RE = re.compile(
    r"(?:_hash(?:e[sd])?|_sha\d*|_digest|_count|_total|_len(?:gth)?|_domain|_masked|_redacted|_truncated|_prefix)$",
    re.IGNORECASE,
)

_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})


def _is_pii_name(name: str) -> bool:
    n = name.lower()
    return not _SAFE_SUFFIX_RE.search(n) and bool(_PII_NAME_RE.search(n))


def _is_logging_call(call: ast.Call) -> bool:
    """logger.info / logging.warning / self._logger.error / LOG.debug — or print."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id == "print"
    if isinstance(f, ast.Attribute) and f.attr in _LOG_METHODS:
        base = f.value
        if isinstance(base, ast.Name):
            return "log" in base.id.lower()
        if isinstance(base, ast.Attribute):
            return "log" in base.attr.lower()
    return False


def _pii_ident(expr: ast.expr):
    """The PII identifier if `expr` is a RAW (unsanitized) PII-named value at
    top level; None for sanctioned or unrelated shapes."""
    if isinstance(expr, ast.Name) and _is_pii_name(expr.id):
        return expr.id
    if isinstance(expr, ast.Attribute) and _is_pii_name(expr.attr):
        return expr.attr
    if isinstance(expr, ast.Subscript):
        if isinstance(expr.slice, ast.Slice):
            return None  # email[:6] — truncation IS the convention
        if isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str) and _is_pii_name(expr.slice.value):
            return expr.slice.value  # sub["email"]
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "get":
        if expr.args and isinstance(expr.args[0], ast.Constant) and isinstance(expr.args[0].value, str):
            if _is_pii_name(expr.args[0].value):
                return expr.args[0].value  # sub.get("email")
    return None


def _interpolated_exprs(arg: ast.expr):
    """The expressions a logging argument actually interpolates: the arg itself,
    f-string fields, %-format operands, .format() arguments. Deliberately does
    NOT recurse into arbitrary nested calls — `hash_email(email)` is sanitized
    by construction of this walk."""
    yield arg
    if isinstance(arg, ast.JoinedStr):
        for v in arg.values:
            if isinstance(v, ast.FormattedValue):
                yield v.value
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
        if isinstance(arg.right, ast.Tuple):
            yield from arg.right.elts
        else:
            yield arg.right
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        yield from arg.args
        for kw in arg.keywords:
            yield kw.value


def scan_file(path: Path):
    """(lineno, identifier) for every raw PII interpolation in a logging call."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # a broken file must not silently shrink the surface
        return [(exc.lineno or 0, f"UNPARSEABLE: {exc.msg}")], 0
    hits, n_calls = [], 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_logging_call(node)):
            continue
        n_calls += 1
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for expr in _interpolated_exprs(arg):
                ident = _pii_ident(expr)
                if ident:
                    hits.append((node.lineno, ident))
    return hits, n_calls


def scan_tree(root: Path, subdirs=SCAN_ROOTS):
    """Violations + census over every *.py under root/<subdirs>. Parameterised
    by root so the mutation tests below can prove the scanner bites."""
    violations, n_files, n_calls = [], 0, 0
    for sub in subdirs:
        for py in sorted((root / sub).rglob("*.py")):
            n_files += 1
            hits, calls = scan_file(py)
            n_calls += calls
            violations += [f"{py.relative_to(root)}:{ln} interpolates raw `{ident}`" for ln, ident in hits]
    return violations, n_files, n_calls


# ═══ The gate ══════════════════════════════════════════════════════════════════


def test_no_raw_pii_in_logging_calls():
    """No logging call under lambdas/ or mcp/ interpolates a raw email / dob /
    phone value. Fix the log site (hash, or truncate per the `email[:6]…` /
    `email_hash[:8]` convention) — do not weaken the guard."""
    violations, n_files, n_calls = scan_tree(ROOT)
    assert not violations, (
        "Raw PII interpolated into logging calls (CloudWatch is Tier 3 — "
        "docs/DATA_GOVERNANCE.md; truncate like the sibling send-loops):\n  " + "\n  ".join(violations)
    )
    # Non-vacuity census: a refactor that empties the walk must fail loudly,
    # not pass silently. Floors are well under the measured 408 files / 2539
    # logging calls (2026-08-09), and far above zero.
    assert n_files > 300, f"suspiciously few files scanned ({n_files}) — a vacuous scan is not a pass"
    assert n_calls > 1000, f"suspiciously few logging calls seen ({n_calls}) — a vacuous scan is not a pass"


# ═══ Mutation proofs — the scanner must actually bite ══════════════════════════


def _tree(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "repo"
    (root / "lambdas" / "web").mkdir(parents=True)
    (root / "mcp").mkdir()
    (root / "lambdas" / "web" / "mod.py").write_text(body, encoding="utf-8")
    (root / "mcp" / "empty.py").write_text("", encoding="utf-8")
    return root


def _violations(tmp_path, body):
    return scan_tree(_tree(tmp_path, body))[0]


def test_flags_raw_email_positional_arg(tmp_path):
    v = _violations(tmp_path, 'logger.warning("send failed (%s) — %s", email, e)\n')
    assert len(v) == 1 and "raw `email`" in v[0], v


def test_flags_raw_email_in_fstring(tmp_path):
    v = _violations(tmp_path, 'logger.info(f"Onboarding email sent to {email}")\n')
    assert len(v) == 1, v


def test_flags_percent_format_and_dotformat_and_dict_access(tmp_path):
    body = (
        'logger.info("sent to %s" % subscriber_email)\n'
        'logger.error("failed for {}".format(sub["email"]))\n'
        'log.debug("row %s", sub.get("email"))\n'
        'logger.info(f"born {date_of_birth}")\n'
    )
    assert len(_violations(tmp_path, body)) == 4


def test_flags_print_too(tmp_path):
    v = _violations(tmp_path, 'print("subscriber:", email)\n')
    assert len(v) == 1, v


def test_sanctioned_forms_stay_quiet(tmp_path):
    body = (
        'logger.info("subscribe: confirmed %s", email_hash[:8])\n'
        'logger.error("send failed to %s…: %s", email[:6], exc)\n'
        'logger.info(f"sent ({email[:6]}...)")\n'
        'logger.info("n=%d domain=%s", email_count, email_domain)\n'
        'logger.debug("hashed %s", hash_email(email))\n'
        'logger.info("plain message, no interpolation")\n'
        "send_email(email)\n"  # not a logging call
    )
    assert _violations(tmp_path, body) == []


def test_unparseable_file_is_a_violation_not_a_skip(tmp_path):
    v = _violations(tmp_path, "def broken(:\n")
    assert len(v) == 1 and "UNPARSEABLE" in v[0], v


def test_the_three_2369_sites_read_clean_and_truncated():
    """The instance half of #2369: the two files that leaked now follow the
    truncation convention (belt to the set-level gate's braces)."""
    for rel in ("lambdas/emails/coach_panel_podcast_lambda.py", "lambdas/web/subscriber_onboarding_lambda.py"):
        hits, n_calls = scan_file(ROOT / rel)
        assert hits == [], f"{rel} still interpolates raw PII: {hits}"
        assert n_calls > 0, f"{rel}: no logging calls seen — the scan went vacuous"
        assert "email[:6]" in (ROOT / rel).read_text(encoding="utf-8"), f"{rel}: truncation idiom missing"
