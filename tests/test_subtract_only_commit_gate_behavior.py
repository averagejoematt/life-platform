"""tests/test_subtract_only_commit_gate_behavior.py — subtract-only as a GATE (#3971).

WHAT #3927 LEFT OPEN. PR #3962 made the CRON path enforce the subtract-only rule:
`routine_generator._enforce_load_floors()` raises every working set to the band-matched
prescription floor and records the pass in `inputs_snapshot["load_floors"]`. The CHAT
path — `manage_hevy_routine draft_custom -> dry_run -> commit`, the surface that
authored BOTH #3927 specimens — was governed only by SKILL.md prose plus an auditor the
authoring session had to remember to call. So on that path the rule was a discipline,
and a routine whose notes said "if set 1 feels good, go up to 85" could still be
committed to Hevy.

WHAT THIS FILE HOLDS. The refusal, driven THROUGH THE TOOL, never against the auditor
directly (that is `tests/test_subtract_only_autoregulation_behavior.py`'s job):

  * `dry_run` REPORTS the audit — floors + every `find_conditional_up` hit;
  * `commit` REFUSES with the named `SUBTRACT_ONLY_VIOLATION` code on a conditional
    up-branch or a working set below its floor, and the refusal carries the floor's
    PROVENANCE (the load, the date, the bodyweight, the band);
  * the sanctioned DOWN-branch ("Drop to 40x10 if set 1 exceeds it.") still commits —
    a rule that ate its own down-branches would be deleted within a week;
  * `floor` / `re_entry` variants are exempt and SAY SO in the result;
  * a committed routine stamps `inputs_snapshot.load_floors.status == "applied"`, which
    is the repo-side half of the live readback (#3971 box 4).

FIXTURE PROVENANCE. Every routine, session and weigh-in below is the WIRE SHAPE out of
`tests/fixtures/subtract_only_3927/`, copied off live DynamoDB on 2026-09-19 — the IR is
deserialized by the production `routine_ir.deserialize`, and the two indexes are handed
in at the exact boundary the live loaders return (`_load_indexes`), so the gate's own
code runs end to end. Nothing here is a hand-rolled stand-in for a wire record.

THE MUTATION CONTROL. `test_mutation_removing_the_refusal_lets_the_specimen_through`
deletes the refusal from the commit path and asserts the specimen then reaches Hevy —
which is what makes every assertion above non-vacuous.
"""

from __future__ import annotations

import copy
import json
import os
from unittest.mock import patch

import pytest
from training.routine_ir import deserialize

from mcp import hevy_prescription_gate as gate, tools_hevy_routine as t
from tests.redteam_binding_testkit import bind

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "subtract_only_3927")

# The compiler renders the title from DynamoDB (phase state + routine index). Stub it so
# these stay offline; title rendering has its own tests (test_routine_title.py).
_TITLE_CTX = {
    "phase": "Phase",
    "type_count_in_phase": 1,
    "all_time_count": 1,
    "phase_started": "2026-09-06",
    "reset_epoch": "2026-09-06",
}

# The two loads at the centre of the specimen, exactly as DynamoDB holds them.
EIGHTY_LB_KG = 36.28743275485118
SEVENTY_FIVE_LB_KG = 34.01946820767298


def _fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def _wire_ir(name: str = "routine_2026-09-19_push.json"):
    """The live ROUTINE# record, through the production deserializer.

    `_`-prefixed keys are the fixture's own provenance annotations, not wire fields.
    `archetype` is supplied because the #3927 lane copied only the fields its own
    assertions needed; the live record's title ("Push — 2026-09-19") carries it, and a
    dataclass default would have been an invented value rather than a read one.
    """
    raw = {"archetype": "push", **{k: v for k, v in _fixture(name).items() if not k.startswith("_")}}
    return deserialize(raw)


def _indexes():
    """(history_index, weight_index) in the shapes the live loaders return."""
    return (
        _fixture("hevy_sessions_by_template_2026-09.json")["by_template_id"],
        _fixture("withings_weighins_2026-09.json")["weigh_ins"],
    )


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Hand the gate the live indexes at the loader boundary — the whole gate still runs."""
    history, weights = _indexes()
    monkeypatch.setattr(gate, "_load_indexes", lambda: (history, weights, None), raising=True)


def _commit(ir, *, create=None):
    """Drive the real `commit` action over one IR and return the tool result. The IR carries a
    #4066 stage-2 binding over its own content — this file is about the subtract-only gate."""
    bind(ir)
    created = create or {"routine": {"id": "hevy-1", "updated_at": "2026-09-19T23:00:00Z", "folder_id": 42}}
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="07B38369"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.list_folders", return_value={"routine_folders": [{"id": 42, "title": "Push"}]}),
        patch("training.hevy_write_client.create_routine", return_value=created) as create_mock,
        patch("training.hevy_write_client.update_routine_with_guard", return_value=created) as update_mock,
        patch(
            "training.hevy_write_client.verify_commit_landed",
            return_value={"verified": True, "reason": None, "folder_id": 42, "updated_at": "2026-09-19T23:00:00Z"},
        ),
    ):
        out = t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})
    out["_create_called"] = create_mock.called
    out["_update_called"] = update_mock.called
    return out


def _dry_run(ir):
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.hevy_template_cache.resolve_movement", return_value="07B38369"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
    ):
        return t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": ir.routine_id})


def _only(ir, movement_key: str):
    """The same wire IR reduced to ONE of its exercises — still a wire record."""
    clone = copy.deepcopy(ir)
    clone.exercises = [ex for ex in clone.exercises if ex.movement_key == movement_key]
    clone.notes = ""
    assert clone.exercises, f"{movement_key} is not in the fixture"
    return clone


def _drafted_custom(exercises, **kw):
    """Author an IR the way chat does — through `draft_custom`, not by hand."""
    captured: dict = {}
    args = {"action": "draft_custom", "target_date": "2026-09-19", "archetype": "push", "exercises": exercises, **kw}
    with patch("training.routine_repo.draft_versioned", side_effect=lambda ir: captured.setdefault("ir", ir)):
        out = t.tool_manage_hevy_routine(args)
    assert out.get("status") == "drafted_custom", out
    return captured["ir"]


# ── box 1: dry_run REPORTS ───────────────────────────────────────────────────────────
def test_dry_run_reports_the_audit_for_the_live_specimen():
    """The 2026-09-19 push routine, off the wire. dry_run names both violation classes."""
    out = _dry_run(_wire_ir())
    audit = out["prescription_audit"]
    assert audit["verdict"] == "refuse"
    assert audit["enforced"] is True
    kinds = {v["kind"] for v in audit["audit"]["violations"]}
    assert kinds == {"conditional_up", "below_floor"}, audit["audit"]["violations"]
    # the floors it saw, not just a verdict
    assert audit["load_floors"]["status"] == "applied"
    assert audit["load_floors"]["band"] == "310-319"
    assert audit["audit"]["floors_checked"] is True


def test_dry_run_still_previews_the_wire_body_it_always_did():
    """The audit is ADDITIVE — dry_run's existing contract is untouched."""
    out = _dry_run(_wire_ir())
    assert out["status"] == "preview" and "wire_body" in out and "validation" in out


# ── box 1: commit REFUSES, by name, with provenance ──────────────────────────────────
def test_the_live_specimen_refuses_the_commit_and_never_reaches_hevy():
    out = _commit(_wire_ir())
    assert out["error_code"] == gate.SUBTRACT_ONLY_ERROR_CODE == "SUBTRACT_ONLY_VIOLATION"
    assert out["_create_called"] is False and out["_update_called"] is False


def test_the_refusal_quotes_the_specimen_clause_verbatim():
    out = _commit(_wire_ir())
    msg = out["error"] if "error" in out else str(out)
    assert "If set 1 is <=7.5 go 80" in msg, msg
    assert "incline_db_press" in msg


def test_the_below_floor_refusal_carries_the_floors_provenance():
    """'Your number is too low' is unactionable. The date, load, bodyweight and band are not."""
    out = _commit(_only(_wire_ir(), "incline_db_press"))
    msg = str(out)
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "80 lb" in msg and "2026-09-11" in msg and "319.7 lb" in msg and "band 310-319" in msg, msg
    assert "75 lb" in msg  # what was prescribed


def test_a_set_below_the_prescription_floor_refuses_even_with_clean_prose():
    """Strip the conditional clause entirely — the LOAD alone still refuses."""
    ir = _only(_wire_ir(), "incline_db_press")
    ir.exercises[0].notes = "Ceiling RPE 9."
    assert all(s.weight_kg == pytest.approx(SEVENTY_FIVE_LB_KG, abs=1e-3) for s in ir.exercises[0].sets)
    out = _commit(ir)
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert out["_create_called"] is False
    assert "below_floor" in str(out)


def test_raising_the_same_sets_to_the_floor_commits():
    """The control for the test above: 80 lb is the floor, so 80 lb passes."""
    ir = _only(_wire_ir(), "incline_db_press")
    ir.exercises[0].notes = "Ceiling RPE 9."
    for s in ir.exercises[0].sets:
        s.weight_kg = EIGHTY_LB_KG
    out = _commit(ir)
    assert out["status"] == "committed", out
    assert out["_create_called"] is True


# ── box 2: the #3927 specimen shapes, planted THROUGH the tool ───────────────────────
def test_the_sanctioned_down_branch_stays_clean():
    """'Drop to 40x10 if set 1 exceeds it.' — verbatim off the same live routine."""
    ir = _drafted_custom(
        [
            {
                "movement_key": "db_shoulder_press",
                "notes": "Ceiling RPE 8.5. Drop to 40x10 if set 1 exceeds it.",
                "sets": [{"weight_lbs": 45, "reps": 8, "count": 3}],
            }
        ]
    )
    out = _commit(ir)
    assert out["status"] == "committed", out
    assert "clean" in out["prescription_gate"]


def test_go_up_to_85_refuses():
    """The sentence class #3971 was filed on, authored the way chat authors it."""
    ir = _drafted_custom(
        [
            {
                "movement_key": "db_shoulder_press",
                "notes": "Ceiling RPE 8.5. If set 1 feels good, go up to 85.",
                "sets": [{"weight_lbs": 75, "reps": 8, "count": 3}],
            }
        ]
    )
    out = _commit(ir)
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "go up to 85" in str(out) or "go up" in str(out)
    assert out["_create_called"] is False


def test_a_draft_custom_set_below_the_floor_refuses():
    """75 lb of incline authored from chat, against the 80 lb he already put on the board."""
    ir = _drafted_custom(
        [{"movement_key": "incline_db_press", "notes": "Ceiling RPE 9.", "sets": [{"weight_lbs": 75, "reps": 8, "count": 3}]}]
    )
    out = _commit(ir)
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "2026-09-11" in str(out)


# ── box 3: floor / re_entry are exempt, and say so ───────────────────────────────────
@pytest.mark.parametrize("variant", ["floor", "re_entry"])
def test_the_no_load_variants_skip_the_refusal_and_say_so(variant):
    ir = _wire_ir()  # the specimen — it WOULD refuse on the ideal variant
    ir.variant = variant
    out = _commit(ir)
    assert out["status"] == "committed", out
    assert "SKIPPED" in out["prescription_gate"] and variant in out["prescription_gate"]
    assert "no load floor by design" in out["prescription_gate"] or "asserts no load" in out["prescription_gate"]


def test_the_ideal_variant_of_the_same_routine_does_refuse():
    """The control that keeps the skip from passing vacuously."""
    ir = _wire_ir()
    assert ir.variant == "ideal"
    assert _commit(ir)["error_code"] == "SUBTRACT_ONLY_VIOLATION"


# ── box 4 (repo-side half): the stored IR records the pass ───────────────────────────
def test_a_committed_routine_stamps_load_floors_applied_into_the_stored_ir():
    """`inputs_snapshot.load_floors.status == 'applied'` is what the live readback reads."""
    ir = _only(_wire_ir(), "incline_db_press")
    ir.exercises[0].notes = "Ceiling RPE 9."
    for s in ir.exercises[0].sets:
        s.weight_kg = EIGHTY_LB_KG
    assert "load_floors" not in (ir.inputs_snapshot or {})
    out = _commit(ir)
    assert out["status"] == "committed"
    stored = ir.inputs_snapshot["load_floors"]
    assert stored["status"] == "applied"
    assert stored["source"] == "chat_commit_gate" and stored["enforcement"] == gate.ENFORCEMENT
    assert stored["movements"]["incline_db_press"]["floor_kg"] == pytest.approx(EIGHTY_LB_KG)
    assert stored["movements"]["incline_db_press"]["basis"]["date"] == "2026-09-11"


def test_a_generator_authored_floor_audit_is_reused_not_recomputed():
    """The cron path already raised the sets; two derivations of one floor would drift."""
    ir = _only(_wire_ir(), "incline_db_press")
    ir.exercises[0].notes = "Ceiling RPE 9."
    ir.inputs_snapshot = {"load_floors": {"status": "applied", "rule": "r", "movements": {}}}
    out = _commit(ir)
    assert out["status"] == "committed", out  # 75 lb passes: the generator's audit asserts no floor
    assert ir.inputs_snapshot["load_floors"]["source"] == "routine_generator"


# ── the absences stay legible ────────────────────────────────────────────────────────
def test_an_index_load_failure_is_named_not_swallowed(monkeypatch):
    """A DDB hiccup costs the FLOOR arm. It must not read as a clean audit."""
    monkeypatch.setattr(gate, "_load_indexes", lambda: ({}, {}, "ClientError: throttled"), raising=True)
    ir = _only(_wire_ir(), "incline_db_press")
    ir.exercises[0].notes = "Ceiling RPE 9."
    out = _commit(ir)
    assert out["status"] == "committed"  # fail-soft, as the cron path degrades
    assert "indexes_unavailable" in out["prescription_gate"]
    assert "floors_checked=False" in out["prescription_gate"]


def test_the_prose_arm_still_fires_when_the_floor_arm_cannot_run(monkeypatch):
    """The conditional-up detector is pure text — no index, no excuse."""
    monkeypatch.setattr(gate, "_load_indexes", lambda: ({}, {}, "ClientError: throttled"), raising=True)
    out = _commit(_only(_wire_ir(), "incline_db_press"))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"


# ── THE MUTATION CONTROL ─────────────────────────────────────────────────────────────
def test_mutation_removing_the_refusal_lets_the_specimen_through():
    """Delete the refusal from the commit path; the #3927 specimen reaches Hevy again.

    This is what makes every assertion above non-vacuous: without this control the
    refusal tests could be passing on some unrelated error (a missing stub, a bad
    routine_id) rather than on the gate. With the refusal removed and NOTHING else
    changed, the same IR commits — so the gate is the only thing stopping it.
    """
    with patch.object(t, "refusal_message", return_value=None):
        out = _commit(_wire_ir())
    assert out.get("status") == "committed", out
    assert out["_create_called"] is True
    # and the unmutated path refuses the very same IR
    assert _commit(_wire_ir())["error_code"] == "SUBTRACT_ONLY_VIOLATION"
