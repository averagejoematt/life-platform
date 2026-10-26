"""tests/test_hae_watch_source_4969.py — `is_apple_device` against the Ultra 4's real source tags (#4969).

The source strings are the exact bytes measured on real HAE payloads under the registry's
`raw_layout` prefix (`raw/matthew/health_auto_export/2026/10/2{5,6}_*.json`, 32 payloads
landing 2026-10-25T22:00Z..2026-10-26T14:16Z, plus 359 from 10-16 onward):

  * the watch alone — "Matthew’s Apple Watch": a CURLY apostrophe (U+2019) and a
    NO-BREAK SPACE (U+00A0) between "Apple" and "Watch", so a test written with a straight
    apostrophe and a plain space would pass while proving nothing about the real tag;
  * the combined tag HAE writes when a bucket holds samples from two devices —
    "Matthew’s Apple Watch|Matt 17" (917 readings of heart_rate / step_count /
    walking_running_distance in the window);
  * the `Name|Connect` combined tag of the 2026-10-04 data-source sweep (C3,
    docs/reviews/DATA_SOURCE_SWEEP_2026-10-04.md) — "Matt 17|Connect";
  * the vendor mirrors that write the same HealthKit types: WHOOP, Withings, Eight Sleep,
    MacroFactor, My Water, Garmin Connect.

Values in the end-to-end case are synthetic: this repo is public and heart rate is Tier 2.
No clock is read: every reading carries a fixed timestamp (#4848).
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import health_auto_export_lambda as hae  # noqa: E402

WATCH = "Matthew’s Apple Watch"  # escaped on purpose: the curly apostrophe and the NBSP are the point
WATCH_PHONE = WATCH + "|Matt 17"  # the combined tag measured on the 10-25/26 payloads
SWEEP_C3 = "Matt 17|Connect"  # the sweep's `Name|Connect` combined tag
VENDORS = ("WHOOP", "Withings", "Eight Sleep", "MacroFactor", "My Water", "Garmin Connect")


def test_the_watch_tag_is_the_measured_bytes():
    # Guards the fixture itself: if someone "tidies" WATCH to ASCII the matcher tests below go vacuous.
    assert "’" in WATCH and " " in WATCH and "'" not in WATCH and " Watch" not in WATCH


def test_is_apple_device_accepts_every_apple_tag_and_no_vendor():
    apple = {tag: hae.is_apple_device(tag) for tag in (WATCH, WATCH_PHONE, SWEEP_C3, "Matt 17", "", None)}
    vendors = {tag: hae.is_apple_device(tag) for tag in VENDORS}
    assert all(apple.values()), f"Apple tags rejected: {[t for t, ok in apple.items() if not ok]}"
    assert not any(vendors.values()), f"vendor tags accepted as Apple: {[t for t, ok in vendors.items() if ok]}"


def test_a_tier2_reading_under_the_real_tags_lands_and_a_vendor_reading_is_dropped():
    def rd(source, qty, minute):
        return {"date": f"2026-10-26 07:{minute:02d}:13 -0700", "source": source, "Avg": qty, "Min": qty, "Max": qty}

    metrics = [{"name": "heart_rate", "units": "count/min", "data": [rd(WATCH, 60, 1), rd(WATCH_PHONE, 70, 2), rd("WHOOP", 200, 3)]}]
    daily, _ts, _audit = hae.process_generic_metrics(metrics)
    # 60 and 70 are the Apple readings; the WHOOP 200 would move the mean to 110 if it leaked in.
    assert daily["2026-10-26"]["heart_rate_apple"] == 65.0
