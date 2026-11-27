"""#6271 — the public tier-0 figures read a projection, and the figures do not move.

`web.site_api_habits.public_tier0_summary` (#6224) read every Habitify row in its window WHOLE: about 21 KB a row,
of which the tier-0 predicate needs only the statuses of the registry's tier-0 habits. #6271 adds a
`ProjectionExpression` (`_tier0_projection`) for the row key, the date and those statuses, each unchanged.
The predicate (`activity_publication.public_tier0_counts` / `public_tier0_figures`) is untouched.

The parity proof: `_reference_public_tier0_summary` below is the whole-row read exactly as it stood before #6271.
Every case runs both against one fake table that applies a projection, a page boundary and the phase filter the way
DynamoDB does (the boundary falls on items READ, before the projection), and requires identical output, both from
the summary and from the `/api/habit_streaks` handler. A seeded random sweep covers many generated histories.

Dates are literals: nothing here reads the clock except the one test that pins it.
"""

from __future__ import annotations

import copy
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

from boto3.dynamodb.conditions import Key  # noqa: E402
from common import (
    activity_publication as AP,  # noqa: E402
    restraint_publication as RP,  # noqa: E402
)
from common.query_pages import query_pages  # noqa: E402
from experiment import phase_filter  # noqa: E402
from experiment.phase_filter import with_phase_filter  # noqa: E402
from web import site_api_habits as H  # noqa: E402
from web.site_api_common import USER_ID, USER_PREFIX, _decimal_to_float  # noqa: E402

U = f"USER#{USER_ID}"
HAB = f"{USER_PREFIX}habitify"
SCORES = f"{USER_PREFIX}habit_scores"
AS_OF = "2026-03-15"
RESTRAINT_GROUP = sorted(RP.RESTRAINT_GROUPS)[0]
CURRENT_PHASE = phase_filter.PHASE_FILTER_VALUES[":phase_experiment"]
JOURNAL_ID = sorted(h for h, fam in AP.HABIT_FAMILIES.items() if fam[1] == "journal_presence")[0]


# ── the reference: the read exactly as it stood before #6271 (whole rows) ─────────────────────────────


def _reference_public_tier0_summary(table, as_of: str, start: str, *, streak_names=None):
    prof = table.query(KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}") & Key("sk").eq("PROFILE#v1"), Limit=1)
    registry = ((prof.get("Items") or [{}])[0] or {}).get("habit_registry") or {}
    latest_scores = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}habit_scores"), ScanIndexForward=False, Limit=1)
    streak_map = ((latest_scores.get("Items") or [{}])[0] or {}).get("vice_streaks") or {}
    rows = _decimal_to_float(
        query_pages(
            table,
            **with_phase_filter(
                {  # ADR-058: hide pilot habitify records
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}habitify") & Key("sk").between(f"DATE#{start}", f"DATE#{as_of}"),
                    "ScanIndexForward": False,
                }
            ),
        ).get("Items", [])
    )
    restraints = {str(n) for n in (streak_names or ())} | {str(k) for k in streak_map}
    return AP.public_tier0_figures(rows, registry, restraints, as_of, start)


# ── a fake table that behaves like DynamoDB where it matters here ────────────────────────────────────


def _key_bounds(cond) -> dict:
    out: dict = {}
    if isinstance(cond, str):  # "pk = :pk" (the handler's own habit_scores read)
        out["pk_ref"] = cond.split("=")[1].strip()
        return out
    expr = cond.get_expression()
    for part in expr["values"] if expr["operator"] == "AND" else [cond]:
        e = part.get_expression()
        name, vals = e["values"][0].name, e["values"][1:]
        if name == "pk":
            out["pk"] = vals[0]
        elif e["operator"] == "=":
            out["sk_eq"] = vals[0]
        else:
            out["sk_range"] = (vals[0], vals[1])
    return out


def _project(item: dict, expr: str, names: dict) -> dict:
    """DynamoDB's projection: each document path copied when it exists; a path through a non-map is skipped."""
    out: dict = {}
    for path in (p.strip() for p in expr.split(",")):
        parts = [names.get(p, p) for p in path.split(".")]
        node, ok = item, True
        for p in parts:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                ok = False
                break
        if not ok:
            continue
        dst = out
        for p in parts[:-1]:
            dst = dst.setdefault(p, {})
        dst[parts[-1]] = copy.deepcopy(node)
    return out


class FakeTable:
    """Query-only. ``page_items`` items READ per page (the 1 MB boundary falls before the projection), the phase
    filter after the page is read, then the projection. Records every call's arguments."""

    def __init__(self, rows, page_items: int = 1000, fail_on: str | None = None):
        self.rows = [json.loads(json.dumps(r, default=str), parse_float=Decimal) for r in rows]
        self.page_items = page_items
        self.fail_on = fail_on
        self.calls: list = []

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, Limit=None, ExclusiveStartKey=None, **kw):
        self.calls.append(dict(kw, KeyConditionExpression=KeyConditionExpression, ScanIndexForward=ScanIndexForward, Limit=Limit))
        b = _key_bounds(KeyConditionExpression)
        pk = b.get("pk") or (kw.get("ExpressionAttributeValues") or {}).get(b.get("pk_ref"))
        if self.fail_on and pk == self.fail_on:
            raise RuntimeError("simulated read failure")
        items = [r for r in self.rows if r["pk"] == pk]
        if "sk_eq" in b:
            items = [r for r in items if r["sk"] == b["sk_eq"]]
        if "sk_range" in b:
            items = [r for r in items if b["sk_range"][0] <= r["sk"] <= b["sk_range"][1]]
        items.sort(key=lambda r: r["sk"], reverse=not ScanIndexForward)
        if ExclusiveStartKey:
            sks = [r["sk"] for r in items]
            items = items[sks.index(ExclusiveStartKey["sk"]) + 1 :]
        cap = min(self.page_items, int(Limit)) if Limit else self.page_items
        page, more = items[:cap], len(items) > cap
        if "#phase" in str(kw.get("FilterExpression") or ""):
            page = [r for r in page if r.get("phase") in (None, CURRENT_PHASE)]
        if kw.get("ProjectionExpression"):
            page = [_project(r, kw["ProjectionExpression"], kw.get("ExpressionAttributeNames") or {}) for r in page]
        resp = {"Items": copy.deepcopy(page), "Count": len(page)}
        if more:
            last = items[cap - 1]
            resp["LastEvaluatedKey"] = {"pk": last["pk"], "sk": last["sk"]}
        return resp

    def get_item(self, **_kw):
        raise AssertionError("public_tier0_summary must read through Query only")


# ── synthetic histories ──────────────────────────────────────────────────────────────────────────────


def _day(offset: int, as_of: str = AS_OF) -> str:
    return (date.fromisoformat(as_of) - timedelta(days=offset)).isoformat()


def _status(done: bool, *, group="Core", hid="", scheduled=True, **extra) -> dict:
    st = {
        "status": "completed" if done else "not_completed",
        "scheduled_today": scheduled,
        "group": group,
        "periodicity": "daily",
        "current_value": Decimal(1) if done else Decimal(0),
        "target_value": Decimal(1),
        "completed_at": "2026-01-01T08:00:00Z" if done else None,
        "miss_source": None if done else "synthetic",
        "status_channel": "synthetic",
        "aliases": ["synthetic alias"],
        "notes": "synthetic private note",
    }
    if hid:
        st["habit_id"] = hid
    st.update(extra)
    return st


def _registry() -> dict:
    return {
        "habit_a": {"tier": Decimal(0), "publication": "public"},
        "habit_b": {"tier": "0", "publication": "public"},
        "habit_c": {"tier": 1, "publication": "public"},  # tier 1: never counts
        "habit_d": {"tier": 0, "publication": "private"},  # owner-declared private
        "habit_e": {"tier": 0, "publication": "public", "status": "archived"},  # inactive in the registry
        "restraint_a": {"tier": 0, "publication": "public"},  # a restraint by its tracker group / streak key
        "restraint_b": {"tier": 0, "publication": "public", RP.REGISTRY_FLAG: True},  # by the registry flag
    }


def _row(d: str, statuses: dict, **extra) -> dict:
    row = {
        "pk": HAB,
        "sk": f"DATE#{d}",
        "date": d,
        "phase": CURRENT_PHASE,
        "habit_statuses": statuses,
        "by_group": {"Core": Decimal(50)},
        "habits": ["synthetic"],
        "completion_pct": Decimal(50),
    }
    row.update(extra)
    return row


def _statuses(ok: bool = True, *, restraint_done: bool = True, archived_done: bool = True) -> dict:
    return {
        "habit_a": _status(ok),
        "habit_b": _status(True),
        "habit_c": _status(False),
        "habit_d": _status(False),
        "habit_e": _status(archived_done),
        "habit_x": _status(False),  # not in the registry: never counts
        "restraint_a": _status(restraint_done, group=RESTRAINT_GROUP.title()),
        "restraint_b": _status(restraint_done),
    }


def _table(days: dict, *, registry=None, streaks=None, extra_rows=(), page_items: int = 1000, fail_on=None) -> FakeTable:
    """``days`` maps an offset from AS_OF to that day's statuses (a missing offset is a missing row)."""
    rows = [{"pk": U, "sk": "PROFILE#v1", "habit_registry": _registry() if registry is None else registry}]
    rows += [_row(_day(o), st) for o, st in days.items()]
    rows.append({"pk": SCORES, "sk": f"DATE#{AS_OF}", "date": AS_OF, "vice_streaks": streaks or {"restraint_a": Decimal(7)}})
    rows += list(extra_rows)
    return FakeTable(rows, page_items=page_items, fail_on=fail_on)


def _both(table: FakeTable, as_of: str = AS_OF, start: str = "2026-01-01", streak_names=None) -> tuple:
    new = H.public_tier0_summary(table, as_of, start, streak_names=streak_names)
    old = _reference_public_tier0_summary(table, as_of, start, streak_names=streak_names)
    return new, old


def _handler_both(table: FakeTable, genesis: str, monkeypatch) -> tuple:
    def experiment_date(n: int) -> str:
        return max(_day(n - 1), genesis)

    g = {"table": table, "_experiment_date": experiment_date}
    new = H.habit_streaks(_g=g)
    real = H.public_tier0_summary
    H.public_tier0_summary = _reference_public_tier0_summary
    try:
        old = H.habit_streaks(_g=g)
    finally:
        H.public_tier0_summary = real
    return _body(new), _body(old)


def _body(resp: dict) -> dict:
    """The handler's response with its ``_meta`` (serve-time stamps) removed."""
    body = json.loads(resp["body"])
    body.pop("_meta", None)
    return {"status": resp["statusCode"], "body": body}


# ── the cases ────────────────────────────────────────────────────────────────────────────────────────


def test_the_window_read_is_projected_and_names_only_tier0_habits():
    t = _table({0: _statuses()})
    H.public_tier0_summary(t, AS_OF, "2026-01-01")
    hab = [c for c in t.calls if _key_bounds(c["KeyConditionExpression"]).get("pk") == HAB]
    assert len(hab) == 1
    proj, names = hab[0]["ProjectionExpression"], hab[0]["ExpressionAttributeNames"]
    projected = {names[p.split(".")[1]] for p in proj.split(", ") if p.count(".") == 1}
    assert projected == {"habit_a", "habit_b", "habit_d", "habit_e", "restraint_a", "restraint_b"}
    # DynamoDB rejects a name the expressions never use; the phase filter's own name must be used too.
    used = proj + " " + hab[0]["FilterExpression"]
    assert all(p in used for p in names), names


def test_projection_alone_moves_no_page_boundary():
    """The fake reads ``page_items`` items per page before projecting, as DynamoDB does: the page count is the same."""
    days = {o: _statuses() for o in range(40)}
    t_new, t_old = _table(days, page_items=7), _table(days, page_items=7)
    H.public_tier0_summary(t_new, AS_OF, _day(39))
    _reference_public_tier0_summary(t_old, AS_OF, _day(39))
    assert len(t_new.calls) == len(t_old.calls) == 2 + 6


@pytest.mark.parametrize("page_items", [1, 3, 1000])
def test_a_long_unbroken_streak_across_many_pages(page_items):
    days = {o: _statuses() for o in range(120)}
    new, old = _both(_table(days, page_items=page_items), start=_day(119))
    assert new == old
    assert new["streak"] == 120 and new["total"] == 3


def test_a_streak_broken_yesterday():
    days = {o: _statuses(ok=(o != 1)) for o in range(30)}
    new, old = _both(_table(days), start=_day(29))
    assert new == old and new["streak"] == 1


def test_broken_exactly_at_the_lookback_cap():
    """Perfect from the window's first day to as_of; the day before the window is perfect too and is not counted."""
    days = {o: _statuses() for o in range(31)}
    days[31] = _statuses(ok=False)
    new, old = _both(_table(days), start=_day(30))
    assert new == old and new["streak"] == 31
    new2, old2 = _both(_table(days), start=_day(31))
    assert new2 == old2 and new2["streak"] == 31


def test_a_missing_day_record_breaks_the_run():
    days = {o: _statuses() for o in range(20) if o != 6}
    new, old = _both(_table(days), start=_day(19))
    assert new == old and new["streak"] == 6


def test_an_inactive_habit_in_the_registry_counts_as_before():
    """The predicate does not read the registry ``status``; an archived tier-0 habit's status is read the same way."""
    days = {o: _statuses() for o in range(10)}
    days[0]["habit_e"]["status"] = "not_completed"
    new, old = _both(_table(days), start=_day(9))
    assert new == old


def test_a_habit_that_changes_classification_or_tier_mid_history():
    days = {o: _statuses() for o in range(15)}
    for o in range(5, 15):  # an older id that classifies as the private journal
        days[o]["habit_a"]["habit_id"] = JOURNAL_ID
    for o in range(8, 11):  # an older tracker group that marks it a restraint (the union then holds it out everywhere)
        days[o]["habit_b"]["group"] = RESTRAINT_GROUP
    days[3]["habit_b"] = "not a map"  # a malformed stored status
    for registry in (_registry(), {**_registry(), "habit_a": {"tier": 2, "publication": "public"}}):
        new, old = _both(_table(days, registry=registry), start=_day(14))
        assert new == old


def test_restraint_habits_kept_or_missed_move_nothing():
    def run(done: bool, streak: int) -> dict:
        days = {o: _statuses(restraint_done=done) for o in range(25)}
        new, old = _both(_table(days, streaks={"restraint_a": Decimal(streak)}), start=_day(24))
        assert new == old
        return new

    assert run(True, 90) == run(False, 0)
    days = {o: _statuses(ok=(o != 3)) for o in range(25)}  # control: an ordinary miss does move it
    assert _both(_table(days), start=_day(24))[0] != run(True, 90)


def test_a_day_with_only_restraint_habits_breaks_the_run():
    days = {o: _statuses() for o in range(12)}
    days[4] = {"restraint_a": _status(True, group=RESTRAINT_GROUP), "restraint_b": _status(True)}
    new, old = _both(_table(days), start=_day(11))
    assert new == old and new["streak"] == 4


def test_the_genesis_boundary_and_pilot_rows(monkeypatch):
    """The handler's window is clamped at genesis (``_experiment_date``); a pre-genesis or pilot row never counts."""
    days = {o: _statuses() for o in range(60)}
    pilot = _row(_day(2), _statuses(ok=False), phase="pilot")
    genesis = _day(20)
    new, old = _handler_both(_table(days), genesis, monkeypatch)
    assert new == old
    assert new["body"]["habit_streaks"]["aggregate_streak"] == 21
    # a pilot row in the window replaces nothing (the phase filter drops it) — the same both ways
    t2 = _table({o: _statuses() for o in range(60) if o != 2}, extra_rows=[pilot])
    new2, old2 = _handler_both(t2, genesis, monkeypatch)
    assert new2 == old2 and new2["body"]["habit_streaks"]["aggregate_streak"] == 2


def test_a_pacific_midnight_today(monkeypatch):
    """The clock pinned at 00:00 Pacific: the handler's empty-state day and the scored day agree both ways."""
    instant = datetime(2026, 3, 16, 7, 0, 0, tzinfo=timezone.utc)  # 00:00 PDT

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(H, "datetime", _Frozen)
    empty = FakeTable([{"pk": U, "sk": "PROFILE#v1", "habit_registry": _registry()}])
    g = {"table": empty, "_experiment_date": lambda n: "2026-01-01"}
    body = json.loads(H.habit_streaks(_g=g)["body"])
    assert body["habit_streaks"]["as_of_date"] == AS_OF
    days = {o: _statuses() for o in range(9)}
    new, old = _handler_both(_table(days), "2026-01-01", monkeypatch)
    assert new == old and new["body"]["habit_streaks"]["as_of_date"] == AS_OF


def test_an_empty_table():
    t = FakeTable([])
    assert _both(t) == ({"as_of_date": AS_OF, "done": 0, "total": 0, "pct": 0, "streak": 0},) * 2


def test_an_empty_registry_reads_keys_only():
    t = _table({0: _statuses()}, registry={})
    new, old = _both(t)
    assert new == old
    hab = [c for c in t.calls if c.get("ProjectionExpression")]
    assert hab and hab[0]["ProjectionExpression"] == "#t0sk, #t0date"


def test_a_registry_too_large_for_one_expression_falls_back_to_whole_status_maps():
    registry = {f"habit_{i:03d}": {"tier": 0, "publication": "public"} for i in range(400)}
    proj = H._tier0_projection(registry)
    assert proj["ProjectionExpression"] == "#t0sk, #t0date, #t0hs"
    days = {o: {n: _status(True) for n in list(registry)[:30]} for o in range(5)}
    new, old = _both(_table(days, registry=registry), start=_day(4))
    assert new == old and new["streak"] == 5


@pytest.mark.parametrize("fail_on", [HAB, U, SCORES])
def test_a_read_failure_publishes_nothing(fail_on):
    t = _table({0: _statuses()}, fail_on=fail_on)
    with pytest.raises(RuntimeError):
        H.public_tier0_summary(t, AS_OF, "2026-01-01")
    with pytest.raises(RuntimeError):
        _reference_public_tier0_summary(t, AS_OF, "2026-01-01")
    assert H.public_tier0_or_none(t, AS_OF, "2026-01-01") is None


# ── the randomised sweep ─────────────────────────────────────────────────────────────────────────────


def _random_history(rng: random.Random) -> tuple:
    names = [f"habit_{c}" for c in "abcdefghij"] + ["restraint_a", "restraint_b", "restraint_c"]
    public_ids = sorted(AP.PUBLIC_HABIT_IDS)
    registry: dict = {}
    for n in names:
        if rng.random() < 0.15:
            continue  # not in the registry
        meta: dict = {"tier": rng.choice([0, 0, 0, 1, 2, "0", Decimal(0), "x"])}
        r = rng.random()
        if r < 0.5:
            meta["publication"] = "public"
        elif r < 0.6:
            meta["publication"] = "private"
        elif r < 0.75 and public_ids:
            meta["habitify_id"] = rng.choice(public_ids)
        if rng.random() < 0.1:
            meta[RP.REGISTRY_FLAG] = True
        if rng.random() < 0.1:
            meta["group"] = RESTRAINT_GROUP
        if rng.random() < 0.1:
            meta["status"] = "archived"
        registry[n] = meta
    if rng.random() < 0.05:
        registry["habit_z"] = "not a map"
    n_days = rng.randint(1, 70)
    days: dict = {}
    for o in range(n_days):
        if rng.random() < 0.05:
            continue  # a missing row
        st: dict = {}
        for n in names:
            if rng.random() < 0.1:
                continue
            if rng.random() < 0.02:
                st[n] = rng.choice(["bad", None, [1]])
                continue
            hid = rng.choice(["", "", JOURNAL_ID] + public_ids[:2])
            grp = rng.choice(["Core", "Optimize", RESTRAINT_GROUP, RESTRAINT_GROUP.title(), None])
            st[n] = _status(rng.random() < 0.85, group=grp, hid=hid, scheduled=rng.random() < 0.9)
            if rng.random() < 0.1:
                st[n].pop("scheduled_today")
        days[o] = st
    streaks = {n: Decimal(rng.randint(0, 99)) for n in names if n.startswith("restraint") and rng.random() < 0.5}
    start = _day(rng.randint(0, n_days + 3))
    pilot = []
    if rng.random() < 0.2:  # a pilot row in the window, in place of that day's row
        o = rng.randint(0, n_days)
        days.pop(o, None)
        pilot.append(_row(_day(o), {names[0]: _status(False)}, phase="pilot"))
    return days, registry, streaks, start, pilot


@pytest.mark.parametrize("published", [False, True])
def test_seeded_random_histories_are_identical(published, monkeypatch):
    monkeypatch.setattr(RP, "RESTRAINT_DATA_PUBLISHED", published)
    rng = random.Random(6271 + int(published))
    for i in range(300):
        days, registry, streaks, start, pilot = _random_history(rng)
        t = _table(days, registry=registry, streaks=streaks, extra_rows=pilot, page_items=rng.choice([1, 4, 1000]))
        names = {"restraint_c"} if rng.random() < 0.3 else None
        new, old = _both(t, start=start, streak_names=names)
        assert new == old, (i, new, old)
