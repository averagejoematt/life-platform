"""tests/test_wrong_obituary_specimens_4218.py — /method/'s Wrong Feed cards say what was measured.

#4218 (epic #4182): `_wrong_obituary` printed a directional call's EWMA slope as the
measured value ("recovery score measured 0.08"), dropped a point call's tolerance band
("the call was within 52.9"), and served the evaluator's raw reason string verbatim as
"what changed" (the page uppercases it: "RECOVERY_SCORE=73.00 ON 2026-09-13 VS …").

Fixtures are the live `/api/wrong` rows read 2026-09-26 (the distinct reason strings of
that day's 39 obituaries), rebuilt into the LEARNING# record shape the evaluator writes.
"""

import os
import re
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_foresight as fs  # noqa: E402

# (date, coach, evaluator reason) — verbatim from /api/wrong obituaries[].what_changed, 2026-09-26.
LIVE_2026_09_26 = [
    (
        "2026-09-26",
        "sleep",
        "recovery_score=73.00 on 2026-09-13 vs predicted 52.9 ±18.2532 (±1 SD of the trailing 30-day personal series "
        "(n=31 readings, SD=18.2532)); |Δ|=20.10 → outside tolerance",
    ),
    ("2026-09-26", "nutrition", "recovery_score trend=up (slope=0.0778), predicted=down"),
    ("2026-09-26", "nutrition", "total_protein_g trend=up (slope=0.0314), predicted=down"),
    ("2026-09-26", "explorer", "dispute docket resolved: total_calories_kcal_7day_avg >= 2200 on 2026-08-10"),
    ("2026-09-25", "nutrition", "total_calories_kcal trend=up (slope=0.0859), predicted=down"),
    (
        "2026-09-24",
        "sleep",
        "recovery_score=24.00 on 2026-09-11 vs predicted 66.2 ±17.9488 (±1 SD of the trailing 30-day personal series "
        "(n=31 readings, SD=17.9488)); |Δ|=42.20 → outside tolerance",
    ),
    ("2026-09-24", "sleep", "sleep_duration_hours trend=up (slope=0.0247), predicted=down"),
    ("2026-09-24", "nutrition", "recovery_score trend=up (slope=0.1439), predicted=down"),
    ("2026-09-20", "sleep", "predicted up, metric flat (slope=-0.0180, within ±0.02 noise band) — no movement to confirm the call"),
    (
        "2026-09-19",
        "sleep",
        "sleep_duration_hours=8.98 on 2026-09-13 vs predicted 7.2 ±1.2395 (±1 SD of the trailing 30-day personal series "
        "(n=31 readings, SD=1.2395)); |Δ|=1.78 → outside tolerance",
    ),
    (
        "2026-09-17",
        "sleep",
        "sleep_duration_hours=4.70 on 2026-09-11 vs predicted 7.1 ±1.1708 (±1 SD of the trailing 30-day personal series "
        "(n=31 readings, SD=1.1708)); |Δ|=2.40 → outside tolerance",
    ),
]


def _record(date, coach, reason, *, with_type=True):
    """Rebuild the LEARNING# row the evaluator wrote for a live reason string."""
    rec = {"date": date, "coach_id": coach, "prediction_id": f"{coach}-{date}-{abs(hash(reason)) % 10**6}", "status": "refuted"}
    rec["reason"] = reason
    if m := re.match(r"^(\w+)=([\d.]+) on \S+ vs predicted ([\d.]+) ", reason):
        rec.update(evaluation_type="point", metric=m.group(1), condition="within")
        rec.update(actual_value=Decimal(m.group(2)), threshold=Decimal(m.group(3)))
    elif m := re.match(r"^(\w+) trend=(\w+) \(slope=([-\d.]+)\), predicted=(\w+)$", reason):
        rec.update(evaluation_type="directional", metric=m.group(1), condition=m.group(4), actual_value=Decimal(m.group(3)))
    elif m := re.match(r"^predicted (\w+), metric flat \(slope=([-\d.]+)", reason):
        rec.update(evaluation_type="directional", metric="sleep_duration_hours", condition=m.group(1), actual_value=Decimal(m.group(2)))
    elif reason.startswith("dispute docket"):
        rec.update(evaluation_type="machine", metric="total_calories_kcal_7day_avg", condition="gte", threshold=Decimal("2200"))
    else:  # pragma: no cover — a fixture row this parser does not know is a fixture bug
        raise AssertionError(reason)
    if not with_type:
        rec.pop("evaluation_type")
    return rec


# What a reader must never see on a card: evaluator vocabulary, and a metric id
# (lower- OR upper-snake — the page uppercases the "what changed" line).
_LEAK = re.compile(r"trend=|slope=|predicted=|\|Δ\||\b[A-Za-z]+_[A-Za-z0-9_]+\b")


def _served(card):
    return [card["believed"], card["number"], card["what_changed"]]


class TestSpecimens:
    def test_trend_miss_names_a_direction_not_a_measured_slope(self):
        """RED pre-#4218: number == 'recovery score measured 0.08' (the slope as a score)."""
        o = fs._wrong_obituary("nutrition", _record(*LIVE_2026_09_26[1]))
        assert o["believed"] == "recovery score would trend down"
        assert o["number"] == (
            "measured rising: the smoothed average of recovery score rose 7.8% across its last 7 readings — the call was falling"
        )
        assert "measured 0.0" not in o["number"]
        assert o["what_changed"] == "The trend ran up, the opposite of the call, so it was graded refuted."

    def test_flat_trend_miss_states_the_noise_band(self):
        o = fs._wrong_obituary("sleep", _record(*LIVE_2026_09_26[8]))
        assert o["believed"] == "sleep duration would trend up"
        assert o["number"].startswith("measured flat: ")
        assert "inside the ±2% noise band — the call was rising" in o["number"]
        assert "measured -0.02" not in o["number"]

    def test_interval_miss_states_its_band(self):
        """RED pre-#4218: 'recovery score measured 73 — the call was within 52.9' (no band)."""
        o = fs._wrong_obituary("sleep", _record(*LIVE_2026_09_26[0]))
        band = "±18.3 (one standard deviation of his last 30 days)"
        assert o["believed"] == f"recovery score would come in at 52.9 {band}"
        assert o["number"] == f"recovery score measured 73.0 on September 13 — the call was 52.9 {band}"
        assert o["what_changed"] == "It landed 20.1 from the call, outside the ±18.3 band."

    def test_interval_miss_carries_the_metric_unit(self):
        o = fs._wrong_obituary("sleep", _record(*LIVE_2026_09_26[9]))
        assert o["number"] == (
            "sleep duration measured 8.98 hours on September 13 — the call was 7.20 hours ±1.24 (one standard deviation of his last 30 days)"
        )

    def test_positive_control_threshold_card_keeps_its_measured_value(self):
        """A machine (threshold) call's actual_value IS a reading — it stays 'measured N'."""
        rec = {
            "evaluation_type": "machine",
            "metric": "steps",
            "condition": "gte",
            "threshold": Decimal("8000"),
            "actual_value": Decimal("6512"),
            "reason": "steps=6512.0000 fails gte 8000",
            "prediction_id": "p-steps",
        }
        o = fs._wrong_obituary("training", rec)
        assert o["believed"] == "steps would come in at or above 8,000"
        assert o["number"] == "steps measured 6,512 — the call was at or above 8,000"
        assert o["what_changed"] == "It came in at 6,512, not at or above 8,000."

    def test_docket_resolution_reads_as_a_sentence(self):
        o = fs._wrong_obituary("explorer", _record(*LIVE_2026_09_26[3]))
        assert o["believed"] == "7-day average total calories would come in at or above 2,200 kcal"
        assert o["what_changed"] == "Settled against the call by the dispute docket on August 10."


class TestNoRawEvaluatorStringServed:
    def test_no_live_card_leaks_evaluator_vocabulary(self):
        """Guard over the 09-26 corpus, typed AND untyped (condition-only) records."""
        for row in LIVE_2026_09_26:
            for with_type in (True, False):
                o = fs._wrong_obituary(row[1], _record(*row, with_type=with_type))
                for field in _served(o):
                    assert not _LEAK.search(field), (row[2], field)
                assert not re.search(r"measured -?0\.\d", o["number"]), o["number"]

    def test_mutation_control_the_pre_4218_card_trips_the_guard(self):
        """The old format — slope as 'measured', raw reason as what_changed — must FAIL the guard,
        or the guard above proves nothing."""
        date, coach, reason = LIVE_2026_09_26[1]
        rec = _record(date, coach, reason)
        old_number = f"{rec['metric'].replace('_', ' ')} measured {round(float(rec['actual_value']), 2)}"
        assert re.search(r"measured -?0\.\d", old_number)
        assert _LEAK.search(reason)
        assert _LEAK.search(reason.upper())
