"""#953 — scripts/validate_beats.py guards the /wrap build-beat commit.

The validator must (1) pass the live feed, and (2) reject the exact failure
class that hit 2026-07-10: string PRs where the schema wants label/url objects.
"""

import copy
import importlib.util
import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location("validate_beats", os.path.join(_REPO, "scripts", "validate_beats.py"))
validate_beats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_beats)

_GOOD_BEAT = {
    "id": "beat-test",
    "date": "2026-07-11",
    "title": "A test beat",
    "shipped": "x" * 30,
    "why_it_mattered": "w" * 30,
    "gotcha": "y" * 30,
    "honest_miss": "z" * 30,
    "prs": [{"label": "PR #953", "url": "https://github.com/averagejoematt/life-platform/pull/953"}],
}


def test_live_feed_is_valid():
    data = json.load(open(os.path.join(_REPO, "site", "story", "build", "beats.json")))
    assert validate_beats.validate(data) == []


def test_valid_beat_passes():
    assert validate_beats.validate({"beats": [_GOOD_BEAT]}) == []


def test_string_prs_rejected():
    """The 2026-07-10 wiki-session failure: prs as plain strings."""
    bad = copy.deepcopy(_GOOD_BEAT)
    bad["prs"] = ["#923", "#924"]
    errors = validate_beats.validate({"beats": [bad]})
    assert any("prs[0]" in e and "object" in e for e in errors), errors


def test_missing_why_it_mattered_rejected():
    """#1120 — a changelog-grade beat (no why-it-mattered layer) can't ship."""
    bad = copy.deepcopy(_GOOD_BEAT)
    del bad["why_it_mattered"]
    errors = validate_beats.validate({"beats": [bad]})
    assert any("'why_it_mattered'" in e for e in errors), errors


def test_missing_prose_and_bad_url_rejected():
    bad = copy.deepcopy(_GOOD_BEAT)
    bad["gotcha"] = "too short"
    bad["prs"] = [{"label": "PR #1", "url": "https://example.com/1"}]
    errors = validate_beats.validate({"beats": [bad]})
    assert any("'gotcha'" in e for e in errors), errors
    assert any("'url'" in e for e in errors), errors
