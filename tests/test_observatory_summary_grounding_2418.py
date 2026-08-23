"""tests/test_observatory_summary_grounding_2418.py — the derived reader prose, gated (#2418).

WHAT THE ISSUE SAID, AND WHAT THE CENSUS MEASURED
-------------------------------------------------
#2418 named `observatory_summary` — the coach-analysis text readers actually see,
because the serving paths prefer it over the gated `content` — and named three of them.
Measuring the module on 2026-08-10 found SIX, and found something the issue did not:

  * `site_api_coach_narrative.py`  — `observatory_summary or content`
  * `site_api_lambda.py`           — `position_summary or observatory_summary or content`
  * `coach_observatory_renderer.py`— `observatory_summary or content`
  * `site_api_coach_profile.py`    — `key_recommendation or observatory_summary or ""`
  * `coach_panel_podcast_lambda.py`— `key_recommendation or observatory_summary or ""`
  * `coach_daily_reflection_lambda.py` — `key_recommendation or observatory_summary or ""`

On HALF the paths `key_recommendation` — a second condensation from the same model call,
with no guard of any kind on it — outranks the field the issue was about. Gating
`observatory_summary` alone would have left the actually-served text ungated on three
surfaces and reported green. So the unit here is the SET (`coach_derived_prose`
.DERIVED_PROSE_FIELDS), and the three `or ""` chains now end at `content`.

The tests below are in three groups: the derived consumer census (guard the SET), the
gate's behaviour (regenerate-once-then-HOLD, and never take the lane down), and the
mutation proofs the acceptance asks for.
"""

import ast
import os

import grounding_wiring
import pytest
from grounding_wiring import REPO, SURFACES, scan_source
from test_invoke_site_census_2390 import EXEMPTIONS, SITES, UNGATED_READER_KNOWN, classify, surface_modules

coach_derived_prose = pytest.importorskip("coach.coach_derived_prose")
csu = pytest.importorskip("coach.coach_state_updater")

WRITER = "lambdas/coach/coach_state_updater.py"
SURFACE_KEY = "lambdas/coach/coach_state_updater.py::_gate_derived_prose"

# The three that read the field directly and already ended their chain at `content`.
DIRECT_READERS = frozenset(
    {
        "lambdas/web/site_api_coach_narrative.py",
        # site_api_lambda LEFT this set deliberately (#2972): its one read was the
        # public dashboard blurb slot, which now serves ONLY the audience-guarded
        # `public_summary` (coach/audience_guard.public_blurb) — the coaching-register
        # fallthrough to observatory_summary/content was the audience_violation defect.
        "lambdas/coach/coach_observatory_renderer.py",
    }
)
# The three that ended at `or ""` and now go through the shared read seam.
HELPER_READERS = frozenset(
    {
        "lambdas/web/site_api_coach_profile.py",
        "lambdas/emails/coach_panel_podcast_lambda.py",
        "lambdas/compute/coach_daily_reflection_lambda.py",
    }
)

NARRATIVE = (
    "On the night of 2026-08-06 Whoop caught 55% recovery, with HRV at 42 ms and resting HR at 53 bpm. "
    "You logged four meals against a 190 g protein target. I'd hold the load this week."
)


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _modules_reading(field):
    """Every module under lambdas/ with a literal ``X.get("<field>")`` — derived, not listed."""
    hits = set()
    for base, dirs, files in os.walk(os.path.join(REPO, "lambdas")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(base, name), REPO)
            source = _read(rel)
            if field not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == field
                ):
                    hits.add(rel)
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# 1. THE CONSUMER CENSUS — guard the SET, not the instance
# ══════════════════════════════════════════════════════════════════════════════


class TestTheSixServingPaths:
    def test_every_direct_reader_of_the_summary_is_known(self):
        """A seventh publisher of the ungated condensation must fail here, not ship."""
        assert _modules_reading("observatory_summary") == set(DIRECT_READERS) | {WRITER}, (
            "a module reads observatory_summary that this census does not know about. Add it to "
            "DIRECT_READERS (and give it a `content` fallback) or route it through "
            "coach_derived_prose.served_summary — an ungated condensation with no fallback is #2418 itself."
        )

    def test_every_direct_reader_falls_back_to_content_in_the_same_expression(self):
        """`observatory_summary` and `content` must be alternatives of ONE `or` chain.

        Structural rather than textual: a `content` read somewhere else in the module is
        not a fallback. The BoolOp is the fallback.
        """
        for rel in sorted(DIRECT_READERS):
            chains = [
                node
                for node in ast.walk(ast.parse(_read(rel)))
                if isinstance(node, ast.BoolOp) and "'observatory_summary'" in ast.dump(node) and "'content'" in ast.dump(node)
            ]
            assert chains, f"{rel} reads observatory_summary without `content` as an alternative in the same or-chain"

    def test_the_helper_readers_route_through_the_shared_seam(self):
        """The three that used to end at `or ""` — a held condensation left them blank."""
        for rel in sorted(HELPER_READERS):
            source = _read(rel)
            assert "coach_derived_prose.served_summary(" in source, f"{rel} no longer uses the shared derived-prose read seam"
            assert 'observatory_summary") or ""' not in source, f"{rel} still ends its chain at the empty string"

    def test_the_census_is_five_paths(self):
        # Six until #2972 moved site_api_lambda's dashboard blurb slot off
        # observatory_summary entirely (see the DIRECT_READERS note above).
        assert len(DIRECT_READERS | HELPER_READERS) == 5

    def test_a_held_record_still_serves_the_gated_narrative(self):
        """The whole point of the fallback: HOLD degrades, it does not blank."""
        held = {"observatory_summary": None, "key_recommendation": None, "content": NARRATIVE}
        served = coach_derived_prose.served_summary(held)
        assert served and served.startswith("On the night of 2026-08-06")
        assert coach_derived_prose.served_summary({"key_recommendation": "Hold the load.", "content": NARRATIVE}) == "Hold the load."
        assert coach_derived_prose.served_summary({}) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE GATE — regenerate once, then HOLD; never take the lane down
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def captured(monkeypatch):
    box = {}
    monkeypatch.setattr(csu, "_put_item", lambda item: box.update(item) or True)
    return box


def _no_model(monkeypatch):
    """The regen must not reach a model in these tests; if it does, say so loudly."""

    def _boom(*a, **kw):
        raise AssertionError("the gate called the model when the test did not stub one")

    monkeypatch.setattr(csu, "_call_haiku", _boom)


def _model_returns(monkeypatch, payload):
    calls = []

    def _fake(system=None, user_message=None, max_tokens=None, temperature=None):
        calls.append(user_message)
        return payload

    monkeypatch.setattr(csu, "_call_haiku", _fake)
    return calls


class TestRegenerateOrHold:
    def test_a_fabricated_number_in_the_summary_holds_the_whole_derived_set(self, captured, monkeypatch):
        """The #2418 class end to end. The condensation states a figure the narrative
        never contained; the one regen (stubbed to repeat the offence) does not fix it,
        so the derived set is HELD and the read sites serve `content`."""
        _model_returns(monkeypatch, {"observatory_summary": "Your HRV sat at 133 ms all week.", "key_recommendation": None})
        csu._write_output_record(
            "sleep_coach",
            "2026-08-08",
            "daily_brief",
            NARRATIVE,
            {
                "observatory_summary": "Your HRV sat at 133 ms all week, so I'd hold the load.",
                "key_recommendation": "Hold the load this week.",
                "elena_quote": "The sleep coach is not looking at his meals.",
                "themes": ["hrv_recovery"],
            },
        )
        assert captured["observatory_summary"] is None
        assert captured["key_recommendation"] is None, "the SET is held — key_recommendation outranks the summary on three paths"
        assert captured["elena_quote"] is None
        assert captured["derived_prose_held"] is True, "a grounding HOLD must be distinguishable from an empty extraction"
        assert "133" not in str(captured.get("observatory_summary"))
        assert captured["content"] == NARRATIVE, "the coach's own gated narrative still ships"
        assert captured["themes"] == ["hrv_recovery"], "the record and the state machine are untouched — this holds a condensation"

    def test_a_fabrication_in_key_recommendation_alone_also_holds(self, captured, monkeypatch):
        """Guard the SET: the field the issue did not name is the one three paths serve first."""
        _model_returns(monkeypatch, {"key_recommendation": "Push to 9,000 steps."})
        csu._write_output_record(
            "sleep_coach",
            "2026-08-08",
            "daily_brief",
            NARRATIVE,
            {"observatory_summary": "I caught 55% recovery on the night of 2026-08-06.", "key_recommendation": "Push to 9,000 steps."},
        )
        assert captured["key_recommendation"] is None and captured["observatory_summary"] is None
        assert captured["derived_prose_held"] is True

    def test_one_corrective_regen_can_save_the_condensation(self, captured, monkeypatch):
        """regenerate-OR-hold: a faithful rewrite is kept and nothing is held."""
        faithful = "I caught 55% recovery on the night of 2026-08-06, with HRV at 42 ms. I'd hold the load."
        calls = _model_returns(monkeypatch, {"observatory_summary": faithful, "key_recommendation": "Hold the load.", "elena_quote": None})
        csu._write_output_record(
            "sleep_coach",
            "2026-08-08",
            "daily_brief",
            NARRATIVE,
            {"observatory_summary": "Your HRV sat at 133 ms all week.", "key_recommendation": "Hold the load."},
        )
        assert len(calls) == 1, "exactly ONE corrective regeneration — never a loop"
        assert captured["observatory_summary"] == faithful
        assert "derived_prose_held" not in captured

    def test_a_faithful_condensation_never_reaches_the_model(self, captured, monkeypatch):
        """A gate that regenerates on clean text is a gate that doubles the AI bill."""
        _no_model(monkeypatch)
        good = "I caught 55% recovery on the night of 2026-08-06, with HRV at 42 ms. I'd hold the load this week."
        csu._write_output_record("sleep_coach", "2026-08-08", "daily_brief", NARRATIVE, {"observatory_summary": good})
        assert captured["observatory_summary"] == good

    def test_an_extraction_with_no_derived_prose_is_left_alone(self, captured, monkeypatch):
        _no_model(monkeypatch)
        csu._write_output_record("sleep_coach", "2026-08-08", "daily_brief", NARRATIVE, {"themes": ["sleep"]})
        assert captured["observatory_summary"] is None and "derived_prose_held" not in captured

    def test_a_failing_regeneration_holds_and_does_not_raise(self, captured, monkeypatch):
        """FAIL-CLOSED ON THE ARTIFACT, NEVER ON THE LANE (#2503 -> #2510).

        A raising model call inside the gate must cost the condensation and nothing
        else: the OUTPUT# record is still written, so coach state keeps being written
        even when Bedrock is down or the budget tier has cut inference off.
        """

        def _explode(*a, **kw):
            raise RuntimeError("bedrock is down")

        monkeypatch.setattr(csu, "_call_haiku", _explode)
        csu._write_output_record(
            "sleep_coach", "2026-08-08", "daily_brief", NARRATIVE, {"observatory_summary": "Your HRV sat at 133 ms all week."}
        )
        assert captured["derived_prose_held"] is True
        assert captured["content"] == NARRATIVE

    def test_the_night_class_is_armed_from_the_source_narrative(self):
        """#1968, honestly armed: the map is the SOURCE's own dated claims, so a
        condensation that re-dates a reading is adjudicated rather than waved through."""
        from ai.night_scope import nightly_vitals_from_narrative

        night_map = nightly_vitals_from_narrative(NARRATIVE)
        assert night_map.get("2026-08-06", {}).get("recovery_pct") == 55
        assert night_map.get("2026-08-06", {}).get("hrv_ms") == 42
        # A narrative that dates nothing arms the label class and adjudicates nothing —
        # never a guessed authority (ADR-104).
        assert nightly_vitals_from_narrative("Recovery was fine and HRV looked flat.") == {}


class TestTheHoldIsScopedToTheArtifact:
    def test_hold_nulls_only_the_derived_prose(self):
        held = coach_derived_prose.hold({"observatory_summary": "x", "key_recommendation": "y", "themes": ["a"], "content": "n"})
        # The whole set — four since #2972 added public_summary — derived, not hand-counted.
        assert [held[f] for f in coach_derived_prose.DERIVED_PROSE_FIELDS] == [None] * len(coach_derived_prose.DERIVED_PROSE_FIELDS)
        assert len(coach_derived_prose.DERIVED_PROSE_FIELDS) == 4
        assert held["themes"] == ["a"] and held["content"] == "n"

    def test_hold_does_not_mutate_the_caller(self):
        original = {"observatory_summary": "x"}
        coach_derived_prose.hold(original)
        assert original["observatory_summary"] == "x"

    def test_the_blob_is_prose_only(self):
        blob = coach_derived_prose.prose_blob({"observatory_summary": "A.", "key_recommendation": "B.", "structural_fingerprint": {"p": 4}})
        assert blob == "A.\n\nB." and "4" not in blob, "structured extraction metadata must never be graded as prose"


# ══════════════════════════════════════════════════════════════════════════════
# 3. MUTATION PROOFS — acceptance box 4
# ══════════════════════════════════════════════════════════════════════════════


class TestMutationProof:
    def test_the_live_surface_arms_all_four_required_classes(self):
        armed = scan_source(WRITER, _read(WRITER)).get(SURFACE_KEY)
        assert armed is not None, f"{SURFACE_KEY} is not a derived grounding surface — the chokepoint call left the module"
        assert (
            SURFACES[SURFACE_KEY]["required"] <= armed
        ), f"registered as arming {sorted(SURFACES[SURFACE_KEY]['required'])}, actually arms {sorted(armed)}"
        assert {"numbers", "dates", "freshness", "night"} <= armed

    def test_removing_the_gate_call_deregisters_the_surface(self):
        """Delete the chokepoint call and the wiring registry stops seeing the surface —
        which is what makes the SURFACES entry evidence rather than a claim."""
        mutated = _read(WRITER).replace("grounding_findings(\n", "dict(\n", 1)
        assert mutated != _read(WRITER), "the mutation did not mutate — the call shape moved"
        assert SURFACE_KEY not in scan_source(WRITER, mutated)

    def test_a_deregistered_surface_reds_the_2390_census(self):
        """And with the surface gone the module is unclassified: it is no longer in
        UNGATED_READER_KNOWN (that is what #2418 closed), so nothing catches it."""
        assert WRITER in SITES, "precondition: the writer still reaches the model"
        assert classify(WRITER, surface_modules()) == ["surfaces"], "the acceptance bar: registered, with NO exemption"
        assert WRITER not in UNGATED_READER_KNOWN and WRITER not in EXEMPTIONS
        assert (
            classify(WRITER, surface_modules() - {WRITER}) == []
        ), "deregistering must leave the module unclassified — the census's whole job"

    def test_dropping_a_gate_class_reds_the_wiring_registry(self):
        """The per-class half: silently dropping `nightly_vitals` must not pass."""
        mutated = _read(WRITER).replace("            nightly_vitals=_nights,\n", "", 1)
        assert mutated != _read(WRITER)
        armed = scan_source(WRITER, mutated).get(SURFACE_KEY, set())
        assert "night" not in armed
        assert not SURFACES[SURFACE_KEY]["required"] <= armed, "the registry must red when a required class is disarmed"

    def test_the_registry_entry_writes_a_reason_for_the_one_exempt_class(self):
        exempt = SURFACES[SURFACE_KEY]["exempt"]
        assert set(exempt) == {"behavioral"}
        assert len(exempt["behavioral"]) >= 200, "an exemption reason short enough to skim is a gesture"
        assert set(SURFACES[SURFACE_KEY]["required"]) | set(exempt) == set(grounding_wiring.GATE_CLASSES)

    def test_bypassing_the_gate_reproduces_the_defect(self, captured, monkeypatch):
        """The behavioural half: a mutation must actually mutate.

        The defect used here is a fabrication in `key_recommendation`, deliberately —
        it is the field with NO other guard (`guard_derived_summary` covers
        `observatory_summary` alone, which is why bypassing this gate would not visibly
        change that field). It is also the field three of the six paths serve FIRST, so
        this is the marginal thing #2418 bought, isolated.
        """
        monkeypatch.setattr(csu, "_gate_derived_prose", lambda coach_id, date, text, extraction: (extraction, []))
        bad = "Push to 9,000 steps this week."
        csu._write_output_record("sleep_coach", "2026-08-08", "daily_brief", NARRATIVE, {"key_recommendation": bad})
        assert captured["key_recommendation"] == bad, "gate bypassed ⇒ the ungated condensation is persisted"
