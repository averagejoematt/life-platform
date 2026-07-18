"""test_rss_truncation.py — guard for #1261.

The RSS builder used to cut item descriptions with a raw fixed-length slice
(`excerpt[:357]`), producing mid-word fragments in feed readers (e.g. "…before any
dat", "…measures his stre"). #1261 replaces that with the shared word-boundary
helper `text_utils.truncate_at_word` (the ONE helper from #1224).

This test drives `scripts/v4_build_rss.main()` end-to-end (network + blog manifest
mocked) with a crafted over-length excerpt whose naive 357-char slice would land
mid-word, then parses the emitted RSS and asserts the `<description>` ends on a
word boundary — i.e. the character in the SOURCE right after the emitted text is
whitespace (nothing was split), never a letter continuing a word.

Non-vacuity: against the PRE-FIX builder (the `[:357]` slice) this FAILS, because
the source character after the cut is a letter. See the PR body for the captured
failing run.
"""

import io
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest

# The builder lives in scripts/ (not on the default test path). lambdas/ is already
# on sys.path via tests/conftest.py, so the builder's `from text_utils import ...`
# resolves once scripts/ is importable.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

import v4_build_rss  # noqa: E402

# A deterministic over-length excerpt: 80 blocks of "abcdefghij " (11 chars each,
# 880 chars total). Every block is 10 letters then a single space, so the naive
# `[:357]` slice lands at index 357 → offset 357 % 11 == 5 → the letter 'f',
# squarely mid-word. A correct word-boundary cut must instead break at the space
# preceding index 360.
LONG_EXCERPT = "abcdefghij " * 80


def _run_builder(monkeypatch, tmp_path, excerpt):
    """Invoke v4_build_rss.main() with the network + blog manifest mocked, returning
    the emitted RSS XML string."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "posts": [
            {
                "date": today,
                "title": "Word Boundary Guard",
                "url": "/journal/posts/week-01/",
                "excerpt": excerpt,
            }
        ]
    }

    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    def _fake_urlopen(url, timeout=0):
        return _FakeResp(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(v4_build_rss, "urlopen", _fake_urlopen)
    # Keep the feed to the single crafted item — no real essay manifest.
    monkeypatch.setattr(v4_build_rss, "_blog_posts", lambda: [])

    out = tmp_path / "rss.xml"
    out_alias = tmp_path / "feed.xml"
    monkeypatch.setattr(v4_build_rss, "OUT", out)
    monkeypatch.setattr(v4_build_rss, "OUT_ALIAS", out_alias)

    rc = v4_build_rss.main()
    assert rc == 0
    return out.read_text(encoding="utf-8")


def _first_description(xml_text):
    """Parse the RSS (also asserts XML validity) and return the first item's
    <description> text, entity-unescaped by ElementTree."""
    root = ET.fromstring(xml_text)  # noqa: S314 — our own generated feed (trusted); raises on malformed XML
    item = root.find("./channel/item")
    assert item is not None, "feed has no <item>"
    desc = item.findtext("description")
    assert desc is not None, "item has no <description>"
    return desc


def test_rss_excerpt_does_not_end_mid_word(monkeypatch, tmp_path):
    """A truncated RSS description must end on a word boundary + ellipsis — never a
    partial trailing token."""
    xml_text = _run_builder(monkeypatch, tmp_path, LONG_EXCERPT)
    desc = _first_description(xml_text)

    src = " ".join(LONG_EXCERPT.split())

    # The excerpt is over-length, so it MUST have been truncated (ellipsis appended).
    assert desc.endswith("…"), f"expected a truncated excerpt ending in an ellipsis, got: {desc!r}"

    body = desc[:-1].rstrip()
    # The emitted body must be a prefix of the source...
    assert src.startswith(body), f"emitted body is not a prefix of the source excerpt: {body!r}"
    # ...ending exactly at a word boundary: the SOURCE character immediately after the
    # emitted text must be whitespace (or the body reached the end). A mid-word cut
    # (the old `[:357]` slice) leaves a letter there → this fails.
    assert len(body) < len(src), "over-length excerpt should have been shortened"
    next_char = src[len(body)]
    assert next_char.isspace(), (
        f"description ends mid-word: emitted {body[-15:]!r}, but the source continues "
        f"with {next_char!r} (no whitespace boundary) — mid-word truncation"
    )


def test_short_excerpt_is_not_ellipsized(monkeypatch, tmp_path):
    """An excerpt already within the limit is emitted verbatim — no spurious ellipsis
    (the #1224 helper only signals a cut when it actually shortened the text)."""
    short = "A short chronicle excerpt that fits well within the RSS limit."
    xml_text = _run_builder(monkeypatch, tmp_path, short)
    desc = _first_description(xml_text)
    assert desc == short
    assert not desc.endswith("…")


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
