"""#3620 (security ROW4) — `common.client_ip.salted_ip_hash`, THE shared helper.

`web/site_api_social_engage.py`'s own AST sweep (tests/test_ip_hash_salt_3620.py)
scoped itself to ONE module and pinned ONE (independently-implemented) salted digest
function. The repo-wide grep the issue names (`grep -rn "sha256(.*ip" lambdas/ mcp/`)
found six more unsalted call sites across four more modules — this file pins the
ONE helper they all now route through: `common.client_ip.salted_ip_hash`.

Same three properties as the engage-module tests, on the shared helper directly:

  1. determinism — same ip + same salt -> same digest.
  2. salt-dependence — same ip + a different salt -> a different digest.
  3. fail-CLOSED — no salt -> `None`.

See tests/test_ip_hash_salt_sweep_3620.py for the repo-wide call-site sweep.
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from common import client_ip as _client_ip  # noqa: E402


class _Logger:
    def __init__(self):
        self.errors = []

    def error(self, msg):
        self.errors.append(msg)

    def info(self, msg):
        pass

    def warning(self, msg):
        pass


def _with_salt(monkeypatch, salt):
    """Patch `common.client_ip._get_secret` to return (or fail to return) `salt`.

    `salt=None` simulates the unavailable-secret state (a missing secret, a missing
    IAM grant, or a Secrets Manager outage all land here identically).
    """

    def fake_get_secret(secret_id, client):
        assert secret_id == _client_ip._IP_HASH_SALT_SECRET_NAME
        if salt is None:
            raise RuntimeError("ResourceNotFoundException")
        return salt

    monkeypatch.setattr(_client_ip, "_get_secret", fake_get_secret)


def test_same_ip_same_salt_is_stable(monkeypatch):
    _with_salt(monkeypatch, "salt-alpha")
    a = _client_ip.salted_ip_hash("203.0.113.7")
    b = _client_ip.salted_ip_hash("203.0.113.7")
    assert a == b
    assert a is not None and len(a) == 16


def test_different_salt_changes_the_digest(monkeypatch):
    _with_salt(monkeypatch, "salt-alpha")
    first = _client_ip.salted_ip_hash("203.0.113.7")
    _with_salt(monkeypatch, "salt-beta")
    second = _client_ip.salted_ip_hash("203.0.113.7")
    assert first != second, "the salt does not reach the hash input — the fix is decorative"


def test_different_ip_same_salt_differs(monkeypatch):
    _with_salt(monkeypatch, "salt-alpha")
    assert _client_ip.salted_ip_hash("203.0.113.7") != _client_ip.salted_ip_hash("203.0.113.8")


def test_digest_is_not_the_unsalted_form(monkeypatch):
    """The control that catches a silent revert to `sha256(ip)`."""
    _with_salt(monkeypatch, "salt-alpha")
    unsalted = hashlib.sha256(b"203.0.113.7").hexdigest()[:16]
    assert _client_ip.salted_ip_hash("203.0.113.7") != unsalted


def test_missing_salt_returns_none_and_logs(monkeypatch):
    _with_salt(monkeypatch, None)
    log = _Logger()
    assert _client_ip.salted_ip_hash("203.0.113.7", log) is None
    assert any("fail-closed" in m for m in log.errors)


def test_empty_salt_returns_none(monkeypatch):
    """An empty SecretString is the shape a half-provisioned secret takes."""
    _with_salt(monkeypatch, "")
    assert _client_ip.salted_ip_hash("203.0.113.7") is None


def test_default_logger_is_used_when_none_passed(monkeypatch):
    """`logger=None` must not raise — it falls back to the module's own logger."""
    _with_salt(monkeypatch, None)
    assert _client_ip.salted_ip_hash("203.0.113.7") is None  # no TypeError, no crash


def test_this_helper_reads_the_same_secret_name_as_the_engage_module():
    """The two independent implementations (see the module docstring in
    common/client_ip.py) must never drift onto different secrets."""
    from web import site_api_social_engage as _engage

    assert _client_ip._IP_HASH_SALT_SECRET_NAME == _engage._IP_HASH_SALT_SECRET_NAME
