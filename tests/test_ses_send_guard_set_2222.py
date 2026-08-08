#!/usr/bin/env python3
"""tests/test_ses_send_guard_set_2222.py — the SET-level ratchet on the SES
send-suppressor gate (#2222).

#2216 fixed one module (`nutrition_review_lambda`) that could mail on any
invoke. #2222 is the observation that the *set* — every module in `lambdas/`
that defines a `lambda_handler` and sends through SES — had 18 members with no
suppressor at all, two of which mail third parties (`milestone_digest_lambda`
mails a friends-and-family list, `partner_email_lambda` mails an address
resolved from SSM at runtime). This is the repo's highest-recurrence defect
class: guard the SET, not the instance.

So this file does not carry a hand-written list of 18 module names — a hand
list rots at the 19th module. It **derives** the member set from source with an
AST walk and asserts every member routes its send through
`common.send_guard.guarded_send_email` (or is on one of two closed, justified
allowlists). A 19th SES-sending handler that ships without a suppressor fails
this file by name.

Non-vacuity is proved here too, not assumed: `derive_ses_sending_handlers` is
parameterised by root, so the tests below build synthetic trees containing a
deliberately-unguarded module and assert the derivation flags it — and a
guarded one, and a near-miss that imports the helper but still calls SES
directly. Three privacy screens shipped in this repo whose full suite passed
with the screen deleted; that is what those tests exist to prevent.

Everything here is offline: no module under test is imported, no AWS client is
constructed, and no Lambda is invoked.
"""

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
LAMBDAS = ROOT / "lambdas"
if str(LAMBDAS) not in sys.path:
    sys.path.insert(0, str(LAMBDAS))

from common import dry_run  # noqa: E402
from common.send_guard import DRY_RUN_MESSAGE_ID, guarded_send_email, is_dry_run  # noqa: E402

# The SES client methods that put mail on the wire.
SES_SEND_METHODS = frozenset({"send_email", "send_raw_email", "send_templated_email"})

# The sanctioned gate. A member of the set is guarded when every send goes
# through one of these AND the module derives the flag with `is_dry_run`.
GUARD_HELPERS = frozenset({"guarded_send_email", "guarded_send_raw_email"})

# How a module derives the flag from the invoke. Both the bare-name form
# (`is_dry_run(event)`) and the module-qualified form a write gate uses
# (`dry_run.stash(event)`) count — after #2255/#2222 converged on one
# vocabulary, a handler that already stashed the decision for its write gate
# must not be told to re-derive it for its send gate.
GUARD_FLAG_FNS = frozenset({"is_dry_run", "stash"})

# ── Allowlist 1: modules that already carried an equivalent, hand-rolled gate
# before #2222 and were left on it deliberately (converting them would be churn
# on working safety code). Each entry names the token that must still be
# present — a stale entry fails `test_pre_existing_guards_are_not_stale`.
PRE_EXISTING_GUARD = {
    "compute/weekly_signal_lambda.py": "dry_run",
    "emails/between_chronicle_lambda.py": "dry_run",
    "emails/chronicle_email_sender_lambda.py": "dry_run",
    "emails/coach_panel_podcast_lambda.py": "dry_run",
    "emails/daily_brief_lambda.py": "DRY_RUN",
    "emails/nutrition_review_lambda.py": "dry_run",  # #2216 owns this instance
    "emails/wednesday_chronicle_lambda.py": "PREVIEW_MODE",
}

# ── Allowlist 2: event-driven handlers, not scheduled ones. These send in
# direct response to a real-time action by a real person (a reader subscribing,
# an inbound email arriving), so an operator will never "invoke it to see what
# happens" the way they would with a scheduled digest — and a `dry_run` payload
# flag is arguably the wrong shape for them. #2222 excluded the first two by
# name; `insight_email_parser_lambda` is the same class and is excluded here on
# the same reasoning (see the module docstring of this file's PR).
EVENT_DRIVEN_EXEMPT = {
    "emails/insight_email_parser_lambda.py",
    "web/email_subscriber_lambda.py",
    "web/subscriber_onboarding_lambda.py",
}


@dataclass
class ModuleFacts:
    """What the AST walk found in one module."""

    rel: str
    direct_ses_lines: list = field(default_factory=list)
    guarded_lines: list = field(default_factory=list)
    derives_flag: bool = False

    @property
    def is_guarded_by_shared_helper(self) -> bool:
        """Fully routed through the shared gate: no raw send left, and the
        flag is actually derived from the invoke rather than hardcoded."""
        return not self.direct_ses_lines and bool(self.guarded_lines) and self.derives_flag


def derive_ses_sending_handlers(root: Path) -> dict:
    """Every module under `root` that defines a `lambda_handler` AND sends mail.

    "Sends mail" = calls one of `SES_SEND_METHODS` on any object, or calls one
    of the shared `GUARD_HELPERS`. The second clause is load-bearing: once a
    module is converted, its raw `ses.send_email` disappears, and a derivation
    that only looked for raw sends would quietly stop covering it.
    """
    found = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a broken file is another gate's problem
            continue

        has_handler = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "lambda_handler" for n in tree.body)
        if not has_handler:
            continue

        facts = ModuleFacts(rel=path.relative_to(root).as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in SES_SEND_METHODS:
                facts.direct_ses_lines.append(node.lineno)
            elif isinstance(func, ast.Attribute) and func.attr in GUARD_FLAG_FNS:
                facts.derives_flag = True  # `dry_run.stash(event)` / `dry_run.is_dry_run(event)`
            elif isinstance(func, ast.Name):
                if func.id in GUARD_HELPERS:
                    facts.guarded_lines.append(node.lineno)
                elif func.id in GUARD_FLAG_FNS:
                    facts.derives_flag = True

        if facts.direct_ses_lines or facts.guarded_lines:
            found[facts.rel] = facts
    return found


@pytest.fixture(scope="module")
def derived():
    return derive_ses_sending_handlers(LAMBDAS)


# ──────────────────────────────────────────────────────────────────────────
# The ratchet
# ──────────────────────────────────────────────────────────────────────────


def test_derivation_finds_the_real_set(derived):
    """Sanity floor: the walk actually sees the platform's email fleet.

    Without this, a derivation bug that returned {} would make every other
    assertion in this file pass vacuously.
    """
    assert len(derived) >= 25, f"derivation found only {len(derived)} SES-sending handlers — the walk is broken"
    for expected in ("emails/milestone_digest_lambda.py", "emails/partner_email_lambda.py", "emails/weekly_plate_lambda.py"):
        assert expected in derived, f"{expected} vanished from the derived set"


def test_every_ses_sending_handler_honors_a_suppressor(derived):
    """THE test. Every SES-sending Lambda handler in `lambdas/` can be invoked
    without mailing anyone — via the shared gate, or via a named exception."""
    unguarded = []
    for rel, facts in sorted(derived.items()):
        if rel in EVENT_DRIVEN_EXEMPT or rel in PRE_EXISTING_GUARD:
            continue
        if not facts.is_guarded_by_shared_helper:
            unguarded.append(f"{rel} (raw SES sends at lines {facts.direct_ses_lines or '—'}; derives_flag={facts.derives_flag})")
    assert not unguarded, (
        "SES-sending Lambda handlers with no send-suppressor — invoking one of these mails real people.\n"
        "Route the send through common.send_guard.guarded_send_email(client, dry_run, ...) and derive\n"
        "dry_run with is_dry_run(event); see #2222.\n  " + "\n  ".join(unguarded)
    )


def test_tier_a_third_party_mailers_use_the_shared_gate(derived):
    """The two modules that mail somebody other than the operator get named
    explicitly — their regression is a disclosure, not an inbox annoyance."""
    for rel in ("emails/milestone_digest_lambda.py", "emails/partner_email_lambda.py"):
        facts = derived[rel]
        assert facts.is_guarded_by_shared_helper, f"{rel} mails a third party and is not on the shared send gate"


def test_corrected_entries_are_in_the_set_and_gated(derived):
    """#2222 corrected an earlier pass that had miscategorised these two as
    already-guarded. They must not silently fall out of the set again."""
    for rel in ("operational/traffic_digest_lambda.py", "operational/dlq_consumer_lambda.py"):
        assert rel in derived, f"{rel} left the derived set"
        assert derived[rel].is_guarded_by_shared_helper, f"{rel} is in the set but not gated"


def test_pre_existing_guards_are_not_stale(derived):
    """The hand-rolled-guard allowlist is closed and must stay honest: every
    entry still exists, is still in the derived set, and still carries the
    token it was allowlisted for."""
    for rel, token in PRE_EXISTING_GUARD.items():
        assert rel in derived, f"PRE_EXISTING_GUARD entry {rel} is no longer an SES-sending handler — drop it"
        src = (LAMBDAS / rel).read_text(encoding="utf-8")
        assert token in src, f"{rel} was allowlisted for its {token!r} gate and no longer contains it"


def test_event_driven_exemptions_are_not_stale(derived):
    for rel in EVENT_DRIVEN_EXEMPT:
        assert rel in derived, f"EVENT_DRIVEN_EXEMPT entry {rel} is no longer an SES-sending handler — drop it"


# ──────────────────────────────────────────────────────────────────────────
# Non-vacuity: the derivation must FAIL on a broken tree
# ──────────────────────────────────────────────────────────────────────────

_UNGUARDED = """
import boto3
ses = boto3.client("sesv2")

def lambda_handler(event, context):
    ses.send_email(FromEmailAddress="a@b.c", Destination={"ToAddresses": ["d@e.f"]})
    return {"statusCode": 200}
"""

_GUARDED = """
import boto3
from common.send_guard import guarded_send_email, is_dry_run
ses = boto3.client("sesv2")

def lambda_handler(event, context):
    dry_run = is_dry_run(event)
    guarded_send_email(ses, dry_run, FromEmailAddress="a@b.c", Destination={"ToAddresses": ["d@e.f"]})
    return {"statusCode": 200}
"""

_HALF_CONVERTED = """
import boto3
from common.send_guard import guarded_send_email, is_dry_run
ses = boto3.client("sesv2")

def lambda_handler(event, context):
    dry_run = is_dry_run(event)
    guarded_send_email(ses, dry_run, FromEmailAddress="a@b.c", Destination={"ToAddresses": ["d@e.f"]})
    ses.send_email(FromEmailAddress="a@b.c", Destination={"ToAddresses": ["oops@e.f"]})
    return {"statusCode": 200}
"""

_HARDCODED_FLAG = """
import boto3
from common.send_guard import guarded_send_email
ses = boto3.client("sesv2")

def lambda_handler(event, context):
    guarded_send_email(ses, False, FromEmailAddress="a@b.c", Destination={"ToAddresses": ["d@e.f"]})
    return {"statusCode": 200}
"""

_NO_HANDLER = """
import boto3
ses = boto3.client("sesv2")

def send_it():
    ses.send_email(FromEmailAddress="a@b.c")
"""


def _tree(tmp_path, **modules):
    for name, src in modules.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return derive_ses_sending_handlers(tmp_path)


def test_mutation_an_unguarded_module_is_caught(tmp_path):
    """Inject a 19th SES-sending handler with no suppressor: the derivation
    must find it AND classify it unguarded. If this passes when it shouldn't,
    every assertion above is decoration."""
    found = _tree(tmp_path, **{"emails/rogue_lambda.py": _UNGUARDED})
    assert "emails/rogue_lambda.py" in found
    assert not found["emails/rogue_lambda.py"].is_guarded_by_shared_helper


def test_mutation_a_guarded_module_is_accepted(tmp_path):
    """Positive control — the guard must not simply flag everything."""
    found = _tree(tmp_path, **{"emails/good_lambda.py": _GUARDED})
    assert found["emails/good_lambda.py"].is_guarded_by_shared_helper


def test_mutation_a_half_converted_module_is_caught(tmp_path):
    """The realistic regression: someone routes one send through the gate and
    leaves a second raw `ses.send_email` behind. Importing the helper is not
    the property under test — every send going through it is."""
    found = _tree(tmp_path, **{"emails/half_lambda.py": _HALF_CONVERTED})
    assert not found["emails/half_lambda.py"].is_guarded_by_shared_helper


def test_mutation_a_hardcoded_flag_is_caught(tmp_path):
    """`guarded_send_email(ses, False, ...)` mails on every invoke. The flag has
    to be derived from the event, so the module must call `is_dry_run`."""
    found = _tree(tmp_path, **{"emails/hardcoded_lambda.py": _HARDCODED_FLAG})
    assert not found["emails/hardcoded_lambda.py"].is_guarded_by_shared_helper


def test_derivation_ignores_modules_without_a_handler(tmp_path):
    """Scope control: a library that sends mail on behalf of a handler is not
    itself invocable, so it is not a member of the set."""
    found = _tree(tmp_path, **{"emails/helper_only.py": _NO_HANDLER})
    assert found == {}


# ──────────────────────────────────────────────────────────────────────────
# The helper itself
# ──────────────────────────────────────────────────────────────────────────


class _FakeSes:
    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "real-send"}

    def send_raw_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "real-raw-send"}


# ──────────────────────────────────────────────────────────────────────────
# One definition of "dry run" — the SES gate and the write gate must agree
#
# #2255 (daily brief) and #2222 (the SES set) each shipped a module that
# answers "is this invocation a dry run", with different vocabularies. The
# divergence was not cosmetic: `{"no_send": true}` suppressed 17 Lambdas and
# was silently ignored by the brief, which sent for real; `{"force_send": true}`
# was honoured by the brief and ignored by the 17. `send_guard.is_dry_run` now
# delegates to `common.dry_run`, and these tests are the property that stops
# them drifting apart again — neither PR could have had them alone.
# ──────────────────────────────────────────────────────────────────────────

_AGREEMENT_EVENTS = [
    {},
    None,
    [{"Records": []}],  # a non-mapping event must not raise on either side
    {"dry_run": True},
    {"dry_run": False},
    {"dry_run": "true"},
    {"dry_run": "false"},
    {"dry_run": "0"},
    {"dryRun": True},
    {"no_send": True},
    {"preview_mode": True},
    {"test_mode": True},
    {"detail": {"dry_run": True}},
    {"detail": {"no_send": True}},
    {"force_send": True},
    {"dry_run": True, "force_send": True},
    {dry_run.FLAG: True},  # a decision an earlier gate already stashed
    {dry_run.FLAG: False, "dry_run": True},  # the stash wins — one decision per invoke
]

_AGREEMENT_ENVS = [{}, {"DRY_RUN": "true"}, {"DRY_RUN": "false"}, {"NO_SEND": "1"}, {"PREVIEW_MODE": "yes"}]


@pytest.mark.parametrize("env", _AGREEMENT_ENVS)
@pytest.mark.parametrize("event", _AGREEMENT_EVENTS)
def test_the_send_gate_and_the_write_gate_never_disagree(event, env, monkeypatch):
    """There is no event for which mail is suppressed but writes are not (or
    vice versa). `persistence_enabled` is the write half of the same decision,
    so with `demo_mode` off it must be the exact negation of the send half."""
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    suppresses_mail = is_dry_run(event)
    may_write = dry_run.persistence_enabled(event, demo_mode=False)
    assert suppresses_mail is not may_write, f"send gate and write gate disagree for event={event!r} env={env!r}"


@pytest.mark.parametrize("key", list(dry_run.SUPPRESSOR_EVENT_KEYS))
def test_every_alias_in_the_vocabulary_suppresses_both_halves(key, monkeypatch):
    """Derived from the vocabulary itself, so a 6th alias added to
    `common.dry_run` is automatically required to work on both halves — the
    exact failure this convergence fixes."""
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    event = {key: True}
    assert is_dry_run(event) is True, f"{key!r} is in the vocabulary but does not suppress sends"
    assert dry_run.persistence_enabled(event) is False, f"{key!r} is in the vocabulary but does not suppress writes"


@pytest.mark.parametrize("name", list(dry_run.SUPPRESSOR_ENV_VARS))
def test_every_env_var_in_the_vocabulary_suppresses_both_halves(name, monkeypatch):
    for other in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(name, "true")
    assert is_dry_run({}) is True
    assert dry_run.persistence_enabled({}) is False


def test_force_send_overrides_the_environment_on_both_halves(monkeypatch):
    """An operator's one-off real send must behave the same whichever Lambda
    they invoke — this was honoured by the brief and ignored by the 17."""
    monkeypatch.setenv("DRY_RUN", "true")
    assert is_dry_run({"force_send": True}) is False
    assert dry_run.persistence_enabled({"force_send": True}) is True


def test_an_explicit_suppressor_outranks_force_send(monkeypatch):
    """Asking for both is a mistake; the safe reading of a mistake is "do not
    send". Both halves must read it the same way."""
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    event = {"dry_run": True, "force_send": True}
    assert is_dry_run(event) is True
    assert dry_run.persistence_enabled(event) is False


def test_send_guard_does_not_define_its_own_resolution():
    """The delegation is the point. If `send_guard` regrows a vocabulary, the
    two halves can diverge again without any test above noticing."""
    import common.send_guard as sg

    for leaked in ("SUPPRESSOR_EVENT_KEYS", "SUPPRESSOR_ENV_VARS", "_FALSEY_STRINGS", "_truthy"):
        assert not hasattr(sg, leaked), f"send_guard re-grew its own flag resolution ({leaked}) — delegate to common.dry_run"


def test_resolve_rejects_the_string_false(monkeypatch):
    """`resolve` used plain truthiness before this PR, so `{"dry_run": "false"}`
    — the shape a hand-typed console payload produces — read as a dry run and
    silently disabled the send it was meant to permit."""
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for falsey in ("false", "False", "0", "no", "off", "", "  "):
        assert dry_run.resolve({"dry_run": falsey}) is False, f"{falsey!r} read as a dry run"
    for truthy in ("true", "True", "1", "yes"):
        assert dry_run.resolve({"dry_run": truthy}) is True


@pytest.mark.parametrize(
    "event,expected",
    [
        ({}, False),
        (None, False),
        ([{"Records": 1}], False),  # a non-mapping event must not raise
        ({"dry_run": True}, True),
        ({"dryRun": True}, True),
        ({"dry_run": "true"}, True),
        ({"dry_run": "false"}, False),  # a string "false" is NOT a dry run
        ({"dry_run": "0"}, False),
        ({"dry_run": False}, False),
        ({"no_send": 1}, True),
        ({"preview_mode": True}, True),
        ({"test_mode": True}, True),
        ({"detail": {"dry_run": True}}, True),  # EventBridge wrapper
        ({"detail": {"other": True}}, False),
    ],
)
def test_is_dry_run_event_shapes(event, expected, monkeypatch):
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert is_dry_run(event) is expected


def test_is_dry_run_reads_the_environment(monkeypatch):
    """Scheduled rules do not let an operator pass a payload; the env var is
    the escape hatch for those."""
    monkeypatch.setenv("DRY_RUN", "true")
    assert is_dry_run({}) is True
    monkeypatch.setenv("DRY_RUN", "false")
    assert is_dry_run({}) is False


def test_guarded_send_suppresses_and_reports(capsys):
    ses = _FakeSes()
    resp = guarded_send_email(
        ses,
        True,
        FromEmailAddress="from@example.invalid",
        Destination={"ToAddresses": ["friend@example.invalid"]},
        Content={"Simple": {"Subject": {"Data": "hello"}}},
    )
    assert ses.sends == [], "a dry run reached SES"
    assert resp["MessageId"] == DRY_RUN_MESSAGE_ID
    out = capsys.readouterr().out
    assert "friend@example.invalid" in out and "hello" in out, "the dry run did not say what it suppressed"


def test_guarded_send_still_sends_when_not_dry():
    """The other half of the contract — a normal invoke must still mail."""
    ses = _FakeSes()
    resp = guarded_send_email(ses, False, FromEmailAddress="a@b.invalid", Destination={"ToAddresses": ["c@d.invalid"]})
    assert len(ses.sends) == 1
    assert resp["MessageId"] == "real-send"
