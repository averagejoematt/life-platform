"""tests/test_recumbent_after_heavy_lower_5076.py — the recumbent rule as the owner ruled it (2026-10-25, #5076).

Ruling, verbatim: "a" — option (a): "after a lower day" means only the day immediately after a HEAVY lower session,
and only for conditioning blocks; easy days stay on the incline treadmill walk.

Before it, the draft path passed a generic archetype (never a `split.sequence` name), so `recumbent_after` meant
"today is a lower day" and the session before was never read. Now `cardio_menu.choose_kind` reads `previous`
(`cardio_menu.previous_performed` over the Hevy sequence's last credited session, `session_sequence.next_session`'s
`advanced_by`) and serves the recumbent only when that session was `placement.recumbent_after_session` AND it was
yesterday AND the block is a conditioning kind. Loaded walking legs (the second clause) are unchanged.

Tempo and intervals list no treadmill (`cardio_menu.blocks.<kind>.machines`), so on fresh legs they stay on the
bike by the menu's machine list. The why line says so, and the rule is not the reason. The tests pin both halves.

Pure: no clock (every date is passed in), no AWS, no AI.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from training import cardio_menu as cm, training_charter as tc  # noqa: E402

SEQ = tc.charter_value("split.sequence")
DAY = "2026-10-21"  # a Wednesday: Shoulders+arms in the nominal week


def _prev(role: str, date: str = "2026-10-20") -> dict:
    return cm.previous_performed({"session_role": role, "date": date}, DAY)


def _pick(previous, *, last=None, week=None, legs=False, archetype="Shoulders+arms"):
    return cm.choose_kind(
        target_date=DAY,
        archetype=archetype,
        week_kinds=week or [],
        legs_loaded=legs,
        last_tempo_or_hills=last,
        previous=previous,
        days_left=3,
    )


def test_the_charter_carries_the_ruled_meaning_and_the_version_moved():
    c = tc.charter_value("cardio_menu.placement")
    assert c["recumbent_after"][0] == "the day immediately after a heavy lower session, for a conditioning block only"
    assert c["recumbent_after_session"] in SEQ and cm.recumbent_after_session() == "Lower-heavy"
    assert set(cm.recumbent_after_kinds()) == set(cm.HARD)
    import json

    charter = json.loads((REPO / "config" / "training_charter.json").read_text())
    line = next(e for e in charter["change_log"] if "#5076" in e["by"] and "2026-10-25" in e["by"])
    assert line["version"] >= "1.31.0" and line["version"] <= charter["version"]  # restacked at the batch-2 merge (1.31.0 -> 1.32.0)
    assert 'verbatim: "a"' in line["by"] and "only the day immediately after a heavy lower session" in line["by"]


def test_after_lower_heavy_a_tempo_block_rides_the_recumbent_by_the_rule():
    pick = _pick(_prev("lower_heavy"))
    assert (pick["kind"], pick["machine"]) == ("tempo", cm.RECUMBENT)
    assert pick["why"].endswith("the recumbent: conditioning the day after Lower-heavy (the session before was lower_heavy on 2026-10-20)")


def test_after_lower_heavy_a_hills_block_rides_the_recumbent_and_after_lower_volume_it_walks():
    """Hills is the conditioning kind that lists the treadmill, so it is where the rule changes the machine."""
    heavy = _pick(_prev("lower_heavy"), last="tempo")
    volume = _pick(_prev("lower_volume"), last="tempo")
    assert (heavy["kind"], heavy["machine"]) == ("hills", cm.RECUMBENT)
    assert (volume["kind"], volume["machine"]) == ("hills", cm.TREADMILL)
    assert "hills on the treadmill: fresh legs (the session before was lower_volume on 2026-10-20" in volume["why"]
    off = cm.off_default("hills", cm.RECUMBENT, legs_loaded=False, previous=_prev("lower_heavy"))
    assert off["charter"] == "cardio_menu.placement.recumbent_after"


def test_after_lower_volume_a_tempo_block_is_not_put_on_the_recumbent_by_the_rule():
    """Tempo lists no treadmill (`cardio_menu.blocks.tempo.machines`), so the walk is not an option for it. The block
    stays on the menu's first machine, and the why says the menu put it there, not the recumbent rule."""
    assert cm.TREADMILL not in tc.charter_value("cardio_menu.blocks.tempo.machines")
    pick = _pick(_prev("lower_volume"))
    assert pick["kind"] == "tempo" and pick["machine"] == tc.charter_value("cardio_menu.blocks.tempo.machines")[0]
    assert "the recumbent:" not in pick["why"]
    assert pick["why"].endswith(
        "tempo on the bike: the menu's machines for tempo (cardio_menu.blocks.tempo.machines), not the recumbent rule"
    )


def test_after_lower_heavy_an_easy_day_stays_on_the_incline_walk():
    pick = _pick(_prev("lower_heavy"), week=["tempo", "intervals"])
    assert (pick["kind"], pick["machine"]) == ("incline_treadmill_walk", cm.TREADMILL)
    assert pick["why"].endswith(
        "the incline walk: an easy day stays on the walk, also the day after Lower-heavy (the session before was lower_heavy on 2026-10-20)"
    )
    # an easy block a chat author put on the bike is the author's machine, never the recumbent rule
    assert cm.off_default("easy", cm.RECUMBENT, legs_loaded=False, previous=_prev("lower_heavy"))["charter"] is None


def test_lower_heavy_two_days_ago_is_not_the_day_immediately_after():
    prev = _prev("lower_heavy", date="2026-10-19")
    assert prev["day_before"] is False and not cm.after_heavy_lower(prev)
    assert _pick(prev, last="tempo")["machine"] == cm.TREADMILL


def test_a_lower_day_itself_is_not_a_recumbent_day_and_unread_previous_is_named():
    pick = _pick(None, week=["tempo", "intervals"], archetype="Lower-volume")
    assert pick["machine"] == cm.TREADMILL and pick["why"].endswith("(the session before was not read)")
    assert cm.previous_performed(None, DAY) is None and cm.previous_performed({"date": "2026-10-20"}, DAY) is None


def test_loaded_walking_legs_still_put_every_block_on_the_recumbent():
    """The heavy-walking-weekend clause is outside the ruling and unchanged."""
    easy = _pick(_prev("upper_volume"), week=["tempo", "intervals"], legs=True)
    hills = _pick(_prev("upper_volume"), last="tempo", legs=True)
    assert (easy["kind"], easy["machine"]) == ("easy", cm.RECUMBENT) and "heavy walking load" in easy["why"]
    assert hills["machine"] == cm.RECUMBENT


def test_the_weeks_cardio_minutes_are_unchanged_by_the_ruling():
    """The same Mon-Fri week placed before the ruling (`[tempo, easy, intervals, incline walk, easy]`, the pinned
    pre-ruling placement) and after it: each day keeps its block minutes, so the week's movement minutes match."""
    week = [{"date": f"2026-10-{19 + i}", "archetype": SEQ[i]} for i in range(5)] + [{"date": "2026-10-24", "archetype": None}]
    placed = [p for p in cm.place_week(week) if p]
    before = ["tempo", "easy", "intervals", "incline_treadmill_walk", "easy"]
    after = [p["kind"] for p in placed]
    assert after == ["tempo", "incline_treadmill_walk", "intervals", "incline_treadmill_walk", "incline_treadmill_walk"]
    assert [cm.block_minutes(k) for k in after] == [cm.block_minutes(k) for k in before]
    assert sum(cm.block_minutes(k) for k in after) == sum(cm.block_minutes(k) for k in before) > 0
    # the day after Lower-heavy is the one recumbent-by-rule day of the week
    assert [p["machine"] for p in placed] == [cm.RECUMBENT, cm.TREADMILL, cm.RECUMBENT, cm.TREADMILL, cm.TREADMILL]
    assert "the recumbent: conditioning the day after Lower-heavy" in placed[2]["why"]
