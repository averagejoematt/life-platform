"""tests/test_hero_weight_arithmetic.py — #1225 home-hero weight-row guard.

Proves qa_smoke_lambda.assess_hero_weight / check_hero_weight_arithmetic FAIL the
nightly run on the exact inconsistent /api/journey payload that shipped before the
fix (current_weight_lbs int-rounded to 316 while lost_lbs is computed off the raw
315.6, so 316 − 314 = 2 ≠ 1.6), and pass on the reconciled one-decimal payload.

Non-vacuous (the load-bearing assertion): `test_old_inconsistent_payload_fails`
feeds the literal pre-fix payload and asserts .passed is False — a guard that never
fails would not satisfy it. It also covers the trend-honesty leg (a single weigh-in
may not carry a multi-day span) and the fail-SOFT posture on an unreachable API.
"""

import json
import os
import sys

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402

# The literal payload the API returned before #1225: 315.6 shown as 316, delta off
# the raw value, and no weighin_count at all.
OLD_INCONSISTENT = {
    "start_weight_lbs": 314.0,
    "goal_weight_lbs": 185.0,
    "current_weight_lbs": 316,  # int-rounded from 315.6 — the bug
    "lost_lbs": -1.6,  # computed off the raw 315.6
    "progress_pct": -1.2,
    "weighin_span_days": 0,
    "last_weighin_date": "2026-07-13",
}

# The reconciled payload the fix produces: one decimal everywhere + weighin_count.
FIXED_CONSISTENT = {
    "start_weight_lbs": 314.0,
    "goal_weight_lbs": 185.0,
    "current_weight_lbs": 315.6,
    "lost_lbs": -1.6,
    "progress_pct": -1.2,
    "weighin_span_days": 0,
    "weighin_count": 1,
    "last_weighin_date": "2026-07-13",
}


def test_old_inconsistent_payload_fails():
    # The core non-vacuous proof: the pre-fix stat row must be caught.
    ok, msg = qa.assess_hero_weight(OLD_INCONSISTENT)
    assert ok is False
    assert "arithmetic" in msg and "316" in msg


def test_fixed_payload_reconciles():
    ok, msg = qa.assess_hero_weight(FIXED_CONSISTENT)
    assert ok is True, msg


def test_missing_weighin_count_fails():
    # Trend honesty (b): without a count, story.js can't gate the "in N days" claim.
    p = dict(FIXED_CONSISTENT)
    del p["weighin_count"]
    ok, msg = qa.assess_hero_weight(p)
    assert ok is False
    assert "weighin_count" in msg


def test_single_weighin_with_span_fails():
    # A lone weigh-in must span 0 days — a >0 span would license a false N-day trend.
    p = dict(FIXED_CONSISTENT)
    p["weighin_count"] = 1
    p["weighin_span_days"] = 4
    ok, msg = qa.assess_hero_weight(p)
    assert ok is False
    assert "trend" in msg


def test_real_multi_weighin_trend_passes():
    p = dict(FIXED_CONSISTENT)
    p.update({"current_weight_lbs": 311.2, "lost_lbs": 2.8, "weighin_count": 6, "weighin_span_days": 20})
    ok, msg = qa.assess_hero_weight(p)
    assert ok is True, msg


def test_pre_start_is_clean_pass():
    # Pre-start (#931) nulls the weight fields on purpose — nothing to reconcile.
    ok, _ = qa.assess_hero_weight({"pre_start": True, "current_weight_lbs": None})
    assert ok is True


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_reds_on_live_inconsistency(monkeypatch):
    monkeypatch.setattr(qa.urllib.request, "urlopen", lambda req, timeout=None: _Resp({"journey": OLD_INCONSISTENT}))
    (c,) = qa.check_hero_weight_arithmetic()
    assert c.passed is False


def test_check_passes_on_fixed_payload(monkeypatch):
    monkeypatch.setattr(qa.urllib.request, "urlopen", lambda req, timeout=None: _Resp({"journey": FIXED_CONSISTENT}))
    (c,) = qa.check_hero_weight_arithmetic()
    assert c.passed is True


def test_check_fetch_error_is_fail_soft(monkeypatch):
    def _boom(req, timeout=None):
        raise OSError("boom")

    monkeypatch.setattr(qa.urllib.request, "urlopen", _boom)
    (c,) = qa.check_hero_weight_arithmetic()
    assert c.passed is None  # warn — a fetch blip must never red the nightly
