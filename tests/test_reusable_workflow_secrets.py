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
import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# `secrets.GITHUB_TOKEN` is always available inside a reusable workflow and is never
# declared or passed. Everything else is a real, inheritable-by-nothing repo secret.
_ALWAYS_AVAILABLE = {"GITHUB_TOKEN"}

# Must be a real GitHub expression: `${{ … secrets.NAME … }}`. A bare `secrets\.\w+`
# also matches prose and paths — `ci/deprecated_secrets.txt` yields a phantom secret
# named "txt", which is exactly the kind of false finding that makes a gate ignorable.
_SECRET_REF = re.compile(r"\$\{\{[^}]*?secrets\.([A-Za-z_][A-Za-z0-9_]*)")


def _load(path: Path):
    # `on:` is parsed by PyYAML 1.1 rules as the boolean True — hence the lookup below.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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


CALLS = _reusable_calls()
CALL_IDS = [f"{c.name}:{j}->{k.name}" for c, j, k, _ in CALLS]


def test_there_is_something_to_guard():
    """Non-vacuity: if the discovery walk silently found nothing, every assertion
    below would pass while checking exactly zero call sites."""
    assert CALLS, "found no local reusable-workflow calls — the walk is broken, not the repo"


@pytest.mark.parametrize("caller,job,callee,spec", CALLS, ids=CALL_IDS)
def test_callee_declares_every_secret_it_uses(caller, job, callee, spec):
    """The requirement must be stated where it is consumed."""
    assert callee.exists(), f"{caller.name}:{job} calls missing workflow {callee}"
    used = _referenced_secrets(callee)
    declared = _declared_secrets(_load(callee))
    missing = used - declared
    assert not missing, (
        f"{callee.name} references {sorted(missing)} but does not declare them under "
        f"on.workflow_call.secrets — inside a reusable workflow these resolve to '' "
        f"and the step silently does nothing (#2644)."
    )


@pytest.mark.parametrize("caller,job,callee,spec", CALLS, ids=CALL_IDS)
def test_call_site_passes_every_secret_the_callee_uses(caller, job, callee, spec):
    """And it must actually be handed over. This is the half #2644 was missing."""
    used = _referenced_secrets(callee)
    if not used:
        return
    passed = spec.get("secrets")
    if passed == "inherit":
        return
    passed_names = set(passed.keys()) if isinstance(passed, dict) else set()
    missing = used - passed_names
    assert not missing, (
        f"{caller.name}:{job} calls {callee.name}, which needs {sorted(used)}, but the "
        f"call site passes {sorted(passed_names) or 'nothing'}. A reusable workflow "
        f"inherits NO secrets — pass them explicitly (#2644)."
    )
