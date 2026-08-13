"""tests/test_ci_pin_consistency.py — CQ-01: dev tooling pins must match the CI gate.

The enforced format/lint/test gates run across ci-cd.yml/ci-lint.yml/ci-test.yml with
hardcoded versions. requirements-dev.txt must pin the SAME versions, or local
`make format` / `pytest` can pass while the build fails (or vice-versa) — the exact
drift AUDIT CQ-01 found (black 26.5.1 local vs 25.9.0 CI). This test is the
single-source guard.

Extended #1963: the original guard only covered black/ruff/playwright — mypy,
hypothesis, pytest, pytest-cov, boto3, and botocore had all drifted (mypy 2.1.0 CI
vs 2.3.0 dev; hypothesis 6.161.2 vs 6.163.0; pytest/pytest-cov/boto3/botocore
entirely unpinned in ci-test.yml/ci-cd.yml) with nothing to catch it. Both the
literal drift and the guard's blind spot are fixed here.

Extended #2058: pr-checks.yml (advisory pre-merge lane) and fresh-eyes.yml
(scheduled discovery workflow) pin hypothesis/boto3 too but sat outside
_CI_FILES, so they could drift indefinitely with no signal — the exact
"outside the guard's scope, not beyond its capability" shape #1963 named.
Folding them in also forced a strictness fix: the old subset check (every dev
pin must appear SOMEWHERE in the combined CI text) would have stayed green
even with pr-checks.yml/fresh-eyes.yml's stale pins in the mix, because
ci-cd.yml/ci-test.yml already carry the correct version — a stale pin can hide
behind a correct one from another file. The check is now exact-set equality
per tool across the whole _CI_FILES surface.

Extended #2570: the next instance of the SAME shape — "outside the guard's scope,
not beyond its capability". _CI_FILES is a HAND-LIST of workflow files, so a pin
declared anywhere else was invisible: the Makefile's `preflight` target sat on
black 25.9.0 / ruff 0.14.0 / mypy 2.1.0, three versions stale, while advertising
itself as "match CI gates locally", and nothing went red. The declaration surface
is now DERIVED from the tracked tree (`git ls-files`, every `tool==version`), so a
new place that writes a pin is covered the moment it exists rather than the moment
someone remembers this file. The resolution half of #2570 — which black binary the
pre-commit hook actually EXECUTES, versus the version declared here — is a
different question and lives in tests/test_formatter_pin_resolution.py.

Resolved #2609 — the class, not the instance. Every extension above kept the same
shape: TWO copies of a version (requirements-dev.txt + a literal in a workflow) and a
guard demanding they agree. Only one copy had an automated bumper, so every Dependabot
dev-tooling PR was born red and stayed red until a human hand-edited the other side —
28 declarations across 8 workflow files, measured from source, not the 8 the failure
log happened to name. Deferring bumps to avoid that hand-edit rots the pins, which is
the thing Dependabot exists to prevent. The fix deletes the second copy: workflows now
say WHICH packages they need and read the versions from requirements-dev.txt via
scripts/ci_pins.py. Two copies cannot disagree when there is one copy.

The guard's teeth move accordingly, and both directions are mutation-proved below:
  * a workflow that re-introduces a literal `tool==version` fails
    (test_no_workflow_carries_a_second_copy_of_a_pin) — a second copy is the defect
    now, even when it happens to agree today;
  * a workflow that asks the resolver for a package requirements-dev.txt does not pin
    fails (test_every_resolver_argument_is_pinned) — the silent-miss mode, where a
    rename leaves a gate running an unpinned tool;
  * the tree-wide agreement guard (#2570) is unchanged and still covers every OTHER
    place a version could be written down.
Action-SHA bumps (`uses: owner/action@<sha>`) are a genuinely separate problem — a
different Dependabot ecosystem, a different pin syntax, and no second copy — and are
deliberately out of scope here.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REQ = os.path.join(_REPO, "requirements-dev.txt")
# The resolver every CI install goes through (#2609). Repo-relative: it is invoked
# from the workflow's checkout root.
_RESOLVER_SCRIPT = "scripts/ci_pins.py"


def _tracked_files():
    out = subprocess.run(["git", "-C", _REPO, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def _workflow_files():
    """Every tracked workflow, DERIVED (#2609 acceptance).

    _CI_FILES used to be a hand-list of five, which is how #2058's blind spot happened
    (pr-checks.yml/fresh-eyes.yml installed the same tools from outside the guard) and
    how the #2609 blast radius got undercounted (site-deploy/visual-qa/v4-gate/
    webkit-mobile-qa each pin playwright). A workflow is in scope the moment it exists.
    """
    return [p for p in _tracked_files() if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))]


_CI_FILES = [os.path.join(_REPO, p) for p in _workflow_files()]
_CI = _CI_FILES[0] if _CI_FILES else os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")


def _ci_gate_text():
    parts = []
    for p in _CI_FILES:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


# Tools whose versions are BOTH pinned in the CI gate (ci-cd/ci-lint/ci-test.yml) and
# installed for local dev. Extended #1963 to add mypy/hypothesis/pytest/pytest-cov/
# boto3/botocore. Kept as a literal tuple for readability, but
# test_gated_tools_matches_requirements_dev_pins below DERIVES the expected
# membership from requirements-dev.txt itself, so a future Dependabot-managed pin
# can't silently land outside this guard's coverage again (guard the SET, not the
# instance).
_GATED_TOOLS = ("black", "ruff", "mypy", "playwright", "hypothesis", "pytest", "pytest-cov", "boto3", "botocore", "pyyaml")

# requirements-dev.txt pins deliberately OUTSIDE this guard's coverage, each with why:
_UNGATED_DEV_PINS = {
    # ci-lint.yml installs flake8 unpinned ("pip install flake8") — a pre-existing
    # gap #1963 did not scope in; tracked separately from this guard.
    "flake8",
    # The CDK toolchain is pinned bidirectionally by its OWN convention
    # (cdk/requirements.txt <-> ci-cd.yml's `npm install -g aws-cdk@X`, #814,
    # R22-MOD-01) — a CLI-install shape, not this guard's `pip install tool==`
    # pattern, so it doesn't fit _pin_mismatches below.
    "aws-cdk-lib",
    "constructs",
}


def _versions(path, tool):
    """Every '<tool>==<version>' pin found in a file, as a set."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", text))


def _pin_mismatches(ci_text, tools):
    """Every tool in `tools` whose requirements-dev.txt pin isn't among the
    versions `ci_text` installs. Factored out of test_dev_pins_match_ci_gate so a
    synthetic ci_text can prove the guard actually fires (see the prove-red test
    below) without editing real workflow files."""
    mismatches = []
    for tool in tools:
        ci = set(re.findall(rf"\b{tool}==([0-9][0-9A-Za-z.\-]*)", ci_text))
        dev = _versions(_REQ, tool)
        assert ci, f"{tool} not pinned in the CI gate ({', '.join(os.path.basename(p) for p in _CI_FILES)})"
        assert dev, f"{tool} not pinned in requirements-dev.txt"
        # Exact equality, not just "every dev pin appears somewhere in ci" (#2058):
        # a subset check lets a stale pin in one file hide behind a correct pin in
        # another — the exact gap that would have let pr-checks.yml's stale
        # hypothesis==6.161.2 and fresh-eyes.yml's stale boto3==1.43.41 stay
        # invisible even after folding those files into _CI_FILES, since
        # ci-cd.yml/ci-test.yml already carry the right version.
        if dev != ci:
            mismatches.append(f"{tool}: requirements-dev={sorted(dev)} vs ci-gate={sorted(ci)}")
    return mismatches


def _requirements_dev_pinned_tools():
    """Every top-level `name==version` pin in requirements-dev.txt, as tool names."""
    with open(_REQ, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"^([A-Za-z][A-Za-z0-9_.\-]*)==[0-9]", text, re.MULTILINE))


def test_gated_tools_matches_requirements_dev_pins():
    """Guard the SET, not the instance (#1963): every requirements-dev.txt pin not
    on the documented _UNGATED_DEV_PINS exception list must be covered by
    _GATED_TOOLS — a tool Dependabot bumps in requirements-dev.txt can't silently
    sit outside this guard's coverage the way mypy/hypothesis/pytest did."""
    expected = _requirements_dev_pinned_tools() - _UNGATED_DEV_PINS
    actual = set(_GATED_TOOLS)
    assert expected == actual, (
        "requirements-dev.txt pins and _GATED_TOOLS have diverged — add the new tool to "
        "_GATED_TOOLS, or to _UNGATED_DEV_PINS with a rationale if it's deliberately out of "
        f"scope: missing from _GATED_TOOLS={sorted(expected - actual)}, "
        f"stale in _GATED_TOOLS={sorted(actual - expected)}"
    )


def test_guard_fires_on_synthetic_divergence_for_a_newly_covered_tool():
    """Prove-red (#1963 acceptance): the extended guard must actually FIRE on a
    version mismatch for one of the newly-covered tools, not just the original
    black/ruff/playwright set. Reproduces the exact #1963 drift class — CI pinned
    to a stale mypy version while requirements-dev.txt moved on — via synthetic CI
    text, so this stays true even after the real files are reconciled."""
    assert "mypy" in _GATED_TOOLS, "mypy must be a newly-covered tool for this regression proof to be meaningful"
    real_mypy_pin = _versions(_REQ, "mypy")
    assert real_mypy_pin, "requirements-dev.txt must pin mypy for this test to be meaningful"
    synthetic_ci_text = "pip install mypy==0.0.1-synthetic-stale-pin"
    mismatches = _pin_mismatches(synthetic_ci_text, ("mypy",))
    assert mismatches, "the pin-parity guard failed to fire on a synthetic mypy divergence — regression"
    assert mismatches[0].startswith("mypy:")


# --- Doc-command truth (#2006) -------------------------------------------------
# CONVENTIONS §4 tells the operator to DISCOVER the pins by running a grep rather
# than trusting a quoted number. #1655 moved the lint pins from ci-cd.yml to
# ci-lint.yml without updating that command, so the doc's grep silently showed only
# the requirements-dev.txt half — the exact half the doc says not to trust. These
# tests extract the grep commands verbatim from the doc and run them, so the doc
# and the file layout can't drift apart again without a red.

_DOC = os.path.join(_REPO, "docs", "CONVENTIONS.md")


def _doc_pin_commands():
    """Every backticked `grep -E '…=…' <files>` pin-discovery command in CONVENTIONS.md.

    Derived from the doc, not enumerated here (guard the set, not the instance):
    returns [(pattern, full_command), ...] with wrapped lines re-joined.
    """
    with open(_DOC, encoding="utf-8") as f:
        text = f.read()
    cmds = []
    for m in re.finditer(r"`(grep -E '([^']*==[^']*)'[^`]*)`", text):
        cmd = " ".join(m.group(1).split())  # doc wraps long commands across lines
        cmds.append((m.group(2), cmd))
    return cmds


def test_doc_pin_discovery_commands_are_extractable():
    cmds = _doc_pin_commands()
    patterns = [p for p, _ in cmds]
    assert any("mypy==" in p for p in patterns), "CONVENTIONS.md §4 lost its black/ruff/mypy pin-discovery grep"
    assert any("aws-cdk" in p for p in patterns), "CONVENTIONS.md §4 lost its CDK pin-discovery grep"


def test_doc_pin_discovery_commands_surface_every_promised_pin():
    """Each documented grep must run clean AND surface every alternation it promises."""
    for pattern, cmd in _doc_pin_commands():
        proc = subprocess.run(cmd, shell=True, cwd=_REPO, capture_output=True, text=True)  # noqa: S602 repo-authored doc command
        assert proc.returncode == 0, f"documented pin-discovery command failed (rc={proc.returncode}): {cmd}\n{proc.stderr}"
        for token in pattern.split("|"):
            assert token in proc.stdout, f"documented command no longer surfaces '{token}': {cmd}"


def test_doc_lint_pin_grep_surfaces_the_ci_side():
    """The #2006 blindness class, restated for the one-copy world (#2609).

    #2006's defect was that the documented command showed only the requirements-dev.txt
    half while the ENFORCED version lived in a workflow the grep didn't cover — 'read
    the CI pin' was archaeology. Since #2609 the enforced version and the local one are
    the same string in the same file, so the requirement inverts: the documented
    command must surface it, AND the page must say how CI gets there, or the reader is
    back to archaeology by a different route.
    """
    lint_cmds = [(p, c) for p, c in _doc_pin_commands() if "mypy==" in p]
    assert lint_cmds, "no black/ruff/mypy pin-discovery command found in CONVENTIONS.md"
    for pattern, cmd in lint_cmds:
        proc = subprocess.run(cmd, shell=True, cwd=_REPO, capture_output=True, text=True)  # noqa: S602 repo-authored doc command
        assert proc.returncode == 0, f"documented pin-discovery command failed: {cmd}\n{proc.stderr}"
        assert "requirements-dev.txt" in cmd, f"the documented lint-pin command must read the file of record: {cmd}"
        for tool in ("black==", "ruff==", "mypy=="):
            assert tool in proc.stdout, (
                f"'{tool[:-2]}' pin not surfaced from requirements-dev.txt by the documented command — "
                f"the doc's grep is blinded again (#2006 regression): {cmd}"
            )
    with open(_DOC, encoding="utf-8") as f:
        doc = f.read()
    assert _RESOLVER_SCRIPT in doc, (
        f"CONVENTIONS.md §4 no longer names {_RESOLVER_SCRIPT}. With no literal pin in the "
        "workflows, a reader who is not told how CI resolves its versions cannot answer "
        "'what version does the gate run?' from the page — the #2006 failure, relocated."
    )


def test_dev_pins_match_ci_gate():
    """Any gated tool a workflow STILL hardcodes must equal requirements-dev.txt.

    Post-#2609 the workflows carry no literals, so this runs over an empty set and its
    teeth live in the two tests below — but it stays, and stays exact, because the
    moment someone re-introduces a literal (a new workflow copied from an old one, a
    revert) it is the check that catches a wrong one. `_pin_mismatches` is proved to
    fire by test_guard_fires_on_synthetic_divergence_for_a_newly_covered_tool above.
    """
    ci_text = _ci_gate_text()
    still_literal = tuple(t for t in _GATED_TOOLS if re.search(rf"\b{re.escape(t)}==[0-9]", ci_text))
    mismatches = _pin_mismatches(ci_text, still_literal)
    assert not mismatches, "dev tooling pins drifted from the enforced CI gate (CQ-01):\n" + "\n".join(mismatches)


# --- #2609: one copy, read at install time -------------------------------------
# The pin-parity class dies by deleting the second copy rather than automating the
# hand-edit that kept it in sync. These are the teeth that replace the literal
# comparison, and both are factored so a synthetic input can prove them red.


def _resolver_arguments(text):
    """Every package name passed to scripts/ci_pins.py in `text`, in order.

    Parses the shell call form the workflows use:
        PINS=$(python3 scripts/ci_pins.py black ruff)   # trailing comment
    Stops at the closing paren so a trailing comment is never mistaken for a package,
    and drops flags so `--requirements <path>` cannot be read as two packages.
    """
    names = []
    for m in re.finditer(re.escape(_RESOLVER_SCRIPT) + r"([^)\n]*)", text):
        skip_next = False
        for tok in m.group(1).split():
            if skip_next:
                skip_next = False
                continue
            if tok.startswith("-"):
                skip_next = "=" not in tok  # `--requirements PATH` consumes its value
                continue
            names.append(tok)
    return names


def _second_copy_declarations(texts_by_path, tools=_GATED_TOOLS):
    """{path: [literal, ...]} for any file that hardcodes a gated tool's version."""
    rx = re.compile(r"\b(%s)==([0-9][0-9A-Za-z.+\-]*)" % "|".join(re.escape(t) for t in tools))
    return {path: [f"{t}=={v}" for t, v in rx.findall(text)] for path, text in texts_by_path.items() if rx.search(text)}


def _unpinned_resolver_arguments(texts_by_path, known_pins):
    """[(path, name), ...] for every resolver argument the pin file does not pin."""
    known = {_normalize_pin_name(n) for n in known_pins}
    return [
        (path, name)
        for path, text in sorted(texts_by_path.items())
        for name in _resolver_arguments(text)
        if _normalize_pin_name(name) not in known
    ]


def _normalize_pin_name(name):
    """PEP 503 normalization — must agree with scripts/ci_pins.py::normalize."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _workflow_texts():
    out = {}
    for rel in _workflow_files():
        with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
            out[rel] = f.read()
    return out


def test_no_workflow_carries_a_second_copy_of_a_pin():
    """Direction 1 of the #2609 teeth. A literal `tool==version` in a workflow is the
    defect itself — not only when it disagrees today, but because it WILL disagree the
    next time Dependabot bumps requirements-dev.txt, and that bump then arrives red."""
    offenders = _second_copy_declarations(_workflow_texts())
    assert not offenders, (
        "workflow(s) hardcode a tool version again (#2609). The version of record is "
        f"requirements-dev.txt; install via `PINS=$(python3 {_RESOLVER_SCRIPT} <names>)` so a "
        "Dependabot bump lands green with no hand-edit:\n  " + "\n  ".join(f"{p}: {sorted(set(v))}" for p, v in sorted(offenders.items()))
    )


def test_second_copy_guard_fires_on_a_synthetic_literal():
    """Prove-red for direction 1, same pattern as the other synthetic proofs here."""
    offenders = _second_copy_declarations({".github/workflows/fake.yml": "run: pip install black==0.0.1-synthetic\n"})
    assert offenders, "the second-copy guard failed to fire on a synthetic hardcoded pin — regression"
    assert "black==0.0.1-synthetic" in next(iter(offenders.values()))
    # And it must NOT fire on the resolver form, or the fix is unshippable.
    assert not _second_copy_declarations({"x.yml": f"PINS=$(python3 {_RESOLVER_SCRIPT} black ruff)\n"})


def test_every_resolver_argument_is_pinned():
    """Direction 2 of the #2609 teeth — the silent-miss mode.

    A resolver call naming a package requirements-dev.txt does not pin would install
    nothing for it. scripts/ci_pins.py exits non-zero at runtime, but that is a red CI
    run on main; catching it here makes it a red on the PR that renamed the pin."""
    bad = _unpinned_resolver_arguments(_workflow_texts(), _requirements_dev_pinned_tools())
    assert not bad, (
        "workflow(s) ask scripts/ci_pins.py for a package requirements-dev.txt does not pin " f"— the install would fail at runtime: {bad}"
    )


def test_resolver_argument_guard_fires_on_a_synthetic_unknown_package():
    """Prove-red for direction 2."""
    text = {"x.yml": f"PINS=$(python3 {_RESOLVER_SCRIPT} pytest not-a-real-package)"}
    bad = _unpinned_resolver_arguments(text, {"pytest"})
    assert bad == [("x.yml", "not-a-real-package")], bad
    # Normalization must hold in both directions, or `pytest_cov` vs `pytest-cov`
    # would read as a missing pin and this guard would cry wolf.
    assert not _unpinned_resolver_arguments({"x.yml": f"{_RESOLVER_SCRIPT} pytest_cov"}, {"pytest-cov"})
    # Flags are arguments, not packages.
    assert not _unpinned_resolver_arguments({"x.yml": f"{_RESOLVER_SCRIPT} --requirements other.txt pytest"}, {"pytest"})


def test_the_resolver_surface_is_not_vacuous():
    """A derivation that finds nothing passes forever (#1189 lesson, applied again).

    Every gated tool must actually be resolved by at least one workflow — otherwise a
    workflow could quietly drop its install step and every test above stays green.
    """
    resolved = {_normalize_pin_name(n) for text in _workflow_texts().values() for n in _resolver_arguments(text)}
    missing = sorted(t for t in _GATED_TOOLS if _normalize_pin_name(t) not in resolved)
    assert not missing, f"no workflow resolves {missing} through {_RESOLVER_SCRIPT} — its CI install vanished or went back to a literal"
    assert os.path.exists(os.path.join(_REPO, _RESOLVER_SCRIPT)), f"{_RESOLVER_SCRIPT} is missing — every CI install step would fail"


def test_the_resolver_reads_the_same_pin_file_the_guard_does():
    """The resolver must resolve against requirements-dev.txt itself, not a copy of it,
    and must fail loudly on an unknown name rather than silently installing nothing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_pins", os.path.join(_REPO, _RESOLVER_SCRIPT))
    ci_pins = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci_pins)
    assert os.path.abspath(ci_pins.DEFAULT_REQUIREMENTS) == os.path.abspath(_REQ)
    for tool in _GATED_TOOLS:
        (resolved,) = ci_pins.resolve([tool])
        expected = _versions(_REQ, tool)
        assert resolved.split("==")[1] in expected, f"{tool}: resolver returned {resolved}, requirements-dev.txt pins {expected}"
    try:
        ci_pins.resolve(["definitely-not-pinned"])
    except LookupError as exc:
        assert "definitely-not-pinned" in str(exc)
    else:
        raise AssertionError("the resolver silently accepted an unpinned package — a CI gate would run unpinned")


# --- The declaration surface, DERIVED rather than hand-listed (#2570) ----------
# _CI_FILES above is a hand-list, so a pin written down anywhere else — the
# Makefile, a script, a doc — could disagree indefinitely with nothing red. That is
# exactly what happened to `make preflight`. These tests derive the surface instead.

# Paths whose `tool==version` strings are HISTORY, not declarations: frozen review
# artifacts, archived docs and session handovers all quote the pins that were live
# when they were written, and are deliberately never updated (editing a dated record
# would falsify it). Plus the two pin-guard test files, which carry synthetic pins.
_HISTORICAL_PREFIXES = ("docs/reviews/", "docs/archive/", "handovers/")
_HISTORICAL_FILES = ("tests/test_ci_pin_consistency.py", "tests/test_formatter_pin_resolution.py")

# Declarations that are KNOWN stale and deliberately out of scope for the change
# that added this derivation (#2570 is a formatter-toolchain fix). Keyed by
# (path, tool) so a version bump doesn't silently re-arm them; each needs a reason.
# An entry here is a debt, not an exemption — delete it by fixing the file.
#
# Currently EMPTY. #2570 opened it with two docs/LICENSES.md rows; #2588 paid that
# debt the way the ledger intends — by fixing the file, not by aging the entry.
# The resolution was to stop declaring versions in the licence inventory at all
# (docs/LICENSES.md §6.1): auditing the table found 6 of its 13 version rows stale
# and this guard could only ever see 7 of the 13, so exactness there was a fact
# nothing could keep true. The mechanism stays for the next genuinely-deferred row.
_KNOWN_STALE_DECLARATIONS: dict = {}

# The code that RESOLVES a pinned tool at runtime must derive the version, never
# carry a second copy of it (#2570). Derived from the tracked tree the same way as
# everything else: any tracked shell file that sources or is the resolver.
_RESOLVER = os.path.join("deploy", "lib", "pinned_formatters.sh")


def _declaration_sites(tools=_GATED_TOOLS):
    """Derive {tool: {version: [paths]}} from every tracked file that declares a pin."""
    rx = re.compile(r"\b(%s)==([0-9][0-9A-Za-z.+\-]*)" % "|".join(re.escape(t) for t in tools))
    found: dict = {t: {} for t in tools}
    for rel in _tracked_files():
        if rel in _HISTORICAL_FILES or rel.startswith(_HISTORICAL_PREFIXES):
            continue
        try:
            with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        for tool, ver in rx.findall(text):
            if (rel, tool) in _KNOWN_STALE_DECLARATIONS:
                continue
            found[tool].setdefault(ver, []).append(rel)
    return found


def _declaration_disagreements(sites):
    """Factored out so a synthetic `sites` map can prove the guard fires (same
    pattern as test_guard_fires_on_synthetic_divergence_for_a_newly_covered_tool)."""
    problems = []
    for tool, by_version in sorted(sites.items()):
        if len(by_version) > 1:
            detail = "; ".join(f"{ver} in {sorted(set(paths))}" for ver, paths in sorted(by_version.items()))
            problems.append(f"{tool} is declared at {len(by_version)} different versions — {detail}")
    return problems


def test_declaration_derivation_is_not_vacuous():
    """A derivation that finds nothing passes forever. Assert it actually sees the
    two sources the pin contract is built on, without hand-listing the surface."""
    sites = _declaration_sites()
    for tool in ("black", "ruff"):
        paths = sorted({p for ps in sites[tool].values() for p in ps})
        assert paths, f"derived zero declaration sites for {tool} — the derivation is broken, not the tree"
        assert "requirements-dev.txt" in paths, f"{tool} is no longer pinned in requirements-dev.txt (the resolver reads it)"
    # Since #2609 the workflows deliberately declare NO version — they resolve it. The
    # "CI actually installs this tool" half of the old assertion is now
    # test_the_resolver_surface_is_not_vacuous, which checks the resolver call instead
    # of a literal. Asserting a workflow literal here would forbid the fix.


def test_every_declared_pin_agrees_tree_wide():
    """One version per tool, everywhere it is written down — workflows, Makefile,
    scripts, docs. This is the #2570 box: the local gate's version and CI's pin
    cannot diverge again without a red."""
    problems = _declaration_disagreements(_declaration_sites())
    assert not problems, (
        "tool pins have diverged across the tracked tree (CQ-01 / #2570). Every declaration must "
        "equal requirements-dev.txt, which is what the pre-commit hook and deploy/agent_commit.sh "
        "resolve against:\n  " + "\n  ".join(problems)
    )


def test_tree_wide_guard_fires_on_a_synthetic_divergence():
    """Prove-red for the derived surface, mirroring the #1963 pattern above: a
    synthetic sites map with one tool declared twice must be reported."""
    synthetic = {"black": {"26.3.1": ["requirements-dev.txt"], "25.9.0": ["Makefile"]}}
    problems = _declaration_disagreements(synthetic)
    assert problems, "the tree-wide declaration guard failed to fire on a synthetic divergence — regression"
    assert "Makefile" in problems[0] and "25.9.0" in problems[0], problems


def test_known_stale_declarations_are_still_real():
    """The debt ledger must not rot: an entry whose file no longer declares that
    tool is a stale exemption quietly widening the guard's blind spot."""
    rx_cache = {}
    for (rel, tool), reason in _KNOWN_STALE_DECLARATIONS.items():
        assert reason, f"{rel}/{tool} needs a reason"
        path = os.path.join(_REPO, rel)
        assert os.path.exists(path), f"_KNOWN_STALE_DECLARATIONS names a missing file: {rel}"
        with open(path, encoding="utf-8") as f:
            text = f.read()
        rx = rx_cache.setdefault(tool, re.compile(rf"\b{re.escape(tool)}==[0-9]"))
        assert rx.search(text), f"_KNOWN_STALE_DECLARATIONS entry ({rel}, {tool}) no longer applies — delete it"


# --- docs/LICENSES.md declares no versions at all (#2588) ----------------------
# The licence inventory was the first thing the derived surface above caught, and
# fixing the two rows it saw would have left four equally-stale rows it structurally
# cannot see (flake8, pip-audit, aws-cdk-lib, constructs, garth, garminconnect are
# outside _GATED_TOOLS). Measured 2026-08-12: 6 of 13 version rows stale, 18 days
# after the file was written. The decision (docs/LICENSES.md §6.1) is that the table
# annotates LICENCES over packages and never carries a second copy of a pin. This
# guard makes that structural rather than a convention someone has to remember —
# and it removes the file from every future dependabot bump's blast radius.
_LICENSES_DOC = os.path.join(_REPO, "docs", "LICENSES.md")
_ANY_PIN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_.\-]*)==([0-9][0-9A-Za-z.+\-]*)")


def _licenses_doc_pins(text):
    return [f"{name}=={ver}" for name, ver in _ANY_PIN_RE.findall(text)]


def test_licenses_doc_declares_no_patch_exact_pins():
    with open(_LICENSES_DOC, encoding="utf-8") as f:
        text = f.read()
    # Non-vacuous: the table must still NAME the packages it annotates, or this
    # test is guarding an empty document (#1189 lesson).
    for pkg in ("hypothesis", "playwright", "aws-cdk-lib", "garth", "black"):
        assert f"`{pkg}`" in text, f"docs/LICENSES.md no longer names {pkg} — the inventory lost a row, not just its version"
    pins = _licenses_doc_pins(text)
    assert not pins, (
        "docs/LICENSES.md declares patch-exact pins again: "
        f"{sorted(set(pins))}. Per its own §6.1 this table annotates licences over "
        "packages; the version of record is the authoritative pin file. Re-adding a "
        "version re-opens the drift #2588 measured (6 of 13 rows stale in 18 days) and "
        "puts this doc back in the path of every dependabot bump."
    )


def test_licenses_doc_pin_guard_fires_on_a_synthetic_pin():
    """Prove-red, same pattern as the two synthetic-divergence tests above."""
    assert _licenses_doc_pins("| `hypothesis==6.165.0` | Property-based tests |") == ["hypothesis==6.165.0"]
    # Prose that merely mentions a version is not a declaration and must stay allowed —
    # §6.1's own reasoning quotes the stale numbers it replaced.
    assert _licenses_doc_pins("`hypothesis` (6.161.2 vs 6.165.0) — stale") == []


def test_pin_readers_hardcode_no_version():
    """The resolver and both of its callers must READ the pin, never carry a copy —
    a copy is a future divergence with a guaranteed silent window (#2570)."""
    rx = re.compile(r"\b(%s)==([0-9][0-9A-Za-z.+\-]*)" % "|".join(re.escape(t) for t in _GATED_TOOLS))
    for rel in (_RESOLVER, os.path.join("scripts", "install_hooks.sh"), os.path.join("deploy", "agent_commit.sh")):
        path = os.path.join(_REPO, rel)
        assert os.path.exists(path), f"{rel} is missing — the pinned-formatter resolver contract is broken (#2570)"
        with open(path, encoding="utf-8") as f:
            hits = rx.findall(f.read())
        assert not hits, f"{rel} hardcodes a tool pin {hits} — read it from requirements-dev.txt instead (#2570)"
