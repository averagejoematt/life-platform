"""Every From address the platform can send is on an SES-verified domain (#3568).

WHY THIS EXISTS
  The sending vocabulary had two homes — a code default in each sender
  (`SENDER = os.environ.get("EMAIL_SENDER", <literal>)`) and a CDK env value —
  and nothing compared them to each other or to SES. They drifted:
  `between_chronicle_lambda.py` defaulted to `Elena Voss <elena@averagejoematt.com>`
  while `averagejoematt.com` was not an SES identity at all. `MessageRejected`
  was one CDK refactor away, and no test could see it.

  This is the derivation guard for `lambdas/common/email_identity.py`: every
  literal on both sides is resolved by AST and checked against the committed
  verified-domain set, and the reader-facing senders are additionally pinned to
  the site domain — because "verified" alone would happily accept reader mail
  going back out From the personal domain, which is the defect, not the fix.

WHAT WOULD MAKE THIS RED (it has been run against each):
  * a new sender address on a domain not in VERIFIED_SENDING_DOMAINS
  * a reader-facing sender moved off the site domain
  * the CDK value for a reader function disagreeing with the registry
  * the scan finding nothing (the vacuity control below)
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

import common.email_identity as _registry  # noqa: E402
from common.email_identity import (  # noqa: E402
    READER_FACING_SENDERS,
    SITE_DOMAIN,
    VERIFIED_SENDING_DOMAINS,
    is_verified_sender,
    sender_domain,
)

# Directories whose senders are real. `deploy/archive/` is dead code kept for
# history and is deliberately out of scope; so are test fixtures, which use
# example.com on purpose.
LAMBDA_ROOT = REPO / "lambdas"
CDK_STACKS = REPO / "cdk" / "stacks"


def _resolve(node: ast.AST) -> str | None:
    """A string literal, or a registry constant referenced by name."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return getattr(_registry, node.id, None) if isinstance(getattr(_registry, node.id, None), str) else None
    return None


def _code_defaults(tree: ast.AST) -> list[str]:
    """Every string default a module would use if EMAIL_SENDER were unset.

    Catches both shapes in the tree: `os.environ.get("EMAIL_SENDER", X)` and a
    bare `SENDER = "..."` with no env read at all (the operational senders).
    """
    found: list[str] = []
    for node in ast.walk(tree):
        # os.environ.get("EMAIL_SENDER", <default>)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2:
            first = _resolve(node.args[0])
            if first == "EMAIL_SENDER":
                got = _resolve(node.args[1])
                if got:
                    found.append(got)
        # SENDER = "literal" / EMAIL_SENDER = "literal"
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in ("SENDER", "EMAIL_SENDER"):
                    got = _resolve(node.value)
                    if got and "@" in got:
                        found.append(got)
    return found


def _cdk_sender_values(tree: ast.AST) -> list[str]:
    """Every resolvable value assigned to an "EMAIL_SENDER" dict key."""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "EMAIL_SENDER":
                got = _resolve(v)
                if got is None and isinstance(v, ast.BoolOp):  # try_get_context(...) or "literal"
                    for operand in v.values:
                        got = got or _resolve(operand)
                if got:
                    found.append(got)
    return found


def _cdk_reader_env() -> dict[str, str]:
    """{function_name: EMAIL_SENDER} for every create_platform_lambda call."""
    out: dict[str, str] = {}
    for path in sorted(CDK_STACKS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_platform_lambda"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            fname = _resolve(kw.get("function_name")) if kw.get("function_name") is not None else None
            if not fname or "environment" not in kw:
                continue
            for value in _cdk_sender_values(ast.Module(body=[ast.Expr(kw["environment"])], type_ignores=[])):
                out[fname] = value
    return out


def _all_code_defaults() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted(LAMBDA_ROOT.rglob("*.py")):
        got = _code_defaults(ast.parse(path.read_text()))
        if got:
            out[str(path.relative_to(REPO))] = got
    return out


# ─────────────────────────── the guard ───────────────────────────


def test_every_code_default_is_on_a_verified_domain():
    offenders = {path: [s for s in senders if not is_verified_sender(s)] for path, senders in _all_code_defaults().items()}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        "sender default(s) on a domain this account has not verified in SES.\n"
        f"verified: {sorted(VERIFIED_SENDING_DOMAINS)}\n"
        f"offenders: {offenders}\n"
        "Verify the domain (see lambdas/common/email_identity.py) or use a registry constant."
    )


def test_every_cdk_email_sender_is_on_a_verified_domain():
    offenders: dict[str, list[str]] = {}
    for path in sorted(CDK_STACKS.glob("*.py")):
        bad = [s for s in _cdk_sender_values(ast.parse(path.read_text())) if not is_verified_sender(s)]
        if bad:
            offenders[str(path.relative_to(REPO))] = bad
    assert not offenders, f"CDK EMAIL_SENDER on an unverified domain: {offenders}"


def test_reader_facing_functions_send_from_the_site_domain():
    """The point of the issue: a stranger's mail comes From the site, not a personal domain."""
    live = _cdk_reader_env()
    wrong = {}
    for fname, expected in READER_FACING_SENDERS.items():
        actual = live.get(fname)
        if actual != expected:
            wrong[fname] = {"expected": expected, "cdk": actual}
    assert not wrong, (
        "reader-facing function(s) whose CDK EMAIL_SENDER does not match the registry.\n"
        f"{wrong}\n"
        "Reader mail must be From the site domain — update cdk/stacks/*.py, not the registry."
    )
    for fname, expected in READER_FACING_SENDERS.items():
        assert sender_domain(expected) == SITE_DOMAIN, f"{fname}: registry value is off the site domain"


def test_reader_code_defaults_match_the_registry():
    """The code default and the CDK value are the same string, not merely both valid."""
    defaults = _all_code_defaults()
    reader_sources = {
        "lambdas/emails/chronicle_email_sender_lambda.py": READER_FACING_SENDERS["chronicle-email-sender"],
        "lambdas/emails/between_chronicle_lambda.py": READER_FACING_SENDERS["between-chronicle"],
        "lambdas/compute/weekly_signal_lambda.py": READER_FACING_SENDERS["weekly-signal"],
        "lambdas/web/email_subscriber_lambda.py": READER_FACING_SENDERS["email-subscriber"],
        "lambdas/web/subscriber_onboarding_lambda.py": READER_FACING_SENDERS["subscriber-onboarding"],
    }
    for path, expected in reader_sources.items():
        assert path in defaults, f"{path}: no EMAIL_SENDER default found — did the SENDER line move?"
        assert expected in defaults[path], f"{path}: default {defaults[path]} != registry {expected!r}"


# ──────────────────── controls: this gate can fail ────────────────────


def test_positive_control_the_scan_actually_finds_senders():
    """A scan that silently matched nothing would pass every assertion above."""
    defaults = _all_code_defaults()
    assert len(defaults) >= 10, f"only {len(defaults)} modules with an EMAIL_SENDER default — scanner likely broken"
    cdk_values = [v for p in CDK_STACKS.glob("*.py") for v in _cdk_sender_values(ast.parse(p.read_text()))]
    assert len(cdk_values) >= 5, f"only {len(cdk_values)} CDK EMAIL_SENDER values found — scanner likely broken"
    assert len(_cdk_reader_env()) >= 5, "create_platform_lambda walk found too few functions"


@pytest.mark.parametrize(
    "bad",
    [
        'SENDER = os.environ.get("EMAIL_SENDER", "reader@not-verified.example")',
        'SENDER = "plain@not-verified.example"',
    ],
)
def test_negative_control_an_unverified_default_is_caught(bad):
    """The must-fail case fails — on the same code path the real assertion uses."""
    found = _code_defaults(ast.parse(bad))
    assert found, f"scanner did not even see the default in: {bad}"
    assert not any(is_verified_sender(s) for s in found), "an unverified domain was accepted"


def test_negative_control_cdk_scanner_catches_unverified():
    src = 'env = {"EMAIL_SENDER": "ops@not-verified.example"}'
    found = _cdk_sender_values(ast.parse(src))
    assert found == ["ops@not-verified.example"]
    assert not is_verified_sender(found[0])


def test_sender_domain_parses_both_ses_forms():
    assert sender_domain("a@b.com") == "b.com"
    assert sender_domain("Display Name <a@b.com>") == "b.com"
    assert sender_domain("Odd <Name> <a@B.CoM>") == "b.com"
    assert sender_domain("no-at-sign") == ""
    assert not is_verified_sender("no-at-sign")
