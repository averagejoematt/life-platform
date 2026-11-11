"""The split go-live switches (2026-11-09): LAB_LIVE in www/src/lib/lab.js, STORY_LIVE in www/src/lib/story_dark.js.

One committed line each; the Python side (the producer twins, the deploy scan) reads it through
scripts/www_launch_switch.py. A reader that cannot find the line must read DARK (fail closed) — and this test reds when
the committed line is not found exactly once, so a refactor cannot silently change what the deploy believes.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import publish_snapshot_lab  # noqa: E402
import publish_snapshot_story  # noqa: E402
import www_launch_switch as sw  # noqa: E402


def test_each_committed_switch_is_read_exactly():
    assert sw.read_flag(sw.LAB_JS, "LAB_LIVE") in (True, False)
    assert sw.read_flag(sw.STORY_JS, "STORY_LIVE") in (True, False)


def test_the_producer_twins_follow_the_committed_switch():
    assert publish_snapshot_lab.lab_live() is sw.lab_live()
    assert publish_snapshot_story.story_live() is sw.story_live()
    assert publish_snapshot_lab.lab_enabled({}) is sw.lab_live()
    assert publish_snapshot_story.story_enabled({}) is sw.story_live()


def test_unreadable_reads_dark_and_true_reads_live(tmp_path):
    js = tmp_path / "lab.js"
    js.write_text("export const LAB_LIVE = true;\n")
    assert sw.lab_live(str(js)) is True  # the control: a true line IS read as live
    for text in (
        "",
        "export const LAB_LIVE = false;\n",
        "export const LAB_LIVE = true;\nexport const LAB_LIVE = true;\n",  # duplicated: ambiguous
        "export const LAB_LIVE = 1;\n",
        "export let LAB_LIVE = true;\n",
        "// export const LAB_LIVE = true;\n",
    ):
        js.write_text(text)
        assert sw.lab_live(str(js)) is False, text
    assert sw.lab_live(str(tmp_path / "missing.js")) is False


def test_the_deploy_scan_follows_the_switch(tmp_path):
    import check_www_build

    d = tmp_path / "dist"
    (d / "data" / "lab").mkdir(parents=True)
    (d / "data" / "lab" / "index.html").write_text('<main data-lab="index"></main>')
    (d / "story" / "so-far").mkdir(parents=True)
    (d / "story" / "so-far" / "index.html").write_text('<main data-story-dark="timeline"></main>')
    assert check_www_build.lab_leaks(str(d), live=False) and check_www_build.story_leaks(str(d), live=False)  # dark: refused
    assert check_www_build.lab_leaks(str(d), live=True) == [] and check_www_build.story_leaks(str(d), live=True) == []
    (d / "data" / "lab.json").write_text("{}")
    (d / "story.json").write_text("{}")
    assert check_www_build.lab_leaks(str(d), live=True) and check_www_build.story_leaks(str(d), live=True)  # data files never ship
