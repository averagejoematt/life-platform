"""tests/test_recap_coach_line_3749.py — a coach line the card did not invent (#3749).

THE ACCEPTANCE IS SELECTION, NOT GENERATION

The tempting build for "put coach insight on the card" is one Bedrock call per card asking
for a fresh flourish about the day. That is a new AI narrative surface, and ADR-104 would
then require a grounding gate on it, a `grounding_wiring.SURFACES` entry, and a way to
grade it — for a sentence nobody asked a model to originate. #3749 asks for something
strictly better and strictly cheaper: quote a coach who already spoke.

So the property these tests defend is not "the line reads well". It is that the line is a
CONTIGUOUS PREFIX of text a coach actually wrote, from a named record, or there is no line
at all. Everything else here follows from that:

  * `first_sentence` must return a prefix — asserted as a prefix, not by eyeballing output
  * the read seam must be `public_summary` ONLY — the owner-register fields are a
    different audience and falling back to them is the #2972 defect, so there are tests
    that plant each of them alone and require silence
  * absence must stay absence — no line, no placeholder, no substitute
  * the record id must travel with the card, or "which coach said that" is unanswerable

AND ONE THING THAT IS NEW ON THIS SURFACE

Until this change every string on a card was a number this platform formatted or a label
it chose. A coach line is prose written by a language model, which is a category of risk a
blocked-term vocabulary is the wrong shape for. `recap_gate` grew its fourth step in the
same commit; the second half of this file is that step's controls, including the one that
matters most — that a step which runs over an empty list cannot be reported as a pass.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content import recap_data, recap_gate  # noqa: E402

_VOCAB = {"blocked_vices": ["Placeholder Habit"], "blocked_vice_keywords": ["placeholderterm"]}


@pytest.fixture
def clean_channel(monkeypatch):
    from privacy import content_filter_channel as cfc, privacy_guard

    monkeypatch.setattr(cfc, "load", lambda require=False: _VOCAB)
    monkeypatch.setattr(privacy_guard, "_vice_keywords", lambda: ["placeholderterm"])
    privacy_guard.reset_vocabulary_cache()
    yield
    privacy_guard.reset_vocabulary_cache()


class FakeTable:
    """A DDB stand-in that answers only the COACH# query, keyed by (pk, sk-prefix)."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        cond = kwargs["KeyConditionExpression"]
        # boto3's condition objects expose their operands; read the pk/sk out of them
        # rather than re-implementing the expression language.
        pk, sk_prefix = _condition_values(cond)
        out = []
        for r in self.rows:
            if r["pk"] != pk or not r["sk"].startswith(sk_prefix):
                continue
            if "FilterExpression" in kwargs and not _phase_ok(r, kwargs):
                continue
            out.append(r)
        return {"Items": sorted(out, key=lambda r: r["sk"])}


def _condition_values(cond):
    """(pk, sk_prefix) out of a `Key(pk).eq(x) & Key(sk).begins_with(y)` condition."""
    left, right = cond.get_expression()["values"]
    return left.get_expression()["values"][1], right.get_expression()["values"][1]


def _phase_ok(row, kwargs):
    """Mirror PHASE_FILTER_EXPRESSION: current phase, or no phase attribute at all."""
    from experiment import phase_filter

    wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
    return "phase" not in row or row["phase"] == wanted or phase_filter is None


def _row(coach_id, date, *, output_type="daily_brief", phase=None, **attrs):
    from common.constants import EXPERIMENT_PHASE_CURRENT

    row = {"pk": f"COACH#{coach_id}", "sk": f"OUTPUT#{date}#{output_type}", "phase": phase or EXPERIMENT_PHASE_CURRENT}
    row.update(attrs)
    return row


_PUBLIC = "His protein total of 245g clears the 190g target. I'm watching a structural " "vulnerability in the distribution across the day."


# ══════════════════════════════════════════════════════════════════════════════
# 1. SELECTION — the line is a prefix of something a coach wrote
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "text",
    [
        _PUBLIC,
        "One sentence with no terminator",
        "Short. Then more that should not appear.",
        "A question? Followed by an answer.",
        "Exclaimed! And then some.",
        "   leading and trailing whitespace is normalised.   ",
    ],
)
def test_first_sentence_is_always_a_prefix_of_the_input(text):
    """The whole acceptance in one assertion: nothing is added, nothing is reordered."""
    out = recap_data.first_sentence(text)
    normalised = " ".join(text.split())
    assert normalised.startswith(out.rstrip("…")), f"{out!r} is not a prefix of {normalised!r}"


def test_first_sentence_stops_at_the_first_terminator():
    assert recap_data.first_sentence("Short. Then more that should not appear.") == "Short."


def test_a_long_first_sentence_is_cut_at_a_word_boundary_with_an_ellipsis():
    long = "word " * 80
    out = recap_data.first_sentence(long.strip())
    assert len(out) <= recap_data.COACH_LINE_MAX_CHARS + 1
    assert out.endswith("…")
    assert not out.rstrip("…").endswith(" "), "cut mid-space, not at a word boundary"
    # Still a prefix — an ellipsis marks that the thought was cut, it does not add words.
    assert long.strip().startswith(out.rstrip("…"))


def test_no_text_is_no_line():
    for empty in ("", None, "   "):
        assert recap_data.first_sentence(empty) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE READ SEAM — public_summary only, and the record id travels with it
# ══════════════════════════════════════════════════════════════════════════════
def test_a_public_summary_becomes_the_line_and_names_its_record():
    table = FakeTable([_row("mind_coach", "2026-09-14", output_type="daily_brief_mind", public_summary=_PUBLIC)])
    line, source, status = recap_data.coach_line(table, "2026-09-14", "scorecard")

    assert line == "His protein total of 245g clears the 190g target."
    assert source == "COACH#mind_coach|OUTPUT#2026-09-14#daily_brief_mind"
    assert status == recap_data.LINE_OK


@pytest.mark.parametrize("owner_field", ["observatory_summary", "key_recommendation", "elena_quote", "content"])
def test_the_owner_register_is_never_quoted_on_a_public_card(owner_field):
    """#2972's whole point. `served_summary()` would have returned every one of these.

    These four fields are written TO Matthew — second person, coach register. A public
    Instagram card is the one audience they were never written for, and the failure would
    be silent: a plausible, well-formed, completely misaddressed sentence.
    """
    table = FakeTable([_row("mind_coach", "2026-09-14", **{owner_field: "You need to fix your protein distribution."})])
    line, source, status = recap_data.coach_line(table, "2026-09-14", "scorecard")

    assert line is None and source is None, f"{owner_field} reached a public card"
    assert status == recap_data.LINE_ABSENT, "a clean read that found nothing is ABSENT, not a failure"


def test_an_owner_directed_public_summary_is_rejected_by_the_audience_belt():
    """A row written before the write-side seam, or by a run that slipped past it."""
    table = FakeTable([_row("mind_coach", "2026-09-14", public_summary="Matthew — you need to fix your protein.")])
    assert recap_data.coach_line(table, "2026-09-14", "scorecard")[:2] == (None, None)


def test_a_held_condensation_leaves_the_card_silent():
    """ADR-104 HELD the prose; the card carries no line rather than a substitute."""
    table = FakeTable([_row("mind_coach", "2026-09-14", public_summary=None, content="the full narrative", derived_prose_held=True)])
    assert recap_data.coach_line(table, "2026-09-14", "scorecard")[:2] == (None, None)


def test_no_coach_ran_is_ABSENT_and_not_an_error():
    assert recap_data.coach_line(FakeTable([]), "2026-09-14", "scorecard") == (None, None, recap_data.LINE_ABSENT)


def test_a_table_error_is_no_line_but_is_NOT_reported_as_absent():
    """The #3768 assertion, made before the defect rather than after it.

    A card with no quote renders either way — that is deliberate, a missing quote is a
    smaller wrong than a missing card. What must never be true is that a failed READ and
    a quiet day produce the same record. This function queries COACH#* partitions, and
    the recap role can read them today only because its DynamoDB grant carries no
    LeadingKeys condition. One scope-tightening and every query here raises AccessDenied
    — at which point this status is the only thing that would say so.
    """

    class Broken:
        def query(self, **kwargs):
            raise RuntimeError("ddb is having a day")

    line, source, status = recap_data.coach_line(Broken(), "2026-09-14", "scorecard")
    assert (line, source) == (None, None)
    assert status == recap_data.LINE_UNREADABLE, "a failed read reported itself as a quiet day"


def test_one_broken_coach_does_not_hide_a_line_from_another():
    """Fail-soft, but not fail-quiet: a later coach still supplies the line."""

    class HalfBroken(FakeTable):
        def query(self, **kwargs):
            if "mind_coach" in str(kwargs["KeyConditionExpression"].get_expression()):
                raise RuntimeError("that partition is unhappy")
            return super().query(**kwargs)

    rows = [_row("physical_coach", "2026-09-14", public_summary="Physical says a thing.")]
    line, _src, status = recap_data.coach_line(HalfBroken(rows), "2026-09-14", "scorecard")
    assert line == "Physical says a thing."
    assert status == recap_data.LINE_OK


def test_a_previous_cycles_row_at_the_same_date_is_not_quoted():
    """The cross-genesis mistake that bit the beat picker twice, in a second partition."""
    table = FakeTable([_row("mind_coach", "2026-09-14", phase="pilot", public_summary=_PUBLIC)])
    assert recap_data.coach_line(table, "2026-09-14", "scorecard") == (None, None, recap_data.LINE_ABSENT)
    assert "FilterExpression" in table.queries[0], "the coach read skipped the phase filter"


# ══════════════════════════════════════════════════════════════════════════════
# 3. THE BEAT CHOOSES THE VOICE
# ══════════════════════════════════════════════════════════════════════════════
def test_the_beat_chooses_which_coach_speaks():
    rows = [
        _row("physical_coach", "2026-09-14", output_type="daily_brief_physical", public_summary="Physical says a thing."),
        _row("mind_coach", "2026-09-14", output_type="daily_brief_mind", public_summary="Mind says a thing."),
    ]
    session_line, _s1, _st1 = recap_data.coach_line(FakeTable(rows), "2026-09-14", "session")
    scorecard_line, _s2, _st2 = recap_data.coach_line(FakeTable(rows), "2026-09-14", "scorecard")

    assert session_line == "Physical says a thing."
    assert scorecard_line == "Mind says a thing."


def test_the_order_falls_through_to_whoever_actually_ran():
    """A day the head-of-list coach did not run still gets a line."""
    rows = [_row("labs_coach", "2026-09-14", output_type="daily_brief_labs", public_summary="Labs says a thing.")]
    line, _src, _st = recap_data.coach_line(FakeTable(rows), "2026-09-14", "session")
    assert line == "Labs says a thing."


def test_an_unknown_beat_uses_the_default_order():
    rows = [_row("physical_coach", "2026-09-14", public_summary="Physical says a thing.")]
    line, _src, _st = recap_data.coach_line(FakeTable(rows), "2026-09-14", "a-beat-that-does-not-exist")
    assert line == "Physical says a thing."


def test_the_card_order_is_DERIVED_from_the_operational_roster():
    """The first draft hand-typed the roster and was wrong on day one.

    It named `training_coach` — not an operational coach, never wrote an OUTPUT# row —
    and omitted `glucose_coach` and `explorer_coach`, which are. `test_coach_roster_set_
    guard_2334.py` caught it, which is the #2334 lesson landing exactly as designed: the
    roster is a SET, and a copy of it does not drift eventually, it starts drifted.
    """
    from coach import persona_registry

    for beat in ("session", "trajectory", "scorecard", "reckoning", "an-unknown-beat"):
        order = recap_data.card_coach_order(beat)
        assert set(order) == set(
            persona_registry.OPERATIONAL_COACH_IDS
        ), f"the {beat} order is not the operational roster — a hand-typed copy has crept back in"
        assert len(order) == len(set(order)), f"{beat} names a coach twice"


def test_the_beat_head_is_a_single_reference_not_an_enumeration():
    """One id per beat, which is the conformance guard's own line (#2844).

    `_MIN_MEMBERS = 2` there: a one-string literal is a reference, a two-string literal
    is an enumeration of registry vocabulary and must be derived. Keeping the head to a
    single coach is what makes this a preference rather than a second roster.
    """
    from coach import persona_registry

    for beat, lead in recap_data.CARD_COACH_HEAD.items():
        assert isinstance(lead, str), f"{beat}'s head is {lead!r} — a collection here is an enumeration (#2844)"
        assert lead in persona_registry.OPERATIONAL_COACH_IDS, f"{beat} prefers {lead}, which is not operational"
        assert recap_data.card_coach_order(beat)[0] == lead


def test_a_coach_added_to_the_platform_joins_the_card_with_no_edit_here():
    """The property the derivation buys, asserted rather than asserted-in-a-comment."""
    from coach import persona_registry

    order = recap_data.card_coach_order("session")
    assert order[0] == "physical_coach", "the beat head stopped being honoured"
    assert set(order[1:]) == set(persona_registry.OPERATIONAL_COACH_IDS) - {"physical_coach"}


def test_every_operational_coach_writes_public_summary_through_the_audience_guard():
    """Every coach the card can now quote must write the field through the guarded seam.

    There is exactly one writer of `public_summary` for the daily coaches, so the claim
    is checkable: the writer must be the guarded seam. Widened from the old hand-typed
    membership check, because the membership is now the whole operational roster.
    """
    src = (REPO / "lambdas" / "coach" / "coach_state_updater.py").read_text()
    assert (
        'audience_guard.reader_safe(extraction.get("public_summary")' in src
    ), "the single write seam for public_summary moved — every quotable coach's reader-safety claim rests on it"

    from coach import persona_registry

    stances = {p.stem for p in (REPO / "config" / "coaches").glob("*.json")}
    unknown = sorted(c for c in persona_registry.OPERATIONAL_COACH_IDS if c not in stances)
    assert not unknown, f"operational coaches with no stance file: {unknown}"


# ══════════════════════════════════════════════════════════════════════════════
# 3b. THE GROUNDING FAMILY'S COVERAGE OF THE CARD
# ══════════════════════════════════════════════════════════════════════════════
def test_the_card_is_not_a_generation_surface_and_the_registry_agrees():
    """#3749's fourth acceptance box, answered the way a SELECTION design answers it.

    The box asks that the grounded-generation test family cover the card as a surface.
    Under a generation design that would mean a `tests/grounding_wiring.py::SURFACES`
    entry. Under this one it means the opposite, and the opposite is checkable:

    `SURFACES` is DERIVED — `scan_tree()` AST-scans `lambdas/` for calls to a grounding
    chokepoint, and the registry supplies policy only for what the scan discovered. A
    hand-added entry for a surface that makes no such call would red the registry's own
    second direction ("every entry still resolves to a real discovered surface"). So the
    correct state is: the card's modules make no chokepoint call, the scan finds nothing,
    and the family's real contract — a NEW ungated AI surface reds the build — is what
    covers the card going forward.

    This test is the standing assertion of that premise. The day someone adds a Bedrock
    call to the card path, the scan discovers it, `test_grounding_wiring_1967.py` demands
    a policy decision for it, and this test reds first with the reason why.
    """
    import tests.grounding_wiring as gw

    card_modules = (
        "lambdas/content/recap_data.py",
        "lambdas/content/recap_gate.py",
        "lambdas/web/recap_layouts.py",
        "lambdas/web/recap_card_lambda.py",
    )
    all_surfaces = gw.scan_tree()
    # The premise, first. A scanner returning nothing would make the assertion below
    # vacuous — "the card is not a generation surface" and "nothing is" look identical
    # from here, and only one of them is a pass.
    assert len(all_surfaces) >= 10, f"the grounding scan found only {len(all_surfaces)} surfaces — it has gone blind"

    discovered = {key for key in all_surfaces if any(key.startswith(m + "::") for m in card_modules)}
    assert not discovered, (
        f"the card path now calls a grounding chokepoint: {sorted(discovered)}. It became a generation "
        "surface, which #3749 exists to prevent — the coach line is SELECTED. If that is intended, it "
        "needs a SURFACES policy entry and a grading story, not just a passing test."
    )


def test_no_card_module_reaches_bedrock():
    """The blunter half of the same claim, independent of the grounding scan's shape."""
    import ast

    for rel in (
        "lambdas/content/recap_data.py",
        "lambdas/content/recap_gate.py",
        "lambdas/web/recap_layouts.py",
        "lambdas/web/recap_card_lambda.py",
    ):
        tree = ast.parse((REPO / rel).read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [f"{node.module or ''}.{a.name}" for a in node.names]
            for n in names:
                assert "bedrock" not in n.lower(), f"{rel} imports {n} — the card must not generate text"

    # The gate's classifier is the ONE place a model could have been called, and it
    # deliberately is not. `recap_gate` may import the sensitivity gate (which owns a
    # lazy bedrock classifier); what matters is that the card never wires it.
    src = (REPO / "lambdas" / "content" / "recap_gate.py").read_text()
    assert "bedrock_offtopic_classifier" not in src, (
        "the card wired the Bedrock classifier — first-party editorial is on-topic by construction, "
        "and paying for that verdict per card was never the design"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. STEP 4 — the semantic screen the coach line made necessary
# ══════════════════════════════════════════════════════════════════════════════
def test_a_vice_term_in_the_coach_line_holds_the_card(clean_channel):
    result = recap_gate.gate(["Day 8"], free_text=["He kept the placeholderterm streak going."])
    assert result.verdict == recap_gate.VERDICT_HELD
    assert result.may_send is False


def test_a_real_name_in_the_coach_line_holds_the_card(clean_channel):
    result = recap_gate.gate(["Day 8"], free_text=["His numbers look like Huberman's."])
    assert result.verdict == recap_gate.VERDICT_HELD


def test_pii_in_the_coach_line_holds_the_card(clean_channel):
    result = recap_gate.gate(["Day 8"], free_text=["Reach him at matthew@example.com about it."])
    assert result.verdict == recap_gate.VERDICT_HELD


def test_the_gate_record_never_carries_the_coach_line(clean_channel):
    result = recap_gate.gate(["Day 8"], free_text=["He kept the placeholderterm streak going."])
    payload = result.to_dict()
    assert "placeholderterm" not in str(payload)
    assert "streak going" not in str(payload), "the held prose was copied into the audit record"


def test_a_clean_coach_line_clears(clean_channel):
    result = recap_gate.gate(["Day 8"], free_text=[_PUBLIC])
    assert result.verdict == recap_gate.VERDICT_CLEARED
    assert result.may_send is True


def test_a_classifier_that_raises_holds_the_card(clean_channel):
    def boom(_text):
        raise RuntimeError("bedrock is having a day")

    result = recap_gate.gate(["Day 8"], free_text=[_PUBLIC], offtopic_classifier=boom)
    assert result.verdict == recap_gate.VERDICT_HELD, "a classifier error must fail closed"


def test_a_classifier_that_cannot_vouch_holds_the_card(clean_channel):
    from privacy import broadcast_sensitivity_gate as bsg

    result = recap_gate.gate(["Day 8"], free_text=[_PUBLIC], offtopic_classifier=lambda t: bsg.OfftopicResult(None, 0.0))
    assert result.verdict == recap_gate.VERDICT_HELD


def test_step_4_runs_no_classifier_when_there_is_no_prose(clean_channel):
    """The control that keeps step 4 from being a gate that cannot fail, both ways.

    A v1 card has no prose. Step 4 must CLEAR it — holding a card for the absence of the
    thing step 4 judges would be absurd — but it must clear it by SKIPPING, not by calling
    a classifier on "". This test is what distinguishes those two, and the sibling above
    is what proves the step still fires when prose is present.
    """
    calls = []

    def spy(text):
        calls.append(text)
        raise AssertionError("the classifier ran with nothing to classify")

    result = recap_gate.gate(["Day 8", "3 workouts"], free_text=[], offtopic_classifier=spy)
    assert result.verdict == recap_gate.VERDICT_CLEARED
    assert calls == []


def test_step_4_runs_after_step_3_not_before(clean_channel):
    """ADR-105's ordering, asserted by observation rather than by reading the source.

    A card whose DRAWN copy already fails the deterministic whole-card screen must be held
    by step 3, and step 4's classifier must never be reached — a held card should not cost
    a model call, and a semantic verdict must never be able to precede a deterministic one.
    """
    calls = []

    result = recap_gate.gate(
        ["Day 8", "a placeholderterm evening"],
        free_text=["A perfectly clean sentence."],
        offtopic_classifier=lambda t: calls.append(t),
    )
    assert result.verdict == recap_gate.VERDICT_HELD
    assert "publish gate" in result.reason, "held by step 3, not step 4"
    assert calls == [], "step 4 ran before or despite step 3's hold"


def test_the_default_classifier_spends_no_bedrock(clean_channel, monkeypatch):
    """First-party editorial is on-topic by construction — the horizons precedent."""
    from ai import bedrock_client

    def _explode(*a, **k):
        raise AssertionError("the default card classifier called Bedrock")

    monkeypatch.setattr(bedrock_client, "invoke", _explode)
    assert recap_gate.gate(["Day 8"], free_text=[_PUBLIC]).verdict == recap_gate.VERDICT_CLEARED

    verdict = recap_gate._first_party_editorial_classifier("anything at all")
    assert verdict.on_topic is True and verdict.confidence == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. THE CARD — drawn when there is a line, absent when there is not
# ══════════════════════════════════════════════════════════════════════════════
pytest.importorskip("PIL")


def _facts(**kw):
    f = recap_data.DayFacts(date="2026-09-14", day_n=9)
    f.weight_lb = 300.0
    f.baseline_weight_lb = 320.0
    f.goal_weight_lb = 220.0
    f.grade_letter = "B"
    f.component_scores = {"nutrition": 71.0, "movement": 88.0}
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def test_no_coach_line_draws_nothing_at_all():
    """Absence stays absence: the rendered bytes are identical to a card without one."""
    from web import recap_canvas, recap_layouts

    without = recap_canvas.to_png_bytes(recap_layouts.scorecard(_facts(), date_label="SEP 14"))
    also_without = recap_canvas.to_png_bytes(recap_layouts.scorecard(_facts(coach_line=None), date_label="SEP 14"))
    assert without == also_without


def test_a_coach_line_changes_the_card():
    from web import recap_canvas, recap_layouts

    without = recap_canvas.to_png_bytes(recap_layouts.scorecard(_facts(), date_label="SEP 14"))
    with_line = recap_canvas.to_png_bytes(recap_layouts.scorecard(_facts(coach_line=_PUBLIC), date_label="SEP 14"))
    assert without != with_line, "the coach line was selected but never drawn"


def _dense_facts(**kw):
    """A day with everything on it — the day a card is actually worth posting.

    THE FIXTURE THAT CAUGHT THE REAL BUG. The first version of this test used the sparse
    `_facts()` and passed on all four layouts while the line was invisible on the two
    beats that matter most. `_coach_line` drops itself below FLOOR_Y rather than
    overprint the footer, and on a real training day the fact rows had already pushed y
    past the floor — so the quote was selected, screened, stored in the picker record,
    and drawn nowhere. Rendering a card against LIVE data is what showed it; no unit
    test with a thin fixture could.
    """
    w = recap_data.WorkoutFact(
        title="Legs - Lower",
        n_exercises=8,
        n_sets=27,
        volume_lbs=49400.0,
        top_exercise="Romanian Deadlift (Barbell)",
        exercises=[
            "Romanian Deadlift (Barbell)",
            "Linear Leg Press",
            "Calf Press (Machine)",
            "Leg Extension (Machine)",
            "Cable Pallof Press",
            "Glute Machine Kickback",
            "Walking",
            "Stretching",
        ],
    )
    base = dict(
        workouts=[w],
        acwr=1.29,
        acwr_zone="safe",
        readiness=57.0,
        missed_tier0=["Walk 5k", "Morning Sunlight / Luminette Glasses"],
        weekly_rate_lb=-1.4,
        rate_provisional=False,
        rate_ci=(-2.1, -0.7),
        component_scores={"nutrition": 71.0, "movement": 88.0, "sleep_quality": 64.0, "recovery": 55.0},
    )
    base.update(kw)
    return _facts(**base)


def _drawn_pixels(img):
    """How much of the canvas is not background — a proxy for "something was drawn"."""
    return sum(1 for px in img.convert("L").getdata() if px > 40)


@pytest.mark.parametrize("layout", ["scorecard", "trajectory", "session", "reckoning"])
@pytest.mark.parametrize("fixture", ["sparse", "dense"])
def test_every_layout_DRAWS_the_line_on_a_real_day(layout, fixture):
    """Not "the bytes differ" — "more ink landed on the canvas".

    A byte comparison passes when a layout changes anything at all, including nothing
    visible. Counting drawn pixels is what distinguishes "the quote is on the card" from
    "the quote was computed and silently dropped", which is precisely how the first
    version of this test passed against a card that showed no line.
    """
    from web import recap_layouts

    kwargs = {"date_label": "SEP 14"}
    if layout == "reckoning":
        kwargs["week_n"] = 1
    make = _dense_facts if fixture == "dense" else (lambda **kw: _facts(workouts=_dense_facts().workouts, **kw))
    fn = getattr(recap_layouts, layout)

    before = _drawn_pixels(fn(make(), **kwargs))
    after = _drawn_pixels(fn(make(coach_line=_PUBLIC), **kwargs))

    assert after > before + 500, (
        f"{layout} on a {fixture} day drew no visible coach line "
        f"({before} -> {after} lit pixels). It was selected and dropped — check FLOOR_Y."
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. THE CAPTION
# ══════════════════════════════════════════════════════════════════════════════
def test_the_caption_carries_the_line_and_stays_under_the_cap():
    from web import recap_layouts

    caption = recap_layouts.caption_for_beat(
        "scorecard", _facts(coach_line="His protein cleared the target."), day_label="Day 9", date_label="SEP 14"
    )
    assert "His protein cleared the target." in caption
    assert len(caption) <= recap_layouts.CAPTION_MAX_CHARS


def test_a_quote_that_fits_is_kept():
    from web import recap_layouts

    facts = _facts(coach_line="x" * 60)
    caption = recap_layouts.caption_for_beat("scorecard", facts, day_label="Day 9", date_label="SEP 14")
    assert "x" * 60 in caption and len(caption) <= recap_layouts.CAPTION_MAX_CHARS


def test_a_caption_that_would_overflow_drops_the_quote_rather_than_the_numbers():
    """A full-length line beside a day with long habit names — the realistic overflow.

    `COACH_LINE_MAX_CHARS` bounds the quote, but nothing bounds a habit NAME, so the two
    together are what can exceed the cap. The quote is the part that goes: a caption
    truncated mid-number reads as broken, and a caption with no quote reads as a caption.
    """
    from web import recap_layouts

    line = "x" * recap_data.COACH_LINE_MAX_CHARS
    # Two habit names long enough that the quote cannot also fit under the cap. The cap
    # rose 300 → 480 on 2026-09-19 when the caption grew its fixed close (NEXT line, site,
    # tags); the premise assert below is what keeps this fixture honest against the cap.
    habits = [
        "the five kilometre morning walk before breakfast, logged on the watch and checked off by hand",
        "the evening mobility and stretching routine, twenty minutes, before the phone goes away",
    ]

    # Assert the premise before asserting the behaviour. Without this, a future change
    # that shortens the stats would make the quote fit, the drop branch would stop being
    # exercised, and the test would keep passing while proving nothing (#3749).
    without_quote = recap_layouts.caption_for_beat("scorecard", _facts(missed_tier0=habits), day_label="Day 9", date_label="SEP 14")
    assert len(without_quote) + len(line) + 4 > recap_layouts.CAPTION_MAX_CHARS, "this fixture no longer overflows"

    caption = recap_layouts.caption_for_beat(
        "scorecard", _facts(coach_line=line, missed_tier0=habits), day_label="Day 9", date_label="SEP 14"
    )
    assert len(caption) <= recap_layouts.CAPTION_MAX_CHARS
    assert line not in caption, "the quote survived an overflow it should have lost"
    assert "Today graded B." in caption, "the stats were sacrificed for the quote"


def test_the_cap_is_enforced_over_the_finished_string():
    from web import recap_layouts

    facts = _facts(missed_tier0=["a" * 200, "b" * 200])
    caption = recap_layouts.caption_for_beat("scorecard", facts, day_label="Day 9", date_label="SEP 14")
    assert len(caption) <= recap_layouts.CAPTION_MAX_CHARS


def test_the_coach_line_reaches_the_gate_through_gate_strings():
    """The renderer must hand the line to BOTH screens, not just the semantic one."""
    from web import recap_layouts

    facts = _facts(coach_line="He kept the placeholderterm streak going.")
    assert facts.coach_line in recap_layouts.gate_strings(facts, "")
    assert facts.free_text() == [facts.coach_line]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
