"""tests/test_paused_habits_5007.py — the `paused_since` registry facet (#5007).

Fixture: the 2026-10-11..17 week. Synthetic habit names (the repo is public and the real
names are owner data). A stack of supplement habits is paused 2026-10-10 and Habitify keeps
marking them `failed` every day; four non-supplement habits are missed on alternating days.
The pause must remove EXACTLY the stack's share and nothing else; the mutation control (the
same fixture without the facet) must bring every miss back.
"""

import copy
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.habit_pause import is_name_paused_on, is_paused_on  # noqa: E402
from emails.habit_skip_review_lambda import collect_skips  # noqa: E402
from health.habit_streaks import compute_habit_streaks  # noqa: E402
from health.scoring_engine import habitify_reading, score_habits_registry  # noqa: E402

import mcp.tools_habits as th  # noqa: E402

WEEK = [f"2026-10-{d}" for d in range(11, 18)]
STACK = [f"Supp {i}" for i in range(12)]  # the paused supplement stack
OTHERS = ["Walk", "Journal", "Floss", "Stretch"]
SINCE = "2026-10-10"


def _registry(paused=True):
    reg = {}
    for n in STACK:
        reg[n] = {"status": "active", "tier": 1, "category": "supplement", "applicable_days": "daily"}
        if paused:
            reg[n]["paused_since"] = SINCE
    for n in OTHERS:
        reg[n] = {"status": "active", "tier": 1, "category": "other", "applicable_days": "daily"}
    return reg


def _day(date):
    st = {n: {"status": "failed", "group": "Optimize"} for n in STACK}
    for i, n in enumerate(OTHERS):
        miss = (int(date[-2:]) + i) % 2 == 0
        st[n] = {"status": "failed" if miss else "completed", "group": "Other"}
    return {
        "date": date,
        "habit_statuses": st,
        "habits": {n: (1.0 if v["status"] == "completed" else 0.0) for n, v in st.items()},
    }


def _queue(monkeypatch, registry, rows):
    monkeypatch.setattr(th, "_recent_habitify", lambda days: rows)
    monkeypatch.setattr(th, "_captured_reflections", lambda days: {})
    monkeypatch.setattr(th, "get_profile", lambda: {"habit_registry": registry})
    return th.tool_get_habit_reflection_queue({"days": 7})


def test_helper_semantics():
    assert is_paused_on({"paused_since": SINCE}, "2026-10-10")
    assert is_paused_on({"paused_since": SINCE}, "2026-10-17")
    assert not is_paused_on({"paused_since": SINCE}, "2026-10-09")  # history reads as before
    assert not is_paused_on({}, "2026-10-17")
    assert not is_paused_on({"paused_since": SINCE}, None)
    assert is_name_paused_on({"A": {"paused_since": SINCE, "habitify_names": ["Old A"]}}, "Old A", "2026-10-11")


def test_queue_paused_stack_contributes_zero_misses(monkeypatch):
    rows = [_day(d) for d in WEEK]
    others_missed = sum(1 for r in rows for n in OTHERS if r["habit_statuses"][n]["status"] == "failed")
    assert others_missed > 0

    with_facet = _queue(monkeypatch, _registry(paused=True), rows)
    assert with_facet["missed_needs_why_total"] == others_missed
    assert {m["habit"] for m in with_facet["missed_needs_why"]} <= set(OTHERS)
    assert with_facet["paused_habit_days"] == len(STACK) * len(WEEK)

    # mutation control: drop the facet and the stack's share is back, exactly.
    without = _queue(monkeypatch, _registry(paused=False), rows)
    assert without["missed_needs_why_total"] == others_missed + len(STACK) * len(WEEK)
    assert without["paused_habit_days"] == 0


def test_days_before_paused_since_still_count(monkeypatch):
    rows = [_day("2026-10-09"), _day("2026-10-10")]
    out = _queue(monkeypatch, _registry(paused=True), rows)
    stack_misses = [m for m in out["missed_needs_why"] if m["habit"] in STACK]
    assert {m["date"] for m in stack_misses} == {"2026-10-09"}
    assert len(stack_misses) == len(STACK)


def test_reading_and_score_treat_paused_as_not_scheduled():
    reg = _registry()
    rec = _day("2026-10-14")
    assert habitify_reading(rec["habits"], STACK[0], reg[STACK[0]], rec["habit_statuses"]) == 0.0  # date-blind: as before
    assert habitify_reading(rec["habits"], STACK[0], reg[STACK[0]], rec["habit_statuses"], "2026-10-14") is None

    data = {"date": "2026-10-14", "habitify": {"habits": rec["habits"], "habit_statuses": rec["habit_statuses"]}}
    _, paused_details = score_habits_registry(data, {"habit_registry": reg})
    _, base_details = score_habits_registry(data, {"habit_registry": _registry(paused=False)})
    assert paused_details["paused"] == STACK
    assert paused_details["tier1"]["total"] == len(OTHERS)
    assert base_details["tier1"]["total"] == len(OTHERS) + len(STACK)
    assert not any(n in paused_details["tier_status"][1] for n in STACK)


def test_streak_not_broken_by_paused_habit():
    reg = {"Walk": {"status": "active", "tier": 0}, "Supp": {"status": "active", "tier": 0, "paused_since": SINCE}}
    recs = {
        d: {"habits": {"Walk": 1.0, "Supp": 0.0}, "habit_statuses": {"Walk": {"status": "completed"}, "Supp": {"status": "failed"}}}
        for d in WEEK
    }
    out = compute_habit_streaks({"habit_registry": reg}, WEEK[-1], lambda src, d: recs.get(d))
    assert out["tier0_streak"] == len(WEEK)
    reg["Supp"].pop("paused_since")
    out = compute_habit_streaks({"habit_registry": reg}, WEEK[-1], lambda src, d: recs.get(d))
    assert out["tier0_streak"] == 0


def test_skip_nag_ignores_paused_stack():
    records = {"2026-10-12": {"habit_statuses": {**{n: {"status": "skipped"} for n in STACK}, "Walk": {"status": "skipped"}}}}
    assert collect_skips(records, ["2026-10-12"], _registry(paused=True)) == [("2026-10-12", ["Walk"])]
    assert len(collect_skips(records, ["2026-10-12"], _registry(paused=False))[0][1]) == len(STACK) + 1
    assert collect_skips(copy.deepcopy(records), ["2026-10-12"]) == collect_skips(records, ["2026-10-12"], {})
