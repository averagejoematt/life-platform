"""tests/test_brief_rec_pilot_e2e_6158.py — the Morning Brief pilot through the REAL handler sequence (#6158).

Owner ruling 2026-11-22 on #6232, items A and B:
  A. "Demonstrate that the writer can actually read the required stamped SEND/token binding at the moment the
     offer is processed. Test this against the real sequence, not just individually mocked functions."
  B. "Demonstrate what happens when the mail service accepts a send but the canonical writer fails. The miss
     must be observable, the trial response must remain intact, and no false canonical event may be created."

What runs: `emails.daily_brief_lambda.lambda_handler` end to end, inside the repo's handler harness
(`test_daily_brief_behavior`: fake SES that accepts and returns a MessageId, fake S3, no AWS, no network), with
the real `emails.brief_trial` (prepare -> send -> record) and the REAL writer handler
(`coach.recommendation_writer_lambda.lambda_handler`) invoked where production invokes it — synchronously, from
`brief_trial._pilot_record` — against ONE shared table. Only the AI guidance text is supplied (the harness runs
the brief with AI paused); every other step is the production code path.

The shared table models DynamoDB's one consistency hazard on this path: an eventually consistent read issued in
the same run as the write it needs may not see it. A GetItem WITHOUT `ConsistentRead=True` misses any row put
during the current handler run. The writer's binding read is strongly consistent, so it must find the token row
the brief stamped moments earlier; the mutation tests below show both the ordering and the consistent read are
load-bearing.

All fixture text is invented.
"""

from __future__ import annotations

import inspect
import textwrap

import pytest
import test_daily_brief_behavior as _dbb  # noqa: E402 — the handler harness (fakes only, no AWS)
from coach import (
    brief_rec_intake as intake,
    brief_recommendations as seam,
    recommendation_record as rr,
    recommendation_writer_lambda as writer,
)
from common.pacific_time import shift_day_key as brief_shift
from emails import brief_trial as bt

brief, computed_row = _dbb.brief, _dbb.computed_row
frozen_clock, _every_day_is_a_narrative_day = _dbb.frozen_clock, _dbb._every_day_is_a_narrative_day
handler_env, ses, table = _dbb.handler_env, _dbb.ses, _dbb.table

ADMITTED = "Walk for 30 minutes after lunch today."
TRIAL_PK = brief.USER_PREFIX + "brief_trial"
REC_PK = rr.pk("matthew")
SWITCH_KEY = (TRIAL_PK, "SWITCH#format")


class ConditionalCheckFailedException(Exception):
    pass


class Shared:
    """The harness table, plus: create-only conditions honoured, every call logged as (actor, op, pk, sk, consistent),
    and read-after-write staleness for eventually consistent GetItem within one handler run."""

    def __init__(self, inner):
        self.inner = inner
        self.log: list = []
        self.fresh: set = set()  # keys put during the current run
        self.strip_consistent = False  # mutation switch: pretend the caller never asked for a consistent read

    def new_run(self):
        self.fresh = set()

    def view(self, actor):
        return _View(self, actor)


class _View:
    def __init__(self, shared, actor):
        self.s, self.actor = shared, actor

    def put_item(self, Item=None, ConditionExpression=None, **kw):
        key = (Item["pk"], Item["sk"])
        self.s.log.append((self.actor, "put", key[0], key[1], None))
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.s.inner.store:
            raise ConditionalCheckFailedException("ConditionalCheckFailedException")
        self.s.fresh.add(key)
        return self.s.inner.put_item(Item=Item, **kw)

    def get_item(self, Key=None, ConsistentRead=False, **kw):
        consistent = bool(ConsistentRead) and not self.s.strip_consistent
        key = (Key["pk"], Key["sk"])
        self.s.log.append((self.actor, "get", key[0], key[1], consistent))
        if key in self.s.fresh and not consistent:
            return {}  # written moments ago in this run; an eventually consistent read may not see it yet
        return self.s.inner.get_item(Key=Key, **kw)

    def query(self, **kw):
        return self.s.inner.query(**kw)

    def update_item(self, **kw):
        return self.s.inner.update_item(**kw)


@pytest.fixture
def run(handler_env, monkeypatch):
    """Returns `go(**opts)`: one real handler run with the trial on hybrid and the pilot live."""
    r = computed_row()
    handler_env["table"].store[(r["pk"], r["sk"])] = r
    # yesterday carried the same readiness colour, so today's readiness call is a REPEAT and the brief's one NEW
    # coaching recommendation — the one the link goes on — is the guidance line (a NEW readiness call would be linked
    # instead, and the pilot rightly skips it: a fixed-weight score is not a coach's recommendation)
    prev = dict(r, sk="DATE#" + brief_shift(r["sk"][5:15], -1))
    handler_env["table"].store[(prev["pk"], prev["sk"])] = prev
    handler_env["table"].store[SWITCH_KEY] = {"pk": SWITCH_KEY[0], "sk": SWITCH_KEY[1], "value": "hybrid"}
    shared = Shared(handler_env["table"])
    monkeypatch.setattr(brief, "table", shared.view("brief"))
    monkeypatch.setattr(seam, "CANONICAL_INTAKE_LIVE", True)
    real_ai = brief._run_ai_coach_pipeline

    def with_guidance(*a, **k):
        out = dict(real_ai(*a, **k))
        out["tldr_guidance"] = {"tldr": "A steady day.", "guidance": [ADMITTED]}
        return out

    monkeypatch.setattr(brief, "_run_ai_coach_pipeline", with_guidance)
    state = {"writer": None}

    def invoke(payload, client=None):
        """Where production calls lambda:Invoke (RequestResponse): the real writer handler, same table."""
        if state["writer"] is not None:
            return state["writer"](payload)
        monkeypatch.setattr(writer, "_table", shared.view("writer"))
        return writer.lambda_handler(payload)

    monkeypatch.setattr(intake, "invoke_writer", invoke)

    def go(writer_behaviour=None):
        state["writer"] = writer_behaviour
        shared.new_run()
        handler_env["ses"].sent.clear()
        brief.lambda_handler({"force_send": True}, None)
        return shared

    go.env = handler_env
    return go


def _heads(env):
    return [v for (p, s), v in env["table"].store.items() if p == REC_PK and v.get("record_type") == "recommendation"]


def _events(env):
    return [v for (p, s), v in env["table"].store.items() if p == REC_PK and v.get("record_type") == "recommendation_event"]


def _send_row(env):
    rows = [v for (p, s), v in env["table"].store.items() if p == TRIAL_PK and s.startswith("SEND#")]
    assert len(rows) == 1
    return rows[0]


def _token_rows(env):
    return [v for (p, s), v in env["table"].store.items() if p == TRIAL_PK and s.startswith("TOKEN#")]


# ══════════════════════════════════════════════════════════════════════════════
# A. the real order: token stamped and put -> SES accepts -> writer reads the binding
# ══════════════════════════════════════════════════════════════════════════════


def test_the_writer_reads_the_stamped_binding_in_the_real_handler_sequence(run):
    shared = run()
    env = run.env
    assert env["ses"].sent, "the brief was not sent"
    (head,) = _heads(env)
    send = _send_row(env)
    (tok,) = _token_rows(env)
    assert send["rec_offer"] == "offered" and send["delivery_state"] == "accepted_by_mail_service"
    assert head["ses_message_id"] == send["ses_message_id"] == "fake-message-id"
    assert tok["canonical_rec_id"] == head["rec_id"] == send["canonical_rec_id"]
    # the order, as it happened: the brief put the stamped token, THEN the writer read it (consistently), THEN wrote
    log = shared.log
    i_tok_put = next(i for i, e in enumerate(log) if e[:3] == ("brief", "put", TRIAL_PK) and e[3].startswith("TOKEN#"))
    i_bind = next(i for i, e in enumerate(log) if e[:3] == ("writer", "get", TRIAL_PK) and e[3] == tok["sk"])
    i_head = next(i for i, e in enumerate(log) if e[:3] == ("writer", "put", REC_PK))
    i_send = next(i for i, e in enumerate(log) if e[:3] == ("brief", "put", TRIAL_PK) and e[3].startswith("SEND#"))
    assert i_tok_put < i_bind < i_head < i_send
    assert log[i_bind][4] is True, "the binding read must be strongly consistent"
    # nothing but the writer wrote the record
    assert {e[0] for e in log if e[1] == "put" and e[2] == REC_PK} == {"writer"}


def _record_with_token_after_invoke():
    """MUTATION: brief_trial.record with the token-row write moved BELOW the pilot invoke (the measurement block)."""
    src = textwrap.dedent(inspect.getsource(bt.record))
    start = src.index("    try:\n        if trial.token and trial.token_row:")
    end = src.index("    try:\n        m = dict(trial.measurement)")
    token_block = src[start:end]
    mutated = src[:start] + src[end:] + token_block.replace("\n    ", "\n    ")
    ns: dict = {}
    exec(compile(mutated, "<mutated record>", "exec"), bt.__dict__, ns)  # noqa: S102 — an in-test mutation of our own code
    return ns["record"]


def test_mutation_the_stamp_after_the_invoke_is_refused(run, monkeypatch):
    monkeypatch.setattr(bt, "record", _record_with_token_after_invoke())
    run()
    env = run.env
    send = _send_row(env)
    assert send["rec_offer"] == "refused" and "no stamped token" in send["rec_offer_reason"]
    assert _heads(env) == [] and _events(env) == []
    assert _token_rows(env), "the mutated record still wrote the token, just too late"


def test_mutation_an_eventually_consistent_binding_read_is_refused(run):
    """MUTATION: the same run with the writer's binding read downgraded to eventually consistent."""
    brief.table.s.strip_consistent = True  # the fixture's shared table, seen by both principals
    run()
    send = _send_row(run.env)
    assert send["rec_offer"] == "refused" and "no stamped token" in send["rec_offer_reason"] and _heads(run.env) == []


# ══════════════════════════════════════════════════════════════════════════════
# B. the mail service accepts, then the writer fails
# ══════════════════════════════════════════════════════════════════════════════


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class ReadTimeoutError(Exception):
    pass


def _throws(payload):
    if payload.get("action") == "offer":
        raise intake.WriterFailed("InternalServerError")  # the writer ran and raised (its Errors alarm counts it)
    return writer.lambda_handler(payload)


def _times_out(payload):
    raise ReadTimeoutError("Read timeout on endpoint URL")


def _throttled(payload):
    raise _ClientError("TooManyRequestsException")


def _refuses(payload):
    if payload.get("action") == "offer":
        return {"state": "refused", "reason": "no stamped token row for this send"}
    return writer.lambda_handler(payload)


@pytest.mark.parametrize(
    "behaviour,state,error",
    [
        (_throws, "writer_failed", "InternalServerError"),
        (_times_out, "writer_failed", "ReadTimeoutError"),
        (_throttled, "writer_failed", "TooManyRequestsException"),
        (_refuses, "refused", None),
    ],
)
def test_an_accepted_send_with_a_failed_writer_is_observable_intact_and_records_nothing(run, monkeypatch, behaviour, state, error):
    from web import site_api_brief_response as sb

    warnings: list = []
    monkeypatch.setattr(brief.logger, "warning", lambda msg, *a, **k: warnings.append(msg % a if a else msg))
    run(writer_behaviour=behaviour)
    env = run.env
    assert env["ses"].sent, "the brief still goes out"
    # OBSERVABLE: the SEND# row names the miss and its class; the daily-brief log carries one line
    send = _send_row(env)
    assert send["delivery_state"] == "accepted_by_mail_service" and send["rec_offer"] == state
    assert send.get("rec_offer_error") == error
    assert any("[brief_rec_pilot] offer" in w for w in warnings)
    # NOTHING FALSE: no head, no event
    assert _heads(env) == [] and _events(env) == []
    # INTACT: the trial token row is there, stamped, unspent — and the answer page still records his answer
    (tok,) = _token_rows(env)
    assert tok["canonical_rec_id"] and not tok.get("used_at")
    monkeypatch.setattr(sb, "_deps", lambda: (env["table"], brief.logger))
    monkeypatch.setattr(sb, "salted_ip_hash", lambda ip, logger=None: "iphash")
    real_update = env["table"].update_item

    def door_update(**kw):  # the harness table records updates only; apply the door's two the way DynamoDB would
        real_update(**kw)
        row = env["table"].store.get((kw["Key"]["pk"], kw["Key"]["sk"]))
        if row is None or kw["Key"]["pk"].startswith("RATE#"):
            return {"Attributes": {"count": 1}}
        v = kw["ExpressionAttributeValues"]
        if kw["Key"]["sk"].startswith("TOKEN#"):
            row.update(used_at=v[":u"], response=v[":r"], response_status=v[":s"])
        return {"Attributes": dict(row)}

    monkeypatch.setattr(env["table"], "update_item", door_update)
    # the door looks the row up by the hash of the token it is handed; recover the token from the hybrid email link
    html = env["ses"].sent[-1]["Content"]["Simple"]["Body"]["Html"]["Data"]
    token = html.split("/api/brief_response?t=")[1][:43]
    ev = {
        "body": "t=" + token + "&response=done",
        "headers": {"cloudfront-viewer-address": "203.0.113.7:1"},
        "requestContext": {"http": {"method": "POST"}},
    }
    assert sb.handle_brief_response(ev)["statusCode"] == 200
    assert env["table"].store[(TRIAL_PK, tok["sk"])]["response"] == "done"
    # LATER: the next run's carry (writer healthy) sees his answer, finds no head, and writes NOTHING — no head is
    # created for the unrecorded offer, no event, no retry of the offer. Only a SEND# row and the log say what happened.
    send["pilot_tokens"] = {tok["sk"][len("TOKEN#") :]: tok["canonical_rec_id"]}  # even had the send bound it
    counts = writer.carry(Shared(env["table"]).view("writer"))
    assert counts["no_head"] == 1 and counts["carried"] == 0
    assert _heads(env) == [] and _events(env) == []


def test_the_carry_step_never_creates_a_head_or_an_event_for_an_offer_it_never_recorded(run):
    """Exactly what `carry` does with an answer whose head was never written: counts it `no_head` and writes nothing."""
    run(writer_behaviour=_throws)
    env = run.env
    (tok,) = _token_rows(env)
    tok["used_at"], tok["response"] = "2026-11-25T18:00:00+00:00", "done"
    send = _send_row(env)
    send["pilot_tokens"] = {tok["sk"][6:]: tok["canonical_rec_id"]}  # even if bound
    store = env["table"].store
    store.pop(SWITCH_KEY)  # no new brief: only the carry runs
    counts = writer.carry(Shared(env["table"]).view("writer"))
    assert counts["no_head"] == 1 and counts["carried"] == 0
    assert _heads(env) == [] and _events(env) == []
