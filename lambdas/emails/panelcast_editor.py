"""panelcast_editor.py — the weekly Panel's Haiku editor pass, under a JSON schema (#4501).

The editor ran out of budget. In 60 days of `/aws/lambda/coach-panel-podcast` (read
2026-10-01), all three `editor unparseable` lines (09-25 attempt 1; 09-30 attempts 1 and 2)
follow a Haiku `TRUNCATED at max_tokens=600`, cut inside the `issues` list so the JSON never
closed. (A parsed reply logged nothing, so the window holds no measured verdict length.) The
pipeline then failed open to `pass`, and nothing said that the editor had not been read.

Two changes, both here:
  * the request carries EDITOR_OUTPUT_SCHEMA as `output_config.format` through
    `ai.structured_json.call_json` (#4276's one door), so Bedrock constrains the shape;
  * the prompt bounds the verdict (at most EDITOR_MAX_ISSUES issues of one short sentence)
    and the budget is EDITOR_MAX_TOKENS. The measured replies were all CUT at 600, so 600 is
    a lower bound on what an unbounded verdict costs, not a size. The bounded verdict is
    about 5 x 30 words plus a quote, roughly 250 tokens; 1500 leaves room for a model that
    ignores the bound without paying for an unbounded ramble.

A reply that still does not parse is UNEVALUATED: the log names the decoder's error and
position, and the result carries `verdict: "unevaluated"` with no issues. It is never read as
a hold, and never as a reason it did not state. The weekly run then goes on to the
deterministic safety gate and the read-aloud QA judge, as it did before.
"""

from __future__ import annotations

import json
from typing import Any, Callable

EDITOR_MAX_TOKENS = 1500
EDITOR_MAX_ISSUES = 5
VERDICTS = ("pass", "revise", "hold")
UNEVALUATED = "unevaluated"

EDITOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "issues": {"type": "array", "items": {"type": "string"}},
        "pull_quote": {"type": "string"},
    },
    "required": ["verdict", "issues", "pull_quote"],
    "additionalProperties": False,
}


def editor_system(bible: dict) -> str:
    return (
        "You are the EDITOR of a narrative podcast. Judge the script against this rubric and return ONLY JSON "
        '{"verdict":"pass"|"revise"|"hold","issues":[...],"pull_quote":"..."}. '
        f"RUBRIC:\n{json.dumps((bible or {}).get('editor_rubric', {}))}\n"
        "Use 'hold' (route to a human, do NOT publish) if you detect any: causal claim, a bogus finding on a tiny sample, "
        "a report-card/judgmental tone, a hard week handled without compassion, or a reference to grief/family/a named person. "
        "Use 'revise' for fixable quality issues; 'pass' only if it clears the must-pass bar and the quality floor. "
        f"Be brief: at most {EDITOR_MAX_ISSUES} issues, each ONE sentence under 30 words (quote at most a few words of the "
        "script); pull_quote is one line under 25 words, or an empty string."
    )


def _valid(parsed: Any) -> bool:
    return (
        isinstance(parsed, dict)
        and parsed.get("verdict") in VERDICTS
        and isinstance(parsed.get("issues", []), list)
        and all(isinstance(i, str) for i in parsed.get("issues", []))
    )


def review(turns: list, bible: dict, invoke: Callable[..., dict], model: str, logger) -> dict:
    """Run the editor. Returns a parsed {verdict, issues, pull_quote}, or verdict UNEVALUATED."""
    from ai.structured_json import call_json, decode_error

    script = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    body = {
        "model": model,
        "max_tokens": EDITOR_MAX_TOKENS,
        "system": editor_system(bible),
        "messages": [{"role": "user", "content": script}],
    }
    for attempt in (1, 2):
        try:
            parsed = call_json(lambda b: invoke(b, model_name=model), body, schema=EDITOR_OUTPUT_SCHEMA, label="panelcast_editor")
        except Exception as e:  # noqa: BLE001 — an infra failure is UNEVALUATED, never a verdict
            logger.warning("[panel] editor UNEVALUATED (attempt %d): call failed — %s", attempt, str(e)[:200])
            continue
        if _valid(parsed):
            out = {
                "verdict": parsed["verdict"],
                "issues": list(parsed.get("issues") or []),
                "pull_quote": str(parsed.get("pull_quote") or ""),
            }
            logger.info("[panel] editor verdict=%s (attempt %d) issues=%s", out["verdict"], attempt, out["issues"])
            return out
        logger.warning(
            "[panel] editor UNEVALUATED (attempt %d): %s — reply starts %.120r",
            attempt,
            "an object without a valid verdict/issues" if isinstance(parsed, dict) else decode_error(parsed),
            parsed if isinstance(parsed, str) else json.dumps(parsed)[:120],
        )
    logger.warning("[panel] editor UNEVALUATED after 2 attempts — no verdict was read; not a hold reason (safety gate + weekly QA decide)")
    return {"verdict": UNEVALUATED, "issues": [], "pull_quote": ""}
