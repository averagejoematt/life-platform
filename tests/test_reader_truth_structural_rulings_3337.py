"""#3337 — every adjudication rule in the reader-truth ledger decides on STRUCTURE.

THE CHARGE. `lambdas/operational/reader_truth_rulings.py` carried 13 `def is_*`
(14 since #3379 added `is_uncited_temporal_objection`, classified below)
adjudication rules and three of them decided on the judge's PHRASING:
`is_vagueness_objection` (an adjective regex), `is_self_refuted` (a six-phrase
withdrawal list) and `is_active_vs_passive_objection` (a silence-verb list). Every
phrase-matched member of the #2959 → #3003 → #3199 → #3208 family has failed in the
field; #3208's instance gated main. A suppressor keyed to one wording is one
paraphrase from BOTH failure directions at once — gating a healthy deploy, and
exempting a real defect that happens to use the trigger words.

WHAT THIS FILE HOLDS.

  1. THE REGISTRY (`test_every_is_rule_is_classified`) — the rules (14 since #3379), each with the
     structural predicate it decides on, derived from the module by AST. A new
     `is_*` that is not classified here reds the suite, so the sweep cannot go stale
     the way an epic checklist does.

  2. A MUTATION TEST PER RESHAPED RULE — the same objection worded ≥3 ways yields the
     same verdict, and (where the rule demotes) a GENUINE impossibility that uses the
     rule's trigger words is NOT adjudicated. Every paraphrase is listed inline so
     the next reader can add the next one.

  3. THE NEVER-DECIDES-ALONE PROOF — for each rule that kept a phrase regex as a
     tiebreak, a note that matches the phrase but fails the structural precondition
     is NOT adjudicated.

  4. THE FAMILY SWEEP (`test_the_2959_3003_3199_3208_family_still_resolves`) — every
     recorded wire note in the family, re-run through the reshaped rules, with the
     structural-vs-tiebreak split counted. The counts printed by this test are the
     ones posted on the issue.

FIXTURE PROVENANCE. Every note marked WIRE is a recorded judge output: the #2959 /
#3003 / #3199 / #3208 notes are replayed from `tests/test_reader_truth_qa.py` (whose
own comments name the CI runs and artifacts they came from), the #3258 note from
`tests/test_reader_truth_retracted_3258.py` (character-count-asserted against the log
line's own stamp), and the two 2026-08-30 notes from
`/aws/lambda/life-platform-qa-smoke`'s `[QA] DETAIL … full note (N chars)` lines.
Paraphrases are labelled PARAPHRASE and are explicitly synthetic — they are the
mutation, and they are never used as evidence that a class exists.
"""

import ast
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import reader_truth_rulings as R  # noqa: E402

# WIRE notes replay under the frame they were RECORDED in (cycle-14, genesis
# 2026-08-17) — see test_reader_truth_qa.py's note; the 2026-09-01 re-anchor
# proved the live constant breaks the corpus at every reset.
_RECORDED_GENESIS = "2026-08-17"

_START = _RECORDED_GENESIS

import pytest


@pytest.fixture(autouse=True)
def _recorded_frame(monkeypatch):
    """assess_prose computes phase ground truth from constants at CALL time; the
    wire corpus replays under its recorded frame (see _RECORDED_GENESIS above)."""
    monkeypatch.setattr("common.constants.EXPERIMENT_START_DATE", _RECORDED_GENESIS)


_S = date.fromisoformat(_START)


def _day(n):
    """The ISO date of Day N of the current cycle (1-indexed, like the rubric)."""
    return (_S + timedelta(days=n - 1)).isoformat()


def _f(note, page="/", category="temporal_contradiction", severity="high", **extra):
    f = {"page": page, "category": category, "severity": severity, "note": note}
    f.update(extra)
    return f


# ── 1. the registry: 14 rules, each with the structure it decides on ───────────
# Dated sweep 2026-08-30 (#3337). "structural" = decides on category / surface /
# claim class / parsed evidence values / a structured judge field. "tiebreak" = a
# phrase regex survives, but only to break a tie a structural predicate already
# allowed, and it prints when it does. Nothing in this ledger is "lexical" any more.
RULE_CLASSIFICATION = {
    "is_code_owned_temporal": ("structural", "category + page in CODE_OWNED_TEMPORAL_SURFACES + a cited date <= cycle start"),
    "is_wake_frame_correct": (
        "structural",
        "category + night-scoped surface + (one-day date span OR quoted as_of_date/night_of satisfying the convention, fresh vs today)",
    ),
    "is_utc_offset_misread": ("structural", "category + surface + the note's own UTC→Pacific arithmetic recomputed and found wrong"),
    "is_durable_design_copy": ("structural", "category + every quoted span is registered DURABLE_DESIGN_COPY"),
    "is_vagueness_objection": (
        "tiebreak",
        "category + `basis` field OR (nothing out of phase, no payload date field, grounded in today's Day N); "
        "the adjective regex only breaks a tie, and only when nothing is out of phase in the judge's own words",
    ),
    "is_day_counter_bound_inference": (
        "structural",
        "category + a claimed data-quantity number equal (+-1) to the cited day number, lexical scaffold OR N/M fraction",
    ),
    "is_prior_cycle_archive": ("structural", "category + an archival path prefix + a cited pre-cycle date or prior cycle label"),
    "is_position_banner_misread": ("structural", "category + a quoted banner day + a cited content date mapped to a different day"),
    "is_coach_surface_audience": ("structural", "category + page under /coaching/"),
    "is_self_refuted": (
        "tiebreak",
        "`basis` field OR (nothing out of phase, no payload date field) + the #2959 withdrawal phrases in the FINAL sentence only",
    ),
    "is_sparsity_objection": ("structural", "category + the quoted honest reading count <= the cited day number"),
    "is_active_vs_passive_objection": (
        "structural",
        "category + a quoted claim scoped to the cycle start + an evidence set that is only the phase's own anchors",
    ),
    "is_uncited_temporal_objection": (
        "structural",
        "category + the judge's own sentences (quoted copy excluded) cite NO date, day number, or elapsed span, "
        "and name no payload date field — a parsed-evidence absence, no wording consulted",
    ),
    "is_advisory": ("structural", "reads the `rulings` FIELD the assessment loop wrote — never the note"),
}

# Rules that still keep a phrase regex, and the ONE structural precondition each
# requires before the phrase is allowed to speak. Empty means the sweep found none.
TIEBREAK_RESIDUE = {
    "is_vagueness_objection": (
        "nothing out of phase in the judge's own sentences (dates and day numbers count wherever they "
        "appear; a span counts only when the judge states it rather than quoting it)"
    ),
    "is_self_refuted": "nothing out of phase anywhere in the note, and no payload date field named",
}


def _is_rule_names():
    src = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("is_")}


def test_every_is_rule_is_classified():
    """The sweep is derived from the module, never from a note that rots (#3337).

    An `is_*` added without a line in RULE_CLASSIFICATION reds here — which is the
    only way this classification stays true after the PR that wrote it.
    """
    found = _is_rule_names()
    assert found == set(RULE_CLASSIFICATION), (
        "the `is_*` rule set no longer matches the #3337 classification.\n"
        f"  unclassified: {sorted(found - set(RULE_CLASSIFICATION))}\n"
        f"  stale entries: {sorted(set(RULE_CLASSIFICATION) - found)}\n"
        "Classify the new rule structural-vs-tiebreak (see the module header's bar) before merging."
    )
    assert len(found) == 14, f"the ledger holds {len(found)} rules; the sweep counts 14 (#3337 + #3379) — update the sweep with the count"


def test_no_rule_is_classified_purely_lexical():
    """The bar itself: a rule whose verdict is a phrase is not allowed to exist."""
    lexical = sorted(n for n, (kind, _) in RULE_CLASSIFICATION.items() if kind not in ("structural", "tiebreak"))
    assert not lexical, f"purely lexical rules remain: {lexical}"
    for name in TIEBREAK_RESIDUE:
        assert RULE_CLASSIFICATION[name][0] == "tiebreak", name


def test_the_header_states_the_bar():
    """Acceptance box 5: the bar is written where the next author will read it."""
    head = Path(R.__file__).read_text(encoding="utf-8")[:4000]
    assert "STRUCTURAL, NEVER PHRASE-MATCHED" in head
    for token in ("category", "PARSED EVIDENCE VALUES", "TIEBREAK", "#3337"):
        assert token in head, token


# ── 2. mutation: is_vagueness_objection ───────────────────────────────────────
# The objection: /story/timeline/ on Day 6 says "4 days without an entry"; the
# judge's OWN arithmetic puts the last entry on Day 2, inside the cycle, so nothing
# it cites is impossible. Same objection, five wordings — only the first is the wire.
VAGUENESS_PARAPHRASES = [
    # WIRE (#3003, CI run 32601989142)
    "The milestone states 'The logs have gone quiet — 4 days without an entry' on Day 6. "
    "If 4 days have passed without an entry, the last entry would have been on Day 2 or earlier. "
    "However, Day 1 is listed as 2026-08-17, making Day 6 equal to 2026-08-22. "
    "The phrase '4 days without an entry' is vague about whether it counts calendar days or elapsed 24-hour periods.",
    # PARAPHRASE 1 — no trigger word anywhere ("does not commit to")
    "The milestone reads 'The logs have gone quiet — 4 days without an entry' on Day 6. Working it "
    "through: 4 days back from Day 6 puts the last entry at Day 2, inside the cycle. The wording does "
    "not commit to calendar days versus elapsed 24-hour periods.",
    # PARAPHRASE 2 — the objection stated as a reader-experience complaint
    "On Day 6 the page claims '4 days without an entry'. Counting back from Day 6 that places the "
    "last entry at Day 2, which is in-cycle, so nothing here is impossible; a first-time reader simply "
    "cannot tell which counting convention the sentence uses.",
    # PARAPHRASE 3 — hedged with a different adjective family
    "'4 days without an entry' appears on Day 6. The arithmetic resolves: the last entry lands on Day "
    "2 of the cycle. The sentence is loose about whether it means calendar days or rolling periods.",
    # PARAPHRASE 4 — no hedging language at all, just the resolved arithmetic
    "The copy says '4 days without an entry' and the banner says Day 6. 4 days before Day 6 is Day 2, "
    "so the gap fits entirely inside the cycle.",
]

# The must-fail direction: a REAL impossibility that uses the rule's trigger words.
# Pre-#3337 this was demoted because the adjective regex decided alone.
VAGUENESS_GENUINE_IMPOSSIBILITY = (
    "The page states 'No training logged — 57 days' on Day 5 of the cycle. A 57-day history is "
    "impossible when the cycle has existed for 5 days, though it is unclear whether the copy means "
    "calendar days."
)


def test_vagueness_objection_is_wording_independent():
    for i, note in enumerate(VAGUENESS_PARAPHRASES):
        f = _f(note, page="/story/timeline/")
        assert R.is_vagueness_objection(f, _START, _day(6)) is True, f"paraphrase {i} escaped the ruling: {note[:80]}"


def test_vagueness_objection_spares_a_genuine_impossibility_using_its_trigger_words():
    f = _f(VAGUENESS_GENUINE_IMPOSSIBILITY, page="/data/training/")
    assert R.is_vagueness_objection(f, _START, _day(5)) is False, (
        "a 57-day claim on Day 5 is an impossibility the phase establishes — the word 'unclear' "
        "must not demote it (the #3337 charge, both directions)"
    )


def test_vagueness_objection_never_touches_a_payload_dating_finding():
    """WIRE, 2026-08-30, /api/vitals d1c6a0 — every value in phase, and TRUE (a real
    6-day scale gap). A note naming payload date fields is a data claim, never this class."""
    note = (
        "weight_as_of is 2026-08-24 (6 days ago), but the API metadata states as_of_date is 2026-08-30 "
        "(today, Day 14). The window_disclosure acknowledges this discrepancy but the weight field's age "
        "(6 days stale within a 14-day cycle) combined with null weight_delta fields suggests the weight "
        "data may not be current enough to support daily narrative claims. The disclosure text itself is "
        "explanatory rather than contradictory, but the stale weight reading undermines real-time "
        "cockpit/home claims about 'today's whole-life score.'"
    )
    assert R.is_vagueness_objection(_f(note, page="/api/vitals"), _START, _day(14)) is False


def test_vagueness_phrase_cannot_decide_alone():
    """The tiebreak contract: the adjective is present, the structural precondition is not."""
    note = (
        "The copy claims 'three weeks of data'. Three weeks is 21 days and the cycle is 4 days old, so "
        "the claim is impossible, though it is unclear whether the copy means calendar weeks."
    )
    assert R.is_vagueness_objection(_f(note), _START, _day(4)) is False


def test_vagueness_objection_spares_the_archetypal_true_positive():
    """The regression this reshape nearly shipped, kept as a wall.

    A judge quoting an out-of-phase claim and objecting in one clause cites the
    impossible quantity INSIDE the quote. An earlier draft read only the judge's own
    sentences and would have demoted this — the archetypal reader-truth finding.
    """
    note = "The home page says 'over the past three weeks' but we are on Day 6 of the cycle."
    assert R.is_vagueness_objection(_f(note), _START, _day(6)) is False


def test_vagueness_objection_reads_the_judges_own_basis_field():
    """Channel 1: a field, not a phrase — and it works on a note the evidence channels miss."""
    note = "The banner claims a 40-day streak on Day 4; the wording could mean either cycle."
    assert R.is_vagueness_objection(_f(note), _START, _day(4)) is False
    assert R.is_vagueness_objection(_f(note, basis="ambiguity"), _START, _day(4)) is True


# ── 2. mutation: is_self_refuted ──────────────────────────────────────────────
# A withdrawal is a speech act; the ONLY wording-independent channel for it is the
# structured field #3258 named and #3337 shipped. These five notes retract in five
# different words; with `basis` filled, all five drop.
WITHDRAWAL_PARAPHRASES = [
    # WIRE (#2959, run 32618360726, /data/wall/)
    "Lists 'ATTEMPT 14 FROM 2026-08-17 alive · day 6', which is correct for the phase. However, the "
    "cycle started 2026-08-17 and today is 2026-08-22, making this Day 6 elapsed — the label is "
    "accurate. No contradiction here on rechecking arithmetic.",
    # WIRE (#3258, finding 539c6d, /) — the retraction the phrase list could not see
    "However, the context makes clear it is a prospective goal. No flag warranted on reconsideration.",
    # PARAPHRASE 1
    "Re-reading the banner against Day 6, the arithmetic checks out and I withdraw the objection.",
    # PARAPHRASE 2
    "On a second pass this resolves cleanly; there is nothing to flag here after all.",
    # PARAPHRASE 3
    "Scratch that — the label matches the phase once inclusive counting is applied.",
]


def test_self_refuted_is_wording_independent_when_the_judge_fills_basis():
    for i, note in enumerate(WITHDRAWAL_PARAPHRASES):
        f = _f(note, page="/data/wall/", basis="withdrawn")
        assert R.is_self_refuted(f, _START, _day(6)) is True, f"paraphrase {i} escaped: {note[:80]}"


def test_self_refuted_residue_is_named_and_measured():
    """RESIDUE, honestly: without the field, only the #2959 wordings are caught.

    This is the #3258 residue, unchanged — the phrase list was deliberately NOT
    extended. The test exists so the residue is a measured number in the suite
    rather than a sentence in a PR body.
    """
    caught = [n for n in WITHDRAWAL_PARAPHRASES if R.is_self_refuted(_f(n, page="/data/wall/"), _START, _day(6))]
    assert len(caught) == 1, (
        f"{len(caught)} of {len(WITHDRAWAL_PARAPHRASES)} withdrawal wordings are caught without the "
        "`basis` field. If this grew, the phrase list was extended — route on the field instead (#3258)."
    )


def test_self_refuted_spares_a_real_impossibility_that_ends_in_a_withdrawal_phrase():
    """The must-fail direction, and a behaviour CHANGE: pre-#3337 the final sentence
    decided alone, so a note proving a real out-of-phase claim was dropped anyway."""
    note = (
        "The page narrates 'over the past three weeks' on Day 6 of the cycle. A 21-day history is "
        "impossible in a 6-day cycle. Otherwise the section is internally consistent."
    )
    assert R.is_self_refuted(_f(note), _START, _day(6)) is False


def test_self_refuted_spares_a_payload_dating_finding_that_ends_in_a_withdrawal_phrase():
    """WIRE-shaped: the /api/glucose e5eafd class, which the deterministic plausibility
    pass independently FAILED with arithmetic. It must keep gating."""
    note = (
        "as_of_date is 2026-08-22, but the payload was generated on 2026-08-24 (Day 8). The stamp "
        "should be the last complete day. The rest of the payload is self-consistent."
    )
    assert R.is_self_refuted(_f(note, page="/api/glucose"), _START, _day(8)) is False


# ── 2. mutation: is_active_vs_passive_objection ───────────────────────────────
# The objection: coach copy scopes a silence claim to the cycle window ("since
# August 17th"), and the judge objects with nothing but the cycle window. Five
# wordings, none of which share a verb — the pre-#3337 matcher required
# "active logging/tracking … went silent".
ACTIVE_VS_PASSIVE_PARAPHRASES = [
    # WIRE (#3199, /method/board/, 2026-08-25)
    "Dr. Eli Marsh states 'active logging went silent across food, training, habits, and journal since "
    "August 17th' — but August 17 is Day 1 of the current cycle, and today is Day 9 (2026-08-25). The phras",
    # PARAPHRASE 1 — no "active", no silence verb
    "The board copy reads 'no entries in food, training, habits or journal since August 17th'. August 17 "
    "is Day 1 of the current cycle and today is Day 9.",
    # PARAPHRASE 2 — a different noun for the same category set
    "The coach writes 'the deliberate-logging surfaces have recorded nothing since August 17th'. That "
    "date is Day 1 of this cycle; today is Day 9.",
    # PARAPHRASE 3 — adjectival, present tense
    "Copy claims 'food, training, habits and journal are empty since August 17th' — but August 17 is the "
    "cycle start (Day 1) and we are on Day 9.",
    # PARAPHRASE 4 — the objection stated as a bare restatement
    "'nothing has been logged by hand since August 17th' is the claim. August 17 is Day 1; today is Day 9.",
]


def test_active_vs_passive_objection_is_wording_independent():
    for i, note in enumerate(ACTIVE_VS_PASSIVE_PARAPHRASES):
        f = _f(note, page="/method/board/")
        assert R.is_active_vs_passive_objection(f, _START, _day(9)) is True, f"paraphrase {i} escaped: {note[:80]}"


def test_active_vs_passive_objection_spares_an_objection_carrying_real_evidence():
    """The residue this ruling promised and now ENFORCES: a cited entry after the
    since-date is evidence, and the finding survives — trigger words and all."""
    note = (
        "'active logging went silent across food, training, habits, and journal since August 17th' — but a "
        "training session was logged on 2026-08-20 and two journal entries exist. Today is Day 9."
    )
    assert R.is_active_vs_passive_objection(_f(note, page="/method/board/"), _START, _day(9)) is False


def test_active_vs_passive_objection_spares_a_since_date_that_is_not_genesis():
    """The #2941 banner-itself-wrong shape, with the trigger words present."""
    note = (
        "States 'active logging went silent since August 16th' — but August 16 is a day before Day 1 of "
        "the current cycle (2026-08-17), and today is Day 9. The cited since-date predates genesis."
    )
    assert R.is_active_vs_passive_objection(_f(note, page="/method/board/"), _START, _day(9)) is False


def test_active_vs_passive_objection_spares_a_wrong_banner_day():
    note = (
        "The page header states 'DAY 9 · WEEK 2, SINCE AUGUST 17 2026', but today is August 23, 2026. "
        "August 23 is Day 7, not Day 9 — the banner overstates the cycle position."
    )
    assert R.is_active_vs_passive_objection(_f(note), _START, _day(7)) is False


# ── 2. mutation: is_wake_frame_correct (widened in the same pass) ──────────────
# LIVE at the time of writing: `qa-smoke-warnings` was in ALARM, cited to #3337,
# on this finding. WIRE from /aws/lambda/life-platform-qa-smoke, Day 14, fcd7d5,
# `[QA] DETAIL … full note (551 chars)`.
WAKE_FRAME_LIVE_WIRE = (
    "The payload states 'as_of_date': '2026-08-29' and 'night_of': '2026-08-28', but today is 2026-08-30 "
    "(Day 14). The as_of_date should not be two days in the past on a daily-computed surface; the design "
    "allows as_of_date to be yesterday (2026-08-29), but this payload is dated to two days ago. The "
    "trend_note acknowledges the wake-date convention and notes that 'sleep_trend rows are keyed by WAKE "
    "date', but the primary sleep_detail object's as_of_date being 2026-08-29 while the payload was "
    "generated 2026-08-31 exceeds the acceptable staleness window."
)
WAKE_FRAME_PARAPHRASES = [
    WAKE_FRAME_LIVE_WIRE,
    # PARAPHRASE 1 — the same field values, a plain staleness accusation
    "The surface reports 'as_of_date': '2026-08-29' with 'night_of': '2026-08-28'. Compared against the "
    "generation time this reads a day behind what a daily surface should publish.",
    # PARAPHRASE 2 — no "stale" anywhere
    "'night_of': '2026-08-28' sits under 'as_of_date': '2026-08-29', which does not line up with the "
    "current date on a surface that claims to refresh every morning.",
    # PARAPHRASE 3 — states the convention and objects anyway
    "Field 'as_of_date' = 2026-08-29 and field 'night_of' = 2026-08-28. Even granting the wake-date "
    "convention, a reader landing today sees a payload that is not dated today.",
]


def test_wake_frame_convention_channel_resolves_the_live_sleep_detail_finding():
    for i, note in enumerate(WAKE_FRAME_PARAPHRASES):
        f = _f(note, page="/api/sleep_detail", severity="med")
        assert R.is_wake_frame_correct(f, "2026-08-30") is True, f"paraphrase {i} escaped: {note[:80]}"


def test_wake_frame_convention_channel_spares_a_genuinely_stale_payload():
    """The discriminator: as_of four days behind today is real staleness and keeps gating."""
    note = "The payload states 'as_of_date': '2026-08-26' and 'night_of': '2026-08-25', but today is 2026-08-30."
    assert R.is_wake_frame_correct(_f(note, page="/api/sleep_detail"), "2026-08-30") is False


def test_wake_frame_convention_channel_needs_the_clock():
    """Fail-closed: no `today`, no channel-2 verdict — the finding survives."""
    assert R.is_wake_frame_correct(_f(WAKE_FRAME_LIVE_WIRE, page="/api/sleep_detail"), None) is False


# ── 3. the fail-closed posture of the whole reshape ───────────────────────────


def test_every_reshaped_rule_fails_closed_without_the_phase():
    """No phase anchors → no adjudication. A caller that cannot supply the ground
    truth keeps the finding at full severity, which is the safe direction."""
    for fn, note in (
        (R.is_vagueness_objection, VAGUENESS_PARAPHRASES[0]),
        (R.is_self_refuted, WITHDRAWAL_PARAPHRASES[0]),
        (R.is_active_vs_passive_objection, ACTIVE_VS_PASSIVE_PARAPHRASES[0]),
    ):
        assert fn(_f(note, page="/method/board/")) is False, fn.__name__


def test_the_basis_field_can_only_fire_a_ruling_never_veto_one():
    """`basis: "impossibility"` on a note the structural channel adjudicates must not
    rescue it — the field is additive, and an unmeasured prompt change may never
    become a new way for the judge to override code (ADR-105, #2613)."""
    f = _f(VAGUENESS_PARAPHRASES[1], page="/story/timeline/", basis="impossibility")
    assert R.is_vagueness_objection(f, _START, _day(6)) is True


def test_an_unknown_basis_value_is_ignored():
    f = _f("The banner claims a 40-day streak on Day 4.", basis="nonsense")
    assert R.judge_basis(f) is None
    assert R.is_vagueness_objection(f, _START, _day(4)) is False


# ── 4. the #2959/#3003/#3199/#3208 family, re-run ─────────────────────────────
# Acceptance box 4. Each row is (label, note, page, day, the rulings that must fire).
# The notes are the recorded wire; the day is the day each was RECORDED on — a wire
# note judged against the wrong day is not the wire.
FAMILY = [
    (
        "#2959 / HRV 7-day average",
        "Home page states 'HRV spiked to 49ms (+27% above your 7-day average)' but only 6 days of "
        "current-experiment data can exist. A 7-day average is impossible on Day 6 of the experiment "
        "(Day 1 = 2026-08-17, today = 2026-08-22). This contradicts the phase constraint that at most "
        "6 days of current-experiment data exist.",
        "/",
        6,
        {"day_counter_bound"},
    ),
    (
        "#2959 /cockpit/ HRV average",
        "Cockpit states 'HRV spiked to 49ms (+27% above your 7-day average)' in the daily line. This is "
        "impossible on Day 6 when only 6 days of data exist—a 7-day average cannot be computed from 6 "
        "days of current-cycle data.",
        "/cockpit/",
        6,
        {"day_counter_bound"},
    ),
    (
        "#2959 /method/board/ graded forecasts",
        "States 'THIS SEASON · CYCLE 14' with '26 GRADED FORECASTS' on Day 5, but only 5 days of data "
        "can exist in the current cycle (started 2026-08-17). On Day 5, a maximum of 5 days of in-cycle "
        "data is possible.",
        "/method/board/",
        5,
        {"day_counter_bound"},
    ),
    (
        "#2959 /data/wall/ self-refuting",
        WITHDRAWAL_PARAPHRASES[0],
        "/data/wall/",
        6,
        {"self_refuted"},
    ),
    (
        "#2959 /method/survival/ self-refuting",
        "The survival curve page shows '6 SILENT DAYS RIGHT NOW' and the engagement table shows cycle "
        "14 with strip '······' (6 dots) and '0/6' engagement. The header says 'DAY 6 · WEEK 1, SINCE "
        "AUGUST 17 2026'. This is self-consistent and correct: 6 days have elapsed, all silent. "
        "No contradiction.",
        "/method/survival/",
        6,
        {"self_refuted"},
    ),
    (
        "#3003 /story/timeline/ vagueness",
        VAGUENESS_PARAPHRASES[0],
        "/story/timeline/",
        6,
        {"vagueness_objection"},
    ),
    (
        "#3199 /method/results/ sparsity",
        "The page reads 'LATEST 326.2 LB · 1 READING SO FAR' next to an HRV series with 9 daily readings. "
        "A single weight reading across 9 days of an active tracking experiment is impossible on Day 9.",
        "/method/results/",
        9,
        {"sparsity_objection"},
    ),
    (
        "#3199 /method/board/ active-vs-passive",
        ACTIVE_VS_PASSIVE_PARAPHRASES[0],
        "/method/board/",
        9,
        {"active_vs_passive"},
    ),
    (
        "#3208 /method/intelligence/ 9/10 fraction",
        "States 'DAYS OF DATA TOWARD THE FIRST CORRELATION MATRIX · 9/10' and 'No correlations yet — the "
        "honest state, not a broken pipeline. The weekly matrix computes its first pairs once 10 overlapping days "
        "of this cycle's data exist.' On Day 10 of the cycle, 10 days of data should exist, making this claim "
        "impossible. The page claims correlations cannot compute until 10 days exist, yet we are on Day 10, so "
        "this is contradictory.",
        "/method/intelligence/",
        10,
        {"day_counter_bound"},
    ),
    (
        "#3208 /method/intelligence/ live re-run wording",
        "Page states 'DAYS OF DATA TOWARD THE FIRST CORRELATION MATRIX · 9/10' but the phase is Day 10 of the "
        "experiment. On Day 10, a maximum of 10 days of current-cycle data can exist, not 9. The counter should "
        "read 10/10 or indicate 10 overlapping days are now available for the first correlation matrix computation.",
        "/method/intelligence/",
        10,
        {"day_counter_bound"},
    ),
    (
        "#3258 / retraction (539c6d)",
        "Home page states 'This attempt starts at the Day‑1 weigh‑in, aimed at 185 lbs held for 90 "
        "consecutive days' but does not explicitly label this as a forward-looking goal or checkpoint. "
        "The prose is framed in present tense ('This attempt starts') which could be read as describing "
        "an ongoing or past event rather than a future target. However, the context ('aimed at', 'or the "
        "checkpoint fails') makes clear it is a prospective goal. This is ambiguous rather than "
        "contradictory — the phrasing is acceptable for describing a cycle objective. No flag warranted "
        "on reconsideration.",
        "/",
        11,
        {"vagueness_objection"},
    ),
]

# The two findings that were holding `qa-smoke-warnings` in ALARM on 2026-08-30, and
# what must happen to each. The vitals one is a REAL defect and must keep alarming.
LIVE_ALARM_FINDINGS = [
    ("fcd7d5 /api/sleep_detail (wake convention)", WAKE_FRAME_LIVE_WIRE, "/api/sleep_detail", 14, "dropped"),
    (
        "d1c6a0 /api/vitals (real 6-day scale gap)",
        "weight_as_of is 2026-08-24 (6 days ago), but the API metadata states as_of_date is 2026-08-30 "
        "(today, Day 14). The window_disclosure acknowledges this discrepancy but the weight field's age "
        "(6 days stale within a 14-day cycle) combined with null weight_delta fields suggests the weight "
        "data may not be current enough to support daily narrative claims. The disclosure text itself is "
        "explanatory rather than contradictory, but the stale weight reading undermines real-time "
        "cockpit/home claims about 'today's whole-life score.'",
        "/api/vitals",
        14,
        "survives",
    ),
]


def _adjudicate(note, page, day):
    """Every ruling id that fires on a finding, drops included — the family sweep's unit."""
    f = _f(note, page=page)
    today = _day(day)
    fired = set()
    for name, fn in (
        ("code_owned_temporal", lambda x: R.is_code_owned_temporal(x, _START)),
        ("wake_frame_correct", lambda x: R.is_wake_frame_correct(x, today)),
        ("utc_offset_misread", R.is_utc_offset_misread),
        ("durable_design_copy", R.is_durable_design_copy),
        ("prior_cycle_archive", lambda x: R.is_prior_cycle_archive(x, _START)),
        ("coach_surface_audience", R.is_coach_surface_audience),
        ("self_refuted", lambda x: R.is_self_refuted(x, _START, today)),
    ):
        if fn(f):
            fired.add(name)
    for ruling_id, _label, fires, _reason in R.advisory_rulings(_START, today):
        if fires(f):
            fired.add(ruling_id)
    return fired


def test_the_2959_3003_3199_3208_family_still_resolves():
    """Box 4: every recorded family member, re-run through the reshaped rules.

    Not a smoke test — this is the regression wall for the whole reshape. If a
    future structural tightening drops one of these, it drops a measured
    false-positive class back into the gate.
    """
    unresolved = []
    for label, note, page, day, expected in FAMILY:
        fired = _adjudicate(note, page, day)
        if not expected <= fired:
            unresolved.append(f"{label}: expected {sorted(expected)}, fired {sorted(fired) or 'nothing'}")
    assert not unresolved, "family members no longer adjudicated:\n  " + "\n  ".join(unresolved)
    print(f"\n#3337 family sweep: {len(FAMILY)}/{len(FAMILY)} recorded members still resolve.")


def test_the_family_sweep_reports_its_structural_vs_tiebreak_split():
    """The count posted on the issue, computed rather than claimed.

    A member "resolves structurally" when no tiebreak line was printed for it; the
    tiebreak path prints (`#3337 residue: …`), which is what makes the residue
    countable in production too.
    """
    import io
    from contextlib import redirect_stdout

    structural, tiebroken = [], []
    for label, note, page, day, _expected in FAMILY:
        buf = io.StringIO()
        with redirect_stdout(buf):
            _adjudicate(note, page, day)
        (tiebroken if "LOGGED TIEBREAK" in buf.getvalue() else structural).append(label)
    print(f"\n#3337 sweep: {len(structural)} resolve structurally, {len(tiebroken)} via a logged tiebreak.")
    print("  structural: " + ", ".join(structural))
    print("  tiebreak:   " + (", ".join(tiebroken) or "none"))
    assert len(structural) + len(tiebroken) == len(FAMILY)
    assert len(structural) >= 8, "the reshape was supposed to move most of the family onto structural channels"


def test_the_committed_truth_baseline_holds_no_family_debt():
    """The other half of box 4: the committed reader-truth ledger itself.

    `tests/truth_baseline.json` is the (page, category) debt file the gate reads. If
    it ever carries family entries, they belong in the sweep above too — so read it
    rather than asserting from memory.
    """
    import json

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "truth_baseline.json")
    with open(path, encoding="utf-8") as fh:
        pages = json.load(fh).get("pages") or {}
    entries = sum(len(v or {}) for v in pages.values()) if isinstance(pages, dict) else 0
    print(f"\n#3337: tests/truth_baseline.json carries {entries} baselined (page, category) entr(ies).")
    assert entries == 0, (
        f"the committed truth baseline now carries {entries} entries. #3337's sweep was taken against an "
        "EMPTY ledger; re-run each entry through the reshaped rules and record the result here."
    )


def test_the_live_alarm_findings_resolve_the_way_the_issue_says():
    """The honest answer to 'does this clear the live alarm?', asserted rather than promised."""
    for label, note, page, day, expectation in LIVE_ALARM_FINDINGS:
        fired = _adjudicate(note, page, day)
        if expectation == "dropped":
            assert fired, f"{label} is still unadjudicated — the alarm's cited cause survives"
        else:
            assert not fired, f"{label} was adjudicated away; it is a REAL finding and must keep alarming (fired {sorted(fired)})"
