"""tests/test_receipts_endpoint.py — #1397, the Glass Engine.

/api/receipts publishes the budget ENVELOPE (ceiling, month-to-date, month-end
projection, tier, and what that tier has switched off) from what cost_governor
already writes. The whole point of the page is that a reader can trust the
numbers, so the guards here are mostly honesty guards:

  1. Every dollar figure comes from the governor's breakdown param — never a
     literal, and never recomputed here (a second implementation of the
     governor's math could disagree with the governor, and then the page that
     exists to make spending legible would be the thing lying about it).
  2. A missing or STALE breakdown omits the figures and says why. The failure
     mode this blocks is the nastiest one for a cost page: silently serving
     last-known values forever, looking perfectly healthy.
  3. The tier ladder stays lockstep with cost_governor._TIER_LABELS, so the
     page can't describe a tier the governor doesn't actually enforce.
  4. The staleness bound stays lockstep with budget_guard._BREAKDOWN_MAX_AGE_S.
  5. A CloudWatch failure costs you the spend curve, not the whole receipt.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from web import site_api_intelligence as sai  # noqa: E402

_TIER_PARAM = "/life-platform/budget-tier"
_BREAKDOWN_PARAM = "/life-platform/budget-breakdown"


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeCW:
    def __init__(self, datapoints=None, raises=False):
        self._datapoints = datapoints or []
        self._raises = raises

    def get_metric_statistics(self, **kw):
        if self._raises:
            raise RuntimeError("simulated CloudWatch failure")
        return {"Datapoints": self._datapoints}

    def list_metrics(self, **kw):  # pragma: no cover — receipts doesn't list metrics
        return {"Metrics": []}


class _FakeSSM:
    def __init__(self, params, raises_for=()):
        self._params = params
        self._raises_for = set(raises_for)

    def get_parameter(self, Name):
        if Name in self._raises_for or Name not in self._params:
            raise RuntimeError("simulated SSM failure")
        return {"Parameter": {"Value": self._params[Name]}}


def _install(monkeypatch, ssm, cw=None):
    cw = cw or _FakeCW()

    def _client(service, **kw):
        if service == "cloudwatch":
            return cw
        if service == "ssm":
            return ssm
        raise AssertionError(f"unexpected client: {service}")

    monkeypatch.setattr(sai.boto3, "client", _client)


def _payload(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _breakdown(age_hours=1.0, **over):
    computed = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    base = {
        "tier": 1,
        "mtd": 26.11,
        "projected": 62.4,
        "ceiling": 85.0,
        "surge_active": False,
        "recent_uniques": 120,
        "surge_threshold": 900,
        "ai_daily": 1.2,
        "non_ai_daily": 0.8,
        "computed_at": computed.isoformat(),
    }
    base.update(over)
    return base


def _ssm_with(breakdown, tier="1"):
    return _FakeSSM({_TIER_PARAM: tier, _BREAKDOWN_PARAM: json.dumps(breakdown)})


# ── 1. figures come from the breakdown, not from literals ────────────────────
def test_every_dollar_figure_is_the_breakdown_value(monkeypatch):
    bd = _breakdown(mtd=31.5, projected=70.25, ceiling=100.0, surge_active=True, recent_uniques=972)
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())

    assert d["stale"] is False and d["stale_reason"] is None
    assert d["month_to_date_usd"] == 31.5
    assert d["projected_month_end_usd"] == 70.25
    assert d["ceiling_usd"] == 100.0
    assert d["surge_active"] is True
    assert d["recent_uniques"] == 972
    assert d["ai_daily_usd"] == 1.2 and d["non_ai_daily_usd"] == 0.8
    # Percentages are derived from the SAME breakdown numbers, so they can't drift
    # away from the figures printed next to them.
    assert d["projected_pct_of_ceiling"] == pytest.approx(70.25 / 100.0 * 100, abs=0.05)
    assert d["mtd_pct_of_ceiling"] == pytest.approx(31.5 / 100.0 * 100, abs=0.05)


def test_ceiling_is_not_a_hardcoded_85(monkeypatch):
    """The #1230 defect class: a literal ceiling is wrong the moment surge floats it."""
    _install(monkeypatch, _ssm_with(_breakdown(ceiling=100.0, surge_active=True)))
    assert _payload(sai.handle_receipts())["ceiling_usd"] == 100.0


# ── 2. stale / missing → omit the figures and SAY SO ─────────────────────────
def test_stale_breakdown_omits_figures_and_explains(monkeypatch):
    """A 3-day-old breakdown must not be served as if it were current."""
    _install(monkeypatch, _ssm_with(_breakdown(age_hours=72)))
    d = _payload(sai.handle_receipts())

    assert d["stale"] is True
    assert "72h ago" in d["stale_reason"]
    # The figures are ABSENT, not frozen at their last value.
    for k in ("month_to_date_usd", "projected_month_end_usd", "ceiling_usd", "ai_daily_usd"):
        assert d[k] is None, f"{k} should be omitted when the breakdown is stale"
    assert "projected_pct_of_ceiling" not in d
    # The tier still reports — it is read independently and stays truthful.
    assert d["tier"] == 1 and d["tier_semantics"]


def test_missing_breakdown_is_stale_not_a_500(monkeypatch):
    _install(monkeypatch, _FakeSSM({_TIER_PARAM: "0"}))
    d = _payload(sai.handle_receipts())
    assert d["stale"] is True and d["stale_reason"]
    assert d["month_to_date_usd"] is None


def test_breakdown_without_computed_at_is_stale(monkeypatch):
    """No timestamp means unfalsifiable freshness — treat as stale, not as fresh."""
    bd = _breakdown()
    bd.pop("computed_at")
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert d["stale"] is True
    assert "computed_at" in d["stale_reason"]


def test_fresh_breakdown_just_inside_the_bound_is_not_stale(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown(age_hours=47)))
    assert _payload(sai.handle_receipts())["stale"] is False


# ── 3 & 4. lockstep with the engines that actually enforce this ──────────────
def test_tier_semantics_cover_exactly_the_governor_tiers():
    sys.path.insert(0, str(_REPO / "lambdas" / "operational"))
    import cost_governor_lambda as gov

    assert set(sai._TIER_SEMANTICS) == set(gov._TIER_LABELS), (
        "the receipts page describes a different set of tiers than the governor enforces — " "one of them has gained or lost a tier"
    )


def test_staleness_bound_matches_budget_guard():
    import budget_guard

    assert (
        sai._BREAKDOWN_MAX_AGE_S == budget_guard._BREAKDOWN_MAX_AGE_S
    ), "the page and the guard disagree about when a breakdown stops being current"


def test_tier_semantics_name_what_is_paused():
    """Tier prose must be actionable — a severity word alone tells a reader nothing."""
    assert "Nothing is paused" in sai._TIER_SEMANTICS[0]
    for t in (1, 2, 3):
        assert "paused" in sai._TIER_SEMANTICS[t].lower() or "hard stop" in sai._TIER_SEMANTICS[t].lower()


# ── 5. the curve is a bonus, never a dependency ──────────────────────────────
def test_history_renders_from_cloudwatch_maximums(monkeypatch):
    pts = [
        {"Timestamp": datetime(2026, 7, 1, tzinfo=timezone.utc), "Maximum": 3.2},
        {"Timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc), "Maximum": 11.9},
        {"Timestamp": datetime(2026, 7, 2, tzinfo=timezone.utc), "Maximum": 7.4},
    ]
    _install(monkeypatch, _ssm_with(_breakdown()), _FakeCW(datapoints=pts))
    hist = _payload(sai.handle_receipts())["history"]
    # Sorted ascending by date regardless of the order CloudWatch returns them —
    # an unsorted series would draw a zig-zag that looks like real volatility.
    assert [h["date"] for h in hist] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert [h["mtd_usd"] for h in hist] == [3.2, 7.4, 11.9]


def test_cloudwatch_failure_costs_the_curve_not_the_receipt(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown()), _FakeCW(raises=True))
    d = _payload(sai.handle_receipts())
    assert d["history"] == []
    assert d["month_to_date_usd"] == 26.11  # the rest of the receipt survives


def test_total_ssm_failure_returns_503_not_a_fabricated_receipt(monkeypatch):
    _install(monkeypatch, _FakeSSM({}, raises_for=(_TIER_PARAM, _BREAKDOWN_PARAM)))
    d = _payload(sai.handle_receipts())
    # tier unreadable AND breakdown unreadable → nothing truthful left to show
    assert d["tier"] is None and d["stale"] is True


# ── per-feature honesty (the reason there is no dollar column) ───────────────
def test_per_feature_note_explains_why_tokens_not_dollars(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown()))
    note = _payload(sai.handle_receipts())["per_feature_note"]
    assert "tokens" in note and "model dimension" in note


# ── 6. the projection anchor date (#1618) ────────────────────────────────────
def test_month_end_date_is_the_last_calendar_day_of_this_month(monkeypatch):
    """The spend curve extends its dashed projection to this date; it must be the
    real last day of the current month, not a fabricated or off-by-one date."""
    import calendar as _cal

    _install(monkeypatch, _ssm_with(_breakdown()))
    d = _payload(sai.handle_receipts())
    now = datetime.now(timezone.utc)
    expected = now.replace(day=_cal.monthrange(now.year, now.month)[1]).strftime("%Y-%m-%d")
    assert d["month_end_date"] == expected


def test_month_end_date_is_present_even_when_breakdown_is_stale(monkeypatch):
    """The anchor is calendar-deterministic, so it is available regardless of the
    governor's breakdown — the front-end simply won't draw a projection without a value."""
    _install(monkeypatch, _ssm_with(_breakdown(age_hours=72)))
    d = _payload(sai.handle_receipts())
    assert d["stale"] is True
    assert d["month_end_date"] and d["month_end_date"].startswith(datetime.now(timezone.utc).strftime("%Y-%m"))


# ── the route is actually wired ─────────────────────────────────────────────
def test_receipts_route_registered():
    from web import site_api_lambda as sal

    assert sal.ROUTES["/api/receipts"] is sai.handle_receipts
