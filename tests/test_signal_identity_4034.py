"""tests/test_signal_identity_4034.py — hand-offs with identity (#4034 box 5).

`remediation/signal_identity.py` gives every needs-human line a stable id keyed on
(alarm-or-check, StateTransitionedTimestamp), merges each run into
`remediation-log/signal_ledger.json`, and refuses to re-send a line whose state has not
moved. `scripts/alarm_page_close.py` reads the same ledger for the monthly close.

The #3443 co-owned-record trap is contract-tested here: the merge never drops a record it
did not write, a concurrent writer that lands between our read and our write is re-read and
kept (S3 conditional put), an unreadable ledger is never written over, and the merger's own
`_meta.merged_at` is the dead-man's input. The monthly-close tests read a ledger PRODUCED BY
THE WRITER (the fixture is the wire), never a hand-built dict.
"""

import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("remediation", "scripts", "deploy"):
    p = os.path.join(_ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import signal_identity as si  # noqa: E402
from alarm_citation_age import post_dates  # noqa: E402

T0 = datetime(2026, 9, 21, 17, 35, tzinfo=timezone.utc)  # a Monday run
EPISODE = "2026-09-20T11:32:26.123000+00:00"


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _S3:
    """get_object/put_object on the real call shape, with ETag + IfMatch/IfNoneMatch semantics."""

    def __init__(self, deny_read=False):
        self.objects, self.etags, self.puts, self.deny_read = {}, {}, 0, deny_read
        self.before_put = None  # hook: a concurrent writer landing between our read and write

    def get_object(self, Bucket, Key):
        if self.deny_read:
            raise _ClientError("AccessDenied")
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key]), "ETag": self.etags[Key]}

    def put_object(self, Bucket, Key, Body, ContentType, IfMatch=None, IfNoneMatch=None):
        if self.before_put:
            hook, self.before_put = self.before_put, None
            hook(self)
        if IfNoneMatch == "*" and Key in self.objects:
            raise _ClientError("PreconditionFailed")
        if IfMatch is not None and self.etags.get(Key) != IfMatch:
            raise _ClientError("PreconditionFailed")
        self.puts += 1
        self.objects[Key] = Body
        self.etags[Key] = f'"etag-{self.puts}"'
        return {"ETag": self.etags[Key]}

    def ledger(self):
        return json.loads(self.objects[si.SIGNAL_LEDGER_KEY])


def _signals(transitioned=EPISODE):
    return {"alarms": [{"name": "qa-smoke-warnings", "updated": transitioned, "transitioned": transitioned}], "secrets_stale": []}


def _aged_item(transitioned=EPISODE):
    return {
        "issue": "Alarm 'qa-smoke-warnings' has been in ALARM for 3d",
        "action": "x",
        "signal": {"check": "qa-smoke-warnings", "state_ts": transitioned},
    }


# ── identity ────────────────────────────────────────────────────────────────


def test_the_id_is_stable_across_timestamp_spellings():
    a = si.signal_id("qa-smoke-warnings", "2026-09-20T11:32:26.123000+00:00")
    b = si.signal_id("qa-smoke-warnings", "2026-09-20 11:32:26+00:00")
    c = si.signal_id("qa-smoke-warnings", "2026-09-20T04:32:26-07:00")
    assert a == b == c == "qa-smoke-warnings@2026-09-20T11:32:26+00:00"
    assert si.signal_id("qa-smoke-warnings", "2026-09-22T00:00:00Z") != a, "a new transition must be a new id"


def test_keying_deterministic_llm_and_unkeyable_lines():
    sig = _signals()
    assert si.key_item(_aged_item(), sig)[:2] == ("qa-smoke-warnings", "2026-09-20T11:32:26+00:00")
    llm = {"issue": "qa-smoke-warnings is red because of cross_surface:vitals", "action": "fix it"}
    assert si.key_item(llm, sig) == ("qa-smoke-warnings", "2026-09-20T11:32:26+00:00", "alarm")
    # a name that is a PREFIX of another alarm must not key to it
    assert si.key_item({"issue": "qa-smoke-warnings-extra broke"}, sig)[2] == "unkeyed"
    secret = {"issue": "rotate life-platform/ai-keys"}
    sig2 = {"alarms": [], "secrets_stale": [{"name": "life-platform/ai-keys", "last_changed": "2026-03-08T00:00:00+00:00"}]}
    assert si.key_item(secret, sig2)[0] == "secret:life-platform/ai-keys"
    note = si.key_item({"issue": "general musing"}, sig)
    assert note[0].startswith("agent-note:") and note[2] == "unkeyed"


# ── the merge (the co-owned record) ─────────────────────────────────────────


def _obs(sid="qa-smoke-warnings@2026-09-20T11:32:26+00:00", acted=False):
    return [{"id": sid, "check": sid.split("@")[0], "state_ts": sid.split("@")[1], "kind": "alarm", "summary": "s", "acted_on": acted}]


def test_merge_first_seen_renewals_and_idempotence():
    led, new, ren = si.merge(si.empty_ledger(), _obs(), T0)
    sid = _obs()[0]["id"]
    assert new == [sid] and ren == [] and led[sid]["renewals"] == 0 and led[sid]["first_seen"] == "2026-09-21T17:35:00+00:00"
    led, new, ren = si.merge(led, _obs(), T0)  # the same run merging twice changes nothing
    assert led[sid]["renewals"] == 0
    led, new, ren = si.merge(led, _obs(acted=True), T0 + timedelta(days=2))
    assert new == [] and ren == [sid] and led[sid]["renewals"] == 1
    assert led[sid]["first_seen"] == "2026-09-21T17:35:00+00:00", "a renewal rewrote first_seen — the #3443 erasure"
    assert led[sid]["acted_on_at"] == "2026-09-23T17:35:00+00:00"
    assert led[si.META]["merged_at"] == "2026-09-23T17:35:00+00:00" and led[si.META]["created_at"] == "2026-09-21T17:35:00+00:00"


def test_merge_never_drops_a_record_it_did_not_write():
    led, *_ = si.merge(si.empty_ledger(), _obs("other-alarm@2026-09-01T00:00:00+00:00"), T0)
    led, *_ = si.merge(led, _obs(), T0 + timedelta(days=2))
    assert "other-alarm@2026-09-01T00:00:00+00:00" in led


def test_save_rereads_and_keeps_a_concurrent_writers_entry():
    s3 = _S3()
    si.save(s3, "b", _obs("first@2026-09-01T00:00:00+00:00"), T0)

    def concurrent(store):  # a dispatch run lands its own merge between our read and our write
        other, _ = si.load(store, "b")
        other, *_ = si.merge(other, _obs("concurrent@2026-09-02T00:00:00+00:00"), T0 + timedelta(minutes=5))
        store.objects[si.SIGNAL_LEDGER_KEY] = json.dumps(other).encode()
        store.etags[si.SIGNAL_LEDGER_KEY] = '"etag-concurrent"'

    s3.before_put = concurrent
    si.save(s3, "b", _obs(), T0 + timedelta(minutes=6))
    led = s3.ledger()
    assert {"first@2026-09-01T00:00:00+00:00", "concurrent@2026-09-02T00:00:00+00:00", _obs()[0]["id"]} <= set(led), sorted(led)


def test_an_unreadable_ledger_is_never_written_over():
    s3 = _S3(deny_read=True)
    with pytest.raises(_ClientError):
        si.save(s3, "b", _obs(), T0)
    assert s3.puts == 0


# ── the merger's own dead-man ───────────────────────────────────────────────


def test_merger_deadman():
    led, *_ = si.merge(si.empty_ledger(), [], T0)
    assert si.merger_deadman_item(led, T0 + timedelta(hours=72)) is None  # Fri -> Mon, the designed gap
    item = si.merger_deadman_item(led, T0 + timedelta(hours=si.MERGER_STALE_HOURS + 1))
    assert item and "signal-ledger-merger" == item["signal"]["check"]
    assert si.merger_deadman_item(si.empty_ledger(), T0) is None  # first run ever is not stale


# ── the agent: send once, carry after, new episode re-sends ─────────────────


def _agent():
    import agent  # noqa: PLC0415

    return agent


def test_agent_sends_once_then_carries_then_resends_on_a_new_episode(monkeypatch):
    agent = _agent()
    s3 = _S3()
    monkeypatch.setattr(agent, "_citations_and_predicate", lambda: ({}, post_dates))

    r1 = agent.apply_signal_identity({"needs_human": [_aged_item()]}, _signals(), now=T0, s3=s3)
    assert len(r1["needs_human"]) == 1 and r1["needs_human"][0]["signal_id"] == "qa-smoke-warnings@2026-09-20T11:32:26+00:00"
    assert "carried" not in r1

    r2 = agent.apply_signal_identity({"needs_human": [_aged_item()]}, _signals(), now=T0 + timedelta(days=2), s3=s3)
    assert r2["needs_human"] == [], "a line whose state timestamp has not moved was RE-SENT"
    assert r2["carried"][0]["renewals"] == 1 and r2["carried"][0]["first_seen"] == "2026-09-21T17:35:00+00:00"

    new_ep = "2026-09-24T02:00:00+00:00"
    r3 = agent.apply_signal_identity({"needs_human": [_aged_item(new_ep)]}, _signals(new_ep), now=T0 + timedelta(days=4), s3=s3)
    assert len(r3["needs_human"]) == 1, "a NEW episode of the same alarm must be sent"


def test_agent_clean_run_still_stamps_the_merger(monkeypatch):
    agent = _agent()
    s3 = _S3()
    monkeypatch.setattr(agent, "_citations_and_predicate", lambda: ({}, post_dates))
    agent.apply_signal_identity({}, {"alarms": []}, now=T0, s3=s3)
    assert s3.ledger()[si.META]["merged_at"] == "2026-09-21T17:35:00+00:00"


def test_agent_ledger_failure_is_a_line_not_a_crash(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "_citations_and_predicate", lambda: ({}, post_dates))
    out = agent.apply_signal_identity({"needs_human": [_aged_item()]}, _signals(), now=T0, s3=_S3(deny_read=True))
    assert any("could not be merged" in i["issue"] for i in out["needs_human"])


def test_acted_on_means_cited_after_the_episode_began():
    sig = _signals()
    assert si.acted_on_checks(sig, {"qa-smoke-warnings": {"cause_observed": "2026-09-21"}}, post_dates) == {"qa-smoke-warnings"}
    assert si.acted_on_checks(sig, {"qa-smoke-warnings": {"cause_observed": "2026-09-20"}}, post_dates) == set()


def test_every_deterministic_needs_human_builder_stamps_a_signal_key():
    """Guard the SET: every deterministic needs-human item the agent builds carries its key."""
    agent = _agent()
    now = T0
    old = (now - timedelta(days=5)).isoformat()
    sig = {
        "alarms": [{"name": "x-alarm", "updated": old, "transitioned": old}],
        "secrets_stale": [{"name": "s", "age_days": 400, "last_changed": old}],
    }
    items = [i for _, i in agent.aged_alarm_escalations(sig, now=now, audience={})]
    items += [i for _, i in agent.stale_secret_escalations(sig, now=now)]
    items += [i for _, i in agent.ack_ratchet_escalations(sig, {"x-alarm": {"renewals": 5}}, now=now)]
    assert len(items) == 3 and all(i.get("signal", {}).get("check") for i in items), items


# ── the monthly close reads what the writer wrote ───────────────────────────


def _written_ledger():
    """A ledger produced by the WRITER — the fixture is the wire."""
    s3 = _S3()
    si.save(s3, "b", _obs("a3@2026-08-20T00:00:00+00:00"), datetime(2026, 8, 21, tzinfo=timezone.utc))  # last month
    si.save(s3, "b", _obs("a1@2026-09-01T00:00:00+00:00", acted=True), datetime(2026, 9, 2, tzinfo=timezone.utc))
    si.save(s3, "b", _obs("a2@2026-09-05T00:00:00+00:00"), datetime(2026, 9, 6, tzinfo=timezone.utc))
    si.save(s3, "b", _obs("a2@2026-09-05T00:00:00+00:00"), datetime(2026, 9, 8, tzinfo=timezone.utc))  # carried, not a page
    return s3


def test_page_accounting_on_the_writers_ledger():
    s3 = _written_ledger()
    acct = si.page_accounting(
        s3.ledger(), date(2026, 9, 1), date(2026, 10, 1), {"a1", "a2", "a3", "never-fired"}, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert (acct["pages_sent"], acct["pages_acted_on"]) == (2, 1) and acct["ratio"] == 0.5
    assert acct["demote_candidates"] == ["a2", "a3", "never-fired"]
    assert acct["provisional"] and acct["coverage_days"] < 90


def test_page_block_prints_and_fails_on_a_stale_merger():
    import alarm_page_close as apc

    s3 = _written_ledger()
    lines, problems = apc.page_block_lines(
        s3, date(2026, 9, 1), date(2026, 10, 1), now=datetime(2026, 9, 9, tzinfo=timezone.utc), inventory={"a1", "a2"}
    )
    text = "\n".join(lines)
    assert "pages sent 2 · acted on 1 · ratio 50%" in text and "PROVISIONAL" in text and "- a2" in text
    assert problems == []
    _, stale = apc.page_block_lines(
        s3, date(2026, 9, 1), date(2026, 10, 1), now=datetime(2026, 9, 20, tzinfo=timezone.utc), inventory={"a1"}
    )
    assert stale and stale[0][0] == "FAIL" and "merger last ran" in stale[0][1]
    _, unread = apc.page_block_lines(_S3(deny_read=True), date(2026, 9, 1), date(2026, 10, 1), inventory=set())
    assert unread and unread[0][0] == "UNAVAILABLE"


def test_monthly_close_runs_the_page_block():
    with open(os.path.join(_ROOT, "scripts", "monthly_close.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "alarm_page_close.page_block_lines(" in src and "_problem(msg, label)" in src
