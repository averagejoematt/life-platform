"""tests/test_critic_veto_override_4076.py — the owner override of ONE vetoing critic (#4076).

On 2026-09-22 the only way past a stage-2 veto was to skip stage 2 entirely, and skipping it
also dropped the joints critic's set cap — a change that had nothing to do with the veto.
The override is the narrow door instead:

  * `plan_next_session(routine_id, veto_override={critic, owner_words})` marks ONLY the named
    critic's veto overridden, with his words verbatim;
  * every other critic's change is applied exactly as without the override (the joints cap);
  * the words go to the corrections ledger through the `log_coach_correction` write path,
    naming the vetoing critic and signal — and if that write fails, the veto stands;
  * the override is visible on the committed routine's record, in the Hevy notes and in the
    commit result line.

The fixture is the 09-22 shape: the historian vetoes (a model escalation on a flagged
metric), the joints critic cuts the session 20 -> 14 — the owner's signed −30 % deload, computed
in code since #4149 (the fake model still asks for 16; its number is never applied). Mutation
controls are named per test.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics  # noqa: E402
from test_tools_plan_critics_3752 import KG, _approving, _commit_patches, _evidence, _stage2_patches  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import (
    tools_hevy_routine as t,  # noqa: E402
    tools_plan as tp,  # noqa: E402
)

WORDS = "Overruling the historian:  I benched and squatted this load on Friday, the band is 2019 data. Joints cap stands."


def _routine():
    """20 sets over five movements; exercise 0 is a 200 lb squat over the band-matched ceiling."""
    ex = [ExerciseBlock(movement_key="tmpl:0", rationale_tag="Squat (Barbell)", sets=[Set(weight_kg=200.0 * KG, reps=5) for _ in range(4)])]
    ex += [
        ExerciseBlock(movement_key=f"tmpl:{i}", rationale_tag=f"Move {i}", sets=[Set(weight_kg=40, reps=10) for _ in range(4)])
        for i in range(1, 5)
    ]
    return RoutineSpec(
        routine_id="r-4076",
        target_date="2026-09-22",
        archetype="full_body",
        version=1,
        source_action="draft_custom",
        notes="Full body.",
        exercises=ex,
    )


def _fixture_evidence(*, pain0=False):
    ev = _evidence(pain0=pain0)  # weeks_in_block=0 -> the historian's squat flag is a `change`
    # #4161: the joints cut is driven by the fatigue trigger now (readiness below the floor 2 days
    # running — `_run` patches the readiness reader), not the retired loaded-streak escalation.
    ev["loaded_lifting_streak"] = 5
    rows = [dict(ev["exercises"][0])]
    rows += [
        {
            "idx": i,
            "label": f"Move {i}",
            "template_id": str(i),
            "days_since": 3,
            "pain_flag_any": False,
            "pain_dates": [],
            "pain_layer_status": "ok",
        }
        for i in range(1, 5)
    ]
    ev["exercises"] = rows
    return ev


def _reply(obj):
    return {"content": [{"type": "text", "text": json.dumps(obj)}], "stop_reason": "end_turn"}


def _model(body):
    """The 09-22 shape: the historian escalates its squat `change` to a VETO; the joints critic
    caps the session four sets under whatever draft it is handed; the others approve."""
    sent = json.loads(body["messages"][0]["content"].split("\nReturn the JSON object.")[0])
    if "blueprint_historian" in body["system"]:
        return _reply(
            {"verdict": "veto", "metric": "band_top_lbs[0]", "value": 198.4, "field": None, "to": None, "sentence": "Too heavy, cold."}
        )
    if "joints_tendons" in body["system"]:
        to = sent["draft"]["total_sets"] - 4
        return _reply(
            {
                "verdict": "change",
                "metric": "fatigue_trigger",
                "value": 5,
                "field": "session.total_sets",
                "to": to,
                "sentence": f"Day 10 of a streak; cap at {to}.",
            }
        )
    return _approving(body)


def _run(ir, *, override=None, evidence=None, ledger=None, ledger_error=None):
    ledger = ledger if ledger is not None else []

    def record(item_ref, words, error_class):
        if ledger_error:
            raise ledger_error
        ledger.append({"item_ref": item_ref, "words": words, "error_class": error_class})
        return f"CORRECTION#2026-09-22#{len(ledger):08x}"

    args = {"target_date": "2026-09-22", "routine_id": ir.routine_id}
    if override is not None:
        args["veto_override"] = override
    with ExitStack() as st:
        for cm in _stage2_patches(ir, evidence or _fixture_evidence(), invoke=_model):
            st.enter_context(cm)
        st.enter_context(patch("mcp.tools_plan._record_override_correction", side_effect=record))
        st.enter_context(patch("mcp.tools_plan._readiness_low_streak", return_value=(2, {"state": "measured"})))  # #4161
        out = tp.tool_plan_next_session(args)
    return out, ledger


def _commit(ir):
    created = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, created):
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    return res, created


def _total_sets(ir):
    return sum(len(e.sets) for e in ir.exercises)


# ── the fixture the issue names ──────────────────────────────────────────────────────
def test_veto_plus_override_keeps_the_joints_cap_and_records_the_override_on_the_committed_routine():
    """Mutation controls: (a) in `veto_reason`, count overridden vetoes again (`standing_vetoes`
    -> every veto) -> the commit refuses CRITIC_VETO and this reds; (b) drop the
    `critic_overrides.apply_overrides(...)` call in `_run_stage_2` -> no override record and this reds;
    (c) skip `apply_changes` when an override is present -> total sets stay 20 and this reds."""
    ir = _routine()
    out, ledger = _run(ir, override={"critic": "blueprint_historian", "owner_words": WORDS})
    crit = out["critics"]

    hist = next(v for v in crit["verdicts"] if v["critic"] == "blueprint_historian")
    assert hist["verdict"] == "veto", "the critic still said it — the override does not rewrite the verdict"
    assert hist["owner_override"]["owner_words"] == WORDS, "verbatim, double space included"
    assert crit["veto"] is False and crit["recheck"]["passed"] is True
    assert "OVERRIDDEN by the owner" in crit["next"]

    # every OTHER critic's change still applied — the joints set cap
    assert {"critic": "joints_tendons", "field": "session.total_sets", "to": 14, "applied": True, "why": None} in crit["changes"]
    assert _total_sets(ir) == 14 and crit["recheck"]["total_sets"] == 14
    # and ONLY the historian's objection is lifted: its own field (the squat load) is not applied
    assert all(s.weight_kg == pytest.approx(200.0 * KG, abs=0.01) for s in ir.exercises[0].sets)

    # the log_coach_correction write path, naming the critic and the signal
    assert len(ledger) == 1
    row = ledger[0]
    assert row["words"] == WORDS and row["error_class"] == "other"
    assert row["item_ref"]["surface"] == "plan_critics" and row["item_ref"]["coach"] == "training_coach"
    assert row["item_ref"]["critic"] == "blueprint_historian" and row["item_ref"]["signal"] == "band_top_lbs[0]"
    assert row["item_ref"]["routine_id"] == "r-4076"

    [rec] = crit["owner_overrides"]
    assert rec["applied"] is True and rec["critic"] == "blueprint_historian" and rec["owner_words"] == WORDS
    assert rec["signal"] == "band_top_lbs[0]" and rec["correction_id"].startswith("CORRECTION#")

    res, created = _commit(ir)
    assert res.get("status") == "committed", res
    assert "historian veto (owner-overridden)" in res["critics"]
    assert "joints/tendons change" in res["critics"]
    body = created[0]["routine"]
    assert sum(len(e["sets"]) for e in body["exercises"]) == 14, "the cap reached Hevy"
    notes = body["exercises"][0]["notes"]
    assert "- historian VETO OVERRIDDEN BY OWNER" in notes
    assert "owner override of historian (" in notes and "I benched and squatted this load on Friday" in notes
    # the committed routine's own record carries the override, words verbatim
    stored = ir.inputs_snapshot["critics"]
    assert stored["owner_overrides"][0]["owner_words"] == WORDS and stored["veto"] is False


def test_no_override_the_veto_holds_and_the_commit_refuses():
    """The mutation control for the fixture above: the same draft, the same critics, no
    override -> the veto stands and the commit refuses by name. (The joints cap is still
    applied to the stored draft — it always was; what was lost on 09-22 was the commit.)"""
    ir = _routine()
    out, ledger = _run(ir)
    crit = out["critics"]
    assert crit["veto"] is True and crit["owner_overrides"] == [] and ledger == []
    assert crit["next"].startswith("VETO") and "veto_override" in crit["next"]
    assert _total_sets(ir) == 14
    res, created = _commit(ir)
    assert "CRITIC_VETO" in json.dumps(res) and created == []


def test_the_override_lifts_only_the_named_critic_another_veto_still_blocks():
    """Mutation control: make `standing_vetoes` drop every veto once ANY override is applied
    -> the joints pain veto stops blocking and this reds."""
    ir = _routine()
    out, ledger = _run(ir, override={"critic": "blueprint_historian", "owner_words": WORDS}, evidence=_fixture_evidence(pain0=True))
    crit = out["critics"]
    j = next(v for v in crit["verdicts"] if v["critic"] == "joints_tendons")
    assert j["verdict"] == "veto" and "owner_override" not in j
    assert crit["veto"] is True and len(ledger) == 1
    assert crit["recheck"]["passed"] is False
    res, created = _commit(ir)
    assert "CRITIC_VETO" in json.dumps(res) and "pain flag" in json.dumps(res) and created == []


def test_an_override_on_a_critic_that_did_not_veto_is_recorded_unapplied_and_logs_nothing():
    ir = _routine()
    out, ledger = _run(ir, override={"critic": "rate_advocate", "owner_words": WORDS})
    crit = out["critics"]
    [rec] = crit["owner_overrides"]
    assert rec["applied"] is False and "did not veto" in rec["why"]
    assert ledger == [] and crit["veto"] is True, "the historian's veto was not the one named — it stands"


def test_a_failed_ledger_write_leaves_the_veto_standing():
    """An override with no audit row is the silent bypass this replaces. Mutation control:
    mark the verdict before calling `record_correction` -> the veto lifts and this reds."""
    ir = _routine()
    out, _ = _run(ir, override={"critic": "blueprint_historian", "owner_words": WORDS}, ledger_error=RuntimeError("ddb down"))
    crit = out["critics"]
    [rec] = crit["owner_overrides"]
    assert rec["applied"] is False and "override NOT applied" in rec["why"] and "ddb down" in rec["why"]
    assert crit["veto"] is True
    assert not any(v.get("owner_override") for v in crit["verdicts"])


@pytest.mark.parametrize(
    "override, needle",
    [
        ({"critic": "nutrition", "owner_words": WORDS}, "must be one of"),
        ({"critic": "blueprint_historian", "owner_words": "   "}, "needs owner_words"),
        ({"critic": "blueprint_historian"}, "needs owner_words"),
        ([{"critic": "joints_tendons", "owner_words": "a"}, {"critic": "joints_tendons", "owner_words": "b"}], "twice"),
        ("override it", "must be objects"),
    ],
)
def test_a_malformed_override_is_an_error_before_anything_runs(override, needle):
    ir = _routine()
    with patch("training.routine_repo.get_current", side_effect=AssertionError("nothing may run on a malformed override")):
        out = tp.tool_plan_next_session({"target_date": "2026-09-22", "routine_id": ir.routine_id, "veto_override": override})
    assert needle in json.dumps(out), out


def test_an_override_without_a_routine_id_is_refused():
    out = tp.tool_plan_next_session({"target_date": "2026-09-22", "veto_override": {"critic": "joints_tendons", "owner_words": "x"}})
    assert "MISSING_ARG" in json.dumps(out) and "routine_id" in json.dumps(out)


def test_veto_reason_skips_only_overridden_vetoes_on_a_stored_record():
    rec = {
        "verdicts": [
            {"critic": "blueprint_historian", "verdict": "veto", "reason": "band", "owner_override": {"owner_words": "mine"}},
            {"critic": "joints_tendons", "verdict": "veto", "reason": "pain flag on Squat"},
        ]
    }
    ir = _routine()
    ir.inputs_snapshot = {"critics": rec}
    assert critics.veto_reason(ir) == "joints_tendons: pain flag on Squat"
    rec["verdicts"].pop()
    assert critics.veto_reason(ir) is None
    # an `owner_override` key on a non-veto is meaningless and never counts as one
    assert critics.is_overridden({"verdict": "change", "owner_override": {"owner_words": "x"}}) is False


def test_the_thread_row_carries_the_override_and_drops_it_from_surprises():
    ir = _routine()
    _run(ir, override={"critic": "blueprint_historian", "owner_words": WORDS})
    row = critics.thread_entry(ir, today="2026-09-22")
    assert row["surprises"] == []
    assert row["owner_overrides"] == [
        {"critic": "blueprint_historian", "signal": "band_top_lbs[0]", "owner_words": WORDS, "at": row["owner_overrides"][0]["at"]}
    ]
    hist = next(e for e in row["learning_log"] if e["critic"] == "blueprint_historian")
    assert hist["verdict"] == "veto" and hist["owner_overridden"] is True


def test_the_ledger_write_is_the_log_coach_correction_path():
    """`_record_override_correction` writes through `coach_corrections.write_correction` — the
    same function `log_coach_correction` calls — cycle-stamped the same way. Mutation control:
    point it at any other writer -> no CORRECTION# row lands on the ledger partition and this reds."""
    from coach import coach_checkin, coach_corrections
    from fakes import FakeDdbTable

    table = FakeDdbTable()
    ref = {"surface": "plan_critics", "coach": "training_coach", "critic": "blueprint_historian", "signal": "band_top_lbs[0]"}
    with patch("mcp.config.table", table), patch.object(coach_checkin, "read_cycle", return_value=17):
        sk = tp._record_override_correction(ref, WORDS, "other")
    [row] = table.puts
    assert row["pk"] == coach_corrections.PK and row["sk"] == sk and sk.startswith("CORRECTION#")
    assert row["correction_text"] == WORDS and row["item_ref"]["critic"] == "blueprint_historian" and row["cycle"] == 17
