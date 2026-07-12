"""tests/test_month_rollup_1115.py — /api/month_rollup contract (#1115).

The integrator's month-altitude rollup: written weekly by ai-expert-analyzer
from the trailing ~4 weekly lab notes, served read-only here. The contract under
test is the HONESTY surface (ADR-104):

  * pre-start        → null narrative + the countdown meta (never a wiped
                       cycle's rollup presented as current)
  * nothing written  → null narrative, pre_start False (the designed
                       early-cycle empty state — the front-end renders its
                       honest-empty copy)
  * tombstoned       → null (a reset's wipe is respected on the get_item path)
  * stale cycle      → a record whose days_in_experiment outruns the live day
                       count is withheld (Stage0 Fix 3 semantics)
  * happy path       → narrative + headline + attribution served

Plus the generator's honest-skip: fewer than 2 week notes in the window → no
call, no write, None. All offline; genesis dates derive from now(PT).
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as coach, site_api_common as common  # noqa: E402


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _set_genesis(monkeypatch, iso):
    for mod in (common, coach):
        monkeypatch.setattr(mod, "EXPERIMENT_START", iso)


def _future(monkeypatch, days=2):
    start = _today_pt() + timedelta(days=days)
    _set_genesis(monkeypatch, _iso(start))
    return _iso(start)


def _past(monkeypatch, days=30):
    start = _today_pt() - timedelta(days=days)
    _set_genesis(monkeypatch, _iso(start))
    return _iso(start)


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _rollup_row(**over):
    row = {
        "pk": f"{coach.USER_PREFIX}ai_analysis",
        "sk": "EXPERT#integrator_month",
        "expert_key": "integrator_month",
        "narrative": "Four weeks of the same honest pattern: training held, logging wobbled.",
        "headline": "A month of holding the line",
        "week_count": 4,
        "window_label": "2026-06-15 to 2026-07-12",
        "days_in_experiment": 28,
        "generated_at": "2026-07-12T14:00:00+00:00",
    }
    row.update(over)
    return row


def test_pre_start_null_with_countdown(monkeypatch):
    start = _future(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_rollup_row()]))
    b = _body(coach.handle_month_rollup())
    assert b["pre_start"] is True
    assert b["start_date"] == start
    assert b["narrative"] is None  # the stored rollup predates the staged genesis


def test_nothing_written_yet_is_honest_null(monkeypatch):
    _past(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[]))
    b = _body(coach.handle_month_rollup())
    assert b["pre_start"] is False
    assert b["narrative"] is None
    assert "headline" not in b or b.get("headline") is None


def test_tombstoned_record_withheld(monkeypatch):
    _past(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_rollup_row(tombstone=True)]))
    b = _body(coach.handle_month_rollup())
    assert b["narrative"] is None


def test_stale_cycle_record_withheld(monkeypatch):
    # genesis 10 days ago but the record claims day 28 → a prior cycle's rollup
    _past(monkeypatch, days=9)  # day_n = 10
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_rollup_row(days_in_experiment=28)]))
    b = _body(coach.handle_month_rollup())
    assert b["pre_start"] is False
    assert b["narrative"] is None


def test_happy_path_serves_narrative_and_attribution(monkeypatch):
    _past(monkeypatch, days=40)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_rollup_row()]))
    b = _body(coach.handle_month_rollup())
    assert b["pre_start"] is False
    assert b["narrative"].startswith("Four weeks")
    assert b["headline"] == "A month of holding the line"
    assert b["week_count"] == 4
    assert b["window_label"] == "2026-06-15 to 2026-07-12"
    assert b["coach_name"] == "Dr. Kai Nakamura"


def test_route_registered():
    from web import site_api_lambda as lam

    assert lam.ROUTES.get("/api/month_rollup") is coach.handle_month_rollup


# ── the generator's honest-skip (offline; no model call) ─────────────────────


def test_generator_skips_below_two_week_notes(monkeypatch):
    from intelligence import ai_expert_analyzer_lambda as axa

    class _OneWeekTable:
        def query(self, **kw):
            return {"Items": [{"week": 1, "week_label": "Week 1", "ai_tone": "steady"}]}

        def put_item(self, Item):  # pragma: no cover — must not be reached
            raise AssertionError("skip path must not write")

    monkeypatch.setattr(axa, "table", _OneWeekTable())
    monkeypatch.setattr(axa, "_get_api_key", lambda: (_ for _ in ()).throw(AssertionError("skip path must not fetch a key")))
    assert axa.generate_month_rollup() is None
