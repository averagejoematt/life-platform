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


# ── #3784: the guard checked only the FIRST hop ──────────────────────────────
# `_allowed_names()` is stdlib ∪ lane deps ∪ _repo_local_names(), and the last term
# adds every directory name in the repo. So `web`, `content`, `lambdas`, `mcp` are
# allowed UNCONDITIONALLY — a first-party module that transitively reaches a
# non-lane third-party package was invisible.
#
# It passed on 2026-09-14 while a THIRD instance of its own class shipped and redded
# main: tests/test_recap_campaign_3741.py imported `web.recap_charts` at module
# scope, which reaches `web.card_engine`, which does `from PIL import Image`. PIL is
# not in the lane, collection died, and — because a collection error takes the WHOLE
# lane with exit 2 rather than exit 1 — `Plan` and `Deploy` skipped behind it.
#
# DEPTH: full transitive closure over first-party modules, not a fixed number of
# hops. The issue offers "one level is enough for all three known cases", but that is
# only true of the cases we have seen: `web.recap_layouts -> web.recap_charts ->
# web.card_engine -> PIL` is already TWO hops, and picking a depth means the next
# chain one hop longer is invisible again — the same shape as checking the first hop.
# The first-party graph is finite and small, so the closure is cheap, and it is
# memoized and cycle-safe.
_FIRST_PARTY_ROOTS = ("lambdas", "mcp", "scripts", "deploy", "cdk", "remediation", "")


def _resolve_first_party(dotted):
    """The file a dotted first-party module name resolves to, or None.

    `lambdas/` is packaged by domain and staged at the ZIP ROOT, so runtime imports
    read `from web import card_engine` while the file lives at lambdas/web/card_engine.py.
    Both spellings are tried.
    """
    parts = dotted.split(".")
    for root in _FIRST_PARTY_ROOTS:
        base = REPO_ROOT / root if root else REPO_ROOT
        cand = base.joinpath(*parts)
        for path in (cand.with_suffix(".py"), cand / "__init__.py"):
            if path.is_file():
                return path
    return None


def _transitive_third_party(dotted, allowed, _seen=None, _depth=0):
    """Third-party top-level names reachable from a first-party module at module scope.

    Returns [(name, chain)] so a finding can name the PATH, not just the leaf — the
    thing a reader needs in order to fix it.
    """
    if _seen is None:
        _seen = set()
    if dotted in _seen or _depth > 12:  # 12 is a cycle/pathology stop, not a policy depth
        return []
    _seen.add(dotted)
    path = _resolve_first_party(dotted)
    if path is None:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    found = []
    for _lineno, top, target in _module_scope_imports(tree, with_targets=True):
        if _resolve_first_party(target or top) is not None:
            for name, chain in _transitive_third_party(target or top, allowed, _seen, _depth + 1):
                found.append((name, [dotted] + chain))
        elif top not in allowed:
            found.append((top, [dotted, top]))
    return found


def _module_scope_imports(tree, with_targets=False):
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
                out.extend((node.lineno, a.name.split(".")[0], a.name) for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                # `from web import recap_charts` names a SUBMODULE, and that submodule is
                # what reaches PIL — the dotted parent alone would resolve to a package
                # __init__ that imports nothing.
                emitted = False
                for a in node.names:
                    cand = f"{node.module}.{a.name}"
                    if _resolve_first_party(cand) is not None:
                        out.append((node.lineno, top, cand))
                        emitted = True
                if not emitted:
                    out.append((node.lineno, top, node.module))
            elif isinstance(node, ast.If):
                _sweep(node.body)
                _sweep(node.orelse)

    _sweep(tree.body)
    return out if with_targets else [(ln, top) for ln, top, _t in out]


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
        for lineno, name, target in _module_scope_imports(tree, with_targets=True):
            if name not in allowed and name not in guarded:
                offenders.append(
                    f"{path.name}:{lineno}: module-scope import of `{name}` is outside the "
                    f"deploy-critical lane's dep set {LANE_THIRD_PARTY_DEPS} — collection would "
                    f'crash the whole lane (#2699/#2732 class). pytest.importorskip("{name}") '
                    "first, or move the import into the test body."
                )
                continue
            # #3784: the first hop is first-party and therefore always allowed. Follow it.
            if _resolve_first_party(target) is None:
                continue
            for reached, chain in _transitive_third_party(target, allowed):
                if reached in guarded:
                    continue  # an importorskip before the import is the sanctioned escape
                offenders.append(
                    f"{path.name}:{lineno}: module-scope import of `{target}` TRANSITIVELY reaches "
                    f"`{reached}`, which is outside the lane's dep set {LANE_THIRD_PARTY_DEPS} — "
                    f"chain: {' -> '.join(chain)}. Collection would crash the WHOLE lane with exit 2 "
                    f'(#3784 class, the #2699/#2732 defect one hop out). pytest.importorskip("{reached}") '
                    "before the import, or move the import into the test body."
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
    """Mutation proof, in-suite and permanent: a planted forbidden import is flagged.

    The acceptance asks for watched-fail evidence; this keeps it executable
    forever instead of a one-time PR-body paste.

    The plant is `requests`, NOT `yaml`. It was `yaml` until #3684 put pyyaml in
    LANE_THIRD_PARTY_DEPS — at which point the plant became LEGAL and this mutation
    proof silently stopped proving anything (it failed loudly here, which is the only
    reason the coupling was noticed). A positive control keyed to a value that can
    later be sanctioned is a control with an expiry date on it.

    `requests` cannot acquire that problem: CLAUDE.md forbids external HTTP libraries
    outright — stdlib urllib only, with Bedrock via boto3 the single stated exception —
    so it can never legitimately enter the lane dep set.
    """
    plant = tmp_path / "test_planted_offender.py"
    plant.write_text("import requests\n\n\ndef test_x():\n    pass\n")
    tree = ast.parse(plant.read_text())
    hits = [n for _, n in _module_scope_imports(tree) if n not in _allowed_names()]
    assert hits == ["requests"], "the guard must flag a module-scope import outside the dep set"


def test_the_two_prior_instances_stay_guarded():
    """#2699/#2732's importorskip fixes are the sanctioned shape — never flagged."""
    src = "import pytest\npytest.importorskip('yaml')\nimport yaml\n\n\ndef test_x():\n    pass\n"
    tree = ast.parse(src)
    guarded = _importorskip_names(tree)
    offenders = [n for _, n in _module_scope_imports(tree) if n == "yaml" and n not in guarded]
    assert offenders == [], "importorskip-then-import is the sanctioned escape and must stay exempt"


# ── #3784: the transitive hop the first-hop check could not see ──────────────
_PROBE_3784 = "test_census_probe_3784_transitive.py"


def _run_guard_over(tmp_tests: Path):
    """Run the pure sweep over one planted file, without pytest re-collecting the repo."""
    allowed = _allowed_names()
    tree = ast.parse(tmp_tests.read_text(encoding="utf-8"), filename=str(tmp_tests))
    guarded = _importorskip_names(tree)
    found = []
    for lineno, name, target in _module_scope_imports(tree, with_targets=True):
        if name not in allowed and name not in guarded:
            found.append((name, ["<direct>", name]))
            continue
        if _resolve_first_party(target) is None:
            continue
        for reached, chain in _transitive_third_party(target, allowed):
            if reached not in guarded:
                found.append((reached, chain))
    return found


@pytest.mark.deploy_critical
def test_MUST_FAIL_a_first_party_import_that_transitively_reaches_a_non_lane_dep(tmp_path):
    """The exact shape that shipped and redded main on 2026-09-14.

    `web.recap_canvas` -> `web.card_engine` -> `PIL`. The old guard returned [] for this:
    `web` is a repo directory, so `_repo_local_names()` allowed it unconditionally and the
    first-hop check was satisfied.
    """
    probe = tmp_path / _PROBE_3784
    probe.write_text("from web import recap_canvas\n", encoding="utf-8")
    found = _run_guard_over(probe)
    assert any(name == "PIL" for name, _chain in found), (
        f"a module-scope first-party import reaching PIL was NOT reported — the transitive " f"hop is invisible again (#3784). got: {found}"
    )
    chain = next(c for n, c in found if n == "PIL")
    assert "web.card_engine" in chain, f"the finding must name the PATH, not just the leaf — got {chain}"


@pytest.mark.deploy_critical
def test_the_importorskip_escape_STAYS_exempt_for_a_transitive_reach(tmp_path):
    """The control without which the fix above is just a louder guard.

    `pytest.importorskip("PIL")` before the import is the sanctioned shape — collection
    skips rather than crashing — and it must keep working for a TRANSITIVE reach, not only
    a direct one. tests/test_recap_render_3744.py relies on exactly this.
    """
    probe = tmp_path / _PROBE_3784
    probe.write_text('import pytest\n\npytest.importorskip("PIL")\n\nfrom web import recap_canvas\n', encoding="utf-8")
    assert _run_guard_over(probe) == [], "the sanctioned importorskip escape was broken by the transitive check"


@pytest.mark.deploy_critical
def test_a_first_party_import_that_reaches_nothing_third_party_is_silent(tmp_path):
    """Negative control: the guard must not red every first-party import in the repo."""
    probe = tmp_path / _PROBE_3784
    probe.write_text("from common import constants\n", encoding="utf-8")
    assert _run_guard_over(probe) == [], "a harmless first-party import was reported — the check cries wolf"


@pytest.mark.deploy_critical
def test_the_closure_is_cycle_safe():
    """A first-party import cycle must terminate rather than recurse forever."""
    allowed = _allowed_names()
    # `web` is a real package with real internal edges; running the closure over it is the
    # cheapest honest cycle exercise available without planting files in the source tree.
    out = _transitive_third_party("web.recap_canvas", allowed)
    assert any(n == "PIL" for n, _c in out)
