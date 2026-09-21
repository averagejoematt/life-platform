"""tests/test_reset_price_3601.py — the PRICE of a reset, and the close that prints it (#3601 box 1+2).

WHAT THIS GUARDS. `docs/PROPORTIONALITY.md` priced the reset MACHINERY and never priced
the reset EVENT, so every reset-machinery demote trigger in that ledger multiplied a
cadence by a price nobody had measured. `deploy/restart_cost_model.py` is that price.
The failure mode it must not have is the one the ledger already demonstrated once with
"a few times a quarter": a confident number with no derivation behind it.

So the assertions below are mostly about PROVENANCE, not arithmetic:

  * every component names a basis (measured / registry-priced / bounded-estimate), an n,
    and a source — a dollar figure without one raises rather than prints (must-fail
    controls in both directions);
  * an empty model is an ERROR, never "$0.00 per reset" — the vacuous-pass class;
  * "no datapoints in the window" is an ERROR, never a measured zero — `measure_marginal`
    must be unable to report an absent series as free;
  * the ledger row quotes the MODEL's numbers, computed here from the module, so the doc
    and its source cannot drift into two numbers (the #3601 defect, re-instantiated).

THE ONE MEASURED ZERO IS DELIBERATE AND IS ASSERTED AS SUCH. `reader-truth-qa` carries
`usd=0.0`: #3601 assumed a reset buys a truth pass, and the measurement says it does not
(median delta −$0.023, inside the day-to-day band). That component is kept at zero rather
than deleted, because a refuted assumption that leaves no trace gets re-assumed.
"""

from __future__ import annotations

import datetime
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "deploy", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import restart_cost_model as rcm  # noqa: E402


# ── the model prices itself honestly, or not at all ──────────────────────────
def test_the_model_prices_a_reset_at_a_positive_sum_of_its_components():
    rcm.validate()
    assert rcm.total_usd() == round(sum(c.usd for c in rcm.RESET_COST_COMPONENTS), 4)
    assert rcm.total_usd() > 0, "a reset is not free; a zero total here means the components went missing"
    assert rcm.high_usd() >= rcm.total_usd(), "the worst case cannot be under the planning figure"


def test_MUST_FAIL_an_empty_model_is_an_ERROR_not_a_price_of_zero(monkeypatch):
    """The vacuous pass: a component tuple that parses empty would print `$0.00 per reset`
    with total confidence. Opposite facts must not render identically."""
    monkeypatch.setattr(rcm, "RESET_COST_COMPONENTS", ())
    with pytest.raises(ValueError) as e:
        rcm.validate()
    assert "EMPTY" in str(e.value)


def test_MUST_FAIL_a_component_with_no_source_or_no_n_is_REFUSED(monkeypatch):
    """The defect in one assertion: a dollar figure lands in the ledger with nothing
    behind it — exactly what `a few times a quarter` was."""
    good = rcm.RESET_COST_COMPONENTS[0]
    for field in ("source", "n"):
        monkeypatch.setattr(rcm, "RESET_COST_COMPONENTS", (replace(good, **{field: "  "}),))
        with pytest.raises(ValueError) as e:
            rcm.validate()
        assert "unsourced numbers do not ship" in str(e.value)


def test_MUST_FAIL_an_unknown_basis_is_REFUSED(monkeypatch):
    monkeypatch.setattr(rcm, "RESET_COST_COMPONENTS", (replace(rcm.RESET_COST_COMPONENTS[0], basis="vibes"),))
    with pytest.raises(ValueError) as e:
        rcm.validate()
    assert "'vibes'" in str(e.value)


def test_MUST_FAIL_a_high_below_the_planning_figure_is_REFUSED(monkeypatch):
    monkeypatch.setattr(rcm, "RESET_COST_COMPONENTS", (replace(rcm.RESET_COST_COMPONENTS[0], usd=1.0, high_usd=0.5),))
    with pytest.raises(ValueError):
        rcm.validate()


def test_MUST_FAIL_dropping_the_non_cash_costs_is_REFUSED(monkeypatch):
    """The cash price alone misrepresents a reset by an order of magnitude. The module
    must not be able to publish the dollars with the operator session and the defect
    surface quietly removed."""
    monkeypatch.setattr(rcm, "NON_CASH_COSTS", ())
    with pytest.raises(ValueError) as e:
        rcm.validate()
    assert "misrepresents" in str(e.value)


def test_every_measured_component_names_the_platforms_own_cost_instrument():
    measured = [c for c in rcm.RESET_COST_COMPONENTS if c.basis == rcm.BASIS_MEASURED]
    assert measured, "a model with no measured component is an estimate wearing a measurement's clothes"
    for c in measured:
        assert rcm.METRIC_NAME in c.source, f"{c.name}: a 'measured' basis must cite {rcm.METRIC_NAME}, not prose"
        assert "n=" in c.n, f"{c.name}: ADR-105 — a measured number states its n"


def test_the_refuted_assumption_is_KEPT_as_a_measured_zero():
    truth = [c for c in rcm.RESET_COST_COMPONENTS if "truth" in c.name]
    assert len(truth) == 1, "the reader-truth-qa component was deleted; a refuted assumption with no trace gets re-assumed"
    assert truth[0].usd == 0.0 and truth[0].basis == rcm.BASIS_MEASURED


def test_per_quarter_is_the_price_of_a_CADENCE_not_of_one_event():
    assert rcm.per_quarter_usd(9.2) == round(rcm.total_usd() * 9.2, 2)
    assert rcm.per_quarter_usd(3.0) < rcm.per_quarter_usd(9.2), "the 30-day rule's whole point is that the cadence is the multiplier"


def test_the_frozen_measurement_goes_STALE_and_the_printout_says_so():
    """A frozen number with no expiry becomes folklore — the exact rot #3601 was filed on."""
    fresh = rcm.MEASURED_AT + datetime.timedelta(days=rcm.STALE_AFTER_DAYS)
    stale = rcm.MEASURED_AT + datetime.timedelta(days=rcm.STALE_AFTER_DAYS + 1)
    assert rcm.is_stale(fresh) is False
    assert rcm.is_stale(stale) is True
    assert not any("STALE" in ln for ln in rcm.format_lines(fresh))
    assert any("STALE" in ln for ln in rcm.format_lines(stale))


# ── the live re-derivation: absence is not zero ──────────────────────────────
class _FakeCW:
    def __init__(self, daily):
        self._daily = daily
        self.calls = []

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        return {"Datapoints": [{"Timestamp": datetime.datetime.fromisoformat(d + "T00:00:00"), "Sum": v} for d, v in self._daily.items()]}


def test_measure_marginal_reports_an_ABSENT_series_as_an_error():
    out = rcm.measure_marginal(_FakeCW({}), "visual-ai-qa", ("2026-09-05",), datetime.date(2026, 9, 1), datetime.date(2026, 9, 10))
    assert "error" in out and "not a zero" in out["error"]


def test_measure_marginal_reports_a_window_with_no_baseline_as_an_error():
    daily = {"2026-09-05": 1.0}
    out = rcm.measure_marginal(_FakeCW(daily), "f", ("2026-09-05",), datetime.date(2026, 9, 1), datetime.date(2026, 9, 10))
    assert "error" in out and "a delta needs both" in out["error"]


def test_measure_marginal_computes_a_MARGINAL_delta_not_a_day_total():
    """The control that matters: a reset day's TOTAL is dominated by the attended session
    that ran the reset. Charging the total would price the operator, not the event."""
    daily = {"2026-09-01": 0.10, "2026-09-02": 0.20, "2026-09-03": 0.30, "2026-09-05": 0.70}
    out = rcm.measure_marginal(_FakeCW(daily), "f", ("2026-09-05",), datetime.date(2026, 9, 1), datetime.date(2026, 9, 10))
    assert out["baseline_median"] == 0.2 and out["baseline_n"] == 3
    assert out["delta_median"] == 0.5, "the delta is reset-day minus baseline, not the reset day's total (0.70)"


def test_measure_marginal_is_READ_ONLY():
    cw = _FakeCW({"2026-09-01": 0.1, "2026-09-05": 0.2})
    rcm.measure_marginal(cw, "f", ("2026-09-05",), datetime.date(2026, 9, 1), datetime.date(2026, 9, 10))
    assert cw.calls and all(
        set(c) <= {"Namespace", "MetricName", "Dimensions", "StartTime", "EndTime", "Period", "Statistics"} for c in cw.calls
    )


# ── the ledger row and the close quote the MODEL, not a second copy ──────────
def test_the_PROPORTIONALITY_row_quotes_the_MODEL_and_cannot_drift():
    row = (ROOT / "docs" / "PROPORTIONALITY.md").read_text(encoding="utf-8")
    assert f"${rcm.total_usd():.2f} cash per reset" in row, "the ledger's $/reset is no longer the model's number"
    assert f"worst observed ${rcm.high_usd():.2f}" in row
    assert "restart_cost_model.py" in row, "the row must name the derivation, not just the figure"
    assert "30-day minimum cycle length" in row, "the row must carry the ruling the price is buying down (#3606 ruling 1)"
    assert "Demote trigger:" in row


def test_MUST_FAIL_a_reset_on_the_first_of_the_NEXT_month_is_not_in_this_close(tmp_path, monkeypatch):
    """The window is half-open, `[start, end)`, because `_month_window()` hands every
    query in the close the FIRST of the next month as `end`.

    Found by running the real close for August 2026: it listed `2026-09-01` among
    August's resets. A `<=` here does not just miscount — it double-counts that reset in
    two consecutive closes, and each close's `reset spend this month` line is wrong in
    opposite directions."""
    import monthly_close

    geneses = 'CYCLE_GENESES = {\n    1: "2026-08-17",\n    2: "2026-09-01",\n}\n'
    root = _fake_tree(tmp_path, "1 findings CONFIRMED\n", geneses)
    monkeypatch.setattr(monthly_close, "_REPO_ROOT", str(root))
    aug = monthly_close.reset_cadence(datetime.date(2026, 8, 1), datetime.date(2026, 9, 1), today=datetime.date(2026, 9, 20))
    sep = monthly_close.reset_cadence(datetime.date(2026, 9, 1), datetime.date(2026, 10, 1), today=datetime.date(2026, 9, 20))
    assert aug["in_month_dates"] == ["2026-08-17"], f"a 2026-09-01 re-anchor is not August's: {aug['in_month_dates']}"
    assert sep["in_month_dates"] == ["2026-09-01"]
    assert aug["in_month"] + sep["in_month"] == 2, "each reset belongs to exactly one close"


def test_the_close_prints_the_reset_block_without_touching_AWS():
    import monthly_close

    lines, problems = monthly_close.reset_block_lines(datetime.date(2026, 9, 1), datetime.date(2026, 10, 1))
    assert problems == [], f"the reset block reported problems: {problems}"
    text = "\n".join(lines)
    assert "resets this month" in text
    assert "$/reset (model)" in text and f"${rcm.total_usd():.2f}" in text
    assert "findings per reset" in text
    assert "DEMOTE-candidate list" in text, "the fourth line must be NAMED as missing, not silently absent"
    assert "reset spend this month" in text


def test_the_close_and_the_model_report_ONE_price():
    import monthly_close

    rp = monthly_close.reset_price()
    assert not rp.get("error"), rp
    assert rp["usd"] == rcm.total_usd() and rp["high_usd"] == rcm.high_usd()


def test_MUST_FAIL_a_model_that_refuses_to_price_itself_surfaces_in_the_close(monkeypatch):
    import monthly_close

    monkeypatch.setattr(rcm, "RESET_COST_COMPONENTS", ())
    rp = monthly_close.reset_price()
    assert "REFUSED to price itself" in rp.get("error", "")
    lines, problems = monthly_close.reset_block_lines(datetime.date(2026, 9, 1), datetime.date(2026, 10, 1))
    assert any(label == "RESET-PRICE" for label, _ in problems), "a broken price model must make the close exit non-zero"


# ── findings per reset: a rate, with a stated window ─────────────────────────
def test_findings_per_reset_is_a_rate_over_a_named_review_window():
    import monthly_close

    fpr = monthly_close.findings_per_reset()
    assert not fpr.get("error"), fpr
    assert fpr["review"].startswith("FULLREVIEW_")
    assert fpr["findings"] > 0 and fpr["resets"] > 0
    assert fpr["rate"] == round(fpr["findings"] / fpr["resets"], 1)
    assert "->" in fpr["window"], "a rate with no window is not a rate"


def _fake_tree(tmp_path, review_text, geneses_block):
    (tmp_path / "docs" / "reviews").mkdir(parents=True)
    (tmp_path / "docs" / "reviews" / "FULLREVIEW_2026-08-16_DELTA.md").write_text("prior\n", encoding="utf-8")
    (tmp_path / "docs" / "reviews" / "FULLREVIEW_2026-09-05.md").write_text(review_text, encoding="utf-8")
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    (tmp_path / "lambdas" / "web" / "site_api_data.py").write_text(geneses_block, encoding="utf-8")
    return tmp_path


_REAL_GENESES = 'CYCLE_GENESES = {\n    1: "2026-08-17",\n    2: "2026-09-01",\n}\n'


def test_MUST_FAIL_a_review_with_no_findings_literal_is_an_ERROR_not_a_zero(tmp_path, monkeypatch):
    import monthly_close

    root = _fake_tree(tmp_path, "no count in here at all\n", _REAL_GENESES)
    monkeypatch.setattr(monthly_close, "_REPO_ROOT", str(root))
    out = monthly_close.findings_per_reset()
    assert "error" in out and "not parsed, so not reported as zero" in out["error"]


def test_MUST_FAIL_an_EMPTY_cycle_registry_is_an_ERROR_not_a_cadence_of_zero(tmp_path, monkeypatch):
    import monthly_close

    root = _fake_tree(tmp_path, "7 findings CONFIRMED\n", "CYCLE_GENESES = {\n}\n")
    monkeypatch.setattr(monthly_close, "_REPO_ROOT", str(root))
    assert "parsed EMPTY" in monthly_close.findings_per_reset().get("error", "")
    assert "parsed EMPTY" in monthly_close.reset_cadence(datetime.date(2026, 9, 1), datetime.date(2026, 10, 1)).get("error", "")


def test_the_rate_uses_the_reviews_OWN_window(tmp_path, monkeypatch):
    """A control on the denominator: a genesis outside (prev review, this review] must not
    be counted, or the rate silently improves by widening its window."""
    import monthly_close

    geneses = 'CYCLE_GENESES = {\n    1: "2026-07-01",\n    2: "2026-08-17",\n    3: "2026-09-01",\n    4: "2026-09-30",\n}\n'
    root = _fake_tree(tmp_path, "10 findings CONFIRMED\n", geneses)
    monkeypatch.setattr(monthly_close, "_REPO_ROOT", str(root))
    out = monthly_close.findings_per_reset()
    assert out["resets"] == 2 and out["reset_dates"] == ["2026-08-17", "2026-09-01"], out
    assert out["rate"] == 5.0
