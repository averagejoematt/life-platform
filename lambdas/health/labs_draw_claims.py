"""labs_draw_claims.py — the ONE detector for "narrates arranging a past lab draw" (#3728, #4134).

Two consumers, one detector:

- the nightly reader-truth check (`operational.qa_check_coach_labs`) catches the class at the
  serving edge, after it has shipped;
- the coach quality gate (`coach.coach_quality_gate`) refuses the labs coach's draft before it
  ships, through the gate's existing regenerate-or-hold path (#4134).

It lived only in the nightly until #4134. On 2026-09-23 the stored labs-coach narrative said
"Schedule the draw. Lock the training calendar … so the 48-hour window is protected", the
nightly FAILED on it, and nothing upstream could have refused it — the detector was on the
wrong side of the publish. Two copies would drift (#3737's analyzer and the coach producer did
exactly that), so both sides import this module.

The rule: when the labs store's newest draw is in the PAST, no sentence may arrange a draw, or
instruct ahead of one, unless it names a FUTURE panel ("next", "follow-up", …) — that stays
sayable. Pure: no I/O, no clock.
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")

_SCHEDULING_VERB = r"(?:schedul\w*|book\w*|arrang\w*|plan(?:ning|s|ned)?\s+(?:for|to)|prepare\s+for|mark\s+your\s+calendar)"
DRAW_NOUN = r"(?:draw|panel|bloodwork|blood\s+work|lab\s+order)"
_SCHEDULING_A_DRAW = re.compile(_SCHEDULING_VERB + r"[^.!?;\n]{0,40}?\b" + DRAW_NOUN + r"\b", re.IGNORECASE)

# An honest forward-looking sentence names a FUTURE panel rather than borrowing the date
# of a past one. These make the sentence legitimate, so they are not findings.
_FUTURE_PANEL = re.compile(r"\b(?:next|another|a\s+second|follow[-\s]?up|upcoming|re[-\s]?test|repeat)\b", re.IGNORECASE)

# An INSTRUCTION anchored to a past draw — "Report any unusual fatigue BEFORE THE APRIL DRAW" —
# has no scheduling verb at all. The discriminator against ordinary past tense ("His HbA1c
# before the April draw was 5.9") is that the sentence OPENS with a bare imperative.
_DIRECTIVE_OPENER = re.compile(
    r"^\s*(?:Report|Verify|Execute|Document|Confirm|Ensure|Bring|Fast|Avoid|Mark|Check|Make\s+sure|Be\s+sure|Remember)\b",
    re.IGNORECASE,
)
_AHEAD_OF_A_DRAW = re.compile(
    r"\b(?:before|ahead\s+of|prior\s+to|in\s+advance\s+of)\s+(?:the\s+)?(?:\w+\s+){0,2}?" + DRAW_NOUN + r"\b", re.IGNORECASE
)


def schedules_a_past_draw(text: str | None) -> list[str]:
    """Sentences that arrange, or instruct ahead of, a draw without naming a future one."""
    out = []
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        if _FUTURE_PANEL.search(sentence):
            continue  # naming the NEXT panel is honest and must stay sayable
        arranging = _SCHEDULING_A_DRAW.search(sentence)
        instructing = _DIRECTIVE_OPENER.search(sentence) and _AHEAD_OF_A_DRAW.search(sentence)
        if arranging or instructing:
            out.append(" ".join(sentence.split())[:120])
    return out
