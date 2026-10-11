"""#4674 — the repair for the two published surfaces PR #4734's writer fix could not reach.

The fixtures are the wire: the three live objects as served on 2026-10-11 ~06:45Z
(tests/fixtures/published_content_4674/). What is held: the week-2 episode takes the
chapter's title in both the list and the feed; the week-4 excerpt loses the cut clause and
nothing else; every other post, episode and feed line is byte-for-byte unchanged; and a live
object that no longer carries the expected text is refused, never guessed at.
"""

import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "published_content_4674")
SPEC = importlib.util.spec_from_file_location("repair_4674", os.path.join(HERE, "..", "deploy", "repair_published_content_4674.py"))
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh) if name.endswith(".json") else fh.read()


def test_the_week_2_episode_takes_the_chapters_title_and_no_other_episode_moves():
    before = _load("episodes.json")
    after = R.rewrite_episodes(before)
    wk2 = [e for e in after["episodes"] if e["week"] == 2][0]
    assert wk2["title"] == "EP2 · Nine Days and No Rest"
    others = lambda d: [e for e in d["episodes"] if e["week"] != 2]  # noqa: E731
    assert others(after) == others(before)
    assert after["pending"] == before["pending"]
    assert [e for e in before["episodes"] if e["week"] == 2][0]["title"] == "EP2 · Nine Days and Counting", "the fixture is the wire"


def test_the_feed_changes_exactly_one_title_line():
    before = _load("feed.xml")
    after = R.rewrite_feed(before)
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert diff == [("    <title>EP2 · Nine Days and Counting</title>", "    <title>EP2 · Nine Days and No Rest</title>")]
    assert len(before.splitlines()) == len(after.splitlines())


def test_the_week_4_excerpt_loses_the_cut_clause_and_keeps_the_rest():
    before = _load("posts.json")
    after = R.rewrite_posts(before)
    wk4 = [p for p in after["posts"] if p["week"] == 4][0]
    assert "pace flag" not in wk4["excerpt"]
    assert wk4["excerpt"].endswith("He is down 15 pounds total, and the streak is the question that will define the coming week.*…")
    assert wk4["excerpt"].startswith("*He has trained every day for 23 days straight")
    others = lambda d: [p for p in d["posts"] if p["week"] != 4]  # noqa: E731
    assert others(after) == others(before)
    assert {k: v for k, v in wk4.items() if k != "excerpt"} == {
        k: v for k, v in [p for p in before["posts"] if p["week"] == 4][0].items() if k != "excerpt"
    }


def test_an_owner_supplied_excerpt_is_used_but_never_one_with_the_cut_term():
    before = _load("posts.json")
    after = R.rewrite_posts(before, excerpt="Twenty-three days straight.")
    assert [p for p in after["posts"] if p["week"] == 4][0]["excerpt"] == "Twenty-three days straight."
    with pytest.raises(R.Unchanged):
        R.rewrite_posts(before, excerpt="the pace-flag is live")


def test_a_live_object_without_the_expected_text_is_refused():
    posts = _load("posts.json")
    for p in posts["posts"]:
        if p["week"] == 4:
            p["excerpt"] = "Already corrected."
    with pytest.raises(R.Unchanged):
        R.rewrite_posts(posts)
    episodes = _load("episodes.json")
    for e in episodes["episodes"]:
        if e["week"] == 2:
            e["title"] = "EP2 · Nine Days and No Rest"
    with pytest.raises(R.Unchanged):
        R.rewrite_episodes(episodes)
    with pytest.raises(R.Unchanged):
        R.rewrite_feed(_load("feed.xml").replace("Nine Days and Counting", "Nine Days and No Rest"))


def test_the_plan_is_three_objects_with_their_content_types_and_a_readable_diff():
    plan = R.changes(_load("posts.json"), _load("episodes.json"), _load("feed.xml"))
    assert [(k, ct) for k, _o, _n, ct in plan] == [
        ("generated/journal/posts.json", "application/json"),
        ("generated/panelcast/episodes.json", "application/json"),
        ("generated/panelcast/feed.xml", "application/rss+xml"),
    ]
    for key, old, new, _ct in plan:
        assert old != new
        assert "Nine Days and Counting" in R.unified(key, old, new) or "pace flag" in R.unified(key, old, new)
