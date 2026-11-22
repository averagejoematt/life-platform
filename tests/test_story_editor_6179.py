"""tests/test_story_editor_6179.py — the Story Desk's editor and the hard gates it must not loosen (#6179).

Owner ruling 2026-11-22: "An editor should make the writing better; a verifier should establish that the result is
true." The fixture draft is built from sentences of a chapter already published on the live site (The Rate Flag,
/story/week-12/), so no unpublished text is in this file. No model is called: the writer, the fact read and the editor
are fakes.

What is proven here:
  1. the switch defaults OFF, and off is today's pipeline (the editor is never reached, the row shape is unchanged);
  2. the hard gates are not loosened: ``post_hard`` is exactly ``post`` minus its style findings, and the dek loses
     only its style ("top line:") findings — the one reclassification;
  3. a revised draft that fails ANY hard gate is held exactly as the same text is held on the off path: the publish
     audit blocks it and the owner's approval click refuses it;
  4. the editor cannot add a claim: a revision with a new number, date word, name, quotation, scene, feeling or cause
     is discarded, and the previous version goes forward;
  5. the editor is bounded (two calls at most), runs on a different model from the writer, and stands down when the
     budget tier pauses the chronicle feature;
  6. a revised week always waits for the owner (its advisory list is never empty, so publish_holds forces the preview).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import budget_guard, model_routing  # noqa: E402
from content import (  # noqa: E402
    autopublish_audit,
    elena_canon,
    story_craft,
    story_editor,
    story_pipeline,
    story_writers,
)

# ── fixtures: sentences from the published Week 10 chapter (/story/week-12/) ──

DRAFT = """"The Rate Flag"

Monday, Day 65 of a year-long experiment, put him on the scale at 292.6 pounds — nearly 35 pounds below the 327.3 he weighed on the first morning. The number is good. The speed is the question.

This week's loss was 5.2 pounds, against a season average of 3.8. That is what tripped the platform's lean-mass rate flag.

Protein is the part he controls. Across the seven days he averaged 151 grams against a floor of 170. Only Sunday (188) and Monday (174) cleared it; the furthest misses were Thursday (134), Saturday (124) and Tuesday (115).

Lisa Park had called 65 for that Tuesday morning. The reading came in 28 points lower, outside her tolerance band.

Max Reyes's calls fared better. On Thursday he made two calls for Friday morning: recovery around 68.8, and weight around 295 pounds. Friday's recovery was 73 and the scale read 293.6. Both landed within tolerance.

There is no note from him this week explaining the choice, so this installment reports what happened and leaves the reason alone.

---
*Week 10 of The Measured Life*"""

# A revision in the direction of the prototype second edition: cuts and reorders only, nothing added.
REVISION_OK = """"The Rate Flag"

This week's loss was 5.2 pounds, against a season average of 3.8. That is what tripped the platform's lean-mass rate flag.

On Monday, Day 65, the scale read 292.6 pounds, nearly 35 below the 327.3 of the first morning.

Protein is the part he controls. He averaged 151 grams against a floor of 170, and only Sunday and Monday cleared it.

Lisa Park had called 65 for that Tuesday morning. The reading came in 28 points lower, outside her tolerance band.

On Thursday Max Reyes called Friday morning's recovery around 68.8 and weight around 295 pounds. Friday's recovery was 73 and the scale read 293.6.

There is no note from him this week explaining the choice, so this installment reports what happened and leaves the reason alone.

---
*Week 10 of The Measured Life*"""

DOSSIER = {
    "week": 10,
    "window": {
        "start": "2026-11-04",
        "end": "2026-11-10",
        "experiment_days": "Day 60 to Day 66",
        "calendar": {"2026-11-09": "Monday, Day 65", "2026-11-05": "Thursday, Day 61", "2026-11-06": "Friday, Day 62"},
    },
    "weight": {
        "available": True,
        "first_weigh_in": {"lbs": 327.3},
        "week_start": {"lbs": 295.0},
        "week_end": {"lbs": 292.6},
        "week_change_lbs": -5.2,
        "season_avg_weekly_change_lbs": -3.8,
        "total_change_lbs": -34.7,
        "weigh_ins_in_window": [{"date": "2026-11-05", "lbs": 293.9}, {"date": "2026-11-06", "lbs": 293.6}],
    },
    "nutrition": {"protein_avg_g": 151, "protein_floor_g": 170, "protein_by_day": [188, 174, 134, 124, 115]},
    "recovery_and_sleep": {"recovery_by_day": [63, 37, 73, 68, 77]},
    "roster": [{"coach_id": "sleep", "name": "Lisa Park"}, {"coach_id": "physical", "name": "Max Reyes"}],
    "predictions": {
        "graded_this_week": [
            {"coach": "Lisa Park", "claim": "Tuesday morning recovery near 65", "result": "wrong", "evidence": "37 vs 65 (-28)"},
            {"coach": "Max Reyes", "claim": "Friday recovery near 68.8 and weight near 295", "result": "right", "evidence": "73; 293.6"},
        ]
    },
    "coaches_this_week": [],
    "owner_voice": {"answers": []},
}
BUDGET = {"top_line": "Day 65: the scale is down again and the pace has tripped the platform's own flag.", "featured_coaches": ["physical"]}

# Marker words the fake fact read treats as false, so each hard gate can be tripped on demand.
FACT_BAD = "nineteen consecutive mornings"


def _fake_fact_check(text, dossier, *, context=None, invoke=None):
    return [f"fact: {FACT_BAD!r} — the dossier shows no such streak → cut it"] if FACT_BAD in text else []


@pytest.fixture
def gates(monkeypatch):
    monkeypatch.setattr(story_writers, "fact_check", _fake_fact_check)
    return story_pipeline._Gates(10, DOSSIER, BUDGET, {}, None, {})


def _reply(text: str, notes=("none",), stop="end_turn"):
    body = text + f"\n\n{story_editor.NOTES_MARKER}\n" + "\n".join(f"- {n}" for n in notes)
    return {"content": [{"type": "text", "text": body}], "stop_reason": stop, "usage": {"input_tokens": 9000, "output_tokens": 1800}}


class _Editor:
    """A scripted editor model: hands back the queued replies in order and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, body, model):
        self.calls.append((body, model))
        return self.replies.pop(0) if self.replies else _reply(DRAFT)


def _revise(gates, editor, **kw):
    kw.setdefault("allow_spend", lambda: True)
    return story_editor.revise(
        DRAFT,
        packet=json.dumps(DOSSIER),
        allowed=gates.allowed,
        notes_for=lambda body: story_editor.craft_notes(body, dossier=DOSSIER, weight_known=True, previous={}, owner_lines=[])
        + story_editor.review_notes(body, DOSSIER),
        hard_check=lambda md: gates.post_deterministic(md, "end_turn"),
        invoke=editor,
        log=lambda *_: None,
        **kw,
    )


# ── 1. the switch ────────────────────────────────────────────────────────────


def test_the_switch_defaults_off_and_only_an_explicit_on_enables_it():
    assert story_editor.enabled({}) is False
    for off in ("off", "", "0", "no", "onn", "false"):
        assert story_editor.enabled({"STORY_EDITOR": off}) is False, off
    for on in ("on", "ON", "1", "true"):
        assert story_editor.enabled({"STORY_EDITOR": on}) is True, on


def _wire_live_week(monkeypatch, *, draft=DRAFT, editor=None):
    """live_week with every model and table read faked. Returns the list the fake writer appends its calls to."""
    from content import story_desk, story_dossier, story_ledger

    wk = {"week": 10, "start": "2026-11-04", "end": "2026-11-10", "day_first": 60, "day_last": 66}
    monkeypatch.setattr(story_dossier, "season_weeks", lambda through=None: [wk])
    monkeypatch.setattr(story_dossier, "week_dossier", lambda table, w: (json.loads(json.dumps(DOSSIER)), []))
    monkeypatch.setattr(story_ledger, "latest_visible", lambda table, pk, d: {})
    monkeypatch.setattr(story_pipeline, "_published_before", lambda table, pk, d, n: {})
    monkeypatch.setattr(story_desk, "run_desk", lambda dossier, ledger, week, log=print: dict(BUDGET))
    writer_calls = []

    def write_chronicle(dossier, budget, ledger, *, week, previous=None, fix=None, prior_draft=None, invoke=None):
        writer_calls.append(fix)
        return draft, "end_turn"

    monkeypatch.setattr(story_writers, "write_chronicle", write_chronicle)
    monkeypatch.setattr(story_writers, "fact_check", _fake_fact_check)
    monkeypatch.setattr(
        story_writers,
        "write_episode",
        lambda *a, **k: (
            {"title": "t", "excerpt": "e", "turns": [{"speaker": "elena", "line": "I'm Elena Voss. This has been The Measured Life."}]},
            "end_turn",
        ),
    )
    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
    from ai import bedrock_client

    monkeypatch.setattr(bedrock_client, "invoke_with_retry", editor or _Editor(_reply(REVISION_OK)))
    return writer_calls


def test_switch_off_is_todays_pipeline_and_the_editor_is_never_reached(monkeypatch):
    monkeypatch.delenv("STORY_EDITOR", raising=False)
    _wire_live_week(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("the editor ran with the switch off")

    monkeypatch.setattr(story_editor, "revise", _boom)
    out = story_pipeline.live_week(None, "2026-11-10", log=lambda *_: None)
    assert "editor" not in out
    assert DRAFT.splitlines()[2][:40] in out["raw_installment"]  # the writer's text, untouched
    # the craft verdict is today's: story_craft's own findings, no advisory prefix
    assert out["craft_findings"] and not any(f.startswith(story_editor.ADVISORY_PREFIX) for f in out["craft_findings"])


def test_switch_on_runs_the_editor_and_the_verifier_sees_the_revised_text(monkeypatch):
    monkeypatch.setenv("STORY_EDITOR", "on")
    _wire_live_week(monkeypatch, editor=_Editor(_reply(REVISION_OK), _reply(REVISION_OK)))
    out = story_pipeline.live_week(None, "2026-11-10", log=lambda *_: None)
    assert out["editor"]["accepted"] >= 1
    assert "Max Reyes's calls fared better" not in out["raw_installment"]  # the revision went forward
    assert out["title"] == "The Rate Flag"
    assert out["craft_findings"][0] == story_editor.ADVISORY_PREFIX + story_editor.REVISED_NOTE
    assert all(f.startswith(story_editor.ADVISORY_PREFIX) for f in out["craft_findings"])


def test_switch_on_writer_rewrites_answer_only_hard_findings(monkeypatch):
    monkeypatch.setenv("STORY_EDITOR", "on")
    bad = DRAFT.replace("The number is good.", f"He logged {FACT_BAD}.")
    calls = _wire_live_week(monkeypatch, draft=bad)
    story_pipeline.live_week(None, "2026-11-10", log=lambda *_: None)
    fixes = [f for f in calls if f]
    assert fixes, "a hard finding must still get the writer's corrective rewrite"
    assert all(not str(x).startswith(("craft:", "repeat:")) for f in fixes for x in f), "style findings went to the writer"


# ── 2. the hard gates are not loosened ───────────────────────────────────────

_HARD_SPECIMENS = {
    "clean": DRAFT,
    "ungrounded number": DRAFT.replace("averaged 151 grams", "averaged 161 grams"),
    "quote not held": DRAFT.replace(
        "Lisa Park had called 65",
        'Park said, "the recovery numbers will rebound strongly by the middle of the week for sure." She had called 65',
    ),
    "story door count": DRAFT.replace("The speed is the question.", "It is his fifteenth reset."),
    "off-record": DRAFT.replace("Protein is the part he controls.", "His wife cooked dinner."),
    "fact read": DRAFT.replace("The number is good.", f"He logged {FACT_BAD}."),
    "cut off": DRAFT.rsplit("---", 1)[0],
    "craft only": DRAFT.replace("The speed is the question.", "The speed is the story. The question is whether it holds."),
}


def test_post_hard_is_exactly_post_minus_its_style_findings(gates):
    for name, text in _HARD_SPECIMENS.items():
        full = gates.post(text, "end_turn")
        hard = gates.post_hard(text, "end_turn")
        assert sorted(hard) == sorted(f for f in full if not autopublish_audit.is_style_finding(f)), name
        assert all(autopublish_audit.is_style_finding(f) for f in full if f not in hard), name


def test_every_hard_specimen_trips_its_gate(gates):
    for name, text in _HARD_SPECIMENS.items():
        hard = gates.post_hard(text, "end_turn")
        assert bool(hard) is (name not in ("clean", "craft only")), (name, hard)


def test_the_dek_loses_only_its_style_findings(gates):
    top = "Day 65: a 5.2-pound drop, 151 grams of protein, 37 recovery and 999 of something else, per the WHOOP strap and the scale."
    full = gates.dek(top)
    hard = gates.dek_hard(top)
    moved = [f for f in full if f not in hard]
    assert moved and all(f.startswith(("dek: top line:", "dek: craft:")) for f in moved), moved
    assert any("999" in f for f in hard), "an ungrounded figure in the dek is still hard"
    assert set(hard) <= set(full)


# ── 3. a revised draft that fails a hard gate is held exactly as before ──────


def _row(text, findings, craft):
    return {
        "sk": "DATE#2026-11-10",
        "date": "2026-11-10",
        "status": "draft",
        "title": "The Rate Flag",
        "stats_line": "Day 60 to Day 66",
        "content_markdown": text,
        "desk_findings_json": json.dumps({"post": findings, "episode": []}),
        "desk_craft_json": json.dumps(craft),
        "publish_hold": "craft_hold" if craft else None,
    }


@pytest.fixture
def approve(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "matthew-life-platform")
    path = Path(__file__).resolve().parents[1] / "lambdas" / "emails" / "chronicle_approve_lambda.py"
    spec = importlib.util.spec_from_file_location("chronicle_approve_lambda_6179", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_revision_failing_any_hard_gate_is_held_exactly_as_the_off_path_holds_it(gates, approve):
    for name, text in _HARD_SPECIMENS.items():
        if name in ("clean", "craft only"):
            continue
        off_row = _row(text, gates.post(text, "end_turn"), story_craft.chronicle_findings(text, week=10))
        on_row = _row(text, gates.post_hard(text, "end_turn"), story_editor.advisory_lines({"accepted": 1, "advisory": []}))
        off_block = [b for b in autopublish_audit.blocking_items(off_row) if not b.startswith("craft hold")]
        on_block = [b for b in autopublish_audit.blocking_items(on_row) if not b.startswith("craft hold")]
        assert on_block, name
        assert sorted(on_block) == sorted(off_block), name
        assert approve.approval_refusal(on_row) == approve.approval_refusal(off_row) != [], name


def test_a_clean_revision_still_needs_the_owner_click(gates, approve):
    row = _row(REVISION_OK, gates.post_hard(REVISION_OK, "end_turn"), story_editor.advisory_lines({"accepted": 1, "advisory": []}))
    assert approve.approval_refusal(row) == []  # nothing true is wrong with it, so his click may publish it …
    assert any(b.startswith("craft hold") for b in autopublish_audit.blocking_items(row))  # … and nothing else can


def test_editor_advisory_is_never_empty_so_publish_holds_forces_the_preview():
    for record in ({"accepted": 1, "advisory": []}, {"accepted": 0, "advisory": []}, {"accepted": 0, "advisory": ["x"]}):
        assert story_editor.advisory_lines(record)


# ── 4. the editor cannot add a claim ─────────────────────────────────────────


def test_a_pure_cut_and_reorder_revision_carries_no_new_claim(gates):
    assert story_editor.new_claims(REVISION_OK, DRAFT, json.dumps(DOSSIER), gates.allowed) == []


@pytest.mark.parametrize(
    "added, what",
    [
        ("He averaged 151 grams, up from 140 the week before.", "number"),
        ("He averaged 151 grams across twenty-two meals.", "number"),
        ("Marcus Webb had warned about this.", "name"),
        ("The plan's waypoint arrives in December.", "date word"),
        ('Reyes put it simply: "the scale is lying to him this week."', "quotation"),
        ("When I reached him on Friday, he paused before answering.", "scene"),
        ("He felt frustrated by the slow week.", "feeling"),
        ("Protein fell because he was travelling.", "cause"),
    ],
)
def test_a_revision_that_adds_a_claim_is_caught(gates, added, what):
    revision = REVISION_OK.replace("Protein is the part he controls.", f"Protein is the part he controls. {added}")
    found = story_editor.new_claims(revision, DRAFT, json.dumps(DOSSIER), gates.allowed)
    assert found, what


def test_a_claim_carrying_revision_is_discarded_and_the_draft_goes_forward(gates):
    invented = REVISION_OK.replace("Protein is the part he controls.", "Marcus Webb, when I reached him this week, paused.")
    editor = _Editor(_reply(invented), _reply(invented))
    rec = _revise(gates, editor)
    assert rec["text"] == DRAFT and rec["accepted"] == 0
    assert [r["outcome"] for r in rec["rounds"]] == ["discarded", "discarded"]
    assert "THROWN AWAY" in editor.calls[1][0]["messages"][0]["content"][-1]["text"]  # round two is told why
    assert any("discarded" in a for a in rec["advisory"])


def test_a_revision_that_adds_a_hard_finding_is_discarded(gates):
    door = REVISION_OK.replace("Protein is the part he controls.", "Protein is the part he controls on his fifteenth reset.")
    rec = _revise(gates, _Editor(_reply(door), _reply(DRAFT)))
    assert rec["rounds"][0]["outcome"] == "discarded"
    assert any("hard-gate finding" in w for w in rec["rounds"][0]["why"])


def test_the_title_is_the_ledgers_and_the_editor_cannot_change_it(gates):
    retitled = REVISION_OK.replace('"The Rate Flag"', '"Fast Enough to Worry"', 1)
    rec = _revise(gates, _Editor(_reply(retitled)))
    assert story_writers.split_title(rec["text"])[0] == "The Rate Flag"


# ── 5. bounded, a different model, budget-aware ──────────────────────────────


def test_at_most_two_editor_calls_a_week(gates):
    still_noisy = REVISION_OK.replace("Protein is the part he controls.", "Protein is the story.")
    editor = _Editor(*[_reply(still_noisy)] * 5)
    rec = _revise(gates, editor)
    assert len(editor.calls) == story_editor.MAX_ROUNDS == 2
    assert rec["accepted"] == 2
    assert any("is the story" in a for a in rec["advisory"]), "what the editor could not fix rides along for the owner"


def test_the_editor_runs_on_a_different_model_from_the_writer():
    assert model_routing.model_for("story.editor", env={}) != model_routing.model_for("story.writer", env={})
    assert story_editor.EDITOR_MODEL != story_writers.WRITER_MODEL


def test_the_editor_spends_under_the_band_2_reader_narrative_feature():
    assert model_routing.ROUTES["story.editor"].feature == story_editor.BUDGET_FEATURE == "chronicle"
    assert budget_guard._FEATURE_CUTOFF["chronicle"] == 2


def test_the_same_model_is_self_review_and_the_edit_is_skipped(gates):
    editor = _Editor(_reply(REVISION_OK))
    rec = _revise(gates, editor, editor_model="m", writer_model="m")
    assert editor.calls == [] and rec["text"] == DRAFT and rec["advisory"]


def test_a_paused_budget_tier_skips_the_edit(gates):
    editor = _Editor(_reply(REVISION_OK))
    rec = _revise(gates, editor, allow_spend=lambda: False)
    assert editor.calls == [] and rec["text"] == DRAFT
    assert "budget tier" in rec["advisory"][0]


def test_an_editor_error_leaves_the_draft(gates):
    def broken(body, model):
        raise RuntimeError("throttled")

    rec = _revise(gates, broken)
    assert rec["text"] == DRAFT and rec["rounds"][0]["outcome"] == "error"


def test_a_cut_off_editor_reply_is_discarded(gates):
    rec = _revise(gates, _Editor(_reply(REVISION_OK, stop="max_tokens"), _reply(DRAFT)))
    assert rec["rounds"][0]["outcome"] == "discarded"


# ── the prompt: Elena from the canon, the packet cached ──────────────────────


def test_elena_comes_from_the_canon_and_is_not_redefined_here():
    assert elena_canon.voice_block() in story_editor.system_prompt()
    src = Path(story_editor.__file__).read_text()
    for line in elena_canon.TEMPERAMENT + elena_canon.NEVER:
        assert line not in src, "story_editor restates the canon instead of importing it"


def test_the_packet_is_the_cached_prefix_and_the_draft_is_not(gates):
    body = story_editor.edit_body(story_editor.system_prompt(), "PACKET", DRAFT, ["a note"])
    blocks = body["messages"][0]["content"]
    assert blocks[0].get("cache_control") and "PACKET" in blocks[0]["text"] and DRAFT not in blocks[0]["text"]
    assert DRAFT in blocks[1]["text"] and not blocks[1].get("cache_control")


def test_the_editor_sees_the_writers_own_evidence():
    assert story_editor.packet_for(DOSSIER, BUDGET, {}, 10, None) == story_writers._context(DOSSIER, BUDGET, {}, 10, None)


def test_review_notes_catch_the_debt_maps_tics():
    body = (
        "Matthew is a man running a year-long, fully instrumented health experiment.\n\n"
        "The rate is the story. That number deserves a moment, because it has been earned.\n\n"
        "Marcus Webb, when I reached him this week, said little. He paused.\n\n"
        "Max Reyes's calls fared better: both landed within tolerance."
    )
    notes = " | ".join(story_editor.review_notes(body, DOSSIER))
    for expect in ("re-introduces", "is the story", "flattery", "scene or interview", "nothing changes"):
        assert expect in notes, expect
    assert story_editor.review_notes(REVISION_OK.split("\n", 2)[2], DOSSIER) == []


def test_the_same_hard_finding_in_a_reworded_sentence_is_not_a_new_one():
    """Found by the first dry run: a revision that kept one callback problem but reworded its sentence was discarded as
    'adding' it. The comparison keys on the finding without its sentence excerpt, and counts: one more is one more."""
    before = [
        "callback: '60' in a sentence recalling Week 4 does not appear in Week 4: \"The bet from last week is settled first: it fell\""
    ]
    reworded = [
        "callback: '60' in a sentence recalling Week 4 does not appear in Week 4: \"Last week's bet is settled first, and it went the other way\""
    ]
    assert story_editor.added_findings(reworded, before) == []
    assert story_editor.added_findings(reworded * 2, before) == reworded
    assert story_editor.added_findings(
        ["ungrounded number: '161' is not in the week's dossier"], ["ungrounded number: '151.2' is not in the week's dossier"]
    )


def test_a_packet_figure_the_draft_never_printed_is_a_new_claim_outside_a_baseline_comparison(gates):
    """Found by the dry run: the editor wrote "23 straight days of training" from a 23 the packet held in another
    meaning. A packet-only figure is admitted only inside the 'nothing changes' comparison the editor is asked for."""
    packet = json.dumps({**DOSSIER, "training": {"sessions_this_season": 23}})
    claim = REVISION_OK.replace("Protein is the part he controls.", "It came after 23 straight days of training.")
    assert any("'23'" in x for x in story_editor.new_claims(claim, DRAFT, packet, gates.allowed))
    baseline = REVISION_OK.replace(
        "Friday's recovery was 73 and the scale read 293.6.",
        "Friday's recovery was 73 and the scale read 293.6. Thursday had shown 293.9, so a guess that nothing changes would also have landed.",
    )
    assert story_editor.new_claims(baseline, DRAFT, packet, gates.allowed) == []


def test_the_editors_own_remarks_reach_the_owner_labelled_unverified(gates):
    rec = _revise(gates, _Editor(_reply(REVISION_OK, notes=("I fixed the protein mean",)), _reply(REVISION_OK, notes=("I fixed it",))))
    assert any(a.startswith(story_editor.UNVERIFIED_PREFIX) for a in rec["advisory"])
    assert not any(a == "I fixed it" for a in rec["advisory"])
