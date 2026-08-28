"""tests/test_behavioral_availability_2056.py — #2056: arming the #1699 gate beyond coach-v2.

The premise, measured on origin/main before any code was written: the ungrounded-
behavioral class was armed on 1 of 15 derived grounding surfaces, and 12 of the other 14
cited ONE shared exemption — "no per-generation-date log-availability map at this layer".
That sentence named a missing input, not a reason, so it could never be discharged.

Two things had to be true for a surface to arm HONESTLY, and both are tested here:

  1. A real map, derived from that day's actual log data — never guessed, never empty.
     `ai.behavior_logs` owns the derivations (a render payload, the stored engagement
     signal's per-channel `last_log_date`, a domain snapshot's `days_since_last_*`), each
     pure and each reading only records the caller already loaded.
  2. DECLARED COVERAGE. The pre-#2056 contract read absence from a bare set as "no log",
     which is only sound when the caller can see every category. A surface that can see
     food but not steps had to either stay dark or flag every step claim falsely — and a
     gate that fires when it simply could not see is how a gate gets switched off.
     `LogAvailability(present, covered)` makes "I cannot answer for this" sayable, and an
     unanswerable category is never a finding (ADR-104 behavioral-absence semantics).

The negative + positive proof the issue asks for is `TestArmedSurfaceProof` at the
bottom: on a newly-armed surface, a synthetic ungrounded same-day claim is flagged, the
same claim with the log present passes, and a claim in a category the surface CANNOT see
does not false-flag off the incomplete map.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import (
    behavior_logs as bl,  # noqa: E402
    grounded_generation as gg,  # noqa: E402
)


def _cats(findings):
    return sorted(f["category"] for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# 1. The coverage contract
# ─────────────────────────────────────────────────────────────────────────────


class TestCoverageContract:
    def test_bare_iterable_is_still_full_coverage(self):
        """The pre-#2056 contract, unchanged — coach-v2's armed behavior is bit-for-bit
        what it was. An empty set still means 'no logs today', so every same-day claim
        flags; that is the whole reason a guessed map is worse than none."""
        text = "You hit your steps today and you logged your meals today."
        assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=set())) == ["nutrition", "steps"]
        assert gg.ungrounded_behavioral_findings(text, available_logs={"steps", "nutrition"}) == []

    def test_uncovered_category_is_unknown_never_a_finding(self):
        """The #2056 change. `covered` says what the caller can answer for AT ALL."""
        text = "You hit your steps today."
        seen_food_only = bl.LogAvailability(present=frozenset(), covered=frozenset({"nutrition"}))
        assert gg.ungrounded_behavioral_findings(text, available_logs=seen_food_only) == []

    def test_covered_and_absent_still_flags(self):
        """Declared coverage must not become a way to switch the gate off quietly."""
        text = "You hit your steps today."
        sees_steps = bl.LogAvailability(present=frozenset(), covered=frozenset({"steps"}))
        assert _cats(gg.ungrounded_behavioral_findings(text, available_logs=sees_steps)) == ["steps"]

    def test_covered_and_present_passes(self):
        text = "You hit your steps today."
        logged = bl.LogAvailability(present=frozenset({"steps"}), covered=frozenset({"steps"}))
        assert gg.ungrounded_behavioral_findings(text, available_logs=logged) == []

    def test_none_still_opts_out(self):
        assert gg.ungrounded_behavioral_findings("You hit your steps today.", available_logs=None) == []

    def test_full_helper_covers_the_whole_vocabulary(self):
        full = bl.LogAvailability.full({"steps"})
        assert full.covered == frozenset(bl.LOG_CATEGORIES)
        assert full.present == frozenset({"steps"})

    def test_none_helper_answers_nothing(self):
        assert gg.ungrounded_behavioral_findings("You hit your steps today.", available_logs=bl.LogAvailability.none()) == []

    def test_tokens_outside_the_vocabulary_are_dropped_from_both_sets(self):
        """A stray token in `covered` would license a finding for a category no pattern
        can produce — both sets go through the one vocabulary."""
        a = bl.as_availability(bl.LogAvailability(present=frozenset({"Steps ", "bogus"}), covered=frozenset({"steps", "bogus"})))
        assert a.present == frozenset({"steps"})
        assert a.covered == frozenset({"steps"})

    def test_every_claim_pattern_category_is_in_the_vocabulary(self):
        """Guard the SET: a new claim pattern cannot introduce a category no derivation
        (and no caller's map) knows about."""
        pattern_cats = {c for c, _rx in bl._UB_CLAIM_PATTERNS}
        assert pattern_cats <= set(bl.LOG_CATEGORIES)
        # and the vocabulary carries no dead entry
        assert set(bl.LOG_CATEGORIES) == pattern_cats


# ─────────────────────────────────────────────────────────────────────────────
# 2. Derivation A — the stored engagement signal (per-channel last_log_date)
# ─────────────────────────────────────────────────────────────────────────────


def _signal(**channels):
    """An engagement_state STATE#current record shaped like engagement_core writes it."""
    return {
        "date": channels.pop("_date", "2026-08-06"),
        "experiment_window_start": channels.pop("_window", "2026-08-03"),
        "channel_detail": {src: {"last_log_date": d, "gap_days": 0} for src, d in channels.items()},
    }


class TestPresenceDerivation:
    def test_channel_logged_on_the_target_day_is_present(self):
        a = bl.available_logs_from_presence(_signal(macrofactor="2026-08-06", hevy="2026-08-06"), "2026-08-06")
        assert a.present == frozenset({"nutrition", "workout"})
        assert a.covered == frozenset({"nutrition", "workout"})

    def test_channel_whose_latest_log_predates_the_day_is_covered_absent(self):
        a = bl.available_logs_from_presence(_signal(macrofactor="2026-08-04"), "2026-08-06")
        assert a.present == frozenset()
        assert a.covered == frozenset({"nutrition"})

    def test_channel_whose_latest_log_is_LATER_is_unknown(self):
        """The record keeps only the most recent log date. A channel that logged today
        says nothing about whether it also logged the day before — so the honest answer
        for that earlier day is 'unknown', not 'absent'. This is the case that would
        false-flag the daily debrief, which narrates the latest COMPUTED day."""
        a = bl.available_logs_from_presence(_signal(macrofactor="2026-08-06"), "2026-08-05")
        assert a.covered == frozenset()

    def test_never_logged_inside_the_observed_window_is_covered_absent(self):
        a = bl.available_logs_from_presence(_signal(macrofactor=None), "2026-08-06")
        assert a.covered == frozenset({"nutrition"})
        assert a.present == frozenset()

    def test_never_logged_with_no_window_bound_is_unknown(self):
        sig = _signal(macrofactor=None)
        sig["experiment_window_start"] = None
        assert bl.available_logs_from_presence(sig, "2026-08-06").covered == frozenset()

    def test_a_signal_older_than_the_target_day_answers_nothing(self):
        """A presence record computed BEFORE the day being asked about cannot speak for
        it. Answering anyway would be the stale-read class #1691 exists for."""
        a = bl.available_logs_from_presence(_signal(_date="2026-08-04", macrofactor="2026-08-04"), "2026-08-06")
        assert a == bl.LogAvailability.none()

    def test_steps_and_eating_window_are_never_covered_by_presence(self):
        """Deliberate: steps come from a wearable that is not an engagement channel (and
        garmin is paused, ADR-074), and no channel records an eating window at all. They
        stay UNCOVERED rather than being reported absent — that distinction is the whole
        point of this module."""
        a = bl.available_logs_from_presence(_signal(macrofactor="2026-08-06", hevy="2026-08-06", notion="2026-08-06"), "2026-08-06")
        assert "steps" not in a.covered
        assert "eating_window" not in a.covered
        assert "fasting" not in a.covered

    @pytest.mark.parametrize("bad", [None, {}, {"date": None}, {"date": "2026-08-06"}, "not-a-dict"])
    def test_junk_input_answers_nothing_rather_than_raising(self, bad):
        assert bl.available_logs_from_presence(bad, "2026-08-06").covered == frozenset()

    def test_bad_target_date_answers_nothing(self):
        assert bl.available_logs_from_presence(_signal(macrofactor="2026-08-06"), None) == bl.LogAvailability.none()

    def test_channel_absent_from_the_record_is_not_covered(self):
        a = bl.available_logs_from_presence(_signal(macrofactor="2026-08-06"), "2026-08-06")
        assert a.covered == frozenset({"nutrition"})  # hevy/notion were never in the record

    def test_the_channel_map_matches_the_live_engagement_registry(self):
        """Guard the SET, not the instance: every channel this module claims to read must
        still BE an engagement channel, so a registry rename cannot silently disarm the
        derivation while the test suite stays green."""
        from content.engagement_core import MANUAL_CHANNELS

        assert set(bl.PRESENCE_CHANNEL_CATEGORIES) <= set(MANUAL_CHANNELS)
        assert set(bl.PRESENCE_CHANNEL_CATEGORIES.values()) <= set(bl.LOG_CATEGORIES)

    def test_derivation_agrees_with_a_real_compute_presence_record(self):
        """End-to-end against the actual writer, not a hand-shaped fixture."""
        from content.engagement_core import compute_presence

        sig = compute_presence(
            "2026-08-06",
            {"macrofactor": ["2026-08-06", "2026-08-05"], "hevy": ["2026-08-04"], "notion": []},
            experiment_start="2026-08-03",
        )
        a = bl.available_logs_from_presence(sig, "2026-08-06")
        assert "nutrition" in a.present  # logged that very day
        assert "journal" in a.covered and "journal" not in a.present  # nothing in-window
        # #3252: `workout` USED to read "covered, absent — last lift was 08-04". It no
        # longer can. The presence record carries Hevy and nothing else, while the
        # registry's workout denominator is hevy + strava + apple_health, so this
        # derivation has not consulted two of the three sources that could have recorded
        # a workout. Under the 2026-08-28 auto-sync ruling that makes the absence
        # unlicensed, not true — the exact shape that let /method/board/ say "no
        # training since August 17th" with two Strava activities in the window.
        assert "workout" not in a.covered and "workout" not in a.present


# ─────────────────────────────────────────────────────────────────────────────
# 3. Derivation B — a domain snapshot's days_since_last_* fields
# ─────────────────────────────────────────────────────────────────────────────


class TestRecencyDerivation:
    def test_zero_days_since_is_present(self):
        a = bl.available_logs_from_recency({"days_since_last_food_log": 0})
        assert a.present == frozenset({"nutrition"})
        assert a.covered == frozenset({"nutrition"})

    def test_positive_days_since_is_covered_absent(self):
        a = bl.available_logs_from_recency({"days_since_last_journal": 3})
        assert a.present == frozenset()
        assert a.covered == frozenset({"journal"})

    def test_a_hevy_only_lift_field_cannot_carry_a_workout_absence(self):
        """#3252: `days_since_last_lift` is computed from Hevy rows alone, so on its own
        it has consulted one of the three sources in the workout denominator. Absence
        demotes to uncovered; naming the other two restores it."""
        assert bl.available_logs_from_recency({"days_since_last_lift": 3}).covered == frozenset()
        named = bl.available_logs_from_recency({"days_since_last_lift": 3}, sources_observed=("strava", "apple_health"))
        assert named.covered == frozenset({"workout"}) and named.present == frozenset()

    def test_none_means_nothing_in_the_lookback_which_is_also_absent(self):
        """`_recency_stats` returns None when the whole window is empty. 'No log in 30
        days' is an answer, not an unknown."""
        a = bl.available_logs_from_recency({"days_since_last_journal": None})
        assert a.covered == frozenset({"journal"})
        assert a.present == frozenset()

    def test_a_field_the_snapshot_does_not_carry_is_uncovered(self):
        """This is the per-expert partial coverage: the nutrition snapshot answers for
        food and stays silent about training."""
        a = bl.available_logs_from_recency({"days_since_last_food_log": 0})
        assert a.covered == frozenset({"nutrition"})

    def test_unparseable_value_says_nothing(self):
        assert bl.available_logs_from_recency({"days_since_last_food_log": "soon"}).covered == frozenset()

    @pytest.mark.parametrize("bad", [None, {}, "nope", 7])
    def test_junk_input_answers_nothing(self, bad):
        assert bl.available_logs_from_recency(bad) == bl.LogAvailability.none()

    def test_fields_match_what_the_analyzer_actually_emits(self):
        """The derivation reads keys the integrator's snapshots really carry. If a
        snapshot renames one, this fails instead of the gate going quietly dark."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence", "ai_expert_analyzer_lambda.py")).read()
        for field in bl.RECENCY_FIELD_CATEGORIES:
            assert f'"{field}"' in src, f"{field} no longer appears in the analyzer's snapshots"

    def test_recency_stats_zero_round_trips_into_present(self):
        """The seam itself: `_recency_stats(days, today)[0] == 0` ⇒ present."""
        from intelligence.item_recency import recency_stats

        since, _ = recency_stats(["2026-08-04", "2026-08-06"], "2026-08-06")
        assert since == 0
        assert bl.available_logs_from_recency({"days_since_last_food_log": since}).present == frozenset({"nutrition"})


# ─────────────────────────────────────────────────────────────────────────────
# 4. The extracted recency helpers behave exactly as they did in the analyzer
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractedRecencyHelpers:
    def test_analyzer_still_exposes_the_private_aliases(self):
        """A re-export is not a patch point, but these ARE reached for by name in
        tests/test_presence_severity_and_ack.py — the aliases must survive the move."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))
        os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
        import ai_expert_analyzer_lambda as az

        assert az._recency_stats(["2026-06-29"], "2026-06-30") == (1, 1)
        assert az._item_dates([{"sk": "DATE#2026-06-29#X"}]) == {"2026-06-29"}
        assert az._latest_date([{"sk": "DATE#2026-06-29"}, {"sk": "DATE#2026-07-01"}]) == "2026-07-01"

    def test_helpers_ignore_non_date_sort_keys(self):
        from intelligence.item_recency import item_dates, latest_date

        rows = [{"sk": "DATE#2026-06-29"}, {"sk": "STATE#current"}, {}]
        assert item_dates(rows) == {"2026-06-29"}
        assert latest_date(rows) == "2026-06-29"

    def test_empty_is_honest_defaults(self):
        from intelligence.item_recency import latest_date, recency_stats

        assert latest_date([]) is None
        assert recency_stats([], "2026-06-30") == (None, 0)
        assert recency_stats(None, "2026-06-30") == (None, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. The census — what the registry says, asserted rather than described
# ─────────────────────────────────────────────────────────────────────────────


class TestSurfaceCensus:
    def test_the_behavioral_class_arms_on_more_than_coach_v2(self):
        from grounding_wiring import SURFACES, scan_tree

        armed = {k for k, v in scan_tree().items() if "behavioral" in v}
        assert "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline" in armed  # the incumbent
        for newly in (
            "lambdas/ai/ai_calls.py::_ground_legacy_output",
            "lambdas/emails/daily_debrief_lambda.py::narrate",
            "lambdas/compute/state_of_matthew_lambda.py::narration_gate",
            # #2421 renamed this surface: the analyzer's four previously ungated paths
            # joined `generate_and_cache` behind one `_gate_prose` chokepoint.
            "lambdas/intelligence/ai_expert_analyzer_lambda.py::_gate_prose",
            # #2195 — #2056's one recorded residual, armed once its cost was measured.
            "lambdas/coach/coach_history_summarizer.py::_apply_grounding_gate",
        ):
            assert newly in armed, f"{newly} lost its #1699 wiring"
        # and the registry POLICY agrees with what the tree actually does
        assert {k for k, v in SURFACES.items() if "behavioral" in v["required"]} == armed

    def test_no_surface_cites_a_blanket_missing_map_exemption_any_more(self):
        """The #2056 outcome in one assertion: the one exemption 12 surfaces shared is
        gone, and no reason is cited by a majority of the exempt set (which is what an
        un-actionable placeholder looks like)."""
        from grounding_wiring import SURFACES

        reasons = [v["exempt"]["behavioral"] for v in SURFACES.values() if "behavioral" in v["exempt"]]
        assert reasons, "the census should still have exempt surfaces — this is honest partial, not a claim of 100%"
        assert not any("no per-generation-date log-availability map at this layer" in r for r in reasons)
        most_shared = max(reasons.count(r) for r in set(reasons))
        assert most_shared <= len(reasons) // 2 + 1, "one reason is doing too much work again"

    def test_every_exempt_surface_states_a_real_reason(self):
        from grounding_wiring import SURFACES

        for key, entry in SURFACES.items():
            reason = entry["exempt"].get("behavioral")
            if reason is None:
                continue
            assert len(reason) > 80, f"{key}: exemption reason is too thin to be a decision"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Negative + positive proof on a newly-armed surface (the issue's AC3)
# ─────────────────────────────────────────────────────────────────────────────


class TestArmedSurfaceProof:
    """Driven through `daily_debrief_lambda.narrate`'s ACTUAL gate composition — the
    same `grounding_findings` call the live path makes, with a real engagement record."""

    UNGROUNDED = "You logged your meals today and the day held together."
    GROUNDED = "You logged your meals today and the day held together."
    UNSEEN = "You hit your steps today and the day held together."

    def _findings(self, text, sig, date_iso):
        return gg.grounding_findings(
            text,
            facts=None,
            allowed={"1"},
            available_logs=bl.available_logs_from_presence(sig, date_iso),
        )

    def test_negative_ungrounded_same_day_claim_is_flagged(self):
        sig = _signal(macrofactor="2026-08-04")  # last food log two days before the day narrated
        found = self._findings(self.UNGROUNDED, sig, "2026-08-06")
        assert [f["type"] for f in found] == ["ungrounded_behavioral"]
        assert found[0]["category"] == "nutrition"

    def test_positive_same_claim_with_the_log_present_passes(self):
        sig = _signal(macrofactor="2026-08-06")
        assert self._findings(self.GROUNDED, sig, "2026-08-06") == []

    def test_no_false_flag_from_a_category_the_surface_cannot_see(self):
        """The failure this design exists to prevent: the debrief's record says nothing
        about steps, so a step claim must NOT be flagged off an incomplete map."""
        sig = _signal(macrofactor="2026-08-06")
        assert self._findings(self.UNSEEN, sig, "2026-08-06") == []

    def test_advice_framing_is_still_not_a_completed_action_claim(self):
        sig = _signal(macrofactor="2026-08-04")
        assert self._findings("Try to log your meals today.", sig, "2026-08-06") == []

    def test_prior_period_claim_is_still_out_of_scope(self):
        sig = _signal(macrofactor="2026-08-04")
        assert self._findings("Last week you logged your meals every day.", sig, "2026-08-06") == []

    def test_the_debrief_gate_is_genuinely_wired_to_this_map(self):
        """Not a re-implementation: narrate() must pass the derived map. Proved by
        calling the real function with the model stubbed out."""
        import ai.bedrock_client as bc
        import emails.daily_debrief_lambda as dd

        facts = {"date": "2026-08-06", "day_grade": "B", "day_grade_score": 81}
        sig = _signal(macrofactor="2026-08-04")

        def _fake_invoke(_body, model_name=None):
            return {"content": [{"text": "You logged your meals today. The grade was 81."}]}

        real = bc.invoke
        bc.invoke = _fake_invoke
        try:
            armed = dd.narrate(facts, "", presence_signal=sig)
            unarmed = dd.narrate(facts, "")
        finally:
            bc.invoke = real
        assert armed["narrated"] is False and armed["reason"] == "grounding_gate"
        assert unarmed["narrated"] is True, "without the signal the class must stay unarmed — the opt-out contract"


class TestLegacyBriefSurfaceProof:
    """The other newly-armed shape: full coverage from the daily-brief render payload.

    `_ground_legacy_output` gates the four legacy coach calls (BoD, training+nutrition,
    journal, TL;DR). They sit inside the SAME render coach-v2 gates and see the same
    `data` dict, so the map is the real full-coverage one — which is why the negative
    case here flags a category (steps) the presence-derived surfaces must leave alone.
    """

    def _run(self, draft, data):
        import ai.ai_calls as ac

        return ac._ground_legacy_output(
            "unit_test",
            draft,
            lambda _corr: "",  # no rewrite — keep the original, findings are what we assert
            "recovery 68",
            available_logs=ac._available_logs_for_today(data, None, None),
        )

    def test_journal_entries_ground_a_same_day_journal_claim(self):
        """The #2056 widening: without `data["journal_entries"]` feeding the map, arming
        these surfaces would have reported 'no journal log' on a day Matthew journaled."""
        import ai.ai_calls as ac

        logs = ac._available_logs_for_today({"journal_entries": [{"raw_text": "wrote a bit"}]}, None, None)
        assert "journal" in logs
        assert "journal" not in ac._available_logs_for_today({}, None, None)

    def test_coach_v2_map_is_still_a_bare_full_coverage_set(self):
        """The incumbent surface's contract is untouched — a bare set, read as full
        coverage, so its behavior is bit-for-bit what #1699 shipped."""
        import ai.ai_calls as ac

        logs = ac._available_logs_for_today({"garmin": {"steps": 9000}}, {"journal_mood": 4}, "2026-08-06")
        assert isinstance(logs, set) and not isinstance(logs, bl.LogAvailability)
        assert bl.as_availability(logs).covered == frozenset(bl.LOG_CATEGORIES)

    def test_gate_is_reached_through_the_legacy_harness(self):
        """Negative: a same-day step claim with no garmin data in the render flags, and
        the harness keeps the draft (its regen offered nothing better) — the #966
        keep-if-strictly-improved disposition these four surfaces already had."""
        import ai.ai_calls as ac

        draft = "You hit your steps today."
        assert self._run(draft, {"macrofactor": {"calories": 1800}}) == draft
        found = gg.ungrounded_behavioral_findings(
            draft, available_logs=ac._available_logs_for_today({"macrofactor": {"calories": 1800}}, None, None)
        )
        assert [f["category"] for f in found] == ["steps"]

    def test_positive_same_claim_with_garmin_present_passes(self):
        import ai.ai_calls as ac

        found = gg.ungrounded_behavioral_findings(
            "You hit your steps today.",
            available_logs=ac._available_logs_for_today({"garmin": {"steps": 9000}}, None, None),
        )
        assert found == []
