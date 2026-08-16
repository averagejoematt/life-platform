"""coach_style_gate.py — the deterministic style ceiling on a coach's text (#2535).

WHY THIS IS A GATE AND NOT A PROMPT RULE. Both of the habits below were already
banned in the prompt, and both survived. #2481 wrote "No assistant-isms ('Honest
answer:', 'Great question')" into the CONVERSATION RULES; the 2026-08-10 simulation
sweep then measured **23 uses of "Honest answer" in 536 replies** — 23 of the 27 total
assistant-ism hits in the corpus. The em-dash is worse: **77% of replies carried one**,
and the voice spec made no measurable difference — the one coach whose spec sanctions
em-dashes ran 80%, the coach told "Complete sentences, periods" ran 78%, and the
lowest of eight was still 66%. An instruction that produces no separation between the
coach it permits and the coach it forbids is not an instruction, it is decoration.

This module is the same answer ``coach_chat.enforce_emoji_policy`` already gives for
emoji, and it is stated in that function's own docstring: *the prompt shapes the habit,
this guarantees the ceiling*. Deterministic computation before any model verdict
(ADR-105).

THE EM-DASH THRESHOLD IS MEASURED, NOT CHOSEN. The corpus distribution:

    0 em-dashes  123 replies (22%)
    1            339        (63%)
    2             62        (11%)
    3+            12         (2%)

That distribution rules out the obvious design. A per-reply cap of one would touch
only the 14% with two or more and leave the headline rate at 77%, because the mass is
at *exactly one*. So the ceiling has to work across replies, not inside them — hence
the alternation rule, which is the one already proven on this surface for emoji: at
most one per reply, and none at all if the previous reply had one. That bounds the
long-run rate at ~50% and, on the measured distribution, lands nearer 40%.

WHAT IT DELIBERATELY DOES NOT DO. It does not strip every em-dash. Judges cited
punctuation in 7% of tells against 25% for rhetorical symmetry (#2534) — em-dash
frequency is a real but secondary signal, and stripping it to zero would damage
legitimate prose to over-fit a minor tell. One coach's spec sanctions the character
for a stated purpose; that use survives, it just stops being every coach's reflex.

ORDERING. This runs INSIDE the same window as the emoji policy — after the bubble
split, before the grounding gate — because the gate must adjudicate exactly the text
that will be sent. A formatter that touches a reply after it has been gated invents a
new defect behind the gate's back, which is the ordering invariant ``run_turn``
already documents.

SAFETY. Every transform here is punctuation-only and must never alter a number, a
date, or a word. The grounding gate runs immediately after and would catch a mangled
number, but relying on that would be backwards: this module's contract is that its
output differs from its input only in punctuation and whitespace.
"""

from __future__ import annotations

import re

# At most one em-dash per reply, and none when the previous reply had one. Mirrors
# the emoji ceiling exactly — same shape, same rationale, same alternation.
MAX_EM_DASHES = 1

_EM_DASH = "—"

# Assistant-isms banned by #2481 that a deterministic pass can remove without
# rewriting the sentence. Each pattern matches ONLY at a clause opening — sentence
# start, bubble start, or just after a comma — because the same words can be a
# legitimate noun phrase mid-sentence ("that's worth a quick honest answer from you",
# measured in the corpus, must survive untouched). A gate that mangles honest prose to
# catch a stock phrase has made the reply worse, not better.
_CLAUSE_START = r"(?:(?<=\A)|(?<=\n)|(?<=[.!?]\s)|(?<=[.!?]\s\s)|(?<=,\s))"

_BANNED_OPENERS = [
    # "Honest answer: X" / "Honest answer is X" / "The honest answer is that X" /
    # "Honestly the honest answer is X" / "Honest answer, X"
    #
    # The separator set is exhaustive against the measured corpus and deliberately
    # STOPS THERE. "Honest answer to that depends on…", "that's the honest answer for
    # almost everything", "is the honest answer that you need a break" are all real
    # replies where the phrase is the grammatical subject or object — removing it
    # would leave a broken sentence, which is a worse defect than the tic. Those are
    # left alone on purpose; see the issue comment for why zero hits is not a safe
    # target for a deterministic pass.
    re.compile(_CLAUSE_START + r"(?:Honestly,?\s+)?(?:The\s+)?honest answer(?:\s+is(?:\s+that)?|[:,])\s*", re.I),
    # "Great question" / "Good question" — with or without trailing punctuation.
    re.compile(_CLAUSE_START + r"(?:That's a\s+)?(?:great|good)\s+question[.!,]?\s*", re.I),
    # "To be honest," / "To be fair," as a hedge opener.
    re.compile(_CLAUSE_START + r"To be (?:honest|fair),\s*", re.I),
    # #2492 — the ceremonial-acknowledgment class on being corrected. The prompt
    # already bans thanking him for a correction (#2534); this makes it hold. Same
    # precision-first discipline as above: each pattern requires the phrase to be a
    # complete ceremonial clause (terminal punctuation, dash, or clause end) so
    # legitimate gratitude mid-sentence ("thanks for the coffee rec") and load-bearing
    # grammar ("you're right that duration matters" — stripping would orphan the
    # complement) survive untouched.
    re.compile(_CLAUSE_START + r"Thank(?:s| you) for (?:the|that|this) correction(?:[.!,]|\s*—)\s*", re.I),
    re.compile(_CLAUSE_START + r"Thank(?:s| you) for correcting me(?:[.!,]|\s*—)\s*", re.I),
    re.compile(_CLAUSE_START + r"I appreciate (?:the|that|your) correction(?:[.!,]|\s*—)\s*", re.I),
    re.compile(_CLAUSE_START + r"Thank(?:s| you) for (?:pointing (?:that|this) out|flagging (?:that|this))(?:[.!,]|\s*—)\s*", re.I),
    re.compile(_CLAUSE_START + r"You'?re absolutely right(?:[.!]|\s*—)\s*", re.I),
]


def _recapitalize(text: str) -> str:
    """Re-capitalize a clause whose opening words were removed.

    Stripping "Honest answer: " from "Honest answer: it's close" leaves "it's close"
    starting a sentence in lowercase. Only the FIRST character of the string and of
    each sentence that now begins lowercase is touched, and only when it is an ASCII
    letter — never a number, so a reply that now opens on a figure is left exactly as
    the model wrote it.
    """

    def _upper_at(m: re.Match) -> str:
        return m.group(0)[:-1] + m.group(0)[-1].upper()

    if text and text[0].islower() and text[0].isalpha():
        text = text[0].upper() + text[1:]
    return re.sub(r"(?:(?<=[.!?]\s)|(?<=[.!?]\s\s))[a-z]", _upper_at, text)


# An opener can be followed by a separator that only made sense as its punctuation:
# "Good question — the answer is duration" strips to "— the answer is duration", which
# is a worse artefact than the phrase it removed. Absorb the orphan.
_ORPHAN_LEAD = re.compile(r"^\s*[—:;,\-]+\s*")


def strip_banned_openers(text: str) -> str:
    """Remove the prompt-banned hedge openers, then repair the capitalisation."""
    out = text or ""
    for rx in _BANNED_OPENERS:
        out = rx.sub("", out)
    if out == (text or ""):
        return out
    out = _ORPHAN_LEAD.sub("", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return _recapitalize(out)


def demote_em_dashes(text: str, allowance: int) -> tuple:
    """Convert em-dashes beyond ``allowance`` to commas. Returns (text, used).

    A comma rather than a period: a period needs the next word capitalised and can
    turn an appositive into a fragment ("duration is only one input. Which is why…"),
    while a comma preserves the clause relationship the em-dash was carrying. The
    result is occasionally a comma splice — which is exactly how people text, and a
    great deal less machine-like than the dash it replaces.

    The FIRST ``allowance`` dashes are kept, so a reply that legitimately uses one for
    a labelled interpretation keeps it; the reflexive extras are what go.
    """
    if not text or _EM_DASH not in text:
        return text, 0

    kept = 0
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != _EM_DASH:
            out.append(ch)
            i += 1
            continue
        if kept < allowance:
            kept += 1
            out.append(ch)
            i += 1
            continue
        # Replace " — " (or "—") with ", ", absorbing the surrounding spaces so the
        # result has exactly one space after the comma.
        while out and out[-1] in " \t":
            out.pop()
        j = i + 1
        while j < len(text) and text[j] in " \t":
            j += 1
        # Never produce ",," or " ," — if the clause already ended in a comma or a
        # sentence terminator, the dash simply disappears.
        if out and out[-1] in ",;:.!?":
            out.append(" ")
        else:
            out.append(", ")
        i = j
    return "".join(out), kept


def enforce_style(bubbles: list, last_reply_had_em_dash: bool = False) -> list:
    """The deterministic style ceiling over one reply's bubbles.

    ``last_reply_had_em_dash`` implements the alternation that the measured
    distribution requires: with 63% of replies carrying exactly one em-dash, a
    per-reply cap alone cannot move the headline rate, so a reply following one that
    used its allowance gets none.

    Punctuation and whitespace only — no word, number or date is altered.
    """
    bubbles = [b for b in (bubbles or [])]
    if not bubbles:
        return bubbles

    cleaned = [strip_banned_openers(b) for b in bubbles]
    # A bubble emptied by the strip (it was nothing but the stock phrase) is dropped
    # rather than sent blank; if that empties everything, the original stands, because
    # sending nothing is a worse failure than sending a banned phrase.
    cleaned = [c for c in cleaned if c.strip()] or bubbles

    allowance = 0 if last_reply_had_em_dash else MAX_EM_DASHES
    out = []
    for b in cleaned:
        text, used = demote_em_dashes(b, allowance)
        allowance -= used  # the ceiling is per REPLY, not per bubble
        out.append(text)
    return out


def has_em_dash(text: str) -> bool:
    return _EM_DASH in (text or "")
