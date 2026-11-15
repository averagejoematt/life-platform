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

#5952: the band above could not see a 2x error — the literal sat at "~$100" while the last
closed month billed $218.99, and $100 is comfortably inside [$65, surge]. The SERVED figure is
now derived per request from the governor's month-to-date series (site_api_rollups.
_monthly_cost_fields → site_api_budget.last_closed_month_cost), and the tests below hold it to
`SERVED_TOLERANCE` of the month it was read from — so ~$100 against a $219 month, or ~$440,
fails. The literal is now only the stack manifest's pinned copy; its loose band stays as the
#1232 floor guard, and the served-value tests are the run-rate guard.
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone

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


# ── #5952: the served figure is the last closed month, read — and a 2x error fails ─────────

# The tightest tolerance the rounding allows: the display rounds to $10, so at the band's floor
# ($50) a correct figure can be off by $5 = 10%. A 2x error is off by 50% or 100%.
SERVED_TOLERANCE = 0.10

# Ground truth for the fixture, read-only on 2026-11-14: the governor's
# LifePlatform/Budget::EstimatedMonthToDateSpend maxima per closed month, and the Cost Explorer
# UnblendedCost bill for the same month. The governor reads within ~2% of the invoice.
GOVERNOR_MONTH_MAX = {"2026-08": 181.1054676118, "2026-09": 136.3564358754, "2026-10": 222.4897535689}
CE_BILLED = {"2026-08": 180.58, "2026-09": 137.15, "2026-10": 218.99}


def _within(display: str, usd: float) -> bool:
    m = re.search(r"(\d+(?:\.\d+)?)", display or "")
    return m is not None and abs(float(m.group(1)) - usd) <= SERVED_TOLERANCE * usd


class _CW:
    """A CloudWatch stub serving the governor's running month-to-date total, one Maximum a day."""

    def __init__(self, month_start, days, final_usd, fail=False):
        self.calls = []
        self.fail = fail
        self.points = [{"Timestamp": month_start + timedelta(days=i), "Maximum": final_usd * (i + 1) / days} for i in range(days)]

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"Datapoints": list(self.points)}


_OCT = datetime(2026, 10, 1, tzinfo=timezone.utc)
_NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)  # frozen — no live clock (#4848)


def test_served_cost_is_the_last_closed_month():
    from web.site_api_budget import last_closed_month_cost

    cw = _CW(_OCT, 31, GOVERNOR_MONTH_MAX["2026-10"])
    got = last_closed_month_cost(cw, _NOW)
    assert got["month"] == "2026-10"
    assert got["display"] == "~$220"
    assert got["usd"] == round(GOVERNOR_MONTH_MAX["2026-10"], 2)
    # it asked for exactly October, and only the governor's own series
    call = cw.calls[0]
    assert (call["Namespace"], call["MetricName"]) == ("LifePlatform/Budget", "EstimatedMonthToDateSpend")
    assert call["StartTime"] == _OCT and call["EndTime"] == datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_every_measured_closed_month_lands_inside_the_tolerance_of_its_invoice():
    """The derivation, run on each month's real governor reading, agrees with Cost Explorer."""
    from web.site_api_budget import last_closed_month_cost

    for month, usd in GOVERNOR_MONTH_MAX.items():
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
        nxt = (start + timedelta(days=32)).replace(day=1)
        days = (nxt - start).days
        got = last_closed_month_cost(_CW(start, days, usd), nxt + timedelta(days=3))
        assert got["month"] == month
        assert _within(got["display"], CE_BILLED[month]), f"{month}: served {got['display']} vs billed ${CE_BILLED[month]}"


def test_the_band_rejects_a_2x_error():
    """The #5952 shape: the old literal (and its mirror) against October's bill must FAIL the band."""
    passed = [w for w in ("~$100", "~$110", "~$440") if _within(w, CE_BILLED["2026-10"])]
    assert not passed, f"a 2x error passed the band: {passed}"
    assert _within("~$220", CE_BILLED["2026-10"])


def test_platform_stats_serves_the_derived_figure_not_the_literal(monkeypatch):
    import boto3
    from web import site_api_rollups as r

    monkeypatch.setattr(r, "_CLOSED_MONTH_MEMO", {})
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _CW(_OCT, 31, GOVERNOR_MONTH_MAX["2026-10"]))
    fields = r._monthly_cost_fields(_NOW)
    assert fields["monthly_cost"] == "~$220"
    assert fields["monthly_cost_month"] == "2026-10"
    assert _within(fields["monthly_cost"], CE_BILLED["2026-10"])


def test_an_unreadable_month_is_a_gap_never_the_pinned_literal(monkeypatch):
    import boto3
    from web import site_api_rollups as r

    monkeypatch.setattr(r, "_CLOSED_MONTH_MEMO", {})
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _CW(_OCT, 31, 222.49, fail=True))
    fields = r._monthly_cost_fields(_NOW)
    assert fields["monthly_cost"] == ""
    assert fields["monthly_cost"] != PLATFORM_STATS["monthly_cost"]
    assert fields["monthly_cost_usd"] is None
    assert r._CLOSED_MONTH_MEMO == {}, "a failed read must not be memoised"


def test_a_month_the_governor_stopped_writing_early_is_withheld():
    """Readings that end a week before the month does are not that month's total."""
    from web.site_api_budget import last_closed_month_cost

    assert last_closed_month_cost(_CW(_OCT, 24, 150.0), _NOW) is None
    assert last_closed_month_cost(_CW(_OCT, 31, 0.0), _NOW) is None


def test_the_year_boundary_reads_december():
    from web.site_api_budget import last_closed_month_cost

    dec = datetime(2025, 12, 1, tzinfo=timezone.utc)
    got = last_closed_month_cost(_CW(dec, 31, 96.0), datetime(2026, 1, 5, tzinfo=timezone.utc))
    assert (got["month"], got["display"]) == ("2025-12", "~$100")
