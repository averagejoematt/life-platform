"""tests/test_brief_rec_pilot_6158.py — the Morning Brief as the recommendation record's first intake (#6158 pilot).

Each of the owner's section-6 demonstrations (ruling 2026-11-22, "Pilot acceptance") is one named test below, run
through the REAL brief trial (`emails.brief_trial.prepare` / `record`), the REAL dedicated writer
(`coach.recommendation_writer_lambda`, invoked in-process where production invokes it synchronously), the REAL
response door (`web.site_api_brief_response`) and the REAL owner tool (`manage_coach_recommendation`) against one
recording fake table that tags every call with the principal that made it — no AWS.

Plus the owner's feedback on #6232 (2026-11-22): only the writer writes the record (the brief cannot); every write is
create-only; a repeat is an EXPOSURE on the existing recommendation, never a new decision; the fold carries a spent
token exactly once and never an altered, duplicated or pre-activation one; the accountable lead is kept apart from
the recommendation's origin; "accepted by the mail service" is the only delivery claim. And: the pilot ships dark and
dark is the trial as it was; the record being unavailable never costs the brief and is never reconstructed later.

All fixture text is invented.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

for _k, _v in (
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "test-bucket"),
    ("TABLE_NAME", "life-platform-test"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)
from coach import (  # noqa: E402
    brief_recommendations as seam,
    recommendation_record as rr,
    recommendation_writer_lambda as writer,  # noqa: E402
)
from content import brief_hybrid as bh  # noqa: E402
from emails import brief_trial as bt  # noqa: E402

import mcp.tools_coach_recommendations as tcr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UP = "USER#matthew#SOURCE#"
TRIAL_PK = UP + "brief_trial"
REC_PK = rr.pk("matthew")
D1 = "2026-11-24"  # a data day; its brief is for the 25th
ADMITTED = "Walk for 30 minutes after lunch today."
NOT_ADMITTED = "Steps dropped sharply — a single walk is the highest-leverage move."


class ConditionalCheckFailedException(Exception):
    pass


def _key_parts(cond) -> dict:
    out: dict = {}
    stack = [cond]
    while stack:
        expr = stack.pop().get_expression()
        op = expr["operator"]
        if op == "AND":
            stack.extend(expr["values"])
        elif op == "=":
            out["pk"] = expr["values"][1]
        elif op == "begins_with":
            out["prefix"] = expr["values"][1]
        elif op == "BETWEEN":
            out["between"] = (expr["values"][1], expr["values"][2])
    return out


class Table:
    """Every call recorded as (op, pk, sk); conditional puts and the door's two updates evaluated for real."""

    def __init__(self):
        self.store: dict = {}
        self.ops: list = []
        self.fail_pk: str | None = None  # every call touching this partition raises (the record "unavailable")
        self.actor = "brief"  # which principal is calling: "brief" (daily-brief, the door, the owner tool) or "writer"

    def _check(self, pk):
        if self.fail_pk and pk == self.fail_pk:
            raise RuntimeError("ProvisionedThroughputExceededException")

    def get_item(self, Key=None, **_):
        self.ops.append(("get", Key["pk"], Key["sk"], self.actor))
        self._check(Key["pk"])
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item=None, ConditionExpression=None, **_):
        self.ops.append(("put", Item["pk"], Item["sk"], self.actor))
        self._check(Item["pk"])
        k = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and k in self.store:
            raise ConditionalCheckFailedException("ConditionalCheckFailedException")
        self.store[k] = dict(Item)
        return {}

    def update_item(self, Key=None, ConditionExpression="", ExpressionAttributeValues=None, **_):
        self.ops.append(("update", Key["pk"], Key["sk"], self.actor))
        self._check(Key["pk"])
        v = ExpressionAttributeValues or {}
        k = (Key["pk"], Key["sk"])
        if Key["pk"].startswith("RATE#"):
            it = self.store.setdefault(k, {"count": 0})
            it["count"] += v.get(":inc", 1)
            return {"Attributes": {"count": it["count"]}}
        it = self.store.get(k)
        if it is None:
            raise ConditionalCheckFailedException("ConditionalCheckFailedException")
        if Key["sk"].startswith("TOKEN#"):
            if it.get("used_at") or int(it["expires_at"]) <= v[":now"]:
                raise ConditionalCheckFailedException("ConditionalCheckFailedException")
            it.update(used_at=v[":u"], response=v[":r"], response_status=v[":s"])
        else:
            it.update(response=v[":s"], response_word=v[":r"], response_at=v[":u"], response_rec_id=v[":id"])
        return {"Attributes": dict(it)}

    def query(self, **kw):
        parts = _key_parts(kw["KeyConditionExpression"])
        self.ops.append(("query", parts.get("pk"), parts.get("prefix") or str(parts.get("between")), self.actor))
        self._check(parts.get("pk"))
        rows = [r for (p, _s), r in self.store.items() if p == parts.get("pk")]
        if "prefix" in parts:
            rows = [r for r in rows if r["sk"].startswith(parts["prefix"])]
        if "between" in parts:
            lo, hi = parts["between"]
            rows = [r for r in rows if lo <= r["sk"] <= hi]
        rows.sort(key=lambda r: r["sk"])
        return {"Items": [dict(r) for r in rows]}

    def rows(self, pk, prefix=""):
        return [r for (p, s), r in sorted(self.store.items()) if p == pk and s.startswith(prefix)]

    def heads(self):
        return [r for r in self.rows(REC_PK) if r.get("record_type") == "recommendation"]

    def events(self):
        return [r for r in self.rows(REC_PK) if r.get("record_type") == "recommendation_event"]

    def written_pks(self):
        return {o[1] for o in self.ops if o[0] in ("put", "update")}


class AsWriter:
    """The writer's view of the same table: every call it makes is tagged `writer`."""

    def __init__(self, t):
        self._t = t

    def __getattr__(self, name):
        fn = getattr(self._t, name)

        def call(*a, **k):
            self._t.actor = "writer"
            try:
                return fn(*a, **k)
            finally:
                self._t.actor = "brief"

        return call


class _Log:
    def __init__(self):
        self.lines: list = []

    def warning(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    info = error = warning


def _go_live(monkeypatch, t):
    """The switch on, and the brief's synchronous invoke of the writer run in-process against the same table."""
    from coach import brief_rec_intake as intake

    monkeypatch.setattr(seam, "CANONICAL_INTAKE_LIVE", True)
    monkeypatch.setattr(writer, "_table", AsWriter(t))
    monkeypatch.setattr(intake, "invoke_writer", lambda payload, client=None: writer.lambda_handler(json.loads(json.dumps(payload))))


@pytest.fixture
def table(monkeypatch):
    t = Table()
    monkeypatch.setattr(tcr, "_table_ref", t)
    monkeypatch.setattr(tcr, "_user_id_ref", "matthew")
    return t


@pytest.fixture
def live(monkeypatch, table):
    _go_live(monkeypatch, table)


def _prepare(t, day, guidance, log=None):
    return bt.prepare(
        variant="hybrid",
        table=t,
        fetch_range=lambda *a, **k: [],
        user_prefix=UP,
        data={"date": day},
        profile={},
        computed={},
        component_details={},
        readiness_score=None,
        readiness_colour=None,
        mvp_streak=None,
        day_grade_score=None,
        grade=None,
        tldr_guidance={"guidance": list(guidance)},
        editorial={},
        today_short="Tue Nov 25",
        site_url="https://example.invalid",
        recipient="owner@example.invalid",
        logger=log or _Log(),
    )


def _send(t, day, guidance=(ADMITTED,), message_id="ses-msg-1", log=None):
    """One brief: prepare -> (the send) -> record. `message_id=None` = SES never accepted it."""
    log = log or _Log()
    trial = _prepare(t, day, guidance, log)
    assert trial is not None
    bt.record(t, UP, trial, 1234, True, log, sent={"MessageId": message_id} if message_id else None)
    return trial


def _door(monkeypatch, t):
    from web import site_api_brief_response as sb

    monkeypatch.setattr(sb, "_deps", lambda: (t, _Log()))
    monkeypatch.setattr(sb, "salted_ip_hash", lambda ip, logger=None: "iphash")
    return sb


def _press(sb, token, button):
    ev = {
        "body": urlencode({"t": token, "response": button}),
        "headers": {"cloudfront-viewer-address": "203.0.113.7:1"},
        "requestContext": {"http": {"method": "POST"}},
    }
    return sb.handle_brief_response(ev)["statusCode"]


def _view(t, rec_id):
    return next(v for v in rr.fold(t.rows(REC_PK)) if v["rec_id"] == rec_id)


# ══════════════════════════════════════════════════════════════════════════════
# the owner's section-6 demonstrations
# ══════════════════════════════════════════════════════════════════════════════

AI_ORIGIN = ("system", "ai_calls.call_tldr_and_guidance")


def test_one_delivered_recommendation_creates_one_record(live, table):
    trial = _send(table, D1)
    (head,) = table.heads()
    assert head["text"] == ADMITTED and head["date"] == "2026-11-25" and head["channel"] == "coach_brief"
    assert head["recorded_by"] == rr.RECORDED_BY_BRIEF and head["first_send_day"] == D1
    # accurate lifecycle words: offered, accepted by the mail service — never "delivered" or "read"
    assert head["lifecycle_state"] == "offered" and head["delivery_state"] == "accepted_by_mail_service"
    assert head["ses_message_id"] == "ses-msg-1" and head["accepted_by_mail_service_at"].endswith("Z")
    assert not {k for k in head if "deliver" in k and k != "delivery_state"} and "delivered" not in str(head.values())
    assert head["brief_rec_id"] == trial.view.decision.rec_id and head["follow_up_surface"] == rr.SURFACE_BRIEF
    assert head["rec_id"] == rr.rec_id_for(rr.LEAD_COACH_ID, "2026-11-25", ADMITTED)
    (tok,) = table.rows(TRIAL_PK, "TOKEN#")
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert tok["canonical_rec_id"] == send["canonical_rec_id"] == head["rec_id"]
    assert send["rec_offer"] == "offered" and send["delivery_state"] == "accepted_by_mail_service"
    assert send["pilot_tokens"] == {seam.token_hash(trial.token): head["rec_id"]}
    v = _view(table, head["rec_id"])
    assert v["response"] == rr.NOT_RECORDED and rr.status_of(v, "2026-11-25") == "active" and v["exposures"] == []


def test_a_duplicate_send_creates_no_second_record(live, table):
    _send(table, D1, message_id="ses-msg-1")
    _send(table, D1, message_id="ses-msg-2")  # force_send / a retry of the same brief
    _send(table, D1, guidance=("Walk for 30 minutes after dinner today.",), message_id="ses-msg-3")  # reworded, same run
    assert len(table.heads()) == 1 and table.heads()[0]["ses_message_id"] == "ses-msg-1" and table.events() == []
    assert table.store[(TRIAL_PK, "SEND#" + D1)]["rec_offer"] == "duplicate"


def test_a_repeat_is_an_exposure_on_the_same_recommendation_not_a_new_decision(live, table, monkeypatch):
    first = _send(table, D1)
    rid = first.token_row["canonical_rec_id"]
    second = _send(table, "2026-11-25", message_id="ses-msg-2")  # the same recommendation, shown again
    assert len(table.heads()) == 1 and second.token_row["canonical_rec_id"] == rid
    (exp,) = [e for e in table.events() if e["kind"] == rr.EVENT_EXPOSURE]
    assert exp["rec_id"] == rid and exp["send_day"] == "2026-11-25" and exp["ses_message_id"] == "ses-msg-2"
    assert exp["recorded_by"] == rr.RECORDED_BY_BRIEF and exp["delivery_state"] == "accepted_by_mail_service" and "response" not in exp
    assert table.store[(TRIAL_PK, "SEND#2026-11-25")]["rec_offer"] == "exposure_recorded"
    # he answers; a later repeat records the exposure, keeps his answer and does NOT ask again
    assert _press(_door(monkeypatch, table), second.token, "done") == 200
    _send(table, "2026-11-26", guidance=("Take the stairs at work this morning.",))  # carries the answer
    third = _send(table, "2026-11-27", message_id="ses-msg-4")  # the walk again
    v = _view(table, rid)
    assert v["response"] == rr.ACCEPTED and [e["send_day"] for e in v["exposures"]] == ["2026-11-25", "2026-11-27"]
    assert third.view.respond_url is None and "You answered “accepted”" in third.view.respond_note
    assert "Answer: done" not in third.block_html and seam.token_hash(third.token) not in table.store[(TRIAL_PK, "SEND#2026-11-27")].get(
        "pilot_tokens", {}
    )
    assert len([e for e in table.events() if e["kind"] == rr.EVENT_RESPONSE]) == 1  # the exposure reset nothing
    # an exposure is a send, never an answer: the fold ignores it for every derived state
    assert rr.fold([table.store[(REC_PK, rr.head_sk(rid))], exp])[0]["response"] == rr.NOT_RECORDED


def test_a_still_open_answer_on_a_repeat_is_shown_and_can_be_replaced(live, table, monkeypatch):
    first = _send(table, D1)
    assert _press(_door(monkeypatch, table), first.token, "still_deciding") == 200
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    again = _send(table, "2026-11-26")
    assert again.view.respond_url and "Your last answer: “still deciding”" in again.view.respond_note


def test_an_undelivered_brief_creates_no_false_offered_record(live, table):
    trial = _send(table, D1, message_id=None)  # the mail service returned no MessageId
    assert table.heads() == [] and REC_PK not in table.written_pks()
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert send["rec_offer"] == "not_accepted_by_mail_service" and send["delivery_state"] == "not_accepted_by_mail_service"
    t2 = Table()  # generated (prepared, link stamped) but never sent: record() is never reached -> nothing at all
    _prepare(t2, D1, (ADMITTED,))
    assert REC_PK not in t2.written_pks()
    t3 = Table()  # a dry run / demo writes nothing for the trial or the record
    bt.record(t3, UP, _prepare(t3, D1, (ADMITTED,)), 10, False, _Log(), sent={"MessageId": "m"})
    assert t3.written_pks() == set()
    assert trial.token_row["canonical_rec_id"]
    # and the writer itself refuses an offer with no message id, whoever invokes it
    assert writer.offer(AsWriter(table), {"action": "offer", "ses_message_id": "", "canonical_rec_id": "x"})["state"] == "refused"


@pytest.mark.parametrize("button,answer", [("done", rr.ACCEPTED), ("not_doing", rr.DECLINED), ("still_deciding", rr.STILL_DECIDING)])
def test_his_explicit_response_is_captured_correctly(live, table, monkeypatch, button, answer):
    trial = _send(table, D1)
    sb = _door(monkeypatch, table)
    before = time.time()
    assert _press(sb, trial.token, button) == 200
    assert table.events() == []  # the public door writes the trial row only
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))  # the next brief carries it
    (ev,) = table.events()
    head = table.store[(REC_PK, rr.head_sk(trial.token_row["canonical_rec_id"]))]
    assert ev["rec_id"] == head["rec_id"] and ev["response"] == answer and ev["recorded_by"] == rr.RECORDED_BY_OWNER
    assert ev["via"] == "brief_response_button" and ev["carried_by"] == rr.RECORDED_BY_BRIEF and ev["send_day"] == D1
    assert ev["token_hash"] == seam.token_hash(trial.token) and ev["words"] == seam.RESPONSE_WORDS[button]
    assert ev["recorded_at"] >= time.strftime("%Y-%m-%dT%H:%M", time.gmtime(before - 60))  # his press, not the carry
    v = _view(table, head["rec_id"])
    assert v["response"] == answer and v["response_recorded_at"] == ev["recorded_at"]
    assert rr.is_closed(v) is (answer == rr.DECLINED)  # only a decline closes; accepted waits for an outcome


def test_the_same_response_submitted_twice_is_recorded_once(live, table, monkeypatch):
    trial = _send(table, D1)
    sb = _door(monkeypatch, table)
    assert _press(sb, trial.token, "done") == 200
    assert _press(sb, trial.token, "done") == 410 and _press(sb, trial.token, "not_doing") == 410  # the door spends once
    w = AsWriter(table)
    n1, n2 = writer.carry(w), writer.carry(w)
    assert (n1["carried"], n2["carried"], n2["already"]) == (1, 0, 1) and len(table.events()) == 1
    # even a carry that did not see the event (a concurrent run) cannot add a second: the key is fixed by the token
    real = rr.read_rows
    monkeypatch.setattr(
        writer.rr, "read_rows", lambda t, u, rid=None: [r for r in real(t, u, rid) if r.get("record_type") != "recommendation_event"]
    )
    n3 = writer.carry(w)
    assert n3["carried"] == 0 and n3["already"] == 1 and len(table.events()) == 1


def test_a_token_row_altered_or_duplicated_cannot_make_a_second_answer(live, table, monkeypatch):
    a = _send(table, D1)
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    (other,) = {t["canonical_rec_id"] for t in table.rows(TRIAL_PK, "TOKEN#")} - {a.token_row["canonical_rec_id"]}
    sb = _door(monkeypatch, table)
    assert _press(sb, a.token, "done") == 200
    key = (TRIAL_PK, "TOKEN#" + seam.token_hash(a.token))
    w = AsWriter(table)
    # duplicated: the same spent row copied under another hash
    table.store[(TRIAL_PK, "TOKEN#" + "f" * 64)] = {**table.store[key], "sk": "TOKEN#" + "f" * 64, "response": "not_doing"}
    # altered: the spent row re-pointed at another recommendation before the carry
    table.store[key] = {**table.store[key], "canonical_rec_id": other}
    n = writer.carry(w)
    assert n["carried"] == 0 and n["unbound"] == 2 and table.events() == []
    table.store[key] = {**table.store[key], "canonical_rec_id": a.token_row["canonical_rec_id"]}  # restored
    assert writer.carry(w)["carried"] == 1 and writer.carry(w)["carried"] == 0
    assert [e["response"] for e in table.events()] == [rr.ACCEPTED]


def test_silence_is_not_recorded_as_acceptance(live, table, monkeypatch):
    trial = _send(table, D1)
    sb = _door(monkeypatch, table)
    get = {"queryStringParameters": {"t": trial.token}, "headers": {"cloudfront-viewer-address": "203.0.113.7:1"}}
    get["requestContext"] = {"http": {"method": "GET"}}
    assert sb.handle_brief_response(get)["statusCode"] == 200  # a scanner opening the link
    for day in ("2026-11-25", "2026-11-26", "2026-11-27"):
        _send(table, day, guidance=("Take the stairs at work this morning.",))
    assert not [e for e in table.events() if e["rec_id"] == trial.token_row["canonical_rec_id"]]
    v = _view(table, trial.token_row["canonical_rec_id"])
    assert v["response"] == rr.NOT_RECORDED and v["response_label"] == "not recorded" and not rr.is_closed(v)
    assert rr.status_of(v, "2027-06-01") == "active"  # it never expires into a verdict


def test_a_follow_up_is_scheduled_or_left_open(live, table, monkeypatch):
    trial = _send(table, D1)
    rid = trial.token_row["canonical_rec_id"]
    sb = _door(monkeypatch, table)
    assert _press(sb, trial.token, "still_deciding") == 200
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    v = _view(table, rid)
    assert v["response"] == rr.STILL_DECIDING and v["follow_up_on"] is None  # LEFT OPEN: the pilot never invents a date
    assert not any(e["kind"] == rr.EVENT_FOLLOW_UP for e in table.events())
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-26")
    assert (
        tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-28"})["status"] == "recorded"
    )
    before = _send(table, "2026-11-26", guidance=("Take the stairs at work this morning.",))  # brief for the 27th: not yet due
    assert before.view.follow_up is None and "FOLLOW-UP DUE" not in before.block_html
    due = _send(table, "2026-11-27", guidance=("Take the stairs at work this morning.",))  # brief for the 28th: due
    assert due.view.follow_up["rec_id"] == rid and "FOLLOW-UP DUE" in due.block_html and due.follow_token
    send = table.store[(TRIAL_PK, "SEND#2026-11-27")]
    assert send["follow_up_rec_id"] == rid and send["pilot_tokens"][seam.token_hash(due.follow_token)] == rid
    ftok = table.store[(TRIAL_PK, "TOKEN#" + seam.token_hash(due.follow_token))]
    assert ftok["canonical_rec_id"] == rid and ftok["send_day"] == D1  # the page names the brief that offered it
    again = _send(table, "2026-11-28", guidance=("Take the stairs at work this morning.",))
    assert again.view.follow_up is None  # asked ONCE
    assert _press(sb, due.follow_token, "done") == 200
    _send(table, "2026-11-29", guidance=("Take the stairs at work this morning.",))
    assert _view(table, rid)["response"] == rr.ACCEPTED


def test_a_due_follow_up_is_asked_even_on_a_brief_with_no_recommendation_of_its_own(live, table, monkeypatch):
    rid = _send(table, D1).token_row["canonical_rec_id"]
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-25")
    tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-27"})
    quiet = _send(table, "2026-11-26", guidance=())  # nothing new and no coaching recommendation that morning
    assert quiet.token is None and quiet.view.follow_up["rec_id"] == rid and quiet.follow_token
    assert (TRIAL_PK, "TOKEN#" + seam.token_hash(quiet.follow_token)) in table.store
    assert table.store[(TRIAL_PK, "SEND#2026-11-26")]["follow_up_rec_id"] == rid


def test_no_duplicate_follow_up_across_channels():
    """The two askers partition the due set: the brief asks only what a brief offered, the conversation the rest."""
    base = {"follow_up_on": "2026-11-20", "outcome": None, "response": rr.NOT_RECORDED}
    views = [
        {**base, "rec_id": "rec_20261110_eli_marsh_0000000a", "follow_up_surface": rr.SURFACE_BRIEF},
        {**base, "rec_id": "rec_20261110_eli_marsh_0000000b", "follow_up_surface": rr.SURFACE_CONVERSATION},
        {**base, "rec_id": "rec_20261110_eli_marsh_0000000c"},  # every row written before the pilot: no field
    ]
    brief = {v["rec_id"] for v in rr.due_follow_ups(views, "2026-11-22", surface=rr.SURFACE_BRIEF)}
    talk = {v["rec_id"] for v in rr.due_follow_ups(views, "2026-11-22")}  # the conversation's default
    every = {v["rec_id"] for v in rr.due_follow_ups(views, "2026-11-22", surface=None)}
    assert brief and talk and not brief & talk and brief | talk == every == {v["rec_id"] for v in views}
    src = (ROOT / "lambdas/coach/coach_context_pilot.py").read_text()
    assert "surface=" not in src and "rr.due_follow_ups(views, day)" in src
    assert "surface=rr.SURFACE_BRIEF" in (ROOT / "lambdas/coach/brief_rec_intake.py").read_text()


def test_a_real_outcome_closes_the_loop(live, table, monkeypatch):
    trial = _send(table, D1)
    rid = trial.token_row["canonical_rec_id"]
    assert _press(_door(monkeypatch, table), trial.token, "done") == 200
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-30")
    out = tcr.tool_manage_coach_recommendation({"action": "outcome", "rec_id": rid, "outcome_notes": "Did it four of five days."})
    assert out["status"] == "recorded"
    v = _view(table, rid)
    assert rr.is_closed(v) and v["outcome"]["outcome_notes"] == "Did it four of five days." and v["response"] == rr.ACCEPTED
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    resp = next(e for e in table.events() if e["kind"] == rr.EVENT_RESPONSE)
    outc = next(e for e in table.events() if e["kind"] == rr.EVENT_OUTCOME)
    assert send["canonical_rec_id"] == resp["rec_id"] == outc["rec_id"] == rid and resp["send_day"] == D1
    assert outc["recorded_by"] == rr.RECORDED_BY_OWNER and "via" not in outc  # his own report, through his tool


# ══════════════════════════════════════════════════════════════════════════════
# the writer: the only brief-side principal, create-only
# ══════════════════════════════════════════════════════════════════════════════

WRITER = ROOT / "lambdas/coach/recommendation_writer_lambda.py"
_FORBIDDEN_WRITES = {"update_item", "delete_item", "batch_writer", "batch_write_item", "transact_write_items", "execute_statement"}


def _write_sweep(src: str) -> list[str]:
    """Every put_item without a ConditionExpression, and every non-create write at all."""
    bad = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "put_item" and "ConditionExpression" not in {k.arg for k in n.keywords}:
                bad.append(f"line {n.lineno}: put_item without ConditionExpression")
            elif n.func.attr in _FORBIDDEN_WRITES:
                bad.append(f"line {n.lineno}: {n.func.attr}")
    return bad


def test_every_writer_write_is_create_only():
    src = WRITER.read_text()
    assert _write_sweep(src) == []
    puts = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "put_item"]
    assert len(puts) == 1 and '_CONDITION = "attribute_not_exists(sk)"' in src  # one door, create-only
    # the brief-side planner never writes the record at all
    assert not [
        n
        for n in ast.walk(ast.parse((ROOT / "lambdas/coach/brief_rec_intake.py").read_text()))
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in _FORBIDDEN_WRITES | {"put_item"}
    ]


def test_the_write_sweep_can_fail():
    assert _write_sweep("t.put_item(Item=x)\n") and _write_sweep("t.update_item(Key=k)\n") and _write_sweep("t.batch_writer()\n")
    assert _write_sweep("t.put_item(Item=x, ConditionExpression='attribute_not_exists(sk)')\n") == []


def test_only_the_writer_writes_the_record_in_a_full_run(live, table, monkeypatch):
    trial = _send(table, D1)
    _press(_door(monkeypatch, table), trial.token, "done")
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    _send(table, "2026-11-26")  # an exposure
    rec_writes = [o for o in table.ops if o[1] == REC_PK and o[0] in ("put", "update")]
    assert rec_writes and {o[3] for o in rec_writes} == {"writer"} and {o[0] for o in rec_writes} == {"put"}
    writer_pks = {o[1] for o in table.ops if o[3] == "writer"}
    assert writer_pks <= {REC_PK, TRIAL_PK} and {o[1] for o in table.ops if o[3] == "writer" and o[0] == "put"} == {REC_PK}


def test_a_head_put_twice_is_refused_by_its_condition(live, table):
    _send(table, D1)
    (head,) = table.heads()
    with pytest.raises(ConditionalCheckFailedException):
        table.put_item(Item=dict(head), ConditionExpression="attribute_not_exists(sk)")
    assert writer._put_new(AsWriter(table), dict(head)) is False and table.heads() == [head]


def test_the_writer_refuses_an_offer_that_is_not_the_briefs_own_send(live, table):
    trial = _send(table, D1)
    w = AsWriter(table)
    good = {"action": "offer", "new": True, "canonical_rec_id": trial.token_row["canonical_rec_id"], "send_day": D1, "ses_message_id": "m"}
    assert writer.offer(w, {**good, "token_hash": "0" * 64})["state"] == "refused"  # no such stamped token
    assert writer.offer(w, {**good, "token_hash": seam.token_hash(trial.token), "send_day": "2026-11-20"})["state"] == "refused"
    forged = rr.rec_id_for(rr.LEAD_COACH_ID, "2026-11-25", "Lift heavy every morning this week.")
    assert writer.offer(w, {**good, "token_hash": seam.token_hash(trial.token), "canonical_rec_id": forged})["state"] == "refused"
    assert writer.lambda_handler({"action": "delete"})["state"] == "refused"
    assert len(table.heads()) == 1


def test_no_action_or_outcome_is_fabricated(live, table, monkeypatch):
    """The writer can make three rows and only three: an offer, an exposure, his button answer. It imports nothing
    that holds sensor, training or nutrition data, and its answer comes only from the button the page posted."""
    tree = ast.parse(WRITER.read_text())
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("build_")
    }
    assert calls == {"build_offered_head", "build_exposure_event", "build_button_response"}
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imports <= {
        "__future__",
        "logging",
        "os",
        "typing",
        "boto3",
        "boto3.dynamodb.conditions",
        "common.pacific_time",
        "common.platform_logger",
        "coach",
    }
    src = WRITER.read_text()
    assert "EVENT_OUTCOME" not in src and "EVENT_FOLLOW_UP" not in src and "outcome_notes" not in src
    (resp_call,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "build_button_response"]
    kw = {k.arg: ast.unparse(k.value) for k in resp_call.keywords}
    assert kw["response"] == "BUTTON_RESPONSES.get(str(tok.get('response')))"


def test_the_button_vocabulary_maps_onto_the_record():
    assert set(writer.BUTTON_RESPONSES) == set(seam.RESPONSES) == set(seam.RESPONSE_WORDS)
    assert set(writer.BUTTON_RESPONSES.values()) <= set(rr.RESPONSES)
    with pytest.raises(rr.RecommendationError):
        rr.build_button_response(
            user_id="matthew", rec={"rec_id": "x"}, response="completed", answered_at="t", token_hash="0" * 64, send_day=D1, word=""
        )


def test_the_answer_door_authentication_and_replay_tests_exist():
    """The door's own proofs (tests/test_brief_hybrid_trial_6175.py, tests/test_brief_response_scope_6175.py) — named
    here so a rename or deletion of any of them reds this pilot too."""
    need = {
        "tests/test_brief_hybrid_trial_6175.py": (
            "test_the_url_carries_an_opaque_token_and_nothing_else",  # 256-bit, 43-char, SHA-256 at rest, URL = token only
            "test_the_send_records_the_token_hash_never_the_token_and_the_measurement_row",
            "test_opening_the_link_shows_a_confirmation_page_and_writes_nothing",
            "test_only_the_explicit_post_records_and_the_token_is_single_use",
            "test_an_expired_token_records_nothing",
            "test_a_token_is_scoped_to_its_own_row_and_nothing_else_is_accepted",
            "test_both_verbs_are_metered_and_the_meter_fails_closed",
        ),
        "tests/test_brief_response_scope_6175.py": (
            "test_invalid_token_writes_nothing_but_the_limiter_counter",
            "test_a_crafted_body_cannot_retarget_a_write",
            "test_a_get_or_head_with_a_valid_token_records_nothing_and_leaves_the_token_unspent",
            "test_expired_reused_and_malformed_tokens_record_nothing",
            "test_the_site_api_role_cannot_write_the_canonical_recommendation_record",
        ),
    }
    for rel, names in need.items():
        defined = {n.name for n in ast.parse((ROOT / rel).read_text()).body if isinstance(n, ast.FunctionDef)}
        assert set(names) <= defined, (rel, set(names) - defined)
    assert seam.TOKEN_TTL_SECONDS == 48 * 3600 and seam.TOKEN_RE.pattern == r"^[A-Za-z0-9_-]{43}$"


# ══════════════════════════════════════════════════════════════════════════════
# attribution: accountable lead vs origin
# ══════════════════════════════════════════════════════════════════════════════


def test_the_lead_is_accountable_and_the_origin_is_the_real_source(live, table):
    _send(table, D1)
    (head,) = table.heads()
    assert head["coach_id"] == head["accountable_coach_id"] == rr.LEAD_COACH_ID
    assert (head["origin_kind"], head["origin_id"]) == AI_ORIGIN and head["origin_id"] != rr.LEAD_COACH_ID
    v = _view(table, head["rec_id"])
    assert (v["accountable_coach_id"], v["origin_kind"], v["origin_id"]) == (rr.LEAD_COACH_ID, *AI_ORIGIN)


def test_an_unknown_origin_is_recorded_as_unknown_never_as_the_lead():
    from coach import brief_rec_intake as intake

    for src in ("ai_guidance", "readiness", "food_export"):
        kind, oid = intake.origin_of(src)
        assert kind != rr.ORIGIN_UNKNOWN and oid and oid != rr.LEAD_COACH_ID
    assert intake.origin_of("something_new") == (rr.ORIGIN_UNKNOWN, None) and intake.origin_of(None) == (rr.ORIGIN_UNKNOWN, None)
    kw = dict(
        user_id="matthew",
        coach_id=rr.LEAD_COACH_ID,
        text=ADMITTED,
        day="2026-11-25",
        send_day=D1,
        accepted_at="2026-11-25T17:00:00.000Z",
        ses_message_id="m",
        brief_rec_id="2026-11-24#movement",
        source="x",
        recorded_at="2026-11-25T17:00:01.000Z",
    )
    head = rr.build_offered_head(origin_kind=rr.ORIGIN_UNKNOWN, origin_id=None, **kw)
    assert head["origin_kind"] == "unknown" and "origin_id" not in head
    for bad in ((rr.ORIGIN_UNKNOWN, rr.LEAD_COACH_ID), (rr.ORIGIN_SYSTEM, None), (rr.ORIGIN_COACH, "not_a_persona"), ("lead", "x")):
        with pytest.raises(rr.RecommendationError):
            rr.build_offered_head(origin_kind=bad[0], origin_id=bad[1], **kw)
    assert rr.build_offered_head(origin_kind=rr.ORIGIN_COACH, origin_id="sleep_coach", **kw)["origin_id"] == "sleep_coach"


# ══════════════════════════════════════════════════════════════════════════════
# activation boundary, degradation, the switch
# ══════════════════════════════════════════════════════════════════════════════


def test_trial_rows_from_before_activation_are_never_carried(table, monkeypatch):
    """Owner constraint: sends and answers made before the pilot is live stay in the trial partition."""
    sb = _door(monkeypatch, table)
    old = _send(table, D1)  # pilot OFF: the trial as it runs today
    assert "canonical_rec_id" not in old.token_row and _press(sb, old.token, "done") == 200
    _go_live(monkeypatch, table)
    _send(table, "2026-11-25")  # the first send after activation: the SAME recommendation, a REPEAT of that run
    assert len(table.heads()) == 1 and table.heads()[0]["date"] == "2026-11-26"  # offered on its real day
    for _ in range(2):
        _send(table, "2026-11-26", guidance=("Take the stairs at work this morning.",))
    assert not [e for e in table.events() if e["kind"] == rr.EVENT_RESPONSE]  # the pre-activation "done" is never folded
    assert table.store[(TRIAL_PK, "SEND#2026-11-26")]["rec_answers"]["pre_activation"] >= 1
    for path in (WRITER, ROOT / "lambdas/coach/brief_rec_intake.py"):
        assert "reconcil" not in path.read_text().lower()


def test_the_record_unavailable_still_sends_records_nothing_and_logs(live, table):
    table.fail_pk = REC_PK
    log = _Log()
    trial = _send(table, D1, log=log)
    assert trial.block_html and trial.subject
    assert trial.pilot == {"state": "record_unavailable"} and "canonical_rec_id" not in trial.token_row
    assert not any(o[0] in ("put", "update") and o[1] == REC_PK for o in table.ops)
    assert table.store[(TRIAL_PK, "SEND#" + D1)]["rec_pilot_state"] == "record_unavailable"
    assert any("record unavailable" in line for line in log.lines)


def test_a_failed_offer_write_is_logged_and_never_reconstructed(live, table, monkeypatch):
    real_put = table.put_item

    def put(Item=None, **kw):
        if Item["pk"] == REC_PK and Item.get("record_type") == "recommendation":
            raise RuntimeError("InternalServerError")
        return real_put(Item=Item, **kw)

    monkeypatch.setattr(table, "put_item", put)
    log = _Log()
    trial = _send(table, D1, log=log)
    assert table.heads() == [] and table.store[(TRIAL_PK, "SEND#" + D1)]["rec_offer"] == "writer_failed"
    assert any("offer not recorded" in line for line in log.lines)
    _press(_door(monkeypatch, table), trial.token, "done")
    monkeypatch.setattr(table, "put_item", real_put)
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    assert trial.token_row["canonical_rec_id"] not in {h["rec_id"] for h in table.heads()}  # no head made later
    assert not table.events() and table.store[(TRIAL_PK, "SEND#2026-11-25")]["rec_answers"]["no_head"] == 1


def test_an_ineligible_recommendation_is_not_recorded_and_says_why(live, table):
    _send(table, D1, guidance=(NOT_ADMITTED,))
    assert table.heads() == []
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert send["rec_offer"] == "not_eligible" and "not admitted" in send["rec_offer_reason"]
    from coach import brief_rec_intake as intake

    assert intake.eligibility(bh.readiness_rec("red", 40, [40], D1))[0] is False  # a fixed-weight score
    assert intake.eligibility(bh.export_rec(D1, None))[0] is False


def test_the_pilot_ships_dark_and_dark_is_the_trial_as_it_was(table, monkeypatch):
    assert seam.CANONICAL_INTAKE_LIVE is False
    for mod in ("coach.brief_rec_intake", "coach.recommendation_writer_lambda"):
        monkeypatch.setitem(sys.modules, mod, None)  # any import while dark would raise
    trial = _send(table, D1)
    assert trial.pilot is None and trial.follow_token is None and "canonical_rec_id" not in trial.token_row
    assert REC_PK not in {o[1] for o in table.ops}  # not one read or write of the record
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    pilot_fields = {
        "rec_pilot_state",
        "rec_offer",
        "ses_message_id",
        "canonical_rec_id",
        "follow_up_rec_id",
        "rec_answers",
        "pilot_tokens",
        "delivery_state",
    }
    assert not pilot_fields & set(send)
    assert trial.block_html == bh.render_html(trial.view) and "FOLLOW-UP DUE" not in trial.block_html
    assert trial.view.follow_up is None and trial.view.follow_up_url is None and trial.view.respond_note is None


def test_the_handler_hands_record_the_ses_reply_only_for_an_accepted_send():
    src = (ROOT / "lambdas/emails/daily_brief_lambda.py").read_text()
    assert src.count("_ses_sent = ses.send_email(") == 1
    assert 'brief_trial.record(table, USER_PREFIX, _trial, len(html), _persist, logger, sent=locals().get("_ses_sent"))' in src
    i_send, i_rec = src.index("_ses_sent = ses.send_email("), src.index("brief_trial.record(")
    assert src.index('if event.get("_dry_run_resolved"):', i_send - 400) < i_send < i_rec


# ══════════════════════════════════════════════════════════════════════════════
# IAM, read from source (aws_cdk is not installed in the unit suite)
# ══════════════════════════════════════════════════════════════════════════════

_ITEM_WRITES = ["dynamodb:BatchWriteItem", "dynamodb:DeleteItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]


def _fn(path: Path, name: str) -> ast.FunctionDef:
    (fn,) = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name]
    return fn


def test_the_daily_brief_role_cannot_write_the_record_and_may_only_invoke_the_writer():
    src = (ROOT / "cdk/stacks/email_stack.py").read_text()
    tree = ast.parse(src)
    consts = {
        t.id: ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name) and t.id.startswith("RECOMMENDATION_RECORD_")
    }
    assert consts["RECOMMENDATION_RECORD_PK"] == rr.pk("matthew")
    assert sorted(consts["RECOMMENDATION_RECORD_DENIED_ACTIONS"]) == _ITEM_WRITES  # EVERY item write, PutItem included
    body = ast.unparse(_fn(ROOT / "cdk/stacks/email_stack.py", "recommendation_record_no_write"))
    assert "effect=iam.Effect.DENY" in body and "sid='RecommendationRecordNoWrite'" in body
    assert "{'ForAnyValue:StringEquals': {'dynamodb:LeadingKeys': [RECOMMENDATION_RECORD_PK]}}" in body
    assert src.count("_daily_brief.role.add_to_principal_policy(recommendation_record_no_write())") == 1
    assert src.count("recommendation_record_no_write()") == 2  # applied to the daily-brief role only
    email = ast.unparse(_fn(ROOT / "cdk/stacks/role_policies_email.py", "email_daily_brief"))
    assert "function:coach-recommendation-writer" in email and "coach_recommendations" not in email


def test_the_writer_role_is_putitem_only_on_the_record_partition():
    fn = _fn(ROOT / "cdk/stacks/role_policies_compute.py", "compute_recommendation_writer")
    (rec_pk,) = [ast.literal_eval(n.value) for n in fn.body if isinstance(n, ast.Assign) and n.targets[0].id == "rec_pk"]
    assert rec_pk == rr.pk("matthew")
    stmts = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "PolicyStatement"]
    by_sid = {}
    for st in stmts:
        kw = {k.arg: k.value for k in st.keywords}
        by_sid[ast.literal_eval(kw["sid"])] = (
            ast.literal_eval(kw["actions"]),
            ast.unparse(kw["conditions"]) if "conditions" in kw else None,
        )
    assert set(by_sid) == {"RecommendationRecordCreateOnly", "RecordAndTrialRead", "KMS"}
    assert by_sid["RecommendationRecordCreateOnly"] == (
        ["dynamodb:PutItem"],
        "{'ForAllValues:StringEquals': {'dynamodb:LeadingKeys': [rec_pk]}}",
    )
    assert by_sid["RecordAndTrialRead"] == (
        ["dynamodb:GetItem", "dynamodb:Query"],
        "{'ForAllValues:StringEquals': {'dynamodb:LeadingKeys': [rec_pk, 'USER#matthew#SOURCE#brief_trial']}}",
    )
    every_action = [a for acts, _ in by_sid.values() for a in acts]
    assert not set(every_action) & {"dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "dynamodb:*"}
    stack = (ROOT / "cdk/stacks/compute_stack.py").read_text()
    assert 'function_name="coach-recommendation-writer"' in stack and "custom_policies=rp.compute_recommendation_writer()" in stack
