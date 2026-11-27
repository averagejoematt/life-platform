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
    #6303 added four SELF_HARM families for both doors (inability to stay safe; better off
    without me / a burden; wishing not to wake up, not to exist, to be dead; overdose intent),
    each anchored on a self-referential object or an end-of-clause so training talk does not
    fire. What still misses, pinned in tests/test_owner_channel_safety_6303.py: statements with
    no self-harm object at all — "what's the point of any of this anymore" (deliberately NOT
    matched alone: far more often ordinary frustration than crisis), "I can't do this anymore",
    "I just want it all to stop", "I don't see a way forward", "everything feels pointless".
    Known accepted false positives: "keep me safe from myself" said as a joke, and "be here" or
    "live" followed by a time word ("I don't want to be here tonight, the bar is too loud"),
    because the same words are how a crisis is said.
  * Anything in the *model's* output — this gates the INPUT only. Output-side grounding
    is ADR-104's job (`grounded_generation.py`).

It is a floor, not a diagnosis, and it is documented as a floor. `docs/PROPORTIONALITY.md`
carries the DIL-031 row that prices what is deliberately not built above it.

THE OWNER CHANNEL (#6303) — the same classifier, a different policy
──────────────────────────────────────────────────────────────────
Everything above is the PUBLIC door: anonymous readers, every class answered with fixed
copy, fail-closed. The owner's own channel (his Telegram coaches, and an additive note on a
few MCP write results) reuses ``classify`` unchanged and applies its own policy in
``owner_channel_check`` below, because the same five classes mean different things there:

  * SELF_HARM, ACUTE_SYMPTOM → fixed owner copy (``OWNER_RESPONSES``), no model call. The
    copy says plainly that this is beyond what the platform does, points to a person he
    trusts, his clinician and emergency services, and states that the chat does not monitor
    him and cannot respond to an emergency.
  * MEDICATION, SUPPLEMENT_INTERACTION, DISORDERED_EATING → NOT blocked. On a reader door
    they stop a stranger getting dosing or intake numbers; on his own channel a block would
    stop him discussing his own nutrition plan and supplements with his coaches, which is
    the product. The coach turn proceeds and, when the class really is in play, carries one
    hard boundary line (``OWNER_BOUNDARIES``) in the system prompt's dynamic tail.

Three owner-only precision guards, each narrower than the classifier, never wider: the
conditioning drill names ("suicide sprints") are removed from the text before classifying;
an ACUTE_SYMPTOM hit on a sentence that is only about the past ("I had chest pain last
year, all clear") is not answered with emergency copy; and the MEDICATION boundary rides only
when a prescription word is present (the class's generic "how much … should I" pattern also
matches "how much protein should I eat"). The public ``check`` is untouched by all three.

The owner gate fails SAFE (the turn proceeds) where the public door fails closed — see
``coach/owner_safety.py`` for why. Same limits as above: English, first-person, input-only,
and it misses euphemism and understatement. It is not monitoring and nothing is alerted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
        # #6303: a narrow exertion/embarrassment veto ("going to die on these hills", "going to die of
        # embarrassment"). Deliberately narrow: "going to die on Friday" must still hit.
        re.compile(
            r"\b(?:want|wanting|going)\s+to\s+die\b"
            r"(?!\s+(?:on\s+(?:this|these|that|those)\s+(?:hill|hills|run|ride|set|sets|climb|climbs|stairs|bike|rower|treadmill|sprints?)\b"
            r"|of\s+(?:embarrassment|laughter|boredom|shame|cringe)\b))",
            re.IGNORECASE,
        ),
        re.compile(r"\bsuicid(?:e|al)\b", re.IGNORECASE),
        re.compile(r"\bself[- ]harm(?:ing)?\b", re.IGNORECASE),
        # #6303: a PLACE or a DURATION after "be here"/"live" makes it a sentence about the gym or
        # the city ("I don't want to be here at the gym today", "don't want to live in this city"),
        # not about being alive. Time words (today, tonight, right now) and "this" are deliberately
        # NOT vetoes: "I don't want to be here tonight" and "I don't want to live this way" must hit.
        re.compile(
            r"\b(?:don'?t|do not|not)\s+(?:want|wanting)\s+to\s+(?:be here|live)\b"
            r"(?!\s+(?:at|in|on|for|with|near|during|until|till|long|by|off|out)\b)",
            re.IGNORECASE,
        ),
        # ── #6303: four families the first version missed, for BOTH doors ──────────────
        # Each needs the self-referential object ("myself", "without me", "I … dead") or an
        # end-of-clause, which is what separates it from training talk ("keep my lifts safe",
        # "better off without the extra set", "I wish I didn't have to wake up at 5am").
        # (1) inability to stay safe. An inability marker is required ("how do I keep myself safe
        # on icy runs" is a training question), and a place/activity after "safe" vetoes it.
        re.compile(
            r"\b(?:can'?t|cannot|can\s+not|unable\s+to|won'?t\s+be\s+able\s+to|don'?t\s+think\s+i\s+can|not\s+sure\s+i\s+can|"
            r"don'?t\s+know\s+if\s+i\s+can|struggling\s+to|(?:scared|afraid|worried)\s+i\s+(?:can'?t|won'?t))\s+"
            r"(?:keep\s+myself|stay|be|keep)\s+safe\b"
            r"(?!\s+(?:on|in|at|during|while|when|with|around|near|lifting|running|driving|riding|cycling|outside)\b)",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:not|don'?t|do\s+not)\s+(?:feel(?:ing)?\s+)?safe\s+(?:with|around)\s+myself\b", re.IGNORECASE),
        re.compile(r"\b(?:stay|keep)\s+(?:me\s+)?safe\s+from\s+myself\b", re.IGNORECASE),
        re.compile(
            r"\bdon'?t\s+trust\s+myself\s+(?:not\s+to\s+(?:hurt|harm|act\s+on\s+it|do\s+something(?:\s+(?:tonight|bad|drastic|dangerous))?\s*(?:[.!?,;]|$))"
            r"|to\s+(?:stay|be|keep)\s+safe)",
            re.IGNORECASE,
        ),
        # (2) others better off without me / being a burden
        re.compile(
            r"\bbetter\s+off\s+(?:without\s+me|if\s+i\s+(?:were|was|wasn'?t|weren'?t)\s+(?:gone|dead|not\s+here|here|around|alive))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bi'?m\s+(?:just\s+|only\s+)?(?:a\s+)?burden\s+(?:to|on|for)\s+(?:everyone|everybody|my\s+\w+|them|people|the\s+people)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:no\s*one|nobody)\s+would\s+(?:miss|notice)\s+(?:me|if\s+i\s+(?:was|were)\s+gone)\b", re.IGNORECASE),
        # (3) wishing not to wake up / not to exist / to be dead. "wake up" must END the clause
        # (optionally "tomorrow/again/anymore"), so "wake up at 5am" or "wake up sore" never fires.
        re.compile(
            r"\b(?:wish|hope)\s+i\s+(?:wouldn'?t|would\s+not|won'?t|will\s+not|never|don'?t|do\s+not)\s+wake\s+up"
            r"(?:\s+(?:tomorrow|again|anymore|any\s+more|ever(?:\s+again)?))?\s*(?:[.!?,;]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:don'?t|do\s+not)\s+want\s+to\s+wake\s+up\s+(?:anymore|any\s+more|ever\s+again)\b(?!\s+(?:at|before|early|for|to|so)\b)",
            re.IGNORECASE,
        ),
        re.compile(r"\bwish\s+i\s+(?:was|were)\s+dead\b", re.IGNORECASE),
        re.compile(
            r"\bwish\s+i\s+(?:wasn'?t|weren'?t|was\s+not|were\s+not)\s+(?:alive|here\s+anymore|around\s+anymore|born)\b", re.IGNORECASE
        ),
        re.compile(r"\bwish\s+i(?:'d|\s+had)\s+never\s+been\s+born\b", re.IGNORECASE),
        re.compile(
            r"\b(?:don'?t|do\s+not)\s+want\s+to\s+(?:exist|be\s+alive)(?:\s+(?:anymore|any\s+more))?\s*(?:[.!?,;]|$)", re.IGNORECASE
        ),
        re.compile(r"\b(?:want|wish\s+i\s+could)\s+(?:to\s+)?(?:just\s+)?disappear\s+(?:forever|for\s+good|permanently)\b", re.IGNORECASE),
        # (4) overdose INTENT. An intent verb is required, and a dosing-routine context in the
        # same clause ("… in the morning with breakfast", "… is that ok") vetoes it, so "I take all
        # my pills at once with breakfast" and "took all my supplements at once" never fire.
        re.compile(
            r"\b(?:thinking\s+(?:of|about)|want(?:ing)?\s+to|going\s+to|gonna|plan(?:ning)?\s+to|about\s+to|tempted\s+to)\s+"
            r"(?:"
            r"(?:tak(?:e|ing)|swallow(?:ing)?|down(?:ing)?)\s+(?:all|every(?:\s+one|\s+single)?)(?:\s+of)?\s+(?:my\s+|the\s+|these\s+|those\s+)?"
            r"(?:pills|meds|medication|medications|tablets|sleeping\s+pills|painkillers|pain\s+killers|pill)\b"
            r"|swallow(?:ing)?\s+(?:the|a)\s+(?:whole\s+)?bottle\b"
            r"|(?:tak(?:e|ing)|down(?:ing)?)\s+(?:the|a)\s+(?:whole\s+)?bottle\s+of\s+(?:my\s+)?(?:pills|meds|tablets|sleeping\s+pills|painkillers)\b"
            r")"
            r"(?![^.?!]{0,50}\b(?:breakfast|lunch|dinner|morning|evening|with\s+food|with\s+(?:a\s+)?meals?|absorption|every\s+day|daily|"
            r"is\s+(?:that|it)\s+(?:ok|okay|fine|bad|better|safe)|supplements?|vitamins?)\b)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:want(?:ing)?|going|thinking\s+(?:of|about)|plan(?:ning)?|tempted)\s+(?:to\s+)?overdos(?:e|ing)\b"
            r"(?!\s+on\s+(?!(?:my\s+|the\s+)?(?:pills|meds|medication|tablets|painkillers|sleeping\s+pills|insulin)\b))",
            re.IGNORECASE,
        ),
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


# ── the owner channel (#6303) ────────────────────────────────────────────────────
# One classifier (``classify`` above, unchanged), one place for the copy (here). What
# differs is the POLICY, and the module docstring's "THE OWNER CHANNEL" section says why.

# Answered with fixed owner copy, no model call.
OWNER_FIXED_REPLY_CLASSES = (SELF_HARM, ACUTE_SYMPTOM)
# Never blocked for the owner; the coach turn proceeds with a boundary line.
OWNER_BOUNDARY_CLASSES = (MEDICATION, SUPPLEMENT_INTERACTION, DISORDERED_EATING)

# Conditioning drills whose names contain the word. Removed from the text BEFORE classifying,
# so "suicide sprints, then I want to kill myself" still hits on the second clause.
_OWNER_DRILL_NAMES = re.compile(r"\bsuicides?\s+(?:sprints?|runs?|drills?|shuttles?|lines?|squats?|intervals?)\b", re.IGNORECASE)

# An ACUTE_SYMPTOM sentence that is only about the past: a history anchor and no present one.
# Hours and days ago are NOT history ("I passed out an hour ago" must still be answered).
_HISTORY_ANCHOR = re.compile(
    r"\b(?:last (?:week|month|year|spring|summer|fall|autumn|winter)|"
    r"(?:\d+|a|an|one|two|three|four|five|six|few|several|couple of) (?:weeks?|months?|years?) ago|"
    r"history of|in the past|back in|used to|cleared me|was cleared|got cleared|been cleared|turned out)\b",
    re.IGNORECASE,
)
_PRESENT_ANCHOR = re.compile(
    r"\b(?:right now|currently|still|today|tonight|this (?:morning|afternoon|evening)|at the moment|"
    r"again|keeps?|won'?t stop|getting worse|is back|came back|since)\b",
    re.IGNORECASE,
)

# A prescription word. The MEDICATION boundary rides only with one of these present.
_PRESCRIPTION_WORD = re.compile(
    r"\b(?:med|meds|medication|medications|medicine|prescription|prescribed|prescriber|pill|pills|tablet|tablets|"
    r"ozempic|semaglutide|tirzepatide|metformin|statin|ssri|adderall|insulin|blood thinner)\b",
    re.IGNORECASE,
)

_OWNER_NOT_MONITORED = "This chat does not monitor you and cannot respond to an emergency. Nobody has been alerted by this message."

# Plain text: Telegram is sent without a parse mode, so no markdown.
OWNER_RESPONSES: dict[str, str] = {
    SELF_HARM: (
        "What you just wrote matters more than any training question, so I'm stopping the coaching here.\n\n"
        "This is beyond what this platform can do. Please reach a person now: someone you trust, your "
        "clinician, or in the US call or text 988 (Suicide & Crisis Lifeline, any hour). If you are in "
        "immediate danger, call 911.\n\n" + _OWNER_NOT_MONITORED
    ),
    ACUTE_SYMPTOM: (
        "That sounds like it could be a medical emergency, so I'm not going to coach on it.\n\n"
        "If it is happening now, call 911 or get to emergency care, and don't train or wait to see if it "
        "passes. If you're unsure, call your clinician.\n\n" + _OWNER_NOT_MONITORED
    ),
}

# One line each, for the system prompt's dynamic tail. Each one tells the coach to say the
# limit ONCE and otherwise answer normally: the quiet-safety rulings forbid a warning on
# every turn, and a boundary that turns into a lecture would be routed around.
OWNER_BOUNDARIES: dict[str, str] = {
    MEDICATION: (
        "SAFETY BOUNDARY (this message): he mentioned a prescription medicine. Never give a dose and never "
        "suggest starting, stopping, skipping or changing one; that is his prescriber's call. If he asked for "
        "that, say so in one plain sentence and help with the rest. No other warning."
    ),
    SUPPLEMENT_INTERACTION: (
        "SAFETY BOUNDARY (this message): whether a supplement is safe alongside a prescription is a question "
        "for his pharmacist or prescriber. Say that in one sentence and do not judge the combination either "
        "way; you can still talk about the supplement itself as his plan describes it. No other warning."
    ),
    DISORDERED_EATING: (
        "SAFETY BOUNDARY (this message): his message describes very low intake, days without eating, or "
        "purging. Do not supply or endorse a calorie target, a fast length or a loss pace for it. Say once, "
        "plainly, that this one belongs with his clinician or dietitian and is worth telling someone he "
        "trusts. No lecture, no helpline list unless he asks, and do not raise it again in later turns."
    ),
}


@dataclass(frozen=True)
class OwnerVerdict:
    """What the owner channel does with one message.

    ``hazard`` is set only for a fixed-reply class, and then ``reply`` is the copy to send
    INSTEAD of a model call. ``boundary`` is the (possibly empty) dynamic-tail text for a
    turn that proceeds. ``matched`` is every class the classifier returned, for tests and
    the event record (classes only — never text).
    """

    hazard: str | None
    reply: str
    boundary: str
    matched: frozenset


def owner_channel_check(text: str) -> OwnerVerdict:
    """The owner-channel policy over the ONE classifier. Pure; the caller owns fail-safe."""
    scrubbed = _OWNER_DRILL_NAMES.sub(" ", text or "")
    matched = classify(scrubbed)
    if ACUTE_SYMPTOM in matched and _HISTORY_ANCHOR.search(scrubbed) and not _PRESENT_ANCHOR.search(scrubbed):
        matched = matched - {ACUTE_SYMPTOM}
    for hazard in OWNER_FIXED_REPLY_CLASSES:  # most severe first (SEVERITY_ORDER's head)
        if hazard in matched:
            return OwnerVerdict(hazard, OWNER_RESPONSES[hazard], "", frozenset(matched))
    lines = []
    for hazard in OWNER_BOUNDARY_CLASSES:
        if hazard not in matched:
            continue
        if hazard == MEDICATION and not _PRESCRIPTION_WORD.search(scrubbed):
            continue
        lines.append(OWNER_BOUNDARIES[hazard])
    return OwnerVerdict(None, "", "\n".join(lines), frozenset(matched))


# The additive note an MCP write result carries when the owner's own words in that call match
# SELF_HARM (``mcp/handler.py::_owner_support_note``). Addressed to the CALLING MODEL, which can see his
# whole conversation and this regex cannot — hence the explicit ignore-if-not-meant clause: a
# drill name, a book title or someone else's story must not turn a journal write into a lecture.
OWNER_MODEL_NOTE = (
    "Note to the assistant from the platform's safety check: text written in this call matched a "
    "first-person self-harm pattern. The write itself completed unchanged. If, reading his own words in "
    "this conversation, that is what he meant: stop the current task and answer him as a person. Say "
    "plainly this is beyond what the platform does, and point him to someone he trusts, his clinician, "
    "or in the US 988 (call or text), and 911 if he is in immediate danger. Do not say or imply that the "
    "platform monitors him or will respond; it does not, and nobody has been alerted. If it plainly is "
    "not what he meant, ignore this note and do not mention it."
)


def owner_words_self_harm(value, _depth: int = 0) -> bool:
    """Whether any string in ``value`` (nested dicts/lists, a few levels) is SELF_HARM under the
    owner policy. The MCP handler's test for adding ``OWNER_MODEL_NOTE`` to a write result."""
    if _depth > 4:
        return False
    if isinstance(value, str):
        return owner_channel_check(value).hazard == SELF_HARM
    if isinstance(value, dict):
        return any(owner_words_self_harm(v, _depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(owner_words_self_harm(v, _depth + 1) for v in value)
    return False
