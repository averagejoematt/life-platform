"""tests/test_chronicle_withdrawn_installment.py — a WITHDRAWN chronicle installment (owner ruling 2026-11-10) never
comes back to the public site: both manifest builders keep it off /journal/posts.json (its URL slot kept, like an
unlisted row), the lead-in page builder never renders its page again, and the v9 producer never makes it a chapter.

The withdrawal is by sort key in content.chronicle_schema.WITHDRAWN_SKS, so the stored row is never edited. Each check
has a mutation control: with the key removed from the set, the installment reappears.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from datetime import datetime, timedelta  # noqa: E402

import publish_snapshot as ps  # noqa: E402
import publish_snapshot_chapters as psc  # noqa: E402
import pytest  # noqa: E402
import restart_leadin_pages as rlp  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402
from content import chronicle_schema  # noqa: E402

_G = chron.EXPERIMENT_START_DATE
WITHDRAWN_SK = "DATE#2026-09-05"


def _d(days):
    return (datetime.strptime(_G, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _inst(title, date, sk, week=0):
    return {
        "title": title,
        "week_number": week,
        "date": date,
        "sk": sk,
        "stats_line": "",
        "word_count": 100,
        "content_markdown": "body",
        "phase": "experiment",
    }


PART_I = _inst("Before the Numbers", _d(-6), f"DATE#{_d(-200)}")
PLAN = _inst("The Plan, On the Record", _d(-1), WITHDRAWN_SK)
WK1 = _inst("Week one", _d(2), f"DATE#{_d(2)}", week=1)
ALL = [PART_I, PLAN, WK1]


class _NoS3:
    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _wednesday_manifest(monkeypatch):
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: False)
    _k, _h, js = chron.publish_to_journal(
        title=WK1["title"], stats_line="", body_html="<p>b</p>", week_num=1, date_str=WK1["date"], all_installments=ALL, write_to_s3=False
    )
    return json.loads(js)["posts"]


def _leadin_run(monkeypatch):
    """The lead-in builder's manifest and the page keys it would write (dry run, no AWS)."""
    captured = {"pages": []}

    class _T:
        def query(self, **kw):
            return {"Items": ALL}

    class _R:
        def Table(self, name):
            return _T()

    monkeypatch.setattr(rlp.boto3, "resource", lambda *a, **k: _R())
    monkeypatch.setattr(rlp.boto3, "client", lambda *a, **k: None)
    real_dumps = rlp.json.dumps
    real_render = rlp.render_post_html

    def spy(obj, *a, **k):
        if isinstance(obj, dict) and "posts" in obj:
            captured["posts"] = obj["posts"]
        return real_dumps(obj, *a, **k)

    def render_spy(title, *a, **k):
        captured["pages"].append(title)
        return real_render(title, *a, **k)

    monkeypatch.setattr(rlp.json, "dumps", spy)
    monkeypatch.setattr(rlp, "render_post_html", render_spy)
    rlp.run(apply=False)
    return captured


def test_the_withdrawn_key_is_the_week_03_installment():
    assert WITHDRAWN_SK in chronicle_schema.WITHDRAWN_SKS
    assert chronicle_schema.is_withdrawn({"sk": WITHDRAWN_SK})
    assert chronicle_schema.off_the_list({"sk": WITHDRAWN_SK})
    assert chronicle_schema.off_the_list({"sk": "DATE#2000-01-01", "unlisted": True})
    assert not chronicle_schema.off_the_list({"sk": "DATE#2000-01-01"})


def test_both_manifests_drop_it_and_keep_every_other_url(monkeypatch):
    lead = _leadin_run(monkeypatch)
    for posts in (_wednesday_manifest(monkeypatch), lead["posts"]):
        titles = [p["title"] for p in posts]
        assert "The Plan, On the Record" not in titles
        urls = {p["title"]: p["url"] for p in posts}
        assert urls["Before the Numbers"] == "/journal/posts/week-01/"
        assert urls["Week one"] == "/journal/posts/week-03/"  # the slot sequence is unchanged (week-02 stays held by the withdrawn row)


def test_the_leadin_builder_never_renders_its_page(monkeypatch):
    pages = _leadin_run(monkeypatch)["pages"]
    assert "The Plan, On the Record" not in pages
    assert "Before the Numbers" in pages  # control: the builder did render pages


def test_mutation_control_unwithdrawn_reappears(monkeypatch):
    monkeypatch.setattr(chronicle_schema, "WITHDRAWN_SKS", frozenset())
    assert "The Plan, On the Record" in [p["title"] for p in _wednesday_manifest(monkeypatch)]
    lead = _leadin_run(monkeypatch)
    assert "The Plan, On the Record" in [p["title"] for p in lead["posts"]]
    assert "The Plan, On the Record" in lead["pages"]


def _ctx(posts):
    ctx = ps.LiveContext("https://example.invalid", {"edition": {"as_of": "2026-11-10"}, "posts": {"posts": posts}})
    return ctx


@pytest.fixture
def _no_body(monkeypatch):
    monkeypatch.setattr(ps, "_chapter_body", lambda ctx, url: None)


def test_the_v9_producer_never_makes_a_withdrawn_url_a_chapter(_no_body):
    posts = [
        {
            "url": "/journal/posts/week-03/",
            "title": "The Plan, On the Record",
            "date": "2026-09-05",
            "week": 0,
            "label": "Prologue · Part II",
        },
        {"url": "/journal/posts/week-02/", "title": "The Night Before Everything", "date": "2026-09-05", "week": 0, "label": "Prologue"},
        {"url": "/journal/posts/week-04/", "title": "76% on Day Two", "date": "2026-09-08", "week": 1, "label": "Week 1"},
    ]
    ctx = _ctx(posts)
    ps._live_chapters(ctx)
    assert [c["id"] for c in ctx.objs["chapter"]] == ["week-04"]


def test_v9_mutation_control_an_unlisted_url_is_a_chapter(_no_body, monkeypatch):
    monkeypatch.setattr(psc, "WITHDRAWN_CHAPTER_URLS", frozenset())
    ctx = _ctx(
        [
            {
                "url": "/journal/posts/week-03/",
                "title": "The Plan, On the Record",
                "date": "2026-09-05",
                "week": 0,
                "label": "Prologue · Part II",
            }
        ]
    )
    ps._live_chapters(ctx)
    assert [c["id"] for c in ctx.objs["chapter"]] == ["week-03"]
