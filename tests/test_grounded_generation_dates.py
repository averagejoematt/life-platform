"""#1242 — fabricated calendar dates must be caught by the grounded-generation gate.

The defect: a full ISO date decomposes into benign small ints + a benign year, so the
ADR-104 number gate (fabricated_numbers) is structurally blind to a wholly invented
date. The wednesday chronicle solved this locally with a legitimate-date allow-list;
this promotes that concept into the shared gate as a distinct token class.

Non-vacuity: `test_iso_date_invisible_to_number_gate` characterizes the exact blindness
this issue fixes (the number gate alone returns [] for an invented date, pre- AND
post-fix — the number gate is deliberately untouched). The real regression guard is
`test_fabricated_iso_date_is_flagged` / `test_fabricated_longform_date_is_flagged`,
which FAIL against pre-#1242 code (grounding_findings had no allowed_dates parameter
and no date awareness) and pass once the date gate lands.

Stdlib-only imports — no layer-only deps at module top (keeps pytest --collect-only clean).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import grounded_generation as gg  # noqa: E402


def test_iso_date_invisible_to_number_gate():
    """Characterization of the defect: the number gate CANNOT see a fabricated date.

    '2026-07-08' tokenizes to {2026, 7, 8} — all benign — so fabricated_numbers
    returns [] even against an empty allow-list. This holds pre- and post-fix because
    the number gate is intentionally left untouched; the date gate is a separate class.
    """
    text = "The turning point came on 2026-07-08."
    assert gg.numbers_in_text(text) == {2026.0, 7.0, 8.0}
    assert gg.fabricated_numbers(text, set()) == []


def test_fabricated_iso_date_is_flagged():
    """A fabricated ISO date not in the allow-list yields a fabricated_date finding."""
    text = "The turning point came on 2026-07-08, when everything shifted."
    allowed = gg.allowed_dates("Week ending: 2026-07-15. The prior update was 2026-07-01.")
    findings = gg.grounding_findings(text, allowed_dates=allowed)
    fab = [f for f in findings if f.get("type") == "fabricated_date"]
    assert len(fab) == 1, findings
    assert fab[0]["claimed"] == "2026-07-08"


def test_fabricated_longform_date_is_flagged():
    """Long-form dates ('July 8, 2026', '8 July 2026') are caught too, normalized to ISO."""
    allowed = gg.allowed_dates("The data packet covers Week ending: 2026-07-15.")
    for text in (
        "It all changed on July 8, 2026, when the streak broke.",
        "The break came on 8 July 2026 without warning.",
    ):
        findings = gg.grounding_findings(text, allowed_dates=allowed)
        fab = [f for f in findings if f.get("type") == "fabricated_date"]
        assert fab and fab[0]["claimed"] == "2026-07-08", (text, findings)


def test_legitimate_iso_date_passes():
    """A date present in the input allow-list produces no fabricated_date finding."""
    text = "The week ending 2026-07-15 was the turning point."
    allowed = gg.allowed_dates("Week ending: 2026-07-15. Earlier: 2026-07-08.")
    findings = gg.grounding_findings(text, allowed_dates=allowed)
    assert [f for f in findings if f.get("type") == "fabricated_date"] == []


def test_legitimate_date_matches_across_formats():
    """An input ISO date grounds a long-form restatement in the output (and vice versa)."""
    text = "Everything turned on July 15, 2026."
    allowed = gg.allowed_dates("Week ending: 2026-07-15.")  # ISO in the input
    findings = gg.grounding_findings(text, allowed_dates=allowed)
    assert [f for f in findings if f.get("type") == "fabricated_date"] == []


def test_partial_date_without_year_is_ignored():
    """A bare 'July 8th' (no year) is a partial token this gate leaves to the weekday check."""
    text = "It happened on July 8th."
    findings = gg.grounding_findings(text, allowed_dates=set())
    assert [f for f in findings if f.get("type") == "fabricated_date"] == []
    assert gg.dates_in_text(text) == set()


def test_invalid_date_is_not_extracted():
    """A non-date like 2026-13-40 is rejected by the calendar validator, not flagged."""
    assert gg.dates_in_text("build 2026-13-40 shipped") == set()


def test_backward_compat_no_allowed_dates_arg():
    """Existing callers (no allowed_dates) keep the exact pre-#1242 behavior: no date check."""
    text = "The turning point came on 2026-07-08."
    # No allowed / no allowed_dates -> no findings at all, as before.
    assert gg.grounding_findings(text) == []
    # allowed (numbers) supplied but allowed_dates omitted -> still no date finding.
    assert [f for f in gg.grounding_findings(text, allowed=set()) if f.get("type") == "fabricated_date"] == []


def test_correction_prompt_covers_fabricated_date():
    """The single-rewrite correction addendum names the fabricated date explicitly."""
    findings = [{"type": "fabricated_date", "claimed": "2026-07-08", "detail": "the date 2026-07-08 appears..."}]
    prompt = gg.correction_prompt(findings)
    assert "2026-07-08" in prompt
    assert "never invent one" in prompt
