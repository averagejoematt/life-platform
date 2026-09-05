"""tests/test_nudge_decimal_and_ledger_3569.py — #3569.

coach-nudge (#1382) delivered nudges and persisted NOTHING. `_finalize`'s
`put_item` had no Decimal coercion, `trigger_payload` is the trigger's payload
verbatim, and both firing triggers put a real Python float in it
(`_acwr_readings` -> `float(it["acwr"])`, `_verdicts_resolving_tomorrow` ->
`float(pred["confidence"])`). Live at filing time: 3 identical
`TypeError: Float types are not supported` crashes (2026-08-06/08-07/08-30),
4 `COACH#nudge_ledger` rows ALL at `status=attempting`, and ZERO `NUDGE#` rows
across all nine coach partitions.

The fixture here is the WIRE, not a mock of the coercer: `_WireTable.put_item`
runs boto3's own `TypeSerializer` over the item, which is the exact call that
raised in production. A test whose fake accepts floats proves nothing about a
float bug.

Four things are pinned:
  1. the killing float round-trips through the real handler path and lands as a
     Decimal in a real NUDGE# record;
  2. NEGATIVE CONTROL — with the coercion removed, the same run reds (no record,
     ledger `failed`) and, crucially, sends NO email;
  3. the durable write precedes the irreversible send (the record already exists
     when SES is called), and a send failure corrects the record it wrote;
  4. the dead-man reds on a stuck `attempting` row and on zero-NUDGE#-behind-a-
     send, and is green on a healthy pair.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import emails.coach_nudge_lambda as shell  # noqa: E402
from boto3.dynamodb.types import TypeSerializer  # noqa: E402
from coach import coach_nudge_engine as eng  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from operational import nudge_ledger_qa as dead_man  # noqa: E402

# The #1382 suite already owns the shell's stand-up rig (fixed clock, fake SES,
# fake Bedrock, pk-dispatching query hook). Reused rather than re-forked so this
# file exercises the SAME wiring the feature's own acceptance tests do.
from test_coach_nudge_1382 import ConditionalCheckFailedException, _pk_dispatch_query_hook, _wire  # noqa: E402

# 18:30 PT 2026-07-24 == 01:30Z 2026-07-25 (PDT) — inside the send window.
NOW_UTC = datetime(2026, 7, 25, 1, 30, 0, tzinfo=timezone.utc)
DATE_PT = "2026-07-24"

# The float that killed it, arriving the way production produces it: DDB serves
# `acwr` as a Decimal, `_acwr_readings` casts it to float, and the cast value is
# copied verbatim into `payload` -> `trigger_payload`.
ACWR_ROWS = [
    {
        "pk": "USER#matthew#SOURCE#computed_metrics",
        "sk": "DATE#2026-07-24",
        "acwr": Decimal("1.42"),
        "acwr_zone": "danger",
    },
    {
        "pk": "USER#matthew#SOURCE#computed_metrics",
        "sk": "DATE#2026-07-23",
        "acwr": Decimal("1.05"),
        "acwr_zone": "safe",
    },
]

# No digits anywhere: the grounding gate only permits numbers/dates present in
# the payload, and this test is about the write path, not about phrasing.
CLEAN_COPY = (
    "Your acute load crossed into the danger band today, which makes this a decision point about "
    "tonight's session rather than a verdict. Doing nothing with it is a completely fine call."
)


class _WireTable(FakeDdbTable):
    """FakeDdbTable whose `put_item` is the REAL boto3 serializer.

    `TypeSerializer().serialize(...)` is the exact code that raised
    `TypeError: Float types are not supported` in production, so a float that
    reaches this fake fails here for the same reason it failed on the wire. A
    fake that quietly accepts floats cannot witness this bug at all.
    """

    def __init__(self, rows=None):
        super().__init__(rows=rows or [], query_hook=_pk_dispatch_query_hook)
        self.serializer = TypeSerializer()

    def put_item(self, Item, **kwargs):  # noqa: N803 — boto3's own kwarg name
        self.puts.append(Item)
        self.serializer.serialize(Item)  # the wire: raises TypeError on any float
        if kwargs.get("ConditionExpression") and self._key_of(Item) in self.store:
            raise ConditionalCheckFailedException("The conditional request failed")
        self.store[self._key_of(Item)] = Item


def _nudges(table):
    return [it for it in table.store.values() if str(it.get("sk", "")).startswith("NUDGE#")]


def _ledger(table):
    return table.store.get((eng.LEDGER_PK, eng.ledger_sk(DATE_PT)))


# ══════════════════════════════════════════════════════════════════════════════
# 1. The killing float round-trips through the real write path
# ══════════════════════════════════════════════════════════════════════════════


def test_the_float_that_killed_it_now_lands_as_a_decimal(monkeypatch):
    table = _WireTable(rows=ACWR_ROWS)
    ses, _ = _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)

    out = shell.lambda_handler({}, None)

    assert out["nudge"] == "sent", out
    assert out["trigger"] == eng.TRIGGER_ACWR_BAND_CROSS
    assert len(ses.sends) == 1

    records = _nudges(table)
    assert len(records) == 1, "the whole point of #3569: a sent nudge has a record"
    record = records[0]
    assert record["pk"] == "COACH#training_coach"
    assert record["status"] == "sent"
    # The float is preserved in value, converted in TYPE — this is the fix.
    assert record["trigger_payload"]["acwr"] == Decimal("1.42")
    assert isinstance(record["trigger_payload"]["acwr"], Decimal)
    assert not isinstance(record["trigger_payload"]["acwr"], float)

    ledger = _ledger(table)
    assert ledger["status"] == "sent" and ledger["graded"] is False
    assert (ledger["nudge_pk"], ledger["nudge_sk"]) == (record["pk"], record["sk"])


def test_the_verdict_triggers_confidence_float_also_round_trips(monkeypatch):
    """The other float source: `float(pred["confidence"])` in the verdict trigger."""
    prediction = {
        "pk": "COACH#explorer_coach",
        "sk": "PREDICTION#p-001",
        "prediction_id": "p-001",
        "status": "pending",
        "created_date": "2026-07-04",  # +21d (the evaluator's effective window) == tomorrow_pt
        "claim_natural": "a claim with no numbers in it",
        "confidence": Decimal("0.72"),
        "evaluation": {"evaluation_window_days": 14},
    }
    table = _WireTable(rows=[prediction])
    _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)

    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "sent", out
    assert out["trigger"] == eng.TRIGGER_VERDICT_TOMORROW
    record = _nudges(table)[0]
    assert record["trigger_payload"]["stated_confidence"] == Decimal("0.72")
    assert isinstance(record["trigger_payload"]["stated_confidence"], Decimal)


# ══════════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE CONTROL — remove the coercion and the same run must red
# ══════════════════════════════════════════════════════════════════════════════


def test_negative_control_without_the_coercion_the_write_dies_exactly_as_it_did(monkeypatch):
    """Mutate the fix away: `floats_to_decimal` becomes the identity.

    This reproduces the production failure end-to-end — and asserts the second
    half of #3569 at the same time: because the durable write now runs FIRST,
    the crash costs a record that was never written instead of an email that was
    already sent.
    """
    table = _WireTable(rows=ACWR_ROWS)
    ses, _ = _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    monkeypatch.setattr(shell, "floats_to_decimal", lambda obj, precision=None: obj)

    with pytest.raises(shell.NudgeWriteError) as caught:
        shell.lambda_handler({}, None)
    assert "Float types are not supported" in str(caught.value)

    assert _nudges(table) == [], "no record — this is the bug being reproduced"
    assert ses.sends == [], "and with the write first, NO email went out either"
    # The failure is loud in the ledger: never left at `attempting`.
    ledger = _ledger(table)
    assert ledger["status"] == eng.STATUS_FAILED
    assert "Float types are not supported" in ledger["error"]
    assert ledger["attempted_at"]


def test_negative_control_is_not_vacuous_the_unmutated_run_passes(monkeypatch):
    """Positive control for the mutation above: same table, same firing, coercion
    left in place -> the record lands. Without this, a mutation test that reds
    for any reason at all would look like a proof."""
    table = _WireTable(rows=ACWR_ROWS)
    _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    assert shell.lambda_handler({}, None)["nudge"] == "sent"
    assert len(_nudges(table)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. Ordering: the durable write precedes the irreversible side effect
# ══════════════════════════════════════════════════════════════════════════════


def test_the_record_already_exists_when_ses_is_called(monkeypatch):
    """The ordering assertion, stated where it can fail: at SES-call time the
    NUDGE# record must already be in the store. On the pre-#3569 order this is
    empty, so this test is the regression guard for the reorder itself."""
    table = _WireTable(rows=ACWR_ROWS)
    _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    seen = {}
    original = shell._send_email

    def _observing_send(coach_name, copy_text, dry_run=False):
        seen["records_at_send_time"] = len(_nudges(table))
        seen["ledger_at_send_time"] = dict(_ledger(table) or {})
        return original(coach_name, copy_text, dry_run=dry_run)

    monkeypatch.setattr(shell, "_send_email", _observing_send)
    shell.lambda_handler({}, None)

    assert seen["records_at_send_time"] == 1
    assert seen["ledger_at_send_time"]["status"] == "sent"


def test_an_unwritable_record_is_never_delivered(monkeypatch):
    """Generalised past the float: ANY put failure must stop the send."""
    table = _WireTable(rows=ACWR_ROWS)
    ses, _ = _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    real_put = table.put_item

    def _explode(Item, **kwargs):  # noqa: N803
        if str(Item.get("sk", "")).startswith("NUDGE#"):
            raise RuntimeError("ProvisionedThroughputExceededException")
        return real_put(Item, **kwargs)

    monkeypatch.setattr(table, "put_item", _explode)

    with pytest.raises(shell.NudgeWriteError):
        shell.lambda_handler({}, None)
    assert ses.sends == []
    assert _ledger(table)["status"] == eng.STATUS_FAILED
    assert "ProvisionedThroughputExceeded" in _ledger(table)["error"]


def test_a_failed_send_corrects_the_record_it_already_wrote(monkeypatch):
    """The write-first order's one new obligation: a record saying `sent` must be
    downgraded when SES then fails — same pk/sk, so it is corrected in place and
    never orphaned as a phantom delivery."""
    table = _WireTable(rows=ACWR_ROWS)
    _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)

    def _boom(coach_name, copy_text, dry_run=False):
        raise RuntimeError("MessageRejected")

    monkeypatch.setattr(shell, "_send_email", _boom)

    out = shell.lambda_handler({}, None)
    assert out["reason"] == "ses_error" and out["statusCode"] == 500
    records = _nudges(table)
    assert len(records) == 1, "corrected in place — not a second, orphaned record"
    assert records[0]["status"] == eng.STATUS_BLOCKED
    assert "outcome" not in records[0]  # nothing was delivered, so nothing is pending
    assert records[0]["gate_findings"] == ["ses_error:MessageRejected"]
    assert _ledger(table)["status"] == eng.STATUS_BLOCKED


def test_the_reservation_now_carries_a_timestamp(monkeypatch):
    """Without `attempted_at` a stuck row cannot be aged — the dead-man's first
    leg would have had nothing to measure."""
    table = _WireTable(rows=ACWR_ROWS)
    _wire(monkeypatch, table, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    monkeypatch.setattr(shell, "_finalize", lambda *a, **k: (_ for _ in ()).throw(shell.NudgeWriteError("stop here")))
    with pytest.raises(shell.NudgeWriteError):
        shell.lambda_handler({}, None)
    assert _ledger(table)["status"] == eng.STATUS_ATTEMPTING
    assert _ledger(table)["attempted_at"] == "2026-07-25T01:30:00Z"


# ══════════════════════════════════════════════════════════════════════════════
# 4. The dead-man
# ══════════════════════════════════════════════════════════════════════════════

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class _Check:
    def __init__(self, name, category, partition):
        self.name, self.category, self.partition = name, category, partition
        self.passed, self.message, self.details = None, "", []

    def ok(self, msg=""):
        self.passed, self.message = True, msg
        return self

    def fail(self, msg=""):
        self.passed, self.message = False, msg
        return self

    def warn(self, msg="", chronic=False):
        self.passed, self.message = None, msg
        return self

    def with_details(self, lines):
        self.details = list(lines)
        return self


class _LedgerTable:
    """Query answers the ledger partition; get_item answers the NUDGE# store."""

    def __init__(self, ledger_rows, records=None):
        self.ledger_rows = list(ledger_rows)
        self.records = {(r["pk"], r["sk"]): r for r in (records or [])}

    def query(self, **kwargs):
        return {"Items": list(self.ledger_rows)}

    def get_item(self, Key):  # noqa: N803
        item = self.records.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}


def _day(offset_days):
    return (NOW.date() - timedelta(days=offset_days)).isoformat()


def _row(offset_days, status, **over):
    row = {
        "pk": eng.LEDGER_PK,
        "sk": f"{eng.LEDGER_SK_PREFIX}{_day(offset_days)}",
        "record_type": "coach_nudge_ledger",
        "status": status,
        "coach_id": "training_coach",
        "trigger_type": eng.TRIGGER_ACWR_BAND_CROSS,
    }
    row.update(over)
    return row


def _run(table):
    (check,) = dead_man.check_nudge_ledger_liveness(table, _Check, "content_truth", now_utc=NOW)
    return check


def test_dead_man_reds_on_a_row_stuck_at_attempting(monkeypatch):
    stuck = _row(2, eng.STATUS_ATTEMPTING, attempted_at=f"{_day(2)}T15:10:29Z", graded=True)
    check = _run(_LedgerTable([stuck]))
    assert check.passed is False
    assert "stuck at 'attempting'" in check.message
    assert _day(2) in check.message


def test_dead_man_reds_on_the_four_live_undateable_pre_fix_rows():
    """The exact live shape at filing time: reservations with NO timestamp at
    all. The sk-date fallback still ages them, so the check is not blind to the
    very rows that motivated it."""
    rows = [_row(n, eng.STATUS_ATTEMPTING, graded=True) for n in (2, 3, 4)]
    check = _run(_LedgerTable(rows))
    assert check.passed is False
    assert "3 reservation(s) stuck" in check.message


def test_dead_man_reds_when_a_send_produced_no_nudge_record():
    """The #3569 signature by name: terminal ledger rows, zero NUDGE# records."""
    sent = _row(
        1,
        eng.STATUS_SENT,
        nudge_pk="COACH#training_coach",
        nudge_sk=f"NUDGE#{_day(1)}#deadbeef",
        sent_at=f"{_day(1)}T15:10:29Z",
        graded=False,
    )
    check = _run(_LedgerTable([sent], records=[]))
    assert check.passed is False
    assert "ZERO NUDGE# records" in check.message


def test_dead_man_reds_on_a_recorded_write_failure():
    failed = _row(1, eng.STATUS_FAILED, error="Float types are not supported. Use Decimal types instead.", graded=True)
    check = _run(_LedgerTable([failed]))
    assert check.passed is False
    assert "record write(s) failed" in check.message
    assert "Float types are not supported" in check.message


def test_dead_man_is_green_on_a_healthy_pair():
    record = {
        "pk": "COACH#training_coach",
        "sk": f"NUDGE#{_day(1)}#deadbeef",
        "status": eng.STATUS_SENT,
        "trigger_payload": {"acwr": Decimal("1.42")},
    }
    sent = _row(
        1,
        eng.STATUS_SENT,
        nudge_pk=record["pk"],
        nudge_sk=record["sk"],
        sent_at=f"{_day(1)}T15:10:29Z",
        graded=False,
    )
    check = _run(_LedgerTable([sent], records=[record]))
    assert check.passed is True, check.message
    assert "every one terminal with its NUDGE# record present" in check.message


def test_dead_man_does_not_red_a_reservation_that_is_still_young():
    """A run in flight is not a fault: `attempting` inside the stuck window is
    the normal state for the seconds a nudge takes."""
    fresh = _row(0, eng.STATUS_ATTEMPTING, attempted_at="2026-09-04T11:59:00Z", graded=True)
    check = _run(_LedgerTable([fresh]))
    assert check.passed is True, check.message


def test_dead_man_is_honest_about_an_empty_window():
    check = _run(_LedgerTable([]))
    assert check.passed is True
    assert "no nudge attempted" in check.message


def test_dead_man_reds_on_a_ddb_error_rather_than_passing_quietly():
    class _Broken:
        def query(self, **kwargs):
            raise RuntimeError("AccessDeniedException")

    check = _run(_Broken())
    assert check.passed is False
    assert "AccessDeniedException" in check.message


def test_dead_man_is_wired_into_the_nightly_sweep():
    """A dead-man nobody runs is the class it exists to prevent. Derived from
    the live registry, never from a remembered line number."""
    sys.modules.pop("operational.qa_smoke_lambda", None)
    pytest.importorskip("operational.qa_smoke_lambda")
    from operational import qa_smoke_lambda as qa

    labels = [label for label, _fn in qa.check_steps()]
    assert "nudge_ledger_liveness" in labels
