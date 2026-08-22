"""tests/test_docs_ci_owns_doc_gates.py — #1908: a docs-only fix must clear the gate it fixes.

THE DEFECT (three occurrences in three days — #1900, #1906, #1914):

The doc gates (`sync_doc_metadata --check`, `check_doc_links`, `check_doc_tombstones`,
`check_doc_facts`, `check_doc_index --strict`, `generate_adr_index --check`) ran in BOTH
docs-ci.yml and ci-cd.yml's Lint job (via ci-lint.yml). The ci-lint copy existed for a
real reason — a CODE change can invalidate a doc — but it created a one-way trap:

  * the gate fails inside CI/CD (triggered by a code push)
  * the fix is, by definition, a DOCS edit
  * `docs/**` is not in ci-cd.yml's `paths:` filter, so that fix cannot re-run CI/CD
  * `scripts/check_main_green.py` reads the **CI/CD workflow only**, so main keeps
    reporting the OLD failure
  * the only way to clear it is a manual `workflow_dispatch`, which also runs
    Plan → Deploy — charging a *documentation* fix a production approval (or leaving a
    stranded one, #1901)

FIX (option 1 on the issue): docs-ci.yml becomes the gates' single home AND gains the
code-side trigger paths, so code-push coverage is preserved rather than dropped.

A SECOND, SILENT DEFECT found while making the change: docs-ci.yml checked out at the
default depth 1, and `check_doc_index.py` SKIPS the #973 engine-doc drift gate on a
shallow clone (per-file git dates are meaningless there). So docs-ci had been running
`--strict` with its drift half disabled the whole time, reporting green regardless. Now
that this is the gate's only home, `fetch-depth: 0` is load-bearing — hence the test
below, which would otherwise be the easiest thing in this file to regress silently.
"""

import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOCS_CI = os.path.join(_REPO, ".github", "workflows", "docs-ci.yml")
_CI_LINT = os.path.join(_REPO, ".github", "workflows", "ci-lint.yml")
_CI_CD = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")

# The gates whose remediation is a docs edit. Any of these running inside the
# deploy pipeline reintroduces the trap.
_DOC_GATES = [
    "deploy/sync_doc_metadata.py --check",
    "scripts/check_doc_links.py",
    "scripts/check_doc_tombstones.py",
    "scripts/check_doc_facts.py",
    "scripts/check_doc_index.py --strict",
    "scripts/generate_adr_index.py --check",
    # #2975 — same shape as the ADR index: `--check` gates here, `--apply` reconciles in
    # CI/CD's run_generators(). It lives here because the thing that stales it is a
    # docs/** edit (every wrap adds incident rows), and it used to gate only in CI/CD's
    # Unit Tests, where the red always landed on a later, innocent commit.
    "scripts/incident_log_patterns.py --check",
]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


# ── The gates live in Docs CI, and only there ────────────────────────────────


@pytest.mark.parametrize("gate", _DOC_GATES)
def test_docs_ci_runs_every_doc_gate(gate):
    code = _strip_comments(_read(_DOCS_CI))
    assert gate in code, f"#1908: docs-ci.yml is the doc gates' single home — {gate!r} must run there"


@pytest.mark.parametrize("gate", _DOC_GATES)
def test_deploy_pipeline_does_not_run_doc_gates(gate):
    """THE regression guard. A doc gate inside the deploy pipeline cannot be cleared by
    the docs edit that fixes it — and clearing it costs a production approval."""
    for path in (_CI_LINT, _CI_CD):
        code = _strip_comments(_read(path))
        assert gate not in code, (
            f"#1908: {gate!r} must not run in {os.path.basename(path)} — its fix is a docs edit, "
            f"and docs/** cannot re-trigger the deploy pipeline. It belongs in docs-ci.yml."
        )


# ── Code-push coverage must be preserved, not dropped ────────────────────────


def test_docs_ci_triggers_on_the_source_half_of_the_coupling():
    """Moving the gates must not lose the coverage the ci-lint copy provided. The #973
    drift gate compares engine docs against their declared `Sources of truth`, which live
    under lambdas/, mcp/ and config/ — so a push to those must run these gates."""
    text = _read(_DOCS_CI)
    for needed in ("'lambdas/**'", "'mcp/**'", "'config/**'"):
        assert needed in text, f"#1908: docs-ci.yml must trigger on {needed} — a source change can drift an engine doc"


def test_engine_doc_sources_are_covered_by_a_trigger_path():
    """Derived, not enumerated: read the ACTUAL `Sources of truth` out of every engine
    doc and assert each one sits under a docs-ci trigger path. A new engine doc citing a
    directory nobody added to the trigger fails here instead of silently losing its gate."""
    engines_dir = os.path.join(_REPO, "docs", "engines")
    if not os.path.isdir(engines_dir):
        pytest.skip("no docs/engines/")
    text = _read(_DOCS_CI)
    globs = set(re.findall(r"-\s*'([^']+)'", text))
    prefixes = {g.split("/")[0] for g in globs if "/" in g}

    sources = set()
    for name in os.listdir(engines_dir):
        if not name.endswith(".md"):
            continue
        body = _read(os.path.join(engines_dir, name))
        m = re.search(r"\*\*Sources of truth:\*\*(.+?)(?:\n\n|\n#)", body, re.S)
        if not m:
            continue
        sources.update(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|json))`", m.group(1)))

    assert sources, "no engine-doc sources parsed — the regex may have drifted from the doc format"
    uncovered = sorted(s for s in sources if s.split("/")[0] not in prefixes)
    assert not uncovered, (
        "#1908: these engine-doc sources are not under any docs-ci.yml trigger path, so a change "
        f"to them would not run the drift gate: {uncovered}"
    )


def _trigger_paths():
    """(push, pull_request) path lists as docs-ci.yml declares them.

    Parsed as YAML, not regexed. The regex this replaced terminated a block at the first
    entry carrying a trailing `# comment` — `- 'scripts/doc_facts_ops.py'   # …`, the 7th
    of 15 — so the identity assertion it fed was comparing two six-element PREFIXES and
    could not see the tails diverge at all. Found 2026-08-22 while making the tails
    deliberately diverge (#2982); the guard would have stayed green either way.
    """
    import yaml  # in requirements-dev; imported here so collection never depends on it

    spec = yaml.safe_load(_read(_DOCS_CI))
    # PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1 truthiness).
    triggers = spec.get("on", spec.get(True))
    assert triggers, "docs-ci.yml has no trigger block"
    return triggers["push"]["paths"], triggers["pull_request"]["paths"]


# #2982's decision, recorded as an assertion. The two tests-side fact SOURCES a doc gate
# genuinely reads — derived below rather than trusted from this list, which exists only to
# make the intent legible next to the asymmetry it licenses.
_TESTS_PR_PATHS = {"tests/qa_manifest.py", "tests/leak_token_sweep.py", "tests/test_platform_stats_truth.py"}


def test_the_only_push_vs_pr_asymmetry_is_the_tests_glob():
    """GitHub Actions has no YAML anchors, so the two lists are duplicated by hand — which
    means they can drift by hand. They were identical until #2982, which licensed exactly
    ONE difference and nothing else.

    `tests/**` on `pull_request` made every test-adding PR a guaranteed CI round-trip: the
    branch reds on a `test_count` literal `agent_commit.sh` is policy-forbidden to stamp
    (#2372). The `push` trigger keeps `tests/**`, so main is still fully gated and the
    reconcile bot still owns the counter.
    """
    push, pr = _trigger_paths()
    assert set(push) - set(pr) == {"tests/**"}, (
        "the only sanctioned push-vs-PR difference is dropping the blanket tests/** glob from "
        f"the PR trigger (#2982). Push-only paths are {sorted(set(push) - set(pr))}"
    )
    assert set(pr) - set(push) == _TESTS_PR_PATHS, (
        "the PR trigger must add back exactly the real tests-side couplings and nothing else. "
        f"PR-only paths are {sorted(set(pr) - set(push))}"
    )


def test_every_tests_side_fact_source_is_on_the_pr_trigger():
    """THE guard that makes #2982 safe, derived rather than enumerated.

    Dropping the blanket `tests/**` glob is only sound while the specific files a doc gate
    READS are still listed. So read the gate scripts and find every `tests/<file>.py` they
    reference as a path — a NEW coupling added later must be added to the PR trigger here,
    or it fails, rather than silently losing its gate the way #1908's engine docs could.
    """
    gate_scripts = [
        os.path.join(_REPO, "deploy", "sync_doc_metadata.py"),
        os.path.join(_REPO, "scripts", "check_doc_facts.py"),
        os.path.join(_REPO, "scripts", "check_doc_index.py"),
        os.path.join(_REPO, "scripts", "check_doc_links.py"),
        os.path.join(_REPO, "scripts", "check_doc_tombstones.py"),
        os.path.join(_REPO, "scripts", "generate_adr_index.py"),
        os.path.join(_REPO, "scripts", "incident_log_patterns.py"),
    ]
    # `ROOT / "tests" / "name.py"` — a real path construction, not a mention in prose.
    pat = re.compile(r'"tests"\s*/\s*"([A-Za-z0-9_]+\.py)"')
    referenced = set()
    for path in gate_scripts:
        if os.path.exists(path):
            referenced.update(pat.findall(_read(path)))

    assert referenced, "no tests/ fact sources found in any gate script — the pattern has drifted from the code"
    _, pr = _trigger_paths()
    missing = sorted(f"tests/{n}" for n in referenced if f"tests/{n}" not in pr)
    assert not missing, (
        f"#2982: a doc gate reads {missing} but the PR trigger does not list it, so a PR editing it "
        "would not run the gate it can break. Add it to docs-ci.yml's pull_request paths."
    )


# ── The silent-skip trap ─────────────────────────────────────────────────────


def test_docs_ci_checks_out_full_history():
    """check_doc_index.py SKIPS the #973 drift gate on a shallow clone. With the default
    depth-1 checkout, docs-ci ran `--strict` with the drift half disabled and still
    reported green — the failure mode this test exists to prevent."""
    text = _read(_DOCS_CI)
    job = text[text.index("jobs:") :]
    assert re.search(r"fetch-depth:\s*0", job), (
        "#1908/#973: docs-ci.yml must check out with fetch-depth: 0 — on a shallow clone "
        "the engine-doc drift gate silently skips and the workflow reports a green it did not earn"
    )


def test_shallow_clone_really_does_skip_the_drift_gate():
    """Proves the guard above is guarding something real, rather than asserting a knob
    whose effect nobody verified."""
    import subprocess
    import sys

    src = _read(os.path.join(_REPO, "scripts", "check_doc_index.py"))
    assert "_is_shallow_repository" in src and "skip drift gate" in src, (
        "check_doc_index.py no longer skips on shallow clones — if that changed, the "
        "fetch-depth: 0 requirement should be re-derived rather than assumed"
    )
    # And the skip path really returns nothing flagged.
    probe = (
        "import sys; sys.path.insert(0, %r);\n"
        "import importlib.util, pathlib\n"
        "spec = importlib.util.spec_from_file_location('cdi', %r)\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "m._is_shallow_repository = lambda: True\n"
        "flagged, notes = m.check_engine_source_freshness()\n"
        "print('FLAGGED', len(flagged)); print('NOTE', any('shallow' in n for n in notes))"
    ) % (os.path.join(_REPO, "scripts"), os.path.join(_REPO, "scripts", "check_doc_index.py"))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=_REPO, timeout=60)
    assert (
        "FLAGGED 0" in out.stdout and "NOTE True" in out.stdout
    ), f"expected the shallow path to flag nothing and note the skip; got:\n{out.stdout}\n{out.stderr}"
