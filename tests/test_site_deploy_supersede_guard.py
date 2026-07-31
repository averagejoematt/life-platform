"""tests/test_site_deploy_supersede_guard.py — #1907: a recovery re-run must never be silently stranded.

site-deploy.yml skips a queued run whose HEAD is an ancestor of origin/main, justified by
"the newer commit has its own queued run that deploys a strict superset of this one."

**That is only true when the newer commit matches this workflow's `paths:` filter.** The
workflow triggers on `site/**` (plus its own file), so a merge touching only `docs/`
advances origin/main WITHOUT creating a replacement run.

The live failure mode (found 2026-07-29, one merge away from firing):

  1. a `site/**` merge deploys; a post-deploy gate flakes (smoke `exit 28`, #1911)
     → auto-rollback reverts the site
  2. the operator re-runs the site-deploy run to restore the correct tree — correct move
  3. a docs-only merge lands while that re-run is in flight → origin/main advances
  4. the re-run declares itself superseded and skips — and NOTHING replaces it

Net: the site stays on the rolled-back tree indefinitely, both runs report success, the
skip is a clean exit, and nothing alarms. At the time, the rolled-back tree was the one
carrying a real clinician's name on a live public page (#1891).

These tests execute the ACTUAL shell from the workflow (extracted by regex — this module
must not depend on PyYAML, per test_site_deploy_workflow.py's note that CI's test job
installs only pytest/boto3) against real throwaway git repositories. Asserting on the
shipped logic rather than a paraphrase is the point: a regex-only test would still pass if
someone rewrote the condition incorrectly.
"""

import os
import re
import subprocess
import textwrap

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SITE_DEPLOY = os.path.join(_REPO, ".github", "workflows", "site-deploy.yml")


def _extract_supersede_script():
    """Pull the `run: |` body of the 'Superseded-run check' step out of the workflow."""
    with open(_SITE_DEPLOY, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = next((i for i, ln in enumerate(lines) if "name: Superseded-run check" in ln), None)
    assert start is not None, "the 'Superseded-run check' step is missing from site-deploy.yml"
    run_idx = next((i for i in range(start, len(lines)) if re.match(r"\s*run:\s*\|", lines[i])), None)
    assert run_idx is not None, "the Superseded-run check step has no `run: |` block"
    body_indent = len(lines[run_idx + 1]) - len(lines[run_idx + 1].lstrip())
    body = []
    for ln in lines[run_idx + 1 :]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) < body_indent:
            break
        body.append(ln)
    script = textwrap.dedent("\n".join(body))
    assert "superseded=" in script, "extracted block does not look like the supersede check"
    return script


_SCRIPT = _extract_supersede_script()


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_repos(tmp_path, newer_files):
    """A clone whose HEAD is one commit behind an origin/main that changed `newer_files`.

    Returns the clone path, positioned exactly as a queued/re-run CI checkout would be.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "t@t.t")
    _git(seed, "config", "user.name", "t")
    for p in ("site/index.html", "docs/README.md", ".github/workflows/site-deploy.yml"):
        f = seed / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("seed\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True, capture_output=True)

    # The CI checkout: at the seed commit (this run's HEAD).
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")

    if newer_files:
        # A newer commit lands on origin/main while this run is in flight.
        for p in newer_files:
            f = seed / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("newer\n")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "newer")
        _git(seed, "push", "-q", str(origin), "main")
    return work


def _run_check(tmp_path, newer_files):
    work = _make_repos(tmp_path, newer_files)
    out_file = tmp_path / "gh_output"
    out_file.write_text("")
    proc = subprocess.run(
        ["bash", "-c", _SCRIPT],
        cwd=work,
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_OUTPUT": str(out_file)},
        timeout=60,
    )
    assert proc.returncode == 0, f"supersede check errored:\n{proc.stdout}\n{proc.stderr}"
    m = re.search(r"superseded=(true|false)", out_file.read_text())
    assert m, f"no superseded output written. stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    return m.group(1), proc.stdout


# ── The incident ──────────────────────────────────────────────────────────────


def test_docs_only_newer_commit_does_not_supersede(tmp_path):
    """THE #1907 regression guard. A docs-only merge creates NO site-deploy run, so
    skipping here would strand the site on the rolled-back tree with every run green."""
    verdict, log = _run_check(tmp_path, ["docs/README.md"])
    assert verdict == "false", (
        "a docs-only commit does not match the site/** path filter, so it has no run of "
        "its own — this run must NOT declare itself superseded (#1907)"
    )
    assert "NOT superseded" in log, "the non-supersede decision must be explained in the log"


def test_unrelated_path_newer_commit_does_not_supersede(tmp_path):
    """Generalises beyond docs/: ANY non-trigger path has the same problem."""
    verdict, _ = _run_check(tmp_path, ["lambdas/web/site_api_lambda.py"])
    assert verdict == "false"


# ── The behaviour that must be preserved ──────────────────────────────────────


def test_site_change_still_supersedes(tmp_path):
    """The original purpose still holds: a newer site/ commit HAS its own run."""
    verdict, log = _run_check(tmp_path, ["site/index.html"])
    assert verdict == "true", "a newer site/ commit genuinely supersedes this run"
    assert "site/index.html" in log, "the skip must name what changed, so it is auditable"


def test_workflow_change_still_supersedes(tmp_path):
    """site-deploy.yml is itself a trigger path — a change to it also creates a run."""
    verdict, _ = _run_check(tmp_path, [".github/workflows/site-deploy.yml"])
    assert verdict == "true"


def test_mixed_change_supersedes(tmp_path):
    verdict, _ = _run_check(tmp_path, ["docs/README.md", "site/index.html"])
    assert verdict == "true", "a range containing a site/ change has a replacement run"


def test_head_at_tip_is_not_superseded(tmp_path):
    verdict, _ = _run_check(tmp_path, [])
    assert verdict == "false", "the normal case (HEAD == origin/main) must deploy"


# ── Auditability + the path list staying in sync with the trigger ─────────────


def test_skip_names_the_superseding_commit(tmp_path):
    """Acceptance: a skip must be auditable, not assumed."""
    _, log = _run_check(tmp_path, ["site/index.html"])
    assert "superseding commit:" in log, "a skip must record WHICH commit supersedes it"


def test_supersede_path_list_mirrors_the_trigger_paths():
    """If someone adds a trigger path but not to the supersede check, the check would
    again skip runs that nothing replaces. Derived from the workflow's own `paths:`."""
    with open(_SITE_DEPLOY, encoding="utf-8") as f:
        text = f.read()
    trigger = re.search(r"on:\s*\n\s*push:\s*\n\s*branches:.*?\n\s*paths:\s*\n((?:\s*-\s*'[^']+'.*\n)+)", text)
    assert trigger, "could not locate on.push.paths in site-deploy.yml"
    paths = re.findall(r"-\s*'([^']+)'", trigger.group(1))
    assert paths, "no trigger paths parsed"
    for p in paths:
        stem = p.replace("/**", "/").rstrip("/")
        assert stem in _SCRIPT, (
            f"trigger path {p!r} is not consulted by the supersede check — a commit touching "
            f"only {p!r} would create a replacement run that the check cannot see (#1907)"
        )
