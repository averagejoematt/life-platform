"""tests/test_evening_checkin_mood_5123.py — the evening check-in's 0-4 mood rating (#5123, owner ruling 2026-10-25
"(a) Add one 0-4 mood question") and the mood read that now uses it.

Held here:
  * a three-number reply (``2 3 1 tired``) still parses with mood absent, and a four-number reply (``2 3 1 3 tired``)
    sets it — the Telegram door and the MCP door write the same row;
  * an out-of-range mood is refused on every door, and nothing is written;
  * a row without mood is still a complete check-in (``decide`` says already_logged; the core habit reads True);
  * the mood read uses the check-in's own rating when an evening carries one, and keeps "not measured" — never an
    inference from stress or cravings — when none does;
  * the partner view (#5125 R5) is unchanged: it never projects, bands or names the mood rating.

Every clock is passed in (no asserted value reaches ``datetime.now``, #4848). Values here are the 0-4 scale only.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from coach import evening_checkin as ec  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from health import (
    checkin_partner_view as pv,  # noqa: E402
    mood_read as mr,  # noqa: E402
)

EVENING = datetime(2026, 10, 28, 20, 5, tzinfo=PACIFIC)
EVENING_UTC = EVENING.astimezone(timezone.utc)
DAY = "2026-10-28"
TODAY = "2026-10-24"


class Table:
    """A small DynamoDB double that applies SET updates (names/values, UPDATED_OLD), gets, puts and pk-range queries."""

    def __init__(self):
        self.store: dict = {}

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, ReturnValues=None):
        names = ExpressionAttributeNames or {}
        row = self.store.setdefault((Key["pk"], Key["sk"]), dict(Key))
        old = {}
        for part in UpdateExpression[len("SET ") :].split(","):
            lhs, rhs = (x.strip() for x in part.split("="))
            attr = names.get(lhs, lhs)
            if attr in row:
                old[attr] = row[attr]
            row[attr] = ExpressionAttributeValues[rhs]
        return {"Attributes": old} if ReturnValues == "UPDATED_OLD" and old else {}

    def query(self, **kw):
        pk, lo, hi = (kw["ExpressionAttributeValues"][k] for k in (":pk", ":lo", ":hi"))
        return {"Items": [dict(v) for (p, s), v in sorted(self.store.items()) if p == pk and lo <= s <= hi]}


def _prompted(table, day=DAY):
    table.store[(ec.LEDGER_PK, f"PROMPT#{day}")] = {"pk": ec.LEDGER_PK, "sk": f"PROMPT#{day}", "status": "sent"}


# ── the two reply shapes ────────────────────────────────────────────────────────────────────────


def test_version_prompt_and_field_set_carry_the_mood_question():
    assert ec.VERSION == "evening-checkin@1.1.0"
    assert ec.FIELDS == ("hunger", "stress", "cravings", "mood") and ec.COMPLETE_FIELDS == ("hunger", "stress", "cravings")
    assert "mood" in ec.PROMPT_TEXT and "2 3 1 3 tired" in ec.PROMPT_TEXT and len(ec.PROMPT_TEXT) <= 150
    assert "mood" in ec.USAGE_TEXT


def test_a_three_number_reply_still_parses_with_mood_absent():
    values, explicit = ec.parse_reply("2 3 1 tired")
    assert values == {"hunger": 2, "stress": 3, "cravings": 1, "word": "tired"} and explicit is False
    assert ec.parse_reply("231") == ({"hunger": 2, "stress": 3, "cravings": 1}, False)
    table = Table()
    _prompted(table)
    reply = ec.capture_reply(table, "2 3 1 tired", EVENING)
    row = table.store[(ec.PK, f"DATE#{DAY}")]
    assert "mood" not in row and (row["hunger"], row["stress"], row["cravings"], row["word"]) == (2, 3, 1, "tired")
    assert reply == f"Logged the check-in for {DAY}: hunger 2, stress 3, cravings 1, 'tired'."
    assert row["version"] == "evening-checkin@1.1.0"


def test_a_four_number_reply_sets_mood_on_both_doors():
    values, explicit = ec.parse_reply("/checkin 2,3,1,4 wired")
    assert values == {"hunger": 2, "stress": 3, "cravings": 1, "mood": 4, "word": "wired"} and explicit is True
    assert ec.parse_reply("2 3 1 3") == ({"hunger": 2, "stress": 3, "cravings": 1, "mood": 3}, False)
    table = Table()
    _prompted(table)
    reply = ec.capture_reply(table, "2 3 1 3 tired", EVENING)
    row = table.store[(ec.PK, f"DATE#{DAY}")]
    assert row["mood"] == 3 and row["source"] == "telegram"
    assert reply == f"Logged the check-in for {DAY}: hunger 2, stress 3, cravings 1, mood 3, 'tired'."
    again = ec.capture_reply(table, "/checkin 2 3 1 0 flat", EVENING)  # the same evening, overwritten in place
    assert again.startswith("Updated the check-in") and table.store[(ec.PK, f"DATE#{DAY}")]["mood"] == 0
    assert len([k for k in table.store if k[0] == ec.PK]) == 1


def test_mcp_door_takes_mood_and_its_input_table_names_it(monkeypatch):
    from mcp import tools_lifestyle as tl
    from mcp.registry import TOOLS

    schema = TOOLS["log_evening_intake"]["schema"]["inputSchema"]
    assert schema["properties"]["mood"]["type"] == "integer" and "0-4" in schema["properties"]["mood"]["description"]
    assert "mood" in TOOLS["log_evening_intake"]["schema"]["description"]
    table = Table()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: DAY)
    monkeypatch.setattr(tl, "pacific_now", lambda: EVENING)
    out = TOOLS["log_evening_intake"]["fn"]({"mood": 3})
    assert out["logged"] and out["date"] == DAY and out["mood"] == 3 and out["private"] is True
    row = table.store[(ec.PK, f"DATE#{DAY}")]
    assert (row["mood"], row["source"]) == (3, "mcp") and "stress" not in row  # partial, as the other fields allow
    assert table.store.get(("USER#matthew#SOURCE#private_intake", f"DATE#{DAY}")) is None  # no count: the drinks ledger is untouched


# ── refusal ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [{"mood": 5}, {"mood": -1}, {"mood": "great"}, {"mood": 2.5}, {"mood": True}])
def test_an_out_of_range_mood_is_refused_and_nothing_is_written(bad, monkeypatch):
    with pytest.raises(ValueError):
        ec.validate(bad)
    table = Table()
    with pytest.raises(ValueError):
        ec.write(table, DAY, bad, "mcp", now_utc=EVENING_UTC)
    assert table.store == {}
    from mcp import tools_lifestyle as tl
    from mcp.registry import TOOLS

    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: DAY)
    monkeypatch.setattr(tl, "pacific_now", lambda: EVENING)
    with pytest.raises(ValueError):
        TOOLS["log_evening_intake"]["fn"]({"count": 1, **bad})
    assert table.store == {}


def test_a_fifth_out_of_scale_number_on_the_chat_door_is_usage_not_a_row():
    table = Table()
    _prompted(table)
    assert ec.capture_reply(table, "/checkin 2 3 1 5 bad", EVENING) == ec.USAGE_TEXT
    assert ec.capture_reply(table, "2 3 1 5 bad", EVENING) is None  # a bare line that is not a check-in: the coach answers
    assert not [k for k in table.store if k[0] == ec.PK]


# ── a row without mood is still complete ────────────────────────────────────────────────────────


def test_a_row_without_mood_is_still_tonights_answer():
    from health import core_habits

    table = Table()
    ec.write(table, DAY, {"hunger": 1, "stress": 1, "cravings": 1}, "telegram", now_utc=EVENING_UTC)
    assert ec.decide(table, DAY, EVENING, lambda p: ("tok", 1))[0] == "already_logged"  # no second prompt for a 3-number answer
    assert core_habits.checkin_state({"hunger": 1, "stress": 1, "cravings": 1}, None) is True
    assert core_habits.checkin_state({"hunger": 1, "stress": 1, "cravings": 1, "mood": 2}, None) is True
    assert core_habits.checkin_state({"mood": 2}, {"status": "sent"}) is False  # mood alone is not a check-in


# ── the mood read ───────────────────────────────────────────────────────────────────────────────


def _checkins(stresses, moods=None):
    rows = []
    for i, s in enumerate(stresses):
        row = {
            "pk": mr.CHECKIN_PK,
            "sk": f"DATE#2026-10-{10 + i:02d}",
            "date": f"2026-10-{10 + i:02d}",
            "stress": Decimal(s),
            "hunger": Decimal(2),
            "cravings": Decimal(1),
            "word": "exhausted",
        }
        if moods is not None and moods[i] is not None:
            row["mood"] = Decimal(moods[i])
        rows.append(row)
    return rows


def test_the_mood_read_uses_his_own_rating_when_an_evening_carries_one():
    read = mr.resolve([], _checkins([2, 2, 2, 2, 2, 2], moods=[1, 1, 1, 3, 3, 3]))
    assert read["source"] == "evening_checkin"
    assert read["mood_trend"] == {"direction": "rising", "avg": 2.0, "delta": 2.0, "n": 6} and read["mood_unrated"] is None
    assert read["social_quality"] is None and read["flourishing"] is None  # still never borrowed
    text = "\n".join(mr.owner_lines(read))
    assert "Reported mood (his own 0-4 rating, 4 = great): rising (mean 2.0 on 0-4, 4 = great" in text
    assert "Connection and flourishing: not measured" in text and "Mood: not measured" not in text
    assert "exhausted" not in text and "word" not in read
    partial = mr.resolve([], _checkins([2] * 6, moods=[None, None, None, None, 4, None]))  # one rated evening: n=1, honest
    assert partial["mood_trend"]["n"] == 1 and partial["mood_trend"]["direction"] == "insufficient_data"
    assert "too few readings for a direction (n=1" in "\n".join(mr.owner_lines(partial))


def test_without_a_mood_rating_the_read_says_not_measured_and_never_infers():
    read = mr.resolve([], _checkins([1, 1, 1, 3, 3, 3]))  # the pre-1.1.0 rows: no mood anywhere
    assert read["source"] == "evening_checkin" and read["mood_trend"] is None
    assert read["mood_unrated"] == mr.MOOD_UNRATED
    text = "\n".join(mr.owner_lines(read))
    assert "Mood: not measured this window" in text and "do not infer them" in text and "Reported mood" not in text
    assert mr.resolve([], _checkins([2, 2], moods=[4, 4]))["source"] == "unavailable"  # the stress floor still gates the source


def test_the_mind_thread_week_lists_mood_only_when_rated():
    from coach import coach_domain_facts as cdf

    table = Table()
    for r in _checkins([2, 2, 2], moods=[None, 3, 3]):
        r["sk"] = f"DATE#2026-10-{22 + int(r['date'][-2:]) - 10:02d}"  # 2026-10-22..24, inside the 7-day window to TODAY
        table.store[(r["pk"], r["sk"])] = r
    lines = cdf._checkin_lines(table, TODAY)
    assert any(line.startswith("mood mean 3.0 over 2 evening(s)") for line in lines)
    assert "exhausted" not in "\n".join(lines)
    bare = Table()
    for r in _checkins([2, 2, 2]):
        r["sk"] = f"DATE#2026-10-{22 + int(r['date'][-2:]) - 10:02d}"
        bare.store[(r["pk"], r["sk"])] = r
    assert not any(line.startswith("mood") for line in cdf._checkin_lines(bare, TODAY))


# ── the partner view is unchanged ───────────────────────────────────────────────────────────────


def test_the_partner_view_never_sees_the_mood_rating():
    assert pv.FIELDS == ("stress", "hunger", "cravings") and "mood" not in pv.PROJECTION
    rows = [
        {"sk": f"DATE#2026-10-{d:02d}", "has_checkin": True, "stress": 3, "hunger": 1, "cravings": 1, "mood": 0} for d in (20, 21, 22, 23)
    ]
    view = pv.summarize(rows, rows)
    assert set(view["ratings"]) == {"stress", "hunger", "cravings"} and view["evenings"] == 4
    assert "mood" not in repr(view)
