"""site_api_ai_prompt.py — prompt shaping + the grounding vocabulary it feeds.

Extracted from `site_api_ai_lambda.py` when #2276's grounding fix pushed that module
past the 2,000-line god-module gate (`tests/test_lambda_size_gate.py`). Grandfathering
a file that had just been grown would have been the wrong answer — the gate exists to
force exactly this split.

These pieces belong together, and the coupling is the reason #2276 existed:
`_shrink_for_prompt` bounds the JSON the model is shown without ever cutting a token
in half, and `_grounding_allow_lists` builds the ADR-104 gate's allowed-number
vocabulary from the SOURCE payload rather than from that bounded string. Splitting
them across modules would make it easy to reintroduce the bug where the gate inherits
its vocabulary from whatever the truncator happened to emit — and so certifies a
figure the truncation itself corrupted.

`site_api_ai_lambda` re-exports every name here, so existing callers and tests keep
their import path.
"""

import json

from ai.ai_context import build_experiment_phase_context, format_experiment_phase_context


def _shrink_for_prompt(data, cap: int = 9000) -> str:
    """Deterministically bound the JSON handed to the model WITHOUT ever cutting
    the text mid-token. The return value is always parseable JSON, and every
    scalar in it is a scalar that exists in `data`.

    #2276 — MEASURED: the old body trimmed long lists and then did an
    unconditional `txt[:cap]`, contradicting its own docstring. A payload still
    over `cap` after trimming was sliced anywhere: a 40-key payload at cap=200
    came out ending `"value": 1234.567` — unparseable JSON AND a number that
    exists nowhere in the source. That is not cosmetic. `_handle_explain` derives
    the ADR-104 grounded-generation allow-list from this string, so the slice's
    invented `1234.567` entered the gate's vocabulary and the gate *certified* it
    as grounded. Shrinking now drops whole list elements, then whole top-level
    entries — never characters.
    """

    def _trim(v, keep: int):
        if isinstance(v, list):
            return [_trim(x, keep) for x in v[:keep]]
        if isinstance(v, dict):
            return {k: _trim(x, keep) for k, x in v.items()}
        return v

    shrunk = data
    for keep in (12, 8, 4, 2, 1, 0):
        shrunk = _trim(data, keep)
        txt = json.dumps(shrunk, default=str)
        if len(txt) <= cap:
            return txt

    # Still over cap with every list emptied: drop whole top-level entries, in
    # order, until what remains fits. `json.dumps({k: v})[1:-1]` is the exact
    # rendered width of one entry under the default separators, so the budget is
    # measured rather than guessed — no trailing slice is ever needed.
    if isinstance(shrunk, dict):
        kept: dict = {}
        size = 2  # "{}"
        for k, v in shrunk.items():
            entry = len(json.dumps({k: v}, default=str)) - 2
            add = entry + (2 if kept else 0)  # ", " separator
            if size + add > cap:
                break
            kept[k] = v
            size += add
        return json.dumps(kept, default=str)
    # A single oversized scalar: refuse it whole rather than hand the model half
    # of it. `null` is honest; a half-number is not.
    return json.dumps(None)


def _grounding_allow_lists(gg, payload, prompt_txt: str, day_ctx: str):
    """Build the ADR-104 gate's vocabulary as a subset of the SOURCE data (#2276).

    The allow-lists used to be derived from `prompt_txt` alone — the same string
    `_shrink_for_prompt` had just bounded. Any corruption of that string silently
    ENLARGED the gate's vocabulary, so the gate could vouch for a figure that
    appears nowhere in the fetched JSON: exactly inverting its purpose.

    Intersecting the prompt-derived set with the source-derived one makes the
    invariant structural rather than a consequence of the truncator being
    correct: `allowed ⊆ numbers(payload) ∪ numbers(day_ctx)` holds however
    `prompt_txt` was produced. The intersection (rather than the union) is
    deliberate — a number dropped from the prompt is one the model never saw, so
    citing it is a hallucination even though the source contains it.
    """
    return (
        gg.allowed_numbers(prompt_txt, day_ctx) & gg.allowed_numbers(payload, day_ctx),
        gg.allowed_dates(prompt_txt, day_ctx) & gg.allowed_dates(payload, day_ctx),
    )


_EXPLAIN_SYSTEM = (
    "You are the plain-English tour guide for averagejoematt.com — Matthew's public, single-subject (N=1) "
    "health experiment. A reader tapped 'explain this page' on a data-dense surface. You receive the page's "
    "REAL, server-fetched JSON and a description of what the surface shows.\n\n"
    "RULES (absolute):\n"
    "- 3-4 short sentences of plain English. No headers, no bullets, no markdown.\n"
    "- Narrate ONLY values present in the JSON — never compute, average, or extrapolate a number yourself.\n"
    "- Correlative framing only: 'tracks with', 'coincided with' — never causal claims, never health advice.\n"
    "- If the data is thin or empty, say so honestly and plainly (the experiment-day context tells you why a "
    "young record is short) — never pad with invented data.\n"
    "- The reader is NOT Matthew; the data and devices are Matthew's.\n"
    "- N=1: flag thin evidence as preliminary where it matters."
)


def board_grounding_findings(system_text: str, message_text: str, answer_text: str, prior_answers: str = "") -> list:
    """ADR-104 board gate core — the exact allowed-set + findings composition BOTH
    board endpoints apply (initial ask and per-turn follow-up): every number the
    coach states must exist in its system context, the reader messages, or (for
    follow-ups) its own prior answers. Extracted so the #812 golden-surface eval
    harness replays fixtures through the ACTUAL gate path, not a re-implementation.
    Returns grounded_generation findings ([] = grounded)."""
    from ai import grounded_generation as _gg
    from ai.grounding_gate_params import cycle_gate_params  # #1967

    _srcs = (system_text, message_text, prior_answers or None)
    allowed = _gg.allowed_numbers(*_srcs)
    # #1967: date allow-list from the SAME sources, plus the cycle anchors (#1691/#1897).
    return _gg.grounding_findings(answer_text, allowed=allowed, allowed_dates=_gg.allowed_dates(*_srcs), **cycle_gate_params())


#: The domains /api/explain narrates a week over — prompt vocabulary, kept beside
#: the prompt that consumes it.
_EXPLAIN_WEEK_DOMAINS = ("sleep", "training", "nutrition", "glucose", "physical", "mind")


def _phase_context_block() -> str:
    """#1086: the ONE shared experiment-phase block (day/week/stage, pre-start
    state, audience, cannot-exist-yet guardrail) for the public AI surfaces.
    Anchored to "now" (PT) — these are live-request prompts. Rendered into the
    UNCACHED prompt parts only: /api/ask's plain system string and the board's
    user turn — never the board's cache_control-wrapped persona system block
    (COST-OPT-2: the block changes daily; the persona block stays byte-stable)."""
    return format_experiment_phase_context(build_experiment_phase_context())
