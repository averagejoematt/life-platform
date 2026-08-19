"""tests/test_coach_quality_gate_number_grounding_2573.py — #2573.

The BLOCKING coach quality gate (ADR-108) could not fail a brief for inventing a
number, because no criterion in its four-part rubric mentioned one. Measured
2026-08-11 over three identical Bedrock runs: all three fabricated-number canaries
scored 92 / 92 / 82 and PASSED, against `PASS_SCORE_THRESHOLD = 60`.

The fix does not teach an LLM to do arithmetic in prose. It CONSUMES the ADR-104
deterministic verdict (ADR-105: deterministic computation before any LLM verdict),
which the platform already computes and already trusts on every other surface.

What this file proves, with the judge stubbed so the LLM is not the variable:
  1. MUTATION PROOF — with criterion 5 in place a fabricated-number canary FAILS;
     strip the grounding context (the pre-#2573 world) and the SAME draft, the SAME
     stubbed judge, and the SAME threshold let it PASS again.
  2. The deterministic verdict outranks the model: a judge returning passed=true
     and score=92 cannot ship a draft the grounder failed.
  3. Honest absence: no allow-list on the wire is reported as absence, never as a
     clean verdict, and never blocks.
  4. Goldens are not false-flagged — the allow-list is the same one the
     deterministic golden-brief eval curated the 30 goldens against.
  5. The rubric text actually reaches the ASSEMBLED PROMPT (specs and prompts are
     assembled at runtime; asserting on the local constant alone is not proof).
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import pytest  # noqa: E402
from ai.quality_gate_contract import (  # noqa: E402
    AUTHORITATIVE_FACTS_KEY,
    GROUNDING_ALLOWLIST_KEY,
    brief_with_grounding,
    quality_gate_event,
)

# The three canaries the issue names — the ones that scored 92/92/82 and passed.
FABRICATION_CANARIES = ("canary_hrv_fabricated", "canary_weight_fabricated", "canary_glucose_trend_fabricated")

# A judge that is as generous as the measured one was: passes everything, high score.
GENEROUS_JUDGE = {"passed": True, "score": 92, "voice_distinctiveness_score": 80}


def _stub_judge(*_a, **_k):
    return dict(GENEROUS_JUDGE)


@pytest.fixture()
def gate():
    from coach import coach_quality_gate as g

    return g


def _fixtures():
    import golden_brief_eval as gbe

    return gbe.load_fixtures()


def _canary(cid):
    _golden, canaries = _fixtures()
    for c in canaries:
        if c["id"] == cid:
            return c
    raise AssertionError(f"canary {cid} missing from the fixture corpus")


def _brief_for(fx):
    import golden_brief_eval as gbe

    return brief_with_grounding(fx.get("generation_brief"), fx.get("authoritative_facts") or {}, gbe.allowed_for(fx))


def _judge(gate, coach_id, text, brief):
    """Run the gate's REAL entry point with the LLM stubbed and the two AWS reads
    substituted, exactly as the calibration harness does."""
    real_call, real_load, real_peers, real_query = (
        gate._call_haiku,
        gate._load_voice_spec,
        gate._fetch_other_coaches_recent_outputs,
        gate._query_begins_with,
    )
    try:
        gate._call_haiku = _stub_judge
        gate._load_voice_spec = lambda cid: {}
        gate._fetch_other_coaches_recent_outputs = lambda cid, other_coach_ids=None: {}
        gate._query_begins_with = lambda *a, **k: []
        return gate.lambda_handler(quality_gate_event(coach_id, text, brief), None)
    finally:
        gate._call_haiku = real_call
        gate._load_voice_spec = real_load
        gate._fetch_other_coaches_recent_outputs = real_peers
        gate._query_begins_with = real_query


# ── 1. the mutation proof ────────────────────────────────────────────────────
@pytest.mark.parametrize("cid", FABRICATION_CANARIES)
def test_fabricated_number_canary_fails_with_criterion_5(gate, cid):
    """The headline acceptance item: the canaries that scored 92/92/82 now fail."""
    cn = _canary(cid)
    report = _judge(gate, cn["coach_id"], cn["mutated_output"], _brief_for(cn))
    assert report["passed"] is False, f"{cid} still passes: {report.get('number_grounding')}"
    assert report["number_grounding"]["status"] == "measured"
    assert report["number_grounding"]["verdict"] == "ungrounded"
    assert report["number_grounding_violations"], "the finding must be reported, not only enforced"


@pytest.mark.parametrize("cid", FABRICATION_CANARIES)
def test_reverting_the_criterion_lets_the_same_canary_pass_again(gate, cid):
    """The other half of the mutation proof — otherwise the test proves only that
    something, somewhere, fails. Removing the grounding context reproduces the
    pre-#2573 world: same draft, same stubbed judge (passed=true, score=92), same
    PASS_SCORE_THRESHOLD, and the fabricated number ships."""
    cn = _canary(cid)
    pre_2573_brief = cn.get("generation_brief")  # no allow-list, no facts — as it was
    report = _judge(gate, cn["coach_id"], cn["mutated_output"], pre_2573_brief)
    assert report["passed"] is True, "the pre-#2573 path should reproduce the measured pass"
    assert report["score"] == 92
    assert report["number_grounding"]["status"] == "no_grounding_context"


# ── 2. the deterministic verdict outranks the model ──────────────────────────
def test_model_cannot_overrule_the_deterministic_verdict(gate):
    """A judge that ignores criterion 5 entirely — or a future prompt edit that
    drops it — still cannot ship a draft the grounder failed. The consumption is
    structural, not a prompt instruction (this repo's own lesson: a prompt rule
    cannot guarantee structure)."""
    cn = _canary("canary_weight_fabricated")
    report = _judge(gate, cn["coach_id"], cn["mutated_output"], _brief_for(cn))
    assert report["score"] == 92 and report["passed"] is False, "score high, verdict blocked — the grounder decided"


def test_deterministic_block_survives_an_unreachable_judge(gate):
    """Deterministic-first: the permissive fallback exists for the LLM's opinion,
    not for the arithmetic."""
    cn = _canary("canary_hrv_fabricated")

    def _boom(*_a, **_k):
        raise RuntimeError("bedrock unreachable")

    real_call, real_load = gate._call_haiku, gate._load_voice_spec
    try:
        gate._call_haiku = _boom
        gate._load_voice_spec = lambda cid: {}
        report = gate.lambda_handler(quality_gate_event(cn["coach_id"], cn["mutated_output"], _brief_for(cn)), None)
    finally:
        gate._call_haiku, gate._load_voice_spec = real_call, real_load
    assert report["_fallback"] is True
    assert report["passed"] is False, "a fabricated number must block even when the judge is down"


# ── 3. honest absence ────────────────────────────────────────────────────────
def test_missing_allowlist_is_absence_not_a_clean_verdict(gate):
    r = gate._number_grounding_report("your HRV hit 58 ms", {"narrative_beat": "steady-state"})
    assert r["status"] == "no_grounding_context"
    assert r["verdict"] is None, "absence must never wear a verdict"
    assert "findings" not in r


def test_empty_allowlist_is_a_real_statement_and_is_honoured(gate):
    """An EMPTY allow-list means 'the coach was given no numbers', which is a real
    (if unusual) claim — distinct from 'nobody told me'."""
    brief = {GROUNDING_ALLOWLIST_KEY: [], AUTHORITATIVE_FACTS_KEY: {}}
    r = gate._number_grounding_report("your resting heart rate is 51 bpm", brief)
    assert r["status"] == "measured" and r["verdict"] == "ungrounded"


def test_detector_failure_is_reported_as_error_never_as_clean(gate):
    r = gate._number_grounding_report("text", {GROUNDING_ALLOWLIST_KEY: ["not-a-number"]})
    assert r["status"] == "error" and r["verdict"] is None


# ── 4. no false flags on the goldens ─────────────────────────────────────────
def test_no_golden_is_false_flagged_by_the_new_criterion(gate):
    """Sensitivity protection. The allow-list is the same one `golden_brief_eval`
    already asserts zero findings against, so this holds by construction — the test
    exists so a future change to either side cannot break it silently."""
    golden, _canaries = _fixtures()
    flagged = []
    for fx in golden:
        r = gate._number_grounding_report(fx["reference_output"], _brief_for(fx))
        if r.get("findings"):
            flagged.append((fx["id"], r["findings"]))
    assert not flagged, flagged


# ── 5. the rubric reaches the assembled prompt ───────────────────────────────
def test_criterion_5_is_in_the_system_prompt(gate):
    sp = gate.QUALITY_GATE_SYSTEM_PROMPT
    assert "Fabricated / Ungrounded Numbers" in sp
    assert "Number Grounding" in sp, "the criterion must point at the deterministic verdict it consumes"


def test_the_verdict_reaches_the_assembled_user_message(gate):
    """Assert on what the model is actually handed, not on a local constant."""
    cn = _canary("canary_glucose_trend_fabricated")
    captured = {}
    real_build = gate._build_quality_gate_message

    def _cap(*a, **k):
        msg = real_build(*a, **k)
        captured["prompt"] = msg
        return msg

    try:
        gate._build_quality_gate_message = _cap
        _judge(gate, cn["coach_id"], cn["mutated_output"], _brief_for(cn))
    finally:
        gate._build_quality_gate_message = real_build
    prompt = captured["prompt"]
    assert "## Number Grounding (deterministic verdict — ALREADY DECIDED)" in prompt
    assert "FAILED" in prompt


def test_unavailable_verdict_is_rendered_not_omitted(gate):
    """Silence in the prompt would read as 'clean' to the judge. The UNAVAILABLE
    state is rendered explicitly."""
    block = gate._number_grounding_block({"status": "no_grounding_context", "verdict": None})
    assert "UNAVAILABLE" in block
    assert "Do not guess" in block
    clean = gate._number_grounding_block({"status": "measured", "verdict": "clean", "findings": [], "n_allowed": 12})
    assert "CLEAN" in clean and "UNAVAILABLE" not in clean, "the two states must not read alike"


# ── the wire contract ────────────────────────────────────────────────────────
def test_brief_with_grounding_does_not_change_the_top_level_event_shape():
    """`tests/test_judge_calibration_1374.py` diffs the wire payload key-by-key
    against the live call site. Nesting the grounding context inside the brief
    keeps that contract intact."""
    plain = quality_gate_event("sleep_coach", "text", {"narrative_beat": "x"}, generation_date="2026-01-01")
    grounded = quality_gate_event(
        "sleep_coach", "text", brief_with_grounding({"narrative_beat": "x"}, {"rhr_bpm": 54}, {54.0}), generation_date="2026-01-01"
    )
    assert set(plain) == set(grounded)
    assert grounded["generation_brief"][GROUNDING_ALLOWLIST_KEY] == [54.0]
    assert json.dumps(grounded)  # the payload must survive the wire


def test_brief_with_grounding_is_pure():
    brief = {"narrative_beat": "x"}
    brief_with_grounding(brief, {"rhr_bpm": 54}, {54.0})
    assert brief == {"narrative_beat": "x"}, "the caller's brief must not be mutated"


def test_none_allowlist_is_not_attached():
    """The generation path's grounding gate did not run ⇒ no allow-list ⇒ the gate
    must see absence, not an empty list it would treat as authoritative."""
    out = brief_with_grounding({"narrative_beat": "x"}, {}, None)
    assert GROUNDING_ALLOWLIST_KEY not in out


# ── 6. #2815 — the wire event's clock agrees with the gate's own default ────────
def test_quality_gate_event_falls_back_to_the_pacific_day_at_a_pt_evening_instant(monkeypatch):
    """#2815: `quality_gate_event`'s `generation_date` fallback used naive
    `date.today()` (Lambda TZ=UTC). Production reaches this exact fallback —
    `ai_calls.py:1316` calls `quality_gate_event(coach_id, output_text, brief)`
    with NO generation_date. Pin a PT-evening instant (still today in Pacific,
    already tomorrow in UTC) and prove the stamped date is the PACIFIC day."""
    from datetime import datetime as _dt

    from ai.quality_gate_contract import quality_gate_event
    from common import pacific_time

    # 2026-03-04 20:00 PT (PST, UTC-8) == 2026-03-05 04:00 UTC — inside the 17:00-24:00 PT
    # window, and deliberately far from "today" so a naive `date.today()` regression
    # (which ignores this mock and reads the real wall clock) cannot pass by coincidence.
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _dt(2026, 3, 4, 20, 0))
    event = quality_gate_event("sleep_coach", "text", {"narrative_beat": "x"})
    assert event["generation_date"] == "2026-03-04", "stamped tomorrow's (UTC) date instead of today's (Pacific)"


def test_ai_calls_to_cycle_gate_params_chain_agrees_at_a_pt_evening_instant(monkeypatch):
    """The full chain the acceptance box names: `ai_calls.py:1316` (no explicit
    date) -> `coach_quality_gate.py:812` passes the wire event's date into
    `_number_grounding_report` -> `cycle_gate_params(generation_date)`. Before
    the fix, the wire event carried the naive-UTC day while `cycle_gate_params`'s
    OWN no-argument default (#2675) already used Pacific — so an event-supplied
    date silently OUTRANKED and desynced from the gate's Pacific default during
    this exact PT-evening window. Prove they now agree."""
    from datetime import datetime as _dt

    from ai.grounding_gate_params import cycle_gate_params
    from ai.quality_gate_contract import quality_gate_event
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _dt(2026, 3, 4, 20, 0))
    wire_event = quality_gate_event("sleep_coach", "text", {"narrative_beat": "x"})  # mirrors ai_calls.py:1316
    from_event = cycle_gate_params(wire_event["generation_date"])  # mirrors coach_quality_gate.py:812
    bare_default = cycle_gate_params(None)  # the gate's own #2675 Pacific default
    assert from_event["generation_date_iso"] == bare_default["generation_date_iso"] == "2026-03-04"
