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
    assert len(mapping) == len(non_templated)
    for e in non_templated:
        assert mapping[e["job_name"]] == e["timeout_minutes"]


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
