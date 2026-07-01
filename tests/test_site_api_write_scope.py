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
