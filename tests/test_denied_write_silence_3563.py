#!/usr/bin/env python3
"""tests/test_denied_write_silence_3563.py — a DENIED DynamoDB write must not be silent (#3563).

THE INCIDENT THIS GUARDS. Two fail-soft DynamoDB writes were refused by IAM for weeks and
nothing on the platform could see it:

  * `chronicle-email-sender::_record_email_send` — 3/3 sends from 2026-08-08 wrote the
    `email_log#wednesday_chronicle` row the public status page reads, 3/3 were
    AccessDenied, and the denial was logged at **INFO**. `/api/status` therefore reported
    the flagship weekly product as red / "46d ago" for four weeks while it shipped.
  * `life-platform-freshness-checker` — the #1480 journal-dark episode sentinel on the
    notion partition: 155 denials in 14 days, every run re-opening the episode into the
    digest, so the dedup that PR shipped had never once worked.

The grants are repaired in the same PR (`cdk/stacks/role_policies_email.py`,
`role_policies_operational.py`) and `tests/test_role_family_write_scope.py` is the parity
ratchet that keeps them repaired. THIS file guards the other half — the half that made a
four-week outage possible in the first place: **fail-soft is the right contract and it is
by construction silent**, so the swallowing path must emit something an instrument can see.
Both functions' only alarm is `AWS/Lambda Errors`, which needs a raised exception; a
swallowed denial is invisible to it by construction.

THE SHAPE (the #2654 twin, per `cdk/stacks/monitoring_silence_alarms.py`). The handler logs
a literal TOKEN at ERROR, a CloudWatch MetricFilter on that token mints a metric, an alarm
on the metric routes to the digest. The failure mode of that shape is DRIFT — the alarm
watches a string nothing writes any more — so the token is asserted from BOTH ends:

  1. the lambda constant is the string the `logger.error(...)` call actually interpolates
     (AST-read at the call site, not grepped anywhere near it), and the swallow is at
     ERROR, never INFO;
  2. `tests/cdk_alarm_pins.filter_tokens_for` finds the SAME token wired into an alarm,
     searching the whole `cdk/stacks/` tree and naming no file — and an empty result is a
     failure, so "the alarm was deleted" reds here rather than passing quietly.

Run:  python3 -m pytest tests/test_denied_write_silence_3563.py -v
"""

from __future__ import annotations

import ast
import os

import pytest
from cdk_alarm_pins import filter_tokens_for

# #416 / ADR-117: deploy-critical — this is the visibility half of an IAM-denial contract.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SENDER_SRC = os.path.join(ROOT, "lambdas", "emails", "chronicle_email_sender_lambda.py")
CHECKER_SRC = os.path.join(ROOT, "lambdas", "emails", "freshness_checker_lambda.py")

# (module, constant, alarm-name fragment, how many swallow sites must carry it)
TWINS = (
    (SENDER_SRC, "STATUS_WRITE_FAILED_TOKEN", "chronicle-status-write-failed", 1),
    (CHECKER_SRC, "SENTINEL_WRITE_FAILED_TOKEN", "freshness-sentinel-write-failed", 3),
)


def _tree(path: str) -> ast.AST:
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def _module_constant(path: str, name: str) -> str:
    """The string a module-level `NAME = "..."` binds, or fail naming the module."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == name and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise AssertionError(f"{os.path.relpath(path, ROOT)} no longer defines a string constant {name} — the twin has no lambda side")


def _logger_calls(path: str, name: str) -> list:
    """[(level, lineno)] for every `logger.<level>(...)` whose args mention `name`.

    Reads the CALL SITE, so a constant that is defined and then never used — the way a
    twin pin usually rots — is an empty list here, not a pass."""
    out = []
    for node in ast.walk(_tree(path)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        if any(isinstance(a, ast.Name) and a.id == name for a in node.args):
            out.append((node.func.attr, node.lineno))
    return out


@pytest.mark.parametrize("path,const,alarm_fragment,expected_sites", TWINS)
def test_the_swallowed_write_logs_the_token_at_error(path, const, alarm_fragment, expected_sites):
    """Leg 1: the lambda side. The token is real, it is USED, and it is ERROR not INFO."""
    token = _module_constant(path, const)
    assert token and token.isupper() and " " not in token, f"{const}={token!r} is not a filter-pattern-shaped literal"
    sites = _logger_calls(path, const)
    assert len(sites) == expected_sites, (
        f"{os.path.relpath(path, ROOT)}: expected {expected_sites} swallow site(s) logging {const}, found {len(sites)}: {sites}. "
        "A new fail-soft DynamoDB write in this module must carry the token too, or this alarm does not cover it."
    )
    bad = [(level, lineno) for level, lineno in sites if level not in ("error", "exception")]
    assert not bad, (
        f"{os.path.relpath(path, ROOT)}: a swallowed write logged at {bad} — #3563 IS the incident where an "
        "AccessDeniedException sat at INFO for four weeks. ERROR or nothing."
    )


@pytest.mark.parametrize("path,const,alarm_fragment,expected_sites", TWINS)
def test_the_metric_filter_watches_exactly_that_token(path, const, alarm_fragment, expected_sites):
    """Leg 2: the CDK side. Same token, wired into an alarm, found without naming a file."""
    tokens = filter_tokens_for(alarm_fragment)
    assert tokens, (
        f"no MetricFilter token is wired into an alarm named like {alarm_fragment!r} anywhere in cdk/stacks/ — "
        "the alarm was deleted or renamed, and the swallowed write is silent again (#3563)."
    )
    assert tokens == {_module_constant(path, const)}, (
        f"alarm {alarm_fragment!r} watches {sorted(tokens)} but the lambda logs "
        f"{_module_constant(path, const)!r} — the filter pattern and the handler have drifted apart."
    )


def test_both_alarms_are_distinct_and_neither_is_the_other():
    """A copy-paste that points both filters at one token would pass every assertion above
    per-parameter and leave one function unwatched. Asserted once, globally."""
    tokens = {const: _module_constant(path, const) for path, const, _frag, _n in TWINS}
    assert len(set(tokens.values())) == len(tokens), f"the two #3563 silence tokens collide: {tokens}"
