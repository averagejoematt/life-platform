"""quality_gate_contract.py — the wire contract between the coach pipeline and
the `coach-quality-gate` Lambda (#1374).

One tiny module with one job: own the EXACT event payload production sends to the
quality gate, so that everything which needs to reproduce that call — the caller
(`ai_calls._invoke_quality_gate_sync`) and the judge-calibration harness
(`tests/judge_calibration.py`) — reads it from the same place.

Why it is its own module rather than a helper inside `ai_calls`: `ai_calls` is a
baselined god-module under the #1665 size ratchet, and this is exactly the
"cohesive helper module beside it" that ratchet asks for. It is also genuinely
separable — a call contract, not generation logic — and importing it costs nothing
(stdlib + `common.pacific_time`, no boto3, no clients), which is what lets a test
harness pull the production payload shape without dragging the generation stack
in behind it.

The drift this prevents is specific and has bitten before: a harness that
hand-rebuilds a production call slowly diverges from it and then manufactures
findings about an instrument nothing actually uses.
"""

from typing import Any, Iterable, Optional

from common.pacific_time import pacific_today

# The deployed function name the coach pipeline invokes synchronously (ADR-108/#390).
QUALITY_GATE_FUNCTION_NAME = "coach-quality-gate"

# ── #2573: the deterministic grounding context, carried INSIDE generation_brief ──
# The gate's rubric was blind to fabricated numbers (all three canaries scored
# 92/92/82 and passed). The fix consumes the ADR-104 deterministic verdict rather
# than asking the LLM to re-decide it in prose (ADR-105: deterministic computation
# before any LLM verdict) — but the gate Lambda cannot recompute that verdict on
# its own, because the allow-list is derived from the ASSEMBLED GENERATION PROMPT,
# which never crosses the wire. So the caller ships the already-computed allow-list.
#
# Why nested in `generation_brief` rather than as new top-level event keys: the
# top-level payload shape is diffed key-by-key against the live call site by
# `tests/test_judge_calibration_1374.py`, and the brief is already the "everything
# the generation had" channel. Nesting keeps the wire contract's top-level keys
# byte-identical and costs the size-ratcheted `ai_calls` no new call-site lines.
GROUNDING_ALLOWLIST_KEY = "grounding_allowlist"
AUTHORITATIVE_FACTS_KEY = "authoritative_facts"

# ── #3414: the opt-in field for ASYNC callers — verdict captured CALLEE-side ──
# A fire-and-forget (Event) invoke returns nothing to its caller, so a caller
# that wants the verdict MEASURED must say so on the event itself; the gate
# Lambda then emits the CloudWatch datapoints + eval retention as it completes
# (`coach_quality_gate._emit_async_verdict`). The value is the `eval_retention`
# surface name (e.g. "board_ask"). This is a DELIBERATE contract change, not an
# incidental one: the key is attached ONLY when a caller passes
# `emit_verdict=...` — the daily brief's enforcement wire payload
# (`ai_calls._invoke_quality_gate_sync`, key-by-key-diffed by
# `tests/test_judge_calibration_1374.py`) stays byte-identical, and a report
# emitted this way is OBSERVED, never enforced (no regenerate-or-hold exists on
# an async channel — the reader already has the text).
EMIT_VERDICT_KEY = "emit_verdict"


def quality_gate_event(
    coach_id: str,
    output_text: str,
    generation_brief: Any,
    generation_date: Optional[str] = None,
    emit_verdict: Optional[str] = None,
) -> dict[str, Any]:
    """The EXACT event payload production sends to `coach-quality-gate`.

    `tests/test_judge_calibration_1374.py` diffs the real wire payload against
    this function key-by-key, so the caller and this builder cannot separate.

    Note what is deliberately ABSENT, because it matters to any replay: no
    `voice_spec` (the gate loads it from S3), no `other_coach_outputs` (the gate
    queries DynamoDB), no `skip_cross_coach`. A hermetic replay has to substitute
    for those two AWS reads and must say so rather than quietly measuring a
    different prompt — see `judge_calibration.FIDELITY_GAPS`.

    `emit_verdict` (#3414, async callers only): a surface name opts in to
    callee-side verdict capture — see `EMIT_VERDICT_KEY` above. `None` (the
    default, and what every synchronous enforcement caller passes) attaches no
    key at all, keeping the enforcement wire payload byte-identical to pre-#3414.
    """
    event: dict[str, Any] = {
        "coach_id": coach_id,
        "output_text": output_text,
        "generation_brief": generation_brief if isinstance(generation_brief, dict) else None,
        # #2815: was naive `date.today()` (Lambda TZ=UTC). `ai_calls.py:1316` calls
        # this with NO generation_date, so the naive clock stamped the wire event
        # on every production quality-gate call; `coach_quality_gate.py` then
        # passed that explicit date into `cycle_gate_params`, BYPASSING the #2675
        # Pacific default it would otherwise fall back to. An evening-PT
        # generation was judged against tomorrow's cycle position.
        "generation_date": generation_date or pacific_today(),
    }
    if emit_verdict is not None:
        event[EMIT_VERDICT_KEY] = str(emit_verdict)
    return event


def report_findings(report: dict) -> list:
    """Translate a gate report's violation sections into eval-retention findings.

    ONE mapping platform-wide (#744/#3202/#3414): the daily-brief translator
    (`ai.coach_brief_retention.retain_coach_brief_flag`) and the gate's own
    async-channel capture (`coach_quality_gate._emit_async_verdict`) both read
    it from here, so the two surfaces' retained records cannot drift apart.
    Order is load-bearing only for stability of the retained payloads:
    anti-pattern, decision-class, cross-coach, cycle-boundary (#1973), then the
    deterministic number-grounding findings (#3202 — the one class whose absence
    made the 2026-08-26 holds undiagnosable without an offline re-run).
    """
    findings = []
    for v in report.get("anti_pattern_violations") or []:
        phrase = v.get("phrase") if isinstance(v, dict) else v
        if phrase:
            findings.append({"type": "anti_pattern", "detail": phrase})
    for v in report.get("decision_class_violations") or []:
        if isinstance(v, dict):
            findings.append({"type": "decision_class", "detail": v.get("excerpt", "")})
    for flag in report.get("cross_coach_similarity_flags") or []:
        if isinstance(flag, dict):
            findings.append({"type": "cross_coach_similarity", "detail": flag.get("reason", "")})
    for v in report.get("cycle_boundary_violations") or []:  # #1973
        if isinstance(v, dict):
            findings.append({"type": "cycle_boundary", "detail": v.get("reason", "")})
    _raw_gr = report.get("number_grounding")
    _gr: dict = _raw_gr if isinstance(_raw_gr, dict) else {}
    findings += [{"type": f.get("type"), "detail": f.get("detail", "")} for f in (_gr.get("findings") or []) if isinstance(f, dict)]
    return findings


try:  # #2813 — register with the standing PT-day producer/gate contract sweep
    # (tests/test_pt_day_contract_sweep_2813.py). Optional and inert on a partial
    # bundle; registration is never load-bearing for the wire event this builds.
    from common.pt_day_contract import pt_day_contract as _pt_day_contract

    quality_gate_event = _pt_day_contract(extract=lambda r: r["generation_date"], args=("test-coach", "text", {}))(quality_gate_event)
except Exception:  # noqa: BLE001
    pass


def grounding_from_brief(generation_brief: Any) -> tuple:
    """The READ half of `brief_with_grounding` — ``(allowed_numbers_set, facts_or_None)``
    recovered from a brief that carries the #2573 grounding context (#3202).

    Lives here because this module already owns both keys; the alternative was a private
    reader in the size-ratcheted `ai_calls`, which is exactly the "cohesive helper module
    beside it" case the #1665 ratchet asks for. Total, never raising: a brief that is not
    a dict, or carries no allow-list, or carries an unparseable one, yields ``(set(), …)``
    — its only caller is `eval_retention`, which is never load-bearing.
    """
    if not isinstance(generation_brief, dict):
        return set(), None
    try:
        allowed = {float(n) for n in (generation_brief.get(GROUNDING_ALLOWLIST_KEY) or [])}
    except (TypeError, ValueError):
        allowed = set()
    return allowed, generation_brief.get(AUTHORITATIVE_FACTS_KEY)


def brief_with_grounding(
    generation_brief: Any,
    canonical_facts: Optional[dict] = None,
    allowed_numbers: Optional[Iterable[float]] = None,
) -> Any:
    """Attach the caller's DETERMINISTIC grounding context to the brief (#2573).

    `allowed_numbers` is `grounded_generation.allowed_numbers(prompt, data, facts)`
    as the generation path already computed it — every number the model was given.
    `canonical_facts` is the same dict the ADR-104 grounding gate uses for the
    RHR/recovery/HRV contradiction check.

    THE PRESENCE OF THE ALLOW-LIST KEY IS THE SIGNAL. The gate treats a missing
    `grounding_allowlist` as "this caller supplied no grounding context" and its
    number check reports honest absence rather than a green verdict — never a
    silent pass. An allow-list of `None` (the generation path's grounding gate did
    not run, e.g. `grounded_generation` failed to import) is therefore NOT attached;
    an EMPTY allow-list is a real, if unusual, statement and IS attached.

    Pure: returns a new dict, never mutates the caller's brief.
    """
    if not isinstance(generation_brief, dict):
        return generation_brief
    out = dict(generation_brief)
    out[AUTHORITATIVE_FACTS_KEY] = dict(canonical_facts or {})
    if allowed_numbers is not None:
        out[GROUNDING_ALLOWLIST_KEY] = sorted(float(n) for n in allowed_numbers)
    return out
