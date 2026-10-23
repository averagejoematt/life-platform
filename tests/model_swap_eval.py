"""model_swap_eval.py — replay one AI feature through an incumbent and a candidate model (#4771, epic #4768).

WHY
  None of the existing evals compares output QUALITY across models. `golden_brief_eval`,
  `golden_surface_eval` and `safety_eval_matrix` prove the deterministic gates fire;
  `judge_calibration` grades the quality-gate judge; the voice-fidelity harness is a
  monthly voice test. So there was no honest way to say a cheaper model is good enough
  (ADR-104/105), and every swap on epic #4768 waits on this harness
  (docs/AI_MODEL_STRATEGY.md §3 rule 7: a swap lands only on a non-inferior verdict
  with n and an interval, and with every deterministic gate passing).

WHAT ONE RUN DOES
  1. Builds the feature's replay cases from FROZEN, committed inputs —
     `tests/fixtures/golden_briefs`, `tests/fixtures/golden_surfaces`,
     `tests/fixtures/safety_eval` (the refusal family's benign questions, admitted only
     if the real hazard gate `ai.safety_contract.check` lets them through) — plus any
     captured sample under `tests/fixtures/model_swap/<feature>.json`.
  2. Sends every case to BOTH models through the one chokepoint
     (`bedrock_client.invoke_with_retry`), the same body to each.
  3. Runs every output through the deterministic gates that apply to the feature — the
     surface's own gate (`golden_surface_eval.evaluate_fixture`), the golden-brief
     honesty gate (`golden_brief_eval.evaluate_output`), the deterministic halves of
     `coach_quality_gate` (number grounding, labs-draw), schema conformance for a
     structured feature, and the owner-only privacy probe (`safety_eval_matrix`) on all.
     A candidate gate failure is REPORTED PER GATE and BLOCKS the verdict; it is never
     averaged into the judge's score.
  4. Shows a blind pairwise judge both outputs, order randomised per case by a recorded
     seed, with no model names. The judge model may not be the candidate (refused).
  5. Reports win / tie / loss with n, the candidate preference share
     p = (W + T/2) / n and its Wilson 95% interval (`common.stats_core.wilson_interval`),
     against a stated non-inferiority margin.

THE VERDICT (ADR-105: say what the numbers can carry, nothing more)
  NON_INFERIOR    no candidate gate failure, and the Wilson LOWER bound of p is at least
                  0.5 - MARGIN. With MARGIN = 0.10 that means the candidate may lose at most
                  ten points of preference share against parity, at 95%.
  INFERIOR        the Wilson UPPER bound of p is below 0.5 — the candidate is reliably worse.
  INCONCLUSIVE    neither: the interval is too wide. The report says roughly what n would
                  clear the bar at the observed share. Ties count half and are treated as
                  binomial, which overstates variance — the conservative direction.
  BLOCKED_BY_GATE a candidate output failed a deterministic gate (or the candidate call failed).
  INCOMPLETE      a budget stop (tier 3 or the dev-session cap) ended the run early.
  DRY_RUN         no model was called. A dry run can never report NON_INFERIOR.
  REFUSED         the pre-flight ceiling estimate exceeds the dev-session cap; nothing was sent.

COST
  Every billed call is priced with `bedrock_client.estimate_cost_usd` and the run prints
  per-arm and total dollars. Before the first call the run prices a CEILING (every
  output at max_tokens, input tokens at chars/4 x 1.3 for tokenizer drift) and refuses to
  start if that ceiling exceeds this run's dev-session cap (`ai/dev_session_cap.py`:
  $5 per run, or `DEV_AI_BUDGET_USD`). Inside the run the chokepoint's own cap still
  applies; a refusal there ends the run as INCOMPLETE with everything measured so far.

WHAT IS NOT HERE (stated, not glossed)
  * The LLM half of `coach_quality_gate` (the Haiku rubric) is itself a model call; it is
    the pairwise judge's job here, not a gate's. Its deterministic halves ARE run.
  * The safety-eval injection and refusal families evaluate a constructed PROMPT or an
    INPUT before any model runs — they are model-independent, so a swap cannot move them.
  * Replay prompts. `state_of_matthew` and `field_notes` use the live builders
    (`build_narration_body`, `build_prompt`) and `chronicle` / `board_ask` the frozen
    system + user pair. `coach_brief` and `memoir` use an AUTHORED replay prompt built
    from the fixture's own inputs, because the live builders need DynamoDB state the
    fixtures do not carry. Both arms always receive the identical body, which is what a
    pairwise comparison needs; each case's `prompt_provenance` says which kind it is.

THE THREE INTERNAL FEATURES OF THE OPEN-WEIGHT TRIAL (#4776)
  `coach_quality_gate`, `coach_state_update` and `coherence_semantic` replay the LLM half of
  the blocking coach judge, the coach state extraction and the coherence sentinel's semantic
  pass over the labelled `tests/fixtures/golden_briefs` corpus (30 goldens + 15 canaries): the
  judge and the sentinel see each brief's text against its own facts, the extractor sees each
  golden's text. Every body comes from the LIVE builder (`_build_quality_gate_message` under
  `QUALITY_GATE_SYSTEM_PROMPT`, `build_extraction_message` under `EXTRACTION_SYSTEM_PROMPT`,
  `coherence_sentinel_lambda.semantic_body`) and is requested under the feature's own output
  schema. Their deterministic gates: schema conformance; for the judge, a seeded fault the
  DETERMINISTIC grounder flagged (rendered into the prompt, which the rubric says to report)
  or an anti-pattern canary that the reply waves through (`passed` true at a passing score)
  is `missed_seeded_fault`; for the sentinel, `coherent: true` with issues listed is a
  contradiction. The pairwise judge decides everything else. A non-Anthropic candidate goes
  through the same chokepoint, translated by its Converse adapter — the arms and the meters
  do not know the difference, which is the point.

Run (one feature per run):
    python3 tests/model_swap_eval.py --feature field_notes --candidate claude-haiku-5-5 --dry-run
    python3 tests/model_swap_eval.py --feature field_notes --candidate claude-haiku-5-5 --n 4
    python3 tests/model_swap_eval.py --feature coach_quality_gate --incumbent claude-haiku-4-5-20251001 --candidate gpt-oss-120b --dry-run
    python3 tests/model_swap_eval.py --list

`claude-haiku-5-5` is a mapped NAME since #4770 and the four #4776 candidates (gpt-oss-120b,
gpt-oss-20b, qwen3-32b, nova-micro) since #4776; each prices on its own row. The #4776 trial's
baseline is the current Haiku 4.5 (owner ruling 2026-10-23), the three features' default incumbent.
Haiku 5.5 still needs model access (#4772) — a real run against it fails at the call and is
reported as such, never as a verdict.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── path + env setup: work both under pytest (conftest sets paths) and standalone ──
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (
    os.path.join(_REPO, "lambdas", "intelligence"),
    os.path.join(_REPO, "lambdas", "emails"),
    os.path.join(_REPO, "lambdas"),
    _REPO,
    _HERE,
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Hermetic until a real replay: modules under test build boto3 clients at import.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "eval@example.com")
os.environ.setdefault("EMAIL_SENDER", "eval@example.com")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

import golden_brief_eval as gbe  # noqa: E402
import golden_surface_eval as gse  # noqa: E402
import safety_eval_matrix as sem  # noqa: E402
from ai import grounded_generation as gg  # noqa: E402
from common.stats_core import wilson_interval  # noqa: E402

FIXTURES = os.path.join(_HERE, "fixtures")
CAPTURED_DIR = os.path.join(FIXTURES, "model_swap")

# ── verdicts ────────────────────────────────────────────────────────────────────────
NON_INFERIOR = "NON_INFERIOR"
INFERIOR = "INFERIOR"
INCONCLUSIVE = "INCONCLUSIVE"
BLOCKED_BY_GATE = "BLOCKED_BY_GATE"
INCOMPLETE = "INCOMPLETE"
DRY_RUN = "DRY_RUN"
REFUSED = "REFUSED"

# Non-inferiority margin on the candidate preference share p = (W + T/2) / n. Parity is
# 0.5; the candidate is non-inferior when the Wilson 95% lower bound of p is >= 0.40.
MARGIN = 0.10
PARITY = 0.5
DEFAULT_SEED = 4771
# Stronger than the Haiku workhorse arms; never the candidate (enforced). On the two Sonnet
# features (coach_brief, memoir) it IS the incumbent — a self-preference risk toward the
# incumbent, which the report states as a warning rather than hiding (validate_models).
DEFAULT_JUDGE = "claude-sonnet-4-6"
JUDGE_MAX_TOKENS = 400
JUDGE_TASK_CHAR_CAP = 6000  # the task shown to the judge is truncated (and says so) to bound judge cost
TOKENIZER_MARGIN = 1.3  # docs/AI_MODEL_STRATEGY.md §2: the 5.5 tokenizer reads ~30% more tokens (unverified)
DRY_RUN_STUB = "[dry-run stub: no model was called]"


# ══ cases ═════════════════════════════════════════════════════════════════════════════
@dataclass
class Case:
    """One frozen input, replayed identically through both arms."""

    id: str
    source: str  # fixture file the input came from
    body: dict  # Anthropic Messages body WITHOUT a model key
    gate: Callable[[Any], list]  # output -> findings [{gate, type?, detail}]
    prompt_provenance: str  # "live builder" / "frozen pair" / "authored replay prompt"
    schema: Optional[dict] = None  # a structured feature's JSON schema (sent as output_config, checked after)
    reference: Any = None  # the fixture's known-good output, used ONLY by a dry run


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _inputs_of(pack_dir):
    """Every fixture in a golden/canary pack, golden first. A canary's INPUT is a valid
    frozen input; its mutated output is ignored (it never reaches either model)."""
    out = []
    for name in ("golden.json", "canaries.json"):
        path = os.path.join(pack_dir, name)
        if os.path.exists(path):
            out.extend((os.path.relpath(path, _REPO), fx) for fx in _load(path))
    return out


def _gate_label(findings, gate):
    return [{"gate": gate, **f} for f in findings]


def _text(output):
    return output if isinstance(output, str) else json.dumps(output, default=str, sort_keys=True)


def _universal_gates(output):
    """Gates every output runs, whatever the feature: an empty output, and the safety
    matrix's owner-only privacy probe (vocabulary derived live from privacy.field_tiers)."""
    findings = []
    if output is None or (isinstance(output, str) and not output.strip()):
        findings.append({"gate": "empty_output", "detail": "the model returned no text"})
    else:
        findings.extend(_gate_label(sem.owner_only_leak_findings(_text(output)), "privacy_owner_only"))
    return findings


def _surface_gate(surface, fx):
    def gate(output):
        return _gate_label(gse.evaluate_fixture(surface, fx, output), f"{surface}_surface_gate")

    return gate


# ── coach_brief: golden_briefs, narrative tier ───────────────────────────────────────
def _coach_brief_cases():
    cases = []
    for src, fx in _inputs_of(os.path.join(FIXTURES, "golden_briefs")):
        coach_id = fx["coach_id"]
        spec = gbe.voice_spec(coach_id)
        facts = fx.get("authoritative_facts") or {}
        brief = fx.get("generation_brief") or {}
        rules = json.dumps(spec.get("structural_voice_rules") or {}, sort_keys=True)[:1500]
        system = (
            f"You are {spec.get('display_name') or coach_id}, the platform's {spec.get('domain') or 'health'} coach. "
            f"{spec.get('bio') or ''}\n\nYour structural voice rules (JSON): {rules}\n\n"
            "Write today's short note to Matthew (60-120 words, prose, second person). Use ONLY numbers that appear "
            "in the authoritative facts or the generation brief; invent no figure, date or trend. Stay inside the "
            "brief's decision_class_ceiling. Never name the underlying software, vendor or model.\n\n" + gg.authoritative_facts_block(facts)
        )
        user = "Generation brief (JSON):\n" + json.dumps(brief, indent=1, sort_keys=True) + "\n\nWrite the note."
        allowed = gbe.allowed_for(fx)

        def gate(output, coach_id=coach_id, facts=facts, brief=brief, allowed=allowed):
            from ai.quality_gate_contract import brief_with_grounding
            from coach import coach_quality_gate as cqg

            text = _text(output)
            findings = _gate_label(gbe.evaluate_output(coach_id, text, facts, allowed), "golden_brief_honesty")
            report = cqg._number_grounding_report(text, brief_with_grounding(brief, facts, sorted(allowed)))
            if report.get("status") != "measured":
                findings.append({"gate": "coach_quality_gate_numbers", "type": "gate_unmeasured", "detail": str(report)[:300]})
            findings.extend(_gate_label(report.get("findings") or [], "coach_quality_gate_numbers"))
            findings.extend(_gate_label(cqg._labs_draw_findings(coach_id, text), "coach_quality_gate_labs_draw"))
            return findings

        cases.append(
            Case(
                id=fx["id"],
                source=src,
                body={"system": system, "messages": [{"role": "user", "content": user}], "max_tokens": 600},
                gate=gate,
                prompt_provenance="authored replay prompt (voice spec + fixture brief + facts block)",
                reference=fx.get("reference_output"),
            )
        )
    return cases


# ── board_ask: golden_surfaces/board_ask + safety_eval/refusal's benign questions ─────
def _board_ask_cases():
    from ai.ai_context import wrap_untrusted_reader_text
    from ai.safety_contract import check as hazard_check

    def case_for(cid, src, fx, provenance):
        i = fx["inputs"]
        user = "READER QUESTION: " + wrap_untrusted_reader_text(i["question"])
        return Case(
            id=cid,
            source=src,
            body={"system": i["system_context"], "messages": [{"role": "user", "content": user}], "max_tokens": 500},
            gate=_surface_gate("board_ask", fx),
            prompt_provenance=provenance,
            reference=fx.get("reference_output"),
        )

    pack = _inputs_of(os.path.join(FIXTURES, "golden_surfaces", "board_ask"))
    cases = [case_for(fx["id"], src, fx, "frozen pair (system_context + wrapped reader question)") for src, fx in pack]
    # The refusal family's GOLDEN questions are benign reader questions the hazard gate must
    # let through — i.e. real model traffic. Admitted only if the REAL gate still passes them;
    # each is asked against the first board_ask fixture's stance.
    base = pack[0][1]
    refusal = os.path.join(FIXTURES, "safety_eval", "refusal", "golden.json")
    for fx in _load(refusal):
        q = fx["inputs"]["question"]
        if not hazard_check(q)[0]:
            continue
        synth = {"id": fx["id"], "inputs": {"system_context": base["inputs"]["system_context"], "question": q}}
        cases.append(
            case_for(fx["id"], os.path.relpath(refusal, _REPO), synth, "frozen pair (board_ask stance + safety_eval benign question)")
        )
    return cases


# ── chronicle: frozen elena_prompt + data packet ─────────────────────────────────────
def _chronicle_cases():
    cases = []
    for src, fx in _inputs_of(os.path.join(FIXTURES, "golden_surfaces", "chronicle")):
        i = fx["inputs"]
        cases.append(
            Case(
                id=fx["id"],
                source=src,
                body={"system": i["elena_prompt"], "messages": [{"role": "user", "content": i["user_message"]}], "max_tokens": 900},
                gate=_surface_gate("chronicle", fx),
                prompt_provenance="frozen pair (elena_prompt + user_message)",
                reference=fx.get("reference_output"),
            )
        )
    return cases


# ── memoir: narrative tier ───────────────────────────────────────────────────────────
def _memoir_cases():
    from compute import coach_memoir_lambda as memoir

    cases = []
    for src, fx in _inputs_of(os.path.join(FIXTURES, "golden_surfaces", "memoir")):
        facts = fx["inputs"]["facts"]
        user = (
            f"Here is your real, graded track record for {facts.get('quarter')} (JSON):\n"
            + json.dumps(facts, indent=1, sort_keys=True, default=str)
            + "\n\nWrite your first-person quarterly memoir — a reckoning with your own record."
        )
        cases.append(
            Case(
                id=fx["id"],
                source=src,
                body={"system": memoir._SYSTEM_RULES, "messages": [{"role": "user", "content": user}], "max_tokens": 900},
                gate=_surface_gate("memoir", fx),
                prompt_provenance="authored replay prompt (live _SYSTEM_RULES + fixture facts as JSON)",
                reference=fx.get("reference_output"),
            )
        )
    return cases


# ── state_of_matthew: the live body builder ──────────────────────────────────────────
def _state_of_matthew_cases():
    from compute import state_of_matthew_lambda as som

    cases = []
    for src, fx in _inputs_of(os.path.join(FIXTURES, "golden_surfaces", "state_of_matthew")):
        body = som.build_narration_body(copy.deepcopy(fx["inputs"]["state"]))
        body.pop("model", None)
        cases.append(
            Case(
                id=fx["id"],
                source=src,
                body=body,
                gate=_surface_gate("state_of_matthew", fx),
                prompt_provenance="live builder (state_of_matthew_lambda.build_narration_body)",
                reference=fx.get("reference_output"),
            )
        )
    return cases


# ── field_notes: structured (JSON schema), the live prompt builder ───────────────────
def _field_notes_cases():
    import field_notes_lambda as fnl
    from ai.structured_json import schema_findings

    cases = []
    for src, fx in _inputs_of(os.path.join(FIXTURES, "golden_surfaces", "field_notes")):
        record = fx["inputs"]["metrics_record"]
        prompt = fnl.build_prompt("2026-W28", {"computed_metrics": [record]}, [])

        def gate(output, fx=fx, prompt=prompt):
            if not isinstance(output, dict):
                return [{"gate": "schema_conformance", "detail": f"output is not a JSON object: {str(output)[:160]!r}"}]
            findings = _gate_label([{"detail": d} for d in schema_findings(output, fnl.NOTES_SCHEMA)], "schema_conformance")
            findings.extend(_gate_label(gse.evaluate_fixture("field_notes", fx, output), "field_notes_surface_gate"))
            # #2426's allow-list half, minus the date-dependent cycle params (both arms see the same gate).
            text = "\n\n".join(str(output.get(k) or "") for k in fnl._NOTE_FIELDS)
            findings.extend(
                _gate_label(
                    gg.grounding_findings(text, allowed=gg.allowed_numbers(prompt), allowed_dates=gg.allowed_dates(prompt)),
                    "field_notes_allowlist",
                )
            )
            return findings

        cases.append(
            Case(
                id=fx["id"],
                source=src,
                body={"messages": [{"role": "user", "content": prompt}], "max_tokens": 2000},
                gate=gate,
                prompt_provenance="live builder (field_notes_lambda.build_prompt; week data reconstructed from the metrics record)",
                schema=fnl.NOTES_SCHEMA,
                reference=fx.get("reference_output"),
            )
        )
    return cases


# ── #4776: the three internal features of the open-weight trial, over the labelled briefs ─────
def _labelled_briefs():
    """[(label, fixture, text)] — the 30 goldens (good) and 15 canaries (defective) of
    tests/fixtures/golden_briefs, the same corpus judge_calibration.py replays."""
    golden, canaries = gbe.load_fixtures()
    rows = [("good", fx, fx["reference_output"]) for fx in golden]
    rows += [("defective", cn, cn["mutated_output"]) for cn in canaries]
    return rows


def _brief_with_grounding(fx):
    from ai.quality_gate_contract import brief_with_grounding

    return brief_with_grounding(fx.get("generation_brief"), fx.get("authoritative_facts") or {}, gbe.allowed_for(fx))


def _schema_gate(output, schema, label):
    from ai.structured_json import schema_findings

    if not isinstance(output, dict):
        return [{"gate": label, "detail": f"output is not a JSON object: {str(output)[:160]!r}"}]
    return _gate_label([{"detail": d} for d in schema_findings(output, schema)], label)


def _coach_quality_gate_cases():
    """The LLM half of the blocking coach judge (coach/coach_quality_gate.py), one case per
    labelled brief. The deterministic number verdict is computed exactly as production does
    and rendered INTO the prompt; a seeded fault it flagged, or an anti-pattern canary, that the
    reply still passes is `missed_seeded_fault` — the one thing a judge may never do."""
    from coach import coach_quality_gate as cqg
    from coach.persona_core import load_voice_spec

    cases = []
    for label, fx, text in _labelled_briefs():
        coach_id = fx["coach_id"]
        brief = _brief_with_grounding(fx)
        grounding = cqg._number_grounding_report(text, brief)
        spec = load_voice_spec(coach_id) or {}
        user = cqg._build_quality_gate_message(coach_id, text, spec, brief, None, grounding=grounding)
        grounder_failed = grounding.get("status") == "measured" and bool(grounding.get("findings"))
        anti_pattern = label == "defective" and "anti_pattern" in (fx.get("expect_checks") or [])

        def gate(output, grounder_failed=grounder_failed, anti_pattern=anti_pattern):
            findings = _schema_gate(output, cqg.QUALITY_GATE_OUTPUT_SCHEMA, "schema_conformance")
            if not isinstance(output, dict):
                return findings
            score = output.get("score")
            waved_through = output.get("passed") is True and isinstance(score, (int, float)) and score >= cqg.PASS_SCORE_THRESHOLD
            if grounder_failed and waved_through:
                findings.append(
                    {
                        "gate": "missed_seeded_fault",
                        "detail": "the deterministic grounder FAILED this draft (rendered in the prompt) and the reply still passed it at a passing score",
                    }
                )
            elif anti_pattern and waved_through and not output.get("anti_pattern_violations"):
                findings.append(
                    {
                        "gate": "missed_seeded_fault",
                        "detail": "an anti-pattern canary passed at a passing score with no anti_pattern_violations",
                    }
                )
            return findings

        cases.append(
            Case(
                id=fx["id"],
                source="tests/fixtures/golden_briefs/" + ("golden.json" if label == "good" else "canaries.json"),
                body={
                    "system": [{"type": "text", "text": cqg.QUALITY_GATE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": user}],
                    "max_tokens": cqg.QUALITY_GATE_MAX_TOKENS,
                    "temperature": 0.1,
                },
                gate=gate,
                prompt_provenance="live builder (coach_quality_gate._build_quality_gate_message; repo voice spec, no peer outputs — judge_calibration.FIDELITY_GAPS)",
                schema=cqg.QUALITY_GATE_OUTPUT_SCHEMA,
            )
        )
    return cases


def _coach_state_update_cases():
    """The coach state extraction (coach/coach_state_updater.py) over each GOLDEN brief's own
    text — the exact body `_call_haiku` builds, under EXTRACTION_OUTPUT_SCHEMA."""
    from coach import coach_json_schemas as schemas, coach_state_updater as csu
    from coach.persona_core import load_voice_spec

    cases = []
    for label, fx, text in _labelled_briefs():
        if label != "good":
            continue
        spec = load_voice_spec(fx["coach_id"]) or {}
        user = csu._build_extraction_message(fx["coach_id"], text, "daily_brief_section", spec)

        def gate(output):
            return _schema_gate(output, schemas.EXTRACTION_OUTPUT_SCHEMA, "schema_conformance")

        cases.append(
            Case(
                id=fx["id"],
                source="tests/fixtures/golden_briefs/golden.json",
                body={
                    "system": [{"type": "text", "text": csu.EXTRACTION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": user}],
                    "max_tokens": 3000,
                    "temperature": 0.1,
                },
                gate=gate,
                prompt_provenance="live builder (coach_state_updater._build_extraction_message; repo voice spec)",
                schema=schemas.EXTRACTION_OUTPUT_SCHEMA,
            )
        )
    return cases


def _coherence_semantic_cases():
    """The coherence sentinel's semantic pass (operational/coherence_sentinel_lambda.py) with each
    labelled brief as the served narrative and its own authoritative facts as the facts line —
    the live `semantic_body`, under _SEMANTIC_SCHEMA. `coherent: true` with issues listed is a
    self-contradiction; whether a canary's fault clears the prompt's own >25% bar is the judge's call."""
    from operational import coherence_sentinel_lambda as sentinel

    cases = []
    for label, fx, text in _labelled_briefs():
        facts = fx.get("authoritative_facts") or {}
        if not facts:
            continue
        body = sentinel.semantic_body(facts, [text])
        body.pop("model", None)

        def gate(output):
            findings = _schema_gate(output, sentinel._SEMANTIC_SCHEMA, "schema_conformance")
            if isinstance(output, dict) and output.get("coherent") is True and output.get("issues"):
                findings.append({"gate": "coherent_but_issues_listed", "detail": f"coherent=true with issues {output.get('issues')!r}"})
            return findings

        cases.append(
            Case(
                id=fx["id"],
                source="tests/fixtures/golden_briefs/" + ("golden.json" if label == "good" else "canaries.json"),
                body=body,
                gate=gate,
                prompt_provenance="live builder (coherence_sentinel_lambda.semantic_body; the brief's own facts as the facts line)",
                schema=sentinel._SEMANTIC_SCHEMA,
            )
        )
    return cases


@dataclass(frozen=True)
class Feature:
    name: str
    route: str  # the #4770 model_routing route (PR #4786); used once that module is on main
    main_default: tuple  # (module, attribute) holding the incumbent model on main today
    build: Callable[[], list]
    structured: bool = False


FEATURES = {
    f.name: f
    for f in (
        Feature("coach_brief", "shared.narrative", ("ai.ai_transport", "AI_MODEL"), _coach_brief_cases),
        Feature("board_ask", "website_ai", ("web.site_api_ai_lambda", "AI_MODEL_HAIKU"), _board_ask_cases),
        Feature("chronicle", "chronicle", ("wednesday_chronicle_lambda", "AI_MODEL_HAIKU"), _chronicle_cases),
        Feature("memoir", "coach_narrative.memoir", ("compute.coach_memoir_lambda", "MODEL"), _memoir_cases),
        Feature("state_of_matthew", "state_of_matthew", ("compute.state_of_matthew_lambda", "MODEL"), _state_of_matthew_cases),
        Feature("field_notes", "field_notes", ("field_notes_lambda", "AI_MODEL"), _field_notes_cases, structured=True),
        # #4776: the open-weight trial's three internal features (all structured).
        Feature(
            "coach_quality_gate",
            "coach_narrative.quality_gate",
            ("coach.coach_quality_gate", "AI_MODEL_HAIKU"),
            _coach_quality_gate_cases,
            structured=True,
        ),
        Feature(
            "coach_state_update",
            "coach_narrative.state_update",
            ("coach.coach_state_updater", "AI_MODEL_HAIKU"),
            _coach_state_update_cases,
            structured=True,
        ),
        Feature(
            "coherence_semantic",
            "coherence_semantic",
            ("operational.coherence_sentinel_lambda", "AI_MODEL_HAIKU"),
            _coherence_semantic_cases,
            structured=True,
        ),
    )
}


def incumbent_model(feature: Feature) -> str:
    """The model the feature runs on TODAY. Through the #4770 registry when it is on main
    (PR #4786), else the module attribute each caller still reads on main."""
    try:
        from ai import model_routing  # type: ignore[attr-defined]
    except ImportError:
        model_routing = None
    if model_routing is not None:
        return model_routing.model_for(feature.route)
    import importlib

    mod_name, attr = feature.main_default
    return getattr(importlib.import_module(mod_name), attr)


# ── captured per-feature samples (tests/fixtures/model_swap/<feature>.json) ───────────
def captured_privacy_findings(payload) -> list:
    """Owner-only vocabulary in a captured sample. A committed fixture must carry none —
    the repo is public (the harvest rule: a person reviews before anything is promoted)."""
    return sem.owner_only_leak_findings(payload)


def load_captured(feature_name, directory=CAPTURED_DIR):
    """Captured request bodies for a feature: a JSON list of
    {id, provenance, body: {system?, messages, max_tokens}, gate: {allowed?: [...], facts?: {...}}}.
    Gated through `grounded_generation.grounding_findings` with the recorded allow-list.
    Refuses (raises) a file that carries owner-only vocabulary, rather than replaying it."""
    path = os.path.join(directory, f"{feature_name}.json")
    if not os.path.exists(path):
        return []
    rows = _load(path)
    leaks = captured_privacy_findings(rows)
    if leaks:
        raise ValueError(f"{path}: captured sample carries owner-only vocabulary, refusing to replay it: {leaks[:3]}")
    cases = []
    for row in rows:
        g = row.get("gate") or {}
        allowed = {float(x) for x in g["allowed"]} if g.get("allowed") is not None else None
        facts = g.get("facts")

        def gate(output, allowed=allowed, facts=facts):
            return _gate_label(gg.grounding_findings(_text(output), facts=facts, allowed=allowed), "captured_allowlist")

        body = {k: v for k, v in row["body"].items() if k != "model"}
        cases.append(Case(row["id"], os.path.relpath(path, _REPO), body, gate, f"captured ({row.get('provenance', 'no provenance')})"))
    return cases


def body_key(body: dict) -> str:
    return json.dumps({k: v for k, v in body.items() if k not in ("model", "output_config")}, sort_keys=True, default=str)


def build_cases(feature_name, n=None, seed=DEFAULT_SEED, captured_dir=CAPTURED_DIR):
    """The feature's replay cases: a seeded sample of at most `n`, one per DISTINCT body.

    A canary pack often reuses its golden's inputs; replaying the same body twice would
    count one input as two and narrow the interval dishonestly, so duplicates are dropped
    (the golden — which carries the reference output — is kept)."""
    feature = FEATURES[feature_name]
    seen, cases = set(), []
    for c in feature.build() + load_captured(feature_name, captured_dir):
        key = body_key(c.body)
        if key not in seen:
            seen.add(key)
            cases.append(c)
    cases.sort(key=lambda c: c.id)
    random.Random(seed).shuffle(cases)
    return cases[:n] if n else cases


# ══ models, prices, invokers ═══════════════════════════════════════════════════════════
def _bc():
    from ai import bedrock_client

    return bedrock_client


def resolved(model: str) -> str:
    return _bc().resolve_model_id(model)


def price_row(model: str) -> str:
    return _bc().price_key_for(resolved(model)) or "UNPRICED (metered at the fable fallback)"


def call_cost(usage: dict, model: str) -> float:
    return float(_bc().estimate_cost_usd(usage or {}, resolved(model)))


def bedrock_invoker(body: dict, model: str) -> dict:
    """The real replay: the platform's one chokepoint, its retry policy and every guard in it
    (budget tier, dev-session cap, usage metering)."""
    return _bc().invoke_with_retry(dict(body), model_name=model)


def schema_stub(schema):
    """A minimal instance of a JSON schema — every required key (all keys when none are
    required), strings as the dry-run stub (or the first enum value), numbers 0, booleans True,
    arrays empty, a nullable as its first non-null type. Offline only; it answers the schema,
    never the task."""
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        props = schema.get("properties") or {}
        keys = schema.get("required") or list(props)
        return {k: schema_stub(props.get(k) or {}) for k in keys}
    if t == "array":
        return []
    if t == "string":
        return DRY_RUN_STUB
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return True
    return None


def dry_run_invoker_for(cases):
    """An offline invoker: echoes each case's frozen reference output (or a stub) with a
    chars/4 usage estimate. Nothing leaves the machine."""
    by_body = {body_key(c.body): c for c in cases}

    def invoke(body, model):
        case = by_body.get(body_key(body))
        ref = case.reference if case is not None and case.reference is not None else None
        if ref is None:
            fmt = ((body.get("output_config") or {}).get("format") or {}).get("schema")
            ref = schema_stub(fmt) if fmt else DRY_RUN_STUB
        text = _text(ref)
        return {
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": len(json.dumps(body, default=str)) // 4, "output_tokens": len(text) // 4},
            "stop_reason": "end_turn",
        }

    return invoke


def dry_run_judge(body, model):
    return {"content": [{"type": "text", "text": json.dumps({"winner": "tie", "reason": "dry run: no judge was called"})}], "usage": {}}


# ══ the judge ═══════════════════════════════════════════════════════════════════════════
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"winner": {"type": "string", "enum": ["A", "B", "tie"]}, "reason": {"type": "string"}},
    "required": ["winner", "reason"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You are a blind evaluator. Two responses, A and B, were written for the SAME task by two different "
    "writers; you are not told which is which and the order is random. Decide which response better does "
    "the task, judging in this order: (1) faithfulness — every number and claim is supported by the task's "
    "own data, nothing invented, no causal claim the data cannot carry; (2) does what the task's instructions "
    "ask (format, length, voice, required elements); (3) clarity and usefulness to the intended reader. "
    "Do not reward length, confidence or polish for their own sake. If neither is meaningfully better, say "
    'tie. Respond ONLY with JSON: {"winner": "A" | "B" | "tie", "reason": "<one sentence>"}.'
)


def task_text(body: dict) -> str:
    system = body.get("system")
    if isinstance(system, list):
        system = "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    parts = [f"SYSTEM:\n{system}"] if system else []
    for m in body.get("messages") or []:
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
        parts.append(f"{str(m.get('role', '')).upper()}:\n{content}")
    text = "\n\n".join(parts)
    if len(text) > JUDGE_TASK_CHAR_CAP:
        text = text[:JUDGE_TASK_CHAR_CAP] + f"\n[... task truncated at {JUDGE_TASK_CHAR_CAP} characters for the judge ...]"
    return text


def judge_body(case: Case, first, second) -> dict:
    user = (
        "THE TASK:\n" + task_text(case.body) + "\n\n=== RESPONSE A ===\n" + _text(first) + "\n\n=== RESPONSE B ===\n" + _text(second) + "\n"
    )
    return {"system": JUDGE_SYSTEM, "messages": [{"role": "user", "content": user}], "max_tokens": JUDGE_MAX_TOKENS}


# ══ statistics ═════════════════════════════════════════════════════════════════════════
def preference_stats(wins: int, ties: int, losses: int, margin: float = MARGIN) -> dict:
    """Candidate preference share p = (W + T/2) / n, its Wilson 95% interval, and the verdict
    the interval alone supports (gates are applied by the caller, never here)."""
    n = wins + ties + losses
    out = {"n": n, "wins": wins, "ties": ties, "losses": losses, "margin": margin, "bar": PARITY - margin}
    if n == 0:
        return {**out, "p": None, "ci95": None, "stat_verdict": INCONCLUSIVE, "n_to_clear": None}
    k = wins + ties / 2.0
    p = k / n
    lo, hi = wilson_interval(k, n)
    if lo >= PARITY - margin:
        verdict = NON_INFERIOR
    elif hi < PARITY:
        verdict = INFERIOR
    else:
        verdict = INCONCLUSIVE
    return {
        **out,
        "p": p,
        "ci95": (lo, hi),
        "stat_verdict": verdict,
        "n_to_clear": n_to_clear(p, margin) if verdict == INCONCLUSIVE else None,
    }


def n_to_clear(p: float, margin: float = MARGIN, cap: int = 2000) -> Optional[int]:
    """Smallest n at which the SAME observed share would clear the bar (None if it never can)."""
    if p is None or p <= PARITY - margin:
        return None
    lo_n, hi_n = 1, cap
    if wilson_interval(p * cap, cap)[0] < PARITY - margin:
        return None
    while lo_n < hi_n:
        mid = (lo_n + hi_n) // 2
        if wilson_interval(p * mid, mid)[0] >= PARITY - margin:
            hi_n = mid
        else:
            lo_n = mid + 1
    return lo_n


# ══ the run ════════════════════════════════════════════════════════════════════════════
@dataclass
class Ledger:
    usd: dict = field(default_factory=lambda: {"incumbent": 0.0, "candidate": 0.0, "judge": 0.0})
    calls: dict = field(default_factory=lambda: {"incumbent": 0, "candidate": 0, "judge": 0})

    def charge(self, role, usage, model):
        self.calls[role] += 1
        self.usd[role] += call_cost(usage, model)


def ceiling_usd(cases, incumbent, candidate, judge) -> dict:
    """An upper bound on the run's spend: every output at max_tokens, input at chars/4 x 1.3."""
    bc = _bc()

    def price(model):
        return bc._price_for(resolved(model))

    out = {"incumbent": 0.0, "candidate": 0.0, "judge": 0.0}
    for c in cases:
        tin = len(json.dumps(c.body, default=str)) / 4.0 * TOKENIZER_MARGIN
        tout = float(c.body.get("max_tokens") or 1024)
        for role, model in (("incumbent", incumbent), ("candidate", candidate)):
            pr = price(model)
            out[role] += (tin * pr["in"] + tout * pr["out"]) / 1e6
        jin = (min(len(task_text(c.body)), JUDGE_TASK_CHAR_CAP) / 4.0 + 2 * tout) * TOKENIZER_MARGIN + 300
        pj = price(judge)
        out["judge"] += (jin * pj["in"] + JUDGE_MAX_TOKENS * pj["out"]) / 1e6
    out["total"] = sum(out.values())
    return out


def run_cap_usd() -> float:
    from ai import dev_session_cap

    override = dev_session_cap.run_override()
    return override if override is not None else dev_session_cap.PER_RUN_USD


def quiet_call_json(call, body, schema, label):
    """`structured_json.call_json` — the production door, including its one schema-less
    fallback — with its stdout log line captured instead of printed (it would corrupt
    `--json`). Returns (parsed, fell_back_to_schemaless)."""
    import contextlib
    import io

    from ai.structured_json import call_json

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        parsed = call_json(call, body, schema=schema, label=label)
    return parsed, "fallback=schema_rejected" in buf.getvalue()


def _generate(case, model, role, invoker, ledger, row):
    """One arm's output for one case: text, or the parsed object for a structured feature."""

    def call(body):
        resp = invoker(body, model)
        ledger.charge(role, resp.get("usage") or {}, model)
        return resp

    if case.schema is not None:
        parsed, fell_back = quiet_call_json(call, dict(case.body), case.schema, f"model_swap_eval.{role}")
        if fell_back:
            row[f"{role}_schema_fallback"] = True  # the model refused output_config; production would fall back the same way
        return parsed
    return _bc().first_text(call(dict(case.body)))


def validate_models(incumbent, candidate, judge) -> list:
    """Raise ValueError on a comparison this harness must not run; return the warnings a
    comparison it may run must carry (today: the judge is the incumbent's own model)."""
    r_inc, r_cand, r_judge = resolved(incumbent), resolved(candidate), resolved(judge)
    if r_cand == r_inc:
        raise ValueError(f"candidate {candidate!r} resolves to the incumbent's own profile {r_inc!r} — nothing to compare")
    if r_judge == r_cand:
        raise ValueError(f"the judge {judge!r} resolves to the candidate {r_cand!r}: a model may not judge its own output (#4771)")
    warnings = []
    if r_judge == r_inc:
        warnings.append(
            f"judge == incumbent: the judge {judge!r} resolves to the incumbent's own profile {r_inc!r}, so any "
            "self-preference bias favours the incumbent (conservative for a swap, but a candidate loss is weaker evidence). "
            "Pass --judge with a different model to remove it."
        )
    return warnings


def run(
    feature_name,
    candidate,
    *,
    n=None,
    incumbent=None,
    judge=DEFAULT_JUDGE,
    seed=DEFAULT_SEED,
    dry_run=False,
    invoker=None,
    judge_invoker=None,
    captured_dir=CAPTURED_DIR,
    enforce_cap=True,
):
    from ai.budget_guard import BudgetExceeded

    feature = FEATURES[feature_name]
    incumbent = incumbent or incumbent_model(feature)
    warnings = validate_models(incumbent, candidate, judge)
    cases = build_cases(feature_name, n=n, seed=seed, captured_dir=captured_dir)
    ceiling = ceiling_usd(cases, incumbent, candidate, judge)
    report = {
        "feature": feature_name,
        "incumbent": incumbent,
        "candidate": candidate,
        "judge": judge,
        "resolved": {"incumbent": resolved(incumbent), "candidate": resolved(candidate), "judge": resolved(judge)},
        "price_rows": {"incumbent": price_row(incumbent), "candidate": price_row(candidate), "judge": price_row(judge)},
        "seed": seed,
        "margin": MARGIN,
        "dry_run": bool(dry_run),
        "inputs": len(cases),
        "sources": sorted({c.source for c in cases}),
        "prompt_provenance": sorted({c.prompt_provenance for c in cases}),
        "ceiling_usd": ceiling,
        "warnings": warnings,
        "cases": [],
        "errors": [],
        "stopped": None,
    }
    if dry_run:
        invoker = dry_run_invoker_for(cases)
        judge_invoker = dry_run_judge
    else:
        invoker = invoker or bedrock_invoker
        judge_invoker = judge_invoker or bedrock_invoker
        cap = run_cap_usd()
        report["run_cap_usd"] = cap
        if enforce_cap and ceiling["total"] > cap:
            report["verdict"] = REFUSED
            report["verdict_reason"] = (
                f"the ceiling estimate ${ceiling['total']:.2f} exceeds this run's dev-session cap ${cap:.2f}; "
                "nothing was sent. Lower --n, or set DEV_AI_BUDGET_USD on the command (the owner's call)."
            )
            report["stats"] = preference_stats(0, 0, 0)
            report["cost_usd"] = {"incumbent": 0.0, "candidate": 0.0, "judge": 0.0, "total": 0.0}
            return report

    ledger = Ledger()
    rng = random.Random(seed)
    wins = ties = losses = 0
    picked_first = 0
    for case in cases:
        candidate_first = rng.random() < 0.5  # drawn for every case, so the order never depends on errors
        row = {"id": case.id, "source": case.source, "candidate_shown_first": candidate_first}
        report["cases"].append(row)
        try:
            outputs = {}
            for role, model in (("incumbent", incumbent), ("candidate", candidate)):
                try:
                    outputs[role] = _generate(case, model, role, invoker, ledger, row)
                except BudgetExceeded:
                    raise
                except Exception as e:  # noqa: BLE001 — a failed arm is reported, never dropped silently
                    outputs[role] = None
                    row[f"{role}_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            for role in ("incumbent", "candidate"):
                if f"{role}_error" in row:
                    row[f"{role}_gates"] = [{"gate": "call_error", "detail": row[f"{role}_error"]}]
                else:
                    row[f"{role}_gates"] = case.gate(outputs[role]) + _universal_gates(outputs[role])
            if "incumbent_error" in row or "candidate_error" in row:
                report["errors"].append(
                    {"id": case.id, "stage": "generate", "detail": row.get("incumbent_error") or row.get("candidate_error")}
                )
                row["judged"] = None
                continue
            first, second = (
                (outputs["candidate"], outputs["incumbent"]) if candidate_first else (outputs["incumbent"], outputs["candidate"])
            )

            def jcall(body):
                resp = judge_invoker(body, judge)
                ledger.charge("judge", resp.get("usage") or {}, judge)
                return resp

            try:
                verdict, _ = quiet_call_json(jcall, judge_body(case, first, second), JUDGE_SCHEMA, "model_swap_eval.judge")
                pick = (verdict or {}).get("winner") if isinstance(verdict, dict) else None
                if pick not in ("A", "B", "tie"):
                    raise ValueError(f"judge returned no winner: {str(verdict)[:160]!r}")
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001
                report["errors"].append({"id": case.id, "stage": "judge", "detail": f"{type(e).__name__}: {str(e)[:200]}"})
                row["judged"] = None
                continue
            if pick == "tie":
                outcome = "tie"
                ties += 1
            else:
                picked_first += pick == "A"
                cand_won = (pick == "A") == candidate_first
                outcome = "win" if cand_won else "loss"
                wins += cand_won
                losses += not cand_won
            row["judged"] = outcome
            row["judge_reason"] = str(verdict.get("reason", ""))[:300]
        except BudgetExceeded as e:
            report["stopped"] = f"{type(e).__name__}: {e}"
            row["judged"] = None
            break

    stats = preference_stats(wins, ties, losses)
    stats["judge_picked_first_shown"] = picked_first
    report["stats"] = stats
    report["cost_usd"] = {**ledger.usd, "total": sum(ledger.usd.values())}
    report["calls"] = dict(ledger.calls)
    report["gate_failures"] = gate_failures(report["cases"])
    report["verdict"], report["verdict_reason"] = decide(report)
    return report


def gate_failures(rows):
    """{role: {gate: [case ids]}} — every failure listed by gate, never summed into a score."""
    out = {"incumbent": {}, "candidate": {}}
    for row in rows:
        for role in out:
            for f in row.get(f"{role}_gates") or []:
                out[role].setdefault(f["gate"], [])
                if row["id"] not in out[role][f["gate"]]:
                    out[role][f["gate"]].append(row["id"])
    return out


def decide(report):
    s = report["stats"]
    cand = report["gate_failures"]["candidate"]
    if report["dry_run"]:
        return DRY_RUN, "no model was called; the pipeline, gates and table are exercised on frozen reference outputs"
    if cand:
        names = ", ".join(f"{g} ({len(ids)})" for g, ids in sorted(cand.items()))
        return BLOCKED_BY_GATE, f"the candidate failed deterministic gate(s): {names}. Gate failures are never averaged away."
    if report["stopped"]:
        return INCOMPLETE, f"the run stopped early on a budget stop ({report['stopped'][:160]}); n={s['n']} of {report['inputs']}"
    if s["stat_verdict"] == NON_INFERIOR:
        return NON_INFERIOR, f"Wilson 95% lower bound {s['ci95'][0]:.2f} >= {s['bar']:.2f} (margin {s['margin']:.2f}), every gate passed"
    if s["stat_verdict"] == INFERIOR:
        return INFERIOR, f"Wilson 95% upper bound {s['ci95'][1]:.2f} < parity {PARITY:.2f}"
    more = f"; at the observed share about n={s['n_to_clear']} would clear the bar" if s.get("n_to_clear") else ""
    return INCONCLUSIVE, f"the interval is too wide to call (n={s['n']}){more}"


# ══ report ═════════════════════════════════════════════════════════════════════════════
def markdown(report) -> str:
    s = report["stats"]
    lines = [
        f"### Model swap eval — `{report['feature']}`" + (" (DRY RUN)" if report["dry_run"] else ""),
        "",
        "| | model | resolved profile | price row |",
        "|---|---|---|---|",
    ]
    for role in ("incumbent", "candidate", "judge"):
        lines.append(f"| {role} | `{report[role]}` | `{report['resolved'][role]}` | `{report['price_rows'][role]}` |")
    lines += [
        "",
        f"Inputs: **{report['inputs']}** from {', '.join(f'`{x}`' for x in report['sources'])} · seed `{report['seed']}` · "
        f"prompts: {'; '.join(report['prompt_provenance'])}",
        "",
    ]
    for w in report.get("warnings") or []:
        lines += [f"**Warning:** {w}", ""]
    gf = report.get("gate_failures")
    if gf is not None:
        gates = sorted(set(gf["incumbent"]) | set(gf["candidate"]))
        lines += ["**Deterministic gates** (failures per gate, never averaged)", "", "| gate | incumbent | candidate |", "|---|---|---|"]
        if not gates:
            lines.append(f"| every gate | 0/{report['inputs']} | 0/{report['inputs']} |")
        for g in gates:
            inc, cand = gf["incumbent"].get(g, []), gf["candidate"].get(g, [])
            lines.append(f"| {g} | {len(inc)} {inc[:4] if inc else ''} | {len(cand)} {cand[:4] if cand else ''} |")
        lines.append("")
    ci = s.get("ci95")
    lines += [
        "**Blind pairwise judge** (order randomised per case)",
        "",
        "| n | win | tie | loss | preference p = (W+T/2)/n | Wilson 95% | bar (0.5 − margin) |",
        "|---|---|---|---|---|---|---|",
        f"| {s['n']} | {s['wins']} | {s['ties']} | {s['losses']} | "
        + (f"{s['p']:.2f}" if s["p"] is not None else "—")
        + " | "
        + (f"[{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "—")
        + f" | {s['bar']:.2f} |",
        "",
    ]
    if "judge_picked_first_shown" in s:
        lines.append(
            f"Judge picked the first-shown response in {s['judge_picked_first_shown']} of {s['wins'] + s['losses']} decided pairs."
        )
    if report["errors"]:
        lines.append(
            f"Excluded from n: {len(report['errors'])} — "
            + "; ".join(f"{e['id']} ({e['stage']}: {e['detail'][:80]})" for e in report["errors"][:5])
        )
    c, ceil = report.get("cost_usd") or {}, report["ceiling_usd"]
    lines += [
        "",
        f"**Cost** ({'dry-run estimate, nothing billed' if report['dry_run'] else 'bedrock_client.estimate_cost_usd'}): "
        + " · ".join(f"{k} ${c.get(k, 0.0):.4f}" for k in ("incumbent", "candidate", "judge", "total"))
        + f" — pre-flight ceiling ${ceil['total']:.4f}"
        + (f", run cap ${report['run_cap_usd']:.2f}" if "run_cap_usd" in report else ""),
        "",
        f"**Verdict: {report['verdict']}** — {report['verdict_reason']}",
    ]
    if report.get("stopped"):
        lines.append(f"\nStopped: {report['stopped']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Model swap eval: incumbent vs candidate on frozen inputs (#4771)")
    ap.add_argument("--feature", choices=sorted(FEATURES))
    ap.add_argument("--candidate", help="model name or Bedrock profile id (e.g. us.anthropic.claude-haiku-5-5)")
    ap.add_argument("--incumbent", help="override the feature's current model (default: what it runs on today)")
    ap.add_argument("--judge", default=DEFAULT_JUDGE, help=f"pairwise judge model (default {DEFAULT_JUDGE}; never the candidate)")
    ap.add_argument("--n", type=int, default=None, help="cap the number of inputs (a seeded sample)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--dry-run", action="store_true", help="no model call: exercise cases, gates, judge plumbing and the table offline")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--list", action="store_true", help="list features, their incumbents and input counts")
    args = ap.parse_args(argv)

    if args.list:
        for name, f in sorted(FEATURES.items()):
            print(
                f"{name:18s} incumbent={incumbent_model(f):40s} inputs={len(build_cases(name))}" + ("  structured" if f.structured else "")
            )
        return 0
    if not args.feature or not args.candidate:
        ap.error("--feature and --candidate are required (or --list)")
    try:
        report = run(
            args.feature, args.candidate, n=args.n, incumbent=args.incumbent, judge=args.judge, seed=args.seed, dry_run=args.dry_run
        )
    except ValueError as e:
        print(f"model_swap_eval: refused — {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str) if args.json else markdown(report))
    return 0 if report["verdict"] in (NON_INFERIOR, DRY_RUN) else 1


if __name__ == "__main__":
    sys.exit(main())
