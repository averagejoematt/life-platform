#!/usr/bin/env python3
"""tests/test_suite_parallel_safety_3025.py — the pre-merge full suite runs in parallel,
and stays able to (#3025's duration class, 8th instance and first structural answer).

WHY THIS EXISTS. The full-suite duration budget has been breached and answered seven
times — #1349, #1966, #2152, #3025, #3106, #3224, #3265, with #3731 live as the eighth —
and every answer raised the number or de-duplicated a whole-repo scan. The suite itself
never stopped being one process. Measured 2026-09-15, 1,134 files / ~26k tests:

    CI, serial (run 34912585378, ubuntu-latest 4 vCPU)  1,649s  25,962 / 71 skip / 35 xfail
    local serial, 12 cores                              1,603s  25,986 / 56 / 35
    local -n auto --dist loadfile                         411s  25,984 / 58 / 35

Same 26,077 total either way — nothing lost from collection. The 2 reclassified are
credential-gated (`tests/conftest.py`'s #381 hermetic fakes): under `-n auto` each worker
starts clean, so they skip rather than reaching a developer's real `~/.aws`. CI has no
credentials at all, so the sets are identical there.

THE ONE CROSS-FILE HAZARD, AND WHY THE RULE IS A MARKER AND NOT A BAN
  `--dist loadfile` keeps a file's tests on one worker, so every intra-file ordering
  assumption survives for free. What can still race is the suite's only genuinely shared
  mutable state: **the checkout**. Dozens of tests rglob `lambdas/` or the repo tree, so a
  test that plants a file there races every one of them.

  Two such writers existed, and they need OPPOSITE treatment — which is the whole lesson:

  1. `tests/test_rate_limit_identity_1221.py`'s must-fail probe planted a handler inside
     `lambdas/` to prove its own AST walk could see one. It did NOT need the real tree —
     only *a* tree. Fixed at the source (`_raw_identity_reads` takes a `tree_root`), so it
     is no longer a writer at all. Fixing a reader instead would have left the next probe
     free to reintroduce it.
  2. `tests/test_qa_smoke_fault_isolation_2307.py::test_the_widened_scan_actually_covers_each_root`
     plants `_null_coercion_mutation_proof_2336.py` in EVERY real scan root. Here the real
     tree IS the point — the test exists to prove each root is wired, and a temp dir would
     make it vacuous. It cannot be fixed at the source, so it is marked `serial`.

  The first draft of this file got that wrong. It banned in-tree writes outright with an
  empty exception set, which would have been a guard that is confidently incorrect about
  its own domain — and it enumerated ONE member of a two-member set, the exact
  "guard the instance, not the set" failure it was written to prevent. The second writer
  was found empirically, not by reading: it surfaced in roughly 1 parallel run in 3 as
  `first-party package(s) ['lambdas'] hold .py modules`, a red naming a file that no
  longer existed by the time anyone read the log.

THE RULE, therefore: **a test that plants a file inside the checkout must be marked
`serial`** — deselected from `-n auto`, run afterwards in one process where no concurrent
reader exists. Registered below with a reason each.

HONEST LIMIT OF THE DETECTOR. The static scan below reads two idioms: a `dir=`-argument
tempfile, and a write through a path rooted at a repo-root constant (including one bound
by a `for` loop over such a constant — how writer 2 is written). It is an AST pass, not a
proof: a sufficiently indirect idiom can evade it. **The registry, not the scan, is the
source of truth, and the `serial` marker is what actually protects the run.** The scan's
job is to make an UNregistered writer of a known shape impossible to add quietly.
"""

import ast
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# NOT `PR_CHECKS`: that spelling matches gate_census._REGISTRY_NAME's `.*_CHECKS` arm and the
# census minted a phantom `registry::` gate for what is a single path string, not a registry of
# gate entries (#3315). The sanctioned remedy for a registry-name phantom is to rename the
# constant, which is what this is — not a ledger line for a gate that does not exist.
PR_CHECKS_WORKFLOW = os.path.join(REPO, ".github", "workflows", "pr-checks.yml")

# ── the registry (charter primitive 1) ───────────────────────────────────────
#
# test id -> why it must write into the real checkout. An entry here is a claim that the
# write CANNOT be pointed at a private temp dir without making the test vacuous. Every
# entry must carry `@pytest.mark.serial`; `test_every_registered_writer_is_marked_serial`
# is what makes that true rather than intended.
IN_TREE_WRITERS = {
    "tests/test_doc_drift_date_stamp_2649.py": (
        "rewrites the REAL docs/ARCHITECTURE.md to prove the drift gate distinguishes a "
        "date-only re-stamp from substantive drift; a copy would prove only that the gate "
        "can read a copy."
    ),
    "tests/test_doc_restamp_rule_2986.py": (
        "rewrites the REAL docs/SLOs.md for the on-repo proof of #2986's no-manufactured-"
        "freshness rule — the rule is about the live surface, so the live surface is the "
        "fixture. The write is done by a FIXTURE (`live_doc`), which is why this registry "
        "is keyed by file and not by test."
    ),
    "tests/test_ingestion_day_key_derivation_3666.py": (
        "plants _planted_day_key_{writer,reader}_3666.py inside the REAL lambdas/ingestion/ "
        "to prove the scan covers that package rather than a synthetic tree."
    ),
    "tests/test_config_ownership_3785.py": (
        "plants the generated `config/hevy_template_index.json` back into the REAL config/ tree "
        "— the incident's own precondition — to prove the ownership audit reds on a restored "
        "committed twin. A temp copy would prove only that the audit can read a temp copy; the "
        "claim is about THIS checkout's config/ directory."
    ),
    "tests/test_qa_smoke_fault_isolation_2307.py": (
        "plants a synthetic offender in EVERY real NULL_COERCION_SCAN_ROOTS entry (lambdas/ "
        "included) to prove each root is wired (#2336's own mutation proof). This is the "
        "one that was caught live: it reached test_mypy_clean_modules in ~1 parallel run "
        "in 3 as `first-party package(s) ['lambdas'] hold .py modules`."
    ),
}

# A checkout-root constant is MODULE-LEVEL and SHOUTY: `_REPO`, `ROOT`, `HERE`,
# `NULL_COERCION_SCAN_ROOTS`. That casing rule is doing real work — dozens of tests build
# a FAKE repo with `repo = tmp_path / "repo"` and then write into it freely, which is
# correct and must never be flagged. The first draft matched `repo` case-insensitively
# and reported 20+ of those as violations; a guard that cries wolf on the safe majority
# is one people learn to silence.
_ROOT_CONST = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
_ROOT_ISH = re.compile(r"REPO|ROOT|LAMBDAS|HERE")
# Expressions that produce a directory OUTSIDE the checkout — a name bound to one of
# these is safe no matter what it is called.
_TMP_ISH = re.compile(r"\btmp_path\b|\btmpdir\b|TemporaryDirectory|mkdtemp|mkstemp|gettempdir")
# Attribute calls that create or write a filesystem entry.
_WRITE_ATTRS = {"write_text", "write_bytes", "touch", "mkdir", "symlink_to", "hardlink_to"}
# tempfile factories that place their result at a caller-chosen location.
_TEMPFILE_FACTORIES = {"TemporaryDirectory", "NamedTemporaryFile", "mkdtemp", "mkstemp"}


def _base_name(node):
    """The leftmost Name of a path expression: `root / "a" / "b"` -> 'root'."""
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
            continue
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        if isinstance(node, ast.Call):
            node = node.func
            continue
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        return None


class _Scan(ast.NodeVisitor):
    """(lineno, func, idiom) for writes whose path is rooted in the real checkout."""

    def __init__(self):
        self.root_names = set()
        self.tmp_names = set()
        self.hits = []
        self._func = None
        self._depth = 0

    def visit_Module(self, node):
        # pass 1: module-level root constants only
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and _ROOT_CONST.match(t.id) and _ROOT_ISH.search(t.id.upper()):
                        self.root_names.add(t.id)
        self.generic_visit(node)

    def visit_Assign(self, node):
        # anything bound from a tmp-ish expression is safe, whatever it is named
        src = ast.unparse(node.value)
        if _TMP_ISH.search(src):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.tmp_names.add(t.id)
                    self.root_names.discard(t.id)
        else:
            b = _base_name(node.value)
            if b and b in self.tmp_names:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.tmp_names.add(t.id)
            # PROPAGATE root-ness through an intermediate binding. The real culprit is
            # written as two statements —
            #     mutant = root / "_null_coercion_mutation_proof_2336.py"
            #     mutant.write_text(mutant_src)
            # — and a detector that only understands `(root / "x").write_text()` reads
            # the whole file as clean. That is exactly how the first version of this
            # scanner reported ZERO in-tree writers and passed vacuously.
            elif b and b in self.root_names:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.root_names.add(t.id)
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None and _TMP_ISH.search(ast.unparse(item.context_expr)):
                if isinstance(item.optional_vars, ast.Name):
                    self.tmp_names.add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_For(self, node):
        it = _base_name(node.iter)
        if it and it in self.root_names and isinstance(node.target, ast.Name):
            self.root_names.add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        prev, self._func = self._func, node.name
        # a pytest fixture argument named tmp_path/tmpdir is safe by definition
        for a in node.args.args:
            if _TMP_ISH.search(a.arg):
                self.tmp_names.add(a.arg)
        self.generic_visit(node)
        self._func = prev

    def visit_Call(self, node):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
        if name in _TEMPFILE_FACTORIES:
            for kw in node.keywords:
                if kw.arg == "dir":
                    b = _base_name(kw.value)
                    if b and b in self.root_names and b not in self.tmp_names:
                        self.hits.append((node.lineno, self._func, f"{name}(dir=...{b}...)"))
        if isinstance(fn, ast.Attribute) and fn.attr in _WRITE_ATTRS:
            b = _base_name(fn.value)
            if b and b in self.root_names and b not in self.tmp_names:
                self.hits.append((node.lineno, self._func, f"{b}....{fn.attr}()"))
        self.generic_visit(node)


def _scan_source(src: str):
    scan = _Scan()
    scan.visit(ast.parse(src))
    return scan.hits


def _in_tree_writers_on_disk():
    """[(file, lineno, func, idiom)] for every detected in-tree write under tests/."""
    out = []
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            try:
                hits = _scan_source(fh.read())
            except SyntaxError:  # pragma: no cover
                continue
        for lineno, func, idiom in hits:
            out.append((name, lineno, func, idiom))
    return out


# ── the property ─────────────────────────────────────────────────────────────
def test_every_in_tree_writer_is_registered():
    """An in-tree write the registry does not know about races every rglob sweep.

    Keyed by FILE, not by test: `--dist loadfile` groups a file onto one worker, so the
    file is the unit that actually gets scheduled — and a write done by a FIXTURE
    (test_doc_restamp_rule_2986's `live_doc` writes docs/SLOs.md) belongs to no single test.
    """
    registered = {k.split("/")[-1] for k in IN_TREE_WRITERS}
    found = {h[0] for h in _in_tree_writers_on_disk()}
    unregistered = sorted(found - registered - {os.path.basename(__file__)})
    assert not unregistered, (
        "these write inside the checkout and are not in IN_TREE_WRITERS, so they race every "
        f"rglob sweep under `pytest -n auto` (#3025): {unregistered}\n  "
        "Fix it at the source (point the write at a private temp dir) if the real tree is not "
        "the point. If it IS the point, register the file here with the reason and give it "
        "`pytestmark = pytest.mark.serial`."
    )


def test_the_scan_is_not_vacuous():
    """THE control this file needed and did not have. Its first two drafts each passed
    while detecting ZERO writers — once because the regex could not see a write through a
    loop-bound root, once because the real culprit binds the path to an intermediate first
    (`mutant = root / "x"` then `mutant.write_text(...)`) while the planted control used the
    one-line form. A set guard that finds nothing is indistinguishable from a clean repo."""
    found = {h[0] for h in _in_tree_writers_on_disk()}
    assert found, "the scan found NO in-tree writers at all — it is broken, not the repo clean"
    assert len(found) >= len(IN_TREE_WRITERS), f"scan sees {sorted(found)} but {len(IN_TREE_WRITERS)} are registered"


def test_the_registry_has_no_stale_entry():
    """A registered file that no longer writes in-tree would sit out of the parallel pass
    forever for a reason that stopped being true — the shrink direction of the ratchet."""
    writing = {h[0] for h in _in_tree_writers_on_disk()}
    stale = sorted(k for k in IN_TREE_WRITERS if k.split("/")[-1] not in writing)
    assert not stale, f"registered but no longer writes in-tree — drop the entry AND the marker: {stale}"


def test_every_registered_writer_is_marked_serial():
    """Registering is not protecting. The module-level marker is what deselects it from
    `-n auto`; without it the registry is a list of known hazards nobody acts on."""
    missing = []
    for rel in IN_TREE_WRITERS:
        path = os.path.join(REPO, rel)
        assert os.path.exists(path), f"registry names a file that does not exist: {rel}"
        with open(path, encoding="utf-8") as fh:
            if "pytestmark = pytest.mark.serial" not in fh.read():
                missing.append(rel)
    assert not missing, f"registered in-tree writer(s) missing `pytestmark = pytest.mark.serial`: {missing}"


def test_the_scan_can_actually_fail_on_both_idioms():
    """A guard that cannot fail is not a guard — and this one was WRONG about its own set
    on the first draft, so both idioms get a planted control taken from the real culprits."""
    # idiom 1 — the 2026-09-15 rate-limit probe, before it was fixed at the source
    kw = "dir"
    idiom1 = f'import tempfile\n_REPO = "x"\ndef f():\n    with tempfile.TemporaryDirectory({kw}=_REPO) as d:\n        pass\n'
    assert _scan_source(idiom1), "idiom 1 (tempfile dir=) is not detected"
    # idiom 2 — the #2336 mutation proof, in ITS OWN two-statement shape. This control
    # was originally written in the one-line form `(root / "x").write_text()`, which the
    # scanner detected while missing the real culprit entirely: the fixture has to be the
    # wire, or the guard proves only that it can catch the example you invented.
    idiom2 = 'SCAN_ROOTS = [1]\ndef f():\n    for root in SCAN_ROOTS:\n        mutant = root / "probe.py"\n        mutant.write_text("x")\n'
    assert _scan_source(idiom2), "idiom 2 (write via an intermediate bound from a loop-bound root) is not detected"
    idiom2_direct = 'SCAN_ROOTS = [1]\ndef f():\n    for root in SCAN_ROOTS:\n        (root / "probe.py").write_text("x")\n'
    assert _scan_source(idiom2_direct), "idiom 2 (direct form) is not detected"
    # ...and the shapes that must NOT be flagged
    for safe in (
        "import tempfile\ndef f():\n    with tempfile.TemporaryDirectory() as d:\n        pass\n",
        'def f(tmp_path):\n    (tmp_path / "a.py").write_text("x")\n',
        'def f(tmp_path):\n    (tmp_path / "lambdas" / "web").mkdir(parents=True)\n',
    ):
        assert not _scan_source(safe), f"false positive on a safe shape:\n{safe}"


# ── the parallel run itself ──────────────────────────────────────────────────
def _full_suite_steps():
    with open(PR_CHECKS_WORKFLOW, encoding="utf-8") as fh:
        src = fh.read()
    block = src[src.index("  full-suite:") :]
    return re.findall(r"run:\s*(python3 -m pytest[^\n]*)", block)


def test_the_full_suite_runs_a_parallel_pass_and_a_serial_pass():
    """Two passes, and BOTH are asserted — a contract that reads only the first line is
    how a second step drifts unwatched."""
    steps = _full_suite_steps()
    assert len(steps) == 2, f"expected exactly 2 pytest steps (parallel + serial), found {len(steps)}: {steps}"
    par, ser = steps
    assert "-n auto" in par and "--dist loadfile" in par, f"the parallel pass lost its parallelism: {par}"
    assert '-m "not serial"' in par or "-m 'not serial'" in par, f"the parallel pass must deselect the serial set: {par}"
    assert "-m serial" in ser or '-m "serial"' in ser, f"the second pass must select the serial set: {ser}"
    assert "-n " not in ser, f"the serial pass must be single-process: {ser}"
    for step in steps:
        assert "|" not in step, f"piped — its exit status is no longer the gate's (#2746): {step}"
        assert "--ignore=tests/test_integration_aws.py" in step, f"selection divergence: {step}"


def test_xdist_is_pinned_and_installed_by_the_lane_that_uses_it():
    with open(os.path.join(REPO, "requirements-dev.txt"), encoding="utf-8") as fh:
        assert re.search(r"^pytest-xdist==\d+\.\d+\.\d+$", fh.read(), re.M), "pytest-xdist is not pinned in requirements-dev.txt"
    with open(PR_CHECKS_WORKFLOW, encoding="utf-8") as fh:
        block = fh.read()
    block = block[block.index("  full-suite:") :]
    m = re.search(r"ci_pins\.py ([^\)\n]+)", block)
    assert m and "pytest-xdist" in m.group(1).split(), "the full-suite lane does not install pytest-xdist"


def test_the_serial_marker_is_registered_in_pytest_ini():
    """An unregistered mark is a silent typo: `-m serial` would select nothing and the
    parallel pass would quietly run the writer it was supposed to hold back."""
    with open(os.path.join(REPO, "pytest.ini"), encoding="utf-8") as fh:
        assert re.search(r"^\s*serial:", fh.read(), re.M), "the `serial` marker is not declared in pytest.ini"
