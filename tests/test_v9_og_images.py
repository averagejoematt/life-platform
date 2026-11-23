"""scripts/v9_og_images.py — the share cards (2026-11-14, sprint II): only a published chapter gets one, the bytes are
deterministic, and a card's name carries the hash of its bytes (the deploy caches assets/ for a year)."""

import importlib.util
import json
import os
import re

import pytest

pytest.importorskip("PIL")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("v9_og_images", os.path.join(ROOT, "scripts", "v9_og_images.py"))
og = importlib.util.module_from_spec(spec)
spec.loader.exec_module(og)

PUBLISHED = {
    "id": "week-12",
    "type": "chapter",
    "visibility": "public",
    "status": "published",
    "week": 10,
    "week_label": "Week 10",
    "title": "The Rate Flag",
    "excerpt": "A dek.",
    "data_through": "2026-11-10",
}


def test_a_published_chapter_gets_a_hashed_card(tmp_path):
    path = og.chapter_card(PUBLISHED, str(tmp_path))
    assert re.search(r"/week-12\.[0-9a-f]{8}\.png$", path)
    again = og.chapter_card(PUBLISHED, str(tmp_path / ".."))  # a second draw of the same object
    assert os.path.basename(path) == os.path.basename(again), "the same object draws the same bytes"


@pytest.mark.parametrize("status", ["held", "skipped", "pending"])
def test_an_unpublished_week_never_gets_a_card(tmp_path, status):
    assert og.chapter_card({**PUBLISHED, "status": status, "title": "Week 8"}, str(tmp_path)) is None
    assert og.chapter_card({**PUBLISHED, "visibility": "private"}, str(tmp_path)) is None
    assert os.listdir(tmp_path) == []


def test_the_run_removes_a_card_whose_chapter_is_gone(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "chapters.json").write_text(json.dumps([PUBLISHED]))
    out = tmp_path / "out"
    out.mkdir()
    (out / "week-99.deadbeef.png").write_bytes(b"x")
    import sys

    argv = sys.argv
    sys.argv = ["v9_og_images.py", "--snapshot", str(snap), "--out", str(out)]
    try:
        assert og.main() == 0
    finally:
        sys.argv = argv
    names = os.listdir(out)
    assert not any(n.startswith("week-99") for n in names)
    assert any(n.startswith("week-12.") for n in names)


# ── #6193 B4: the card prints the ONE summary rule's summary, never the first edition's once an edition is served ──

FIRST = "The first edition's summary, which a later edition withdrew."
EDITION = {
    "chapter_id": "week-12",
    "body_html": "<p>x</p>",
    "edition_line": "Second edition, revised 23 November 2026. First published 13 November 2026.",
    "signature": "Second edition, revised 23 November 2026 — Average Joe Matt editorial record",
    "title": "The Rate Flag",
    "summary": "The edition's own summary line.",
    "approvals": [{"by": "owner", "on": "2026-11-23", "via": "x"}],
}
TABLE = {"headers": {"week-12": {"replaces": "The first edition's", "text": "An approved replacement summary."}}}


def test_the_card_text_follows_the_one_summary_rule():
    c = {**PUBLISHED, "excerpt": FIRST}
    served = {"state": "ok", "editions": [EDITION]}
    assert og.card_text(c, served, truth_live=True, table=TABLE) == "The edition's own summary line."  # edition first
    assert og.card_text(c, served, truth_live=False, table=TABLE) == "The edition's own summary line."
    assert og.card_text(c, None, truth_live=True, table=TABLE) == "An approved replacement summary."  # then #6177
    assert og.card_text(c, None, truth_live=False, table=TABLE) == FIRST  # then the served one
    unsigned = {"state": "ok", "editions": [{**EDITION, "signature": "Second edition — someone"}]}
    assert og.card_text(c, unsigned, truth_live=False, table=TABLE) == FIRST  # a malformed edition is no edition


def test_a_card_for_a_chapter_with_a_served_edition_never_draws_the_first_editions_summary(tmp_path, monkeypatch):
    drawn = []
    real = og.wrap
    monkeypatch.setattr(og, "wrap", lambda dr, text, f, w, n: drawn.append(text) or real(dr, text, f, w, n))
    og.chapter_card({**PUBLISHED, "excerpt": FIRST}, str(tmp_path), {"state": "ok", "editions": [EDITION]})
    assert "The edition's own summary line." in drawn and FIRST not in drawn
