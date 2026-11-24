"""tests/test_public_content_fixes_6224.py — #6224: the targeted public-content corrections hold.

* the Org Chart essay's summary carries no superseded opening: every sentence of it is in the approved body, and the
  obsolete "merges the fix" claim is gone from the summary (the body keeps its own dated history);
* the essay has one canonical address (the v9 page): the legacy permalink names it, the RSS item links it;
* the RSS channel's home is the v9 Story page, not the old-template /story/chronicle/;
* /stack/ lands on a page that exists (/protocols/supplements/), never the never-built /data/stack/;
* /subscribe/ prints no subscriber count and no storage identifier.
"""

# premerge-gate: reads deploy/generated/v4_redirects_function.js (the edge redirect table regenerated from redirects.map)

import html
import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _essay():
    return next(p for p in json.loads(_read("site/journal/blog.json"))["posts"] if p["id"] == "org-chart-of-one")


def test_the_essay_summary_is_the_approved_opening_and_nothing_superseded():
    body = html.unescape(re.sub(r"<[^>]+>", "", _read("site/journal/essays/org-chart-of-one/body.html")))
    excerpt = _essay()["excerpt"]
    assert "merges the fix" not in excerpt and "every morning" not in excerpt
    for sentence in re.split(r"(?<=\.)\s+", excerpt):
        assert sentence.rstrip(".") in body, f"summary sentence not in the approved body: {sentence!r}"


def test_the_essay_has_one_canonical_address():
    import v4_build_journal as J
    import v4_build_rss as R

    post = _essay()
    page = J.render(post)
    assert '<link rel="canonical" href="https://averagejoematt.com/story/essays/org-chart-of-one/">' in page
    assert '"@id": "https://averagejoematt.com/story/essays/org-chart-of-one/"' in page
    assert R.essay_canonical_link(post) == "https://averagejoematt.com/story/essays/org-chart-of-one/"
    assert R.essay_canonical_link({"id": "week-08", "url": "/journal/posts/week-08/"}) is None


def test_the_rss_channel_home_is_the_story_page():
    src = _read("scripts/v4_build_rss.py")
    assert 'CHANNEL_HOME = "/story/"' in src
    assert "{BASE}/story/chronicle/</link>" not in src


def test_stack_redirects_to_a_live_page():
    table = dict(line.split("\t", 1) for line in _read("redirects.map").splitlines() if "\t" in line)
    assert table["/stack/"] == "/protocols/supplements/"
    assert '"/stack/": "/protocols/supplements/"' in _read("deploy/generated/v4_redirects_function.js")
    assert os.path.isfile(os.path.join(_REPO, "site/protocols/supplements/index.html"))


def test_subscribe_prints_no_count_and_no_storage_identifier():
    page = _read("site/subscribe/index.html")
    js = _read("site/assets/js/subscribe_page.js")
    ladder = _read("site/assets/js/engagement_ladder.js")
    assert "/api/sub_count" not in js and "so far." not in js
    assert "p.source" not in ladder and "<code>" not in ladder
    assert '"subscriber"' in ladder and "UNCOUNTED" in ladder
    for text in (page, js, ladder):
        assert not re.search(r"\bddb:|\bs3:generated|USER#matthew", text)
    assert "Anomalies, surfaced" not in page and "every Wednesday" not in page


_QUIET = (
    "A 5.4-mile walk through 50-degree Seattle air, a Tuesday morning weigh-in at 305.4 pounds, and the quiet realization "
    "that the 275-pound Month 2 waypoint is no longer a comfortable abstraction."
)


def _recap_body(beats):
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    from web import site_api_coach_narrative as nar

    item = {"pk": "USER#matthew#SOURCE#chronicle", "sk": "RECAP#latest", "story_so_far": "s", "recent_beats": beats, "as_of": "2026-11-10"}

    class T:
        def get_item(self, Key, **_):
            return {"Item": dict(item)}

    resp = nar.handle_recap(_g={"table": T(), "_current_day_n": lambda: 99, "_regeneration_paused": lambda _f: False})
    return json.loads(resp["body"])["recap"]


def test_the_recap_withholds_the_inferred_feeling_beat_and_keeps_the_rest():
    kept = {"beat": "Day 17 brings 315.0 pounds and a slowing loss rate.", "date": "2026-09-22", "week": 3}
    recap = _recap_body([kept, {"beat": _QUIET, "date": "2026-10-13", "week": 6}])
    assert [b["beat"] for b in recap["recent_beats"]] == [kept["beat"]]
    # an exact-text match only: a regenerated beat with other words is served as written
    other = {"beat": _QUIET.replace("305.4", "305.5"), "date": "2026-10-13", "week": 6}
    assert _recap_body([other])["recent_beats"] == [other]
