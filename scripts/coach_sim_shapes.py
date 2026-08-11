#!/usr/bin/env python3
"""
coach_sim_shapes.py — the SHAPE metrics for a coach sim run (#2536).

Split out of ``coach_sim_analyze`` when that module crossed the 1,200-line ceiling.
The seam is a real one rather than a line-count convenience: everything here answers
one question — *what shape is this reply, and do eight personas share it* — and
answers it with no model, no network, and no dependency on the rest of the analyzer.
The metrics next door measure a reply against itself (length, em-dashes, balanced
clauses); these measure replies against EACH OTHER.

Why the module exists at all. Shingle-Jaccard between two coaches answering the same
message ran under 0.06 — which reads as healthy voice separation — while six of eight
produced the same three moves in different vocabularies: a demonstrative
acknowledgement, his own phrase quoted back, a menu question. A similarity metric
built on shared WORDS cannot see shared SHAPE, and the failure it misses is the one
that makes a roster of eight read as one model wearing name tags.

  structural_signature            one reply -> a coarse shape string
  structural_collapse             per archetype: how many distinct shapes of eight
  opening_construction_collisions the 3-word opening stem, shared across coaches
  absence_phrasing_collisions     how the roster says "I don't have that"
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

# Sentence splitting on terminal punctuation only. ``_SENTENCE_OR_BUBBLE`` below adds
# the bubble break, which this surface needs and prose does not.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


_MENU_QUESTION = re.compile(r"\?[\s\"']*$")
# The menu question — "the tracking, the whole project, or something else?" — is the
# template's signature move. The span between the first comma and the "or" routinely
# contains further commas, so it must not be excluded from the middle class.
_OR_LIST = re.compile(r",[^?]{2,80}\bor\b[^?]{2,40}\?")

# A leading discourse particle ("Yeah.", "Ha.", "Fair.") is punctuation with a
# vocabulary — it carries no move. It used to be classified as its own opening class,
# which meant a coach could bolt "Yeah." onto the front of the template and register as
# a DIFFERENT shape from a coach running the identical template without it. Measured
# 2026-08-10 on venting_no_question: two of the eight "distinct" shapes differed from
# another coach's by exactly that one word. The particle is stripped before the opening
# move is read, so it can no longer manufacture distinctness.
# A bubble break IS a sentence break on this surface. ``_SENTENCE_SPLIT`` only breaks
# after . ! ?, and a coach who fires two bubbles without terminal punctuation —
# "rough ones have a way of landing on day 1" / "eaten anything yet?" — reads as ONE
# sentence that happens to end in a question mark, so its opening move fingerprints as
# a question when the first thing he actually sent was a statement. Measured: 2 of 8
# off_lane openers were misread this way.
_SENTENCE_OR_BUBBLE = re.compile(r"(?<=[.!?])\s+|\n+")
_DISCOURSE_PARTICLE = re.compile(
    r"^(?:yeah|yep|yup|ok|okay|ha+h?|oh|ah|fair|right|hm+|mm+|sure|ugh|well|honestly|god)\b[\s,.!?…—–-]*", re.I
)
_GREETING_OPEN = re.compile(r"^(?:hey|hi|hello|morning|evening|afternoon)\b", re.I)
# Elided first person — "Don't have that.", "No idea." — is a statement about what the
# COACH has, not an imperative. Reading it as a directive puts every honest-absence
# opener in the wrong class, which is the class this issue is measuring.
_ELIDED_SELF = re.compile(
    r"^(?:no idea\b|not sure\b|(?:don'?t|can'?t|couldn'?t|won'?t|haven'?t|didn'?t|doesn'?t)\s+(?:have|know|see|think|remember|get|track|recall)\b)",
    re.I,
)
_SELF_OPEN = re.compile(r"^(?:i|i'?m|i'?d|i'?ve|i'?ll|my|me)\b", re.I)
_HIS_STATE_OPEN = re.compile(r"^(?:that|this|it|there|those|these|you|you'?re|you'?ve|your|sounds like)\b", re.I)
_DIRECTIVE_OPEN = re.compile(
    r"^(?:skip|take|go|leave|stop|drop|eat|sleep|rest|call|keep|put|let|give|forget|don'?t|do|try|hold|park|text|ask|check)\b", re.I
)


def _opening_move(first_sentence: str) -> str:
    """Which of five moves the reply OPENS with — who the first clause is about.

    The axis this replaced read grammatical FORM: "does the reply start with a
    demonstrative pronoun". That works exactly until the demonstrative is banned, at
    which point every reply falls into one residual OPEN_STATEMENT bucket and the
    fingerprint stops discriminating precisely on the corpus it was built for. The
    axis is about STANCE instead — the thing that actually differs between Lisa Park
    sitting with it, Steve Brooks naming the load, and Nora Vale declining to
    interpret — and it is checked in a fixed order because the classes overlap.
    """
    s = (first_sentence or "").strip()
    if not s:
        return "OPEN_PARTICLE"
    if _GREETING_OPEN.match(s):
        return "OPEN_GREETING"
    if s.endswith("?"):
        return "OPEN_QUESTION"
    if _ELIDED_SELF.match(s) or _SELF_OPEN.match(s):
        return "OPEN_SELF"  # what the coach has / thinks / will do
    if _HIS_STATE_OPEN.match(s):
        return "ACK_HIS_STATE"  # the template's move 1 — naming his state back at him
    if _DIRECTIVE_OPEN.match(s):
        return "OPEN_DIRECTIVE"  # a call, delivered as an instruction
    return "OPEN_FACT"  # a third-person statement about the data, the week, the world


def structural_signature(reply: str, inbound: str) -> str:
    """A compact shape-of-the-reply fingerprint, content words removed.

    Shingle-Jaccard measures shared WORDS, and it badly understates the failure this
    exists to catch: eight coaches answering "honestly I'm just tired of all of this"
    with the same two-move template — a demonstrative acknowledgement ("That lands.")
    followed by a menu question echoing his phrase back ("What's the 'all of this' —
    the tracking, the project, or something else?"). Synonym choice keeps the Jaccard
    near zero while the STRUCTURE is identical, which is exactly what makes a roster
    of eight read as one model wearing name tags.

    The signature is deliberately coarse. It is not trying to describe the reply; it
    is trying to make two replies that would feel interchangeable to a reader hash to
    the same string, so "how many distinct shapes did eight personas produce" becomes
    a countable number.

    THREE AXES, and the space got SMALLER when they were revised (#2536): 4 opening
    classes x 2 echo x 3 close x 3 sentence-count buckets = 72 cells before, 7 x 2 x 3
    = 42 now. That direction is deliberate. A fingerprint that gains cells can report
    "more distinct shapes" for a change that did nothing, so the sentence-count bucket
    — a LENGTH proxy, already measured exactly by ``reply_metrics``, and the axis on
    which a one-word "Yeah." bubble split a cluster in two — came out in the same pass
    that gave the opening move its three extra stance classes.
    """
    r = (reply or "").strip()
    if not r:
        return "EMPTY"
    body = _DISCOURSE_PARTICLE.sub("", r).strip() or r
    first = next((x for x in _SENTENCE_OR_BUBBLE.split(body) if x.strip()), "").strip()
    parts = [_opening_move(first)]

    # Does it quote his own words back at him? The tell of the template, not of care.
    # The opening quote must be at a word boundary: an unanchored character class
    # matches the apostrophe inside "What's" first and captures the wrong span, which
    # silently zeroed this signal on exactly the replies it exists to catch.
    echo = False
    for token in re.findall(r"(?:(?<=\s)|^)[\"“‘']([^\"”’']{4,40})[\"”’']", r):
        if token.lower() in (inbound or "").lower():
            echo = True
    parts.append("ECHO_QUOTE" if echo else "NO_ECHO")

    if _OR_LIST.search(r):
        parts.append("MENU_QUESTION")
    elif _MENU_QUESTION.search(r):
        parts.append("CLOSING_QUESTION")
    else:
        parts.append("CLOSES_STATEMENT")
    return "|".join(parts)


def structural_collapse(convos: list) -> list:
    """Per archetype: how many DISTINCT reply shapes did the eight personas produce?

    Eight distinct signatures means eight voices. One or two means the personas are
    decoration on a single template, and the fix belongs in the engine (or in what
    the voice specs are asked to differentiate), not in one coach's config.

    ``dominant_coaches`` names the cluster. The count alone says a template is running;
    it does not say whose specs to open, and a metric that reports a problem without
    reporting where it lives gets read once and then ignored.
    """
    by_arch = defaultdict(dict)
    for c in convos:
        turns = c.get("turns") or []
        if turns:
            by_arch[c["archetype"]][c["coach"]] = structural_signature(turns[0]["reply"], turns[0]["inbound"])

    rows = []
    for arch, by_coach in by_arch.items():
        if len(by_coach) < 4:  # a per-coach domain scenario has nothing to compare against
            continue
        sigs = Counter(by_coach.values())
        top_sig, top_n = sigs.most_common(1)[0]
        rows.append(
            {
                "archetype": arch,
                "coaches": len(by_coach),
                "distinct_shapes": len(sigs),
                "largest_cluster": top_n,
                "dominant_shape": top_sig,
                "dominant_coaches": sorted(c for c, s in by_coach.items() if s == top_sig),
                "collapse_ratio": round(top_n / len(by_coach), 2),
            }
        )
    return sorted(rows, key=lambda r: -r["collapse_ratio"])


# The absence cues an honest coach reaches for. Deliberately a cue list rather than a
# phrase blacklist: what is being measured is not WHETHER a coach admits it has no
# data (it must — ADR-104) but whether eight of them admit it in the same words.
_ABSENCE_CUE = re.compile(
    r"(i (?:don'?t|do not) (?:have|know|track)|don'?t have|no idea|not tracked|don'?t track|no data|nothing (?:on|in|that far)|"
    r"let me check|can'?t (?:see|pull|tell)|isn'?t (?:something|in) )",
    re.I,
)


def _stem(text: str, n: int) -> str:
    """First n words, lowercased, stripped of punctuation, leading particle removed."""
    body = _DISCOURSE_PARTICLE.sub("", (text or "").strip()).strip() or (text or "").strip()
    words = [w.strip("\"“”‘’'.,;:!?—–-…()") for w in body.lower().split()]
    return " ".join([w for w in words if w][:n])


def _collisions(stems_by_coach: dict, min_coaches: int) -> list:
    rows = [
        {"stem": stem, "coaches": sorted(coaches), "n_coaches": len(coaches), "uses": uses}
        for stem, (coaches, uses) in stems_by_coach.items()
        if len(coaches) >= min_coaches and stem
    ]
    return sorted(rows, key=lambda r: (-r["n_coaches"], -r["uses"]))


def opening_construction_collisions(convos: list, stem_words: int = 3, min_coaches: int = 3) -> list:
    """Opening CONSTRUCTIONS shared across coaches — the three-word stem, not the phrase.

    ``opener_collisions`` keys on the first FOUR words, which is one word too many to
    see this failure: "that kind of tired", "that kind of monday" and "that kind of
    day" are three different keys and one construction. Measured on the same corpus,
    the four-word key reported 3 coaches and the three-word stem reported 6 — and 6 is
    the number in the finding this metric exists to close.
    """
    stems: dict = defaultdict(lambda: (set(), 0))
    for c in convos:
        turns = c.get("turns") or []
        if not turns:
            continue
        stem = _stem(turns[0]["reply"], stem_words)
        coaches, uses = stems[stem]
        coaches.add(c["coach"])
        stems[stem] = (coaches, uses + 1)
    return _collisions(stems, min_coaches)


def absence_phrasing_collisions(convos: list, stem_words: int = 3, min_coaches: int = 3) -> list:
    """How the roster says "I don't have that" — one stem per absence sentence.

    Honest absence is REQUIRED (ADR-104) and is not the defect; sounding like one
    person doing it is. Every sentence carrying an absence cue contributes the stem it
    opens with, across every turn rather than the first — a refusal is usually the
    answer to his second or third message, so a first-turn-only measure cannot see it.
    """
    stems: dict = defaultdict(lambda: (set(), 0))
    for c in convos:
        for t in c.get("turns") or []:
            for sentence in _SENTENCE_OR_BUBBLE.split(t.get("reply") or ""):
                if _ABSENCE_CUE.search(sentence):
                    stem = _stem(sentence, stem_words)
                    coaches, uses = stems[stem]
                    coaches.add(c["coach"])
                    stems[stem] = (coaches, uses + 1)
    return _collisions(stems, min_coaches)
