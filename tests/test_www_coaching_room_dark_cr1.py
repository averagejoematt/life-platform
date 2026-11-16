"""CR1 — the Coaching Room, built dark (owner ruling 2026-11-08: NO-GO for publication; private implementation allowed).

Two Python halves of the switch (the build half is www/tests/room.test.mjs):
  * the producer writes the room's data file (calibration.json) ONLY with WEB_ROOM=1 — off, the snapshot is
    byte-identical (manifest included, bar its clock) to a snapshot without the room;
  * scripts/check_www_build.py's scan — which every deploy runs (`--scan-only`) — refuses a dist that carries room
    output, so a room build can never be synced. Each with its mutation control.
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
import publish_snapshot_calibration  # noqa: E402
from publish_snapshot_calibration import ABSENT_CALIBRATION, resolve_and_validate, room_enabled, shape  # noqa: E402

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


@pytest.fixture(autouse=True)
def _committed_switch_off(monkeypatch):
    """These proofs are about the PRIVATE switch (WEB_ROOM): the committed `room_public` is pinned off, so they hold the
    same before and after the CR1 launch merge (tests/test_www_coaching_room_cr1_public.py pins it on)."""
    monkeypatch.setattr(publish_snapshot_calibration, "committed_room_public", lambda path=None: "off")


def _export(tmp_path, name, env_on: bool, monkeypatch):
    if env_on:
        monkeypatch.setenv("WEB_ROOM", "1")
    else:
        monkeypatch.delenv("WEB_ROOM", raising=False)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


def test_only_the_literal_one_turns_the_room_on():
    assert room_enabled({}) is False
    for v in ("", "0", "true", "yes", " 1"):
        assert room_enabled({"WEB_ROOM": v}) is False
    assert room_enabled({"WEB_ROOM": "1"}) is True


def test_switch_off_writes_no_room_file_and_on_writes_it(tmp_path, monkeypatch):
    off_manifest, off = _export(tmp_path, "off", False, monkeypatch)
    assert not (off / "calibration.json").exists()
    assert "calibration.json" not in off_manifest["files"]
    # the control: the same export with the switch on DOES write it — otherwise the off case proves nothing
    on_manifest, on = _export(tmp_path, "on", True, monkeypatch)
    assert (on / "calibration.json").exists()
    assert "calibration.json" in on_manifest["files"]
    # every other file is byte-identical between the two exports (the room adds, never alters)
    for name in sorted(os.listdir(off)):
        if name in ("manifest.json", "series"):
            continue
        assert (off / name).read_bytes() == (on / name).read_bytes(), name


def test_switch_off_over_a_room_export_removes_the_stale_room_file(tmp_path, monkeypatch):
    _export(tmp_path, "same", True, monkeypatch)
    _m, out = _export(tmp_path, "same", False, monkeypatch)
    assert not (out / "calibration.json").exists()


def test_coach_ref_resolves_against_the_public_coaches_and_a_missing_one_is_null(tmp_path, monkeypatch):
    _m, on = _export(tmp_path, "on", True, monkeypatch)
    data = json.loads((on / "calibration.json").read_text())
    refs = {c["coach_id"]: c["coach_ref"] for c in data["calibration"]["coaches"]}
    assert refs["sleep"] == "sleep_coach"
    assert refs["physical"] is None  # not a public Coach in the fixture: no link, no dangling edge


def test_shape_carries_the_served_payload_without_its_clock():
    cal = {
        "_meta": {"generated_at": "x"},
        "as_of": "2026-11-08",
        "coaches": [{"coach_id": "sleep", "n": 1, "confirmed": 0}],
        "platform": {},
    }
    pred = {"overall": {"decided": 199, "confirmed": 82, "accuracy_pct": 41.2, "secret_extra": 1}}
    out = shape(cal, pred)
    assert out["state"] == "ok" and "_meta" not in out["calibration"]
    assert out["record"]["accuracy_pct"] == 41.2 and "secret_extra" not in out["record"]
    assert out["calibration"]["coaches"][0]["persona"] == "sleep_coach"
    assert shape(None, pred)["state"] == "absent" and shape(cal, {})["state"] == ABSENT_CALIBRATION["state"]


def test_a_malformed_room_file_is_refused():
    bad = {"state": "ok", "calibration": {"platform": {"strata": {}}}, "record": {"decided": 1, "confirmed": 1}}
    with pytest.raises(ValueError, match="strata.coaches"):
        resolve_and_validate(bad, {"coach": []})


def _dist(tmp_path, html: str = "<!doctype html><p>ok</p>"):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text(html)
    return d


def test_the_deploy_scan_refuses_room_output_and_passes_a_clean_dist(tmp_path):
    assert check_www_build.room_paths()[0] == "/system/calibration/"  # read off www/src/lib/room.js (CR2 adds the per-coach record)
    clean = _dist(tmp_path)
    assert check_www_build.room_leaks(str(clean), published="off") == []
    # the controls: a room page, the data file, the marker — each must red the scan the deploy runs
    (clean / "system" / "calibration").mkdir(parents=True)
    (clean / "system" / "calibration" / "index.html").write_text("<p>room</p>")
    (clean / "calibration.json").write_text("{}")
    (clean / "system" / "index.html").write_text('<section data-room="entry"></section>')
    leaks = check_www_build.room_leaks(str(clean), published="off")
    assert any("a Coaching Room page" in x for x in leaks)
    assert any("data file" in x for x in leaks)
    assert any("marker" in x for x in leaks)
