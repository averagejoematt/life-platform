"""His own words reach a page through one door (owner ruling 2026-11-15).

The owner approved five first-person lines, each for a named page. They are pinned in ``www/src/lib/own_words.js`` and
published only where the platform's consent record (ADR-142, ``/api/journal_quotes``) serves the same day and words.
These tests hold the three places that have to agree — the pin, the consent record's key, the snapshot's data file —
and the build scan that keeps a line on the page it was approved for.
"""

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

import check_www_build as cwb  # noqa: E402
import publish_snapshot_own_words as psw  # noqa: E402
from content import journal_quotes as jq  # noqa: E402

FIXTURE = os.path.join(REPO, "www", "content", "fixtures", "own_words.json")
#: The placements the owner approved, and the page(s) each approval names. Adding one is a new approval.
APPROVED = {
    "beginning": ["/story/moments/"],
    "content": ["/"],
    "ai_verdict": ["/system/"],
    "coaches_changed": ["/system/calibration/"],
    "pace": ["/story/*/", "/story/moments/"],
}


def test_the_pins_are_exactly_the_approved_placements_and_scopes():
    pins = cwb.own_words_pins()
    assert {k: v["scope"] for k, v in pins.items()} == APPROVED


def test_each_pinned_line_hashes_to_its_consent_record_and_passes_the_mark_time_gate():
    """The pin's `sk` is the consent record's key, a hash of the words: one changed character derives another key."""
    for key, pin in cwb.own_words_pins().items():
        assert jq.quote_sk(pin["date"], pin["text"]) == pin["sk"], key
        assert jq.find_mark_violations(pin["text"]) == [], key
        assert len(pin["text"]) <= jq.MAX_QUOTE_CHARS
    edited = dict(next(iter(cwb.own_words_pins().values())))
    assert jq.quote_sk(edited["date"], edited["text"] + "!") != edited["sk"]  # the control: an edit is a different record


def test_the_fixture_serves_exactly_the_pinned_lines():
    doc = psw.validate(json.load(open(FIXTURE, encoding="utf-8")))
    assert {(q["date"], q["quote"]) for q in doc["quotes"]} == {(p["date"], p["text"]) for p in cwb.own_words_pins().values()}


def test_the_exporter_carries_the_day_and_the_words_and_nothing_else():
    served = {
        "quotes": [
            {
                "date": "2026-11-08",
                "quote": "A line.",
                "marked_at": "2026-11-15T00:00:00Z",
                "channel": "journal",
                "receipts": "/cockpit/?date=2026-11-08",
            },
            {"date": "not-a-day", "quote": "dropped"},
            {"date": "2026-11-09", "quote": "   "},
        ],
        "featured": {"quote": "never carried"},
    }
    doc = psw.validate(psw.compose(served))
    assert doc["quotes"] == [{"date": "2026-11-08", "quote": "A line."}] and doc["state"] == "ok"
    assert psw.compose(None)["state"] == "absent" and psw.compose({"quotes": "x"})["quotes"] == []

    def boom(_path):
        raise OSError("down")

    assert psw.live_own_words(boom, lambda _m: None) == psw.ABSENT_OWN_WORDS  # a dead route places no line


@pytest.mark.parametrize(
    "bad",
    [
        {"state": "ok", "source": [], "absent_text": None, "quotes": [{"date": "2026-11-08", "quote": "x", "channel": "journal"}]},
        {"state": "ok", "source": [], "absent_text": None, "quotes": [{"date": "2026-11-08", "quote": ""}]},
        {"state": "absent", "source": [], "absent_text": "x", "quotes": [{"date": "2026-11-08", "quote": "x"}]},
        {"state": "ok", "source": [], "absent_text": None, "quotes": [], "marked_at": "2026-11-15"},
        {"state": "ok", "source": [], "absent_text": None, "quotes": [{"date": "2026-11-08", "quote": "x" * 501}]},
    ],
)
def test_the_data_file_refuses_any_field_beyond_the_day_and_the_words(bad):
    with pytest.raises(ValueError):
        psw.validate(bad)


def _dist(tmp_path, pages: dict[str, str], served: list[dict] | None):
    dist = tmp_path / "dist"
    for route, body in pages.items():
        d = dist / route.strip("/") if route.strip("/") else dist
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(f"<html><body><main>{body}</main></body></html>", encoding="utf-8")
    snap = tmp_path / "snapshot"
    snap.mkdir()
    if served is not None:
        (snap / "own_words.json").write_text(
            json.dumps({"state": "ok", "source": [], "absent_text": None, "quotes": served}), encoding="utf-8"
        )
    return str(dist), str(snap)


def test_the_scan_holds_a_line_to_its_page_its_consent_and_its_exact_words(tmp_path):
    pins = cwb.own_words_pins()
    ai, start = pins["ai_verdict"], pins["beginning"]
    esc = lambda t: t.replace("'", "&#39;")  # noqa: E731 — Astro escapes the apostrophe; the scan must still see the line
    fig = lambda key, text: f'<figure data-own-words="{key}"><blockquote>{esc(text)}</blockquote></figure>'  # noqa: E731
    served = [{"date": p["date"], "quote": p["text"]} for p in pins.values()]

    ok = _dist(tmp_path / "ok", {"/system/": fig("ai_verdict", ai["text"]), "/story/moments/": fig("beginning", start["text"])}, served)
    assert cwb.own_words_scope(*ok) == []
    # the three ways it must fail — each a planted control
    elsewhere = _dist(tmp_path / "elsewhere", {"/data/": fig("ai_verdict", ai["text"])}, served)
    assert any("outside the page" in i for i in cwb.own_words_scope(*elsewhere))
    revoked = _dist(tmp_path / "revoked", {"/system/": fig("ai_verdict", ai["text"])}, [q for q in served if q["quote"] != ai["text"]])
    assert any("does not serve it" in i for i in cwb.own_words_scope(*revoked))
    no_file = _dist(tmp_path / "nofile", {"/system/": fig("ai_verdict", ai["text"])}, None)
    assert any("does not serve it" in i for i in cwb.own_words_scope(*no_file))
    unpinned = _dist(
        tmp_path / "unpinned",
        {"/system/": "<p>Another line he marked.</p>"},
        served + [{"date": "2026-11-08", "quote": "Another line he marked."}],
    )
    assert any("no approved placement" in i for i in cwb.own_words_scope(*unpinned))
    stray_key = _dist(tmp_path / "stray", {"/system/": '<figure data-own-words="unknown"></figure>'}, served)
    assert any("does not pin" in i for i in cwb.own_words_scope(*stray_key))
