"""test_judge_calibration_1374.py — the contract for the judge-calibration harness (#1374).

A calibration harness is only worth anything if it CANNOT report a flattering
number it did not measure. These tests pin exactly that, and each one was
mutation-proved in both directions before landing (break the scorer -> red;
restore -> green):

  * the corpus really carries BOTH classes and is not empty (a harness that
    passes against an empty or all-one-class corpus is the headline failure);
  * the replay tracks its REAL call site — the event is diffed key-by-key against
    the payload `_invoke_quality_gate_sync` puts on the wire;
  * the local voice specs actually reach the ASSEMBLED PROMPT (the S3-first trap:
    a spec that "loaded" but never made the prompt calibrates nothing);
  * a gate that cannot evaluate produces NOT_RUN, never a matrix — the fallback
    report wears `passed=True` and would otherwise manufacture sensitivity 1.0;
  * an all-pass judge reports specificity 0/5, and the harness says so;
  * every rate carries its denominator and an interval, and n=5 is marked thin.

Fully offline: `_call_haiku` is always stubbed here, so no Bedrock call is made.
"""

import json
import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judge_calibration as jc  # noqa: E402
import pytest  # noqa: E402


# ── deterministic stub judges (no Bedrock) ───────────────────────────────────
def _stub(score_for):
    """A `_call_haiku` replacement scoring by fixture id. `score_for` maps the
    output text to a score; the stub returns the gate's real JSON contract."""

    def _call(system, user_message, max_tokens=800, temperature=0.1):
        score = score_for(user_message)
        return {
            "passed": score >= 60,
            "score": score,
            "anti_pattern_violations": [],
            "decision_class_violations": [],
            "voice_distinctiveness_score": 70,
            "cross_coach_similarity_flags": [],
            "suggestions": [],
        }

    return _call


def _perfect_judge():
    """Scores the 5 canary texts low and everything else high — the judge the
    corpus would need to earn a clean matrix."""
    from judge_calibration import labeled_cases

    bad_texts = {c["output_text"] for c in labeled_cases() if c["label"] == jc.LABEL_DEFECTIVE}
    return _stub(lambda msg: 20 if any(t in msg for t in bad_texts) else 85)


def _all_pass_judge():
    return _stub(lambda msg: 95)


# ── the corpus is real, labeled, and two-class ───────────────────────────────
def test_corpus_is_not_empty_and_carries_both_classes():
    cases = jc.labeled_cases()
    good = [c for c in cases if c["label"] == jc.LABEL_GOOD]
    bad = [c for c in cases if c["label"] == jc.LABEL_DEFECTIVE]
    assert len(cases) == 35, len(cases)
    assert len(good) == 30, len(good)
    assert len(bad) == 5, len(bad)
    # No case may reach the judge without the brief production sends alongside it.
    assert all(isinstance(c["generation_brief"], dict) for c in cases)


def test_a_degenerate_corpus_is_an_ERROR_not_a_matrix():
    """The headline failure this task forbids: a calibration that 'passes' against
    a corpus with nothing to calibrate against."""
    good_only = [c for c in jc.labeled_cases() if c["label"] == jc.LABEL_GOOD]
    assert any("no LABEL_DEFECTIVE" in d for d in jc.corpus_defects(good_only))
    bad_only = [c for c in jc.labeled_cases() if c["label"] == jc.LABEL_DEFECTIVE]
    assert any("no LABEL_GOOD" in d for d in jc.corpus_defects(bad_only))
    assert jc.corpus_defects([]) == ["corpus is empty"]


def test_run_over_a_degenerate_corpus_emits_no_matrix(monkeypatch):
    monkeypatch.setattr(jc, "labeled_cases", lambda: [])
    r = jc.run(call_haiku=_perfect_judge())
    assert r["verdict"] == jc.ERROR
    assert "matrix" not in r


# ── the replay tracks its real call site ─────────────────────────────────────
def test_replay_event_is_byte_identical_to_the_production_wire_payload():
    """The 'harness must track its call site' rule, enforced structurally.

    Capture what `_invoke_quality_gate_sync` actually puts on the wire and diff it
    key-by-key against `quality_gate_event` — the builder the harness replays
    through. A hand-rebuilt production call drifts silently; this makes drift red.
    """
    from ai import ai_calls

    sent = {}

    class _FakeClient:
        def invoke(self, **kwargs):
            sent.update(kwargs)

            class _P:
                @staticmethod
                def read():
                    return json.dumps({"passed": True, "score": 90}).encode()

            return {"Payload": _P()}

    brief = {"decision_class_ceiling": "observational"}
    ai_calls._invoke_quality_gate_sync(_FakeClient(), "sleep_coach", "text under test", brief)

    assert sent["FunctionName"] == ai_calls.QUALITY_GATE_FUNCTION_NAME
    assert sent["InvocationType"] == "RequestResponse"
    wire = json.loads(sent["Payload"].decode())
    built = ai_calls.quality_gate_event("sleep_coach", "text under test", brief, generation_date=wire["generation_date"])

    assert set(wire) == set(built), f"key drift: wire={sorted(wire)} builder={sorted(built)}"
    for k in sorted(built):
        assert wire[k] == built[k], f"kwarg {k!r} drifted: wire={wire[k]!r} builder={built[k]!r}"


def test_the_harness_replays_through_that_same_builder(monkeypatch):
    """Guards the other half, behaviourally: neuter `quality_gate_event` and the
    replay must break. If the harness grew its own event dict this stays green
    while silently calibrating a payload production never sends."""
    import inspect

    from ai import quality_gate_contract
    from coach import coach_quality_gate as gate

    sentinel = RuntimeError("quality_gate_event was bypassed")

    def _explode(*a, **k):
        raise sentinel

    monkeypatch.setattr(quality_gate_contract, "quality_gate_event", _explode)
    with pytest.raises(RuntimeError) as exc:
        jc._judge_one(gate, jc.labeled_cases()[0], call_haiku=_all_pass_judge())
    assert exc.value is sentinel

    # …and the event payload is not re-typed anywhere in the replay.
    src = inspect.getsource(jc._judge_one)
    assert "quality_gate_event(" in src
    assert '"output_text":' not in src, "harness is hand-building the event payload — the drift class #1374 forbids"
    assert '"generation_date":' not in src


def test_a_non_dict_brief_is_nulled_exactly_as_production_does():
    from ai import ai_calls
    from ai.quality_gate_contract import quality_gate_event

    assert quality_gate_event("c", "t", "not-a-dict", generation_date="2026-01-01")["generation_brief"] is None
    # the caller module must keep exposing the shared builder, not grow its own
    assert ai_calls.quality_gate_event is quality_gate_event


# ── the S3-first trap: assert on the ASSEMBLED PROMPT ────────────────────────
def test_local_voice_specs_actually_reach_the_assembled_prompt():
    """Production loads specs from S3; this replay serves the repo copy. Trusting
    that a spec 'was loaded' proves nothing — assert the coach's own blacklist
    phrase is present in the message the model receives."""
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    probed = [x for x in r["results"] if x["voice_spec_reached_prompt"] is not None]
    assert probed, "no fixture had a blacklist phrase to probe with — the prompt check is vacuous"
    assert all(x["voice_spec_reached_prompt"] for x in probed), [x["id"] for x in probed if not x["voice_spec_reached_prompt"]]
    assert r["voice_spec_reached_prompt_n"] >= 30, r["voice_spec_reached_prompt_n"]
    assert all(x["prompt_chars"] > 200 for x in r["results"])


def test_the_fidelity_gaps_are_stated_in_every_report():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    joined = " ".join(r["fidelity_gaps"])
    assert "S3" in joined and "DynamoDB" in joined
    assert "cross-coach" in joined.lower()


# ── a gate that cannot evaluate must not produce a matrix ────────────────────
def test_the_permissive_fallback_is_never_counted_as_a_pass():
    """`_run_quality_gate` swallows every exception and returns passed=True,
    score=50. Counted naively that is sensitivity 30/30 out of a dead endpoint."""

    def _boom(system, user_message, max_tokens=800, temperature=0.1):
        raise RuntimeError("simulated Bedrock outage")

    r = jc.run(call_haiku=_boom, check_budget=False)
    assert r["verdict"] == jc.NOT_RUN, r.get("matrix")
    assert "matrix" not in r
    assert r["n_unavailable"] == 35
    assert all(not x["usable"] for x in r["results"])
    assert any("fallback" in reason for reason in r["unavailable_reasons"])


def test_a_partial_outage_shrinks_the_denominator_rather_than_the_truth():
    """Some cases evaluate, some do not. Every rate must count only the ones that
    did — a denominator of 35 over 20 real verdicts is a fabricated n."""
    from judge_calibration import labeled_cases

    bad_texts = {c["output_text"] for c in labeled_cases() if c["label"] == jc.LABEL_DEFECTIVE}
    state = {"n": 0}

    def _flaky(system, user_message, max_tokens=800, temperature=0.1):
        state["n"] += 1
        if state["n"] % 3 == 0:
            raise RuntimeError("simulated throttle")
        score = 20 if any(t in user_message for t in bad_texts) else 85
        return {"passed": score >= 60, "score": score, "voice_distinctiveness_score": 70}

    r = jc.run(call_haiku=_flaky, check_budget=False)
    assert r["verdict"] == jc.MEASURED
    m = r["matrix"]
    assert 0 < r["n_unavailable"] < 35
    assert m["n_usable"] == 35 - r["n_unavailable"]
    assert m["n_positives_good"] + m["n_negatives_defective"] == m["n_usable"]
    assert sum(m["cells"].values()) == m["n_usable"]


def test_budget_tier_three_reports_not_run_not_a_matrix(monkeypatch):
    monkeypatch.setattr(jc, "budget_tier", lambda: 3)
    r = jc.run()
    assert r["verdict"] == jc.NOT_RUN
    assert "matrix" not in r
    assert "tier 3" in r["not_run_reason"]


# ── the matrix arithmetic ────────────────────────────────────────────────────
def test_a_perfect_judge_yields_the_expected_cells():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    assert r["verdict"] == jc.MEASURED
    c = r["matrix"]["cells"]
    assert c == {"golden_passed_tp": 30, "golden_failed_fn": 0, "canary_failed_tn": 5, "canary_passed_fp": 0}
    assert r["matrix"]["sensitivity_agrees_with_good_work"]["denominator"] == 30
    assert r["matrix"]["specificity_catches_defects"]["denominator"] == 5


def test_an_all_pass_judge_reports_zero_specificity_and_says_so():
    """The flattering-looking failure: a judge that passes everything scores a
    perfect sensitivity. The report must not read as good news."""
    r = jc.run(call_haiku=_all_pass_judge(), check_budget=False)
    m = r["matrix"]
    assert m["cells"]["canary_failed_tn"] == 0
    assert m["specificity_catches_defects"]["point"] == 0.0
    assert m["sensitivity_agrees_with_good_work"]["point"] == 1.0
    assert "specificity 0/5" in jc.ops_line(r)
    assert any("lower bound" in s for s in r["cannot_support"])


def test_the_matrix_is_sensitive_to_a_single_flipped_verdict():
    """Mutation in-test: flip ONE canary to passing and exactly one cell moves."""
    from judge_calibration import labeled_cases

    cases = labeled_cases()
    bad = [c for c in cases if c["label"] == jc.LABEL_DEFECTIVE]
    leaked, rest = bad[0]["output_text"], {c["output_text"] for c in bad[1:]}
    judge = _stub(lambda msg: 85 if (leaked in msg or not any(t in msg for t in rest)) else 20)
    c = jc.run(call_haiku=judge, check_budget=False)["matrix"]["cells"]
    assert c == {"golden_passed_tp": 30, "golden_failed_fn": 0, "canary_failed_tn": 4, "canary_passed_fp": 1}


# ── uncertainty is mandatory, and n=5 is loud about being thin ───────────────
def test_every_rate_carries_numerator_denominator_and_interval():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    m = r["matrix"]
    for key in ("sensitivity_agrees_with_good_work", "specificity_catches_defects", "accuracy_overall"):
        rt = m[key]
        assert set(("numerator", "denominator", "point", "ci95_wilson", "thin")).issubset(rt), key
        assert rt["denominator"] > 0 and rt["ci95_wilson"] is not None, key
        assert not isinstance(rt, float), key


def test_five_negatives_is_reported_as_a_thin_denominator():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    spec = r["matrix"]["specificity_catches_defects"]
    assert spec["denominator"] == 5
    assert spec["thin"] is True
    assert "below the 10-case floor" in spec["note"]
    # 5/5 does NOT license "the judge catches ~100% of defects".
    lo, hi = spec["ci95_wilson"]
    assert lo < 0.6, f"a 5/5 lower bound of {lo} would overstate what 5 cases can show"
    assert any("Do not publish" in s for s in r["cannot_support"])
    assert any("n=5" in s or "n=5 " in s for s in r["cannot_support"])


def test_thirty_positives_is_not_flagged_thin():
    """The thin flag must discriminate, not decorate everything."""
    assert jc.rate(30, 30)["thin"] is False
    assert jc.rate(5, 5)["thin"] is True


def test_wilson_is_not_the_normal_approximation_at_saturation():
    """The reason Wilson: at 5/5 the normal approximation gives the zero-width
    interval [1.0, 1.0], which is exactly the overstated precision this issue
    exists to prevent."""
    lo5, hi5 = jc.wilson_interval(5, 5)
    assert hi5 == 1.0 and lo5 < 0.6, (lo5, hi5)
    lo30, hi30 = jc.wilson_interval(30, 30)
    assert lo30 > lo5, "a 30-case interval must be tighter than a 5-case one"
    # a textbook checkpoint: 50/100 -> approximately [0.404, 0.596]
    lo, hi = jc.wilson_interval(50, 100)
    assert abs(lo - 0.4038) < 0.001 and abs(hi - 0.5962) < 0.001, (lo, hi)
    assert jc.wilson_interval(0, 0) is None


def test_a_rate_with_no_denominator_refuses_to_exist():
    r = jc.rate(0, 0)
    assert r["point"] is None and r["ci95_wilson"] is None
    assert "no rate exists" in r["note"]


# ── the corpus/rubric mismatch is measured, not asserted in prose ────────────
def test_rubric_scope_classifies_each_canary_fault_class():
    """The judge's prompt has four criteria — anti-patterns, decision class, voice
    distinctiveness, cross-coach similarity — and NO rule about fabricated numbers
    or contradicted vitals. That mismatch has to be a computed fact."""
    assert jc.rubric_scope(["anti_pattern"]) == jc.IN_RUBRIC
    assert jc.rubric_scope(["evidence_ceiling"]) == jc.ADJACENT
    assert jc.rubric_scope(["grounding_contradiction"]) == jc.OUT_OF_RUBRIC
    # weakest link wins, and an unknown/absent class is never optimistically scoped
    assert jc.rubric_scope(["anti_pattern", "grounding_contradiction"]) == jc.OUT_OF_RUBRIC
    assert jc.rubric_scope([]) == jc.OUT_OF_RUBRIC
    assert jc.rubric_scope(["something_new"]) == jc.OUT_OF_RUBRIC


def test_only_one_of_the_five_negatives_is_in_rubric():
    bad = [c for c in jc.labeled_cases() if c["label"] == jc.LABEL_DEFECTIVE]
    scopes = [c["rubric_scope"] for c in bad]
    assert scopes.count(jc.IN_RUBRIC) == 1, scopes
    assert scopes.count(jc.IN_RUBRIC) + scopes.count(jc.ADJACENT) + scopes.count(jc.OUT_OF_RUBRIC) == 5


def test_specificity_is_split_by_rubric_scope_and_every_split_is_thin():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    scoped = r["matrix"]["specificity_by_rubric_scope"]
    assert set(scoped) == {jc.IN_RUBRIC, jc.ADJACENT, jc.OUT_OF_RUBRIC}
    assert sum(s["denominator"] for s in scoped.values()) == 5
    assert scoped[jc.IN_RUBRIC]["denominator"] == 1
    assert all(s["thin"] for s in scoped.values()), "a sub-rate over 1-3 cases must never be presented as a figure"


def test_the_corpus_rubric_mismatch_is_stated_in_what_it_cannot_support():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    joined = " ".join(r["cannot_support"])
    assert "CORPUS/RUBRIC MISMATCH" in joined
    assert "only 1 of the 5 negatives" in joined
    assert "coverage gap" in joined


# ── the report says what it cannot support, even when it looks good ──────────
def test_a_clean_matrix_still_states_what_it_cannot_support():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    joined = " ".join(r["cannot_support"])
    assert "hand-authored" in joined.lower()
    assert "margin-aware" in joined.lower(), "the un-derivable third acceptance item must be stated, not quietly skipped"
    assert len(r["cannot_support"]) >= 3


def test_text_report_renders_the_matrix_with_its_n():
    out = jc.text_report(jc.run(call_haiku=_perfect_judge(), check_budget=False))
    assert "n=30" in out and "n= 5" in out
    assert "95% CI" in out and "THIN" in out
    assert "CANNOT support" in out


def test_text_report_for_not_run_emits_no_numbers(monkeypatch):
    monkeypatch.setattr(jc, "budget_tier", lambda: 3)
    out = jc.text_report(jc.run())
    assert "NOT RUN" in out
    assert "sensitivity" not in out.lower() and "specificity" not in out.lower()


# ── which mechanism actually blocked ─────────────────────────────────────────
def test_threshold_attribution_separates_the_numeric_gate_from_the_model_boolean():
    """`_run_quality_gate` only ever TIGHTENS the model's boolean. A block at a
    score above the threshold was decided by the model, not the threshold — and
    calibrating 'against PASS_SCORE_THRESHOLD' has to admit which one is deciding."""
    from judge_calibration import labeled_cases

    cases = labeled_cases()
    bad = {c["output_text"] for c in cases if c["label"] == jc.LABEL_DEFECTIVE}
    first_good = next(c["output_text"] for c in cases if c["label"] == jc.LABEL_GOOD)

    def _call(system, user_message, max_tokens=800, temperature=0.1):
        if any(t in user_message for t in bad):
            return {"passed": False, "score": 20, "voice_distinctiveness_score": 70}  # numeric gate
        if first_good in user_message:
            return {"passed": False, "score": 75, "voice_distinctiveness_score": 70}  # model boolean, above 60
        return {"passed": True, "score": 90, "voice_distinctiveness_score": 70}

    ta = jc.run(call_haiku=_call, check_budget=False)["threshold_attribution"]
    assert ta["threshold"] == 60
    assert ta["n_fail_decisions"] == 6
    assert ta["by_score_threshold"] == 5
    assert ta["by_model_boolean_at_or_above_threshold"] == 1
    assert ta["model_boolean_ids"] == ["sleep_01"]
    assert "note" not in ta, "the note must only fire when the model boolean DOMINATES"


def test_a_score_exactly_at_the_threshold_is_attributed_to_the_model_not_the_gate():
    """The boundary the production code actually tests is `score < THRESHOLD`, so
    a fail at EXACTLY 60 was the model's call, not the numeric gate's. Without a
    case sitting on the boundary, `>=` and `>` are indistinguishable and the
    attribution split is untested where it matters most."""

    def _call(system, user_message, max_tokens=800, temperature=0.1):
        return {"passed": False, "score": 60, "voice_distinctiveness_score": 70}

    ta = jc.run(call_haiku=_call, check_budget=False)["threshold_attribution"]
    assert ta["n_fail_decisions"] == 35
    assert ta["by_score_threshold"] == 0, "score == threshold must NOT be credited to the numeric gate"
    assert ta["by_model_boolean_at_or_above_threshold"] == 35


def test_a_dominant_model_boolean_earns_the_threshold_is_inert_note():
    def _call(system, user_message, max_tokens=800, temperature=0.1):
        return {"passed": False, "score": 62, "voice_distinctiveness_score": 70}

    ta = jc.run(call_haiku=_call, check_budget=False)["threshold_attribution"]
    assert ta["by_score_threshold"] == 0
    assert ta["by_model_boolean_at_or_above_threshold"] == 35
    assert "not the operative control" in ta["note"]


# ── --json must be machine-parseable (the gate logs to stdout) ───────────────
def test_json_mode_emits_exactly_one_parseable_document(monkeypatch, capsys):
    """The gate's structured logger writes JSON lines to stdout; unquieted they
    interleave with the report and `--json` yields something no tool can read.

    Stubs `_call_haiku` on the gate module itself (not via the `call_haiku` arg)
    so this drives the real no-arg `run()` path the CLI uses — including the
    logger quieting — without a Bedrock call.
    """
    import golden_brief_eval as gbe
    from coach import coach_quality_gate as gate

    monkeypatch.setattr(gate, "_call_haiku", _perfect_judge())
    monkeypatch.setattr(jc, "budget_tier", lambda: 0)

    assert gbe.main(["--judge-calibration", "--json"]) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)  # raises if any log line leaked into stdout
    assert parsed["verdict"] == jc.MEASURED
    assert parsed["matrix"]["n_usable"] == 35


def test_the_gate_logger_is_quiet_during_the_replay_and_restored_after():
    """Asserted from INSIDE the replay, not via capsys.

    The gate's structured logger binds its own stream handler, so a leaked log
    line does not reach capsys and a stdout assertion cannot see this failure at
    all. Sampling the effective level at each call site is the check that
    actually discriminates.
    """
    import logging

    from coach import coach_quality_gate as gate

    seen = []

    def _call(system, user_message, max_tokens=800, temperature=0.1):
        seen.append(gate.logger.level)
        return {"passed": True, "score": 90, "voice_distinctiveness_score": 70}

    gate.logger.setLevel(logging.INFO)
    try:
        jc.run(call_haiku=_call, check_budget=False)
        assert len(seen) == 35
        assert set(seen) == {logging.WARNING}, f"gate logger was not quieted during the replay: {sorted(set(seen))}"
        assert gate.logger.level == logging.INFO, "quieting leaked out of the run"
    finally:
        gate.logger.setLevel(logging.INFO)


# ── threshold sweep is honest about being derived ────────────────────────────
def test_threshold_sweep_starts_at_the_real_threshold_and_claims_no_new_n():
    r = jc.run(call_haiku=_perfect_judge(), check_budget=False)
    sweep = r["threshold_sweep"]
    assert sweep["rows"][0]["threshold"] == r["threshold"] == 60
    assert "adds no independent n" in sweep["basis"]
    # monotone: raising the bar can only pass fewer goldens
    passed = [row["golden_passed"] for row in sweep["rows"]]
    assert passed == sorted(passed, reverse=True), passed


# ── the mode is reachable from the documented entry point ────────────────────
def test_golden_brief_eval_exposes_the_judge_calibration_flag(monkeypatch, capsys):
    import golden_brief_eval as gbe

    monkeypatch.setattr(jc, "run", lambda: {"verdict": jc.ERROR, "corpus_defects": ["stub"], "corpus": {"n_total": 0}})
    assert gbe.main(["--judge-calibration"]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_the_deterministic_verdict_is_unchanged_by_this_story():
    """#1374 must not perturb the deploy-gating harness it plugs into."""
    import golden_brief_eval as gbe

    assert gbe.run()["verdict"] == gbe.OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
