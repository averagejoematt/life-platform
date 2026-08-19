"""tests/test_doc_facts_budget_2899.py — the ceiling half of the doc-facts gate.

#2899. `scripts/check_doc_facts.py` reported "✅ no live doc/source states a stale
count/budget" across 122 docs + 416 source files while three docs still stated the
retired $85 as current truth. The issue guessed the cause was markdown formatting
(bold / table cells / blockquotes). It was not — bold matched fine. Reproducing each
site against the real matcher found THREE DIFFERENT mechanisms:

  1. docs/ARCHITECTURE.md:89  — the regex DID find $85. The line also said "raised
     from $75", and the exemption was per-LINE, so the historical framing of one
     figure exempted the stale CURRENT figure beside it.
  2. docs/INFRASTRUCTURE.md:16 — the regex found NOTHING. "$85/month all-in" carries
     no budget/ceiling/cap/guardrail word within the 20-char window, so the pattern
     never fired at all.
  3. docs/COST_TRACKER.md:7   — the regex WOULD have flagged it. The file is on the
     gate's own EXEMPT_FILES skip list — so the one doc the gate names as the
     canonical spend ledger was the one doc whose ceiling nothing checked.

Each mechanism gets its own fixture below, because a fix for one is not a fix for
the others. The charter's gate rule is the bar: a gate that cannot fail is a green
light wired to nothing, so every fixture is a PLANTED defect asserted to flag.
"""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_cdf", ROOT / "scripts" / "check_doc_facts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def facts():
    return _load()


# ── Mechanism 1: the per-LINE exemption swallowed a current claim ─────────────

ARCHITECTURE_89 = "**$85/mo all-in cap** (ADR-063, raised from $75 + surge-to-$100 rule per ADR-133)"


def test_historical_framing_does_not_exempt_a_current_claim_on_the_same_line(facts):
    """The measured ARCHITECTURE.md:89 miss. "raised from $75" is legitimate history;
    the "$85 ... cap" beside it is a stale CURRENT claim and must still flag."""
    offenders = facts._budget_offenders(ARCHITECTURE_89)
    assert 85 in offenders, f"the stale current $85 must flag, got {offenders}"


def test_the_historical_figure_on_that_same_line_is_still_exempt(facts):
    """Precision half: fixing mechanism 1 must not start flagging real history.
    $75 is framed by "raised from" and leads a "-> " transition; it must stay silent."""
    assert 75 not in facts._budget_offenders(ARCHITECTURE_89)


@pytest.mark.parametrize(
    "line",
    [
        "the ceiling was $85 all-in",
        "budget ceiling $85 -> $150",
        "budget ceiling $85 → $150",
        "raised the cap from $85",
        "the $75 reference ceiling",  # _THRESHOLD_REFERENCE_CEILING, a live constant
        "budget ceiling $85 <!-- drift-ok: quoting the pre-ADR-133 ladder -->",
    ],
)
def test_genuine_history_is_not_flagged(facts, line):
    """Guard the SET of exemption shapes, not one instance — prefix framing, both
    arrow glyphs, the reference-ceiling postfix, and the documented drift-ok hatch."""
    assert facts._budget_offenders(line) == [], line


# ── Mechanism 2: no trigger word near the figure, so nothing matched ──────────

INFRASTRUCTURE_16 = "$85/month all-in, **enforced** (… floats to $100 on reader-traffic surge)"


def test_all_in_phrasing_is_matched_at_all(facts):
    """The measured INFRASTRUCTURE.md:16 miss: the old vocabulary
    (budget|ceiling|cap|guardrail) found ZERO matches on this line."""
    assert 85 in facts._budget_offenders(INFRASTRUCTURE_16)


def test_per_user_projection_is_not_mistaken_for_a_ceiling(facts):
    """Precision: widening the vocabulary must not swallow the shape the 20-char
    window exists to protect — a per-user cost projection that merely says /month."""
    assert facts._budget_offenders("projected spend of $405/month per active reader") == []


# ── Mechanism 3: the canonical ledger was on the gate's own skip list ─────────

COST_TRACKER_7 = "> Budget ceiling: **$85/month all-in** base, floating to **$100 in surge mode**"


def test_cost_tracker_ceiling_is_scanned_despite_the_file_being_exempt(facts, tmp_path):
    """docs/COST_TRACKER.md stays in EXEMPT_FILES (a ledger may state history), but
    its CEILING claim is now scanned explicitly. Without this the canonical spend doc
    is the only one a reader is pointed to and the only one unchecked."""
    doc = tmp_path / "COST_TRACKER.md"
    doc.write_text(f"**Verified:** {dt.date.today().isoformat()}\n\n{COST_TRACKER_7}\n", encoding="utf-8")
    hits = facts._cost_tracker_hits(doc, today=dt.date.today())
    assert any("$85" in h for h in hits), f"the exempt ledger's ceiling claim must flag, got {hits}"


def test_cost_tracker_is_still_exempt_from_the_general_doc_scan(facts):
    """The re-inclusion is targeted. Removing the file from EXEMPT_FILES wholesale
    would flag its historical monthly-actuals rows, which are legitimate history."""
    assert "docs/COST_TRACKER.md" in facts.EXEMPT_FILES


# ── Markdown shapes: asserted, since the issue named them as the suspect ──────


@pytest.mark.parametrize(
    "shape,line",
    [
        ("bold", "The budget ceiling is **$85** all-in"),
        ("table-cell", "| Budget | $85/month all-in, **enforced** | alerts at 50/70/85/100% |"),
        ("blockquote", "> Budget ceiling: **$85/month all-in** base"),
        ("plain", "the $85 budget ceiling"),
    ],
)
def test_planted_defect_flags_in_every_markdown_shape(facts, shape, line):
    """Mutation evidence across formatting. These all pass on the OLD code too —
    formatting was never the defect — but they are pinned so a future precision
    tightening cannot quietly lose them."""
    assert 85 in facts._budget_offenders(line), f"{shape}: {line}"


# ── The second gap: only the BASE was ever checked ────────────────────────────


def test_allowed_set_is_derived_from_the_governor_not_hand_typed(facts):
    """Charter rule 1. The permanent base/surge pair must come from
    cost_governor_lambda.py, so moving the ceiling cannot leave this gate behind."""
    allowed, provenance = facts._governor_ceilings(today=dt.date(2026, 9, 15))
    assert {150, 176} <= allowed, f"base/surge must be parsed from the governor, got {allowed}"
    assert "base/surge" in provenance


def test_dated_window_value_is_allowed_only_while_the_window_is_in_effect(facts):
    """The $115-for-twelve-days defect. BUDGET_OK held only the permanent base, so
    nothing had an opinion about the figure actually in force. The window pair is now
    allowed inside its dates and flagged outside them — an auto-revert matching the
    governor's own, with no deploy and nobody having to remember."""
    inside, _ = facts._governor_ceilings(today=dt.date(2026, 8, 15))
    outside, _ = facts._governor_ceilings(today=dt.date(2026, 9, 1))  # window end is exclusive

    assert {200, 235} <= inside, f"August's raised window must be allowed inside it, got {inside}"
    assert 200 not in outside and 235 not in outside, f"September must reject August's window, got {outside}"

    line = "the budget ceiling is $200 all-in"
    assert facts._budget_offenders(line, allowed=inside) == []
    assert 200 in facts._budget_offenders(line, allowed=outside)


# ── Non-vacuity + the live integration assertion ──────────────────────────────


def test_the_scan_surface_is_non_empty(facts):
    """A floored surface, in the style of test_pacific_today_guard_2414.py: every
    assertion above is worthless if the real gate walks zero files."""
    assert len(facts._scan_files()) >= 50
    assert len(facts._scan_source_files()) >= 50


def test_live_repo_states_no_stale_ceiling(facts):
    """The integration half: the real corpus must be clean under the widened gate."""
    hits = [h for h in facts._cost_tracker_hits(ROOT / "docs" / "COST_TRACKER.md") if "budget ceiling claims" in h]
    for doc in facts._scan_files():
        for line in doc.read_text(encoding="utf-8").splitlines():
            hits += [f"{doc.relative_to(ROOT)}: ${a}" for a in facts._budget_offenders(line)]
    assert hits == [], "live docs state a stale ceiling:\n" + "\n".join(hits)
