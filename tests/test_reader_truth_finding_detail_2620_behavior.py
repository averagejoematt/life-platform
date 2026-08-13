"""tests/test_reader_truth_finding_detail_2620_behavior.py — #2620: a reader-truth
finding must be READABLE IN FULL from the run that produced it.

The defect this pins closed: every finding was formatted once, as
``f"{page} [{category}] {note[:90]}"``, and that string was the only place the
text ever went. There was no verbose mode, no artifact, no second emit — the
model's reasoning was generated, truncated, and discarded. #2613 cost two days
and a hand-reproduction of the live call site to recover a 289-char note of
which 199 chars had been thrown away, and three nightly runs cut the SAME
finding at three different points so one problem read as three.

Four contracts, each mutation-proven (the assertion fails if the fix is
reverted, not merely if the code changes shape):

  1. **Recoverable.** A note longer than the inline budget appears IN FULL in
     the detail lines — and the length is stated, so a reader knows nothing was
     cut from the detail itself.
  2. **Truncation is marked as truncation.** The inline summary says
     ``…[+N chars]``. A bare ``…`` is indistinguishable from prose the model
     itself wrote trailing off.
  3. **One finding reads as one finding.** A run-invariant group id (page +
     category, deliberately NOT the reworded note) ties three nights' three
     phrasings together, and byte-identical repeats inside one run collapse to
     ``×N`` rather than N lines.
  4. **Nothing is silently dropped.** The inline cap says how many findings it
     did not show, and every finding past it still gets its own detail line.

Both the FAIL path (high) and the WARN path (low/med) are covered — the guardrail
on the issue is that low/med findings are the ones nobody reproduces by hand, so
an unreadable warn is a warn that is never triaged.

No AWS and no network: the LLM/fetch seams are replaced with bounded fakes.
"""

from __future__ import annotations

import os

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

import pytest  # noqa: E402
from operational import qa_check_reader_truth as rt  # noqa: E402
from operational.qa_check import (  # noqa: E402
    CONTENT_TRUTH,
    DETAIL_LINE_CAP,
    SNIPPET_CHARS,
    Check,
    detail_log_lines,
    finding_group,
    summarize_findings,
)

# The real note from #2613, verbatim from the issue — 289 chars, of which the
# 90-char cut kept 90 and discarded 199. Using the actual text (not a synthetic
# "x" * 300) keeps this test honest about the shape of what gets lost: the
# discarded two thirds is where the reasoning and the date evidence live.
NOTE_2613 = (
    "sleep_trend contains a row dated 2026-08-10 with sleep_start timestamp 2026-08-10T05:05:46.420Z. "
    "Per the figure_scope documentation, trend rows are keyed by WAKE date, so this row represents the "
    "night of 2026-08-09. However, the experiment started on 2026-08-10 (Day 1); data from the night "
    "of 2026-08-09 predates it."
)


def _finding(note=NOTE_2613, page="/api/sleep_detail", category="temporal_contradiction", severity="high"):
    return {"page": page, "category": category, "severity": severity, "note": note}


# ---------------------------------------------------------------------------
# 1. Recoverable in full
# ---------------------------------------------------------------------------


def test_the_note_is_longer_than_the_inline_budget_so_this_test_has_teeth():
    """Guard the guard: if SNIPPET_CHARS ever grew past the note, every
    assertion below would pass vacuously."""
    assert len(NOTE_2613) > SNIPPET_CHARS, "the fixture note no longer overflows the summary — this suite would prove nothing"


def test_full_note_is_recoverable_from_the_detail_lines():
    summary, details = summarize_findings([_finding()])
    assert NOTE_2613 not in summary, "the summary is supposed to stay short — if it carries the whole note, the split has collapsed"
    assert len(details) == 1
    assert NOTE_2613 in details[0], "the untruncated note is not recoverable — this is exactly the #2620 defect"
    assert str(len(NOTE_2613)) in details[0], "the detail line must state the note's length so a reader knows it is complete"


def test_detail_line_carries_the_page_and_category_so_it_stands_alone():
    _, details = summarize_findings([_finding()])
    assert "/api/sleep_detail" in details[0] and "temporal_contradiction" in details[0]
    assert "high" in details[0], "severity is part of triage; a detail line without it forces a hop back to the summary"


def test_a_short_note_is_never_truncated_and_still_gets_its_detail_line():
    short = "day_n says 3 but the page says Day 2"
    summary, details = summarize_findings([_finding(note=short)])
    assert short in summary and "…" not in summary
    assert short in details[0]


# ---------------------------------------------------------------------------
# 2. Truncation is marked AS truncation
# ---------------------------------------------------------------------------


def test_the_summary_states_how_many_characters_it_removed():
    summary, _ = summarize_findings([_finding()])
    assert f"…[+{len(NOTE_2613) - SNIPPET_CHARS} chars]" in summary, (
        "the cut must announce itself. A bare '…' reads as prose — that is how #2613's three "
        f"truncations were mistaken for three findings. Got: {summary!r}"
    )


def test_the_snippet_keeps_exactly_the_inline_budget_and_no_more():
    summary, _ = summarize_findings([_finding()])
    assert NOTE_2613[:SNIPPET_CHARS] in summary
    assert NOTE_2613[: SNIPPET_CHARS + 1] not in summary


# ---------------------------------------------------------------------------
# 3. One finding reads as one finding
# ---------------------------------------------------------------------------


def test_the_group_id_survives_the_model_rewording_the_same_finding():
    """#2613's actual failure mode: three nights, three phrasings, one defect.

    The id is hashed over page+category precisely BECAUSE the note moves. If it
    were hashed over the note, this test would fail — which is the mutation.
    """
    nights = [
        _finding(note="sleep_trend contains a row dated 2026-08-10 but the experiment started then"),
        _finding(note="the sleep_start timestamp on the 2026-08-10 row predates Day 1"),
        _finding(note="a row keyed to the 2026-08-09 night appears with the 2026-08-10 wake date"),
    ]
    ids = {finding_group(f) for f in nights}
    assert len(ids) == 1, f"three phrasings of one defect produced {len(ids)} ids — they will read as separate findings again"

    other = finding_group(_finding(page="/api/vitals"))
    assert other not in ids, "a different page must not share the group id — the id would then group nothing"


def test_the_group_id_appears_in_both_the_summary_and_the_detail_line():
    summary, details = summarize_findings([_finding()])
    gid = finding_group(_finding())
    assert gid in summary and gid in details[0], "the id has to be on BOTH lines or it cannot join them"


def test_identical_findings_inside_one_run_collapse_to_one_line_with_a_count():
    summary, details = summarize_findings([_finding(), _finding(), _finding()])
    assert len(details) == 1, "three byte-identical findings produced three detail lines — that is the inflation #2620 names"
    assert "×3" in details[0] and "×3" in summary


def test_findings_that_differ_only_in_note_are_kept_apart():
    """Dedupe collapses byte-identical findings only. Two genuinely different
    notes on one page are two findings and must both survive."""
    _, details = summarize_findings([_finding(note="first problem"), _finding(note="second problem")])
    assert len(details) == 2


# ---------------------------------------------------------------------------
# 4. Nothing is silently dropped
# ---------------------------------------------------------------------------


def test_findings_past_the_inline_cap_are_counted_and_still_detailed():
    findings = [_finding(note=f"finding number {i} " + NOTE_2613) for i in range(6)]
    summary, details = summarize_findings(findings)
    assert "(+2 more finding(s), all listed below)" in summary, f"the 5th and 6th findings vanished from the summary: {summary!r}"
    assert len(details) == 6, "every finding needs a detail line — the old code dropped the 5th onward entirely"
    for i in range(6):
        assert any(f"finding number {i} " in d for d in details)


def test_the_detail_cap_bounds_a_pathological_run_and_says_that_it_did():
    findings = [_finding(note=f"n{i} " + NOTE_2613) for i in range(DETAIL_LINE_CAP + 5)]
    _, details = summarize_findings(findings)
    assert len(details) == DETAIL_LINE_CAP + 1, "the cap must hold — an unbounded run would be the log-volume regression"
    assert "5 further finding(s) not detailed" in details[-1], "a suppressed finding must be COUNTED, never silently absent"


# ---------------------------------------------------------------------------
# 5. Shape tolerance — the frozen-artifact findings carry `detail`, no severity
# ---------------------------------------------------------------------------


def test_a_finding_with_no_severity_and_a_different_text_key_still_works():
    frozen = {"page": "/journal/posts/week-01/", "category": "superseded_weight_unannotated", "detail": "x" * 250}
    summary, details = summarize_findings([frozen], key="detail", width=110, inline=3)
    assert "…[+140 chars]" in summary
    assert "x" * 250 in details[0]
    assert "full detail (250 chars)" in details[0]


def test_missing_fields_never_raise():
    summary, details = summarize_findings([{}, None])
    assert isinstance(summary, str) and len(details) >= 1


# ---------------------------------------------------------------------------
# 6. Emission — the lines actually reach the log, beneath their own summary
# ---------------------------------------------------------------------------


def test_a_check_with_no_details_emits_no_lines():
    """The cost claim in the PR body: a clean nightly adds ZERO bytes."""
    assert detail_log_lines(Check("x", "Reader Truth", CONTENT_TRUTH).ok("all clean")) == []


def test_detail_lines_are_tagged_for_logs_insights_and_name_their_check():
    c = Check("reader_truth:verdict", "Reader Truth", CONTENT_TRUTH).fail("2 high truth finding(s)").with_details(["a", "b"])
    lines = detail_log_lines(c)
    assert lines == [
        "[QA] DETAIL [content_truth] Reader Truth / reader_truth:verdict: a",
        "[QA] DETAIL [content_truth] Reader Truth / reader_truth:verdict: b",
    ]


def test_the_handler_prints_the_details_under_both_the_fail_and_the_warn_line():
    """Static proof of ordering + coverage, because invoking the real handler
    SENDS MAIL. Both loops must call detail_log_lines, or the recovery path
    exists in the data and nowhere in the log."""
    import ast
    import inspect

    from operational import qa_smoke_lambda

    tree = ast.parse(inspect.getsource(qa_smoke_lambda.lambda_handler))
    loops = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.For)
        and any(
            isinstance(c, ast.Call) and getattr(c.func, "id", None) == "detail_log_lines"
            for c in ast.walk(ast.Module(body=n.body, type_ignores=[]))
        )
    ]
    assert len(loops) >= 2, "detail_log_lines is not called from both the FAIL and the WARN print loops — one path stays unreadable"


# ---------------------------------------------------------------------------
# 7. End-to-end through check_reader_truth — the real call sites
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_reader_truth(monkeypatch):
    """Replace the fetch + the two AI seams; leave the formatting real."""
    from operational import reader_truth_qa

    surfaces = [{"name": "API · sleep detail", "path": "/api/sleep_detail", "prose": "{}", "frozen": False}]
    monkeypatch.setattr(rt, "_fetch_reader_truth_surfaces", lambda: (surfaces, []))
    monkeypatch.setattr(rt, "_check_phase_plausibility", lambda s: [])
    monkeypatch.setattr(rt, "_check_frozen_artifacts", lambda s: [])
    monkeypatch.setattr(reader_truth_qa, "phase_context", lambda *a, **k: {"pre_start": False, "day_n": 3, "days_until_start": 0})
    return reader_truth_qa


def _run(monkeypatch, findings):
    from ai import budget_guard
    from operational import reader_truth_qa

    monkeypatch.setattr(budget_guard, "allow", lambda *a, **k: True)
    monkeypatch.setattr(reader_truth_qa, "assess_prose", lambda *a, **k: (findings, []))
    return {c.name: c for c in rt.check_reader_truth()}["reader_truth:verdict"]


def test_a_high_finding_fails_and_carries_its_full_note(stub_reader_truth, monkeypatch):
    verdict = _run(monkeypatch, [_finding()])
    assert verdict.passed is False
    assert NOTE_2613 not in verdict.message
    assert any(NOTE_2613 in d for d in verdict.details), "the FAIL path lost the note again"


def test_the_low_med_warn_path_carries_its_full_note_too(stub_reader_truth, monkeypatch):
    """The guardrail on #2620: low/med findings are the ones nobody reproduces
    by hand, so an unreadable warn is a warn that is never triaged."""
    verdict = _run(monkeypatch, [_finding(severity="med")])
    assert verdict.passed is None
    assert any(NOTE_2613 in d for d in verdict.details), "the WARN path still discards the note — half the fix is missing"


def test_a_clean_run_attaches_no_details(stub_reader_truth, monkeypatch):
    verdict = _run(monkeypatch, [])
    assert verdict.passed is True and verdict.details == []


def test_the_deterministic_plausibility_path_also_carries_its_full_note(monkeypatch):
    """#1922's pass built the same 90-char string inline. It is never
    budget-paused, so it is the pass MOST likely to be the one an operator
    reads — and it had the identical blind spot."""
    from operational import phase_plausibility, reader_truth_qa

    monkeypatch.setattr(phase_plausibility, "sweep_payloads", lambda payloads: ([_finding()], []))
    monkeypatch.setattr(reader_truth_qa, "phase_context", lambda *a, **k: {"pre_start": False, "day_n": 3, "days_until_start": 0})
    checks = rt._check_phase_plausibility([{"path": "/api/sleep_detail", "prose": "{}"}])
    det = [c for c in checks if c.passed is False]
    assert det, "the deterministic pass did not fail on a planted finding"
    assert any(NOTE_2613 in d for d in det[0].details)


def test_the_frozen_artifact_path_also_carries_its_full_detail(monkeypatch):
    from operational import weight_truth_qa

    long_detail = "Prologue I presents 268.0 lbs as the starting weight, " + ("but the experiment runs on 254.6 lbs. " * 6)
    monkeypatch.setattr(
        weight_truth_qa,
        "assess_frozen_artifact_weights",
        lambda pages, baseline: [{"page": "/journal/posts/week-01/", "category": "superseded_weight_unannotated", "detail": long_detail}],
    )
    checks = rt._check_frozen_artifacts([{"path": "/journal/posts/week-01/", "name": "Prologue I", "prose": "x", "frozen": True}])
    assert checks[0].passed is False
    assert any(long_detail in d for d in checks[0].details)
