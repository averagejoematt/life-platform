"""tests/test_check_job_timeout_headroom_3678.py — #3678 acceptance box 2: the
`timeout-minutes` derivation guard.

`scripts/check_job_timeout_headroom.py` enumerates every job with `timeout-minutes`
across `.github/workflows/*.yml` (via `ci_job_timeouts.py` — never one hard-coded
job) and reds when a job's own ceiling sits below its measured p95 x the stated
headroom multiplier.

THE MUST-FAIL PROOF (the positive control this issue's own hard requirements ask
for): `test_reds_on_todays_stale_15_minute_ceiling_positive_control` feeds this
module SYNTHETIC durations shaped exactly like the real trailing-30-run
measurement taken live 2026-09-07 (`python3 scripts/check_job_timeout_headroom.py
--job "Collect + deploy-critical + format"` against the THEN-unchanged
`pr-checks.yml`, genuine p95 = 14.87min, n=21/28) against the ORIGINAL
`timeout-minutes: 15` and asserts RED — watched fail before `pr-checks.yml`'s
ceiling was raised in this same PR. Its twin then re-runs the identical samples
against the RAISED 18-minute ceiling and asserts OK, so the guard is proven to
distinguish the two states, not just to always say RED or always say OK.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_job_timeout_headroom as cjth  # noqa: E402


def _entry(name="Collect + deploy-critical + format", file_="pr-checks.yml", timeout_minutes=15, templated=False):
    return {"job_name": name, "file": file_, "timeout_minutes": timeout_minutes, "templated": templated}


# ── percentile — pure, offline ──────────────────────────────────────────────


def test_percentile_p95_of_a_known_series():
    # 0..99 -> p95 (linear method) is 94.05
    vals = list(range(100))
    assert cjth.percentile(vals, 95) == 94.05


def test_percentile_single_value():
    assert cjth.percentile([42.0], 95) == 42.0


def test_percentile_empty_is_none():
    assert cjth.percentile([], 95) is None


# ── genuine_durations — the censored-sample exclusion (#3678) ──────────────


def test_genuine_durations_excludes_cancelled_job_conclusions():
    samples = [
        ("success", "success", 800.0),
        ("cancelled", "cancelled", 900.0),  # censored by the ceiling itself — excluded
        ("failure", "failure", 850.0),  # a REAL completion, even though it failed content-wise
        ("success", "success", None),  # unparseable timestamp — excluded regardless
    ]
    assert cjth.genuine_durations(samples) == [800.0, 850.0]


# ── evaluate_job — the core derivation, pure ────────────────────────────────


def test_evaluate_job_templated_is_skipped_not_asserted():
    rep = cjth.evaluate_job(_entry(templated=True), [])
    assert rep["status"] == "SKIPPED-TEMPLATED"


def test_evaluate_job_insufficient_data_below_the_min_sample_floor():
    samples = [("success", "success", 100.0)] * (cjth.MIN_GENUINE_SAMPLES - 1)
    rep = cjth.evaluate_job(_entry(), samples)
    assert rep["status"] == "INSUFFICIENT-DATA"


def test_evaluate_job_reds_when_ceiling_sits_below_p95_times_headroom():
    # All samples at 850s (14.17min). p95=850s=14.17min * 1.2 = 17.0min required; ceiling 15 < 17.0 -> RED.
    samples = [("success", "success", 850.0)] * cjth.MIN_GENUINE_SAMPLES
    rep = cjth.evaluate_job(_entry(timeout_minutes=15), samples)
    assert rep["status"] == "RED"


def test_evaluate_job_ok_when_ceiling_clears_p95_times_headroom():
    samples = [("success", "success", 850.0)] * cjth.MIN_GENUINE_SAMPLES
    rep = cjth.evaluate_job(_entry(timeout_minutes=20), samples)
    assert rep["status"] == "OK"


# ── measure_job_durations — pure by injection ───────────────────────────────


def test_measure_job_durations_filters_to_the_named_job_and_completed_runs():
    def run_lister(workflow_file, window):
        assert workflow_file == "pr-checks.yml"
        assert window == 30
        return [
            {"databaseId": 1, "conclusion": "success", "status": "completed"},
            {"databaseId": 2, "conclusion": "success", "status": "in_progress"},  # not completed -> skipped
        ]

    def jobs_fetcher(run_id):
        if run_id == 1:
            return [
                {
                    "name": "Collect + deploy-critical + format",
                    "conclusion": "success",
                    "started_at": "2026-09-07T18:00:00Z",
                    "completed_at": "2026-09-07T18:14:00Z",
                },
                {
                    "name": "some other job",
                    "conclusion": "success",
                    "started_at": "2026-09-07T18:00:00Z",
                    "completed_at": "2026-09-07T18:01:00Z",
                },
            ]
        return None

    samples = cjth.measure_job_durations("pr-checks.yml", "Collect + deploy-critical + format", 30, run_lister, jobs_fetcher)
    assert samples == [("success", "success", 840.0)]


# ── run_checks / main — the enumerate-measure-evaluate integration ─────────


def _write_pr_checks_fixture(dirpath, timeout_minutes):
    with open(os.path.join(dirpath, "pr-checks.yml"), "w", encoding="utf-8") as fh:
        fh.write(f"""
name: PR checks
on: pull_request
jobs:
  fast-lane:
    name: Collect + deploy-critical + format
    runs-on: ubuntu-latest
    timeout-minutes: {timeout_minutes}
    steps:
      - run: echo hi
""")


def _synthetic_2026_09_07_samples():
    """Shaped like the real live measurement: mostly genuine completions in the
    583s-900s band (min from the real sample was 583s, max genuine was exactly
    900s), plus a handful of `cancelled` (censored, excluded) near the ceiling —
    same shape `python3 scripts/check_job_timeout_headroom.py --job "Collect +
    deploy-critical + format"` printed live on 2026-09-07: p95=14.87min, n=21/28.
    """
    genuine = [583, 680, 707, 718, 724, 776, 837, 844, 852, 853, 858, 858, 873, 874, 877, 878, 882, 883, 884, 884, 900]
    censored = [901, 903, 905, 908, 922, 938, 940]
    samples = [("success", "success", float(d)) for d in genuine] + [("cancelled", "cancelled", float(d)) for d in censored]
    return samples


def _seconds_to_gh_timestamp(base_seconds_from_epoch_marker, delta_seconds):
    """A `%Y-%m-%dT%H:%M:%SZ` timestamp `delta_seconds` after a fixed base — lets
    a test hand `measure_job_durations` an EXACT duration without hand-computing
    HH:MM:SS wraparound."""
    from datetime import datetime, timedelta

    base = datetime(2026, 9, 7, 18, 0, 0)
    return (base + timedelta(seconds=base_seconds_from_epoch_marker + delta_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _synthetic_run_lister_and_jobs_fetcher(samples, job_name):
    """(run_lister, jobs_fetcher) that reproduce exactly `samples` through the
    real `measure_job_durations` — one fabricated run per sample, so the
    integration path (`run_checks`/`main`) sees the SAME population the direct
    `evaluate_job` tests above do."""
    runs = [{"databaseId": i, "conclusion": run_c, "status": "completed"} for i, (run_c, _job_c, _d) in enumerate(samples)]

    def run_lister(_workflow_file, _window):
        return runs

    def jobs_fetcher(run_id):
        _run_c, job_c, dur = samples[run_id]
        if dur is None:
            return [{"name": job_name, "conclusion": job_c, "started_at": None, "completed_at": None}]
        started = _seconds_to_gh_timestamp(0, 0)
        completed = _seconds_to_gh_timestamp(0, dur)
        return [{"name": job_name, "conclusion": job_c, "started_at": started, "completed_at": completed}]

    return run_lister, jobs_fetcher


def test_reds_on_todays_stale_15_minute_ceiling_positive_control():
    """MUST-FAIL PROOF (#3678 hard requirement): today's config (15m against this
    measured p95) must RED, through the real `run_checks` integration path
    (enumerate the fixture workflow -> measure via injected gh I/O -> evaluate).
    This is the exact synthetic shape of the live 2026-09-07 measurement — see
    `_synthetic_2026_09_07_samples`'s docstring above."""
    job_name = "Collect + deploy-critical + format"
    with tempfile.TemporaryDirectory() as d:
        _write_pr_checks_fixture(d, timeout_minutes=15)
        samples = _synthetic_2026_09_07_samples()
        run_lister, jobs_fetcher = _synthetic_run_lister_and_jobs_fetcher(samples, job_name)
        reports = cjth.run_checks(workflow_dir=d, run_lister=run_lister, jobs_fetcher=jobs_fetcher)
        assert len(reports) == 1
        rep = reports[0]
        assert rep["status"] == "RED", rep
        assert rep["timeout_minutes"] == 15
        assert 14.5 < rep["p95_minutes"] < 15.0, rep


def test_ok_on_the_re_derived_18_minute_ceiling_negative_control():
    """The SAME synthetic samples against the RAISED ceiling this PR ships
    (18min) must clear through the same `run_checks` path — proving the guard
    actually distinguishes the two states rather than always reporting one
    answer."""
    job_name = "Collect + deploy-critical + format"
    with tempfile.TemporaryDirectory() as d:
        _write_pr_checks_fixture(d, timeout_minutes=18)
        samples = _synthetic_2026_09_07_samples()
        run_lister, jobs_fetcher = _synthetic_run_lister_and_jobs_fetcher(samples, job_name)
        reports = cjth.run_checks(workflow_dir=d, run_lister=run_lister, jobs_fetcher=jobs_fetcher)
        assert reports[0]["status"] == "OK", reports[0]
        assert reports[0]["timeout_minutes"] == 18


def test_main_returns_1_and_prints_red_for_the_stale_config(capsys, monkeypatch):
    """Same proof, exercised through `main()` end-to-end — the actual entry
    point a driver invokes, not just `run_checks`."""
    job_name = "Collect + deploy-critical + format"
    with tempfile.TemporaryDirectory() as d:
        _write_pr_checks_fixture(d, timeout_minutes=15)
        samples = _synthetic_2026_09_07_samples()
        run_lister, jobs_fetcher = _synthetic_run_lister_and_jobs_fetcher(samples, job_name)
        monkeypatch.setattr(cjth, "_gh_run_lister", run_lister)
        monkeypatch.setattr(cjth, "_gh_jobs_fetcher", jobs_fetcher)
        monkeypatch.setattr(cjth.ci_job_timeouts, "WORKFLOW_DIR", d)
        # The fixture workflow deliberately declares only ONE job (the fast-lane
        # under test) — lower the population floor so this test exercises the
        # RED path, not the (separately tested) population-floor guard.
        monkeypatch.setattr(cjth, "JOB_TIMEOUT_FLOOR", 1)
        rc = cjth.main([])
        out = capsys.readouterr().out
        assert rc == 1
        assert "RED" in out


def test_population_floor_breach_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(cjth.ci_job_timeouts, "iter_job_timeouts", lambda workflow_dir=None: [])
    rc = cjth.main([])
    assert rc == 1


def test_a_job_that_cannot_be_measured_is_reported_unverified_never_red(monkeypatch):
    def _raise(*_a, **_kw):
        raise RuntimeError("gh: not authenticated")

    entries = [{"job_name": "Some job", "file": "x.yml", "timeout_minutes": 10, "templated": False}]
    monkeypatch.setattr(cjth.ci_job_timeouts, "iter_job_timeouts", lambda workflow_dir=None: entries)
    reports = cjth.run_checks(run_lister=_raise, jobs_fetcher=lambda rid: None)
    assert reports[0]["status"] == "UNVERIFIED"
