"""#3252 box 2 — a narrative asserting an absence must NAME the sources it checked.

THE BOX
-------
    A grounded-generation check asserts that any narrative asserting an absence names the
    sources it checked, so an auto-synced source cannot be silently excluded.

THE RULING IT ENCODES (owner, 2026-08-28, ADR-104 amendment)
------------------------------------------------------------
An auto-synced source counts as logging. If the data arrived, it was logged, whether or
not Matthew typed it — so "you didn't log a run" is WRONG when Strava synced one. The
check is therefore "name every source you consulted", not "name the manual ones".

WHY THERE IS NO PHRASE LIST IN HERE
-----------------------------------
Every phrase-matched member of the #2959/#3003/#3199 demotion family has failed in the
field, and "an absence claim" has no reliable surface form. The structural signal is the
GROUNDING FACT that licensed the sentence — an `AbsenceTransition` whose kind is
`never_logged`/`paused`, or a `LogAvailability` category that is covered-and-not-present.
Both are computed in code before any model runs (ADR-105), so the check grades the
platform's own claim instead of guessing at English. `test_the_check_cannot_phrase_match`
proves the module contains no regex and no text parameter at all.
"""

import ast
import pathlib

import pytest
from ai import absence_sourcing as asrc, behavior_logs as bl
from ingestion.source_registry import SOURCE_REGISTRY, evidence_sources_by_category

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "lambdas" / "ai" / "absence_sourcing.py"

# The live ground truth quoted in #3252 (DynamoDB, 2026-08-28), verbatim: the window the
# board declared empty of training contained two Strava activities.
WINDOW_START = "2026-08-17"
TODAY = "2026-08-28"
STRAVA_ROWS = ("2026-08-17", "2026-08-18")


# ─────────────────────────────────────────────────────────────────────────────
# 1. The denominator is DERIVED from the registry — not stated here, not stated there
# ─────────────────────────────────────────────────────────────────────────────
class TestDenominatorIsDerived:
    def test_the_auto_synced_source_is_in_the_workout_denominator(self):
        """Strava carries no `engagement_channel` and is not a manual log. It is still
        evidence, which is the whole ruling."""
        assert "strava" in asrc.evidence_sources("workout")
        assert "hevy" in asrc.evidence_sources("workout")
        assert SOURCE_REGISTRY["strava"].get("engagement_channel") is None

    def test_the_module_hard_codes_no_source_id(self):
        """A hand-typed "sources that count" list would reintroduce the same class one
        layer up. Proven by AST: no string constant anywhere in the module equals a
        registry source id."""
        tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        # The module docstring names Strava/Garmin as narrative examples; only bare
        # source-id literals (the shape a lookup would use) are the defect.
        assert literals & set(SOURCE_REGISTRY) == set()

    def test_every_declared_category_is_in_the_one_vocabulary(self):
        """`evidence_for` speaks LOG_CATEGORIES or it speaks nothing — a token no gate
        knows would be a denominator nobody can consult."""
        assert set(evidence_sources_by_category()) <= set(bl.LOG_CATEGORIES)

    def test_a_category_no_source_records_is_unsourceable_not_absent(self):
        """Nothing in the pipeline records an eating window. "He broke his window" is
        therefore never establishable from ingest evidence, and saying so is the honest
        answer — not a clean absence."""
        assert asrc.evidence_sources("eating_window") == ()
        g = asrc.absence_sourcing("eating_window", sources_observed=("macrofactor", "hevy", "strava"))
        assert g.kind == asrc.KIND_UNSOURCEABLE and not g.licenses_absence


# ─────────────────────────────────────────────────────────────────────────────
# 2. The detector is structural
# ─────────────────────────────────────────────────────────────────────────────
class TestStructuralNotPhraseMatched:
    def test_the_check_cannot_phrase_match(self):
        """No `re` import, no regex, and no text parameter: the check is structurally
        incapable of pattern-matching prose, so it cannot join the #3199 family."""
        src = _MODULE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert "re" not in imported
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "unsourced_absence_findings")
        params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
        assert "text" not in params and "narrative" not in params

    def test_only_the_two_absence_kinds_are_checked(self):
        """`logged` has no absence in it and `unknown` licenses nothing; grading either
        would be the check guessing."""
        for kind in (bl.TRANSITION_LOGGED, bl.TRANSITION_UNKNOWN):
            tr = bl.AbsenceTransition("workout", kind, None, None, WINDOW_START)
            assert asrc.unsourced_absence_findings({"workout": tr}, sources_observed=("hevy",)) == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. The live defect, replayed through the REAL presence writer
# ─────────────────────────────────────────────────────────────────────────────
def _real_signal():
    """The engagement_state record `engagement_core.compute_presence` actually writes for
    the #3252 window: MacroFactor and Hevy empty, Notion empty. Strava is NOT a presence
    channel — which is precisely why its two activities were invisible to the claim."""
    from content.engagement_core import compute_presence

    return compute_presence(TODAY, {"macrofactor": [], "hevy": [], "notion": []}, experiment_start=WINDOW_START)


class TestTheLiveDefect:
    def test_the_presence_signal_cannot_carry_a_training_absence(self):
        sig = _real_signal()
        assert "strava" not in (sig.get("channel_detail") or {})  # the silent exclusion, on the wire
        a = bl.available_logs_from_presence(sig, TODAY)
        assert "workout" not in a.covered  # unknown — never licensed, never flagged
        assert "nutrition" in a.covered  # MacroFactor IS the whole nutrition denominator

    def test_the_transition_demotes_to_unknown(self):
        sig = _real_signal()
        assert bl.transition_from_presence_signal(sig, "nutrition").kind == bl.TRANSITION_NEVER_LOGGED
        assert bl.transition_from_presence_signal(sig, "workout").kind == bl.TRANSITION_UNKNOWN

    def test_the_finding_names_what_was_checked_and_what_was_not(self):
        tr = bl.AbsenceTransition("workout", bl.TRANSITION_NEVER_LOGGED, None, None, WINDOW_START)
        found = asrc.unsourced_absence_findings({"workout": tr}, sources_observed=("hevy",))
        assert len(found) == 1
        f = found[0]
        assert f["type"] == "unsourced_absence" and f["kind"] == asrc.KIND_UNSOURCED
        assert f["checked"] == ["hevy"] and "strava" in f["unchecked"]
        assert "strava" in f["detail"] and "hevy" in f["detail"]

    def test_naming_every_source_licenses_the_claim(self):
        """The positive control. Consult all three and the absence is a true statement
        again — the check narrows claims, it does not ban them."""
        tr = bl.AbsenceTransition("workout", bl.TRANSITION_NEVER_LOGGED, None, None, WINDOW_START)
        observed = asrc.evidence_sources("workout")
        assert asrc.unsourced_absence_findings({"workout": tr}, sources_observed=observed) == []
        g = asrc.absence_sourcing("workout", sources_observed=observed)
        assert g.licenses_absence and set(g.checked) == set(observed)

    def test_a_strava_activity_inside_the_window_is_a_log(self):
        """The ruling, stated as data: an auto-synced activity in the window means the
        category is PRESENT, and a present category is never demoted."""
        avail = bl.LogAvailability(frozenset({"workout"}), frozenset({"workout"}), frozenset({("workout", STRAVA_ROWS[-1])}))
        out = asrc.sourced_availability(avail, sources_observed=("hevy",))
        assert out.present == frozenset({"workout"}) and "workout" in out.covered


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stale is not absent (#3268)
# ─────────────────────────────────────────────────────────────────────────────
class TestStaleIsNotAbsent:
    def test_a_paused_source_makes_the_claim_stale_not_absent(self):
        """Garmin is paused (ADR-074). A step absence resting on it is a hole in the
        record, and `stale` is a different sentence from `sourced`."""
        assert SOURCE_REGISTRY["garmin"].get("paused") is True
        g = asrc.absence_sourcing("steps", sources_observed=asrc.evidence_sources("steps"))
        assert g.kind == asrc.KIND_STALE and g.stale == ("garmin",) and not g.licenses_absence
        assert "not a confirmed absence" in g.narrative_input().lower() or "NOT a confirmed absence" in g.narrative_input()

    def test_a_dark_infrastructure_source_is_stale(self):
        """Apple Health pushes without Matthew's participation, so its silence is a
        broken pipe, not a fact about him."""
        g = asrc.absence_sourcing(
            "workout",
            sources_observed=("hevy", "strava", "apple_health"),
            source_last_dates={"hevy": None, "strava": None, "apple_health": None},
            window_start=WINDOW_START,
        )
        assert g.kind == asrc.KIND_STALE and g.stale == ("apple_health",)

    def test_a_quiet_BEHAVIORAL_source_is_the_absence_itself(self):
        """The asymmetry that makes the distinction usable: MacroFactor's last upload
        predating the window IS the nutrition absence. Grading it `stale` would delete
        the one true absence claim the platform has."""
        assert SOURCE_REGISTRY["macrofactor"]["behavioral"] is True
        g = asrc.absence_sourcing(
            "nutrition",
            sources_observed=("macrofactor",),
            source_last_dates={"macrofactor": "2026-07-14"},
            window_start=WINDOW_START,
        )
        assert g.kind == asrc.KIND_SOURCED and g.licenses_absence

    def test_the_three_unlicensed_kinds_never_license(self):
        for kind in (asrc.KIND_STALE, asrc.KIND_UNSOURCED, asrc.KIND_UNSOURCEABLE):
            assert kind in asrc.SOURCING_KINDS
        assert [k for k in asrc.SOURCING_KINDS if k != asrc.KIND_SOURCED] == [
            asrc.KIND_STALE,
            asrc.KIND_UNSOURCED,
            asrc.KIND_UNSOURCEABLE,
        ]


# ─────────────────────────────────────────────────────────────────────────────
# 5. The must-fail case — the check has to be able to say no
# ─────────────────────────────────────────────────────────────────────────────
class TestTheCheckCanFail:
    def test_a_short_denominator_MUST_produce_a_finding(self):
        """The negative control, made to actually fail. If `unsourced_absence_findings`
        ever degraded to `return []` — the dark-gate shape #2578 counts — this assertion
        is the one that reds. Paired with `test_naming_every_source_licenses_the_claim`
        above (the positive control), which reds if it degraded to "always flag"."""
        tr = bl.AbsenceTransition("workout", bl.TRANSITION_PAUSED, "2026-08-20", 8, WINDOW_START)
        assert asrc.unsourced_absence_findings({"workout": tr}, sources_observed=("hevy",)) != []

    def test_the_fail_closed_demotion_MUST_remove_the_category(self):
        """Same shape for `sourced_availability`: if it degraded to returning its input,
        this reds."""
        avail = bl.LogAvailability(frozenset(), frozenset({"workout"}), frozenset({("workout", "2026-08-20")}))
        out = asrc.sourced_availability(avail, sources_observed=("hevy",))
        assert "workout" not in out.covered and not out.knows_last_date("workout")

    def test_the_transition_demotion_MUST_change_the_kind(self):
        tr = bl.AbsenceTransition("workout", bl.TRANSITION_NEVER_LOGGED, None, None, WINDOW_START)
        out = asrc.sourced_transitions({"workout": tr}, sources_observed=("hevy",))
        assert out["workout"].kind == bl.TRANSITION_UNKNOWN

    def test_a_bad_input_never_raises(self):
        for junk in (None, "", 0, [], {"workout": "not a transition"}):
            assert asrc.unsourced_absence_findings(junk, sources_observed=("hevy",)) == []
        assert asrc.sourced_availability(None, sources_observed=()) is None
        with pytest.raises(AssertionError):
            # Sanity: the suite's own assertions are live, not vacuous.
            assert asrc.absence_sourcing("workout", sources_observed=("hevy",)).licenses_absence
