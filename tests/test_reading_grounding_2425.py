"""tests/test_reading_grounding_2425.py — #2425's designed exit from UNGATED_READER_KNOWN.

The reading shelf (`reading_enrich`) and the constellation (`reading_constellation`)
published LLM fields onto the reading public allowlists with prompt-level instructions
as the only grounding — the posture ADR-104 rejects, called out by name in the same
package's `horizons_retrospective`. The fix is per-field-honest:

  * enrich: closed vocabularies validated DETERMINISTICALLY (domainTags/era — an
    out-of-vocabulary value never ships; the prompt is generated from the same
    constants), difficulty clamped in code, and the one free-text field (themes)
    crossing the numbers/dates/freshness chokepoint against the assembled prompt;
  * constellation: every idea label/gist crossing the chokepoint against the owner's
    own quoted words (the prompt's stated grounding contract, made code).

This file pins the REGISTRATION half: both modules are SURFACES entries, the census
classifies them as covered, and stripping either gate call deregisters the surface —
which is exactly what the wiring test (`test_registry_has_no_stale_entries`) and the
census's unclassified check red on. Behavior tests live with each module's own tests
(test_reading_enrich.py / test_reading_constellation.py).
"""

import os

ENRICH = "lambdas/reading/reading_enrich.py"
CONSTELLATION = "lambdas/reading/reading_constellation.py"
ENRICH_SURFACE = f"{ENRICH}::_grounded_themes"
CONSTELLATION_SURFACE = f"{CONSTELLATION}::_idea_grounding_findings"


class TestRegisteredSurfacesAndCensus:
    def test_both_surfaces_are_registered_and_armed(self):
        from grounding_wiring import SURFACES, scan_tree

        found = scan_tree()
        for key in (ENRICH_SURFACE, CONSTELLATION_SURFACE):
            assert key in SURFACES, f"{key} must be a registered grounding surface"
            assert {"numbers", "dates", "freshness"} <= found[key], f"{key} arms only {sorted(found[key])}"

    def test_census_counts_both_modules_as_covered(self):
        import test_invoke_site_census_2390 as census

        for module in (ENRICH, CONSTELLATION):
            assert module not in census.UNGATED_READER_KNOWN, f"{module} must exit the tracked-defect table via SURFACES"
            assert module in census.SITES, f"precondition: {module} still references a model seam"
            assert census.classify(module, census.SURFACE_MODULES) == ["surfaces"]

    def test_stripping_either_gate_call_deregisters_the_surface(self):
        """Mutation proof (acceptance box 4): remove the chokepoint call and the
        derivation loses the surface, so wiring's stale-entry check and the
        census's surfaces-bucket classification both red."""
        from grounding_wiring import REPO, scan_source

        for module, key in ((ENRICH, ENRICH_SURFACE), (CONSTELLATION, CONSTELLATION_SURFACE)):
            src = open(os.path.join(REPO, module), encoding="utf-8").read()
            sabotaged = src.replace("grounding_findings(", "disabled_findings(")
            assert key not in scan_source(module, sabotaged), f"stripping the gate must deregister {key}"
            # and the un-sabotaged source really is discovered (the scan is not vacuous)
            assert key in scan_source(module, src)
