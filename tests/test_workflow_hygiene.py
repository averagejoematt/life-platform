"""tests/test_workflow_hygiene.py — #1331: auto-rollback must key on a real QA
verdict, never on harness/plumbing noise.

Incident: account-wide GitHub Actions artifact-quota exhaustion (recalculates
every 6-12h, unrelated to any single deploy) failed the "Upload screenshots +
report" post-step in site-deploy.yml's `visual-qa` job AFTER it had already
printed "✅ GATE PASSED" — the failed upload flipped the job's overall
`result` to `failure`, and `rollback-site-on-failure` (which `needs: [...,
visual-qa]` and fires on `needs.visual-qa.result == 'failure'`) auto-rolled-
back a healthy production deploy (observed 2026-07-16 and 2026-07-17; see
`reference_ci_artifact_quota_rollback.md`).

Structural guard (text-based on purpose, like test_site_deploy_workflow.py —
CI's `test` job installs only pytest/boto3/botocore, no PyYAML, so this must
not depend on it): for every workflow under .github/workflows/, find any job
that looks like a rollback job (id/body signals rollback intent) and whose
`if:` condition reads `needs.<upstream>.result` for some job listed in its
`needs:`. For every such upstream job, every `actions/upload-artifact` step
inside it MUST carry `continue-on-error: true` — a diagnostics side-channel
must never be able to flip the job conclusion that a rollback decision reads.
"""

import glob
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKFLOWS_DIR = os.path.join(_REPO, ".github", "workflows")
_SITE_DEPLOY = os.path.join(_WORKFLOWS_DIR, "site-deploy.yml")

_ROLLBACK_SCRIPTS = ("rollback_site.sh", "rollback_lambda.sh")

# Matches a top-level job header, e.g. "  rollback-site-on-failure:" — this repo's
# workflows consistently indent job ids exactly 2 spaces under `jobs:`.
_JOB_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):[ \t]*$", re.MULTILINE)

# A step-list-item marker at a given indent, e.g. "      - name: ..." or
# "      - uses: ...". Steps are the list items directly under a job's `steps:`.
_STEP_MARKER_RE = re.compile(r"^([ \t]+)- ", re.MULTILINE)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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


def _job_needs(body):
    """Extract the list of job ids in a job's `needs:` — inline scalar, inline
    list, or a multi-line `- item` list."""
    m = re.search(r"^    needs:[ \t]*(.*)$", body, re.MULTILINE)
    if not m:
        return []
    inline = m.group(1).strip()
    if inline.startswith("["):
        return [x.strip().strip("'\"") for x in inline.strip("[]").split(",") if x.strip()]
    if inline:
        return [inline.strip("'\"")]
    # Multi-line list: subsequent "      - job" lines immediately after `needs:`.
    tail = body[m.end() :]  # noqa: E203
    items = []
    for line in tail.splitlines():
        lm = re.match(r"^      - ([A-Za-z0-9_-]+)[ \t]*$", line)
        if lm:
            items.append(lm.group(1))
        elif line.strip() == "" or line.startswith("      "):
            continue
        else:
            break
    return items


def _job_if_condition(body):
    """Extract a job-level `if:` condition, joining a folded block scalar
    (`if: >-` followed by indented continuation lines) into one string."""
    m = re.search(r"^    if:[ \t]*(.*)$", body, re.MULTILINE)
    if not m:
        return ""
    first = m.group(1).strip()
    if first in (">-", ">", "|", "|-"):
        tail = body[m.end() :]  # noqa: E203
        cont = []
        for line in tail.splitlines():
            if re.match(r"^      \S", line):
                cont.append(line.strip())
            elif line.strip() == "":
                continue
            else:
                break
        return " ".join(cont)
    return first


def _is_rollback_job(job_id, body):
    if "rollback" in job_id.lower():
        return True
    return any(script in body for script in _ROLLBACK_SCRIPTS)


def _steps_in(body):
    """Split a job's body into step-text chunks, grouped by the indent level of
    the FIRST step marker found (steps are siblings at one indent; nested list
    items inside `with:`/`run:` blocks sit deeper and are captured inside their
    parent step's chunk, which is what we want)."""
    markers = list(_STEP_MARKER_RE.finditer(body))
    if not markers:
        return []
    step_indent = markers[0].group(1)
    top = [m for m in markers if m.group(1) == step_indent]
    chunks = []
    for i, m in enumerate(top):
        start = m.start()
        end = top[i + 1].start() if i + 1 < len(top) else len(body)
        chunks.append(body[start:end])
    return chunks


def _upload_artifact_steps_missing_continue_on_error(body):
    offenders = []
    for step in _steps_in(body):
        if "actions/upload-artifact@" not in step:
            continue
        if "continue-on-error: true" not in step:
            name_m = re.search(r"- name:\s*(.+)", step)
            offenders.append(name_m.group(1).strip() if name_m else step.splitlines()[0].strip())
    return offenders


def _iter_workflow_files():
    return sorted(glob.glob(os.path.join(_WORKFLOWS_DIR, "*.yml")))


def test_upload_artifact_steps_feeding_a_rollback_neednt_be_missed_by_this_test():
    """Sanity check on the parser itself: site-deploy.yml must actually contain
    an upload-artifact step inside `visual-qa`, and rollback-site-on-failure must
    actually key on `needs.visual-qa.result` — otherwise the guard below would
    pass vacuously and prove nothing."""
    text = _read(_SITE_DEPLOY)
    bodies = _job_bodies(text)
    assert "visual-qa" in bodies
    assert "actions/upload-artifact@" in bodies["visual-qa"]
    assert "rollback-site-on-failure" in bodies
    assert _is_rollback_job("rollback-site-on-failure", bodies["rollback-site-on-failure"])
    assert "visual-qa" in _job_needs(bodies["rollback-site-on-failure"])
    assert "needs.visual-qa.result" in _job_if_condition(bodies["rollback-site-on-failure"])


def test_rollback_feeder_jobs_guard_upload_artifact_with_continue_on_error():
    """The regression guard (#1331): a diagnostics upload must never be able to
    flip the job conclusion that a rollback `needs` condition reads.

    For every workflow, for every job that looks like a rollback job AND whose
    `if:` references `needs.<upstream>.result` for a job in its `needs:` list,
    every `actions/upload-artifact` step in that upstream job must carry
    `continue-on-error: true`.
    """
    failures = []
    for path in _iter_workflow_files():
        text = _read(path)
        bodies = _job_bodies(text)
        for job_id, body in bodies.items():
            if not _is_rollback_job(job_id, body):
                continue
            needs = _job_needs(body)
            if_cond = _job_if_condition(body)
            for upstream in needs:
                if f"needs.{upstream}.result" not in if_cond:
                    continue  # this upstream's result doesn't gate the rollback
                upstream_body = bodies.get(upstream)
                if upstream_body is None:
                    continue
                offenders = _upload_artifact_steps_missing_continue_on_error(upstream_body)
                for offender in offenders:
                    failures.append(
                        f"{os.path.basename(path)}: job '{upstream}' feeds rollback job "
                        f"'{job_id}' (via needs.{upstream}.result) but its upload-artifact "
                        f"step '{offender}' has no continue-on-error: true — harness/quota "
                        f"noise on that upload can flip the job conclusion and fire an "
                        f"auto-rollback of a healthy deploy (#1331)."
                    )
    assert not failures, "\n" + "\n".join(failures)
