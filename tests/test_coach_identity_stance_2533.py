"""#2533 — the identity stance is present, per-persona, and actually reaches the prompt.

Owner decision 2026-08-10: the coaches disclose that they are fictional composites and
then move on. Not deception — every other exchange should feel like texting a coach
rather than operating a chatbot.

The measured failure this guards against is not "a coach lied". It is that the
disclosure was IDENTICAL across the roster: `"No — I'm a"` opened 6 of 8 coaches
verbatim, and a blind judge panel called 100% of those conversations AI. So the tests
below assert three separate things, because any one of them can hold while the others
rot:

  1. every texting persona HAS a stance (a new coach must not join the roster without
     one and quietly fall back to the base model's answer);
  2. the stances are DISTINCT from each other (one well-written stance copied around
     would fix the tone and leave the collapse untouched — which is the whole defect);
  3. the stance actually RENDERS into the block the chat surface sends, untruncated
     (`persona_core._clip` caps fields at `_MAX_FIELD_CHARS`, so a stance written past
     the cap is silently cut mid-instruction — a rule the coach never finishes reading).

Guarding the SET, not an instance: (1) derives its coach list from
`persona_registry.TEXTING_PERSONA_IDS` rather than a hard-coded list, so adding a
texting coach without a stance fails here instead of shipping.
"""

import json

import pytest
from coach.persona_core import _MAX_FIELD_CHARS, load_voice_spec, texting_block
from coach.persona_registry import TEXTING_PERSONA_IDS


def _spec(coach_id):
    spec = load_voice_spec(coach_id)
    assert spec, f"{coach_id}: voice spec did not load"
    return spec


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_every_texting_persona_has_an_identity_stance(coach_id):
    stance = (_spec(coach_id).get("texting_style") or {}).get("identity_stance")
    assert stance, f"{coach_id}: no texting_style.identity_stance — it would answer 'are you real?' as the base model"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_identity_stance_fits_under_the_render_cap(coach_id):
    """A stance past the cap is truncated mid-sentence by _clip and never read whole."""
    stance = (_spec(coach_id).get("texting_style") or {}).get("identity_stance") or ""
    assert len(stance) <= _MAX_FIELD_CHARS, f"{coach_id}: stance is {len(stance)} chars, _clip truncates at {_MAX_FIELD_CHARS}"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_identity_stance_reaches_the_texting_block(coach_id):
    """The field is inert unless texting_block renders it — the chat surface's only path."""
    stance = (_spec(coach_id).get("texting_style") or {}).get("identity_stance") or ""
    block = texting_block(_spec(coach_id))
    assert stance in block, f"{coach_id}: identity_stance did not render into texting_block"


def test_identity_stances_are_distinct_across_the_roster():
    """The defect was sameness, not absence — eight stances must be eight stances."""
    stances = {c: (_spec(c).get("texting_style") or {}).get("identity_stance") or "" for c in TEXTING_PERSONA_IDS}
    assert len(set(stances.values())) == len(stances), "identity stances are not unique across the texting roster"


def test_identity_stances_do_not_share_an_opening_construction():
    """`"No — I'm a"` opening 6 of 8 is the measured failure; guard the shape, not the string."""
    openings = [
        " ".join((s or "").split()[:6]).lower()
        for s in ((_spec(c).get("texting_style") or {}).get("identity_stance") for c in TEXTING_PERSONA_IDS)
    ]
    duplicated = {o for o in openings if openings.count(o) > 1}
    assert not duplicated, f"identity stances share an opening construction: {duplicated}"


def test_shared_standard_still_forbids_claiming_to_be_human():
    """The disclosure requirement is the thing the per-persona stances IMPLEMENT.

    If this boundary is ever deleted, the stances become eight coaches deciding for
    themselves whether to admit what they are — so the two are pinned together.
    """
    std = load_voice_spec("_shared_standard")
    boundaries = " ".join(std.get("safety_boundaries") or []).lower()
    assert "never claim to be human" in boundaries
    assert "never let him believe you are" in boundaries


def test_shared_standard_bounds_the_disclosure_to_one_telling():
    """Disclose and move on — the owner decision, not a lecture."""
    std = load_voice_spec("_shared_standard")
    boundaries = " ".join(std.get("safety_boundaries") or []).lower()
    assert "in one line" in boundaries, "the once-only framing is missing"
    assert "never narrate how you work" in boundaries, "the architecture-narration ban is missing"


def test_shared_standard_supplies_no_quotable_self_description():
    """The rule must state the OBLIGATION without handing over the WORDS.

    Measured 2026-08-10: the boundary read "every coach is a canonical fictional
    composite", and 5 of 8 coaches answered "are you a real person?" with the phrase
    "fictional composite" — they were quoting the substrate every one of them
    inherits. A shared prompt that supplies a label produces a shared answer, however
    many per-persona stances sit downstream of it. So the boundary names the duty and
    the stance names the wording.
    """
    std = load_voice_spec("_shared_standard")
    boundaries = " ".join(std.get("safety_boundaries") or []).lower()
    for label in ("fictional composite", "canonical fictional", "fictional ai"):
        assert label not in boundaries, f"shared boundary supplies a quotable self-description: {label!r}"
    assert "your own words" in boundaries, "the boundary must defer the wording to each persona's stance"


@pytest.mark.parametrize("coach_id", TEXTING_PERSONA_IDS)
def test_voice_spec_is_valid_json_on_disk(coach_id):
    """The stances were inserted by a text edit to keep the diff reviewable — so the
    files' validity is asserted rather than assumed."""
    from common.repo_config import config_path

    with open(config_path("coaches", f"{coach_id}.json")) as fh:
        json.load(fh)
