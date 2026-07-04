"""tests/test_scenario_explorer.py — the what-followed precompute (#550, ADR-105).

Pins the pure core: lever matching against day-rows, next-day pairing (what
FOLLOWED, not same-day), the effective-n honesty gate (thin cells hidden, never
padded), distribution summaries + bootstrap diff CIs, determinism, and the
payload's anti-causal framing.
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "compute"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import scenario_explorer_lambda as scn  # noqa: E402


def _rows(n=60, seed=11, sleep_effect=8.0):
    """Synthetic day-rows: recovery the day after a 7.5h+ night is boosted."""
    rng = random.Random(seed)
    rows = {}
    from datetime import date, timedelta

    d0 = date(2026, 4, 1)
    sleeps = []
    for i in range(n):
        s = 6.0 + rng.random() * 3.0  # 6.0-9.0h
        sleeps.append(s)
        prev_sleep = sleeps[i - 1] if i else None
        rec = 55 + rng.gauss(0, 5) + (sleep_effect if (prev_sleep or 0) >= 7.5 else 0)
        rows[(d0 + timedelta(days=i)).isoformat()] = {
            "date": (d0 + timedelta(days=i)).isoformat(),
            "total_sleep_hrs": round(s, 2),
            "recovery": round(rec, 1),
            "steps": 8000 + int(rng.random() * 6000),
        }
    return rows


LEVER_SLEEP = next(lv for lv in scn.LEVERS if lv["slug"] == "sleep_7p5")


class TestSplitNextDay:
    def test_pairs_next_day_not_same_day(self):
        rows = {
            "2026-05-01": {"total_sleep_hrs": 8.0, "recovery": 50},
            "2026-05-02": {"total_sleep_hrs": 6.0, "recovery": 90},
            "2026-05-03": {"total_sleep_hrs": 7.0, "recovery": 40},
        }
        matched, comparison = scn.split_next_day_values(rows, LEVER_SLEEP, "recovery")
        assert matched == [90.0]  # the day AFTER the 8h night
        assert comparison == [40.0]  # the day after the 6h night; 05-03 has no next day

    def test_missing_fields_drop_out(self):
        rows = {
            "2026-05-01": {"recovery": 50},  # no sleep value → not classifiable
            "2026-05-02": {"total_sleep_hrs": 8.0},  # next day missing outcome
            "2026-05-03": {"recovery": 70},
        }
        matched, comparison = scn.split_next_day_values(rows, LEVER_SLEEP, "recovery")
        assert matched == [70.0] and comparison == []


class TestBuildCell:
    def test_thin_arm_hidden(self):
        assert scn.build_cell([70.0] * 5, [60.0] * 20) is None  # matched n < 8
        assert scn.build_cell([70.0 + i for i in range(12)], [60.0] * 5) is None  # comparison thin

    def test_effective_n_gate(self):
        # 10 raw points but near-perfect autocorrelation → n_eff collapses → hidden
        sticky = [70.0, 70.1, 70.2, 70.3, 70.4, 70.5, 70.6, 70.7, 70.8, 70.9]
        assert scn.build_cell(sticky, [60.0 + i * 0.5 for i in range(20)]) is None

    def test_cell_shape_and_ci(self):
        rng = random.Random(5)
        matched = [70 + rng.gauss(0, 4) for _ in range(25)]
        comparison = [60 + rng.gauss(0, 4) for _ in range(40)]
        c = scn.build_cell(matched, comparison)
        assert c is not None
        assert c["p25"] <= c["median"] <= c["p75"]
        assert c["n"] == 25 and c["n_comparison"] == 40
        assert c["n_eff"] <= 25
        assert c["diff"] > 5
        assert c["diff_ci95"][0] < c["diff"] < c["diff_ci95"][1]
        assert c["ci_excludes_zero"] is True

    def test_deterministic(self):
        rng = random.Random(6)
        m = [70 + rng.gauss(0, 4) for _ in range(20)]
        cp = [60 + rng.gauss(0, 4) for _ in range(30)]
        assert scn.build_cell(m, cp) == scn.build_cell(list(m), list(cp))


class TestBuildPayload:
    def test_payload_shape_and_framing(self):
        payload = scn.build_payload(_rows(), "2026-07-04")
        assert payload["record_type"] == "scenario_summary"
        assert "never causal" in payload["framing"]
        by_slug = {lv["slug"]: lv for lv in payload["levers"]}
        assert set(by_slug) == {lv["slug"] for lv in scn.LEVERS}
        sleep = by_slug["sleep_7p5"]
        assert sleep["n_matched_days"] > 10
        rec = sleep["outcomes"].get("recovery")
        assert rec is not None
        assert rec["diff"] > 4  # the planted effect shows up
        # levers with no data in the synthetic rows carry empty outcomes, not fakes
        assert by_slug["protein_150"]["outcomes"] == {}
        assert payload["cells_hidden_thin"] > 0

    def test_quantile(self):
        assert scn._quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
        assert scn._quantile([1.0, 2.0, 3.0, 4.0], 0.25) == 1.75
        assert scn._quantile([7.0], 0.75) == 7.0
