"""tests/test_presence_food_registry_5955.py — a lull is never stated over days with food rows (#5955).

The presence record is a once-a-day snapshot (adaptive-mode, 17:35 UTC). MacroFactor arrives in
batched exports that land later and back-fill several days, so the stored record named a 3-day
lull over four days that already had food rows. /api/presence now re-checks the food registry at
read time: a food log inside the stated gap (or a failed registry read) fails closed to "present",
and the served `last_log_date` is the newest food row.

The guard: for every scenario, a served lull must have NO food row inside its stated gap.
The must-fail control: the same guard run over the STORED record (the pre-fix read path) flags it.
All values are synthetic.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from content import engagement_core as ec  # noqa: E402
from web import (
    site_api_data as sad,  # noqa: E402
    site_api_freshness as fresh,  # noqa: E402
)

_TODAY = "2026-07-14"


def _record(**over):
    """A synthetic stale public projection: food last logged on the 9th, quiet on the 13th."""
    pub = {
        "date": "2026-07-13",
        "presence_class": "quiet",
        "severity": "loud",
        "gap_days": 3,
        "last_food_log_date": "2026-07-09",
        "last_manual_log_date": "2026-07-09",
        "channels_quiet": ["food", "training"],
        "channels_quiet_count": 2,
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
        "experiment_window_start": "2026-06-01",
        "channel_detail": {
            "macrofactor": {"label": "food", "last_log_date": "2026-07-09", "gap_days": 3, "dropout_streak_days": 3},
        },
    }
    pub.update(over)
    return {"pk": "USER#matthew#SOURCE#engagement_state", "sk": "STATE#current", "date": pub["date"], "public": pub}


def _food_row(day, entries):
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{day}", "entries_count": entries}


class _Table:
    """get_item serves the presence record; query serves the macrofactor partition, honouring the
    sk BETWEEN bounds and paging one item at a time (so a single-page read would miss rows)."""

    def __init__(self, record, food_rows, fail_query=False):
        self.record = record
        self.rows = sorted(food_rows, key=lambda r: r["sk"])
        self.fail_query = fail_query
        self.queries = 0

    def get_item(self, Key=None):
        return {"Item": self.record} if self.record is not None else {}

    def query(self, **kw):
        self.queries += 1
        if self.fail_query:
            raise RuntimeError("synthetic throttle")
        cond = kw["KeyConditionExpression"]
        lo, hi = cond._values[1]._values[1], cond._values[1]._values[2]
        pk = cond._values[0]._values[1]
        rows = [r for r in self.rows if r["pk"] == pk and lo <= r["sk"] <= hi]
        start = kw.get("ExclusiveStartKey")
        if start:
            rows = [r for r in rows if r["sk"] > start["sk"]]
        page = rows[:1]
        resp = {"Items": [{"sk": r["sk"], "entries_count": r["entries_count"]} for r in page]}
        if len(rows) > 1:
            resp["LastEvaluatedKey"] = {"pk": pk, "sk": page[0]["sk"]}
        return resp


def _serve(monkeypatch, table):
    monkeypatch.setattr(sad, "table", table)
    monkeypatch.setattr(fresh, "pacific_today", lambda: _TODAY)
    resp = sad.handle_presence()
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def _lull_offenders(served, food_rows):
    """THE guard: food-log days inside a served lull's stated gap. A served lull must have none."""
    if served.get("presence_class") not in ec.LOUD_CLASSES:
        return []
    logged = [r["sk"][5:15] for r in food_rows if ec.public_counts_as_logged(ec.PRIMARY_CHANNEL, r)]
    return ec.food_logs_inside_stated_gap(
        {
            "last_food_log_date": served.get("last_log_date") or served.get("last_food_log_date"),
            "experiment_window_start": served.get("experiment_window_start"),
        },
        logged,
    )


_BACKFILL = [_food_row(d, n) for d, n in (("2026-07-08", 9), ("2026-07-09", 12), ("2026-07-10", 3), ("2026-07-11", 10), ("2026-07-13", 1))]
_STUBS = [_food_row("2026-07-08", 9), _food_row("2026-07-09", 12), _food_row("2026-07-10", 0), _food_row("2026-07-11", 0)]

_SCENARIOS = {
    # name: (record, food rows, expected served class, expected last_log_date)
    "backfilled export after the compute": (_record(), _BACKFILL, "present", "2026-07-13"),
    "only stub rows after the last log": (_record(), _STUBS, "quiet", "2026-07-09"),
    "registry agrees with the record": (_record(), _BACKFILL[:2], "quiet", "2026-07-09"),
    "no food log this cycle, a log on the window start": (
        _record(last_food_log_date=None, gap_days=40, presence_class="dark", experiment_window_start="2026-07-11"),
        [_food_row("2026-07-11", 4)],
        "present",
        "2026-07-11",
    ),
}


def test_no_served_lull_over_food_rows(monkeypatch):
    """Every scenario: a served lull has no food row inside its gap, and the served class and
    last_log_date are the registry's. Reports every offender, not the first."""
    bad = []
    for name, (record, rows, want_cls, want_last) in _SCENARIOS.items():
        body = _serve(monkeypatch, _Table(record, rows))
        offenders = _lull_offenders(body, rows)
        if offenders:
            bad.append(f"{name}: lull {body['presence_class']!r} stated over food rows {offenders}")
        if body["presence_class"] != want_cls or body["last_log_date"] != want_last:
            bad.append(f"{name}: served {body['presence_class']}/{body['last_log_date']}, want {want_cls}/{want_last}")
        if body["in_lull"] != (want_cls in ec.LOUD_CLASSES):
            bad.append(f"{name}: in_lull {body['in_lull']} disagrees with class {body['presence_class']}")
    assert not bad, "\n".join(bad)


def test_must_fail_control_the_stored_record_is_flagged():
    """The guard has teeth: run over the STORED (pre-fix, unreconciled) record it names the
    back-filled days. If this ever returns [] the guard above proves nothing."""
    record, rows, _, _ = _SCENARIOS["backfilled export after the compute"]
    stored = dict(record["public"], last_log_date=record["public"]["last_food_log_date"])
    assert _lull_offenders(stored, rows) == ["2026-07-10", "2026-07-11", "2026-07-13"]


def test_backfill_reconciles_every_food_mark(monkeypatch):
    body = _serve(monkeypatch, _Table(_record(), _BACKFILL))
    assert body["gap_days"] == 0  # newest log 07-13, today 07-14: inside the 24 h grace
    assert body["in_lull"] is False
    assert body["channels_quiet_count"] == 1  # food left the quiet list; training stays
    food = next(c for c in body["channels"] if c["id"] == "macrofactor")
    assert food["last_log_date"] == "2026-07-13" and food["gap_days"] == 0 and food["quiet"] is False


def test_registry_read_reads_every_page(monkeypatch):
    """The fake pages one row at a time; the newest row is only on the last page."""
    table = _Table(_record(), _BACKFILL)
    body = _serve(monkeypatch, table)
    assert body["last_log_date"] == "2026-07-13"
    assert table.queries >= 3


def test_failed_registry_read_fails_closed_to_present(monkeypatch):
    body = _serve(monkeypatch, _Table(_record(), _BACKFILL, fail_query=True))
    assert body["presence_class"] == "present" and body["in_lull"] is False


def test_present_record_is_untouched_by_a_failed_read(monkeypatch):
    body = _serve(monkeypatch, _Table(_record(presence_class="present", gap_days=0), [], fail_query=True))
    assert body["presence_class"] == "present" and body["last_log_date"] == "2026-07-09"


def test_reconcile_never_mutates_its_input():
    rec = _record()["public"]
    snapshot = json.dumps(rec, sort_keys=True)
    ec.reconcile_presence_with_food_registry(rec, ["2026-07-12"], _TODAY)
    assert json.dumps(rec, sort_keys=True) == snapshot


def test_compute_log_dates_reads_every_page(monkeypatch):
    """The compute side: `_log_dates` pages through the window (DynamoDB's 1 MB page is measured
    before projection and a MacroFactor row carries its diary, so a first-page read drops the
    NEWEST days). The fake returns one item per page; the newest day must still be counted."""
    from compute import adaptive_mode_lambda as am

    rows = [{"sk": f"DATE#2026-07-{d:02d}", "entries_count": 5} for d in (10, 11, 12, 13)]

    class _PagedTable:
        def query(self, **kw):
            start = (kw.get("ExclusiveStartKey") or {}).get("sk", "")
            rest = [r for r in rows if r["sk"] > start]
            resp = {"Items": rest[:1]}
            if len(rest) > 1:
                resp["LastEvaluatedKey"] = {"sk": rest[0]["sk"]}
            return resp

    monkeypatch.setattr(am, "table", _PagedTable())
    assert am._log_dates("macrofactor", _TODAY, attrs=("entries_count",)) == ["2026-07-13", "2026-07-12", "2026-07-11", "2026-07-10"]
