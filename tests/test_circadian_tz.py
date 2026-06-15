"""tests/test_circadian_tz.py — elite review (2026-06-15) bug cluster.

circadian_compliance_lambda._parse_time_to_hour converted UTC -> "PT" with a
hardcoded -8h offset, which is an hour wrong during PDT (~8 months/yr) and
skewed the wake/meal-hour circadian scores. It now uses DST-aware ZoneInfo.
These pin both sides of the DST boundary.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("lambdas", "lambdas/compute", "cdk/layer-build/python"):
    sys.path.insert(0, os.path.join(ROOT, p))

import circadian_compliance_lambda as cc  # noqa: E402


def test_pt_conversion_during_pdt_summer():
    # 2026-06-15 15:00 UTC → PDT is UTC-7 → 08:00 local → hour 8.0
    # (the old hardcoded UTC-8 would wrongly give 7.0)
    assert cc._parse_time_to_hour("2026-06-15T15:00:00Z") == 8.0


def test_pt_conversion_during_pst_winter():
    # 2026-01-15 15:00 UTC → PST is UTC-8 → 07:00 local → hour 7.0
    assert cc._parse_time_to_hour("2026-01-15T15:00:00Z") == 7.0


def test_naive_iso_treated_as_utc():
    # No tz suffix → assumed UTC, then converted (summer → UTC-7)
    assert cc._parse_time_to_hour("2026-06-15T15:30:00") == 8.5


def test_plain_hhmm_passthrough():
    # "HH:MM" with no date is taken as-is (no tz conversion path)
    assert cc._parse_time_to_hour("06:30") == 6.5


def test_empty_returns_none():
    assert cc._parse_time_to_hour("") is None
    assert cc._parse_time_to_hour(None) is None
