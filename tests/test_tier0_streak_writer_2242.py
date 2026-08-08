"""tests/test_tier0_streak_writer_2242.py — the Tier-0 perfect-day streak has a WRITER (#2242).

Before this fix the `habit_scores` partition carried no streak field at all: both
writers (`compute/daily_metrics_compute_lambda.store_habit_scores`, the primary,
and `emails/daily_brief_lambda.store_habit_scores`, the fallback) computed the
Tier-0 streak and then dropped it on this partition, while six read sites asked
for `t0_perfect_streak`. Eleven awards — the five streak badges (week_warrior →
half_year_hold) and the six N-Day Streak milestone rungs (7/14/30/90/180/365) —
therefore read a permanent 0 and were structurally unearnable regardless of
behaviour. Publishing an award that cannot be earned is a false claim to a reader
(ADR-104), so the contract under test is end-to-end:

  * the writers persist the streak under the ONE canonical name,
  * an honest 0 is written (absence would read as "no data", not "streak broken"),
  * the record a writer produced — never a hand-typed fixture — makes
    /api/habit_streaks, the five badges and the six milestone rungs move,
  * the dead alias `t0_aggregate_streak` has no reader left anywhere.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

for _k, _v in [
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
    ("TABLE_NAME", "life-platform"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "brief@example.invalid"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

_import_err = None
try:
    import daily_metrics_compute_lambda as dmc  # noqa: E402
    from health import (
        achievement_rules,  # noqa: E402
        milestone_ledger as ml,  # noqa: E402
    )
    from web import (
        site_api_habits as habits,  # noqa: E402
        site_api_vitals as vitals,  # noqa: E402
    )
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"lambda modules unavailable: {_import_err}")

USER_PREFIX = "USER#matthew#SOURCE#"
HABIT_PK = USER_PREFIX + "habit_scores"
CANONICAL = "t0_perfect_streak"
DEAD_ALIAS = "t0_aggregate_streak"

STREAK_BADGES = ("week_warrior", "fortnight", "monthly_grind", "quarterly", "half_year_hold")
STREAK_RUNGS = ("streak_7", "streak_14", "streak_30", "streak_90", "streak_180", "streak_365")


# ── Doubles ───────────────────────────────────────────────────────────────────


class FakeTable:
    """Minimal DDB Table double: pk/sk store, pk-only / begins_with / BETWEEN."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, Item, ConditionExpression=None, **_kw):  # noqa: N803 — boto3 kwarg casing
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists(sk)" in str(ConditionExpression) and key in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[key] = dict(Item)

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {}) or {}
        pk = vals.get(":pk")
        cond = str(kw.get("KeyConditionExpression") or "")
        out = [dict(v) for (k_pk, k_sk), v in self.items.items() if k_pk == pk and _sk_matches(cond, k_sk, vals)]
        out.sort(key=lambda i: i["sk"], reverse=not kw.get("ScanIndexForward", True))
        limit = kw.get("Limit")
        return {"Items": out[:limit] if limit else out}

    # the habit_scores row the writers produce
    def habit_rows(self) -> list[dict]:
        return [dict(v) for (pk, _sk), v in self.items.items() if pk == HABIT_PK]


def _sk_matches(cond: str, sk: str, vals: dict) -> bool:
    if "begins_with" in cond:
        return sk.startswith(vals.get(":sk", ""))
    if "BETWEEN" in cond:
        return vals[":s"] <= sk <= vals[":e"]
    return True


def _component_details(t0_done=6, t0_total=6):
    """The `habits_mvp` detail block both writers require (tier_weighted method)."""
    return {
        "habits_mvp": {
            "composite_method": "tier_weighted",
            "tier0": {"done": t0_done, "total": t0_total},
            "tier1": {"done": 2, "total": 3},
            "vices": {"held": 1, "total": 1},
            "tier_status": {0: {f"h{i}": i < t0_done for i in range(t0_total)}, 1: {"stretch": True}},
        }
    }


PROFILE = {
    "habit_registry": {
        "h0": {"status": "active", "tier": 0, "synergy_group": "core"},
        "h1": {"status": "active", "tier": 0, "synergy_group": "core"},
    }
}


def _write(streak, *, module=dmc, t0_done=6, date_str="2026-08-06"):
    """Run the REAL writer against a fake table and return the row it wrote."""
    table = FakeTable()
    module.table = table
    module.store_habit_scores(
        date_str,
        _component_details(t0_done=t0_done),
        {"habits_mvp": 92.0},
        {"no_delivery": 5},
        PROFILE,
        tier0_streak=streak,
    )
    rows = table.habit_rows()
    assert rows, "the writer wrote no habit_scores row at all"
    return table, rows[0]


# ── 1. The writers persist the canonical field ────────────────────────────────


def test_primary_writer_persists_the_field_the_readers_agree_on(monkeypatch):
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    _table, row = _write(7)
    assert CANONICAL in row, f"daily-metrics-compute wrote no {CANONICAL} — the eleven streak awards stay unearnable"
    assert int(row[CANONICAL]) == 7
    assert DEAD_ALIAS not in row


def test_writer_persists_an_honest_zero(monkeypatch):
    """A broken streak must be written as 0, not omitted (ADR-104: absence != 0)."""
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    _table, row = _write(0, t0_done=4)
    assert CANONICAL in row, "a broken streak was omitted — the reader cannot tell 'reset' from 'no data'"
    assert int(row[CANONICAL]) == 0


def test_fallback_brief_writer_agrees_with_the_primary(monkeypatch):
    """The brief's fallback writer must use the same name, or the streak resets
    to 0 on every day daily-metrics-compute did not run."""
    brief = pytest.importorskip("daily_brief_lambda")
    monkeypatch.setattr(brief, "table", FakeTable(), raising=False)
    _table, row = _write(23, module=brief)
    assert int(row[CANONICAL]) == 23


# ── 2. Writer output → the reader surfaces ────────────────────────────────────


def test_habit_streaks_endpoint_reports_the_written_streak(monkeypatch):
    """/api/habit_streaks returns a nonzero aggregate_streak off the row the
    writer produced (no hand-typed field name anywhere in this path)."""
    import json

    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    table, _row = _write(31)
    resp = habits.habit_streaks(_g={"table": table})
    body = json.loads(resp["body"])["habit_streaks"]
    assert body["aggregate_streak"] == 31


def _achievements(monkeypatch, table):
    import json

    monkeypatch.setattr(vitals, "table", table)
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    resp = vitals.handle_achievements()
    assert resp["statusCode"] == 200
    return {a["id"]: a for a in json.loads(resp["body"])["achievements"]}


@pytest.mark.parametrize("streak,expected_earned", [(0, ()), (7, ("week_warrior",)), (180, STREAK_BADGES)])
def test_streak_badges_transition_from_unearned_to_earned(monkeypatch, streak, expected_earned):
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    table, _row = _write(streak)
    badges = _achievements(monkeypatch, table)
    for bid in STREAK_BADGES:
        assert badges[bid]["earned"] is (bid in expected_earned), f"{bid} earned={badges[bid]['earned']} at streak={streak}"


def test_streak_badges_read_the_written_row_directly(monkeypatch):
    """The badge engine's streak extractor sees the writer's row."""
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    _table, row = _write(45)
    assert achievement_rules._streak_of(row) == 45


@pytest.mark.parametrize("streak,expected", [(0, set()), (365, set(STREAK_RUNGS))])
def test_milestone_streak_rungs_can_fire(monkeypatch, streak, expected):
    """The six N-Day Streak rungs become satisfiable off the written row."""
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    table, _row = _write(streak)
    signals = ml.collect_signals(table, USER_PREFIX, None, "2026-08-07")
    assert signals["tier0_streak"] == streak
    decision = ml.evaluate(signals, existing_ids=set(), last_event_date=None, today="2026-08-07", suppressed=False)
    fired = {e["milestone_id"] for e in decision["to_write"]} | set(decision["deferred"])
    assert expected <= fired, f"streak rungs {expected - fired} unreachable at tier0_streak={streak}"
    if not expected:
        assert not (set(STREAK_RUNGS) & fired)


# ── 3. Reset-on-miss round trip ───────────────────────────────────────────────


def test_reset_on_miss_round_trips_to_zero(monkeypatch):
    """A missed Tier-0 day breaks the streak, and the break is what gets stored."""
    registry = {"a": {"status": "active", "tier": 0}, "b": {"status": "active", "tier": 0}}
    profile = {"habit_registry": registry, "mvp_habits": ["a", "b"]}

    # 2026-08-06 complete, 2026-08-05 missed 'b'
    days = {
        "2026-08-06": {"habits": {"a": 1, "b": 1}},
        "2026-08-05": {"habits": {"a": 1, "b": 0}},
        "2026-08-04": {"habits": {"a": 1, "b": 1}},
    }
    monkeypatch.setattr(dmc, "fetch_date", lambda src, d: days.get(d))
    assert dmc.compute_habit_streaks(profile, "2026-08-06")["tier0_streak"] == 1

    # …and the miss itself stores an explicit 0
    monkeypatch.setattr(dmc, "fetch_date", lambda src, d: days.get(d))
    assert dmc.compute_habit_streaks(profile, "2026-08-05")["tier0_streak"] == 0
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    _table, row = _write(dmc.compute_habit_streaks(profile, "2026-08-05")["tier0_streak"])
    assert int(row[CANONICAL]) == 0


# ── 4. The dead alias has no reader left (the partial guard-the-SET) ──────────


def test_no_source_file_still_reads_the_dead_alias():
    """`t0_aggregate_streak` never had a writer; #2242 canonicalised on
    `t0_perfect_streak` and removed the alias from every read site. A new
    reference would reintroduce a name nothing writes."""
    offenders = []
    for base in ("lambdas", "mcp", "deploy", "scripts", "web"):
        root = REPO_ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "archive" in path.parts:
                continue
            if DEAD_ALIAS in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"{DEAD_ALIAS} has no writer anywhere; these files still read it: {offenders}"


def test_writer_value_is_decimal_for_dynamodb(monkeypatch):
    monkeypatch.setattr(dmc, "table", FakeTable(), raising=False)
    _table, row = _write(9)
    assert isinstance(row[CANONICAL], Decimal), "boto3 rejects float/int-as-float — the streak must be Decimal"
