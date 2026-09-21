"""#3620 (security ROW4, `review:*` label) — the repo-wide sweep, not the module-scoped one.

`tests/test_ip_hash_salt_3620.py`'s own SET assertion says the label is why it guards
"the class, not the specimen" — and then only ever walked ONE module
(`web/site_api_social_engage.py`). Running the issue's own instruction —
`grep -rn "sha256(.*ip" lambdas/ mcp/` — found six more unsalted call sites across
four more modules (`site_api_social_ladder.py`, `site_api_social_challenges.py`,
`site_api_social_experiments.py`, `site_api_ai_lambda.py` x3, `email_subscriber_lambda.py`),
none of which the module-scoped sweep could ever see.

This is that grep, made permanent: every `sha256(...)` call anywhere under `lambdas/`
or `mcp/` whose argument mentions `ip` must be one of an explicit, reasoned allowlist
(the ONE salted core implementation per module, or a documented exception) — anything
else fails by construction, so a NEW unsalted call site anywhere in the fleet reds this
test instead of waiting for someone to remember to extend a per-module list.
"""

import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCAN_DIRS = (os.path.join(_ROOT, "lambdas"), os.path.join(_ROOT, "mcp"))

# Matches a REAL call — `.sha256(` (the dot excludes prose like a docstring's
# "`sha256(salt + ip)`", which has no method-call dot before it) — whose argument
# expression (before the first closing paren) contains an `ip` TOKEN: bounded by
# non-letters on both sides, so `source_ip`, `client_ip`, `{ip}` and a bare `ip` all
# match (same as the issue's own `grep -rn "sha256(.*ip"`) while `.strip()`,
# `recipient` and `principal` — "ip" glued mid-word — do not. Deliberately loose
# beyond that: a false positive just needs a new allowlist line with a reason; a
# false negative is the failure mode this test exists to prevent.
_SHA256_IP_RE = re.compile(r"\.sha256\([^)]*(?<![A-Za-z])ip(?![A-Za-z])", re.IGNORECASE)

# Every (relative path, exact stripped source line) this sweep is allowed to contain,
# with WHY:
#   "core"      — the ONE helper's own salted digest — reads the secret FIRST, this is
#                 the line every other call site routes through (directly or via the
#                 module-private wrapper below).
#   "unsalted"  — deliberately not salted; the file itself carries the full reasoning
#                 inline, right above the line named here.
_ALLOWED = {
    (
        "lambdas/common/client_ip.py",
        'return hashlib.sha256(f"{salt}:{source_ip}".encode()).hexdigest()[:16]',
    ): "core",
    (
        "lambdas/web/site_api_social_engage.py",
        'return _hashlib.sha256(f"{salt}:{source_ip}".encode()).hexdigest()[:16]',
    ): "core (independent, identical-form implementation — see client_ip.py's module docstring)",
    (
        "lambdas/operational/traffic_digest_lambda.py",
        'return hashlib.sha256(f"{ip}|{ua}".encode("utf-8", "ignore")).hexdigest()[:16]',
    ): "unsalted (ephemeral, in-memory-only, never persisted/logged/emitted — see _ipkey's docstring)",
}


def _iter_py_files():
    for base in _SCAN_DIRS:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _find_hits():
    hits = []
    for path in _iter_py_files():
        rel = os.path.relpath(path, _ROOT).replace(os.sep, "/")
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if _SHA256_IP_RE.search(stripped):
                    hits.append((rel, stripped))
    return hits


def test_every_sha256_ip_call_site_is_triaged():
    hits = _find_hits()
    assert hits, "the sweep found NOTHING — the regex broke, not the fleet (there must be >=2 core lines)"
    untriaged = [h for h in hits if h not in _ALLOWED]
    assert not untriaged, f"unsalted/untriaged sha256(ip) call site(s) — route through common.client_ip.salted_ip_hash: {untriaged}"


def test_the_allowlist_names_every_line_it_finds():
    """The inverse direction: an allowlist entry that no longer matches anything live
    (the line moved or was deleted) is a stale exception hiding a real fix — assert
    every entry is still findable, not just that nothing UNLISTED is findable."""
    hits = set(_find_hits())
    stale = [k for k in _ALLOWED if k not in hits]
    assert not stale, f"stale allowlist entr(y/ies) — the line no longer exists, remove it: {stale}"


def test_regex_control_catches_a_planted_unsalted_call():
    """Must-fail control (#3594 review:* discipline): proves the regex actually fires
    on the exact shape it exists to catch, using literal source text — not a file on
    disk under lambdas/, so this control can never accidentally pass the sweep above."""
    planted = [
        "ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]",
        "ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]",
        'return hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()[:16]',
    ]
    for line in planted:
        assert _SHA256_IP_RE.search(line), f"control line should have matched: {line}"

    # And the negative control: a hash that has nothing to do with an IP must NOT match
    # (this sweep is not "every sha256 call in the fleet").
    assert not _SHA256_IP_RE.search("email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]")
    assert not _SHA256_IP_RE.search('return hashlib.sha256(f"{salt}:{source_ip}".encode()).hexdigest()[:16]'.replace("source_ip", "src"))


def test_salted_ip_hash_call_sites_exist_for_every_fixed_module():
    """Cheap anchor: the SIX modules #3620's grep found must still call the shared
    helper by name — if a future refactor renamed or removed the call, the sweep
    above would go quiet for the wrong reason (no sha256(ip) line at all, salted OR
    not) rather than catching a regression."""
    expected = {
        "lambdas/web/site_api_social_ladder.py": "salted_ip_hash(",
        "lambdas/web/site_api_social_challenges.py": "salted_ip_hash(",
        "lambdas/web/site_api_social_experiments.py": "salted_ip_hash(",
        "lambdas/web/site_api_ai_lambda.py": "salted_ip_hash(",
        "lambdas/web/email_subscriber_lambda.py": "salted_ip_hash(",
        "lambdas/web/site_api_social.py": "salted_ip_hash",  # the facade re-export
    }
    for rel, needle in expected.items():
        text = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        assert needle in text, f"{rel} no longer references {needle!r} — did the fix regress?"
