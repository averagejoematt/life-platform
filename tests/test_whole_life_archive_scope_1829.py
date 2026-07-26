"""test_whole_life_archive_scope_1829.py — the archive block's scope claim is TRUE.

#1829: both call sites of the #1385 whole-life archive pass ADR-058's
`with_phase_filter`, so the read is default-deny — chronicle is EXPERIMENT_SCOPED and
every reset re-stamps prior installments to pilot/tombstoned. Live after the cycle-11
reset: 18 installments, exactly 3 survive the filter (all cycle 11). The block
nevertheless opened with

    "=== THE MEASURED LIFE — FULL MULTI-CYCLE ARCHIVE (every prior installment, oldest first) ==="

handing Elena / State of Matthew a false completeness claim inside a 1h-cached system
block. The dangerous output is a DIGIT-FREE universal — "across every week on record he
has never…" — which is fabricated-by-omission and invisible to the number/date grounding
gate. The failure was also invisible in logs (a bare count).

Posture taken (issue fix-direction (a), truth-in-labeling): the default-deny read is the
sanctioned reset posture (ADR-058 + ADR-077 curation) and is UNCHANGED. What changes is
that the header is derived from the items actually present and explicitly forbids
completeness claims beyond them, and both call sites log the real scope.

Hermetic — pure string/dict assertions.

Run with:   python3 -m pytest tests/test_whole_life_archive_scope_1829.py -v
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import whole_life_context as wlc  # noqa: E402


def _inst(date, *, cycle, week, body="body text"):
    item = {"date": date, "week_number": week, "title": f"Week {week}", "content_markdown": body}
    if cycle is not None:
        item["cycle"] = cycle
    return item


# The live post-reset shape: 3 surviving installments, all cycle 11.
POST_RESET = [_inst("2026-07-08", cycle=11, week=1), _inst("2026-07-15", cycle=11, week=2), _inst("2026-07-22", cycle=11, week=3)]


# ── 1. The false completeness claim is gone ──────────────────────────────────
def test_header_no_longer_claims_every_prior_installment():
    text = wlc.format_full_archive(POST_RESET)
    assert "every prior installment" not in text
    assert "FULL MULTI-CYCLE ARCHIVE" not in text


def test_header_states_the_real_count_and_cycles():
    """No invented numbers (ADR-104): the header's facts come from the items present."""
    header = wlc.archive_header(POST_RESET)
    assert "(3 installments, cycle 11; oldest first)" in header  # one cycle ⇒ singular, no implied breadth

    multi = wlc.archive_header(POST_RESET + [_inst("2026-03-04", cycle=10, week=9)])
    assert "(4 installments, cycles 10, 11; oldest first)" in multi


def test_header_forbids_completeness_claims_the_grounding_gate_cannot_catch():
    """The scope caveat is the only defense against a digit-free universal."""
    header = wlc.archive_header(POST_RESET).lower()
    assert "not necessarily every installment ever written" in header
    assert "do not make completeness claims" in header
    assert "he has never once" in header  # the banned phrasing is shown by example


def test_single_installment_header_is_grammatical_and_honest():
    header = wlc.archive_header([_inst("2026-07-22", cycle=11, week=3)])
    assert "1 installment," in header and "1 installments" not in header


# ── 2. archive_scope reports what is really there ────────────────────────────
def test_archive_scope_counts_cycles_and_unlabeled():
    scope = wlc.archive_scope(POST_RESET + [_inst("2026-03-04", cycle=10, week=9), _inst("2026-02-01", cycle=None, week=1)])
    assert scope == {"count": 5, "cycles": [10, 11], "unlabeled": 1}


def test_archive_scope_ignores_empty_installments_like_the_renderer():
    """Same inclusion rule as `format_full_archive`, so the logged count matches the
    rendered one — a scope log that disagrees with the block would be its own defect."""
    items = POST_RESET + [{"date": "2026-06-01", "cycle": 11, "content_markdown": "   "}]
    assert wlc.archive_scope(items)["count"] == 3
    assert wlc.format_full_archive(items).count("--- ") == 3


def test_archive_scope_survives_a_junk_cycle_stamp():
    assert wlc.archive_scope([_inst("2026-07-22", cycle="eleven", week=3)]) == {"count": 1, "cycles": [], "unlabeled": 1}


def test_no_cycle_stamps_says_so_rather_than_guessing():
    header = wlc.archive_header([_inst("2026-07-22", cycle=None, week=3)])
    assert "no cycle stamps" in header


# ── 3. Nothing else about the block regressed ────────────────────────────────
def test_body_is_still_oldest_first_and_untruncated():
    installments = [
        {"cycle": 2, "week_number": 1, "date": "2026-07-01", "title": "New start", "content_markdown": "B" * 5000},
        {"cycle": 1, "week_number": 3, "date": "2026-05-08", "title": "The plunge", "content_markdown": "A" * 5000},
    ]
    text = wlc.format_full_archive(installments)
    assert text.index("The plunge") < text.index("New start")
    assert "A" * 5000 in text and "B" * 5000 in text


def test_empty_archive_still_renders_nothing():
    """Honest absence: no items ⇒ no block, and therefore no scope claim at all."""
    assert wlc.format_full_archive([]) == ""
    assert wlc.archive_scope([]) == {"count": 0, "cycles": [], "unlabeled": 0}


def test_elision_note_still_fires_and_the_header_counts_all_in_scope_items():
    """Over-budget path: the header describes the SCOPE, the note describes the cut —
    the two together stay true."""
    items = [_inst(f"2026-0{(i % 9) + 1}-0{(i % 9) + 1}", cycle=11, week=i, body="X" * 400) for i in range(10)]
    text = wlc.format_full_archive(items, max_chars=2000)
    assert "10 installments" in text
    assert re.search(r"\[\d+ older installment\(s\) elided", text)


# ── 4. Both call sites log the real scope ────────────────────────────────────
def test_both_call_sites_log_the_actual_scope_not_a_bare_count():
    for rel in (
        os.path.join("lambdas", "emails", "wednesday_chronicle_lambda.py"),
        os.path.join("lambdas", "compute", "state_of_matthew_lambda.py"),
    ):
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert "archive_scope(" in src, f"{rel} still logs a bare installment count"
        assert "cycles=" in src
