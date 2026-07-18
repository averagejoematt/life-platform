"""tests/test_source_freshness_cross_phase_1203.py — #1203 freshness reads liveness cross-phase.

The public freshness board must report a source's TRUE last-update date and
"dark N days" count even when that source's newest DATE# record predates the
current experiment cycle. After a reset, all pre-genesis records are tagged
phase=pilot (ADR-077) — so a source that has genuinely gone dark (e.g. MacroFactor
dark since 2026-06-24) had its real last-write date phase-filtered OUT of the
freshness read, rendering last_update:null / days_dark:null on the public board
exactly when the lapse is longest. Freshness is pipe/behavior LIVENESS (a "dark N
days" signal about real recency regardless of experiment phase); the sources on
this board are RAW_TIMESERIES (cross_phase), so the read must span cycles — matching
the operator checker (freshness_checker_lambda.py, no phase filter) and the
deliberate include_pilot=True device-agreement read.

The fake table below is faithful to real DynamoDB semantics: Limit is applied
BEFORE FilterExpression. That is what makes this guard non-vacuous — a phase-filtered
Limit:1 read fetches the single newest DATE# then filters it out as phase!=current,
returning EMPTY (the #1203 blindfold); include_pilot=True bypasses the filter and
returns the real record. The prior #746 fixture (_FreshnessFakeTable) ignored the
FilterExpression entirely and so could not exercise this path.
"""

import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from phase_filter import with_phase_filter  # noqa: E402
from web import site_api_data as sad  # noqa: E402

# A source whose ONLY DATE# record predates the current cycle and is tagged
# phase=pilot — the post-reset state described in #1203. Pinned far in the past
# (like the #746 fixture) so the record is definitively stale past every source's
# window and days_dark > 0 regardless of the wall clock — no golden-date time bomb.
# The real-world evidence was MacroFactor at DATE#2026-06-24; the mechanism (a
# pre-genesis phase=pilot record hidden by the filter) is identical.
_PILOT_DATE = "2020-01-01"


class _PilotOnlyTable:
    """Faithful mini-DynamoDB for a partition whose newest (and only) DATE# record
    is phase=pilot. Reproduces the engine's Limit-then-FilterExpression ordering so
    a phase-filtered read returns EMPTY while an include_pilot read returns the row."""

    def query(self, **kwargs):
        items = [{"sk": f"DATE#{_PILOT_DATE}", "phase": "pilot"}]
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]  # DDB applies Limit BEFORE the FilterExpression
        fe = kwargs.get("FilterExpression")
        vals = kwargs.get("ExpressionAttributeValues") or {}
        if fe and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [it for it in items if it.get("phase") in (None, current)]
        return {"Items": items}

    def get_item(self, Key=None):
        return {}  # no HAE datatype-liveness sentinel


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def test_fake_table_models_the_phase_blindfold():
    """Non-vacuous anchor: the fixture faithfully models the bug. A default
    (phase-filtered) Limit:1 read of a pilot-only partition returns EMPTY — which is
    exactly why the old code produced last_update:null. include_pilot=True restores
    the real record. If either assertion flips, the guard below no longer bites."""
    t = _PilotOnlyTable()
    filtered = with_phase_filter({"Limit": 1})
    assert t.query(**filtered).get("Items") == [], "phase filter must blind a pilot-only Limit:1 read"
    passed = with_phase_filter({"Limit": 1}, include_pilot=True)
    assert t.query(**passed).get("Items") == [{"sk": f"DATE#{_PILOT_DATE}", "phase": "pilot"}]


def test_source_freshness_reports_true_last_update_for_pilot_only_source(monkeypatch):
    """The regression guard from the issue: a manual source whose only records are
    phase=pilot must render non-null last_update, stale_hours, and days_dark > 0."""
    monkeypatch.setattr(sad, "table", _PilotOnlyTable())
    body = _body(sad.handle_source_freshness())
    by = {s["id"]: s for s in body["sources"]}

    md = by["measurements"]  # a manual (MCP) source per #746
    assert md["last_update"] == _PILOT_DATE, "true last-update date must survive the phase filter"
    assert md["age_hours"] is not None and md["age_hours"] > 0
    assert md["stale_hours"] is not None
    assert md["status"] == "behavioral-stale"  # behavioral — never a broken-pipe stamp
    assert isinstance(md["days_dark"], int) and md["days_dark"] > 0

    # food_delivery is the other pre-cycle-dark manual source called out in the issue.
    fd = by["food_delivery"]
    assert fd["last_update"] == _PILOT_DATE
    assert isinstance(fd["days_dark"], int) and fd["days_dark"] > 0


def test_last_sync_reports_true_last_seen_for_pilot_only_source(monkeypatch):
    """The same-basis pulse read (/api/last_sync) must also span cycles, or the
    cockpit sync line masks a genuinely dark pipe with last_seen:null."""
    monkeypatch.setattr(sad, "table", _PilotOnlyTable())
    body = _body(sad.handle_last_sync())
    by = {s["id"]: s for s in body["sources"]}

    md = by["measurements"]
    assert md["last_seen"] is not None, "pulse must report the true last write across phases"
    assert md["precision"] == "day"
    assert md["status"] in ("stale", "behavioral-stale")


def test_days_dark_from_pilot_date_is_positive():
    """Sanity: the fixture date is far enough past that days_dark is always > 0,
    independent of the wall clock (no golden-date time bomb)."""
    now = datetime.now(timezone.utc)
    assert sad._days_dark(_PILOT_DATE, now) > 0
