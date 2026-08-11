"""judge_calibration.py — calibrate the coach quality-gate JUDGE as an instrument (#1374).

The quality gate (`lambdas/coach/coach_quality_gate.py`) is an LLM that decides
whether a coach's draft ships. Since ADR-108/#390 its verdict is BLOCKING. Nothing
has ever measured the judge itself: how often does it pass work that is genuinely
good, and how often does it catch work that is genuinely bad? Published verdicts
without those two numbers are an instrument reading with no calibration certificate.

WHY THIS COULD BE BUILT TODAY (the stale-blocker correction, #1374)
────────────────────────────────────────────────────────────────────
The issue was deferred on "unblocked by ~30 days of verdict history". That wait can
never end, because no true-negative is ever persisted:

  * `lambdas/experiment/eval_retention.py` — the module docstring's Design section
    states it outright ("Only FLAGGED events are retained"), and `retain()`'s own
    docstring enumerates a verdict vocabulary that is entirely `flagged_*`.
  * `lambdas/ai/ai_calls.py::_enforce_quality_gate` — computes
    `fired = not report.get("passed", True)` and calls `_retain_coach_brief_flag`
    only under `if fired:`. A passing verdict is retained nowhere.
  * `lambdas/coach/coach_quality_gate.py` — contains zero `put_item` calls. The
    gate persists nothing at all; it logs a one-line summary (coach, passed,
    score, counts) that carries neither the draft nor the brief, so a log line is
    not replayable even if it were retained.

So the retained corpus can only ever contain the judge's own POSITIVES, and they
carry no independent ground-truth label. Sensitivity and specificity are both
undefined on it, at 30 days and at 300.

Meanwhile the labeled set the acceptance criteria ask for already exists and has
since #742: `tests/fixtures/golden_briefs/golden.json` holds 30 hand-authored
known-good coach outputs and `canaries.json` holds 5 fault-injected ones — 35
labeled cases, each carrying a `generation_brief`, which is exactly the shape
`coach_quality_gate._run_quality_gate` consumes. That is the golden set.

WHAT THIS HARNESS DOES
──────────────────────
Replays all 35 labeled cases through the gate's REAL entry point
(`coach_quality_gate.lambda_handler`) using the REAL production event payload
(`ai_calls.quality_gate_event` — the same function `_invoke_quality_gate_sync`
puts on the wire, so the replay cannot drift from the call site), and reports a
confusion matrix against `PASS_SCORE_THRESHOLD`.

THE HONESTY CONTRACT (ADR-104 honest numbers, ADR-105 rigor bar)
────────────────────────────────────────────────────────────────
1. Every rate carries its denominator, and the denominator counts only cases that
   produced a REAL verdict. `_run_quality_gate` swallows every exception and
   returns `_build_fallback_report` — `passed=True, score=50`. Counting those as
   passes would manufacture a flattering sensitivity out of a dead Bedrock
   endpoint. They are excluded and reported as `unavailable`.
2. Uncertainty, not point estimates. Every rate ships a 95% Wilson score interval.
3. **5 negatives is a thin specificity denominator.** With 5 canaries, even a
   perfect 5/5 has a 95% Wilson lower bound near 0.57 — the measurement cannot
   distinguish an excellent judge from a mediocre one. `THIN_DENOMINATOR_N` marks
   it in the report and the text renderer says it in words. A specificity figure
   from this corpus is a floor-and-ceiling, never a precise number.
4. Deterministic before LLM: the corpus shape, the labels, and the matrix
   arithmetic are all plain code. The LLM only supplies per-case verdicts.
5. If the judge cannot be reached at all, the verdict is `NOT_RUN` and NO matrix
   is emitted. A calibration harness that reports numbers when the instrument did
   not run is the precise failure this issue exists to prevent.

FIDELITY GAPS — what a hermetic replay is NOT measuring
──────────────────────────────────────────────────────
Production's event omits `voice_spec` and `other_coach_outputs`, so the live gate
loads specs from S3 and queries DynamoDB for peer outputs. A local replay cannot,
so it substitutes. Both substitutions change the assembled prompt, so both are
recorded in `FIDELITY_GAPS` and echoed in every report. In particular the voice
specs come from the repo's `config/coaches/*.json`, NOT from S3 — if S3 has
drifted from the repo, this harness calibrated the repo's judge. The harness
asserts on the ASSEMBLED PROMPT (`voice_spec_reached_prompt`) rather than trusting
that a spec was loaded.

Run:
    python3 tests/golden_brief_eval.py --judge-calibration          # Bedrock spend (~35 Haiku calls)
    python3 tests/golden_brief_eval.py --judge-calibration --json
"""

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

# ── verdict levels ───────────────────────────────────────────────────────────
MEASURED = "MEASURED"
NOT_RUN = "NOT_RUN"
ERROR = "ERROR"

# Ground-truth labels. The convention is stated explicitly in every report because
# "positive" is ambiguous for a gate: here POSITIVE = the output is genuinely
# publishable (a golden), NEGATIVE = the output carries an induced defect (a
# canary). Under that convention `sensitivity` is the judge's agreement with good
# work and `specificity` is its catch rate on bad work.
LABEL_GOOD = "good"
LABEL_DEFECTIVE = "defective"
CONVENTION = "positive = output is genuinely publishable (golden); negative = output carries an induced defect (canary)"

# Below this many labeled cases in a class, a rate computed on it is reported as a
# bound, never as a figure. 5 canaries sit under it — deliberately loud.
THIN_DENOMINATOR_N = 10

_Z95 = 1.959963984540054

# ── the corpus/rubric mismatch, made explicit ────────────────────────────────
# The 5 canaries were authored (#742) to exercise the DETERMINISTIC honesty gate.
# The LLM judge being calibrated here scores an entirely different rubric —
# `coach_quality_gate.QUALITY_GATE_SYSTEM_PROMPT` has exactly four criteria:
# anti-patterns, decision-class compliance, voice distinctiveness, cross-coach
# similarity. There is NO criterion for a fabricated number and none for
# contradicting a canonical vital. So most of the available negatives sit outside
# what this judge was ever asked to look for, and a raw specificity over all five
# would quietly indict the judge for missing faults that are not its job.
#
# This mapping is the deterministic record of that mismatch. It is not a defence
# of the judge: a fault the blocking gate cannot see is still a fault that ships.
# It is the difference between "the judge is bad at its rubric" and "the rubric
# has a hole", which are different findings with different fixes.
IN_RUBRIC = "in_rubric"  # criterion 1 (anti-pattern) — squarely the judge's job
ADJACENT = "adjacent"  # criterion 2 talks about an "evidence ceiling", but in the
# recommendation-strength sense, not the invented-number sense
OUT_OF_RUBRIC = "out_of_rubric"  # no criterion mentions it at all

# The rubric AS MEASURED 2026-08-11 (#2573's finding): four criteria, none of which
# mentions an invented number. Kept verbatim so the before/after split is legible
# rather than asserted — the whole point of the finding was that the gap was
# readable off the criteria list.
RUBRIC_SCOPE_PRE_2573 = {
    "anti_pattern": IN_RUBRIC,
    "evidence_ceiling": ADJACENT,
    "grounding_contradiction": OUT_OF_RUBRIC,
}

# The rubric after #2573 adds criterion 5 (fabricated / ungrounded numbers), which
# CONSUMES the deterministic ADR-104 verdict rather than re-deciding it. Both the
# fabricated-number class ("evidence_ceiling" in the deterministic eval's labelling)
# and the canonical-contradiction class are now squarely in scope.
RUBRIC_SCOPE_POST_2573 = {
    "anti_pattern": IN_RUBRIC,
    "evidence_ceiling": IN_RUBRIC,
    "grounding_contradiction": IN_RUBRIC,
}

RUBRIC_SCOPE = RUBRIC_SCOPE_POST_2573  # what the CURRENT judge is asked to look for


def rubric_scope(expect_checks, mapping=None):
    """Weakest-link scope for one canary: a fault is only IN_RUBRIC if every check
    it expects is."""
    mapping = mapping if mapping is not None else RUBRIC_SCOPE
    scopes = {mapping.get(c, OUT_OF_RUBRIC) for c in (expect_checks or [])}
    if not scopes:
        return OUT_OF_RUBRIC
    for level in (OUT_OF_RUBRIC, ADJACENT, IN_RUBRIC):
        if level in scopes:
            return level
    return OUT_OF_RUBRIC


# The two substitutions a hermetic replay must make, because production's event
# (see ai_calls.quality_gate_event) carries neither. Echoed in every report.
FIDELITY_GAPS = (
    "voice_spec: production's gate reads config/coaches/{coach}.json from S3; this replay serves the "
    "REPO copy. If S3 has drifted from the repo, this calibrated the repo's judge, not production's.",
    "other_coach_outputs: production's gate queries DynamoDB for each peer coach's latest OUTPUT# and "
    "puts them in the prompt for the cross-coach-similarity criterion (20% of the rubric). This replay "
    "supplies none, so criterion 4 is scored against an empty comparison set.",
)


# ── uncertainty ──────────────────────────────────────────────────────────────
def wilson_interval(k, n, z=_Z95):
    """95% Wilson score interval for k successes in n trials. Pure arithmetic — no
    scipy, no LLM. Wilson (not normal-approximation) precisely because n is small
    and k/n saturates at 1.0 here, where the normal approximation returns the
    absurd zero-width interval [1.0, 1.0]."""
    if not n:
        return None
    p = k / n
    denom = 1.0 + (z * z) / n
    centre = (p + (z * z) / (2 * n)) / denom
    half = (z / denom) * math.sqrt((p * (1.0 - p)) / n + (z * z) / (4.0 * n * n))
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def rate(k, n):
    """A rate that refuses to exist without its denominator.

    Returns a dict, never a bare float — a bare float is how a point estimate
    escapes its n and gets quoted as a measurement (ADR-105).
    """
    out = {
        "numerator": k,
        "denominator": n,
        "point": round(k / n, 4) if n else None,
        "ci95_wilson": wilson_interval(k, n),
        "thin": bool(n and n < THIN_DENOMINATOR_N),
    }
    if not n:
        out["note"] = "no usable verdicts in this class — no rate exists"
    elif out["thin"]:
        lo, hi = out["ci95_wilson"]
        out["note"] = (
            f"n={n} is below the {THIN_DENOMINATOR_N}-case floor: the 95% interval spans "
            f"{round((hi - lo) * 100, 1)} points ([{lo}, {hi}]). Read this as a bound, not a figure."
        )
    return out


# ── the labeled corpus ───────────────────────────────────────────────────────
def labeled_cases():
    """The 35 labeled cases: 30 goldens (LABEL_GOOD) + 5 canaries (LABEL_DEFECTIVE).

    Deterministic, offline, no AWS. Each case carries the text the judge sees and
    the `generation_brief` production would have sent alongside it.
    """
    import golden_brief_eval as gbe
    from ai.quality_gate_contract import brief_with_grounding

    def _brief(fx):
        """The brief production now ships (#2573): the fixture's own brief plus the
        DETERMINISTIC grounding context — canonical facts and the numeric allow-list
        the generation path computed. `gbe.allowed_for` is the same allow-list the
        deterministic eval curated these 30 goldens against, so a golden cannot be
        false-flagged here without also failing `golden_brief_eval`."""
        return brief_with_grounding(fx.get("generation_brief"), fx.get("authoritative_facts") or {}, gbe.allowed_for(fx))

    golden, canaries = gbe.load_fixtures()
    cases = []
    for fx in golden:
        cases.append(
            {
                "id": fx["id"],
                "coach_id": fx["coach_id"],
                "label": LABEL_GOOD,
                "output_text": fx["reference_output"],
                "generation_brief": _brief(fx),
            }
        )
    for cn in canaries:
        cases.append(
            {
                "id": cn["id"],
                "coach_id": cn["coach_id"],
                "label": LABEL_DEFECTIVE,
                "output_text": cn["mutated_output"],
                "generation_brief": _brief(cn),
                "mutation": cn.get("mutation"),
                "expect_checks": cn.get("expect_checks") or [],
                "rubric_scope": rubric_scope(cn.get("expect_checks")),
                "rubric_scope_pre_2573": rubric_scope(cn.get("expect_checks"), RUBRIC_SCOPE_PRE_2573),
            }
        )
    return cases


def corpus_defects(cases):
    """Reasons this corpus cannot support a calibration at all. A harness that
    happily computes a matrix over an empty or single-class corpus is worse than
    one that computes nothing — it reports confidence it never earned."""
    problems = []
    if not cases:
        problems.append("corpus is empty")
        return problems
    good = sum(1 for c in cases if c["label"] == LABEL_GOOD)
    bad = sum(1 for c in cases if c["label"] == LABEL_DEFECTIVE)
    if not good:
        problems.append("corpus has no LABEL_GOOD cases — sensitivity is undefined")
    if not bad:
        problems.append("corpus has no LABEL_DEFECTIVE cases — specificity is undefined")
    missing_brief = [c["id"] for c in cases if not isinstance(c.get("generation_brief"), dict)]
    if missing_brief:
        problems.append(f"{len(missing_brief)} case(s) carry no generation_brief dict: {missing_brief[:5]}")
    return problems


# ── replaying one case through the gate's real entry point ───────────────────
def _repo_voice_spec(coach_id):
    """The repo's copy of a coach voice spec — the local stand-in for the S3 read
    production does. Returns {} when absent, mirroring `_load_voice_spec`."""
    path = os.path.join(_REPO, "config", "coaches", f"{coach_id}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _blacklist_probe(spec):
    """A phrase from this coach's own blacklist that must appear in the assembled
    prompt if the spec really reached it. Returns None when the spec has none —
    then `voice_spec_reached_prompt` is reported as None (unknown), never True."""
    phrases = ((spec.get("anti_pattern_detection") or {}).get("phrase_blacklist")) or []
    for p in phrases:
        if isinstance(p, str) and p.strip():
            return p
    return None


def _judge_one(gate, case, call_haiku=None, generation_date="2026-01-01"):
    """Replay ONE labeled case through `coach_quality_gate.lambda_handler`.

    The event is built by `ai_calls.quality_gate_event` — the same function the
    production wire path uses — so the replay tracks its call site by
    construction rather than by resemblance.

    Substitutes for the two AWS reads production's event forces (see
    FIDELITY_GAPS) and captures the ASSEMBLED PROMPT so the report can assert
    what actually reached the model instead of what we assume was loaded.
    """
    from ai.quality_gate_contract import quality_gate_event

    event = quality_gate_event(case["coach_id"], case["output_text"], case["generation_brief"], generation_date=generation_date)

    spec = _repo_voice_spec(case["coach_id"])
    probe = _blacklist_probe(spec)
    captured = {}

    real_build = gate._build_quality_gate_message
    real_load = gate._load_voice_spec
    real_peers = gate._fetch_other_coaches_recent_outputs
    real_query = gate._query_begins_with
    real_call = gate._call_haiku

    def _capturing_build(*a, **k):
        msg = real_build(*a, **k)
        captured["prompt"] = msg
        return msg

    try:
        gate._build_quality_gate_message = _capturing_build
        gate._load_voice_spec = lambda cid: _repo_voice_spec(cid)
        gate._fetch_other_coaches_recent_outputs = lambda cid, other_coach_ids=None: {}
        gate._query_begins_with = lambda *a, **k: []
        if call_haiku is not None:
            gate._call_haiku = call_haiku
        report = gate.lambda_handler(event, None)
    finally:
        gate._build_quality_gate_message = real_build
        gate._load_voice_spec = real_load
        gate._fetch_other_coaches_recent_outputs = real_peers
        gate._query_begins_with = real_query
        gate._call_haiku = real_call

    prompt = captured.get("prompt")
    if probe is None or prompt is None:
        reached = None
    else:
        reached = probe.lower() in prompt.lower()

    # A fallback report is NOT a verdict — it is the gate saying "I could not
    # evaluate", wearing passed=True. Same for the handler's own 500 path.
    unavailable_reason = None
    if not isinstance(report, dict):
        unavailable_reason = f"non-dict gate return: {type(report).__name__}"
    elif report.get("_fallback"):
        sug = (report.get("suggestions") or [""])[0]
        unavailable_reason = f"gate returned its permissive fallback report ({sug})"
    elif report.get("statusCode") not in (200, None):
        unavailable_reason = f"gate returned statusCode={report.get('statusCode')}: {report.get('error')}"
    elif not isinstance(report.get("score"), (int, float)):
        unavailable_reason = f"gate returned no numeric score (score={report.get('score')!r})"

    return {
        "id": case["id"],
        "coach_id": case["coach_id"],
        "label": case["label"],
        "score": report.get("score") if isinstance(report, dict) else None,
        "judge_passed": bool(report.get("passed")) if isinstance(report, dict) else None,
        "voice_distinctiveness_score": report.get("voice_distinctiveness_score") if isinstance(report, dict) else None,
        "rubric_scope": case.get("rubric_scope"),
        "rubric_scope_pre_2573": case.get("rubric_scope_pre_2573"),
        "mutation": case.get("mutation"),
        # #2573: which mechanism spoke. `deterministic_verdict` is the ADR-104
        # grounder's answer, computed before the LLM; `deterministic_block` is
        # whether it alone was sufficient to fail the draft.
        "deterministic_status": (report.get("number_grounding") or {}).get("status") if isinstance(report, dict) else None,
        "deterministic_verdict": (report.get("number_grounding") or {}).get("verdict") if isinstance(report, dict) else None,
        "deterministic_block": bool((report.get("number_grounding") or {}).get("findings")) if isinstance(report, dict) else None,
        "voice_spec_reached_prompt": reached,
        "blacklist_probe": probe,
        "prompt_chars": len(prompt) if prompt else 0,
        "usable": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
    }


# ── the matrix ───────────────────────────────────────────────────────────────
def confusion_matrix(results):
    """Deterministic 2x2 over the USABLE results only.

    Cells are named in plain language as well as tp/fn/tn/fp, because which class
    is "positive" is a convention and a mislabelled matrix is an honest-looking
    lie. See CONVENTION.
    """
    usable = [r for r in results if r["usable"]]
    golden_passed = sum(1 for r in usable if r["label"] == LABEL_GOOD and r["judge_passed"])
    golden_failed = sum(1 for r in usable if r["label"] == LABEL_GOOD and not r["judge_passed"])
    canary_failed = sum(1 for r in usable if r["label"] == LABEL_DEFECTIVE and not r["judge_passed"])
    canary_passed = sum(1 for r in usable if r["label"] == LABEL_DEFECTIVE and r["judge_passed"])

    n_good = golden_passed + golden_failed
    n_bad = canary_failed + canary_passed

    # Specificity split by whether the injected fault is even in this judge's
    # rubric. Both sub-rates are far below the thin floor and are reported as
    # such — the split exists to stop one number conflating two questions, not to
    # manufacture a better-looking one.
    def _split(key):
        out = {}
        for scope in (IN_RUBRIC, ADJACENT, OUT_OF_RUBRIC):
            rows = [r for r in usable if r["label"] == LABEL_DEFECTIVE and r.get(key) == scope]
            if rows:
                out[scope] = rate(sum(1 for r in rows if not r["judge_passed"]), len(rows))
        return out

    by_scope = _split("rubric_scope")
    # #2573: the same negatives scored against the PRE-fix rubric map, so the
    # published split shows what moved rather than only where it landed.
    by_scope_pre = _split("rubric_scope_pre_2573")

    return {
        "convention": CONVENTION,
        "cells": {
            "golden_passed_tp": golden_passed,
            "golden_failed_fn": golden_failed,
            "canary_failed_tn": canary_failed,
            "canary_passed_fp": canary_passed,
        },
        "n_usable": len(usable),
        "n_positives_good": n_good,
        "n_negatives_defective": n_bad,
        "sensitivity_agrees_with_good_work": rate(golden_passed, n_good),
        "specificity_catches_defects": rate(canary_failed, n_bad),
        "specificity_by_rubric_scope": by_scope,
        "specificity_by_rubric_scope_pre_2573": by_scope_pre,
        "accuracy_overall": rate(golden_passed + canary_failed, len(usable)),
    }


def threshold_attribution(results, base_threshold):
    """WHICH mechanism actually blocked each draft.

    `_run_quality_gate` computes `passed` from the model's own boolean and then
    only ever TIGHTENS it (`if score < PASS_SCORE_THRESHOLD: passed = False`). So
    a block can come from two different places, and they have very different
    implications:

      * `by_score_threshold` — the numeric gate fired. Tuning
        PASS_SCORE_THRESHOLD moves this.
      * `by_model_boolean`   — the model returned passed=False while scoring AT
        OR ABOVE the threshold. The number and the verdict disagree, and the
        threshold is not the operative control. Tuning it moves nothing here.

    Calibrating "against PASS_SCORE_THRESHOLD" is only meaningful to the extent
    the threshold is what decides. This makes that share visible instead of
    assumed.
    """
    usable = [r for r in results if r["usable"]]
    failed = [r for r in usable if not r["judge_passed"]]
    # #2573 adds a THIRD mechanism, and it outranks the other two: the deterministic
    # ADR-104 grounder's verdict, computed before the LLM and applied structurally.
    # Attributed first, because when it fires the other two are not what decided.
    by_determ = [r["id"] for r in failed if r.get("deterministic_block")]
    rest = [r for r in failed if not r.get("deterministic_block")]
    by_score = [r["id"] for r in rest if r["score"] < base_threshold]
    by_boolean = [r["id"] for r in rest if r["score"] >= base_threshold]
    out = {
        "threshold": base_threshold,
        "n_fail_decisions": len(failed),
        "by_deterministic_number_grounding": len(by_determ),
        "by_score_threshold": len(by_score),
        "by_model_boolean_at_or_above_threshold": len(by_boolean),
        "deterministic_ids": sorted(by_determ),
        "model_boolean_ids": sorted(by_boolean),
        "operative_control": (
            "deterministic_number_grounding"
            if len(by_determ) >= max(len(by_score), len(by_boolean))
            else ("model_boolean" if len(by_boolean) > len(by_score) else "PASS_SCORE_THRESHOLD")
        ),
    }
    if failed and len(by_score) < len(failed):
        out["note"] = (
            f"Of {len(failed)} blocking decisions: {len(by_determ)} by the deterministic number-grounding "
            f"verdict, {len(by_boolean)} by the model's own passed=False while scoring AT OR ABOVE "
            f"{base_threshold}, {len(by_score)} by the score threshold itself. PASS_SCORE_THRESHOLD is the "
            f"operative control for {len(by_score)} of {len(failed)} — retuning it would not move the rest."
        )
    return out


def threshold_sweep(results, base_threshold):
    """How the matrix moves as PASS_SCORE_THRESHOLD rises.

    Reconstructible ONLY upward. `_run_quality_gate` returns `passed` already
    forced False for any score < base_threshold, so the model's raw boolean is
    unrecoverable below it and this sweep does not pretend otherwise. At t >=
    base_threshold the decision is exactly `passed_at_base AND score >= t`.

    Derived from the SAME 35 verdicts — it is not independent evidence and adds
    no n. Reported as counts only, deliberately without intervals.
    """
    usable = [r for r in results if r["usable"]]
    rows = []
    for t in range(int(base_threshold), 101, 5):
        gp = sum(1 for r in usable if r["label"] == LABEL_GOOD and r["judge_passed"] and r["score"] >= t)
        cp = sum(1 for r in usable if r["label"] == LABEL_DEFECTIVE and r["judge_passed"] and r["score"] >= t)
        n_good = sum(1 for r in usable if r["label"] == LABEL_GOOD)
        n_bad = sum(1 for r in usable if r["label"] == LABEL_DEFECTIVE)
        rows.append(
            {
                "threshold": t,
                "golden_passed": gp,
                "n_good": n_good,
                "canary_caught": n_bad - cp,
                "n_defective": n_bad,
            }
        )
    return {"basis": "derived from the same verdicts — adds no independent n; t < base threshold is not reconstructible", "rows": rows}


# ── budget posture ───────────────────────────────────────────────────────────
def budget_tier():
    """Current budget tier from SSM, or None if unreadable. Read-only.

    This harness pauses at tier 3 ONLY — the #1927 lesson: the two AI CI gates
    used to pause at tier 1 and were consequently dark 26 of 30 days while still
    reporting green. A calibration instrument that silently does not run is the
    same failure. At tier 3 it reports NOT_RUN, loudly.
    """
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))
        return int(ssm.get_parameter(Name="/life-platform/budget-tier")["Parameter"]["Value"])
    except Exception:
        return None


# ── the run ──────────────────────────────────────────────────────────────────
def run(call_haiku=None, check_budget=True):
    """Replay the labeled corpus through the judge and report the matrix.

    `call_haiku` (optional) replaces `coach_quality_gate._call_haiku` — the tests'
    deterministic stub. When None the real Bedrock-backed path runs.
    """
    from coach import coach_quality_gate as gate

    cases = labeled_cases()
    defects = corpus_defects(cases)
    base = {
        "threshold": gate.PASS_SCORE_THRESHOLD,
        "threshold_source": "coach_quality_gate.PASS_SCORE_THRESHOLD",
        "entry_point": "coach_quality_gate.lambda_handler",
        "event_builder": "ai_calls.quality_gate_event (the production wire payload)",
        "corpus": {
            "n_total": len(cases),
            "n_good_golden": sum(1 for c in cases if c["label"] == LABEL_GOOD),
            "n_defective_canary": sum(1 for c in cases if c["label"] == LABEL_DEFECTIVE),
            "source": "tests/fixtures/golden_briefs/{golden,canaries}.json",
        },
        "fidelity_gaps": list(FIDELITY_GAPS),
    }

    if defects:
        return {**base, "verdict": ERROR, "corpus_defects": defects}

    tier = budget_tier() if check_budget and call_haiku is None else None
    if tier is not None and tier >= 3:
        return {
            **base,
            "verdict": NOT_RUN,
            "budget_tier": tier,
            "not_run_reason": "budget tier 3 — AI paused platform-wide (ADR-125); the judge could not be exercised",
        }

    # The gate's structured logger writes one JSON line per case to STDOUT, which
    # would interleave with `--json` and make the report unparseable. Quiet it for
    # the replay only: the harness records every verdict itself, in more detail
    # than the log line carries (which holds no draft and no brief — see this
    # module's header on why those log lines are not a replayable corpus).
    import logging

    prior_level = gate.logger.level
    try:
        gate.logger.setLevel(logging.WARNING)
        results = [_judge_one(gate, c, call_haiku=call_haiku) for c in cases]
    finally:
        gate.logger.setLevel(prior_level)
    usable = [r for r in results if r["usable"]]
    unavailable = [r for r in results if not r["usable"]]

    report = {
        **base,
        "budget_tier": tier,
        "results": results,
        "n_unavailable": len(unavailable),
        "unavailable_reasons": sorted({r["unavailable_reason"] for r in unavailable}),
        "voice_spec_reached_prompt_n": sum(1 for r in results if r["voice_spec_reached_prompt"]),
        "voice_spec_probe_absent_n": sum(1 for r in results if r["voice_spec_reached_prompt"] is None),
    }

    if not usable:
        report["verdict"] = NOT_RUN
        report["not_run_reason"] = (
            f"0 of {len(results)} cases produced a real verdict — the gate's permissive fallback is not a "
            "verdict and is never counted as a pass. No matrix is emitted."
        )
        return report

    report["verdict"] = MEASURED
    report["matrix"] = confusion_matrix(results)
    report["threshold_attribution"] = threshold_attribution(results, gate.PASS_SCORE_THRESHOLD)
    report["threshold_sweep"] = threshold_sweep(results, gate.PASS_SCORE_THRESHOLD)
    report["cannot_support"] = _cannot_support(report["matrix"], report["threshold_attribution"])
    return report


def _cannot_support(matrix, attribution=None):
    """What this matrix does NOT license anyone to claim. Emitted even — especially
    — when the numbers look good: an instrument that overstates its own precision
    is the failure #1374 exists to prevent."""
    out = []
    spec = matrix["specificity_catches_defects"]
    sens = matrix["sensitivity_agrees_with_good_work"]
    if spec["thin"]:
        lo, hi = spec["ci95_wilson"]
        out.append(
            f"Specificity rests on n={spec['denominator']} induced defects. Its 95% interval is [{lo}, {hi}] — "
            f"consistent with a judge that catches most defects AND with one that misses a large share. "
            f"Do not publish {spec['point']} as the judge's catch rate."
        )
    out.append(
        f"The {matrix['n_negatives_defective']} canaries are HAND-AUTHORED faults of three known classes "
        "(fabricated number, vital contradiction, blacklisted phrase). They are not a sample of the defects "
        "real generation produces, so this specificity does not generalise to field failure modes."
    )
    scoped = matrix.get("specificity_by_rubric_scope") or {}
    n_in = (scoped.get(IN_RUBRIC) or {}).get("denominator", 0)
    n_off = sum((scoped.get(s) or {}).get("denominator", 0) for s in (ADJACENT, OUT_OF_RUBRIC))
    if n_off:
        out.append(
            f"CORPUS/RUBRIC MISMATCH: only {n_in} of the {n_in + n_off} negatives is squarely inside this "
            f"judge's four-criterion rubric; {n_off} inject fabricated numbers or vital contradictions, which "
            "the quality-gate prompt never asks about. The headline specificity therefore blends 'the judge "
            "is weak' with 'the rubric has no rule for this'. Neither reading is established here, and the "
            f"in-rubric sub-rate rests on n={n_in} — not a measurement at all."
        )
        out.append(
            "The corollary is a real finding independent of the judge's skill: faults the DETERMINISTIC gate "
            "catches every time are invisible to the BLOCKING LLM gate, because they are absent from its "
            "rubric. That is a coverage gap in the gate, not noise in the estimate."
        )
    out.append(
        "The 30 goldens were authored to be clean and were curated against the DETERMINISTIC gate. "
        "Sensitivity here measures agreement with obviously-good work, which is the easy half of the job; "
        "it says nothing about borderline drafts, which are where a blocking gate actually costs something."
    )
    if sens["denominator"] and sens["point"] == 1.0:
        out.append("A saturated 1.0 is a lower bound, not a measurement — the corpus contains no case this judge failed.")
    out.append(
        "Margin-aware gating (this issue's third acceptance item) is NOT derivable from these numbers: "
        "an error margin set from a 5-case denominator would be a made-up margin wearing a statistic."
    )
    n_det = (attribution or {}).get("by_deterministic_number_grounding") or 0
    if n_det:
        out.append(
            f"#2573: {n_det} of the caught defects were caught by the DETERMINISTIC number-grounding verdict, "
            "not by the LLM's own judgement. Post-#2573 specificity is therefore the specificity of the "
            "COMBINED gate (deterministic prepass + judge), which is what actually ships — but it is NOT a "
            "measurement of the judge's own discrimination, and must not be quoted as one."
        )
    return out


# ── rendering ────────────────────────────────────────────────────────────────
def _fmt_rate(label, r):
    if not r["denominator"]:
        return f"  {label}: — ({r.get('note')})"
    lo, hi = r["ci95_wilson"]
    line = f"  {label}: {r['numerator']}/{r['denominator']} = {r['point']:.3f}  95% CI [{lo:.3f}, {hi:.3f}]"
    if r["thin"]:
        line += "   ← THIN"
    return line


def text_report(report):
    lines = [ops_line(report), ""]
    v = report["verdict"]
    if v == ERROR:
        lines.append("Corpus cannot support a calibration:")
        lines += [f"   ✗ {d}" for d in report["corpus_defects"]]
        return "\n".join(lines)
    if v == NOT_RUN:
        lines.append(f"NOT RUN — {report['not_run_reason']}")
        lines.append("No confusion matrix is emitted. This is the honest output, not a degraded one.")
        if report.get("n_unavailable"):
            lines.append(f"\n{report['n_unavailable']} case(s) unavailable:")
            lines += [f"   · {r}" for r in report["unavailable_reasons"]]
        return "\n".join(lines)

    m = report["matrix"]
    c = m["cells"]
    lines.append(f"Convention: {m['convention']}")
    lines.append(f"Threshold: score < {report['threshold']} fails ({report['threshold_source']})")
    lines.append("")
    lines.append("                        judge PASSED   judge FAILED")
    lines.append(f"  golden   (good,  n={m['n_positives_good']:>2})   {c['golden_passed_tp']:>10}   {c['golden_failed_fn']:>12}")
    lines.append(f"  canary   (bad,   n={m['n_negatives_defective']:>2})   {c['canary_passed_fp']:>10}   {c['canary_failed_tn']:>12}")
    lines.append("")
    lines.append(_fmt_rate("sensitivity (agrees with good work)", m["sensitivity_agrees_with_good_work"]))
    lines.append(_fmt_rate("specificity (catches defects)      ", m["specificity_catches_defects"]))
    lines.append(_fmt_rate("overall accuracy                   ", m["accuracy_overall"]))
    for label, key in (
        ("CURRENT rubric (post-#2573, criterion 5 present)", "specificity_by_rubric_scope"),
        ("PRE-#2573 rubric (four criteria, none about numbers)", "specificity_by_rubric_scope_pre_2573"),
    ):
        scoped = m.get(key) or {}
        if scoped:
            lines.append("")
            lines.append(f"  specificity split by rubric scope — {label}:")
            for scope in (IN_RUBRIC, ADJACENT, OUT_OF_RUBRIC):
                if scope in scoped:
                    lines.append(_fmt_rate(f"  {scope:<14}", scoped[scope]))
    if report.get("n_unavailable"):
        lines.append(
            f"\n{report['n_unavailable']} of {len(report['results'])} case(s) produced NO verdict and are excluded from every denominator:"
        )
        lines += [f"   · {r}" for r in report["unavailable_reasons"]]
    ta = report.get("threshold_attribution") or {}
    if ta.get("n_fail_decisions"):
        lines.append(
            f"\nWhat actually blocked ({ta['n_fail_decisions']} decisions): "
            f"{ta.get('by_deterministic_number_grounding', 0)} by the DETERMINISTIC number-grounding verdict, "
            f"{ta['by_score_threshold']} by the score threshold, "
            f"{ta['by_model_boolean_at_or_above_threshold']} by the model's own passed=False at or above "
            f"{ta['threshold']}.  Operative control: {ta.get('operative_control')}."
        )
        if ta.get("note"):
            lines.append(f"   ! {ta['note']}")
    lines.append("\nWhat this matrix CANNOT support:")
    lines += [f"   ! {s}" for s in report["cannot_support"]]
    lines.append("\nFidelity gaps (this replay is not production):")
    lines += [f"   ~ {g}" for g in report["fidelity_gaps"]]
    lines.append(
        f"\nVoice specs verified present in the ASSEMBLED PROMPT for "
        f"{report['voice_spec_reached_prompt_n']}/{len(report['results'])} cases "
        f"({report['voice_spec_probe_absent_n']} had no blacklist phrase to probe with)."
    )
    return "\n".join(lines)


def ops_line(report):
    v = report["verdict"]
    if v == ERROR:
        return f"✗ Judge calibration: ERROR — {len(report.get('corpus_defects') or [])} corpus defect(s)"
    corp = report["corpus"]
    if v == NOT_RUN:
        return f"· Judge calibration: NOT RUN — {corp['n_total']} labeled cases ready, judge unreachable"
    m = report["matrix"]
    sens = m["sensitivity_agrees_with_good_work"]
    spec = m["specificity_catches_defects"]
    return (
        f"✓ Judge calibration: sensitivity {sens['numerator']}/{sens['denominator']}, "
        f"specificity {spec['numerator']}/{spec['denominator']} (thin), "
        f"{report['n_unavailable']} no-verdict — n={m['n_usable']} usable of {corp['n_total']}"
    )
