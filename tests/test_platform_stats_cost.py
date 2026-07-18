"""tests/test_platform_stats_cost.py — the public monthly_cost can't silently rot.

Replays #1232: /api/platform_stats (the "radical-accessibility receipt" page)
served monthly_cost = "~$60" while the budget governor's own numbers said June 2026
actual $79.80 and July projected $82.22 — a ~25% understatement, and its comment
cited the RETIRED "$75 cap" (the effective ceiling is $85, floating to $100 in surge,
ADR-133). monthly_cost is a hand-maintained JUDGMENT field, deliberately exempt from
sync_doc_metadata's discoverers (which need live AWS creds and don't run in the offline
CI gate). So this is the OFFLINE guard: it asserts the served literal is not the stale
"~$60" and parses to a plausible band consistent with the ~$80 run-rate under the $85/
$100 ceiling. The reconcile-time (creds-bearing) discoverer can tighten this against the
governor's ProjectedMonthlySpend; this test is what reds the offline pytest gate.

Non-vacuity: this test FAILS against the pre-fix "~$60" literal (60 <= LOWER_FLOOR).
"""

import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web.site_api_common import PLATFORM_STATS  # noqa: E402

# Ground-truth band (#1232): the trailing run-rate is ~$80 (June actual $79.80, July
# projected $82.22). The effective ceiling is $85, floating to $100 in surge (ADR-133).
# Bounds are derived from that real domain — NOT a blanket [0,100] — so the gate stays
# honest if spend genuinely climbs toward the surge ceiling.
LOWER_FLOOR = 65  # the stale "~$60" (and any <=$65 understatement) must fail here
BAND_LO = 50  # a plausible-total sanity floor
BAND_HI = 100  # the ADR-133 surge ceiling — above this, the literal is implausible


def _monthly_cost_dollars() -> float:
    raw = PLATFORM_STATS["monthly_cost"]
    assert isinstance(raw, str), f"monthly_cost must be a display string, got {type(raw)!r}"
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    assert m is not None, f"monthly_cost {raw!r} has no parseable dollar figure"
    return float(m.group(1))


def test_monthly_cost_is_not_the_stale_60():
    """The exact evidence pointer from #1232 must no longer reproduce."""
    assert PLATFORM_STATS["monthly_cost"] != "~$60", "reverted to the stale #1232 literal — see tests/test_platform_stats_cost.py"


def test_monthly_cost_parses_to_plausible_band():
    """Pinned figure must sit in the ground-truth band and above the understatement floor."""
    dollars = _monthly_cost_dollars()
    assert dollars > LOWER_FLOOR, f"monthly_cost ${dollars:.0f} <= ${LOWER_FLOOR} understates the ~$80 run-rate (#1232)"
    assert BAND_LO <= dollars <= BAND_HI, f"monthly_cost ${dollars:.0f} outside the plausible ${BAND_LO}-${BAND_HI} band"
