"""tests/test_post_social.py — #1622: unit coverage for scripts/post_social.py.

Two things worth locking down without any real network call:
  1. Candidate matching — an RSS `<item>` is matched to the moments-index
     `chronicles` dict by its un-tagged path, and `chronicle_share_kit.build_kit`
     produces a caption carrying the title, the link, and the excerpt. An RSS item
     whose path is NOT in the moments-index `chronicles` allowlist must never
     become a candidate (the structural content allowlist, per #1622's brief).
  2. `strip_links()` — the #1631 forward-compat helper — must strip every
     http(s):// URL, including one embedded mid-sentence (the "reply-shaped
     string" case: a link surrounded by other prose, not just a bare URL alone).

All network access is mocked (`post_social._get` is monkeypatched); nothing here
touches a real socket, AWS, or the keychain.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
import post_social  # noqa: E402

MOMENTS_INDEX_JSON = """
{"generated_at": "2026-08-02T19:30:11+00:00", "chronicles": {
  "/journal/posts/week-02/": "/moments/assets/chronicle-week-02.png"
}}
"""

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>The Night Before Everything</title>
    <link>https://averagejoematt.com/journal/posts/week-02/?utm_source=rss&amp;utm_medium=feed</link>
    <guid isPermaLink="true">https://averagejoematt.com/journal/posts/week-02/</guid>
    <description>The habit tracker logged a 2 out of 100 on the eve of an earlier launch, the night this piece was written and its numbers are kept verbatim.</description>
    <pubDate>Sun, 26 Jul 2026 12:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Not In The Allowlist</title>
    <link>https://averagejoematt.com/journal/posts/week-99/</link>
    <guid isPermaLink="true">https://averagejoematt.com/journal/posts/week-99/</guid>
    <description>This chronicle path is not a key in the moments-index chronicles dict, so it must never surface as a postable candidate.</description>
    <pubDate>Sun, 26 Jul 2026 12:00:00 +0000</pubDate>
  </item>
</channel></rss>
"""


def _fake_get(monkeypatch):
    def fake(url, timeout=10):
        if url == post_social.MOMENTS_INDEX_URL:
            return MOMENTS_INDEX_JSON
        if url == post_social.RSS_URL:
            return RSS_XML
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(post_social, "_get", fake)


def test_list_candidates_matches_allowlisted_rss_item_only(monkeypatch):
    _fake_get(monkeypatch)

    candidates = post_social.list_candidates()

    assert len(candidates) == 1, "the un-allowlisted week-99 item must not become a candidate"
    only = candidates[0]
    assert only["path"] == "/journal/posts/week-02/"
    kit = only["kit"]
    assert kit["title"] == "The Night Before Everything"
    assert kit["canonical_url"] == "https://averagejoematt.com/journal/posts/week-02/"
    assert "The Night Before Everything" in kit["caption"]
    assert "journal/posts/week-02" in kit["caption"]


def test_list_candidates_empty_moments_index_yields_no_candidates(monkeypatch):
    def fake(url, timeout=10):
        if url == post_social.MOMENTS_INDEX_URL:
            return '{"chronicles": {}}'
        raise AssertionError("rss.xml should never be fetched when the moments index has no chronicles")

    monkeypatch.setattr(post_social, "_get", fake)

    assert post_social.list_candidates() == []


def test_strip_links_removes_bare_url():
    assert post_social.strip_links("Check this out: https://example.com/a/b?x=1 — worth a read") == "Check this out: — worth a read"


def test_strip_links_no_link_survives_mid_sentence_reply_shaped_string():
    text = "Replying here — see https://x.com/i/status/12345 for the thread, also http://short.ly/xyz works too."
    result = post_social.strip_links(text)
    assert "http://" not in result
    assert "https://" not in result
    assert "Replying here" in result
    assert "works too." in result


def test_strip_links_handles_no_url_present():
    assert post_social.strip_links("Nothing to strip here.") == "Nothing to strip here."


def test_truncate_for_bluesky_stays_under_limit_and_keeps_link():
    link = "https://averagejoematt.com/journal/posts/week-02/?utm_source=x&utm_medium=social&utm_campaign=chronicle"
    caption = "\n\n".join(["Title here", "word " * 100, link])

    out = post_social.truncate_for_bluesky(caption, limit=300)

    assert len(out) <= 300
    assert out.endswith(link)


def test_truncate_for_bluesky_is_a_no_op_under_limit():
    caption = "Short caption\n\nhttps://averagejoematt.com/journal/posts/week-02/"
    assert post_social.truncate_for_bluesky(caption, limit=300) == caption
