"""#2671 — get_sources must agree with the tools that actually query the data.

`get_sources` is the orientation call a session makes first, so a false negative here
closes a line of inquiry before it starts. Measured against live DynamoDB on 2026-08-15,
four of thirty sources disagreed with their own partitions:

    source          get_sources said                    the partition holds
    apple_health    available false, latest 2026-08-15   DATE# 2012-06-03 .. 2026-08-15
    dexa            available false                      DATE# 2025-05-10 .. 2026-03-30
    labs            available false                      DATE# 2019-05-01 .. 2026-04-03
    food_delivery   latest_date null                     newest DATE# is 2026-03-28

apple_health's row is self-refuting on its face — `available: false` beside a
`latest_date` of *today*.

THE FILED SET WAS ALMOST RIGHT AND THE FOURTH NAME WAS WRONG. The issue named
apple_health, labs, food_delivery and **strava**. Sweeping all 30 registered sources
against both query paths says the fourth is **dexa**: strava's partition edges are both
clean `DATE#` rows carrying a `date` attribute, so it always agreed. dexa is the worst of
the four — a year of body-composition scans reported as absent.

TWO CAUSES, both from asking the partition a different question than the domain tools ask.

1. The edge queries were unconstrained, so "oldest" and "newest" were whatever sorted
   first and last in the WHOLE partition — including rows that are not observations:

       apple_health   oldest  ALERTSTATE#ah_activity_degraded   (an operational marker)
       food_delivery  newest  YEAR#2026                         (a rollup)
       labs           newest  PROVIDER#function_health#2025-spring

   So apple_health's availability was decided by an alert-state row. Every domain tool
   ranges inside `DATE#` (`query_source` uses `sk.between("DATE#…", "DATE#…~")`); now
   this does too. That is the single truth source the issue asks for.

2. `available` keyed off the `date` ATTRIBUTE rather than the record's existence. That
   attribute duplicates the key's own date segment and is not always written — labs'
   oldest row is `DATE#2019-05-01` with no `date` field at all — so a present record read
   as absent. The date now comes from the sk, which is what the write built the key from.

The 2026-05-03 comment on the old code ("at least one source partition has a record
without a `date` field; was raising KeyError") had already SEEN this. It fixed the crash
with `.get()` and left the wrong answer behind — the exception became silence.

THE CROSS-CHECK IS THE TEST (acceptance box 3). `test_get_sources_agrees_with_the_domain_
tool_path_for_every_source` runs both paths over the same fixture for every source and
fails on any disagreement, rather than asserting four remembered values. The fixture rows
are the ones measured on the live table, marker sks included — a fixture of tidy `DATE#`
rows would have passed against the unfixed code.
"""

from __future__ import annotations

import os
import sys

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

from mcp import tools_data  # noqa: E402

USER_PREFIX = "USER#matthew#SOURCE#"

# Exactly the shapes the live table holds. Each entry: (sk, has_date_attribute).
PARTITIONS = {
    # available:false beside latest_date=today — decided by an ALERTSTATE marker row
    "apple_health": [("ALERTSTATE#ah_activity_degraded", False), ("DATE#2012-06-03", True), ("DATE#2026-08-15", True)],
    # a year of scans, reported absent
    "dexa": [("DATE#2025-05-10", True), ("DATE#2026-03-30", True)],
    # oldest DATE# row carries no `date` attribute; newest edge is a PROVIDER# row
    "labs": [("DATE#2019-05-01", False), ("DATE#2026-04-03", False), ("PROVIDER#function_health#2025-spring", False)],
    # newest edge is a YEAR# rollup, so latest_date came back null
    "food_delivery": [("DATE#2011-09-26#TXN#001", True), ("DATE#2026-03-28", False), ("YEAR#2026", False)],
    # the control: both edges are clean DATE# rows — this one always agreed
    "strava": [("DATE#2009-05-27", True), ("DATE#2026-08-10", True)],
    # the other control: genuinely empty
    "bluesky": [],
    # a declared-paused source with data that stopped
    "garmin": [("DATE#2022-04-25", True), ("DATE#2026-06-15", True)],
}


class FakeTable:
    """Honours `begins_with` and `between` on sk, plus ordering — the defect lives in the
    KEY CONDITION, so a stub that ignores it would test nothing."""

    def __init__(self, partitions):
        self.rows = []
        for src, entries in partitions.items():
            for sk, has_date in entries:
                row = {"pk": f"{USER_PREFIX}{src}", "sk": sk}
                if has_date and sk.startswith("DATE#"):
                    row["date"] = sk.split("DATE#", 1)[1][:10]
                self.rows.append(row)
        self.rows.sort(key=lambda r: (r["pk"], r["sk"]))

    def query(self, **kwargs):
        cond = kwargs["KeyConditionExpression"]
        expr = cond.get_expression()
        pk_cond, sk_cond = expr["values"]
        pk = pk_cond.get_expression()["values"][1]
        sk_expr = sk_cond.get_expression()
        op, vals = sk_expr["operator"], sk_expr["values"]
        matched = [r for r in self.rows if r["pk"] == pk]
        if op == "begins_with":
            matched = [r for r in matched if r["sk"].startswith(vals[1])]
        elif op == "BETWEEN":
            matched = [r for r in matched if vals[1] <= r["sk"] <= vals[2]]
        else:  # pragma: no cover — a third form would be a silent behaviour change
            raise AssertionError(f"unexpected sk operator: {op}")
        if not kwargs.get("ScanIndexForward", True):
            matched = list(reversed(matched))
        limit = kwargs.get("Limit")
        return {"Items": matched[:limit] if limit else matched}

    def get_item(self, **_kwargs):
        return {}


@pytest.fixture
def sources(monkeypatch):
    t = FakeTable(PARTITIONS)
    monkeypatch.setattr(tools_data, "table", t)
    monkeypatch.setattr(tools_data, "SOURCES", sorted(PARTITIONS))
    import mcp.core as core

    monkeypatch.setattr(core, "table", t)
    return t


def _domain_span(source):
    """What a DOMAIN tool sees: mcp.core.query_source's own DATE#-scoped range."""
    from mcp.core import query_source

    items = query_source(source, "1900-01-01", "2999-12-31")
    dates = sorted(str(i.get("date") or i["sk"].split("DATE#", 1)[1][:10])[:10] for i in items)
    return (dates[0], dates[-1]) if dates else (None, None)


# ── acceptance box 3: the cross-check, not four remembered values ────────────


def test_get_sources_agrees_with_the_domain_tool_path_for_every_source(sources):
    out = tools_data.tool_get_sources({})
    disagreements = []
    for source in sorted(PARTITIONS):
        first, last = _domain_span(source)
        row = out[source]
        if row["available"] != (last is not None) or row["first_date"] != first or row["latest_date"] != last:
            disagreements.append(f"{source}: get_sources={row} domain path first={first} last={last}")
    assert not disagreements, "get_sources contradicts the tools that query the data:\n  " + "\n  ".join(disagreements)


def test_the_fixture_would_have_caught_the_bug(sources):
    """Vacuity guard. A fixture of tidy DATE# rows passes against the unfixed code, so
    the marker rows that caused each live disagreement must actually be present."""
    marker_sks = {sk for entries in PARTITIONS.values() for sk, _ in entries if not sk.startswith("DATE#")}
    assert {"ALERTSTATE#ah_activity_degraded", "YEAR#2026"} <= marker_sks
    dateless = [sk for entries in PARTITIONS.values() for sk, has in entries if sk.startswith("DATE#") and not has]
    assert dateless, "a DATE# row with no `date` attribute is half the bug — keep one in the fixture"


# ── the four live cases, named ───────────────────────────────────────────────


def test_apple_health_is_not_self_refuting(sources):
    row = tools_data.tool_get_sources({})["apple_health"]
    assert row["available"] is True, "available:false beside a latest_date is a contradiction on its face"
    assert row["latest_date"] == "2026-08-15"
    assert row["first_date"] == "2012-06-03", "an ALERTSTATE marker is not the oldest observation"


def test_dexa_is_the_real_fourth_source(sources):
    """The issue named strava; the wire named dexa. A year of scans read as absent."""
    out = tools_data.tool_get_sources({})
    assert out["dexa"]["available"] is True
    assert (out["dexa"]["first_date"], out["dexa"]["latest_date"]) == ("2025-05-10", "2026-03-30")


def test_strava_was_never_wrong(sources):
    """The control that corrects the filed set — both its edges are clean DATE# rows."""
    out = tools_data.tool_get_sources({})
    assert (out["strava"]["first_date"], out["strava"]["latest_date"]) == ("2009-05-27", "2026-08-10")


def test_labs_survives_a_date_row_with_no_date_attribute(sources):
    """The sk is authoritative; the `date` attribute is a duplicate that is not always written."""
    row = tools_data.tool_get_sources({})["labs"]
    assert row["available"] is True
    assert (row["first_date"], row["latest_date"]) == ("2019-05-01", "2026-04-03")


def test_food_delivery_latest_is_not_swallowed_by_a_year_rollup(sources):
    assert tools_data.tool_get_sources({})["food_delivery"]["latest_date"] == "2026-03-28"


# ── acceptance box 4 + the controls ──────────────────────────────────────────


def test_an_empty_partition_is_still_reported_absent(sources):
    """A fix that calls everything available is not a fix."""
    row = tools_data.tool_get_sources({})["bluesky"]
    assert row["available"] is False
    assert row["first_date"] is None and row["latest_date"] is None


def test_a_paused_source_is_labelled_paused_not_absent(sources):
    """Acceptance box 4 — and the layer this needed, which is not where it looks.

    `resolve_source_state` alone answers `stale` for garmin. Its DECLARED_PAUSED_SOURCES
    is deliberately EMPTY, and its own comment says why: garmin's pause is registry-driven
    (source_registry `paused=True`, ADR-074), not declared there. So the `paused` facet has
    to be read from the registry, which is what the issue's fourth box actually asks for.
    """
    from ingestion.source_registry import qa_paused
    from ingestion.source_state import DECLARED_PAUSED_SOURCES, resolve_source_state

    assert "garmin" not in DECLARED_PAUSED_SOURCES, "precondition: the declared list is empty by design"
    assert "garmin" in {k for k, _ in qa_paused()}, "precondition: garmin is registry-paused (ADR-074)"
    assert resolve_source_state("garmin", "2026-06-15", "2026-08-15") == "stale", "precondition: the bare call says stale"

    row = tools_data.tool_get_sources({})["garmin"]
    assert row["available"] is True, "paused is not absent — the data is still on file"
    assert row["state"] == "paused"


def test_freshness_still_wins_over_the_paused_label(sources, monkeypatch):
    """A paused source that starts producing again must read `live` with no code change —
    otherwise the label suppresses exactly the re-enable it exists to describe."""
    fresh = FakeTable(
        {
            **PARTITIONS,
            "garmin": [("DATE#2022-04-25", True), ("DATE#" + tools_data.datetime.now(tools_data.timezone.utc).date().isoformat(), True)],
        }
    )
    monkeypatch.setattr(tools_data, "table", fresh)
    assert tools_data.tool_get_sources({})["garmin"]["state"] == "live"


def test_every_source_carries_a_state(sources):
    for source, row in tools_data.tool_get_sources({}).items():
        assert row.get("state") in {"live", "paused", "stale", "rate_limited"}, f"{source}: {row}"


def test_every_registered_source_appears_in_the_answer():
    """Derived from the live registry, not the fixture — a new source must not vanish."""
    from ingestion.source_registry import mcp_source_ids

    assert set(tools_data.SOURCES) == set(mcp_source_ids())
