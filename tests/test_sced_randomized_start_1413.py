"""tests/test_sced_randomized_start_1413.py — SCED discipline: the randomized start (#1413, epic #1365).

Single-case experimental design (SCED) brings two things the n-of-1 pipeline lacked:

  1. A create_experiment mode that DRAWS the intervention start at random from a
     pre-declared 7-14 day window (frozen in the prereg spec — no post-hoc edits).
     A hand-picked start correlates with how the subject already feels; a drawn one
     cannot, so coincident trends stop masquerading as effects.
  2. A start-point randomization (permutation) test in the verdict engine: the
     observed pre/post mean difference is ranked against the same statistic at every
     start the window could have produced. Valid under autocorrelation — the
     inference comes from the randomization actually performed, not an i.i.d.
     assumption a daily physiological series never satisfies (ADR-105).

All fixture dates are pinned far in the FUTURE (2050) because the must-be-future
window check compares against the real creation date — see
reference_golden_tests_wallclock (a near-future date is a time bomb).
"""

import json
import os
import random
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

import experiment_design as ed  # noqa: E402
import stats_core  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_lifestyle as tl  # noqa: E402

STOP = "run the full 21 days regardless of interim trend; abort only if recovery < 40% for 3 consecutive days"


def _design(**over):
    d = {
        "baseline_days": 7,
        "washout_days": 0,
        "stopping_rule": STOP,
        "criterion": {"metric": "steps", "direction": "higher", "min_effect": 100},
        "randomized_start": {"window_start": "2050-01-08", "window_end": "2050-01-14"},
    }
    d.update(over)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# The permutation core (stats_core) — pinned against HAND-COMPUTED randomization
# distributions, per the acceptance criterion.
# ══════════════════════════════════════════════════════════════════════════════


class TestStartPointRandomizationTest:
    def test_step_series_known_distribution(self):
        # values:      [0, 0, 0, 0, 10, 10, 10, 10]
        # candidates:   k=2..6 → T(k) = mean(values[k:]) - mean(values[:k])
        #   T(2)=20/3  T(3)=8  T(4)=10  T(5)=8  T(6)=20/3
        # observed T(4)=10 is the strict maximum → one-sided p = 1/5.
        r = stats_core.start_point_randomization_test([0, 0, 0, 0, 10, 10, 10, 10], [2, 3, 4, 5, 6], 4, direction="higher", min_per_arm=2)
        assert r["p_value"] == 0.2
        assert r["observed_stat"] == 10.0
        assert r["n_candidates"] == 5 and r["n_used"] == 5 and r["n_excluded"] == 0
        assert r["min_p"] == 0.2

    def test_pure_linear_trend_is_never_credited(self):
        # The SCED rationale in one line: on a pure pre-existing trend every candidate
        # start "shows an effect" of identical size — T(k) = 5 for ALL k on 1..10 —
        # so the observed split is not extreme at all: p = 1.0.
        r = stats_core.start_point_randomization_test(list(range(1, 11)), [3, 4, 5, 6, 7], 5, direction="higher", min_per_arm=2)
        assert r["p_value"] == 1.0
        assert r["observed_stat"] == 5.0

    def test_lower_direction(self):
        # [10,10,10,0,0,0], candidates 2/3/4: T(2)=-7.5, T(3)=-10, T(4)=-7.5.
        # Predicted LOWER, observed T(3)=-10 strict minimum → p = 1/3.
        r = stats_core.start_point_randomization_test([10, 10, 10, 0, 0, 0], [2, 3, 4], 3, direction="lower", min_per_arm=2)
        assert r["p_value"] == round(1 / 3, 4)
        assert r["observed_stat"] == -10.0

    def test_washout_excluded_and_thin_candidates_dropped(self):
        # washout=1: post arm at k is values[k+1:]. Candidate 6's post arm has a
        # single point (< min_per_arm 2) → excluded, honestly counted.
        r = stats_core.start_point_randomization_test(
            [0, 0, 0, 0, 10, 10, 10, 10], [2, 4, 6], 4, direction="higher", washout=1, min_per_arm=2
        )
        assert r["n_candidates"] == 3 and r["n_used"] == 2 and r["n_excluded"] == 1
        # T(2)=mean(values[3:])-0=8; T(4)=mean(values[5:])-0=10 → observed max → p=1/2
        assert r["p_value"] == 0.5

    def test_none_gaps_are_skipped(self):
        r = stats_core.start_point_randomization_test([0, None, 0, 0, 10, None, 10, 10], [2, 3, 4], 4, direction="higher", min_per_arm=2)
        assert r is not None
        assert r["observed_stat"] == 10.0  # pre [0,0,0] → 0, post [10,10,10] → 10

    def test_degenerate_inputs_return_none(self):
        # actual start not among the declared candidates
        assert stats_core.start_point_randomization_test([1, 2, 3, 4], [2], 3, min_per_arm=1) is None
        # actual candidate itself has a thin arm
        assert stats_core.start_point_randomization_test([1, 2, 3], [1], 1, min_per_arm=5) is None
        # fewer than 2 usable candidates → no distribution to rank against
        assert stats_core.start_point_randomization_test([1, 2, 3, 4], [2, 9], 2, min_per_arm=2) is None
        assert stats_core.start_point_randomization_test([], [2, 3], 2) is None
        assert stats_core.start_point_randomization_test([1, 2, 3, 4], [1, 2, 3], 2, direction="sideways") is None


# ══════════════════════════════════════════════════════════════════════════════
# Design validation + the draw (experiment_design)
# ══════════════════════════════════════════════════════════════════════════════


class TestRandomizedStartDesign:
    def test_valid_window_accepted(self):
        ok, issues = ed.validate_design(_design())
        assert ok, issues

    def test_window_size_bounds(self):
        # 6 days: too narrow to randomize meaningfully. 15: beyond the declared cap.
        for end in ("2050-01-13", "2050-01-22"):
            ok, issues = ed.validate_design(_design(randomized_start={"window_start": "2050-01-08", "window_end": end}))
            assert not ok and any("randomized_start" in i for i in issues), end

    def test_reversed_and_malformed_windows_rejected(self):
        for bad in (
            {"window_start": "2050-01-14", "window_end": "2050-01-08"},
            {"window_start": "not-a-date", "window_end": "2050-01-14"},
            {"window_start": "2050-01-08"},
            {"window_start": "2050-01-08", "window_end": "2050-01-14", "extra": 1},
            "2050-01-08..2050-01-14",
        ):
            ok, issues = ed.validate_design(_design(randomized_start=bad))
            assert not ok and any("randomized_start" in i for i in issues), bad

    def test_draw_is_uniform_over_window_and_carries_provenance(self):
        rs = {"window_start": "2050-01-08", "window_end": "2050-01-14"}
        dates = ed.candidate_start_dates(rs)
        assert dates[0] == "2050-01-08" and dates[-1] == "2050-01-14" and len(dates) == 7
        drawn, prov = ed.draw_start_date(rs, rng=random.Random(42))
        assert drawn in dates
        assert prov["n_candidates"] == 7
        assert prov["window_start"] == "2050-01-08" and prov["window_end"] == "2050-01-14"
        assert dates[prov["drawn_index"]] == drawn
        assert prov["method"] == "uniform_random"
        # deterministic under an injected rng (the production draw uses SystemRandom)
        assert ed.draw_start_date(rs, rng=random.Random(42))[0] == drawn

    def test_window_must_not_predate_registration(self):
        # Pure check with an EXPLICIT today (wallclock-safe): a window already begun
        # at registration time is post-hoc, not pre-declared.
        rs = {"window_start": "2050-01-08", "window_end": "2050-01-14"}
        ok, _ = ed.validate_start_window_not_past(rs, today="2050-01-08")
        assert ok
        ok, issue = ed.validate_start_window_not_past(rs, today="2050-01-09")
        assert not ok and "window" in issue


class TestRandomizationTestOrchestration:
    def test_dated_series_known_p(self):
        # Window 2050-01-08..14 (7 candidates), actual drawn start 2050-01-11,
        # baseline_days=7 → series spans 2050-01-01..2050-01-24. Values step
        # 1000 → 2000 exactly at the actual start → observed stat is the strict
        # max of the randomization distribution → p = 1/7.
        d = _design()
        values = {}
        for day in range(1, 25):
            date = f"2050-01-{day:02d}"
            values[date] = 1000.0 if day < 11 else 2000.0
        r = ed.randomization_test(d, values, "2050-01-11", "2050-01-24")
        assert r["p_value"] == round(1 / 7, 4)
        assert r["observed_stat"] == 1000.0
        assert r["n_candidates"] == 7 and r["n_used"] == 7
        assert r["window_start"] == "2050-01-08" and r["window_end"] == "2050-01-14"
        assert r["actual_start"] == "2050-01-11"
        assert r["direction"] == "higher"
        assert "randomization" in r["method"].lower() or "randomization" in r.get("engine", "")

    def test_without_randomized_start_returns_none(self):
        d = _design()
        del d["randomized_start"]
        assert ed.randomization_test(d, {"2050-01-01": 1.0}, "2050-01-11", "2050-01-24") is None

    def test_actual_start_outside_window_returns_none(self):
        assert ed.randomization_test(_design(), {"2050-01-01": 1.0}, "2050-01-20", "2050-01-24") is None

    def test_summary_carries_randomization_p(self):
        stats = {
            "n_baseline": 7,
            "n_window": 14,
            "mean_baseline": 1000.0,
            "mean_window": 2000.0,
            "effect_size": 1000.0,
            "ci95_low": 900.0,
            "ci95_high": 1100.0,
            "cohens_d": None,
            "verdict": "supported",
            "randomization": {"p_value": 0.1429, "n_used": 7, "min_p": 0.1429},
        }
        s = ed.analysis_summary(_design(), stats)
        assert "randomization p=0.1429" in s
        assert "7 candidate starts" in s
        assert s.endswith("-> supported.")


# ══════════════════════════════════════════════════════════════════════════════
# create_experiment: the draw happens at creation and is frozen in the prereg
# artifact; a hand-picked start_date is structurally impossible in this mode.
# ══════════════════════════════════════════════════════════════════════════════


class _FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def _create(monkeypatch, args):
    table = FakeDdbTable()
    s3 = _FakeS3()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "s3_client", s3)
    return tl.tool_create_experiment(args), table, s3


class TestCreateExperimentRandomizedStart:
    def test_start_is_drawn_from_window_and_frozen_in_prereg(self, monkeypatch):
        resp, table, s3 = _create(
            monkeypatch,
            {"name": "SCED Test", "hypothesis": "steps rise", "design": _design()},
        )
        dates = ed.candidate_start_dates(_design()["randomized_start"])
        assert resp["start_date"] in dates
        draw = resp["start_draw"]
        assert draw["n_candidates"] == 7 and draw["method"] == "uniform_random"
        assert draw["window_start"] == "2050-01-08" and draw["window_end"] == "2050-01-14"
        assert draw["drawn_at"]  # provenance: when the draw happened
        item = table.puts[0]
        assert item["start_date"] == resp["start_date"]
        assert item["start_draw"]["n_candidates"] == 7
        # The public artifact freezes BOTH the declared window (inside design) and the draw.
        body = json.loads(s3.puts[0]["Body"])
        assert body["design"]["randomized_start"] == {"window_start": "2050-01-08", "window_end": "2050-01-14"}
        assert body["start_draw"]["window_start"] == "2050-01-08"
        assert body["start_date"] == resp["start_date"]

    def test_explicit_start_date_rejected(self, monkeypatch):
        try:
            _create(
                monkeypatch,
                {"name": "SCED Test", "hypothesis": "steps rise", "start_date": "2050-01-09", "design": _design()},
            )
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "start_date" in str(e)

    def test_window_already_begun_rejected(self, monkeypatch):
        past = _design(randomized_start={"window_start": "2020-01-01", "window_end": "2020-01-07"})
        try:
            _create(monkeypatch, {"name": "SCED Test", "hypothesis": "steps rise", "design": past})
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "window" in str(e)


class TestClosePathRandomization:
    def test_run_design_analysis_attaches_randomization(self, monkeypatch):
        d = _design()

        def fake_query_source(source, start, end, **kw):
            assert source == "apple_health"
            items = []
            from datetime import datetime, timedelta

            cur = datetime.strptime(start, "%Y-%m-%d")
            stop = datetime.strptime(end, "%Y-%m-%d")
            while cur <= stop:
                date = cur.strftime("%Y-%m-%d")
                items.append({"sk": f"DATE#{date}", "steps": 1000.0 if date < "2050-01-11" else 2000.0})
                cur += timedelta(days=1)
            return items

        monkeypatch.setattr(tl, "query_source", fake_query_source)
        existing = {"start_date": "2050-01-11", "design": d}
        analysis = tl._run_design_analysis(existing, d, "2050-01-24")
        assert analysis["verdict"] == "supported"
        rand = analysis["randomization"]
        assert rand["p_value"] == round(1 / 7, 4)
        assert rand["n_used"] == 7
        assert "randomization p=" in analysis["summary"]
