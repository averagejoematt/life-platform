"""#2644 — a reusable workflow inherits NO secrets; the wiring must be explicit.

`ci-lint.yml` was extracted from `ci-cd.yml` in #1655 with its steps copied
verbatim, including `env: CONTENT_FILTER_JSON: ${{ secrets.CONTENT_FILTER_JSON }}`.
Inside a `workflow_call` that expression resolves to the **empty string** unless the
caller passes the secret explicitly. So from #2370 until this test landed, the
content-policy scan skipped on every main-pipeline run while the secret existed,
the env line was present, and the step ran green. Every visible signal said armed.

This guards the SET, not the instance: it walks EVERY local reusable-workflow call
in `.github/workflows/`, so the next extracted job that quietly depends on a secret
fails here on the day it lands rather than a month later.

The rule enforced, for each `uses: ./.github/workflows/X.yml` call:
  1. every `secrets.NAME` that X actually references must be declared under X's
     `on.workflow_call.secrets`, and
  2. the call site must pass it (explicitly, or via `secrets: inherit`).
"""

import re
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# `secrets.GITHUB_TOKEN` is always available inside a reusable workflow and is never
# declared or passed. Everything else is a real, inheritable-by-nothing repo secret.
_ALWAYS_AVAILABLE = {"GITHUB_TOKEN"}

# Must be a real GitHub expression: `${{ … secrets.NAME … }}`. A bare `secrets\.\w+`
# also matches prose and paths — `ci/deprecated_secrets.txt` yields a phantom secret
# named "txt", which is exactly the kind of false finding that makes a gate ignorable.
_SECRET_REF = re.compile(r"\$\{\{[^}]*?secrets\.([A-Za-z_][A-Za-z0-9_]*)")


def _yaml():
    """PyYAML is absent from CI's minimal deploy-critical lane, which still COLLECTS
    every test module — so a module-level `import yaml` fails that lane's collection
    and skips the deploy (#2644 did exactly that on main). Imported lazily and
    skipped-if-missing, per tests/test_site_deploy_workflow.py. The Unit Tests lane
    does install pyyaml, so this guard really runs in CI."""
    return pytest.importorskip("yaml")


def _load(path: Path):
    # `on:` is parsed by PyYAML 1.1 rules as the boolean True — hence the lookup below.
    return _yaml().safe_load(path.read_text(encoding="utf-8"))


def _referenced_secrets(path: Path):
    """Secret names the workflow body actually uses.

    Read from the raw text rather than the parsed tree so a reference anywhere —
    `env:`, `with:`, an inline `run:` — is caught.
    """
    return {n for n in _SECRET_REF.findall(path.read_text(encoding="utf-8")) if n not in _ALWAYS_AVAILABLE}


def _declared_secrets(doc):
    trigger = doc.get("on", doc.get(True, {})) or {}
    call = (trigger or {}).get("workflow_call") or {}
    return set((call.get("secrets") or {}).keys())


REPO_ROOT = WORKFLOW_DIR.parents[1]


def _reusable_calls():
    """(caller_path, job_name, callee_path, job_spec) for every local call."""
    out = []
    for wf in sorted(WORKFLOW_DIR.glob("*.yml")):
        doc = _load(wf)
        if not isinstance(doc, dict):
            continue
        for job_name, spec in (doc.get("jobs") or {}).items():
            if not isinstance(spec, dict):
                continue
            uses = spec.get("uses")
            if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
                # NB: not lstrip("./") — that strips the leading dot of ".github" too.
                out.append((wf, job_name, REPO_ROOT / uses[2:], spec))
    return out


def test_there_is_something_to_guard():
    """Non-vacuity: if the discovery walk silently found nothing, both assertions
    below would pass while checking exactly zero call sites."""
    assert _reusable_calls(), "found no local reusable-workflow calls — the walk is broken, not the repo"


def test_callee_declares_every_secret_it_uses():
    """The requirement must be stated where it is consumed."""
    problems = []
    for caller, job, callee, _spec in _reusable_calls():
        assert callee.exists(), f"{caller.name}:{job} calls missing workflow {callee}"
        missing = _referenced_secrets(callee) - _declared_secrets(_load(callee))
        if missing:
            problems.append(
                f"{callee.name} references {sorted(missing)} but does not declare them under "
                f"on.workflow_call.secrets — inside a reusable workflow these resolve to '' "
                f"and the step silently does nothing (called by {caller.name}:{job})."
            )
    assert not problems, "\n".join(problems)


def test_call_site_passes_every_secret_the_callee_uses():
    """And it must actually be handed over. This is the half #2644 was missing."""
    problems = []
    for caller, job, callee, spec in _reusable_calls():
        used = _referenced_secrets(callee)
        if not used:
            continue
        passed = spec.get("secrets")
        if passed == "inherit":
            continue
        passed_names = set(passed.keys()) if isinstance(passed, dict) else set()
        missing = used - passed_names
        if missing:
            problems.append(
                f"{caller.name}:{job} calls {callee.name}, which needs {sorted(used)}, but the "
                f"call site passes {sorted(passed_names) or 'nothing'}. A reusable workflow "
                f"inherits NO secrets — pass them explicitly."
            )
    assert not problems, "\n".join(problems)
