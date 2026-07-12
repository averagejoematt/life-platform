"""coach_traits.py — AUTHORED trait scores for the coaching cast (#1113):
the 8 operational coaches + the head coach (lead tier, #1112).

These are deterministic, human-authored character design — cast sheet numbers,
NOT AI-generated and NOT derived from data at page-view time. They exist so a
coach's bio page can render the personality that already governs the voice spec
(`config/coaches/{id}.json` decision_style) and the CC-series characterization
as scored traits a reader can compare across the cast.

Honesty contract (ADR-104 adjacent): the site must always label these as
authored fiction-design, never as measured behavior. The `disclosure` string in
`traits_for()` carries that label to the front-end.

Every score is authored against two anchors, in this order:
  1. the coach's own decision_style in config/coaches/{id}.json (the actual
     prompt material — e.g. Reyes "requires 4+ weeks", Webb "flatly state"),
  2. the CC-series characterization (/story/coaches/).
If a voice spec changes character, update the score here in the same PR —
`tests/test_coach_traits.py` enforces structure, a human enforces fidelity.

Shared axes (0-100) so the numbers are comparable across the cast; each pole is
labelled so a bar reads as a position between two temperaments, not a grade.
"""

# The shared axes every coach is scored on. Order is render order.
TRAIT_AXES = [
    {"key": "evidence_bar", "label": "evidence bar", "low": "acts on early signal", "high": "wants weeks of proof"},
    {"key": "boldness", "label": "boldness", "low": "hedges", "high": "states it flat"},
    {"key": "revision_speed", "label": "revision speed", "low": "slow to update", "high": "updates immediately"},
    {"key": "intervention_urge", "label": "intervention urge", "low": "watches first", "high": "prescribes fast"},
    {"key": "range", "label": "range", "low": "stays in lane", "high": "reads everything"},
]

# coach_id -> {"scores": {axis_key: 0-100}, "note": one authored line}
COACH_TRAITS = {
    "sleep_coach": {
        "scores": {"evidence_bar": 60, "boldness": 25, "revision_speed": 85, "intervention_urge": 40, "range": 45},
        "note": "A careful reader of converging signals — quick to say she was wrong, slow to say she's sure.",
    },
    "training_coach": {
        "scores": {"evidence_bar": 45, "boldness": 65, "revision_speed": 65, "intervention_urge": 80, "range": 35},
        "note": "Adjusts the plan inside the week — bold about load and recovery, quiet about mechanism.",
    },
    "nutrition_coach": {
        "scores": {"evidence_bar": 70, "boldness": 85, "revision_speed": 75, "intervention_urge": 70, "range": 25},
        "note": "Flat statements inside his lane, hedges the moment he leaves it — unsentimental when a call misses.",
    },
    "mind_coach": {
        "scores": {"evidence_bar": 55, "boldness": 30, "revision_speed": 35, "intervention_urge": 20, "range": 60},
        "note": "Names a pattern in days but prescribes in weeks — sits with a read before revising it.",
    },
    "physical_coach": {
        "scores": {"evidence_bar": 90, "boldness": 70, "revision_speed": 20, "intervention_urge": 55, "range": 40},
        "note": "Operates in months — won't chase a weekly fluctuation, and won't soften a DEXA verdict either.",
    },
    "glucose_coach": {
        "scores": {"evidence_bar": 40, "boldness": 80, "revision_speed": 80, "intervention_urge": 60, "range": 45},
        "note": "The trace is right there — calls a meal response after two repetitions, updates the mechanism just as fast.",
    },
    "labs_coach": {
        "scores": {"evidence_bar": 85, "boldness": 70, "revision_speed": 55, "intervention_urge": 50, "range": 35},
        "note": "Two draws make a trend, one makes a caveat — bold only where a clinical threshold backs him.",
    },
    "explorer_coach": {
        "scores": {"evidence_bar": 50, "boldness": 30, "revision_speed": 90, "intervention_urge": 15, "range": 95},
        "note": "A low bar to notice, a high bar to act — delighted to be refuted, and every domain is his domain.",
    },
    # #1112 — the head coach (lead tier). Authored against the eli_marsh persona
    # (config/personas.json philosophy) + his board_of_directors.json voice: the
    # generalist above eight specialists, decisive about the single priority,
    # rigorous about correlation-vs-verdict, one experiment at a time.
    "eli_marsh": {
        "scores": {"evidence_bar": 75, "boldness": 60, "revision_speed": 55, "intervention_urge": 70, "range": 90},
        "note": "The generalist above eight specialists — turns competing reads into one call, and never runs two experiments at once.",
    },
}

_DISCLOSURE = "Authored character design — fixed numbers written into the cast by the author, not generated and not measured."


def traits_for(coach_id):
    """Render-ready trait block for one coach, or None for unknown ids.

    Shape: {"axes": [{key,label,low,high,score}, ...], "note": str, "disclosure": str}
    Axes render in TRAIT_AXES order. Deterministic — pure dict lookups.
    """
    entry = COACH_TRAITS.get(coach_id)
    if not entry:
        return None
    axes = [{**axis, "score": entry["scores"][axis["key"]]} for axis in TRAIT_AXES]
    return {"axes": axes, "note": entry["note"], "disclosure": _DISCLOSURE}
