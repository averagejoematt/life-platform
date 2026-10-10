"""tests/test_story_door_pace_flag_4674.py — #4674: "pace flag" is a cut term the story door refuses, and a week's
chapter and Panel episode carry ONE title."""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from content import story_checks  # noqa: E402
from emails import panelcast_desk  # noqa: E402


def _cut_terms():
    with open(os.path.join(_REPO, "site", "data", "glossary.json"), encoding="utf-8") as f:
        g = json.load(f)
    entries = g if isinstance(g, list) else next(v for v in g.values() if isinstance(v, list) and v and isinstance(v[0], dict))
    return {e["term"] for e in entries if e.get("ruling") == "cut"}


def test_pace_flag_is_cut_in_the_registry_and_the_story_door_copy_is_inside_it():
    assert "pace flag" in _cut_terms()
    assert set(story_checks._CUT_TERMS) <= _cut_terms()


def test_story_door_rejects_pace_flag_and_passes_plain_prose():
    bad = "By Thursday the pace flag is live, and the week reads differently."
    assert any("pace flag" in f for f in story_checks.story_door(bad))
    assert any("Pace_Flag" in f for f in story_checks.story_door("The Pace_Flag turned on."))
    assert story_checks.story_door("By Thursday he was on pace, and the week read differently.") == []


def test_the_episode_carries_the_chapters_title():
    post = {"title": "Nine Days and No Rest"}
    ep = {"title": "Nine Days and Counting"}
    assert panelcast_desk.episode_title(post, ep) == "Nine Days and No Rest"
    assert panelcast_desk.episode_title({}, ep) == "Nine Days and Counting"  # fallback only when the chapter has none
