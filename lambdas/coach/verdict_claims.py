"""verdict_claims.py — does a text call a prediction right, wrong or checked against its CURRENT grade? (owner ruling 2026-11-03)

THE RULING (verbatim, 2026-11-03): "Corrected authoritative grades must flow into coach-facing summaries and
future narratives. A coach must not continue claiming a prediction was wrong, right or measurable after its
authoritative classification has changed. … Do not let generated narratives invent explanations for a correction."

THE DEFECT IT CLOSES. The mind coach's read of 2 November said its protein → journaling call "was wrong" — true of
the grade it was shown that morning (refuted). On 3 November the owner re-classified the call as could-not-be-checked
(rule #5611:m). The stored read kept saying "the mechanism was wrong" on /api/coaching-dashboard, because nothing
compared a stored or freshly generated text with the call's current grade.

WHAT THIS MODULE IS. Pure (no boto3, no clock, no network) so the writer (``coach_state_updater``), the read sites
(``web``), the publication snapshot (``scripts/publish_snapshot_corrections.py``) and the agreement check
(``scripts/check_coach_verdict_agreement.py``) share ONE rule:

* ``assertions(text)`` — each sentence that asserts a verdict about a call (``wrong`` / ``right`` / ``checked``),
  with the window of sentences around it that names the call;
* ``findings(text, calls)`` — each assertion matched to the calls it can be about (claims sharing at least two content
  words with the window; a negatively framed claim is never a candidate), and kept only when it CONTRADICTS the
  authoritative status of EVERY such call:
  ``confirmed`` + "wrong", ``refuted`` + "right", or any verdict at all about a call that is not decided
  (``expired`` / ``inconclusive`` / ``observational`` / ``pending``: "could not be checked", "not graded", "open").

The matcher is lexical, deliberately conservative in the SAFE direction: a finding withholds a text (or falls it back
to a deterministic, records-built summary); it never rewrites one. When any call the text plausibly names agrees with
it, it is not a finding — a public correction note beside a quotation that was in fact right is the worse error.
"""

from __future__ import annotations

import re
from typing import Iterable

#: The ledger's one call-outcome vocabulary (www/src/lib/format.js CALL_OUTCOME, scripts/publish_snapshot CALL_OUTCOME).
OUTCOME_WORDS = {
    "confirmed": "right",
    "refuted": "wrong",
    "expired": "could not be checked",
    "inconclusive": "inconclusive",
    "pending": "open",
    "observation": "not graded",
    "observational": "not graded",
    "under_review": "disputed — under classification review",
}

#: The only statuses a text may describe as right or wrong.
DECIDED = ("confirmed", "refuted")

#: The subject of a verdict: the coach itself ("I was wrong") or a call-noun phrase ("the mechanism", "my read that …",
#: "Matthew's protein-primacy prediction"). "Marcus Webb is right that …" (a colleague's point) is not a call's verdict.
_SUBJ = (
    r"(?:\bI\b|\b(?:my|the|that|this|his|her|their|our|an?|[A-Z][a-z]+['’]s)\s+(?:[\w-]+\s+){0,3}?"
    r"(?:call|calls|prediction|predictions|read|theory|mechanism|bet|guess|hypothesis|idea|model|forecast|expectation|story|link)\b)"
)
_GAP = r"(?:[\w'’,-]+\s+){0,10}?"
_BE = r"(?:was|were|is|am|are|turned out(?: to be)?|proved|has been|have been|got (?:it|that|this))\s+(?:\w+\s+){0,2}?"
_WRONG = re.compile(
    rf"{_SUBJ}\s+{_GAP}(?:{_BE}(?:wrong|incorrect|mistaken|refuted|disproved|disproven|false)\b"
    r"|(?:didn['’]?t|did not|doesn['’]?t|does not|hasn['’]?t|has not|won['’]?t)\s+(?:hold|held|pan out|panned out|bear out|survive)\b)",
    re.IGNORECASE,
)
_RIGHT = re.compile(
    rf"{_SUBJ}\s+{_GAP}(?:{_BE}(?:right|correct|confirmed|vindicated|borne out)\b|(?:held up|came true|panned out|has held|held)\b)",
    re.IGNORECASE,
)
_CHECKED = re.compile(
    r"\b(?:the data|the numbers|the record)\s+(?:showed|proved|settled|answered)\s+(?:it|that|the call|the question)\b"
    r"|\b(?:the call|my call|the prediction|my prediction|that call|that prediction|the bet|my bet)\s+(?:was|has been)\s+(?:settled|tested|measured)\b",
    re.IGNORECASE,
)
#: A negated verdict ("I haven't been wrong yet") and a tally ("right 4 times", "two confirmed calls") assert no call's verdict.
_NEGATED = re.compile(r"(?:n['’]t|\bnot|\bnever)\s+(?:been\s+|yet\s+|always\s+)?(?:wrong|right|correct|incorrect)\b", re.IGNORECASE)
_TALLY = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|zero)\s+(?:times|of\s+(?:my|the|his)\s+\w+|confirmed|refuted|calls|predictions|out of)\b",
    re.IGNORECASE,
)
#: A window must speak of a CALL (a prediction, a bet, an idea the coach held) — not just of a reading.
_CALL_CUE = re.compile(
    r"\b(?:predict\w*|forecast\w*|call|calls|bet|bets|expect\w*|thought|think|believed|hypothes\w*|theory|idea|mechanism|"
    r"guess\w*|said|claimed|wager\w*|read)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+|\n{2,}")
_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(
    "that this with from into than then more less over under about after before around toward towards would will could "
    "should might must shall have been being were they them their there here what when where which while your yours "
    "mine just also only even still very much many some each every both such same other another again once since "
    "until within without across tomorrow today yesterday night nights week weeks days daily matthew coach would "
    "continue continues continued keep keeps kept stay stays remain remains likely around approximately roughly level "
    "levels score scores trend trends rate rates number numbers data reading readings value values target point "
    # the words OF a verdict or a call are not what a call is ABOUT — they never tie a sentence to a call
    "prediction predictions predicted predict predicts call calls called confirmed refuted wrong right correct "
    "incorrect expected expect expects thought think believed theory hypothesis idea mechanism read reads "
    "subject quarter month months year clean sheet graded grade grades miss missed hold held".split()
)

#: Lookbehind/lookahead (in sentences) for the call a verdict sentence is about.
BEFORE, AFTER = 2, 2
#: A text speaks of calls made in the LOOKBACK_DAYS before it (a call is referenced while it is fresh).
LOOKBACK_DAYS = 60
#: The fewest shared content words that tie a window to a call.
MIN_OVERLAP = 2


def outcome_words(status: str | None) -> str:
    return OUTCOME_WORDS.get(str(status or ""), str(status or "unknown"))


def _stem(word: str) -> str:
    return word[:5]


def stems(text: str) -> set[str]:
    """Content-word stems: lower-cased words of 4+ letters, stop words out, the first five letters kept."""
    return {_stem(w) for w in _WORD.findall(str(text or "").lower()) if len(w) >= 4 and w not in _STOP}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(str(text or "")) if s and s.strip()]


def polarity(sentence: str) -> str | None:
    """``wrong`` / ``right`` / ``checked`` — the verdict a sentence asserts — or None."""
    if _TALLY.search(sentence) or _NEGATED.search(sentence):
        return None
    if _WRONG.search(sentence):
        return "wrong"
    if _RIGHT.search(sentence):
        return "right"
    if _CHECKED.search(sentence):
        return "checked"
    return None


def assertions(text: str) -> list[dict]:
    """Every verdict-asserting sentence whose window speaks of a call: ``{sentence, polarity, window}``."""
    ss = sentences(text)
    out = []
    for i, s in enumerate(ss):
        p = polarity(s)
        if not p:
            continue
        window = " ".join(ss[max(0, i - BEFORE) : i + AFTER + 1])
        if not _CALL_CUE.search(window):
            continue
        out.append({"sentence": s, "polarity": p, "window": window})
    return out


def contradicts(polarity_: str, status: str | None) -> bool:
    """Does asserting ``polarity_`` about a call contradict its authoritative ``status``?"""
    st = str(status or "")
    if st == "confirmed":
        return polarity_ == "wrong"
    if st == "refuted":
        return polarity_ == "right"
    return True  # not decided: neither right, wrong, nor "checked"


#: A claim framed as a negation or a contrast ("the barrier is not metabolic", "X rather than Y") inverts the meaning of a
#: verdict about it ("the metabolic theory didn't hold" AGREES with it), which a lexical matcher cannot see — so such a
#: claim is never a match candidate (triage of the 2026-11-03 live findings: every docket-position false positive).
_NEGATIVE_CLAIM = re.compile(
    r"\b(?:not|never|no longer|rather than|instead of|isn['’]t|aren['’]t|wasn['’]t|doesn['’]t|don['’]t|won['’]t)\b", re.IGNORECASE
)


def _scored(window: str, calls: Iterable[dict]) -> list[tuple[int, dict]]:
    """Every call sharing at least ``MIN_OVERLAP`` content words with the window, most shared first."""
    w = stems(window)
    scored = []
    for c in calls:
        n = len(w & stems(c.get("claim") or ""))
        if n >= MIN_OVERLAP:
            scored.append((n, c))
    return sorted(scored, key=lambda x: -x[0])


def _in_reach(call: dict, as_of: str | None) -> bool:
    said = str(call.get("said_on") or "")[:10]
    if not as_of or len(said) != 10:
        return True
    from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741/#3609)

    a, b = parse_day_key(str(as_of)[:10]), parse_day_key(said)
    if a is None or b is None:
        return True
    return 0 <= (a - b).days <= LOOKBACK_DAYS


def findings(text: str, calls: Iterable[dict], *, as_of: str | None = None) -> list[dict]:
    """The assertions in ``text`` that contradict the CURRENT status of the call they are about.

    ``calls`` = ``[{prediction_id, claim, status, said_on?}]`` with ``status`` the authoritative (post-correction) one.
    ``as_of`` (the text's own day) limits the candidates to calls said in the ``LOOKBACK_DAYS`` before it.
    Each finding: ``{prediction_id, sentence, asserted, status, status_words}``.
    """
    calls = [
        c
        for c in calls or []
        if isinstance(c, dict) and str(c.get("claim") or "").strip() and _in_reach(c, as_of) and not _NEGATIVE_CLAIM.search(str(c["claim"]))
    ]
    out = []
    for a in assertions(text):
        scored = _scored(a["window"], calls)
        if not scored:
            continue
        if any(not contradicts(a["polarity"], c.get("status")) for _, c in scored):
            continue  # some call it plausibly names agrees with it: never flag (a false correction is worse than none)
        c = scored[0][1]
        out.append(
            {
                "prediction_id": c.get("prediction_id"),
                "sentence": a["sentence"],
                "asserted": a["polarity"],
                "status": c.get("status"),
                "status_words": outcome_words(c.get("status")),
            }
        )
    return out


#: The prompt contract: what every generation that is shown a corrected call is told (the validator enforces it).
PROMPT_CONTRACT = (
    "GRADE CORRECTIONS (owner ruling, 3 November 2026): each call's grade below is its CURRENT, authoritative grade. "
    "Describe a call as right only if its grade is confirmed, as wrong only if its grade is refuted. A call whose grade "
    "is expired (could not be checked), inconclusive, an observation (not graded) or still open must not be described "
    "as right, wrong, proved, missed or measured — not even as your own admission. If a call's grade was corrected, you "
    "may mention the correction only as recorded: its date and the recorded reason given here, word for word. Never "
    "explain why a correction happened beyond that recorded reason, and never speculate about it."
)


def correction_lines(notes: Iterable[dict]) -> list[str]:
    """One deterministic line per corrected call for a prompt: date, original → current grade, recorded reason."""
    out = []
    for n in notes or []:
        day = str(n.get("corrected_at") or "")[:10] or "date not recorded"
        reason = str(n.get("explanation") or "").strip() or "no recorded reason"
        claim = str(n.get("claim") or "").strip()
        out.append(
            f"- {day}: the call {('“' + claim[:140] + '”') if claim else n.get('prediction_id')} was re-graded from "
            f"{n.get('original_status')} ({outcome_words(n.get('original_status'))}) to {n.get('current_status')} "
            f"({outcome_words(n.get('current_status'))}). Recorded reason: {reason}"
        )
    return out
