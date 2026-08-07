"""tests/test_status_cost_honesty.py — #1909.

`/api/status` published `pct_of_budget: 627, status: "red"` on a platform running
correctly INSIDE its ceiling, because it divided by a hardcoded `budget = 15.0`
that predates the ADR-063 budget system. That is the inverse of the usual
honest-numbers failure — a needlessly ALARMING number rather than a flattering
one — and ADR-104 cuts both ways.

Measuring the endpoint turned up two more defects the issue had not recorded:

  * It re-derived the projection with its own assumptions (`days_in_month = 30`),
    so the platform published two different projections of one quantity ~$8 apart.
  * `TimePeriod={"Start": month_start, "End": today}` is an EMPTY range on the 1st
    of the month, which Cost Explorer rejects — so the entire cost block silently
    vanished every month-start. Confirmed live: three ValidationExceptions in the
    site-api log on 2026-08-01, none on any other day.

All three came from re-deriving what cost_governor already computes. The fix reads
the governor's persisted breakdown — the same numbers the tier decision is made
from — so they cannot disagree by construction, the effective ceiling (ADR-133
dated window + surge float) is handled without this endpoint knowing those exist,
and there is no Cost Explorer call left to break on the 1st.

These guards mirror tests/test_receipts_endpoint.py: /api/receipts already did the
honest version of this, and #1909 is /api/status doing the dishonest one.
"""

import ast
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from ai import budget_guard  # noqa: E402
from operational import cost_governor_lambda as cg  # noqa: E402
from web import site_api_intelligence as sai  # noqa: E402

# #1654 (god-module breakup): the cost block and its only caller no longer share a
# file — `_budget_cost_block` moved to web/site_api_budget.py with the rest of the
# AI-spend domain, and `/api/status` (its caller) to web/site_api_status.py, both
# behind the unchanged site_api_intelligence facade. Guard the SET, not the instance:
# scan the whole family so these assertions keep biting wherever inside it the code
# lives, instead of passing vacuously the next time a module is split.
_SRC_FILES = (
    "site_api_intelligence.py",
    "site_api_budget.py",
    "site_api_status.py",
    "site_api_pulse.py",
    "site_api_discovery.py",
    "site_api_foresight.py",
)
_SRC = "\n".join((_REPO / "lambdas" / "web" / name).read_text() for name in _SRC_FILES)


def _status_cost_block():
    """The source of the cost block, located structurally rather than by line."""
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_budget_cost_block":
            return ast.unparse(node)
    raise AssertionError("_budget_cost_block not found")


def test_cost_block_is_reachable_without_standing_up_the_whole_handler():
    """The seam this test suite depends on.

    handle_status touches DynamoDB, CloudWatch and every pipeline component; a
    test that had to mock all of it to reach four lines of arithmetic would be
    testing everything except the thing that was wrong — and in practice it broke
    on unrelated module state another test had left behind.
    """
    assert callable(sai._budget_cost_block)
    assert "_budget_cost_block()" in _SRC, "handle_status must still call it"


# ── 1. The denominator is not a literal ──────────────────────────────────────


def test_no_hardcoded_budget_denominator():
    """The exact defect: a literal standing in for the real ceiling."""
    block = _status_cost_block()
    assert "budget = 15.0" not in block
    assert "15.0" not in block, "a bare numeric ceiling is back in handle_status"


def test_cost_block_reads_the_governors_breakdown():
    block = _status_cost_block()
    assert "read_breakdown" in block, "/api/status must read the governor's numbers, not re-derive them"
    assert "budget_guard" in block


def test_status_no_longer_calls_cost_explorer():
    """The month-start blackout cannot recur if the call is gone entirely."""
    block = _status_cost_block()
    assert "get_cost_and_usage" not in block
    assert "days_in_month" not in block, "a second projection method is how the two published figures diverged"


def test_dead_cost_cache_globals_are_gone():
    assert "_cost_cache: dict" not in _SRC
    assert "_cost_cache_ts = 0" not in _SRC


# ── 2. The traffic light follows the tier that is actually enforced ──────────


def test_tier_status_mapping_covers_every_tier_the_governor_can_set():
    """A tier with no mapping would fall through to a default and hide itself."""
    assert set(sai._BUDGET_TIER_STATUS) == set(cg._TIER_LABELS) if hasattr(cg, "_TIER_LABELS") else True
    assert set(sai._BUDGET_TIER_STATUS) == {0, 1, 2, 3}


def test_tier_1_is_not_reported_as_green():
    """Something IS switched off at tier 1 — calling it green is the flattering
    half of the same ADR-104 failure this issue fixes on the alarming side."""
    assert sai._BUDGET_TIER_STATUS[0] == "green"
    assert sai._BUDGET_TIER_STATUS[1] == "yellow"
    assert sai._BUDGET_TIER_STATUS[3] == "red"


def test_tier_semantics_are_shared_with_the_receipts_page():
    """One vocabulary for one fact — not a second description free to drift."""
    for tier in (0, 1, 2, 3):
        assert sai._TIER_SEMANTICS.get(tier), f"tier {tier} has no published semantics"


# ── 3. Functional: the published block, against a real breakdown shape ───────


def _run_status(monkeypatch, breakdown):
    """Exercise the real cost block against a real breakdown shape."""
    monkeypatch.setattr(budget_guard, "read_breakdown", lambda *a, **k: breakdown)
    return sai._budget_cost_block()


def _breakdown(ceiling, projected, tier, mtd=10.0):
    return {
        "tier": tier,
        "mtd": mtd,
        "projected": projected,
        "ceiling": ceiling,
        "ai_daily": 0.61,
        "non_ai_daily": 0.0,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_percentage_is_against_the_effective_ceiling_july_window(monkeypatch):
    """Inside the ADR-133 dated window the ceiling is $115, not the $85 base."""
    cost = _run_status(monkeypatch, _breakdown(115.0, 102.10, 2))
    assert cost["budget"] == 115.0
    assert cost["pct_of_budget"] == 89, "102.10/115 = 89% — correctly tier 2, not 627%"
    assert cost["tier"] == 2
    assert cost["status"] == "yellow"


def test_percentage_is_against_the_effective_ceiling_after_the_revert(monkeypatch):
    """The window auto-reverted on 2026-08-01; the endpoint must follow it."""
    cost = _run_status(monkeypatch, _breakdown(85.0, 18.8, 0, mtd=0.4))
    assert cost["budget"] == 85.0
    assert cost["pct_of_budget"] == 22
    assert cost["status"] == "green"


def test_the_original_defect_would_have_read_627_percent(monkeypatch):
    """Anchor the regression to the number that was actually served."""
    cost = _run_status(monkeypatch, _breakdown(115.0, 94.02, 2))
    assert round((94.02 / 15.0) * 100) == 627, "sanity: this is the old arithmetic"
    assert cost["pct_of_budget"] == 82, "the same spend, against the real ceiling"
    assert cost["status"] != "red"


def test_missing_breakdown_publishes_no_cost_block_rather_than_a_guess(monkeypatch):
    """read_breakdown() returns None when stale/missing. Silence beats invention."""
    assert _run_status(monkeypatch, None) == {}


def test_tier_and_semantics_ride_alongside_the_percentage(monkeypatch):
    """The tier is the number the system acts on — publish it, not just a ratio."""
    cost = _run_status(monkeypatch, _breakdown(85.0, 80.0, 3))
    assert cost["tier"] == 3
    assert "Hard stop" in cost["tier_semantics"]
    assert cost["status"] == "red"
    assert cost["as_of"]


# ── 4. The ceiling the governor reports really does honour the dated window ──


class _FrozenDatetime:
    """Freezes only .now(); everything else defers to the real datetime.

    `_active_ceilings()` reads the wall clock, so the boundary can only be
    exercised by controlling it. Freezing beats computing a date relative to
    today — a fixture date plus now-math is a time bomb that passes until the
    window it straddles moves.
    """

    _frozen = None

    @classmethod
    def now(cls, tz=None):
        return cls._frozen

    def __getattr__(self, name):  # pragma: no cover — passthrough
        return getattr(datetime, name)


def _ceilings_on(monkeypatch, when):
    frozen = type("F", (_FrozenDatetime,), {"_frozen": when})
    monkeypatch.setattr(cg, "datetime", frozen)
    monkeypatch.setattr(cg, "_CEILING_ENV_OVERRIDE", None)
    return cg._active_ceilings()


def test_governor_effective_ceiling_moves_across_the_july_boundary(monkeypatch):
    """The acceptance clause 'including inside the dated July window'.

    /api/status now inherits whatever ceiling the governor computed, so the honesty
    of the published percentage rests on THIS function being right about the date.
    """
    base_july, surge_july = _ceilings_on(monkeypatch, datetime(2026, 7, 15, tzinfo=timezone.utc))
    base_aug, _surge_aug = _ceilings_on(monkeypatch, datetime(2026, 8, 15, tzinfo=timezone.utc))

    assert base_july == cg._TEMP_CEILING_USD, "inside the window the raised ceiling must apply"
    assert surge_july == cg._TEMP_SURGE_CEILING_USD
    assert base_aug == cg.MONTHLY_CEILING, "August must be back on the standing ceiling"
    assert base_july > base_aug


def test_the_window_reverts_on_its_own_date_with_no_deploy(monkeypatch):
    """The half-open bound is the whole mechanism: 08-01 is already reverted."""
    last_july, _ = _ceilings_on(monkeypatch, datetime(2026, 7, 31, 23, 59, tzinfo=timezone.utc))
    first_aug, _ = _ceilings_on(monkeypatch, datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
    assert last_july == cg._TEMP_CEILING_USD
    assert first_aug == cg.MONTHLY_CEILING
