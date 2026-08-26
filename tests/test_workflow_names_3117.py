"""tests/test_workflow_names_3117.py — #3117: no workflow `name:` may silently
truncate at a YAML comment start.

THE DEFECT: `pr-checks.yml`'s `full-suite` job carried `name: Full unit suite
(pre-merge, #3025)`. YAML treats an unquoted `#` preceded by whitespace as a
COMMENT START, so everything from " #3025)" onward was stripped before GitHub
ever saw the string — the wire check-run name silently truncated to `Full unit
suite (pre-merge,` (trailing comma). `deploy/wait_pr_green.sh` (#3103) had to
hardcode that truncated string to match what GitHub actually reports, which is
exactly the trap: anyone reading the YAML source would copy the un-truncated
form and require a check-run name that never reports (would-be load-bearing the
day this check enters `deploy/github_posture.json`'s required-context set).

`(#2831)` in the `api-before-frontend` job's name is FINE — its `#` is preceded
by `(`, not whitespace, so YAML never treats it as a comment start. The rule
this file enforces is specifically "no ' #' (whitespace then hash) in an
UNQUOTED name value," not "no `#` anywhere in a name."

Text-based on purpose, like tests/test_workflow_hygiene.py: this file must stay
importable/runnable in ci-cd.yml's post-merge `test` job, which installs only
pytest/boto3/botocore (no PyYAML) — see that file's own docstring for the same
constraint. It also runs pre-merge without any extra classification, because
pr-checks.yml's `full-suite` job runs `pytest tests/ --ignore=tests/
test_integration_aws.py` (virtually the whole tree, this file included), not
just the fast-lane's marker-scoped subset.
"""

import glob
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKFLOWS_DIR = os.path.join(_REPO, ".github", "workflows")

# A top-level job header, e.g. "  full-suite:" — this repo's workflows
# consistently indent job ids exactly 2 spaces under `jobs:`.
_JOB_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):[ \t]*$", re.MULTILINE)

# A job-level `name:` field — 4-space indent, direct child of the job.
_JOB_NAME_RE = re.compile(r"^    name:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _iter_workflow_files():
    return sorted(glob.glob(os.path.join(_WORKFLOWS_DIR, "*.yml")))


def _job_bodies(text):
    """Return {job_id: body_text} for every top-level job in a workflow file.
    A job's body runs from just after its header to the next job header (or EOF)."""
    headers = list(_JOB_HEADER_RE.finditer(text))
    bodies = {}
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        bodies[m.group(1)] = text[start:end]
    return bodies


def _job_name_value(body):
    """The job's own `name:` field value, raw (quotes, if any, still attached).
    Only the FIRST `    name:` in the body counts — later ones belong to steps
    nested one indent deeper and are a different field entirely."""
    m = _JOB_NAME_RE.search(body)
    return m.group(1) if m else None


def _is_quoted(value):
    return len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]


def test_the_parser_actually_finds_the_known_job_names():
    """Sanity check on the parser itself: pr-checks.yml must contain a
    `full-suite` job with a `name:` field, or the sweep below would pass
    vacuously and prove nothing."""
    text = _read(os.path.join(_WORKFLOWS_DIR, "pr-checks.yml"))
    bodies = _job_bodies(text)
    assert "full-suite" in bodies
    name = _job_name_value(bodies["full-suite"])
    assert name is not None
    assert name == "Full unit suite (pre-merge, issue 3025)"


def test_no_job_name_contains_an_unquoted_comment_start():
    """The #3117 regression guard: an unquoted `name:` value must never contain
    ' #' (whitespace immediately followed by `#`) — that is a YAML comment
    start, and GitHub receives everything BEFORE it, silently truncated.

    A QUOTED value (single or double) is exempt — YAML does not treat `#`
    inside a quoted scalar as a comment start, so `name: "Full unit suite #3025"`
    would be safe. This repo's convention (see the full-suite job's own #3117
    comment) is still to avoid the character entirely rather than lean on
    quoting, but this guard only needs to catch the case that actually lies.
    """
    failures = []
    for path in _iter_workflow_files():
        text = _read(path)
        bodies = _job_bodies(text)
        for job_id, body in bodies.items():
            name = _job_name_value(body)
            if name is None:
                continue
            if _is_quoted(name):
                continue
            if " #" in name:
                truncated = name.split(" #", 1)[0]
                failures.append(
                    f"{os.path.basename(path)}: job '{job_id}' has name {name!r} — "
                    f"unquoted ' #' is a YAML comment start, so GitHub would actually "
                    f"receive {truncated!r} (#3117 class). Quote the string or remove "
                    f"the '#'."
                )
    assert not failures, "\n" + "\n".join(failures)
