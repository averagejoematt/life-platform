"""tests/test_brief_rec_pilot_6158.py — the Morning Brief as the recommendation record's first intake (#6158 pilot).

Each of the owner's section-6 demonstrations (ruling 2026-11-22, "Pilot acceptance") is one named test below, run
through the REAL brief trial (`emails.brief_trial.prepare` / `record`), the REAL response door
(`web.site_api_brief_response`) and the REAL owner tool (`manage_coach_recommendation`) against one recording fake
table — no AWS. Plus: the pilot ships dark and dark is the trial as it was; trial rows from before activation are
never carried into the record; the record being unavailable never costs the brief and is never reconstructed later.

All fixture text is invented.
"""

from __future__ import annotations

import ast
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
from coach import brief_recommendations as seam, recommendation_record as rr  # noqa: E402
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

    def _check(self, pk):
        if self.fail_pk and pk == self.fail_pk:
            raise RuntimeError("ProvisionedThroughputExceededException")

    def get_item(self, Key=None, **_):
        self.ops.append(("get", Key["pk"], Key["sk"]))
        self._check(Key["pk"])
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item=None, ConditionExpression=None, **_):
        self.ops.append(("put", Item["pk"], Item["sk"]))
        self._check(Item["pk"])
        k = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and k in self.store:
            raise ConditionalCheckFailedException("ConditionalCheckFailedException")
        self.store[k] = dict(Item)
        return {}

    def update_item(self, Key=None, ConditionExpression="", ExpressionAttributeValues=None, **_):
        self.ops.append(("update", Key["pk"], Key["sk"]))
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
        self.ops.append(("query", parts.get("pk"), parts.get("prefix") or str(parts.get("between"))))
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
        return {pk for op, pk, _ in self.ops if op in ("put", "update")}


class _Log:
    def __init__(self):
        self.lines: list = []

    def warning(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    info = error = warning


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(seam, "CANONICAL_INTAKE_LIVE", True)


@pytest.fixture
def table(monkeypatch):
    t = Table()
    monkeypatch.setattr(tcr, "_table_ref", t)
    monkeypatch.setattr(tcr, "_user_id_ref", "matthew")
    return t


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


def test_one_delivered_recommendation_creates_one_record(live, table):
    trial = _send(table, D1)
    (head,) = table.heads()
    assert head["text"] == ADMITTED and head["date"] == "2026-11-25" and head["channel"] == "coach_brief"
    assert head["coach_id"] == rr.LEAD_COACH_ID and head["recorded_by"] == rr.RECORDED_BY_BRIEF
    assert head["ses_message_id"] == "ses-msg-1" and head["offered_at"] and head["brief_rec_id"] == trial.view.decision.rec_id
    assert head["rec_id"] == rr.rec_id_for(rr.LEAD_COACH_ID, "2026-11-25", ADMITTED) and head["follow_up_surface"] == rr.SURFACE_BRIEF
    assert head["evidence"] and "coordinating lead" in head["context"]
    # brief <-> record association, both ways
    (tok,) = table.rows(TRIAL_PK, "TOKEN#")
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert tok["canonical_rec_id"] == send["canonical_rec_id"] == head["rec_id"]
    assert send["rec_offer"] == "recorded" and send["ses_message_id"] == "ses-msg-1"
    v = _view(table, head["rec_id"])
    assert v["response"] == rr.NOT_RECORDED and rr.status_of(v, "2026-11-25") == "active"


def test_a_duplicate_send_creates_no_second_record(live, table):
    _send(table, D1, message_id="ses-msg-1")
    _send(table, D1, message_id="ses-msg-2")  # force_send / a retry of the same brief
    _send(table, D1, guidance=("Walk for 30 minutes after dinner today.",), message_id="ses-msg-3")  # reworded, same run
    assert len(table.heads()) == 1 and table.heads()[0]["ses_message_id"] == "ses-msg-1"
    # and the same recommendation repeated tomorrow links to it rather than making another
    _send(table, "2026-11-25", message_id="ses-msg-4")
    assert len(table.heads()) == 1
    assert table.store[(TRIAL_PK, "SEND#2026-11-25")]["rec_offer"] == "linked"


def test_a_head_put_twice_is_refused_by_its_condition(live, table):
    trial = _prepare(table, D1, (ADMITTED,))
    from coach import brief_rec_intake as intake

    offer = trial.pilot["offer"]
    assert intake.write_offer(table, offer, ses_message_id="m", offered_at="t") == "recorded"
    assert intake.write_offer(table, offer, ses_message_id="m", offered_at="t") == "duplicate"
    assert len(table.heads()) == 1


def test_an_undelivered_brief_creates_no_false_offered_record(live, table):
    trial = _send(table, D1, message_id=None)  # SES returned no MessageId
    assert table.heads() == [] and REC_PK not in table.written_pks()
    assert table.store[(TRIAL_PK, "SEND#" + D1)]["rec_offer"] == "not_delivered"
    # generated (prepared, link stamped) but never sent: record() is never reached -> nothing at all
    t2 = Table()
    _prepare(t2, D1, (ADMITTED,))
    assert REC_PK not in t2.written_pks() and t2.heads() == []
    # a dry run / demo writes nothing for the trial or the record
    t3 = Table()
    bt.record(t3, UP, _prepare(t3, D1, (ADMITTED,)), 10, False, _Log(), sent={"MessageId": "m"})
    assert t3.written_pks() == set()
    assert trial.token_row["canonical_rec_id"]  # the link was stamped, but no head exists to carry an answer into


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
    from coach import brief_rec_intake as intake

    trial = _send(table, D1)
    sb = _door(monkeypatch, table)
    assert _press(sb, trial.token, "done") == 200
    assert _press(sb, trial.token, "done") == 410 and _press(sb, trial.token, "not_doing") == 410  # the door spends once
    n1, n2 = intake.carry_responses(table, TRIAL_PK), intake.carry_responses(table, TRIAL_PK)
    assert (n1["carried"], n2["carried"], n2["already"]) == (1, 0, 1) and len(table.events()) == 1
    # even a carry that did not see the event (a concurrent run) cannot add a second: the key is fixed by the token
    real = rr.read_rows
    monkeypatch.setattr(
        intake.rr, "read_rows", lambda t, u, rid=None: [r for r in real(t, u, rid) if r.get("record_type") != "recommendation_event"]
    )
    n3 = intake.carry_responses(table, TRIAL_PK)
    assert n3["carried"] == 0 and n3["already"] == 1 and len(table.events()) == 1


def test_silence_is_not_recorded_as_acceptance(live, table, monkeypatch):
    trial = _send(table, D1)
    sb = _door(monkeypatch, table)
    get = {"queryStringParameters": {"t": trial.token}, "headers": {"cloudfront-viewer-address": "203.0.113.7:1"}}
    get["requestContext"] = {"http": {"method": "GET"}}
    assert sb.handle_brief_response(get)["statusCode"] == 200  # a scanner opening the link
    for day in ("2026-11-25", "2026-11-26", "2026-11-27"):
        _send(table, day, guidance=("Take the stairs at work this morning.",))
    assert all(e["rec_id"] != trial.token_row["canonical_rec_id"] for e in table.events())
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
    # he agrees a date through the existing workflow (the owner tool)
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-26")
    assert (
        tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-28"})["status"] == "recorded"
    )
    before = _send(table, "2026-11-26", guidance=("Take the stairs at work this morning.",))  # brief for the 27th: not yet due
    assert before.view.follow_up is None and "FOLLOW-UP DUE" not in before.block_html
    due = _send(table, "2026-11-27", guidance=("Take the stairs at work this morning.",))  # brief for the 28th: due
    assert due.view.follow_up["rec_id"] == rid and "FOLLOW-UP DUE" in due.block_html and due.follow_token
    assert table.store[(TRIAL_PK, "SEND#2026-11-27")]["follow_up_rec_id"] == rid
    ftok = table.store[(TRIAL_PK, "TOKEN#" + seam.token_hash(due.follow_token))]
    assert ftok["canonical_rec_id"] == rid and ftok["send_day"] == D1  # the page names the brief that offered it
    again = _send(table, "2026-11-28", guidance=("Take the stairs at work this morning.",))
    assert again.view.follow_up is None  # asked ONCE
    # the follow-up answer is his, carried like any other
    assert _press(sb, due.follow_token, "done") == 200
    _send(table, "2026-11-29", guidance=("Take the stairs at work this morning.",))
    assert _view(table, rid)["response"] == rr.ACCEPTED


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
    # the coach-context pilot (unchanged, dark) asks through the default surface; the brief through its own
    src = (ROOT / "lambdas/coach/coach_context_pilot.py").read_text()
    assert "surface=" not in src and "rr.due_follow_ups(views, day)" in src
    assert "surface=rr.SURFACE_BRIEF" in (ROOT / "lambdas/coach/brief_rec_intake.py").read_text()


def test_a_real_outcome_closes_the_loop(live, table, monkeypatch):
    trial = _send(table, D1)
    rid = trial.token_row["canonical_rec_id"]
    sb = _door(monkeypatch, table)
    assert _press(sb, trial.token, "done") == 200
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-30")
    out = tcr.tool_manage_coach_recommendation({"action": "outcome", "rec_id": rid, "outcome_notes": "Did it four of five days."})
    assert out["status"] == "recorded"
    v = _view(table, rid)
    assert rr.is_closed(v) and v["outcome"]["outcome_notes"] == "Did it four of five days." and v["response"] == rr.ACCEPTED
    # one chain, keyed end to end: send -> token -> head -> response -> outcome
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    resp = next(e for e in table.events() if e["kind"] == rr.EVENT_RESPONSE)
    outc = next(e for e in table.events() if e["kind"] == rr.EVENT_OUTCOME)
    assert send["canonical_rec_id"] == resp["rec_id"] == outc["rec_id"] == rid and resp["send_day"] == D1
    assert outc["recorded_by"] == rr.RECORDED_BY_OWNER and "via" not in outc  # his own report, through his tool


def test_no_action_or_outcome_is_fabricated(live, table, monkeypatch):
    """The intake can make two rows and only two: an offer, and his button answer. Its inputs are the brief's own
    recommendation and the spent token rows; it reads and writes two partitions and imports nothing that holds
    sensor, training or nutrition data."""
    src = (ROOT / "lambdas/coach/brief_rec_intake.py").read_text()
    tree = ast.parse(src)
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("build_")
    }
    assert calls == {"build_offered_head", "build_button_response"}
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imports <= {
        "__future__",
        "logging",
        "dataclasses",
        "datetime",
        "typing",
        "boto3.dynamodb.conditions",
        "common.pacific_time",
        "coach",
    }
    assert "EVENT_OUTCOME" not in src and "EVENT_FOLLOW_UP" not in src and "outcome_notes" not in src
    # the answer is looked up from the button the page posted, nothing else
    (resp_call,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "build_button_response"]
    kw = {k.arg: ast.unparse(k.value) for k in resp_call.keywords}
    assert kw["response"] == "BUTTON_RESPONSES.get(str(tok.get('response')))"
    # and in a full run, every table call is one of the two partitions (or the door's own limiter)
    trial = _send(table, D1)
    _press(_door(monkeypatch, table), trial.token, "done")
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    pilot_ops = {pk for _op, pk, _ in table.ops}
    assert pilot_ops <= {TRIAL_PK, REC_PK, UP + "chronicle"} | {p for p in pilot_ops if str(p).startswith("RATE#brief_response")}


def test_the_button_vocabulary_maps_onto_the_record():
    from coach import brief_rec_intake as intake

    assert set(intake.BUTTON_RESPONSES) == set(seam.RESPONSES) == set(seam.RESPONSE_WORDS)
    assert set(intake.BUTTON_RESPONSES.values()) <= set(rr.RESPONSES)
    with pytest.raises(rr.RecommendationError):
        rr.build_button_response(
            user_id="matthew", rec={"rec_id": "x"}, response="completed", answered_at="t", token_hash="0" * 64, send_day=D1, word=""
        )


# ══════════════════════════════════════════════════════════════════════════════
# activation boundary, degradation, the switch
# ══════════════════════════════════════════════════════════════════════════════


def test_trial_rows_from_before_activation_are_never_carried(table, monkeypatch):
    """Coordinator/owner constraint: sends and answers made before the pilot is live stay in the trial partition."""
    sb = _door(monkeypatch, table)
    old = _send(table, D1)  # pilot OFF: the trial as it runs today
    assert "canonical_rec_id" not in old.token_row and _press(sb, old.token, "done") == 200
    monkeypatch.setattr(seam, "CANONICAL_INTAKE_LIVE", True)
    _send(table, "2026-11-25")  # the first send after activation: the SAME recommendation, a REPEAT of that run
    assert len(table.heads()) == 1 and table.heads()[0]["date"] == "2026-11-26"  # offered on its real day, not the run's start
    for _ in range(2):
        _send(table, "2026-11-26", guidance=("Take the stairs at work this morning.",))
    assert table.events() == []  # the pre-activation "done" is never folded into it
    assert table.store[(TRIAL_PK, "SEND#2026-11-26")]["rec_answers"]["pre_activation"] >= 1
    assert "reconcil" not in (ROOT / "lambdas/coach/brief_rec_intake.py").read_text().split('"""', 2)[2]


def test_the_record_unavailable_still_sends_records_nothing_and_logs(live, table):
    table.fail_pk = REC_PK
    log = _Log()
    trial = _send(table, D1, log=log)
    assert trial.block_html and trial.subject  # the brief goes out as the trial's
    assert trial.pilot == {"state": "record_unavailable"} and "canonical_rec_id" not in trial.token_row
    assert not any(op in ("put", "update") and pk == REC_PK for op, pk, _ in table.ops)
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
    assert table.heads() == [] and table.store[(TRIAL_PK, "SEND#" + D1)]["rec_offer"] == "write_failed"
    assert any("offer not recorded" in line for line in log.lines)
    _press(_door(monkeypatch, table), trial.token, "done")
    monkeypatch.setattr(table, "put_item", real_put)
    _send(table, "2026-11-25", guidance=("Take the stairs at work this morning.",))
    assert trial.token_row["canonical_rec_id"] not in {h["rec_id"] for h in table.heads()}  # no head made later
    assert table.events() == [] and table.store[(TRIAL_PK, "SEND#2026-11-25")]["rec_answers"]["no_head"] == 1


def test_an_ineligible_recommendation_is_not_recorded_and_says_why(live, table):
    _send(table, D1, guidance=(NOT_ADMITTED,))
    assert table.heads() == []
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert send["rec_offer"] == "not_eligible" and "not admitted" in send["rec_offer_reason"]
    from coach import brief_rec_intake as intake

    readiness = bh.readiness_rec("red", 40, [40], D1)
    assert intake.eligibility(readiness)[0] is False  # a fixed-weight score is not a coach's recommendation
    assert intake.eligibility(bh.export_rec(D1, None))[0] is False


def test_the_pilot_ships_dark_and_dark_is_the_trial_as_it_was(table, monkeypatch):
    assert seam.CANONICAL_INTAKE_LIVE is False
    sys.modules.pop("coach.brief_rec_intake", None)
    monkeypatch.setitem(sys.modules, "coach.brief_rec_intake", None)  # any import while dark would raise
    trial = _send(table, D1)
    assert trial.pilot is None and trial.follow_token is None and "canonical_rec_id" not in trial.token_row
    assert REC_PK not in {pk for _op, pk, _ in table.ops}  # not one read or write of the record
    send = table.store[(TRIAL_PK, "SEND#" + D1)]
    assert not {"rec_pilot_state", "rec_offer", "ses_message_id", "canonical_rec_id", "follow_up_rec_id", "rec_answers"} & set(send)
    assert trial.block_html == bh.render_html(trial.view) and "FOLLOW-UP DUE" not in trial.block_html
    assert trial.view.follow_up is None and trial.view.follow_up_url is None


def test_the_handler_hands_record_the_ses_reply_only_for_an_accepted_send():
    """daily_brief_lambda: `_ses_sent` is bound only on the branch that called SES and got a reply; a dry run never
    binds it, and a raising send never reaches `record`."""
    src = (ROOT / "lambdas/emails/daily_brief_lambda.py").read_text()
    assert src.count("_ses_sent = ses.send_email(") == 1
    assert 'brief_trial.record(table, USER_PREFIX, _trial, len(html), _persist, logger, sent=locals().get("_ses_sent"))' in src
    i_send, i_rec = src.index("_ses_sent = ses.send_email("), src.index("brief_trial.record(")
    assert src.index('if event.get("_dry_run_resolved"):', i_send - 400) < i_send < i_rec


def test_the_daily_brief_role_is_append_only_on_the_record_partition():
    sys.path.insert(0, str(ROOT / "cdk"))
    from stacks import role_policies_email as rpe

    stmts = [s.to_statement_json() for s in rpe.email_daily_brief()]
    deny = [s for s in stmts if s.get("Effect") == "Deny"]
    assert len(deny) == 1 and deny[0]["Sid"] == "RecommendationRecordAppendOnly"
    assert sorted(deny[0]["Action"]) == ["dynamodb:BatchWriteItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem"]
    assert deny[0]["Condition"] == {"ForAnyValue:StringEquals": {"dynamodb:LeadingKeys": [rr.pk("matthew")]}}
    assert rpe.RECOMMENDATION_RECORD_PK == rr.pk("matthew")
    allows = [s for s in stmts if s.get("Effect", "Allow") == "Allow"]
    assert not any("coach_recommendations" in str(s) for s in allows)  # no new Allow names the record


def test_a_due_follow_up_is_asked_even_on_a_brief_with_no_recommendation_of_its_own(live, table, monkeypatch):
    rid = _send(table, D1).token_row["canonical_rec_id"]
    monkeypatch.setattr(tcr, "pacific_today", lambda: "2026-11-25")
    tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-27"})
    quiet = _send(table, "2026-11-26", guidance=())  # nothing new and no coaching recommendation that morning
    assert quiet.token is None and quiet.view.follow_up["rec_id"] == rid and quiet.follow_token
    assert (TRIAL_PK, "TOKEN#" + seam.token_hash(quiet.follow_token)) in table.store
    assert table.store[(TRIAL_PK, "SEND#2026-11-26")]["follow_up_rec_id"] == rid
