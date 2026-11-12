"""CR2 publishes (owner GO 2026-11-11, second message) — the Python halves of the committed switch at "cr2".

The build half is www/tests/room.test.mjs. Here:
  * the scope: the committed `room_public: "cr2"` (or a private WEB_ROOM=cr2) is CR1 + CR2; CR3 only on WEB_ROOM=1;
  * the producer writes coach_room.json on a CR2 scope WITHOUT any CR3 (docket) part — keys gone, not emptied — and
    with it on the whole room (the control);
  * the deploy scan at "cr2" admits the record pages and the CR2 markers and still refuses every CR3 page, marker and
    docket key, coach_room.json in the dist, and the private-build banner; at "cr1" the same record page is refused.
Each with its mutation control.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)

import check_www_build  # noqa: E402
import publish_snapshot  # noqa: E402
import publish_snapshot_calibration  # noqa: E402
from publish_snapshot_calibration import room_all, room_cr2, room_scope  # noqa: E402

from deploy import www_owned_paths  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")
CR3_KEYS = ("docket_entries", "docket_counts", "docket_disclosure", "docket_positions", '"docket"')


def test_the_committed_switch_is_cr2():
    assert www_owned_paths.load()["room_public"] == "cr2", "CR2 was released by the owner's GO of 2026-11-11 (second message)"
    assert www_owned_paths.room_public({"room_public": "cr2"}) == "cr2"
    assert www_owned_paths.room_public({"room_public": "cr3"}) == "off", "no value publishes CR3"


def test_the_cr2_scope_matrix():
    assert room_scope({}, "cr2") == "cr2" and room_cr2({}, "cr2") and not room_all({}, "cr2")
    assert room_scope({"WEB_ROOM": "cr2"}, "off") == "cr2"
    assert not room_cr2({}, "cr1") and not room_cr2({}, "off"), "a CR1 build carries no CR2"
    assert room_cr2({"WEB_ROOM": "1"}, "off") and room_all({"WEB_ROOM": "1"}, "off")


def _export(tmp_path, name, monkeypatch, env, committed):
    if env is None:
        monkeypatch.delenv("WEB_ROOM", raising=False)
    else:
        monkeypatch.setenv("WEB_ROOM", env)
    monkeypatch.setattr(publish_snapshot_calibration, "committed_room_public", lambda path=None: committed)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


@pytest.mark.parametrize("env,committed", [(None, "cr2"), ("cr2", "off")])
def test_a_cr2_export_writes_coach_room_without_any_cr3_part(tmp_path, monkeypatch, env, committed):
    manifest, out = _export(tmp_path, "cr2", monkeypatch, env, committed)
    assert (out / "calibration.json").exists() and (out / "coach_room.json").exists() and "coach_room.json" in manifest["files"]
    text = (out / "coach_room.json").read_text()
    for k in CR3_KEYS:
        assert (k if k.startswith('"') else f'"{k}"') not in text, k
    room = json.loads(text)
    assert room["coaches"]["eli_marsh"]["approved_words"]["state"] == "ok"
    corrected = [r for r in room["coaches"]["eli_marsh"]["approved_words"]["lead_reads"] if r.get("correction")]
    assert corrected and corrected[0]["correction"]["note"].startswith("Correction added"), "a correction carries through whole"
    # the control: the whole room (WEB_ROOM=1, private) keeps the docket — otherwise the CR2 case proves nothing
    _m, all_out = _export(tmp_path, "all", monkeypatch, "1", committed)
    assert '"docket_entries"' in (all_out / "coach_room.json").read_text()


def test_an_annotated_read_whose_correction_is_malformed_is_dropped():
    import publish_snapshot_coach_room as P

    payload = {
        "coach_id": "eli_marsh",
        "approved_at": "2026-11-09",
        "sealed_calls": [],
        "lead_reads": [
            {
                "date": "2026-10-28",
                "text": "Words.",
                "cited": [],
                "correction": {"kind": "correction", "annotated_at": "2026-11-11", "note": ""},
            },
            {"date": "2026-10-27", "text": "Other words.", "cited": []},
        ],
    }
    out = P._approved_words(payload)
    assert [r["date"] for r in out["lead_reads"]] == ["2026-10-27"], "never the words without their correction"


def _page(d, rel, html):
    (d / rel).mkdir(parents=True, exist_ok=True)
    (d / rel / "index.html").write_text(html)


def _cr2_dist(tmp_path):
    d = tmp_path / "dist"
    _page(d, "system/calibration", '<main data-room="calibration"></main>')
    _page(d, "system/ledger/refuted", '<main data-room="refuted"></main>')
    _page(d, "system", '<section data-room="entry"></section><div data-room="coach-entry"></div>')
    _page(d, "system/coaches/eli_marsh/record", '<main data-room="coach-record"><h1>x</h1></main>')
    _page(d, "system/coaches/eli_marsh", '<section data-room="coach-entry"></section>')
    return d


def test_the_deploy_scan_publishes_cr1_and_cr2(tmp_path):
    d = _cr2_dist(tmp_path)
    assert check_www_build.room_leaks(str(d), published="cr2") == []
    # the control: the same dist under the CR1 switch refuses the record page and the CR2 markers
    cr1 = check_www_build.room_leaks(str(d), published="cr1")
    assert any(x.startswith("system/coaches/eli_marsh/record/: a CR2 Coaching Room page") for x in cr1), cr1
    assert any("data-room='coach-entry'" in x for x in cr1) and any("data-room='coach-record'" in x for x in cr1), cr1


@pytest.mark.parametrize(
    "plant,expect",
    [
        (lambda d: _page(d, "system/docket", "<p>d</p>"), "system/docket/: a CR3 Coaching Room page"),
        (lambda d: _page(d, "system/docket/2026-09-23-a-b", "<p>d</p>"), "system/docket/2026-09-23-a-b/: a CR3 Coaching Room page"),
        (lambda d: (d / "coach_room.json").write_text("{}"), "coach_room.json: the Coaching Room's data file"),
        (
            lambda d: _page(d, "system/ledger/disagreements/x", '<section data-room="disagreement-entry"></section>'),
            "data-room='disagreement-entry'",
        ),
        (
            lambda d: _page(d, "system/coaches/eli_marsh/record", '<div data-room="coach-record" data-room-private="">p</div>'),
            "private-build banner",
        ),
        (
            lambda d: _page(d, "system/calibration", '<div data-x="{&quot;docket_positions&quot;:[]}"></div>'),
            "CR3-only key 'docket_positions'",
        ),
        (lambda d: _page(d, "system/calibration", "<div data-x='{\"docket_entries\":[]}'></div>"), "CR3-only key 'docket_entries'"),
    ],
)
def test_a_cr2_published_scan_still_refuses_cr3_and_private_output(tmp_path, plant, expect):
    d = _cr2_dist(tmp_path)
    assert check_www_build.room_leaks(str(d), published="cr2") == []
    plant(d)
    leaks = check_www_build.room_leaks(str(d), published="cr2")
    assert any(expect in x for x in leaks), (expect, leaks)
