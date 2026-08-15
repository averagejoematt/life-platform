"""#2741 — a blocking alarm's FAIL boundary must not be a coin flip.

Measured 2026-08-15 against byte-identical content: the same durable-design-copy
finding appeared in **2 of 8** runs, at two different severities (low/med, then
high) with two different rationales. `high` maps to `verdict.fail()`, and a FAIL is
what reddens `qa-smoke-failures` — so a single non-deterministic LLM call was
deciding whether a blocking alarm went red.

Note what this is NOT: the #1922/#2613 remedy of RETIRING the class. Those classes
were retired because they were persistent (3/3, 3/3, 4/5 runs). A 2/8 class is
flaky, and retiring it would delete real coverage to fix a flake.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import qa_check_reader_truth as q  # noqa: E402
from operational.qa_check import finding_group  # noqa: E402


def _f(page, category, severity, note="n"):
    return {"page": page, "category": category, "severity": severity, "note": note}


_REAL = _f("/api/sleep_detail", "fabricated_number", "high", "sleep_hours 99 with no reading behind it")
_FLAKY = _f("/", "temporal_contradiction", "high", "Home states 'starts at the Day-1 weigh-in' but today is Day 6")


def _patch(monkeypatch, second_pass):
    """Stub only the LLM call; the confirmation logic under test runs for real."""

    class _Stub:
        BUDGET_FEATURE = "x"

        @staticmethod
        def assess_prose(surfaces, invoke):
            return list(second_pass), []

    monkeypatch.setitem(sys.modules, "ai.bedrock_client", type("B", (), {"invoke": staticmethod(lambda *a, **k: "")}))
    monkeypatch.setattr(q, "reader_truth_qa", _Stub, raising=False)
    import operational

    monkeypatch.setattr(operational, "reader_truth_qa", _Stub, raising=False)


def test_a_finding_that_does_not_reproduce_is_demoted_not_dropped(monkeypatch):
    """The regression. An unconfirmed high must not FAIL — and must not vanish."""
    _patch(monkeypatch, second_pass=[])  # second pass sees nothing
    confirmed, unconfirmed, note = q._confirm_high_findings([_FLAKY], surfaces=[{"path": "/"}])
    assert confirmed == []
    assert unconfirmed == [_FLAKY]
    assert note and finding_group(_FLAKY) in note


def test_a_finding_that_reproduces_still_fails(monkeypatch):
    """The half that must NOT regress: a real, reproducible high keeps its teeth."""
    _patch(monkeypatch, second_pass=[_REAL])
    confirmed, unconfirmed, note = q._confirm_high_findings([_REAL], surfaces=[{"path": "/api/sleep_detail"}])
    assert confirmed == [_REAL]
    assert unconfirmed == []
    assert note is None


def test_identity_is_page_and_category_not_the_reworded_note(monkeypatch):
    """The model rewords its rationale every run (#2613's three-runs-read-as-three-
    problems). Matching on the note would make confirmation impossible by design."""
    reworded = dict(_REAL, note="a completely different sentence about the same defect")
    _patch(monkeypatch, second_pass=[reworded])
    confirmed, unconfirmed, _ = q._confirm_high_findings([_REAL], surfaces=[{"path": "/api/sleep_detail"}])
    assert confirmed == [_REAL], "confirmation must survive the model rewording its own note"
    assert unconfirmed == []


def test_a_mixed_run_splits_rather_than_all_or_nothing(monkeypatch):
    _patch(monkeypatch, second_pass=[_REAL])
    confirmed, unconfirmed, note = q._confirm_high_findings([_REAL, _FLAKY], surfaces=[{"path": "/"}])
    assert confirmed == [_REAL]
    assert unconfirmed == [_FLAKY]
    assert note and finding_group(_FLAKY) in note


def test_an_unavailable_confirmation_pass_fails_CLOSED(monkeypatch):
    """A second opinion that cannot be obtained must never be the reason a genuine
    finding is downgraded. The failure direction preserves the old behaviour."""

    class _Boom:
        BUDGET_FEATURE = "x"

        @staticmethod
        def assess_prose(surfaces, invoke):
            raise RuntimeError("bedrock throttled")

    monkeypatch.setitem(sys.modules, "ai.bedrock_client", type("B", (), {"invoke": staticmethod(lambda *a, **k: "")}))
    import operational

    monkeypatch.setattr(operational, "reader_truth_qa", _Boom, raising=False)
    confirmed, unconfirmed, note = q._confirm_high_findings([_REAL], surfaces=[{"path": "/x"}])
    assert confirmed == [_REAL], "an errored confirmation pass must not downgrade a high"
    assert unconfirmed == []
    assert note and "fail-closed" in note
