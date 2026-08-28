"""#2382 — the deterministic absence-transition guard.

THE DEFECT, restated so a future reader does not have to reconstruct it.

Six of the eight public coach cards narrated the genesis-clamped food-log gap as an event
that never happened — "your food logs paused four days ago", "You've been quiet since
Tuesday", "dark since around August 2nd" — while the last MacroFactor row was 2026-06-24
and the cockpit one door away honestly said "MACROFACTOR 44D AGO". Food logging was
already ~39 days dark AT genesis. Nothing paused on Aug 4; there was nothing to pause.

The mechanism was structural, not a model failure. `engagement_core.compute_presence`
handed down `gap_days=4` (the #955 clamp, measuring the CYCLE WINDOW) together with
`last_food_log_date=None`, and `LogAvailability` carried category SETS with no dates —
so "never logged in this window" and "logged, then stopped four days ago" were the same
shape downstream. Every consumer that wanted to describe the silence had to guess.

PR #2394 fixed the PROMPT: the never-logged branch now states the true fact and forbids
the pause phrasing. That was the right first half and it is not sufficient — prompt rules
cannot guarantee structure (the 0/15 podcast-gate precedent). This file covers the second
half, in three layers:

  1. `LogAvailability.last_dates` — the availability object carries DATES, with three
     distinguishable answers (a real date / known-none / unknown), not two.
  2. `absence_transition()` — the narrative input is DERIVED IN CODE from those dates
     before any model is involved (ADR-105), and `never_logged` cannot carry a day-count
     by construction. That is the load-bearing claim, and `TestNeverLoggedCannotSayPaused`
     is its proof.
  3. `absence_transition_findings()` — the output-side guard: a stop/pause/went-quiet
     framing about a channel with no in-window last-log date is a finding.

MUTATION PROOF lives in `TestMutationProof` at the bottom: it sabotages the derivation the
way a careless refactor would (collapsing known-none back into unknown, and letting the
window's age leak onto the channel as a day-count) and asserts the guard turns RED. A
guard that stays green under sabotage has proved nothing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import behavior_logs as bl  # noqa: E402

GENESIS = "2026-08-03"
TODAY = "2026-08-07"


def _signal(*, food_last, window=GENESIS, date=TODAY, gap_days=4):
    """An engagement_state STATE#current record in the shape compute_presence writes.

    `food_last=None` is the live #2382 case: the clamp reports a 4-day window gap with no
    food log date anywhere in it.
    """
    return {
        "date": date,
        "presence_class": "dark",
        "severity": "loud",
        "gap_days": gap_days,
        "last_food_log_date": food_last,
        "experiment_window_start": window,
        "channels_quiet": ["food"],
        "returned": False,
        "channel_detail": {
            "macrofactor": {"last_log_date": food_last, "gap_days": gap_days},
            "hevy": {"last_log_date": "2026-08-05", "gap_days": 2},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. The structure: availability carries dates, with THREE answers not two
# ─────────────────────────────────────────────────────────────────────────────


class TestLogAvailabilityCarriesDates:
    def test_the_two_set_constructor_still_works_unchanged(self):
        """The #2056 contract is load-bearing on nine surfaces. The new field is a
        defaulted third element, so every existing construction site still compiles and
        still compares equal to what it compared equal to before."""
        a = bl.LogAvailability(present=frozenset({"nutrition"}), covered=frozenset({"nutrition"}))
        assert a.present == frozenset({"nutrition"})
        assert a.last_dates == frozenset()
        assert bl.LogAvailability(frozenset(), frozenset()) == bl.LogAvailability.none()

    def test_known_date_known_none_and_unknown_are_three_distinct_answers(self):
        """The whole point of the change. Before it, the middle case was unsayable."""
        a = bl.LogAvailability(
            frozenset(),
            frozenset({"nutrition", "workout"}),
            frozenset({("nutrition", None), ("workout", "2026-08-05")}),
        )
        assert a.knows_last_date("nutrition") and a.last_date("nutrition") is None  # known: never
        assert a.knows_last_date("workout") and a.last_date("workout") == "2026-08-05"  # known: date
        assert not a.knows_last_date("journal") and a.last_date("journal") is None  # unknown

    def test_a_junk_date_degrades_to_unknown_not_to_never_logged(self):
        """Direction matters: guessing "never" from an unparseable value would manufacture
        exactly the certainty this field exists to withhold."""
        a = bl.as_availability(bl.LogAvailability(frozenset(), frozenset({"nutrition"}), frozenset({("nutrition", "soon")})))
        assert not a.knows_last_date("nutrition")

    def test_dates_survive_as_availability_normalisation(self):
        a = bl.as_availability(bl.LogAvailability(frozenset(), frozenset({"nutrition"}), frozenset({("NUTRITION ", "2026-08-05")})))
        assert a.last_date("nutrition") == "2026-08-05"

    def test_a_bare_set_caller_still_gets_full_coverage_and_no_dates(self):
        a = bl.as_availability({"steps"})
        assert a.covered == frozenset(bl.LOG_CATEGORIES)
        assert a.last_dates == frozenset()

    def test_the_presence_derivation_now_carries_the_dates_it_already_read(self):
        a = bl.available_logs_from_presence(_signal(food_last="2026-08-05"), TODAY)
        assert a.last_date("nutrition") == "2026-08-05"
        # #3252: the workout date the signal carries is Hevy's, and Hevy is one of three
        # sources in the registry's workout denominator. An absence derived from it is
        # unlicensed, so the derivation drops the category rather than handing a short
        # claim onward — `knows_last_date` is the honest answer, and it is False.
        assert not a.knows_last_date("workout")

    def test_the_recency_derivation_reconstructs_dates_when_given_a_reference(self):
        a = bl.available_logs_from_recency({"days_since_last_food_log": 3}, reference_date=TODAY)
        assert a.last_date("nutrition") == "2026-08-04"

    def test_recency_without_a_reference_is_byte_identical_for_existing_callers(self):
        """No existing caller passes the new argument; none may change behaviour."""
        data = {"days_since_last_food_log": 3, "days_since_last_lift": 0}
        a = bl.available_logs_from_recency(data)
        assert (a.present, a.covered) == (frozenset({"workout"}), frozenset({"nutrition", "workout"}))
        assert a.last_dates == frozenset()

    def test_recency_none_is_the_known_never_logged_answer(self):
        """`_recency_stats` returns None when the whole lookback is empty — an answer."""
        a = bl.available_logs_from_recency({"days_since_last_journal": None}, reference_date=TODAY)
        assert a.knows_last_date("journal") and a.last_date("journal") is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. The derivation: the narrative input is computed, not narrated
# ─────────────────────────────────────────────────────────────────────────────


class TestNeverLoggedCannotSayPaused:
    """THE load-bearing class. If any of these ever fails, #2382 has regressed."""

    def test_the_live_defect_case_derives_never_logged_not_paused(self):
        tr = bl.transition_from_presence_signal(_signal(food_last=None))
        assert tr.kind == bl.TRANSITION_NEVER_LOGGED
        assert tr.licenses_transition is False

    def test_never_logged_carries_no_day_count_and_no_date_at_all(self):
        """The clamp's `gap_days=4` is a fact about the WINDOW. Attaching it to the
        channel is how "39 days quiet" became "paused four days ago"; there is no code
        path that can attach it, whatever the caller passes in."""
        for gap in (0, 4, 39, 44, 10_000):
            tr = bl.transition_from_presence_signal(_signal(food_last=None, gap_days=gap))
            assert tr.days_since_last_log is None
            assert tr.last_log_date is None

    def test_the_derived_narrative_input_states_the_absence_and_forbids_the_event(self):
        text = bl.transition_from_presence_signal(_signal(food_last=None)).narrative_input()
        assert "nothing logged at any point in this window" in text
        assert "NO transition happened" in text
        assert "days before the reference day" not in text

    @pytest.mark.parametrize("banned", ["paused", "stopped", "went quiet", "days ago", "since "])
    def test_no_transition_vocabulary_can_reach_the_never_logged_input(self, banned):
        """Property-style: whatever the record says, the never-logged sentence never
        contains a transition word or a countable gap."""
        for gap in (None, 0, 4, 44):
            text = bl.transition_from_presence_signal(_signal(food_last=None, gap_days=gap)).narrative_input()
            assert banned not in text.lower()

    def test_a_real_in_window_gap_IS_licensed_and_carries_the_true_count(self):
        """The negative control. The fix must not lobotomise the honest case — when a log
        really does exist and really did stop, "four days ago" is TRUE and must survive."""
        tr = bl.transition_from_presence_signal(_signal(food_last="2026-08-03"))
        assert tr.kind == bl.TRANSITION_PAUSED
        assert tr.licenses_transition is True
        assert (tr.last_log_date, tr.days_since_last_log) == ("2026-08-03", 4)
        assert "4 days before the reference day" in tr.narrative_input()

    def test_a_log_on_the_reference_day_is_no_absence_at_all(self):
        tr = bl.transition_from_presence_signal(_signal(food_last=TODAY))
        assert tr.kind == bl.TRANSITION_LOGGED
        assert tr.licenses_transition is False

    def test_a_record_that_does_not_carry_the_fact_is_unknown_not_never_logged(self):
        sig = _signal(food_last=None)
        del sig["last_food_log_date"]
        sig["channel_detail"]["macrofactor"] = {"gap_days": 4}
        tr = bl.transition_from_presence_signal(sig)
        assert tr.kind == bl.TRANSITION_UNKNOWN
        assert tr.licenses_transition is False
        assert "no answer available" in tr.narrative_input()

    def test_a_real_date_with_no_reference_day_is_unknown_not_paused(self):
        """A transition asserted without a measured gap is the thing this refuses."""
        sig = _signal(food_last="2026-08-03")
        sig["date"] = None
        assert bl.transition_from_presence_signal(sig).kind == bl.TRANSITION_UNKNOWN

    @pytest.mark.parametrize("junk", [None, {}, "not-a-dict", 7, {"channel_detail": "nope"}])
    def test_junk_input_answers_unknown_rather_than_raising(self, junk):
        assert bl.transition_from_presence_signal(junk).kind == bl.TRANSITION_UNKNOWN

    def test_only_paused_ever_licenses_a_transition(self):
        """Guard the SET: the licensing predicate is one kind, and adding a kind without
        deciding its licensing fails here rather than shipping a permissive default."""
        licensed = {
            k for k in bl.ABSENCE_TRANSITION_KINDS if bl.AbsenceTransition("nutrition", k, "2026-08-03", 4, GENESIS).licenses_transition
        }
        assert licensed == {bl.TRANSITION_PAUSED}


# ─────────────────────────────────────────────────────────────────────────────
# 3. The output-side guard
# ─────────────────────────────────────────────────────────────────────────────

# Verbatim from the live cards the run-3 panel captured. These are the sentences the
# platform actually published; each one must be a finding.
LIVE_FABRICATIONS = [
    "Your food logs paused four days ago, Matthew.",
    "The food logging has been dark since around August 2nd.",
    "You stopped logging meals about four days ago.",
    "Your nutrition tracking went silent four days ago.",
    "It's been four days since you logged a meal.",
    "Your meal tracking went quiet four days ago.",
]

# The DOCUMENTED LIMIT, kept as a test rather than a comment so it cannot quietly widen.
# "You've been quiet since Tuesday, Matthew" was one of the six live cards, and this guard
# cannot attribute it: it names no channel, and on that same day the habits channel had
# genuinely gone quiet (habitify last logged 08-03), so the sentence is TRUE of one channel
# and false of another. A heuristic that guessed would flag an honest sentence. The
# unattributed form stays the derivation's job (the block never hands a coach a bare
# day-count for a never-logged channel), not the text guard's.
UNATTRIBUTABLE = "You've been quiet since Tuesday, Matthew."


class TestTheGuardFlagsTheFabricatedTransition:
    @pytest.fixture
    def never_logged(self):
        return bl.absence_transitions(
            bl.LogAvailability(frozenset(), frozenset({"nutrition"}), frozenset({("nutrition", None)})),
            TODAY,
            GENESIS,
        )

    @pytest.mark.parametrize("sentence", LIVE_FABRICATIONS)
    def test_every_published_fabrication_is_a_finding(self, never_logged, sentence):
        found = bl.absence_transition_findings(sentence, transitions=never_logged)
        assert found, f"the guard missed a sentence the platform actually published: {sentence!r}"
        assert found[0]["type"] == "fabricated_absence_transition"
        assert found[0]["category"] == "nutrition"

    def test_the_unattributable_sentence_is_a_known_limit_not_a_finding(self, never_logged):
        """Pinned deliberately. See UNATTRIBUTABLE above: no channel is named, and the
        habits channel really had gone quiet that day, so flagging it would grade a true
        sentence. If a future change makes the guard fire here, that is a decision to
        make on purpose — this test is where it gets made."""
        assert bl.absence_transition_findings(UNATTRIBUTABLE, transitions=never_logged) == []

    def test_the_honest_phrasing_is_not_a_finding(self, never_logged):
        honest = (
            "Nothing has been logged yet this cycle, Matthew — no food log at any point in it. "
            "I can't see a single meal, and I'm not going to pretend I know why."
        )
        assert bl.absence_transition_findings(honest, transitions=never_logged) == []

    def test_a_REAL_pause_is_never_flagged(self):
        """The false-positive control: with a real in-window last-log date, "paused four
        days ago" is true, and a guard that flags a true sentence is noise."""
        real = bl.absence_transitions(
            bl.LogAvailability(frozenset(), frozenset({"nutrition"}), frozenset({("nutrition", "2026-08-03")})),
            TODAY,
            GENESIS,
        )
        for sentence in LIVE_FABRICATIONS:
            assert bl.absence_transition_findings(sentence, transitions=real) == []

    def test_an_unknown_category_never_flags(self):
        """ADR-104 at the gate's own input: a gate that fires when it merely could not see
        is not a truth pass, it is noise that gets the gate switched off."""
        unknown = bl.absence_transitions(bl.LogAvailability(frozenset(), frozenset({"nutrition"})), TODAY, GENESIS)
        assert unknown == {}
        for sentence in LIVE_FABRICATIONS:
            assert bl.absence_transition_findings(sentence, transitions=unknown) == []

    def test_a_transition_about_a_DIFFERENT_channel_is_not_flagged(self):
        """The habits half of those same sentences was genuinely true (habitify last
        logged 08-03) — the fabrication was specifically the FOOD channel's transition."""
        never_logged_food = bl.absence_transitions(
            bl.LogAvailability(frozenset(), frozenset({"nutrition"}), frozenset({("nutrition", None)})),
            TODAY,
            GENESIS,
        )
        assert bl.absence_transition_findings("Your lifting stopped four days ago.", transitions=never_logged_food) == []

    def test_it_accepts_a_single_transition_as_well_as_a_map(self):
        tr = bl.transition_from_presence_signal(_signal(food_last=None))
        assert bl.absence_transition_findings("Your food logs paused four days ago.", transitions=tr)

    @pytest.mark.parametrize("junk", [None, {}, "nope", 7, {"nutrition": "not-a-transition"}])
    def test_junk_transitions_return_no_findings_rather_than_raising(self, junk):
        assert bl.absence_transition_findings("Your food logs paused four days ago.", transitions=junk) == []

    def test_the_gate_is_reachable_from_the_grounded_generation_entrypoint(self):
        """Import-path guard: every other gate in this family is consumed through
        `grounded_generation`, so a caller must be able to reach this one the same way."""
        from ai import grounded_generation as gg

        assert gg.absence_transition_findings is bl.absence_transition_findings
        assert gg.AbsenceTransition is bl.AbsenceTransition


# ─────────────────────────────────────────────────────────────────────────────
# 4. The seam: the surface where #2382 actually fired
# ─────────────────────────────────────────────────────────────────────────────


class TestPresenceBlockDerivesItsBranch:
    def test_the_never_logged_block_carries_the_derived_ground_truth_line(self):
        from content.engagement_core import presence_prompt_block

        block = presence_prompt_block(_signal(food_last=None))
        assert "GROUND TRUTH (derived, not narrated):" in block
        assert "nothing logged at any point in this window" in block
        assert "since his last food log" not in block

    def test_the_block_and_the_derivation_cannot_disagree(self):
        """The #2394 wording and the #2382 derivation are the same decision, read once.
        A record the derivation calls `paused` must get the day-count wording, and one it
        calls `never_logged` must get the absence wording — always, both directions."""
        from content.engagement_core import presence_prompt_block

        for last, kind in ((None, bl.TRANSITION_NEVER_LOGGED), ("2026-08-03", bl.TRANSITION_PAUSED), (TODAY, bl.TRANSITION_LOGGED)):
            sig = _signal(food_last=last)
            block = presence_prompt_block(sig)
            assert bl.transition_from_presence_signal(sig).kind == kind
            if kind == bl.TRANSITION_NEVER_LOGGED:
                assert "NOTHING has been logged this cycle" in block
            else:
                assert "since his last food log" in block
                assert "NOTHING has been logged this cycle" not in block

    def test_the_blocks_own_output_passes_its_own_guard(self):
        """End to end: the steering block the coaches actually receive must not itself
        contain a sentence the transition guard would flag."""
        from content.engagement_core import presence_prompt_block

        sig = _signal(food_last=None)
        block = presence_prompt_block(sig)
        transitions = {"nutrition": bl.transition_from_presence_signal(sig)}
        # The block quotes the forbidden phrasings in order to forbid them; strip the
        # quoted instruction line before checking the assertions it makes in its own voice.
        assertions = "\n".join(ln for ln in block.splitlines() if "Do NOT say" not in ln and "date a transition" not in ln)
        assert bl.absence_transition_findings(assertions, transitions=transitions) == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. MUTATION PROOF — a guard that survives sabotage has proved nothing
# ─────────────────────────────────────────────────────────────────────────────


class TestMutationProof:
    def test_collapsing_known_none_back_into_unknown_breaks_the_guard(self, monkeypatch):
        """Mutation 1 — the pre-#2382 world, restored: availability carries no dates, so
        `never_logged` becomes unsayable and the fabricated transition sails through."""
        real = bl.transition_from_presence_signal

        def sabotaged(signal, category="nutrition"):
            tr = real(signal, category)
            if tr.kind == bl.TRANSITION_NEVER_LOGGED:
                return bl.AbsenceTransition(tr.category, bl.TRANSITION_UNKNOWN, None, None, tr.window_start)
            return tr

        monkeypatch.setattr(bl, "transition_from_presence_signal", sabotaged)
        tr = bl.transition_from_presence_signal(_signal(food_last=None))
        assert tr.kind != bl.TRANSITION_NEVER_LOGGED  # the sabotage really did land
        assert bl.absence_transition_findings("Your food logs paused four days ago.", transitions={"nutrition": tr}) == []

    def test_letting_the_window_age_leak_onto_the_channel_breaks_the_guard(self):
        """Mutation 2 — the ORIGINAL defect, reproduced exactly: hand the never-logged
        channel the clamp's `gap_days` as though it were a real gap, and the derivation
        starts licensing "paused four days ago" for a channel that never logged."""
        sig = _signal(food_last=None, gap_days=4)
        honest = bl.transition_from_presence_signal(sig)
        assert honest.licenses_transition is False

        leaked = bl.AbsenceTransition("nutrition", bl.TRANSITION_PAUSED, "2026-08-03", sig["gap_days"], GENESIS)
        assert leaked.licenses_transition is True, "the mutation must actually change behaviour"
        assert bl.absence_transition_findings("Your food logs paused four days ago.", transitions={"nutrition": leaked}) == []

    def test_dropping_the_transition_vocabulary_breaks_the_guard(self, monkeypatch):
        """Mutation 3 — soften the pattern to something that matches nothing, and the
        live fabrications stop being findings. Proves the sentences pass through the
        regex rather than through some incidental branch."""
        import re

        never_logged = {"nutrition": bl.transition_from_presence_signal(_signal(food_last=None))}
        assert all(bl.absence_transition_findings(s, transitions=never_logged) for s in LIVE_FABRICATIONS)

        monkeypatch.setattr(bl, "_AT_TRANSITION_RE", re.compile(r"\bzzzz-no-such-token\b"))
        assert all(bl.absence_transition_findings(s, transitions=never_logged) == [] for s in LIVE_FABRICATIONS)

    def test_reverting_the_presence_block_branch_reintroduces_the_false_wording(self, monkeypatch):
        """Mutation 4 — at the seam: make the derivation unavailable AND null out the
        fallback, and the block goes straight back to "it has been ~4 days since his last
        food log" for a channel that never logged. This is the sentence six live cards
        paraphrased, so its absence is what the seam test is really pinning."""
        from content import engagement_core as ec

        sig = _signal(food_last=None)
        assert "NOTHING has been logged this cycle" in ec.presence_prompt_block(sig)

        monkeypatch.setattr(
            ec,
            "_food_absence_transition",
            lambda s: bl.AbsenceTransition("nutrition", bl.TRANSITION_PAUSED, "2026-08-03", 4, GENESIS),
        )
        reverted = ec.presence_prompt_block(sig)
        assert "since his last food log" in reverted, "the mutation must actually change behaviour"
        assert "NOTHING has been logged this cycle" not in reverted
