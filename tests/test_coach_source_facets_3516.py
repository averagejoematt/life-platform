"""tests/test_coach_source_facets_3516.py — #3516: a paused source is never a sync failure.

THE DEFECT (live, Day 0 of cycle 16). `coach_brief_input_gate.data_inventory` rendered
every source as `AVAILABLE` / `not available` and nothing else. With no reason attached,
the coaches supplied one, and the one they reached for was a sync failure:

    /api/coach_analysis?domain=physical  — "Garmin step data isn't syncing to my
        dashboard yet, which blocks meaningful tracking of his 8,000+ steps/day protocol"
    /api/coach_analysis?domain=nutrition — "MacroFactor isn't syncing yet — that's fine
        for today, but it needs to be running by tomorrow"

Garmin is `paused: True` in the source registry (ADR-074, no EventBridge rule) and CANNOT
report; MacroFactor is `stale_hours: 96` with a `method` that literally says "~24h behind
by design". Neither is a sync problem, and on every day either is absent — Garmin
permanently — readers were told otherwise.

GUARD THE SET, NOT THE INSTANCE. The interesting tests below are not "Garmin renders
PAUSED". They are:

  * every registry source with a caveat facet is REACHABLE from one derivation
    (`caveated_source_ids`), so a source becoming paused (or having its cadence loosened
    past the default) cannot silently go back to being narrated as a sync failure;
  * every inventory row's registry id RESOLVES, and every caveated source the inventory
    lists renders its facet — asserted by iterating the registry, not a hand list;
  * the ONE caveat sentence is composed in the registry, so the coach inventory and the
    analyzer's `movement_source_reason` cannot word the same fact two ways.

The two live sentences are the positive controls for the gate.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_brief_input_gate as gate  # noqa: E402
from ingestion import source_registry as sr  # noqa: E402
from intelligence import analyzer_grounding as ag  # noqa: E402

# The two sentences that actually shipped, verbatim.
LIVE_GARMIN = "Garmin step data isn't syncing to my dashboard yet, which blocks meaningful tracking of his 8,000+ steps/day protocol."
LIVE_MACROFACTOR = "MacroFactor isn't syncing yet — that's fine for today, but it needs to be running by tomorrow."


# ── the facet itself ─────────────────────────────────────────────────────────


def test_the_caveated_set_is_derived_and_non_empty():
    caveated = sr.caveated_source_ids()
    assert caveated, "no source carries a caveat facet — the derivation is dark"
    # Derived, not declared: every member must be explainable by its own registry row.
    for src in caveated:
        entry = sr.SOURCE_REGISTRY[src]
        hours = entry.get("stale_hours")
        assert entry.get("paused") or (
            isinstance(hours, (int, float)) and hours > sr.DEFAULT_STALE_HOURS
        ), f"{src} is in the caveated set for no facet reason"
    # And the complement: no source OUTSIDE the set has a facet reason.
    for src, entry in sr.SOURCE_REGISTRY.items():
        if src in caveated:
            continue
        hours = entry.get("stale_hours")
        assert not entry.get("paused"), f"{src} is paused but not caveated"
        assert not (isinstance(hours, (int, float)) and hours > sr.DEFAULT_STALE_HOURS), f"{src} lags but is not caveated"


def test_garmin_is_paused_with_the_registrys_own_reason():
    facet = sr.availability_facet("garmin")
    assert facet["status"] == sr.AVAILABILITY_PAUSED
    # The reason is the registry's `method` string verbatim — never a sentence composed
    # at the surface, which is how the ADR reference would drift.
    assert facet["reason"] == sr.SOURCE_REGISTRY["garmin"]["method"]
    assert "ADR-074" in facet["caveat"], "the pause's ADR must reach the reader through the registry's own words"
    assert "never a sync failure" in facet["caveat"]


def test_macrofactor_is_lagging_with_its_registry_threshold():
    facet = sr.availability_facet("macrofactor")
    assert facet["status"] == sr.AVAILABILITY_LAGGING
    assert facet["lag_hours"] == sr.SOURCE_REGISTRY["macrofactor"]["stale_hours"]
    assert "96h" in facet["caveat"]


def test_an_unknown_source_can_never_manufacture_a_caveat():
    facet = sr.availability_facet("not-a-source")
    assert facet["status"] == sr.AVAILABILITY_LIVE
    assert facet["caveat"] == ""


def test_a_live_source_carries_no_caveat_negative_control():
    # whoop: infrastructure, no pause, no stale_hours override. If this ever starts
    # rendering a caveat the facet has gone permissive and every line becomes noise.
    assert sr.availability_facet("whoop")["caveat"] == ""


# ── the inventory renders the facet, for the WHOLE set ───────────────────────


def test_every_inventory_row_resolves_to_a_real_registry_source_or_declares_none():
    for name, keys, source_id in gate.INVENTORY_ROWS:
        assert keys, f"{name} names no brief-data key"
        if source_id is not None:
            assert source_id in sr.SOURCE_REGISTRY, f"{name} points at {source_id!r}, which is not in the registry"


def test_every_caveated_source_the_inventory_lists_renders_its_facet():
    """THE SET GUARD. Derived from the registry, not from the two sources the live
    defect happened to name — a newly paused source is covered the moment it is paused."""
    rendered = gate.data_inventory({})
    caveated = sr.caveated_source_ids()
    listed = {sid for _n, _k, sid in gate.INVENTORY_ROWS if sid}
    covered = listed & caveated
    assert covered, "the inventory lists no caveated source — this guard would be vacuous"
    for source_id in sorted(covered):
        caveat = sr.availability_facet(source_id)["caveat"]
        assert caveat in rendered, f"{source_id}'s registry caveat is missing from the rendered inventory"


def test_the_inventory_still_says_available_and_carries_the_rule():
    rendered = gate.data_inventory({"whoop": [{"recovery": 60}]})
    assert "  - Whoop recovery/sleep: AVAILABLE" in rendered
    assert "  - Garmin steps: not available" in rendered
    assert "never attribute a CAUSE to an absence this inventory does not state" in rendered


def test_the_analyzer_and_the_inventory_use_THE_SAME_sentence():
    """One wording, one place. Two surfaces composing their own sentence is how the same
    paused source got two different fictions in the first place."""
    reasons = ag.movement_source_reasons({"garmin": "paused", "strava": "live"})
    assert reasons["garmin"] == sr.availability_facet("garmin")["caveat"]
    assert "strava" not in reasons, "a live source must not get an empty caveat that invites narration"
    assert reasons["garmin"] in gate.data_inventory({})


# ── the regenerate-or-hold gate ──────────────────────────────────────────────


def test_the_two_live_sentences_are_findings_positive_control():
    for text, expected in ((LIVE_GARMIN, "garmin"), (LIVE_MACROFACTOR, "macrofactor")):
        found = gate.source_facet_findings(text)
        assert found, f"the live sentence must be a finding: {text}"
        assert found[0]["source"] == expected
        assert found[0]["type"] == "source_facet_misattribution"


def test_honest_phrasings_are_not_findings_negative_controls():
    for text in (
        "Garmin is paused (ADR-074), so steps cannot be read this cycle.",
        "MacroFactor arrives about a day behind by design, so today's log is not in yet.",
        "Strava shows no runs this week.",
        "Whoop isn't syncing yet.",  # a LIVE source: not this gate's business, however worded
        "",
    ):
        assert gate.source_facet_findings(text) == [], f"false positive on: {text!r}"


def test_a_regeneration_that_fixes_the_claim_is_published():
    fixed = "Garmin is paused under ADR-074, so it cannot report steps at all."
    out, finding = gate.enforce_source_facet_attribution(LIVE_GARMIN, {}, lambda _note: fixed)
    assert out == fixed
    assert finding["source"] == "garmin"


def test_a_regeneration_that_repeats_the_claim_is_HELD():
    out, finding = gate.enforce_source_facet_attribution(LIVE_GARMIN, {}, lambda _note: LIVE_GARMIN)
    assert out is None, "a surviving misattribution must be held, not published"
    assert finding["source"] == "garmin"


def test_a_failed_regeneration_holds_rather_than_publishing():
    def boom(_note):
        raise RuntimeError("bedrock down")

    out, finding = gate.enforce_source_facet_attribution(LIVE_GARMIN, {}, boom)
    assert out is None
    assert finding is not None


def test_clean_text_passes_through_untouched_and_never_calls_the_model():
    def never(_note):
        raise AssertionError("regenerate_fn must not be called when there is no finding")

    clean = "Hevy shows two sessions this week and the volume is climbing."
    out, finding = gate.enforce_source_facet_attribution(clean, {}, never)
    assert out == clean
    assert finding is None


def test_the_correction_note_quotes_the_registrys_caveat():
    note = gate.source_facet_correction(gate.source_facet_findings(LIVE_GARMIN))
    assert sr.availability_facet("garmin")["caveat"] in note
    assert "Rewrite those sentences" in note
