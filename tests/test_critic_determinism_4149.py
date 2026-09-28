"""tests/test_critic_determinism_4149.py — one input, one red-team answer; no critic change is uncommittable.

WHY THESE EXIST (#4149, epic #3742)

On 2026-09-23 three stage-2 runs read the SAME signal — squat_barbell `days_since_movement`
98/99 — and the joints/tendons critic answered three ways: sets 3 -> 2 (routine f097b359),
load -25 % to 36 kg (1b09ec51, then REFUSED by the commit gate against its 48 kg floor), load
-13 % to 135 lb (b1b99604). The model chose the number. Separately, the prescription audit
read the note "don't add weight" as a conditional up-branch.

What these tests hold:

  1. THE REPLAY — the three stored runs (tests/fixtures/critic_determinism_4149, read-only from
     DynamoDB) replayed through the critics, each input crossed with ALL THREE stored model
     outputs, give ONE answer per input: the days-since rule computed in code (working sets
     capped at NOVEL_AGAIN_MAX_WORKING_SETS, load untouched). No run moves the squat's load.
  2. EVERY NUMERIC CHANGE IS CODE'S — a grounded model escalation applies the flag's own
     field/to, never the model's; the prompt is pinned at temperature 0.
  3. THE FLOOR CLAMP — a critic load change below the subtract-only floor (the commit gate's
     own floors, per set, back-off seam included) is clamped with the conflict named, or
     surfaced unapplied; the result passes `audit_prescription`.
  4. NEGATION — `find_conditional_up` does not read a prohibition as progression, and still
     reads every real conditional-up phrasing.

Mutation controls are named per test.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics as c  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import recovery_authoring as ra  # noqa: E402

FIXTURE = json.loads((REPO / "tests/fixtures/critic_determinism_4149/runs_2026_09_23.json").read_text())
RUNS = FIXTURE["runs"]
SQUAT_FLOOR = FIXTURE["gate_floor_kg_2026_09_24"]["squat_barbell"]
BACK_OFF_SCHEME = {"status": "ok", "back_offs": 2}


# ── builders over the stored rows ─────────────────────────────────────────────────────
def _ir_of(run: dict) -> RoutineSpec:
    return RoutineSpec(
        routine_id=run["routine_id"],
        target_date=run["target_date"],
        archetype="full_body",
        exercises=[
            ExerciseBlock(
                movement_key=e["movement_key"],
                rationale_tag=e["rationale_tag"],
                sets=[Set(weight_kg=s["weight_kg"], reps=s["reps"], type=s["type"] or "normal") for s in e["sets"]],
            )
            for e in run["draft_exercises"]
        ],
    )


def _idx_numbers(nums: dict, prefix: str) -> dict[int, object]:
    return {int(k[len(prefix) + 1 : -1]): v for k, v in nums.items() if k.startswith(prefix + "[")}


def _joints_packet(run: dict, draft: dict) -> dict:
    """The joints packet rebuilt from the run's stored inputs (`packet_numbers.joints_tendons`).

    b1b99604's pain flag on idx 1 carried an owner dismissal (#4036, `pain_dismissed[1]`); a
    dismissed instance adds neither a flag nor a violation, so it is replayed as no flag — the
    packet's flags are identical either way."""
    n = run["joints_packet_numbers"]
    pain = {
        i: {"pain_flag_any": bool(v) and not n.get(f"pain_dismissed[{i}]"), "pain_dates": []}
        for i, v in _idx_numbers(n, "pain_flag").items()
    }
    return c.build_joints_packet(
        draft,
        pain_by_idx=pain,
        days_since_by_idx=_idx_numbers(n, "days_since_movement"),
        active_day_streak=n.get("active_day_streak"),
        loaded_lifting_streak=n.get("loaded_lifting_streak"),
        pain_layer_status=n.get("pain_layer_status"),
    )


def _replying(model_json: dict):
    def invoke(body):
        return {"content": [{"type": "text", "text": json.dumps(model_json)}], "stop_reason": "end_turn"}

    return invoke


def _joints_verdict(run: dict, model_json: dict | None) -> tuple[dict, RoutineSpec]:
    ir = _ir_of(run)
    draft = c.draft_summary(ir)
    packet = _joints_packet(run, draft)
    model = c.parse_model_verdict(_replying(model_json)({})) if model_json else None
    v = c.reconcile(c.deterministic_verdict(packet), model, packet)
    c.apply_changes(ir, [v])
    return v, ir


def _working(ex) -> list:
    return [s for s in ex.sets if (s.type or "normal") != "warmup"]


# ── 1. the replay ─────────────────────────────────────────────────────────────────────
def test_the_fixture_is_the_three_divergent_runs_the_issue_names():
    """Guard the fixture itself: three runs, one signal, three different stored changes."""
    assert [r["routine_id"][:8] for r in RUNS] == ["f097b359", "1b09ec51", "b1b99604"]
    assert [r["joints_packet_numbers"]["days_since_movement[0]"] for r in RUNS] == [98, 98, 99]
    assert all(r["draft_exercises"][0]["movement_key"] == "squat_barbell" for r in RUNS)
    stored = [(r["joints_stored_verdict"]["field"], r["joints_stored_verdict"]["to"]) for r in RUNS]
    assert stored == [("exercises[0].set_count", 2), ("exercises[0].weight_lbs", 79.35), ("exercises[0].weight_lbs", 135)]


def test_each_stored_input_gives_one_answer_whatever_the_model_said():
    """Every input crossed with all three stored model outputs (and no model at all) lands on
    the SAME verdict and the SAME squat. Mutation control: drop the `governed` check in
    `reconcile` -> the -25 % / -13 % model outputs escalate the info flag on 1b09ec51 into a
    change and its answers diverge; set the novel-again flag's `governed=False` -> same."""
    divergent = {}
    for run in RUNS:
        answers = set()
        for model_json in [None] + [r["joints_stored_model"] for r in RUNS]:
            v, ir = _joints_verdict(run, model_json)
            squat = _working(ir.exercises[0])
            answers.add((v["verdict"], v["metric"], v["field"], v["to"], len(squat), tuple(s.weight_kg for s in squat)))
        if len(answers) != 1:
            divergent[run["routine_id"][:8]] = answers
    assert not divergent, divergent


def test_the_one_answer_is_the_code_rule_volume_capped_load_untouched():
    """The ruling, on the replay: every run ends with the squat at <= NOVEL_AGAIN_MAX_WORKING_SETS
    working sets and every surviving set at the coach's drafted load — no critic cut the load."""
    cap = c.NOVEL_AGAIN_MAX_WORKING_SETS
    for run in RUNS:
        v, ir = _joints_verdict(run, run["joints_stored_model"])
        drafted = [s["weight_kg"] for s in run["draft_exercises"][0]["sets"]]
        after = [s.weight_kg for s in _working(ir.exercises[0])]
        assert len(after) <= cap, (run["routine_id"], after)
        assert after == drafted[: len(after)], "the days-since rule moved the load"
        assert v["field"] in (None, "exercises[0].set_count"), v
        if len(drafted) > cap:
            assert (v["verdict"], v["field"], v["to"]) == ("change", "exercises[0].set_count", cap), v
            assert "load stays the entry ramp's" in v["reason"]
        else:  # already at the cap: the rule is met, and the model's -25 % load cut is discarded by name
            assert v["verdict"] == "approve" and v["discarded"] and "#4149" in v["discarded"], v
    # 98 and 99 days are the same signal class: the two 3-set drafts get the identical verdict
    a = _joints_verdict(RUNS[0], RUNS[0]["joints_stored_model"])[0]
    b = _joints_verdict(RUNS[2], RUNS[2]["joints_stored_model"])[0]
    assert (a["verdict"], a["field"], a["to"]) == (b["verdict"], b["field"], b["to"])


def test_the_replayed_answer_commits_against_the_gate_floor_the_minus_25_run_failed():
    """1b09ec51's stored change put the squat at 36 kg; the gate refused it at 48. Replayed, the
    squat keeps 48/43 and `audit_prescription` passes. Mutation control: apply the stored
    `joints_stored_verdict` instead -> below_floor and this reds (asserted as the contrast)."""
    run = RUNS[1]
    floors = {"squat_barbell": SQUAT_FLOOR}
    _, ir = _joints_verdict(run, run["joints_stored_model"])
    assert ra.audit_prescription(ir.exercises[:1], floors=floors, scheme=BACK_OFF_SCHEME)["ok"] is True
    old = _ir_of(run)
    c.apply_changes(old, [{"critic": "joints_tendons", "verdict": "change", **run["joints_stored_verdict"]}])
    kinds = [x["kind"] for x in ra.audit_prescription(old.exercises[:1], floors=floors, scheme=BACK_OFF_SCHEME)["violations"]]
    assert kinds == ["below_floor", "below_floor"], "the specimen: 36 kg against 48 and 43"


# ── 2. every numeric change is code's ────────────────────────────────────────────────
def test_a_grounded_escalation_applies_the_flags_number_never_the_models():
    """The flag's number, never the model's. Since #4161 the advocate's flag is governed (it adds
    nothing), so this is held on the joints fatigue flag — a governed `change` the model cannot move.
    Mutation control: in `reconcile`, take `to` from the model again -> 8/40/2 not 14 and this reds."""
    from coach import critics_fatigue as cf

    d = {"total_sets": 20, "exercises": []}
    fat = cf.assess(readiness_low_streak_days=2, perf_by_idx={}, soreness_by_idx={}, same_region={"state": "clear"})
    p = c.build_joints_packet(
        d, pain_by_idx={}, days_since_by_idx={}, active_day_streak=5, loaded_lifting_streak=5, pain_layer_status="ok", fatigue=fat
    )
    for asked in (8, 40, 2):
        m = {"verdict": "veto", "metric": "fatigue_trigger", "value": True, "field": "session.total_sets", "to": asked, "sentence": "x"}
        v = c.reconcile(c.deterministic_verdict(p), m, p)
        assert (v["verdict"], v["field"], v["to"]) == ("change", "session.total_sets", 14)


def test_the_advocate_adds_nothing_whatever_the_model_asks():
    """#4161 RULING (owner-approved 2026-09-24, Roth 2023): the advocate's "+1 set" is DROPPED. Its
    all-clear flag is governed info — a model escalation on it is discarded — and `apply_changes`
    refuses any total above the draft. Mutation control: restore a field/to on the flag -> a change
    verdict appears and this reds."""
    ir = RoutineSpec(
        routine_id="r",
        target_date="2026-09-24",
        archetype="x",
        exercises=[ExerciseBlock(movement_key="tmpl:1", rationale_tag="Row", sets=[Set(weight_kg=40, reps=10) for _ in range(5)])],
    )
    d = c.draft_summary(ir)
    p = c.build_rate_advocate_packet(
        d, tripwires=[{"id": "a", "state": "clear"}], walking=None, rate_target=None, current_rate_lb_wk=None, lifting_sessions_7d=None
    )
    f = next(f for f in p["flags"] if f["metric"] == "tripwires_clear")
    assert f["severity"] == "info" and f["governed"] is True and f["field"] is None and f["to"] is None
    for asked in (8, 40, 6):
        m = {"verdict": "change", "metric": "tripwires_clear", "value": 1, "field": "session.total_sets", "to": asked, "sentence": "More."}
        v = c.reconcile(c.deterministic_verdict(p), m, p)
        assert v["verdict"] == "approve" and "governs" in (v["discarded"] or "")
    [rec] = c.apply_changes(ir, [{"critic": "rate_advocate", "verdict": "change", "field": "session.total_sets", "to": 6}])
    assert rec["applied"] is False and "no critic adds sets" in rec["why"] and c.MAX_ADDED_SETS == 0
    assert sum(len(e.sets) for e in ir.exercises) == 5 and c.ADVOCATE_RULING["adds_sets"] == 0


def test_a_long_loaded_streak_with_no_performance_drop_does_not_trigger():
    """#4161: the loaded-streak escalation is RETIRED. A 6-day lifting streak with readiness clear and
    no same-role performance drop flags nothing; the streak is context in `numbers`."""
    from coach import critics_fatigue as cf

    d = {"total_sets": 20, "exercises": []}
    fat = cf.assess(readiness_low_streak_days=0, perf_by_idx={0: {"state": "clear"}}, soreness_by_idx={}, same_region={"state": "clear"})
    p = c.build_joints_packet(
        d, pain_by_idx={}, days_since_by_idx={}, active_day_streak=6, loaded_lifting_streak=6, pain_layer_status="ok", fatigue=fat
    )
    assert p["numbers"]["loaded_lifting_streak"] == 6 and p["numbers"]["fatigue_trigger"] is False
    assert c.deterministic_verdict(p)["verdict"] == "approve" and not [f for f in p["flags"] if f["severity"] == "change"]


def test_every_critic_prompt_is_pinned_at_temperature_zero():
    """Mutation control: drop `"temperature": 0` from `_prompt` -> this reds."""
    ir = _ir_of(RUNS[0])
    d = c.draft_summary(ir)
    seen = []

    def capture(body):
        seen.append(body)
        return {"content": [{"type": "text", "text": '{"verdict":"approve","metric":null,"sentence":"ok"}'}], "stop_reason": "end_turn"}

    packets = {
        "muscle_defense": c.build_muscle_defense_packet(
            d, anchor_trends={}, protein_days_missed_7d=0, protein_days_measured_7d=7, program_week=1
        ),
        "joints_tendons": _joints_packet(RUNS[0], d),
        "rate_advocate": c.build_rate_advocate_packet(
            d, tripwires=[], walking=None, rate_target=None, current_rate_lb_wk=None, lifting_sessions_7d=None
        ),
        "blueprint_historian": c.build_historian_packet(d, reference=None),
    }
    c.run_critics(packets, d, invoke=capture, model_allowed=True)
    assert len(seen) == 4 and all(b.get("temperature") == 0 for b in seen)


# ── 3. the floor clamp ───────────────────────────────────────────────────────────────
def _squat_ir(top=48.0, back=43.0, n_back=2):
    return RoutineSpec(
        routine_id="r-clamp",
        target_date="2026-09-24",
        archetype="full_body",
        exercises=[
            ExerciseBlock(
                movement_key="squat_barbell",
                rationale_tag="custom",
                sets=[Set(weight_kg=top, reps=6)] + [Set(weight_kg=back, reps=8) for _ in range(n_back)],
            )
        ],
    )


def _gate_floors(ex):
    return ra.set_floors_kg(ex, SQUAT_FLOOR if ex.movement_key == "squat_barbell" else {}, BACK_OFF_SCHEME["back_offs"])


def test_a_load_change_the_floor_swallows_is_surfaced_as_a_conflict_not_applied():
    """The 1b09ec51 specimen through the clamp: 79.35 lb is 36 kg on every set, under 48 and 43.
    Mutation control: call `apply_changes` without `set_floors` -> applied, 36 kg, and this reds."""
    ir = _squat_ir()
    [rec] = c.apply_changes(
        ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].weight_lbs", "to": 79.35}], set_floors=_gate_floors
    )
    assert rec["applied"] is False and rec["why"].startswith("conflict:")
    assert "joints_tendons vs the subtract-only floor" in rec["conflict"] and "floor 48.0kg" in rec["conflict"]
    assert [s.weight_kg for s in ir.exercises[0].sets] == [48.0, 43.0, 43.0]
    assert ra.audit_prescription(ir.exercises, floors={"squat_barbell": SQUAT_FLOOR}, scheme=BACK_OFF_SCHEME)["ok"] is True


def test_a_partial_cut_is_clamped_to_each_sets_own_floor_and_named():
    """Top set drafted ABOVE the floor: a cut to 45 kg lands the top on its 48 floor and leaves
    the 43 back-offs where the back-off floor holds them — the same per-set split the gate uses."""
    ir = _squat_ir(top=52.0, back=46.0)
    [rec] = c.apply_changes(
        ir,
        [{"critic": "blueprint_historian", "verdict": "change", "field": "exercises[0].weight_lbs", "to": 45 * c._LBS_PER_KG}],
        set_floors=_gate_floors,
    )
    assert rec["applied"] is True and "set 1 45.0kg < floor 48.0kg" in rec["conflict"]
    assert [round(s.weight_kg, 2) for s in ir.exercises[0].sets] == [48.0, 45.0, 45.0]
    assert ra.audit_prescription(ir.exercises, floors={"squat_barbell": SQUAT_FLOOR}, scheme=BACK_OFF_SCHEME)["ok"] is True


def test_an_added_set_is_refused_so_no_back_off_window_can_be_overrun():
    """#4149 held an advocate-cloned 4th set to the TOP floor (#4065). Since #4161 no critic adds
    sets, so the case cannot arise: the addition is refused by name and the draft is unchanged."""
    ir = _squat_ir()
    before = [s.weight_kg for s in ir.exercises[0].sets]
    [rec] = c.apply_changes(
        ir, [{"critic": "rate_advocate", "verdict": "change", "field": "session.total_sets", "to": 4}], set_floors=_gate_floors
    )
    assert rec["applied"] is False and "no critic adds sets" in rec["why"]
    assert [s.weight_kg for s in ir.exercises[0].sets] == before
    assert ra.audit_prescription(ir.exercises, floors={"squat_barbell": SQUAT_FLOOR}, scheme=BACK_OFF_SCHEME)["ok"] is True


def test_the_clamp_and_the_gate_judge_with_one_predicate():
    """#4149 mirrored the gate's 0.05 kg tolerance into `critics_apply` and held the two NUMBERS
    equal. #4065 replaced both with ONE plate-grid predicate on the bundled side
    (`training.rep_scheme.is_below_floor`), so there is no second number left to keep equal."""
    from coach import critics_apply
    from training import rep_scheme

    assert critics_apply.is_below_floor is rep_scheme.is_below_floor
    assert ra.rep_scheme.is_below_floor is rep_scheme.is_below_floor
    assert not hasattr(c, "FLOOR_TOLERANCE_KG") and not hasattr(critics_apply, "FLOOR_TOLERANCE_KG")
    assert not hasattr(ra, "LOAD_TOLERANCE_KG")


def test_critic_set_floors_reads_the_commit_gates_own_floors():
    """`critic_set_floors` is the gate's floor (a stored generator audit is reused, no I/O), split
    per set by `set_floors_kg`; a no-load variant asserts none and so clamps nothing."""
    from mcp import hevy_prescription_gate as g

    ir = _squat_ir()
    ir.inputs_snapshot = {"load_floors": {"status": "applied", "movements": {"squat_barbell": SQUAT_FLOOR}}}
    floors_of = g.critic_set_floors(ir)
    n = ra._n_back_offs(None)[0]
    assert floors_of(ir.exercises[0]) == ra.set_floors_kg(ir.exercises[0], SQUAT_FLOOR, n)
    ir.variant = "floor"
    assert g.critic_set_floors(ir) is None


def test_stage_2_holds_a_critic_cut_at_the_gate_floor_and_the_commit_gate_is_clean():
    """End to end through `plan_next_session`: the historian's cold cut (90 kg band best less 10 %
    = 178.6 lb) lands under a 190 lb floor. Stage 2 clamps it, names the conflict, and the commit
    gate passes. Mutation control: revert the `set_floors=` argument in `_run_stage_2` -> the
    squat sits at 178.6 lb and `prescription_gate` refuses."""
    from test_tools_plan_critics_3752 import KG, _evidence, _ir, _run

    from mcp import hevy_prescription_gate as g

    ir = _ir(squat_lbs=200.0)
    floor = {"floor_kg": round(190.0 * KG, 2), "status": "applied"}
    ir.inputs_snapshot = {"load_floors": {"status": "applied", "movements": {"tmpl:1": floor}}}
    out, _, _ = _run(ir, _evidence(weeks_in_block=0))
    [rec] = [r for r in out["critics"]["changes"] if r["critic"] == "blueprint_historian"]
    assert rec["field"] == "exercises[0].weight_lbs" and "clamped to the floor (#4149)" in (rec.get("conflict") or "")
    assert ir.exercises[0].sets[0].weight_kg == pytest.approx(floor["floor_kg"])
    assert g.prescription_gate(ir)["verdict"] == "clean"
    assert "CONFLICT: blueprint_historian vs the subtract-only floor" in out["critics"]["notes_preview"]
    # #4387: the stored record carries the recent-aerobic rows the joints critic argued from (the live-proof read)
    assert set(out["critics"]["recent_aerobic"]) == {"window", "rows", "totals", "cardio_pick"}
    assert "weight_bearing_hr_48h" in out["critics"]["packet_numbers"]["joints_tendons"]


# ── 4. the conditional-up detector reads negation ────────────────────────────────────
PROHIBITIONS = [
    "If it feels heavy, don't add weight.",
    "If the bar slows, do not add weight.",
    "If in doubt, never add load.",
    "When it moves fast, still do NOT add load.",
    "If set 1 grinds, don’t go up.",
    "If RPE hits 9, no extra set.",
    "If it feels easy, dont add weight — hold 48.",
    "Once it is smooth, be careful not to add load this week.",
]
CONDITIONAL_UPS = [
    ("Ceiling RPE 9. If set 1 is <=7.5 go 80 - you had 80x8 on 09-11 leading with incline.", "go_to_number"),
    ("If it moves well, add weight.", "add_load"),
    ("If you're not sore add weight.", "add_load"),
    ("if not tired, add 5 lb", "add_load"),
    ("If it feels easy, don't stop — add 5 lb.", "add_load"),
    ("If the first set is clean, don't rest long and add weight.", "add_load"),
    ("If set 1 flies, never mind the plan: add another set.", "add_set"),
    ("65 only if set 1 was <=8 (GREEN)", "number_only_if"),
]


def test_a_prohibition_of_progression_is_not_a_conditional_up_finding():
    """Mutation control: make `_negated` return False -> every row here is an offender."""
    offenders = {t: ra.find_conditional_up(t) for t in PROHIBITIONS if ra.find_conditional_up(t)}
    assert not offenders, offenders


def test_a_real_conditional_up_is_still_a_finding():
    """Mutation control: make `_negated` return True -> every row but the self-contained
    `number_only_if` form is an offender (the detector would be blind)."""
    offenders = {}
    for text, pattern in CONDITIONAL_UPS:
        got = [h["pattern"] for h in ra.find_conditional_up(text)]
        if got != [pattern]:
            offenders[text] = got
    assert not offenders, offenders


def test_the_audit_no_longer_refuses_the_09_23_note():
    ex = [{"movement_key": "squat_barbell", "notes": "Week 1 ramp. If it feels heavy, don't add weight.", "sets": []}]
    assert ra.audit_prescription(ex, "", floors=None, scheme=BACK_OFF_SCHEME)["violations"] == []


# ── 5. the live proof, replayed (#4149 box 4) ────────────────────────────────────────
# The first stage-2 runs on a STALE-ANCHOR movement after the code rule shipped, read back from
# DynamoDB (`live_proof_runs`): af379af3 v6 at 2026-09-26T03:54:17Z (trap-bar deadlift, exposure 1
# after 323 days) and ff7518cd v3 at 2026-09-27T02:00:56Z (machine row, exposure 1, never in the
# window). Live, each got the cap 3 -> 2 working sets, load untouched, recheck.passed = true, no
# veto — a committable draft. Replayed here through the #4161 `stale_by_idx` path the 09-23 replay
# never exercises (it predates stale exposure), with every stored model output crossed in.
LIVE = FIXTURE["live_proof_runs"]["runs"]


def _stale_by_idx(n: dict) -> dict[int, dict]:
    """`critics_fatigue.stale_exposure` output rebuilt from the packet's stored numbers. The stored
    numbers carry exposure and gap_days, not gap_class; `stale_exposure` gives gap_days None to
    BOTH the long class (never / before the window) and the `none` class (current for the whole
    window), and the two are told apart here by `days_since_movement` — None means never."""
    from coach import critics_fatigue as cf

    out = {}
    for i, exposure in _idx_numbers(n, "stale_exposure").items():
        gap = n.get(f"stale_gap_days[{i}]")
        if gap is None:
            cls = "long" if n.get(f"days_since_movement[{i}]") is None else "none"
        else:
            cls = "long" if int(gap) >= cf.STALE_LONG_GAP_DAYS else "short"
        out[i] = {"exposure": int(exposure), "gap_days": gap, "gap_class": cls}
    return out


def _live_joints_packet(run: dict, draft: dict) -> dict:
    n = run["joints_packet_numbers"]
    return c.build_joints_packet(
        draft,
        pain_by_idx={i: {"pain_flag_any": bool(v), "pain_dates": []} for i, v in _idx_numbers(n, "pain_flag").items()},
        days_since_by_idx=_idx_numbers(n, "days_since_movement"),
        active_day_streak=n.get("active_day_streak"),
        loaded_lifting_streak=n.get("loaded_lifting_streak"),
        pain_layer_status=n.get("pain_layer_status"),
        stale_by_idx=_stale_by_idx(n),
    )


def _live_verdict(run: dict, model_json: dict | None) -> tuple[dict, RoutineSpec, list]:
    ir = _ir_of(run)
    packet = _live_joints_packet(run, c.draft_summary(ir))
    model = c.parse_model_verdict(_replying(model_json)({})) if model_json else None
    v = c.reconcile(c.deterministic_verdict(packet), model, packet)
    recs = c.apply_changes(ir, [v], set_floors=lambda ex: [])  # no load floor stored for these lifts: the clamp has nothing to hold
    return v, ir, recs


def test_the_live_proof_fixture_is_two_stale_anchor_runs_on_the_shipped_engine():
    """Guard the fixture: two runs after #4155 (critics@1.5.0), each with ONE exposure-1 long-gap
    anchor lift drafted at 3 working sets, each stored committable (recheck passed, no veto)."""
    assert [r["routine_id"][:8] for r in LIVE] == ["af379af3", "ff7518cd"]
    assert [r["ran_at"][:19] for r in LIVE] == ["2026-09-26T03:54:17", "2026-09-27T02:00:56"]
    assert all(r["engine"] == "critics@1.5.0" for r in LIVE)
    assert all(r["recheck"]["passed"] is True and r["veto"] is False for r in LIVE)
    for run, idx in zip(LIVE, (0, 1)):
        n = run["joints_packet_numbers"]
        assert n[f"stale_exposure[{idx}]"] == 1 and n[f"stale_gap_days[{idx}]"] in (323, None)
        assert run["draft_exercises"][idx]["rationale_tag"].startswith("anchor:")
        assert len(run["draft_exercises"][idx]["sets"]) == 3
        assert (run["joints_stored_verdict"]["field"], run["joints_stored_verdict"]["to"]) == (f"exercises[{idx}].set_count", 2)


def test_a_stale_anchor_run_gives_one_committable_answer_whatever_the_model_said():
    """The live-proof replay: each run crossed with no model, its own model, and the three 09-23
    models (one of which asked for the -25 % load cut) lands on ONE answer — the flagged anchor at
    the long-gap cap, every surviving set at the coach's load, no set of any other lift moved, and
    the same set total the live recheck recorded. Mutation control: `STALE_CAPS["long"][1] = 3` ->
    no cap flag, the draft keeps 3 working sets and this reds."""
    from coach import critics_fatigue as cf

    cap = cf.STALE_CAPS["long"][1]
    models = [None] + [r["joints_stored_model"] for r in LIVE] + [r["joints_stored_model"] for r in RUNS]
    for run, idx in zip(LIVE, (0, 1)):
        answers = set()
        for model_json in models:
            v, ir, recs = _live_verdict(run, model_json)
            lift = _working(ir.exercises[idx])
            drafted = [s["weight_kg"] for s in run["draft_exercises"][idx]["sets"]]
            assert len(lift) == cap and [s.weight_kg for s in lift] == drafted[:cap], (run["routine_id"][:8], model_json)
            for j, ex in enumerate(ir.exercises):
                if j != idx:
                    assert [s.weight_kg for s in ex.sets] == [s["weight_kg"] for s in run["draft_exercises"][j]["sets"]]
            assert [r_["applied"] for r_ in recs] == [True] and "clamped_to_floor" not in recs[0]
            assert sum(len(e.sets) for e in ir.exercises) == run["recheck"]["total_sets"]
            answers.add((v["verdict"], v["metric"], v["field"], v["to"], v.get("discarded")))
        assert answers == {("change", f"days_since_movement[{idx}]", f"exercises[{idx}].set_count", cap, None)}, answers
        # the replay reproduces the stored verdict exactly, and on the revised draft the flagged
        # lift's own rule is met: no change-grade flag on that metric, no violation anywhere.
        # (LIVE RESIDUE, observed on this fixture and left for its own issue: ff7518cd drafted a
        # SECOND exposure-1 long-gap lift, machine_shoulder_press at idx 2 with 3 working sets;
        # `deterministic_verdict` carries one change per critic, so it stays over the cap and
        # `recheck` passes because it counts vetoes, not changes. Not #4149's box.)
        v, ir, _ = _live_verdict(run, run["joints_stored_model"])
        keys = ("verdict", "metric", "field", "to")
        assert {k: v[k] for k in keys} == {k: run["joints_stored_verdict"][k] for k in keys}
        again = _live_joints_packet(run, c.draft_summary(ir))
        assert not [f for f in again["flags"] if f["severity"] == "change" and f["metric"] == v["metric"]]
        assert not again["violations"]


# ── 6. the clamp states the conflict as data ─────────────────────────────────────────
def test_the_clamp_records_the_conflict_as_data_beside_the_sentence():
    """Box 2's record shape: `clamped_to_floor`, `requested_kg`, `floor_kg`, `clamped_sets` beside
    the prose `conflict`. The 1b09ec51 specimen (79.35 lb = 36 kg on every set) and the partial
    cut (45 kg: only the top set under its 48 floor). Mutation control: drop the four assignments
    at the end of `_hold_at_floors` -> KeyError here."""
    ir = _squat_ir()
    [rec] = c.apply_changes(
        ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].weight_lbs", "to": 79.35}], set_floors=_gate_floors
    )
    assert rec["clamped_to_floor"] is True and rec["floor_kg"] == 48.0
    assert rec["requested_kg"] == pytest.approx(36.0, abs=0.01)
    assert [(r["set"], r["requested_kg"], r["floor_kg"]) for r in rec["clamped_sets"]] == [
        (1, 35.99, 48.0),
        (2, 35.99, 43.0),
        (3, 35.99, 43.0),
    ]
    assert all(r["exercise"] == "squat_barbell" for r in rec["clamped_sets"])
    assert rec["conflict"].startswith("joints_tendons vs the subtract-only floor") and rec["applied"] is False
    partial = _squat_ir(top=52.0, back=46.0)
    [rec] = c.apply_changes(
        partial,
        [{"critic": "blueprint_historian", "verdict": "change", "field": "exercises[0].weight_lbs", "to": 45 * c._LBS_PER_KG}],
        set_floors=_gate_floors,
    )
    assert (rec["clamped_to_floor"], rec["requested_kg"], rec["floor_kg"]) == (True, 45.0, 48.0)
    assert rec["clamped_sets"] == [{"exercise": "squat_barbell", "set": 1, "requested_kg": 45.0, "floor_kg": 48.0}]
    assert rec["applied"] is True


def test_a_change_the_floor_never_touches_carries_no_clamp_fields():
    """Negative control: a set-count cut on a draft at its floors clashes with nothing, so the
    record carries neither `conflict` nor any of the data fields — absence means no clamp."""
    ir = _squat_ir()
    [rec] = c.apply_changes(
        ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].set_count", "to": 2}], set_floors=_gate_floors
    )
    assert rec["applied"] is True
    assert not ({"conflict", "clamped_to_floor", "requested_kg", "floor_kg", "clamped_sets"} & set(rec))
    assert [s.weight_kg for s in ir.exercises[0].sets] == [48.0, 43.0]
