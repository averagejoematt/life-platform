"""tests/test_budget_ceiling_registry_2898.py — #2898: the ceiling family has ONE source.

THE DEFECT (measured, #2836)
  Moving the monthly base $85 → $150 should have been a one-line edit. It was a 26-file
  sweep, because the number lived in five authoritative code sites plus ~18 prose ones.
  Nothing failed when a copy drifted; it just lied. `coach_sim_scoreboard.py` and
  `COACH_HUMANITY_ROADMAP.md` still said $115 twelve days after #2734 raised the August
  window to $200, with two guards running over those files the whole time.

THE CONTRACT THIS GUARD ENFORCES (charter primitive #2, the derivation guard)
  `lambdas/operational/cost_governor_lambda.py` owns four numbers — MONTHLY_CEILING,
  SURGE_CEILING_USD, and the dated pair _TEMP_CEILING_USD / _TEMP_SURGE_CEILING_USD. No
  other executable site in lambdas/, cdk/, mcp/, scripts/, deploy/, tests/ or site/ may
  state one of them as a literal. Consumers import (`site_api_budget`), or parse via the
  ONE shared derivation `scripts/budget_ceilings.py` (`core_stack`, `check_doc_facts`).

WHY THIS IS NOT check_doc_facts's JOB — the two are complements, not overlaps
  `scripts/check_doc_facts.py` fails on a ceiling figure that is WRONG (a line claiming a
  figure the governor does not currently allow). It is silent on a figure that is RIGHT
  and hand-typed — which is every copy, on the day it is written. That is the state the
  whole family sat in, permanently green, right up until the number moved. This guard
  fails on the hand-typing itself, so the copy never exists to go stale.

GUARD THE SET, NOT THE INSTANCE
  Nothing below hand-lists a dollar figure. Every rule derives its forbidden values from
  the governor via `budget_ceilings.read_family().all_figures()`, and the file surface
  from `git ls-files` — so a new consumer, a new ceiling value, or a new file joins the
  guard's population without anyone editing this file. That makes it a repo-shape ratchet,
  and it is registered in `tests/conftest.py::_PREMERGE_EXTRA_FILES` accordingly (#2372).

FIXTURE MUST BE THE WIRE
  `test_ast_parse_matches_the_imported_governor` imports the real governor module and
  asserts the AST derivation agrees with it field by field. Without that, every other
  assertion here could be self-consistently wrong about what the governor actually says.

Run:  python3 -m pytest tests/test_budget_ceiling_registry_2898.py -v
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import budget_ceilings  # noqa: E402
from budget_ceilings import read_family  # noqa: E402

FAMILY = read_family()

# The forbidden values, derived. `all_figures()` is deliberately the window-agnostic set:
# a hand-typed copy of the dated-window pair is the exact drift #2836 measured, and it must
# be illegal on the day it is written, not only after the window expires (#2898 box 4).
FORBIDDEN = FAMILY.all_figures()

# The executable surface. `git ls-files` — never a filesystem walk — so build artifacts
# (`cdk/_bundle_staging/`, `cdk/_mcp_staging/`, which contain a STAGED COPY of the governor
# itself) can never be mistaken for source and turn this guard into a permanent red.
_CODE_ROOTS = ("lambdas/", "cdk/", "mcp/", "scripts/", "deploy/", "tests/")
_SITE_ROOT = "site/"
# The frozen pre-v4 mirror. Same exemption check_doc_facts grants it: it is a historical
# artifact nobody edits, and rewriting it to derive would be rewriting history.
_SITE_EXEMPT = ("site/legacy/",)

# A ceiling-ish CONSTANT name. Two shapes, both drawn from what the tree actually uses:
# anything with "ceiling" in it, and the budget-amount family (BUDGET_LIMIT/…_USD/…_AMOUNT/
# …_CAP). Deliberately NOT a bare "budget": `platform_memory.py` has a local `budget =
# max(200, ...)` counting CHARACTERS, and a guard that flags token budgets as dollars is a
# guard people learn to route around.
_CEILING_NAME = re.compile(r"ceiling|budget[a-z0-9_]*(usd|limit|amount|cap)", re.I)
# The same idea for a dict key: `{"budget_ceiling_usd": 150}` is a hand-typed copy that no
# constant-name rule would ever see.
_CEILING_KEY = re.compile(r"^[a-z_]*(ceiling|budget_(limit|amount|usd|cap))[a-z_]*$", re.I)


def _tracked(prefixes) -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=_REPO, capture_output=True, text=True, check=True).stdout.split()
    return [_REPO / f for f in out if f.startswith(prefixes)]


def _numeric_literals(node) -> list[float]:
    return [
        c.value
        for c in ast.walk(node)
        if isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool)
    ]


def _constant_assignments(tree):
    """Module-level and class-level assignments — where constants live.

    Function bodies are out of scope on purpose: a local named `ceiling` is nearly always
    a loop or clamp variable, and this guard is about the declared vocabulary of the tree.
    """
    for node in tree.body:
        yield node
        if isinstance(node, ast.ClassDef):
            yield from node.body


def _python_offenders(files, forbidden) -> list[str]:
    """Every hand-typed ceiling-family literal in `files`. The scan is exposed (and takes
    `files`/`forbidden`) so the mutation tests can run the REAL rule over a planted file
    rather than a re-implementation of it — the #1189 non-vacuous-scan lesson."""
    forbidden = {float(v) for v in forbidden}
    hits = []
    governor = FAMILY.source.resolve()
    for path in files:
        if path.suffix != ".py" or path.resolve() == governor:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO) if path.is_relative_to(_REPO) else path
        for node in _constant_assignments(tree):
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            if node.value is None or not any(_CEILING_NAME.search(n) for n in names):
                continue
            bad = sorted({v for v in _numeric_literals(node.value) if float(v) in forbidden})
            if bad:
                hits.append(f"{rel}:{node.lineno}: {names} hand-types the ceiling family {bad}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and _CEILING_KEY.match(key.value)):
                    continue
                bad = sorted({v for v in _numeric_literals(value) if float(v) in forbidden})
                if bad:
                    hits.append(f"{rel}:{key.lineno}: key {key.value!r} hand-types the ceiling family {bad}")
    return hits


def _site_offenders(files, forbidden) -> list[str]:
    """Ceiling-family dollar figures written as literals in shipped site source.

    Text, not AST, because the target is `"$150"` inside a template string — the form the
    2026-08-23 diligence fact-check found shipping stale in four places no gate scanned.
    """
    figures = sorted({int(v) for v in forbidden})
    if not figures:
        return []
    pattern = re.compile(r"\$(" + "|".join(str(f) for f in figures) + r")\b(?!\.\d)")
    hits = []
    for path in files:
        if path.suffix not in (".js", ".html"):
            continue
        rel = str(path.relative_to(_REPO)) if path.is_relative_to(_REPO) else str(path)
        if rel.startswith(_SITE_EXEMPT):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for mo in pattern.finditer(line):
                hits.append(f"{rel}:{lineno}: hand-typed ${mo.group(1)} — read it from /api/receipts instead\n      | {line.strip()[:120]}")
    return hits


# ── The source is real, and the parse agrees with it ──────────────────────────


def test_ast_parse_matches_the_imported_governor():
    """Fixture-must-be-the-wire: the AST derivation and the executed module agree.

    Everything else in this file trusts `read_family()`. If that parse silently returned
    None for a renamed constant, every rule below would pass over an empty forbidden set —
    green, and enforcing nothing.
    """
    from operational import cost_governor_lambda as gov

    assert FAMILY.base == gov.MONTHLY_CEILING
    assert FAMILY.surge == gov.SURGE_CEILING_USD
    assert FAMILY.window_base == gov._TEMP_CEILING_USD
    assert FAMILY.window_surge == gov._TEMP_SURGE_CEILING_USD
    assert FAMILY.window == gov._TEMP_CEILING_WINDOW


def test_the_family_is_non_empty_and_covers_the_dated_window():
    """#2898 box 4: the window pair is part of the family, not an afterthought.

    A four-figure family is also this whole file's non-vacuity precondition — an empty
    FORBIDDEN set would make every sweep below pass by finding nothing to look for.
    """
    assert FAMILY.window is not None, "the governor's dated ceiling window is no longer discoverable"
    assert len(FORBIDDEN) == 4, f"expected base + surge + the dated pair, derived {sorted(FORBIDDEN)}"
    assert FAMILY.all_figures() >= {int(FAMILY.window_base), int(FAMILY.window_surge)}


# ── The sweep: nobody hand-types a ceiling figure ─────────────────────────────


def test_no_python_consumer_hand_types_the_ceiling_family():
    offenders = _python_offenders(_tracked(_CODE_ROOTS), FORBIDDEN)
    assert not offenders, "hand-typed budget-ceiling copies — derive from the cost governor (#2898):\n" + "\n".join(offenders)


def test_no_site_asset_hand_types_the_ceiling_family():
    offenders = _site_offenders(_tracked((_SITE_ROOT,)), FORBIDDEN)
    assert not offenders, "hand-typed budget-ceiling copies in shipped site source (#2898):\n" + "\n".join(offenders)


# ── The named consumers, each proved to derive ────────────────────────────────


def test_site_api_budget_fallback_is_the_governor_constant():
    """#2898 work item 1. The fail-closed fallback is MONTHLY_CEILING itself."""
    from operational import cost_governor_lambda as gov
    from web import site_api_budget as budget

    assert budget._ADR133_BASE_CEILING_USD == gov.MONTHLY_CEILING
    assert budget._ADR133_BASE_CEILING_USD is gov.MONTHLY_CEILING, "same object — an equal-but-separate literal is the drift this guards"


def test_site_api_budget_declares_no_ceiling_literal():
    """The value equality above would still pass if someone re-typed the same number.
    This is the structural half: the assignment's right-hand side must be a NAME."""
    tree = ast.parse((_REPO / "lambdas" / "web" / "site_api_budget.py").read_text(encoding="utf-8"))
    found = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ADR133_BASE_CEILING_USD" for t in n.targets)
    ]
    assert len(found) == 1, "_ADR133_BASE_CEILING_USD is no longer a single module-level assignment"
    assert isinstance(found[0].value, ast.Name), "_ADR133_BASE_CEILING_USD must be bound to an imported name, not a literal (#2898)"


def test_site_api_intelligence_reexports_the_derived_value():
    """The facade re-import (site_api_intelligence:62) must follow, not shadow."""
    from web import site_api_budget as budget, site_api_intelligence as sai

    assert sai._ADR133_BASE_CEILING_USD is budget._ADR133_BASE_CEILING_USD


def test_cdk_budget_backstop_derives_from_the_governor():
    """#2898 work item 2. The AWS Budgets amount is the governor's base.

    The two sat out of step by design through August 2026 (#2836) and the reason expires
    with the dated window; from here the backstop tracks the base by construction.

    Asserted through `budget_ceilings.budget_amount_usd()` rather than by importing
    `stacks.core_stack`, deliberately. `aws_cdk` is not installed in the offline test job
    and `tests/test_role_policies.py` puts a STUB module into `sys.modules` at import
    time to work around that — so a real stack import passes alone and fails in the
    suite, on a stub a different file installed. (Measured, not theorised: the first
    draft of this test did import the stack, passed in isolation, and failed the full
    run with `cannot import name 'Duration' from 'aws_cdk'`.) The AST test below binds
    that value to the actual `SpendProperty(amount=...)` call site, and the synth-diff
    on the PR is the end-to-end evidence: byte-identical template, Amount 150.
    """
    amount = budget_ceilings.budget_amount_usd()

    assert amount == FAMILY.base
    assert isinstance(amount, int), "an integral ceiling must synth as an int — 150.0 would rewrite the CfnBudget template"


def test_cdk_budget_amount_is_not_a_template_literal():
    """AST half: `SpendProperty(amount=...)` must reference the derived module constant.

    Name-checked, not just non-literal: `amount=42` and `amount=SOME_OTHER_NAME` are both
    ways to smuggle a second source in, and only one of them is a Constant.
    """
    tree = ast.parse((_REPO / "cdk" / "stacks" / "core_stack.py").read_text(encoding="utf-8"))
    amounts = [
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "SpendProperty"
        for kw in node.keywords
        if kw.arg == "amount"
    ]
    assert amounts, "the CfnBudget SpendProperty(amount=...) call is gone — this guard is now vacuous"
    for value in amounts:
        assert not isinstance(value, ast.Constant), "the AWS Budgets amount must derive from the cost governor, not a literal (#2898)"
        assert isinstance(value, ast.Name) and value.id == "BUDGET_AMOUNT_USD", f"unexpected budget amount source: {ast.dump(value)}"

    # ...and BUDGET_AMOUNT_USD is itself computed, not re-typed.
    bound = [
        n.value
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign))
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
        if isinstance(t, ast.Name) and t.id == "BUDGET_AMOUNT_USD"
    ]
    assert len(bound) == 1 and isinstance(bound[0], ast.Call), "BUDGET_AMOUNT_USD must be derived by a call, not assigned a value"


def test_doc_facts_gate_derives_its_allowed_set_from_the_same_module():
    """#2898 work item 5. The prose gate's BUDGET_OK is the shared derivation's output —
    it used to be a hand-typed set that had to be edited in the same commit as the thing
    it policed, which makes a gate a rubber stamp."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_docfacts_2898", _REPO / "scripts" / "check_doc_facts.py")
    facts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(facts)

    assert facts.BUDGET_OK == FAMILY.figures()
    assert facts._governor_ceilings is budget_ceilings.governor_ceilings, "the doc gate must use the ONE derivation, not a second parser"
    # The gate's own error message must not restate the truth it derives (#2898).
    assert str(int(FAMILY.base)) not in _gate_message_template(), "check_doc_facts hand-types the ceiling in its own failure text"


def _gate_message_template() -> str:
    """The literal source of the ceiling-offender message, so the assertion above reads
    the shipped string rather than a re-render of it."""
    text = (_REPO / "scripts" / "check_doc_facts.py").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if "budget ceiling, truth is" in line)


# Files that match "names the window constant AND calls ast.parse" without being a second
# derivation. `budget_ceilings.py` IS the derivation; this file names the constant only to
# assert the parse agrees with the imported module, and calls `ast.parse` to read consumers.
# (Not hypothetical bookkeeping: this file did not self-match until the commit that TRACKED
# it — `git ls-files` cannot see an untracked file — so the guard's own population changed
# under it at commit time. Worth remembering for any `ls-files`-scoped sweep.)
_NOT_A_SECOND_PARSER = frozenset({"budget_ceilings.py", Path(__file__).name})


def test_only_one_ast_derivation_of_the_ceiling_family_exists():
    """The collapse has to hold one level up too: two PARSERS of the governor would be the
    same hand-maintenance problem wearing a different hat (it is why check_doc_facts's
    parse moved into scripts/budget_ceilings.py rather than being copied into CDK)."""
    parsers = []
    for path in _tracked(_CODE_ROOTS):
        if path.suffix != ".py" or path.name in _NOT_A_SECOND_PARSER:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if budget_ceilings.WINDOW_NAME in text and "ast.parse" in text:
            parsers.append(str(path.relative_to(_REPO)))
    assert not parsers, "a second AST parser of the governor's ceilings exists — use scripts/budget_ceilings.py:\n" + "\n".join(parsers)


# ── Mutation proof: the sweeps bite ───────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        "MONTHLY_CEILING_USD = {v}\n",  # the constant copy
        "class C:\n    CEILING_USD = {v}\n",  # a class attribute
        "BUDGET_LIMIT_USD = float({v})\n",  # wrapped in a call
        'CONFIG = {{"budget_ceiling_usd": {v}}}\n',  # the dict-key form
    ],
    ids=["module-const", "class-attr", "wrapped-call", "dict-key"],
)
def test_python_sweep_bites_on_a_planted_copy(tmp_path, body):
    planted = tmp_path / "planted_consumer.py"
    planted.write_text(body.format(v=int(FAMILY.base)), encoding="utf-8")
    assert _python_offenders([planted], FORBIDDEN), f"the python sweep missed a hand-typed copy shaped as: {body!r}"


def test_python_sweep_bites_on_the_dated_window_value_too(tmp_path):
    """#2898 box 4, mutation-proved: a copy of the AUGUST pair is illegal today, not only
    once the window has expired and check_doc_facts starts calling it stale."""
    planted = tmp_path / "planted_window.py"
    planted.write_text(f"TEMP_CEILING_USD = {int(FAMILY.window_base)}\n", encoding="utf-8")
    assert _python_offenders([planted], FORBIDDEN), "the dated-window pair is not being guarded"


def test_python_sweep_ignores_an_unrelated_number(tmp_path):
    """Non-false-positivity: a character budget is not a dollar ceiling."""
    planted = tmp_path / "unrelated.py"
    planted.write_text(
        "CEILING_USD = 7\n\n\ndef f(max_chars):\n    budget = max(200, int(max_chars))\n    return budget\n", encoding="utf-8"
    )
    assert not _python_offenders([planted], FORBIDDEN)


def test_site_sweep_bites_on_a_planted_copy(tmp_path):
    planted = tmp_path / "planted.js"
    planted.write_text(f"const t = `hard ceiling — ${int(FAMILY.base)} base`;\n", encoding="utf-8")
    assert _site_offenders([planted], FORBIDDEN), "the site sweep missed a hand-typed ceiling figure"


def test_site_sweep_ignores_the_dated_adr063_original(tmp_path):
    """$75 is history the governor no longer owns — it must stay sayable."""
    planted = tmp_path / "history.js"
    planted.write_text('const t = "ADR-063 set the original $75";\n', encoding="utf-8")
    assert not _site_offenders([planted], FORBIDDEN)
    assert 75 not in FORBIDDEN, "if the ADR-063 original ever re-enters the family, revisit this exemption"
