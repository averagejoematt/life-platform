"""tests/test_npm_pin_consistency_2759.py — the npm leg of the CI pin guards (#2759).

Sibling of tests/test_ci_pin_consistency.py, which guards the PIP legs (`pip install
tool==X` second copies, `scripts/ci_pins.py` resolver arguments). This file guards the
npm shape of the same one-legged-pin class:

* `.github/workflows/remediation-agent.yml` installed the claude-code CLI with
  `npm install -g @anthropic-ai/claude-code` — no version on a toolchain install in a
  scheduled job that assumes `github-actions-remediation-role` via OIDC and holds a
  PR-writing `GITHUB_TOKEN`. Every run pulled whatever npm released that day.
* `.github/dependabot.yml` had no npm ecosystem entry covering it, so there was no
  automated bumper either — the zero-legged variant of the class that let the CDK CLI
  pin sit months stale (#2468).

The fix is the #2609 one-copy pattern applied to npm (the same treatment #2760 gives
the CDK CLI via cdk/package.json): the version of record is
`remediation/package.json`'s `@anthropic-ai/claude-code` devDependency, Dependabot's
npm ecosystem (`/remediation`) bumps it, and the workflow resolves it at install time.
These tests make each leg a checked fact and each regression shape a red, proven by
mutation on synthetic text (#2759 acceptance box 3):

* a BARE `npm install -g <pkg>` (no version, no resolver variable) in any workflow;
* a workflow literal `@anthropic-ai/claude-code@X` (a second copy that can only rot);
* the manifest losing the devDependency, or pinning a range instead of an exact
  version;
* dependabot.yml losing the npm `/remediation` ecosystem entry.

Deliberately a SEPARATE file from test_ci_pin_consistency.py: the pip guard is being
extended concurrently for #2760 (PR #2955 rewrites its `_GATED_TOOLS`/exception
blocks and appends its own #2760 guard section), and this file must land cleanly
before or after that PR. The pip-side sweep (`pip install <bare-name>`) is #2760's
`test_no_workflow_installs_an_unpinned_package`, not duplicated here.
"""

import json
import os
import re
import subprocess

import pytest

# yaml is outside the deploy-critical lane's dep set (#2699/#2732 class) —
# importorskip so collection in the minimal lane never crashes; the full
# Unit Tests lane (PyYAML installed) still runs every test here.
yaml = pytest.importorskip("yaml")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLAUDE_CODE = "@anthropic-ai/claude-code"
# Repo-relative, exactly as the workflow's `node -p "require('./…')"` names it.
_MANIFEST = "remediation/package.json"
_AGENT_WORKFLOW = ".github/workflows/remediation-agent.yml"


def _tracked_files():
    out = subprocess.run(["git", "-C", _REPO, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def _workflow_texts():
    """{repo-relative path: text} for every tracked workflow, DERIVED from git
    ls-files (the #2570 lesson: a hand-list of workflow files is how blind spots
    happen — a workflow is in scope the moment it exists)."""
    texts = {}
    for rel in _tracked_files():
        if rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml")):
            with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
                texts[rel] = f.read()
    return texts


# --- the bare-install sweep -----------------------------------------------------


def _bare_npm_installs(texts_by_path):
    """[(path, package), ...] for every package a global `npm install` line would
    resolve from the registry at whatever version released today.

    Not a finding: `@<version>`-suffixed packages (an exact literal is the
    SECOND-COPY guard's concern for claude-code, and the CDK CLI literal is
    #2760's), `$VAR`-resolved forms (`"pkg@${VERSION}"`, the manifest-resolved
    shape this repo standardizes on), and flags.
    """
    findings = []
    for path, text in sorted(texts_by_path.items()):
        for line in text.splitlines():
            line = re.sub(r"\s#.*$", "", line)
            m = re.search(r"\bnpm\s+install\s+(?:-g|--global)\s+(.*)$", line)
            if not m:
                continue
            # Stop at shell connectives so `… && next` is never read as packages.
            args = re.split(r"\s*(?:&&|\|\||;)\s*", m.group(1))[0]
            for tok in (t.strip("\"'") for t in args.split()):
                if not tok or tok.startswith("-"):
                    continue
                if "$" in tok:
                    continue  # resolved at install time from a manifest
                name, sep, _version = tok.rpartition("@")
                if not sep or not name:
                    # No version suffix. For a scoped package (`@scope/pkg`) the
                    # only `@` is at index 0, so rpartition leaves name empty —
                    # also bare.
                    findings.append((path, tok))
    return findings


def test_no_workflow_runs_a_bare_global_npm_install():
    """The #2759 box: a global npm install with no version and no resolver variable
    floats to latest inside CI — a red, whatever the package."""
    bad = _bare_npm_installs(_workflow_texts())
    assert not bad, (
        "workflow(s) install npm packages UNPINNED — the install floats to whatever "
        "released today, invisible to every pip-shaped pin guard (#2759). Put the "
        "version in a Dependabot-covered package.json and resolve it at install time "
        f"(the {_MANIFEST} / cdk/package.json pattern): {bad}"
    )


def test_bare_npm_install_guard_fires_on_the_shipped_defect():
    """Prove-red by mutation (#2759 acceptance): the exact line that shipped must be
    a finding — and the sanctioned forms must stay clean, or the fix is unshippable."""
    bad = _bare_npm_installs({"x.yml": "          npm install -g @anthropic-ai/claude-code\n"})
    assert bad == [("x.yml", _CLAUDE_CODE)], bad
    # Unscoped bare install is the same defect.
    assert _bare_npm_installs({"x.yml": "npm install -g aws-cdk --quiet"}) == [("x.yml", "aws-cdk")]
    ok = "\n".join(
        [
            "          CLAUDE_CODE_VERSION=$(node -p \"require('./remediation/package.json')\")",
            '          npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"',
            # The CDK CLI in both its states: the #814 exact literal (main today)
            # and the #2760 manifest-resolved form (after PR #2955) — neither bare.
            "          npm install -g aws-cdk@2.1135.1 --quiet",
            '          npm install -g "aws-cdk@${CDK_CLI_VERSION}" --quiet',
            "          npm install -g pkg@1.0.0 && echo done",
        ]
    )
    assert not _bare_npm_installs({"x.yml": ok})


# --- the version of record ------------------------------------------------------

_CLAUDE_CODE_LITERAL_RE = re.compile(re.escape(_CLAUDE_CODE) + r"@[0-9][0-9A-Za-z.\-]*")


def _claude_code_literal_installs(texts_by_path):
    """[(path, literal), ...] for every hardcoded `@anthropic-ai/claude-code@X` in a
    workflow. The resolved form (`@${CLAUDE_CODE_VERSION}`) is deliberately not
    matched — that is the shape the version of record exists to feed."""
    return [(p, lit) for p, text in sorted(texts_by_path.items()) for lit in _CLAUDE_CODE_LITERAL_RE.findall(text)]


def test_claude_code_version_of_record_is_remediation_package_json():
    with open(os.path.join(_REPO, _MANIFEST), encoding="utf-8") as f:
        pkg = json.load(f)
    version = pkg.get("devDependencies", {}).get(_CLAUDE_CODE)
    assert version, f"{_MANIFEST} lost its {_CLAUDE_CODE} devDependency — the claude-code CLI has no version of record again (#2759)"
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), (
        f"{_MANIFEST} pins {_CLAUDE_CODE} as '{version}' — must be an EXACT version "
        "(no ^/~ range): a range floats, which is the defect this leg exists to end (#2759)"
    )
    offenders = _claude_code_literal_installs(_workflow_texts())
    assert not offenders, (
        f"workflow(s) hardcode the claude-code CLI version (#2759). The version of record "
        f"is {_MANIFEST}; resolve it at install time so the Dependabot npm bump moves the "
        f"ONLY copy: {offenders}"
    )
    # Non-vacuous (the #1189 lesson): the remediation workflow must still INSTALL the
    # CLI, resolved from the manifest — otherwise this guard stays green after the
    # install step vanishes.
    agent = _workflow_texts()[_AGENT_WORKFLOW]
    assert f"{_CLAUDE_CODE}@" in agent, f"{_AGENT_WORKFLOW} no longer installs the claude-code CLI at all — the agent lost its toolchain"
    assert _MANIFEST in agent, f"{_AGENT_WORKFLOW}'s claude-code install no longer resolves from {_MANIFEST} (#2759)"


def test_claude_code_literal_guard_fires_on_a_synthetic_literal():
    """Prove-red for the second-copy shape, same pattern as every synthetic proof in
    the pip guard."""
    offenders = _claude_code_literal_installs({"x.yml": "npm install -g @anthropic-ai/claude-code@2.0.0"})
    assert offenders == [("x.yml", "@anthropic-ai/claude-code@2.0.0")], offenders
    assert not _claude_code_literal_installs({"x.yml": 'npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"'})


# --- the Dependabot leg ---------------------------------------------------------


def test_claude_code_pin_has_a_dependabot_npm_leg():
    """A pin Dependabot cannot see is one-legged by definition (#2468): the npm
    ecosystem entry for /remediation is the leg; losing it re-opens the incident."""
    with open(os.path.join(_REPO, ".github", "dependabot.yml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    legs = [u for u in cfg.get("updates", []) if u.get("package-ecosystem") == "npm" and u.get("directory") == "/remediation"]
    assert (
        legs
    ), ".github/dependabot.yml lost the npm /remediation ecosystem entry — the claude-code CLI pin is one-legged again (#2759/#2468)"
