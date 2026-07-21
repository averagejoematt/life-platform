"""tests/test_achievement_first_earn_1624.py — badges cannot un-earn (#1624).

The bug: `handle_achievements()` was stateless. Every badge computed
`earned_date = today if <condition> else None`, so (a) no first-earn was ever
recorded, and (b) a badge un-earned the moment its metric dipped back under the
threshold — a 2-3 lb hydration swing was enough to revoke `lost_10`.

The two tests the issue names explicitly are `test_weight_oscillation_*` and
`test_streak_break_and_rebuild_*`. Both drive the metric up across the threshold,
back down under it, and up again, and assert the badge stays earned with a
first-earn date that never moves. Against the pre-#1624 code both fail: the badge
flips to earned=False in the trough, and earned_date is today on every pass.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

import achievement_rules as ar  # noqa: E402

USER_PREFIX = "USER#matthew#SOURCE#"


class FakeTable:
    """Minimal DDB Table double: pk/sk store, begins_with + BETWEEN key conditions,
    and the attribute_not_exists(sk) conditional put the ledger relies on."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 — boto3 kwarg casing
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            existing = self.items[key]
            ok = ("attribute_not_exists(sk)" in ConditionExpression and key not in self.items) or (
                "attribute_exists(tombstone)" in ConditionExpression and existing.get("tombstone")
            )
            if not ok:
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
    return True


def _weight_day(date: str, lbs: float) -> dict:
    return {"pk": USER_PREFIX + "withings", "sk": f"DATE#{date}", "weight_lbs": lbs}


def _habit_day(date: str, streak: int) -> dict:
    return {"pk": USER_PREFIX + "habit_scores", "sk": f"DATE#{date}", "t0_perfect_streak": streak}


def _run_day(table, today: str) -> dict:
    """One writer pass + one reader pass, exactly as the two Lambdas do it.

    Returns the rendered badge list keyed by id — i.e. what /api/achievements
    would serve at the end of that day.
    """
    inputs = ar.collect_inputs(table, USER_PREFIX, None, start_weight_lbs=300.0, today=today, window_start="2026-01-01")
    signals = ar.signals_from(inputs)
    existing = ar.read_first_earns(table, USER_PREFIX, None)
    ar.persist_first_earns(table, USER_PREFIX, signals, ar.histories_from(inputs), existing, today)
    # The reader re-reads the ledger — it never writes (core data queries must not write).
    first_earns = ar.read_first_earns(table, USER_PREFIX, None)
    return {b["id"]: b for b in ar.render(signals, first_earns)}


# ── AC: a weight series driven up and down across the threshold ───────────────


def test_weight_oscillation_never_un_earns_a_badge():
    """The named regression: a 10 lb loss, a water-weight regain, then a re-loss.

    Day 1  290.0 lbs → 10.0 lbs down → lost_10 crosses.
    Day 2  292.5 lbs →  7.5 lbs down → BELOW the threshold (this is the trough that
           used to revoke the badge — 2.5 lb, i.e. ordinary hydration noise).
    Day 3  289.0 lbs → 11.0 lbs down → back over.

    lost_10 must be earned on all three days, and its earned_date must never move
    off day 1.
    """
    table = FakeTable()
    seen_dates = []

    for date, lbs in [("2026-03-01", 290.0), ("2026-03-02", 292.5), ("2026-03-03", 289.0)]:
        table.put_item(Item=_weight_day(date, lbs))
        badges = _run_day(table, date)
        assert badges["lost_10"]["earned"] is True, f"lost_10 un-earned on {date} — a 2.5 lb water swing revoked a badge (#1624)"
        seen_dates.append(badges["lost_10"]["earned_date"])

    assert seen_dates == ["2026-03-01"] * 3, f"earned_date moved across the oscillation: {seen_dates} — it must pin to the first crossing"


def test_weight_badge_not_yet_crossed_stays_locked():
    """Non-vacuity for the test above: below the threshold and never crossed, the
    badge is genuinely locked and undated."""
    table = FakeTable()
    table.put_item(Item=_weight_day("2026-03-01", 296.0))  # 4 lbs down
    badges = _run_day(table, "2026-03-01")
    assert badges["lost_10"]["earned"] is False
    assert badges["lost_10"]["earned_date"] is None
    assert badges["lost_5"]["earned"] is False


# ── AC: a streak break-and-rebuild ───────────────────────────────────────────


def test_streak_break_and_rebuild_never_un_earns_a_badge():
    """week_warrior crosses at a 7-day streak, survives the streak breaking to 0,
    and its earned_date does not move when the streak is rebuilt past 7 again."""
    table = FakeTable()
    # Build to 7, break to 0, rebuild past 7.
    series = list(range(1, 8)) + [0, 1, 2] + list(range(3, 10))
    dates = [f"2026-04-{d:02d}" for d in range(1, len(series) + 1)]

    earned_flags = []
    earned_dates = []
    for date, streak in zip(dates, series):
        table.put_item(Item=_habit_day(date, streak))
        badges = _run_day(table, date)
        if streak >= 7 or badges["week_warrior"]["earned"]:
            earned_flags.append((date, badges["week_warrior"]["earned"]))
            earned_dates.append(badges["week_warrior"]["earned_date"])

    first_cross = dates[6]  # the 7th day, streak == 7
    assert all(flag for _, flag in earned_flags[1:]), f"week_warrior un-earned when the streak broke: {earned_flags}"
    assert set(earned_dates) == {first_cross}, f"earned_date moved across the break/rebuild: {sorted(set(earned_dates))}"


def test_streak_badge_above_is_still_gated():
    """Non-vacuity: breaking the streak must NOT hand out the 30-day badge."""
    table = FakeTable()
    for i, streak in enumerate(list(range(1, 8)) + [0], start=1):
        table.put_item(Item=_habit_day(f"2026-04-{i:02d}", streak))
        badges = _run_day(table, f"2026-04-{i:02d}")
    assert badges["monthly_grind"]["earned"] is False
    assert badges["monthly_grind"]["earned_date"] is None


# ── The write-once contract ──────────────────────────────────────────────────


def test_first_earn_record_is_never_rewritten():
    table = FakeTable()
    table.put_item(Item=_weight_day("2026-03-01", 289.0))
    _run_day(table, "2026-03-01")
    before = dict(table.items[(USER_PREFIX + "achievements", "BADGE#lost_10")])

    # Ten more days of the metric bouncing around the threshold.
    for i in range(2, 12):
        table.put_item(Item=_weight_day(f"2026-03-{i:02d}", 289.0 + (3.0 if i % 2 else -3.0)))
        _run_day(table, f"2026-03-{i:02d}")

    after = table.items[(USER_PREFIX + "achievements", "BADGE#lost_10")]
    assert after == before, "the first-earn record was mutated after it was written — it must be write-once"


def test_serving_path_writes_nothing():
    """/api/achievements is a core data query: render() + read_first_earns() must not
    touch the table (CLAUDE.md — core data queries must never write)."""
    table = FakeTable()
    table.put_item(Item=_weight_day("2026-03-01", 289.0))
    _run_day(table, "2026-03-01")
    snapshot = {k: dict(v) for k, v in table.items.items()}

    inputs = ar.collect_inputs(table, USER_PREFIX, None, start_weight_lbs=300.0, today="2026-03-02", window_start="2026-01-01")
    signals = ar.signals_from(inputs)
    ar.render(signals, ar.read_first_earns(table, USER_PREFIX, None))
    assert table.items == snapshot, "the read path mutated DynamoDB"


# ── Honest dates (ADR-104) ───────────────────────────────────────────────────


def test_true_now_but_unrecorded_serves_earned_with_a_null_date():
    """A badge true right now with no ledger record yet is earned and UNDATED.
    It is never stamped with today — that was the original defect."""
    table = FakeTable()
    table.put_item(Item=_weight_day("2026-03-01", 289.0))
    inputs = ar.collect_inputs(table, USER_PREFIX, None, start_weight_lbs=300.0, today="2026-03-01", window_start="2026-01-01")
    badges = {b["id"]: b for b in ar.render(ar.signals_from(inputs), {})}
    assert badges["lost_10"]["earned"] is True
    assert badges["lost_10"]["earned_date"] is None


def test_backfill_derives_the_real_first_crossing_not_today():
    """The badge was already true weeks before the ledger existed. The backfill must
    date it from stored history — NOT from the day the sweep first ran."""
    table = FakeTable()
    for i, lbs in enumerate([296.0, 293.0, 289.5, 288.0, 287.0], start=1):
        table.put_item(Item=_weight_day(f"2026-03-{i:02d}", lbs))

    badges = _run_day(table, "2026-03-20")  # ledger's first-ever run, well after the fact
    assert badges["lost_10"]["earned"] is True
    assert badges["lost_10"]["earned_date"] == "2026-03-03", "backfill must derive the first crossing (289.5 lbs on 03-03), not stamp today"
    rec = table.items[(USER_PREFIX + "achievements", "BADGE#lost_10")]
    assert rec["date_basis"] == ar.BASIS_DERIVED


def test_underivable_badge_is_recorded_earned_but_undated():
    """exp_all_pillars has no dated series a first-crossing can be read off, so it is
    recorded earned-but-UNDATED rather than given an invented date (ADR-104)."""
    table = FakeTable()
    for i, pillar in enumerate(["sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline"], start=1):
        table.put_item(
            Item={
                "pk": USER_PREFIX + "experiments",
                "sk": f"EXP#{i}",
                "status": "completed",
                "tags": [pillar],
                "end_date": f"2026-02-{i:02d}",
            }
        )
    badges = _run_day(table, "2026-03-01")
    assert badges["exp_all_pillars"]["earned"] is True
    assert badges["exp_all_pillars"]["earned_date"] is None, "an underivable date must stay null, never today"
    rec = table.items[(USER_PREFIX + "achievements", "BADGE#exp_all_pillars")]
    assert rec["date_basis"] == ar.BASIS_UNDETERMINED

    # …while a sibling badge on the same data WITH a dated series does get a date.
    assert badges["exp_3_completed"]["earned_date"] == "2026-02-03"


def test_no_badge_ever_receives_a_manufactured_date():
    """Sweep across a run where every badge family is partly true: no earned_date may
    equal the run date unless the stored history genuinely shows that crossing."""
    table = FakeTable()
    table.put_item(Item=_weight_day("2026-03-01", 289.0))
    table.put_item(Item=_habit_day("2026-03-01", 8))
    run_date = "2026-06-15"
    badges = _run_day(table, run_date)
    dated = {b["id"]: b["earned_date"] for b in badges.values() if b["earned_date"]}
    assert run_date not in dated.values(), f"a badge was stamped with the run date: {dated}"


# ── Single source of truth for the thresholds ────────────────────────────────


def test_threshold_logic_lives_only_in_achievement_rules():
    """The writer and the reader must both delegate — neither may re-implement a
    comparison, or they drift back into the #1624 failure mode."""
    import ast

    tree = ast.parse((ROOT / "lambdas" / "web" / "site_api_vitals.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "handle_achievements")
    # Drop the docstring — it DESCRIBES the old pattern, which must not trip this guard.
    stmts = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    body = "\n".join(ast.unparse(s) for s in stmts)
    assert "earned_date" not in body, "handle_achievements still computes earned_date itself (#1624)"
    assert "achievement_rules." in body, "handle_achievements must delegate to the shared rules module"
    for literal in ("current_streak >= 7", "lost_lbs >= 10", "days_tracked >= 30"):
        assert literal not in body, f"threshold {literal!r} re-implemented in the serving path — it belongs in achievement_rules"


def test_catalog_is_complete_and_unique():
    assert len(ar.BADGE_IDS) == len(set(ar.BADGE_IDS)), "duplicate badge id"
    assert len(ar.BADGE_RULES) == 40, "badge count changed — update the /api/achievements schema snapshot too"
    for rule in ar.BADGE_RULES:
        assert rule.comparator in ar.COMPARATORS
        if rule.hint_kind == "static":
            assert rule.hint_text, f"{rule.id}: static hint with no text"


def test_achievements_partition_is_registered_in_the_phase_taxonomy():
    """ADR-077: a new partition must be classified deliberately, not defaulted."""
    import phase_taxonomy

    assert phase_taxonomy.SOURCE_CLASS["achievements"] == phase_taxonomy.EXPERIMENT_SCOPED
    assert phase_taxonomy.classify(USER_PREFIX + "achievements", "BADGE#lost_10") == phase_taxonomy.EXPERIMENT_SCOPED


# ── Across an experiment reset (ADR-077) ─────────────────────────────────────


class PhaseFilteredTable(FakeTable):
    """FakeTable + the ADR-058 read filter: tombstoned rows are hidden, exactly as
    with_phase_filter hides them on the real read paths."""

    def query(self, **kw):
        res = FakeTable.query(self, **kw)
        return {"Items": [i for i in res["Items"] if not i.get("tombstone")]}


def test_reset_tombstone_does_not_block_the_next_cycle():
    """The restart wipe tombstones IN PLACE — UpdateItem adds tombstone=true on the
    SAME pk/sk (Interpretation B); it does not move the item. So after a reset the key
    is still occupied while the phase filter hides the record.

    A bare `attribute_not_exists(sk)` would therefore refuse every write for the rest
    of the platform's life after the first reset: the writer sees an empty ledger,
    tries to record, is rejected, and swallows it. Every badge would serve
    earned-with-a-null-date forever. The archived record must be supersedable.
    """
    table = PhaseFilteredTable()
    table.put_item(Item=_weight_day("2026-03-01", 289.0))
    _run_day(table, "2026-03-01")
    ledger_key = (USER_PREFIX + "achievements", "BADGE#lost_10")
    assert table.items[ledger_key]["earned_date"] == "2026-03-01"

    # ── the reset: tombstone in place, as restart_intelligence_wipe.py does it ──
    table.items[ledger_key].update({"tombstone": True, "phase": "pilot"})
    table.items[(USER_PREFIX + "withings", "DATE#2026-03-01")]["tombstone"] = True

    # New cycle: a fresh weigh-in that crosses the same threshold.
    table.put_item(Item=_weight_day("2026-08-01", 288.0))
    badges = _run_day(table, "2026-08-01")

    assert badges["lost_10"]["earned"] is True
    assert badges["lost_10"]["earned_date"] == "2026-08-01", "the new cycle must record its own first-earn from current-cycle evidence"
    assert not table.items[ledger_key].get("tombstone"), "the archived record should have been superseded by the new cycle's"
