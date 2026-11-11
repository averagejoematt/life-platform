"""
tests/test_ddb_patterns.py — DynamoDB usage pattern linter.

Validates DynamoDB patterns across all Lambda source files without needing
AWS credentials or a running environment. Runs in CI Job 2 (test).

Rules enforced:
  D1  pk/sk string construction follows USER#<user>#SOURCE#<source> / DATE#YYYY-MM-DD format
  D2  'date' reserved word — any FilterExpression/KeyConditionExpression that includes
      a bare 'date' attribute must use ExpressionAttributeNames
  D3  schema_version included in put_item calls for ingestion Lambdas (DATA-1)
  D4  table.put_item calls in ingestion Lambdas are preceded by validate_item or
      validate_and_write (DATA-2 enforcement at code level)
  D5  no private float->Decimal walker outside lambdas/common/numeric.py (#1207)
  D6  no uncoerced float in a put_item/update_item payload in lambdas/ + mcp/ (#5524)

Run with:   python3 -m pytest tests/test_ddb_patterns.py -v
Or directly: python3 tests/test_ddb_patterns.py

v1.0.0 — 2026-03-11
"""

import ast
import os
import re
import sys
import textwrap

import pytest

# #416 / ADR-117: deploy-critical lane (DynamoDB access-pattern linter).
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")


# P3.1 (2026-05-25): handler files now live in lambdas/{subpkg}/*.py — build
# a flat-name → real-path index so test helpers below can take filenames like
# "whoop_lambda.py" and resolve them regardless of subpackage.
def _build_lambda_index():
    idx = {}
    for root, _, files in os.walk(LAMBDAS_DIR):
        if "__pycache__" in root:
            continue
        for fname in files:
            if fname.endswith(".py"):
                idx[fname] = os.path.join(root, fname)
    return idx


_LAMBDA_INDEX = _build_lambda_index()


def _src(filename: str) -> str:
    path = _LAMBDA_INDEX.get(filename) or os.path.join(LAMBDAS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _exists(filename: str) -> bool:
    return filename in _LAMBDA_INDEX or os.path.exists(os.path.join(LAMBDAS_DIR, filename))


# ── Lambda sets ───────────────────────────────────────────────────────────────

# All Lambdas that interact with DynamoDB
DDB_LAMBDAS = [
    "strava_lambda.py",
    "whoop_lambda.py",
    "eightsleep_lambda.py",
    "habitify_lambda.py",
    "withings_lambda.py",
    "todoist_lambda.py",
    "notion_lambda.py",
    "macrofactor_lambda.py",
    "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py",
    "weather_lambda.py",
    "enrichment_lambda.py",
    "journal_enrichment_lambda.py",
    "daily_brief_lambda.py",
    "weekly_digest_lambda.py",
    "monthly_digest_lambda.py",
    "nutrition_review_lambda.py",
    "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py",
    "monday_compass_lambda.py",
    "partner_email_lambda.py",
    "anomaly_detector_lambda.py",
    "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py",
    "adaptive_mode_lambda.py",
    "character_sheet_lambda.py",
    "daily_metrics_compute_lambda.py",
    "dashboard_refresh_lambda.py",
    "failure_pattern_compute_lambda.py",
    "freshness_checker_lambda.py",
    "insight_email_parser_lambda.py",
    "canary_lambda.py",
    "qa_smoke_lambda.py",
    "data_export_lambda.py",
    "data_reconciliation_lambda.py",
]

INGESTION_LAMBDAS = [
    "strava_lambda.py",
    "whoop_lambda.py",
    "eightsleep_lambda.py",
    "habitify_lambda.py",
    "withings_lambda.py",
    "todoist_lambda.py",
    "notion_lambda.py",
    "macrofactor_lambda.py",
    "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py",
    "weather_lambda.py",
    "enrichment_lambda.py",
    "journal_enrichment_lambda.py",
]

# Known gaps for D3 (schema_version) — remove when fixed
D3_KNOWN_GAPS: set[str] = {
    "dropbox_poll_lambda.py",  # pre-existing gap — schema_version not yet added
    "health_auto_export_lambda.py",  # pre-existing gap — schema_version not yet added
}

# Known gaps for D4 (put_item preceded by validate) — remove when fixed
D4_KNOWN_GAPS: set[str] = {
    "weather_lambda.py",  # weather_handler.py is the canonical file; check separately
    "dropbox_poll_lambda.py",  # uses conditional put_item path — validator not yet wired
}


# ══════════════════════════════════════════════════════════════════════════════
# D1 — pk/sk format consistency
# ══════════════════════════════════════════════════════════════════════════════

# Valid pk patterns — compiled for reuse
_VALID_PK_PATTERNS = [
    re.compile(r"USER#\w+#SOURCE#\w"),  # USER#matthew#SOURCE#whoop
    re.compile(r"USER#\w+#profile"),  # USER#matthew#profile (profile key)
    re.compile(r"USER#\w+#hypothes"),  # hypotheses partition
    re.compile(r"USER#\w+#platform"),  # platform_memory partition
    re.compile(r"USER#\w+#anomal"),  # anomalies partition
    re.compile(r"USER#\w+#failure"),  # failure_pattern partition
    re.compile(r"USER#\w+#insights"),  # insights partition
    re.compile(r"USER#\w+#character"),  # character sheet partition
    re.compile(r"USER#\w+#day_grade"),  # day_grade partition
    re.compile(r"USER#\w+#habit"),  # habit_scores partition
    re.compile(r"USER#\w+#adaptive"),  # adaptive_mode partition
    re.compile(r"CANARY#"),  # canary test records
    re.compile(r'f"USER#'),  # f-string construction (any)
    re.compile(r"f'USER#"),  # f-string construction (any)
    re.compile(r"USER_PREFIX"),  # constant-based construction
    re.compile(r"PROFILE_PK"),  # profile constant
    re.compile(r"HYPOTHESES_PK"),  # hypotheses constant
]

_VALID_SK_PATTERNS = [
    re.compile(r"DATE#\d"),  # DATE#2026-...
    re.compile(r'DATE#" \+'),  # DATE#" + date_str
    re.compile(r"DATE#' \+"),
    re.compile(r'f"DATE#'),  # f-string
    re.compile(r"f'DATE#"),
    re.compile(r'"DATE#" \+ date'),
    re.compile(r"PROFILE#"),  # PROFILE#v1
    re.compile(r"HYPOTHESIS#"),  # HYPOTHESIS# prefix
    re.compile(r"CANARY#"),
    re.compile(r"SK_PREFIX"),  # constant
    re.compile(r"sk_prefix"),
    re.compile(r"begins_with"),  # query using begins_with
    re.compile(r"between\("),  # query using between
    re.compile(r"\.lt\("),  # Key().lt()
    re.compile(r"\.gte?\("),  # Key().gte()
    re.compile(r'"sk":\s*sk\b'),  # "sk": sk (variable)
    re.compile(r'"sk":\s*f"'),  # "sk": f"..."
    re.compile(r'"sk":\s*"[A-Z]'),  # "sk": "DATE#..." direct literal
]


def _check_pk_sk_patterns(src: str) -> list[str]:
    """Find pk/sk constructions that don't match any known-valid pattern."""
    issues = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Check pk constructions
        if re.search(r'"pk"\s*:\s*["\']', stripped) or re.search(r'"pk"\s*:\s*f["\']', stripped):
            # Has a pk literal assignment — check it matches a valid pattern
            if not any(p.search(stripped) for p in _VALID_PK_PATTERNS):
                # Allow if it's just a Key().eq() call or variable reference
                if not re.search(r'Key\(|pk\s*=\s*[a-z_]|"pk"\s*:\s*[a-z_]', stripped):
                    issues.append(f"  line {i}: suspect pk construction: {stripped[:120]}")

    return issues


@pytest.mark.parametrize("filename", sorted(DDB_LAMBDAS))
def test_d1_pk_sk_format(filename):
    """D1: pk/sk string constructions should follow platform key conventions."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    src = _src(filename)
    issues = _check_pk_sk_patterns(src)
    assert not issues, (
        f"{filename}: non-standard pk/sk constructions found. "
        f"Platform convention: pk=USER#<user>#SOURCE#<source>, sk=DATE#YYYY-MM-DD.\n" + "\n".join(issues)
    )


# ══════════════════════════════════════════════════════════════════════════════
# D2 — 'date' reserved word requires ExpressionAttributeNames
# ══════════════════════════════════════════════════════════════════════════════

# Expression types that can reference attribute names
_EXPR_KEYWORDS = re.compile(
    r"FilterExpression|KeyConditionExpression|ConditionExpression|" r"ProjectionExpression|UpdateExpression",
    re.IGNORECASE,
)

# Patterns that indicate a bare 'date' attribute reference (not a value or comment)
# 'date' appears as an attribute name, not as part of a string like "DATE#" or date_str
_BARE_DATE_IN_EXPR = re.compile(r"\bdate\b(?!\s*_|\s*str|\s*=|\s*>|\s*<|\s*!)")


def _find_unguarded_date_expressions(src: str) -> list[str]:
    """Find expression lines that reference 'date' without ExpressionAttributeNames."""
    issues = []
    lines = src.splitlines()

    for i, line in enumerate(lines):
        if not _EXPR_KEYWORDS.search(line):
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Does this line contain a bare 'date' attribute reference?
        if not re.search(r"['\"]date['\"]|Attr\(['\"]date", line, re.IGNORECASE):
            continue
        # Is it already guarded? Check surrounding 20 lines for ExpressionAttributeNames
        context_start = max(0, i - 5)
        context_end = min(len(lines), i + 15)
        context = "\n".join(lines[context_start:context_end])
        if "ExpressionAttributeNames" not in context:
            issues.append(f"  line {i+1}: 'date' in expression without ExpressionAttributeNames: {stripped[:120]}")

    return issues


@pytest.mark.parametrize("filename", sorted(DDB_LAMBDAS))
def test_d2_date_reserved_word_guarded(filename):
    """D2: 'date' is a DynamoDB reserved word — must use ExpressionAttributeNames."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    src = _src(filename)
    issues = _find_unguarded_date_expressions(src)
    assert not issues, (
        f"{filename}: 'date' used as attribute name in DDB expression without "
        f"ExpressionAttributeNames. This will cause a runtime error.\n"
        f'Fix: add ExpressionAttributeNames={{"#d": "date"}} and use #d in the expression.\n' + "\n".join(issues)
    )


# ══════════════════════════════════════════════════════════════════════════════
# D3 — schema_version in ingestion put_item items
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("filename", sorted(INGESTION_LAMBDAS))
def test_d3_schema_version_present(filename):
    """D3: Ingestion Lambdas must include schema_version in DDB items (DATA-1)."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in D3_KNOWN_GAPS:
        pytest.xfail(f"Known D3 gap: {filename} — see D3_KNOWN_GAPS")
    src = _src(filename)
    has_put_item = "put_item" in src or "validate_and_write" in src
    if not has_put_item:
        pytest.skip(f"{filename} has no put_item or validate_and_write call")
    assert "schema_version" in src, (
        f"{filename}: no schema_version field found. All ingestion Lambdas must include "
        f"'schema_version': 1 (or current version) in the item dict before calling "
        f"put_item(). Required for DATA-1 compliance and ingestion_validator."
    )


# ══════════════════════════════════════════════════════════════════════════════
# D4 — put_item in ingestion Lambdas preceded by validate call
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("filename", sorted(INGESTION_LAMBDAS))
def test_d4_put_item_guarded_by_validator(filename):
    """D4: Ingestion Lambdas must call validate_item/validate_and_write before put_item.

    'Built but not wired' is the highest-risk gap.  This check ensures that
    having ingestion_validator imported is not enough — it must actually be
    called before any table.put_item().
    """
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in D4_KNOWN_GAPS:
        pytest.xfail(f"Known D4 gap: {filename} — see D4_KNOWN_GAPS")
    src = _src(filename)
    has_put_item = "put_item(" in src or "validate_and_write(" in src
    if not has_put_item:
        pytest.skip(f"{filename} has no put_item call")
    has_validate = (
        "validate_item(" in src
        or "validate_and_write(" in src
        or "should_skip_ddb" in src
        # P4.1 (2026-05-17): SIMP-2 framework wraps validation around every
        # DDB write internally — Lambdas using run_ingestion() are compliant.
        or "run_ingestion(" in src
    )
    assert has_validate, (
        f"{filename}: has put_item() but no validate_item() / validate_and_write() / "
        f"run_ingestion() call. DATA-2 requires validation before every DDB write in "
        f"ingestion Lambdas. Either: (a) use SIMP-2 run_ingestion() which validates "
        f"internally, (b) use validate_and_write() as a drop-in replacement, or "
        f"(c) wrap put_item with explicit validate_item() + should_skip_ddb check."
    )


# ══════════════════════════════════════════════════════════════════════════════
# D5 (#1207) — no divergent float→Decimal walker outside lambdas/numeric.py
# ══════════════════════════════════════════════════════════════════════════════

MCP_DIR = os.path.join(ROOT, "mcp")

# The recursive float→Decimal walker was re-implemented ~17x under five fork names
# (def _to_decimal / _decimalize_dict / _float_to_decimal / _floats_to_decimal /
# to_decimal) with divergent NaN/Inf semantics — the plain copies passed Decimal('NaN')
# through, which boto3's TypeSerializer rejects at write time. Consolidated into
# numeric.floats_to_decimal (#1207). This guard fails if any private copy — under any
# of the historical fork names — reappears (top-level or nested).
#
# Deliberately NOT matched (each is a genuinely-DIFFERENT contract, so consolidating
# would silently change behavior — the #1207 remit was to unify only the NaN/Inf guard
# + the round-precision, expressed via floats_to_decimal(..., precision=)):
#   * SCALAR coercers (not recursive walkers): coach_prediction_evaluator._scalar_to_decimal,
#     measurements._parse_decimal_field.
#   * int→Decimal / key-stringifying / zero-fallback recursive walkers, left as-is and
#     tracked as follow-up: character_sheet_lambda._dec (int→Decimal),
#     episode_detect_lambda._deep_dec (round(4) + int→Decimal + str(k) key coercion),
#     weekly_correlation_compute_lambda._deep_dec (zero-fallback `_to_dec(obj) or 0`).
#   * (#5524) the `try: from numeric import floats_to_decimal / except ImportError: def
#     floats_to_decimal` fallback shims this list used to sanction are all gone (measured
#     2026-11-10: `def floats_to_decimal` exists only in common/numeric.py), and the one
#     entry it misdescribed as a shim — health_auto_export — was an unconditional
#     redefinition, now deleted. So the canonical name itself is forbidden outside numeric.py.
_FORBIDDEN_DECIMAL_DEF = re.compile(
    r"^\s*def\s+(?:_to_decimal|_decimalize\w*|_float_to_decimal|_floats_to_decimal|to_decimal|floats_to_decimal)\s*\(",
    re.MULTILINE,
)


def _iter_python_sources():
    """All lambdas/ + mcp/ .py files, excluding caches and CDK build-staging copies
    (cdk/_*_staging regenerate from source and must not be linted here)."""
    for base in (LAMBDAS_DIR, MCP_DIR):
        for root, _, files in os.walk(base):
            if "__pycache__" in root or "_staging" in root or "cdk.out" in root:
                continue
            for fname in files:
                if fname.endswith(".py"):
                    yield os.path.join(root, fname)


def test_d5_no_forked_floats_to_decimal():
    """D5 (#1207): the recursive float→Decimal walker lives ONLY in lambdas/numeric.py.

    Callers must `from numeric import floats_to_decimal` — not fork a private copy.
    This is the regression guard for the ~10 divergent forks consolidated in #1207.
    """
    numeric_path = os.path.abspath(os.path.join(LAMBDAS_DIR, "common", "numeric.py"))
    offenders = []
    for path in _iter_python_sources():
        if os.path.abspath(path) == numeric_path:
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for m in _FORBIDDEN_DECIMAL_DEF.finditer(src):
            offenders.append(f"{os.path.relpath(path, ROOT)}: {m.group(0).strip()}")
    assert not offenders, (
        "Divergent float→Decimal copy reintroduced — import "
        "`from numeric import floats_to_decimal` (with precision=/NaN-guard) instead of "
        "forking a private walker (#1207):\n  " + "\n  ".join(offenders)
    )


# ══════════════════════════════════════════════════════════════════════════════
# D6 (#5524) — no uncoerced float in a DynamoDB write payload
# ══════════════════════════════════════════════════════════════════════════════
#
# boto3's TypeSerializer rejects a Python float ("Float types are not supported. Use Decimal
# types instead.") — at WRITE time, in production, on the first row that happens to carry
# one. #3569 promised a repo-wide gate and only per-writer tests landed
# (test_nudge_decimal_and_ledger_3569.py, test_strava_reingest_decimal_5255.py), so a new
# writer was unguarded until its first live failure.
#
# THE RULE (AST, no imports of the code under test). For every `<x>.put_item(Item=P)` and
# `<x>.update_item(ExpressionAttributeValues=P)` call under lambdas/ and mcp/:
#   * P wrapped whole in a coercion call (floats_to_decimal(...), Decimal(...), any name in
#     _DECIMAL_COERCERS) passes;
#   * otherwise every VALUE in P — and, when P is a bare name, every dict literal assigned
#     to that name in the same function plus every `P["k"] = v` store — is inspected, and a
#     value that is PROVABLY a float is red: a float literal, `float(...)`, `time.time()`,
#     `math.*`/`statistics.*` results, `round(<float>, n)`, or a true division `a / b`
#     (int / int is a float in Python 3) with neither side a Decimal coercion.
#
# THE BOUND, stated rather than implied. A value produced by an arbitrary call
# (`build_item(...)`, a helper's return) is NOT followed — the gate cannot type it, and
# guessing would red every builder. Those writers keep their per-writer tests. What this
# gate guarantees is narrower and total: no write payload SPELLS a float at the call site.
# Measured 2026-11-10: 307 put_item/update_item call sites in lambdas/ (120 dict literals,
# 104 names, 64 calls — 48 of them floats_to_decimal) and zero offenders, so the allowlist
# below starts empty.
_D6_WRITE_KWARG = {"put_item": "Item", "update_item": "ExpressionAttributeValues"}
_DECIMAL_COERCERS = frozenset(
    {
        "floats_to_decimal",
        "Decimal",
        "to_ddb_decimal",
        "_to_ddb",
        "_ddb",
        "_dec",
        "_deep_dec",
        "_to_dec",
        "_scalar_to_decimal",
        "_parse_decimal_field",
        "int",
        "str",
        "bool",
        "len",
    }
)
_FLOAT_MODULE_CALLS = frozenset({"math", "statistics"})

# "<relpath>:<line>" -> the written reason a float there is safe (e.g. the payload is
# coerced by a caller the AST cannot see). Keep it short; each entry is a review.
D6_UNCOERCED_FLOAT_REASONS: dict[str, str] = {}


def _callee_name(fn) -> str:
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _is_coercion(node) -> bool:
    return isinstance(node, ast.Call) and _callee_name(node.func) in _DECIMAL_COERCERS


def _provably_float(node) -> bool:
    """True when `node` evaluates to a Python float whatever its operands' runtime values."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, float)
    if isinstance(node, ast.Call):
        if _is_coercion(node):
            return False
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "float":
            return True
        if isinstance(fn, ast.Name) and fn.id == "round" and node.args:
            return len(node.args) >= 2 and _provably_float(node.args[0])
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            if fn.value.id in _FLOAT_MODULE_CALLS or (fn.value.id, fn.attr) == ("time", "time"):
                return True
        return False
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Div):
            return not (_is_coercion(node.left) or _is_coercion(node.right))
        return _provably_float(node.left) or _provably_float(node.right)
    if isinstance(node, ast.UnaryOp):
        return _provably_float(node.operand)
    if isinstance(node, ast.IfExp):
        return _provably_float(node.body) or _provably_float(node.orelse)
    return False


def _payload_values(node):
    """Every value expression in a payload literal; a call is a leaf (never descended)."""
    if isinstance(node, ast.Dict):
        for v in node.values:
            yield from _payload_values(v)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for v in node.elts:
            yield from _payload_values(v)
    else:
        yield node


class _D6Visitor(ast.NodeVisitor):
    """Walks one module, keeping a per-function table of what each local name was bound to."""

    def __init__(self):
        self.scopes = [{}]
        self.hits = []  # (lineno, source of the float value)

    def _visit_scope(self, node):
        binds: dict = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if isinstance(tgt, ast.Name):
                        binds.setdefault(tgt.id, []).append(sub.value)
                    elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
                        binds.setdefault(tgt.value.id, []).append(ast.Dict(keys=[None], values=[sub.value]))
        self.scopes.append(binds)
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _visit_scope

    def visit_Call(self, node):
        kwarg = _D6_WRITE_KWARG.get(_callee_name(node.func)) if isinstance(node.func, ast.Attribute) else None
        for kw in node.keywords if kwarg else ():
            if kw.arg != kwarg:
                continue
            candidates = self.scopes[-1].get(kw.value.id, []) if isinstance(kw.value, ast.Name) else [kw.value]
            for payload in candidates:
                if _is_coercion(payload):
                    continue
                for value in _payload_values(payload):
                    if _provably_float(value):
                        self.hits.append((value.lineno, ast.unparse(value)))
        self.generic_visit(node)


def uncoerced_float_writes(src: str) -> list:
    """[(lineno, value source)] for every provable float in a write payload in `src`."""
    visitor = _D6Visitor()
    visitor.visit(ast.parse(src))
    return sorted(set(visitor.hits))


def test_d6_no_uncoerced_float_in_a_write_payload():
    """D6 (#5524): a float a write payload spells at the call site must pass a Decimal coercion."""
    offenders, scanned = [], 0
    for path in _iter_python_sources():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if "put_item(" not in src and "update_item(" not in src:
            continue
        scanned += 1
        rel = os.path.relpath(path, ROOT)
        for lineno, value in uncoerced_float_writes(src):
            if f"{rel}:{lineno}" not in D6_UNCOERCED_FLOAT_REASONS:
                offenders.append(f"{rel}:{lineno}: {value}")
    assert scanned >= 100, f"D6 scanned only {scanned} writer modules — the sweep went blind"
    assert not offenders, (
        "Uncoerced float in a DynamoDB write payload — boto3 rejects it at write time. Wrap the value "
        "(Decimal(str(v))) or the payload (`from common.numeric import floats_to_decimal`) (#5524):\n  " + "\n  ".join(offenders)
    )


def test_d6_allowlist_entries_carry_a_reason():
    for site, reason in D6_UNCOERCED_FLOAT_REASONS.items():
        assert isinstance(reason, str) and len(reason) >= 25, f"{site}: a D6 exemption needs a written reason"


_D6_PLANTS = {
    "a float literal in an Item literal": "def f(t):\n    t.put_item(Item={'pk': 'a', 'v': 0.5})\n",
    "a division in an Item literal": "def f(t, a, b):\n    t.put_item(Item={'pk': 'a', 'ratio': a / b})\n",
    "round() of a division, through a local name": "def f(t, a):\n    item = {'pk': 'a', 's': round(a / 3, 2)}\n    t.put_item(Item=item)\n",
    "a subscript store onto the payload name": "def f(t, a):\n    item = {'pk': 'a'}\n    item['avg'] = a / 2\n    t.put_item(Item=item)\n",
    "float() in update_item values": "def f(t, x):\n    t.update_item(Key={}, ExpressionAttributeValues={':v': float(x)})\n",
    "time.time() nested in a list": "import time\ndef f(t):\n    t.put_item(Item={'pk': 'a', 'seen': [time.time()]})\n",
    "a batch writer": "def f(t):\n    with t.batch_writer() as b:\n        b.put_item(Item={'pk': 'a', 'v': 1.5})\n",
}


def test_d6_mutation_control_reds_on_every_planted_shape():
    """The must-fail control: each planted shape is one the rule must catch. One test that
    reports every miss (not a parametrize — the census counts a parameter as a gate)."""
    missed = sorted(label for label, src in _D6_PLANTS.items() if not uncoerced_float_writes(src))
    assert not missed, f"D6 went blind to: {missed}"


def test_d6_coerced_shapes_stay_green():
    """The other half: the coercions the codebase actually uses must not red."""
    src = textwrap.dedent("""
        from decimal import Decimal
        def f(t, a, b, x):
            t.put_item(Item=floats_to_decimal({'pk': 'a', 'v': a / b}))
            t.put_item(Item={'pk': 'a', 'v': Decimal(str(round(a / b, 2))), 'n': int(a / b), 'w': helper(0.5)})
            item = floats_to_decimal({'pk': 'a', 'v': 0.5})
            t.put_item(Item=item)
            t.update_item(Key={}, ExpressionAttributeValues={':v': Decimal(a) / Decimal(b), ':n': 3})
        """)
    assert uncoerced_float_writes(src) == []


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)

# premerge-gate: structural gate that sweeps the repo tree (#2372)
