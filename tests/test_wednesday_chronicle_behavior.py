"""tests/test_wednesday_chronicle_behavior.py — behavioural contracts for the
Wednesday Chronicle generator (`lambdas/emails/wednesday_chronicle_lambda.py`).

The existing chronicle suite covers the pieces the #1654 god-module split moved
OUT of this file — the data packet (test_chronicle_data_packet.py), the recap
(test_chronicle_recap.py), weekday grounding, prologue ordering, the share kit,
the post template, Elena's tombstoned persona state (#1200) — plus the SENDER's
double-send gate (test_chronicle_double_send_2112.py, a different Lambda:
`chronicle-email-sender`).

Nothing covered `lambda_handler` itself, and that is where this Lambda's risk
lives: it is the function that spends Bedrock money, decides whether a week is
published or held, writes the installment row, and mails Matthew. This file
covers the handler end to end plus the helpers that stayed behind:

  * the handler's route table — recap_only, budget pause, gather failure, packet
    failure, AI failure, the ADR-104 grounding gate, the #914 presence hold, the
    AI-3 block, the privacy hold, PREVIEW_MODE vs immediate publish;
  * what is actually WRITTEN and MAILED on each route (which is the only way to
    tell a "held" week from a silently-skipped one);
  * Elena's notebook block and Margaret's edit pass — the prompt obligations and
    the ≤1/month editor's-note gate;
  * record_email_send.

SAFETY: this file never invokes a deployed Lambda and never lets anything reach
`ses.send_email` for real — `m.ses` is always a `FakeSES`. `chronicle-email-
sender` has no dry_run gate at all (#2111) and is never touched here. No AWS, no
Bedrock, no network: `call_anthropic` is always a local fake.

Clock discipline: this is a WEEKLY sender whose week numbering and ISO-week
lookups are load-bearing, so every test that touches "now" freezes it via
`_FrozenDatetime` monkeypatched onto the module. No test combines a fixture date
with a real `datetime.now()`.

Fakes are hand-rolled and bounded — no MagicMock inside a pagination- or
loop-shaped read.

This file carried six `DEFECT (tranche-3 discovery)` xfail markers. #2221 burned
all six — every one named a real defect, and each fix landed in production code
(the facade, emails/chronicle_personas.py, emails/chronicle_render.py,
emails/chronicle_store.py and scripts/v4_build_journal.py). There are no xfails
left here: a failure in this file is a regression, not a known gap.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

# The module reads these at import time (S3_BUCKET/EMAIL_RECIPIENT/EMAIL_SENDER are
# os.environ[...] lookups, not .get) and builds boto3 clients at module level.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import wednesday_chronicle_lambda as m  # noqa: E402
from ai import budget_guard as _budget_guard  # noqa: E402
from experiment import eval_retention  # noqa: E402
from privacy import privacy_guard  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock — Wednesday 2026-08-05 15:00 UTC (the EventBridge slot,
# cron(0 15 ? * WED *) = 7:00 AM PT). 2026-08-05 is a Wednesday.
# ──────────────────────────────────────────────────────────────────────────────

FROZEN_NOW = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
WEEK_END = "2026-08-04"  # the window's last day (yesterday), the installment's date


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`/`utcnow()`.

    A subclass (rather than a Mock) keeps `strptime`, arithmetic and `.date()`
    working, which the module and the helpers it delegates to use on the same
    name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(m, "datetime", _FrozenDatetime)
    for mod_name in ("emails.chronicle_store", "emails.chronicle_render", "emails.chronicle_recap"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "datetime"):
            monkeypatch.setattr(mod, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Bounded fakes
# ──────────────────────────────────────────────────────────────────────────────


def _key_condition(cond):
    """Flatten a boto3 `Key(...).eq(...) & Key(...).begins_with(...)` tree into
    a plain `{field: (operator, value)}` dict.

    `_elena_notebook_block` and `_due_callback_promises` build boto3 condition
    objects, while every other read in the module passes a KeyConditionExpression
    STRING plus ExpressionAttributeValues. The fake has to serve both shapes, and
    guessing by call order would make the fake order-dependent — so it reads the
    condition instead.
    """
    out = {}
    if isinstance(cond, str):
        return out
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        for sub in expr["values"]:
            out.update(_key_condition(sub))
        return out
    field, value = expr["values"]
    out[field.name] = (expr["operator"], value)
    return out


class FakeTable:
    """Bounded DynamoDB `Table` stand-in.

    `rows` is a flat list of items. `query()` serves the ones whose pk matches and
    whose sk carries the requested prefix / range; `get_item()` reads the same
    list by (pk, sk). Every call is logged for assertions. No unbounded mock is
    used anywhere: the fake owns a finite list and returns slices of it.
    """

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries = []
        self.gets = []
        self.puts = []
        self.put_kwargs = []
        self.put_error = None
        self.query_error = None
        self.get_error = None

    def _matching(self, pk, sk_prefix=None, sk_lo=None, sk_hi=None):
        out = [r for r in self.rows if r.get("pk") == pk]
        if sk_prefix:
            out = [r for r in out if str(r.get("sk", "")).startswith(sk_prefix)]
        if sk_lo is not None and sk_hi is not None:
            out = [r for r in out if sk_lo <= str(r.get("sk", "")) <= sk_hi]
        out.sort(key=lambda r: str(r.get("sk", "")))
        return out

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error:
            raise self.query_error
        cond = kwargs.get("KeyConditionExpression")
        eav = kwargs.get("ExpressionAttributeValues") or {}
        if isinstance(cond, str):
            pk = eav.get(":pk")
            items = self._matching(pk, sk_prefix=eav.get(":prefix"), sk_lo=eav.get(":s"), sk_hi=eav.get(":e"))
        else:
            flat = _key_condition(cond)
            pk = flat.get("pk", (None, None))[1]
            prefix = flat.get("sk", (None, None))[1] if flat.get("sk", ("", ""))[0] == "begins_with" else None
            items = self._matching(pk, sk_prefix=prefix)
        if kwargs.get("ScanIndexForward") is False:
            items = list(reversed(items))
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        return {"Items": items}

    def get_item(self, Key=None, **kwargs):
        self.gets.append(Key)
        if self.get_error:
            raise self.get_error
        for r in self.rows:
            if r.get("pk") == Key.get("pk") and r.get("sk") == Key.get("sk"):
                return {"Item": r}
        return {}

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        self.put_kwargs.append({"Item": Item, **kwargs})
        if self.put_error:
            raise self.put_error
        self.rows = [r for r in self.rows if (r.get("pk"), r.get("sk")) != (Item.get("pk"), Item.get("sk"))]
        self.rows.append(Item)
        return {}


class FakeSES:
    """Records sends. NOTHING in this file may reach the real SES client."""

    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "fake"}


class FakeS3:
    """Bounded S3 stand-in — an in-memory key/value store with optional canned
    reads for the board config and the journal manifest."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []
        self.gets = []

    def get_object(self, Bucket=None, Key=None, **kwargs):
        self.gets.append(Key)
        if Key not in self.objects:
            raise RuntimeError(f"NoSuchKey: {Key}")

        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

        return {"Body": _Body(self.objects[Key])}

    def put_object(self, Bucket=None, Key=None, Body=None, **kwargs):
        self.puts.append({"Key": Key, "Body": Body, **kwargs})
        self.objects[Key] = Body
        return {}


class FakeLambdaClient:
    """Stands in for every `boto3.client(...)` built inside a function body.

    The handler builds a Lambda client for the elena-state-updater invoke; the
    fail-soft retention/archive helpers it calls build S3 clients the same way.
    One fake answers all of them so no call can escape to AWS.
    """

    def __init__(self):
        self.invocations = []
        self.error = None

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        if self.error:
            raise self.error
        return {"StatusCode": 202}

    def put_object(self, **kwargs):
        return {}

    def get_object(self, **kwargs):
        raise RuntimeError("NoSuchKey")


class FakeInsightWriter:
    def __init__(self, context=""):
        self.context = context
        self.written = []

    def build_insights_context(self, **kwargs):
        return self.context

    def write_insight(self, **kwargs):
        self.written.append(kwargs)
        return kwargs

    def _extract_pillars_from_text(self, text):
        return ["mind"]


# ──────────────────────────────────────────────────────────────────────────────
# Installment fixtures
#
# Every number in the prose below also appears in the data packet the fake AI is
# given, so the ADR-104 grounding allow-list is satisfied without a regeneration
# round-trip. The prose is deliberately plain: no real public figure, no named
# substance — the deterministic privacy gate runs for real in these tests.
# ──────────────────────────────────────────────────────────────────────────────

TITLE = "The Week the Numbers Stopped Arguing"
STATS_LINE = "Weight: 312.4 lbs | Week Grade: avg 66 | T0 Streak: 5 days"
BODY = (
    "The scale read 312.4 on Tuesday morning and he looked at it for a long time.\n\n"
    "Something had shifted in the middle of the week, and it was not the kind of shift that "
    "shows up as a headline. His recovery held steady while the training load climbed, which "
    "is the sort of quiet arithmetic that only makes sense in retrospect. He took the rest day "
    "he had been avoiding, and the week did not fall apart.\n\n"
    "By Friday the pattern was legible enough to name. Five days of the streak intact, an "
    "average grade of 66, and a body that had stopped treating every session as an emergency.\n\n"
    "What happens next is the part nobody can chart in advance.\n\n"
    "---\n"
    "*Week 5 of The Measured Life*"
)
RAW_INSTALLMENT = f'"{TITLE}"\n\n[{STATS_LINE}]\n\n{BODY}'

DATA_PACKET = (
    "Week number: 5\n"
    "Window: 2026-07-29 -> 2026-08-04\n"
    "Weight: 312.4 lbs (latest weigh-in)\n"
    "Week grade: avg 66 across 7 days\n"
    "Tier 0 streak: 5 days\n"
    "Rest days taken: 1\n"
)


def _data(**over):
    d = {
        "dates": {"start": "2026-07-29", "end": WEEK_END},
        "prev_installments": [],
        "profile": {"journey_start_date": "2026-08-03", "goal_weight_lbs": 220},
        "narrative_arc": None,
    }
    d.update(over)
    return d


def _installment_row(date_str, week, title="Prior Week", md="Earlier prose about the week.", status="published"):
    return {
        "pk": f"USER#{m.USER_ID}#SOURCE#chronicle",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "week_number": week,
        "title": title,
        "content_markdown": md,
        "status": status,
    }


@pytest.fixture
def env(monkeypatch, frozen_clock):
    """Wire lambda_handler to fakes. Mail is NEVER sent; nothing reaches AWS."""
    table = FakeTable()
    ses = FakeSES()
    s3 = FakeS3()
    writer = FakeInsightWriter()
    lam = FakeLambdaClient()
    calls = {"ai": [], "packet": []}
    state = {"ai": RAW_INSTALLMENT, "ai_error": None, "data": _data(), "packet": (DATA_PACKET, 5)}

    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "ses", ses)
    monkeypatch.setattr(m, "s3", s3)
    monkeypatch.setattr(m, "insight_writer", writer)
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "PREVIEW_MODE", True)
    monkeypatch.setattr(m, "APPROVE_LAMBDA_URL", "https://approve.example.invalid/")
    monkeypatch.setattr(m.boto3, "client", lambda *a, **k: lam)

    # Budget guard reads SSM — pin it open rather than reaching the network.
    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    # Eval retention owns its own DynamoDB handle (it is fail-soft, so a real
    # write would only surface as a warning) — capture it instead of letting it
    # reach AWS.
    retained = []
    monkeypatch.setattr(eval_retention, "retain", lambda *a, **k: retained.append((a, k)))

    def _fake_ai(system_prompt, user_message, archive_text=None):
        calls["ai"].append({"system": system_prompt, "user": user_message, "archive": archive_text})
        if state["ai_error"]:
            raise state["ai_error"]
        return state["ai"]

    monkeypatch.setattr(m, "call_anthropic", _fake_ai)
    monkeypatch.setattr(m, "gather_chronicle_data", lambda: state["data"])

    def _fake_packet(data):
        calls["packet"].append(data)
        if isinstance(state["packet"], Exception):
            raise state["packet"]
        return state["packet"]

    monkeypatch.setattr(m, "build_data_packet", _fake_packet)
    # The grounding gate's findings function is exercised in its own tests; the
    # default route is "clean draft" so one handler run == one AI call.
    monkeypatch.setattr(m, "installment_grounding_findings", lambda *a, **k: [])
    # Margaret's red pen needs Bedrock; it has its own tests below.
    monkeypatch.setattr(m, "_run_margaret_edit_pass", lambda raw, wk, ds, prompt, allowed: raw)
    monkeypatch.setattr(m, "build_recap", lambda data, **kw: {"as_of": WEEK_END, "recent_beats": ["a beat"]})

    return {
        "table": table,
        "ses": ses,
        "s3": s3,
        "writer": writer,
        "lambda_client": lam,
        "calls": calls,
        "state": state,
        "retained": retained,
        "monkeypatch": monkeypatch,
    }


def _stored_installment(env):
    # sk filter (#2669): the generation-cache row (RAWCACHE#, chronicle_store)
    # shares the partition and source; "the stored installment" means the DATE# row.
    rows = [p for p in env["table"].puts if p.get("source") == "chronicle" and str(p.get("sk", "")).startswith("DATE#")]
    return rows[0] if rows else None


def _preview_email(env):
    return env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]


def _pending_marker(env):
    for put in env["s3"].puts:
        if put["Key"] == "generated/journal/posts.json":
            return json.loads(put["Body"]).get("pending")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# The #1654 facade — the split modules must see this file's LIVE state
#
# Every helper moved to emails/chronicle_*.py reads the facade's globals through a
# per-call `_g` hand-off. That is the whole contract of the split: monkeypatching
# `wednesday_chronicle_lambda.table` (as every caller and every test does) has to
# reach the moved code. If a delegator ever stops passing globals(), the helpers
# would silently read the module's import-time boto3 clients — against production.
# ══════════════════════════════════════════════════════════════════════════════


def test_the_range_query_facade_reads_the_configured_table_and_user(monkeypatch):
    from common import digest_utils

    seen = {}
    monkeypatch.setattr(digest_utils, "query_range", lambda table, source, s, e, user_id=None: seen.update(locals()) or {})
    monkeypatch.setattr(m, "table", FakeTable())
    m.query_range("whoop", "2026-07-29", WEEK_END)
    assert seen["table"] is m.table
    assert seen["user_id"] == m.USER_ID
    assert (seen["source"], seen["s"], seen["e"]) == ("whoop", "2026-07-29", WEEK_END)


def test_the_list_query_facade_preserves_duplicates_for_per_workout_schemas(monkeypatch):
    from common import digest_utils

    seen = {}
    monkeypatch.setattr(digest_utils, "query_range_list", lambda table, source, s, e, user_id=None: seen.update(locals()) or [])
    monkeypatch.setattr(m, "table", FakeTable())
    m.query_range_list("hevy", "2026-07-29", WEEK_END)
    assert seen["source"] == "hevy" and seen["user_id"] == m.USER_ID


def test_the_profile_facade_reads_the_configured_table_and_user(monkeypatch):
    from intelligence import intelligence_common

    seen = {}
    monkeypatch.setattr(intelligence_common, "fetch_profile", lambda table, user_id: seen.update({"t": table, "u": user_id}) or {"ok": 1})
    monkeypatch.setattr(m, "table", FakeTable())
    assert m.fetch_profile() == {"ok": 1}
    assert seen["u"] == m.USER_ID


def test_the_gather_facade_hands_the_split_module_this_files_globals(monkeypatch):
    from emails import chronicle_data

    seen = {}
    monkeypatch.setattr(chronicle_data, "gather_chronicle_data", lambda *, _g: seen.update(_g) or {"ok": 1})
    assert m.gather_chronicle_data() == {"ok": 1}
    assert seen["USER_ID"] == m.USER_ID
    assert seen["table"] is m.table


def test_the_calendar_facts_facade_forwards_the_window_and_the_genesis():
    facts = m.build_calendar_facts("2026-08-03", "2026-08-04", genesis="2026-08-03")
    assert "2026-08-03" in facts and "2026-08-04" in facts


def test_the_stats_line_facade_renders_the_line_a_reader_sees(monkeypatch):
    monkeypatch.setattr(m, "table", FakeTable())
    out = m.display_stats_line(STATS_LINE, WEEK_END)
    assert isinstance(out, str)
    assert "312.4" in out


def test_the_recap_facade_hands_the_split_module_this_files_globals(monkeypatch):
    from emails import chronicle_recap

    seen = {}
    monkeypatch.setattr(chronicle_recap, "build_recap", lambda data, new_installment_md=None, new_meta=None, *, _g: seen.update(_g) or None)
    m.build_recap(_data())
    assert seen["privacy_guard"] is m.privacy_guard


def test_the_grounding_findings_facade_forwards_the_archive(monkeypatch):
    from emails import chronicle_prompt

    seen = {}
    monkeypatch.setattr(
        chronicle_prompt,
        "installment_grounding_findings",
        lambda p, u, t, archive_text=None: seen.update({"archive": archive_text}) or [],
    )
    m.installment_grounding_findings("P", "U", "T", archive_text="ARCHIVE")
    assert seen["archive"] == "ARCHIVE"


# ══════════════════════════════════════════════════════════════════════════════
# record_email_send
# ══════════════════════════════════════════════════════════════════════════════


def test_a_send_is_recorded_under_todays_date_for_the_status_page(frozen_clock):
    table = FakeTable()
    m.record_email_send(table, "wednesday_chronicle")
    item = table.puts[0]
    assert item["sk"] == f"DATE#{FROZEN_NOW.date().isoformat()}"
    assert item["status"] == "success"
    assert item["pk"].endswith("email_log#wednesday_chronicle")


def test_the_send_record_expires_after_about_ninety_days(frozen_clock):
    table = FakeTable()
    m.record_email_send(table, "wednesday_chronicle")
    ttl_days = (table.puts[0]["ttl"] - time.time()) / 86400
    assert 89 < ttl_days <= 90


def test_a_failed_status_write_never_takes_down_the_chronicle(frozen_clock):
    table = FakeTable()
    table.put_error = RuntimeError("throughput exceeded")
    m.record_email_send(table, "wednesday_chronicle")  # must not raise


def test_the_send_record_is_keyed_to_the_configured_user(monkeypatch, frozen_clock):
    """#2221 (was a tranche-3 xfail): record_email_send hard-coded 'USER#matthew' while
    every other write in this Lambda derives the user from USER_ID."""
    monkeypatch.setattr(m, "USER_ID", "someone_else")
    table = FakeTable()
    m.record_email_send(table, "wednesday_chronicle")
    assert table.puts[0]["pk"].startswith("USER#someone_else#")


# ══════════════════════════════════════════════════════════════════════════════
# _elena_notebook_block — the persistent-memory prompt obligations (#537)
# ══════════════════════════════════════════════════════════════════════════════

ELENA_PK = "PERSONA#elena"


def _stance(headline="He is testing whether structure can outlast motivation.", **over):
    row = {"pk": ELENA_PK, "sk": "STANCE#latest", "headline_stance": headline}
    row.update(over)
    return row


def _thread(slug, summary, opened=1, last_ref=None, status="open"):
    row = {
        "pk": ELENA_PK,
        "sk": f"THREAD#{slug}",
        "slug": slug,
        "summary": summary,
        "status": status,
        "opened_week": opened,
    }
    if last_ref is not None:
        row["last_referenced_week"] = last_ref
    return row


def _callback(promise, due, made=1, status="pending"):
    return {
        "pk": ELENA_PK,
        "sk": f"CALLBACK#{promise[:12]}",
        "promise": promise,
        "due_by_week": due,
        "made_in_week": made,
        "status": status,
    }


def _notebook(monkeypatch, rows, week=5):
    monkeypatch.setattr(m, "table", FakeTable(rows))
    return m._elena_notebook_block(week)


def test_an_empty_notebook_adds_nothing_to_the_prompt(monkeypatch):
    assert _notebook(monkeypatch, []) == ""


def test_the_notebook_carries_elenas_stance_and_its_positions(monkeypatch):
    stance = _stance(positions=["The streak is a proxy, not the point.", "Rest is the hard skill."])
    block = _notebook(monkeypatch, [stance])
    assert "YOUR EDITORIAL STANCE" in block
    assert "structure can outlast motivation" in block
    assert "The streak is a proxy, not the point." in block


def test_only_the_first_five_stance_positions_reach_the_prompt(monkeypatch):
    stance = _stance(positions=[f"position {i}" for i in range(9)])
    block = _notebook(monkeypatch, [stance])
    assert block.count("- position:") == 5


def test_a_stance_that_changed_says_how_it_changed(monkeypatch):
    block = _notebook(monkeypatch, [_stance(how_my_stance_changed="Last week's rest day made me less sure.")])
    assert "How my read changed after last week: Last week's rest day made me less sure." in block


def test_a_stance_flagged_for_grounding_is_withheld_from_the_prompt(monkeypatch):
    """A stance the grounding gate flagged must not be replayed as fact."""
    block = _notebook(monkeypatch, [_stance(grounding_flag=True)])
    assert "YOUR EDITORIAL STANCE" not in block


def test_open_threads_reach_the_prompt_with_their_age(monkeypatch):
    block = _notebook(monkeypatch, [_thread("rest-day-fear", "He will not take a rest day.", opened=2, last_ref=5)], week=5)
    assert "OPEN STORY THREADS" in block
    assert "[opened wk 2, age 3 wk]" in block  # 5 - 2
    assert "rest-day-fear: He will not take a rest day." in block


def test_a_thread_untouched_for_three_weeks_is_flagged_stale(monkeypatch):
    block = _notebook(monkeypatch, [_thread("old", "An unresolved tension.", opened=1, last_ref=2)], week=5)
    assert "[STALE — close it or complicate it THIS week]" in block  # 5 - 2 == 3


def test_a_thread_referenced_last_week_is_not_flagged_stale(monkeypatch):
    block = _notebook(monkeypatch, [_thread("fresh", "A live tension.", opened=1, last_ref=4)], week=5)
    assert "STALE" not in block


def test_a_closed_thread_is_not_replayed_as_an_obligation(monkeypatch):
    block = _notebook(monkeypatch, [_thread("done", "Resolved last week.", status="closed")])
    assert "OPEN STORY THREADS" not in block


def test_at_most_eight_open_threads_reach_the_prompt(monkeypatch):
    rows = [_thread(f"t{i}", f"tension {i}", opened=1, last_ref=5) for i in range(12)]
    block = _notebook(monkeypatch, rows, week=5)
    assert block.count("[opened wk 1") == 8


def test_a_promise_due_this_week_is_stated_as_an_obligation(monkeypatch):
    block = _notebook(monkeypatch, [_callback("Return to the question of whether he likes any of this.", due=5, made=3)], week=5)
    assert "PROMISES DUE" in block
    assert "[made wk 3, due now]" in block


def test_a_promise_past_its_due_week_says_how_overdue_it_is(monkeypatch):
    block = _notebook(monkeypatch, [_callback("Follow up on the rest day.", due=3, made=1)], week=5)
    assert "OVERDUE by 2 wk" in block  # 5 - 3


def test_a_promise_not_yet_due_is_kept_alive_but_separate(monkeypatch):
    block = _notebook(monkeypatch, [_callback("Revisit the weight plateau.", due=9, made=5)], week=5)
    assert "PROMISES OUTSTANDING" in block
    assert "[due wk 9]" in block
    assert "PROMISES DUE" not in block


def test_a_paid_off_promise_is_not_asked_for_twice(monkeypatch):
    block = _notebook(monkeypatch, [_callback("Already paid.", due=3, status="paid")], week=5)
    assert "PROMISES" not in block


def test_running_motifs_reach_the_prompt_with_their_reuse_rule(monkeypatch):
    motifs = {"pk": ELENA_PK, "sk": "MOTIF#state", "motifs": [{"phrase": "the quiet arithmetic"}, "the scale as a witness"]}
    block = _notebook(monkeypatch, [motifs])
    assert "YOUR RUNNING MOTIFS" in block
    assert "at most one per installment" in block
    assert "the quiet arithmetic; the scale as a witness" in block


def test_at_most_six_motifs_reach_the_prompt(monkeypatch):
    motifs = {"pk": ELENA_PK, "sk": "MOTIF#state", "motifs": [f"motif {i}" for i in range(10)]}
    block = _notebook(monkeypatch, [motifs])
    assert block.count("motif ") == 6


def test_a_notebook_read_failure_degrades_to_no_block_rather_than_a_failed_week(monkeypatch):
    table = FakeTable()
    table.query_error = RuntimeError("ddb down")
    monkeypatch.setattr(m, "table", table)
    assert m._elena_notebook_block(5) == ""


def test_a_promise_due_in_the_prologue_week_is_still_due(monkeypatch):
    """#2221 (was a tranche-3 xfail): week 0 is a REAL week — the prologue. The
    `int(x or 10**6)` idiom made a week-0 deadline falsy, so the most overdue promise
    Elena could hold was the one the gate could never surface. Owner is
    emails/chronicle_personas.py, not the facade."""
    block = _notebook(monkeypatch, [_callback("Explain why he started.", due=0, made=0)], week=5)
    assert "PROMISES DUE" in block


# ══════════════════════════════════════════════════════════════════════════════
# _due_callback_promises — Margaret's critique input (#548)
# ══════════════════════════════════════════════════════════════════════════════


def test_only_promises_due_by_this_week_are_handed_to_margaret(monkeypatch):
    rows = [_callback("Due now.", due=5), _callback("Not yet.", due=8), _callback("Overdue.", due=2)]
    monkeypatch.setattr(m, "table", FakeTable(rows))
    assert sorted(m._due_callback_promises(5)) == ["Due now.", "Overdue."]


def test_at_most_five_due_promises_are_handed_to_margaret(monkeypatch):
    rows = [_callback(f"Promise {i}.", due=1) for i in range(9)]
    monkeypatch.setattr(m, "table", FakeTable(rows))
    assert len(m._due_callback_promises(5)) == 5


def test_the_promise_limit_is_caller_configurable(monkeypatch):
    rows = [_callback(f"Promise {i}.", due=1) for i in range(9)]
    monkeypatch.setattr(m, "table", FakeTable(rows))
    assert len(m._due_callback_promises(5, limit=2)) == 2


def test_a_promise_row_with_no_text_is_dropped_rather_than_handed_over_empty(monkeypatch):
    row = _callback("x", due=1)
    del row["promise"]
    monkeypatch.setattr(m, "table", FakeTable([row]))
    assert m._due_callback_promises(5) == []


def test_a_ledger_read_failure_leaves_margaret_without_the_cross_reference(monkeypatch):
    table = FakeTable()
    table.query_error = RuntimeError("ddb down")
    monkeypatch.setattr(m, "table", table)
    assert m._due_callback_promises(5) == []


# ══════════════════════════════════════════════════════════════════════════════
# Margaret's editor's-note ledger
# ══════════════════════════════════════════════════════════════════════════════

MARGARET_PK = "PERSONA#margaret"


def test_no_prior_editors_note_reports_absence(monkeypatch):
    monkeypatch.setattr(m, "table", FakeTable())
    assert m._margaret_last_note_date() is None


def test_the_last_editors_note_date_drives_the_monthly_gate(monkeypatch):
    monkeypatch.setattr(m, "table", FakeTable([{"pk": MARGARET_PK, "sk": "NOTE#latest", "date": "2026-07-15"}]))
    assert m._margaret_last_note_date() == "2026-07-15"


def test_a_ledger_read_failure_does_not_block_the_edit_pass(monkeypatch):
    table = FakeTable()
    table.get_error = RuntimeError("ddb down")
    monkeypatch.setattr(m, "table", table)
    assert m._margaret_last_note_date() is None


def test_a_published_note_is_recorded_both_dated_and_as_latest(monkeypatch, frozen_clock):
    table = FakeTable()
    monkeypatch.setattr(m, "table", table)
    m._record_margaret_note(WEEK_END, 5, "A note about restraint.")
    sks = [p["sk"] for p in table.puts]
    assert sks == [f"NOTE#{WEEK_END}", "NOTE#latest"]
    assert table.puts[0]["note"] == "A note about restraint."
    assert table.puts[0]["week_number"] == 5


def test_a_failed_note_write_never_blocks_the_installment(monkeypatch, frozen_clock):
    table = FakeTable()
    table.put_error = RuntimeError("throughput exceeded")
    monkeypatch.setattr(m, "table", table)
    m._record_margaret_note(WEEK_END, 5, "A note.")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# _margaret_haiku_call / _run_margaret_edit_pass
# ══════════════════════════════════════════════════════════════════════════════


def test_margarets_pen_runs_on_the_cheap_model_at_a_low_temperature(monkeypatch):
    from common import retry_utils

    seen = {}
    monkeypatch.setattr(retry_utils, "call_anthropic_api", lambda **kw: seen.update(kw) or "critique")
    assert m._margaret_haiku_call("SYSTEM", "USER") == "critique"
    assert seen["model"] == m.AI_MODEL_HAIKU
    assert seen["temperature"] == 0.3
    assert seen["system"] == "SYSTEM" and seen["prompt"] == "USER"


def test_a_budget_pause_keeps_elenas_draft_untouched(monkeypatch):
    monkeypatch.setattr(_budget_guard, "allow", lambda feature: feature != "chronicle_editor")
    out = m._run_margaret_edit_pass(RAW_INSTALLMENT, 5, WEEK_END, "ELENA PROMPT", {"312.4"})
    assert out == RAW_INSTALLMENT


def test_the_edit_pass_returns_margarets_revision_when_she_revises(monkeypatch):
    from ai import margaret_editor_pass as mep

    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(m, "table", FakeTable())
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    monkeypatch.setattr(
        mep,
        "run_pass",
        lambda *a, **k: {
            "final_text": "REVISED PROSE",
            "revised": True,
            "revision_reason": "tightened",
            "critique": {},
            "editors_note": "",
        },
    )
    assert m._run_margaret_edit_pass(RAW_INSTALLMENT, 5, WEEK_END, "ELENA PROMPT", None) == "REVISED PROSE"


def test_an_editors_note_that_publishes_is_recorded_for_the_monthly_gate(monkeypatch, frozen_clock):
    from ai import margaret_editor_pass as mep

    table = FakeTable()
    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    monkeypatch.setattr(
        mep,
        "run_pass",
        lambda *a, **k: {
            "final_text": RAW_INSTALLMENT,
            "revised": False,
            "revision_reason": "clean",
            "critique": {},
            "editors_note": "> Editor's note: we held a claim this week.",
        },
    )
    m._run_margaret_edit_pass(RAW_INSTALLMENT, 5, WEEK_END, "ELENA PROMPT", None)
    assert [p["sk"] for p in table.puts] == [f"NOTE#{WEEK_END}", "NOTE#latest"]


def test_a_failing_edit_pass_keeps_elenas_draft_rather_than_losing_the_week(monkeypatch):
    from ai import margaret_editor_pass as mep

    def _boom(*a, **k):
        raise RuntimeError("bedrock throttled")

    monkeypatch.setattr(_budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(m, "table", FakeTable())
    monkeypatch.setattr(m, "_HAS_BOARD_LOADER", False)
    monkeypatch.setattr(mep, "run_pass", _boom)
    assert m._run_margaret_edit_pass(RAW_INSTALLMENT, 5, WEEK_END, "ELENA PROMPT", None) == RAW_INSTALLMENT


# ══════════════════════════════════════════════════════════════════════════════
# _invoke_elena_state_updater
# ══════════════════════════════════════════════════════════════════════════════


def test_the_state_updater_is_invoked_asynchronously_with_the_published_date(monkeypatch):
    lam = FakeLambdaClient()
    monkeypatch.setattr(m.boto3, "client", lambda *a, **k: lam)
    m._invoke_elena_state_updater(WEEK_END)
    assert lam.invocations[0]["InvocationType"] == "Event"
    assert json.loads(lam.invocations[0]["Payload"]) == {"date": WEEK_END}


def test_a_failed_state_updater_invoke_never_fails_the_publish(monkeypatch):
    lam = FakeLambdaClient()
    lam.error = RuntimeError("function not found")
    monkeypatch.setattr(m.boto3, "client", lambda *a, **k: lam)
    m._invoke_elena_state_updater(WEEK_END)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# parse_installment / markdown_to_html — what the reader ends up with
# ══════════════════════════════════════════════════════════════════════════════


def test_the_title_stats_line_and_body_are_split_out_of_elenas_draft():
    title, stats, body = m.parse_installment(RAW_INSTALLMENT)
    assert title == TITLE
    assert stats == STATS_LINE
    assert body.startswith("The scale read 312.4")


def test_a_draft_with_no_stats_line_still_yields_a_title_and_a_body():
    title, stats, body = m.parse_installment('"A Quiet Week"\n\nHe went for a walk and thought about nothing in particular.')
    assert title == "A Quiet Week"
    assert stats == ""
    assert body.startswith("He went for a walk")


def test_an_untitled_draft_is_labelled_untitled_rather_than_crashing():
    assert m.parse_installment("")[0] == "Untitled"


def test_a_board_interview_is_rendered_as_a_blockquote():
    html = m.markdown_to_html("He asked about the plateau.\n\n> Dr. Park was unimpressed.\n\nThe answer stayed with him.")
    assert "<blockquote>Dr. Park was unimpressed.</blockquote>" in html


def test_the_closing_signature_is_rendered_as_a_signature_line():
    assert 'class="signature"' in m.markdown_to_html("Prose.\n\n---\n*Week 5 of The Measured Life*")


def test_a_board_interview_at_the_very_end_of_an_installment_is_not_dropped():
    """The buffer is flushed after the loop, so an interview as the closing beat
    survives. Pinned because losing it would be invisible: has_board_interview
    would still be stored True while the quote vanished from email and journal."""
    html = m.markdown_to_html("He asked about the plateau.\n\n> Dr. Park had the last word.")
    assert "<blockquote>Dr. Park had the last word.</blockquote>" in html


def test_a_blockquote_without_a_space_is_still_recognised_as_an_interview():
    """#2221 (was a tranche-3 xfail): the markdown blockquote marker is ">"; the space
    after it is optional. All THREE matchers were strict — the handler's has_board
    detector, markdown_to_html, and scripts/v4_build_journal.py (the public page)."""
    body = "He asked about the plateau.\n\n>Dr. Park was unimpressed.\n\nHe let it sit."
    assert any(line.strip().startswith(">") for line in body.split("\n"))
    assert "<blockquote>" in m.markdown_to_html(body)


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — recap_only route
# ══════════════════════════════════════════════════════════════════════════════


def test_recap_only_writes_the_recap_without_generating_a_new_week(env):
    written = []
    env["monkeypatch"].setattr(m, "_write_recap", lambda recap, date_str: written.append((recap, date_str)))
    resp = m.lambda_handler({"recap_only": True}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "recap_written"
    assert written[0][1] == WEEK_END
    assert env["calls"]["ai"] == []  # no Bedrock spend
    assert env["ses"].sent == []


def test_recap_only_reports_how_many_beats_it_committed(env):
    env["monkeypatch"].setattr(m, "_write_recap", lambda recap, date_str: None)
    env["monkeypatch"].setattr(m, "build_recap", lambda data, **kw: {"as_of": WEEK_END, "recent_beats": ["a", "b", "c"]})
    assert json.loads(m.lambda_handler({"recap_only": True}, None)["body"])["beats"] == 3


def test_recap_only_with_no_published_history_writes_nothing(env):
    env["monkeypatch"].setattr(m, "build_recap", lambda data, **kw: None)
    resp = m.lambda_handler({"recap_only": True}, None)
    assert json.loads(resp["body"])["status"] == "recap_skipped"


def test_recap_only_reports_failure_when_the_data_gather_fails(env):
    env["monkeypatch"].setattr(m, "gather_chronicle_data", lambda: None)
    assert m.lambda_handler({"recap_only": True}, None)["statusCode"] == 500


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the pause / failure routes
# ══════════════════════════════════════════════════════════════════════════════


def test_a_budget_pause_skips_the_week_without_spending_on_bedrock(env):
    env["monkeypatch"].setattr(_budget_guard, "allow", lambda feature: feature != "chronicle")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200 and "budget tier" in resp["body"]
    assert env["calls"]["ai"] == []
    assert env["ses"].sent == []


def test_a_budget_paused_week_tells_the_reader_why_it_is_missing(env):
    """#803: a held week must leave a trace the site can render, not a silent gap."""
    env["monkeypatch"].setattr(_budget_guard, "allow", lambda feature: feature != "chronicle")
    m.lambda_handler({}, None)
    pending = _pending_marker(env)
    assert pending["reason"] == "budget_tier"
    assert "AI budget guard" in pending["display"]


def test_a_failed_data_gather_reports_failure_and_publishes_nothing(env):
    env["monkeypatch"].setattr(m, "gather_chronicle_data", lambda: None)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert env["ses"].sent == [] and env["table"].puts == []


def test_a_broken_data_packet_degrades_to_a_visible_five_hundred(env):
    env["state"]["packet"] = KeyError("total_score")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert "Failed to build data packet" in resp["body"]
    assert env["ses"].sent == []


def test_an_ai_failure_reports_failure_and_publishes_nothing(env):
    env["state"]["ai_error"] = RuntimeError("bedrock throttled")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert "AI generation failed" in resp["body"]
    assert env["ses"].sent == []
    assert _stored_installment(env) is None


def test_an_installment_the_safety_validator_blocks_is_never_published(env):
    env["state"]["ai"] = '"T"\n\n[x]\n\nToo short.'  # under AI-3's 200-char floor
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert "[AI-3]" in resp["body"]
    assert env["ses"].sent == [] and _stored_installment(env) is None


def test_a_week_held_by_the_safety_validator_tells_the_reader_it_was_held(env):
    """#2221 (was a tranche-3 xfail, #803 class): every non-publishing exit now leaves a
    reader-facing marker via _held_week — the AI-3 block, the #914 presence hold, the
    packet failure, the AI failure and the gather failure, not just budget + privacy."""
    env["state"]["ai"] = '"T"\n\n[x]\n\nToo short.'
    m.lambda_handler({}, None)
    assert _pending_marker(env) is not None


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the privacy gate
# ══════════════════════════════════════════════════════════════════════════════


def test_an_installment_that_fails_the_privacy_gate_is_never_stored_or_mailed(env):
    def _boom(text, context=""):
        raise privacy_guard.PrivacyViolation([("vice", "a private habit label")])

    env["monkeypatch"].setattr(privacy_guard, "assert_clean", _boom)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "privacy_hold"
    assert env["ses"].sent == []
    assert _stored_installment(env) is None


def test_a_privacy_held_week_leaves_a_marker_explaining_the_gap(env):
    def _boom(text, context=""):
        raise privacy_guard.PrivacyViolation([("name", "a real public figure")])

    env["monkeypatch"].setattr(privacy_guard, "assert_clean", _boom)
    m.lambda_handler({}, None)
    pending = _pending_marker(env)
    assert pending["week"] == 5
    assert pending["reason"] == "privacy_hold"
    assert "safety check" in pending["display"]


def test_the_privacy_gate_reads_the_title_the_stats_line_and_the_whole_body(env):
    seen = []
    env["monkeypatch"].setattr(privacy_guard, "assert_clean", lambda text, context="": seen.append(text))
    m.lambda_handler({}, None)
    gated = seen[0]
    assert TITLE in gated and STATS_LINE in gated
    assert "quiet arithmetic that only makes sense in retrospect" in gated


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the prompt Elena is actually given
# ══════════════════════════════════════════════════════════════════════════════


def test_the_prompt_carries_this_weeks_data_packet(env):
    m.lambda_handler({}, None)
    assert DATA_PACKET in env["calls"]["ai"][0]["user"]


def test_a_first_installment_is_told_to_establish_the_story(env):
    m.lambda_handler({}, None)
    assert "This is the FIRST installment." in env["calls"]["ai"][0]["user"]


def test_previous_installments_are_replayed_oldest_first_for_continuity(env):
    env["state"]["data"] = _data(
        prev_installments=[
            {"week_number": 4, "title": "The Fourth", "content_markdown": "Fourth week prose."},
            {"week_number": 3, "title": "The Third", "content_markdown": "Third week prose."},
        ]
    )
    user = env["calls"]["ai"]
    m.lambda_handler({}, None)
    body = user[0]["user"]
    assert body.index('Week 3: "The Third"') < body.index('Week 4: "The Fourth"')
    assert "This is the FIRST installment." not in body


def test_recent_theses_are_named_as_angles_not_to_repeat(env):
    env["state"]["data"] = _data(prev_installments=[{"week_number": 4, "title": "The Fourth", "content_markdown": "prose"}])
    m.lambda_handler({}, None)
    user = env["calls"]["ai"][0]["user"]
    assert "THESIS GUARDRAILS" in user
    assert '- "The Fourth"' in user
    assert "MUST be orthogonal" in user


def test_a_long_previous_installment_is_truncated_to_protect_the_token_budget(env):
    env["state"]["data"] = _data(prev_installments=[{"week_number": 4, "title": "Long", "content_markdown": "x" * 5000}])
    m.lambda_handler({}, None)
    assert "[...truncated...]" in env["calls"]["ai"][0]["user"]


def test_elenas_notebook_obligations_are_appended_to_the_prompt(env):
    env["table"].rows.append(_thread("rest-day-fear", "He will not rest.", opened=2, last_ref=5))
    m.lambda_handler({}, None)
    assert "YOUR NOTEBOOK" in env["calls"]["ai"][0]["user"]
    assert "rest-day-fear" in env["calls"]["ai"][0]["user"]


def test_the_platform_insight_ledger_is_framed_as_a_hypothesis_not_gospel(env):
    env["writer"].context = "PLATFORM INSIGHTS: recovery is trailing load."
    m.lambda_handler({}, None)
    user = env["calls"]["ai"][0]["user"]
    assert user.startswith("\n=== FIELD NOTES (AI LAB NOTEBOOK) ===")
    assert "Treat this as a HYPOTHESIS, not gospel." in user
    assert "recovery is trailing load." in user


def test_a_broken_insight_ledger_never_blocks_the_week(env):
    class Exploding(FakeInsightWriter):
        def build_insights_context(self, **kwargs):
            raise RuntimeError("ddb down")

    env["monkeypatch"].setattr(m, "insight_writer", Exploding())
    assert m.lambda_handler({}, None)["statusCode"] == 200


def test_the_whole_life_archive_is_passed_as_its_own_cached_block(env):
    env["table"].rows.append(_installment_row("2026-07-28", 4, title="The Fourth"))
    m.lambda_handler({}, None)
    archive = env["calls"]["ai"][0]["archive"]
    assert archive and "The Fourth" in archive


def test_the_prompt_falls_back_to_the_hardcoded_persona_without_a_board_config(env):
    m.lambda_handler({}, None)
    assert env["calls"]["ai"][0]["system"] == m._FALLBACK_ELENA_PROMPT


def test_a_configured_persona_prompt_is_preferred_over_the_fallback(env):
    env["monkeypatch"].setattr(m, "_build_elena_prompt_from_config", lambda: "CONFIGURED ELENA")
    m.lambda_handler({}, None)
    assert env["calls"]["ai"][0]["system"] == "CONFIGURED ELENA"


def test_the_editorial_guidance_asks_for_a_story_not_a_recap(env):
    m.lambda_handler({}, None)
    user = env["calls"]["ai"][0]["user"]
    assert "you are writing a STORY, not a weekly recap" in user
    assert "DO NOT walk through the week day by day" in user


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the ADR-104 grounding gate
# ══════════════════════════════════════════════════════════════════════════════


def test_a_flagged_draft_is_regenerated_once_and_the_better_draft_is_kept(env):
    findings = {"n": 0}

    def _findings(elena_prompt, user_message, text, archive_text=None):
        # the first draft is flagged, the corrected one is clean.
        # NB the module calls this as (prompt, user_message, text) — the text is
        # the THIRD argument, not the first.
        return [] if "CORRECTED" in text else [{"kind": "ungrounded_number", "detail": "418"}]

    env["monkeypatch"].setattr(m, "installment_grounding_findings", _findings)

    def _ai(system, user, archive_text=None):
        findings["n"] += 1
        env["calls"]["ai"].append({"system": system, "user": user, "archive": archive_text})
        if findings["n"] == 1:
            return RAW_INSTALLMENT
        return RAW_INSTALLMENT.replace("312.4 on Tuesday", "312.4 on Tuesday CORRECTED")

    env["monkeypatch"].setattr(m, "call_anthropic", _ai)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert findings["n"] == 2  # exactly one corrective rewrite, never a loop
    assert "CORRECTED" in _stored_installment(env)["content_markdown"]


def test_a_draft_that_stays_flagged_still_ships_the_best_available_version(env):
    env["monkeypatch"].setattr(m, "installment_grounding_findings", lambda *a, **k: [{"kind": "ungrounded_number", "detail": "418"}])
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _stored_installment(env) is not None


def test_a_grounding_gate_error_fails_open_rather_than_losing_the_week(env):
    def _boom(*a, **k):
        raise RuntimeError("allow-list build failed")

    env["monkeypatch"].setattr(m, "installment_grounding_findings", _boom)
    assert m.lambda_handler({}, None)["statusCode"] == 200


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the #914 presence-acknowledgment gate
# ══════════════════════════════════════════════════════════════════════════════

QUIET_SIGNAL = {
    "pk": f"USER#{m.USER_ID}#SOURCE#engagement_state",
    "sk": "STATE#current",
    "presence_class": "quiet",
    "severity": "alarm",
    "days_since_last_log": 9,
    "quiet_days": 9,
}


def test_a_quiet_stretch_is_named_in_the_prompt_before_elena_writes(env):
    env["table"].rows.append(dict(QUIET_SIGNAL))
    m.lambda_handler({}, None)
    assert "=== PRESENCE / QUIET STRETCH ===" in env["calls"]["ai"][0]["user"]


def test_an_installment_held_by_the_presence_gate_is_not_published(env):
    from content import engagement_core

    env["monkeypatch"].setattr(engagement_core, "presence_ack_required", lambda sig: True)
    env["monkeypatch"].setattr(
        engagement_core, "enforce_presence_acknowledgment", lambda text, sig, regenerate_fn=None: (None, {"detail": "x"})
    )
    env["table"].rows.append(dict(QUIET_SIGNAL))
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 500
    assert "presence gap unacknowledged" in resp["body"]
    assert env["ses"].sent == [] and _stored_installment(env) is None


def test_a_presence_gate_error_fails_open_rather_than_losing_the_week(env):
    from content import engagement_core

    def _boom(*a, **k):
        raise RuntimeError("anchor check exploded")

    env["monkeypatch"].setattr(engagement_core, "presence_ack_required", lambda sig: True)
    env["monkeypatch"].setattr(engagement_core, "enforce_presence_acknowledgment", _boom)
    env["table"].rows.append(dict(QUIET_SIGNAL))
    assert m.lambda_handler({}, None)["statusCode"] == 200


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — PREVIEW_MODE (the default: draft + approval email)
# ══════════════════════════════════════════════════════════════════════════════


def test_preview_mode_stores_a_draft_rather_than_publishing(env):
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    stored = _stored_installment(env)
    assert stored["status"] == "draft"
    assert stored["sk"] == f"DATE#{WEEK_END}"
    assert stored["title"] == TITLE
    assert stored["week_number"] == 5


def test_a_draft_carries_a_single_use_approval_token(env):
    m.lambda_handler({}, None)
    token = _stored_installment(env)["approval_token"]
    assert re.fullmatch(r"[0-9a-f]{64}", token)


def test_two_forced_regenerations_never_reuse_the_same_approval_token(env):
    """Distinct drafts get distinct tokens. #2254 made a plain re-run a no-op, so the
    two-drafts case now requires the explicit {'force': true} regeneration."""
    m.lambda_handler({}, None)
    first = _stored_installment(env)["approval_token"]
    env["table"].puts.clear()
    m.lambda_handler({"force": True}, None)
    second = _stored_installment(env)
    assert second is not None, "a forced regeneration must actually store a new draft"
    assert second["approval_token"] != first


def test_a_draft_carries_the_prebuilt_artifacts_the_approver_will_publish(env):
    m.lambda_handler({}, None)
    stored = _stored_installment(env)
    assert stored["draft_email_html"].startswith("<!DOCTYPE html>") or "<html" in stored["draft_email_html"]
    assert stored["draft_journal_post_key"].startswith("generated/journal/posts/")
    assert json.loads(stored["draft_recap_json"])["as_of"] == WEEK_END


def test_preview_mode_writes_nothing_to_the_public_journal(env):
    m.lambda_handler({}, None)
    assert [p["Key"] for p in env["s3"].puts] == []


def test_the_preview_email_carries_approve_and_request_changes_links(env):
    m.lambda_handler({}, None)
    html = _preview_email(env)
    assert "PREVIEW — Not yet published" in html
    assert f"?date={WEEK_END}" in html
    assert "action=approve" in html and "action=request_changes" in html


def test_the_preview_email_carries_the_week_and_the_title(env):
    m.lambda_handler({}, None)
    assert f"Week 5: &ldquo;{TITLE}&rdquo;" in _preview_email(env)


def test_the_preview_email_goes_only_to_the_configured_recipient(env):
    m.lambda_handler({}, None)
    assert len(env["ses"].sent) == 1
    assert env["ses"].sent[0]["Destination"]["ToAddresses"] == [m.RECIPIENT]


def test_the_preview_run_does_not_advance_elenas_persistent_memory(env):
    """A draft is not a publication — her notebook must not move until approval."""
    m.lambda_handler({}, None)
    assert env["lambda_client"].invocations == []


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — immediate-publish mode
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def publish_env(env):
    env["monkeypatch"].setattr(m, "PREVIEW_MODE", False)
    return env


def test_publishing_stores_the_installment_as_published(publish_env):
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _stored_installment(publish_env)["status"] == "published"


def test_publishing_mails_the_installment_with_the_week_and_title_in_the_subject(publish_env):
    m.lambda_handler({}, None)
    sent = publish_env["ses"].sent[0]
    assert sent["Content"]["Simple"]["Subject"]["Data"] == f'The Measured Life — Week 5: "{TITLE}"'
    assert sent["FromEmailAddress"] == m.SENDER


def test_the_mailed_installment_carries_elenas_prose(publish_env):
    m.lambda_handler({}, None)
    html = publish_env["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "quiet arithmetic" in html
    assert "https://averagejoematt.com/story/chronicle/" in html


def test_publishing_writes_the_post_and_the_listing_manifest(publish_env):
    m.lambda_handler({}, None)
    keys = [p["Key"] for p in publish_env["s3"].puts]
    assert any(k.startswith("generated/journal/posts/") and k.endswith("index.html") for k in keys)
    assert "generated/journal/posts.json" in keys


def test_publishing_advances_elenas_persistent_memory(publish_env):
    m.lambda_handler({}, None)
    assert json.loads(publish_env["lambda_client"].invocations[0]["Payload"]) == {"date": WEEK_END}


def test_publishing_commits_the_recap_it_generated(publish_env):
    written = []
    publish_env["monkeypatch"].setattr(m, "_write_recap", lambda recap, date_str: written.append(date_str))
    m.lambda_handler({}, None)
    assert written == [WEEK_END]


def test_a_journal_publish_failure_never_loses_the_email(publish_env):
    publish_env["monkeypatch"].setattr(m, "publish_to_journal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("s3 down")))
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(publish_env["ses"].sent) == 1


def test_a_published_week_is_recorded_in_the_insight_ledger(publish_env):
    m.lambda_handler({}, None)
    written = publish_env["writer"].written
    assert len(written) == 1
    assert written[0]["digest_type"] == "chronicle"
    assert written[0]["tags"] == ["chronicle", "narrative", "week_5"]
    assert written[0]["date"] == WEEK_END


def test_a_published_week_is_logged_for_the_status_page(publish_env):
    m.lambda_handler({}, None)
    assert [p for p in publish_env["table"].puts if "email_log" in p.get("pk", "")]


def test_a_board_interview_is_flagged_on_the_stored_installment(publish_env):
    publish_env["state"]["ai"] = RAW_INSTALLMENT.replace("What happens next", "> Dr. Park was blunt about it.\n\nWhat happens next")
    m.lambda_handler({}, None)
    assert _stored_installment(publish_env)["has_board_interview"] is True


def test_margarets_editors_note_is_not_mistaken_for_a_board_interview(publish_env):
    publish_env["state"]["ai"] = RAW_INSTALLMENT.replace(
        "What happens next", "> Editor's note: one claim was held this week.\n\nWhat happens next"
    )
    m.lambda_handler({}, None)
    assert _stored_installment(publish_env)["has_board_interview"] is False


def test_a_quiet_week_with_no_interview_is_flagged_as_such(publish_env):
    m.lambda_handler({}, None)
    assert _stored_installment(publish_env)["has_board_interview"] is False


def test_an_installment_query_failure_still_publishes_this_week(publish_env):
    """The listing query is context; losing it must not lose the installment."""
    publish_env["table"].query_error = RuntimeError("ddb down")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(publish_env["ses"].sent) == 1


def test_the_share_kit_is_written_alongside_the_published_post(publish_env):
    m.lambda_handler({}, None)
    kits = [p for p in publish_env["s3"].puts if "share" in p["Key"] or p["Key"].endswith("kit.json")]
    assert kits, [p["Key"] for p in publish_env["s3"].puts]


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — idempotency, dry-run, and the status record
# ══════════════════════════════════════════════════════════════════════════════


def test_a_second_run_on_the_same_week_does_not_regenerate_or_resend(env):
    """#2254 (was a tranche-3 xfail): the generator's half of the #2112 idempotency
    class. A retry / manual re-invoke / at-least-once redelivery must cost no Bedrock
    call and raise no second email."""
    m.lambda_handler({}, None)
    m.lambda_handler({}, None)
    assert len(env["calls"]["ai"]) == 1
    assert len(env["ses"].sent) == 1


def test_a_second_run_reports_the_week_it_refused_to_regenerate(env):
    m.lambda_handler({}, None)
    body = json.loads(m.lambda_handler({}, None)["body"])
    assert body["status"] == "already_generated"
    assert body["date"] == WEEK_END
    assert body["existing_status"] == "draft"


def test_a_second_run_leaves_the_stored_draft_and_its_approval_token_untouched(env):
    """The reader-facing harm this gate prevents: a re-run used to mint a fresh
    approval_token over the draft, silently 403-ing the approve link already in
    Matthew's inbox, and to replace content he may have already approved."""
    m.lambda_handler({}, None)
    first = dict(_stored_installment(env))
    env["table"].puts.clear()
    m.lambda_handler({}, None)
    assert env["table"].puts == []  # nothing written at all — not the row, not an email_log
    row = env["table"].get_item(Key={"pk": first["pk"], "sk": first["sk"]})["Item"]
    assert row["approval_token"] == first["approval_token"]
    assert row["content_markdown"] == first["content_markdown"]


def test_an_already_published_week_is_never_regenerated_on_the_publish_route(publish_env):
    """Not preview-only: the immediate-publish route would otherwise overwrite a live
    post and re-mail the installment."""
    m.lambda_handler({}, None)
    assert _stored_installment(publish_env)["status"] == "published"
    resp = m.lambda_handler({}, None)
    assert json.loads(resp["body"])["existing_status"] == "published"
    assert len(publish_env["calls"]["ai"]) == 1
    assert len(publish_env["ses"].sent) == 1


def test_a_week_whose_changes_were_requested_is_regenerated_without_force(env):
    """chronicle_approve tells Matthew to "Re-run the wednesday-chronicle Lambda" after
    Request Changes, so changes_requested must NOT be protected — the gate would
    otherwise deadlock the one path that exists to fix a rejected week."""
    env["table"].rows.append(
        _installment_row(WEEK_END, 5, title="The rejected draft", status="changes_requested"),
    )
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _stored_installment(env)["status"] == "draft"
    assert len(env["calls"]["ai"]) == 1


def test_a_crashed_runs_cache_never_serves_a_requested_regeneration(env):
    """#2669: the cache fills the void a CRASH left (no DATE# row). A
    changes_requested week regenerates without force by design — reusing the
    cached text would re-store the exact draft Matthew rejected."""
    env["table"].rows.append(_installment_row(WEEK_END, 5, title="The rejected draft", status="changes_requested"))
    env["table"].rows.append(
        {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"RAWCACHE#{WEEK_END}", "source": "chronicle", "raw_text": RAW_INSTALLMENT}
    )
    m.lambda_handler({}, None)
    assert len(env["calls"]["ai"]) >= 1, "the regeneration must be FRESH — the cache may not satisfy it"


def test_the_cache_is_reused_when_a_crash_left_no_installment_row(env):
    """#2669: the crash case — the pipeline finished, the persist never ran.
    A retry must reuse the cached text and pay for zero model calls."""
    env["table"].rows.append(
        {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"RAWCACHE#{WEEK_END}", "source": "chronicle", "raw_text": RAW_INSTALLMENT}
    )
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert env["calls"]["ai"] == [], "a cache hit must cost zero generations"
    stored = _stored_installment(env)
    assert stored is not None and TITLE in str(stored.get("title", "")), "the cached text is what gets stored"


def test_force_regenerates_a_week_that_already_has_a_draft(env):
    m.lambda_handler({}, None)
    env["table"].puts.clear()
    m.lambda_handler({"force": True}, None)
    assert _stored_installment(env) is not None
    assert len(env["calls"]["ai"]) == 2


def test_an_idempotency_read_failure_does_not_stop_the_week_from_being_written(env):
    """Fail-open on the read: a DDB blip must not silently skip the week. The
    conditional put is the fail-closed backstop in that case."""
    env["table"].get_error = RuntimeError("ddb down")
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert _stored_installment(env)["status"] == "draft"


def test_a_refused_conditional_put_suppresses_the_preview_email(env):
    """The last line of defence: if the row is protected at WRITE time (a racing
    invoke landed between the idempotency read and the put), the approval_token was
    never persisted — mailing its approve link would hand Matthew a button that 403s."""

    class _Refusing(Exception):
        pass

    _Refusing.__name__ = "ConditionalCheckFailedException"

    def _put(Item=None, **kwargs):
        if Item.get("source") == "chronicle" and "ConditionExpression" in kwargs:
            raise _Refusing("The conditional request failed")
        return FakeTable.put_item(env["table"], Item=Item, **kwargs)

    env["table"].put_item = _put
    resp = m.lambda_handler({}, None)
    assert json.loads(resp["body"])["status"] == "already_generated"
    assert env["ses"].sent == []


def test_the_installment_put_is_conditional_unless_overwrite_is_explicit(env):
    """Mutation proof for the guard itself: the put carries a ConditionExpression that
    names both protected statuses, and only `force` drops it."""
    m.lambda_handler({}, None)
    kwargs = [
        k
        for k in env["table"].put_kwargs
        if (k.get("Item") or {}).get("source") == "chronicle" and str((k.get("Item") or {}).get("sk", "")).startswith("DATE#")
    ][0]
    assert "ConditionExpression" in kwargs
    assert set(kwargs["ExpressionAttributeValues"].values()) == set(m._store.PROTECTED_STATUSES)
    env["table"].put_kwargs.clear()
    m.lambda_handler({"force": True}, None)
    forced = [
        k
        for k in env["table"].put_kwargs
        if (k.get("Item") or {}).get("source") == "chronicle" and str((k.get("Item") or {}).get("sk", "")).startswith("DATE#")
    ][0]
    assert "ConditionExpression" not in forced


def test_a_dry_run_invocation_builds_the_week_without_mailing_it(env):
    """#2221 (was a tranche-3 xfail, #2111 class): {"dry_run": true} rehearses the week
    and writes nothing — no row, no S3, no pending marker, no email_log, no mail."""
    resp = m.lambda_handler({"dry_run": True}, None)
    assert resp["statusCode"] == 200
    assert env["ses"].sent == []


def _email_log_pks(env):
    return [p.get("pk", "") for p in env["table"].puts if "email_log" in p.get("pk", "")]


def test_a_draft_that_was_never_mailed_is_not_logged_as_a_successful_send(env):
    """#2254 (was a tranche-3 xfail). site_api_status reads NOTHING but the presence of
    a row in email_log#wednesday_chronicle (_last_sync/_uptime_90d both project `sk`
    only), so a status field on that same partition would be invisible — the row itself
    is the claim. A preview must therefore not land there at all."""
    m.lambda_handler({}, None)
    assert "USER#matthew#SOURCE#email_log#wednesday_chronicle" not in _email_log_pks(env)


def test_the_preview_run_is_still_logged_under_its_own_partition(env):
    """Suppressing the false claim must not lose the observability: the preview run is
    recorded, just where it cannot be read as a reader-facing send."""
    m.lambda_handler({}, None)
    assert "USER#matthew#SOURCE#email_log#wednesday_chronicle_preview" in _email_log_pks(env)


def test_the_publish_route_still_logs_a_real_send(publish_env):
    m.lambda_handler({}, None)
    assert "USER#matthew#SOURCE#email_log#wednesday_chronicle" in _email_log_pks(publish_env)


def _is_listing_query(kwargs):
    """The handler's all-installments listing read, told apart from the #1385 whole-life
    archive read of the SAME partition (which carries an explicit Limit=500)."""
    eav = kwargs.get("ExpressionAttributeValues") or {}
    return (
        isinstance(eav, dict)
        and str(eav.get(":pk", "")).endswith("SOURCE#chronicle")
        and eav.get(":prefix") == "DATE#"
        and "Limit" not in kwargs
    )


def _paging_table(publish_env, pages):
    """Replace the chronicle listing query with a scripted multi-page response.

    Only the installment listing is paged; every other read in the handler still goes to
    the real FakeTable, so the handler runs end to end.
    """
    seen = []
    real_query = publish_env["table"].query

    def _paged(**kwargs):
        if not _is_listing_query(kwargs):
            return real_query(**kwargs)
        seen.append(kwargs)
        idx = len(seen) - 1
        out = {"Items": pages[idx]}
        if idx + 1 < len(pages):
            out["LastEvaluatedKey"] = {"sk": pages[idx][-1]["sk"]}
        return out

    publish_env["table"].query = _paged
    return seen


def test_the_installment_listing_is_read_across_every_page(publish_env):
    """#2254 (was a tranche-3 xfail)."""
    seen = _paging_table(publish_env, [[_installment_row("2026-07-28", 4)], [_installment_row("2026-07-21", 3)]])
    m.lambda_handler({}, None)
    assert any("ExclusiveStartKey" in q for q in seen)


def test_no_post_beyond_the_first_page_is_dropped_from_the_public_manifest(publish_env):
    """The consequence the pagination exists to prevent: publish_to_journal REGENERATES
    generated/journal/posts.json wholesale from this list, so anything the query silently
    truncated is DELETED from the public listing — and, because the week-NN sequence is
    the index into this same list, the survivors are renumbered too."""
    _paging_table(
        publish_env,
        [
            [_installment_row("2026-07-28", 4, title="Page one post")],
            [_installment_row("2026-07-21", 3, title="Page two post")],
            [_installment_row("2026-07-14", 2, title="Page three post")],
        ],
    )
    m.lambda_handler({}, None)
    manifest = None
    for put in publish_env["s3"].puts:
        if put["Key"] == "generated/journal/posts.json":
            manifest = json.loads(put["Body"])
    assert manifest is not None
    titles = [p["title"] for p in manifest["posts"]]
    assert "Page three post" in titles, f"oldest page dropped from the public manifest: {titles}"
    assert {"Page one post", "Page two post"} <= set(titles)
    # The new week is the 4th-oldest of 4 -> sequence 4; a dropped page would shift it.
    assert [p["sequence"] for p in manifest["posts"] if p["title"] == TITLE] == [4]


def test_the_pagination_loop_stops_at_its_page_cap(publish_env):
    """A malformed/never-terminating LastEvaluatedKey must not spin the Lambda for its
    whole timeout."""
    calls = []

    real_query = publish_env["table"].query

    def _never_ends(**kwargs):
        if not _is_listing_query(kwargs):
            return real_query(**kwargs)
        calls.append(kwargs)
        return {"Items": [], "LastEvaluatedKey": {"sk": "DATE#2026-01-01"}}

    publish_env["table"].query = _never_ends
    m.lambda_handler({}, None)
    assert len(calls) == m._MAX_INSTALLMENT_PAGES


def test_an_unmeasurable_confidence_is_stored_as_unknown_not_as_medium(env):
    """#2221 (was a tranche-3 xfail, ADR-105): an unmeasurable confidence is stored as
    UNKNOWN. "MEDIUM" asserted a middling verdict over a journey nobody measured."""
    from common import digest_utils

    env["monkeypatch"].setattr(digest_utils, "compute_confidence", lambda **kw: (_ for _ in ()).throw(RuntimeError("no")))
    env["monkeypatch"].setattr(m, "compute_confidence", lambda **kw: (_ for _ in ()).throw(RuntimeError("no")))
    m.lambda_handler({}, None)
    assert _stored_installment(env)["_confidence_level"] != "MEDIUM"


def test_the_stored_installment_records_the_confidence_it_computed(env):
    m.lambda_handler({}, None)
    stored = _stored_installment(env)
    # journey_start 2026-08-03, week end 2026-08-04 -> 1 day of data -> LOW (<14d)
    assert stored["_confidence_level"] == "LOW"


def test_a_long_journey_earns_a_higher_confidence_than_a_new_one(env):
    env["state"]["data"] = _data(profile={"journey_start_date": "2026-01-01", "goal_weight_lbs": 220})
    m.lambda_handler({}, None)
    assert _stored_installment(env)["_confidence_level"] != "LOW"


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler — the fail-soft guarantees
#
# Everything in this section is context or convenience. None of it may cost the
# week: an installment that was generated, grounded and privacy-cleared must ship.
# ══════════════════════════════════════════════════════════════════════════════


def test_a_failed_archive_build_never_loses_the_week(env):
    from health import whole_life_context

    env["monkeypatch"].setattr(
        whole_life_context, "format_full_archive", lambda items: (_ for _ in ()).throw(RuntimeError("archive exploded"))
    )
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert env["calls"]["ai"][0]["archive"] == ""


def test_a_failed_presence_signal_read_never_loses_the_week(env):
    env["monkeypatch"].setattr(m, "_load_engagement_signal", lambda: (_ for _ in ()).throw(RuntimeError("ddb down")))
    assert m.lambda_handler({}, None)["statusCode"] == 200


def test_a_failed_envelope_schema_check_never_loses_the_week(env):
    from content import chronicle_schema

    env["monkeypatch"].setattr(chronicle_schema, "parse_stats_line", lambda s: (_ for _ in ()).throw(RuntimeError("bad line")))
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert _stored_installment(env) is not None


def test_a_validator_warning_is_logged_but_still_ships_the_week(env):
    from ai import ai_output_validator as aiv

    result = aiv.AIValidationResult(original_text=RAW_INSTALLMENT, output_type=aiv.AIOutputType.CHRONICLE, warnings=["generic phrasing"])
    env["monkeypatch"].setattr(m, "validate_ai_output", lambda *a, **k: result)
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(env["ses"].sent) == 1


def test_a_share_kit_that_fails_the_privacy_gate_is_dropped_not_published(env):
    """The kit only recombines already-gated fields, but the re-assertion is
    defence in depth: if it fires the week still ships, without the kit."""
    calls = {"n": 0}
    real = privacy_guard.assert_clean

    def _gate(text, context=""):
        calls["n"] += 1
        if "share kit" in context:
            raise privacy_guard.PrivacyViolation([("name", "a real public figure")])
        return real(text, context=context)

    env["monkeypatch"].setattr(privacy_guard, "assert_clean", _gate)
    env["monkeypatch"].setattr(m, "PREVIEW_MODE", False)
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(env["ses"].sent) == 1
    assert not [p for p in env["s3"].puts if p["Key"].endswith("kit.json")]


def test_a_failed_share_kit_build_never_loses_the_week(env):
    from content import chronicle_share_kit

    env["monkeypatch"].setattr(chronicle_share_kit, "build_kit", lambda **kw: (_ for _ in ()).throw(RuntimeError("kit exploded")))
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(env["ses"].sent) == 1


def test_a_failed_share_kit_write_never_loses_the_email(publish_env):
    def _put(Bucket=None, Key=None, Body=None, **kwargs):
        if Key.endswith("kit.json"):
            raise RuntimeError("s3 down")
        publish_env["s3"].puts.append({"Key": Key, "Body": Body})
        return {}

    publish_env["s3"].put_object = _put
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(publish_env["ses"].sent) == 1


def test_a_failed_draft_artifact_build_still_stores_the_draft(env):
    env["monkeypatch"].setattr(m, "publish_to_journal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("render exploded")))
    resp = m.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    stored = _stored_installment(env)
    assert stored["status"] == "draft"
    assert "draft_journal_post_html" not in stored


def test_a_failed_insight_write_never_loses_the_week(env):
    class Exploding(FakeInsightWriter):
        def write_insight(self, **kwargs):
            raise RuntimeError("ddb down")

    env["monkeypatch"].setattr(m, "insight_writer", Exploding())
    assert m.lambda_handler({}, None)["statusCode"] == 200
    assert len(env["ses"].sent) == 1


def test_a_fired_grounding_gate_retains_the_draft_and_final_pair_as_eval_data(env):
    """#812/#744: a fired gate is labelled eval data — the pair must be kept."""
    env["monkeypatch"].setattr(m, "installment_grounding_findings", lambda *a, **k: [{"kind": "ungrounded_number", "detail": "418"}])
    m.lambda_handler({}, None)
    assert env["retained"], "the flagged draft/final pair was not retained"
    args, kwargs = env["retained"][0]
    assert args[0] == "chronicle"
    assert kwargs["extra"] == {"week_number": 5}


def test_a_failed_retention_write_never_loses_the_week(env):
    env["monkeypatch"].setattr(m, "installment_grounding_findings", lambda *a, **k: [{"kind": "ungrounded_number", "detail": "418"}])
    env["monkeypatch"].setattr(eval_retention, "retain", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ddb down")))
    assert m.lambda_handler({}, None)["statusCode"] == 200


def test_decimal_values_from_dynamodb_never_reach_the_prompt_as_decimals(env):
    env["table"].rows.append(dict(_installment_row("2026-07-28", Decimal("4")), content_markdown="Fourth week prose."))
    m.lambda_handler({}, None)
    assert "Decimal(" not in (env["calls"]["ai"][0]["archive"] or "")
