"""#2343 — a same-day coach card published yesterday's recovery/HRV as current.

MEASURED, 2026-08-08 (all three mechanisms proposed at filing were wrong):

  /api/vitals              as_of_date 2026-08-08 · recovery 31.0 · hrv 32.0
  /api/coaching-dashboard  Dr. Marcus Webb, analysis_generated_at 2026-08-08T17:02:13Z
                           "… Whoop shows 55% recovery and HRV at 42 ms …"

55 / 42 are 2026-08-07's REAL Whoop readings, exact on both metrics — the day was
wrong, not the values, so an existence-based grounding check cannot see it.

THE PATH (acceptance item 1). The vital did NOT come from the nutrition persona's
fact block, which queries macrofactor only. `computed_metrics` is written for the
completed PREVIOUS day (daily-metrics-compute, 16:40 UTC), while /api/vitals resolves
the whoop partition directly — so the coach fact set is structurally one day behind
the cockpit. `ai_calls` injects it via `grounded_generation.authoritative_facts_block`
into the SHARED system prompt every persona receives.

The #1968 seam then worked exactly as designed: the DDB record for that render holds

  content: "… Whoop caught 55% recovery on the night of 2026-08-06, HRV at 42 ms,
            resting HR at 53 bpm …"

Dated. Checkable. But the field the dashboard publishes is `observatory_summary` — an
LLM condensation produced AFTER every grounding gate, which dropped the night and
re-framed the reading in the present tense. A grounded artifact condensed into an
ungrounded one, with nothing looking at the condensation.

These tests are built from the two verbatim strings above.
"""

import pytest
from ai import night_scope
from coach.reading_date_fidelity import dropped_reading_date_findings, guard_derived_summary, summary_keeps_reading_dates

# Verbatim from COACH#nutrition_coach / OUTPUT#2026-08-08#daily_brief_nutrition.
LIVE_NARRATIVE = (
    "Four days without a food log. That's the hard constraint right now — not motivation, not the plan "
    "itself, but the missing data. The wearables are still running — Whoop caught 55% recovery on the "
    "night of 2026-08-06, HRV at 42 ms, resting HR at 53 bpm — so the passive picture is intact. What "
    "I can't see is what you ate."
)
LIVE_SUMMARY = (
    "Four days without food logs has created a hard constraint on everything else. I can see your "
    "wearables data — Whoop shows 55% recovery and HRV at 42 ms — but without meal logs, I can't assess "
    "whether your 190g protein target is actually distributed across meals in a way that drives muscle "
    "protein synthesis."
)


class TestTheMeasuredIncident:
    def test_the_live_condensation_is_caught(self):
        findings = dropped_reading_date_findings(LIVE_SUMMARY, source_text=LIVE_NARRATIVE)
        by_metric = {f["metric"]: f for f in findings}
        assert "recovery_pct" in by_metric, "the 55% the reader saw as today's must fire"
        assert "hrv_ms" in by_metric, "the 42 ms the reader saw as today's must fire"
        assert by_metric["recovery_pct"]["claimed"] == 55.0
        assert by_metric["hrv_ms"]["claimed"] == 42.0
        for f in findings:
            assert f["type"] == "dropped_reading_date"
            assert f["source_night"] == "2026-08-06"

    def test_the_source_narrative_itself_is_honest(self):
        """The narrative dated the reading — this gate must not accuse it."""
        assert dropped_reading_date_findings(LIVE_NARRATIVE, source_text=LIVE_NARRATIVE) == []

    def test_a_condensation_that_keeps_the_night_passes(self):
        """The repair the guard is asking for, and the mutation control for it."""
        repaired = (
            "Four days without food logs has created a hard constraint on everything else. I can see your "
            "wearables data — Whoop caught 55% recovery on the night of 2026-08-06 and HRV at 42 ms — but "
            "without meal logs, I can't assess whether your 190g protein target is distributed."
        )
        assert dropped_reading_date_findings(repaired, source_text=LIVE_NARRATIVE) == []

    def test_a_condensation_that_drops_the_figure_passes(self):
        """ "Drop the figure rather than its day" must actually be an accepted way out."""
        dropped = (
            "Four days without food logs has created a hard constraint on everything else. The wearables "
            "are still running, so the passive picture is intact — what I can't see is what you ate."
        )
        assert dropped_reading_date_findings(dropped, source_text=LIVE_NARRATIVE) == []


class TestPointTheCardAtThePriorDay:
    """Acceptance item 3, mutation-proved: point a card at the prior day's row and watch
    it fire. The narrative is regenerated against yesterday's reading (which is what the
    day-behind `computed_metrics` record actually hands every persona); the condensation
    then presents it with no day on it."""

    @pytest.mark.parametrize(
        "night,recovery,hrv",
        [("2026-08-07", 55, 42), ("2026-08-06", 44, 35), ("2026-07-31", 61, 48)],
    )
    def test_undated_restatement_of_a_prior_day_reading_fires(self, night, recovery, hrv):
        source = f"Whoop logged {recovery}% recovery on the night of {night}, with HRV at {hrv} ms."
        summary = f"Right now Whoop shows {recovery}% recovery and HRV at {hrv} ms."
        findings = dropped_reading_date_findings(summary, source_text=source)
        assert {f["metric"] for f in findings} == {"recovery_pct", "hrv_ms"}
        assert all(f["source_night"] == night for f in findings)

    def test_naming_the_wrong_day_is_its_own_finding(self):
        source = "Whoop logged 55% recovery on the night of 2026-08-06, with HRV at 42 ms."
        summary = "Whoop logged 55% recovery on the night of 2026-08-04."
        findings = dropped_reading_date_findings(summary, source_text=source)
        assert [f["type"] for f in findings] == ["reading_date_mismatch"]
        assert findings[0]["summary_night"] == "2026-08-04"
        assert findings[0]["source_night"] == "2026-08-06"


class TestScope:
    """A guard that fires on correct writing gets switched off. These pin the edges."""

    def test_a_figure_the_source_never_dated_is_not_adjudicated(self):
        """Unknown means unknown (ADR-104) — the narrative's own honesty is #1968's job."""
        assert dropped_reading_date_findings(LIVE_SUMMARY, source_text="Whoop caught 55% recovery, HRV at 42 ms.") == []

    def test_a_different_value_is_not_the_same_reading(self):
        source = "Whoop caught 55% recovery on the night of 2026-08-06."
        assert dropped_reading_date_findings("Whoop shows 31% recovery.", source_text=source) == []

    def test_a_relative_temporal_token_is_left_to_the_date_gates(self):
        source = "Whoop caught 55% recovery on the night of 2026-08-06."
        assert dropped_reading_date_findings("Yesterday Whoop caught 55% recovery.", source_text=source) == []

    def test_a_target_restated_with_the_same_number_does_not_fire(self):
        source = "You slept 7.5 hours on the night of 2026-08-06."
        assert dropped_reading_date_findings("Aim for 7.5 hours of sleep tonight.", source_text=source) == []

    def test_empty_inputs_are_inert(self):
        assert dropped_reading_date_findings("", source_text=LIVE_NARRATIVE) == []
        assert dropped_reading_date_findings(LIVE_SUMMARY, source_text="") == []
        assert dropped_reading_date_findings(None, source_text=None) == []


class TestWhyTheExistingGatesMissedIt:
    """Two structural reasons, both pinned so a later edit cannot quietly restore them."""

    def test_the_night_gate_skips_the_published_sentence_on_its_modal_guard(self):
        """`night_scoped_vitals_findings` is armed on every coach render and still saw
        nothing: its modal guard skips any sentence containing "can", and the published
        sentence opens "I can see your wearables data …". Documented, not fixed here —
        widening that guard changes behaviour for every caller of the narrative gate."""
        assert night_scope.night_scoped_vitals_findings(LIVE_SUMMARY, nightly_vitals={}) == []

    def test_vital_claims_in_sees_the_sentence_the_night_gate_skips(self):
        claims = night_scope.vital_claims_in(LIVE_SUMMARY, skip_targets=False)
        assert ("recovery_pct", 55.0) in {(m, v) for m, v, _ in claims}
        assert ("hrv_ms", 42.0) in {(m, v) for m, v, _ in claims}

    def test_the_target_filter_alone_would_swallow_the_whole_sentence(self):
        """ "…your 190g protein target…" sits two clauses from the vitals; the #1968
        sentence-level target filter drops the lot. Hence `skip_targets=False`."""
        assert night_scope.vital_claims_in(LIVE_SUMMARY) == []


class TestWritePathWiring:
    """Guard the SET, not the instance: BOTH derived-summary write paths apply it."""

    def test_summary_keeps_reading_dates_rejects_to_none(self):
        cleaned, rejected, findings = summary_keeps_reading_dates(LIVE_SUMMARY, source_text=LIVE_NARRATIVE)
        assert cleaned is None and rejected is True and findings
        kept, rejected2, findings2 = summary_keeps_reading_dates(LIVE_NARRATIVE, source_text=LIVE_NARRATIVE)
        assert kept == LIVE_NARRATIVE and rejected2 is False and findings2 == []

    def test_coach_state_updater_write_path_nulls_the_summary(self, monkeypatch):
        """`_write_output_record` must not persist the undated condensation — the read
        sites' existing `observatory_summary or content` fallback then serves the dated
        narrative. Mutation-proof: with the guard bypassed, the bad text is persisted."""
        from coach import coach_state_updater as csu

        captured = {}
        monkeypatch.setattr(csu, "_put_item", lambda item: captured.update(item) or True)
        csu._write_output_record(
            "nutrition_coach", "2026-08-08", "daily_brief_nutrition", LIVE_NARRATIVE, {"observatory_summary": LIVE_SUMMARY}
        )
        assert captured["observatory_summary"] is None
        assert captured["content"] == LIVE_NARRATIVE  # the dated artifact still ships

        captured.clear()
        monkeypatch.setattr(csu, "guard_derived_summary", lambda s, *a, **kw: s)
        # #2418 put a SECOND, independent guard on this same write path — the ADR-104
        # grounding gate over the whole derived-prose set — and it catches this live
        # example too (the summary's "55" / "42" are in the narrative, but its
        # unlabeled figures trip the #1968 night class the gate now arms). Reproducing
        # the original defect therefore means bypassing both; that is the layering
        # working, and pinning it here is what stops a future edit deleting one guard
        # and reading the other's green as proof the first was never needed.
        monkeypatch.setattr(csu, "_gate_derived_prose", lambda coach_id, date, text, extraction: (extraction, []))
        csu._write_output_record(
            "nutrition_coach", "2026-08-08", "daily_brief_nutrition", LIVE_NARRATIVE, {"observatory_summary": LIVE_SUMMARY}
        )
        assert captured["observatory_summary"] == LIVE_SUMMARY, "both guards bypassed ⇒ the live defect is reproduced"

    def test_a_clean_summary_still_reaches_the_record(self, monkeypatch):
        from coach import coach_state_updater as csu

        good = "I caught 55% recovery on the night of 2026-08-06, with HRV at 42 ms. Log your meals."
        captured = {}
        monkeypatch.setattr(csu, "_put_item", lambda item: captured.update(item) or True)
        csu._write_output_record("nutrition_coach", "2026-08-08", "daily_brief_nutrition", LIVE_NARRATIVE, {"observatory_summary": good})
        assert captured["observatory_summary"] == good

    def test_both_derived_summary_writers_are_wired(self):
        """Guard the SET: the two places that persist an LLM condensation of a coach
        narrative both apply the check. A third writer added later without it is the
        recurrence, so this asserts on the write modules rather than on one call."""
        import inspect

        from coach import coach_state_updater
        from intelligence import intelligence_common

        for mod, field in ((coach_state_updater, "observatory_summary"), (intelligence_common, "position_summary")):
            src = inspect.getsource(mod)
            assert "guard_derived_summary(" in src, f"{mod.__name__} does not apply the #2343 check"
            assert f'"{field}"' in src

    def test_the_helper_is_inert_on_empty_input(self):
        assert guard_derived_summary("", "src", "position_summary") == ""
        assert guard_derived_summary(None, "src", "position_summary") is None


class TestFabricatedNumberFloor:
    """#2390 (AIQ-1's A-half): the re-parse is a second model call, and a
    condensation is not licensed to INTRODUCE data. The day-correspondence guard
    above catches a real figure losing its night; this floor catches a figure the
    source narrative never contained at all — which is how a summary invents a
    reading no existence check downstream can distinguish from data."""

    NARRATIVE = "On the night of 2026-08-06, WHOOP recorded a recovery score of 55% with HRV at 42 ms. I want protein at the floor before I trust the trend."

    def test_a_number_absent_from_the_source_narrative_rejects_the_summary(self):
        from coach.reading_date_fidelity import guard_derived_summary

        out = guard_derived_summary(
            "I'm seeing recovery in the low 60s and expecting 178 g protein days.", self.NARRATIVE, "position_summary"
        )
        assert out is None, "178 appears nowhere in the narrative — the condensation invented it"

    def test_a_summary_restating_the_narratives_own_figures_passes(self):
        from coach.reading_date_fidelity import guard_derived_summary

        s = "On the night of 2026-08-06 recovery was 55% — I'm watching HRV at 42 ms before calling it."
        assert guard_derived_summary(s, self.NARRATIVE, "position_summary") == s

    def test_a_numberless_summary_passes(self):
        from coach.reading_date_fidelity import guard_derived_summary

        s = "I'm cautious about the recovery trend and want more protein data before I move."
        assert guard_derived_summary(s, self.NARRATIVE, "position_summary") == s

    def test_the_rejection_composes_with_the_date_guard_not_instead_of_it(self):
        """Both classes live in one seam — a summary can fail EITHER. The date guard
        fires first on a dropped night; the number floor fires on an invented figure
        even when every dated figure kept its night."""
        from coach.reading_date_fidelity import guard_derived_summary

        dropped_night = "Whoop shows 55% recovery and HRV at 42 ms."
        assert guard_derived_summary(dropped_night, self.NARRATIVE, "position_summary") is None
        invented = "Night of 2026-08-06: recovery 55%. I project 91.4 kg by October."
        assert guard_derived_summary(invented, self.NARRATIVE, "position_summary") is None
