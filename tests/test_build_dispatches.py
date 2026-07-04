"""#380 — the Build log: engineering exhaust distilled into public beats.

Pins the contract: the feed is valid and complete (every beat carries the
three-part format), every published string passes the privacy gate the rest of
the platform uses, and the Story app actually has the section wired.
"""

import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

BEATS_PATH = os.path.join(_REPO, "site/story/build/beats.json")
DISPATCHES_JS = open(os.path.join(_REPO, "site/assets/js/dispatches.js")).read()


def _beats():
    return json.load(open(BEATS_PATH))


def test_feed_shape_and_three_part_format():
    data = _beats()
    assert isinstance(data.get("beats"), list)
    for b in data["beats"]:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", b["date"]), b
        assert b.get("id") and b.get("title")
        # The format IS the honesty: shipped + gotcha + honest miss, all present.
        for key in ("shipped", "gotcha", "honest_miss"):
            assert b.get(key) and len(b[key]) > 20, f"beat {b['id']} missing {key}"


def test_beat_receipts_point_at_the_repo():
    for b in _beats()["beats"]:
        for pr in b.get("prs", []):
            assert pr["url"].startswith("https://github.com/averagejoematt/life-platform/pull/"), pr


def test_beats_pass_the_privacy_gate():
    """Same fail-closed bar as every other published surface (#354/ADR-104)."""
    import privacy_guard

    for b in _beats()["beats"]:
        for key in ("title", "shipped", "gotcha", "honest_miss"):
            privacy_guard.assert_clean(b.get(key, ""), context=f"{b['id']}.{key}")


def test_story_app_has_the_build_section():
    assert '"/story/build/beats.json"' in DISPATCHES_JS
    assert "the honest miss" in DISPATCHES_JS
    assert "merged" in DISPATCHES_JS  # the merged-work-only framing is user-visible


def test_section_shell_emitted():
    assert os.path.exists(os.path.join(_REPO, "site/story/build/index.html"))
    build_script = open(os.path.join(_REPO, "scripts/v4_build_dispatches.py")).read()
    assert '"build"' in build_script or "('build'" in build_script or '("build"' in build_script


def test_checklist_carries_the_honesty_rules():
    doc = open(os.path.join(_REPO, "docs/content/BUILD_DISPATCH_CHECKLIST.md")).read()
    assert "Merged + deployed only" in doc
    assert "content_policy_scan" in doc
    assert "honest_miss" in doc
