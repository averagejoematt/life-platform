"""tests/test_monthly_close_secrets_reconciliation_3447.py — #3447 leg (d).

The R1 cost-surface secrets count (``tests/test_secret_references.KNOWN_SECRETS``,
lambdas/+mcp/ source scan) is a CODE-REFERENCE registry, not the live billable
Secrets Manager estate — the two have already drifted (28 registry vs 26 live
as of 2026-09-02; ``life-platform/github-billing`` is live+billed but referenced
only from ``deploy/``, outside the scan's scope). ``scripts/monthly_close.py``
now prints a read-only registry-vs-estate reconciliation at close; this file
proves the derivation (AST, never hand-restated) and the diffing logic both
directions, with AWS mocked (no live calls in CI).
"""

import pathlib
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import monthly_close as mc  # noqa: E402


def test_known_secrets_registry_derived_by_ast_matches_the_source_of_truth():
    """No hand-restated copy: this must read exactly what
    tests/test_secret_references.KNOWN_SECRETS holds."""
    from test_secret_references import KNOWN_SECRETS  # the module under test, imported directly for the control

    assert mc._known_secrets_registry() == KNOWN_SECRETS


def _paginate(names):
    class _Paginator:
        def paginate(self):
            yield {"SecretList": [{"Name": n} for n in names]}

    return _Paginator()


def test_reconciliation_finds_a_live_secret_with_no_registry_row():
    """The founding finding, reproduced: a live+billed secret referenced only
    from deploy/ (outside the KNOWN_SECRETS scan scope) is estate-only."""
    registry = {"life-platform/whoop", "life-platform/withings"}
    fake_client = mock.Mock()
    fake_client.get_paginator.return_value = _paginate(["life-platform/whoop", "life-platform/withings", "life-platform/github-billing"])
    with (
        mock.patch.object(mc, "_known_secrets_registry", return_value=registry),
        mock.patch.object(mc.boto3, "client", return_value=fake_client),
    ):
        got_registry, estate = mc._secrets_reconciliation()
    assert got_registry == registry
    estate_only = estate - got_registry
    assert estate_only == {"life-platform/github-billing"}


def test_reconciliation_finds_a_registry_row_with_no_live_secret():
    """A deferred/disarmed feature's row (e.g. a not-yet-provisioned secret)
    is registry-only — a real, but different, drift direction than (a)."""
    registry = {"life-platform/whoop", "life-platform/continuity-contacts"}
    fake_client = mock.Mock()
    fake_client.get_paginator.return_value = _paginate(["life-platform/whoop"])
    with (
        mock.patch.object(mc, "_known_secrets_registry", return_value=registry),
        mock.patch.object(mc.boto3, "client", return_value=fake_client),
    ):
        got_registry, estate = mc._secrets_reconciliation()
    registry_only = got_registry - estate
    assert registry_only == {"life-platform/continuity-contacts"}


def test_reconciliation_exact_agreement_is_quiet():
    """Negative control: registry and estate matching exactly must produce no
    diff in either direction."""
    registry = {"life-platform/whoop", "life-platform/withings"}
    fake_client = mock.Mock()
    fake_client.get_paginator.return_value = _paginate(sorted(registry))
    with (
        mock.patch.object(mc, "_known_secrets_registry", return_value=registry),
        mock.patch.object(mc.boto3, "client", return_value=fake_client),
    ):
        got_registry, estate = mc._secrets_reconciliation()
    assert got_registry - estate == set()
    assert estate - got_registry == set()
