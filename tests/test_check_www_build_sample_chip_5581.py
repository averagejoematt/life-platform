"""#5581 — the fixture-only "Sample content" chip is a defect on a LIVE build (scripts/check_www_build.scan)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import check_www_build as cwb  # noqa: E402


def _build(tmp_path, mode):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(f"<html><body><footer>{cwb.SAMPLE_CHIP}</footer></body></html>")
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "manifest.json").write_text(json.dumps({"mode": mode}))
    return str(dist), str(snap)


def test_live_build_with_chip_is_an_issue(tmp_path):
    dist, snap = _build(tmp_path, "live")
    issues = cwb.scan(dist, require_noindex=False, forbidden_ids=set(), snapshot_dir=snap)
    assert any("LIVE build" in i for i in issues)


def test_fixture_build_with_chip_is_clean(tmp_path):
    dist, snap = _build(tmp_path, "fixture")
    assert cwb.scan(dist, require_noindex=False, forbidden_ids=set(), snapshot_dir=snap) == []
