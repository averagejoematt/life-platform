"""tests/test_inbound_auth_gate_4633.py — the inbound-email door's sender-authentication verdict (#4633).

The 2026-10-04 data-source sweep found the one mail-fed capture path authenticated by a header allowlist alone: the
hand-made receipt rule stored every message, the S3 notification fired the parser regardless of SES's own verdicts,
and the allowlist carried a hardcoded fallback address in a public repository.

What this pins:
  * the receipt gate (lambdas/emails/inbound_auth_gate_lambda.py, the SES rule's first action, RequestResponse):
    CONTINUE only on an aligned DMARC PASS + no spam/virus FAIL + a listed From; STOP_RULE_SET on everything else,
    including a missing verdict, a missing receipt, an empty event and an unset allowlist — and its [REJECT] line
    carries no address (it is the line the issue's live proof pastes);
  * the parser refuses an ALLOWED_SENDERS message whose SES verdict is missing or failing (defence in depth), on EVERY
    route — insight, review-pack correction, Story Desk reply — and an SES-direct record on its receipt verdicts
    before the S3 read;
  * with the allowlist unset the parser fails closed and writes nothing;
  * no fallback address remains in source, and every record-writing call in the parser sits below the verdict.

Fixtures are the real SES shapes (the receipt-rule Lambda event as SES documents it; the Authentication-Results
header as SES wrote it on a real inbound message, read 2026-10-10) with every address swapped for .invalid.
Fully offline: fake S3 / DDB / CloudWatch / SES; no AWS, no network, no mail sent.
"""

import ast
import copy
import io
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from content import story_questions as sq  # noqa: E402
from emails import (
    inbound_auth_gate_lambda as gate,  # noqa: E402
    insight_email_parser_lambda as iep,  # noqa: E402
)

OWNER_ADDR = "owner@example.invalid"  # stands in for an ALLOWED_SENDERS address
DESK_ADDR = "desk-inbox@example.invalid"  # stands in for a STORY_REPLY_SENDERS address
STRANGER = "someone@elsewhere.invalid"
INBOUND = "insight@aws.example.invalid"

# ── the SES receipt-rule Lambda event, as SES documents it (addresses redacted) ──────────────────────────────────────
RECEIPT_EVENT = {
    "Records": [
        {
            "eventSource": "aws:ses",
            "eventVersion": "1.0",
            "ses": {
                "mail": {
                    "timestamp": "2026-10-11T17:00:00.000Z",
                    "source": OWNER_ADDR,
                    "messageId": "o3vrnil0e2ic28tr",
                    "destination": [INBOUND],
                    "headersTruncated": False,
                    "headers": [
                        {"name": "Return-Path", "value": f"<{OWNER_ADDR}>"},
                        {"name": "From", "value": f"Matthew <{OWNER_ADDR}>"},
                        {"name": "To", "value": INBOUND},
                        {"name": "Subject", "value": "Re: Daily Brief"},
                    ],
                    "commonHeaders": {
                        "returnPath": OWNER_ADDR,
                        "from": [f"Matthew <{OWNER_ADDR}>"],
                        "date": "Sat, 11 Oct 2026 10:00:00 -0700",
                        "to": [INBOUND],
                        "messageId": "<CA+x@mail.example.invalid>",
                        "subject": "Re: Daily Brief",
                    },
                },
                "receipt": {
                    "timestamp": "2026-10-11T17:00:00.000Z",
                    "processingTimeMillis": 574,
                    "recipients": [INBOUND],
                    "spamVerdict": {"status": "PASS"},
                    "virusVerdict": {"status": "PASS"},
                    "spfVerdict": {"status": "PASS"},
                    "dkimVerdict": {"status": "PASS"},
                    "dmarcVerdict": {"status": "PASS"},
                    "dmarcPolicy": "quarantine",
                    "action": {
                        "type": "Lambda",
                        "functionArn": "arn:aws:lambda:us-west-2:000000000000:function:inbound-auth-gate",
                        "invocationType": "RequestResponse",
                    },
                },
            },
        }
    ]
}


def _event(**overrides):
    """A deep copy of the documented event with receipt verdicts / From overridden: dmarc="FAIL", sender="x@y"."""
    ev = copy.deepcopy(RECEIPT_EVENT)
    rec = ev["Records"][0]["ses"]
    for k, v in overrides.items():
        if k == "sender":
            rec["mail"]["commonHeaders"]["from"] = [v]
        elif k == "receipt":
            rec["receipt"] = v
        else:
            rec["receipt"][f"{k}Verdict"] = {"status": v}
    return ev


@pytest.fixture
def listed(monkeypatch):
    monkeypatch.setenv("ALLOWED_SENDERS", OWNER_ADDR)
    monkeypatch.setenv("STORY_REPLY_SENDERS", DESK_ADDR)


# ── the gate ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_an_authenticated_listed_sender_continues(listed, capsys):
    assert gate.lambda_handler(_event(), None) == {"disposition": "CONTINUE"}
    out = capsys.readouterr().out
    assert "[PASS]" in out and "messageId=o3vrnil0e2ic28tr" in out and "dmarc=PASS" in out


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"dmarc": "FAIL"}, "dmarc_fail"),
        ({"dmarc": "GRAY"}, "dmarc_gray"),  # no policy published = not authenticated, not "probably fine"
        ({"dmarc": "PROCESSING_FAILED"}, "dmarc_processing_failed"),
        ({"receipt": {}}, "dmarc_missing"),  # no verdicts at all
        ({"receipt": {"dmarcVerdict": {}}}, "dmarc_missing"),  # a verdict object with no status
        ({"virus": "FAIL"}, "virusVerdict_fail"),
        ({"spam": "FAIL"}, "spamVerdict_fail"),
        ({"spam": "PROCESSING_FAILED"}, "spamVerdict_processing_failed"),
    ],
)
def test_a_failing_or_missing_verdict_stops_the_rule_set(listed, capsys, overrides, reason):
    assert gate.lambda_handler(_event(**overrides), None) == {"disposition": "STOP_RULE_SET"}
    out = capsys.readouterr().out
    assert f"[REJECT] inbound message refused at the receipt gate: messageId=o3vrnil0e2ic28tr reason={reason} " in out
    assert "STOP_RULE_SET, nothing stored" in out


def test_the_reject_line_carries_no_address_and_names_every_verdict(listed, capsys):
    gate.lambda_handler(_event(dmarc="FAIL", dkim="GRAY", spf="FAIL"), None)
    out = capsys.readouterr().out
    assert "@" not in out, "the live-proof line is pasted into a public issue — never an address"
    assert "spf=FAIL dkim=GRAY dmarc=FAIL spam=PASS virus=PASS" in out


def test_dkim_alone_is_not_enough_at_the_gate(listed):
    """Both listed domains publish DMARC with strict alignment (read 2026-10-11), so a DMARC PASS is the aligned proof;
    a DKIM PASS says only that SOME signature verified — the parser's header check does the aligned DKIM read."""
    assert gate.lambda_handler(_event(dmarc="GRAY", dkim="PASS", spf="PASS"), None) == {"disposition": "STOP_RULE_SET"}


def test_an_unlisted_or_disguised_from_is_refused_even_when_authenticated(listed, capsys):
    for sender in (STRANGER, f'"{OWNER_ADDR}" <{STRANGER}>', "", "not-an-address"):
        assert gate.lambda_handler(_event(sender=sender), None) == {"disposition": "STOP_RULE_SET"}, sender
        assert "reason=sender_not_listed" in capsys.readouterr().out, sender


def test_a_desk_sender_passes_the_gate_and_the_parser_scopes_its_route(listed):
    assert gate.lambda_handler(_event(sender=f"Desk <{DESK_ADDR}>"), None) == {"disposition": "CONTINUE"}


def test_with_the_allowlist_unset_the_gate_refuses_everything(monkeypatch, capsys):
    monkeypatch.delenv("ALLOWED_SENDERS", raising=False)
    monkeypatch.delenv("STORY_REPLY_SENDERS", raising=False)
    assert gate.lambda_handler(_event(), None) == {"disposition": "STOP_RULE_SET"}
    assert "reason=allowlist_unset" in capsys.readouterr().out
    monkeypatch.setenv("ALLOWED_SENDERS", " , ")  # whitespace and commas are not an allowlist either
    assert gate.lambda_handler(_event(), None) == {"disposition": "STOP_RULE_SET"}


def test_an_empty_or_malformed_event_stops(listed):
    for ev in ({}, {"Records": []}, {"Records": [{}]}, {"Records": [{"ses": "junk"}]}, None):
        assert gate.lambda_handler(ev, None) == {"disposition": "STOP_RULE_SET"}, ev


def test_one_refusal_refuses_a_whole_batch(listed):
    ev = _event()
    ev["Records"].append(_event(dmarc="FAIL")["Records"][0])
    assert gate.lambda_handler(ev, None) == {"disposition": "STOP_RULE_SET"}


def test_the_gate_builds_no_aws_client():
    """Zero grants is the role; zero clients is the code — the two together make 'writes nothing' structural."""
    src = open(os.path.join(LAMBDAS, "emails", "inbound_auth_gate_lambda.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "boto3" not in imported and "botocore" not in imported, imported
    assert "urllib" not in imported


# ── the parser: defence in depth on every route ────────────────────────────────────────────────────────────────────────

SES_PASS = (
    "amazonses.com;\r\n"
    " spf=pass (spfCheck: domain of example.invalid designates 192.0.2.16 as permitted sender) client-ip=192.0.2.16;"
    " envelope-from=owner@example.invalid; helo=mail.example.invalid;\r\n"
    " dkim=pass header.i=@example.invalid;\r\n"
    " dmarc=pass header.from=example.invalid;"
)
SES_FAIL = "amazonses.com; spf=fail smtp.mailfrom=elsewhere.invalid; dkim=none; dmarc=fail header.from=example.invalid;"
SENDER_CLAIM = "mx.attacker.invalid; dmarc=pass header.from=example.invalid"  # not SES's word — a header the sender wrote

INSIGHT_BODY = "track this: the afternoon craving window follows a short night\n"
REVIEW_PACK_SUBJECT = "Re: AI Review Pack — Week 5"
SQ_SUBJECT = "Re: The Measured Life · Week 5 · 3 quick questions [SQ-W5]"
SQ_BODY = "> Q1: Did you think about skipping Thursday's session?\nNo, never crossed my mind.\n"


def _email(sender, subject, body, auth_headers=()):
    head = "".join(f"Authentication-Results: {h}\r\n" for h in auth_headers)
    return (
        head + f"From: Matthew <{sender}>\r\n"
        f"To: {INBOUND}\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body.replace("\n", "\r\n")
    ).encode("utf-8")


class FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, **kw):
        self.puts.append(kw["Item"])
        return {}

    def query(self, **kw):
        return {"Items": []}

    def get_item(self, **kw):
        return {}


class FakeS3:
    def __init__(self, raw):
        self.raw = raw
        self.puts = []
        self.reads = 0

    def get_object(self, **kw):
        self.reads += 1
        return {"Body": io.BytesIO(self.raw)}

    def put_object(self, **kw):
        self.puts.append({"Key": kw["Key"], "record": json.loads(kw["Body"])})
        return {}


class FakeCW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


class FakeSes:
    def __init__(self):
        self.sends = []

    def send_email(self, **kw):
        self.sends.append(kw)
        return {"MessageId": "x"}


S3_RECORD = {"s3": {"bucket": {"name": "b"}, "object": {"key": "raw/inbound_email/m1"}}}


@pytest.fixture
def run(monkeypatch):
    """Drive the real handler on one raw email; return (table, s3, cw, ses, corrections, words)."""

    def _run(raw, allowed=frozenset({OWNER_ADDR}), story_senders=frozenset(), record=None):
        table, s3, cw, ses = FakeTable(), FakeS3(raw), FakeCW(), FakeSes()
        corrections, words = [], []
        monkeypatch.setattr(iep, "table", table)
        monkeypatch.setattr(iep, "s3", s3)
        monkeypatch.setattr(iep, "cloudwatch", cw)
        monkeypatch.setattr(iep, "ses", ses)
        monkeypatch.setattr(iep, "ALLOWED_SENDERS", frozenset(allowed))
        monkeypatch.setattr(iep, "STORY_REPLY_SENDERS", frozenset(story_senders))
        monkeypatch.setattr(iep, "experiment_stamp_for", lambda pk, sk, **kw: {})
        monkeypatch.setattr(iep, "_store_owner_words", lambda *a: words.append(a) or 0)
        if iep.coach_corrections is not None:
            monkeypatch.setattr(iep.coach_corrections, "write_correction", lambda *a, **k: corrections.append(a) or "sk")
        resp = iep.lambda_handler({"Records": [record or S3_RECORD]}, None)
        assert resp["statusCode"] == 200
        return table, s3, cw, ses, corrections, words

    return _run


def _reasons(s3):
    return [p["record"]["reason"] for p in s3.puts]


def test_the_allowlist_has_no_fallback_in_source():
    """With the environment unset the module-level list is EMPTY — not one address, not a TODO with an address."""
    src = open(os.path.join(LAMBDAS, "emails", "insight_email_parser_lambda.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ALLOWED_SENDERS" for t in n.targets)]
    assert len(assigns) == 1
    literals = [n.value for n in ast.walk(assigns[0].value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("@" in s for s in literals), f"a fallback address is back in source: {literals}"
    assert 'os.environ.get("ALLOWED_SENDERS"' in src, "the list comes from the environment"


def test_with_the_allowlist_unset_the_parser_refuses_and_writes_nothing(run):
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, "Re: Daily Brief", INSIGHT_BODY, [SES_PASS]), allowed=frozenset())
    assert table.puts == [] and ses.sends == [] and corrections == [] and words == []
    assert _reasons(s3) == ["allowlist_unset"]
    assert [c["MetricData"][0]["MetricName"] for c in cw.calls] == ["InsightParseFailure"]
    assert "craving" not in json.dumps(s3.puts), "the refusal trace never carries the body"
    assert iep.sender_verdict(OWNER_ADDR, "x", None) == "allowlist_unset"  # both module-level sets are patched empty above


def test_an_allowed_sender_with_a_verdict_lands_an_insight(run):
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, "Re: Daily Brief", INSIGHT_BODY, [SES_PASS]))
    assert [r["sk"][:8] for r in table.puts if str(r.get("sk", "")).startswith("INSIGHT#")] == ["INSIGHT#"]
    assert len(ses.sends) == 1 and s3.puts == []


@pytest.mark.parametrize(
    "headers", [[], [SES_FAIL], [SES_FAIL, SES_PASS], [SENDER_CLAIM]], ids=["missing", "failing", "forged-below", "sender-claim"]
)
def test_an_allowed_sender_without_ses_verdict_is_refused_on_the_insight_route(run, headers):
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, "Re: Daily Brief", INSIGHT_BODY, headers))
    assert table.puts == [] and ses.sends == [], headers
    assert _reasons(s3) == ["sender_unauthenticated"], headers
    env = json.dumps(s3.puts[0]["record"])
    assert OWNER_ADDR in env and "craving" not in env, "who and what, never the words"


def test_the_review_pack_correction_route_sits_behind_the_verdict(run):
    body = "#3 the weight baseline is stale\n"
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, REVIEW_PACK_SUBJECT, body, []))
    assert corrections == [] and table.puts == [] and ses.sends == []
    assert _reasons(s3) == ["sender_unauthenticated"]


def test_the_story_desk_route_sits_behind_the_verdict_for_an_allowed_sender_too(run):
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, SQ_SUBJECT, SQ_BODY, [SES_FAIL]))
    assert [r for r in table.puts if str(r.get("sk", "")).startswith(sq.QA_SK_PREFIX)] == [] and words == []
    assert _reasons(s3) == ["sender_unauthenticated"]
    # and with the verdict, the same message lands (the #4546 behaviour, unchanged)
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, SQ_SUBJECT, SQ_BODY, [SES_PASS]))
    assert len([r for r in table.puts if str(r.get("sk", "")).startswith(sq.QA_SK_PREFIX)]) == 1 and len(words) == 1


def test_an_ses_direct_record_is_refused_on_its_receipt_before_the_s3_read(run):
    rec = copy.deepcopy(RECEIPT_EVENT["Records"][0])
    rec["ses"]["receipt"]["dmarcVerdict"] = {"status": "FAIL"}
    table, s3, cw, ses, corrections, words = run(_email(OWNER_ADDR, "Re: Daily Brief", INSIGHT_BODY, [SES_PASS]), record=rec)
    assert s3.reads == 0, "the verdict is read before the object is"
    assert table.puts == [] and ses.sends == [] and _reasons(s3) == ["receipt_dmarc_fail"]
    # a passing receipt proceeds to the ordinary path (the key is the SES messageId's landing key)
    table, s3, cw, ses, corrections, words = run(
        _email(OWNER_ADDR, "Re: Daily Brief", INSIGHT_BODY, [SES_PASS]), record=copy.deepcopy(RECEIPT_EVENT["Records"][0])
    )
    assert s3.reads == 1 and len(ses.sends) == 1


def test_the_log_lines_never_print_the_allowlist(run, capsys):
    run(_email(STRANGER, "Re: Daily Brief", INSIGHT_BODY, [SES_PASS]))
    assert OWNER_ADDR not in capsys.readouterr().out


# ── every record type the parser can write sits behind the verdict ─────────────────────────────────────────────────────

#: The inventory the PR lists. A new writer must be added here — and must sit below the verdict in lambda_handler.
WRITE_SITES = {
    "save_insight": "INSIGHT#<ts> row in USER#matthew#SOURCE#insights",
    "handle_review_pack_reply": "corrections-ledger rows via coach_corrections.write_correction (+ confirmation send)",
    "put_item": "Story Desk QA row (story_questions.qa_row) in USER#matthew#SOURCE#insights",
    "_store_owner_words": "owner-words entries via owner_words.record",
    "record_sent": "email_log# send-ledger rows via common.send_ledger",
    "send_confirmation": "the insight confirmation send (guarded_send_email)",
}


def _handler_calls():
    src = open(os.path.join(LAMBDAS, "emails", "insight_email_parser_lambda.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
    calls = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            calls.append((name, n.lineno))
    return calls


def test_every_write_site_in_the_handler_is_below_the_verdict():
    calls = _handler_calls()
    verdict_line = next(line for name, line in calls if name == "sender_verdict")
    seen = {name for name, _ in calls if name in WRITE_SITES}
    assert seen == set(WRITE_SITES), f"the write-site inventory drifted: {sorted(seen ^ set(WRITE_SITES))}"
    above = [(name, line) for name, line in calls if name in WRITE_SITES and line < verdict_line]
    assert above == [], f"a record write precedes the sender verdict: {above}"
    # the only S3 write above the verdict is the refusal trace itself (the dead-letter envelope), never a record
    s3_above = {name for name, line in calls if line < verdict_line and name in {"put_object", "put_item", "send_email"}}
    assert s3_above == set(), s3_above


# ── the rule is IaC, and its shape is the contract ─────────────────────────────────────────────────────────────────────


def _operational_stack_tree():
    return ast.parse(open(os.path.join(ROOT, "cdk", "stacks", "operational_stack.py"), encoding="utf-8").read())


def _kw(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def test_the_receipt_rule_is_defined_in_cdk_with_the_gate_as_its_only_action():
    tree = _operational_stack_tree()
    add_rule = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_rule"]
    assert len(add_rule) == 1, "exactly one receipt rule is added to the imported rule set"
    call = add_rule[0]
    assert _kw(call, "after") is None, "no `after=`: an AWS::SES::ReceiptRule without After is inserted at the HEAD of the set"
    assert isinstance(_kw(call, "scan_enabled"), ast.Constant) and _kw(call, "scan_enabled").value is True
    actions = _kw(call, "actions")
    assert isinstance(actions, ast.List) and len(actions.elts) == 1, "the verdict is the rule's only action — no store in this rule"
    lam = actions.elts[0]
    assert getattr(lam.func, "attr", "") == "Lambda"
    inv = _kw(lam, "invocation_type")
    assert getattr(inv, "attr", "") == "REQUEST_RESPONSE", "an Event invocation cannot stop the rule set"
    assert getattr(_kw(lam, "function"), "id", "") == "inbound_auth_gate"
    imported = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "from_receipt_rule_set_name"]
    assert len(imported) == 1, "the ACTIVE rule set is imported by name, never replaced by a second one"


def test_the_gate_and_the_parser_read_one_sender_constant_and_the_gate_holds_no_grants():
    tree = _operational_stack_tree()
    ctor = {
        _kw(n, "function_name").value: n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "create_platform_lambda"
        and isinstance(_kw(n, "function_name"), ast.Constant)
    }
    for fn in ("inbound-auth-gate", "insight-email-parser"):
        env = _kw(ctor[fn], "environment")
        assert isinstance(env, ast.Call) and getattr(env.args[0], "id", "") == "INBOUND_SENDER_ENV", fn
    # Zero grants is a LITERAL `[]` at the call site, not a policy function: the static IAM linter's R6
    # (tests/test_role_policies.py) reads an empty policy function as a half-written one, and this role
    # has no policy to write. `[]` (not None) is what keeps the helper on its least-privilege path.
    policies = _kw(ctor["inbound-auth-gate"], "custom_policies")
    assert isinstance(policies, ast.List) and policies.elts == [], "the gate's role is zero grants"
    rp_src = open(os.path.join(ROOT, "cdk", "stacks", "role_policies_operational.py"), encoding="utf-8").read()
    assert "inbound_auth_gate" not in rp_src, "no policy function for a role with no policy (R6)"
