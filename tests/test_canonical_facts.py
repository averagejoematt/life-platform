"""
tests/test_canonical_facts.py — the one canonical-facts schema + its producer contract.

canonical_facts.build_canonical_facts is the single extraction of the day's key
numbers from a computed_metrics record; the coach-grounding reader and the
Coherence Sentinel both use it. These tests pin the extraction AND the contract
that the producer (daily_metrics_compute) actually writes every field the schema
reads — a producer-side rename that broke grounding (the 30-vs-86 class) would
fail here instead of silently shipping.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import canonical_facts as cf  # noqa: E402

_PRODUCER = os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute", "daily_metrics_compute_lambda.py")


class TestExtraction:
    def test_round_trip_rounds_and_carries_as_of(self):
        rec = {
            "recovery_pct": 30.04,
            "hrv_ms": 25.18,
            "rhr_bpm": 58,
            "protein_g_avg": 140.72,
            "protein_g_target": 190,
            "protein_g_floor": 170,
            "latest_weight": 300.84,
            "weekly_rate_lbs": -1.7,
            "date": "2026-06-27",
        }
        f = cf.build_canonical_facts(rec)
        assert f["recovery_pct"] == 30.0
        assert f["hrv_ms"] == 25.2
        assert f["protein_g_avg"] == 140.7  # intake, distinct from target/floor
        assert f["protein_g_target"] == 190.0
        assert f["latest_weight"] == 300.8
        assert f["as_of"] == "2026-06-27"

    def test_missing_and_bad_values_become_none(self):
        f = cf.build_canonical_facts({"recovery_pct": None, "hrv_ms": "n/a"})
        assert f["recovery_pct"] is None
        assert f["hrv_ms"] is None
        assert f["latest_weight"] is None  # absent
        assert f["as_of"] is None

    def test_empty_record_is_all_none(self):
        f = cf.build_canonical_facts({})
        assert set(f) == set(cf.NUMERIC_FIELDS) | {"as_of"}
        assert all(f[k] is None for k in cf.NUMERIC_FIELDS)

    def test_units_documented_for_every_field(self):
        # Every numeric fact must carry a unit note (the HRV-ms / protein-distinct contract).
        assert set(cf.FIELD_UNITS) == set(cf.NUMERIC_FIELDS)
        assert "millisecond" in cf.FIELD_UNITS["hrv_ms"].lower()


class TestProducerContract:
    def test_producer_writes_every_canonical_field(self):
        """daily_metrics_compute must write each field build_canonical_facts reads."""
        src = open(_PRODUCER, encoding="utf-8").read()
        missing = [f for f in cf.NUMERIC_FIELDS if not re.search(rf'["\']{re.escape(f)}["\']', src)]
        assert not missing, f"computed_metrics producer is missing canonical fields: {missing}"
