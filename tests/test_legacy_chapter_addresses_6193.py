"""tests/test_legacy_chapter_addresses_6193.py — a chapter's legacy address follows its served edition (#6193, §4).

Owner ruling 2026-11-22 (final edition rehearsal §4): once a corrected edition is public, ``/journal/posts/<page>/``
redirects to ``/story/<id>/``; feed guids stay; no loop, no wrong week; retired/held/withdrawn chapters follow their
visibility; the original is kept privately; no other legacy path keeps the first edition. Synthetic fixtures and
in-memory fakes only — nothing here reaches AWS or the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content import (
    chapter_editions as CE,  # noqa: E402
    legacy_chapter_addresses as LA,  # noqa: E402
)

SUMMARY = "Synthetic edition summary, for a test only."


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    """The suite starts every test with the switch off (tests/conftest.py); these run with the committed value, on."""
    monkeypatch.setattr(CE, "LIVE", True)


def _chapter(cid, url, status="published", title="A week"):
    return {"id": cid, "status": status, "url_legacy": url, "title": title}


# A page id is not a chapter number: this synthetic chapter week-06 lives at page week-09 (as program week 1 lives at
# week-04 on the real site). The mapping must come from url_legacy alone.
CHAPTERS = [
    _chapter("week-06", "/journal/posts/week-09/"),
    _chapter("week-04", "/journal/posts/week-04/"),
    _chapter("program-week-08", None, status="retired"),
    _chapter("program-week-07", None, status="skipped"),
    _chapter("week-11", None, status="held"),
]


def _ed(cid, n=2, summary=SUMMARY):
    return {"chapter_id": cid, "edition": n, "summary": summary}


def _plan(editions, chapters=CHAPTERS):
    return LA.plan(editions, chapters)


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_no_served_edition_or_the_switch_off_plans_nothing(monkeypatch):
    assert _plan([]) == {"chapters": [], "refused": []}
    monkeypatch.setattr(CE, "LIVE", False)
    assert _plan([_ed("week-06")]) == {"chapters": [], "refused": []}


def test_the_legacy_address_is_the_chapters_own_url_never_week_arithmetic():
    (x,) = _plan([_ed("week-06")])["chapters"]
    assert x["legacy_path"] == "/journal/posts/week-09/"
    assert x["legacy_key"] == "generated/journal/posts/week-09/index.html"
    assert x["share_kit_key"] == "generated/moments/share-kits/week-09/kit.json"
    assert x["story_path"] == "/story/week-06/" and x["story_url"] == "https://averagejoematt.com/story/week-06/"


def test_retired_held_skipped_and_unknown_chapters_are_never_planned():
    p = _plan([_ed("program-week-08"), _ed("week-11"), _ed("week-99"), _ed("not-an-id")])
    assert p["chapters"] == []
    assert {cid for cid, _ in p["refused"]} == {"program-week-08", "week-11", "week-99", "not-an-id"}


def test_two_chapters_claiming_one_page_are_both_refused():
    chapters = CHAPTERS + [_chapter("week-05", "/journal/posts/week-09/")]
    p = _plan([_ed("week-06"), _ed("week-05")], chapters)
    assert p["chapters"] == [] and len(p["refused"]) == 2


def test_a_chapter_without_a_journal_permalink_is_refused():
    p = _plan([_ed("week-04")], [_chapter("week-04", "/story/week-04/")])
    assert p["chapters"] == [] and "no journal permalink" in p["refused"][0][1]


# ── the redirect document ───────────────────────────────────────────────────────────────────────────────────────────────
def test_the_redirect_document_names_only_the_canonical_chapter():
    (x,) = _plan([_ed("week-06")])["chapters"]
    page = LA.redirect_page(x)
    assert '<link rel="canonical" href="https://averagejoematt.com/story/week-06/">' in page
    assert '<meta property="og:url" content="https://averagejoematt.com/story/week-06/">' in page
    assert '<meta http-equiv="refresh" content="0; url=/story/week-06/">' in page
    assert '<meta name="robots" content="noindex">' in page
    assert SUMMARY not in page and "og:description" not in page and "/journal/" not in page
    assert len(page.encode()) <= LA.MAX_REDIRECT_BYTES
    assert LA.redirect_target(page.encode()) == "/story/week-06/"


def test_a_first_edition_page_is_never_mistaken_for_the_redirect():
    big = b"<html>" + b"x" * LA.MAX_REDIRECT_BYTES + b'<meta name="lp-legacy-chapter-redirect" content="/story/week-06/"></html>'
    assert LA.redirect_target(big) is None
    assert LA.redirect_target(b"<html><title>A week</title></html>") is None
    assert LA.redirect_target(b'<meta name="lp-legacy-chapter-redirect" content="/journal/posts/week-09/">') is None
    assert LA.redirect_target(None) is None


def test_a_redirect_to_anything_but_a_story_page_is_refused():
    (x,) = _plan([_ed("week-06")])["chapters"]
    for bad in ({**x, "story_path": "/journal/posts/week-09/"}, {**x, "story_url": "https://example.com/story/week-06/"}):
        with pytest.raises(LA.PlanError):
            LA.redirect_page(bad)


def test_no_redirect_loop_with_the_edge_function():
    """The edge function 301s exact URIs in its table first; neither side of the redirect may be in it."""
    src = open(os.path.join(_REPO, "deploy", "generated", "v4_redirects_function.js"), encoding="utf-8").read()
    table = json.loads(re.search(r"var R = (\{.*?\});\nfunction handler", src, re.DOTALL).group(1))
    assert not [k for k in table if re.match(r"^/(story|journal/posts)/week-\d+/?$", k)]
    assert not [v for v in table.values() if re.match(r"^/journal/posts/week-\d+/?$", str(v))]


# ── posts.json and the share kit ────────────────────────────────────────────────────────────────────────────────────────
POSTS = {
    "posts": [
        {"url": "/journal/posts/week-09/", "title": "A week", "excerpt": "First-edition excerpt.", "week": 6},
        {"url": "/journal/posts/week-04/", "title": "Another", "excerpt": "Untouched excerpt.", "week": 1},
    ],
    "updated_at": "2026-11-01T00:00:00Z",
}


def test_the_manifest_takes_the_edition_summary_and_nothing_else_moves():
    entries = _plan([_ed("week-06")])["chapters"]
    doc, changed = LA.manifest_update(POSTS, entries, {}, "2026-11-23T00:00:00Z")
    assert changed == ["/journal/posts/week-09/"]
    a, b = doc["posts"]
    assert a == {**POSTS["posts"][0], "excerpt": SUMMARY, "edition": 2}
    assert b == POSTS["posts"][1]
    assert doc["updated_at"] == "2026-11-23T00:00:00Z"
    assert LA.manifest_update(doc, entries, {}, "later") == (doc, [])  # idempotent


def test_a_withdrawn_edition_gets_its_original_excerpt_back_and_a_missing_original_refuses():
    marked, _ = LA.manifest_update(POSTS, _plan([_ed("week-06")])["chapters"], {}, "t1")
    back, changed = LA.manifest_update(marked, [], {"/journal/posts/week-09/": "First-edition excerpt."}, "t2")
    assert changed == ["/journal/posts/week-09/"] and back["posts"][0] == POSTS["posts"][0]
    with pytest.raises(LA.PlanError):
        LA.manifest_update(marked, [], {}, "t2")


def test_a_served_chapter_outside_this_run_is_kept_exactly():
    marked, _ = LA.manifest_update(POSTS, _plan([_ed("week-06")])["chapters"], {}, "t1")
    assert LA.manifest_update(marked, [], {}, "t2", keep={"/journal/posts/week-09/"}) == (marked, [])


def test_the_share_kit_takes_the_summary_and_the_canonical_chapter():
    (x,) = _plan([_ed("week-06")])["chapters"]
    kit = {"title": "A week", "excerpt": "First-edition excerpt.", "canonical_url": "https://averagejoematt.com/journal/posts/week-09/"}
    assert LA.share_kit_update(kit, x) == {"title": "A week", "excerpt": SUMMARY, "canonical_url": x["story_url"]}


# ── rule G (scripts/check_public_copies.py) ─────────────────────────────────────────────────────────────────────────────
def _clean_store(x):
    posts, _ = LA.manifest_update(POSTS, [x], {}, "t")
    kit = LA.share_kit_update({"excerpt": "old", "canonical_url": "old"}, x)
    return {x["legacy_key"]: LA.redirect_page(x).encode(), x["share_kit_key"]: json.dumps(kit).encode()}, posts


def test_rule_g_is_clean_once_every_copy_follows_the_edition():
    (x,) = _plan([_ed("week-06")])["chapters"]
    store, posts = _clean_store(x)
    archive = {"web/journal/posts/week-09/index.html": store[x["legacy_key"]]}
    assert LA.copy_issues([x], store.get, posts, archive) == []


def test_rule_g_names_each_copy_that_still_carries_the_first_edition():
    """One planted first edition per copy (the page, posts.json, the share kit, the archive): each is named exactly
    once, by key, and no message carries a word of the page (the CI log is public)."""
    (x,) = _plan([_ed("week-06")])["chapters"]
    wrong = []
    for what in ("page", "posts", "kit", "archive"):
        store, posts = _clean_store(x)
        archive = {"web/journal/posts/week-09/index.html": store[x["legacy_key"]]}
        if what == "page":
            store[x["legacy_key"]] = b"<html><title>A week</title>" + b"planted prose " * 400 + b"</html>"
        elif what == "posts":
            posts = POSTS
        elif what == "kit":
            store[x["share_kit_key"]] = json.dumps({"excerpt": "First-edition excerpt."}).encode()
        else:
            archive["web/journal/posts/week-09/index.html"] = b"<html>planted prose</html>"
        issues = LA.copy_issues([x], store.get, posts, archive)
        if len(issues) != 1 or issues[0][1] != "G" or "planted" in issues[0][2] or "First-edition excerpt" in issues[0][2]:
            wrong.append((what, issues))
    assert wrong == []


def test_rule_g_waits_for_an_archive_built_before_the_redirect():
    (x,) = _plan([_ed("week-06")])["chapters"]
    store, posts = _clean_store(x)
    archive = {"web/journal/posts/week-09/index.html": b"<html>first edition</html>"}
    written = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    early, late = datetime(2026, 11, 23, 1, tzinfo=timezone.utc), datetime(2026, 11, 24, 1, tzinfo=timezone.utc)
    assert LA.copy_issues([x], store.get, posts, archive, early, {x["legacy_key"]: written}) == []
    assert len(LA.copy_issues([x], store.get, posts, archive, late, {x["legacy_key"]: written})) == 1


def test_rule_g_in_the_guard_reads_the_snapshot_and_is_silent_without_an_edition(tmp_path):
    import check_public_copies as G

    (tmp_path / "chapters.json").write_text(json.dumps(CHAPTERS))
    listing = [{"Key": "generated/journal/posts/week-09/index.html", "LastModified": datetime(2026, 11, 23, tzinfo=timezone.utc)}]
    first = {"generated/journal/posts/week-09/index.html": b"<html>" + b"first edition " * 300 + b"</html>"}
    facts = {"counts": {}}
    assert G.legacy_chapter_issues(str(tmp_path), listing, first.get, None, facts) == [] and facts["counts"]["chapters"] == 0
    (tmp_path / "chapter_editions.json").write_text(json.dumps({"state": "ok", "source": [], "editions": [_ed("week-06")]}))
    issues = G.legacy_chapter_issues(str(tmp_path), listing, first.get, None, facts)
    assert [i[1] for i in issues] == ["G"] and facts["counts"]["chapters"] == 1


# ── the attended writer (scripts/legacy_chapter_redirects.py) over fakes ────────────────────────────────────────────────
class _Body(io.BytesIO):
    def read(self, *a):
        return super().read(*a)


class FakeS3:
    def __init__(self, objects):
        self.objects = {k: {"Body": v, "meta": {}} for k, v in objects.items()}
        self.puts = []

    def get_object(self, Bucket, Key, VersionId=None):
        if Key not in self.objects:
            raise KeyError(f"NoSuchKey {Key}")
        return {"Body": _Body(self.objects[Key]["Body"])}

    def head_object(self, Bucket, Key):
        return dict(self.objects[Key]["meta"])

    def put_object(self, Bucket, Key, Body, ContentType, IfNoneMatch=None, **extra):
        if IfNoneMatch == "*" and Key in self.objects:
            raise RuntimeError("PreconditionFailed")
        self.objects[Key] = {"Body": Body, "meta": {k: v for k, v in extra.items() if k == "WebsiteRedirectLocation"}}
        self.puts.append((Key, IfNoneMatch, extra.get("WebsiteRedirectLocation")))

    def get_paginator(self, _name):
        store = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(store.objects) if k.startswith(Prefix)]}

        return _P()


class FakeTable:
    def __init__(self, items):
        self.items = items

    def get_item(self, Key, ConsistentRead=False):
        return {"Item": self.items[Key["sk"]]} if Key["sk"] in self.items else {}


FIRST = b"<html><title>A week - The Measured Life</title>" + b"first edition prose " * 200 + b"</html>"


def _records(cid="week-06", page="week-09", body=FIRST, backed_up=True):
    key = f"generated/journal/posts/{page}/index.html"
    bkey = f"backups/chronicle-editions/{cid}/20261122T000000Z/s3/{key}"
    pointer = {
        "sk": CE.sk_original(cid),
        "objects": [{"source": f"s3:{key}", "backup_key": bkey, "sha256": hashlib.sha256(body).hexdigest()}],
    }
    items = {CE.sk_original(cid): pointer, CE.sk_restore(cid): {"sk": CE.sk_restore(cid)}} if backed_up else {}
    return items, ({bkey: body} if backed_up else {})


def _world(page_body=FIRST, **kw):
    items, backups = _records(**kw)
    kit = json.dumps({"excerpt": "First-edition excerpt.", "canonical_url": "https://averagejoematt.com/journal/posts/week-09/"}).encode()
    s3 = FakeS3({"generated/journal/posts/week-09/index.html": page_body, "generated/moments/share-kits/week-09/kit.json": kit, **backups})
    s3.objects[LA.POSTS_KEY] = {"Body": json.dumps(POSTS).encode(), "meta": {}}
    return s3, FakeTable(items)


def test_the_writer_refuses_without_the_first_edition_backup_and_restore_rehearsal():
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    s3, table = _world(backed_up=False)
    with pytest.raises(R.Refused, match="not proven kept"):
        R.chapter_steps(x, s3, table, "S")


def test_the_writer_refuses_when_the_backup_names_another_page():
    """Two records must agree on the page: the snapshot's url_legacy and the backup pointer's journal page."""
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    items, backups = _records(page="week-06")
    s3, _ = _world()
    with pytest.raises(R.Refused, match="disagree"):
        R.chapter_steps(x, s3, FakeTable(items), "S")


def test_the_writer_backs_up_then_replaces_reads_back_and_sets_the_redirect():
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    s3, table = _world()
    steps = R.chapter_steps(x, s3, table, "S") + R.manifest_steps([x], s3, "S", "2026-11-23T00:00:00Z")
    kinds = [s["kind"] for s in steps]
    assert kinds.count("page") == 1 and kinds.count("kit") == 1 and kinds.count("manifest") == 1
    assert kinds.count("backup") == 2  # the kit and posts.json as they stood; the page is already in the edition backup
    paths = R.apply(steps, s3, log=lambda m: None)
    first_public = next(i for i, p in enumerate(s3.puts) if p[1] is None)
    assert all(p[1] == "*" for p in s3.puts[:first_public]) and all(p[0].startswith(LA.BACKUP_ROOT) for p in s3.puts[:first_public])
    assert LA.redirect_target(s3.objects[x["legacy_key"]]["Body"]) == "/story/week-06/"
    assert s3.objects[x["legacy_key"]]["meta"]["WebsiteRedirectLocation"] == "/story/week-06/"
    assert json.loads(s3.objects[LA.POSTS_KEY]["Body"])["posts"][0]["excerpt"] == SUMMARY
    assert paths == ["/journal/posts.json", "/journal/posts/week-09/*", "/moments/share-kits/week-09/kit.json"]
    assert LA.copy_issues([x], lambda k: s3.objects.get(k, {}).get("Body"), json.loads(s3.objects[LA.POSTS_KEY]["Body"])) == []
    # a second run has nothing to do
    assert R.chapter_steps(x, s3, table, "S2") == [] and R.manifest_steps([x], s3, "S2", "t") == []


def test_a_page_changed_since_the_edition_backup_is_kept_again_first():
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    s3, table = _world()
    s3.objects[x["legacy_key"]]["Body"] = FIRST + b"<!-- rewritten later -->"
    steps = R.chapter_steps(x, s3, table, "S")
    assert [s["kind"] for s in steps][:2] == ["backup", "page"] and steps[0]["key"].endswith("/s3/" + x["legacy_key"])


def test_a_withdrawn_edition_restores_the_excerpt_and_kit_and_keeps_the_redirect():
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    s3, table = _world()
    original_kit = s3.objects[x["share_kit_key"]]["Body"]
    R.apply(R.chapter_steps(x, s3, table, "S1") + R.manifest_steps([x], s3, "S1", "t1"), s3, log=lambda m: None)
    steps = R.manifest_steps([], s3, "S2", "t2")  # the edition is no longer served
    R.apply(steps, s3, log=lambda m: None)
    assert json.loads(s3.objects[LA.POSTS_KEY]["Body"]) == {**POSTS, "updated_at": "t2"}
    assert s3.objects[x["share_kit_key"]]["Body"] == original_kit
    assert LA.redirect_target(s3.objects[x["legacy_key"]]["Body"]) == "/story/week-06/"  # still the governed page


def test_a_failed_read_back_stops_the_run():
    import legacy_chapter_redirects as R

    (x,) = _plan([_ed("week-06")])["chapters"]
    s3, table = _world()
    steps = R.chapter_steps(x, s3, table, "S")
    real = s3.put_object

    def lossy(**kw):
        real(**{**kw, "Body": kw["Body"][:-1]})

    s3.put_object = lossy
    with pytest.raises(R.Unverified):
        R.apply(steps, s3, log=lambda m: None)


# ── the feed (scripts/v4_build_rss.py) ──────────────────────────────────────────────────────────────────────────────────
def test_feed_links_follow_the_producers_url_to_id_rule():
    import v4_build_rss

    urls = ["/journal/posts/week-04/", "/journal/posts/week-09/", "/journal/posts/week-03/", "/journal/essays/x/"]
    assert v4_build_rss.edition_links_by_url({"editions": [{"chapter_id": "week-04"}, {"chapter_id": "week-03"}]}, urls) == {
        "/journal/posts/week-04/": "https://averagejoematt.com/story/week-04/"
    }  # week-03 is a withdrawn installment (publish_snapshot_chapters.WITHDRAWN_CHAPTER_URLS): never a chapter
    assert v4_build_rss.edition_links_by_url({"weeks": []}, urls) == {}
    assert v4_build_rss.edition_links_by_url({"editions": []}, urls) == {}
