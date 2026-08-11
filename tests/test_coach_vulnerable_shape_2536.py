"""#2536 — eight personas, one template: per-persona shapes for the two collapsed cases.

WHAT THE MEASUREMENT SAID. One identical opener ("honestly I'm just tired of all of
this") put to all eight texting personas, re-measured after #2534's composure pass:
7 of 8 opened by naming his state back at him, the three-word stem "that kind of"
opened replies from 5 different coaches, and on honest absence "don't have that"
opened the admission for 6 of 8. Shingle-Jaccard across those same replies is under
0.06 — different words, one shape.

WHY THE FIX SPLITS IN TWO. The shared prompt can only FORBID the template's three
moves; it cannot supply eight replacements without becoming the ninth template (the
#2533 lesson — a shared prompt that supplies wording produces one shared answer). So
what each coach does INSTEAD is per-persona, in its own idiom, in its own spec.

These tests pin the STRUCTURE of the change, not its effect. A prompt rule's effect is
measured by the sim harness, not asserted by a unit test, and pretending otherwise is
the "gate that guards nothing" failure. What is assertable: every texting persona has
both clauses, they are distinct, they fit under the render cap, they reach the block
the chat surface actually sends, the shared rules name the three measured
constructions by name, and the rules ride in the volatile tail so the cached prefix
stays byte-stable (COST-OPT-2).
"""

import pytest
from coach.coach_chat import build_system_prompt
from coach.persona_core import _MAX_FIELD_CHARS, load_voice_spec, texting_block
from coach.persona_registry import TEXTING_PERSONA_IDS

_FIELDS = ("vulnerable_shape", "absence_shape")


def _style(coach_id):
    spec = load_voice_spec(coach_id)
    assert spec, f"{coach_id}: voice spec did not load"
    return spec.get("texting_style") or {}


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
@pytest.mark.parametrize("field", _FIELDS)
def test_every_texting_persona_has_both_clauses(coach_id, field):
    """Derived from the registry, so a new texting coach cannot join without them."""
    assert _style(coach_id).get(field), f"{coach_id}: no texting_style.{field}"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
@pytest.mark.parametrize("field", _FIELDS)
def test_clauses_fit_under_the_render_cap(coach_id, field):
    """Past the cap `_clip` truncates mid-instruction and the coach never reads the rule."""
    value = _style(coach_id).get(field) or ""
    assert len(value) <= _MAX_FIELD_CHARS, f"{coach_id}.{field}: {len(value)} chars, clipped at {_MAX_FIELD_CHARS}"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
@pytest.mark.parametrize("field", _FIELDS)
def test_clauses_reach_the_texting_block(coach_id, field):
    """Inert unless texting_block renders them — the chat surface's only path. A field
    added to eight specs and left out of the labels tuple is eight edits and no change."""
    value = _style(coach_id).get(field) or ""
    assert value in texting_block(load_voice_spec(coach_id))


@pytest.mark.parametrize("field", _FIELDS)
def test_clauses_are_distinct_across_the_roster(field):
    """One shared sentence copied eight times fixes the tone and leaves the collapse
    untouched. That is the failure this issue IS; it must not be the fix as well."""
    values = {c: _style(c).get(field) for c in TEXTING_PERSONA_IDS}
    assert len(set(values.values())) == len(values), f"{field}: duplicate clauses in {values}"


@pytest.mark.parametrize("field", _FIELDS)
def test_clauses_do_not_share_an_opening(field):
    """Distinct strings that all open the same way would prescribe the same first move
    — which is the collapse restated one level down."""
    openings = [" ".join((_style(c).get(field) or "").split()[:5]).lower() for c in TEXTING_PERSONA_IDS]
    dupes = {o for o in openings if openings.count(o) > 1}
    assert not dupes, f"{field} clauses share an opening: {dupes}"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
@pytest.mark.parametrize("field", _FIELDS)
def test_clauses_do_not_repeat_their_own_label(coach_id, field):
    """Rendered as '- <Label>: <value>'; a value that restates the label reads as
    '- When you don't have it: When you don't have it, …'."""
    value = (_style(coach_id).get(field) or "").lower()
    assert not value.startswith("when "), f"{coach_id}.{field} opens by restating its own label"


# Deferral is the failure mode a voice-differentiation clause can accidentally buy:
# "I'll check and get back to you" sounds like eight different people and admits
# nothing, and nothing in this repo ever gets back to him. ADR-104 says the gap is
# stated in the same message; these are the constructions that would let it not be.
_DEFERRAL_LICENCE = (
    "get back to you",
    "check and let you know",
    "look into it",
    "i'll find out",
    "circle back",
    "let me check",
    "come back to it",
)


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_absence_clauses_never_license_deferring_the_admission(coach_id):
    """ADR-104. Differentiating HOW a coach says it has no data must not soften WHETHER
    it says so — a clause that only told the coach to sound different would be a
    grounding regression dressed as a voice fix. The obligation itself is asserted on
    the shared rule below; this pins that no per-persona clause undercuts it."""
    value = (_style(coach_id).get("absence_shape") or "").lower()
    licensed = [d for d in _DEFERRAL_LICENCE if d in value and f"no {d}" not in value and f'no "{d}"' not in value]
    assert not licensed, f"{coach_id}: absence_shape licenses deferral instead of admission — {licensed}"


# ── The shared rules ──────────────────────────────────────────────────────────


def _rules() -> str:
    return build_system_prompt("persona", "memory", "facts", "Dr. Lisa Park").lower()


def test_shared_rules_ban_the_demonstrative_acknowledgement():
    """Move 1 of the template — measured opening 7 of 8 replies to the same message."""
    rules = _rules()
    assert "naming his state back at him" in rules
    assert "that kind of tired" in rules


def test_shared_rules_ban_quoting_his_words_back_at_him():
    """Move 2 — his own phrase returned in quotation marks as a question."""
    assert "own words in quotation marks" in _rules()


def test_shared_rules_ban_the_menu_question():
    """Move 3 — 'the tracking, the whole project, or something else?'."""
    rules = _rules()
    assert "never offer him a menu" in rules
    assert "list of options" in rules


def test_shared_rules_differentiate_absence_without_weakening_it():
    """The phrasing is the coach's; the fact is not negotiable, and the rule has to say
    both or it reads as permission to hedge."""
    rules = _rules()
    assert "the words you would use" in rules
    assert "the fact never bends" in rules
    assert "you say that in the same message" in rules


def test_template_rules_ride_in_the_volatile_tail_not_the_cached_prefix():
    """The cached prefix must stay byte-identical per coach for COST-OPT-2. Rules
    belong in the tail — where #2481's and #2534's already are — or every turn
    re-bills the persona substrate."""
    from coach.coach_chat import build_system_blocks

    blocks = build_system_blocks("persona", "memory", "facts", "Dr. Lisa Park")
    cached = [b for b in blocks if b.get("cache_control")]
    assert cached, "the stable prefix lost its cache_control"
    assert "never offer him a menu" not in cached[0]["text"].lower()
