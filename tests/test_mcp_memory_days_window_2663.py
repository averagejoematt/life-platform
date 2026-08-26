"""#2663 — `list_memory_categories(days=N)` filtered on the wrong segment of the sort key.

Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    list_memory_categories {"days": 1}    -> baseline_snapshot, latest_date 2026-05-03
    list_memory_categories {"days": 3650} -> byte-for-byte the same result
    list_memory_categories {"days": -1}   -> validation error (already fixed by #2659)

A one-day window returned a record from three months earlier, and a ten-year window
returned nothing more. The issue called `days` decorative. It is worse than decorative:
the filter ran, against the wrong thing.

    sk  = "MEMORY#<category>#<date>"                    (mcp.tools_memory._memory_sk)
    key = sk BETWEEN "MEMORY#<start-date>" AND "MEMORY#~"

The bound after `MEMORY#` is a DATE; the segment it is compared against is a CATEGORY
NAME. Every category ('b'…'w') sorts above any "2026-…" and below "~", so the range
matched the whole partition for every possible value of `days`. The same expression
would have silently EXCLUDED a category the day one was named with a leading digit —
a filter that is inert today and wrong tomorrow, with no error either way.

Date cannot be range-queried from this key at all, so the fix reads the partition and
applies the window after. Two things that came with it, because the read had to change
anyway and both are the same honesty class:

  * `LastEvaluatedKey` was never followed — `total_records` was a PAGE count published
    as a corpus count (the #2221 defect in a second tool). Now paginated, with
    `records_scanned` and `scan_exhausted` naming what was actually counted (ADR-104).
  * the date fell back to `""` when the duplicate `date` attribute was absent, which
    sorts below every window start — such a row would have been silently dropped from
    every window. It now falls back to the sk's own last segment, which is where the
    date came from in the first place.

These are unit tests over a fake table: the real defect is in the KEY EXPRESSION and
the post-filter, so the fixture models DynamoDB's actual `begins_with` + pagination
semantics rather than the tool's assumptions about them. The pre-fix key expression is
replayed against the same fixture in `test_the_old_key_expression_matched_everything`,
so the mechanism is proven here and not merely asserted in a comment.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from pacific_clock import freeze_pacific  # #2817: the Pacific clock a converted module actually reads

from mcp import tools_memory  # noqa: E402
from mcp.handler import _validate_tool_args  # noqa: E402

# #2223: FROZEN, not `datetime.now()`. The tool reads its OWN clock at call time, so a
# module-level wall-clock sample taken at import would desync from it on a CI run that
# crosses midnight — and every window assertion here is relative to "today". The
# `_frozen_clock` fixture pins the tool to this same instant, so the two cannot drift.
TODAY = date(2026, 8, 15)
_FROZEN_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102 — mirrors datetime.now's signature
        return _FROZEN_NOW if tz else _FROZEN_NOW.replace(tzinfo=None)


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# The corpus the live partition actually looks like: a handful of categories whose
# records span months, which is exactly the shape that made the bug invisible.
CORPUS = [
    ("baseline_snapshot", _d(104)),
    ("coaching_calibration", _d(6)),
    ("constraints_preferences", _d(6)),
    ("failure_patterns", _d(5)),
    ("what_worked", _d(0)),
    ("what_worked", _d(200)),
]


class FakeTable:
    """Models the DynamoDB semantics the tool depends on: sk ordering, begins_with,
    BETWEEN, and paged results. Deliberately NOT a stub that returns a canned list —
    the defect lives in the key expression, so the key expression has to be honoured."""

    def __init__(self, rows, page_size=2):
        self.rows = sorted(rows, key=lambda r: r["sk"])
        self.page_size = page_size
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        expr = kwargs["KeyConditionExpression"]
        vals = kwargs["ExpressionAttributeValues"]
        if "begins_with(sk" in expr:
            matched = [r for r in self.rows if r["sk"].startswith(vals[":p"])]
        elif "BETWEEN" in expr:
            matched = [r for r in self.rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        else:  # pragma: no cover — a third form would be a silent behaviour change
            raise AssertionError(f"unexpected key expression: {expr}")
        start = 0
        if kwargs.get("ExclusiveStartKey"):
            last = kwargs["ExclusiveStartKey"]["sk"]
            start = next(i for i, r in enumerate(matched) if r["sk"] == last) + 1
        page = matched[start : start + self.page_size]
        out = {"Items": page}
        if start + self.page_size < len(matched):
            out["LastEvaluatedKey"] = {"sk": page[-1]["sk"]}
        return out


def _rows(corpus=CORPUS, drop_date_attr=()):
    rows = []
    for cat, day in corpus:
        row = {"sk": f"MEMORY#{cat}#{day}", "category": cat}
        if (cat, day) not in drop_date_attr:
            row["date"] = day
        rows.append(row)
    return rows


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """Pin the tool's clock to the same instant TODAY was built from (#2223)."""
    monkeypatch.setattr(tools_memory, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, tools_memory, _FrozenDatetime)  # #2817: pin the PACIFIC helpers this module now calls


@pytest.fixture
def table(monkeypatch):
    t = FakeTable(_rows())
    monkeypatch.setattr(tools_memory, "_get_table", lambda: t)
    monkeypatch.setattr(tools_memory._pm, "taxonomy_summary", lambda: {})
    return t


def _cats(result):
    return {c["category"]: c["count"] for c in result["categories"]}


# ── the defect ───────────────────────────────────────────────────────────────


def test_the_old_key_expression_matched_everything_whatever_days_said():
    """Proof of mechanism, replayed against the same fixture: the pre-fix bound was inert."""
    t = FakeTable(_rows(), page_size=100)
    for days in (1, 30, 365, 3650):
        start = (TODAY - timedelta(days=days)).isoformat()
        got = t.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": "x", ":s": f"MEMORY#{start}", ":e": "MEMORY#~"},
        )
        assert len(got["Items"]) == len(CORPUS), f"days={days} was expected to be inert pre-fix"


def test_a_category_name_sorting_below_the_date_bound_would_have_been_silently_dropped():
    """The other half of the same bug: inert today, wrong the day a category is renamed.

    The name is derived, not literal: any category sorting below "MEMORY#<start-date>"
    vanishes. `{year-10}_archive` is guaranteed to be one, whatever year this runs in —
    note that a name merely *starting* with a digit is not enough (`2fa_recovery` sorts
    ABOVE `2026-…`, because 'f' > '0'), which is precisely why this is a landmine rather
    than a visible rule.
    """
    doomed = f"{TODAY.year - 10}_archive"
    t = FakeTable(_rows(corpus=CORPUS + [(doomed, _d(0))]), page_size=100)
    got = t.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
        ExpressionAttributeValues={":pk": "x", ":s": f"MEMORY#{_d(90)}", ":e": "MEMORY#~"},
    )
    assert not any(r["sk"].startswith(f"MEMORY#{doomed}") for r in got["Items"]), "precondition: this name must sort below the bound"

    # …and the fix does not have that hole, because it does not range on the name at all.
    fixed = t.query(KeyConditionExpression="pk = :pk AND begins_with(sk, :p)", ExpressionAttributeValues={":pk": "x", ":p": "MEMORY#"})
    assert any(r["sk"].startswith(f"MEMORY#{doomed}") for r in fixed["Items"])


# ── the fix ──────────────────────────────────────────────────────────────────


def test_a_narrow_window_excludes_older_records(table):
    result = tools_memory.tool_list_memory_categories({"days": 7})
    assert "baseline_snapshot" not in _cats(result), f"104-day-old record inside a 7-day window: {_cats(result)}"
    assert _cats(result)["what_worked"] == 1, "only the same-day what_worked belongs in a 7-day window"


def test_two_different_days_values_produce_different_results(table):
    """The issue's own third acceptance box."""
    narrow = tools_memory.tool_list_memory_categories({"days": 7})
    wide = tools_memory.tool_list_memory_categories({"days": 365})
    assert _cats(narrow) != _cats(wide)
    assert narrow["total_records"] < wide["total_records"]


def test_the_widest_window_still_reaches_every_record(table):
    """The control. A window fix that under-returns is not a fix."""
    result = tools_memory.tool_list_memory_categories({"days": 365})
    assert result["total_records"] == len(CORPUS), "a 365-day window contains every row in the fixture"
    assert _cats(result)["what_worked"] == 2, "both what_worked rows (day 0 and day 200) are in range"


def test_the_default_window_is_ninety_days(table):
    result = tools_memory.tool_list_memory_categories({})
    assert result["lookback_days"] == 90
    assert "baseline_snapshot" not in _cats(result), "the 104-day-old record is outside the default window"


def test_the_response_states_the_window_it_applied(table):
    result = tools_memory.tool_list_memory_categories({"days": 30})
    assert result["window_start"] == _d(30)
    assert result["lookback_days"] == 30


# ── what came with it ────────────────────────────────────────────────────────


def test_the_scan_is_paginated_and_counts_are_labelled(table):
    """Pre-fix this read one 2-item page and published it as the corpus (#2221's class)."""
    result = tools_memory.tool_list_memory_categories({"days": 365})
    assert len(table.calls) > 1, "LastEvaluatedKey was not followed"
    assert result["records_scanned"] == len(CORPUS)
    assert result["scan_exhausted"] is True
    assert result["total_records"] <= result["records_scanned"]


def test_a_row_missing_the_duplicate_date_attribute_is_dated_from_its_key(monkeypatch):
    """`""` sorts below every window start — such a row vanished from every window."""
    t = FakeTable(_rows(drop_date_attr={("what_worked", _d(0))}))
    monkeypatch.setattr(tools_memory, "_get_table", lambda: t)
    monkeypatch.setattr(tools_memory._pm, "taxonomy_summary", lambda: {})
    result = tools_memory.tool_list_memory_categories({"days": 7})
    assert _cats(result).get("what_worked") == 1, "a row without a `date` attribute was dropped"


def test_the_page_cap_is_reported_not_hidden(monkeypatch):
    """A truncated scan must say so rather than publish a floor as a total."""
    big = [(f"cat_{i:03d}", _d(1)) for i in range(200)]
    t = FakeTable(_rows(corpus=big), page_size=1)
    monkeypatch.setattr(tools_memory, "_get_table", lambda: t)
    monkeypatch.setattr(tools_memory._pm, "taxonomy_summary", lambda: {})
    result = tools_memory.tool_list_memory_categories({"days": 7})
    assert len(table_calls := t.calls) == tools_memory._MEMORY_MAX_PAGES, table_calls
    assert result["scan_exhausted"] is False


# ── the boundary ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad,why", [(0, "at least 1"), (-1, "at least 1"), (3650, "at most 365")])
def test_an_out_of_range_days_is_refused_not_clamped(bad, why):
    """Acceptance box 2. `min(max(1, days), 365)` silently answered a different question."""
    err = _validate_tool_args("list_memory_categories", {"days": bad})
    assert err is not None and why in err, f"days={bad} -> {err!r}"


def test_a_valid_days_still_passes():
    assert _validate_tool_args("list_memory_categories", {"days": 30}) is None
