"""tests/test_reading_enrich.py — LLM book enrichment parse + fail-soft.

Bedrock is never called: a fake `caller` returns an Anthropic-shaped response.
Asserts JSON parsing (incl. fenced), subscore clamping + derived length +
composite, and the fail-soft stub on every failure path.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from reading import reading_enrich as re_mod  # noqa: E402


def _resp(payload, fenced=False):
    text = json.dumps(payload)
    if fenced:
        text = "```json\n" + text + "\n```"
    return {"content": [{"type": "text", "text": text}]}


def test_happy_path_tags_and_difficulty():
    def caller(_body):
        return _resp(
            {
                "domainTags": ["Sci-Fi", "fiction"],
                "themes": ["Survival", "problem-solving"],
                "era": "contemporary",
                "difficulty": {"density": 2, "prose": 2, "structure": 1},
            }
        )

    out = re_mod.enrich_book({"title": "Project Hail Mary", "author": "Andy Weir", "pageCount": 496}, caller=caller)
    assert out["enriched"] is True
    assert out["domainTags"] == ["sci-fi", "fiction"]  # lowercased
    assert out["themes"] == ["survival", "problem-solving"]
    assert out["era"] == "contemporary"
    d = out["difficulty"]
    assert d["density"] == 2 and d["prose"] == 2 and d["structure"] == 1
    assert d["length"] == 3  # 496pp → bucket 3
    assert d["composite"] == round((2 + 2 + 1 + 3) / 4, 2)


def test_fenced_json_parsed():
    def caller(_body):
        return _resp({"domainTags": ["history"], "themes": [], "era": "modern", "difficulty": {}}, fenced=True)

    out = re_mod.enrich_book({"title": "T", "author": "A", "pageCount": 100}, caller=caller)
    assert out["enriched"] is True and out["domainTags"] == ["history"]
    assert out["difficulty"]["length"] == 1  # 100pp → bucket 1


def test_subscores_clamped_and_capped():
    def caller(_body):
        return _resp(
            {
                "domainTags": ["a", "b", "c", "d", "e", "f"],
                "themes": ["t1", "t2", "t3", "t4", "t5"],
                "era": "bogus",
                "difficulty": {"density": 9, "prose": 0, "structure": 3},
            }
        )

    out = re_mod.enrich_book({"title": "T", "author": "A"}, caller=caller)
    assert len(out["domainTags"]) == 4 and len(out["themes"]) == 4  # capped
    assert out["era"] is None  # invalid era dropped
    assert out["difficulty"]["density"] == 5 and out["difficulty"]["prose"] == 1  # clamped to 1..5


def test_fail_soft_on_bad_json():
    def caller(_body):
        return {"content": [{"type": "text", "text": "not json at all"}]}

    out = re_mod.enrich_book({"title": "T", "author": "A"}, caller=caller)
    assert out["enriched"] is False and out["domainTags"] == [] and out["enrichError"]


def test_fail_soft_on_exception():
    def caller(_body):
        raise RuntimeError("bedrock down")

    out = re_mod.enrich_book({"title": "T", "author": "A"}, caller=caller)
    assert out["enriched"] is False and out["enrichError"] == "RuntimeError"


def test_no_title_returns_empty():
    out = re_mod.enrich_book({"author": "A"}, caller=lambda b: _resp({}))
    assert out["enriched"] is False
