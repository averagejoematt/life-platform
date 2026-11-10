"""CR2's two public-safe sources in the room's data file (owner ruling 2026-11-09, third, D + E) — the producer half.

scripts/publish_snapshot_coach_room.py fetches, per public coach, ``/api/coach_room_words?coach=<id>`` (the approved
historical words) and ``/api/coach_brief?coach=<id>`` (the public-safe brief) and carries them as served:
  * a 404 or any failure is an ABSENCE (``state: "absent"``), never an empty list presented as "none";
  * every carried string passes the private-family belt, and a private-family string never reaches the file;
  * the brief's first cycle is read off ``common/public_brief_policy.py`` (no hand-typed date on the page);
  * nothing is fetched for a coach whose profile failed (that coach is left out whole).
The build half is www/tests/coach_room_cr2_sources.test.mjs; the route is tests/test_coach_room_words_cr2.py.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

import publish_snapshot_coach_room as P  # noqa: E402

WORDS = {
    "coach_id": "sleep_coach",
    "approved_at": "2026-11-09",
    "sealed_calls": [
        {
            "prediction_id": "pred_a",
            "claim": "Sample sealed call one.",
            "logged_date": "2026-09-06",
            "status": "confirmed",
            "metric": "weight_lbs",
        },
        {"prediction_id": "pred_b", "claim": "Sample call that mentions the journal.", "logged_date": "2026-09-06", "status": "refuted"},
    ],
    "lead_reads": [],
}
BRIEF = {
    "coach_id": "sleep_coach",
    "briefs": [
        {
            "cycle": "2026-11-16",
            "cycle_end": "2026-11-22",
            "data_through": "2026-11-15",
            "generated_at": "2026-11-16T14:05:00+00:00",
            "observations": [
                {
                    "id": "o1",
                    "metric": "hrv",
                    "label": "HRV",
                    "unit": "ms",
                    "last7": {"mean": 52, "n": 7},
                    "latest": {"date": "2026-11-15", "value": 55},
                }
            ],
            "interpretations": [
                {"id": "i1", "text": "Sample reading.", "cites": ["o1"]},
                {"id": "i2", "text": "Sample about mood.", "cites": ["o1"]},
            ],
            "predictions": [
                {
                    "id": "p1",
                    "prediction_id": "x",
                    "claim": "HRV will rise over the next 14 days.",
                    "confidence": 0.6,
                    "ledger": {"status": "pending"},
                }
            ],
            "evaluation_criteria": [{"prediction": "p1", "type": "directional", "rule_sentence": "Graded on the first and last readings."}],
            "recommendations": [{"id": "r1", "text": "Sample recommendation.", "rationale": "Sample why."}],
            "owner_actions": [{"recommendation_id": "r1", "state": "pending"}],
            "revisions": [],
        }
    ],
}


def _profile(pid):
    return {"persona_id": pid, "_meta": {"served_at": "2026-11-17T00:00:00Z"}}


def _getter(responses):
    calls = []

    def get(path):
        calls.append(path)
        if path in responses:
            return responses[path]
        raise urllib.error.HTTPError(path, 404, "Not Found", None, None)

    return get, calls


def test_dark_routes_are_recorded_as_absent_never_as_none():
    get, calls = _getter({"/api/coach/sleep_coach": _profile("sleep_coach")})
    room = P.live_coach_room(get, ["sleep_coach"], log=lambda m: None)
    c = room["coaches"]["sleep_coach"]
    assert c["approved_words"] == {"state": "absent", "sealed_calls": [], "lead_reads": []}
    assert c["public_briefs"]["state"] == "absent" and c["public_briefs"]["briefs"] == []
    assert c["public_briefs"]["first_cycle"] == "2026-11-16"
    assert "/api/coach_room_words?coach=sleep_coach" in calls and "/api/coach_brief?coach=sleep_coach" in calls


def test_served_sources_are_carried_with_the_private_family_belt():
    get, _ = _getter(
        {
            "/api/coach/sleep_coach": _profile("sleep_coach"),
            "/api/coach_room_words?coach=sleep_coach": WORDS,
            "/api/coach_brief?coach=sleep_coach": BRIEF,
        }
    )
    room = P.live_coach_room(get, ["sleep_coach"], log=lambda m: None)
    c = room["coaches"]["sleep_coach"]
    w = c["approved_words"]
    assert w["state"] == "ok" and w["approved_at"] == "2026-11-09"
    assert [x["claim"] for x in w["sealed_calls"]] == ["Sample sealed call one."], "a private-family string is dropped, not shown"
    b = c["public_briefs"]
    assert b["state"] == "ok" and len(b["briefs"]) == 1
    br = b["briefs"][0]
    assert [i["text"] for i in br["interpretations"]] == ["Sample reading."]
    assert br["predictions"][0]["status"] == "pending" and "prediction_id" not in br["predictions"][0]
    assert br["owner_actions"][0]["state"] == "pending"
    blob = json.dumps(room)
    assert "journal" not in blob and "mood" not in blob
    # the whole file still passes the producer's own validation (no private family anywhere)
    P.resolve_and_validate(room, {"coach": [{"id": "sleep_coach"}]})


def test_a_coach_whose_profile_failed_is_left_out_and_its_sources_are_not_fetched():
    get, calls = _getter({"/api/coach_room_words?coach=sleep_coach": WORDS})
    room = P.live_coach_room(get, ["sleep_coach"], log=lambda m: None)
    assert room["state"] == "absent"
    assert calls[0] == "/api/coach/sleep_coach" and not any("coach_room_words" in p for p in calls)


def test_the_first_cycle_is_read_off_the_policy_and_unreadable_is_none(tmp_path):
    from common import public_brief_policy as POL

    assert P.first_brief_cycle() == POL.FIRST_CYCLE
    assert P.first_brief_cycle(str(tmp_path / "missing.py")) is None


def test_a_malformed_payload_is_absent():
    assert P._approved_words({"sealed_calls": "x"})["state"] == "absent"
    assert P._approved_words(None)["state"] == "absent"
    assert P._public_briefs({"briefs": None}, "2026-11-16")["state"] == "absent"
