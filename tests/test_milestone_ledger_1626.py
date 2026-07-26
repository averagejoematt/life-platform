"""tests/test_milestone_ledger_1626.py — the durable MILESTONE# event ledger (#1626).

The governing rule under test: **a rung crossed is a rung consumed, forever.**
No un-fire, no re-fire. The acceptance criteria, mapped to tests:

  * write-once / idempotent / immutable       → test_hysteresis_*, test_entries_are_never_mutated
  * trailing 7-day mean, never one weigh-in   → test_weight_needs_a_real_window_not_one_weigh_in
    (stored event carries window + n + mean)     test_event_carries_window_n_and_mean
  * ONE global cooldown across ALL categories → test_three_categories_in_one_week_yield_one_event
  * permanent hysteresis                      → test_hysteresis_back_and_forth_yields_exactly_one_event
  * deliberate reset behaviour (ADR-077)      → test_partition_is_registered_cross_phase
  * consumers read, never re-derive           → test_single_writer_and_no_mutation_paths,
                                                test_read_paths_write_nothing
"""

import ast
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

import milestone_ledger as ml  # noqa: E402

USER_PREFIX = "USER#matthew#SOURCE#"
LEDGER_PK = USER_PREFIX + "milestones"


class FakeTable:
    """Minimal DDB Table double: pk/sk store; pk-only, begins_with and BETWEEN
    key conditions; the attribute_not_exists(sk) conditional put the ledger
    relies on. (Same shape as the #1624 test double.)"""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 — boto3 kwarg casing
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists(sk)" in ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[key] = dict(Item)

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        pk = vals[":pk"]
        cond = kw["KeyConditionExpression"]
        out = [dict(v) for (k_pk, k_sk), v in self.items.items() if k_pk == pk and _sk_matches(cond, k_sk, vals)]
        out.sort(key=lambda i: i["sk"])
        return {"Items": out}


def _sk_matches(cond: str, sk: str, vals: dict) -> bool:
    if "begins_with" in cond:
        return sk.startswith(vals[":sk"])
    if "BETWEEN" in cond:
        return vals[":s"] <= sk <= vals[":e"]
    return True  # pk-only query


def _weight_day(date: str, lbs: float) -> dict:
    return {"pk": USER_PREFIX + "withings", "sk": f"DATE#{date}", "weight_lbs": lbs}


def _habit_day(date: str, streak: int) -> dict:
    return {"pk": USER_PREFIX + "habit_scores", "sk": f"DATE#{date}", "t0_perfect_streak": streak}


def _sweep(table, today: str) -> dict:
    return ml.sweep(table, USER_PREFIX, None, today)


def _ledger_items(table) -> dict[str, dict]:
    return {sk: dict(v) for (pk, sk), v in table.items.items() if pk == LEDGER_PK}


def _dates(start_md: str, n: int) -> list[str]:
    """n consecutive dates starting at 2026-<start_md> (month-day, e.g. '05-01')."""
    from datetime import datetime, timedelta

    d0 = datetime.strptime(f"2026-{start_md}", "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


# ── AC: trailing mean, never a single weigh-in ───────────────────────────────


def test_weight_needs_a_real_window_not_one_weigh_in():
    """A single weigh-in far below the threshold must NOT fire; the rung fires
    only once the trailing 7-day window holds >= 3 weigh-ins whose mean crosses."""
    table = FakeTable()
    _sweep(table, "2026-05-01")  # genesis: empty ledger, nothing satisfied

    table.put_item(Item=_weight_day("2026-05-02", 245.0))
    r = _sweep(table, "2026-05-02")
    assert r["announced"] == [], "one weigh-in fired a weight milestone — the AC forbids exactly this"

    table.put_item(Item=_weight_day("2026-05-03", 245.0))
    r = _sweep(table, "2026-05-03")
    assert r["announced"] == [], "two weigh-ins fired — the window needs n >= 3"

    table.put_item(Item=_weight_day("2026-05-04", 245.0))
    r = _sweep(table, "2026-05-04")
    assert [e["milestone_id"] for e in r["announced"]] == ["weight_sub_250"]


def test_event_carries_window_n_and_mean():
    """ADR-105: the stored event must carry the window, the n, and the mean —
    a consumer can render the claim with its uncertainty, or refuse to."""
    table = FakeTable()
    _sweep(table, "2026-05-01")
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)

    rec = table.items[(LEDGER_PK, "MILESTONE#weight_sub_250")]
    meas = rec["measurement"]
    assert meas["window_days"] == 7
    assert meas["n"] == 3
    assert meas["mean_lbs"] == Decimal("245.0")
    assert meas["threshold_lbs"] == 250
    assert meas["window_start"] == "2026-04-28" and meas["window_end"] == "2026-05-04"
    assert rec["event_date"] == "2026-05-04"


def test_same_ladder_rungs_crossed_together_are_subsumed_not_drip_announced():
    """Mean 245 satisfies sub_340…sub_250 at once. The deepest rung announces;
    the shallower ones are consumed silently (subsumed) — a lesser rung must
    never be announced AFTER a greater one."""
    table = FakeTable()
    _sweep(table, "2026-05-01")
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)

    items = _ledger_items(table)
    assert items["MILESTONE#weight_sub_250"]["announce"] is True
    for t in range(260, 350, 10):
        rec = items[f"MILESTONE#weight_sub_{t}"]
        assert rec["announce"] is False and rec["subsumed_by"] == "weight_sub_250", f"sub_{t} must be consumed by the sub_250 crossing"

    # …and none of them ever announces later, even far outside the cooldown.
    for d in _dates("06-01", 3):
        table.put_item(Item=_weight_day(d, 245.0))
        r = _sweep(table, d)
        assert r["announced"] == []


# ── AC: ONE global cooldown across ALL categories combined ───────────────────


def test_three_categories_in_one_week_yield_exactly_one_event():
    """The fixture the issue names: weight, streak and days_tracked all trip
    inside one week — exactly ONE event may announce. The deferred rungs are
    NOT consumed: they announce later, after the global cooldown."""
    table = FakeTable()

    # Genesis state: mean ~252 (consumes sub_260+ as baseline), streak 3,
    # 25 days tracked, level 1 — so sub_250, streak_7, days_tracked_30 are all
    # still unconsumed and un-satisfied.
    for d in ("2026-04-29", "2026-04-30", "2026-05-01"):
        table.put_item(Item=_weight_day(d, 252.0))
    for i, d in enumerate(_dates("04-06", 25)):
        table.put_item(Item=_habit_day(d, min(3, i + 1)))
    g = _sweep(table, "2026-05-01")
    assert g["genesis"] and g["announced"] == []

    # The week: weight crosses on 05-04; streak hits 7 on 05-05; the 30th
    # tracked day lands on 05-06.
    week = _dates("05-02", 7)  # 05-02 .. 05-08
    weights = {"2026-05-02": 248.0, "2026-05-03": 247.0, "2026-05-04": 246.0}
    streaks = {d: s for d, s in zip(week, [4, 5, 6, 7, 8, 9, 9])}

    announced = []
    for d in week:
        if d in weights:
            table.put_item(Item=_weight_day(d, weights[d]))
        table.put_item(Item=_habit_day(d, streaks[d]))
        r = _sweep(table, d)
        announced += [e["milestone_id"] for e in r["announced"]]

    assert announced == ["weight_sub_250"], f"three categories tripped in one week must yield exactly one event, got {announced}"

    # The deferred categories announce AFTER the cooldown — one per window,
    # highest-priority category first.
    later = []
    for d in _dates("05-09", 12):  # through 2026-05-20
        table.put_item(Item=_habit_day(d, 9))
        r = _sweep(table, d)
        later += [(d, e["milestone_id"]) for e in r["announced"]]
    assert later == [("2026-05-16", "streak_7")], f"the deferred streak rung must fire once the 12-day global cooldown expires, got {later}"


def test_cooldown_constant_is_inside_the_issue_band():
    assert 10 <= ml.GLOBAL_COOLDOWN_DAYS <= 14, "the global cooldown must stay in the 10-14 day band the issue pins"


# ── AC: permanent hysteresis ─────────────────────────────────────────────────


def test_hysteresis_back_and_forth_yields_exactly_one_event():
    """Drive the trailing mean below the threshold, back above, and below again
    (with the cooldown fully expired in between) — exactly one event may exist,
    and the stored entry must be byte-identical to the day it was written."""
    table = FakeTable()
    for d in ("2026-04-29", "2026-04-30", "2026-05-01"):
        table.put_item(Item=_weight_day(d, 252.0))
    _sweep(table, "2026-05-01")  # genesis (consumes sub_260+ as baseline)

    # Below: crossing confirmed.
    for d, lbs in [("2026-05-02", 246.0), ("2026-05-03", 245.0), ("2026-05-04", 244.0)]:
        table.put_item(Item=_weight_day(d, lbs))
        _sweep(table, d)
    assert (LEDGER_PK, "MILESTONE#weight_sub_250") in table.items
    snapshot = dict(table.items[(LEDGER_PK, "MILESTONE#weight_sub_250")])

    # Back above for 16 days (cooldown long expired), then below again for 7.
    for d in _dates("05-05", 16):
        table.put_item(Item=_weight_day(d, 253.0))
        _sweep(table, d)
    for d in _dates("05-21", 7):
        table.put_item(Item=_weight_day(d, 244.0))
        r = _sweep(table, d)
        assert r["announced"] == [], "the rung re-fired after an oscillation — hysteresis must be permanent"

    records = [sk for sk in _ledger_items(table) if sk == "MILESTONE#weight_sub_250"]
    assert len(records) == 1
    assert (
        table.items[(LEDGER_PK, "MILESTONE#weight_sub_250")] == snapshot
    ), "the stored event was mutated — entries are write-once, forever"


def test_entries_are_never_mutated_by_re_evaluation():
    """Idempotency: sweeping the same day repeatedly writes nothing new and
    changes nothing existing."""
    table = FakeTable()
    _sweep(table, "2026-05-01")
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)
    before = {k: dict(v) for k, v in table.items.items()}

    for _ in range(5):
        r = _sweep(table, "2026-05-04")
        assert r["written"] == [] and r["announced"] == []
    assert table.items == before


# ── Ledger genesis (ADR-104: no manufactured history) ────────────────────────


def test_genesis_consumes_already_true_rungs_without_announcing():
    """Rungs already satisfied when the ledger first runs are consumed as
    baseline — announce=False, event_date=None (their crossings predate the
    ledger; no honest date exists) — and can never fire later."""
    table = FakeTable()
    for d in ("2026-04-29", "2026-04-30", "2026-05-01"):
        table.put_item(Item=_weight_day(d, 252.0))
    for i, d in enumerate(_dates("03-01", 40)):
        table.put_item(Item=_habit_day(d, i + 1))

    r = _sweep(table, "2026-05-01")
    assert r["genesis"] is True and r["announced"] == []
    items = _ledger_items(table)
    assert "LEDGER#genesis" in items
    baselines = [v for sk, v in items.items() if sk.startswith("MILESTONE#")]
    assert baselines, "already-satisfied rungs must be consumed at genesis"
    for rec in baselines:
        assert rec["announce"] is False and rec["origin"] == "baseline"
        assert rec["event_date"] is None, "a baseline entry must not carry a manufactured event date (ADR-104)"
    assert {"MILESTONE#weight_sub_260", "MILESTONE#streak_30", "MILESTONE#days_tracked_30"} <= set(items)

    # Nothing announced from history, ever: the consumer surface is empty.
    assert ml.read_announced_events(table, USER_PREFIX) == []

    # And genesis is a one-time state: a later fresh crossing IS announced.
    for d, lbs in [("2026-05-02", 246.0), ("2026-05-03", 245.0), ("2026-05-04", 244.0)]:
        table.put_item(Item=_weight_day(d, lbs))
        r = _sweep(table, d)
    assert [e["milestone_id"] for e in ml.read_announced_events(table, USER_PREFIX)] == ["weight_sub_250"]


# ── Reset behaviour (ADR-077) ────────────────────────────────────────────────


def test_partition_is_registered_cross_phase():
    """The reset behaviour is a recorded decision: SOURCE#milestones survives
    every experiment reset (a dated past fact stays true in cycle N+1 — wiping
    it would re-fire consumed rungs, the exact defect #1626 removes)."""
    import phase_taxonomy

    assert phase_taxonomy.SOURCE_CLASS["milestones"] == phase_taxonomy.CROSS_PHASE
    cls = phase_taxonomy.classify(LEDGER_PK, "MILESTONE#weight_sub_250")
    assert cls == phase_taxonomy.CROSS_PHASE
    assert phase_taxonomy.never_touch(cls), "the phase machinery must never tag/wipe/filter the milestone ledger"


# ── Consumers read; nothing else derives "a milestone happened" ──────────────


def test_read_paths_write_nothing():
    table = FakeTable()
    _sweep(table, "2026-05-01")
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)
    snapshot = {k: dict(v) for k, v in table.items.items()}

    ml.read_ledger(table, USER_PREFIX)
    ml.read_announced_events(table, USER_PREFIX)
    assert table.items == snapshot, "a ledger read mutated DynamoDB"


def test_single_writer_and_no_mutation_paths():
    """Exactly one module in lambdas/ + mcp/ may write the milestones partition,
    and that module must expose NO update or delete path (immutability is
    structural, not a convention)."""
    writers = set()
    for base in (ROOT / "lambdas", ROOT / "mcp"):
        for path in base.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"put_item", "update_item", "delete_item"} and "milestones" in ast.unparse(node):
                        writers.add((path.name, node.func.attr))
    assert writers == {("milestone_ledger.py", "put_item")}, f"unexpected milestone-partition writers/mutators: {sorted(writers)}"


# ── DDB safety ───────────────────────────────────────────────────────────────


def test_written_items_are_decimal_safe():
    """boto3 rejects Python floats — every stored number must be Decimal/int."""

    def _no_floats(obj, path="item"):
        if isinstance(obj, float):
            raise AssertionError(f"raw float at {path} — cast to Decimal before writing")
        if isinstance(obj, dict):
            for k, v in obj.items():
                _no_floats(v, f"{path}.{k}")
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                _no_floats(v, f"{path}[{i}]")

    table = FakeTable()
    _sweep(table, "2026-05-01")
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)
    for sk, item in _ledger_items(table).items():
        _no_floats(item, sk)


def test_catalog_ids_unique_and_ladders_ordered():
    assert len(ml.MILESTONE_IDS) == len(set(ml.MILESTONE_IDS)), "duplicate milestone id"
    for cat in ml.CATEGORY_PRIORITY:
        depths = [r.depth for r in ml.MILESTONE_RULES if r.category == cat]
        assert depths == sorted(depths), f"{cat} ladder depths out of order"
    assert set(r.category for r in ml.MILESTONE_RULES) == set(ml.CATEGORY_PRIORITY)
