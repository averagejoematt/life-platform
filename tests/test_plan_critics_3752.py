"""tests/test_plan_critics_3752.py — four critics, disjoint evidence, bounded by the numbers.

WHY THESE EXIST

The owner's bar (#3752) is a red team, not a persona list: critics that hold DIFFERENT data
and must name a NUMBER. What these tests hold `coach.critics` to:

  1. DISJOINT — the four packets share no metric name. Two critics reading the same number
     agree by construction; the disagreement the owner asked for needs different numbers.
  2. NEGATIVE CONTROL (#3851) — a clean draft draws no objection even from a model that
     vetoes everything. A critic that always objects is a critic nobody reads.
  3. POSITIVE CONTROL — a draft violating a redline in the owner's calibration doc draws the
     veto, from the numbers, whatever the model says (ADR-105: computation before verdict).
  4. BOUNDED ESCALATION — the model may add an objection only on a metric its packet flags,
     one step at most; a veto needs a redline.
  5. HONEST PAUSE — a paused model is reported as paused on the verdict, never as approval.
  6. EVERY OBJECTION NAMES ITS NUMBER — change/veto carry the metric, the value and the
     provenance; the notes block renders them for the gym.

Mutation controls named per test; run with `python3 -B` after purging __pycache__ (an
md5 on the source is not proof the mutation ran — see the 09-19 finding).
"""

from __future__ import annotations

import itertools
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from coach import critics as c  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

KG = 1 / c._LBS_PER_KG


def _ir(*, squat_lbs=176.0, second="Leg Extension (Machine)", second_lbs=88.0, failure=False, notes=""):
    return RoutineSpec(
        routine_id="r-3752",
        target_date="2026-09-20",
        archetype="legs",
        exercises=[
            ExerciseBlock(
                movement_key="tmpl:1",
                rationale_tag="Squat (Barbell)",
                notes=notes,
                sets=[
                    Set(weight_kg=60 * KG, reps=8, type="warmup"),
                    Set(weight_kg=squat_lbs * KG, reps=5, type="failure" if failure else "normal"),
                ],
            ),
            ExerciseBlock(movement_key="tmpl:2", rationale_tag=second, sets=[Set(weight_kg=second_lbs * KG, reps=12) for _ in range(3)]),
        ],
    )


def _packets(
    d,
    *,
    pain=None,
    days_since=None,
    trends=None,
    protein=0,
    tripwires=None,
    reference=None,
    consecutive=1,
    active=1,
    layer="ok",
    lifts_7d=2,
    walking=None,
    weeks_in_block=0,
    program_week=7,  # #4098: past `not_before_week`, so the anchor-drop tripwire is armed
):
    return {
        "muscle_defense": c.build_muscle_defense_packet(
            d,
            anchor_trends=(
                trends
                if trends is not None
                else {0: {"drop_pct": 0.0, "sessions_below": 0, "baseline_median_e1rm_lb": 210.0, "last_top_lbs": 180.0, "n_sessions": 5}}
            ),
            protein_days_missed_7d=protein,
            protein_days_measured_7d=7,
            program_week=program_week,
        ),
        "joints_tendons": c.build_joints_packet(
            d,
            pain_by_idx=pain if pain is not None else {0: {"pain_flag_any": False}, 1: {"pain_flag_any": False}},
            days_since_by_idx=days_since if days_since is not None else {0: 3, 1: 5},
            active_day_streak=active,
            loaded_lifting_streak=consecutive,
            pain_layer_status=layer,
        ),
        "rate_advocate": c.build_rate_advocate_packet(
            d,
            tripwires=tripwires if tripwires is not None else [{"id": "a", "state": "clear"}, {"id": "b", "state": "unknown"}],
            walking=walking,
            rate_target={"low_lb_wk": 1.6, "high_lb_wk": 3.2, "provenance": "owner"},
            current_rate_lb_wk=2.0,
            lifting_sessions_7d=lifts_7d,
        ),
        "blueprint_historian": c.build_historian_packet(
            d,
            weeks_in_block=weeks_in_block,
            reference=(
                reference
                if reference is not None
                else {
                    "proven_target": {
                        "band": "310-319",
                        "band_distance_lb": 0,
                        "sets_wk": 40,
                        "volume_citable": True,
                        "top_kg_by_movement": {"Squat (Barbell)": 90},
                    }
                }
            ),
        ),
    }


def _model(verdict, metric, field=None, to=None, sentence="Objection. And a second sentence that must be cut."):
    def invoke(body):
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"verdict": verdict, "metric": metric, "value": 1, "field": field, "to": to, "sentence": sentence}),
                }
            ],
            "stop_reason": "end_turn",
        }

    return invoke


# ── 1. disjoint ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("variant", ["clean", "flagged"])
def test_the_four_packets_are_pairwise_disjoint(variant):
    """Mutation control: give the historian a `protein_days_missed_7d` key → this reds."""
    d = c.draft_summary(_ir())
    P = _packets(d) if variant == "clean" else _packets(d, protein=4, pain={0: {"pain_flag_any": True, "pain_dates": ["2026-09-12"]}})
    keys = {cid: set(p["numbers"]) for cid, p in P.items()}
    for a, b in itertools.combinations(keys, 2):
        assert not (keys[a] & keys[b]), f"{a} and {b} share {keys[a] & keys[b]}"
    assert set(P) == set(c.CRITIC_IDS)


# ── 2. negative control ───────────────────────────────────────────────────────
def test_negative_control_a_clean_draft_draws_no_objection_from_an_always_vetoing_model():
    """THE #3851 guard. Every packet clean → an always-veto model produces four approvals,
    each recording that its objection was discarded. Mutation control: in `reconcile`,
    drop the `metric not in flagged` check → the model's veto is honoured and this reds."""
    d = c.draft_summary(_ir())
    P = _packets(d)
    assert all(not p["flags"] and not p["violations"] for p in P.values()), {k: p["flags"] for k, p in P.items()}
    vs = c.run_critics(P, d, invoke=_model("veto", "protein_days_missed_7d"), model_allowed=True)
    assert [v["verdict"] for v in vs] == ["approve"] * 4
    assert all(v["discarded"] and "#3851" in v["discarded"] for v in vs), [v["discarded"] for v in vs]
    assert c.apply_changes(_ir(), vs) == []


def test_a_model_change_on_an_unflagged_metric_is_discarded():
    d = c.draft_summary(_ir())
    P = _packets(d)
    vs = c.run_critics(P, d, invoke=_model("change", "band", field="exercises[0].weight_lbs", to=100), model_allowed=True)
    assert all(v["verdict"] == "approve" for v in vs)
    assert all(v["discarded"] for v in vs)


# ── 3. positive controls — the owner's calibration-doc redlines ──────────────
def test_positive_control_a_pain_flag_on_a_drafted_movement_draws_the_joints_veto():
    """Mutation control: make `build_joints_packet` append the pain finding to `flags` at
    severity "change" instead of `violations` → verdict becomes change and this reds."""
    d = c.draft_summary(_ir())
    P = _packets(d, pain={0: {"pain_flag_any": True, "pain_dates": ["2026-09-12"]}, 1: {"pain_flag_any": False}})
    for invoke in (None, _model("approve", "loaded_lifting_streak")):
        vs = c.run_critics(P, d, invoke=invoke, model_allowed=invoke is not None, model_paused_reason="tier 3")
        j = next(v for v in vs if v["critic"] == "joints_tendons")
        assert j["verdict"] == "veto", j
        assert j["redline"] == "pain_flag_loaded"
        assert j["metric"] == "pain_flag[0]" and j["value"] is True
        assert "Squat (Barbell)" in j["reason"]
        assert j["field"] == "exercises[0].drop"
        assert [v["verdict"] for v in vs if v["critic"] != "joints_tendons"] == ["approve"] * 3


def test_positive_control_to_failure_on_a_novel_again_pattern_vetoes():
    d = c.draft_summary(_ir(failure=True))
    P = _packets(d, days_since={0: 45, 1: 5})
    j = next(v for v in c.run_critics(P, d, invoke=None, model_allowed=False) if v["critic"] == "joints_tendons")
    assert j["verdict"] == "veto" and j["redline"] == "failure_on_novel_session_1"
    # the same set on a WARM pattern is not a violation
    P2 = _packets(d, days_since={0: 3, 1: 5})
    assert (
        next(v for v in c.run_critics(P2, d, invoke=None, model_allowed=False) if v["critic"] == "joints_tendons")["verdict"] == "approve"
    )


def test_positive_control_two_heavy_axial_patterns_cold_vetoes_and_one_warm_does_not():
    ir = _ir(second="Deadlift (Barbell)", second_lbs=225.0)
    d = c.draft_summary(ir)
    assert [e["axial"] for e in d["exercises"]] == ["squat", "hinge"]
    P = _packets(d, days_since={0: 20, 1: None})
    j = next(v for v in c.run_critics(P, d, invoke=None, model_allowed=False) if v["critic"] == "joints_tendons")
    assert j["verdict"] == "veto" and j["redline"] == "two_heavy_axial_cold"
    assert j["metric"] == "heavy_axial_patterns_cold" and j["value"] == 2
    warm = _packets(d, days_since={0: 3, 1: None})
    assert (
        next(v for v in c.run_critics(warm, d, invoke=None, model_allowed=False) if v["critic"] == "joints_tendons")["verdict"] == "approve"
    )


def test_a_dark_note_layer_makes_pain_unknown_never_clear():
    d = c.draft_summary(_ir())
    P = _packets(d, pain={0: {"pain_flag_any": None}, 1: {"pain_flag_any": None}}, layer="dark")
    j = P["joints_tendons"]
    assert "pain_flag[0]" in j["unknown"] and j["numbers"]["pain_flag[0]"] is None
    assert not j["violations"]
    assert any(f["metric"] == "pain_layer_status" for f in j["flags"])


# ── 4. owner redlines (unsigned) produce change, not veto ─────────────────────
def test_a_tripped_owner_tripwire_is_a_change_not_a_veto_while_3753_is_unsigned():
    d = c.draft_summary(_ir())
    P = _packets(
        d,
        protein=3,
        trends={
            0: {
                "drop_pct": 12.0,
                "sessions_below": 2,
                "baseline_median_e1rm_lb": 233.3,
                "last_top_lbs": 170.0,
                "n_sessions": 6,
                # #4112: idx 0 is Squat (Barbell) in `_ir` — a core anchor, so it can escalate.
                "anchor_family": "squat",
            }
        },
    )
    m = next(v for v in c.run_critics(P, d, invoke=None, model_allowed=False) if v["critic"] == "muscle_defense")
    assert m["verdict"] == "change"
    assert m["metric"] == "protein_days_missed_7d" and m["value"] == 3 and m["provenance"] == "owner"
    # the population-derived anchor-drop threshold says so where it fires (ADR-105)
    drop = next(f for f in P["muscle_defense"]["flags"] if f["metric"] == "anchor_drop_pct[0]")
    assert drop["provenance"] == "population-derived" and "not his variance" in drop["reason"]
    assert drop["field"] == "exercises[0].weight_lbs" and drop["to"] == 170.0


# ── #4112: the tier gate — an accessory drop never escalates the critic's own verdict ─
def test_an_accessory_drop_never_reaches_the_muscle_defense_verdict_4112():
    """The SAME trip-eligible numbers as the test above, minus `anchor_family` (idx 0 read as
    an accessory, not the drafted squat's core-anchor identity) — the drop stays `info` and
    cannot promote the critic's verdict past whatever the clean run would already be.

    MUTATION CONTROL: this is the positive-control test above with one key removed; if the
    tier gate in `critics_muscle_defense.build_muscle_defense_packet` is dropped, this reds
    (`anchor_drop_pct[0]` would read `change` and `m["verdict"]` would carry the anchor
    metric instead of staying on the clean-draft's `approve`).
    """
    d = c.draft_summary(_ir())
    P = _packets(
        d,
        trends={
            0: {
                "drop_pct": 12.0,
                "sessions_below": 2,
                "baseline_median_e1rm_lb": 233.3,
                "last_top_lbs": 170.0,
                "n_sessions": 6,
            }
        },
    )
    drop = next(f for f in P["muscle_defense"]["flags"] if f["metric"] == "anchor_drop_pct[0]")
    assert drop["severity"] == "info" and "accessory" in drop["reason"]
    m = next(v for v in c.run_critics(P, d, invoke=None, model_allowed=False) if v["critic"] == "muscle_defense")
    assert m["verdict"] == "approve"


def test_the_historian_argues_a_load_down_with_the_detraining_discount_never_up():
    d = c.draft_summary(_ir(squat_lbs=200.0))
    P = _packets(
        d,
        reference={
            "proven_target": {
                "band": "310-319",
                "band_distance_lb": 9,
                "volume_citable": False,
                "n_effective": 4.0,
                "top_kg_by_movement": {"Squat (Barbell)": 90},
                "attested": {"minutes_typical": 45},
            }
        },
    )
    h = next(v for v in c.run_critics(P, d, invoke=None, model_allowed=False) if v["critic"] == "blueprint_historian")
    assert h["verdict"] == "change" and h["field"] == "exercises[0].weight_lbs"
    assert h["to"] == pytest.approx(90 * c._LBS_PER_KG * 0.9, abs=0.1)
    nums = P["blueprint_historian"]["numbers"]
    assert nums["attested_basis"] == "OWNER-ATTESTED, NOT MEASURED"
    assert (
        nums["attested_cardio_hr_wk"] is None
    ), "the live overlay key is cardio_hr_wk_attested; a per-session minutes key was never emitted"
    assert any("descriptive only" in f["reason"] for f in P["blueprint_historian"]["flags"])
    assert any("not a mirror" in f["reason"] for f in P["blueprint_historian"]["flags"])
    # under the ceiling: no change
    low = _packets(
        c.draft_summary(_ir(squat_lbs=150.0)),
        reference={"proven_target": {"band": "310-319", "top_kg_by_movement": {"Squat (Barbell)": 90}}},
    )
    assert c.deterministic_verdict(low["blueprint_historian"])["verdict"] == "approve"


# ── 5. bounded escalation ─────────────────────────────────────────────────────
def test_the_model_may_escalate_one_step_on_a_flagged_metric_and_a_veto_needs_a_redline():
    d = c.draft_summary(_ir())
    P = _packets(d, protein=1)  # info flag on protein_days_missed_7d, nothing else
    vs = c.run_critics(P, d, invoke=_model("veto", "protein_days_missed_7d"), model_allowed=True)
    m = next(v for v in vs if v["critic"] == "muscle_defense")
    assert m["verdict"] == "change", m
    assert "downgraded to change" in m["discarded"]
    assert m["metric"] == "protein_days_missed_7d" and m["value"] == 1
    assert m["sentence"] == "Objection." and m["reason"] == "Objection."
    assert all(v["verdict"] == "approve" for v in vs if v["critic"] != "muscle_defense")


def test_the_advocate_argues_but_never_adds_sets_and_never_vetoes():
    """#4161 RULING: the advocate's "+1 set" is dropped (Roth 2023). All-clear is still SAID (a
    governed info flag); a model veto on it is discarded, and nothing is applied."""
    d = c.draft_summary(_ir())
    P = _packets(d, tripwires=[{"id": "a", "state": "clear"}, {"id": "b", "state": "clear"}])
    assert any(f["metric"] == "tripwires_clear" for f in P["rate_advocate"]["flags"])
    vs = c.run_critics(P, d, invoke=_model("veto", "tripwires_clear", field="session.total_sets", to=8), model_allowed=True)
    a = next(v for v in vs if v["critic"] == "rate_advocate")
    assert a["verdict"] == "approve" and "governs" in a["discarded"]
    ir = _ir()
    assert all(r["applied"] is False for r in c.apply_changes(ir, vs))
    assert sum(len(e.sets) for e in ir.exercises) == 5


def test_an_addition_from_any_critic_is_refused():
    ir = _ir()  # 5 sets
    rec = c.apply_changes(ir, [{"critic": "rate_advocate", "verdict": "change", "field": "session.total_sets", "to": 40}])
    assert rec[0]["applied"] is False and "no critic adds sets" in rec[0]["why"]
    assert sum(len(e.sets) for e in ir.exercises) == 5 + c.MAX_ADDED_SETS == 5


# ── 6. the model layer: parse, pause, failure ────────────────────────────────
def test_a_paused_model_is_reported_as_paused_on_every_verdict_never_as_approval():
    d = c.draft_summary(_ir())
    vs = c.run_critics(_packets(d), d, invoke=_model("veto", "band"), model_allowed=False, model_paused_reason="budget tier 2")
    assert all(v["model"] == {"paused": "budget tier 2"} for v in vs)
    assert all(v["verdict"] == "approve" and v["discarded"] is None for v in vs)


def test_a_model_failure_is_recorded_on_the_verdict_not_raised():
    d = c.draft_summary(_ir())

    def boom(body):
        raise RuntimeError("ThrottlingException")

    vs = c.run_critics(_packets(d), d, invoke=boom, model_allowed=True)
    assert all(v["model"]["error"].startswith("RuntimeError") for v in vs)
    assert all(v["verdict"] == "approve" for v in vs)


@pytest.mark.parametrize(
    "resp, err",
    [
        ({"content": [{"type": "text", "text": "x"}], "stop_reason": "max_tokens"}, "truncated"),
        ({"content": [{"type": "text", "text": "no json here"}], "stop_reason": "end_turn"}, "no JSON object"),
        ({"content": [{"type": "text", "text": '{"verdict": "maybe"}'}], "stop_reason": "end_turn"}, "verdict not in"),
        ({"content": [{"type": "text", "text": "{not json}"}], "stop_reason": "end_turn"}, "json.loads failed"),
    ],
)
def test_parse_model_verdict_names_each_failure_and_never_fabricates(resp, err):
    out = c.parse_model_verdict(resp)
    assert err in out["error"]


def test_each_critic_is_a_separate_call_over_only_its_own_packet():
    """The prompt a critic sees carries ITS numbers and no other critic's."""
    d = c.draft_summary(_ir())
    P = _packets(d)
    seen = []

    def capture(body):
        seen.append(body)
        return {"content": [{"type": "text", "text": '{"verdict":"approve","metric":null,"sentence":"Fine."}'}], "stop_reason": "end_turn"}

    c.run_critics(P, d, invoke=capture, model_allowed=True)
    assert len(seen) == 4
    for body, cid in zip(seen, c.CRITIC_IDS):
        assert cid in body["system"]
        sent = json.loads(body["messages"][0]["content"].split("\nReturn the JSON object.")[0])
        assert set(sent["packet"]["numbers"]) == set(P[cid]["numbers"])
        for other in c.CRITIC_IDS:
            if other != cid:
                assert not (set(sent["packet"]["numbers"]) & set(P[other]["numbers"]))
        assert body["max_tokens"] == c.MAX_TOKENS and body["model"] == c.HAIKU_MODEL


# ── 7. apply + recheck ────────────────────────────────────────────────────────
def test_apply_changes_moves_weight_reps_set_count_and_drop_and_names_the_unappliable():
    ir = _ir()
    rec = c.apply_changes(
        ir,
        [
            {"critic": "blueprint_historian", "verdict": "change", "field": "exercises[0].weight_lbs", "to": 150.0},
            {"critic": "muscle_defense", "verdict": "change", "field": "exercises[1].set_count", "to": 2},
            {"critic": "x", "verdict": "change", "field": "exercises[1].reps", "to": 10},
            {"critic": "y", "verdict": "change", "field": "exercises[9].reps", "to": 10},
            {"critic": "z", "verdict": "change", "field": "session.rest_seconds", "to": 90},
            {"critic": "w", "verdict": "change", "field": None},
            {"critic": "v", "verdict": "approve"},
        ],
    )
    assert ir.exercises[0].sets[0].weight_kg == pytest.approx(60 * KG)  # warmup untouched
    assert ir.exercises[0].sets[1].weight_kg == pytest.approx(150 * KG, abs=0.01)
    assert len(ir.exercises[1].sets) == 2 and all(s.reps == 10 for s in ir.exercises[1].sets)
    assert [r["applied"] for r in rec] == [True, True, True, False, False, False]
    assert rec[3]["why"] == "exercises[9] does not exist"
    assert rec[4]["why"] == "field outside the change grammar"
    assert "coach must act" in rec[5]["why"]
    ir2 = _ir()
    assert c.apply_changes(ir2, [{"critic": "j", "verdict": "change", "field": "exercises[0].drop", "to": True}])[0]["applied"]
    assert [e.movement_key for e in ir2.exercises] == ["tmpl:2"]


def test_recheck_passes_once_the_vetoed_movement_is_dropped_and_fails_while_it_stands():
    ir = _ir()
    evidence_pain = {0: {"pain_flag_any": True, "pain_dates": ["2026-09-12"]}, 1: {"pain_flag_any": False}}

    def build(d):
        # the pain evidence is keyed by ORIGINAL idx; after a drop the survivor is idx 0
        keyed = {i: evidence_pain.get(1 if len(d["exercises"]) == 1 else i, {"pain_flag_any": False}) for i in range(len(d["exercises"]))}
        return _packets(d, pain=keyed)

    before = c.recheck(ir, build)
    assert before["passed"] is False and before["remaining_vetoes"][0]["critic"] == "joints_tendons"
    c.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].drop", "to": True}])
    after = c.recheck(ir, build)
    assert after["passed"] is True and after["exercise_count"] == 1


# ── 8. what rides on the routine ──────────────────────────────────────────────
def _with_verdicts(ir, vs, changes=()):
    ir.inputs_snapshot["critics"] = {
        "engine": c.CRITICS_VERSION,
        "ran_at": "2026-09-19T23:00:00+00:00",
        "verdicts": vs,
        "changes": list(changes),
    }
    return ir


def test_veto_reason_reads_only_the_stored_verdicts():
    ir = _ir()
    assert c.veto_reason(ir) is None
    d = c.draft_summary(ir)
    vs = c.run_critics(
        _packets(d, pain={0: {"pain_flag_any": True, "pain_dates": ["2026-09-12"]}, 1: {"pain_flag_any": False}}),
        d,
        invoke=None,
        model_allowed=False,
    )
    _with_verdicts(ir, vs)
    reason = c.veto_reason(ir)
    assert reason.startswith("joints_tendons:") and "pain flag" in reason


def test_the_notes_block_carries_every_verdict_its_metric_its_number_and_its_provenance():
    ir = _ir(squat_lbs=200.0)
    d = c.draft_summary(ir)
    P = _packets(
        d,
        protein=3,
        reference={
            "proven_target": {
                "band": "310-319",
                "band_distance_lb": 0,
                "volume_citable": True,
                "top_kg_by_movement": {"Squat (Barbell)": 90},
                "attested": {"minutes_typical": 45},
            }
        },
    )
    vs = c.run_critics(P, d, invoke=None, model_allowed=False, model_paused_reason="tier 2")
    _with_verdicts(ir, vs, changes=[{"critic": "blueprint_historian", "field": "exercises[0].weight_lbs", "to": 178.6, "applied": True}])
    block = c.notes_block(ir)
    # the engine version is read from the module, never re-typed here (#4036: a bump used to red five tests)
    assert block.startswith(f"RED TEAM ({c.CRITICS_VERSION}, 4 critics, 2026-09-19):")
    assert "- muscle-defense CHANGE (model paused): protein_days_missed_7d=3 [owner]" in block
    assert "- historian CHANGE (model paused): band_top_lbs[0]=198.4 [owner]" in block
    assert "- joints/tendons APPROVE" in block and "- rate-advocate APPROVE" in block
    assert block.endswith("applied: exercises[0].weight_lbs -> 178.6")
    assert c.with_notes_block("Custom session.", ir) == "Custom session.\n\n" + block
    assert c.with_notes_block("", ir) == block
    assert c.with_notes_block("why", _ir()) == "why"


def test_the_thread_entry_is_shaped_like_a_thread_row_and_keyed_beside_the_analyzers():
    ir = _ir()
    d = c.draft_summary(ir)
    vs = c.run_critics(
        _packets(d, pain={0: {"pain_flag_any": True, "pain_dates": ["2026-09-12"]}, 1: {"pain_flag_any": False}}),
        d,
        invoke=None,
        model_allowed=False,
    )
    _with_verdicts(ir, vs)
    row = c.thread_entry(ir, today="2026-09-19")
    assert row["pk"] == "USER#matthew" and row["sk"] == "SOURCE#coach_thread#training#2026-09-19#critics"
    assert row["coach_id"] == "training" and row["generation_context"] == "plan_critics"
    for k in ("position_summary", "predictions", "surprises", "stance_changes", "emotional_investment", "open_questions", "learning_log"):
        assert k in row
    assert "joints/tendons veto on pain_flag[0]=True" in row["position_summary"]
    assert len(row["learning_log"]) == 4 and row["learning_log"][1]["provenance"] == "owner"
    json.dumps(row)  # serialisable


def test_every_change_or_veto_names_the_metric_and_the_value_it_relied_on():
    d = c.draft_summary(_ir(squat_lbs=200.0, failure=True))
    P = _packets(d, protein=3, days_since={0: 60, 1: 2}, tripwires=[{"id": "a", "state": "clear"}])
    for v in c.run_critics(P, d, invoke=_model("veto", "tripwires_clear"), model_allowed=True):
        if v["verdict"] != "approve":
            assert v["metric"] in P[v["critic"]]["numbers"], v
            assert v["value"] == P[v["critic"]]["numbers"][v["metric"]]
            assert v["provenance"]


# ── 9. the historian's second axis — found live on 2026-09-19 ────────────────
def test_the_historian_defers_to_a_current_baseline_when_he_is_in_a_block():
    """The 2026-09-19 live finding: the band reference (2019-2024 window) held a 40 lb dumbbell
    row against an 80 lb row performed three days earlier. In a consistent block the band
    figure is DESCRIPTIVE — a cut to 36 lb would be an invented objection (#3851).
    Mutation control: drop the `cold` branch so the change fires regardless → this reds."""
    d = c.draft_summary(_ir(squat_lbs=200.0))
    ref = {
        "proven_target": {
            "band": "300-309",
            "band_distance_lb": 7,
            "window": "2019-12-30..2024-09-16",
            "top_kg_by_movement": {"Squat (Barbell)": 90},
        }
    }
    in_block = _packets(d, reference=ref, weeks_in_block=c.CONSISTENT_BLOCK_WEEKS)
    h = in_block["blueprint_historian"]
    assert h["numbers"]["weeks_in_current_block"] == 2
    top = next(f for f in h["flags"] if f["metric"] == "band_top_lbs[0]")
    assert top["severity"] == "info" and "descriptive" in top["reason"] and top["field"] is None
    assert c.deterministic_verdict(h)["verdict"] == "approve"
    # unknown block length is NOT cold: descriptive only, and named as unreadable
    unk = _packets(d, reference=ref, weeks_in_block=None)["blueprint_historian"]
    assert "weeks_in_current_block" in unk["unknown"] and c.deterministic_verdict(unk)["verdict"] == "approve"
    # cold: the discount applies and the change is down only
    cold = _packets(d, reference=ref, weeks_in_block=1)["blueprint_historian"]
    v = c.deterministic_verdict(cold)
    assert v["verdict"] == "change" and v["to"] == pytest.approx(90 * c._LBS_PER_KG * 0.9, abs=0.1) and "cold" in v["reason"]


def test_the_advocate_says_so_when_the_rate_is_already_above_the_band():
    d = c.draft_summary(_ir())
    P = c.build_rate_advocate_packet(
        d, tripwires=[], walking=None, rate_target={"low_lb_wk": 1.6, "high_lb_wk": 3.2}, current_rate_lb_wk=3.7, lifting_sessions_7d=2
    )
    f = next(f for f in P["flags"] if f["metric"] == "current_rate_lb_wk")
    assert f["severity"] == "info" and "ABOVE" in f["reason"]


# ── the trim shape — found live on 2026-09-20 ────────────────────────────────
def test_a_set_cut_is_spread_round_robin_from_the_largest_exercise_never_hollowing_the_tail():
    """Routine 73bc228c v2: 22 -> 18 came entirely out of the last two accessories (3 -> 1 each).
    Mutation control: restore the reversed()-pop loop → this reds on the [3, 3, 3, 3, 2, 2] shape."""
    ir = RoutineSpec(
        routine_id="r",
        target_date="2026-09-20",
        archetype="pull",
        exercises=[
            ExerciseBlock(movement_key=k, sets=[Set(weight_kg=40, reps=10) for _ in range(n)])
            for k, n in (("lat_pulldown", 4), ("close_grip", 3), ("db_row", 4), ("straight_arm", 3), ("face_pull", 3), ("hammer_curl", 3))
        ]
        + [
            ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=2700)]),
            ExerciseBlock(movement_key="stretching", sets=[Set(duration_seconds=900)]),
        ],
    )
    rec = c.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "session.total_sets", "to": 18}])
    assert rec[0]["applied"] is True
    assert [len(e.sets) for e in ir.exercises] == [3, 3, 3, 3, 2, 2, 1, 1]
    # never below one set, and it says so when it cannot reach the target
    rec2 = c.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "session.total_sets", "to": 3}])
    assert rec2[0]["applied"] is False and "could only trim to 8" in rec2[0]["why"]


def test_the_historian_reads_the_live_attested_overlay_in_hours_per_week():
    d = c.draft_summary(_ir())
    live_attested = {
        "kind": "cycle",
        "cardio_hr_wk_attested": 0.28,
        "cardio_hr_wk_attested_low": 0.19,
        "cardio_hr_wk_attested_high": 0.38,
        "attestation_id": "post_lift_low_cardio",
        "basis": "OWNER-ATTESTED, NOT MEASURED",
    }
    P = c.build_historian_packet(d, reference={"proven_target": {"band": "300-309", "attested": live_attested}}, weeks_in_block=2)
    assert P["numbers"]["attested_cardio_hr_wk"] == 0.28
    f = next(f for f in P["flags"] if f["metric"] == "attested_cardio_hr_wk")
    assert "0.28 hr/wk" in f["reason"] and "NOT MEASURED" in f["reason"] and f["provenance"] == "owner-attested"
