"""#3258 — the reader-truth judge emits findings its own note retracts, and they
lit `qa-smoke-warnings`.

THE WIRE. Both notes below are VERBATIM from `/aws/lambda/life-platform-qa-smoke`
(the `[QA] DETAIL … reader_truth:verdict` lines, which since #3003 carry the
untruncated note). They are not hand-shaped approximations: each log line stamps
its own note length, and `test_the_fixtures_are_the_wire` asserts the fixture
matches that stamp character-for-character. A hand-written paraphrase would fail
that assertion, which is the whole point — a fixture that is not the wire has
passed here before while the real shape failed.

  RETRACTED  finding 539c6d · `/` · [temporal_contradiction/low] · 576 chars, Day 11.
             Its own final sentence: "No flag warranted on reconsideration."
             This is the finding that lit the alarm.

  REAL       finding e5eafd · `/api/glucose` · [temporal_contradiction/med] · 387
             chars, Day 8. Ground truth for it is independent and deterministic:
             the same log group's `reader_truth:plausibility` check FAILED on the
             same payload two days later with arithmetic, no LLM
             ("glucose.as_of_date = 2026-08-24 is 2 day(s) behind today
             2026-08-26"). This one must KEEP alarming.

WHAT IS UNDER TEST. Not a phrase. The pipeline now records the ruling ledger's
adjudication as a FIELD on the finding (`rulings`) and routes on that field:
adjudicated findings ride the non-alarmed ChronicWarnCount, so `WarnCount` — what
`qa-smoke-warnings` fires on — counts exactly the findings no reconsideration
touched. Extending `_WITHDRAWAL_RE` with "no flag warranted" was available and was
deliberately NOT taken: every phrase-matched member of the #2959/#3003/#3199
demotion family has failed in the field.

THE MUST-FAIL CASE runs the recorded payload through the real wire —
`bedrock_client.invoke` → `reader_truth_qa.assess_prose` → `check_reader_truth` →
`qa_check.split_warns()` — and asserts the retracted finding is not on the alarmed
side. Against the pre-fix tree it fails: `assess_prose` consulted the demotion
predicates only under `if f["severity"] != "low"`, so a finding the model itself
rated `low` was never adjudicated at all, and `low` lands in the alarmed WarnCount.
"""

import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import (
    qa_check_reader_truth as q,  # noqa: E402
    reader_truth_qa as rtq,  # noqa: E402
)
from operational.qa_check import emf_summary_line, split_warns  # noqa: E402

# ── the wire ────────────────────────────────────────────────────────────────────
# "[QA] DETAIL [content_truth] Reader Truth / reader_truth:verdict: finding 539c6d ·
#  / [temporal_contradiction/low] — full note (576 chars): …"
RETRACTED_NOTE = (
    "Home page states 'This attempt starts at the Day‑1 weigh‑in, aimed at 185 lbs held for 90 "
    "consecutive days' but does not explicitly label this as a forward-looking goal or checkpoint. "
    "The prose is framed in present tense ('This attempt starts') which could be read as describing "
    "an ongoing or past event rather than a future target. However, the context ('aimed at', 'or the "
    "checkpoint fails') makes clear it is a prospective goal. This is ambiguous rather than "
    "contradictory — the phrasing is acceptable for describing a cycle objective. No flag warranted "
    "on reconsideration."
)
RETRACTED_NOTE_CHARS = 576  # the log line's own stamp

# The phase the retraction was recorded at (Day 11), derived from the live constant so
# a reset moves it — the #3337 rulings take the phase anchors, and a wire note judged
# against the wrong day is no longer the wire.
# Wire-recorded frame (cycle-14, genesis 2026-08-17) — see test_reader_truth_qa.py.
_RECORDED_GENESIS = "2026-08-17"
_PHASE_START = _RECORDED_GENESIS
_DAY_11 = (date.fromisoformat(_RECORDED_GENESIS) + timedelta(days=10)).isoformat()


@pytest.fixture(autouse=True)
def _recorded_frame(monkeypatch):
    """assess_prose computes phase ground truth from constants at CALL time; the
    wire corpus replays under its recorded frame (see _RECORDED_GENESIS above)."""
    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", _RECORDED_GENESIS)


# "… finding e5eafd · /api/glucose [temporal_contradiction/med] — full note (387 chars): …"
REAL_NOTE = (
    "as_of_date is 2026-08-22, but the payload was generated on 2026-08-24 (Day 8). The as_of_date "
    "should reflect the last complete day of data; being two days stale on Day 8 is inconsistent with "
    "the design pattern of 'as of yesterday' (which would be 2026-08-23). The glucose_trend includes "
    "data through 2026-08-22, but the frame indicates it should be current through the last complete day."
)
REAL_NOTE_CHARS = 387


def test_the_fixtures_are_the_wire():
    """A fixture that drifts from the recorded payload proves nothing about the
    recorded payload. The log stamps its own note length; assert against it."""
    assert len(RETRACTED_NOTE) == RETRACTED_NOTE_CHARS, (
        f"RETRACTED_NOTE is {len(RETRACTED_NOTE)} chars, the qa-smoke log recorded "
        f"{RETRACTED_NOTE_CHARS} — this fixture is no longer the wire"
    )
    assert (
        len(REAL_NOTE) == REAL_NOTE_CHARS
    ), f"REAL_NOTE is {len(REAL_NOTE)} chars, the qa-smoke log recorded {REAL_NOTE_CHARS} — this fixture is no longer the wire"
    assert RETRACTED_NOTE.rstrip().endswith("No flag warranted on reconsideration.")


def _verdict_payload(findings):
    """The Bedrock response envelope `bedrock_client.invoke` returns, carrying the
    judge's JSON reply as a text block — the transport `assess_prose` parses."""
    body = {
        "findings": findings,
        "severity": max((f["severity"] for f in findings), key=["low", "med", "high"].index) if findings else "ok",
        "summary": "one sentence",
    }
    return {"content": [{"type": "text", "text": json.dumps(body)}]}


_RETRACTED = {"page": "/", "category": "temporal_contradiction", "severity": "low", "note": RETRACTED_NOTE}
_REAL = {"page": "/api/glucose", "category": "temporal_contradiction", "severity": "med", "note": REAL_NOTE}

_SURFACES = [
    {"name": "Home", "path": "/", "prose": "This attempt starts at the Day-1 weigh-in.", "frozen": False},
    {"name": "API · glucose", "path": "/api/glucose", "prose": '{"as_of_date": "2026-08-22"}', "frozen": False},
]


@pytest.fixture
def nightly(monkeypatch):
    """Drive the REAL `check_reader_truth` with only its three external edges
    stubbed: the HTTPS fetch, the two token-free deterministic passes (they have
    their own suites and would otherwise re-judge the stub payloads), and the
    Bedrock transport. Everything between — assess_prose, the ruling ledger, the
    Check construction, the advisory split — runs for real."""

    def _stub_ai(name, module):
        """Both halves, or the stub silently does not apply.

        `check_reader_truth` reaches Bedrock with `from ai import bedrock_client`,
        which reads the ATTRIBUTE off the already-imported `ai` package and never
        consults sys.modules. Patching sys.modules alone passed when this file ran
        alone (nothing had imported `ai.bedrock_client` yet, so the import fell
        through to the stub) and silently hit the real Bedrock endpoint whenever an
        earlier test file had imported it — an UnrecognizedClientException that
        arrives as a fail-soft WARN, i.e. the test would have "failed for a
        different reason" rather than measuring anything.
        """
        import ai

        monkeypatch.setitem(sys.modules, f"ai.{name}", module)
        monkeypatch.setattr(ai, name, module, raising=False)

    def _run(findings):
        monkeypatch.setattr(q, "_fetch_reader_truth_surfaces", lambda: ([dict(s) for s in _SURFACES], []))
        monkeypatch.setattr(q, "_check_phase_plausibility", lambda surfaces: [])
        monkeypatch.setattr(q, "_check_frozen_artifacts", lambda surfaces: [])
        # No SSM in tests: pin the cycle probe rather than letting it time out.
        monkeypatch.setattr(rtq, "_cycle_probe", {"done": True, "value": 14})
        _stub_ai("budget_guard", types.SimpleNamespace(allow=lambda f: True, current_tier=lambda: 0))

        def _invoke(body, model_name=None):
            # The confirmation pass (#2741) only runs when a high is present; when
            # it does, it replays the same recorded verdict.
            return _verdict_payload(findings)

        _stub_ai("bedrock_client", types.SimpleNamespace(invoke=_invoke))
        checks = q.check_reader_truth()
        assert not [c for c in checks if c.name == "reader_truth:batch"], (
            "an AI batch errored — the Bedrock stub did not apply and this run measured nothing: "
            f"{[c.message for c in checks if c.name == 'reader_truth:batch']}"
        )
        return checks, split_warns(checks)

    return _run


# ── the must-fail case: the retracted finding must not reach WarnCount ─────────


def test_the_retracted_finding_does_not_reach_warncount(nightly):
    """THE REGRESSION (#3258). Replay of the recorded Day-11 payload: the judge's
    own note ends 'No flag warranted on reconsideration', and the alarm lit anyway.

    Fails against the pre-fix tree — the ledger was consulted only above `low`, so
    this finding was never adjudicated and landed on the alarmed side."""
    checks, (alarmed, chronic) = nightly([_RETRACTED])

    doc = json.loads(
        emf_summary_line(passed=0, warned=len(alarmed), failed=0, paused=0, timestamp_ms=1_700_000_000_000, warned_chronic=len(chronic))
    )
    assert doc["WarnCount"] == 0, (
        "the judge's own retraction reached the alarmed WarnCount — qa-smoke-warnings still "
        f"cannot mean 'a finding survived reconsideration'. Alarmed: {[c.message for c in alarmed]}"
    )
    assert doc["ChronicWarnCount"] == 1, "the retracted finding vanished instead of being reported on the non-alarmed channel"

    (adv,) = [c for c in chronic if c.name == "reader_truth:advisory"]
    assert "vagueness_objection" in adv.message, "the adjudication that fired must be named in the check message"
    assert any(RETRACTED_NOTE in d for d in adv.details), "the untruncated note must travel with the advisory (#2620)"


def test_a_real_finding_still_reaches_warncount(nightly):
    """THE OTHER HALF, and the reason this is not a mute. The recorded
    /api/glucose staleness finding — independently confirmed by the deterministic
    plausibility pass, which FAILED on the same field with arithmetic — carries no
    ruling and must keep incrementing the alarmed WarnCount."""
    checks, (alarmed, chronic) = nightly([_REAL])

    doc = json.loads(
        emf_summary_line(passed=0, warned=len(alarmed), failed=0, paused=0, timestamp_ms=1_700_000_000_000, warned_chronic=len(chronic))
    )
    assert doc["WarnCount"] == 1, "a real, unadjudicated truth finding stopped alarming — the alarm went blind"
    assert doc["ChronicWarnCount"] == 0
    assert [c.name for c in alarmed] == ["reader_truth:verdict"]


def test_a_mixed_run_splits_rather_than_muting_both(nightly):
    """The live fail-closed proof, on the two recorded findings together: the
    retracted one leaves WarnCount and the real one stays."""
    checks, (alarmed, chronic) = nightly([_RETRACTED, _REAL])

    assert [c.name for c in alarmed] == ["reader_truth:verdict"]
    assert [c.name for c in chronic] == ["reader_truth:advisory"]
    verdict = next(c for c in checks if c.name == "reader_truth:verdict")
    assert "/api/glucose" in verdict.message
    assert RETRACTED_NOTE[:40] not in verdict.message, "the adjudicated finding leaked back into the alarmed verdict"


# ── the field, not the phrase ──────────────────────────────────────────────────


def test_the_ledger_is_consulted_at_low_severity_too():
    """The precise defect. `is_vagueness_objection` returns True on this note —
    #3003 adjudicated the class two issues ago — but `assess_prose` asked only when
    severity was above `low`, which is the one severity the warnings alarm still
    fires on."""
    assert rtq.is_vagueness_objection(_RETRACTED, _PHASE_START, _DAY_11) is True

    def _invoke(body, model_name=None):
        return _verdict_payload([dict(_RETRACTED)])

    findings, errors = rtq.assess_prose([dict(_SURFACES[0])], _invoke, today_iso=_DAY_11)
    assert errors == []
    assert len(findings) == 1, "adjudicated, not dropped — the evidence stays visible"
    assert findings[0]["severity"] == "low", "an already-low finding must not be re-graded"
    # #3379: the same note also matches the uncited-temporal-objection ruling —
    # its OWN sentences cite no temporal value (the "Day-1" is quoted page copy),
    # the exact shape #3337's comment names. The ledger records every match.
    assert findings[0][rtq.RULINGS_FIELD] == ["uncited_temporal_objection", "vagueness_objection"]
    assert rtq.is_advisory(findings[0]) is True


def test_an_unadjudicated_finding_carries_no_rulings_field():
    """The safety direction: `is_advisory` is False by absence, so a novel finding
    class can never be born muted. Same posture as `Check.warn`'s chronic default."""

    def _invoke(body, model_name=None):
        return _verdict_payload([dict(_REAL)])

    findings, _ = rtq.assess_prose([dict(_SURFACES[1])], _invoke, today_iso=_DAY_11)
    assert len(findings) == 1
    assert not findings[0].get(rtq.RULINGS_FIELD)
    assert rtq.is_advisory(findings[0]) is False


def test_the_withdrawal_phrase_list_was_not_extended():
    """The design constraint, asserted. The cheap fix was to add "no flag
    warranted" to `_WITHDRAWAL_RE`; every phrase-matched member of the
    #2959/#3003/#3199 family has failed in the field, one of them gating main. This
    finding is NOT caught by the phrase matcher, and that is deliberate — it is
    caught by the ruling FIELD. If a later change makes `is_self_refuted` True
    here, the phrase list grew and this test says so out loud."""
    assert rtq.is_self_refuted(_RETRACTED, _PHASE_START, _DAY_11) is False, (
        "_WITHDRAWAL_RE was extended to cover this note. That is the phrase-matched "
        "suppressor family (#2959/#3003/#3199) — route on the `rulings` field instead."
    )


def test_a_demoted_high_is_adjudicated_and_leaves_warncount(nightly):
    """The rulings' original shape still works, and now reaches the channel they
    each promised: a HIGH that resolves to vagueness is demoted to low, recorded as
    adjudicated, and does not alarm. (Pre-fix it was demoted to low and alarmed.)"""
    high = dict(_RETRACTED, severity="high")
    checks, (alarmed, chronic) = nightly([high])
    assert [c.name for c in alarmed] == []
    assert [c.name for c in chronic] == ["reader_truth:advisory"]
    verdict = next(c for c in checks if c.name == "reader_truth:verdict")
    assert verdict.passed is True, "a run whose only finding was adjudicated must not FAIL"
    assert "no truth finding survived the ruling ledger" in verdict.message
    assert "clean" not in verdict.message, "'clean' would overclaim — findings existed, the ledger adjudicated them"
