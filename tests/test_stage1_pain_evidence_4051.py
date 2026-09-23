"""tests/test_stage1_pain_evidence_4051.py — the stage-1 tripwire that was looking at nothing.

THE DEFECT (#4051)
  `plan_next_session` stage 1 built its pain-flag input from `evidence["exercises"]`, and
  that list came from a DRAFT routine's exercise blocks. With no draft — the ordinary case,
  since stage 1 is what you call BEFORE drafting — the list was empty, every branch of
  `_tripwire_states` fell through, and the constraint block reported:

      days_since_movement: {}
      pain_flag_named_site: {state: "clear", observed: []}
      owner_dismissals: []

  Measured 2026-09-22 15:3xZ on the deployed MCP (`plan-engine@1.2.0`), at the same minute
  the derived note layer held `pain_flag_any true, pain_dates ["2026-09-13"]` on Romanian
  Deadlift (Barbell) — a movement performed 2026-09-13 and 2026-09-17 — and the owner's
  dismissal of that exact site sat in DynamoDB (`DISMISSAL#right_lower_back#2026-09-21`,
  written 15:34:06Z, its own `reads_as` computing `dismissed_by_owner`). So the one state
  #4036 says the row must never show — `clear` over a flagged, humanly-overridden site —
  was the state it showed, because the instance never reached the engine. A tripwire that
  cannot see the layer it guards is silence dressed as clearance (#3768's class).

WHAT IS PINNED HERE
  1. THE DERIVATION — the evidence set is the movements PERFORMED in the trailing
     `PAIN_LOOKBACK_DAYS`, read from the Hevy partition CROSS-PHASE (#4030/#4032:
     taxonomy-derived, never a hand-typed `include_pilot`; the 421 tombstoned legacy daily
     aggregates stay excluded), and `days_since_movement` is non-empty on a day with any
     recent session.
  2. THE READ-BACK — with the live flag and the live dismissal both on the record, stage 1
     reads `pain_flag_named_site.state == "dismissed_by_owner"` with the date and his words,
     and `owner_dismissals` is non-empty. This is the read-back #4036 box 5 expects.
  3. THE EMPTY PATH — an empty or unreadable evidence set reads `unknown` with
     `evidence: none — <reason>`, never `clear`.
  4. THE DEGRADED LAYER — today's layer is `degraded` (`cap_exceeded x24`, the Haiku monthly
     cap; deterministic signals only) and the 2026-09-13 flag is one of those degraded rows.
     It still reaches stage 1, with the layer's status beside it. Layer health qualifies the
     ABSENCE of flags; it can never un-say one that is on the record.
  5. MUTATION CONTROL — neutralise the derivation (`_performed_movements` → the pre-#4051
     empty set) and the planted flag disappears; `test_mutation_control_*` asserts BOTH
     halves in one run, so the green above is bought by the derivation, not the fixtures.

THE FIXTURE IS THE WIRE
  `_FakeTable` is patched over `mcp.core.table` and `mcp.tools_training_notes.table`, not
  over any reader, so every assertion runs through the real `query_source` →
  `_apply_phase_filter` → `query_source_cross_phase` path and the real note parse. Every row
  shape below is copied from the live partitions (read-only, 2026-09-22): the Hevy
  per-workout rows, the tombstoned legacy aggregate, the RDL note row with its
  `cap_exceeded` degrade reason, the dismissal record, and the health block.
"""

from __future__ import annotations

import copy
import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import plan_engine, training_context_registry as tcr  # noqa: E402

import mcp.core as core  # noqa: E402
import mcp.tools_plan as tp  # noqa: E402
import mcp.tools_training_notes as tn  # noqa: E402

TODAY = "2026-09-22"
HEVY_PK = "USER#matthew#SOURCE#hevy"
RDL_TID = "2B4B7310"
RDL = "Romanian Deadlift (Barbell)"
LAT_TID = "6A6C31A5"
LAT = "Lat Pulldown (Cable)"
PRESS_TID = "878CD1D0"
PRESS = "Shoulder Press (Dumbbell)"
FLAG_NOTE_DATE = "2026-09-13"
DISMISSED_ON = "2026-09-21"
OWNER_WORDS = "right lower back gone"

# ── the Hevy wire, copied from the live partition ─────────────────────────────
# 2026-08-28 is PRE-GENESIS (cycle 17 genesis is 2026-09-06) and therefore stamped
# `phase=pilot` by the restart tagger — inside the 28-day window, invisible to a
# phase-filtered read. That is the #4030 half of this fix, demonstrated rather than asserted.
_PILOT_SESSION = {
    "pk": HEVY_PK,
    "sk": "DATE#2026-08-28#WORKOUT#36bd9061-190b-43d4-acfd-515f5bb85dd0",
    "date": "2026-08-28",
    "phase": "pilot",
    "workout_name": "Push",
    "exercises": [{"template_id": PRESS_TID, "name": PRESS, "notes": "", "sets": [{"weight_kg": 27.2, "reps": 10}]}],
}
# The superseded generation covering that SAME session: tombstoned in place 2026-05-26.
# `normalize_hevy_items` parses this shape too, so a bypass without the tombstone drop
# counts the session twice.
_LEGACY_TOMBSTONED_DUPLICATE = {
    "pk": HEVY_PK,
    "sk": "DATE#2026-08-28",
    "date": "2026-08-28",
    "phase": "pilot",
    "tombstone": True,
    "tombstoned_reason": "legacy_daily_aggregate_superseded_by_per_workout",
    "workouts": [{"title": "Push", "exercises": [{"name": PRESS, "sets": [{"weight_lbs": 60.0, "reps": 10}]}]}],
}
_SESSION_0913 = {
    "pk": HEVY_PK,
    "sk": "DATE#2026-09-13#WORKOUT#29cbd264-ea01-46d6-bccb-f2692721b1b8",
    "date": "2026-09-13",
    "phase": "experiment",
    "workout_name": "Legs",
    "exercises": [
        {
            "template_id": RDL_TID,
            "name": RDL,
            "notes": (
                "This felt fine. But i could feel my right side of my lower back more consciously.  And so i decided to "
                "not add weight this workout to risk anything."
            ),
            "sets": [{"weight_kg": 79.37866488, "reps": 8}],
        }
    ],
}
_SESSION_0917 = {
    "pk": HEVY_PK,
    "sk": "DATE#2026-09-17#WORKOUT#4c43e553-48c3-4a57-bb48-af833f38a3d6",
    "date": "2026-09-17",
    "phase": "experiment",
    "workout_name": "Legs",
    "exercises": [
        {"template_id": RDL_TID, "name": RDL, "notes": "", "sets": [{"weight_kg": 79.37866488, "reps": 8}]},
        {"template_id": LAT_TID, "name": LAT, "notes": "", "sets": [{"weight_kg": 54.4, "reps": 10}]},
    ],
}

# ── the derived note layer's wire, copied verbatim from the live row ──────────
_RDL_PAIN_NOTE = {
    "pk": f"USER#matthew#SOURCE#training_notes#EXERCISE#{RDL_TID}",
    "sk": "DATE#2026-09-13#WORKOUT#29cbd264-ea01-46d6-bccb-f2692721b1b8",
    "date": FLAG_NOTE_DATE,
    "workout_uid": "hevy:29cbd264-ea01-46d6-bccb-f2692721b1b8",
    "exercise_template": RDL_TID,
    "exercise_name": RDL,
    "inferred": True,
    "degraded": True,
    "degraded_reason": "cap_exceeded: CapExceeded: training-notes Haiku monthly cap 300 reached",
    "extracted_by": "deterministic",
    "pain_flag": True,
    "signals": [{"class": "pain_discomfort", "summary": "deterministic pain-lexicon hit", "confidence": 0.6}],
    "sentiment": None,
    "note_raw": "…i could feel my right side of my lower back more consciously…",
}
_LAT_CLEAN_NOTE = {
    "pk": f"USER#matthew#SOURCE#training_notes#EXERCISE#{LAT_TID}",
    "sk": "DATE#2026-09-17#WORKOUT#4c43e553-48c3-4a57-bb48-af833f38a3d6",
    "date": "2026-09-17",
    "workout_uid": "hevy:4c43e553-48c3-4a57-bb48-af833f38a3d6",
    "exercise_template": LAT_TID,
    "exercise_name": LAT,
    "degraded": False,
    "pain_flag": False,
    "signals": [{"class": "progression", "summary": "added a plate", "confidence": 0.7, "value": "+5 lb"}],
}

# The live health block, read 2026-09-22: DEGRADED, not dark — 24 of 27 recent records
# carry `cap_exceeded`, so the semantic pass did not run on them and the deterministic
# pass's flags are all the layer has. Pinned rather than computed so this file does not
# silently change meaning as the real 14-day window rolls forward.
_LIVE_HEALTH_DEGRADED = {
    "checked": True,
    "lookback_days": 14,
    "noted_exercise_sessions": 27,
    "records_found": 27,
    "degraded": 24,
    "degraded_reasons": {"cap_exceeded": 24},
    "degraded_reasons_note": "cap_exceeded x24",
    "missing_records": 0,
    "extractor_dark": False,
}


def _dismissal_row():
    """The live record, built through the registry so the test and the write agree."""
    rec = tcr.build_dismissal_record(
        site="right lower back",
        dismissed_on=DISMISSED_ON,
        words=OWNER_WORDS,
        movements=[RDL],
        flag_note_date=FLAG_NOTE_DATE,
        recorded_at="2026-09-22T15:34:06Z",
    )
    return {**rec, "pk": tcr.DISMISSAL_PK}


def _rows(include_dismissal=True):
    out = [
        copy.deepcopy(_PILOT_SESSION),
        copy.deepcopy(_LEGACY_TOMBSTONED_DUPLICATE),
        copy.deepcopy(_SESSION_0913),
        copy.deepcopy(_SESSION_0917),
        copy.deepcopy(_RDL_PAIN_NOTE),
        copy.deepcopy(_LAT_CLEAN_NOTE),
    ]
    if include_dismissal:
        out.append(_dismissal_row())
    return out


# ── the fake table: real DynamoDB Query semantics over the shapes these readers build ──
_PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"


def _eval_key_condition(cond, item) -> bool:
    expr = cond.get_expression()
    op = expr["operator"]
    vals = expr["values"]
    if op == "AND":
        return _eval_key_condition(vals[0], item) and _eval_key_condition(vals[1], item)
    attr = vals[0].name
    actual = str(item.get(attr, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    if op == ">=":
        return actual >= vals[1]
    raise AssertionError(f"fake table: unhandled key operator {op!r} — the fixture must be the wire")


class _FakeTable:
    def __init__(self, rows, raise_on_pk=None):
        self.rows = rows
        self.raise_on_pk = raise_on_pk
        self.filter_expressions_seen: list = []
        self.pks_queried: list = []

    def query(self, **kwargs):
        cond = kwargs["KeyConditionExpression"]
        rows = [r for r in self.rows if _eval_key_condition(cond, r)]
        pk = cond.get_expression()["values"][0].get_expression()["values"][1]
        self.pks_queried.append(pk)
        if self.raise_on_pk and self.raise_on_pk in str(pk):
            raise RuntimeError("DDB down")
        fe = kwargs.get("FilterExpression")
        self.filter_expressions_seen.append(fe)
        if fe is not None:
            assert fe == _PHASE_FILTER_EXPRESSION, f"unexpected FilterExpression {fe!r}"
            field = kwargs["ExpressionAttributeNames"]["#phase"]
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            rows = [r for r in rows if field not in r or r[field] == wanted]
        return {"Items": rows}


@pytest.fixture
def wired(monkeypatch):
    fake = _FakeTable(_rows())
    monkeypatch.setattr(core, "table", fake)
    monkeypatch.setattr(tn, "table", fake)
    return fake


# ══════════════════════════════════════════════════════════════════════════════
# 1. the derivation — what he PERFORMED, cross-phase
# ══════════════════════════════════════════════════════════════════════════════
class TestTheDerivation:
    def test_the_evidence_set_is_the_movements_performed_not_a_drafts_list(self, wired):
        ev = tp._gather_performed_evidence(TODAY, "degraded")
        by_label = {r["label"]: r for r in ev["exercises"]}
        assert set(by_label) == {RDL, LAT, PRESS}, "the set is every movement performed in the window"
        assert by_label[RDL]["days_since"] == 5 and by_label[RDL]["last_performed"] == "2026-09-17"
        assert by_label[RDL]["sessions"] == 2, "RDL was performed on 09-13 and 09-17"
        assert ev["scope"]["status"] == "read" and ev["scope"]["movements_considered"] == 3

    def test_the_hevy_read_is_cross_phase_so_the_pre_genesis_half_of_the_window_is_not_dropped(self, wired):
        """The 28-day window straddles the 2026-09-06 genesis. Mutation control: swap
        `_read_hevy_all_phases` for `query_source_range` and the pre-genesis movement
        vanishes while the read still reports success."""
        labels = {r["label"] for r in tp._gather_performed_evidence(TODAY, "ok")["exercises"]}
        assert PRESS in labels, "the phase=pilot session inside the window was dropped"
        hevy_filters = [fe for fe, pk in zip(wired.filter_expressions_seen, wired.pks_queried) if pk == HEVY_PK]
        assert hevy_filters and all(fe is None for fe in hevy_filters), hevy_filters

    def test_the_phase_decision_is_derived_from_the_taxonomy_not_hand_typed(self):
        """#4030/#4032: `source_reads_cross_phase` is the sanctioned derivation. A literal
        `include_pilot=True` in this module would survive a reclassification and be wrong."""
        src = (REPO / "mcp" / "tools_plan.py").read_text()
        assert "include_pilot=" not in src, "the phase decision must come from the taxonomy helper, never a literal"
        assert "_read_hevy_all_phases" in src, "the evidence set must read Hevy through the one sanctioned cross-phase path"

    def test_the_superseded_legacy_generation_is_not_counted_twice(self, wired):
        rows = {r["label"]: r for r in tp._gather_performed_evidence(TODAY, "ok")["exercises"]}
        assert rows[PRESS]["sessions"] == 1, "the tombstoned daily aggregate was counted as a second session"

    def test_days_since_movement_is_non_empty_on_a_day_with_any_recent_session(self, wired):
        block = _stage1(wired)["constraint_block"]
        assert block["days_since_movement"], "a day with three performed movements reported {}"
        assert block["days_since_movement"][RDL] == 5


# ══════════════════════════════════════════════════════════════════════════════
# 2. the read-back #4036 box 5 was written to expect
# ══════════════════════════════════════════════════════════════════════════════
def _stage1(fake, target_date=TODAY, health=None, extra=()):
    """`plan_next_session` with no routine_id, every reader OTHER than the two partitions
    under test stubbed, so the Hevy read, the note read and the dismissal read all run for
    real against `_FakeTable`."""
    patches = [
        patch("mcp.tools_benchmark.tool_get_benchmark", return_value={"applicable": False, "reason": "no band"}),
        patch("mcp.tools_health.tool_get_readiness_score", return_value={"score": 55}),
        patch("mcp.tools_training.tool_get_acwr_status", return_value={"zone": "safe"}),
        patch("mcp.tools_strength.tool_get_muscle_volume", return_value={}),
        patch("mcp.tools_plan._protein_days_7d", return_value=(None, None)),
        patch("mcp.tools_plan._walking_volume_last_7d", return_value=None),
        patch("mcp.tools_plan._rotation_window", return_value=(None, None)),
        patch("mcp.tools_plan._nutrition_critics_block", return_value={"verdicts": []}),
        patch("training.training_notes.training_notes_health", return_value=health or _LIVE_HEALTH_DEGRADED),
        *extra,
    ]
    with ExitStack() as st:
        for cm in patches:
            st.enter_context(cm)
        return tp.tool_plan_next_session({"target_date": target_date})


def _pain_row(out):
    return next(t for t in out["constraint_block"]["tripwires"] if t["id"] == "pain_flag_named_site")


class TestTheReadBack:
    def test_the_flagged_and_dismissed_site_reads_dismissed_by_owner_never_clear(self, wired):
        row = _pain_row(_stage1(wired))
        assert row["state"] == "dismissed_by_owner", row
        assert row["state"] != "clear", "the one state #4036 says this row must never show"
        assert row["observed"] == [RDL]
        assert DISMISSED_ON in row["detail"] and OWNER_WORDS in row["detail"]
        assert row["dismissals"][0]["dismissed"] is True and row["dismissals"][0]["superseded"] is False

    def test_owner_dismissals_is_non_empty_with_the_date_and_his_words(self, wired):
        block = _stage1(wired)["constraint_block"]
        assert block["owner_dismissals"], "owner_dismissals was the empty list the deployed tool returned"
        d = block["owner_dismissals"][0]
        assert d["site"] == "right lower back" and d["dismissed_on"] == DISMISSED_ON and d["words"] == OWNER_WORDS
        line = next((h for h in block["honesty"] if "owner dismissal" in h), None)
        assert line and OWNER_WORDS in line and DISMISSED_ON in line, block["honesty"]

    def test_the_flag_instance_carries_its_own_note_date_so_the_re_arm_can_be_computed(self, wired):
        row = _pain_row(_stage1(wired))
        assert row["instances"] == [{"movement": RDL, "note_dates": [FLAG_NOTE_DATE]}]

    def test_a_later_note_on_the_same_site_re_arms_the_flag_through_the_live_read(self, wired):
        """The re-arm rule is `training_context_registry`'s and is NOT re-implemented here —
        this asserts the stage-1 read feeds it the dates it needs."""
        wired.rows.append(
            {
                **copy.deepcopy(_RDL_PAIN_NOTE),
                "sk": "DATE#2026-09-22#WORKOUT#deadbeef-0000-0000-0000-000000000000",
                "date": "2026-09-22",
                "workout_uid": "hevy:deadbeef",
            }
        )
        row = _pain_row(_stage1(wired))
        assert row["state"] == "tripped", "a note dated after the dismissal must re-arm the flag"
        assert row["dismissals"][0]["state"] == "re_armed" and row["dismissals"][0]["superseded"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. the empty-evidence path is reported, never silently clear
# ══════════════════════════════════════════════════════════════════════════════
class TestTheEmptyPath:
    def test_no_session_in_the_window_reads_unknown_with_evidence_none(self, monkeypatch):
        fake = _FakeTable([_dismissal_row()])  # a dismissal on file, but nothing performed
        monkeypatch.setattr(core, "table", fake)
        monkeypatch.setattr(tn, "table", fake)
        out = _stage1(fake, health={"checked": True, "degraded": 0, "records_found": 4, "extractor_dark": False})
        row = _pain_row(out)
        assert row["state"] == "unknown", row
        assert row["detail"].startswith("evidence: none — "), row["detail"]
        assert "no movement was performed" in row["detail"]
        assert out["constraint_block"]["days_since_movement"] == {}
        assert any("examined NO movements" in h for h in out["constraint_block"]["honesty"])

    def test_an_unreadable_hevy_partition_is_unknown_not_empty(self, monkeypatch):
        fake = _FakeTable(_rows(), raise_on_pk=HEVY_PK)
        monkeypatch.setattr(core, "table", fake)
        monkeypatch.setattr(tn, "table", fake)
        row = _pain_row(_stage1(fake, health={"checked": True, "degraded": 0, "records_found": 4, "extractor_dark": False}))
        assert row["state"] == "unknown"
        assert row["evidence"]["status"] == "unreadable"
        assert "not empty" in row["detail"]

    def test_the_block_always_states_the_scope_it_examined(self, wired):
        scope = _stage1(wired)["constraint_block"]["pain_evidence"]
        assert scope["status"] == "read" and scope["movements_considered"] == 3
        assert scope["window"] == {"start": "2026-08-25", "end": TODAY, "days": tp.PAIN_LOOKBACK_DAYS}
        assert "pilot" in scope["phases_read"] and "experiment" in scope["phases_read"]

    def test_an_examined_set_with_no_flags_is_the_only_thing_that_earns_clear(self, monkeypatch):
        fake = _FakeTable([copy.deepcopy(_SESSION_0917), copy.deepcopy(_LAT_CLEAN_NOTE)])
        monkeypatch.setattr(core, "table", fake)
        monkeypatch.setattr(tn, "table", fake)
        row = _pain_row(_stage1(fake, health={"checked": True, "degraded": 0, "records_found": 4, "extractor_dark": False}))
        assert row["state"] == "clear"
        assert row["evidence"]["movements_considered"] == 2 and row["evidence"]["movements_flagged"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. a degraded layer still surfaces the deterministic flag
# ══════════════════════════════════════════════════════════════════════════════
class TestTheDegradedLayer:
    def test_the_degraded_flag_reaches_stage_1_with_the_layer_status_beside_it(self, wired):
        """Box 3. The planted instance is the live one: `degraded: true, degraded_reason
        cap_exceeded` — the Haiku monthly cap was reached, so the semantic pass never ran and
        `pain_flag` is the deterministic lexicon hit. It is a positive record either way."""
        row = _pain_row(_stage1(wired))
        assert row["observed"] == [RDL], "a degraded layer erased a flag that is on the record"
        assert row["layer_status"] == "degraded"
        assert "cap_exceeded" in row["evidence"]["note_layer_status"] or row["evidence"]["note_layer_status"] == "degraded"
        assert "degraded" in row["layer_note"] and "#3768" in row["layer_note"]

    def test_even_a_dark_layer_cannot_un_say_a_flag_on_the_record(self):
        """Pure-engine. Pre-#4051 a `dark` status returned `unknown` and dropped the flag
        entirely — the guard erasing its own evidence."""
        rows = plan_engine._tripwire_states(
            protein_days_missed_7d=None,
            readiness_low_streak_days=None,
            anchor_lift_drop_pct=None,
            anchor_lift_drop_sessions=None,
            pain_flag_sites=[RDL],
            pain_flag_instances=[{"movement": RDL, "note_dates": [FLAG_NOTE_DATE]}],
            pain_dismissals=[],
            pain_layer_status="dark",
            pain_evidence_scope={"status": "read", "movements_considered": 3},
            weight_stall_days=None,
            adherence_on_plan=None,
        )
        row = next(r for r in rows if r["id"] == "pain_flag_named_site")
        assert row["state"] == "tripped" and row["observed"] == [RDL]
        assert row["layer_status"] == "dark" and "not evidence of no pain" in row["layer_note"]

    def test_a_dark_layer_with_no_flags_is_still_unknown_not_clear(self):
        """#3768 unchanged: absence under a dark layer proves nothing."""
        rows = plan_engine._tripwire_states(
            protein_days_missed_7d=None,
            readiness_low_streak_days=None,
            anchor_lift_drop_pct=None,
            anchor_lift_drop_sessions=None,
            pain_flag_sites=[],
            pain_flag_instances=[],
            pain_dismissals=[],
            pain_layer_status="dark",
            pain_evidence_scope={"status": "read", "movements_considered": 3},
            weight_stall_days=None,
            adherence_on_plan=None,
        )
        row = next(r for r in rows if r["id"] == "pain_flag_named_site")
        assert row["state"] == "unknown" and "#3768" in row["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. the batch note read
# ══════════════════════════════════════════════════════════════════════════════
class TestTheBatchNoteRead:
    def test_it_returns_the_flag_and_its_dates_per_template(self, wired):
        got = tn.pain_flags_for_templates([RDL_TID, LAT_TID, PRESS_TID], "2026-08-25")
        assert got[RDL_TID] == {"pain_flag_any": True, "pain_dates": [FLAG_NOTE_DATE], "sessions_with_notes": 1}
        assert got[LAT_TID]["pain_flag_any"] is False
        assert got[PRESS_TID] == {"pain_flag_any": False, "pain_dates": [], "sessions_with_notes": 0}

    def test_a_template_whose_read_raises_is_reported_not_folded_into_the_clean_ones(self, monkeypatch):
        fake = _FakeTable(_rows(), raise_on_pk=f"EXERCISE#{LAT_TID}")
        monkeypatch.setattr(tn, "table", fake)
        got = tn.pain_flags_for_templates([RDL_TID, LAT_TID], "2026-08-25")
        assert got[RDL_TID]["pain_flag_any"] is True
        assert "error" in got[LAT_TID] and got[LAT_TID].get("pain_flag_any") is None

    def test_an_unreadable_movement_is_counted_in_the_scope(self, monkeypatch):
        fake = _FakeTable(_rows(), raise_on_pk=f"EXERCISE#{LAT_TID}")
        monkeypatch.setattr(core, "table", fake)
        monkeypatch.setattr(tn, "table", fake)
        scope = tp._gather_performed_evidence(TODAY, "degraded")["scope"]
        assert scope["unreadable_movements"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. mutation control
# ══════════════════════════════════════════════════════════════════════════════
def test_mutation_control_break_the_derivation_and_the_planted_flag_disappears(wired):
    """THE control for this whole file. `_performed_movements` is the derivation #4051 adds;
    neutralising it to the pre-#4051 empty set must make the planted, dismissed flag vanish
    — and if it does not, the green above is coming from the fixtures, not the fix.

    Both halves run here so the assertion cannot rot: intact → `dismissed_by_owner` with the
    flag named; broken → no flag at all and the row falls to `unknown` / `evidence: none`."""
    intact = _pain_row(_stage1(wired))
    assert intact["state"] == "dismissed_by_owner" and intact["observed"] == [RDL]

    with patch("mcp.tools_plan._performed_movements", return_value=([], ["experiment", "pilot"], "2026-08-25", 0)):
        broken = _pain_row(_stage1(wired))
    assert broken["state"] != "dismissed_by_owner", "the flag survived the derivation being removed — it is not coming from the derivation"
    assert broken.get("observed") in (None, []), broken
    assert broken["state"] == "unknown" and broken["detail"].startswith("evidence: none — ")
