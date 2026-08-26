"""tests/test_mcp_tools_lifestyle_behavior.py — behavioral contracts for the MCP
lifestyle tools served by ``mcp/tools_lifestyle.py``:

    save_insight / get_insights / update_insight_outcome     (the coaching log)
    create_experiment / list_experiments /
      get_experiment_results / end_experiment                (the n-of-1 engine)
    get_social_connection_trend                              (PERMA / connection)
    get_field_notes / log_field_note_response                (the lab notebook)
    log_evening_intake / get_intake_response                 (PRIVATE, #1405)

plus the two module-private views this file reaches through their real
dispatchers rather than by calling the private function:

    get_mood(view="state_of_mind")   → _get_state_of_mind_trend
    get_daily_metrics(view=...)      → _get_movement_score  (dispatch only; the
                                       DI-1 contracts already live in
                                       tests/test_di1_movement_integrity.py and
                                       are deliberately not duplicated here)

The whole ``mcp/tools_*`` family had zero dedicated behavioural coverage before
this file (#1658 tranche 3). These are the tools Matthew drives from Claude
Desktop and claude.ai, and their output is read as fact.

The contracts pinned here:

  * ADR-104 honest numbers — absence is ABSENT, never a factual 0 or a neutral
    default; a "total" means the total.
  * ADR-105 rigor — an average / correlation / trend ships with its n, and a
    causal-sounding label is earned, not asserted from a bare r.
  * Reader/writer field-name agreement — EVERY DynamoDB field these tools read is
    checked against a real writer under ``lambdas/``. §5 is the audit; it found
    six metrics that can never be populated.
  * #1917 window-name honesty — a field named for an N-day window spans a real N
    days, and a "before vs during" comparison compares equal-length windows.
  * Privacy — the #1405 intake ledger is Matthew-private and must never widen.
  * ADR-058 phase filtering — ``insights``, ``experiments`` and ``field_notes``
    are EXPERIMENT_SCOPED partitions (``lambdas/experiment/phase_taxonomy.py``),
    so a cycle reset must not leave wiped rows reading as live.
  * Registry parity — the SET of tools this file must exercise is DERIVED from
    ``mcp/registry.py``'s ``TOOLS`` dict, never restated ("guard the SET").

Everything is driven through the real registered entry point with the declared
arguments, a frozen clock, and hand-rolled bounded fakes (plus
``tests/fakes.py::FakeDdbTable`` where the shape fits). No MagicMock inside a
loop-shaped read, no AWS, no network — ``_fetch_weather_range`` is the only
urllib caller in the module and nothing here reaches it.

Arithmetic expectations are hand-derived and written as literals with the
derivation in a comment — never "whatever the code returned".

Production defects found while writing this file are marked xfail and NOT fixed
here; each reason names module:line, the function, what it does, what it should
do, and who it is wrong for.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

from mcp import (
    tools_lifestyle as tl,  # noqa: E402
    tools_social_connection as tsc,  # noqa: E402  (#2221 — the connection tool's own module)
)
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 8, 8, 17, 30, 0, tzinfo=timezone.utc)  # 10:30 PT — same PT/UTC calendar day
TODAY = "2026-08-08"

INSIGHTS_PK = "USER#matthew#SOURCE#insights"
EXPERIMENTS_PK = "USER#matthew#SOURCE#experiments"
FIELD_NOTES_PK = "USER#matthew#SOURCE#field_notes"
PRIVATE_INTAKE_PK = "USER#matthew#SOURCE#private_intake"


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()``.

    A subclass, not a Mock, because the module calls ``strptime``,
    ``fromisocalendar``, ``isocalendar`` and ``timedelta`` arithmetic on the same
    name. ``now(None)`` deliberately returns the NAIVE value — several call sites
    in this module use bare ``datetime.now()`` (see §8).
    """

    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return NOW.replace(tzinfo=None)


def _d(offset_days: int, anchor: str = TODAY) -> str:
    return (datetime.strptime(anchor, "%Y-%m-%d") + timedelta(days=offset_days)).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


class FakeSourceReader:
    """Stand-in for ``mcp.core.query_source``.

    Filters to the requested inclusive ``[start, end]`` window (the real one
    issues an ``sk BETWEEN``), returns ``[]`` for an unknown source and for
    ``start > end``, hands back a fresh copy of each row, and records every call
    so a test can assert which partitions were — and were NOT — read.
    """

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple] = []

    def __call__(self, source, start_date, end_date, lean=False, include_pilot=False):
        self.calls.append((source, start_date, end_date, include_pilot))
        if start_date > end_date:
            return []
        out = []
        for row in self.data.get(source, []):
            date = row.get("date") or str(row.get("sk", "")).replace("DATE#", "")
            if start_date <= date <= end_date:
                out.append(dict(row))
        return out

    def window_for(self, source: str) -> tuple[str, str]:
        for src, start, end, _pilot in self.calls:
            if src == source:
                return start, end
        raise AssertionError(f"{source} was never queried; queried: {sorted({c[0] for c in self.calls})}")


class FakeS3:
    """Bounded S3 double: a dict of key → bytes, a `puts` log, and a NoSuchKey
    exception class shaped like botocore's so the module's `except
    s3_client.exceptions.NoSuchKey` path is reachable."""

    class _NoSuchKey(Exception):
        pass

    class _Exceptions:
        NoSuchKey = None  # bound in __init__

    def __init__(self, objects=None, put_raises: Exception | None = None):
        self.objects = dict(objects or {})
        self.puts: list[dict] = []
        self.put_raises = put_raises
        self.exceptions = FakeS3._Exceptions()
        self.exceptions.NoSuchKey = FakeS3._NoSuchKey

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeS3._NoSuchKey(Key)
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        if self.put_raises is not None:
            raise self.put_raises
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}


class _Body:
    def __init__(self, payload):
        self._payload = payload if isinstance(payload, (bytes, str)) else payload

    def read(self):
        return self._payload


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(tl, "datetime", _FrozenDatetime)
    monkeypatch.setattr(tsc, "datetime", _FrozenDatetime)


@pytest.fixture
def table(monkeypatch):
    def _install(rows=None, **kw):
        t = FakeDdbTable(rows=rows or [], **kw)
        monkeypatch.setattr(tl, "table", t)
        return t

    return _install


@pytest.fixture
def sources(monkeypatch):
    def _install(**by_source):
        reader = FakeSourceReader(**by_source)
        monkeypatch.setattr(tl, "query_source", reader)
        # #2221: get_social_connection_trend lives in its own module now — patch the
        # name IT resolves, not only tools_lifestyle's (a re-export is not a patch point).
        monkeypatch.setattr(tsc, "query_source", reader)
        return reader

    return _install


@pytest.fixture
def s3(monkeypatch):
    def _install(objects=None, put_raises=None):
        client = FakeS3(objects=objects, put_raises=put_raises)
        monkeypatch.setattr(tl, "s3_client", client)
        return client

    return _install


def call(tool_name: str, args: dict):
    """Drive a tool through its REAL registered entry point."""
    return TOOLS[tool_name]["fn"](args)


# ═══════════════════════════════════════════════════════════════════════════════
# §1 — Registry parity: the SET under test is derived, never restated
# ═══════════════════════════════════════════════════════════════════════════════

# #2221 lifted get_social_connection_trend into its own module; the SET is still
# DERIVED from the registry, now over both modules this file owns.
_OWNED_MODULES = {"mcp.tools_lifestyle", "mcp.tools_social_connection"}
LIFESTYLE_TOOL_NAMES = {name for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") in _OWNED_MODULES}

EXERCISED_HERE = {
    "create_experiment",
    "end_experiment",
    "get_experiment_results",
    "get_field_notes",
    "get_insights",
    "get_intake_response",
    "get_social_connection_trend",
    "list_experiments",
    "log_evening_intake",
    "log_field_note_response",
    "save_insight",
    "update_insight_outcome",
}


def test_registry_is_the_source_of_truth_for_which_lifestyle_tools_exist():
    assert LIFESTYLE_TOOL_NAMES == EXERCISED_HERE, (
        f"{sorted(_OWNED_MODULES)} now export {sorted(LIFESTYLE_TOOL_NAMES)} through the registry; "
        f"this behavioural file only exercises {sorted(EXERCISED_HERE)}."
    )


def test_module_private_views_are_reachable_only_through_their_dispatchers():
    """Two of this module's views are not registered under their own names — they
    are dispatched from sibling modules. Derive that wiring rather than assuming
    it, so a rename in either place is caught here."""
    from mcp import tools_health, tools_journal

    assert TOOLS["get_daily_metrics"]["fn"] is tools_health.tool_get_daily_metrics
    assert TOOLS["get_mood"]["fn"] is tools_journal.tool_get_mood
    assert "movement" in TOOLS["get_daily_metrics"]["schema"]["inputSchema"]["properties"]["view"]["enum"]
    assert "state_of_mind" in TOOLS["get_mood"]["schema"]["inputSchema"]["properties"]["view"]["enum"]


# ═══════════════════════════════════════════════════════════════════════════════
# §2 — The coaching log: save / get / update
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_insight_writes_the_declared_key_shape(table):
    t = table()
    out = call("save_insight", {"text": "Cut caffeine after 10am", "tags": ["sleep"], "source": "chat"})
    assert out["saved"] is True
    assert out["insight_id"] == "2026-08-08T17:30:00"  # frozen UTC clock, second precision
    # #3114 put the replay claim on the wire first (its own partition), so select the
    # insight row by its pk rather than by position.
    item = next(p for p in t.puts if p["pk"] == INSIGHTS_PK)
    assert item["pk"] == INSIGHTS_PK and item["sk"] == "INSIGHT#2026-08-08T17:30:00"
    assert item["status"] == "open" and item["date_saved"] == TODAY and item["outcome_notes"] == ""


def test_save_insight_requires_text(table):
    table()
    with pytest.raises(ValueError, match="text is required"):
        call("save_insight", {"text": "   "})


def test_save_insight_truncates_the_preview_with_an_ellipsis(table):
    table()
    out = call("save_insight", {"text": "x" * 200})
    assert out["text_preview"] == "x" * 120 + "…"


def test_save_insight_stamps_no_phase_so_it_survives_the_phase_filter(table):
    """OBSERVED (ADR-058): `insights` is an EXPERIMENT_SCOPED partition, but the
    MCP writer stamps no `phase` attribute. The read-side filter admits rows with
    no phase (`attribute_not_exists`), which is what makes the round trip work —
    and also what makes an MCP-written insight invisible to a cycle wipe's
    phase-tag pass until the tagger back-fills it."""
    from experiment.phase_taxonomy import SCOPED_SOURCES

    assert "insights" in SCOPED_SOURCES  # derived, not restated
    t = table()
    call("save_insight", {"text": "note"})
    assert "phase" not in t.puts[0]


def test_get_insights_computes_days_open_and_the_stale_flag_off_a_frozen_clock(table):
    """15 days open + status open ⇒ stale (the flag is strictly > 14). 14 days
    open ⇒ not stale. Both derived from the frozen 2026-08-08 clock."""
    table(
        rows=[
            {"pk": INSIGHTS_PK, "sk": "INSIGHT#a", "insight_id": "a", "date_saved": _d(-15), "status": "open", "text": "old"},
            {"pk": INSIGHTS_PK, "sk": "INSIGHT#b", "insight_id": "b", "date_saved": _d(-14), "status": "open", "text": "edge"},
            {"pk": INSIGHTS_PK, "sk": "INSIGHT#c", "insight_id": "c", "date_saved": _d(-30), "status": "resolved", "text": "done"},
        ]
    )
    out = call("get_insights", {})
    by_id = {r["insight_id"]: r for r in out["insights"]}
    assert by_id["a"]["days_open"] == 15 and by_id["a"]["stale"] is True
    assert by_id["b"]["days_open"] == 14 and by_id["b"]["stale"] is False
    assert by_id["c"]["days_open"] == 30 and by_id["c"]["stale"] is False  # resolved is never stale
    assert out["stale_count"] == 1


def test_get_insights_unparseable_date_yields_none_days_open_not_zero(table):
    """ADR-104: a corrupt date_saved must read as unknown, never as "saved today"."""
    table(rows=[{"pk": INSIGHTS_PK, "sk": "INSIGHT#x", "insight_id": "x", "date_saved": "not-a-date", "status": "open"}])
    row = call("get_insights", {})["insights"][0]
    assert row["days_open"] is None and row["stale"] is False


def test_get_insights_status_filter_narrows_the_result(table):
    table(
        rows=[
            {"pk": INSIGHTS_PK, "sk": "INSIGHT#a", "insight_id": "a", "date_saved": TODAY, "status": "open"},
            {"pk": INSIGHTS_PK, "sk": "INSIGHT#b", "insight_id": "b", "date_saved": TODAY, "status": "acted"},
        ]
    )
    out = call("get_insights", {"status_filter": "acted"})
    assert out["total"] == 1 and out["status_filter"] == "acted"
    assert out["insights"][0]["insight_id"] == "b"


def test_get_insights_total_is_the_corpus_size_and_the_page_says_it_is_a_page(table):
    """FIXED (#2221, ADR-104): `total` used to be len(results) with results cut at
    `limit`, so 120 insights read as "total 50" — the number Matthew gets when he
    asks how many are still open. `total` is now the corpus, `returned` the page,
    and `truncated` says the two differ."""
    rows = [
        {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{i:03d}", "insight_id": f"{i:03d}", "date_saved": TODAY, "status": "open"} for i in range(120)
    ]
    table(rows=rows)
    out = call("get_insights", {})
    assert out["total"] == 120
    assert out["returned"] == 50 == len(out["insights"])
    assert out["truncated"] is True
    assert out["scan_exhausted"] is True


def test_get_insights_follows_the_pagination_cursor(table):
    """The read used to issue ONE query and never follow LastEvaluatedKey, so the
    corpus count was capped by whatever survived a single page — and DynamoDB
    applies `Limit` to items READ, BEFORE the ADR-058 phase FilterExpression, so a
    partition carrying pilot rows yields fewer still. Two pages, 3 rows, no cut."""
    page1 = [{"pk": INSIGHTS_PK, "sk": "INSIGHT#003", "insight_id": "003", "date_saved": TODAY, "status": "open"}]
    page2 = [{"pk": INSIGHTS_PK, "sk": f"INSIGHT#{i:03d}", "insight_id": f"{i:03d}", "date_saved": TODAY, "status": "open"} for i in (2, 1)]
    pages = [{"Items": page1, "LastEvaluatedKey": {"pk": INSIGHTS_PK, "sk": "INSIGHT#003"}}, {"Items": page2}]
    t = FakeDdbTable(rows=[], query_hook=lambda _t, **kw: pages[len(_t.query_calls) - 1])
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tl, "table", t)
    try:
        out = call("get_insights", {})
    finally:
        monkey.undo()
    assert out["total"] == 3 and out["truncated"] is False
    assert [i["insight_id"] for i in out["insights"]] == ["003", "002", "001"]
    assert t.query_calls[1]["ExclusiveStartKey"] == {"pk": INSIGHTS_PK, "sk": "INSIGHT#003"}
    # The phase filter rides on EVERY page, not just the first (ADR-058).
    assert all("#phase" in kw["FilterExpression"] for kw in t.query_calls)


def test_get_insights_read_is_phase_filtered(table):
    """ADR-058: the insights partition is EXPERIMENT_SCOPED, so the read must
    carry the phase filter — otherwise a previous cycle's wiped insights read as
    live coaching items."""
    t = table(rows=[])
    call("get_insights", {})
    kwargs = t.query_calls[0]
    assert "#phase" in kwargs["FilterExpression"]
    assert kwargs["ExpressionAttributeValues"][":phase_experiment"] == "experiment"
    assert kwargs["ScanIndexForward"] is False  # newest-first, as documented


def test_update_insight_outcome_round_trips_through_the_saved_id(table):
    t = table()
    saved = call("save_insight", {"text": "Cut caffeine after 10am"})
    out = call(
        "update_insight_outcome",
        {"insight_id": saved["insight_id"], "outcome_notes": "Worked — deep sleep up", "status": "resolved"},
    )
    assert out["updated"] is True and out["status"] == "resolved"
    assert out["text_preview"] == "Cut caffeine after 10am"
    update = t.updates[0]
    assert update["Key"] == {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{saved['insight_id']}"}
    assert update["ExpressionAttributeValues"][":d"] == TODAY


def test_update_insight_outcome_rejects_an_unknown_status(table):
    table()
    with pytest.raises(ValueError, match="status must be one of"):
        call("update_insight_outcome", {"insight_id": "x", "status": "done"})


def test_update_insight_outcome_rejects_a_missing_insight(table):
    table(rows=[])
    with pytest.raises(ValueError, match="No insight found"):
        call("update_insight_outcome", {"insight_id": "2026-01-01T00:00:00"})


def test_update_insight_outcome_requires_an_id(table):
    table()
    with pytest.raises(ValueError, match="insight_id is required"):
        call("update_insight_outcome", {"insight_id": "  "})


# ═══════════════════════════════════════════════════════════════════════════════
# §3 — get_social_connection_trend
# ═══════════════════════════════════════════════════════════════════════════════

_QUALITY_SCORES = {"alone": 1, "surface": 2, "meaningful": 3, "deep": 4}


def journal_day(date: str, quality: str | None = None, **enriched) -> dict:
    """One Notion journal DATE# record. `enriched_social_quality` is the field
    lambdas/ingestion/journal_enrichment_lambda.py:239 actually writes."""
    rec = {"date": date, **enriched}
    if quality is not None:
        rec["enriched_social_quality"] = quality
    return rec


def test_social_trend_honest_empty_when_the_journal_is_silent(sources):
    sources(notion=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert out["error"] == "No journal data for range."
    assert out["start_date"] == _d(-30) and out["end_date"] == TODAY


def test_social_trend_honest_empty_when_entries_carry_no_social_field(sources):
    """Distinct from "no journal": entries exist but none was enriched. The
    envelope says which, and reports how many entries were examined."""
    sources(notion=[journal_day(TODAY), journal_day(_d(-1))])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert out["error"] == "No enriched_social_quality data found."
    assert out["entries_checked"] == 2


def test_social_trend_scores_streaks_and_overall_average_are_hand_derived(sources):
    """Five consecutive days: deep(4), meaningful(3), surface(2), meaningful(3),
    deep(4) — oldest→newest.
      overall_avg = (4+3+2+3+4)/5 = 16/5 = 3.2
      longest meaningful streak (score >= 3) = 2 (the leading deep+meaningful)
      current streak, walking back from the newest = 2 (deep, meaningful)
      days_since_meaningful = 0 (the newest day is itself meaningful)
    """
    rows = [
        journal_day(_d(-4), "deep"),
        journal_day(_d(-3), "meaningful"),
        journal_day(_d(-2), "surface"),
        journal_day(_d(-1), "meaningful"),
        journal_day(_d(0), "deep"),
    ]
    sources(notion=rows)
    out = call("get_social_connection_trend", {"start_date": _d(-10), "end_date": TODAY})
    assert out["overall_avg_score"] == 3.2
    assert out["total_days_with_data"] == 5
    assert out["distribution"] == {"deep": 2, "meaningful": 2, "surface": 1}
    assert out["streaks"] == {"current_meaningful_streak": 2, "longest_meaningful_streak": 2, "days_since_meaningful": 0}
    assert out["score_legend"] == _QUALITY_SCORES


def test_social_trend_takes_the_best_entry_per_day(sources):
    """Two entries the same day: the higher-quality one wins (a deep conversation
    is not erased by a later surface one)."""
    sources(notion=[journal_day(TODAY, "surface"), journal_day(TODAY, "deep")])
    out = call("get_social_connection_trend", {"start_date": _d(-10), "end_date": TODAY})
    assert out["total_days_with_data"] == 1 and out["overall_avg_score"] == 4.0


def test_social_trend_rolling_7d_spans_seven_calendar_days_not_seven_records(sources):
    """FIXED (#2221/#1917): the rolling windows used to slice the SCORES LIST by
    index, so with one journal entry per month the "rolling_7d" average spanned
    half a year and rolling_7d/rolling_30d collapsed to the same number silently.

    Seven entries, one every 30 days, alternating deep(4)/alone(1) with the newest
    deep. The entries sit at TODAY-180, -150, -120, -90, -60, -30 and TODAY. A real
    7-day window [TODAY-6, TODAY] contains only TODAY, and a real 30-day window
    [TODAY-29, TODAY] also contains only TODAY (the -30 entry is one day outside it)
    ⇒ both are 4.0 at days_logged 1, and both say so. Under the old index slicing
    BOTH read 2.71 — the mean of all seven entries spanning half a year.
    """
    qualities = ["deep", "alone", "deep", "alone", "deep", "alone", "deep"]
    rows = [journal_day(_d(-30 * (6 - i)), q) for i, q in enumerate(qualities)]
    sources(notion=rows)
    out = call("get_social_connection_trend", {"start_date": _d(-365), "end_date": TODAY})
    assert out["rolling_7d_latest"] == {"date": TODAY, "avg": 4.0, "days_logged": 1, "window_days": 7, "window_start": _d(-6)}
    assert out["rolling_30d_latest"] == {"date": TODAY, "avg": 4.0, "days_logged": 1, "window_days": 30, "window_start": _d(-29)}


def test_social_trend_rolling_7d_and_30d_diverge_on_a_gappy_stretch(sources):
    """The two windows are only distinguishable once they are bounded by dates:
    entries at TODAY-20 (alone=1) and TODAY (deep=4). The 7-day window sees only
    TODAY ⇒ 4.0 at n=1; the 30-day window sees both ⇒ (4+1)/2 = 2.5 at n=2. Under
    the old index slicing both read 2.5 and nothing said the "week" was 21 days."""
    sources(notion=[journal_day(_d(-20), "alone"), journal_day(TODAY, "deep")])
    out = call("get_social_connection_trend", {"start_date": _d(-90), "end_date": TODAY})
    assert out["rolling_7d_latest"]["avg"] == 4.0 and out["rolling_7d_latest"]["days_logged"] == 1
    assert out["rolling_30d_latest"]["avg"] == 2.5 and out["rolling_30d_latest"]["days_logged"] == 2


def test_social_trend_rolling_windows_are_bounded_by_dates(sources):
    qualities = ["deep", "alone", "deep", "alone", "deep", "alone", "deep"]
    rows = [journal_day(_d(-30 * (6 - i)), q) for i, q in enumerate(qualities)]
    sources(notion=rows)
    out = call("get_social_connection_trend", {"start_date": _d(-365), "end_date": TODAY})
    assert out["rolling_7d_latest"]["avg"] == 4.0  # only TODAY falls inside a real 7-day window


def test_social_trend_citation_is_gated_on_fourteen_days_of_data(sources):
    """#758: the Seligman/Holt-Lunstad citation is garnish below a real n. 13
    days ⇒ no citation, 14 ⇒ citation. The floor is derived from the module."""
    assert tsc._SOCIAL_CITATION_MIN_N == 14
    thin = [journal_day(_d(-i), "meaningful") for i in range(tsc._SOCIAL_CITATION_MIN_N - 1)]
    sources(notion=thin)
    assert "perma_context" not in call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})

    thick = [journal_day(_d(-i), "meaningful") for i in range(tsc._SOCIAL_CITATION_MIN_N)]
    sources(notion=thick)
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert "Seligman PERMA" in out["perma_context"]


def test_social_trend_correlations_need_ten_paired_days(sources):
    """Below n=10 the correlation is omitted entirely (honest silence, not a
    two-point r)."""
    rows = [journal_day(_d(-i), "deep") for i in range(9)]
    whoop = [{"date": _d(-i), "recovery_score": 50 + i} for i in range(9)]
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert out["health_correlations"] == []


def test_social_trend_correlation_r_is_hand_derived_and_carries_its_n(sources):
    """Ten days, social score alternating deep(4)/alone(1) and recovery moving
    with it perfectly (80 on a 4, 50 on a 1) ⇒ a perfect positive correlation.

      xs = 4,1,4,1,4,1,4,1,4,1   ys = 80,50,80,50,...
      Both series are a two-valued affine map of each other ⇒ r = 1.0 exactly.
    """
    rows, whoop = [], []
    for i in range(10):
        quality = "deep" if i % 2 == 0 else "alone"
        rows.append(journal_day(_d(-i), quality))
        whoop.append({"date": _d(-i), "recovery_score": 80 if i % 2 == 0 else 50})
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    recovery = next(c for c in out["health_correlations"] if c["metric"] == "Recovery")
    assert recovery["r"] == 1.0 and recovery["n"] == 10
    # #2221/ADR-105: a perfect alternation is maximally autocorrelated, so the AR(1)
    # correction collapses the effective n to the floor of 2 and NOTHING inferential can
    # be claimed from it. r=1.0 still stands; the verdict does not.
    assert recovery["n_eff"] == 2.0
    assert recovery["p_value"] is None and recovery["ci_low"] is None
    assert recovery["confidence"] == "LOW" and recovery["impact"] == "INCONCLUSIVE"


def test_social_trend_correlations_carry_p_value_ci_and_multiplicity_control(sources):
    """FIXED (#2221, ADR-105): the module used to publish a bare Pearson r with a
    "strong"/"moderate"/"weak" label at n>=10 — no p, no CI, no effective-n, no
    FDR across the eight correlations it runs. It now routes through the sanctioned
    mcp/helpers.py::correlation_report, which supplies all four, and health +
    journal correlations go through ONE batch so the BH-FDR covers the whole family
    of eight rather than two half-families."""
    rows, whoop = [], []
    for i in range(12):
        rows.append(journal_day(_d(-i), "deep" if i % 2 == 0 else "alone"))
        whoop.append({"date": _d(-i), "recovery_score": 80 if i % 2 == 0 else 50})
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    corr = out["health_correlations"][0]
    assert set(corr) == {"metric", "r", "n", "n_eff", "ci_low", "ci_high", "p_value", "q_value", "confidence", "impact"}
    # The bare unearned verdict is gone for good.
    assert "interpretation" not in corr


def test_social_trend_correlations_route_through_the_sanctioned_report(sources):
    rows, whoop = [], []
    for i in range(12):
        rows.append(journal_day(_d(-i), "deep" if i % 2 == 0 else "alone"))
        whoop.append({"date": _d(-i), "recovery_score": 80 if i % 2 == 0 else 50})
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert {"p_value", "confidence"} <= set(out["health_correlations"][0])


def test_social_trend_whoop_sleep_score_correlation_populates_from_writer_true_records(sources):
    """FIXED (#2221): HEALTH_SOURCES reads ("whoop", "sleep_score"), but the Whoop
    writer (lambdas/ingestion/whoop_lambda.py) stores `sleep_quality_score` — the
    alias only exists after mcp/helpers.py::normalize_whoop_sleep, which this
    function now calls on the way in (as tool_get_experiment_results already did).
    Fed writer-true records, Sleep Score correlates alongside every other whoop
    metric instead of being silently dropped."""
    rows, whoop = [], []
    for i in range(12):
        rows.append(journal_day(_d(-i), "deep" if i % 2 == 0 else "alone"))
        whoop.append(
            {
                "date": _d(-i),
                "recovery_score": 80 if i % 2 == 0 else 50,
                "hrv": 90 if i % 2 == 0 else 60,
                "sleep_quality_score": 85 if i % 2 == 0 else 55,  # the field the writer actually stores
                "sleep_duration_hours": 7.5,
            }
        )
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    metrics = {c["metric"] for c in out["health_correlations"]}
    assert {"Recovery", "HRV", "Sleep Score"} <= metrics
    assert "Sleep Score" in out["meaningful_vs_low_comparison"]


def test_social_trend_correlates_sleep_score_from_writer_true_records(sources):
    rows, whoop = [], []
    for i in range(12):
        rows.append(journal_day(_d(-i), "deep" if i % 2 == 0 else "alone"))
        whoop.append({"date": _d(-i), "sleep_quality_score": 85 if i % 2 == 0 else 55, "sleep_duration_hours": 7.5})
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert "Sleep Score" in {c["metric"] for c in out["health_correlations"]}


def test_social_trend_meaningful_vs_low_comparison_is_hand_derived(sources):
    """Meaningful days (score >= 3) recovery 80,80,80; low days (<= 2) 50,50,50 ⇒
    diff = 30.0. Both means are reported so the reader can see the split."""
    rows, whoop = [], []
    for i in range(6):
        rows.append(journal_day(_d(-i), "deep" if i % 2 == 0 else "alone"))
        whoop.append({"date": _d(-i), "recovery_score": 80 if i % 2 == 0 else 50})
    sources(notion=rows, whoop=whoop, garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    assert out["meaningful_vs_low_comparison"]["Recovery"] == {
        "meaningful_avg": 80.0,
        "low_social_avg": 50.0,
        "diff": 30.0,
    }


def test_social_trend_journal_correlations_are_reported_with_their_n(sources):
    rows = []
    for i in range(10):
        high = i % 2 == 0
        rows.append(journal_day(_d(-i), "deep" if high else "alone", enriched_mood=8 if high else 3))
    sources(notion=rows, whoop=[], garmin=[])
    out = call("get_social_connection_trend", {"start_date": _d(-30), "end_date": TODAY})
    mood = out["journal_correlations"]
    assert [c["metric"] for c in mood] == ["Mood"]
    assert mood[0]["r"] == 1.0 and mood[0]["n"] == 10
    assert {"p_value", "q_value", "n_eff", "confidence"} <= set(mood[0])  # #2221: same report as health


def test_social_trend_days_since_meaningful_is_measured_from_today_not_the_window_end(sources):
    """OBSERVED: mcp/tools_lifestyle.py:465 anchors days_since_meaningful on
    `datetime.now()`, not on the requested end_date. Asked about a window that
    ended 60 days ago, the tool answers with the distance from today."""
    sources(notion=[journal_day(_d(-60), "deep")])
    out = call("get_social_connection_trend", {"start_date": _d(-90), "end_date": _d(-60)})
    assert out["end_date"] == _d(-60)
    assert out["streaks"]["days_since_meaningful"] == 60  # not 0, which the window would imply


# ═══════════════════════════════════════════════════════════════════════════════
# §4 — The n-of-1 experiment engine
# ═══════════════════════════════════════════════════════════════════════════════


def test_create_experiment_requires_name_and_hypothesis(table, s3):
    table()
    s3()
    with pytest.raises(ValueError, match="name is required"):
        call("create_experiment", {"hypothesis": "x"})
    with pytest.raises(ValueError, match="hypothesis is required"):
        call("create_experiment", {"name": "Creatine 5g"})


def test_create_experiment_builds_a_slug_id_and_defaults_the_start_to_today(table, s3):
    t = table()
    s3()
    out = call("create_experiment", {"name": "Creatine 5g daily!", "hypothesis": "Deep sleep up >5%"})
    assert out["created"] is True
    assert out["experiment_id"] == f"creatine-5g-daily_{TODAY}"  # non-alnum → '-', trailing '-' stripped
    assert out["start_date"] == TODAY and out["status"] == "active" and out["iteration"] == 1
    item = t.puts[0]
    assert item["pk"] == EXPERIMENTS_PK and item["sk"] == f"EXP#{out['experiment_id']}"
    assert "end_date" not in item  # None values dropped before the write, not stored as null


def test_create_experiment_rejects_a_duplicate_id(table, s3):
    existing = {"pk": EXPERIMENTS_PK, "sk": f"EXP#creatine_{TODAY}", "status": "active"}
    table(rows=[existing])
    s3()
    with pytest.raises(ValueError, match="already exists"):
        call("create_experiment", {"name": "Creatine", "hypothesis": "h"})


def test_create_experiment_counts_iterations_from_the_same_slug(table, s3):
    """EL-F5: a repeat of the same protocol is iteration 2, derived by re-slugging
    the stored names rather than by a stored counter."""
    table(
        rows=[
            {"pk": EXPERIMENTS_PK, "sk": "EXP#creatine_2026-01-01", "name": "Creatine", "status": "completed"},
            {"pk": EXPERIMENTS_PK, "sk": "EXP#other_2026-01-01", "name": "Other", "status": "completed"},
        ]
    )
    s3()
    out = call("create_experiment", {"name": "Creatine", "hypothesis": "h", "start_date": _d(-1)})
    assert out["iteration"] == 2


def test_create_experiment_rejects_an_invalid_justification(table, s3):
    table()
    s3()
    with pytest.raises(ValueError, match="invalid justification"):
        call("create_experiment", {"name": "X", "hypothesis": "h", "priority": "urgent"})


def test_create_experiment_leaves_absent_justification_fields_absent(table, s3):
    """ADR-104 honest-empty: an omitted why_now is not a placeholder string."""
    t = table()
    s3()
    out = call("create_experiment", {"name": "X", "hypothesis": "h"})
    assert out["why_now"] is None and out["why_now_source"] is None
    assert "why_now" not in t.puts[0] and "hoped_outcome" not in t.puts[0]


def _valid_design(min_effect: float = 2.0) -> dict:
    """A design that satisfies experiment_design.validate_design — the frozen
    pre-registration shape: baseline window, washout, a declared stopping rule,
    and a criterion drawn from the sanctioned DESIGN_METRICS slugs."""
    return {
        "baseline_days": 14,
        "washout_days": 3,
        "stopping_rule": "Run the full 28 days regardless of interim trend; abort only if recovery is under 40% for 3 consecutive days.",
        "criterion": {"metric": "recovery_score", "direction": "higher", "min_effect": min_effect},
    }


def test_create_experiment_freezes_a_public_prereg_artifact_when_a_design_is_given(table, s3):
    """#728: the pre-registration is written to S3 BEFORE any result exists, and
    the response carries its public URL."""
    table()
    client = s3()
    design = _valid_design()
    out = call("create_experiment", {"name": "Creatine", "hypothesis": "h", "design": design})
    assert out["pre_registration_url"] == f"https://averagejoematt.com/experiments/prereg/creatine_{TODAY}.json"
    assert out["pre_registered_at"] == "2026-08-08T17:30:00"
    put = client.puts[0]
    assert put["Key"] == f"generated/experiments/prereg/creatine_{TODAY}.json"
    assert put["ContentType"] == "application/json"
    assert "Frozen at creation, before any results existed" in put["Body"]


def test_create_experiment_stores_design_floats_as_decimal_for_dynamodb(table, s3):
    """boto3 rejects float; the design's fractional min_effect must reach the
    table as Decimal while the public S3 copy keeps raw JSON floats."""
    t = table()
    s3()
    design = _valid_design(min_effect=2.5)
    call("create_experiment", {"name": "Creatine", "hypothesis": "h", "design": design})
    stored = t.puts[0]["design"]["criterion"]["min_effect"]
    assert isinstance(stored, Decimal) and stored == Decimal("2.5")


def test_create_experiment_survives_an_s3_failure_and_says_so(table, s3):
    """Fail-soft, but honestly: the experiment is still created and the response
    carries an explicit warning rather than a silent success."""
    t = table()
    s3(put_raises=RuntimeError("s3 down"))
    design = _valid_design()
    out = call("create_experiment", {"name": "Creatine", "hypothesis": "h", "design": design})
    assert out["created"] is True and out["pre_registration_url"] is None
    assert "no public timestamped proof" in out["pre_registration_warning"]
    assert "prereg_key" not in t.puts[0]


def test_create_experiment_truncates_the_verbatim_matthew_note(table, s3):
    """#1569: the note is Matthew's words, capped at a tweet-length quote."""
    t = table()
    s3()
    out = call("create_experiment", {"name": "X", "hypothesis": "h", "matthew_note": "y" * 800})
    assert len(out["matthew_note"]) == 500
    assert t.puts[0]["matthew_note_at"] == "2026-08-08T17:30:00"


def test_list_experiments_days_active_is_exclusive_of_the_start_day(table):
    """OBSERVED (#1917): days_active = (end - start).days, so an experiment run
    2026-07-26 → 2026-08-08 inclusive — 14 calendar days — reports 13, and
    min_duration_met (>= 14) reads False on the day the 14-day bar is met."""
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "name": "A",
                "start_date": _d(-13),
                "status": "active",
            }
        ]
    )
    out = call("list_experiments", {})
    row = out["experiments"][0]
    assert row["days_active"] == 13
    assert row["min_duration_met"] is False
    assert out == {"total": 1, "active": 1, "completed": 0, "filter": "all", "experiments": [row]}


def test_list_experiments_status_filter_and_counts(table):
    table(
        rows=[
            {"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "start_date": _d(-30), "status": "active"},
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#b",
                "experiment_id": "b",
                "start_date": _d(-60),
                "end_date": _d(-30),
                "status": "completed",
                "grade": "completed",
            },
        ]
    )
    assert call("list_experiments", {})["total"] == 2
    out = call("list_experiments", {"status": "completed"})
    assert out["total"] == 1 and out["filter"] == "completed"
    assert out["experiments"][0]["days_active"] == 30 and out["experiments"][0]["grade"] == "completed"


def test_list_experiments_unparseable_dates_yield_none_not_zero(table):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "start_date": "", "status": "active"}])
    row = call("list_experiments", {})["experiments"][0]
    assert row["days_active"] is None and row["min_duration_met"] is False


def test_list_experiments_read_is_phase_filtered(table):
    from experiment.phase_taxonomy import SCOPED_SOURCES

    assert "experiments" in SCOPED_SOURCES  # derived, not restated
    t = table(rows=[])
    call("list_experiments", {})
    assert "#phase" in t.query_calls[0]["FilterExpression"]


def test_list_experiments_issues_a_single_unpaginated_query(table):
    """OBSERVED: neither insights nor experiments follows LastEvaluatedKey. A
    partition past DynamoDB's 1 MB page limit silently truncates and the reported
    `total` is the truncated count."""
    t = table(rows=[])
    call("list_experiments", {})
    assert len(t.query_calls) == 1
    assert "ExclusiveStartKey" not in t.query_calls[0]


def test_get_experiment_results_requires_an_id_and_an_existing_record(table, sources):
    table(rows=[])
    sources()
    with pytest.raises(ValueError, match="experiment_id is required"):
        call("get_experiment_results", {"experiment_id": " "})
    with pytest.raises(ValueError, match="No experiment found"):
        call("get_experiment_results", {"experiment_id": "nope"})


def test_get_experiment_results_refuses_a_sub_one_day_experiment(table, sources):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "start_date": TODAY, "status": "active"}])
    sources()
    out = call("get_experiment_results", {"experiment_id": "a"})
    assert out == {"error": "Experiment has less than 1 day of data. Check back later."}


def test_get_experiment_results_rejects_a_corrupt_stored_date(table, sources):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "start_date": "2026-13-45", "status": "active"}])
    sources()
    with pytest.raises(ValueError, match="Invalid start_date or end_date"):
        call("get_experiment_results", {"experiment_id": "a"})


def _whoop_writer_true(date: str, recovery: float) -> dict:
    """A Whoop DATE# record using the field names the writer really stores
    (lambdas/ingestion/whoop_lambda.py)."""
    return {"date": date, "recovery_score": recovery, "hrv": 60, "resting_heart_rate": 52, "sleep_duration_hours": 7.5}


def test_get_experiment_results_before_and_during_windows_span_equal_calendar_days(table, sources):
    """FIXED (#2221/#1917): an experiment run 2026-07-01 → 2026-07-14 spans
    during_days = (end - start).days + 1 = 14 CALENDAR DAYS. The BEFORE window is
    [start - 14, start - 1] = 2026-06-17 → 2026-06-30, which is also 14 dates.
    Fed one record per date the two n's match, and both labels say 14 —
    previously the before side was 13 dates while both were labelled "(13 days)"."""
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "name": "A",
                "hypothesis": "h",
                "start_date": "2026-07-01",
                "end_date": "2026-07-14",
                "status": "completed",
            }
        ]
    )
    whoop = [_whoop_writer_true(_d(-i, "2026-07-14"), 70) for i in range(0, 28)]  # 2026-06-17 .. 2026-07-14
    sources(whoop=whoop)
    out = call("get_experiment_results", {"experiment_id": "a"})
    recovery = next(c for c in out["comparisons"] if c["metric"] == "Whoop Recovery")
    assert recovery["before_n"] == 14 and recovery["during_n"] == 14
    assert out["comparison_period"]["before"] == "2026-06-17 → 2026-06-30 (14 days)"
    assert out["comparison_period"]["during"] == "2026-07-01 → 2026-07-14 (14 days)"
    # The min-14-day gate no longer fires a day late on a 14-calendar-day experiment.
    assert out["duration_warning"] is None


def test_experiment_before_and_during_windows_are_equal_length(table, sources):
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "start_date": "2026-07-01",
                "end_date": "2026-07-14",
                "status": "completed",
            }
        ]
    )
    whoop = [_whoop_writer_true(_d(-i, "2026-07-14"), 70) for i in range(0, 28)]
    sources(whoop=whoop)
    out = call("get_experiment_results", {"experiment_id": "a"})
    recovery = next(c for c in out["comparisons"] if c["metric"] == "Whoop Recovery")
    assert recovery["before_n"] == recovery["during_n"]


def test_get_experiment_results_needs_three_points_per_side(table, sources):
    """Below n=3 on either side the metric is dropped entirely rather than
    compared at n=2 (ADR-105)."""
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "start_date": "2026-07-01",
                "end_date": "2026-07-14",
                "status": "completed",
            }
        ]
    )
    sources(whoop=[_whoop_writer_true(d, 70) for d in ("2026-07-01", "2026-07-02")])
    out = call("get_experiment_results", {"experiment_id": "a"})
    assert out["comparisons"] == [] and out["metrics_compared"] == 0


def test_get_experiment_results_delta_effect_size_and_consistency_are_hand_derived(table, sources):
    """Before: recovery 50,50,50,50 (4 days). During: 60,60,60,60 (4 days).

    before_mean = 50.0, during_mean = 60.0, delta = +10.0
    pct_change  = 10/50*100 = 20.0 ⇒ direction 'improved' (higher_is_better)
    Cohen's d   = (60-50)/pooled_sd; both variances are 0 ⇒ pooled_sd 0
                  ⇒ _cohens_d returns None (never a divide-by-zero, never a
                    fabricated 'large' bin)
    consistency = 4 of 4 during-days above the before mean ⇒ 100.0
    """
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "start_date": "2026-07-05",
                "end_date": "2026-07-08",
                "status": "completed",
            }
        ]
    )
    before = [_whoop_writer_true(d, 50) for d in ("2026-07-02", "2026-07-03", "2026-07-04")]
    during = [_whoop_writer_true(d, 60) for d in ("2026-07-05", "2026-07-06", "2026-07-07", "2026-07-08")]
    sources(whoop=before + during)
    out = call("get_experiment_results", {"experiment_id": "a"})
    recovery = next(c for c in out["comparisons"] if c["metric"] == "Whoop Recovery")
    assert recovery["before_mean"] == 50.0 and recovery["during_mean"] == 60.0
    assert recovery["delta"] == 10.0 and recovery["pct_change"] == 20.0
    assert recovery["direction"] == "improved"
    assert recovery["effect_size"] is None  # zero pooled SD ⇒ honest None, not a bin
    assert recovery["consistency_score"] == 100.0
    assert out["improved_count"] == 1 and out["worsened_count"] == 0


def test_get_experiment_results_cohens_d_ships_with_its_n_and_ci(table, sources):
    """ADR-105: the effect size is never binned into small/medium/large; it ships
    with the N it was computed at and an approximate CI half-width of
    1.96/sqrt(n/2). With n = 4 during-days: 1.96/sqrt(2) = 1.386 ⇒ 1.39."""
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "start_date": "2026-07-05",
                "end_date": "2026-07-08",
                "status": "completed",
            }
        ]
    )
    before = [_whoop_writer_true(d, r) for d, r in (("2026-07-02", 48), ("2026-07-03", 50), ("2026-07-04", 52))]
    during = [_whoop_writer_true(d, r) for d, r in (("2026-07-05", 58), ("2026-07-06", 60), ("2026-07-07", 62), ("2026-07-08", 60))]
    sources(whoop=before + during)
    out = call("get_experiment_results", {"experiment_id": "a"})
    effect = next(c for c in out["comparisons"] if c["metric"] == "Whoop Recovery")["effect_size"]
    assert "treat as directional only at N=4" in effect["interpretation"]
    assert "±1.39" in effect["interpretation"]
    assert not any(word in effect["interpretation"] for word in ("small", "medium", "large"))


def test_get_experiment_results_duration_warning_is_domain_specific(table, sources):
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "start_date": "2026-07-05",
                "end_date": "2026-07-08",
                "status": "completed",
                "category": "Supplement",
            }
        ]
    )
    sources(whoop=[])
    out = call("get_experiment_results", {"experiment_id": "a"})
    assert "adaptation noise" in out["duration_warning"]
    assert "week 1 as adaptation noise" in out["board_of_directors"]["Norton"]
    assert "⚠️ Under 14 days" in out["board_of_directors"]["Attia"]


def test_end_experiment_guards_status_and_grade(table):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "status": "active", "start_date": _d(-20)}])
    with pytest.raises(ValueError, match="experiment_id is required"):
        call("end_experiment", {"experiment_id": ""})
    with pytest.raises(ValueError, match="status must be"):
        call("end_experiment", {"experiment_id": "a", "status": "paused"})
    with pytest.raises(ValueError, match="grade must be"):
        call("end_experiment", {"experiment_id": "a", "grade": "B+"})


def test_end_experiment_refuses_to_close_a_closed_experiment(table):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "status": "completed", "start_date": _d(-20)}])
    with pytest.raises(ValueError, match="already completed"):
        call("end_experiment", {"experiment_id": "a"})


def test_end_experiment_infers_grade_and_computes_days_run(table):
    t = table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "name": "A", "status": "active", "start_date": _d(-20)}])
    out = call("end_experiment", {"experiment_id": "a", "outcome": "worked", "compliance_pct": 88, "reflection": "start earlier"})
    assert out["ended"] is True and out["status"] == "completed" and out["grade"] == "completed"
    assert out["end_date"] == TODAY and out["days_run"] == 20
    assert out["compliance_pct"] == 88 and out["reflection"] == "start earlier"
    values = t.updates[0]["ExpressionAttributeValues"]
    assert values[":g"] == "completed" and values[":cp"] == 88


def test_end_experiment_abandoned_grades_as_failed(table):
    table(rows=[{"pk": EXPERIMENTS_PK, "sk": "EXP#a", "experiment_id": "a", "status": "active", "start_date": _d(-5)}])
    out = call("end_experiment", {"experiment_id": "a", "status": "abandoned"})
    assert out["grade"] == "failed" and out["analysis"] is None


def test_end_experiment_design_analysis_failure_never_blocks_the_close(table, monkeypatch):
    """Fail-soft: a broken analysis leaves analysis=None (the honest state) and
    the experiment still closes."""
    table(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#a",
                "experiment_id": "a",
                "status": "active",
                "start_date": _d(-20),
                "design": {"criterion": {"metric": "recovery_score"}},
            }
        ]
    )

    def _boom(*_a, **_kw):
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr(tl, "_run_design_analysis", _boom)
    out = call("end_experiment", {"experiment_id": "a"})
    assert out["ended"] is True and out["analysis"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# §5 — The reader/writer audit on _EXPERIMENT_METRICS
#      (the highest-yield class: a mismatch leaves a metric permanently, silently
#       dark — the experiment engine simply never reports it)
# ═══════════════════════════════════════════════════════════════════════════════

# What each source's INGESTION LAMBDA actually writes for the quantity the
# metric table is after. Every entry verified by reading the writer:
#   whoop        lambdas/ingestion/whoop_lambda.py:401-403  (hrv_rmssd_milli → "hrv")
#   eightsleep   lambdas/ingestion/eightsleep_lambda.py:497 ("time_to_sleep_min")
#   garmin       lambdas/ingestion/garmin_lambda.py:452,496 ("body_battery_high", "avg_stress")
#   withings     lambdas/ingestion/withings_lambda.py:180-181 (weight_kg → "weight_lbs")
#   macrofactor  lambdas/ingestion/macrofactor_lambda.py:52-53 ("calories_kcal", "protein_g")
#   apple_health lambdas/ingestion/health_auto_export_lambda.py:327,332,494
#                ("steps", "blood_glucose_avg", "blood_glucose_time_in_range_pct")
WRITER_TRUE_RECORD = {
    "whoop": {
        "sleep_quality_score": 80,  # normalize_whoop_sleep → sleep_score
        "sleep_efficiency_percentage": 92,  # → sleep_efficiency_pct
        "slow_wave_sleep_hours": 1.5,  # → deep_pct
        "rem_sleep_hours": 1.8,  # → rem_pct
        "sleep_duration_hours": 7.5,
        "recovery_score": 70,
        "hrv": 62,
        "resting_heart_rate": 52,
    },
    "eightsleep": {"time_to_sleep_min": 12},
    "garmin": {"avg_stress": 33, "body_battery_high": 84},
    "withings": {"weight_lbs": 318.4},
    "macrofactor": {"calories_kcal": 2400, "protein_g": 210},
    "apple_health": {"steps": 9400, "blood_glucose_avg": 96, "blood_glucose_time_in_range_pct": 91},
}

# The six metrics that could NOT populate from writer-true data before #2221 —
# each entry is (source, the reader-invented field, the field the writer really
# uses). Kept as the historical record: the repair is asserted against it below,
# so a regression to any one of the invented names is named, not just counted.
PREVIOUSLY_DARK_METRICS = {
    "Sleep Onset Latency": ("eightsleep", "sleep_onset_latency_min", "time_to_sleep_min"),
    "HRV (rMSSD)": ("whoop", "hrv_rmssd", "hrv"),
    "Garmin Stress": ("garmin", "average_stress_level", "avg_stress"),
    "Calories": ("macrofactor", "calories", "calories_kcal"),
    "Mean Glucose": ("apple_health", "cgm_mean_glucose", "blood_glucose_avg"),
    "CGM Time in Range %": ("apple_health", "cgm_time_in_range_pct", "blood_glucose_time_in_range_pct"),
}


def _writer_true_rows(source: str, dates: list[str]) -> list[dict]:
    return [{"date": d, **WRITER_TRUE_RECORD[source]} for d in dates]


def _drive_metric_audit(table_fixture, sources_fixture):
    """Run get_experiment_results against a fully-populated, writer-true platform
    and return the set of metric display names the engine managed to report."""
    table_fixture(
        rows=[
            {
                "pk": EXPERIMENTS_PK,
                "sk": "EXP#audit",
                "experiment_id": "audit",
                "name": "Audit",
                "hypothesis": "everything reports",
                "start_date": "2026-07-05",
                "end_date": "2026-07-08",
                "status": "completed",
            }
        ]
    )
    before_dates = ["2026-07-02", "2026-07-03", "2026-07-04"]
    during_dates = ["2026-07-05", "2026-07-06", "2026-07-07", "2026-07-08"]
    by_source = {src: _writer_true_rows(src, before_dates + during_dates) for src in WRITER_TRUE_RECORD}
    sources_fixture(**by_source)
    out = call("get_experiment_results", {"experiment_id": "audit"})
    return {c["metric"] for c in out["comparisons"]}, out


def test_experiment_metric_registry_has_a_writer_true_fixture_for_every_source():
    """Guard the SET: derive the sources from _EXPERIMENT_METRICS so a new metric
    on a new partition cannot slip past this audit."""
    declared_sources = {src for src, *_rest in tl._EXPERIMENT_METRICS}
    assert declared_sources == set(WRITER_TRUE_RECORD), (
        "mcp/tools_lifestyle.py::_EXPERIMENT_METRICS changed its source set to "
        f"{sorted(declared_sources)}; add a writer-true fixture for the new partition."
    )


def test_every_declared_experiment_metric_populates_from_writer_true_data(table, sources):
    """FIXED (#2221): fed a record from every source using the field names the
    ingestion Lambdas really write, ALL sixteen declared metrics appear in the
    comparison. Six of them could not before — each was a reader-invented field
    name that no writer in lambdas/ has ever produced."""
    reported, out = _drive_metric_audit(table, sources)
    declared = {label for _src, _field, label, _hib in tl._EXPERIMENT_METRICS}

    assert set(PREVIOUSLY_DARK_METRICS) <= declared  # the repaired set is a real subset of the registry
    assert declared == reported
    assert out["metrics_compared"] == len(declared) == 16


def test_no_experiment_metric_still_reads_a_reader_invented_field():
    """Name the six repairs individually so a regression says WHICH one, and pin
    the same repair in lambdas/experiment/experiment_design.py::DESIGN_METRICS —
    a frozen pre-registration whose criterion is HRV/glucose/stress/calories/
    latency evaluated against an empty series until #2221."""
    from experiment import experiment_design

    by_label = {label: (src, field) for src, field, label, _hib in tl._EXPERIMENT_METRICS}
    design_fields = {(src, field) for src, field, _label in experiment_design.DESIGN_METRICS.values()}
    for label, (source, invented_field, writer_field) in PREVIOUSLY_DARK_METRICS.items():
        assert by_label[label] == (source, writer_field), f"{label} must read the writer's field, not '{invented_field}'"
        assert (source, invented_field) not in design_fields, f"DESIGN_METRICS still reads the invented '{invented_field}' for {label}"


def test_experiment_results_normalises_whoop_before_comparing(table, sources):
    """The half of the mismatch class that IS handled: whoop's sleep aliases are
    produced by normalize_whoop_sleep on the way in, so Deep Sleep % is derived
    from slow_wave_sleep_hours / sleep_duration_hours = 1.5/7.5 = 20.0%."""
    reported, out = _drive_metric_audit(table, sources)
    assert "Deep Sleep %" in reported
    deep = next(c for c in out["comparisons"] if c["metric"] == "Deep Sleep %")
    assert deep["before_mean"] == 20.0 and deep["during_mean"] == 20.0


# ═══════════════════════════════════════════════════════════════════════════════
# §6 — Field Notes (the weekly AI-vs-Matthew lab notebook)
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_field_notes_defaults_to_the_current_iso_week(table):
    """2026-08-08 is in ISO week 32 ⇒ '2026-W32'."""
    assert NOW.isocalendar()[1] == 32
    table(rows=[])
    out = call("get_field_notes", {})
    assert out["week"] == "2026-W32" and out["status"] == "not_yet_generated"


def test_get_field_notes_returns_the_ai_page_and_flags_no_response_yet(table):
    table(
        rows=[
            {
                "pk": FIELD_NOTES_PK,
                "sk": "WEEK#2026-W31",
                "week": "2026-W31",
                "week_label": "Aug 1",
                "ai_present": "You trained four times.",
                "ai_generated_at": "2026-08-02T12:00:00",
            }
        ]
    )
    out = call("get_field_notes", {"week": "2026-W31"})
    assert out["has_matthew_response"] is False
    assert out["ai_present"] == "You trained four times."
    assert out["ai_domains"] == [] and out["ai_key_metrics"] == {}  # envelope parity on absence
    assert out["message"] == "AI notes are ready. Matthew hasn't responded yet."


def test_get_field_notes_includes_matthews_page_once_written(table):
    table(
        rows=[
            {
                "pk": FIELD_NOTES_PK,
                "sk": "WEEK#2026-W31",
                "week": "2026-W31",
                "ai_generated_at": "2026-08-02T12:00:00",
                "matthew_notes": "Disagree on the sleep read.",
                "matthew_agreement": "partial",
                "matthew_disputed": ["sleep"],
            }
        ]
    )
    out = call("get_field_notes", {"week": "2026-W31"})
    assert out["has_matthew_response"] is True
    assert out["matthew_agreement"] == "partial" and out["matthew_disputed"] == ["sleep"]


def test_log_field_note_response_validates_the_week_format(table):
    table(rows=[])
    assert call("log_field_note_response", {"week": "", "notes": "x"})["error"].startswith("week is required")
    assert "Invalid week format" in call("log_field_note_response", {"week": "2026-W1", "notes": "x"})["error"]
    assert "notes is required" in call("log_field_note_response", {"week": "2026-W31", "notes": ""})["error"]


def test_log_field_note_response_requires_ai_notes_to_exist_first(table):
    table(rows=[])
    out = call("log_field_note_response", {"week": "2026-W31", "notes": "x"})
    assert out["error"].startswith("No field notes record")

    table(rows=[{"pk": FIELD_NOTES_PK, "sk": "WEEK#2026-W31"}])
    out = call("log_field_note_response", {"week": "2026-W31", "notes": "x"})
    assert "haven't been generated yet" in out["error"]


def test_log_field_note_response_writes_only_matthews_fields(table, monkeypatch):
    """update_item, never put_item — the AI page must survive Matthew's reply."""
    monkeypatch.setattr(tl, "_write_field_note_interactions", lambda *a, **kw: None)
    t = table(
        rows=[
            {
                "pk": FIELD_NOTES_PK,
                "sk": "WEEK#2026-W31",
                "week_label": "Aug 1",
                "ai_present": "Four sessions, two of them hard.",
                "ai_generated_at": "2026-08-02T12:00:00",
            }
        ]
    )
    out = call(
        "log_field_note_response",
        {"week": "2026-W31", "notes": "I felt worse than that reads", "agreement": "partial", "disputed": ["sleep"], "added": "travel"},
    )
    assert out["status"] == "saved" and out["word_count"] == 6 and out["week_label"] == "Aug 1"
    assert t.puts == []
    expr = t.updates[0]["UpdateExpression"]
    assert expr.startswith("SET matthew_notes = :mn")
    assert "matthew_agreement" in expr and "matthew_disputed" in expr and "matthew_added" in expr
    assert "ai_present" not in expr


def test_log_field_note_response_survives_a_broken_coach_write_back(table, monkeypatch):
    """#533's broadcast is a side effect; the saved response is the product and
    must never fail because of it."""

    def _boom(*_a, **_kw):
        raise RuntimeError("persona registry down")

    monkeypatch.setattr(tl, "_write_field_note_interactions", _boom)
    table(rows=[{"pk": FIELD_NOTES_PK, "sk": "WEEK#2026-W31", "ai_generated_at": "2026-08-02T12:00:00"}])
    assert call("log_field_note_response", {"week": "2026-W31", "notes": "ok"})["status"] == "saved"


def test_field_note_week_monday_is_the_iso_monday(table):
    """The SK sorts by date, so the week string must map to a real Monday."""
    assert tl._field_note_week_monday("2026-W32") == "2026-08-03"
    assert datetime.strptime(tl._field_note_week_monday("2026-W32"), "%Y-%m-%d").isoweekday() == 1


def test_log_field_note_response_crashes_on_an_explicit_null_week(table):
    """OBSERVED: `args.get("week", "").strip()` returns None — not "" — when the
    key is present with a null value, which an MCP client can send for an
    optional-looking string. The default only applies to a MISSING key."""
    table(rows=[])
    with pytest.raises(AttributeError):
        call("log_field_note_response", {"week": None, "notes": "x"})


# ═══════════════════════════════════════════════════════════════════════════════
# §7 — The PRIVATE evening-intake ledger (#1405)
# ═══════════════════════════════════════════════════════════════════════════════


def test_log_evening_intake_validates_the_count_range(table):
    table()
    for bad in (None, "two", -1, 5):
        with pytest.raises(ValueError):
            call("log_evening_intake", {"count": bad})


def test_log_evening_intake_writes_only_the_private_partition(table, monkeypatch):
    """Privacy: the count must land in USER#matthew#SOURCE#private_intake and
    nowhere else. private_intake is RAW_TIMESERIES and never publicly served."""
    from experiment.phase_taxonomy import RAW_TIMESERIES_SOURCES

    assert "private_intake" in RAW_TIMESERIES_SOURCES  # derived, not restated
    monkeypatch.setattr(tl, "pacific_today", lambda: TODAY, raising=False)
    t = table(update_item_hook=lambda _t, **kw: {})
    out = call("log_evening_intake", {"count": 2, "date": TODAY})
    assert out == {"logged": True, "date": TODAY, "count": 2, "private": True, "updated": False, "previous_count": None}
    assert t.puts == []
    key = t.updates[0]["Key"]
    assert key == {"pk": PRIVATE_INTAKE_PK, "sk": f"DATE#{TODAY}"}
    assert t.updates[0]["ExpressionAttributeValues"][":v"] == Decimal(2)
    assert t.updates[0]["ExpressionAttributeValues"][":src"] == "mcp"


def test_log_evening_intake_is_observably_idempotent(table):
    """#1484: re-logging the same evening updates the one row and SAYS SO, so the
    flow can report "2 → 1" instead of silently double-counting."""
    t = table(update_item_hook=lambda _t, **kw: {"Attributes": {"intake_count": Decimal(2)}})
    out = call("log_evening_intake", {"count": 1, "date": TODAY})
    assert out["updated"] is True and out["previous_count"] == 2 and out["count"] == 1
    assert len(t.updates) == 1  # one row touched, never a second write


def test_log_evening_intake_rejects_junk_dates(table):
    table(update_item_hook=lambda _t, **kw: {})
    with pytest.raises(ValueError):
        call("log_evening_intake", {"count": 1, "date": "last tuesday"})


def test_log_evening_intake_defaults_to_the_pacific_day_not_utc(monkeypatch, table):
    """#1484: the evening flow runs 18:00-24:00 PT, which is already tomorrow in
    UTC. The default MUST come from pacific_today(), or one evening splits across
    two DATE# rows and double-counts in the dose-response ledger."""
    table(update_item_hook=lambda _t, **kw: {})
    monkeypatch.setattr("common.pacific_time.pacific_today", lambda: "2026-08-07")
    out = call("log_evening_intake", {"count": 3})
    assert out["date"] == "2026-08-07"  # PT day, not the frozen UTC 2026-08-08


def test_get_intake_response_clamps_the_window_silently(table, monkeypatch):
    """OBSERVED (#1917): window_days is clamped to [30, 730] with no note. A
    caller asking for 7 days is answered about 30 and told "window_days": 30 —
    the only tell is that the echoed value differs from the request."""
    seen = {}

    def _fake(tbl, window_days=180):
        seen["window_days"] = window_days
        return {"window_days": window_days, "logged_evenings": 0, "nonzero_evenings": 0}

    monkeypatch.setattr("coach.intake_response.compute_intake_response", _fake)
    table()
    assert call("get_intake_response", {"window_days": 7})["window_days"] == 30
    assert call("get_intake_response", {"window_days": 5000})["window_days"] == 730
    assert call("get_intake_response", {})["window_days"] == 180
    assert seen["window_days"] == 180


# ═══════════════════════════════════════════════════════════════════════════════
# §8 — State of Mind, reached through its real dispatcher (get_mood)
# ═══════════════════════════════════════════════════════════════════════════════


def _som_row(date: str, valence: float, check_ins: int = 2, **extra) -> dict:
    """One apple_health DATE# record carrying the HAE State-of-Mind aggregate.
    Field names verified against the writer,
    lambdas/ingestion/health_auto_export_lambda.py:1294 (som_avg_valence …)."""
    return {
        "pk": "USER#matthew#SOURCE#apple_health",
        "sk": f"DATE#{date}",
        "som_avg_valence": Decimal(str(valence)),
        "som_check_in_count": check_ins,
        "som_top_labels": "calm",
        **extra,
    }


def test_state_of_mind_honest_empty_with_setup_instructions(table, s3):
    table(rows=[])
    s3()
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": _d(-5), "end_date": TODAY})
    assert out["status"] == "no_data"
    assert "How We Feel" in out["message"]
    assert out["period"] == {"start": _d(-5), "end": TODAY}


def test_state_of_mind_summary_is_hand_derived(table, s3):
    """Three days, valence 0.8 / 0.0 / -0.8 (oldest→newest), 2 check-ins each.

    overall_avg = (0.8 + 0.0 + -0.8)/3 = 0.0 ⇒ 'neutral'
    total_check_ins = 6, avg per day = 6/3 = 2.0
    trend: mid = 3//2 = 1 ⇒ first half = 0.8, second half = (0.0 + -0.8)/2 = -0.4
           delta = -0.4 - 0.8 = -1.2 ⇒ < -0.1 ⇒ 'declining'
    """
    rows = [_som_row(_d(-2), 0.8), _som_row(_d(-1), 0.0), _som_row(_d(0), -0.8)]
    table(rows=rows)
    s3()
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": _d(-2), "end_date": TODAY})
    summary = out["summary"]
    assert summary["days_with_data"] == 3
    assert summary["total_check_ins"] == 6 and summary["avg_check_ins_per_day"] == 2.0
    assert summary["overall_avg_valence"] == 0.0 and summary["overall_interpretation"] == "neutral"
    assert summary["trend_direction"] == "declining" and summary["trend_delta"] == -1.2


def test_state_of_mind_recent_7day_average_actually_spans_eight_dates(table, s3):
    """OBSERVED (#1917): mcp/tools_lifestyle.py:640 selects
    `d["date"] >= (now - 7 days)`, an INCLUSIVE lower bound, so the field named
    `recent_7day_avg` covers eight calendar dates (2026-08-01 … 2026-08-08).

    Eight days at valence 1.0 and one older day at -1.0:
      recent_7day_avg = 8.0/8 = 1.0 (the -1.0 day is excluded)
    Add a day at 2026-08-01 with valence -7.0 and it IS included:
      recent_7day_avg = (7*1.0 + -7.0)/8 = 0.0
    """
    rows = [_som_row(_d(-i), 1.0) for i in range(0, 7)] + [_som_row(_d(-7), -7.0), _som_row(_d(-8), -1.0)]
    table(rows=rows)
    s3()
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": _d(-30), "end_date": TODAY})
    assert out["summary"]["recent_7day_avg"] == 0.0  # the 8th date is inside the "7-day" window


def test_state_of_mind_reads_the_user_segmented_s3_prefix(table, s3):
    """The raw check-ins live under raw/matthew/state_of_mind/YYYY/MM/DD.json —
    the un-segmented path silently 404'd and dropped the whole deep analysis.
    Pin the key so a regression is visible."""
    import json

    entries = [
        {
            "valence": 0.5,
            "labels": ["calm"],
            "associations": ["Family"],
            "time": "2026-08-08 09:15:00",
            "valence_classification": "pleasant",
        },
        {
            "valence": -0.5,
            "labels": ["tense"],
            "associations": ["Work"],
            "time": "2026-08-08 19:15:00",
            "valence_classification": "unpleasant",
        },
    ]
    client = s3({"raw/matthew/state_of_mind/2026/08/08.json": json.dumps(entries)})
    table(rows=[_som_row(TODAY, 0.0)])
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": TODAY, "end_date": TODAY})
    assert client is not None
    assert out["top_emotion_labels"] == [{"label": "calm", "count": 1}, {"label": "tense", "count": 1}]
    assert out["valence_distribution"] == {"pleasant": 1, "unpleasant": 1}
    # 09:15 → morning bucket, 19:15 → evening bucket
    assert out["time_of_day_pattern"] == {
        "morning": {"avg_valence": 0.5, "count": 1},
        "evening": {"avg_valence": -0.5, "count": 1},
    }


def test_state_of_mind_association_averages_need_two_observations(table, s3):
    """A single check-in mentioning "Work" is not a finding about work (ADR-105);
    the per-association mean is gated at n>=2 and ships its count."""
    import json

    entries = [
        {"valence": -0.4, "associations": ["Work"], "time": "2026-08-08 10:00:00"},
        {"valence": -0.6, "associations": ["Work"], "time": "2026-08-08 11:00:00"},
        {"valence": 0.9, "associations": ["Hobbies"], "time": "2026-08-08 12:00:00"},
    ]
    s3({"raw/matthew/state_of_mind/2026/08/08.json": json.dumps(entries)})
    table(rows=[_som_row(TODAY, 0.0)])
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": TODAY, "end_date": TODAY})
    assert out["valence_by_association"] == [{"association": "Work", "avg_valence": -0.5, "count": 2}]


def test_state_of_mind_default_window_is_derived_from_a_naive_utc_now(table, s3):
    """OBSERVED: mcp/tools_lifestyle.py:564-565 defaults the window from bare
    `datetime.now()` — neither UTC-aware nor the Pacific calendar day the data is
    keyed by, which `mcp.core.pacific_today()` exists to provide. With the clock
    frozen at 17:30 UTC (10:30 PT, same date) the two agree; in the 16:00-24:00 PT
    window they do not, and the default end_date is tomorrow's empty PT day."""
    t = table(rows=[])
    s3()
    TOOLS["get_mood"]["fn"]({"view": "state_of_mind"})
    # One get_item per day in the range — 91 dates for the default 90-day window.
    assert len(t.store) == 0
    out = TOOLS["get_mood"]["fn"]({"view": "state_of_mind"})
    assert out["period"] == {"start": _d(-90), "end": TODAY}


def test_state_of_mind_reads_day_by_day_instead_of_one_range_query(monkeypatch, s3):
    """OBSERVED: unlike every sibling tool, this view issues one get_item PER DAY
    (mcp/tools_lifestyle.py:572-594) rather than a single sk-BETWEEN query — 91
    round trips for the default 90-day window, and because it bypasses
    query_source entirely the ADR-058 phase filter never applies to it."""
    calls: list = []

    class CountingTable(FakeDdbTable):
        def get_item(self, Key=None, **kwargs):
            calls.append(Key)
            return super().get_item(Key=Key, **kwargs)

    monkeypatch.setattr(tl, "table", CountingTable(rows=[]))
    s3()
    TOOLS["get_mood"]["fn"]({"view": "state_of_mind", "start_date": _d(-9), "end_date": TODAY})
    assert len(calls) == 10  # one per date in a 10-day window
    assert all(k["pk"] == "USER#matthew#SOURCE#apple_health" for k in calls)


# ═══════════════════════════════════════════════════════════════════════════════
# §9 — Movement view: dispatch only (contracts live in test_di1_movement_integrity)
# ═══════════════════════════════════════════════════════════════════════════════


def test_movement_view_dispatches_and_returns_honest_empty(monkeypatch):
    """The movement analysis is exercised in depth by
    tests/test_di1_movement_integrity.py; this pins only that the registered
    dispatcher still reaches it and that a dark platform gets an error envelope,
    not a fabricated zero-movement day."""

    def _empty(sources, start_date, end_date, lean=False, include_pilot=False):
        return {s: [] for s in sources}

    monkeypatch.setattr(tl, "parallel_query_sources", _empty)
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": _d(-7), "end_date": TODAY})
    assert out == {"error": "No Apple Health or Hevy data in range."}


def test_daily_metrics_unknown_view_returns_an_error_envelope():
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "teleport"})
    assert out["error"].startswith("Unknown view")
    assert "movement" in out["valid_views"]


# ═══════════════════════════════════════════════════════════════════════════════
# §10 — The pre-registered close path (#539): _run_design_analysis via end_experiment
# ═══════════════════════════════════════════════════════════════════════════════


def _design_experiment_row(start_date: str, *, baseline_days=14, washout_days=3) -> dict:
    return {
        "pk": EXPERIMENTS_PK,
        "sk": "EXP#designed",
        "experiment_id": "designed",
        "name": "Designed",
        "status": "active",
        "start_date": start_date,
        "design": {
            "baseline_days": baseline_days,
            "washout_days": washout_days,
            "stopping_rule": "Run the full window regardless of interim trend; abort only on 3 consecutive days below 40% recovery.",
            "criterion": {"metric": "recovery_score", "direction": "higher", "min_effect": 2.0},
        },
    }


def _whoop_with_sk(date: str, recovery: float) -> dict:
    """_run_design_analysis reads the date out of the SORT KEY (``sk[5:15]``), not
    the ``date`` attribute — a row without an sk is silently dropped."""
    return {"pk": "USER#matthew#SOURCE#whoop", "sk": f"DATE#{date}", "date": date, "recovery_score": recovery}


def test_end_experiment_runs_the_frozen_design_analysis_over_the_declared_windows(table, sources):
    """Start 2026-07-01, end 2026-08-01, baseline_days 14, washout_days 3:
      baseline = [2026-07-01 - 14, 2026-07-01 - 1] = 2026-06-17 → 2026-06-30
      analysis = [2026-07-01 + 3, 2026-08-01]      = 2026-07-04 → 2026-08-01
    The washout days are excluded from the treated arm, as pre-registered."""
    t = table(rows=[_design_experiment_row("2026-07-01")])
    rows = []
    d = datetime.strptime("2026-06-17", "%Y-%m-%d")
    while d <= datetime.strptime("2026-08-01", "%Y-%m-%d"):
        ds = d.strftime("%Y-%m-%d")
        rows.append(_whoop_with_sk(ds, 50 if ds <= "2026-06-30" else 62))
        d += timedelta(days=1)
    sources(whoop=rows)

    out = call("end_experiment", {"experiment_id": "designed", "end_date": "2026-08-01"})
    analysis = out["analysis"]
    assert analysis["windows"] == {
        "baseline_start": "2026-06-17",
        "baseline_end": "2026-06-30",
        "analysis_start": "2026-07-04",
        "analysis_end": "2026-08-01",
    }
    assert analysis["metric"] == "recovery_score"
    assert analysis["engine"] == "n1-design-v1"
    assert analysis["analyzed_at"] == "2026-08-08T17:30:00"
    assert analysis["verdict"] in ("supported", "contradicted", "inconclusive")
    assert isinstance(analysis["summary"], str) and analysis["summary"]
    # The analysis is persisted as Decimal-safe JSON on the same update.
    assert ":an" in t.updates[0]["ExpressionAttributeValues"]


def test_end_experiment_design_analysis_refuses_when_the_washout_eats_the_window(table, sources):
    """Honest refusal, not a verdict: washout 3 on a 1-day experiment leaves no
    treated arm at all."""
    table(rows=[_design_experiment_row("2026-08-01", washout_days=3)])
    sources(whoop=[])
    out = call("end_experiment", {"experiment_id": "designed", "end_date": "2026-08-02"})
    assert out["analysis"] == {
        "verdict": "inconclusive",
        "summary": "Washout consumed the whole experiment window — no analysis possible.",
        "windows": None,
    }


def test_design_analysis_drops_rows_without_a_sort_key(table, sources):
    """OBSERVED: _dated_values keys on ``str(it.get("sk",""))[5:15]`` and requires
    len == 10, so a row that reaches it without an sk (any caller that strips
    keys, e.g. a lean query) contributes nothing — silently, with no n warning."""
    table(rows=[_design_experiment_row("2026-07-01")])
    sources(whoop=[{"date": d, "recovery_score": 60} for d in ("2026-06-20", "2026-07-10", "2026-07-20")])
    out = call("end_experiment", {"experiment_id": "designed", "end_date": "2026-08-01"})
    assert out["analysis"]["verdict"] == "inconclusive"


def test_create_experiment_derives_why_now_from_a_confirmed_hypothesis(table, s3):
    """#1117: provenance is automatic where it exists — a CONFIRMED hypothesis
    record supplies why_now and stamps its source."""
    hyp = {
        "pk": "USER#matthew#SOURCE#hypotheses",
        "sk": "HYPOTHESIS#h1",
        "hypothesis_id": "h1",
        "status": "confirmed",
        "hypothesis": "Late caffeine suppresses deep sleep",
        "last_checked": "2026-07-30T00:00:00",
    }
    table(rows=[hyp])
    s3()
    out = call("create_experiment", {"name": "Caffeine cutoff", "hypothesis": "h", "source_hypothesis_id": "h1"})
    assert out["why_now_source"] == "hypothesis"
    assert out["why_now"].startswith("Promoted from a confirmed hypothesis: Late caffeine suppresses deep sleep")
    assert "(confirmed 2026-07-30)" in out["why_now"]


def test_create_experiment_missing_hypothesis_leaves_why_now_empty_not_invented(table, s3):
    """ADR-104: a dangling source_hypothesis_id fails soft to honest-empty."""
    table(rows=[])
    s3()
    out = call("create_experiment", {"name": "X", "hypothesis": "h", "source_hypothesis_id": "nope"})
    assert out["why_now"] is None and out["why_now_source"] is None


def test_create_experiment_pulls_why_now_and_evidence_from_the_promoted_library(table, s3):
    """The other promotion trigger: a promoted experiment_library.json entry."""
    import json

    library = {
        "experiments": [
            {
                "id": "creatine",
                "rationale": "Creatine is the most-replicated ergogenic aid.",
                "promoted_date": "2026-07-01",
                "evidence_for": [{"url": "https://example.org/creatine", "title": "Meta-analysis"}],
            }
        ]
    }
    table(rows=[])
    s3({"config/experiment_library.json": json.dumps(library)})
    out = call("create_experiment", {"name": "Creatine", "hypothesis": "h", "library_id": "creatine"})
    assert out["why_now_source"] == "library"
    assert "most-replicated ergogenic aid" in out["why_now"]
    assert out["evidence_links"][0]["url"] == "https://example.org/creatine"


def test_create_experiment_library_lookup_failure_never_blocks_creation(table, s3):
    """Fail-soft: an unreadable library leaves why_now empty rather than raising."""
    table(rows=[])
    s3({"config/experiment_library.json": "{ not json"})
    out = call("create_experiment", {"name": "X", "hypothesis": "h", "library_id": "creatine"})
    assert out["created"] is True and out["why_now"] is None


def test_create_experiment_randomized_start_refuses_a_hand_picked_date(table, s3):
    """#1413 SCED: the whole point is that the start is DRAWN, not chosen."""
    table(rows=[])
    s3()
    design = _valid_design()
    design["randomized_start"] = {"window_start": _d(1), "window_end": _d(10)}
    with pytest.raises(ValueError, match="do not pass start_date"):
        call("create_experiment", {"name": "X", "hypothesis": "h", "start_date": _d(2), "design": design})


def test_create_experiment_randomized_start_refuses_a_window_already_underway(table, s3):
    """A window that has already begun is post-hoc, not pre-declared."""
    table(rows=[])
    s3()
    design = _valid_design()
    design["randomized_start"] = {"window_start": _d(-5), "window_end": _d(5)}
    with pytest.raises(ValueError, match="pre-registration rejected"):
        call("create_experiment", {"name": "X", "hypothesis": "h", "design": design})


def test_create_experiment_randomized_start_draws_and_freezes_its_provenance(table, s3):
    """The draw's window, k, index and timestamp are frozen WITH the design, so
    the artifact proves the start was drawn rather than chosen."""
    table(rows=[])
    client = s3()
    design = _valid_design()
    design["randomized_start"] = {"window_start": _d(1), "window_end": _d(14)}
    out = call("create_experiment", {"name": "X", "hypothesis": "h", "design": design})
    draw = out["start_draw"]
    assert draw is not None and draw["drawn_at"] == "2026-08-08T17:30:00Z"
    assert _d(1) <= out["start_date"] <= _d(14)
    assert '"start_draw"' in client.puts[0]["Body"]


# ═══════════════════════════════════════════════════════════════════════════════
# §11 — get_daily_metrics(view="movement"): the NEAT unit contract
#       (has_workout / step-completeness contracts live in
#        tests/test_di1_movement_integrity.py and are not duplicated here)
# ═══════════════════════════════════════════════════════════════════════════════


def _movement_sources(monkeypatch, *, apple_health=None, strava=None, hevy=None):
    data = {"apple_health": list(apple_health or []), "strava": list(strava or []), "hevy": list(hevy or [])}

    def _parallel(sources, start_date, end_date, lean=False, include_pilot=False):
        return {s: [dict(r) for r in data.get(s, [])] for s in sources}

    monkeypatch.setattr(tl, "parallel_query_sources", _parallel)


def test_movement_neat_converts_kilojoules_before_subtracting(monkeypatch):
    """FIXED (#2221) UNIT ERROR: ``_get_movement_score`` read Strava's
    ``total_kilojoules`` into a variable literally named ``exercise_kcal`` and
    subtracted it from Apple Health's ``active_calories`` (kcal).

    A 2000 kJ ride is 2000 / 4.184 = 478.0 kcal of work. On a day with 900 kcal
    active calories the honest NEAT is 900 - 478.0 = 422 kcal. The tool used to
    compute 900 - 2000 = -1100, clamp at 0, and report NEAT 0.
    """
    _movement_sources(
        monkeypatch,
        apple_health=[{"date": TODAY, "steps": 9000, "active_calories": 900}],
        strava=[{"date": TODAY, "total_kilojoules": 2000, "activity_count": 1}],
    )
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": TODAY, "end_date": TODAY})
    row = out["daily"][0]
    assert row["active_calories"] == 900
    assert row["neat_estimate_kcal"] == 422.0  # 900 kcal - 478.0 kcal, no longer floored at zero
    assert out["summary"]["avg_neat_kcal"] == 422.0


def test_movement_neat_conversion_uses_the_thermochemical_kilocalorie(monkeypatch):
    _movement_sources(
        monkeypatch,
        apple_health=[{"date": TODAY, "steps": 9000, "active_calories": 900}],
        strava=[{"date": TODAY, "total_kilojoules": 2000, "activity_count": 1}],
    )
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": TODAY, "end_date": TODAY})
    assert out["daily"][0]["neat_estimate_kcal"] == pytest.approx(422, abs=5)  # 900 - 2000*0.239


def test_movement_step_target_hit_rate_is_hand_derived(monkeypatch):
    """Four days at 9000/9000/7000/7000 steps against the declared default target
    of 8000 ⇒ 2 of 4 ⇒ 50.0%, and the average is (9000+9000+7000+7000)/4 = 8000."""
    ah = [{"date": _d(-i), "steps": s, "active_calories": 400} for i, s in enumerate((9000, 9000, 7000, 7000))]
    _movement_sources(monkeypatch, apple_health=ah)
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": _d(-3), "end_date": TODAY})
    assert out["summary"]["step_target"] == 8000
    assert out["summary"]["avg_daily_steps"] == 8000
    assert out["summary"]["step_target_hit_rate_pct"] == 50.0


def test_movement_score_is_a_weighted_composite_of_the_present_components(monkeypatch):
    """Seven identical days at exactly the baseline: each component scores
    value / (baseline * 1.5) * 100 = 66.67, and the weighted mean over the
    components present renormalises to the same 66.67 ⇒ rounded 67."""
    ah = [{"date": _d(-i), "steps": 9000, "active_calories": 500} for i in range(7)]
    _movement_sources(monkeypatch, apple_health=ah)
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": _d(-6), "end_date": TODAY})
    assert {r["movement_score"] for r in out["daily"]} == {67}
    assert out["summary"]["avg_movement_score"] == 67


def test_movement_step_coverage_is_published_when_the_field_is_missing(monkeypatch):
    """DI-1.4: an apple_health record can read fresh while the step field is
    absent. The tool reports the gap instead of scoring it as zero movement —
    the ADR-104 posture the rest of this file keeps finding missing elsewhere."""
    ah = [{"date": _d(-1), "steps": 9000, "active_calories": 400}, {"date": TODAY, "active_calories": 400}]
    _movement_sources(monkeypatch, apple_health=ah)
    out = TOOLS["get_daily_metrics"]["fn"]({"view": "movement", "start_date": _d(-1), "end_date": TODAY})
    assert out["summary"]["step_coverage_pct"] == 50.0
    assert out["summary"]["step_incomplete_dates"] == [TODAY]
    assert "steps" not in out["daily"][-1]


# ═══════════════════════════════════════════════════════════════════════════════
# §12 — Dead surface inside the module (ADR-103/144 complexity posture)
# ═══════════════════════════════════════════════════════════════════════════════

# Names defined in mcp/tools_lifestyle.py that nothing calls — derived by counting
# occurrences in the module's own source (a call site would push the count above
# the single definition) and confirmed by a repo-wide grep at authoring time.
_UNREFERENCED = ("_fetch_weather_range", "_is_traveling", "_load_bp_readings", "_tz_offset", "LEDGER_PK")


@pytest.mark.parametrize("name", _UNREFERENCED)
def test_module_carries_helpers_no_registered_tool_can_reach(name):
    """OBSERVED: ~150 lines of this 1,977-line module are unreachable — including
    ``_fetch_weather_range``, the ONLY outbound HTTP call and the only DynamoDB
    WRITE to the weather partition in the whole MCP package. Dead, but
    live-capable: nothing about it is disabled, it is simply never called."""
    import inspect

    source = inspect.getsource(tl)
    assert source.count(name) == 1, f"{name} now has a call site — remove it from the dead-surface list"


def test_the_dead_weather_helper_is_the_modules_only_outbound_http():
    """Pin the exposure: ``urllib.request`` is imported at module scope for a
    function no registered tool reaches."""
    import inspect

    source = inspect.getsource(tl)
    assert "import urllib.request" in source
    assert source.count("urllib.request.urlopen") == 1
