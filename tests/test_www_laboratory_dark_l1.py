"""L1 — the Laboratory, built dark (owner brief 2026-11-08: private prototypes from public-safe experiments, hypotheses
and findings; challenge actions stay disabled).

The Python halves of the switch (the build half is www/tests/lab.test.mjs):
  * the producer writes the Lab's data file (lab.json) ONLY with WEB_LAB=1 — off, the snapshot is byte-identical
    (manifest included, bar its clock) to a snapshot without the Lab;
  * the privacy screen: a mood / journal / State-of-Mind / diary / self-reported read is excluded — not its text, not
    its id, not a count — and a test whose spec metric the publication policy does not classify public is excluded;
  * scripts/check_www_build.py's scan — which every deploy runs (`--scan-only`) — refuses a dist that carries Lab
    output, so a Lab build can never be synced. Each with its mutation control.
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
from publish_snapshot_lab import (  # noqa: E402
    ABSENT_LAB,
    SERIES_OF,
    lab_enabled,
    private_read,
    resolve_and_validate,
    shape,
    shape_tests,
)

FIXTURES = os.path.join(REPO, "www", "content", "fixtures")


def _export(tmp_path, name, env_on: bool, monkeypatch):
    monkeypatch.delenv("WEB_ROOM", raising=False)
    if env_on:
        monkeypatch.setenv("WEB_LAB", "1")
    else:
        monkeypatch.delenv("WEB_LAB", raising=False)
    out = tmp_path / name
    manifest = publish_snapshot.run("fixture", str(out), FIXTURES, "https://example.invalid", 5.0)
    return manifest, out


def test_only_the_literal_one_turns_the_lab_on():
    assert lab_enabled({}) is False
    for v in ("", "0", "true", "yes", " 1"):
        assert lab_enabled({"WEB_LAB": v}) is False
    assert lab_enabled({"WEB_ROOM": "1"}) is False  # the Coaching Room's switch is not the Lab's
    assert lab_enabled({"WEB_LAB": "1"}) is True


def test_switch_off_writes_no_lab_file_and_on_writes_it(tmp_path, monkeypatch):
    off_manifest, off = _export(tmp_path, "off", False, monkeypatch)
    assert not (off / "lab.json").exists()
    assert "lab.json" not in off_manifest["files"]
    # the control: the same export with the switch on DOES write it — otherwise the off case proves nothing
    on_manifest, on = _export(tmp_path, "on", True, monkeypatch)
    assert (on / "lab.json").exists()
    assert "lab.json" in on_manifest["files"]
    # every other file is byte-identical between the two exports (the Lab adds, never alters)
    for name in sorted(os.listdir(off)):
        if name in ("manifest.json", "series"):
            continue
        assert (off / name).read_bytes() == (on / name).read_bytes(), name
    off_files = {k: v for k, v in off_manifest["files"].items()}
    on_files = {k: v for k, v in on_manifest["files"].items() if k != "lab.json"}
    assert off_files == on_files


def test_switch_off_over_a_lab_export_removes_the_stale_lab_file(tmp_path, monkeypatch):
    _export(tmp_path, "same", True, monkeypatch)
    _m, out = _export(tmp_path, "same", False, monkeypatch)
    assert not (out / "lab.json").exists()


def test_a_series_id_the_snapshot_does_not_carry_is_nulled(tmp_path, monkeypatch):
    _m, on = _export(tmp_path, "on", True, monkeypatch)
    data = json.loads((on / "lab.json").read_text())
    series = {p[:-5] for p in os.listdir(on / "series")}
    for t in data["lab_tests"]:
        for k in ("outcome_series", "condition_series"):
            assert t[k] is None or t[k] in series
    assert any(t["outcome_series"] == "recovery_score" for t in data["lab_tests"])
    assert set(SERIES_OF.values()) >= {"recovery_score", "total_protein_g"}


def _exp(i, name, hypothesis, status="backlog", **kw):
    return {"id": i, "name": name, "hypothesis": hypothesis, "status": status, "origin": "library", "votes": 7, **kw}


def test_a_private_read_is_excluded_with_no_trace_and_the_operator_is_told():
    logs: list[str] = []
    payload = {
        "experiments": [
            _exp("creatine-strength", "Creatine", "5g daily will raise 1RMs by 8%.", "available"),
            _exp("gratitude-log", "Gratitude log", "Logging gratitudes will improve mood scores."),
            _exp("cold-plunge", "Cold plunge", "Cold exposure will raise HRV and improve subjective mood."),
            _exp("nmn", "NMN", "NMN will improve HRV and subjective energy."),
        ]
    }
    hyps = {
        "hypotheses": [
            {"hypothesis_id": "hyp_ok", "test_spec": {"condition_metric": "protein_g", "outcome_metric": "recovery"}},
            {"hypothesis_id": "hyp_mood", "test_spec": {"condition_metric": "steps", "outcome_metric": "mood"}},
            {"hypothesis_id": "hyp_diary", "test_spec": {"condition_metric": "diary_day", "outcome_metric": "hrv"}},
        ]
    }
    disc = {
        "ai_findings": [
            {"week": "2026-W45", "metric_a": "HRV", "metric_b": "Recovery", "r": 0.6},
            {"week": "2026-W45", "metric_a": "Mood Valence", "metric_b": "Sleep Score", "r": 0.3},
        ]
    }
    supp = {
        "groups": {
            "sleep": {
                "name": "Sleep",
                "items": [
                    {"key": "glycine", "name": "Glycine", "dose": "3g", "timing": "PM", "why": "Core temperature."},
                    {"key": "glutamine", "name": "Glutamine", "measured_by": "GI-comfort notes in the journal."},
                ],
            }
        }
    }
    data = shape(payload, hyps, disc, supp, {"protocols": [], "count": 0}, logs.append)
    text = json.dumps(data)
    for gone in ("gratitude-log", "cold-plunge", "nmn", "hyp_mood", "hyp_diary", "Mood Valence", "glutamine"):
        assert gone not in text, gone
    assert [x["id"] for x in data["lab_experiments"]] == ["creatine-strength"]
    assert [t["id"] for t in data["lab_tests"]] == ["hyp_ok"]
    assert [f["metric_a"] for f in data["lab_findings"]] == ["HRV"]
    assert [i["id"] for i in data["lab_protocols"]["groups"][0]["items"]] == ["glycine"]
    assert '"votes"' not in text  # reader writes stay out
    assert "excluded" not in text  # not even a count
    # the control: the operator's log names every exclusion
    assert sum("lab: excluded" in m for m in logs) == 7
    # a journal citation is a publication, not his journal
    assert private_read("Journal of Applied Physiology, 2019") is None
    assert private_read("notes in the journal") == "journal"


def test_a_test_is_excluded_when_the_policy_cannot_classify_its_metrics():
    excluded: list = []
    rows = {"hypotheses": [{"hypothesis_id": "h", "test_spec": {"condition_metric": "protein_g", "outcome_metric": "recovery"}}]}
    assert shape_tests(rows, excluded, metric_is_public=lambda _m: False) == []  # fail closed
    assert excluded and excluded[0][1] == "h"
    assert [t["id"] for t in shape_tests(rows, [], metric_is_public=lambda _m: True)] == ["h"]


def test_a_library_pitch_is_never_called_a_result():
    data = shape(
        {"experiments": [_exp("x", "X", "Y will move Z.", result_summary="The best thing ever.")]}, None, None, None, None, lambda m: None
    )
    x = data["lab_experiments"][0]
    assert x["pitch"] == "The best thing ever." and x["run"] is None and x["group"] == "backlog"


def test_validation_refuses_a_private_word_and_a_malformed_interval():
    ok = shape({"experiments": [_exp("x", "X", "Y.")]}, None, None, None, None, lambda m: None)
    resolve_and_validate(json.loads(json.dumps(ok)), {"edition": [{"as_of": "2026-11-08"}]}, set())
    bad = json.loads(json.dumps(ok))
    bad["lab_experiments"][0]["hypothesis"] = "Will lift his mood."
    with pytest.raises(ValueError, match="private read"):
        resolve_and_validate(bad, {}, set())
    bad = json.loads(json.dumps(ok))
    bad["lab_tests"] = [{"id": "t", "ci95_low": 2.0, "ci95_high": 1.0}]
    with pytest.raises(ValueError, match="interval"):
        resolve_and_validate(bad, {}, set())
    assert shape(None, None, None, None, None)["state"] == ABSENT_LAB["state"]


def _dist(tmp_path, html: str = "<!doctype html><p>ok</p>"):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text(html)
    return d


def test_the_deploy_scan_refuses_lab_output_and_passes_a_clean_dist(tmp_path):
    assert "/data/lab/" in check_www_build.room_paths(check_www_build.LAB_JS)  # read off www/src/lib/lab.js
    clean = _dist(tmp_path)
    assert check_www_build.lab_leaks(str(clean)) == []
    # the controls: a Lab page, the data file, the marker — each must red the scan the deploy runs
    (clean / "data" / "lab" / "tests" / "x").mkdir(parents=True)
    (clean / "data" / "lab" / "tests" / "x" / "index.html").write_text("<p>lab</p>")
    (clean / "data" / "lab.json").write_text("{}")
    (clean / "data" / "index.html").write_text('<section data-lab="entry"></section>')
    leaks = check_www_build.lab_leaks(str(clean))
    assert any("a Laboratory page" in x for x in leaks)
    assert any("data file" in x for x in leaks)
    assert any("marker" in x for x in leaks)
    # and the full scan carries it
    assert any("Laboratory" in x for x in check_www_build.scan(str(clean), False, forbidden_ids=set()))
