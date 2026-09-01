"""#3374 R2 — a month-over-month cost jump must name what grew.

WHY IT EXISTS. Nothing governed cost GROWTH structurally. The platform floor grew +16%
Jul→Aug 2026 (~$43 → $49.77 non-AI) with no gate noticing, and the Bedrock `unknown`
attribution bucket reached $33.19 across 8,524 calls in August before #2888/#2892 closed
it. Both were found by a once-a-quarter diligence panel. A quarterly panel is not a
control; it is an audit of the absence of one.

WHAT THE RULE DOES AND DELIBERATELY DOES NOT DO. It requires a `driver:` token on a
Monthly Actuals row that grew past 1.15x the previous close. It does NOT verify the named
driver is correct — that needs live Cost Explorer, which a docs gate has no business
calling. It makes the operator answer "what grew?" at close time instead of a quarter
later. The #1354 ritual already pulls both facts.

THE THRESHOLD IS NOT A ROUND NUMBER. 1.15 is tuned so the founding incident — the Jul→Aug
floor creep at 1.158 — just trips it. `test_the_threshold_catches_its_own_founding_incident`
is that claim as an executable one. A gate calibrated so its own origin story would have
passed is decoration.
"""

import importlib.util
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("_ops_3374", os.path.join(_REPO, "scripts", "doc_facts_ops.py"))
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

HEADER = "## Monthly Actuals\n\n| Month | AWS Bill | Days at tier >=1 | Notes |\n|---|---|---|---|\n"


def _table(tmp_path, *rows):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "COST_TRACKER.md"
    p.write_text(HEADER + "".join(rows), encoding="utf-8")
    return p


def test_a_quiet_month_needs_no_driver(tmp_path):
    doc = _table(
        tmp_path,
        "| Sep 2026 | **$170.00** (CE actual) | 10 / 30 | Steady. |\n",
        "| Oct 2026 | **$180.00** (CE actual) | 8 / 31 | Steady. |\n",  # 1.06x
    )
    assert ops.monthly_close_driver_hits(doc) == []


def test_a_jump_without_a_driver_token_is_a_hit(tmp_path):
    doc = _table(
        tmp_path,
        "| Sep 2026 | **$170.00** (CE actual) | 10 / 30 | Steady. |\n",
        "| Oct 2026 | **$260.00** (CE actual) | 20 / 31 | Bedrock went up a lot. |\n",  # 1.53x
    )
    (hit,) = ops.monthly_close_driver_hits(doc)
    assert "1.53x" in hit and "2026-10" in hit and "driver:" in hit


def test_the_same_jump_WITH_a_driver_token_passes(tmp_path):
    """The must-pass half. Without it, the rule above could be satisfied by a check that
    flags every row, which would be indistinguishable from working."""
    doc = _table(
        tmp_path,
        "| Sep 2026 | **$170.00** (CE actual) | 10 / 30 | Steady. |\n",
        "| Oct 2026 | **$260.00** (CE actual) | 20 / 31 | driver: Bedrock / ci. |\n",
    )
    assert ops.monthly_close_driver_hits(doc) == []


def test_the_threshold_catches_its_own_founding_incident(tmp_path):
    """The Jul->Aug non-AI floor creep, $43.00 -> $49.77 = 1.158x. It must trip."""
    doc = _table(
        tmp_path,
        "| Sep 2026 | **$43.00** (CE actual) | 0 / 30 | Baseline. |\n",
        "| Oct 2026 | **$49.77** (CE actual) | 0 / 31 | Floor creep, unexplained. |\n",
    )
    assert len(ops.monthly_close_driver_hits(doc)) == 1

    # ...and a jump just BELOW the clause does not, so the threshold is a threshold and
    # not an always-on flag: $43.00 -> $49.00 = 1.140x.
    quiet = _table(
        tmp_path / "quiet",
        "| Sep 2026 | **$43.00** (CE actual) | 0 / 30 | Baseline. |\n",
        "| Oct 2026 | **$49.00** (CE actual) | 0 / 31 | Floor creep, unexplained. |\n",
    )
    assert ops.monthly_close_driver_hits(quiet) == []


def test_rows_before_the_effective_month_are_grandfathered(tmp_path):
    """Mar-Aug 2026 all trip 1.15x, and the CallerClass a `driver:` names only went live
    2026-08-23 (#2892). Demanding it of them would demand a fact that did not exist."""
    doc = _table(
        tmp_path,
        "| Jul 2026 | **$98.35** (CE actual) | 26 / 31 | No driver token here. |\n",
        "| Aug 2026 | **$175.85** (CE actual) | 26 / 31 | Nor here. |\n",  # 1.79x
    )
    assert ops.monthly_close_driver_hits(doc) == []


def test_a_row_with_no_dollar_figure_is_skipped_not_guessed(tmp_path):
    """A 'pending' close must not manufacture a ratio out of nothing."""
    doc = _table(
        tmp_path,
        "| Sep 2026 | **$170.00** (CE actual) | 10 / 30 | Steady. |\n",
        "| Oct 2026 | pending | -- | Close not run yet. |\n",
        "| Nov 2026 | **$400.00** (CE actual) | 30 / 30 | Enormous. |\n",
    )
    # Oct is not a row at all, so Nov is compared against Sep -- and still flagged.
    (hit,) = ops.monthly_close_driver_hits(doc)
    assert "2026-11" in hit and "2026-09" in hit


def test_the_live_cost_tracker_parses_and_currently_passes():
    """Against the real doc, not a fixture. Every historical row is pre-effective, so the
    expected state is zero hits AND a non-empty parse -- a parser that silently matched
    nothing would also report zero hits, which is the shape this second assertion exists
    to separate."""
    rows = ops.monthly_actuals_rows()
    assert len(rows) >= 7, f"the Monthly Actuals parser found only {len(rows)} rows — did the table's shape change?"
    assert [r[1] for r in rows] == sorted(r[1] for r in rows), "rows must be oldest-first for the pairwise delta"
    assert ops.monthly_close_driver_hits() == []
