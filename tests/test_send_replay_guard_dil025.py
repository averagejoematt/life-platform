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
  6. structural pins on the two orderings the fix depends on.

Safety: no real AWS anywhere. No Lambda is invoked, no mail is sent, no Bedrock
call is made. `daily-brief` is never invoked live by this suite — per the repo's
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
