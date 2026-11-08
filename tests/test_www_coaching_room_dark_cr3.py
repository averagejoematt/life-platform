"""CR3 — the Coaching Room's disagreements and docket, built dark (owner ruling 2026-11-08: NO-GO for publication; private
implementation allowed). The Python halves (the build half is www/tests/room.test.mjs + www/tests/docket.test.mjs):

  * the producer files every /api/coach_docket entry once, under a room id built from its open day and two seats —
    never from the topic slug, which spells out words the API may withhold;
  * it carries the API's OWN withheld messages (a side's `unsourced.text` / `absent.reason`, a concession's
    `concession_unsourced.text`) and nothing in their place; a private family is still dropped;
  * resolve keeps an entry only when both seats are public coaches;
  * the deploy scan refuses a docket page or the refuted preset; the verbatim rule learns a served concession only
    from a room snapshot.
Each with its mutation control.
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_www_build  # noqa: E402
import publish_snapshot  # noqa: E402
import www_verbatim  # noqa: E402
from publish_snapshot_coach_room import docket_id, resolve_and_validate, shape  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")
HELD = "Not quoted: this was said on September 23 and rests on his glucose sensor, which had sent no reading since August 27."


def _coach(pid: str) -> dict:
    return {"persona_id": pid, "dossier": {}, "stance_history": []}


def _docket() -> dict:
    """The live /api/coach_docket shape of 2026-11-08 (claims, topic and description blanked by the server's gates)."""
    return {
        "open": [],
        "resolved": [
            {
                "topic": "",
                "topic_slug": "glucose_protein_recovery_spike",
                "coach_a": "glucose_coach",
                "coach_b": "nutrition_coach",
                "claims": {"nutrition_coach": ""},
                "criterion": {"condition": "lt", "threshold": 70.0, "description": "", "metric": "recovery_score"},
                "sides": {"glucose_coach": False, "nutrition_coach": True},
                "resolution_date": "2026-09-30",
                "opened_date": "2026-09-23",
                "stakes": {"glucose_coach": {"brier_n": 3.0, "brier": 0.25}, "nutrition_coach": {"brier": 0.25, "brier_n": 10.0}},
                "unsourced": {"glucose_coach": {"reason": "no sensor since 2026-08-27", "said_on": "2026-09-23", "text": HELD}},
                "verdict": {
                    "outcome": "graded",
                    "loser": "glucose_coach",
                    "holds": True,
                    "winner": "nutrition_coach",
                    "actual_value": 59.0,
                },
                "winner": "nutrition_coach",
                "loser": "glucose_coach",
                "actual_value": 59.0,
                "resolved_date": "2026-09-30",
                "concession": None,
                "concession_unsourced": {"reason": "no sensor since 2026-08-27", "text": HELD},
            }
        ],
        "counts": {"open": 0, "resolved": 1},
        "disclosure": "Standing disagreements between AI coaches, each with skin in the game.",
    }


def test_each_entry_is_filed_once_with_a_seat_id_and_the_apis_own_withheld_messages():
    out = shape({"glucose_coach": _coach("glucose_coach"), "nutrition_coach": _coach("nutrition_coach")}, _docket(), None)
    [e] = out["docket_entries"]
    assert e["id"] == "2026-09-23-glucose-coach-nutrition-coach"
    assert "spike" not in json.dumps(out), "the topic slug is never carried — it spells out withheld words"
    assert e["withheld"] == {"glucose_coach": HELD}
    assert e["concession_withheld"] == HELD and e["concession"] == ""
    assert e["loser"] == "glucose_coach" and e["holds"] is True and e["winner"] == "nutrition_coach"
    assert out["docket_counts"] == {"open": 0, "resolved": 1}
    assert out["docket_disclosure"].startswith("Standing disagreements")
    # the same entry is still filed under both coaches (CR2's per-coach section reads it there, now with its id)
    assert [d["id"] for d in out["coaches"]["glucose_coach"]["docket"]] == [e["id"]]
    # the control: no `unsourced` / `concession_unsourced` → no message is invented
    bare = _docket()
    del bare["resolved"][0]["unsourced"], bare["resolved"][0]["concession_unsourced"]
    [b] = shape({"glucose_coach": _coach("glucose_coach")}, bare, None)["docket_entries"]
    assert b["withheld"] == {} and b["concession_withheld"] is None


def test_an_open_items_dark_seat_carries_the_apis_absent_reason_and_a_private_family_is_dropped():
    d = _docket()
    item = dict(d["resolved"][0], absent={"glucose_coach": {"reason": "no CGM reading since 27 August"}})
    del item["unsourced"]
    d = {"open": [item], "resolved": []}
    [e] = shape({"glucose_coach": _coach("glucose_coach")}, d, None)["docket_entries"]
    assert e["status"] == "open" and e["withheld"] == {"glucose_coach": "no CGM reading since 27 August"}
    # the control: a held message that names a private family is not carried
    item["absent"] = {"glucose_coach": {"reason": "rests on the journal"}}
    [e2] = shape({"glucose_coach": _coach("glucose_coach")}, {"open": [item]}, None)["docket_entries"]
    assert e2["withheld"] == {}


def test_ids_stay_unique_and_word_free():
    assert (
        docket_id({"opened_date": "2026-09-23", "coach_a": "Mind_Coach", "coach_b": "sleep coach"}) == "2026-09-23-mind-coach-sleep-coach"
    )
    d = _docket()
    twin = dict(d["resolved"][0], resolution_date="2026-10-07")
    d["resolved"].append(twin)
    ids = [e["id"] for e in shape({"glucose_coach": _coach("glucose_coach")}, d, None)["docket_entries"]]
    assert len(set(ids)) == 2 and ids[1] == "2026-09-23-glucose-coach-nutrition-coach-20261007"


def test_resolve_keeps_an_entry_only_when_both_seats_are_public():
    out = shape({"glucose_coach": _coach("glucose_coach"), "nutrition_coach": _coach("nutrition_coach")}, _docket(), None)
    both = resolve_and_validate(json.loads(json.dumps(out)), {"coach": [{"id": "glucose_coach"}, {"id": "nutrition_coach"}]})
    assert len(both["docket_entries"]) == 1
    one = resolve_and_validate(json.loads(json.dumps(out)), {"coach": [{"id": "nutrition_coach"}]})  # the control
    assert one["docket_entries"] == []


def test_the_fixture_room_export_carries_the_docket_and_the_flag_off_export_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_ROOM", "1")
    publish_snapshot.run("fixture", str(tmp_path / "on"), FIXTURES, "https://example.invalid", 5.0)
    room = json.loads((tmp_path / "on" / "coach_room.json").read_text())
    assert len(room["docket_entries"]) == 4
    monkeypatch.delenv("WEB_ROOM")
    publish_snapshot.run("fixture", str(tmp_path / "off"), FIXTURES, "https://example.invalid", 5.0)
    assert not (tmp_path / "off" / "coach_room.json").exists()
    for name in os.listdir(tmp_path / "off"):
        if os.path.isfile(tmp_path / "off" / name) and name != "manifest.json":
            assert "docket_entries" not in (tmp_path / "off" / name).read_text(), name


def test_the_deploy_scan_refuses_a_docket_page_and_the_refuted_preset(tmp_path):
    paths = check_www_build.room_paths()
    for p in ("/system/docket/", "/system/docket/[id]/", "/system/ledger/refuted/"):
        assert p in paths
    d = tmp_path / "dist"
    (d / "system" / "ledger" / "sleep-20261005-deepsleep01").mkdir(parents=True)
    (d / "system" / "ledger" / "sleep-20261005-deepsleep01" / "index.html").write_text("<p>call</p>")
    (d / "system" / "ledger" / "disagreements" / "x").mkdir(parents=True)
    (d / "system" / "ledger" / "disagreements" / "x" / "index.html").write_text("<p>disagreement</p>")
    assert check_www_build.room_leaks(str(d)) == []  # a ledger page and a disagreement page are not room pages
    for rel in ("system/docket/2026-09-23-a-b", "system/ledger/refuted"):  # the controls
        (d / rel).mkdir(parents=True)
        (d / rel / "index.html").write_text("<p>room</p>")
    leaks = check_www_build.room_leaks(str(d))
    assert any(x.startswith("system/docket/: a Coaching Room page") for x in leaks), leaks
    assert any(x.startswith("system/docket/2026-09-23-a-b/: a Coaching Room page") for x in leaks), leaks
    assert any(x.startswith("system/ledger/refuted/: a Coaching Room page") for x in leaks), leaks


def test_the_verbatim_set_learns_a_concession_only_from_a_room_snapshot(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    base = www_verbatim.verbatim_strings(str(snap))
    said = "Sample concession words."
    room = {"coaches": {}, "docket_entries": [{"claims": {"a": "Side words."}, "concession": said}]}
    (snap / "coach_room.json").write_text(json.dumps(room))
    got = www_verbatim.verbatim_strings(str(snap))
    assert www_verbatim._norm(said) in got and www_verbatim._norm("Side words.") in got
    assert www_verbatim._norm(said) not in base  # the control: no room file, no exemption
