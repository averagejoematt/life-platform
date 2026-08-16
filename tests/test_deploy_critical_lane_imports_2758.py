"""#2758 — the deploy-critical lane's collection surface, guarded as a SET.

The minimal lane installs only ``deploy_critical_lane_deps.LANE_THIRD_PARTY_DEPS``
but runs ``pytest tests/ -m "deploy_critical and not integration"``, which
COLLECTS every module under tests/. A module-scope import outside that dep set
crashes collection for the whole lane and skips Plan → Deploy — it redded main
twice in 48h: #2699 (module-level ``import yaml``) and #2732 (an import-time
census, same shape). Both were fixed per-instance with ``pytest.importorskip``;
this file is the guard for the CLASS (guard the set, not the instance).

Single source of truth: ``tests/deploy_critical_lane_deps.py`` — this guard
checks against it, and ``test_workflow_install_list_matches_the_dep_module``
pins the workflow's literal install list to it (the names stay literal in
ci-cd.yml so ``test_ci_pin_consistency`` can statically verify the pins).

Self-protection: this module imports only stdlib + pytest, so it is collectable
in the minimal lane itself, and it is marked ``deploy_critical`` so the lane
runs it — a new offender fails premerge in BOTH the full suite and the lane.

The sanctioned per-instance escape stays sanctioned: a module-scope import
AFTER a ``pytest.importorskip("<mod>")`` call is exempt (collection hits the
skip first — the #2699/#2732 fix shape).
"""

import ast
import re
import sys
from pathlib import Path

import pytest

from tests.deploy_critical_lane_deps import DEP_IMPORT_NAMES, LANE_THIRD_PARTY_DEPS

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent


_SKIP_DIRS = {".git", ".venv", "node_modules", "cdk.out", "site", "__pycache__", ".pytest_cache"}


def _repo_local_names():
    """Every module/package name the repo itself can satisfy, from any directory.

    tests/ files commonly do their own ``sys.path.insert`` (scripts/, deploy/,
    lambdas domain dirs) before importing — a repo-local module can never be
    missing from the lane's venv, so ANY repo .py stem or package dir is safe.
    The class this guard hunts is third-party names (yaml, requests, …), which
    cannot be satisfied by the tree. Over-allowing a colliding stem is the
    accepted trade: the failure mode it reintroduces is the status quo ante for
    that one name, while under-allowing red-flags hundreds of honest files.
    """
    names = {"tests", "conftest"}

    def _walk(d):
        for child in d.iterdir():
            if child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            if child.suffix == ".py":
                names.add(child.stem)
            elif child.is_dir():
                names.add(child.name)
                _walk(child)

    _walk(REPO_ROOT)
    return names


def _allowed_names():
    allowed = set(sys.stdlib_module_names)
    for dist in LANE_THIRD_PARTY_DEPS:
        allowed |= DEP_IMPORT_NAMES[dist]
    return allowed | _repo_local_names()


def _importorskip_names(tree):
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "importorskip"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(str(node.args[0].value).split(".")[0])
    return names


def _module_scope_imports(tree):
    """(lineno, top-level name) for every import that executes at collection.

    Module body statements only — imports inside defs/classes are lazy and
    exempt. ``try:`` bodies at module scope DO execute, but a try/except
    ImportError is the other sanctioned guard shape, so ast.Try is exempt.
    ``if`` bodies at module scope execute when true, so they are swept.
    """
    out = []

    def _sweep(stmts):
        for node in stmts:
            if isinstance(node, ast.Import):
                out.extend((node.lineno, a.name.split(".")[0]) for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                out.append((node.lineno, node.module.split(".")[0]))
            elif isinstance(node, ast.If):
                _sweep(node.body)
                _sweep(node.orelse)

    _sweep(tree.body)
    return out


@pytest.mark.deploy_critical
def test_top_level_imports_resolve_in_minimal_lane():
    """Every tests/*.py module-scope import must be satisfiable in the minimal lane."""
    allowed = _allowed_names()
    offenders = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as e:  # a syntax error crashes collection even harder
            offenders.append(f"{path.name}:{e.lineno}: does not parse: {e.msg}")
            continue
        guarded = _importorskip_names(tree)
        for lineno, name in _module_scope_imports(tree):
            if name not in allowed and name not in guarded:
                offenders.append(
                    f"{path.name}:{lineno}: module-scope import of `{name}` is outside the "
                    f"deploy-critical lane's dep set {LANE_THIRD_PARTY_DEPS} — collection would "
                    f'crash the whole lane (#2699/#2732 class). pytest.importorskip("{name}") '
                    "first, or move the import into the test body."
                )
    assert not offenders, "\n".join(offenders)


@pytest.mark.deploy_critical
def test_workflow_install_list_matches_the_dep_module():
    """ci-cd.yml's deploy-critical install list == LANE_THIRD_PARTY_DEPS, exactly.

    The names stay LITERAL in the workflow so test_ci_pin_consistency can
    statically verify each is pinned (an indirection was tried and correctly
    rejected by that guard); THIS test is what makes the two copies one source —
    fork the lists in either direction and it names the drift.
    """
    wf = (REPO_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text()
    m = re.search(r"#2758[\s\S]*?ci_pins\.py ([a-z0-9_\- ]+)\)", wf)
    assert m, "could not find the deploy-critical ci_pins.py install line in ci-cd.yml (#2758)"
    workflow_list = tuple(m.group(1).split())
    assert workflow_list == LANE_THIRD_PARTY_DEPS, (
        f"ci-cd.yml installs {workflow_list} but deploy_critical_lane_deps.py declares "
        f"{LANE_THIRD_PARTY_DEPS} — update BOTH in one commit (#2758 single-source contract)."
    )


def test_guard_can_fail_on_a_planted_offender(tmp_path, monkeypatch):
    """Mutation proof, in-suite and permanent: a planted `import yaml` is flagged.

    The acceptance asks for watched-fail evidence; this keeps it executable
    forever instead of a one-time PR-body paste.
    """
    plant = tmp_path / "test_planted_offender.py"
    plant.write_text("import yaml\n\n\ndef test_x():\n    pass\n")
    tree = ast.parse(plant.read_text())
    hits = [n for _, n in _module_scope_imports(tree) if n not in _allowed_names()]
    assert hits == ["yaml"], "the guard must flag a module-scope import outside the dep set"


def test_the_two_prior_instances_stay_guarded():
    """#2699/#2732's importorskip fixes are the sanctioned shape — never flagged."""
    src = "import pytest\npytest.importorskip('yaml')\nimport yaml\n\n\ndef test_x():\n    pass\n"
    tree = ast.parse(src)
    guarded = _importorskip_names(tree)
    offenders = [n for _, n in _module_scope_imports(tree) if n == "yaml" and n not in guarded]
    assert offenders == [], "importorskip-then-import is the sanctioned escape and must stay exempt"
