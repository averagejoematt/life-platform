"""tests/test_evening_intake_idempotency_1484.py — #1484 evening-flow hardening
of the one-tap intake write (`log_evening_intake`).

Two contracts, both load-bearing for the unified evening ritual:

1. **Pacific date keying.** The evening flow runs 6pm-midnight PT — already
   tomorrow in UTC. The tool's default date must be the PACIFIC calendar day
   (`pacific_time.pacific_today`), matching the nudge email's signed-link write
   path (`site_api_social._handle_ritual_log`, which keys by PT). A UTC default
   split one evening across two DATE# rows — double-counting evenings in the
   dose-response arming ledger. Red on the pre-#1484 tree.

2. **Observable idempotency.** Re-logging the same evening must UPDATE the one
   row (SET overwrite — structurally never an ADD) and report it: `updated` +
   `previous_count` from ReturnValues=UPDATED_OLD, so the flow can say
   "updated tonight's count 2 -> 1" instead of silently re-writing.

Hermetic: the DDB table and pacific_time are monkeypatched; no AWS calls.
"""

import os
import sys
from datetime import datetime
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pacific_time  # noqa: E402
from intake_response import PRIVATE_INTAKE_PK  # noqa: E402

import mcp.tools_lifestyle as tl  # noqa: E402


class _FakeTable:
    """Captures update_item kwargs and simulates the UPDATED_OLD contract of a
    real single-row overwrite: the first write returns no Attributes, later
    writes return the previously-stored intake_count."""

    def __init__(self):
        self.calls = []
        self.rows = {}  # (pk, sk) -> intake_count

    def update_item(self, **kw):
        self.calls.append(kw)
        key = (kw["Key"]["pk"], kw["Key"]["sk"])
        old = self.rows.get(key)
        self.rows[key] = kw["ExpressionAttributeValues"][":v"]
        if kw.get("ReturnValues") == "UPDATED_OLD" and old is not None:
            return {"Attributes": {"intake_count": old}}
        return {}


@pytest.fixture()
def ft(monkeypatch):
    fake = _FakeTable()
    monkeypatch.setattr(tl, "table", fake)
    return fake


def test_default_date_is_the_pacific_evening_not_utc(ft, monkeypatch):
    # 2026-07-17 21:00 PT == 2026-07-18 04:00 UTC — the two dates diverge on purpose.
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: datetime(2026, 7, 17, 21, 0, tzinfo=pacific_time.PACIFIC))
    out = tl.tool_log_evening_intake({"count": 2})
    assert out["date"] == "2026-07-17"  # the PT evening — a UTC default would say 2026-07-18
    assert ft.calls[0]["Key"] == {"pk": PRIVATE_INTAKE_PK, "sk": "DATE#2026-07-17"}


def test_relog_same_evening_updates_in_place_and_reports_it(ft):
    first = tl.tool_log_evening_intake({"count": 2, "date": "2026-07-16"})
    assert first["logged"] is True
    assert first["updated"] is False
    assert first["previous_count"] is None

    second = tl.tool_log_evening_intake({"count": 1, "date": "2026-07-16"})
    assert second["updated"] is True
    assert second["previous_count"] == 2
    assert second["count"] == 1

    # One row, not two: both writes hit the identical Key, and the stored value
    # is the latest count — never a sum.
    keys = {(c["Key"]["pk"], c["Key"]["sk"]) for c in ft.calls}
    assert keys == {(PRIVATE_INTAKE_PK, "DATE#2026-07-16")}
    assert ft.rows[(PRIVATE_INTAKE_PK, "DATE#2026-07-16")] == Decimal(1)


def test_write_is_a_set_overwrite_never_an_add(ft):
    """The structural no-double-count guarantee: the UpdateExpression assigns
    intake_count (SET), it never accumulates (ADD / SET x = x + :v)."""
    tl.tool_log_evening_intake({"count": 3, "date": "2026-07-15"})
    expr = ft.calls[0]["UpdateExpression"]
    assert expr.startswith("SET ")
    assert "ADD" not in expr
    assert "intake_count = :v" in expr
    assert "intake_count +" not in expr
    assert ft.calls[0]["ReturnValues"] == "UPDATED_OLD"


def test_count_validation_unchanged(ft):
    with pytest.raises(ValueError):
        tl.tool_log_evening_intake({})
    with pytest.raises(ValueError):
        tl.tool_log_evening_intake({"count": 5})
    with pytest.raises(ValueError):
        tl.tool_log_evening_intake({"count": -1})
    with pytest.raises(ValueError):
        tl.tool_log_evening_intake({"count": 2, "date": "not-a-date"})
    assert ft.calls == []  # nothing reached the table


def test_explicit_backdate_still_wins_over_the_default(ft, monkeypatch):
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: datetime(2026, 7, 17, 21, 0, tzinfo=pacific_time.PACIFIC))
    out = tl.tool_log_evening_intake({"count": 0, "date": "2026-07-14"})
    assert out["date"] == "2026-07-14"
    assert ft.calls[0]["Key"]["sk"] == "DATE#2026-07-14"
