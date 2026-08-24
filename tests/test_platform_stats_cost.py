"""tests/test_platform_stats_cost.py — the public monthly_cost can't silently rot.

Replays #1232: /api/platform_stats (the "radical-accessibility receipt" page)
served monthly_cost = "~$60" while the budget governor's own numbers said June 2026
actual $79.80 — a ~25% understatement, and its comment cited a cap that had been
retired. monthly_cost is a hand-maintained JUDGMENT field, deliberately exempt from
sync_doc_metadata's discoverers (which need live AWS creds and don't run in the offline
CI gate). So this is the OFFLINE guard: it asserts the served literal is not the stale
"~$60" and parses to a plausible band whose upper bound is the governor's own surge
ceiling. The reconcile-time (creds-bearing) discoverer can tighten this against the
governor's ProjectedMonthlySpend; this test is what reds the offline pytest gate.

#2898: neither this docstring nor the band restates a ceiling figure any more. Both did,
and both had gone stale — a stale-number guard carrying stale numbers of its own.

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

sys.path.insert(0, os.path.join(_REPO, "scripts"))

from budget_ceilings import read_family  # noqa: E402
from web.site_api_common import PLATFORM_STATS  # noqa: E402

# Ground-truth band (#1232): the trailing run-rate is the last CLOSED month (June 2026
# $79.80, July 2026 $98.35 — Cost Explorer UnblendedCost, re-read 2026-08-23).
#
# #2898: the upper bound used to be the literal `100  # the ADR-133 surge ceiling`. That
# was a hand-copy of a number this repo has exactly one source for, and it went stale the
# moment the surge ceiling moved — leaving the plausibility bound quietly tighter than the
# envelope it claimed to be. It is now DERIVED from the governor's SURGE_CEILING_USD, so
# it tracks the ceiling family by construction. Falling back is not an option: an
# underivable ceiling means the bound is unknown, and an unknown bound must not silently
# become a permissive one.
_FAMILY = read_family()
assert _FAMILY.surge is not None, "surge ceiling not derivable from the cost governor (#2898)"

LOWER_FLOOR = 65  # the stale "~$60" (and any <=$65 understatement) must fail here
BAND_LO = 50  # a plausible-total sanity floor
BAND_HI = _FAMILY.surge  # the ADR-133 surge ceiling — above this, the literal is implausible


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
    assert dollars > LOWER_FLOOR, f"monthly_cost ${dollars:.0f} <= ${LOWER_FLOOR} understates the measured trailing run-rate (#1232)"
    assert BAND_LO <= dollars <= BAND_HI, f"monthly_cost ${dollars:.0f} outside the plausible ${BAND_LO}-${BAND_HI} band"
