"""tests/test_partial_gate_cluster_2430.py — #2430's designed exit from UNGATED_READER_KNOWN.

Four reader-facing generators each carried a REAL deterministic check and none of them
resolved to a registered grounding decision. That is a distinct failure from "ungated":
the check that existed looked like a gate, so nobody asked what it did not cover.

  * the daily reflection ran ER-03 per reflection — correlative, hedged, no number
    outside the facts — and nothing about dates or the cycle anchor;
  * the quarterly memoir ran fabricated_numbers + the cites_a_miss bar, over a QUARTER,
    with no date class and no span/Day-N class;
  * the meal-photo probe had the #1390 partition isolation as its whole contract, which
    is a data-isolation guarantee, not a claim check on the one string it writes;
  * the podcast has three deterministic per-line gates plus the panelcast_qa judges, and
    it is AT its size-guard cap — so its outcome is a WRITTEN exemption naming the classes
    it does not arm, not a registration, and not a raised baseline.

This file pins the registration half + the mutation proof. Behavior lives with each
module's own tests.
"""

import os

REFLECTION = "lambdas/compute/coach_daily_reflection_lambda.py"
MEMOIR = "lambdas/compute/coach_memoir_lambda.py"
EYEBALL = "lambdas/experiment/eyeball_calibration.py"
PODCAST = "lambdas/emails/coach_panel_podcast_lambda.py"

ARMED = {
    f"{REFLECTION}::_grounding_findings": REFLECTION,
    f"{MEMOIR}::gate_check": MEMOIR,
    f"{EYEBALL}::_grounded_note": EYEBALL,
}
REQUIRED_CLASSES = {"numbers", "dates", "freshness"}


class TestTheThreeArmedSurfaces:
    def test_each_is_registered_and_actually_arms_its_classes(self):
        from grounding_wiring import SURFACES, scan_tree

        found = scan_tree()
        for key in ARMED:
            assert key in SURFACES, f"{key} must be a registered grounding surface"
            assert REQUIRED_CLASSES <= found[key], f"{key} arms only {sorted(found[key])}"
            assert SURFACES[key]["required"] == frozenset(REQUIRED_CLASSES)

    def test_every_unarmed_class_carries_a_written_reason(self):
        """A one-line exemption records that nobody looked (the registry's own header)."""
        from grounding_wiring import GATE_CLASSES, SURFACES

        for key in ARMED:
            entry = SURFACES[key]
            assert entry["required"] | set(entry["exempt"]) == set(GATE_CLASSES)
            for cls, reason in entry["exempt"].items():
                assert len(reason) >= 120, f"{key}/{cls}: an exemption this short is a gesture"

    def test_stripping_a_gate_call_deregisters_its_surface(self):
        """Mutation proof: break the gate, and the derivation loses the surface — which
        is what wiring's stale-entry check and the census's bucket check red on."""
        from grounding_wiring import REPO, scan_source

        for key, module in ARMED.items():
            src = open(os.path.join(REPO, module), encoding="utf-8").read()
            assert key in scan_source(module, src), "precondition: the scan is not vacuous"
            sabotaged = src.replace("grounding_findings(", "disabled_findings(")
            assert key not in scan_source(module, sabotaged), f"stripping the gate must deregister {key}"

    def test_disarming_a_single_class_reds_rather_than_silently_narrowing(self):
        """The #1967 failure mode: a caller drops one kwarg and coverage shrinks with
        nothing failing. Drop `allowed_dates` and the surface must stop arming `dates`."""
        from grounding_wiring import REPO, scan_source

        for key, module in ARMED.items():
            src = open(os.path.join(REPO, module), encoding="utf-8").read()
            narrowed = src.replace("allowed_dates=", "unused_dates=")
            armed = scan_source(module, narrowed).get(key, set())
            assert "dates" not in armed, f"{key} still claims the dates class with allowed_dates removed"


class TestCensusLedger:
    def test_the_three_left_the_tracked_defect_table_as_surfaces(self):
        import test_invoke_site_census_2390 as census

        for module in (REFLECTION, MEMOIR, EYEBALL):
            assert module in census.SITES, f"precondition: {module} still references a model seam"
            assert module not in census.UNGATED_READER_KNOWN, f"{module} must exit the tracked-defect table via SURFACES"
            assert census.classify(module, census.SURFACE_MODULES) == ["surfaces"]

    def test_the_podcast_carries_a_written_exemption_that_names_what_it_misses(self):
        import test_invoke_site_census_2390 as census

        assert census.classify(PODCAST, census.SURFACE_MODULES) == ["exemption"]
        entry = census.EXEMPTIONS[PODCAST]
        assert entry["destination"] == census.READER_DECLARED_PARTIAL
        reason = entry["reason"]
        # The class exists only if the entry does the three things it demands.
        assert "er03_gate.er03_check" in reason, "must say what the deterministic gate DOES check"
        for cls in ("dates", "night-scope", "behavioral"):
            assert cls in reason, f"the unarmed class {cls!r} must be NAMED, not implied"
        assert "1904" in reason and "test_module_size_guard" in reason, "must say why it is declared rather than registered"

    def test_the_podcast_docstring_points_at_the_written_record(self):
        """An exemption nobody can find from the code it exempts is not a record."""
        from grounding_wiring import REPO

        head = open(os.path.join(REPO, PODCAST), encoding="utf-8").read()[:3000]
        assert "#2430" in head and "test_invoke_site_census_2390.py::EXEMPTIONS" in head


class TestPodcastStaysAtItsCap:
    def test_the_exemption_did_not_cost_the_file_a_single_line(self):
        """#2430's sanctioned outcome was ZERO net lines and no raised baseline. The size
        guard would catch growth; this catches the OTHER half — a baseline moved to make
        room, which the guard cannot see because it only compares against whatever the
        baseline currently says."""
        from grounding_wiring import REPO
        from test_module_size_guard import BASELINE

        assert BASELINE[PODCAST] == 1904, "the podcast baseline must not move for #2430 — the exemption exists so it does not have to"
        with open(os.path.join(REPO, PODCAST), encoding="utf-8") as fh:
            assert sum(1 for _ in fh) <= 1904
