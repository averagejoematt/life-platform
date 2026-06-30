"""reading_onboarding.py — the onboarding interview (taste archaeology, calibration §8).

"Not a genre checklist (that's how you get slop)." A conversation that excavates
taste from OUTSIDE the reading domain — because he has taste even without reading
history — and **deliberately refuses to infer taste from his fitness goal**
(the anti-Goggins rule, calibration §11). Runs as his first real conversation
with Cora; the MCP tool surfaces the questions and `synthesize_taste()` turns his
free-text answers into a starting taste hypothesis, stated at honest LOW
confidence and stored on `READING_PROFILE.tasteHypothesis` to seed the cold-start.

The synthesis is LLM-backed (Haiku via the Bedrock chokepoint) but **fail-soft**:
any failure returns a minimal, honest hypothesis rather than blocking onboarding.
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger()

MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

# The question bank (calibration §8). Cora picks ~6-8 conversationally and follows
# threads — this is the pool, not a script. Exclusions are signal too.
QUESTION_BANK = [
    "What film or show genuinely wrecked you — and what was it about it?",
    "What did you reread as a kid, or read more than once ever?",
    "What kind of conversation do you wish you could hold your own in?",
    "Whose mind do you wish you had? Why theirs?",
    "What bores you to tears on a page?",
    "When you imagine 'a person who reads,' what do you picture — and which part appeals?",
    "Comfort vs. challenge: with a free evening, do you want to escape or to be stretched?",
    "Is there a subject you feel embarrassed not to understand?",
]

_SYSTEM_PROMPT = (
    "You are Dr. Cora Vance, a reading coach conducting a taste-archaeology interview. You receive a "
    "person's free-text answers to questions about film, childhood, curiosity, and boredom — NOT about "
    "books or reading (he isn't a reader yet). Infer a STARTING taste hypothesis from these signals. "
    "HARD RULES: (1) Never infer taste from any fitness, health, weight, discipline, or optimization "
    "goal — that is an explicit anti-pattern; steer toward texture he lacks (story, interiority, beauty, "
    "other lives). (2) State everything at LOW confidence — this is a hypothesis to be corrected, not a "
    "verdict. (3) Exclusions (what bores him) are signal — capture them. Respond with ONLY valid JSON."
)

_USER_TEMPLATE = """From these interview answers, infer a starting taste hypothesis. Respond with ONLY this JSON:
{{
  "affinities": [<3-6 short phrases: textures/themes/registers he's likely drawn to>],
  "aversions": [<what to steer away from, incl. anything he said bores him>],
  "starting_domains": [<2-4 domainTags to try first: fiction, history, biography, memoir, poetry, sci-fi, philosophy, nature, classics>],
  "on_ramp_note": <one sentence on how to win his first book, grounded in HIS answers>,
  "confidence": "low",
  "rationale": <one sentence tying the hypothesis to specific things he said>
}}

Answers:
{answers}"""

_VALID_DOMAINS = {
    "fiction",
    "history",
    "biography",
    "memoir",
    "poetry",
    "sci-fi",
    "fantasy",
    "philosophy",
    "nature",
    "classics",
    "science",
    "psychology",
}


def _empty(reason: str = "") -> dict:
    return {
        "affinities": [],
        "aversions": [],
        "starting_domains": [],
        "on_ramp_note": "",
        "confidence": "low",
        "rationale": "",
        "synthesized": False,
        "error": reason or None,
    }


def _format_answers(answers) -> str:
    """Accept {question: answer} or [{question, answer}] or [answer]."""
    lines = []
    if isinstance(answers, dict):
        for q, a in answers.items():
            if a:
                lines.append(f"Q: {q}\nA: {a}")
    elif isinstance(answers, list):
        for item in answers:
            if isinstance(item, dict):
                q, a = item.get("question", ""), item.get("answer", "")
                if a:
                    lines.append(f"Q: {q}\nA: {a}")
            elif item:
                lines.append(f"A: {item}")
    return "\n\n".join(lines)


def _parse(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.warning("[reading_onboarding] JSON parse failed: %s", e)
        return None


def synthesize_taste(answers, *, caller=None) -> dict:
    """Turn interview answers into a starting taste hypothesis. Fail-soft; never
    raises. `caller` overrides the Bedrock bridge (tests inject a fake)."""
    formatted = _format_answers(answers)
    if not formatted:
        return _empty("no answers")
    body = {
        "model": MODEL,
        "max_tokens": 700,
        "system": [{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": _USER_TEMPLATE.format(answers=formatted)}],
    }
    try:
        if caller is None:
            from retry_utils import call_anthropic_raw  # lazy — layer module, runtime only

            req = urllib.request.Request(
                ANTHROPIC_API,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"content-type": "application/json", "anthropic-version": "2023-06-01"},
            )
            result = call_anthropic_raw(req, timeout=40)
        else:
            result = caller(body)
        text = "".join(b.get("text", "") for b in (result or {}).get("content", []) if b.get("type") == "text")
        parsed = _parse(text)
        if not isinstance(parsed, dict):
            return _empty("unparseable")
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.warning("[reading_onboarding] synthesis failed (%s)", type(e).__name__)
        return _empty(type(e).__name__)

    affinities = [str(t).strip() for t in (parsed.get("affinities") or []) if str(t).strip()][:6]
    aversions = [str(t).strip() for t in (parsed.get("aversions") or []) if str(t).strip()][:6]
    domains = [str(d).strip().lower() for d in (parsed.get("starting_domains") or []) if str(d).strip().lower() in _VALID_DOMAINS][:4]
    return {
        "affinities": affinities,
        "aversions": aversions,
        "starting_domains": domains,
        "on_ramp_note": str(parsed.get("on_ramp_note") or "").strip(),
        "confidence": "low",  # always low — a hypothesis to correct (calibration §8)
        "rationale": str(parsed.get("rationale") or "").strip(),
        "synthesized": True,
        "error": None,
    }
