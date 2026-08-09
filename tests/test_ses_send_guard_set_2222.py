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

**The exemption axis (#2291, decided): TRIGGER TYPE, not recipient consent.**
The guard's purpose is operator-invocation safety — "will invoking this by hand
mail someone?" — and a recipient's consent doesn't change what a stray manual
invoke does. A module may therefore be exempt from DEFAULT dry-run suppression
only when its sends are caused by an external event (an inbound email arriving,
a reader's HTTP request), never by a schedule. The exempt set is no longer a
hand-typed list: each exempt module DECLARES `SES_EXEMPT_EVENT_DRIVEN = "<one-line
reason naming its external trigger>"` at module level, this file derives the set
from that marker, asserts each marker-carrying module still sends SES mail (a
stale exemption fails), and asserts its function carries NO EventBridge
`schedule=` in cdk/stacks/ (a scheduled function claiming the exemption fails).
Per-module verdicts:
  - emails/insight_email_parser_lambda.py — STAYS exempt (SES receipt rule →
    S3 → Lambda). #2222 never reviewed this one; reviewed now, same axis.
  - web/email_subscriber_lambda.py — STAYS exempt (reader HTTP request via the
    CloudFront /api/subscribe* Function URL).
  - web/subscriber_onboarding_lambda.py — exemption REVOKED: it is EventBridge-
    scheduled (cron(5 17 * * ? *), email_stack.py), so #2222's "event-driven"
    reasoning was factually wrong for it. It now uses the shared suppressor.
Exempt modules still honor an EXPLICIT `{"dry_run": true}` payload (sends
suppressed via the shared helper, would-have-sent summary reported) — behavior
tested handler-level in tests/test_ses_event_driven_exempt_2291.py.

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

# ── Allowlist 2 (#2291): event-driven handlers, not scheduled ones — no longer
# a hand-typed list. Each exempt module declares the marker below at module
# level with a one-line reason naming its external trigger; the set is DERIVED
# from source (see `derive_event_driven_exemptions`), each member must still be
# an SES-sending handler (stale exemptions fail), and each member's function
# must carry NO EventBridge schedule= in cdk/stacks/ (a scheduled function
# claiming the exemption fails — that is exactly how subscriber_onboarding's
# wrong exemption was caught). Note the exemption no longer waives the shared
# gate: exempt modules must STILL honor an explicit {"dry_run": true} payload
# through `guarded_send_email`; what they are exempt from is only the "an
# operator will invoke this by hand" default posture — their trigger is an
# external event, so a schedule appearing on one is a classification change
# that must be re-reviewed.
EXEMPT_MARKER = "SES_EXEMPT_EVENT_DRIVEN"
CDK_STACKS = ROOT / "cdk" / "stacks"


def derive_event_driven_exemptions(root: Path) -> dict:
    """Every module under `root` declaring `SES_EXEMPT_EVENT_DRIVEN = "<reason>"`
    at module (top) level. Returns {rel_path: reason}."""
    found = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a broken file is another gate's problem
            continue
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            if EXEMPT_MARKER in targets:
                value = node.value
                reason = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else ""
                found[path.relative_to(root).as_posix()] = reason
    return found


def cdk_schedule_facts(module_rel: str, cdk_root: Path) -> dict:
    """Whether cdk stacks define a Lambda for `lambdas/<module_rel>`, and where
    a `schedule=` keyword is attached to that definition.

    Text-derived from the CDK source (AST): every Call carrying a
    `source_file="lambdas/<module_rel>"` keyword is this module's function
    definition; a `schedule=` keyword on it (other than a literal None) makes
    the function EventBridge-scheduled."""
    source_literal = f"lambdas/{module_rel}"
    facts = {"defined_in": [], "scheduled_at": []}
    for path in sorted(cdk_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kws = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            sf = kws.get("source_file")
            if not (isinstance(sf, ast.Constant) and sf.value == source_literal):
                continue
            facts["defined_in"].append(f"{path.name}:{node.lineno}")
            sched = kws.get("schedule")
            if sched is not None and not (isinstance(sched, ast.Constant) and sched.value is None):
                facts["scheduled_at"].append(f"{path.name}:{node.lineno}")
    return facts


EVENT_DRIVEN_EXEMPT = frozenset(derive_event_driven_exemptions(LAMBDAS))


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
        if rel in PRE_EXISTING_GUARD:
            continue
        # #2291: EVENT_DRIVEN_EXEMPT members are deliberately NOT skipped here —
        # the exemption covers default posture, not the gate itself. Since they
        # must honor an explicit {"dry_run": true}, they route through the
        # shared helper like everyone else.
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
    """A marker on a module that no longer sends SES is a stale exemption; a
    marker with no stated reason is an undeclared one. Both fail."""
    exemptions = derive_event_driven_exemptions(LAMBDAS)
    for rel, reason in exemptions.items():
        assert rel in derived, f"{EXEMPT_MARKER} marker on {rel}, but it is no longer an SES-sending handler — remove the marker"
        assert reason.strip(), f"{EXEMPT_MARKER} on {rel} must carry a one-line reason naming its external trigger"


def test_exemption_covers_the_known_event_driven_pair(derived):
    """Sanity floor for the derivation (mirrors test_derivation_finds_the_real_set):
    the two genuinely event-driven senders carry the marker, and the module whose
    #2222 exemption was WRONG — subscriber_onboarding is EventBridge-scheduled —
    does not."""
    assert "emails/insight_email_parser_lambda.py" in EVENT_DRIVEN_EXEMPT
    assert "web/email_subscriber_lambda.py" in EVENT_DRIVEN_EXEMPT
    assert (
        "web/subscriber_onboarding_lambda.py" not in EVENT_DRIVEN_EXEMPT
    ), "subscriber_onboarding is scheduled (email_stack.py) — it must use the shared suppressor, not the event-driven exemption (#2291)"


def test_exempt_modules_are_genuinely_event_driven(derived):
    """THE #2291 rule: a module claiming the trigger-type exemption must have a
    CDK-defined function with NO EventBridge schedule=. A schedule appearing on
    an exempt function is a classification change and must fail loudly."""
    for rel in sorted(EVENT_DRIVEN_EXEMPT):
        facts = cdk_schedule_facts(rel, CDK_STACKS)
        assert facts["defined_in"], f"{rel} claims {EXEMPT_MARKER} but no cdk/stacks definition was found — cannot verify its trigger"
        assert not facts["scheduled_at"], (
            f"{rel} claims the event-driven exemption but its function is EventBridge-scheduled at {facts['scheduled_at']} — "
            "a scheduled sender must use the DEFAULT dry-run suppression (#2291)"
        )


def test_exempt_modules_still_route_through_the_shared_gate(derived):
    """The exemption is about default posture, never about the gate: an exempt
    module must still honor an explicit {'dry_run': true} payload, which means
    every send routes through the shared helper and the flag is derived from
    the event. (Handler-level behavior — SES mock uncalled under dry_run —
    is tested in tests/test_ses_event_driven_exempt_2291.py.)"""
    for rel in sorted(EVENT_DRIVEN_EXEMPT):
        facts = derived[rel]
        assert facts.is_guarded_by_shared_helper, (
            f"{rel} is event-driven-exempt but does not route every send through guarded_send_email with a derived flag — "
            "explicit dry_run would be undefined behavior again (#2291)"
        )


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
# Non-vacuity for the #2291 exemption machinery
# ──────────────────────────────────────────────────────────────────────────

_EXEMPT_GUARDED = _GUARDED.replace(
    "def lambda_handler",
    'SES_EXEMPT_EVENT_DRIVEN = "synthetic external trigger for the mutation test"\n\ndef lambda_handler',
)

_EXEMPT_NO_SES = """
SES_EXEMPT_EVENT_DRIVEN = "a marker left behind after the sends were removed"

def lambda_handler(event, context):
    return {"statusCode": 200}
"""

_EXEMPT_EMPTY_REASON = _GUARDED.replace(
    "def lambda_handler",
    'SES_EXEMPT_EVENT_DRIVEN = ""\n\ndef lambda_handler',
)

_CDK_UNSCHEDULED = """
def build(scope):
    create_platform_lambda(
        scope,
        "SyntheticFn",
        function_name="synthetic-fn",
        source_file="lambdas/emails/synthetic_lambda.py",
        handler="emails.synthetic_lambda.lambda_handler",
    )
"""

_CDK_SCHEDULED = """
def build(scope):
    create_platform_lambda(
        scope,
        "SyntheticFn",
        function_name="synthetic-fn",
        source_file="lambdas/emails/synthetic_lambda.py",
        handler="emails.synthetic_lambda.lambda_handler",
        schedule="cron(0 17 * * ? *)",
    )
"""


def _cdk_tree(tmp_path, src):
    cdk_dir = tmp_path / "cdk_stacks"
    cdk_dir.mkdir(parents=True, exist_ok=True)
    (cdk_dir / "synthetic_stack.py").write_text(src, encoding="utf-8")
    return cdk_dir


def test_mutation_marker_derivation_finds_a_declared_exemption(tmp_path):
    """Positive control: a module-level marker with a reason is derived."""
    (tmp_path / "emails").mkdir(parents=True, exist_ok=True)
    (tmp_path / "emails" / "synthetic_lambda.py").write_text(_EXEMPT_GUARDED, encoding="utf-8")
    exemptions = derive_event_driven_exemptions(tmp_path)
    assert exemptions == {"emails/synthetic_lambda.py": "synthetic external trigger for the mutation test"}


def test_mutation_a_stale_marker_is_caught(tmp_path):
    """A marker on a module that no longer sends SES must be flagged: it is in
    the exemption derivation but NOT in the SES-sender derivation — exactly the
    condition test_event_driven_exemptions_are_not_stale asserts on the real
    tree."""
    (tmp_path / "emails").mkdir(parents=True, exist_ok=True)
    (tmp_path / "emails" / "synthetic_lambda.py").write_text(_EXEMPT_NO_SES, encoding="utf-8")
    exemptions = derive_event_driven_exemptions(tmp_path)
    derived = derive_ses_sending_handlers(tmp_path)
    assert "emails/synthetic_lambda.py" in exemptions
    assert "emails/synthetic_lambda.py" not in derived, "stale marker module must NOT count as an SES sender"


def test_mutation_an_empty_reason_is_caught(tmp_path):
    """The marker's value IS the recorded decision — an empty string is an
    undeclared exemption and must fail the reason assertion."""
    (tmp_path / "emails").mkdir(parents=True, exist_ok=True)
    (tmp_path / "emails" / "synthetic_lambda.py").write_text(_EXEMPT_EMPTY_REASON, encoding="utf-8")
    exemptions = derive_event_driven_exemptions(tmp_path)
    assert exemptions["emails/synthetic_lambda.py"].strip() == ""


def test_mutation_a_schedule_added_to_an_exempt_function_is_caught(tmp_path):
    """#2291 mutation-proof (a): add a schedule= to an exempt function's CDK
    definition in a scratch tree — the schedule check must flag it. This is the
    exact mutation that revealed subscriber_onboarding's exemption was wrong."""
    facts = cdk_schedule_facts("emails/synthetic_lambda.py", _cdk_tree(tmp_path, _CDK_SCHEDULED))
    assert facts["defined_in"], "the synthetic CDK definition must be found"
    assert facts["scheduled_at"], "a schedule= on the definition must be detected"


def test_mutation_an_unscheduled_exempt_function_is_accepted(tmp_path):
    """Positive control — the schedule check must not flag every definition."""
    facts = cdk_schedule_facts("emails/synthetic_lambda.py", _cdk_tree(tmp_path, _CDK_UNSCHEDULED))
    assert facts["defined_in"]
    assert not facts["scheduled_at"]


def test_mutation_a_missing_cdk_definition_is_caught(tmp_path):
    """An exempt module with no CDK definition at all cannot have its trigger
    verified — the real-tree test fails on empty defined_in."""
    facts = cdk_schedule_facts("emails/some_other_lambda.py", _cdk_tree(tmp_path, _CDK_UNSCHEDULED))
    assert not facts["defined_in"]


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
