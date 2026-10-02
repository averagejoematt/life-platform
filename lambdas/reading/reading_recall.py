"""reading_recall.py — spaced-retrieval scheduling + retention (Phase D, spec §7).

The TWO-CLOCK model (calibration §7): the debrief (immediate, on finish) is
reaction; the probes (spaced, weeks later) are retention. This module owns the
PROBE clock — the expanding-interval schedule, the gist scoring of an answer, and
the n-gated **private** retentionScore. It measures gist + changed-prior, NEVER
verbatim, and renders no score until enough probes mean anything (Henning's
refuse-to-render).

Pure logic + a fail-soft LLM gist scorer. The EventBridge sweep
(`reading_recall_sweep_lambda`) and the MCP `answer_recall` action call it.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from common.pacific_time import pacific_now, pacific_today  # #2798: THE Pacific frame — nextDue/askedAt name Pacific days

logger = logging.getLogger()

# Expanding intervals (days) — a probe lands further out each time it's recalled
# well; a miss shortens the next gap (interval_index moves down, not to zero).
INTERVALS = [3, 7, 16, 35, 90, 180]
RETENTION_N_GATE = 3  # no retentionScore until this many scored probes exist (§7)

MODEL = "claude-haiku-4-5-20251001"

_GIST_SYSTEM = (
    "You score spaced-retrieval recall for a reader. You receive the prompt asked weeks after a book "
    "and the reader's answer. Score how well the answer shows DURABLE understanding — can he reconstruct "
    "the argument, connect it to something else, or name a prior it changed. Reward GIST and changed-prior; "
    "do NOT reward verbatim quoting or penalize forgotten wording. An honest 'I remember the feeling but "
    "not the detail' is partial credit, not zero. Respond with ONLY JSON: "
    '{"gist": <0.0-1.0>, "note": "<one short phrase>"}.'
)
# The shape above, constrained at the model (#4276): Bedrock structured outputs via
# ai.structured_json.call_json. The 0-1 range is clamped in code (numeric bounds are not
# a structured-output keyword this door relies on).
_GIST_SCHEMA = {
    "type": "object",
    "properties": {"gist": {"type": "number"}, "note": {"type": "string"}},
    "required": ["gist", "note"],
    "additionalProperties": False,
}


def _today() -> str:
    return pacific_today()


def next_due(interval_index: int, *, from_date: str | None = None) -> str:
    """The next-due ISO date for a probe at this interval index (clamped to range)."""
    idx = max(0, min(int(interval_index), len(INTERVALS) - 1))
    base = date.fromisoformat(from_date) if from_date else pacific_now().date()
    return (base + timedelta(days=INTERVALS[idx])).isoformat()


def advance(interval_index: int, gist: float) -> int:
    """Move the interval index after an answer: up on a strong gist, down (not to
    zero) on a weak one. The ratchet of memory, autoregulated."""
    idx = int(interval_index)
    if gist >= 0.7:
        return min(idx + 1, len(INTERVALS) - 1)
    if gist < 0.4:
        return max(idx - 1, 0)
    return idx  # middling → hold the interval


def retention_score(performance_history: list, *, n_gate: int = RETENTION_N_GATE) -> float | None:
    """Recency-weighted mean gist across scored probes. PRIVATE + n-gated: returns
    None until `n_gate` scored probes exist (never a score off too-thin data)."""
    scored = [p.get("gistScore") for p in (performance_history or []) if isinstance(p.get("gistScore"), (int, float))]
    if len(scored) < n_gate:
        return None
    # weight recent probes more (the curve as it stands now, not the average ever)
    weights = [i + 1 for i in range(len(scored))]
    return round(sum(s * w for s, w in zip(scored, weights)) / sum(weights), 3)


def _bedrock_send(body: dict, timeout: int) -> dict:
    from common.retry_utils import call_anthropic_raw  # lazy — bundled module, runtime only

    return call_anthropic_raw(body, timeout=timeout)


def score_gist(prompt: str, answer: str, *, caller=None) -> dict:
    """LLM-score a recall answer (gist 0-1 + note). Fail-soft: on any failure
    returns {gist: None} so the probe is recorded un-scored rather than guessed."""
    if not answer or not answer.strip():
        return {"gist": None, "note": "no answer", "scored": False}
    body = {
        "model": MODEL,
        "max_tokens": 200,
        "system": [{"type": "text", "text": _GIST_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": f"Prompt (asked weeks later):\n{prompt}\n\nReader's answer:\n{answer}"}],
    }
    try:
        from ai.structured_json import call_json  # #4276: the one door for JSON-shaped model calls

        parsed = call_json(caller or (lambda b: _bedrock_send(b, 30)), body, schema=_GIST_SCHEMA, label="reading_recall")
        if not isinstance(parsed, dict) or not isinstance(parsed.get("gist"), (int, float)):
            return {"gist": None, "note": "unscored", "scored": False}
        gist = max(0.0, min(1.0, float(parsed["gist"])))
        return {"gist": round(gist, 2), "note": str(parsed.get("note") or "").strip()[:80], "scored": True}
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.warning("[reading_recall] gist scoring failed (%s)", type(e).__name__)
        return {"gist": None, "note": type(e).__name__, "scored": False}


def record_answer(recall: dict, answer: str, *, asked_at: str | None = None, caller=None) -> dict:
    """Score an answer, append it to performanceHistory, advance the interval, and
    compute the next due date. Returns the fields to persist (the caller writes them).
    A scored probe advances; an un-scored one is recorded but doesn't move the ratchet."""
    asked_at = asked_at or _today()
    scored = score_gist(recall.get("prompt", ""), answer, caller=caller)
    history = list(recall.get("performanceHistory") or [])
    history.append({"askedAt": asked_at, "gistScore": scored["gist"], "note": scored["note"], "answer": answer[:500]})
    idx = int(recall.get("intervalIndex", 0))
    new_idx = advance(idx, scored["gist"]) if scored["scored"] else idx
    return {
        "performanceHistory": history,
        "intervalIndex": new_idx,
        "nextDue": next_due(new_idx, from_date=asked_at),
        "retentionScore": retention_score(history),  # private, n-gated (None until enough probes)
        "lastProbeAt": asked_at,
    }


def first_probe(*, from_date: str | None = None) -> dict:
    """The first probe for a freshly-finished book — index 0, due in INTERVALS[0] days."""
    return {"intervalIndex": 0, "nextDue": next_due(0, from_date=from_date), "performanceHistory": []}
