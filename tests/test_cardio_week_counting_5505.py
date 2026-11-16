"""tests/test_cardio_week_counting_5505.py — the week's conditioning count under the owner's 2026-11-08 ruling (#5505).

The charter asks for `cardio_menu.conditioning_sessions_per_wk` hard blocks a week. The count used to read only blocks he
PERFORMED as hard, so a week of substituted or skipped blocks re-placed "conditioning 1 of 2" every day (the 10-26 and
11-02 weeks each offered a hard block four times). The ruling (recorded on #5505):

  * a block done on another machine than the one served counts when his note logs an RPE at or above the served kind's
    band — a swap with no logged effort is not evidence (an incline walk instead of a bike tempo is not the tempo);
  * a missed hard offer is re-offered `missed_reoffers_per_wk` times a week; every later miss is dropped (counted).

The replay reads the REAL performed cardio of both weeks (tests/fixtures/cardio_week_5505/performed.json, read-only off
DynamoDB) and simulates the drafts forward under the rule: each day's offer is the menu's own pick, pushed when hard.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from types import SimpleNamespace as NS
from typing import Any

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import cardio_menu, cardio_note  # noqa: E402

_FIX = json.loads((_REPO / "tests" / "fixtures" / "cardio_week_5505" / "performed.json").read_text())


def _by_machine(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in cardio_note.MACHINES}
    for r in rows:
        out.setdefault(r["machine"], []).append({k: v for k, v in r.items() if k != "machine"})
    return out


def _pushed(day: str, kind: str, machine: str = "cycling", **kw: Any) -> NS:
    ex = NS(movement_key=machine, rationale_tag=f"cardio:{machine}:menu:{kind}", notes="")
    return NS(
        target_date=day,
        hevy_routine_id=kw.get("hid", f"h-{day}"),
        status=kw.get("status", "active"),
        version=kw.get("version", 1),
        exercises=[ex],
    )


def _simulate(week_start: str, *, count_missed: bool) -> list[tuple[str, str, str]]:
    """Each day of the week: the menu's pick given his real performed blocks and the simulated pushed offers so far."""
    by_machine = _by_machine(_FIX["weeks"][week_start])
    offers: list[NS] = []
    out = []
    for i in range(7):
        day = (dt.date.fromisoformat(week_start) + dt.timedelta(days=i)).isoformat()
        week = cardio_note.week_kinds(by_machine, week_start, day)
        if count_missed:
            missed = cardio_menu.missed_offers(
                cardio_menu.offered_hard(offers, week_start, day), cardio_note.week_rows(by_machine, week_start, day)
            )
            week = week + missed[cardio_menu.reoffers_per_wk() :]
        pick = cardio_menu.choose_kind(target_date=day, week_kinds=week, days_left=7 - i)
        out.append((day, pick["kind"], pick["why"].split(";")[0]))
        if pick["kind"] in cardio_menu.HARD:
            offers.append(_pushed(day, pick["kind"]))
    return out


@pytest.mark.parametrize("week_start", sorted(_FIX["weeks"]))
def test_a_real_week_of_missed_blocks_is_offered_at_most_once_more_then_dropped(week_start):
    days = _simulate(week_start, count_missed=True)
    hard = [why for _d, kind, why in days if kind in cardio_menu.HARD]
    per_wk = cardio_menu.conditioning_per_wk()
    assert len(hard) <= per_wk + cardio_menu.reoffers_per_wk(), days
    assert hard == [
        f"conditioning 1 of {per_wk} this week",
        f"conditioning 1 of {per_wk} this week",  # the one re-offer
        f"conditioning 2 of {per_wk} this week",
    ], days
    assert all(kind not in cardio_menu.HARD for _d, kind, _w in days[days.index(next(d for d in days if "2 of" in d[2])) + 1 :])


@pytest.mark.parametrize("week_start", sorted(_FIX["weeks"]))
def test_without_the_missed_count_the_same_week_reoffers_daily(week_start):
    """Negative control: the pre-#5505 count (performed only) re-offers past the rule's bound on the same real week."""
    days = _simulate(week_start, count_missed=False)
    hard = [d for d in days if d[1] in cardio_menu.HARD]
    assert len(hard) > cardio_menu.conditioning_per_wk() + cardio_menu.reoffers_per_wk(), days


# ── the swap rule ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_swap_counts_only_at_the_logged_prescribed_effort():
    lo = cardio_menu.wire_band("tempo")[0]
    assert cardio_menu.kind_of_performed("treadmill", f"RPE {lo}", swap_kind="tempo") == "tempo"
    assert cardio_menu.kind_of_performed("treadmill", f"rpe {lo + 1}, felt good", swap_kind="tempo") == "tempo"
    # no logged effort, or under the band: the machine's easy kind
    assert cardio_menu.kind_of_performed("treadmill", "3.1 mph / 5 incline", swap_kind="tempo") == "incline_treadmill_walk"
    assert cardio_menu.kind_of_performed("treadmill", f"RPE {lo - 1}", swap_kind="tempo") == "incline_treadmill_walk"
    assert cardio_menu.kind_of_performed("cycling", "", swap_kind="intervals") == "easy"
    assert cardio_menu.kind_of_performed("cycling", "RPE 9 easy", swap_kind="intervals") == "intervals"  # an RPE is evidence
    # an easy kind is never a swap candidate
    assert cardio_menu.kind_of_performed("cycling", "RPE 9", swap_kind="easy") == "easy"


def test_annotate_served_marks_the_swap_only_for_one_hard_block_on_another_machine():
    catalog = json.loads((_REPO / "config" / "movement_catalog.json").read_text())
    tids = {v: k for k, v in cardio_menu.machine_template_ids(catalog).items()}
    index = {tids["treadmill"]: [{"date": "2026-11-05", "note": "", "hevy_routine_id": "h1"}]}
    one = cardio_menu.annotate_served(index, {"h1": {"cycling": "tempo"}}, catalog)
    assert one[tids["treadmill"]][0].get("served_swap_kind") == "tempo"
    same = cardio_menu.annotate_served(index, {"h1": {"treadmill": "hills"}}, catalog)
    assert same[tids["treadmill"]][0].get("served_kind") == "hills" and "served_swap_kind" not in same[tids["treadmill"]][0]
    easy = cardio_menu.annotate_served(index, {"h1": {"cycling": "easy"}}, catalog)
    assert "served_swap_kind" not in easy[tids["treadmill"]][0]


# ── what counts as an offer ───────────────────────────────────────────────────────────────────────────────────────
def test_only_a_pushed_current_non_test_hard_block_is_an_offer():
    rs = [
        _pushed("2026-11-03", "tempo", version=4),
        _pushed("2026-11-03", "hills", version=3, hid="older"),  # an older version that day
        NS(target_date="2026-11-04", hevy_routine_id=None, status="draft", version=2, exercises=[_pushed("x", "tempo").exercises[0]]),
        _pushed("2026-11-05", "tempo", status="archived"),
        _pushed("2026-11-06", "easy"),
        NS(
            target_date="2026-11-07",
            hevy_routine_id="t",
            status="active",
            version=3,
            exercises=[NS(movement_key="treadmill", rationale_tag="fitness_test:six_minute_walk", notes="Test · 6-minute walk")],
        ),
        _pushed("2026-11-09", "intervals"),  # next week
    ]
    assert cardio_menu.offered_hard(rs, "2026-11-02", "2026-11-09") == [("2026-11-03", "tempo")]


def test_one_hard_block_performed_meets_one_offer_that_day():
    offered = [("2026-11-03", "tempo"), ("2026-11-05", "tempo"), ("2026-11-06", "intervals")]
    performed = [("2026-11-03", "incline_treadmill_walk"), ("2026-11-05", "tempo"), ("2026-11-06", "easy")]
    assert cardio_menu.missed_offers(offered, performed) == ["tempo", "intervals"]


def test_the_label_is_the_slot_ordinal_never_past_the_week():
    # three hard kinds that all fill the tempo-or-hills slot: the intervals slot is still needed — slot 2, not "4 of 2"
    pick = cardio_menu.choose_kind(target_date="2026-11-05", week_kinds=["tempo", "tempo", "hills"], days_left=3)
    assert pick["kind"] == "intervals" and pick["why"].startswith("conditioning 2 of 2 this week"), pick["why"]


def test_history_context_without_routines_is_the_performed_count():
    by = _by_machine(_FIX["weeks"]["2026-11-02"])
    index = {}
    catalog = json.loads((_REPO / "config" / "movement_catalog.json").read_text())
    for tid, key in cardio_menu.machine_template_ids(catalog).items():
        index[tid] = by.get(key, [])
    h = cardio_menu.history_context(index, catalog, "2026-11-08")
    assert h["missed_kinds"] == [] and h["dropped_kinds"] == [] and h["counted_kinds"] == h["week_kinds"]
