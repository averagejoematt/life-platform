#!/usr/bin/env python3
"""tests/test_send_replay_guard_dil025.py — DIL-025: a redriven invocation must
not mail the same letter twice.

The external diligence review (2026-08-23, finding 025, CONFIRMED arch risk)
observed that the platform has external side effects — email senders, write-MCP
tools, webhooks, site writes — with no enterprise-wide statement of which ones
are safe to replay. The census is `docs/IDEMPOTENCY.md`. This file is the
executable half for the sender the census rates highest-consequence: the daily
brief.

**Why the existing guards do not cover this.** Two mechanisms already exist and
neither answers the replay question:

  * `common.send_guard` (#2222) suppresses sends when an OPERATOR asks it to. A
    redrive carries the original scheduled payload, with no suppressor on it, so
    the send gate correctly lets it through. It is not the wrong gate — it is a
    gate for a different question.
  * `daily_brief_lock` (#2860) is a 1200s conditional-put LEASE. It stops the
    async-retry storm it was built for (retries land ~1min and ~2min later) and
    is deliberately short so a genuine crash still gets a real retry. The DLQ
    consumer re-invokes on a `rate(6 hours)` schedule — 18x the lease. The lease
    is structurally incapable of seeing it.

**The vector, end to end.** `daily-brief` routes failures to
`life-platform-ingestion-dlq`. `dlq_consumer_lambda.classify_message` defaults an
unrecognised failure to TRANSIENT, and `retry_message` then re-invokes the
original function with the original payload. A Lambda async-DLQ message body IS
the original invocation event (the consumer's own docstring says so), so the
replayed payload is the EventBridge scheduled event, byte for byte. If the brief
had already mailed before whatever error put it on the queue — and the send sat
~445 lines before the completion record was written, so "sent then crashed" was
a wide window — the redrive mails it again.

The fix is `common.send_ledger`: the completion row the status page already
reads, given a `period_key` naming WHICH brief was sent, written one line after
the SES call and read before the next one.

Structure here:
  1. the replay vector is real, derived from the CDK + consumer source (if the
     DLQ wiring or the retry behaviour ever goes away, these fail and this file
     should be re-read, not deleted);
  2. the wire — the real async-DLQ message shape, run through the REAL consumer
     functions, proving the payload a redrive replays is the original event;
  3. `send_ledger`'s own contract, including both fail-open paths;
  4. the acceptance case — `lambda_handler` invoked with that exact replayed
     event does not reach SES;
  5. non-vacuity — the same invocation with no ledger row DOES proceed, so (4)
     is not passing for an unrelated reason;
  6. structural pins on the two orderings the fix depends on;
  7. **#3113 — the same acceptance case for the rest of the fleet.** DIL-025
     shipped the primitive and wired it into one sender; #3113 extended it to
     eleven more, starting with the two that mail THIRD PARTIES
     (`milestone_digest` → the friends-and-family list, `partner_email` → an
     SSM-resolved partner address). Section 7 drives each of those REAL handlers
     with a seeded ledger row and asserts nothing reaches SES, then removes the
     row and asserts the same invocation proceeds. `docs/IDEMPOTENCY.md` §2b
     carries the nine senders that were assessed and deliberately left without
     the ledger, with the reason each time.

**Mutation proof (how to check these tests are not decoration).** Every §7 case
is paired: `test_*_replay_is_refused` and `test_*_without_the_row_it_proceeds`.
To prove the first is load-bearing, disable the guard in the sender's source —
change its `if send_ledger.should_skip_replay(...)` to `if False:` (or delete the
block) and re-run. Each `*_replay_is_refused` case must FAIL with "reached past the #3113 replay
guard";
the paired `*_without_the_row_it_proceeds` case must still pass, which is what
separates "the guard is gone" from "the handler broke". Both halves were run
this way when #3113 landed. The same trick on `send_ledger.record_sent` (make it
a no-op) fails the `*_records_immediately_after_the_send` case instead.

Safety: no real AWS anywhere. No Lambda is invoked, no mail is sent, no Bedrock
call is made. No email Lambda is ever invoked live by this suite — per the repo's
standing rule, a regen-invoke of an email Lambda sends real mail.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

for _k, _v in [
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
    ("TABLE_NAME", "life-platform"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "brief@example.invalid"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
    ("DLQ_URL", "https://sqs.us-west-2.amazonaws.invalid/1/life-platform-ingestion-dlq"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

from common import (
    dry_run,  # noqa: E402
    send_ledger,  # noqa: E402
)

_import_err = None
try:
    import daily_brief_lambda as brief  # noqa: E402
    import daily_brief_lock as lock  # noqa: E402
    from operational import dlq_consumer_lambda as dlq  # noqa: E402
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    brief = None  # type: ignore
    lock = None  # type: ignore
    dlq = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"daily_brief_lambda unavailable: {_import_err}")  # type: ignore

_LOG = logging.getLogger("test-dil025")

EMAIL_STACK = REPO_ROOT / "cdk" / "stacks" / "email_stack.py"
OPERATIONAL_STACK = REPO_ROOT / "cdk" / "stacks" / "operational_stack.py"
BRIEF_SRC = REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py"
DLQ_SRC = REPO_ROOT / "lambdas" / "operational" / "dlq_consumer_lambda.py"

#: The EventBridge rule ARN shape that appears in a scheduled event's
#: `resources`. `cron(0 17 * * ? *)` is daily-brief's schedule (email_stack.py).
BRIEF_RULE_ARN = "arn:aws:events:us-west-2:205930651321:rule/LifePlatformEmail-DailyBriefSchedule"


def wire_scheduled_event(when: str = "2026-08-24T17:00:00Z") -> dict:
    """THE WIRE: the exact event AWS delivers for a `cron(0 17 * * ? *)` rule.

    This is what daily-brief's scheduled invocation receives, what Lambda copies
    verbatim into the async DLQ on failure, and therefore what the DLQ consumer
    replays. Every assertion below drives this shape rather than a hand-friendly
    `{"dry_run": ...}` stub — a guard proved only against a convenient fixture
    is not proved against the thing that actually arrives.
    """
    return {
        "version": "0",
        "id": "d9a1f0e2-6b3c-4a71-9e15-2f8c4b7d0a33",
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "account": "205930651321",
        "time": when,
        "region": "us-west-2",
        "resources": [BRIEF_RULE_ARN],
        "detail": {},
    }


@pytest.fixture(autouse=True)
def _no_ambient_suppressors(monkeypatch):
    """A stray DRY_RUN in the environment would make every send-path assertion
    below pass vacuously — the brief would suppress its own send for an
    unrelated reason and the guard would never be exercised."""
    for name in dry_run.SUPPRESSOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# 1. The replay vector is real — derived from source, not asserted from memory
# ══════════════════════════════════════════════════════════════════════════════


class TestTheReplayVectorIsReal:
    def test_daily_brief_routes_its_failures_to_the_shared_dlq(self):
        """No DLQ, no redrive. The whole finding rests on this wiring."""
        src = EMAIL_STACK.read_text(encoding="utf-8")
        assert "dlq=local_dlq" in src, "email stack no longer attaches the shared DLQ — re-derive DIL-025's premise"
        assert 'function_name="daily-brief"' in src

    def test_the_dlq_consumer_reinvokes_the_original_function_with_the_original_payload(self):
        """The re-invoke is the mechanism. If this is ever removed, the daily
        brief's redrive exposure goes with it."""
        src = DLQ_SRC.read_text(encoding="utf-8")
        assert "def retry_message(" in src
        assert "lam.invoke(" in src
        assert 'Payload=body_str.encode("utf-8")' in src, "the consumer no longer replays the ORIGINAL body — re-read DIL-025"

    def test_an_unclassified_failure_defaults_to_retry(self):
        """A brief failure with no recognised error pattern is classified
        TRANSIENT, i.e. it takes the re-invoke path. The exposure is the default
        case, not an exotic one."""
        msg = {"Body": json.dumps(wire_scheduled_event()), "Attributes": {"ApproximateReceiveCount": "1"}}
        assert dlq.classify_message(msg) == "transient"

    def test_the_redrive_window_is_far_longer_than_the_inflight_lease(self):
        """THE gap DIL-025 names. #2860's lease is 1200s; the consumer runs
        every 6 hours. A lease cannot cover a redrive, so a durable record is
        the only thing that can."""
        src = OPERATIONAL_STACK.read_text(encoding="utf-8")
        assert "rate(6 hours)" in src, "dlq-consumer cadence changed — re-derive the window in docs/IDEMPOTENCY.md"
        assert lock.DAILY_BRIEF_LOCK_TTL_SECONDS < 6 * 3600


# ══════════════════════════════════════════════════════════════════════════════
# 2. The wire — a real async-DLQ message, through the real consumer functions
# ══════════════════════════════════════════════════════════════════════════════


class TestTheRedrivePayloadIsTheOriginalEvent:
    def test_the_consumer_resolves_the_rule_to_daily_brief(self, monkeypatch):
        """`extract_function_name` resolves an EventBridge failure through the
        rule's target. Only the AWS call is stubbed — with its real response
        shape — so the parsing under test is the shipped parsing."""
        monkeypatch.setattr(dlq, "_rule_fn_cache", {})
        monkeypatch.setattr(
            dlq.events,
            "list_targets_by_rule",
            lambda Rule: {"Targets": [{"Id": "Target0", "Arn": "arn:aws:lambda:us-west-2:205930651321:function:daily-brief"}]},
        )
        resolved = dlq.extract_function_name({"Body": json.dumps(wire_scheduled_event())})
        assert resolved is not None and resolved.endswith(":function:daily-brief")

    def test_the_replayed_payload_is_byte_identical_to_the_original_event(self, monkeypatch):
        """The premise of the entire finding: what gets re-invoked is the
        original scheduled event, so the second run computes the same brief date
        and would build the same letter. Captured off the REAL `retry_message`."""
        original = wire_scheduled_event()
        body_str = json.dumps(original)
        captured = {}

        class _FakeLambdaClient:
            def invoke(self, FunctionName, InvocationType, Payload):
                captured["fn"] = FunctionName
                captured["payload"] = Payload
                captured["type"] = InvocationType
                return {"StatusCode": 202}

        monkeypatch.setattr(dlq, "lam", _FakeLambdaClient())
        assert dlq.retry_message({"Body": body_str}, "daily-brief") is True
        assert captured["type"] == "Event", "an async re-invoke is what Lambda retries again on failure"
        assert json.loads(captured["payload"].decode("utf-8")) == original


# ══════════════════════════════════════════════════════════════════════════════
# 3. send_ledger's own contract
# ══════════════════════════════════════════════════════════════════════════════


class _FakeLedgerTable:
    """A DDB stand-in for exactly the two calls send_ledger makes: a put and a
    newest-first bounded Query on one partition."""

    def __init__(self):
        self.rows: list = []
        self.put_error: Exception | None = None
        self.query_error: Exception | None = None
        self.queries: list = []

    def put_item(self, Item=None, **kw):
        if self.put_error:
            raise self.put_error
        self.rows = [r for r in self.rows if (r["pk"], r["sk"]) != (Item["pk"], Item["sk"])]
        self.rows.append(Item)
        return {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ScanIndexForward=True, Limit=None, **kw):
        if self.query_error:
            raise self.query_error
        self.queries.append({"pk": ExpressionAttributeValues[":pk"], "forward": ScanIndexForward, "limit": Limit})
        items = [r for r in self.rows if r["pk"] == ExpressionAttributeValues[":pk"]]
        items.sort(key=lambda r: r["sk"], reverse=not ScanIndexForward)
        return {"Items": items[:Limit] if Limit else items}


class TestSendLedger:
    def test_a_recorded_period_is_reported_as_already_sent(self):
        t = _FakeLedgerTable()
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23") is False
        send_ledger.record_sent(t, "daily_brief", "2026-08-23")
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23") is True

    def test_a_different_period_is_not_blocked(self):
        """The guard must stop a REPLAY, never tomorrow's legitimate brief."""
        t = _FakeLedgerTable()
        send_ledger.record_sent(t, "daily_brief", "2026-08-23")
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-24") is False

    def test_a_different_sender_has_its_own_ledger(self):
        t = _FakeLedgerTable()
        send_ledger.record_sent(t, "daily_brief", "2026-08-23")
        assert send_ledger.already_sent(t, "weekly_digest", "2026-08-23") is False

    def test_the_guard_survives_a_send_that_crossed_utc_midnight(self):
        """The case a sort-key-only check misses, and the reason `period_key`
        exists. The brief sends at 17:00 UTC; a 6-hourly redrive lands the NEXT
        UTC day about half the time. The row's sort key is then yesterday's,
        while the brief being replayed is the same one."""
        t = _FakeLedgerTable()
        sent_at = int(datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc).timestamp())
        send_ledger.record_sent(t, "daily_brief", "2026-08-23", now=sent_at)
        assert t.rows[0]["sk"] == "DATE#2026-08-24", "sanity: the row is filed under the SEND day"
        assert t.rows[0]["period_key"] == "2026-08-23", "…but records the BRIEF day"
        # The redrive, 6h later, is now the 25th in UTC — and must still be caught.
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23") is True

    def test_the_read_is_newest_first_and_bounded(self):
        """A replay is recent by construction, so the guard must never turn into
        an unbounded partition scan on a 90-day log."""
        t = _FakeLedgerTable()
        send_ledger.already_sent(t, "daily_brief", "2026-08-23")
        assert t.queries[0]["forward"] is False
        assert t.queries[0]["limit"] == send_ledger.DEFAULT_LOOKBACK

    def test_a_read_failure_fails_OPEN(self):
        """A broken guard must degrade to today's behaviour — a duplicate at
        worst — never to a silently unsent brief."""
        t = _FakeLedgerTable()
        t.query_error = RuntimeError("throttled")
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23", logger=_LOG) is False

    def test_a_write_failure_never_raises_after_the_mail_has_gone(self):
        t = _FakeLedgerTable()
        t.put_error = RuntimeError("throttled")
        send_ledger.record_sent(t, "daily_brief", "2026-08-23", logger=_LOG)  # must not raise

    def test_rows_written_before_this_shipped_never_match(self):
        """Rollout safety: a pre-DIL-025 row carries no `period_key`, so the
        guard simply does not fire on it. Nothing to backfill, and the arming is
        a no-op rather than a day where the brief refuses to send."""
        t = _FakeLedgerTable()
        t.rows.append({"pk": send_ledger.email_log_pk("daily_brief"), "sk": "DATE#2026-08-24", "status": "success"})
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23") is False

    def test_the_writer_and_the_reader_agree_on_the_partition(self):
        """A guard that reads a partition nobody writes is silent and passes
        every test that only checks one side."""
        t = _FakeLedgerTable()
        send_ledger.record_sent(t, "daily_brief", "2026-08-23")
        assert t.rows[0]["pk"] == send_ledger.email_log_pk("daily_brief")
        assert send_ledger.already_sent(t, "daily_brief", "2026-08-23") is True

    def test_the_row_still_looks_like_the_status_pages_row(self):
        """DIL-025 must not have quietly changed the surface the status page and
        the missing-send alarm read (`site_api_status._last_sync`)."""
        t = _FakeLedgerTable()
        send_ledger.record_sent(t, "daily_brief", "2026-08-23")
        row = t.rows[0]
        assert row["pk"] == "USER#matthew#SOURCE#email_log#daily_brief"
        assert row["sk"].startswith("DATE#")
        assert row["status"] == "success"
        assert "sent_at" in row and row["ttl"] > 0

    @pytest.mark.parametrize("event", [{"force_send": True}, {"forceSend": True}, {"detail": {"force_send": True}}])
    def test_force_send_is_honoured_as_an_explicit_resend(self, event):
        assert send_ledger.force_resend_requested(event) is True

    @pytest.mark.parametrize("event", [None, {}, wire_scheduled_event(), {"force_send": False}, {"force_send": "false"}])
    def test_an_ordinary_invocation_is_not_a_forced_resend(self, event):
        assert send_ledger.force_resend_requested(event) is False

    def test_send_ledger_does_not_define_its_own_force_vocabulary(self):
        """Same property `test_send_guard_does_not_define_its_own_resolution`
        pins for the send gate: one list, one reader (#2255/#2222)."""
        for leaked in ("FORCE_SEND_EVENT_KEYS", "SUPPRESSOR_EVENT_KEYS", "_truthy"):
            assert not hasattr(send_ledger, leaked), f"send_ledger re-grew its own flag resolution ({leaked})"


# ══════════════════════════════════════════════════════════════════════════════
# 4 + 5. lambda_handler — the acceptance case, and its non-vacuity
# ══════════════════════════════════════════════════════════════════════════════


class _FakeBriefTable(_FakeLedgerTable):
    """Adds the conditional put `acquire_daily_brief_lock` issues, so the #2860
    lease behaves as it really does and cannot be what short-circuits us."""

    def put_item(self, Item=None, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        if ConditionExpression:
            from botocore.exceptions import ClientError

            existing = next((r for r in self.rows if (r["pk"], r["sk"]) == (Item["pk"], Item["sk"])), None)
            if existing is not None:
                now = (ExpressionAttributeValues or {}).get(":now")
                ttl = existing.get("ttl")
                if not (ttl is not None and now is not None and ttl < now):
                    raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
        return super().put_item(Item=Item)


def _seed_sent(table, period_key, sent_on="2026-08-24"):
    table.rows.append(
        {
            "pk": send_ledger.email_log_pk("daily_brief"),
            "sk": f"DATE#{sent_on}",
            "status": "success",
            "sent_at": f"{sent_on}T17:00:00+00:00",
            send_ledger.PERIOD_KEY_ATTR: period_key,
            "ttl": Decimal(9999999999),
        }
    )


def _brief_date_for(event):
    """The content date the handler derives — `yesterday` in UTC. Computed the
    same way the handler computes it so the fixture cannot drift from it."""
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


class _Sentinel(Exception):
    """Raised by a stub to prove execution reached past the guard."""


class TestARedrivenInvocationDoesNotDoubleSend:
    def test_the_replayed_scheduled_event_does_not_reach_ses(self, monkeypatch):
        """THE acceptance case. The brief already sent for this date; the DLQ
        consumer replays the original scheduled event; nothing mails."""
        event = wire_scheduled_event()
        t = _FakeBriefTable()
        _seed_sent(t, _brief_date_for(event))
        monkeypatch.setattr(brief, "table", t)

        def _must_not_be_called(*a, **kw):
            raise AssertionError("reached past the DIL-025 replay guard — this is the second brief the guard exists to prevent")

        # SES first: a duplicate letter is the harm. The rest are the expensive
        # work a short-circuit must also skip.
        monkeypatch.setattr(brief.ses, "send_email", _must_not_be_called)
        monkeypatch.setattr(brief, "fetch_profile", _must_not_be_called)
        monkeypatch.setattr(brief, "gather_daily_data", _must_not_be_called)
        monkeypatch.setattr(brief, "_run_ai_coach_pipeline", _must_not_be_called)

        out = brief.lambda_handler(event, None)

        assert out["statusCode"] == 200
        assert "already sent" in out["body"]
        assert _brief_date_for(event) in out["body"]

    def test_mutation_with_no_ledger_row_the_SAME_event_proceeds_to_build(self, monkeypatch):
        """Non-vacuity. Identical event, identical fixture, only the ledger row
        removed — execution must now get PAST the guard. Without this, the test
        above would pass just as well against a handler that always returns
        early, and the guard would be decoration."""
        event = wire_scheduled_event()
        t = _FakeBriefTable()  # no seeded send
        monkeypatch.setattr(brief, "table", t)
        monkeypatch.setattr(brief, "fetch_profile", lambda *a, **kw: (_ for _ in ()).throw(_Sentinel()))

        with pytest.raises(_Sentinel):
            brief.lambda_handler(event, None)

    def test_a_ledger_row_for_a_DIFFERENT_brief_date_does_not_block(self, monkeypatch):
        """Yesterday's send must never suppress today's brief — the failure mode
        that would turn this guard into a silent outage."""
        event = wire_scheduled_event()
        t = _FakeBriefTable()
        _seed_sent(t, "1999-01-01")
        monkeypatch.setattr(brief, "table", t)
        monkeypatch.setattr(brief, "fetch_profile", lambda *a, **kw: (_ for _ in ()).throw(_Sentinel()))

        with pytest.raises(_Sentinel):
            brief.lambda_handler(event, None)

    def test_an_operator_can_force_a_resend(self, monkeypatch):
        """`force_send` already means "really send" for the dry-run gate; the
        replay guard must not become a new way to refuse a human's explicit
        instruction."""
        event = dict(wire_scheduled_event(), force_send=True)
        t = _FakeBriefTable()
        _seed_sent(t, _brief_date_for(event))
        monkeypatch.setattr(brief, "table", t)
        monkeypatch.setattr(brief, "fetch_profile", lambda *a, **kw: (_ for _ in ()).throw(_Sentinel()))

        with pytest.raises(_Sentinel):
            brief.lambda_handler(event, None)

    def test_a_ledger_read_failure_still_lets_the_brief_send(self, monkeypatch):
        """Fail-open, end to end: a DDB hiccup in the guard must not be the
        reason the day's brief never goes out."""
        event = wire_scheduled_event()
        t = _FakeBriefTable()
        _seed_sent(t, _brief_date_for(event))
        t.query_error = RuntimeError("throttled")
        monkeypatch.setattr(brief, "table", t)
        monkeypatch.setattr(brief, "fetch_profile", lambda *a, **kw: (_ for _ in ()).throw(_Sentinel()))

        with pytest.raises(_Sentinel):
            brief.lambda_handler(event, None)

    def test_a_dry_run_is_never_blocked_by_the_guard(self, monkeypatch):
        """A dry run mails nothing, so it has nothing to replay — and must stay
        usable for diagnosing the very send the ledger has recorded."""
        event = dict(wire_scheduled_event(), dry_run=True)
        t = _FakeBriefTable()
        _seed_sent(t, _brief_date_for(event))
        monkeypatch.setattr(brief, "table", t)
        monkeypatch.setattr(brief, "fetch_profile", lambda *a, **kw: (_ for _ in ()).throw(_Sentinel()))

        with pytest.raises(_Sentinel):
            brief.lambda_handler(event, None)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Structural pins — the two orderings the fix depends on
# ══════════════════════════════════════════════════════════════════════════════


class TestOrdering:
    def test_the_replay_guard_sits_before_the_profile_fetch(self):
        """Same idiom as #2860's pin. The guard must short-circuit before any
        expensive read, not merely before the send."""
        src = BRIEF_SRC.read_text(encoding="utf-8")
        guard_at = src.index('send_ledger.already_sent(table, "daily_brief", yesterday')
        lease_at = src.index("if not acquire_daily_brief_lock(yesterday, _dry_run")
        fetch_at = src.index("profile = fetch_profile()", guard_at)
        assert lease_at < guard_at, "the cheap in-memory-ish lease should be claimed before the ledger read"
        assert guard_at < fetch_at, "the replay guard must run before the profile fetch"

    def test_the_completion_row_is_written_immediately_after_the_send(self):
        """The window this closes. The record used to sit at the very end of the
        handler, ~445 lines and a dozen fail-soft side quests after the mail was
        already gone; a crash in any of them lost the only evidence of the send
        and left the redrive free to repeat it. Anything more than a few lines
        here is that window creeping back."""
        src = BRIEF_SRC.read_text(encoding="utf-8")
        send_at = src.index('EmailTags=[{"Name": "message_type", "Value": "daily_brief"}]')
        record_at = src.index('record_email_send(table, "daily_brief", yesterday)', send_at)
        gap = src.count("\n", send_at, record_at)
        assert gap < 15, f"the completion record drifted {gap} lines from the send it records"

    def test_the_sick_day_branch_also_records_its_send(self):
        """#2221 fixed this branch once already (it returned before recording,
        so every sick day raised a false missed-brief alarm). DIL-025 gives the
        same row replay meaning, so the branch must still write one."""
        src = BRIEF_SRC.read_text(encoding="utf-8")
        assert src.count('record_email_send(table, "daily_brief", yesterday)') == 2

    def test_the_brief_imports_the_shared_ledger_not_a_local_copy(self):
        """AST rather than a source substring: ruff reformats this import block
        into a parenthesized `from common import (dry_run, send_ledger)` the
        moment a second name is added to it, and a literal-string pin would go
        green-to-red on pure formatting — or, worse, quietly stop matching while
        still looking like it checks something."""
        import ast

        tree = ast.parse(BRIEF_SRC.read_text(encoding="utf-8"))
        imported = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == "common" for alias in node.names
        }
        assert "send_ledger" in imported, "daily-brief must use the shared ledger, not a local copy of it"


# ══════════════════════════════════════════════════════════════════════════════
# 7. #3113 — the same acceptance case, for the rest of the fleet
#
# One shape per sender, because the period semantics are per-sender and a swept
# copy-paste is exactly what the issue said not to ship. Each block:
#   (a) seeds the sender's own period key and proves NOTHING reaches SES;
#   (b) removes the row and proves the SAME invocation gets past the guard
#       (non-vacuity — without this, an always-return-early handler passes (a));
#   (c) where it matters, proves the completion row lands right after the send.
#
# See the module docstring for the mutation-proof recipe.
# ══════════════════════════════════════════════════════════════════════════════

for _k, _v in [
    ("S3_BUCKET", "matthew-life-platform"),
    ("SITE_URL", "https://averagejoematt.invalid"),
    ("DIGEST_SECRET", "life-platform/digest"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "web"))

_fleet_import_err = None
try:
    from compute import weekly_signal_lambda as weekly_signal  # noqa: E402
    from emails import (  # noqa: E402
        ai_review_pack_lambda as review_pack,
        anomaly_detector_lambda as anomaly,
        between_chronicle_lambda as between,
        evening_nudge_lambda as nudge,
        insight_email_parser_lambda as parser,
        milestone_digest_lambda as milestone,
        monday_compass_lambda as compass,
        nutrition_review_lambda as nutrition,
        partner_email_lambda as partner,
        weekly_digest_lambda as weekly,
        weekly_plate_lambda as plate,
    )
except Exception as _e:  # pragma: no cover — only when the bundle layout changes
    _fleet_import_err = _e

fleet = pytest.mark.skipif(_fleet_import_err is not None, reason=f"fleet senders unavailable: {_fleet_import_err}")


def _utc_today():
    return datetime.now(timezone.utc).date()


def _this_iso_week(offset_days: int = 0) -> str:
    return f"week:{send_ledger.iso_week_key(_utc_today() - timedelta(days=offset_days))}"


class _FleetTable(_FakeLedgerTable):
    """The ledger fake, plus the two extra reads some fleet senders make on the
    same handle before the guard can matter."""

    def get_item(self, Key=None, **kw):
        return {}

    def update_item(self, **kw):
        return {}


def _seed(table, lambda_name, period_key, user_id="matthew", sent_on="2026-08-24"):
    table.rows.append(
        {
            "pk": send_ledger.email_log_pk(lambda_name, user_id),
            "sk": f"DATE#{sent_on}",
            "status": "success",
            "sent_at": f"{sent_on}T12:00:00+00:00",
            send_ledger.PERIOD_KEY_ATTR: period_key,
            "ttl": Decimal(9999999999),
        }
    )
    return table


def _explode(*a, **kw):
    raise AssertionError("reached past the #3113 replay guard — this is the duplicate letter the guard exists to prevent")


def _sentinel(*a, **kw):
    raise _Sentinel()


# ── 7a. milestone_digest — THIRD PARTY (friends-and-family list) ───────────────


@fleet
class TestMilestoneDigestReplay:
    """The highest-consequence sender in the census: a duplicate here reaches
    people who are not Matthew. Its period key is the MILESTONE ID, not a
    calendar period — the digest is episodic, runs daily, and mails only when a
    window-validated milestone lands."""

    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    @pytest.fixture
    def wired(self, monkeypatch):
        t = _FleetTable()
        monkeypatch.setattr(milestone, "table", t)
        monkeypatch.setattr(
            milestone, "_load_config", lambda: ([{"email": f"f{i}@example.invalid", "name": f"F{i}"} for i in range(5)], "m@x")
        )
        monkeypatch.setattr(milestone, "_celebration_allowed", lambda: True)
        monkeypatch.setattr(
            milestone.milestone_ledger,
            "read_digest_state",
            lambda *a, **kw: {"has_genesis": True, "sent_ids": set(), "last_sent_date": None},
        )
        monkeypatch.setattr(
            milestone.milestone_ledger,
            "read_announced_events",
            lambda *a, **kw: [{"milestone_id": "M-2026-08-24-weight", "label": "Down 30 lb", "event_date": "2026-08-24"}],
        )
        monkeypatch.setattr(milestone.milestone_ledger, "mark_digest_sent", lambda *a, **kw: None)
        return t

    def test_the_period_key_is_the_milestone_not_the_day(self):
        assert milestone._period_key("M-1") == "milestone:M-1"

    def test_replay_is_refused(self, wired, monkeypatch):
        _seed(wired, "milestone_digest", "milestone:M-2026-08-24-weight")
        monkeypatch.setattr(milestone.ses, "send_email", _explode)
        out = milestone.lambda_handler(dict(self.EVENT), None)
        assert out["status"] == "already_sent"

    def test_without_the_row_it_proceeds(self, wired, monkeypatch):
        """Non-vacuity: identical fixture, no ledger row — the fan-out runs."""
        sent = []
        monkeypatch.setattr(milestone.ses, "send_email", lambda **kw: sent.append(kw["Destination"]["ToAddresses"][0]))
        out = milestone.lambda_handler(dict(self.EVENT), None)
        assert out["status"] == "sent" and len(sent) == 5

    def test_the_row_is_written_after_the_FIRST_delivery_not_the_last(self, wired, monkeypatch):
        """The fan-out window: `mark_digest_sent` lands after all five sends, so
        'mailed two people, then crashed' left no record and a redrive re-mailed
        everyone. The ledger row must exist by the time the SECOND send starts."""
        rows_at_second_send = []

        def _capture(**kw):
            rows_at_second_send.append(len(wired.rows))

        monkeypatch.setattr(milestone.ses, "send_email", _capture)
        milestone.lambda_handler(dict(self.EVENT), None)
        assert rows_at_second_send[0] == 0, "no row before the first letter is on the wire"
        assert rows_at_second_send[1] == 1, "the row must exist before the SECOND recipient is mailed"

    def test_an_operator_can_still_force_the_resend(self, wired, monkeypatch):
        _seed(wired, "milestone_digest", "milestone:M-2026-08-24-weight")
        sent = []
        monkeypatch.setattr(milestone.ses, "send_email", lambda **kw: sent.append(1))
        out = milestone.lambda_handler(dict(self.EVENT, force_send=True), None)
        assert out["status"] == "sent" and len(sent) == 5

    def test_a_different_milestone_is_not_blocked(self, wired, monkeypatch):
        """The failure mode that would make this guard an outage: yesterday's
        note must never suppress today's genuinely new milestone."""
        _seed(wired, "milestone_digest", "milestone:SOMETHING-ELSE")
        sent = []
        monkeypatch.setattr(milestone.ses, "send_email", lambda **kw: sent.append(1))
        assert milestone.lambda_handler(dict(self.EVENT), None)["status"] == "sent"


# ── 7b. partner_email — THIRD PARTY (SSM-resolved partner address) ─────────────


@fleet
class TestPartnerEmailReplay:
    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    def test_the_period_key_is_an_iso_week(self):
        assert partner._period_key() == _this_iso_week(1)

    def test_replay_is_refused_before_the_gather_and_the_sonnet_call(self, monkeypatch):
        t = _seed(_FleetTable(), "partner_weekly", partner._period_key())
        monkeypatch.setattr(partner, "table", t)
        monkeypatch.setattr(partner, "gather_all", _explode)  # expensive work, also skipped
        monkeypatch.setattr(partner.ses, "send_email", _explode)
        out = partner.lambda_handler(dict(self.EVENT), None)
        assert out["statusCode"] == 200 and "already sent" in out["body"]

    def test_without_the_row_it_proceeds(self, monkeypatch):
        monkeypatch.setattr(partner, "table", _FleetTable())
        monkeypatch.setattr(partner, "gather_all", _sentinel)
        with pytest.raises(_Sentinel):
            partner.lambda_handler(dict(self.EVENT), None)

    def test_last_weeks_letter_does_not_block_this_weeks(self, monkeypatch):
        t = _seed(_FleetTable(), "partner_weekly", "week:1999-W01")
        monkeypatch.setattr(partner, "table", t)
        monkeypatch.setattr(partner, "gather_all", _sentinel)
        with pytest.raises(_Sentinel):
            partner.lambda_handler(dict(self.EVENT), None)

    def test_a_dry_run_is_never_blocked(self, monkeypatch):
        t = _seed(_FleetTable(), "partner_weekly", partner._period_key())
        monkeypatch.setattr(partner, "table", t)
        monkeypatch.setattr(partner, "gather_all", _sentinel)
        with pytest.raises(_Sentinel):
            partner.lambda_handler(dict(self.EVENT, dry_run=True), None)

    def test_a_ledger_read_failure_still_lets_the_letter_go(self, monkeypatch):
        """Fail-open end to end: a DDB hiccup must not be why the partner's
        letter never arrives."""
        t = _seed(_FleetTable(), "partner_weekly", partner._period_key())
        t.query_error = RuntimeError("throttled")
        monkeypatch.setattr(partner, "table", t)
        monkeypatch.setattr(partner, "gather_all", _sentinel)
        with pytest.raises(_Sentinel):
            partner.lambda_handler(dict(self.EVENT), None)


# ── 7c. the reader/owner-facing weekly letters ────────────────────────────────


@fleet
class TestWeeklyLettersReplay:
    """Five weekly senders, one shape each. Parameterised on the SPEC, not on a
    single assumed period rule: `monday_compass` keys on THIS week (it is the
    letter for the week ahead) while the look-back senders key on yesterday's,
    and getting that backwards is the "silently unsent letter" failure the issue
    warned is worse than the duplicate."""

    # (module, ledger name, expected period key, the first expensive call to sentinel)
    SPECS = [
        (lambda: weekly, "weekly_digest", lambda: _this_iso_week(1), "gather_all"),
        (lambda: plate, "weekly_plate", lambda: _this_iso_week(1), "gather_data"),
        (lambda: compass, "monday_compass", lambda: _this_iso_week(0), "_fetch_todoist_token"),
        (lambda: nutrition, "nutrition_review", lambda: _this_iso_week(0), "gather_nutrition_data"),
        (lambda: between, "between_chronicle", lambda: _this_iso_week(0), "gather_digest"),
    ]
    IDS = ["weekly_digest", "weekly_plate", "monday_compass", "nutrition_review", "between_chronicle"]
    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    @pytest.mark.parametrize("spec", SPECS, ids=IDS)
    def test_replay_is_refused_before_any_expensive_work(self, spec, monkeypatch):
        mod, name, key, first_call = spec
        mod = mod()
        t = _seed(_FleetTable(), name, key())
        monkeypatch.setattr(mod, "table", t)
        monkeypatch.setattr(mod, first_call, _explode)
        monkeypatch.setattr(mod.ses, "send_email", _explode)
        out = mod.lambda_handler(dict(self.EVENT), None)
        assert out["statusCode"] == 200

    @pytest.mark.parametrize("spec", SPECS, ids=IDS)
    def test_without_the_row_the_same_event_proceeds(self, spec, monkeypatch):
        """Non-vacuity. Identical event, identical fixture, only the row gone."""
        mod, name, key, first_call = spec
        mod = mod()
        monkeypatch.setattr(mod, "table", _FleetTable())
        monkeypatch.setattr(mod, first_call, _sentinel)
        with pytest.raises(_Sentinel):
            mod.lambda_handler(dict(self.EVENT), None)

    @pytest.mark.parametrize("spec", SPECS, ids=IDS)
    def test_a_different_week_does_not_block(self, spec, monkeypatch):
        """The outage-shaped failure mode: last week's row must never suppress
        this week's letter."""
        mod, name, key, first_call = spec
        mod = mod()
        monkeypatch.setattr(mod, "table", _seed(_FleetTable(), name, "week:1999-W01"))
        monkeypatch.setattr(mod, first_call, _sentinel)
        with pytest.raises(_Sentinel):
            mod.lambda_handler(dict(self.EVENT), None)

    @pytest.mark.parametrize("spec", SPECS, ids=IDS)
    def test_an_operator_can_force_a_resend(self, spec, monkeypatch):
        mod, name, key, first_call = spec
        mod = mod()
        monkeypatch.setattr(mod, "table", _seed(_FleetTable(), name, key()))
        monkeypatch.setattr(mod, first_call, _sentinel)
        with pytest.raises(_Sentinel):
            mod.lambda_handler(dict(self.EVENT, force_send=True), None)

    @pytest.mark.parametrize("spec", SPECS, ids=IDS)
    def test_a_ledger_read_failure_fails_OPEN(self, spec, monkeypatch):
        mod, name, key, first_call = spec
        mod = mod()
        t = _seed(_FleetTable(), name, key())
        t.query_error = RuntimeError("throttled")
        monkeypatch.setattr(mod, "table", t)
        monkeypatch.setattr(mod, first_call, _sentinel)
        with pytest.raises(_Sentinel):
            mod.lambda_handler(dict(self.EVENT), None)

    def test_the_compass_keys_on_the_week_AHEAD_not_the_one_behind(self):
        """Pinned on its own because it is the one sender whose key differs, and
        a copy-paste of the look-back rule would be invisible for six days of
        every seven (they only disagree on a Monday)."""
        assert compass._period_key() == f"week:{send_ledger.iso_week_key(_utc_today())}"
        assert weekly is not compass


# ── 7d. the senders whose period is NOT a week ────────────────────────────────


@fleet
class TestEveningNudgeReplay:
    """Daily, and the one sender whose key is a PACIFIC date. It runs at 03:00
    UTC (8 PM PT), where a UTC-dated key names *tomorrow* — the same trap
    AUDIT BUG-02 already fixed for the rest of this handler's reads."""

    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    def test_replay_is_refused(self, monkeypatch):
        from common.pacific_time import pacific_today

        t = _seed(_FleetTable(), "evening_nudge", f"date:{pacific_today()}")
        monkeypatch.setattr(nudge, "table", t)
        # Sentinel on the ritual check rather than on one of the three source
        # checks: those are individually wrapped in try/except (a broken check
        # degrades to "missing"), so an exception there proves nothing.
        monkeypatch.setattr(nudge, "_check_evening_ritual", _explode)
        monkeypatch.setattr(nudge.ses, "send_email", _explode)
        out = nudge.lambda_handler(dict(self.EVENT), None)
        assert "already sent" in out["body"]

    def test_without_the_row_the_same_event_proceeds(self, monkeypatch):
        monkeypatch.setattr(nudge, "table", _FleetTable())
        monkeypatch.setattr(nudge, "_check_evening_ritual", _sentinel)
        with pytest.raises(_Sentinel):
            nudge.lambda_handler(dict(self.EVENT), None)

    def test_the_key_is_the_pacific_day_not_the_utc_one(self):
        """A UTC-dated key at 03:00 UTC names tomorrow in Pacific terms, and the
        6-hourly redrive at 09:00 UTC would agree with it only by luck."""
        src = (REPO_ROOT / "lambdas" / "emails" / "evening_nudge_lambda.py").read_text(encoding="utf-8")
        guard_at = src.index('period_key = f"date:{today}"')
        today_at = src.index("today = pacific_today()")
        assert today_at < guard_at, "the guard must key on pacific_today(), not a UTC date"


@fleet
class TestWeeklySignalReplay:
    """Mails the whole confirmed-subscriber list, so a duplicate is the loudest
    one in the fleet. Its #2820 heartbeat is a CloudWatch METRIC and cannot
    answer the replay question — this is the durable half."""

    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    def test_replay_is_refused_before_the_s3_reads(self, monkeypatch):
        t = _seed(_FleetTable(), "weekly_signal", _this_iso_week(0))
        monkeypatch.setattr(weekly_signal, "table", t)
        monkeypatch.setattr(weekly_signal, "_s3_json", _explode)
        monkeypatch.setattr(weekly_signal.ses, "send_email", _explode)
        out = weekly_signal.lambda_handler(dict(self.EVENT), None)
        assert out["sent"] == 0 and "already sent" in out["body"]

    def test_without_the_row_the_same_event_proceeds(self, monkeypatch):
        monkeypatch.setattr(weekly_signal, "table", _FleetTable())
        monkeypatch.setattr(weekly_signal, "_s3_json", _sentinel)
        with pytest.raises(_Sentinel):
            weekly_signal.lambda_handler(dict(self.EVENT), None)

    def test_the_row_lands_after_the_FIRST_subscriber_not_the_last(self, monkeypatch):
        """A 300-name fan-out is the widest 'sent then crashed' window in the
        fleet; the record must exist before the second letter goes out."""
        t = _FleetTable()
        monkeypatch.setattr(weekly_signal, "table", t)
        monkeypatch.setattr(weekly_signal, "_s3_json", lambda *a, **kw: {})
        monkeypatch.setattr(weekly_signal, "_get_weekly_insight", lambda *a, **kw: "")
        monkeypatch.setattr(
            weekly_signal,
            "_get_confirmed_subscribers",
            lambda *a, **kw: [{"email": f"s{i}@example.invalid"} for i in range(3)],
        )
        monkeypatch.setattr(weekly_signal, "_emit_sent_metric", lambda *a, **kw: None)
        monkeypatch.setattr(weekly_signal.time, "sleep", lambda *a, **kw: None)
        rows_seen = []
        monkeypatch.setattr(weekly_signal.ses, "send_email", lambda **kw: rows_seen.append(len(t.rows)))
        weekly_signal.lambda_handler(dict(self.EVENT), None)
        assert rows_seen == [0, 1, 1], f"expected the ledger row after the first send, saw {rows_seen}"


@fleet
class TestAnomalyDetectorReplay:
    """The one sender that must NOT short-circuit. It can mail two different
    letters about the same analysed date, and it also writes a durable anomaly
    record the site reads — so a replay re-runs the analysis and suppresses only
    the mail."""

    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    @pytest.fixture
    def wired(self, monkeypatch):
        t = _FleetTable()
        monkeypatch.setattr(anomaly, "table", t)
        monkeypatch.setattr(anomaly, "_check_travel", lambda *a, **kw: None)
        monkeypatch.setattr(
            anomaly,
            "check_anomalies",
            lambda *a, **kw: [
                {"source": "whoop", "label": "HRV", "yesterday_val": 30, "z_score": -3.1, "direction": "down"},
                {"source": "withings", "label": "Weight", "yesterday_val": 220, "z_score": 3.0, "direction": "up"},
            ],
        )
        monkeypatch.setattr(anomaly, "_check_sustained_streaks", lambda *a, **kw: [])
        monkeypatch.setattr(anomaly, "build_context", lambda *a, **kw: {})
        monkeypatch.setattr(anomaly, "call_haiku_hypothesis", lambda *a, **kw: "h")
        written = {}
        monkeypatch.setattr(anomaly, "write_anomaly_record", lambda *a, **kw: written.update({"called": True, "alert_sent": a[2]}))
        return t, written

    def _yesterday(self):
        return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    def test_replay_suppresses_the_mail_but_still_writes_the_record(self, wired, monkeypatch):
        t, written = wired
        _seed(t, "anomaly_detector", f"date:{self._yesterday()}")
        monkeypatch.setattr(anomaly, "send_alert_email", _explode)
        anomaly.lambda_handler(dict(self.EVENT), None)
        assert written["called"] is True, "a replay must still rewrite the anomaly record"
        assert written["alert_sent"] is True, "the alert DID go out — on the run this replays"

    def test_without_the_row_the_alert_is_sent(self, wired, monkeypatch):
        t, written = wired
        sends = []
        monkeypatch.setattr(anomaly, "send_alert_email", lambda *a, **kw: sends.append(1))
        anomaly.lambda_handler(dict(self.EVENT), None)
        assert sends == [1]

    def test_a_quiet_run_writes_a_key_that_can_never_suppress_a_later_alert(self, wired, monkeypatch):
        """A run that mails nothing still writes the status row. If that row
        carried the guard's key, an operator re-invoking after fixing an ingest
        gap would be refused the alert they just made possible."""
        t, _ = wired
        monkeypatch.setattr(anomaly, "check_anomalies", lambda *a, **kw: [])
        anomaly.lambda_handler(dict(self.EVENT), None)
        assert t.rows[-1][send_ledger.PERIOD_KEY_ATTR] == f"run:{self._yesterday()}"
        assert send_ledger.already_sent(t, "anomaly_detector", f"date:{self._yesterday()}") is False


@fleet
class TestInsightEmailParserReplay:
    """Event-driven, so there is no calendar period at all: the letter's identity
    is the INBOUND MESSAGE it answers, and the S3 object key is that id."""

    def _event(self, key="raw/inbound_email/msg-42"):
        return {"Records": [{"s3": {"bucket": {"name": "matthew-life-platform"}, "object": {"key": key}}}]}

    def test_replay_is_refused_before_the_email_is_even_read(self, monkeypatch):
        """Asserted as "the read never happened", NOT as "an exception escaped":
        every per-record failure in this handler is caught and `continue`d, so a
        raising stub would be swallowed and the test would pass with the guard
        deleted. (It did, until this was rewritten.)"""
        t = _seed(_FleetTable(), "insight_email_parser", "msg:raw/inbound_email/msg-42")
        monkeypatch.setattr(parser, "table", t)
        reads, sends = [], []
        monkeypatch.setattr(parser.s3, "get_object", lambda **kw: reads.append(kw.get("Key")) or _explode())
        monkeypatch.setattr(parser.ses, "send_email", lambda **kw: sends.append(1))
        out = parser.lambda_handler(self._event(), None)
        assert out["statusCode"] == 200
        assert reads == [], "the guard must short-circuit before the inbound email is even read"
        assert sends == [], "no confirmation reply may go out on a replay"

    def test_a_different_inbound_message_is_not_blocked(self, monkeypatch):
        """Non-vacuity. The handler catches an S3 read failure per record and
        continues, so this asserts the READ WAS ATTEMPTED rather than expecting
        an exception to escape — an exception-shaped probe here would pass just
        as well against a handler that skipped the record entirely."""
        t = _seed(_FleetTable(), "insight_email_parser", "msg:raw/inbound_email/SOME-OTHER")
        monkeypatch.setattr(parser, "table", t)
        reads = []
        monkeypatch.setattr(parser.s3, "get_object", lambda **kw: reads.append(kw["Key"]) or _sentinel())
        monkeypatch.setattr(parser, "_persist_failure_envelope", lambda *a, **kw: "")
        parser.lambda_handler(self._event(), None)
        assert reads == ["raw/inbound_email/msg-42"]


@fleet
class TestAiReviewPackReplay:
    """Guarded like the weekly letters, but pinned separately for one reason:
    its `email_log#` partition keeps the historical HYPHEN (`ai-review-pack`).
    A tidier spelling would make the guard read a partition nobody writes —
    silent, and passing every test that only checks one side."""

    EVENT = {"detail-type": "Scheduled Event", "source": "aws.events", "detail": {}}

    def test_the_ledger_name_still_matches_the_status_pages_partition(self):
        assert review_pack.LEDGER_NAME == "ai-review-pack"
        src = (REPO_ROOT / "lambdas" / "emails" / "ai_review_pack_lambda.py").read_text(encoding="utf-8")
        assert "record_email_send(table, LEDGER_NAME, period_key)" in src

    def _wire(self, monkeypatch, table):
        class _Res:
            def Table(self, _name):
                return table

        class _Boto:
            def resource(self, *a, **kw):
                return _Res()

            def client(self, *a, **kw):
                class _C:
                    def send_email(self, **kw):
                        raise AssertionError("reached past the #3113 replay guard")

                return _C()

        monkeypatch.setattr(review_pack, "boto3", _Boto())

    def test_replay_is_refused(self, monkeypatch):
        t = _seed(_FleetTable(), "ai-review-pack", _this_iso_week(0))
        self._wire(monkeypatch, t)
        monkeypatch.setattr(review_pack, "gather_week", _explode)
        out = review_pack.lambda_handler(dict(self.EVENT), None)
        assert out["statusCode"] == 200 and "already sent" in out["body"]

    def test_without_the_row_the_same_event_proceeds(self, monkeypatch):
        self._wire(monkeypatch, _FleetTable())
        monkeypatch.setattr(review_pack, "gather_week", _sentinel)
        with pytest.raises(_Sentinel):
            review_pack.lambda_handler(dict(self.EVENT), None)
