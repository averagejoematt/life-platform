"""
lambdas/ai/safety_contract.py — the clinical-LITE deterministic safety layer (#3050, DIL-031).

THE GAP THIS CLOSES
───────────────────
`/api/ask` and `/api/board_ask` take free text from anyone on the internet and answer it
with health-adjacent coaching grounded in one man's biometrics. Before this module the
only input filter was `_ask_question_safe` (WR-40) — and that is a **privacy** filter: it
blocks questions that would surface owner-private categories, and its refusal copy says
so ("touches on sensitive personal data that the platform doesn't share publicly").

Nothing looked at whether the *asker* was describing a medical emergency. A reader who
typed "I'm having chest pain, should I still train today?" got a training answer.

This module is that missing layer. It is deliberately **clinical-lite**: a full clinical
operating model — a named clinician, a maintained hazard register, an incident-to-review
path — is a dated priced acceptance (DIL-031 in `docs/PROPORTIONALITY.md`) because there
is no clinician to commission it. What is buildable without one is this: a deterministic
classifier over the *question*, and a fixed escalation response that the platform serves
**instead of** calling a model.

WHY DETERMINISTIC, AND WHY IT SHORT-CIRCUITS THE MODEL
──────────────────────────────────────────────────────
ADR-105 requires deterministic computation before any LLM verdict, and this is the
strongest case for it. Three consequences, all deliberate:

  * **No model call happens on a hazard hit.** The platform cannot hallucinate advice it
    never generated. Contrast the ADR-108 quality gate, which is fail-OPEN by design
    because it governs *voice* — serving slightly-off prose beats serving nothing. Safety
    inverts that: this layer is fail-CLOSED, and a classifier error costs a reader one
    unhelpful-but-safe answer, never an unsafe one.
  * **It costs $0 and cannot be disabled by a budget tier.** A safety layer that stops
    working at tier 3 is not a safety layer.
  * **The response is fixed copy, reviewed once, in source.** Not generated, not
    templated from context, not tunable by prompt injection.

PRECISION OVER RECALL — AND WHAT THAT COSTS
────────────────────────────────────────────
This runs on a *fitness* platform, where "my chest was on fire", "I'm dying after that
set" and "my shoulder is killing me" are ordinary sentences. A broad classifier would
fire on them constantly, and a safety control that cries wolf gets routed around — by
readers, and eventually by whoever maintains it.

So the patterns are narrow on purpose: they require a **first-person present-tense
distress marker** near the hazard term, and every class carries explicit negative
patterns for the exertion idioms above. The honest consequence is stated rather than
hidden — see `WHAT THIS DOES NOT CATCH` at the bottom of this docstring.

FIVE CLASSES
────────────
  SELF_HARM             suicidal ideation / self-harm intent → crisis resources, always
  ACUTE_SYMPTOM         chest pain, breathing difficulty, syncope, stroke signs → emergency care
  DISORDERED_EATING     purging, starvation, compulsive restriction → specialist resources
  MEDICATION            dosing, starting/stopping a prescription → prescriber, never us
  SUPPLEMENT_INTERACTION  stacking against a prescription → pharmacist/prescriber

WHAT THIS DOES NOT CATCH (stated, not glossed)
──────────────────────────────────────────────
  * Anything phrased in the third person or hypothetically ("what would you tell someone
    who…"). Widening to catch it would fire on ordinary coaching questions.
  * Non-English input. The patterns are English-only.
  * Euphemism and understatement, which is how distress is most often actually expressed.
  * Anything in the *model's* output — this gates the INPUT only. Output-side grounding
    is ADR-104's job (`grounded_generation.py`).

It is a floor, not a diagnosis, and it is documented as a floor. `docs/PROPORTIONALITY.md`
carries the DIL-031 row that prices what is deliberately not built above it.
"""

from __future__ import annotations

import re

# ── the hazard classes ───────────────────────────────────────────────────────────

SELF_HARM = "self_harm"
ACUTE_SYMPTOM = "acute_symptom"
DISORDERED_EATING = "disordered_eating"
MEDICATION = "medication"
SUPPLEMENT_INTERACTION = "supplement_interaction"

HAZARD_CLASSES = (SELF_HARM, ACUTE_SYMPTOM, DISORDERED_EATING, MEDICATION, SUPPLEMENT_INTERACTION)

# Ordered most-severe first: a question can match several classes, and the response
# must be driven by the most severe one rather than by dict ordering.
SEVERITY_ORDER = (SELF_HARM, ACUTE_SYMPTOM, DISORDERED_EATING, MEDICATION, SUPPLEMENT_INTERACTION)

# First-person present-tense distress markers. The precision half of the design: a hazard
# term only counts when the asker is describing THEMSELVES, now.
# Bare `i\b` is included deliberately: "I passed out at the gym" and "I haven't eaten in
# three days" carry no modal, and requiring one lost both in the first draft. Precision is
# held instead by the hazard term itself plus the exertion veto — the benign corpus in
# tests/test_safety_contract_3050.py is what keeps that honest.
_FIRST_PERSON = r"(?:i'?m|i am|i'?ve|i have|i feel|i felt|i keep|i can'?t|i haven'?t|i\b|my|me\b)"

# Exertion idioms that must NEVER fire the classifier on a fitness platform. Checked
# before the positive patterns; a match here vetoes that class for the sentence.
_EXERTION_IDIOMS = re.compile(
    r"\b(?:"
    r"killing me|on fire|burn(?:ing|ed)?|sore|doms|dying (?:after|from|on)|dead after|"
    r"pumped|smoked|wrecked|destroyed|gassed|tight after|cramp(?:ing|ed)?|"
    r"lungs? (?:were|are) burning|legs? (?:are|were) dead"
    r")\b",
    re.IGNORECASE,
)

_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    SELF_HARM: (
        re.compile(r"\b(?:kill|killing|hurt|harm(?:ing)?)\s+myself\b", re.IGNORECASE),
        re.compile(r"\b(?:end|ending)\s+(?:it all|my life)\b", re.IGNORECASE),
        re.compile(r"\b(?:want|wanting|going)\s+to\s+die\b", re.IGNORECASE),
        re.compile(r"\bsuicid(?:e|al)\b", re.IGNORECASE),
        re.compile(r"\bself[- ]harm(?:ing)?\b", re.IGNORECASE),
        re.compile(r"\b(?:don'?t|do not|not)\s+(?:want|wanting)\s+to\s+(?:be here|live)\b", re.IGNORECASE),
    ),
    ACUTE_SYMPTOM: (
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bchest (?:pain|pressure|tightness)\b", re.IGNORECASE),
        # Anchored on the DISTRESS MODAL, not on _FIRST_PERSON. The first draft required
        # _FIRST_PERSON + "can't breathe", which lost "I can't breathe properly" (the
        # modal was consumed by _FIRST_PERSON); making the modal optional then flagged
        # "I breathe through my nose during zone 2" and "how should I breathe during heavy
        # squats". Anchoring on the modal fixes both — "can't breathe" is inherently
        # distress regardless of who is speaking, and plain "breathe" never is.
        re.compile(r"\b(?:can'?t|cannot|couldn'?t|struggl\w+ to|hard to|trouble|difficulty)\s+breath(?:e|ing)\b", re.IGNORECASE),
        re.compile(r"\b(?:short(?:ness)? of breath|gasping for (?:air|breath))\b", re.IGNORECASE),
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\b(?:passed out|fainted|blacked out|lost consciousness)\b", re.IGNORECASE),
        re.compile(
            rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\b(?:numb|numbness|weakness)\s+(?:in|on)\s+(?:one|my (?:left|right))\s+side\b", re.IGNORECASE
        ),
        # Both orderings: "slurring my speech" and "my speech is slurring".
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bslurr(?:ed|ing)\s+(?:my\s+)?(?:speech|words)\b", re.IGNORECASE),
        re.compile(r"\b(?:speech|words)\s+(?:is|are|was|were|keeps?)\s+slurr(?:ed|ing)\b", re.IGNORECASE),
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bcoughing up blood\b", re.IGNORECASE),
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bworst headache\b", re.IGNORECASE),
    ),
    DISORDERED_EATING: (
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\b(?:purg(?:e|ing)|vomit(?:ing)?)\s+(?:after|to)\b", re.IGNORECASE),
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bmak(?:e|ing)\s+myself\s+(?:throw up|sick|vomit)\b", re.IGNORECASE),
        re.compile(rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\bstarv(?:e|ing)\s+myself\b", re.IGNORECASE),
        # A not-eaten window only signals when it carries a DURATION. The first draft
        # accepted a bare "anything" and a bare "stopped eating", which flagged
        # "I haven't eaten anything since my last workout" (fasted training) and
        # "I stopped eating processed food" (an ordinary diet change). Both are now
        # in the benign corpus.
        re.compile(
            rf"{_FIRST_PERSON}\b[^.?!]{{0,40}}\b(?:haven'?t|have not|hadn'?t|not)\s+eaten\s+"
            r"(?:in|for)\s+(?:\d+|a|two|three|four|five|several)\s*(?:day|days|week|weeks)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:anorexi|bulimi)[ac]\b", re.IGNORECASE),
        re.compile(r"\bbinge\s+(?:and|then)\s+(?:purge|vomit)\b", re.IGNORECASE),
        # Sub-starvation intake targets asked as a goal, not measured as a fact.
        re.compile(r"\b(?:eat(?:ing)?|drop(?:ping)? to|down to)\s+(?:only\s+)?[2-8]?\d{2}\s*(?:cal|kcal|calories)\b", re.IGNORECASE),
    ),
    MEDICATION: (
        re.compile(r"\b(?:how much|what dose|dosage|how many mg|mg should i)\b[^.?!]{0,40}\b(?:should i|do i|can i)\b", re.IGNORECASE),
        re.compile(
            r"\b(?:should i|can i|is it ok(?:ay)? to)\s+(?:stop|quit|come off|double|increase|decrease|skip)\b[^.?!]{0,30}\b(?:my |the )?(?:med|meds|medication|prescription|pill)",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:stop|quit|come off)\s+(?:taking\s+)?my\s+(?:medication|meds|prescription)\b", re.IGNORECASE),
        re.compile(
            r"\b(?:ozempic|semaglutide|tirzepatide|metformin|statin|ssri|adderall|insulin)\b[^.?!]{0,40}\b(?:dose|dosage|how much|should i)\b",
            re.IGNORECASE,
        ),
    ),
    SUPPLEMENT_INTERACTION: (
        re.compile(
            r"\b(?:interact|interaction|safe to (?:take|stack|combine)|mix)\b[^.?!]{0,40}\b(?:with (?:my )?(?:medication|meds|prescription)|prescription)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\btak(?:e|ing)\b[^.?!]{0,30}\bwith my\s+(?:medication|meds|prescription|blood thinner)\b", re.IGNORECASE),
    ),
}

# The served copy. Fixed in source, reviewed once, never generated and never templated
# from context — so prompt injection cannot reach it and a model cannot soften it.
_SHARED_TAIL = (
    "\n\nThis platform is one person's self-experiment. It is not a clinician, it does not "
    "know your situation, and it will not advise you on this."
)

RESPONSES: dict[str, str] = {
    SELF_HARM: (
        "It sounds like you may be going through something serious, and this is not "
        "something an automated health dashboard should try to answer.\n\n"
        "Please talk to someone now. In the US you can call or text **988** (Suicide & "
        "Crisis Lifeline), 24/7. Outside the US, findahelpline.com lists local services. "
        "If you are in immediate danger, please call your local emergency number."
    ),
    ACUTE_SYMPTOM: (
        "What you are describing needs a real clinician, not a training log.\n\n"
        "If this is happening right now — chest pain or pressure, trouble breathing, "
        "fainting, one-sided weakness or numbness, slurred speech — please call your "
        "local emergency number (911 in the US) or get to urgent care. Do not train, and "
        "do not wait to see if it passes." + _SHARED_TAIL
    ),
    DISORDERED_EATING: (
        "This isn't something I'm going to give you numbers for.\n\n"
        "What you're describing is worth talking through with someone who specializes in "
        "it. In the US, the National Alliance for Eating Disorders helpline is "
        "1-866-662-1235; findahelpline.com lists services elsewhere. If you have a GP or "
        "a dietitian, they are a good first call." + _SHARED_TAIL
    ),
    MEDICATION: (
        "I can't help with medication dosing or with starting, stopping or changing a "
        "prescription — that belongs with the person who prescribed it.\n\n"
        "Your prescriber or pharmacist can answer this properly, and a pharmacist will "
        "usually take the question for free." + _SHARED_TAIL
    ),
    SUPPLEMENT_INTERACTION: (
        "Supplement-with-prescription interactions are a real clinical question and I'm "
        "not equipped to answer it.\n\n"
        "A pharmacist can check an interaction for you quickly and at no cost, and they "
        "will have your full medication list." + _SHARED_TAIL
    ),
}


def classify(text: str) -> frozenset[str]:
    """Hazard classes the text matches. Deterministic, English-only, precision-weighted.

    Exertion idioms ("my shoulder is killing me", "my lungs were burning") veto the
    ACUTE_SYMPTOM class for that text — on a fitness platform those are ordinary
    sentences, and a control that fires on them gets routed around. SELF_HARM is
    deliberately NOT vetoed: "killing myself" is matched by its own pattern, and the cost
    of a false positive there is one unnecessary crisis-resource message, which is the
    right side to err on.
    """
    if not text:
        return frozenset()

    idiomatic = bool(_EXERTION_IDIOMS.search(text))
    hits = set()
    for hazard, patterns in _PATTERNS.items():
        if idiomatic and hazard == ACUTE_SYMPTOM:
            continue
        if any(p.search(text) for p in patterns):
            hits.add(hazard)
    return frozenset(hits)


def most_severe(hazards: frozenset[str]) -> str | None:
    """The class that drives the response. Never relies on set/dict iteration order."""
    for hazard in SEVERITY_ORDER:
        if hazard in hazards:
            return hazard
    return None


def check(question: str) -> tuple[bool, str, str | None]:
    """The single entry point for a request handler.

    Returns ``(safe, response, hazard)``:
      * ``(True, "", None)``  — no hazard; the caller proceeds to the model as normal.
      * ``(False, copy, cls)`` — a hazard; the caller serves ``copy`` and **must not**
        call the model. That short-circuit is the point: the platform cannot hallucinate
        advice it never generated.

    Fail-closed by construction — the only way to get ``True`` is for every pattern to
    miss. There is no exception path that yields a safe verdict, because there is nothing
    here that can raise: no I/O, no imports at call time, no network, no model.
    """
    hazards = classify(question or "")
    hazard = most_severe(hazards)
    if hazard is None:
        return True, "", None
    return False, RESPONSES[hazard], hazard
