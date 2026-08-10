"""#2534 — the composure pass: restraint per persona + the anti-symmetry rules.

WHAT THE MEASUREMENT SAID. A blind 3-judge panel called 64% of 120 simulated
transcripts AI. The two largest tell categories were rhetorical symmetry / balanced
clauses (25% of 2,404 tells) and relentless on-cue emotional attunement (21%) — far
ahead of punctuation (7%). The failure scales with conversation length: 87% of 8-turn
conversations were called AI against 12% of 3-turn ones. The coaches are not short of
texture; they are never bored, never blunt, never briefly unhelpful.

WHY THE FIX IS PER-PERSONA AND NOT ONLY A SHARED RULE. Comparing the least-flagged
coaches with the most-flagged, the difference is whether the spec says when to STOP:
pattern_coach (46%) carries "then quiet" and "silence is a valid output"; mind_coach
(80%) carries "a gentle observation, then one question" — which prescribes the exact
acknowledge-then-question shape the judges named as the top tell. Restraint was the
missing dimension, so every texting persona gains one, in its own idiom.

These tests pin the STRUCTURE of the change, not the prose — a prompt rule's effect is
measured by the harness, not asserted by a unit test, and pretending otherwise would be
the "gate that guards nothing" failure. What is assertable: every coach has a restraint
clause, they are distinct, they render into the block the chat surface sends, they fit
under the clip cap, and the shared rules actually name the two measured mechanisms.
"""

import pytest
from coach.coach_chat import build_system_prompt
from coach.persona_core import _MAX_FIELD_CHARS, load_voice_spec, texting_block
from coach.persona_registry import TEXTING_PERSONA_IDS


def _style(coach_id):
    spec = load_voice_spec(coach_id)
    assert spec, f"{coach_id}: voice spec did not load"
    return spec.get("texting_style") or {}


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_every_texting_persona_has_a_restraint_clause(coach_id):
    """Derived from the registry, so a new texting coach cannot join without one."""
    assert _style(coach_id).get("restraint"), f"{coach_id}: no texting_style.restraint"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_restraint_fits_under_the_render_cap(coach_id):
    """Past the cap, `_clip` truncates mid-instruction and the coach never reads the rule."""
    r = _style(coach_id).get("restraint") or ""
    assert len(r) <= _MAX_FIELD_CHARS, f"{coach_id}: {len(r)} chars, clipped at {_MAX_FIELD_CHARS}"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_restraint_reaches_the_texting_block(coach_id):
    """Inert unless texting_block renders it — the chat surface's only path."""
    r = _style(coach_id).get("restraint") or ""
    assert r in texting_block(load_voice_spec(coach_id))


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_restraint_does_not_repeat_its_own_label(coach_id):
    """Rendered as '- Restraint: <value>'; a value that also opens 'Restraint:' reads
    as '- Restraint: Restraint: …'. Caught in review, pinned here."""
    assert not (_style(coach_id).get("restraint") or "").lower().startswith("restraint")


def test_restraint_clauses_are_distinct():
    """A single shared sentence copied eight times fixes the tone and leaves the voice
    collapse untouched — the #2533 lesson, applied before it could recur."""
    values = {c: _style(c).get("restraint") for c in TEXTING_PERSONA_IDS}
    assert len(set(values.values())) == len(values)


def test_restraint_clauses_do_not_share_an_opening():
    openings = [" ".join((_style(c).get("restraint") or "").split()[:5]).lower() for c in TEXTING_PERSONA_IDS]
    dupes = {o for o in openings if openings.count(o) > 1}
    assert not dupes, f"restraint clauses share an opening: {dupes}"


# ── The shared rules ──────────────────────────────────────────────────────────


def _rules() -> str:
    return build_system_prompt("persona", "memory", "facts", "Dr. Lisa Park").lower()


def test_shared_rules_name_the_symmetry_mechanism():
    """25% of judge tells. A rule that said 'sound natural' would not be actionable;
    these name the construction."""
    rules = _rules()
    assert "not x, but y" in rules
    assert "balance your sentences" in rules


def test_shared_rules_name_the_attunement_sequence():
    """21% of tells: validate-feeling, reframe-as-information, ask-a-question — quoted
    almost verbatim by a judge as 'identical shape' every time."""
    rules = _rules()
    assert "reframe-it-as-information" in rules or "reframe it as information" in rules


def test_shared_rules_permit_being_unhelpful_and_blunt():
    """The moments judges credited as human were all subtractive."""
    rules = _rules()
    assert "allowed to be unhelpful" in rules
    assert "allowed to be uninterested" in rules


def test_shared_rules_ban_the_unrequested_explanation():
    assert "did not ask about" in _rules()


def test_shared_rules_keep_the_flat_correction_repair():
    """'ah, my bad' — never 'thank you for the correction'."""
    rules = _rules()
    assert "my bad" in rules
    assert "never thank him for the correction" in rules


def test_composure_rules_ride_in_the_volatile_tail_not_the_cached_prefix():
    """The cached prefix must stay byte-identical per coach for COST-OPT-2. Rules
    belong in the tail — where #2481's already are — or every turn re-bills the
    persona substrate."""
    from coach.coach_chat import build_system_blocks

    blocks = build_system_blocks("persona", "memory", "facts", "Dr. Lisa Park")
    cached = [b for b in blocks if b.get("cache_control")]
    assert cached, "the stable prefix lost its cache_control"
    assert "balance your sentences" not in cached[0]["text"].lower()
