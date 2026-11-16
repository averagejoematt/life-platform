"""training_notes_requests.py — the deterministic `owner_request` detector of the note layer (#5573, spec §5d).

Split out of `training_notes.py` for the #1665 module-size ceiling and re-exported there, so
`training_notes.owner_request_of` is the name every caller uses. Pure: no I/O, no model.
"""

from __future__ import annotations

import re

# ── owner_request (taxonomy amendment 2026-11-08, #5573) ──────────────────────
# A note in which Matthew asks the PLATFORM for something. Three subtypes, decided in this precedence order
# (the more specific deliverable wins when a note carries two):
#   rule_request   — "we should create a rule for that": a standing rule he wants the platform to adopt.
#   form_guidance  — an ASK ("may need", "email me", "send me", "please") + a guidance MEDIUM ("youtube", "video",
#                    "research", "guidance", "email") + a FORM topic (the `_FORM_RE` words, or "how to"). All three:
#                    "watched a youtube video on form" has a medium and a topic and asks for nothing.
#   question       — a question mark after a word, "not sure how/if/whether…", "should I/we", "is this a good…".
# Measured 2026-11-08 over every stored Hevy exercise note (633 noted exercise-sessions, 149 distinct texts,
# 2021-04 → 2026-11): exactly the three requests the issue names fire, nothing else does — a plain form note
# ("felt off on rep 6") carries a form word and no ask, and is the negative control.
OWNER_REQUEST_SUBTYPES = ("form_guidance", "question", "rule_request")
_RULE_REQUEST_RE = re.compile(
    r"\b(?:create|make|add|set\s+up|write)\s+(?:a\s+|the\s+|that\s+)?(?:new\s+)?rule\b|\b(?:need|want)s?\s+a\s+(?:new\s+)?rule\b"
)
_REQUEST_ASK_RE = re.compile(
    r"\b(?:e-?mail(?:ed)?\s+(?:me|it\s+to\s+me)|send\s+me|show\s+me|(?:may|might|would|will)\s+need|i\s+need|"
    r"need\s+(?:some\s+)?(?:help|guidance|research)|can\s+you|could\s+you|please|would\s+like)\b"
)
_REQUEST_MEDIUM_RE = re.compile(r"\b(?:youtube|video|videos|clip|tutorial|research|guidance|cue\s+sheet|e-?mail(?:ed)?|link)\b")
_REQUEST_HOW_TO_RE = re.compile(r"\bhow\s+to\b")
_QUESTION_RE = re.compile(
    r"(?<=[a-z])\s*\?|\bnot\s+sure\s+(?:how|if|whether|why|what|which)\b|\bshould\s+(?:i|we)\b|"
    r"\bis\s+(?:this|it)\s+(?:a\s+)?(?:good|better|worse|bad|worth|ok|okay|right)\b"
)


def owner_request_of(note_text: str):
    """The owner's request in one note — `{"subtype", "matched"}` — or None (#5573). Deterministic; no model.

    `matched` is the phrases that decided it, so a reviewer can see why a row was raised without re-running this.
    """
    t = " ".join((note_text or "").lower().split())
    if not t:
        return None
    m = _RULE_REQUEST_RE.search(t)
    if m:
        return {"subtype": "rule_request", "matched": [m.group(0)]}
    ask, medium = _REQUEST_ASK_RE.search(t), _REQUEST_MEDIUM_RE.search(t)
    from training.training_notes import _FORM_RE  # the form_technique words — one list, read at call time (no cycle)

    topic = _FORM_RE.search(t) or _REQUEST_HOW_TO_RE.search(t)
    if ask and medium and topic:
        return {"subtype": "form_guidance", "matched": [ask.group(0), medium.group(0), topic.group(0)]}
    q = _QUESTION_RE.search(t)
    if q:
        return {"subtype": "question", "matched": [q.group(0).strip()]}
    return None
