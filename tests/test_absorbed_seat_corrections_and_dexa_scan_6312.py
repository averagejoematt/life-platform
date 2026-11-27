"""test_absorbed_seat_corrections_and_dexa_scan_6312.py — two things the Performance coach was
never told (#6312, epic #6284, refs #6149).

1. A correction logged to the retired "training" seat reaches the coach that absorbed it
   (physical) on the brief, the Telegram chat block and the session packet. The absorption
   map is ONE registry (`persona_registry.ABSORBED_BY`); stored rows are never rewritten.
2. The brief's physical block reads the DEXA scan where it is STORED (`body_composition.*`)
   and carries the scan's date and age. The fixture is the stored shape, attribute for
   attribute (names re-read from the live rows 2026-11-26; values synthetic).

Mutations that red each test are named in its docstring. Offline; clock-free (the age is
measured to the brief's own `date`).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from ai import ai_calls, ai_context  # noqa: E402
from coach import coach_corrections as cc, persona_registry  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402


@pytest.fixture(autouse=True)
def _no_ssm(monkeypatch):
    monkeypatch.setattr(cc, "read_cycle", lambda *a, **k: None)


def _table():
    return FakeDdbTable(rows=[], query_hook=lambda t, **_kw: {"Items": list(t.store.values())})


def _write(table, item_ref, text, *, cid, date="2026-11-01"):
    return cc.write_correction(
        table, item_ref, text, "other", now=datetime.fromisoformat(f"{date}T18:00:00+00:00").astimezone(timezone.utc), correction_id=cid
    )


def _seeded():
    t = _table()
    _write(t, {"surface": "chat_coaching", "coach": "training", "signal": "s1"}, "TRAINING-CHAT: synthetic", cid="ffff0001")
    _write(t, {"surface": "coach_brief", "coach": "training_coach"}, "TRAINING-BRIEF: synthetic", cid="ffff0002")
    _write(t, {"surface": "chat_coaching", "coach": "physical", "signal": "s2"}, "PHYSICAL-CHAT: synthetic", cid="ffff0003")
    _write(t, {"surface": "chat_coaching", "coach": "sleep", "signal": "s3"}, "SLEEP-CHAT: synthetic", cid="ffff0004")
    _write(t, {"surface": "chat_coaching", "coach": "mind", "signal": "s4"}, "MIND-CHAT: synthetic", cid="ffff0005")
    return t


# ── 1. the absorbed seat ──────────────────────────────────────────────────────────────
def test_the_absorption_registry_is_one_map_over_the_retired_seats():
    """Mutation: retire a seat without recording who absorbed it, or point it at a non-operational coach."""
    assert set(persona_registry.ABSORBED_BY) == set(persona_registry.RETIRED_COACH_IDS)
    assert set(persona_registry.ABSORBED_BY.values()) <= set(persona_registry.OPERATIONAL_COACH_IDS)
    personas = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "personas.json")))["personas"]
    for old, new in persona_registry.ABSORBED_BY.items():
        assert personas[new]["name"] in personas[old]["retirement_note"], "the prose twin must name the absorbing seat"


def test_absorbing_coach_id_keeps_the_callers_id_form():
    f = persona_registry.absorbing_coach_id
    assert f("training") == "physical" and f("training_coach") == "physical_coach" and f(" Training ") == "physical"
    assert f("mind") == "mind" and f("sleep_coach") == "sleep_coach" and f(None) is None


def test_brief_block_for_the_physical_coach_carries_training_corrections():
    """Mutation: compare through `normalize_coach_id` alone — both TRAINING rows vanish."""
    block = ai_calls._coach_corrections_block("physical_coach", table=_seeded())
    assert "TRAINING-CHAT" in block and "TRAINING-BRIEF" in block and "PHYSICAL-CHAT" in block
    assert "SLEEP-CHAT" not in block and "MIND-CHAT" not in block


def test_chat_block_for_the_performance_coach_carries_training_corrections():
    block = cc.chat_corrections_block(_seeded(), "physical")
    assert "TRAINING-CHAT" in block and "TRAINING-BRIEF" in block and "PHYSICAL-CHAT" in block
    assert "SLEEP-CHAT" not in block


def test_session_packet_still_sees_training_and_now_physical_rows(monkeypatch):
    import mcp.config
    from mcp import tools_coach_packet as pkt

    monkeypatch.setattr(mcp.config, "table", _seeded())
    value, status = pkt._open_corrections("2026-11-26")
    texts = {v["correction_text"] for v in value}
    assert status["state"] == "measured"
    assert {"TRAINING-CHAT: synthetic", "TRAINING-BRIEF: synthetic", "PHYSICAL-CHAT: synthetic"} <= texts
    assert "SLEEP-CHAT: synthetic" not in texts


def test_training_corrections_reach_no_unrelated_coach_and_active_coaches_are_unaffected():
    t = _seeded()
    for other in ("sleep_coach", "mind_coach", "nutrition_coach", "labs_coach"):
        block = ai_calls._coach_corrections_block(other, table=t)
        assert "TRAINING" not in block and "PHYSICAL" not in block, other
    sleep = cc.open_corrections_for(t, coach="sleep_coach", surfaces=cc.OWNER_FACING_SURFACES)
    assert [r["correction_text"] for r in sleep] == ["SLEEP-CHAT: synthetic"]


def test_the_per_coach_bound_holds_when_training_and_physical_rows_merge():
    t = _table()
    for i in range(cc.PROMPT_MEMORY_MAX_PER_COACH + 3):
        coach = "training" if i % 2 else "physical"
        _write(t, {"surface": "chat_coaching", "coach": coach, "n": i}, f"ROW-{i:02d}", cid=f"abab{i:04d}", date=f"2026-10-{i + 10:02d}")
    rows = cc.open_corrections_for(t, coach="physical_coach", surfaces=cc.OWNER_FACING_SURFACES)
    assert len(rows) == cc.PROMPT_MEMORY_MAX_PER_COACH
    assert rows[0]["correction_text"] == f"ROW-{cc.PROMPT_MEMORY_MAX_PER_COACH + 2:02d}"
    assert cc.chat_corrections_block(t, "physical").count("\n- [") == cc.PROMPT_MEMORY_MAX_PER_COACH


# ── 2. the DEXA scan ──────────────────────────────────────────────────────────────────
def _stored_dexa_row(scan_date="2026-03-30"):
    """The STORED shape: `body_composition.*` leaves + `scan_date`, no top-level body_fat_pct.
    Top-level attribute names re-read from the live rows 2026-11-26; numbers are synthetic."""
    return {
        "pk": "USER#matthew#SOURCE#dexa",
        "sk": f"DATE#{scan_date}",
        "scan_date": scan_date,
        "scan_type": "dexa",
        "provider": "synthetic_provider",
        "body_composition": {
            "ag_ratio": 1.1,
            "android_fat_pct": 40.0,
            "body_fat_pct": 33.3,
            "bone_mineral_content_lb": 7.7,
            "fat_mass_lb": 99.9,
            "gynoid_fat_pct": 36.0,
            "lean_mass_lb": 188.8,
            "total_mass_lb": 300.0,
            "visceral_fat_g": 1000.0,
            "visceral_fat_lb": 2.2,
        },
        "body_score": {"numeric": 50},
        "bone": {"t_score": 1.0},
    }


def test_the_physical_block_reads_the_scan_where_it_is_stored_and_dates_it():
    """Mutation: read the leaves off the top level again — all three go null and the date is lost."""
    built = ai_context._build_physical_data({"dexa": _stored_dexa_row(), "date": "2026-11-25"})
    assert (built["body_fat_pct"], built["lean_mass_lb"], built["visceral_fat_lb"]) == (33.3, 188.8, 2.2)
    assert built["dexa_scan_date"] == "2026-03-30" and built["dexa_scan_age_days"] == 240
    note = built["dexa_scan_note"]
    assert "2026-03-30" in note and "240 days" in note and "historical" in note and "not today" in note


def test_an_old_scan_reads_as_old_and_a_new_one_as_recent():
    old = ai_context._build_physical_data({"dexa": _stored_dexa_row("2025-05-10"), "date": "2026-11-25"})
    new = ai_context._build_physical_data({"dexa": _stored_dexa_row("2026-11-20"), "date": "2026-11-25"})
    assert old["dexa_scan_age_days"] == 564 and new["dexa_scan_age_days"] == 5


def test_no_scan_on_file_is_stated_as_absence():
    built = ai_context._build_physical_data({"dexa": None, "date": "2026-11-25"})
    assert built["body_fat_pct"] is None and built["dexa_scan_date"] is None
    assert "No DEXA scan on file" in built["dexa_scan_note"]


def test_an_unparseable_scan_date_does_not_raise():
    row = _stored_dexa_row("not-a-date")
    built = ai_context._build_physical_data({"dexa": row, "date": "2026-11-25"})
    assert built["body_fat_pct"] == 33.3 and built["dexa_scan_age_days"] is None and "could not be computed" in built["dexa_scan_note"]


def test_the_note_never_reads_the_withheld_inferred_label_fields():
    """The scan block touches body_composition + scan_date only (guard: test_inferred_psych_fields_guard_6286)."""
    import inspect

    from intelligence import brief_domain_inputs

    src = inspect.getsource(brief_domain_inputs.dexa_block)
    assert "interpretations" not in src and "score_360" not in src
