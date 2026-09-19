"""tests/test_fake_creds_parity_step_3608.py — #3608 box 5.

THE DEFECT. docs/CONVENTIONS.md §4's FAKE-creds parity invocation was
DOCUMENTATION. Nothing ran it, so the claim "CI's test lanes cannot reach real
AWS credentials" was asserted and never measured — the same shape as box 1's
one-bundle claim.

THE FIX. ci-cd.yml's `test-critical` job runs the invocation for real: the
deploy-critical lane itself executes under it, and a dedicated step runs
`scripts/assert_fake_creds_parity.py`, which fails if boto3 can resolve
anything but the fake pair.

WHAT THIS FILE GUARDS. Not a copy of the invocation — the two texts must AGREE.
The literal is read from docs/CONVENTIONS.md and required to be present in the
workflow, so editing either one alone reds. A TEXT MATCH READS THE COMMENT
EXPLAINING IT (#3853): this file quotes fragments of the invocation, so it
would match itself if it ever scanned `tests/`. It scans exactly two files, by
path, and never a directory.
"""

import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CI_CD = os.path.join(REPO_ROOT, ".github", "workflows", "ci-cd.yml")
CONVENTIONS = os.path.join(REPO_ROOT, "docs", "CONVENTIONS.md")
PARITY_SCRIPT = os.path.join(REPO_ROOT, "scripts", "assert_fake_creds_parity.py")

# The invocation's load-bearing tokens, in the order §4 states them. `env -u`
# for the profile/session (never `AWS_PROFILE=`, which raises ProfileNotFound)
# and a PRESENT-but-invalid key pair.
_REQUIRED_TOKENS = (
    "env -u AWS_PROFILE -u AWS_SESSION_TOKEN",
    "AWS_ACCESS_KEY_ID=FAKEKEY",
    "AWS_SECRET_ACCESS_KEY=FAKESECRET",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_conventions_still_documents_the_invocation():
    """The derivation source. If §4 ever rewrites the incantation, the workflow
    assertions below become a check against a dead doc — this fails first and
    says so."""
    text = _read(CONVENTIONS)
    for token in _REQUIRED_TOKENS:
        assert token in text, f"docs/CONVENTIONS.md §4 no longer contains {token!r} — re-derive this test from the new wording"


def test_ci_cd_runs_the_parity_invocation_not_just_documents_it():
    text = _read(CI_CD)
    for token in _REQUIRED_TOKENS:
        assert token in text, (
            f".github/workflows/ci-cd.yml does not run the CONVENTIONS §4 parity invocation ({token!r} absent). "
            "#3608 box 5 made it a step; a doc-only incantation is what that box was filed against."
        )


def test_the_parity_step_exists_and_calls_the_assertion_script():
    text = _read(CI_CD)
    assert "AWS creds parity" in text, "the dedicated parity STEP is gone from ci-cd.yml"
    assert "scripts/assert_fake_creds_parity.py" in text, "the parity step no longer calls the assertion script"
    assert os.path.exists(PARITY_SCRIPT), "scripts/assert_fake_creds_parity.py is missing"


def test_the_deploy_critical_lane_itself_runs_under_the_fake_creds():
    """The step alone would prove only that ONE process is isolated. The lane
    that actually imports boto3-using modules has to run under it too, or the
    parity claim covers the guard and not the thing guarded."""
    text = _read(CI_CD)
    m = re.search(r"pytest tests/ -m \"deploy_critical and not integration\"", text)
    assert m, "the deploy-critical lane invocation changed shape — re-derive this assertion"
    window = text[max(0, m.start() - 400) : m.start()]
    assert "env -u AWS_PROFILE -u AWS_SESSION_TOKEN" in window, (
        "the deploy-critical pytest lane no longer runs under the §4 FAKE-creds invocation — "
        "boto3 can fall back to a [default] profile in that lane again (#3608 box 5)"
    )


def test_the_assertion_script_never_echoes_a_resolved_key():
    """A parity FAILURE means a real credential was reachable. CI job logs are
    the last place to print one, so the failure path must report the resolution
    METHOD and redact the key. Asserted structurally, because the only way to
    observe it live is to run the gate on a machine that has real credentials."""
    src = _read(PARITY_SCRIPT)
    assert "key redacted" in src
    assert "creds.access_key!r" not in src, "the failure path formats the resolved access key — redact it"
    assert "{creds.access_key}" not in src, "the failure path formats the resolved access key — redact it"
