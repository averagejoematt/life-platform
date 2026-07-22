"""test_coach_correction_resolver.py — the shared "#N -> archived generation" resolver
that both #1690 feedback channels import (epic #1687 S3).

Pins the offline contract:
  - parse_correction_reply: single / multi-line / malformed '#N' extraction (AC3 —
    malformed lines are collected, never dropped)
  - resolve_number: happy path (correct item_ref), unknown-N REPORTED, non-numeric
    REPORTED, empty-week message — all without touching S3 (numbering injected)
  - build_item_ref shape
  - numbered_for_week delegates to the real review_pack_ranker numbering (stable)

Fully offline: qa_archive/week-assembly is never called (numbering is injected, or
_load_week_assembly is monkeypatched).
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import coach_correction_resolver as ccr  # noqa: E402


def _entry(surface, variant, date, key):
    return {
        "surface": surface,
        "variant": variant,
        "date": date,
        "archived_at": f"{date}T12:00:00+00:00",
        "_key": key,
        "text": "some archived text",
        "meta": {},
    }


_NUMBERED = [
    (1, _entry("chronicle", None, "2026-07-20", "generated/qa_archive/text/2026-07-20/chronicle--120000--aaaa1111.json")),
    (
        2,
        _entry(
            "coach_brief",
            "sleep_coach",
            "2026-07-20",
            "generated/qa_archive/text/2026-07-20/coach_brief--sleep_coach--120100--bbbb2222.json",
        ),
    ),
    (
        3,
        _entry(
            "coach_brief",
            "nutrition_coach",
            "2026-07-21",
            "generated/qa_archive/text/2026-07-21/coach_brief--nutrition_coach--120200--cccc3333.json",
        ),
    ),
]


# ── parse_correction_reply ──────────────────────────────────────────────────
def test_parse_single_line():
    out = ccr.parse_correction_reply("#3 the 315 lbs baseline is stale, I'm 321.4")
    assert out["corrections"] == [(3, "the 315 lbs baseline is stale, I'm 321.4")]
    assert out["malformed"] == []


def test_parse_multi_line():
    body = "#1 wrong title\n#2 the protein target should be 190g not 170g\n\n#3 fix framing"
    out = ccr.parse_correction_reply(body)
    assert out["corrections"] == [
        (1, "wrong title"),
        (2, "the protein target should be 190g not 170g"),
        (3, "fix framing"),
    ]
    assert out["malformed"] == []


def test_parse_tolerates_space_after_hash():
    out = ccr.parse_correction_reply("# 4 spaced hash still parses")
    assert out["corrections"] == [(4, "spaced hash still parses")]


def test_parse_collects_malformed_never_drops():
    body = "#3\n#abc not a number\n#5 valid correction\nhello there\n> quoted line"
    out = ccr.parse_correction_reply(body)
    # only the well-formed line resolves to a correction
    assert out["corrections"] == [(5, "valid correction")]
    # '#3' (no text) and '#abc ...' both lead with '#' but don't parse -> reported
    assert "#3" in out["malformed"]
    assert any("abc" in m for m in out["malformed"])
    # a plain greeting is neither a correction nor malformed (ignored)
    assert not any("hello" in m for m in out["malformed"])


def test_parse_empty():
    assert ccr.parse_correction_reply("") == {"corrections": [], "malformed": []}
    assert ccr.parse_correction_reply(None) == {"corrections": [], "malformed": []}


# ── build_item_ref ──────────────────────────────────────────────────────────
def test_build_item_ref_shape():
    _, entry = _NUMBERED[1]
    ref = ccr.build_item_ref(2, entry)
    assert ref == {
        "pack_number": 2,
        "surface": "coach_brief",
        "coach": "sleep_coach",
        "date": "2026-07-20",
        "archive_key": "generated/qa_archive/text/2026-07-20/coach_brief--sleep_coach--120100--bbbb2222.json",
    }


# ── resolve_number (numbering injected — no S3) ─────────────────────────────
def test_resolve_happy_path():
    res = ccr.resolve_number(2, numbered=_NUMBERED)
    assert res["ok"] is True
    assert res["n"] == 2
    assert res["total"] == 3
    assert res["item_ref"]["coach"] == "sleep_coach"
    assert res["item_ref"]["pack_number"] == 2
    assert res["entry"]["surface"] == "coach_brief"


def test_resolve_accepts_numeric_string():
    res = ccr.resolve_number("3", numbered=_NUMBERED)
    assert res["ok"] is True
    assert res["n"] == 3
    assert res["item_ref"]["coach"] == "nutrition_coach"


def test_resolve_unknown_number_reported():
    res = ccr.resolve_number(9, numbered=_NUMBERED)
    assert res["ok"] is False
    assert res["n"] == 9
    assert res["total"] == 3
    assert "no item #9" in res["error"]
    assert "3 items" in res["error"]  # tells Matthew how many exist


def test_resolve_non_numeric_reported():
    res = ccr.resolve_number("abc", numbered=_NUMBERED)
    assert res["ok"] is False
    assert "not a valid item number" in res["error"]


def test_resolve_empty_week_reported():
    res = ccr.resolve_number(1, numbered=[])
    assert res["ok"] is False
    assert res["total"] == 0
    assert "no generations to correct" in res["error"]


# ── numbered_for_week delegates to the real ranker (stable numbering) ────────
def test_numbered_for_week_uses_real_ranker(monkeypatch):
    import review_pack_ranker

    surface_order = review_pack_ranker.DEFAULT_SURFACE_ORDER
    by_surface = {
        "coach_brief": [_NUMBERED[1][1], _NUMBERED[2][1]],
        "chronicle": [_NUMBERED[0][1]],
    }
    # Avoid importing the email module / S3: inject the assembly triple.
    monkeypatch.setattr(ccr, "_load_week_assembly", lambda: (None, None, surface_order))
    numbered = ccr.numbered_for_week(by_surface=by_surface)
    # chronicle sorts before coach_brief (surface order), so chronicle is #1.
    assert numbered[0][1]["surface"] == "chronicle"
    assert [n for n, _ in numbered] == [1, 2, 3]
    # same input -> same numbering (the contract both channels rely on)
    again = ccr.numbered_for_week(by_surface=by_surface)
    assert [(n, e["_key"]) for n, e in numbered] == [(n, e["_key"]) for n, e in again]
