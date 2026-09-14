"""tests/test_recap_card_private_3741.py — the card is his to post, not the platform's.

THE STANDING RULE

`lambdas/content/fingerprint_broadcast.py` records it verbatim:

    AUTOMATED_SYNDICATION_REASON = "denied — ADR-140 rule 5 / #1629: no automated surface
    posts a vitals-derived mark. Human selection only."

This feature is that rule honoured, not an exception to it. The card is rendered, stored
privately, and handed to the owner; HE decides what goes on a grid. #1632 declined
auto-posting in July for its own reasons (Meta App Review, a Business account, a linked
Page) and #3750 keeps that decision dated and revisitable. Nothing here talks to Instagram.

WHAT THAT MEANS STRUCTURALLY, AND WHY IT NEEDS A TEST

"Private" is one CloudFront behaviour away from "public". The `generated/` prefix is
anonymously readable where a behaviour routes to it — that is how the OG cards are served
— so a `/recap/*` path_pattern added by a future well-meaning change would publish every
card ever rendered, retroactively, without touching this feature's code at all.

So the absence of that route is asserted, by name.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WEB_STACK = REPO / "cdk" / "stacks" / "web_stack.py"
HANDLER = REPO / "lambdas" / "web" / "recap_card_lambda.py"


def test_no_cloudfront_behaviour_serves_the_recap_prefix():
    """The one change that would make every card public without touching this feature."""
    src = WEB_STACK.read_text()
    patterns = re.findall(r'path_pattern\s*=\s*["\']([^"\']+)["\']', src)
    offenders = [p for p in patterns if "recap" in p.lower()]
    assert not offenders, (
        f"a CloudFront behaviour now routes {offenders} — every recap card ever rendered just became public, "
        "retroactively. The card is private until the owner posts it (ADR-140 rule 5)."
    )


def test_the_pattern_scan_can_actually_see_the_routes_it_is_checking():
    """NEGATIVE CONTROL. A regex that matches nothing would pass the test above forever.

    #3721's lesson, in miniature: a guard whose extractor has gone blind reports clean.
    """
    src = WEB_STACK.read_text()
    patterns = re.findall(r'path_pattern\s*=\s*["\']([^"\']+)["\']', src)
    assert len(patterns) >= 5, f"only {len(patterns)} path_patterns found — the extractor has gone blind"
    assert any("moments" in p for p in patterns), "the known /moments/* behaviour is not visible to this scan"


def test_the_handler_never_invalidates_cloudfront():
    """An invalidation is a tell: you only invalidate what is served.

    Read as CODE, not as text. The handler's own comment explains why there is nothing to
    invalidate, and a substring check would match that comment and fail — the same shape
    as the asset hasher that counted commented-out paths as edges. A guard that a correct
    explanation can break teaches people to delete the explanation.
    """
    tree = ast.parse(HANDLER.read_text())

    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                called.add(fn.attr)
            elif isinstance(fn, ast.Name):
                called.add(fn.id)
    assert "create_invalidation" not in called, "the recap handler invalidates CloudFront — it should have nothing to invalidate"

    clients = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "client"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert "cloudfront" not in clients, f"the handler builds a CloudFront client: {clients}"


def test_the_handler_talks_to_no_social_platform():
    """String CONSTANTS only — a comment naming Instagram is documentation, not a call."""
    tree = ast.parse(HANDLER.read_text())
    literals = [n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    # The module docstring is a literal too, so check for URL-shaped references rather
    # than the bare word.
    for forbidden in ("graph.facebook", "api.instagram", "/me/media", "graph.instagram"):
        assert not any(
            forbidden in lit for lit in literals
        ), f"the handler references {forbidden!r} — auto-posting is out of scope (#1632, #3750)"


def test_the_stored_object_declares_no_cache_policy():
    """The OG cards set CacheControl because they are served. This one is not."""
    src = HANDLER.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "put_object":
            kwargs = {kw.arg for kw in node.keywords}
            assert "CacheControl" not in kwargs, "the recap object sets CacheControl — that is the shape of something served"
            assert "ACL" not in kwargs, "the recap object sets an ACL — it must inherit the bucket's private default"


def test_the_delivery_path_is_the_owners_own_channels():
    """Telegram 1:1 and his email. Both are 'hand it to him', neither is 'publish'."""
    from_deliver = (REPO / "lambdas" / "content" / "recap_deliver.py").read_text()
    assert "sendPhoto" in from_deliver
    assert "first_private_chat_id" in from_deliver, "delivery does not pin the 1:1 chat — a group id would broadcast the card"


def test_the_standing_rule_is_still_where_this_test_thinks_it_is():
    """If #1629's reason moves or is deleted, this file's premise needs re-reading."""
    fb = (REPO / "lambdas" / "content" / "fingerprint_broadcast.py").read_text()
    assert "AUTOMATED_SYNDICATION_REASON" in fb
    assert "Human selection only" in fb


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
