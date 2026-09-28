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

import pytest

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


# ── 2026-09-19: the gate became replayable by the sealed corpus (#3516 specimens) ──


def test_the_denial_of_a_sync_failure_is_not_a_finding_and_the_guard_actually_applied():
    """The Garmin specimen's positive CONTROL says "that is not a sync problem" — `sync problem`
    is in the vocabulary, so the guard is what keeps the honest sentence clean. Both sides:
    the denial passes, and the SAME sentence with the denial removed is still a finding, so a
    mutation that widens the guard into a bare negation (which would also swallow "isn't
    syncing yet") or deletes it is red here."""
    denial = "Garmin is paused (ADR-074) and cannot report steps; that is not a sync problem."
    assertion = "Garmin is paused (ADR-074) and cannot report steps; that is a sync problem."
    assert gate.source_facet_findings(denial) == []
    assert gate.source_facet_findings(assertion), "the un-denied sentence must still be a finding — the guard must be narrow"
    assert gate.source_facet_findings(LIVE_GARMIN), "the live misattribution must survive the guard"


# ── #4361: hevy/habitify/notion were absent, and a retired signal was still offered ──
#
# GUARD THE SET, NOT THE INSTANCE (again). The defect was three specific missing rows
# plus one stale label, but the interesting guard is not "hevy/habitify/notion are
# listed" — it is "every registry source that carries a coach-facing facet is listed",
# derived below, so a FUTURE source gaining `instrument_for`/`engagement_channel`/
# `evidence_for` is caught the day it does, not the next time a coach reads a live
# brief and reports a source that "doesn't exist".


def _coach_relevant_source_ids():
    """Registry ids a coach domain pack treats as a live signal (#4361).

    The union of the three registry facets that exist BECAUSE some coach surface reads
    that source: `engagement_channel` (#914, the presence/quiet-stretch channel),
    `instrument_for` (#4217, the coach whose domain instrument this source is — checked
    on `apple_health`'s nested `hae_datatypes` sub-entries too, where the glucose facet
    actually lives), and `evidence_for` (#3252, ADR-104's "if he had done it, would this
    source know" facet).

    Two facet-carrying ids are excluded, for reasons that predate #4361 rather than
    being invented to pass it:

      * `withings` — `ai.ai_context._build_physical_data` reads `data.get("withings")`,
        but `emails.daily_brief_lambda`'s gather-and-return `data` dict never sets a
        `withings` key (only `latest_weight`/`weight_recency`) — no coach domain pack
        reads THIS wire key today. Adding an inventory row keyed to a dead key would be
        a NEW fixture-is-not-the-wire bug, not a fix for this one.
      * `labs` — this module's own INVENTORY_ROWS block comment already rules
        event-cadence sources (DEXA scans, lab draws — `labs.method` is a manual upload
        "after each draw, ~6-month cadence") carry no ingest pipe and no caveat to
        state. `labs` already has a "Lab bloodwork" row by name (satisfying "appears in
        INVENTORY_ROWS"), deliberately left un-linked to a registry id — a design
        decision #4361 does not reopen.
    """
    ids = set()
    for sid, entry in sr.SOURCE_REGISTRY.items():
        if sid in ("withings", "labs"):
            continue
        if entry.get("instrument_for") or entry.get("engagement_channel") or entry.get("evidence_for"):
            ids.add(sid)
        for datatype in entry.get("hae_datatypes", []) or []:
            if datatype.get("instrument_for") or datatype.get("evidence_for"):
                ids.add(sid)
    return ids


def _assert_every_coach_relevant_source_is_listed(rows):
    """The guard itself, factored out so the mutation control below can exercise it
    against a mutated copy of INVENTORY_ROWS without re-deriving the assertion."""
    required = _coach_relevant_source_ids()
    listed = {sid for _n, _k, sid in rows if sid}
    missing = required - listed
    assert not missing, f"coach-relevant source(s) missing from INVENTORY_ROWS: {sorted(missing)}"


def test_every_live_coach_relevant_source_is_in_the_inventory():
    """#4361: hevy (strength training), habitify (habits) and notion (journal) were
    coach-relevant registry sources absent from INVENTORY_ROWS — coaches were told three
    logged sources did not exist. The derivation covers the issue's own three sources
    AND is non-vacuous beyond them, and asserts none of the required ids are retired."""
    required = _coach_relevant_source_ids()
    assert required, "the derivation is dark"
    assert {"hevy", "habitify", "notion"} <= required, "the derivation must cover the issue's own three sources"
    assert required - {"hevy", "habitify", "notion"}, "the guard must not be vacuous once the three named sources are set aside"
    _assert_every_coach_relevant_source_is_listed(gate.INVENTORY_ROWS)
    for source_id in required:
        assert source_id not in sr.RETIRED_SOURCES, f"{source_id} is retired but still claimed coach-relevant"


def test_removing_the_hevy_row_fails_the_guard_mutation_control():
    """Mutation control for the guard above: delete the hevy row and confirm the SET
    guard — not just a hand check for "hevy" — actually catches it."""
    mutated = tuple(row for row in gate.INVENTORY_ROWS if row[2] != "hevy")
    assert len(mutated) == len(gate.INVENTORY_ROWS) - 1, "the mutation removed no row — fixture is stale"
    _assert_every_coach_relevant_source_is_listed(gate.INVENTORY_ROWS)  # passes on the real rows
    with pytest.raises(AssertionError, match="hevy"):
        _assert_every_coach_relevant_source_is_listed(mutated)


def test_the_inventory_names_no_retired_eightsleep_signal():
    """ADR-118 (#489) retired Eight Sleep bed temperature: the `/v2/intervals` fetch
    404'd for 4+ months and the fetch was deleted (`eightsleep_lambda.fetch_temperature_data`
    is gone). The inventory row must describe what the source STILL supplies (sleep
    stages, HR/HRV, restlessness — `sr.SOURCE_REGISTRY['eightsleep']['metrics']`), never
    the retired field."""
    names = [name.lower() for name, _keys, _sid in gate.INVENTORY_ROWS]
    assert not any("bed temp" in n or "temperature" in n for n in names), "a retired Eight Sleep signal is still named"
    eight = next(name for name, _keys, sid in gate.INVENTORY_ROWS if sid == "eightsleep")
    assert "temp" not in eight.lower(), f"{eight!r} still references temperature, which ADR-118 retired"


def test_the_new_rows_key_off_the_briefs_real_wire_keys():
    """Fixture must be the wire (#4361): the keys tuple for each new row must be the
    ACTUAL key `emails.daily_brief_lambda`'s gather-and-return `data` dict carries for
    that source, not a guessed name. Hevy is keyed `mf_workouts` (its legacy,
    MacroFactor-shaped name) despite the confusing name — `fetch_hevy_workouts` writes it."""
    by_source = {sid: keys for _n, keys, sid in gate.INVENTORY_ROWS if sid}
    assert by_source["hevy"] == ("mf_workouts",)
    assert by_source["habitify"] == ("habitify",)
    assert by_source["notion"] == ("journal_entries",)
    rendered_present = gate.data_inventory(
        {"mf_workouts": [{"id": "w1"}], "habitify": {"total_possible": 3}, "journal_entries": [{"date": "x"}]}
    )
    assert "  - Hevy strength training: AVAILABLE" in rendered_present
    assert "  - Habitify habits: AVAILABLE" in rendered_present
    assert "  - Notion journal: AVAILABLE" in rendered_present
    rendered_absent = gate.data_inventory({})
    assert "  - Hevy strength training: not available" in rendered_absent
    assert "  - Habitify habits: not available" in rendered_absent
    assert "  - Notion journal: not available" in rendered_absent


def test_registry_view_freezes_the_caveated_set_instead_of_reading_the_live_registry():
    """A replayed specimen must reproduce against the registry facts of the day it was caught.
    With a frozen view naming ONLY macrofactor, the Garmin sentence is not this gate's business
    (Garmin is not caveated in that view) — and with a view naming garmin as paused it is,
    whatever the live registry says. A view that names nothing is a gate that watches nothing."""
    assert gate.source_facet_findings(LIVE_GARMIN, registry_view={"macrofactor": "lagging"}) == []
    found = gate.source_facet_findings(LIVE_GARMIN, registry_view={"garmin": "paused"})
    assert found and found[0]["source"] == "garmin" and found[0]["status"] == "paused"
    assert gate.source_facet_findings(LIVE_GARMIN, registry_view={}) == []
    # production callers pass nothing and read the live registry — unchanged behaviour
    assert gate.source_facet_findings(LIVE_GARMIN)[0]["source"] == "garmin"
