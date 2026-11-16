"""CR1 launches ahead of CR2/CR3 (owner ruling 2026-11-09) — the Python halves of the split switch.

The build half is www/tests/room.test.mjs. Here:
  * the scope: WEB_ROOM=1 → the whole room, WEB_ROOM=cr1 → CR1 only, else the committed `room_public` in
    www/owned_paths.json ("off" | "cr1"); anything else is off (fail closed);
  * the producer writes calibration.json for any CR1 scope and coach_room.json ONLY for the whole room — a CR1 build,
    private or published, carries no CR2/CR3 data;
  * the deploy scan with the committed switch at "cr1" admits the CR1 pages and markers and still refuses every CR2/CR3
    page, coach_room.json, CR2/CR3 marker and key, and any private-build banner; at "off" it refuses CR1 too.
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
from publish_snapshot_calibration import committed_room_public, room_all, room_enabled, room_scope  # noqa: E402

from deploy import www_owned_paths  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


def test_the_scope_matrix():
    for committed in ("off", "cr1"):
        assert room_scope({"WEB_ROOM": "1"}, committed) == "all"
        assert room_scope({"WEB_ROOM": "cr1"}, committed) == "cr1"
    assert room_scope({}, "off") == "off"
    assert room_scope({}, "cr1") == "cr1"  # the committed launch switch
    for v in ("", "0", "true", "yes", " 1", "CR1", "CR2", "cr3", "all"):
        assert room_scope({"WEB_ROOM": v}, "off") == "off", v
    assert room_scope({}, "CR1") == "off" and room_scope({}, "on") == "off", "only the literal 'cr1' publishes"
    assert room_all({"WEB_ROOM": "1"}, "off") and not room_all({"WEB_ROOM": "cr1"}, "off") and not room_all({}, "cr1")
    assert room_enabled({}, "cr1") and not room_enabled({}, "off")


def test_the_committed_switch_reads_fail_closed(tmp_path):
    for body, want in (({"room_public": "cr1"}, "cr1"), ({"room_public": "off"}, "off"), ({"room_public": True}, "off"), ({}, "off")):
        f = tmp_path / "o.json"
        f.write_text(json.dumps(body))
        assert committed_room_public(str(f)) == want, body
        assert www_owned_paths.room_public(body) == want, body
    (tmp_path / "bad.json").write_text("{not json")
    assert committed_room_public(str(tmp_path / "bad.json")) == "off"
    assert committed_room_public(str(tmp_path / "missing.json")) == "off"
    assert www_owned_paths.load().get("room_public") in www_owned_paths.ROOM_PUBLIC_VALUES, "the committed file carries a valid switch"


def _export(tmp_path, name, monkeypatch, env: str | None, committed: str):
    if env is None:
        monkeypatch.delenv("WEB_ROOM", raising=False)
    else:
        monkeypatch.setenv("WEB_ROOM", env)
    monkeypatch.setattr(publish_snapshot_calibration, "committed_room_public", lambda path=None: committed)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


@pytest.mark.parametrize("env,committed", [("cr1", "off"), (None, "cr1")])
def test_a_cr1_export_writes_calibration_and_never_coach_room(tmp_path, monkeypatch, env, committed):
    manifest, out = _export(tmp_path, "cr1", monkeypatch, env, committed)
    assert (out / "calibration.json").exists() and "calibration.json" in manifest["files"]
    assert not (out / "coach_room.json").exists() and "coach_room.json" not in manifest["files"]
    for name in os.listdir(out):
        if os.path.isfile(out / name):
            text = (out / name).read_text()
            for k in ("docket_entries", "stance_history", "commitment_counts", "voice_fidelity"):
                assert f'"{k}"' not in text, (name, k)
    # the control: the whole room (WEB_ROOM=1) does write it — otherwise the CR1 case proves nothing
    _m, all_out = _export(tmp_path, "all", monkeypatch, "1", committed)
    assert (all_out / "coach_room.json").exists()


def test_the_cr1_export_carries_the_verification_summary_as_served(tmp_path, monkeypatch):
    _m, out = _export(tmp_path, "cr1", monkeypatch, "cr1", "off")
    vs = json.loads((out / "calibration.json").read_text())["calibration"]["verification_summary"]
    assert sum(r["n"] for r in vs["excluded_by_category"]) == vs["excluded_total"]
    assert vs["eligible_total"] == vs["excluded_total"] + vs["verified"]["n"]


def _page(d, rel, html):
    (d / rel).mkdir(parents=True, exist_ok=True)
    (d / rel / "index.html").write_text(html)


def test_the_deploy_scan_publishes_cr1_only(tmp_path):
    d = tmp_path / "dist"
    _page(d, "system/calibration", '<main data-room="calibration"><h1>x</h1></main>')
    _page(d, "system/ledger/refuted", '<main data-room="refuted"></main>')
    _page(d, "system", '<section data-room="entry"></section>')
    assert check_www_build.room_leaks(str(d), published="cr1") == []
    # the control: the same CR1 dist with the switch off is refused, page by page and marker by marker
    off = check_www_build.room_leaks(str(d), published="off")
    assert any(x.startswith("system/calibration/: a Coaching Room page") for x in off), off
    assert any(x.startswith("system/ledger/refuted/: a Coaching Room page") for x in off), off
    assert any("data-room='entry'" in x for x in off), off


@pytest.mark.parametrize(
    "plant,expect",
    [
        (
            lambda d: _page(d, "system/coaches/sleep_coach/record", "<p>r</p>"),
            "system/coaches/sleep_coach/record/: a CR2 Coaching Room page",
        ),
        (lambda d: _page(d, "system/docket", "<p>d</p>"), "system/docket/: a CR3 Coaching Room page"),
        (lambda d: _page(d, "system/docket/2026-09-23-a-b", "<p>d</p>"), "system/docket/2026-09-23-a-b/: a CR3 Coaching Room page"),
        (lambda d: (d / "coach_room.json").write_text("{}"), "coach_room.json: the Coaching Room's data file"),
        (lambda d: _page(d, "system/coaches/sleep_coach", '<section data-room="coach-entry"></section>'), "data-room='coach-entry'"),
        (
            lambda d: _page(d, "system/ledger/disagreements/x", '<section data-room="disagreement-entry"></section>'),
            "data-room='disagreement-entry'",
        ),
        (
            lambda d: _page(d, "system/calibration", '<div data-room="calibration" data-room-private="">private</div>'),
            "private-build banner",
        ),
        (
            lambda d: _page(d, "system/calibration", '<div data-payload="{&quot;stance_history&quot;:[]}"></div>'),
            "CR2/CR3-only key 'stance_history'",
        ),
        (lambda d: _page(d, "system/calibration", "<div data-x='{\"docket_entries\":[]}'></div>"), "CR2/CR3-only key 'docket_entries'"),
    ],
)
def test_a_cr1_published_scan_still_refuses_cr2_cr3_and_private_output(tmp_path, plant, expect):
    d = tmp_path / "dist"
    _page(d, "system/calibration", '<main data-room="calibration"></main>')
    assert check_www_build.room_leaks(str(d), published="cr1") == []
    plant(d)
    leaks = check_www_build.room_leaks(str(d), published="cr1")
    assert any(expect in x for x in leaks), (expect, leaks)


def test_the_owned_paths_check_refuses_an_invalid_switch(tmp_path, monkeypatch):
    good = www_owned_paths.load()
    for bad in ("on", True, None, "cr3", "all"):
        data = {**good, "room_public": bad}
        monkeypatch.setattr(www_owned_paths, "load", lambda path=None, data=data: data)
        issues = check_www_build.check_owned_paths({}, str(tmp_path))
        assert any("room_public must be one of" in i for i in issues), (bad, issues)
    data = {**good, "room_public": "cr1"}
    monkeypatch.setattr(www_owned_paths, "load", lambda path=None, data=data: data)
    assert not any("room_public" in i for i in check_www_build.check_owned_paths({}, str(tmp_path)))
