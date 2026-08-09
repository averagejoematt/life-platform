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
                "domainTags": ["history", "science", "fiction", "poetry", "memoir", "nature"],
                "themes": ["t1", "t2", "t3", "t4", "t5"],
                "era": "bogus",
                "difficulty": {"density": 9, "prose": 0, "structure": 3},
            }
        )

    out = re_mod.enrich_book({"title": "T", "author": "A"}, caller=caller)
    assert len(out["domainTags"]) == 4 and len(out["themes"]) == 4  # capped
    assert out["era"] is None  # invalid era dropped
    assert out["difficulty"]["density"] == 5 and out["difficulty"]["prose"] == 1  # clamped to 1..5


# ── #2425: the per-field grounding gate ──────────────────────────────────────
def test_out_of_vocabulary_tag_never_ships():
    """The deterministic half: domainTags is a closed set, enforced in code."""

    def caller(_body):
        return _resp({"domainTags": ["history", "cyberpunk-noir", "SCIENCE", "astrology"], "themes": [], "era": None, "difficulty": {}})

    out = re_mod.enrich_book({"title": "T", "author": "A"}, caller=caller)
    assert out["domainTags"] == ["history", "science"]  # out-of-vocab dropped, case-normalized


def test_prompt_tag_list_is_built_from_the_vocab():
    """Prompt and validator cannot drift: every vocab tag appears in the prompt."""
    for tag in re_mod.DOMAIN_TAG_VOCAB:
        assert tag in re_mod._USER_TEMPLATE
    for era in re_mod.ERA_VOCAB:
        assert era in re_mod._USER_TEMPLATE


def test_theme_with_fabricated_number_is_held():
    """The free-text half: a theme citing a number the prompt never contained is
    dropped; grounded themes still ship (a gate that rejects everything is a gate
    nobody keeps)."""

    def caller(_body):
        return _resp(
            {
                "domainTags": ["sci-fi"],
                "themes": ["surviving 47 days alone", "problem-solving"],
                "era": "contemporary",
                "difficulty": {},
            }
        )

    out = re_mod.enrich_book({"title": "Project Hail Mary", "author": "Andy Weir", "pageCount": 496}, caller=caller)
    assert out["themes"] == ["problem-solving"], "the 47 appears nowhere in the prompt — the theme must be held (#2425)"


def test_theme_number_grounded_in_the_prompt_survives():
    """A number the model WAS given (the page count, a title figure) is legitimate."""

    def caller(_body):
        return _resp({"domainTags": ["classics"], "themes": ["the world of 1984"], "era": "modern", "difficulty": {}})

    out = re_mod.enrich_book({"title": "1984", "author": "George Orwell", "pageCount": 328}, caller=caller)
    assert out["themes"] == ["the world of 1984"]


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
