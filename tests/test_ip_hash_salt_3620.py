"""#3620 (security ROW4) — the reader ip_hash is SALTED, and the doors fail CLOSED.

The defect these tests pin: `sha256(client_ip)[:16]` unsalted is a 2**32 keyspace
over IPv4, i.e. reversible to the reader's address in minutes by anyone who gets
one digest — and this platform PERSISTS the digest (submit_finding /
board_question write it into the stored record, predict writes it into a DDB sort
key) and LOGS it (nudge, ritual_log). The digest was never a pseudonym.

Three properties, in the order they matter:

  1. determinism — same ip + same salt -> same digest (the rate limiter needs a
     stable key; a per-request digest would silently unmeter every door).
  2. salt-dependence — same ip + a different salt -> a different digest (proves
     the salt actually reaches the hash input and is not decorative).
  3. fail-CLOSED — no salt -> `None`, and the caller refuses. This is the one
     that makes the fix real: an unsalted fallback would keep writing the
     reversible value on exactly the days the control was broken.

Property 3 is asserted twice — once on the helper, once through a real handler —
because a helper that returns None is worthless if a call site ignores it.
A SET assertion below derives the call sites from the source, so a seventh door
added later cannot quietly reintroduce the unsalted form.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from web import site_api_social_engage as engage  # noqa: E402

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "lambdas", "web", "site_api_social_engage.py")


class _Logger:
    def __init__(self):
        self.errors = []

    def error(self, msg):
        self.errors.append(msg)

    def info(self, msg):
        pass

    def warning(self, msg):
        pass


def _g_with_salt(monkeypatch, salt):
    """A minimal `_g` hand-off plus a stubbed secret read returning `salt`.

    `salt=None` simulates the unavailable-secret state (GetSecretValue raising —
    a missing secret, a missing IAM grant, or a Secrets Manager outage all land
    here identically, which is the point).
    """

    def fake_get_secret(secret_id, client):
        assert secret_id == engage._IP_HASH_SALT_SECRET_NAME
        if salt is None:
            raise RuntimeError("ResourceNotFoundException")
        return salt

    monkeypatch.setattr(engage, "_get_secret", fake_get_secret)

    class _Boto:
        @staticmethod
        def client(*a, **k):
            return object()

    return {"boto3": _Boto, "logger": _Logger()}


def test_same_ip_same_salt_is_stable(monkeypatch):
    g = _g_with_salt(monkeypatch, "salt-alpha")
    a = engage._salted_ip_hash("203.0.113.7", g)
    b = engage._salted_ip_hash("203.0.113.7", g)
    assert a == b
    assert a is not None and len(a) == 16


def test_different_salt_changes_the_digest(monkeypatch):
    g1 = _g_with_salt(monkeypatch, "salt-alpha")
    first = engage._salted_ip_hash("203.0.113.7", g1)
    g2 = _g_with_salt(monkeypatch, "salt-beta")
    second = engage._salted_ip_hash("203.0.113.7", g2)
    assert first != second, "the salt does not reach the hash input — the fix is decorative"


def test_different_ip_same_salt_differs(monkeypatch):
    g = _g_with_salt(monkeypatch, "salt-alpha")
    assert engage._salted_ip_hash("203.0.113.7", g) != engage._salted_ip_hash("203.0.113.8", g)


def test_digest_is_not_the_unsalted_form(monkeypatch):
    """The control that catches a silent revert to `sha256(ip)`."""
    import hashlib

    g = _g_with_salt(monkeypatch, "salt-alpha")
    unsalted = hashlib.sha256(b"203.0.113.7").hexdigest()[:16]
    assert engage._salted_ip_hash("203.0.113.7", g) != unsalted


def test_missing_salt_returns_none_and_logs(monkeypatch):
    g = _g_with_salt(monkeypatch, None)
    assert engage._salted_ip_hash("203.0.113.7", g) is None
    assert any("fail-closed" in m for m in g["logger"].errors)


def test_empty_salt_returns_none(monkeypatch):
    """An empty SecretString is the shape a half-provisioned secret takes."""
    g = _g_with_salt(monkeypatch, "")
    assert engage._salted_ip_hash("203.0.113.7", g) is None


def test_handler_refuses_the_write_when_the_salt_is_missing(monkeypatch):
    """End-to-end on a real door: /api/nudge must 503, not write, when there is no salt.

    A helper that returns None proves nothing unless the call site branches on it.
    """
    g = _g_with_salt(monkeypatch, None)
    called = {"rate_check": 0}

    def _rate_check(*a, **k):
        called["rate_check"] += 1
        return True, 1, None

    g.update(
        {
            "NUDGE_CATEGORIES": {"watching"},
            "NUDGE_LABELS": {"watching": "Watching"},
            "_envelope": lambda status, payload, **k: {"statusCode": status, "body": payload},
            "_error": lambda status, message, **extra: {"statusCode": status, "body": {"error": message}},
            "_nudge_counts": {},
            "_rate_check": _rate_check,
            "_rate_limited": lambda *a, **k: {"statusCode": 429},
            "_sanitise_text": lambda v: v if isinstance(v, str) else "",
            "extract_client_ip": lambda e: "203.0.113.7",
            "json": __import__("json"),
        }
    )
    resp = engage._handle_nudge({"body": '{"category": "watching"}'}, _g=g)
    assert resp["statusCode"] == 503, resp
    assert called["rate_check"] == 0, "the door proceeded past the missing salt"


def test_every_ip_hash_call_site_is_salted():
    """SET assertion (#3620 carries a review:* label — guard the class, not the specimen).

    Derived from the source by AST, so a seventh door added later is covered
    without anyone remembering to extend a list here: every function that binds a
    local named `ip_hash` must bind it from `_salted_ip_hash`, and no assignment
    in the module may bind `ip_hash` from a bare `hashlib.sha256(...)`.
    """
    tree = ast.parse(open(_MODULE_PATH).read())
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "ip_hash" not in names:
            continue
        sites.append(ast.unparse(node.value))
    assert sites, "no ip_hash assignment found — the AST derivation broke, not the code"
    unsalted = [src for src in sites if not src.startswith("_salted_ip_hash(")]
    assert not unsalted, f"unsalted ip_hash call site(s): {unsalted}"
    assert len(sites) >= 6, f"expected at least the 6 known doors, derived {len(sites)}"


def test_the_secret_is_registered():
    """The name must be in both KNOWN_SECRETS twins or SR1 reds on the next push."""
    from test_secret_references import KNOWN_SECRETS as REF_KNOWN

    assert engage._IP_HASH_SALT_SECRET_NAME in REF_KNOWN


@pytest.mark.parametrize("fn", ["_handle_nudge", "_handle_submit_finding", "_handle_board_question"])
def test_named_doors_still_exist(fn):
    """Cheap anchor: the SET assertion above is only meaningful while these doors do."""
    assert hasattr(engage, fn)
