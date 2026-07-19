"""tests/test_clamp_today_pacific.py — the genesis-eve 500 regression (2026-07-19).

/api/fulfillment_ritual 500'd from 00:00 UTC on genesis eve: _clamp_today
clamped to UTC today while handlers build their BETWEEN upper bound from
PT today — for ~7 hours lower(genesis, via UTC clamp) > upper(PT today) and
DynamoDB rejects the expression. The clamp must be PACIFIC (PT date <= UTC
date always, so it is safe for both upper-bound kinds).
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_common as common  # noqa: E402


def test_clamp_today_clamps_in_pacific_not_utc():
    # genesis eve: UTC has rolled onto genesis day, PT has not — the clamp must
    # come down to the PT date or the BETWEEN bounds invert (the live 500).
    assert common._clamp_today("2026-07-19", _now_date="2026-07-18") == "2026-07-18"


def test_clamp_today_noop_once_date_is_past():
    assert common._clamp_today("2026-07-18", _now_date="2026-07-19") == "2026-07-18"


def test_clamp_today_default_is_the_pacific_date():
    assert common._clamp_today("9999-01-01") == datetime.now(common.PT).strftime("%Y-%m-%d")
