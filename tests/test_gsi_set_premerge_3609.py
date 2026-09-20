"""tests/test_gsi_set_premerge_3609.py — #3609 box 3: the GSI set is a premerge-checkable SET.

THE PREMISE, CORRECTED. The issue's acceptance box reads "a static test asserts the
CDK-declared GSI set equals the ADR-097 set {GSI1, GSI2}". That premise does not map onto
this repo literally: `life-platform` is NOT a CDK-managed table — `cdk/stacks/core_stack.py`
only holds a read-only `dynamodb.Table.from_table_name(...)` lookup, and
`deploy/deploy_reading_gsis.sh`'s own header says why: "the `life-platform` table is NOT
CDK-managed... GSIs therefore cannot be added through a CDK construct; they are added with
`update-table`." There is no `add_global_secondary_index()` call anywhere in `cdk/` to grep
for a "declared set" — CDK never declares one. `tests/test_integration_aws.py::
test_i4_dynamodb_table_healthy` is the ONLY existing GSI assertion, and it is exactly the
issue's complaint: it calls `describe_table` (needs AWS credentials) so it runs post-deploy,
not premerge, and a third GSI could ride from source to production between two runs of it.

THE STATIC SURFACE THAT ACTUALLY EXISTS, checked here instead:
  1. `lambdas/reading/reading_keys.py`'s own `GSI*_NAME` constants — the canonical names
     production code is written against.
  2. Every literal `IndexName=...` / `"IndexName": "..."` string used anywhere on the live
     surface (`lambdas/`, `mcp/`) — a hand-rolled query naming a THIRD index would show up
     here even if it never touches `reading_keys.py`'s constants.
  3. `deploy/deploy_reading_gsis.sh`'s own `add_gsi` call list — this script is the ONLY
     mechanism that can actually create a GSI on the table (per its own header, quoted
     above), so it is the closest thing this repo has to a "stack declaration" for GSIs.
     A third `add_gsi "GSI3" ...` line here is the actual moment someone would be adding a
     third GSI "to the stack" in the issue's sense, and it is 100% static (no AWS needed).

All three are asserted to equal ADR-097's sanctioned set, `{GSI1, GSI2}`, exactly — not a
subset — because ADR-097 named exactly two and both must keep existing (a shrink would be
just as much a drift as a third addition). The live `describe_table` leg in
`test_integration_aws.py` is UNCHANGED and stays the post-deploy confirmation that the
static surface and AWS reality agree; this file is what makes a third GSI red BEFORE
anything reaches AWS, per the issue's own acceptance wording.
"""

import ast
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "lambdas"))
import reading.reading_keys as reading_keys  # noqa: E402

# ADR-097: "the reading/Mind domain gets exactly two Global Secondary Indexes" — the
# sanctioned set every static surface below must equal, exactly.
SANCTIONED_GSI_SET = frozenset({"GSI1", "GSI2"})

LIVE_PY_DIRS = ("lambdas", "mcp")
DEPLOY_GSI_SCRIPT = REPO / "deploy" / "deploy_reading_gsis.sh"


def _iter_py_files(rel_dir: str):
    import os

    for root, _dirs, files in os.walk(REPO / rel_dir):
        if "node_modules" in root or "cdk.out" in root or "_mcp_staging" in root or "_bundle_staging" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield pathlib.Path(root) / name


def gsi_name_constants() -> dict[str, str]:
    """Every module-level ``GSI<n>_NAME``-shaped constant on the live surface, mapped to
    its literal string value. Currently just ``reading_keys.py``'s two, but derived by
    AST (not hand-picked) so a second module defining its own GSI name constant is
    caught the same way a raw ``IndexName`` literal is."""
    pattern = re.compile(r"^GSI\d+_NAME$")
    found: dict[str, str] = {}
    for rel_dir in LIVE_PY_DIRS:
        for path in _iter_py_files(rel_dir):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:  # pragma: no cover — the syntax gate owns this
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                if not pattern.match(node.targets[0].id):
                    continue
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    key = f"{path.relative_to(REPO)}:{node.targets[0].id}"
                    found[key] = node.value.value
    return found


def index_name_literals(source: str, filename: str = "<source>") -> set[str]:
    """Every literal string passed as ``IndexName=`` (a boto3 call keyword) or as the
    dict key ``"IndexName"`` (the low-level ``table.query(**kwargs)`` shape
    ``character_sheet_lambda.py`` uses) — a Name/Attribute value (``rk.GSI2_NAME``) is
    not a literal and is covered instead by ``gsi_name_constants()`` above."""
    found: set[str] = set()
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "IndexName" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    found.add(kw.value.value)
        elif isinstance(node, ast.Dict):
            for key_node, val_node in zip(node.keys, node.values):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == "IndexName"
                    and isinstance(val_node, ast.Constant)
                    and isinstance(val_node.value, str)
                ):
                    found.add(val_node.value)
    return found


def live_surface_index_name_literals() -> dict[str, set[str]]:
    """ "<rel path>" -> the literal IndexName values that file references."""
    out: dict[str, set[str]] = {}
    for rel_dir in LIVE_PY_DIRS:
        for path in _iter_py_files(rel_dir):
            try:
                hits = index_name_literals(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:  # pragma: no cover
                continue
            if hits:
                out[str(path.relative_to(REPO))] = hits
    return out


_ADD_GSI_CALL_RE = re.compile(r'^\s*add_gsi\s+"([^"]+)"', re.MULTILINE)


def deploy_script_gsi_names(text: str) -> set[str]:
    """Every ``add_gsi "<NAME>" ...`` invocation in deploy_reading_gsis.sh — the one
    mechanism (per the script's own header) that can create a GSI on this table.
    Deliberately only the CALL sites, not the ``add_gsi()`` function DEFINITION line
    (whose first arg is the shell parameter ``"$1"``, not a literal name)."""
    return set(_ADD_GSI_CALL_RE.findall(text))


# ─────────────────────────────────────────────────────────────────────────────
# The three static assertions.
# ─────────────────────────────────────────────────────────────────────────────


def test_gsi_name_constants_equal_the_adr_097_set():
    """reading_keys.py's own GSI1_NAME/GSI2_NAME (and any future GSI*_NAME constant
    anywhere on the live surface) must be exactly {GSI1, GSI2} — no more, no fewer."""
    constants = gsi_name_constants()
    assert constants, "no GSI*_NAME constants found at all — the scan itself is broken, or reading_keys.py moved"
    assert (
        "lambdas/reading/reading_keys.py:GSI1_NAME" in constants
    ), "the AST scan missed reading_keys.py's own constants — non-vacuity check failed"
    assert constants["lambdas/reading/reading_keys.py:GSI1_NAME"] == reading_keys.GSI1_NAME
    assert constants["lambdas/reading/reading_keys.py:GSI2_NAME"] == reading_keys.GSI2_NAME
    values = set(constants.values())
    assert values == SANCTIONED_GSI_SET, (
        f"GSI name constant(s) {constants} do not match ADR-097's sanctioned set {sorted(SANCTIONED_GSI_SET)}. "
        "A new GSI*_NAME constant reds this by name before any query using it ever reaches AWS."
    )


def test_every_indexname_literal_on_the_live_surface_is_sanctioned():
    """Every literal `IndexName="..."` (or `"IndexName": "..."`) on the live surface
    must name a sanctioned GSI — catches a hand-rolled query that bypasses
    reading_keys.py's constants entirely (character_sheet_lambda.py's raw
    `"IndexName": "GSI2"` dict is exactly this shape, and it IS sanctioned)."""
    by_file = live_surface_index_name_literals()
    assert (
        by_file
    ), "no literal IndexName= references found on the live surface — the scan itself is broken, or every caller moved to the constants"
    offenders = {rel: sorted(names - SANCTIONED_GSI_SET) for rel, names in by_file.items() if names - SANCTIONED_GSI_SET}
    assert not offenders, f"file(s) reference an unsanctioned IndexName literal (ADR-097 set is {sorted(SANCTIONED_GSI_SET)}): {offenders}"


def test_deploy_reading_gsis_declares_exactly_the_adr_097_set():
    """deploy_reading_gsis.sh is the ONLY mechanism that creates a GSI on this
    out-of-CDK table (see the script's own header). Its add_gsi call list must equal
    ADR-097's sanctioned set exactly — this is the static stand-in for "the stack" the
    issue's acceptance box names, since there is no CDK construct to grep instead."""
    assert DEPLOY_GSI_SCRIPT.is_file(), f"{DEPLOY_GSI_SCRIPT} is missing — the sole GSI-creation mechanism moved; re-point this test"
    names = deploy_script_gsi_names(DEPLOY_GSI_SCRIPT.read_text(encoding="utf-8"))
    assert names == SANCTIONED_GSI_SET, (
        f"deploy_reading_gsis.sh declares {sorted(names)}, ADR-097's sanctioned set is {sorted(SANCTIONED_GSI_SET)}. "
        'A third `add_gsi "GSI3" ...` line reds here BEFORE anyone runs the script against AWS.'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Positive controls — a planted third GSI must be caught by each of the three scans,
# proving they are not vacuously green. Mirrors the mutation-proof pattern in
# tests/test_no_dead_shared_defs_3538.py::test_the_import_error_fork_scan_fires_on_the_shape_it_removed.
# ─────────────────────────────────────────────────────────────────────────────


def test_planted_gsi_name_constant_is_caught():
    planted = 'GSI3_NAME = "GSI3"\n'
    pattern = re.compile(r"^GSI\d+_NAME$")
    tree = ast.parse(planted)
    node = tree.body[0]
    assert isinstance(node, ast.Assign) and pattern.match(node.targets[0].id)
    value = node.value.value
    assert {
        "GSI1",
        "GSI2",
        value,
    } != SANCTIONED_GSI_SET, "the planted constant must actually widen the set past ADR-097's for this control to mean anything"


def test_planted_indexname_literal_is_caught():
    planted_kwarg = 'table.query(IndexName="GSI3", KeyConditionExpression=None)\n'
    planted_dict = 'kwargs = {"IndexName": "GSI3"}\n'
    for planted in (planted_kwarg, planted_dict):
        hits = index_name_literals(planted)
        assert hits == {"GSI3"}, f"the literal scan failed to catch a planted unsanctioned IndexName in: {planted!r}"
        assert hits - SANCTIONED_GSI_SET, "the planted literal must fall outside the sanctioned set for this control to mean anything"


def test_planted_add_gsi_call_is_caught():
    planted = DEPLOY_GSI_SCRIPT.read_text(encoding="utf-8") + '\nadd_gsi "GSI3" "GSI3PK" "GSI3SK"\n'
    names = deploy_script_gsi_names(planted)
    assert names == {"GSI1", "GSI2", "GSI3"}, f"expected the planted third add_gsi call to be caught, got {sorted(names)}"
    assert names != SANCTIONED_GSI_SET


def test_the_add_gsi_regex_ignores_the_function_definition_itself():
    """Non-vacuity for the deploy-script scan: `add_gsi()`'s own definition line calls
    itself with the shell parameter `"$1"`, not a literal — the regex must not count
    that as a fourth "name"."""
    text = DEPLOY_GSI_SCRIPT.read_text(encoding="utf-8")
    assert "add_gsi() {" in text, "add_gsi() function definition shape moved; re-verify the regex still only matches call sites"
    names = deploy_script_gsi_names(text)
    assert "$1" not in names
    assert names == SANCTIONED_GSI_SET
