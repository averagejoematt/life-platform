"""tests/test_public_events_recompute_6224.py — the recomputed public projection keeps valid events (#6224).

Owner decision 2026-11-26 on the recompute: "Preserve unrelated valid activity and achievement events. Recalculate
level-dependent unlocks according to the corrected historical scores. Move milestones to their correct dates where
necessary. Do not erase legitimate history merely because a day's character sheet was recomputed. Do not retain
achievements that no longer satisfy their actual eligibility rules. Do not invent replacement events."

Held here, each with a must-fail control: a corrected-chain (current-method) variant serves its own events on their
dates whatever its origin, while an older-method variant keeps the 2026-11-06 rule; the level series, the level badges
and the level milestone ladder follow the corrected public level (kept / moved / withheld, never invented); every served
event is reproducible from the corrected per-date values; the event comparison loses no public-input pillar event and
reports a planted loss; the correction notice is the owner's text exactly; and an apply followed by a rollback on a fake
table restores every touched item byte-identically. Synthetic records only.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_events as EV  # noqa: E402
import test_public_mind_unscored_6224 as M  # noqa: E402 — the synthetic replayed chain
from health import achievement_rules, character_privacy as CP, milestone_ledger  # noqa: E402

V1, V2 = CP.PUBLIC_METHOD_V1, CP.PUBLIC_METHOD_VERSION


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    """The comparison describes the serving once the containment switch flips after a verified recompute."""
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _rec(day, level, origin, version, events=None, m1_level=None, pillars=None):
    block = {"public_method_version": version, "origin": origin, "character_level": level, "level_events": events or []}
    block.update(pillars or {})
    return {"date": day, "sk": f"DATE#{day}", "character_level": m1_level if m1_level is not None else level, B.PUBLIC: block}


SLEEP_UP = {"type": "level_up", "pillar": "sleep", "old_level": 9, "new_level": 12}
CHAR_UP = {"type": "character_level_up", "old_level": 4, "new_level": 5}


def test_a_recomputed_corrected_chain_date_serves_its_own_events():
    view = CP.public_sheet(_rec("2026-10-01", 5, "recomputed", V2, events=[SLEEP_UP, CHAR_UP]))
    assert view["level_events"] == [SLEEP_UP, CHAR_UP]
    assert [v["date"] for v in CP.public_event_sheets([_rec("2026-10-01", 5, "recomputed", V2, events=[SLEEP_UP])])] == ["2026-10-01"]


def test_must_fail_control_an_older_method_recomputed_date_still_serves_none():
    view = CP.public_sheet(_rec("2026-10-01", 5, "recomputed", V1, events=[SLEEP_UP]))
    # #6224 (2026-11-27): an older-method block is "being recalculated" whatever the switch says — no event at all
    assert view["level_events"] == [] and view["recalculated_level_events"] == [] and view["scores_pending"] is True


def test_the_level_series_credits_the_corrected_public_level():
    recs = [_rec("2026-10-01", 18, "recomputed", V2, m1_level=13), _rec("2026-10-02", 21, "recomputed", V2, m1_level=16)]
    assert CP.event_level_series(recs) == [("2026-10-01", 18), ("2026-10-02", 21)]
    old = [_rec("2026-10-01", 18, "recomputed", V1, m1_level=13)]
    assert CP.event_level_series(old) == []  # control: an older-method block credits no level (#6224 per-block rule)


def test_level_badges_follow_the_corrected_chain_kept_moved_or_withheld_never_invented():
    recs = [_rec("2026-09-10", 2, "recomputed", V2), _rec("2026-09-20", 6, "recomputed", V2), _rec("2026-10-01", 9, "recomputed", V2)]
    stored = {
        "first_level_up": {"earned_date": "2026-09-10"},
        "apprentice": {"earned_date": "2026-09-25"},
        "journeyman": {"earned_date": "2026-10-05"},
    }
    out = achievement_rules.with_corrected_level_badges(stored, recs)
    assert out["first_level_up"]["earned_date"] == "2026-09-10"  # kept
    assert out["apprentice"]["earned_date"] == "2026-09-20"  # moved to where the corrected chain crosses 5
    assert "journeyman" not in out  # level 10 never reached: not retained
    assert "adept" not in out and "master_of_the_craft" not in out  # nothing invented
    # control: with no corrected-chain variant the stored records stand as they are
    assert achievement_rules.with_corrected_level_badges(stored, [_rec("2026-09-10", 2, "live", V1)]) == stored


def test_level_milestones_are_redated_or_withheld_and_other_ladders_pass_through():
    recs = [_rec("2026-09-12", 2, "recomputed", V2), _rec("2026-09-18", 5, "recomputed", V2)]
    events = [
        {"milestone_id": "level_2", "ladder": "level", "event_date": "2026-09-12", "announce": True},
        {"milestone_id": "level_5", "ladder": "level", "event_date": "2026-09-20", "announce": True},
        {"milestone_id": "level_10", "ladder": "level", "event_date": "2026-10-03", "announce": True},
        {"milestone_id": "streak_7", "ladder": "streak", "event_date": "2026-10-04", "announce": True},
    ]
    out = {e["milestone_id"]: e for e in milestone_ledger.corrected_level_entries(events, recs)}
    assert out["level_2"]["event_date"] == "2026-09-12" and "redated_from" not in out["level_2"]
    assert out["level_5"]["event_date"] == "2026-09-18" and out["level_5"]["redated_from"] == "2026-09-20"
    assert "level_10" not in out and out["streak_7"] == events[3]
    assert milestone_ledger.corrected_level_entries(events, [_rec("2026-09-12", 2, "live", V1)]) == events  # control


@pytest.fixture(scope="module")
def chain():
    records, scores = M._history("high")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)
        pub = M._replay(records, scores)
    after = [dict(records[d], **{B.PUBLIC: pub[d]}) for d in sorted(records)]
    return records, after


def test_every_served_event_is_reproducible_from_the_corrected_per_date_values(chain):
    _records, after = chain
    events = EV.served_events(after, old_rule=False)
    values = EV.per_date_values(after)
    days = sorted(values)
    assert events, "the replayed chain fires events (the check is not vacuous)"
    for e in events:
        assert e["who"] != "mind"
        prev = values[days[days.index(e["date"]) - 1]]
        if "tier" in str(e["type"]):
            continue  # a tier event rides a level crossing checked below
        assert (prev.get(e["who"]), values[e["date"]].get(e["who"])) == (e["old"], e["new"]), e


def _pair(day: str, level: int, events: list, pillars: dict) -> tuple:
    """(before, after) records for one date: the same pillar values and events, served before as a LIVE older-method
    variant (Mind scored, a Mind event) and after as the RECOMPUTED corrected chain (no Mind)."""
    before = _rec(
        day,
        level + 1,
        "live",
        V1,
        events=events + [{"type": "level_up", "pillar": "mind", "old_level": 3, "new_level": 4}],
        pillars=pillars,
    )
    after = _rec(day, level, "recomputed", V2, events=list(events), pillars=pillars)
    return before, after


def _synthetic() -> tuple:
    rows = [
        _pair(
            "2026-11-10", 20, [], {"pillar_sleep": {"level": 31, "tier": "Momentum"}, "pillar_movement": {"level": 37, "tier": "Momentum"}}
        ),
        _pair(
            "2026-11-11",
            21,
            [{"type": "level_up", "pillar": "movement", "old_level": 37, "new_level": 40}],
            {"pillar_sleep": {"level": 31, "tier": "Momentum"}, "pillar_movement": {"level": 40, "tier": "Momentum"}},
        ),
        _pair(
            "2026-11-12",
            22,
            [{"type": "level_up", "pillar": "sleep", "old_level": 31, "new_level": 34}],
            {"pillar_sleep": {"level": 34, "tier": "Momentum"}, "pillar_movement": {"level": 40, "tier": "Momentum"}},
        ),
    ]
    return [b for b, _ in rows], [a for _, a in rows]


def test_the_event_comparison_loses_no_public_input_pillar_event():
    before, after = _synthetic()
    comp = EV.event_comparison(before, after, {"apprentice": 5}, [2, 5])
    assert comp["verbatim_losses"] == [] and comp["stored_verbatim_mismatches"] == []
    kept = [r for r in comp["events"]["rows"] if r["who"] in EV.VERBATIM]
    assert len(kept) == 2 and all(r["status"] == "KEPT" for r in kept)
    assert [r["status"] for r in comp["events"]["rows"] if r["who"] == "mind"] == ["REMOVED"] * 3


def test_must_fail_a_planted_dropped_pillar_event_is_reported_lost():
    before, after = _synthetic()
    after[1][B.PUBLIC]["level_events"] = []  # the movement event on 2026-11-11 dropped only because the date was recomputed
    comp = EV.event_comparison(before, after, {}, [])
    assert [(r["date"], r["who"], r["status"]) for r in comp["verbatim_losses"]] == [("2026-11-11", "movement", "REMOVED")]
    assert [m["date"] for m in comp["stored_verbatim_mismatches"]] == ["2026-11-11"]


def test_the_comparison_classifies_kept_moved_removed_added():
    before = [
        {"date": "d1", "who": "sleep", "type": "level_up", "old": 1, "new": 2, "key": ["sleep", "level_up", "2"]},
        {
            "date": "d2",
            "who": "character",
            "type": "character_level_up",
            "old": 2,
            "new": 3,
            "key": ["character", "character_level_up", "3"],
        },
        {"date": "d3", "who": "mind", "type": "level_up", "old": 5, "new": 6, "key": ["mind", "level_up", "6"]},
        {
            "date": "d4",
            "who": "character",
            "type": "character_level_up",
            "old": 3,
            "new": 4,
            "key": ["character", "character_level_up", "4"],
        },
    ]
    after = [
        before[0],
        dict(before[1], date="d5"),
        {"date": "d6", "who": "movement", "type": "level_up", "old": 1, "new": 2, "key": ["movement", "level_up", "2"]},
    ]
    values = {"d5": {"character": 3}, "d4": {"character": 3}, "d6": {"movement": 2}, "d55": {"movement": 1}}
    comp = EV.compare(before, after, values)
    status = {(r["date"], r["who"]): (r["status"], r.get("reason"), r.get("new_date")) for r in comp["rows"]}
    assert status[("d1", "sleep")][0] == "KEPT"
    assert status[("d2", "character")] == ("MOVED", None, "d5")
    assert status[("d3", "mind")][0] == "REMOVED" and "Mind" in status[("d3", "mind")][1]
    assert status[("d4", "character")][:2] == ("REMOVED", "the corrected chain does not reach it")
    assert status[("d6", "movement")][0] == "ADDED"


def test_the_correction_notice_is_the_owners_text_exactly():
    assert CP.PUBLIC_CORRECTION_NOTICE == (
        "We've updated how the public character's scores are calculated.\n\n"
        "Earlier versions included information that should not have contributed to the public character. We've removed "
        "those inputs and recalculated the historical scores using the approved public data.\n\n"
        "As a result, some previously displayed levels, XP totals and achievement dates may differ. The underlying "
        "activities and measurements have not changed.\n\n"
        "Mind is no longer scored publicly. Previous character scores are superseded by the corrected values."
    )
    from health import public_corrections

    led = public_corrections.build_ledger({"2026-09-06": {"character_level": 3}}, "2026-11-26")
    assert led["notice"] == CP.PUBLIC_CORRECTION_NOTICE and led["rows"] == []  # no per-date difference table


class _Table:
    """A fake DynamoDB table: get / put / delete and the two update shapes the backfill uses (SET #p = :p, REMOVE #p)."""

    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): copy.deepcopy(i) for i in items}

    def get_item(self, Key=None, **_kw):  # noqa: N803 — boto3's spelling
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_kw
    ):  # noqa: N803
        attr = (ExpressionAttributeNames or {})["#p"]
        item = self.items[(Key["pk"], Key["sk"])]
        if UpdateExpression.startswith("SET"):
            item[attr] = copy.deepcopy(ExpressionAttributeValues[":p"])
        else:
            item.pop(attr, None)

    def put_item(self, Item=None, **_kw):  # noqa: N803
        self.items[(Item["pk"], Item["sk"])] = copy.deepcopy(Item)

    def delete_item(self, Key=None, **_kw):  # noqa: N803
        self.items.pop((Key["pk"], Key["sk"]), None)


def test_apply_then_rollback_restores_every_touched_item_byte_identically():
    """The write touches only the ``public`` attribute of existing sheet / receipt items plus the one ledger item; the
    pre-image export restores all of them exactly — the item that had no ``public`` loses it again, the ledger is removed."""
    from common.numeric import floats_to_decimal

    sheet = floats_to_decimal({"pk": B.SHEET_PK, "sk": "DATE#2026-10-01", "character_level": 13, "public": {"character_level": 18}})
    receipt = floats_to_decimal({"pk": B.RECEIPT_PK, "sk": "DATE#2026-10-01", "digest": "x"})  # no public block before
    other = floats_to_decimal({"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-10-01", "hrv": 50})
    table = _Table([sheet, receipt, other])
    before = json.dumps({str(k): v for k, v in sorted(table.items.items())}, sort_keys=True, default=str)
    plan = [
        {"pk": B.SHEET_PK, "sk": "DATE#2026-10-01", "value": {"character_level": 16, "public_method_version": V2}, "precision": 4},
        {"pk": B.RECEIPT_PK, "sk": "DATE#2026-10-01", "value": {"transitions": {}}, "precision": None},
    ]
    export = B.build_export(lambda key: table.get_item(Key=key).get("Item"), plan, "2026-11-26T00:00:00Z")
    B.record_ledger_preimage(table, export)
    result = B.apply_plan(table, plan, export)
    B.put_public_ledger(table, {"ledger_version": "v2", "rows": []})
    assert result["written"] == 2 and not result["skipped"]
    assert table.items[(B.SHEET_PK, "DATE#2026-10-01")]["character_level"] == sheet["character_level"]  # method 1 untouched
    assert table.items[("USER#matthew#SOURCE#whoop", "DATE#2026-10-01")] == other  # nothing else touched
    done = B.rollback(table, export, apply=True)
    assert not done["refused"]
    after = json.dumps({str(k): v for k, v in sorted(table.items.items())}, sort_keys=True, default=str)
    assert after == before
