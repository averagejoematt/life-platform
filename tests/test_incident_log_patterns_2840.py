"""tests/test_incident_log_patterns_2840.py — #2840: the patterns section stays derived.

`docs/INCIDENT_LOG.md`'s "Patterns & Observations" was a hand tally of ~32 Feb–Mar rows,
stamped *Verified: 2026-05-19*, that then never moved for three months while the corpus
grew past 140 rows. The three classes dominating the recent record appeared in it nowhere.
Only the "Last updated" line changed per session — a section that looks maintained and is
three months stale.

Re-tallying by hand would buy one correct snapshot and rot identically. So the numbers are
DERIVED (`scripts/incident_log_patterns.py`) and this file fails when the committed prose
disagrees with what the rows actually say. The section cannot silently re-freeze: adding a
row moves a number, and a moved number reds here until the doc is regenerated.

WHY THIS GUARDS THE DERIVATION TOO. The first version of the parser required the severity
cell to be exactly `**Pn**` and silently dropped 18 of 143 rows — the older unbolded `P3`,
the annotated `**P4** (false positive)`, and the non-P `Low`/`**Info**`/`**DR drill**`. A
derivation that quietly discards 13% of its population is the same defect as the frozen
tally it replaces, just harder to see. `test_the_parser_sees_every_dated_row` is the
blindness detector for exactly that (#2578's rule: a derivation returning less than
everything must red, not shrug).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

import incident_log_patterns as ilp  # noqa: E402

DOC = (_REPO / "docs" / "INCIDENT_LOG.md").read_text(encoding="utf-8")
DERIVED = ilp.build()


# ── the derivation must see the whole population ─────────────────────────────


def test_the_parser_sees_every_dated_row():
    """Blindness detector. A bare date-match is the widest possible reading of "a row";
    the real parser must not see fewer, whatever the severity cell happens to say."""
    bare = len(re.findall(r"^\|\s*20\d{2}-\d{2}-\d{2}\s*\|", DOC, re.MULTILINE))
    assert DERIVED["total_rows"] == bare, (
        f"the derivation sees {DERIVED['total_rows']} rows but a bare date-match finds {bare}. "
        "Some row's severity cell is in a shape the parser does not read, and those rows are "
        "silently missing from every number in the Patterns section — the #2840 defect, "
        "reintroduced inside its own fix."
    )


def test_the_derivation_is_not_vacuous():
    """A parser returning nothing would make every committed number trivially wrong but
    could read as 'no incidents'. Zero is never the right answer for this corpus."""
    assert DERIVED["total_rows"] > 100, f"only {DERIVED['total_rows']} rows parsed — the derivation is broken, not the log"
    assert DERIVED["by_class"], "no row matched any root-cause class — the classifier is dead"
    assert DERIVED["silence_axis"]["silent_rows"] > 0, "no silent rows found — the silence detector is dead"


def test_most_rows_are_classified():
    """The classifier is keyword-based over free prose and will never be perfect, but it
    must stay a signal. If most rows stop matching, the distribution below is noise."""
    unclassified = DERIVED["unclassified"]
    total = DERIVED["total_rows"]
    assert (
        unclassified < total / 2
    ), f"{unclassified} of {total} rows match no class — the keyword sets have fallen behind the log's vocabulary"


# ── the committed prose must match the derivation ────────────────────────────


def test_the_row_total_in_the_doc_matches_the_rows():
    assert f"{DERIVED['total_rows']} dated rows" in DOC, (
        f"the Patterns section does not state the live row total ({DERIVED['total_rows']}). "
        "Re-run `python3 scripts/incident_log_patterns.py` and update it."
    )


def test_the_post_june_count_in_the_doc_matches():
    assert (
        f"{DERIVED['post_june_rows']} post-June" in DOC
    ), f"the doc's post-June count is stale — derivation says {DERIVED['post_june_rows']}"


def test_every_month_row_matches_the_derived_count():
    """The per-month table is where staleness shows up first: a new incident lands and the
    month count moves."""
    for month, n in DERIVED["by_month"].items():
        assert f"| {month} | {n} |" in DOC, f"the month table says something other than {n} for {month} — re-run the derivation"


def test_the_three_previously_missing_classes_are_named():
    """The specific defect #2840 was filed for: the classes dominating the post-July record
    appeared nowhere in a section describing Feb–Mar."""
    for name in ("QA-oracle false positive", "lane-subset / union-breach main red", "deploy-plane wedge / strand / race"):
        assert name in DOC, f"{name!r} is a live class in the derivation but is not named in the Patterns section"


def test_the_silence_axis_is_orthogonal_not_a_class():
    """Acceptance box 2. Silence cuts across classes; scoring it as a tenth category would
    hide exactly the cross-class pattern that makes it worth tracking."""
    assert "Silence is an axis, not a class" in DOC
    assert "orthogonal" in DOC.lower()
    silent = DERIVED["silence_axis"]["silent_rows"]
    assert (
        f"**{silent} of {DERIVED['total_rows']}" in DOC or f"{silent} of {DERIVED['total_rows']}" in DOC
    ), f"the doc's silent-row count is stale — derivation says {silent}"


def test_the_ttd_claim_states_its_limits():
    """The honesty requirement (ADR-105). The filed framing — days-scale TTD for silent vs
    minutes for loud — does NOT reproduce over the population; it comes from the worst ~10
    rows, and a third of TTD cells state no parseable duration at all. The section must
    carry the caveat, not just the multiplier."""
    assert (
        "does **not** reproduce" in DOC or "does not reproduce" in DOC
    ), "the section asserts an asymmetry without noting it fails to reproduce over the population"
    assert "no parseable duration" in DOC, "the section does not disclose that a third of TTD cells are unreadable"


def test_pre_july_frequencies_are_marked_as_floors():
    """Acceptance box 4. April is empty and May/June nearly so — under-logging, not
    stability. A reader comparing a pre-July frequency to a post-July one is comparing two
    different instruments."""
    assert "FLOORS" in DOC or "floors" in DOC
    assert "April has zero rows" in DOC


def test_the_row_inclusion_rule_extends_1332():
    """Acceptance box 3. #1332's scope (auto-rollback firings only) is why the timezone
    class read as absent while two live wrong-behaviour fixes shipped."""
    assert "#1332" in DOC
    assert "red main" in DOC or "red a main" in DOC or "a red main" in DOC


def test_the_backfilled_rows_are_present_and_marked():
    """Backfilled rows must be visibly backfilled — a row added months later with no marker
    would make the log's own chronology a lie."""
    assert (
        DOC.count("BACKFILLED 2026-08-21 (#2840)") >= 3
    ), "the three backfilled rows (June Whoop, #2675, #2670) are not all present and marked"
    assert "| 2026-06-08 |" in DOC, "the 2026-06 Whoop row a later P2 cites as precedent is still missing"


def test_the_section_says_it_is_derived():
    """A reader must be able to tell this is regenerated, not hand-maintained — otherwise
    the next person hand-edits a number and the guard's failure looks like a bug."""
    assert "scripts/incident_log_patterns.py" in DOC
    assert "DERIVED" in DOC
