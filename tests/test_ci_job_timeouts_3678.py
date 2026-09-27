"""tests/test_ci_job_timeouts_3678.py — the per-job `timeout-minutes` registry (#3678).

`scripts/ci_job_timeouts.py` is the ONE place both the derivation guard
(`check_job_timeout_headroom.py`) and the cancelled-run discriminator
(`ci_run_verdicts.py`) read a job's declared ceiling from — this file proves the
enumeration itself: real-repo coverage, a synthetic-fixture mutation proof for
the template-name carve-out, and the "no `timeout-minutes` key at all" case.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ci_job_timeouts as cjt  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_workflow(dirpath, filename, text):
    with open(os.path.join(dirpath, filename), "w", encoding="utf-8") as fh:
        fh.write(text)


# ── real-repo coverage (no fixture needed — the actual .github/workflows/) ──


def test_the_real_repo_finds_the_two_pr_checks_jobs_named_in_3678():
    entries = cjt.iter_job_timeouts()
    by_name = {e["job_name"]: e for e in entries}
    assert "Collect + deploy-critical + format" in by_name
    assert "Full unit suite (pre-merge, issue 3025)" in by_name
    fast_lane = by_name["Collect + deploy-critical + format"]
    assert fast_lane["file"] == "pr-checks.yml"
    assert fast_lane["templated"] is False
    assert isinstance(fast_lane["timeout_minutes"], (int, float))


def test_the_real_repo_population_is_more_than_one_job():
    """#3678's whole point: the derivation must enumerate every job, not just the
    one the issue named — a population of 1 would mean the sweep is blind."""
    entries = cjt.iter_job_timeouts()
    assert len(entries) >= 5, entries


def test_timeout_minutes_by_job_name_matches_iter_job_timeouts():
    entries = cjt.iter_job_timeouts()
    mapping = cjt.timeout_minutes_by_job_name()
    non_templated = [e for e in entries if not e["templated"]]
    # #4253: a check-run name can recur across files ("Visual + AI-vision QA" is a job in
    # both ci-cd.yml and site-deploy.yml). The map is keyed by name, so a recurring name is
    # only sound while every copy declares the SAME ceiling — the loop below reds otherwise.
    assert len(mapping) == len({e["job_name"] for e in non_templated})
    for e in non_templated:
        assert mapping[e["job_name"]] == e["timeout_minutes"], (
            f"{e['file']}:{e['job_id']} shares the name {e['job_name']!r} with another job at a different "
            "timeout-minutes — the by-name map would report the wrong ceiling for one of them"
        )


# ── synthetic fixture: templated names are found but excluded (#3678) ──────


def test_a_templated_job_name_is_reported_but_excluded_from_the_map():
    with tempfile.TemporaryDirectory() as d:
        _write_workflow(
            d,
            "matrix.yml",
            """
name: Matrix example
on: push
jobs:
  analyze:
    name: CodeQL analysis (${{ matrix.language }})
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - run: echo hi
""",
        )
        entries = cjt.iter_job_timeouts(d)
        assert len(entries) == 1
        assert entries[0]["templated"] is True
        assert cjt.timeout_minutes_by_job_name(d) == {}


def test_a_job_with_no_explicit_name_falls_back_to_the_job_id():
    with tempfile.TemporaryDirectory() as d:
        _write_workflow(
            d,
            "unnamed.yml",
            """
name: Unnamed job example
on: push
jobs:
  my_job_id:
    runs-on: ubuntu-latest
    timeout-minutes: 7
    steps:
      - run: echo hi
""",
        )
        entries = cjt.iter_job_timeouts(d)
        assert entries == [
            {"file": "unnamed.yml", "job_id": "my_job_id", "job_name": "my_job_id", "timeout_minutes": 7, "templated": False}
        ]


def test_a_job_with_no_timeout_minutes_is_not_enumerated():
    with tempfile.TemporaryDirectory() as d:
        _write_workflow(
            d,
            "no_timeout.yml",
            """
name: No timeout example
on: push
jobs:
  bare:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
""",
        )
        assert cjt.iter_job_timeouts(d) == []


def test_an_empty_workflow_dir_returns_empty_not_an_error():
    with tempfile.TemporaryDirectory() as d:
        assert cjt.iter_job_timeouts(d) == []
        assert cjt.timeout_minutes_by_job_name(d) == {}


def test_a_nonexistent_workflow_dir_degrades_to_empty():
    assert cjt.iter_job_timeouts(os.path.join(_REPO, "definitely-not-a-real-directory-3678")) == []


# ── #4253: every job in the deploy-path workflows is bounded, and one OIDC pin ──
#
# ci-cd, ci-test, ci-lint and site-deploy ran on GitHub's 360-minute default: a hung
# step held the runner AND the deploy concurrency slot for six hours. Each job now
# carries a ceiling measured from its own trailing runs (the table is in the #4253 PR
# body). A job that CALLS a reusable workflow (`uses:`) cannot take `timeout-minutes`
# at all (GitHub rejects the key there) — the callee's job carries it, so the callee
# file is in the set.

_BOUNDED_WORKFLOWS = ("ci-cd.yml", "ci-test.yml", "ci-lint.yml", "site-deploy.yml")
_OIDC_PIN_RE = __import__("re").compile(r"uses:\s*aws-actions/configure-aws-credentials@([0-9a-f]{40})")


def _jobs_without_timeout(workflow_dir, files):
    """`[(file, job_id)]` for every runner job in `files` that declares no `timeout-minutes`."""
    missing = []
    for fname in files:
        with open(os.path.join(workflow_dir, fname), encoding="utf-8") as fh:
            doc = cjt._load_yaml(fh.read())
        jobs = doc.get("jobs")
        assert isinstance(jobs, dict) and jobs, f"{fname} has no jobs — the guard would be vacuous"
        for job_id, job in jobs.items():
            if "uses" in job:  # reusable-workflow caller: the callee job carries the ceiling
                continue
            if job.get("timeout-minutes") is None:
                missing.append((fname, job_id))
    return missing


def _oidc_pins(root):
    """`{sha: [path, ...]}` for every configure-aws-credentials pin under `root`."""
    pins: dict = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith((".yml", ".yaml")):
                path = os.path.join(dirpath, f)
                with open(path, encoding="utf-8") as fh:
                    for sha in _OIDC_PIN_RE.findall(fh.read()):
                        pins.setdefault(sha, []).append(os.path.relpath(path, root))
    return pins


def test_every_job_in_the_four_deploy_path_workflows_declares_timeout_minutes():
    missing = _jobs_without_timeout(cjt.WORKFLOW_DIR, _BOUNDED_WORKFLOWS)
    assert missing == [], f"jobs running on GitHub's 360-min default (#4253): {missing}"


def test_the_timeout_guard_reds_on_a_job_with_no_ceiling_mutation_control():
    """Mutation control: strip one real job's `timeout-minutes` and the guard must name it;
    a reusable-workflow caller without the key must NOT be named."""
    with open(os.path.join(cjt.WORKFLOW_DIR, "ci-lint.yml"), encoding="utf-8") as fh:
        real = fh.read()
    assert "    timeout-minutes:" in real
    mutated = "\n".join(ln for ln in real.split("\n") if not ln.startswith("    timeout-minutes:"))
    with tempfile.TemporaryDirectory() as d:
        _write_workflow(d, "ci-lint.yml", mutated)
        _write_workflow(d, "caller.yml", "on: push\njobs:\n  lint:\n    uses: ./.github/workflows/ci-lint.yml\n")
        assert _jobs_without_timeout(d, ("ci-lint.yml", "caller.yml")) == [("ci-lint.yml", "lint")]
        _write_workflow(d, "ci-lint.yml", real)
        assert _jobs_without_timeout(d, ("ci-lint.yml", "caller.yml")) == []


def test_every_configure_aws_credentials_pin_is_one_sha():
    """The composite (`.github/actions/setup-ci`) and the hand-rolled OIDC blocks drifted
    apart (v6.2.2 vs v6.3.0) because Dependabot's `/` directory never reached the composite
    (#4253). One SHA across `.github/`, composite included."""
    pins = _oidc_pins(os.path.join(_REPO, ".github"))
    composite = [s for s, paths in pins.items() if any(p.startswith(os.path.join("actions", "setup-ci")) for p in paths)]
    assert composite, "the setup-ci composite no longer pins configure-aws-credentials — the guard lost its anchor"
    assert len(pins) == 1, f"configure-aws-credentials pinned at more than one SHA: {pins}"


def test_the_pin_guard_sees_a_drifted_call_site_mutation_control():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "actions", "setup-ci"))
        os.makedirs(os.path.join(d, "workflows"))
        step = "      - uses: aws-actions/configure-aws-credentials@{} # vX\n"
        with open(os.path.join(d, "actions", "setup-ci", "action.yml"), "w") as fh:
            fh.write(step.format("a" * 40))
        with open(os.path.join(d, "workflows", "x.yml"), "w") as fh:
            fh.write(step.format("b" * 40))
        assert len(_oidc_pins(d)) == 2
        with open(os.path.join(d, "workflows", "x.yml"), "w") as fh:
            fh.write(step.format("a" * 40))
        assert len(_oidc_pins(d)) == 1
