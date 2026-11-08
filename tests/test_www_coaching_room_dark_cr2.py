"""CR2 — the Coaching Room's coach profiles, built dark (owner ruling 2026-11-08: NO-GO for publication; private
implementation allowed). The Python halves (the build half is www/tests/room.test.mjs + www/tests/coach_room.test.mjs):

  * the producer writes coach_room.json ONLY with WEB_ROOM=1 — off, the snapshot is unchanged;
  * what it carries: served values only, no id that spells out withheld words, no voice sample, no private family;
  * scripts/check_www_build.py's deploy scan refuses a dist carrying a per-coach record page or coach_room.json;
  * the verbatim rule learns the profiles' quotations only from a room snapshot.
Each with its mutation control.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_www_build  # noqa: E402
import publish_snapshot  # noqa: E402
import www_verbatim  # noqa: E402
from publish_snapshot_coach_room import ABSENT_COACH_ROOM, live_coach_room, resolve_and_validate, shape, shape_coach  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


def _export(tmp_path, name, env_on: bool, monkeypatch):
    if env_on:
        monkeypatch.setenv("WEB_ROOM", "1")
    else:
        monkeypatch.delenv("WEB_ROOM", raising=False)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


def test_switch_off_writes_no_coach_room_and_on_writes_it(tmp_path, monkeypatch):
    off_manifest, off = _export(tmp_path, "off", False, monkeypatch)
    assert not (off / "coach_room.json").exists()
    assert "coach_room.json" not in off_manifest["files"]
    on_manifest, on = _export(tmp_path, "on", True, monkeypatch)  # the control
    assert (on / "coach_room.json").exists()
    assert on_manifest["files"]["coach_room.json"]["count"] == 4  # training_coach has no fixture profile: left out, not faked
    for name in sorted(os.listdir(off)):
        if name in ("manifest.json", "series"):
            continue
        assert (off / name).read_bytes() == (on / name).read_bytes(), name


def test_switch_off_over_a_room_export_removes_the_stale_file(tmp_path, monkeypatch):
    _export(tmp_path, "same", True, monkeypatch)
    _m, out = _export(tmp_path, "same", False, monkeypatch)
    assert not (out / "coach_room.json").exists()


def _payload(**over):
    p = {
        "_meta": {"served_at": "2026-11-08T21:31:13+00:00"},
        "persona_id": "nutrition_coach",
        "absent": False,
        "stance": {"source": "stance", "as_of": "2026-11-08", "headline_read": "", "stage": {"label": ""}},
        "stance_history": [{"as_of": "2026-11-01", "headline_read": "", "stage": {}, "how_my_read_changed": ""}],
        "recent_outputs": [
            {"date": "2026-11-02", "summary": "", "generated_at": "2026-11-02T18:02:21+00:00", "data_through": "2026-11-01"}
        ],
        "dossier": {
            "commitments": [
                {
                    "record_id": "COMMITMENT#commit_20261102_restore_protein_intake_to_170_g_daily_fl",
                    "date": "2026-11-02",
                    "text": "",
                    "status": "kept",
                    "due_date": "2026-11-09",
                    "outcome": "kept",
                    "outcome_date": "2026-11-09",
                    "check": {"metric": "total_protein_g", "direction": "up"},
                    "evidence_link": "/data/nutrition/",
                }
            ],
            "commitment_counts": {"held": 54, "kept": 10, "broken": 2, "pending": 4, "unresolved": 38, "ungradeable": 0},
            "docket_positions": [],
        },
        "voice": {
            "few_shot_example": "Sample passage about the last five days of journal entries.",
            "decision_style": {"revision_style": "Reflective."},
        },
        "character": {"voice": {"tone": "Practical", "style": "Builds from what's working."}},
        "latest_checked": {"prediction_id": "pred_20261019_recovery_score_running_average_would_sta", "claim": ""},
        "memoir": {
            "text": "",
            "_publication": {"state": "withheld", "reason": "withheld: this text's sources are not recorded as publishable"},
        },
    }
    p.update(over)
    return p


def test_the_counts_are_carried_and_no_id_that_spells_out_withheld_words_survives():
    e = shape_coach(_payload())
    assert e["asks"]["commitment_counts"] == {"held": 54, "kept": 10, "broken": 2, "pending": 4, "unresolved": 38, "ungradeable": 0}
    text = json.dumps(e)
    assert "restore_protein" not in text and "recovery_score_running" not in text, "an id slug carries the withheld words"
    assert "record_id" not in text and "prediction_id" not in text and "evidence_link" not in text
    assert e["asks"]["rows"][0]["check"] == {"metric": "total_protein_g", "direction": "up"}


def test_the_voice_sample_is_never_carried_and_a_private_family_is_dropped():
    e = shape_coach(_payload())
    assert "few_shot" not in json.dumps(e) and "journal" not in json.dumps(e).lower()
    assert e["voice"]["revision_style"] == "Reflective."
    # the control: a private family in a served string is emptied, in a check it drops the check (the row stays)
    p = _payload()
    p["character"]["voice"]["tone"] = "Reads the journal closely"
    p["dossier"]["commitments"][0]["check"] = {"metric": "journal_entries", "direction": "up"}
    e2 = shape_coach(p)
    assert e2["voice"]["tone"] == ""
    assert e2["asks"]["rows"][0]["check"] is None
    assert len(e2["asks"]["rows"]) == 1


def test_a_withheld_row_keeps_the_apis_own_message_and_nothing_else():
    p = _payload()
    p["stance_history"][0]["unsourced"] = {"text": "Not quoted: no sleep reading on that day."}
    p["recent_outputs"][0]["_publication"] = {
        "state": "withheld",
        "reason": "withheld: this text's sources are not recorded as publishable",
    }
    e = shape_coach(p)
    assert e["stance_history"][0]["withheld_text"] == "Not quoted: no sleep reading on that day."
    assert e["latest_read"]["withheld_text"] == "withheld: this text's sources are not recorded as publishable"
    assert e["latest_read"]["text"] == ""


def test_the_docket_is_filed_under_both_coaches_and_the_fidelity_line_under_its_own():
    docket = {
        "open": [],
        "resolved": [
            {
                "coach_a": "mind_coach",
                "coach_b": "nutrition_coach",
                "claims": {"mind_coach": "", "nutrition_coach": ""},
                "criterion": {"metric": "recovery_score_7day_avg", "condition": "gte", "threshold": 80.0, "description": ""},
                "sides": {"mind_coach": False, "nutrition_coach": True},
                "stakes": {"nutrition_coach": {"brier": 0.25, "brier_n": 4.0}},
                "verdict": {"winner": "nutrition_coach", "outcome": "graded", "actual_value": 87.5},
                "opened_date": "2026-09-23",
                "resolution_date": "2026-10-07",
                "resolved_date": "2026-10-07",
            }
        ],
    }
    fid = {
        "n": 56.0,
        "correct": 35.0,
        "coaches": [{"coach_id": "nutrition_coach", "n": 8.0, "correct": 5.0, "accuracy_pct": 62.5, "distinguishability": "distinct"}],
    }
    out = shape({"nutrition_coach": _payload(), "mind_coach": _payload(persona_id="mind_coach")}, docket, fid)
    assert out["state"] == "ok"
    assert len(out["coaches"]["nutrition_coach"]["docket"]) == 1 and len(out["coaches"]["mind_coach"]["docket"]) == 1
    assert out["coaches"]["nutrition_coach"]["fidelity"]["correct"] == 5.0
    assert out["coaches"]["mind_coach"]["fidelity"] is None
    assert shape({}, docket, fid)["state"] == ABSENT_COACH_ROOM["state"]


def test_live_fetch_leaves_a_failing_coach_out_and_never_partial():
    def get(path):
        if path == "/api/coach/mind_coach":
            raise TimeoutError("slow")
        if path.startswith("/api/coach/"):
            return _payload(persona_id=path.rsplit("/", 1)[1])
        return None

    out = live_coach_room(get, ["mind_coach", "nutrition_coach"], log=lambda *_: None)
    assert list(out["coaches"]) == ["nutrition_coach"]


def test_resolve_keeps_public_coaches_only_and_refuses_a_private_string():
    out = shape({"nutrition_coach": _payload()}, None, None)
    assert resolve_and_validate(json.loads(json.dumps(out)), {"coach": []})["coaches"] == {}
    bad = json.loads(json.dumps(out))
    bad["coaches"]["nutrition_coach"]["stance"]["headline_read"] = "He has not opened the journal."
    with pytest.raises(ValueError, match="private family"):
        resolve_and_validate(bad, {"coach": [{"id": "nutrition_coach"}]})


def test_the_deploy_scan_refuses_a_record_page_and_the_data_file(tmp_path):
    assert "/system/coaches/[id]/record/" in check_www_build.room_paths()
    assert check_www_build.room_data_files() == ["calibration.json", "coach_room.json"]
    d = tmp_path / "dist"
    (d / "system" / "coaches" / "sleep_coach").mkdir(parents=True)
    (d / "system" / "coaches" / "sleep_coach" / "index.html").write_text("<p>coach</p>")
    assert check_www_build.room_leaks(str(d)) == []  # a coach page is not a room page
    # the controls
    (d / "system" / "coaches" / "sleep_coach" / "record").mkdir()
    (d / "system" / "coaches" / "sleep_coach" / "record" / "index.html").write_text("<p>room</p>")
    (d / "coach_room.json").write_text("{}")
    leaks = check_www_build.room_leaks(str(d))
    assert any(x.startswith("system/coaches/sleep_coach/record/: a Coaching Room page") for x in leaks), leaks
    assert any(x.startswith("coach_room.json: the Coaching Room's data file") for x in leaks), leaks


def test_the_verbatim_set_learns_profile_quotes_only_from_a_room_snapshot(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    base = www_verbatim.verbatim_strings(str(snap))
    room = {"coaches": {"sleep_coach": {"latest_read": {"text": "Sleep held at seven hours."}, "stance_history": [], "asks": {"rows": []}}}}
    (snap / "coach_room.json").write_text(json.dumps(room))
    assert www_verbatim._norm("Sleep held at seven hours.") in www_verbatim.verbatim_strings(str(snap))
    assert www_verbatim._norm("Sleep held at seven hours.") not in base  # the control: no room file, no exemption
