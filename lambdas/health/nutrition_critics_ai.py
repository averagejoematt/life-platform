"""nutrition_critics_ai.py — the model layer over the three nutrition critics (#5114, epic #5094).

`health.nutrition_critics` decides. This module only NARRATES what it decided (ADR-105 rule 3:
an LLM verdict about data is always preceded by the deterministic computation it narrates).

WHAT THE MODEL MAY DO, AND WHAT IT MAY NOT

  * It writes one short narrative per critic over that critic's own evidence packet, plus
    `agrees` and an optional `dissent` sentence — the model's word, recorded on `model`.
  * It may NEVER move a verdict. Unlike the training critics (`coach.critics.reconcile`, where
    a model may escalate one step on a flagged metric), the nutrition verdict, metric, value,
    reason, provenance and the block's `veto` are the deterministic layer's alone: this module
    writes ONLY the verdict's `model` key and the block's `model_*` keys. A `verdict` key in the
    model's reply is ignored and recorded as ignored.
  * Every number in a narrative must appear in what the model was given (ADR-104's allow-list,
    `ai.grounded_generation`, exact tolerance). A narrative citing any other number is WITHHELD,
    never shipped, and the withholding is recorded.
  * Every narrative carries a rigor label computed HERE, never by the model (ADR-104/105).

THE BUDGET CLASS (ADR-125)

Feature `nutrition_critics`, band 1 (`ai.budget_guard._FEATURE_CUTOFF`): an owner-facing,
internal narrative with a complete deterministic fallback — the verdicts and the decisions
offered ship either way, so it is the cheapest thing to pause. Route `nutrition.critics`
(`ai.model_routing.ROUTES`, WORKHORSE / Haiku 4.5, `AI_MODEL_HAIKU` overrides). It is NOT
one of the `charter.*` routes (`training.charter_ai`): those send the cached charter block,
and these calls narrate a packet that already carries every threshold they may cite — the
prompt sits far under the Haiku floor, recorded declined in `ai.prompt_cache.CACHING_DECISIONS`
("nutrition-critics"). A paused layer says `paused` WITH the tier on every verdict, never a
fabricated narrative; the tier-3 refusal inside `bedrock_client.invoke` (BudgetExceeded) is
reported the same way.

PURE apart from the injected `invoke` (the ADR-062 chokepoint or a test double) and the budget
read in `gate()`. It does not import `health.nutrition_critics` (owner-only wiring, #3754):
the MCP resolver hands it the block and the packets.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ai import grounded_generation
from ai.model_routing import model_for

LAYER_VERSION = "nutrition-critics-ai@1.0.0"
ROUTE = "nutrition.critics"
BUDGET_FEATURE = "nutrition_critics"
NUTRITION_CRITICS_MODEL = model_for("nutrition.critics")  # == ROUTE; a literal, so the #4770 route census can read it
MAX_TOKENS = 240  # one JSON object with two short sentences
NARRATIVE_MAX_CHARS = 280

# The verdict fields the model may never write (the no-override rule, tested).
VERDICT_KEYS = ("verdict", "metric", "value", "field", "to", "reason", "redline", "provenance")

DESCRIPTIVE_ONLY = "descriptive only — n=1, his own logged days; no interval and no causal claim (ADR-105 rule 1)"

SYSTEM_PROMPT = (
    "You narrate ONE nutrition critic's verdict for the person it is about. The verdict is FINAL: it was "
    "computed in code from the evidence packet, and you cannot change, soften or escalate it. "
    'Reply with exactly one JSON object: {"narrative": <at most two sentences, at most 280 characters>, '
    '"agrees": true|false, "dissent": <one sentence or null>}. '
    "Rules: cite only numbers that appear in the verdict or the packet; never invent a threshold, a trend, a "
    "date or a cause; describe associations without causal wording; an input listed under `unknown` is "
    "unmeasured, never a miss; no medical advice. If you read the numbers differently from the verdict, set "
    "agrees to false and say why in dissent — the verdict still stands."
)


def _cutoff(guard: Any) -> int | None:
    """The lowest tier at which the feature is paused — derived from the guard's own ladder."""
    return next((t for t in range(4) if BUDGET_FEATURE in guard.paused_features(t)), None)


def gate(guard: Any = None) -> dict[str, Any]:
    """Whether the model layer may run now: {allowed, tier, cutoff, paused}. Never raises and never
    moves the tier — it reads it. `paused` is the honest sentence every verdict carries when not allowed."""
    try:
        if guard is None:
            from ai import budget_guard as guard
        tier, cutoff = guard.current_tier(), _cutoff(guard)
        if guard.allow(BUDGET_FEATURE):
            return {"allowed": True, "tier": tier, "cutoff": cutoff, "paused": None}
        reason = f"paused — budget tier {tier}: {BUDGET_FEATURE} pauses at tier {cutoff} and above (ADR-125); deterministic verdicts only"
        return {"allowed": False, "tier": tier, "cutoff": cutoff, "paused": reason}
    except Exception as e:  # noqa: BLE001 — an unreadable guard pauses the layer, never the verdicts
        return {"allowed": False, "tier": None, "cutoff": None, "paused": f"paused — budget guard unreadable ({type(e).__name__})"}


def build_prompt(verdict: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    """One Messages body per critic: the fixed system text, then the verdict and ITS packet only."""
    user = json.dumps(
        {
            "critic": packet.get("critic"),
            "verdict": {k: verdict.get(k) for k in ("verdict", "metric", "value", "reason", "provenance")},
            "packet": {k: packet.get(k) for k in ("numbers", "flags", "violations", "unknown")},
        },
        sort_keys=True,
        default=str,
    )
    return {
        "model": NUTRITION_CRITICS_MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user + "\nReturn the JSON object."}],
    }


def rigor_label(verdict: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    """The ADR-104/105 label every narrative carries — computed in code, never by the model."""
    return {
        "verdict_source": "deterministic",
        "narrative_source": "model",
        "claim_class": DESCRIPTIVE_ONLY,
        "threshold_provenance": verdict.get("provenance") or "no threshold crossed",
        "unmeasured_inputs": list(packet.get("unknown") or []),
        "number_gate": "every number in the narrative appears in the verdict or the packet (ADR-104)",
    }


def _parse(resp: dict[str, Any]) -> dict[str, Any]:
    """The model's JSON object, or a named failure. Never a fabricated narrative."""
    if (resp or {}).get("stop_reason") == "max_tokens":
        # No retry: MAX_TOKENS and the packet are fixed, so the truncation is deterministic — the #3828 residual.
        return {"error": f"truncated at max_tokens={MAX_TOKENS}"}
    text = "".join(p.get("text", "") for p in (resp or {}).get("content", []) if p.get("type") == "text").strip()
    from ai import structured_json  # the one parse door (#4276)

    try:
        obj = structured_json.load_json_span(text, "{")
    except structured_json.JsonSpanError as e:
        return {"error": f"no JSON object in a {len(text)}-char response" if e.kind == "no_span" else "json.loads failed"}
    narrative = str((obj or {}).get("narrative") or "").strip() if isinstance(obj, dict) else ""
    if not narrative:
        return {"error": "no narrative in the model's object"}
    sentences = re.split(r"(?<=[.!?])\s", narrative)
    out = {"narrative": " ".join(sentences[:2])[:NARRATIVE_MAX_CHARS], "agrees": obj.get("agrees") is not False}
    if obj.get("dissent"):
        out["dissent"] = str(obj["dissent"]).strip()[:200]
    if "verdict" in obj:
        out["model_verdict_ignored"] = f"the model returned verdict={obj['verdict']!r}; the deterministic verdict stands (#5114)"
    return out


def narrate_one(verdict: dict[str, Any], packet: dict[str, Any], resp: dict[str, Any]) -> dict[str, Any]:
    """The `model` record for one verdict: the narrative + its rigor label, or why there is none."""
    parsed = _parse(resp)
    if parsed.get("error"):
        return {"error": parsed["error"], "model": NUTRITION_CRITICS_MODEL}
    text = " ".join(filter(None, (parsed["narrative"], parsed.get("dissent"))))
    allowed = grounded_generation.allowed_numbers({k: verdict.get(k) for k in VERDICT_KEYS}, packet)
    invented = grounded_generation.fabricated_numbers(text, allowed, tolerance=grounded_generation.NUMBER_TOLERANCE_EXACT)
    if invented:
        return {
            "withheld": f"the narrative cited {invented[:3]}, which is in neither the verdict nor the packet (ADR-104 number gate)",
            "model": NUTRITION_CRITICS_MODEL,
        }
    return {**parsed, "rigor": rigor_label(verdict, packet), "model": NUTRITION_CRITICS_MODEL}


def _budget_stop() -> type[BaseException]:
    try:
        from ai.budget_guard import BudgetExceeded

        return BudgetExceeded
    except ImportError:  # pragma: no cover — the guard ships in every bundle
        return type("NoBudgetStop", (Exception,), {})


def _pause(verdicts: list[dict[str, Any]], reason: str, tier: int | None) -> None:
    for v in verdicts:
        v["model"] = {"paused": reason, "tier": tier}


def apply(
    result: dict[str, Any],
    packets: dict[str, dict[str, Any]],
    *,
    invoke: Callable[[dict[str, Any]], dict[str, Any]] | None,
    gate_state: dict[str, Any],
) -> dict[str, Any]:
    """Narrate each verdict of a `nutrition_critics.run` / `block` result in place. Writes only each
    verdict's `model` and the block's `model_ran`, `model_paused_reason` and `model_layer`."""
    verdicts = result.get("verdicts") or []
    layer = {"version": LAYER_VERSION, "feature": BUDGET_FEATURE, "route": ROUTE, "model": NUTRITION_CRITICS_MODEL}
    layer.update(tier=gate_state.get("tier"), pauses_at_tier=gate_state.get("cutoff"))
    result["model_layer"] = layer
    paused = None
    if invoke is None or not gate_state.get("allowed"):
        paused = gate_state.get("paused") or "paused — no model chokepoint was handed in; deterministic verdicts only"
        _pause(verdicts, paused, gate_state.get("tier"))
    stop = _budget_stop()
    for i, v in enumerate(verdicts if invoke is not None and paused is None else []):
        assert invoke is not None  # narrowed for mypy; the loop runs only when it is set
        packet = packets.get(v.get("critic")) or {}
        try:
            v["model"] = narrate_one(v, packet, invoke(build_prompt(v, packet)))
        except stop:
            layer["tier"] = 3
            paused = "paused — budget tier 3: the bedrock_client hard stop refused the call (ADR-125); deterministic verdicts only"
            _pause(verdicts[i:], paused, 3)
            break
        except Exception as e:  # noqa: BLE001 — a model failure is recorded on the verdict, never raised past it
            v["model"] = {"error": f"{type(e).__name__}: {e}"[:200], "model": NUTRITION_CRITICS_MODEL}
    narrated = sum(1 for v in verdicts if (v.get("model") or {}).get("narrative"))
    layer["state"] = ("partial" if narrated else "paused") if paused else ("ran" if narrated else "no_narrative")
    result["model_ran"] = narrated > 0
    result["model_paused_reason"] = paused
    return result
