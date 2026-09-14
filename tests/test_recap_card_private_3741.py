"""tests/test_recap_card_private_3741.py — the card is his to post, not the platform's.

THE STANDING RULE

`lambdas/content/fingerprint_broadcast.py` records it verbatim:

    AUTOMATED_SYNDICATION_REASON = "denied — ADR-140 rule 5 / #1629: no automated surface
    posts a vitals-derived mark. Human selection only."

This feature is that rule honoured, not an exception to it. The card is rendered, stored
privately, and handed to the owner; HE decides what goes on a grid. #1632 declined
auto-posting in July for its own reasons (Meta App Review, a Business account, a linked
Page) and #3750 keeps that decision dated and revisitable. Nothing here talks to Instagram.

WHAT THAT MEANS STRUCTURALLY, AND THE SENTENCE THAT USED TO BE HERE

This file's first version said: *"the `generated/` prefix is anonymously readable WHERE A
BEHAVIOUR ROUTES TO IT"*. That is wrong, and the whole defect is in the clause. The bucket
policy's `PublicReadGenerated` statement grants `Principal: *` `s3:GetObject` on
`generated/*` **at the S3 origin**, with or without CloudFront. So the cards shipped to
`generated/recap/`, CloudFront correctly returned 404 for `/recap/…`, this test passed —
and every card was downloadable with no credentials at
`https://matthew-life-platform.s3.us-west-2.amazonaws.com/generated/recap/2026-09-12.png`,
at a key derivable from a date, in a PUBLIC repo that names the prefix.

Verified live 2026-09-14 before the fix: http 200, 48,779 bytes, byte-identical to the
card. Eight days plus the weekly.

This is #3559 one prefix over — reader-input moderation records carrying `email` and
`ip_hash` had landed in `generated/` for the same reason, and the fix was the same: move
off it. The guard written then covered the reader-input doors by name, so it could not see
a new writer arriving at the same prefix. Guard the SET, not the instance.

WHAT IS GUARDED NOW
  1. the public-read prefixes are DERIVED from `deploy/bucket_policy.json`, never retyped;
  2. the card's output prefix is under NONE of them — with a must-fail control that plants
     `generated/recap/` back and watches this red;
  3. the prefix is also OUTSIDE `ProtectDataFromDeployScripts`, so a card can be purged.
     It could not be, during the incident: the deny that protects `generated/*` from deploy
     scripts also blocked deleting the exposed cards, and they had to be overwritten in
     place instead;
  4. the CDK env and the handler default name the same prefix (a disagreement means the
     deployed function writes somewhere no test has ever looked);
  5. the CloudFront route is still asserted absent — necessary, just never sufficient.
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


# ── the property that actually matters ────────────────────────────────────────
BUCKET_POLICY = REPO / "deploy" / "bucket_policy.json"
CDK_OPERATIONAL = REPO / "cdk" / "stacks" / "operational_stack.py"


def _policy_prefixes(effect: str, anonymous: bool) -> list[str]:
    """Prefixes from the committed bucket policy. Derived, never retyped (#3559's rule)."""
    import json

    doc = json.loads(BUCKET_POLICY.read_text())
    out = []
    for st in doc.get("Statement", []):
        if st.get("Effect") != effect:
            continue
        is_anon = st.get("Principal") == "*" or st.get("Principal") == {"AWS": "*"}
        if is_anon != anonymous:
            continue
        res = st.get("Resource")
        for r in [res] if isinstance(res, str) else (res or []):
            _, _, tail = r.partition(":::")
            _, _, key = tail.partition("/")
            if key:
                out.append(key.rstrip("*"))
    return out


def _recap_prefix() -> str:
    import re as _re

    m = _re.search(r'RECAP_PREFIX\s*=\s*os\.environ\.get\(\s*"RECAP_S3_PREFIX"\s*,\s*"([^"]+)"', HANDLER.read_text())
    assert m, "could not read the handler's output prefix — the extractor has gone blind"
    return m.group(1)


def test_the_card_prefix_is_not_anonymously_readable():
    """THE regression test for the 2026-09-14 exposure. Not 'is there a CDN route' —
    'can a stranger with no credentials GET this object'."""
    public = _policy_prefixes("Allow", anonymous=True)
    assert public, "no anonymous-read prefixes derived — the policy parser has gone blind"
    prefix = _recap_prefix()
    hits = [p for p in public if prefix.startswith(p)]
    assert not hits, (
        f"the recap card writes to {prefix!r}, which is under anonymously-readable {hits} in "
        "deploy/bucket_policy.json. Every card would be world-readable at a date-derivable key."
    )


def test_the_public_prefix_check_can_fail():
    """MUST-FAIL CONTROL: plant the real defect and watch the rule catch it."""
    public = _policy_prefixes("Allow", anonymous=True)
    planted = "generated/recap/"
    hits = [p for p in public if planted.startswith(p)]
    assert hits, "the shipped defect (generated/recap/) is NOT flagged by this rule — the rule is inert"


def test_a_card_can_still_be_purged():
    """The other half of #3559's rule, learned the hard way on 2026-09-14: the exposed
    cards could not be deleted, because `ProtectDataFromDeployScripts` denies DeleteObject
    on `generated/*`. They had to be overwritten in place. A private prefix that cannot be
    emptied is only half a fix."""
    protected = _policy_prefixes("Deny", anonymous=False)
    prefix = _recap_prefix()
    hits = [p for p in protected if prefix.startswith(p)]
    assert not hits, f"the recap prefix {prefix!r} is delete-protected by {hits} — an exposed card could not be removed"


def test_the_deployed_prefix_and_the_handler_default_agree():
    """A disagreement means the deployed function writes somewhere no test has looked."""
    import re as _re

    m = _re.search(r'"RECAP_S3_PREFIX"\s*:\s*"([^"]+)"', CDK_OPERATIONAL.read_text())
    assert m, "the CDK no longer sets RECAP_S3_PREFIX — the handler default becomes the only truth"
    assert m.group(1) == _recap_prefix(), f"CDK sets {m.group(1)!r}, the handler defaults to {_recap_prefix()!r}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
