"""tests/test_site_api_write_scope.py — SEC-01: the public site-api DynamoDB write
must be scoped (LeadingKeys) to exactly the interactive partitions the code writes.

Two guards:
 1. every partition the site-api actually writes is covered by the role's LeadingKeys
    allowlist (so scoping never breaks a live public feature); and
 2. a write-call-site canary — if a new put_item/update_item appears in the site-api
    social module, this test fails so its partition gets added to the allowlist BEFORE
    it ships an AccessDenied to a public endpoint.
"""

import os
import re
from fnmatch import fnmatch

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROLES = os.path.join(_REPO, "cdk", "stacks", "role_policies.py")
_SOCIAL = os.path.join(_REPO, "lambdas", "web", "site_api_social.py")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _site_api_leadingkeys():
    """Extract the LeadingKeys patterns from role_policies.site_api()'s write statement."""
    src = _read(_ROLES)
    body = src[src.index("def site_api(") : src.index("def site_api_ai(")]
    block = re.search(r'DynamoDBWrite.*?dynamodb:LeadingKeys"\s*:\s*\[(.*?)\]', body, re.DOTALL)
    assert block, "site_api() DynamoDBWrite LeadingKeys block not found"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


# Every concrete partition-key the site-api writes (site_api_social.py + rate_limiter.py),
# enumerated from the code. Keep in sync with the write call sites.
_WRITTEN_KEYS = [
    "VOTES#rate_limit",  # vote/follow/predict per-IP rate limits
    "VOTES#experiment_library",  # experiment votes
    "VOTES#challenges",  # challenge votes
    "VOTES#predict_week",  # predict-the-week votes
    "EXPERIMENT_FOLLOWS",  # experiment follows
    "CHALLENGE_FOLLOWS",  # challenge follows
    "USER#matthew#SOURCE#experiment_suggestions",  # reader experiment suggestions
    "USER#matthew#SOURCE#challenges",  # challenge daily check-ins
    "RATE#board_ask#deadbeef",  # shared rate_limiter.py → RATE#{endpoint}#{ip_hash}
]


def test_leadingkeys_cover_every_site_api_write():
    patterns = _site_api_leadingkeys()
    uncovered = [k for k in _WRITTEN_KEYS if not any(fnmatch(k, p) for p in patterns)]
    assert not uncovered, f"site-api writes not covered by LeadingKeys {sorted(patterns)}: {uncovered}"


def test_write_call_site_canary():
    """If this count changes, a write was added/removed — verify its partition is in
    _WRITTEN_KEYS and the role's LeadingKeys before updating this baseline."""
    n = len(re.findall(r"\.(put_item|update_item)\(", _read(_SOCIAL)))
    assert n == 12, (
        f"site_api_social write count is {n}, baseline 12 — a write was added/removed. "
        "Confirm its partition is in the SEC-01 LeadingKeys allowlist + _WRITTEN_KEYS, then update this baseline."
    )


# ── #531: the AI lambda's write scope (board_ask episodic write-back) ─────────

_AI_LAMBDA = os.path.join(_REPO, "lambdas", "web", "site_api_ai_lambda.py")

# Every concrete partition-key the AI lambda writes: rate-limit counters
# (rate_limiter.py, UpdateItem) + the coach interaction write-back (PutItem).
_AI_WRITTEN_KEYS = [
    "RATE#board_ask#deadbeef",
    "RATE#ask#deadbeef",
    "COACH#sleep_coach",  # INTERACTION# episodic records (#531)
]


def _site_api_ai_leadingkeys():
    """Union of LeadingKeys patterns across site_api_ai()'s write statements."""
    src = _read(_ROLES)
    start = src.index("def site_api_ai(")
    nxt = src.find("\ndef ", start + 1)
    body = src[start : nxt if nxt > 0 else len(src)]
    patterns = set()
    for block in re.findall(r'dynamodb:LeadingKeys"\s*:\s*\[(.*?)\]', body, re.DOTALL):
        patterns |= set(re.findall(r'"([^"]+)"', block))
    assert patterns, "site_api_ai() LeadingKeys blocks not found"
    return patterns


def test_ai_leadingkeys_cover_every_ai_lambda_write():
    patterns = _site_api_ai_leadingkeys()
    uncovered = [k for k in _AI_WRITTEN_KEYS if not any(fnmatch(k, p) for p in patterns)]
    assert not uncovered, f"site-api-ai writes not covered by LeadingKeys {sorted(patterns)}: {uncovered}"


def test_ai_write_call_site_canary():
    """The AI lambda's only in-module DDB write is the #531 interaction
    write-back (rate-limit counters live in the shared rate_limiter module).
    If this count changes, scope the new write's partition first."""
    n = len(re.findall(r"\.(put_item|update_item)\(", _read(_AI_LAMBDA)))
    assert n == 1, (
        f"site_api_ai write count is {n}, baseline 1 — a write was added/removed. "
        "Confirm its partition is in site_api_ai()'s LeadingKeys + _AI_WRITTEN_KEYS, then update this baseline."
    )


def test_ai_interaction_write_is_putitem_only():
    """The COACH#* write grant must stay PutItem-only — the public lambda must
    never gain the ability to mutate STANCE#/COMPRESSED#/OUTPUT# in place."""
    src = _read(_ROLES)
    start = src.index('sid="DynamoDBCoachInteractionWrite"')
    block = src[start : start + 600]
    m = re.search(r"actions=\[(.*?)\]", block, re.DOTALL)
    assert m and '"dynamodb:PutItem"' in m.group(1)
    assert "UpdateItem" not in m.group(1) and "DeleteItem" not in m.group(1)
