"""#6156 — the forecast's frozen scoring rule and the walk-forward backtest behind it (owner ruling 2026-11-22 §5).

* THE BACKTEST (``scripts/public_forecast_backtest.py``) never hands the rule a reading on or after the filing day:
  every reading from the filing day on is replaced by an absurd value and every forecast, guess and band is unchanged;
  the outcome is the reading the grader would read (never one on or before the filing day); it reads only the public
  ``/api/series`` route and creates no AWS client; the summary counts what it says it counts.
* THE RULE (``closer_than_nothing_changes`` v1) is graded by the ONE grader only for a spec that carries it: the
  forecast is confirmed iff STRICTLY closer to the reading than the frozen guess (a tie is the guess's), and the
  "nothing changes" stamp is exactly its complement. A coach's number call — a spec without ``scoring`` — grades
  byte-for-byte as before, through both the point grader and the baseline verdict.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import public_forecast_backtest as BT  # noqa: E402
from coach import coach_baseline, prediction_point_grader as PG, public_forecast as F  # noqa: E402
from common import public_forecast_policy as FP  # noqa: E402

GENESIS = "2026-09-06"
END = "2026-11-20"


def _series(metric="weight_lbs", start=GENESIS, end=END, f=lambda i: 315.0 - 0.45 * i + (0.6 if i % 3 else -0.7)):
    s, e = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
    days, i = [], 0
    while s <= e:
        days.append({"date": s.strftime("%Y-%m-%d"), "value": round(f(i), 2), "present": True, "gap": False})
        s += timedelta(days=1)
        i += 1
    return {"metric": metric, "unit": "lb", "source_id": "withings", "as_of": end, "days": days}


# ── the backtest: no future leakage ────────────────────────────────────────────────────────────────────


def test_no_reading_on_or_after_the_filing_day_reaches_the_rule():
    payload = _series()
    weeks = [w for w in BT.walk("weight_trend", payload, "2026-09-20", GENESIS) if not w.get("held")]
    assert len(weeks) >= 6
    for w in weeks:
        poisoned = {
            **payload,
            "days": [dict(d, value=999.0) if d["date"] >= w["filed"] else d for d in payload["days"]],
        }
        again = next(x for x in BT.walk("weight_trend", poisoned, w["filed"], GENESIS) if x["filed"] == w["filed"])
        for k in ("forecast", "guess", "band", "inputs_last", "target"):
            assert again[k] == w[k], (w["filed"], k)
        assert w["inputs_last"] < w["filed"]


def test_cut_before_keeps_only_days_before_the_filing_day_and_inside_the_cycle():
    payload = _series(start="2026-08-20")
    cut = BT.cut_before(payload, "2026-10-05", GENESIS)
    days = [d["date"] for d in cut["days"]]
    assert days[0] == GENESIS and days[-1] == "2026-10-04" and cut["as_of"] == "2026-10-04"


def test_the_outcome_is_the_graders_reading_never_one_on_or_before_the_filing_day():
    r = [("2026-10-10", 1.0), ("2026-10-12", 2.0), ("2026-10-16", 3.0)]
    assert BT.outcome(r, "2026-10-17", "2026-10-10") == (3.0, "2026-10-16")  # within the grace before the target
    assert BT.outcome(r, "2026-10-19", "2026-10-12") == (None, None)  # 16th is three days back: outside the grace
    assert BT.outcome(r, "2026-10-12", "2026-10-11") == (2.0, "2026-10-12")
    assert BT.outcome(r, "2026-10-11", "2026-10-10") == (None, None), "the filing day's own reading never settles a call"


def test_the_filing_days_are_mondays_whose_target_has_been_reached():
    days = BT.filing_days("2026-09-20", "2026-10-12")
    assert days == ["2026-09-21", "2026-09-28", "2026-10-05"]
    assert all(datetime.strptime(d, "%Y-%m-%d").weekday() == 0 for d in days)


def test_the_summary_counts_what_it_says():
    weeks = [
        {"filed": "a", "forecast": 10.0, "guess": 14.5, "band": 3.0, "actual": 11.0},  # rule in, guess out, rule closer
        {"filed": "b", "forecast": 10.0, "guess": 12.0, "band": 3.0, "actual": 11.0},  # both in, tie -> guess
        {"filed": "c", "forecast": 10.0, "guess": 30.0, "band": 1.0, "actual": 20.0},  # both out, tie -> guess
        {"filed": "d", "held": "too_few_readings"},
    ]
    s = BT.summarise(weeks)
    assert (s["n"], s["held"], s["filing_days"]) == (3, 1, 4)
    assert (s["sd_confirmed_rule"], s["sd_confirmed_no_change"], s["sd_both_confirmed"], s["sd_both_refuted"]) == (2, 1, 1, 1)
    assert s["sd_not_distinguished"] == 2 and s["h2h_rule_closer"] == 1 and s["h2h_no_change_as_close_or_closer"] == 2
    assert s["mae_rule"] == pytest.approx((1 + 1 + 10) / 3, abs=1e-3) and s["mae_no_change"] == pytest.approx((3.5 + 1 + 10) / 3, abs=1e-3)


def test_the_backtest_reads_only_the_public_series_route_and_creates_no_aws_client(monkeypatch):
    import boto3

    def no_aws(*a, **k):
        raise AssertionError("the backtest must not create an AWS client")

    monkeypatch.setattr(boto3, "client", no_aws)
    monkeypatch.setattr(boto3, "resource", no_aws)
    urls = []

    def fetch(url):
        urls.append(url)
        metric = url.split("metric=")[1].split("&")[0]
        return _series(metric)

    out = BT.run(fetch, end=END)
    assert set(out) == set(F.RULES) and all(u.startswith(F.PUBLIC_BASE + F.ROUTE + "?metric=") for u in urls)
    assert len(urls) == len(F.RULES), "one GET per metric"
    assert out["weight_trend"]["summary"]["n"] >= 6
    text = BT.render(out, ("2026-09-21", "2026-11-09"))
    assert "head-to-head (frozen)" in text and "%" not in text, "counts only: every n is below the rate floor (ADR-104)"


# ── the frozen rule, in the one grader, for this partition only ────────────────────────────────────────

H2H = {
    "type": "point",
    "metric": "weight_lbs",
    "threshold": 290.0,
    "target_date": "2026-11-30",
    "scoring": FP.SCORING_RULE,
    "scoring_version": 1,
    "baseline_value": 294.0,
    "baseline_on": "2026-11-22",
}


def _grade(spec, actual):
    def get_source_data(source, cache, end, lookback_days=60):
        return [{"date": "2026-11-30", "v": actual}]

    def extract(records, base):
        return [(r["date"], r["v"]) for r in records]

    return PG.evaluate_point(
        {"created_date": "2026-11-23"}, spec, {}, "2026-12-01", get_source_data=get_source_data, extract_metric_series=extract
    )


@pytest.mark.parametrize(
    "actual,status",
    [(289.0, "confirmed"), (291.9, "confirmed"), (292.0, "refuted"), (292.1, "refuted"), (296.0, "refuted"), (284.0, "confirmed")],
)
def test_the_forecast_is_right_only_when_strictly_closer_than_the_guess(actual, status):
    out = _grade(H2H, actual)
    assert out["status"] == status and out["beats_null"] is (status == "confirmed")
    right, why = coach_baseline.verdict("number", H2H, actual=actual, filed_value=123.0, noise_band=0.0)
    assert why is None and right is (status == "refuted"), "the guess's stamp is the complement, from the FROZEN guess value"


def test_the_literal_the_grader_reads_is_the_policys_rule():
    assert PG.HEAD_TO_HEAD == FP.SCORING_RULE and FP.is_head_to_head(H2H) and not FP.is_head_to_head({"type": "point"})


def test_a_coach_number_call_is_graded_exactly_as_before():
    """A spec without ``scoring`` (every coach call, every historical row) takes the unchanged ±tolerance path."""
    coach = {
        "type": "point",
        "metric": "weight_lbs",
        "threshold": 290.0,
        "tolerance": 1.5,
        "tolerance_rule": "±1 SD",
        "target_date": "2026-11-30",
    }
    for actual, status in ((291.5, "confirmed"), (291.6, "refuted"), (288.5, "confirmed"), (293.9, "refuted")):
        out = _grade(coach, actual)
        assert out["status"] == status and "tolerance" in out["reason"]
        right, _why = coach_baseline.verdict("number", coach, actual=actual, filed_value=292.0, noise_band=0.0)
        assert right is (abs(actual - 292.0) <= 1.5)
    assert _grade({k: v for k, v in coach.items() if k != "tolerance"}, 290.0) is None, "a tolerance-less coach spec is still malformed"
    assert _grade({k: v for k, v in H2H.items() if k != "baseline_value"}, 290.0) is None, "a head-to-head spec needs its frozen guess"
