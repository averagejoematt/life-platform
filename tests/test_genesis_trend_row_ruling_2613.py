"""#2613 — the genesis-dated TREND ROW ruling, and the deterministic rule that makes it safe.

Three consecutive nightlies published a high truth finding on `/api/sleep_detail` at
**Day 3** — a phase #2583's Day-1 genesis clause cannot reach. The qa-smoke log
truncates each finding at 90 chars (`qa_check_reader_truth._fmt`), so the three read
as three defects:

    ... sleep_trend contains three entries dated 2026-08-10, 2026-08-11, and 2026-08-12, but the e…
    ... sleep_trend contains 3 entries (dates 2026-08-10, 2026-08-11, 2026-08-12), but the sleep_s…
    ... sleep_trend contains three rows dated 2026-08-10, 2026-08-11, and 2026-08-12, with the 202…

Reproduced untruncated at the real call site, they are ONE finding:

    "sleep_trend contains a row dated 2026-08-10 with sleep_start timestamp
     2026-08-10T05:05:46.420Z. Per the figure_scope documentation, trend rows are keyed
     by WAKE date, so this row represents the night of 2026-08-09. However, the
     experiment started on 2026-08-10 (Day 1); data from the night of 2026-0…"

THE RULING: **the surface is correct; the check was under-scoped.** The trend clamps to
genesis (ADR-077) and is keyed by WAKE date (#1923), so the earliest row is dated
exactly the cycle start and its bedtime necessarily falls the evening before Day 1.

IT RECURS ON EVERY RESET, FOR 30 DAYS. The trend window is `_experiment_date(30)`
clamped to genesis, so the genesis-dated row is present for the first 30 days of every
cycle — not just Day 1. The clause is therefore keyed off "the cycle start", never a
2026-08 date, and these tests derive every fixture date from a symbolic genesis.

WHY THE WIDENING IS SAFE. The defect the exemption resembles — a row genuinely dated
BEFORE genesis (an ADR-077 clamp breach) — is now caught by `phase_plausibility` R6,
which is arithmetic and so can never be budget-paused. R6 checks the row's own `date`;
the clause exempts the NIGHT behind a genesis-dated row. Disjoint halves, per ADR-105.

THE CLAUSE DOES NOT SILENCE THE FINDING, AND THESE TESTS DO NOT PRETEND IT DOES.
Measured 2026-08-13 at the real call site: 3/3 runs raised it before any change, 3/3
with the clause, 4/5 with the clause AND the in-payload disclosure. The model
re-derives the accusation from the payload's own `trend_note`, quoting it approvingly
in the sentence that flags it. So the tests below pin two things that ARE true — the
ruling is recorded, and the deterministic layer is correct and mutation-proven — and
deliberately assert nothing about the LLM going quiet. The durable fix is to retire
this class from the LLM the way #1922 retired `impossible_number`; that needs its own
issue. See the MEASURED block in reader_truth_qa.py.

NB this file deliberately does NOT sweep the source tree, so it stays out of the
`tests/conftest.py` post-merge-only registry: it is a unit suite over two modules.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import phase_plausibility as pp, reader_truth_qa as rt  # noqa: E402

# A SYMBOLIC genesis — the ruling is about "the cycle start", not about 2026-08-10.
# Every fixture date below is derived from it, so this suite cannot rot into a
# 2026-08-specific pin at the next reset (ADR-077: genesis moves every cycle).
GENESIS = "2027-03-01"
_G = date.fromisoformat(GENESIS)


def _d(offset):
    return (_G + timedelta(days=offset)).isoformat()


def _phase(day_n):
    return {
        "today": _d(day_n - 1),
        "start_date": GENESIS,
        "day_n": day_n,
        "pre_start": False,
        "days_until_start": 0,
    }


def _trend_row(offset):
    """One wake-date-keyed sleep_trend row, shaped like the live payload.

    `sleep_start` is the UTC instant of the previous evening's bedtime — for the
    genesis-dated row that is the night BEFORE Day 1, which is the whole point.
    """
    return {
        "date": _d(offset),
        "sleep_score": 89.0,
        "hours": 7.2,
        "sleep_start": f"{_d(offset)}T05:05:46.420Z",
    }


# The live `/api/sleep_detail` shape on Day 3 of a cycle, trimmed to the fields under
# dispute: a 3-row trend whose FIRST row is dated exactly genesis.
def _sleep_detail_day3():
    return {
        "sleep_detail": {
            "sleep_score": 84.0,
            "total_sleep_hours": 7.1,
            "recovery_score": 30.0,
            "hrv": 30.9,
            "rhr": 60.0,
            "as_of_date": _d(2),
            "frame": "last_night",
            "night_of": _d(1),
            "days_tracked": 3,
            "figure_scope": {
                "frame": "last_night",
                "night_of": _d(1),
                "trend_date_field": "date",
                "trend_date_convention": "wake_date",
            },
        },
        "sleep_trend": [_trend_row(0), _trend_row(1), _trend_row(2)],
    }


def _rubric():
    return rt.build_prompt([{"name": "Home", "path": "/", "prose": "x"}], _phase(3))


# ── the clause ────────────────────────────────────────────────────────────────


def test_the_series_clause_exists_and_names_the_trend_locus():
    """The gap #2613 found: the #2575 clause reached the scalar `night_of` only."""
    rubric = _rubric()
    assert "sleep_trend" in rubric, "the clause must name the array the finding actually cites"
    assert "the EVENING BEFORE the cycle start" in rubric
    assert "the first row of a cycle always describes the" in rubric


def test_the_clause_is_written_for_the_recurrence_not_for_day_1():
    """#2583's clause went quiet after Day 1; this one must cover the whole clamp window."""
    rubric = _rubric()
    assert "first 30 days" in rubric, (
        "the row is present for as long as the window stays clamped to genesis — a Day-1-scoped "
        "clause leaves 29 more nights of noise, which is how #2613 got filed at Day 3"
    )
    # Keyed off the cycle start, never a calendar literal from the month it was written.
    assert "2026-08" not in rubric


def test_the_disclosure_notes_are_not_evidence_against_the_frame():
    """#2344's `trend_note` is what taught the model the rule it built the accusation from."""
    rubric = _rubric()
    assert "figure_scope" in rubric and "trend_note" in rubric
    assert "DISCLOSING this frame, never evidence against it" in rubric


def test_the_clause_is_scoped_not_a_blanket_suppression():
    rubric = _rubric()
    assert "`date` is BEFORE the cycle start" in rubric
    assert "precedes the cycle start by more than one day" in rubric


def test_the_2575_scalar_clause_survives_the_widening():
    """The new clause is additive — the ruling it extends must not be displaced."""
    rubric = _rubric()
    assert "the day BEFORE the cycle start" in rubric
    assert "on a surface dated on or after the cycle start" in rubric


# ── the deterministic premise (ADR-105: code leads, the clause only exempts) ──


def test_the_deterministic_layer_passes_the_disputed_payload():
    """The ruling's load-bearing premise. If this fails the exemption is hiding a defect."""
    findings = pp.check_payload("/api/sleep_detail", _sleep_detail_day3(), day_n=3, strict=True, start_date=GENESIS)
    assert findings == [], f"the payload the clause exempts must be deterministically clean: {findings}"


def test_r6_reds_a_row_genuinely_dated_before_genesis():
    """MUTATION PROOF. The genuine clamp breach the widened clause resembles."""
    payload = _sleep_detail_day3()
    payload["sleep_trend"].insert(0, _trend_row(-1))  # a prior-cycle row leaking in
    findings = pp._pre_genesis_row_findings("/api/sleep_detail", payload, GENESIS)
    assert len(findings) == 1, f"exactly the leaked row must red: {findings}"
    assert findings[0]["severity"] == "high"
    assert findings[0]["category"] == "temporal_contradiction"
    assert _d(-1) in findings[0]["note"] and "clamp breach" in findings[0]["note"]
    # ...and it reds through the real entry point, not only the helper.
    via_check = pp.check_payload("/api/sleep_detail", payload, day_n=3, strict=True, start_date=GENESIS)
    assert len(via_check) == 1 and via_check[0]["severity"] == "high"


def test_r6_reds_outside_genesis_week_too():
    """The rule is a DATE comparison, so it does not weaken as the cycle ages."""
    payload = {"sleep_trend": [_trend_row(-5), _trend_row(200)]}
    findings = pp.check_payload("/api/sleep_detail", payload, day_n=201, strict=True, start_date=GENESIS)
    assert len(findings) == 1 and _d(-5) in findings[0]["note"]


def test_r6_does_not_fire_on_the_genesis_dated_row_itself():
    """The exempted artefact: dated exactly genesis, bedtime the evening before."""
    payload = {"sleep_trend": [_trend_row(0)]}
    assert pp._pre_genesis_row_findings("/api/sleep_detail", payload, GENESIS) == []


def test_r6_ignores_a_pre_genesis_bedtime_inside_a_genesis_dated_row():
    """The precise conflation R6 must not make — this is #2613's whole subject."""
    row = _trend_row(0)
    row["sleep_start"] = f"{_d(-1)}T22:05:46.420Z"  # unambiguously the prior evening
    assert pp._pre_genesis_row_findings("/api/sleep_detail", {"sleep_trend": [row]}, GENESIS) == []


def test_r6_is_strict_only_so_narrative_surfaces_may_cite_a_prior_cycle():
    """R4's documented scope, for R4's documented reason (/api/coaches narrates cycles)."""
    payload = {"rows": [_trend_row(-30)]}
    assert pp.check_payload("/api/coaches", payload, day_n=3, strict=False, start_date=GENESIS) == []
    assert len(pp.check_payload("/api/coaches", payload, day_n=3, strict=True, start_date=GENESIS)) == 1


def test_r6_is_skipped_when_no_genesis_is_supplied():
    """Fail-soft: a rule with no cycle start to compare against must not guess one."""
    payload = {"sleep_trend": [_trend_row(-9)]}
    assert pp.check_payload("/api/sleep_detail", payload, day_n=3, strict=True) == []


def test_r6_tolerates_non_date_date_values():
    """Live payloads carry `date: null` and free-text dates; neither may crash or red."""
    payload = {"a": {"date": None}, "b": {"date": "not-a-date"}, "c": {"date": 20260810}}
    assert pp._pre_genesis_row_findings("/api/sleep_detail", payload, GENESIS) == []


# ── the surface half: the trend's timestamp must name its frame (#1968) ──────


def test_the_payload_declares_sleep_start_as_utc():
    """The real gap #2613 exposed, independent of whether the LLM ever goes quiet.

    #2344 named the trend ROW DATE's convention; `sleep_start` stayed a bare UTC
    instant in a payload whose every other date is Pacific. A figure that does not
    name its frame is unreconcilable (#1968) — which is why three nightly runs read
    `…T05:05:46Z` as a local date and could not square it with the wake-date rule.
    """
    import inspect

    from web import site_api_sleep

    src = inspect.getsource(site_api_sleep)
    assert '"trend_sleep_start_tz": "UTC"' in src, "the trend's timestamp frame must be declared, not inferred"
    assert "trend_sleep_start_note" in src
    # It must say the two things a reader needs: the tz split, and why the first row looks early.
    assert "is a Pacific calendar date" in src
    assert "the evening before Day 1" in src


def test_the_2344_row_date_disclosure_survives():
    """The new note extends the #2344 seam; it must not have displaced it."""
    import inspect

    from web import site_api_sleep

    src = inspect.getsource(site_api_sleep)
    assert '"trend_date_convention": "wake_date"' in src
    assert "trend_note" in src


# ── the neighbouring rule must not have been loosened ────────────────────────


def test_r5_still_reds_an_unlabelled_summary_at_any_phase():
    """A genuine summary/trend mismatch outside genesis week still fails (#2613 acceptance).

    R5 is the rule that catches a summary object floating free of any night — the
    #1968 defect. Widening the prose clause must not have touched it.
    """
    summary = {"total_sleep_hours": 8.4, "recovery_score": 54.0, "hrv": 41.1}
    findings = pp.check_payload("/api/sleep_detail", summary, day_n=400, strict=True, start_date=GENESIS)
    assert len(findings) == 1
    assert findings[0]["category"] == "temporal_contradiction"
    assert "no night label" in findings[0]["note"]
