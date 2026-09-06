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

import importlib
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


# ── 1b. the BASE ceiling comes from the payload too (#1999) ──────────────────
# The residual of #1230: `ceiling_usd` was derived, `base_ceiling_usd` was still
# the module literal. During the July-2026 dated window that shipped a receipt
# reading base $85 / in-effect $115 / surge_active false — every number honest,
# the $30 delta attributable to nothing the payload named.


def _gov():
    sys.path.insert(0, str(_REPO / "lambdas" / "operational"))
    import cost_governor_lambda as gov

    return gov


def test_base_ceiling_comes_from_the_governor_not_the_literal(monkeypatch):
    bd = _breakdown(ceiling=115.0, base_ceiling=115.0, surge_ceiling=135.0)
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())

    assert d["base_ceiling_usd"] == 115.0, "base_ceiling_usd is still the hardcoded literal"
    assert d["base_ceiling_usd"] != sai._ADR133_BASE_CEILING_USD
    assert d["surge_ceiling_usd"] == 135.0


def test_dated_window_case_base_ceiling_matches_active_ceilings(monkeypatch):
    """The issue's regression guard: build the payload the governor would ACTUALLY
    write with a dated window in effect, and assert the receipt republishes that
    base — i.e. `base_ceiling_usd == _active_ceilings()[0]`, not the literal."""
    gov = _gov()
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(gov, "_CEILING_ENV_OVERRIDE", False)
    monkeypatch.setattr(gov, "_TEMP_CEILING_WINDOW", (today - timedelta(days=2), today + timedelta(days=5)))
    monkeypatch.setattr(gov, "_TEMP_CEILING_USD", 115.0)
    monkeypatch.setattr(gov, "_TEMP_SURGE_CEILING_USD", 135.0)

    active_base, active_surge = gov._active_ceilings()
    assert active_base == 115.0  # the window is in effect for this test

    bd = _breakdown(
        ceiling=active_base,
        base_ceiling=active_base,
        surge_ceiling=active_surge,
        ceiling_window=gov._active_ceiling_window(),
    )
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())

    assert d["base_ceiling_usd"] == active_base
    win = d["ceiling_window"]
    assert win and win["start"] and win["end_exclusive"]
    assert win["reverts_to_base_ceiling"] == gov.MONTHLY_CEILING
    # The window must be EXPLAINED in the reader-facing prose, not just present
    # as a machine field — the unexplained delta is the whole defect.
    assert f"${active_base:.0f}" in d["note"] and win["start"] in d["note"]
    assert f"${gov.MONTHLY_CEILING:.0f}" in d["note"]


def test_no_window_publishes_null_not_an_invented_one(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown(base_ceiling=85.0, surge_ceiling=100.0, ceiling_window=None)))
    d = _payload(sai.handle_receipts())
    assert d["ceiling_window"] is None
    assert "dated window" not in d["note"]


def test_pre_1999_payload_falls_closed_to_the_literal(monkeypatch):
    """Backward compatibility: the payload SSM holds right now has none of the new
    keys, and keeps having none until the governor's next 8h run rewrites it. The
    receipt must fall back to the documented base, never to null or to zero."""
    bd = _breakdown()  # no base_ceiling / surge_ceiling / ceiling_window
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())

    # #2898: the third term is the GOVERNOR's constant, not a hand-typed 150.0 — this
    # assertion is the pin that the fail-closed fallback really is the governor's base,
    # and pinning it to a literal is what made moving the base a 26-file sweep.
    assert d["base_ceiling_usd"] == sai._ADR133_BASE_CEILING_USD == _gov().MONTHLY_CEILING
    assert d["surge_ceiling_usd"] is None, "a surge ceiling the governor never stated must not be invented"
    assert d["ceiling_window"] is None


def test_garbled_envelope_costs_the_envelope_not_the_receipt(monkeypatch):
    bd = _breakdown(base_ceiling="not-a-number", surge_ceiling=[], ceiling_window="nope")
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())

    assert d["base_ceiling_usd"] == sai._ADR133_BASE_CEILING_USD
    assert d["surge_ceiling_usd"] is None and d["ceiling_window"] is None
    assert d["month_to_date_usd"] == 26.11  # the rest of the receipt survives


def test_incomplete_window_descriptor_yields_no_half_sentence(monkeypatch):
    """A window missing its revert target can't be explained — say nothing rather
    than emit a sentence with a hole in it."""
    bd = _breakdown(base_ceiling=115.0, ceiling_window={"start": "2026-07-01", "end_exclusive": "2026-08-01"})
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert "dated window" not in d["note"]


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
    from ai import budget_guard

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


# ══════════════════════════════════════════════════════════════════════════════
# #3555 — the withholding reason has to be TRUE
#
# This key used to read: "Per-feature usage is reported in tokens, not dollars: the
# per-Lambda metric stream carries no model dimension, so pricing it would mean
# inventing a model mix." Every clause of that is false of this platform.
# `ai.bedrock_client._emit_usage_metrics` computes `estimate_cost_usd(usage, model_id)`
# — the model IS known at the chokepoint — and emits `EstimatedCostUSD{LambdaFunction}`
# from it. That landed 2026-06-16 (#142); the sentence was written 2026-07-21 (#1616),
# five weeks later. Measured on the live account 2026-09-05, one GetMetricData over the
# month returns daily-brief $2.4479, visual-ai-qa $1.7060, remediation-agent $1.5824 …
# and the per-LambdaFunction sum ($9.2349) equals the per-CallerClass sum to the cent,
# i.e. attribution is complete, not partial.
#
# A withholding excuse that misstates the system's own capability is the same ADR-104
# failure as a flattering number, so it is guarded the same way: a phrase list that
# must NOT appear, and a positive control proving the detector can fire.
# ══════════════════════════════════════════════════════════════════════════════
_DISPROVED_REASON_PHRASES = ("model dimension", "model mix", "inventing a model")


def _false_reason_hits(note: str) -> list:
    """Pure detector: which disproved-claim phrases a note contains (#3555)."""
    low = (note or "").lower()
    return [p for p in _DISPROVED_REASON_PHRASES if p in low]


def test_the_false_withholding_reason_detector_actually_fires():
    """Positive control FIRST (the check_doc_facts house rule). Without this, a green
    assertion below could mean "the phrase list never matched anything"."""
    old_note = (
        "Per-feature usage is reported in tokens, not dollars: the per-Lambda metric "
        "stream carries no model dimension, so pricing it would mean inventing a model mix."
    )
    assert _false_reason_hits(old_note) == list(_DISPROVED_REASON_PHRASES)


def test_per_feature_note_no_longer_states_a_reason_that_was_never_true(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown()))
    note = _payload(sai.handle_receipts())["per_feature_note"]
    assert _false_reason_hits(note) == [], f"the disproved withholding reason is back: {note}"


def test_per_feature_note_states_the_limit_that_is_real(monkeypatch):
    """Not simply deleting the excuse: the honest limits are self-metering (an estimate
    against list prices, reconciled to the native meter) and the row being a LAMBDA
    rather than a budget_guard feature — which is why several ledger rows are ungraded."""
    _install(monkeypatch, _ssm_with(_breakdown()))
    note = _payload(sai.handle_receipts())["per_feature_note"].lower()
    assert "self-metered" in note
    assert "estimate" in note and "billed figure" in note
    assert "lambda" in note and "feature" in note


# ══════════════════════════════════════════════════════════════════════════════
# #3554 — a projection may not wear a label broader than its scope
#
# Live 2026-09-05T06:57Z: /api/receipts served `projected_month_end_usd 83.7`,
# `projected_pct_of_ceiling 33.2`, tier 0/green, and NO scope field, while
# /life-platform/budget-breakdown one hop upstream carried `projected_all_classes
# 103.49`, `prod_class_share 0.6956`, `projected_classes ['prod-cron','remediation']`
# and `episodic_classes ['ci','dev-session']`. The published figure extrapolates only
# the recurring caller classes (#2892 — the right input for the tier ladder) and was
# printed under the bare label "projected month-end".
#
# Derivation of both numbers from that same payload, for the record:
#   days_remaining = 30 - 4 = 26
#   all classes:  13.8 + (0.95 + 2.50) * 26            = 103.5   (payload: 103.49)
#   recurring:    13.8 + (0.95 + 2.50 * 0.6956) * 26   =  83.7   (payload:  83.70)
# ══════════════════════════════════════════════════════════════════════════════
_SCOPED = {
    "prod_class_share": 0.6956,
    "projected_all_classes": 103.49,
    "projected_classes": ["prod-cron", "remediation"],
    "episodic_classes": ["ci", "dev-session"],
}
# The effective ceiling on the day the defect was captured — DERIVED, never hand-typed
# (#2898 binds tests too). Reader traffic was 1,011 uniques/7d against the 900 threshold,
# so the surge ceiling was in force.
_LIVE_CEILING = importlib.import_module("operational.cost_governor_lambda").SURGE_CEILING_USD


def _scope_contract_violations(payload: dict) -> list:
    """Pure decision function: the ways a receipts payload can publish a narrow number
    under a broad label. Takes the payload as an argument and reads nothing else, so the
    RULE can be mutation-proved against a synthetic pre-#3554 payload."""
    bad = []
    if payload.get("projected_month_end_usd") is None:
        return bad  # nothing published, nothing to mislabel
    if not payload.get("projected_scope"):
        bad.append("projection published with no scope")
    if payload.get("projected_all_classes_usd") is None:
        bad.append("no all-class projection published beside the narrowed one")
    if not payload.get("projection_note"):
        bad.append("no reader-facing statement of what the projection covers")
    if payload.get("projected_all_classes_usd") is not None and payload.get("projected_all_classes_pct_of_ceiling") is None:
        bad.append("all-class figure published with no percentage beside its sibling")
    return bad


def test_the_scope_contract_detector_reds_on_the_pre_fix_payload():
    """The negative control: reintroduce the defect as a payload and the rule must fail.
    These are the exact keys the live endpoint served on 2026-09-05."""
    pre_fix = {"projected_month_end_usd": 83.7, "projected_pct_of_ceiling": 33.2}
    assert _scope_contract_violations(pre_fix), "the scope rule cannot fail — it guards nothing"
    assert len(_scope_contract_violations(pre_fix)) == 3
    # …and the fourth leg, on a payload that publishes the all-class dollar figure but
    # leaves the reader to divide it by the ceiling themselves.
    half_fixed = dict(pre_fix, projected_scope="x", projection_note="y", projected_all_classes_usd=103.49)
    assert _scope_contract_violations(half_fixed) == ["all-class figure published with no percentage beside its sibling"]


def test_the_projection_never_ships_without_its_scope(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown(**_SCOPED)))
    d = _payload(sai.handle_receipts())
    assert _scope_contract_violations(d) == []


def test_both_projections_ship_with_the_ceiling_percentage_of_each(monkeypatch):
    bd = _breakdown(projected=83.7, ceiling=_LIVE_CEILING, **_SCOPED)
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert d["projected_month_end_usd"] == 83.7
    assert d["projected_all_classes_usd"] == 103.49
    assert d["projected_pct_of_ceiling"] == round(83.7 / _LIVE_CEILING * 100, 1)
    assert d["projected_all_classes_pct_of_ceiling"] == round(103.49 / _LIVE_CEILING * 100, 1)
    # …and the two percentages are genuinely different, or this asserts nothing.
    assert d["projected_all_classes_pct_of_ceiling"] > d["projected_pct_of_ceiling"] + 5
    # Both figures are the governor's own; neither is recomputed here.
    assert d["projected_classes"] == ["prod-cron", "remediation"]
    assert d["episodic_classes"] == ["ci", "dev-session"]


def test_the_scope_label_names_the_classes_that_are_and_are_not_extrapolated(monkeypatch):
    _install(monkeypatch, _ssm_with(_breakdown(**_SCOPED)))
    d = _payload(sai.handle_receipts())
    assert "recurring" in d["projected_scope"]
    assert "prod-cron" in d["projected_scope"] and "remediation" in d["projected_scope"]
    note = d["projection_note"]
    assert "ci" in note and "dev-session" in note
    assert "103.49" in note, "the all-class figure must be stated in prose, not only as a field"


def test_no_caller_class_signal_is_stated_as_all_classes_not_as_a_narrowing(monkeypatch):
    """`prod_class_share is None` is the governor's own "no attribution this run" marker,
    and in that case `projected` IS the all-class figure by construction. Claiming a
    narrowing that did not happen would be the inverse of this issue's defect."""
    bd = _breakdown(projected=90.0, prod_class_share=None, projected_all_classes=90.0)
    bd["projected_classes"] = ["prod-cron", "remediation"]
    bd["episodic_classes"] = ["ci", "dev-session"]
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert d["projected_scope"] == "all spend classes"
    assert "all spend classes" in d["projection_note"]
    assert "recurring" not in d["projected_scope"]


# ── #3554 AC3: the premise the narrowing rests on, surfaced ──────────────────
def test_a_broken_episodic_premise_reaches_the_reader(monkeypatch):
    """An "episodic" class that bills on ~every day of the window is not episodic, and
    the exclusion it justifies is then under-projecting. The page says so."""
    bd = _breakdown(
        **_SCOPED,
        episodic_billing_days={"prod-cron": 30, "ci": 28, "dev-session": 4, "remediation": 13},
        episodic_premise_window_days=30,
        episodic_premise_bar_days=25,
        episodic_premise_violations=["ci"],
    )
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert d["episodic_premise_violations"] == ["ci"]
    assert "28 of the last 30 days" in d["projection_note"]
    assert d["episodic_billing_days"]["ci"] == 28


def test_an_intact_premise_adds_no_alarming_prose(monkeypatch):
    """The negative control for the clause above: a genuinely episodic class must not
    produce a warning, or the warning stops meaning anything."""
    bd = _breakdown(
        **_SCOPED,
        episodic_billing_days={"prod-cron": 30, "ci": 6, "dev-session": 2, "remediation": 13},
        episodic_premise_window_days=30,
        episodic_premise_bar_days=25,
        episodic_premise_violations=[],
    )
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert d["episodic_premise_violations"] == []
    assert "Premise check" not in d["projection_note"]


def test_an_unreadable_premise_measurement_says_so_rather_than_passing(monkeypatch):
    """A failed metric read records None, not 0 — absence must never render as a clean
    bill of health for the label."""
    bd = _breakdown(
        **_SCOPED,
        episodic_billing_days={"ci": None, "dev-session": None},
        episodic_premise_window_days=30,
        episodic_premise_bar_days=25,
        episodic_premise_violations=[],
    )
    _install(monkeypatch, _ssm_with(bd))
    d = _payload(sai.handle_receipts())
    assert "unavailable this run" in d["projection_note"]


def test_a_stale_breakdown_publishes_no_scope_figures_either(monkeypatch):
    """The staleness rule is the page's oldest honesty contract; the new fields join it
    rather than becoming the one number that quietly freezes."""
    _install(monkeypatch, _ssm_with(_breakdown(age_hours=72, **_SCOPED)))
    d = _payload(sai.handle_receipts())
    assert d["stale"] is True
    assert d["projected_month_end_usd"] is None
    assert d["projected_all_classes_usd"] is None
    assert d["projected_scope"] is None


# ── /api/status reads the same scope, so the two surfaces cannot disagree ────
def test_status_cost_block_carries_the_same_scope(monkeypatch):
    from ai import budget_guard

    bd = _breakdown(projected=83.7, ceiling=_LIVE_CEILING, tier=0, **_SCOPED)
    monkeypatch.setattr(budget_guard, "read_breakdown", lambda *a, **k: bd)
    block = sai._budget._budget_cost_block()
    assert block["projected"] == 83.7
    assert block["projected_all_classes"] == 103.49
    assert "recurring" in block["projected_scope"]
    assert block["pct_of_budget"] == round(83.7 / _LIVE_CEILING * 100)
    assert block["pct_of_budget_all_classes"] == round(103.49 / _LIVE_CEILING * 100)


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


# ── the schema baselines pin the new fields (#3554 / #3555) ──────────────────
def _snapshot(slug):
    return json.loads((Path(__file__).resolve().parent / "api_schemas" / f"{slug}.json").read_text())["shape"]["keys"]


def test_receipts_schema_baseline_pins_the_scope_fields():
    """The contract baseline, not just the handler: a later PR that drops a scope field
    from the payload has to drop it here too, which is a reviewable edit rather than a
    silent regression to a narrow number under a broad label."""
    keys = _snapshot("api_receipts")
    for k in (
        "projected_month_end_usd",
        "projected_all_classes_usd",
        "projected_all_classes_pct_of_ceiling",
        "projected_scope",
        "projected_classes",
        "episodic_classes",
        "episodic_billing_days",
        "episodic_premise_violations",
        "projection_note",
    ):
        assert k in keys, f"api_receipts.json no longer pins {k}"


def test_inference_receipt_schema_baseline_pins_the_dollar_column():
    keys = _snapshot("api_inference_receipt")
    assert "month_est_cost_usd" in keys["features"]["items"]["keys"], "the per-feature dollar field left the contract"
    assert "attribution" in keys
    for k in ("reconciliation_ratio", "drift_bar", "unattributed_usd", "note"):
        assert k in keys["attribution"]["keys"]


def test_the_served_payload_supplies_every_scope_key_the_baseline_pins(monkeypatch):
    """Fixture must be the wire: the two assertions above are about a committed FILE, so
    without this one they could both pass against a handler that publishes none of it."""
    _install(monkeypatch, _ssm_with(_breakdown(**_SCOPED)))
    served = _payload(sai.handle_receipts())
    baseline = set(_snapshot("api_receipts"))
    scope_keys = {k for k in baseline if k.startswith(("projected_", "episodic_", "projection_"))}
    assert scope_keys <= set(served), f"handler omits pinned keys: {sorted(scope_keys - set(served))}"
