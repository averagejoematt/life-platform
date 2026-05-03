#!/usr/bin/env python3
"""
tests/test_health_auto_export.py — Unit tests for HAE Lambda's source-priority
deduplication and weight-feed name aliasing.

Covers TD-15 (port SOURCE_PRIORITY from v16.1 backfill into live Lambda),
TD-16 (subsumed by TD-15), and TD-18 (weight_body_mass alias).

No AWS credentials required — only `process_generic_metrics()` and
`pick_source_or_all()` are exercised, neither of which calls boto3 at runtime.
The boto3 client objects in the Lambda module are created at import time
but never used by the tested functions.

Run: python3 -m pytest tests/test_health_auto_export.py -v
"""

import os
import sys
from collections import Counter

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

# Env vars required by health_auto_export_lambda at import time
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("SECRET_NAME", "life-platform/ingestion-keys")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import health_auto_export_lambda as hae
except ImportError as _e:
    _import_err = _e
    hae = None  # type: ignore

if _import_err is not None:
    pytestmark = pytest.mark.skip(  # type: ignore
        reason=f"health_auto_export_lambda unavailable: {_import_err}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# TD-15 — pick_source_or_all() priority resolver
# ──────────────────────────────────────────────────────────────────────────────


class TestPickSourceOrAll:
    """TD-15: pick_source_or_all picks the canonical source per (field, date)."""

    def test_steps_matt17_iphone_wins_over_garmin_connect(self):
        # SOURCE_PRIORITY['steps']: ["matt 17", "matt", "iphone", "apple watch", "watch", "connect"]
        counts = Counter({"iPhone (Matt 17)": 100, "Garmin Connect": 80})
        chosen = hae.pick_source_or_all("steps", counts)
        assert chosen == "iPhone (Matt 17)", \
            f"Expected Matt-17 iPhone to win priority order, got {chosen!r}"

    def test_steps_iphone_wins_when_no_matt17(self):
        # No Matt-17 device — next priority match is 'iphone'
        counts = Counter({"Random iPhone": 100, "Garmin Connect": 80})
        chosen = hae.pick_source_or_all("steps", counts)
        assert chosen == "Random iPhone"

    def test_steps_garmin_wins_when_no_apple(self):
        # 'connect' is the last entry — Garmin Connect matches when nothing else does
        counts = Counter({"Garmin Connect": 80, "Some Other App": 10})
        chosen = hae.pick_source_or_all("steps", counts)
        assert chosen == "Garmin Connect"

    def test_water_my_water_wins_over_macrofactor(self):
        # SOURCE_PRIORITY['water_intake_raw']: ["my water", "waterminder", ...]
        counts = Counter({"My Water": 50, "MacroFactor": 50})
        chosen = hae.pick_source_or_all("water_intake_raw", counts)
        assert chosen == "My Water"

    def test_weight_withings_wins_over_iphone(self):
        # SOURCE_PRIORITY['weight_lbs']: ["withings", ...]
        counts = Counter({"Withings": 1, "iPhone (Matt 17)": 1})
        chosen = hae.pick_source_or_all("weight_lbs", counts)
        assert chosen == "Withings"

    def test_no_priority_returns_none(self):
        # Tier-2 metrics (heart_rate, etc.) have no SOURCE_PRIORITY entry
        # → caller treats None as "use all sources" (legacy aggregation)
        counts = Counter({"Apple Watch": 100, "iPhone": 50})
        chosen = hae.pick_source_or_all("heart_rate", counts)
        assert chosen is None

    def test_single_source_is_returned(self):
        counts = Counter({"iPhone (Matt 17)": 100})
        chosen = hae.pick_source_or_all("steps", counts)
        assert chosen == "iPhone (Matt 17)"

    def test_priority_defined_but_no_match_falls_back_to_most_common(self):
        # 'steps' has a priority list but neither source matches any entry
        counts = Counter({"Unknown App A": 100, "Unknown App B": 50})
        chosen = hae.pick_source_or_all("steps", counts)
        assert chosen == "Unknown App A", \
            "Should fall back to most-common when priority defined but no match"

    def test_empty_counter_returns_none(self):
        chosen = hae.pick_source_or_all("steps", Counter())
        # No sources at all → priority defined but nothing to choose from
        assert chosen is None


# ──────────────────────────────────────────────────────────────────────────────
# TD-15/16 — End-to-end via process_generic_metrics
# ──────────────────────────────────────────────────────────────────────────────


def _reading(source, qty, date_str="2026-05-02 12:00:00 -0800"):
    """Build a single HAE-shaped metric reading."""
    return {"date": date_str, "qty": qty, "source": source}


def _metric(name, *readings):
    return {"name": name, "data": list(readings)}


class TestProcessGenericMetrics:
    """End-to-end: HAE payload → daily aggregates with source-priority dedup."""

    def test_iphone_garmin_step_dedup_iphone_wins(self):
        """TD-15/16: iPhone steps + Garmin steps for same date → only iPhone writes."""
        metrics = [_metric(
            "Step Count",
            _reading("iPhone (Matt 17)", 5000),
            _reading("Garmin Connect", 7500),
        )]
        daily, _, audit = hae.process_generic_metrics(metrics)
        # Only the priority winner's value lands — not the sum (12500)
        assert daily["2026-05-02"]["steps"] == 5000
        # Audit records the choice + rejection for diagnostic visibility
        assert "steps" in audit["2026-05-02"]
        assert audit["2026-05-02"]["steps"]["chosen"] == "iPhone (Matt 17)"
        assert "Garmin Connect" in audit["2026-05-02"]["steps"]["rejected"]

    def test_single_source_unchanged(self):
        """TD-15: when only one source is present, behavior is unchanged."""
        metrics = [_metric(
            "Step Count",
            _reading("iPhone (Matt 17)", 3000),
            _reading("iPhone (Matt 17)", 2000),  # second reading from same source
        )]
        daily, _, audit = hae.process_generic_metrics(metrics)
        assert daily["2026-05-02"]["steps"] == 5000  # sum across same-source readings
        assert audit == {}  # no rejection — nothing to dedup

    def test_water_dedup_my_water_wins_over_macrofactor(self):
        """TD-15: water double-count (My Water + MacroFactor mirroring) gets deduped."""
        metrics = [_metric(
            "Dietary Water",
            _reading("My Water", 60),       # 60 fl_oz_us
            _reading("MacroFactor", 60),    # MacroFactor mirror
        )]
        daily, _, audit = hae.process_generic_metrics(metrics)
        # 60 fl_oz_us → ~1774 mL; not 120 fl_oz / 3548 mL doubled
        assert daily["2026-05-02"]["water_intake_ml"] == round(60 * 29.5735)
        assert audit["2026-05-02"]["water_intake_raw"]["chosen"] == "My Water"

    def test_tier2_no_priority_combines_apple_sources(self):
        """Tier-2 metrics (RHR) have no SOURCE_PRIORITY entry → all Apple sources combine.
        TD-17 / Tier-2: HAE Lambda keeps these but Whoop is source of truth, so
        the dedup story is "is_apple_device filter, then accept everything Apple."
        Resting Heart Rate is the cleanest Tier-2 to assert on (simple avg agg)."""
        metrics = [_metric(
            "Resting Heart Rate",
            _reading("Apple Watch", 50),
            _reading("Apple Watch", 60),
        )]
        daily, _, audit = hae.process_generic_metrics(metrics)
        # 'resting_heart_rate_apple' field, avg agg, no priority rejection
        assert daily["2026-05-02"]["resting_heart_rate_apple"] == 55
        assert audit == {}


# ──────────────────────────────────────────────────────────────────────────────
# TD-18 — weight_body_mass alias
# ──────────────────────────────────────────────────────────────────────────────


class TestWeightBodyMassAlias:
    """TD-18: iOS HAE export sends 'weight_body_mass'; previously the live Lambda
    only knew 'Body Mass' / 'body_mass' and silently ignored the variant."""

    def test_weight_body_mass_lowercase_writes_weight_record(self):
        metrics = [_metric(
            "weight_body_mass",
            _reading("iPhone", 175.0, "2026-05-02 07:00:00 -0800"),
        )]
        daily, _, _ = hae.process_generic_metrics(metrics)
        assert daily["2026-05-02"]["weight_lbs"] == 175.0

    def test_weight_body_mass_titlecase_writes_weight_record(self):
        metrics = [_metric(
            "Weight Body Mass",
            _reading("iPhone", 176.5, "2026-05-02 07:00:00 -0800"),
        )]
        daily, _, _ = hae.process_generic_metrics(metrics)
        assert daily["2026-05-02"]["weight_lbs"] == 176.5

    def test_body_mass_legacy_name_still_works(self):
        """Regression guard: original 'Body Mass' name keeps working."""
        metrics = [_metric(
            "Body Mass",
            _reading("iPhone", 174.0, "2026-05-02 07:00:00 -0800"),
        )]
        daily, _, _ = hae.process_generic_metrics(metrics)
        assert daily["2026-05-02"]["weight_lbs"] == 174.0
