"""tests/test_achievements_badges_1126.py — the badge catalog + its #1126 extension.

/api/achievements feeds three surfaces (the cockpit Journey lens, the character
sheet's Unlocks wall, and the dedicated /data/badges/ page shipped by #1126) from
ONE handler, so the catalog gets engine tests here:

  * ADR-104 honesty — with no records (the genesis-day state) NOTHING is earned,
    and an unearned badge never carries an earned_date;
  * the #1126 catalog additions (fortnight / half_year_hold / adept /
    master_of_the_craft / lost_5 / 30_days) earn at their thresholds and not
    below them;
  * structural contract — unique ids, known categories, the fields every badge
    render consumes, and honest unlock hints on locked marks.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_vitals as vitals  # noqa: E402

NEW_IDS = {"fortnight", "half_year_hold", "adept", "master_of_the_craft", "lost_5", "30_days"}

KNOWN_CATEGORIES = {"streak", "level", "milestone", "data", "science", "challenge"}


def _cond_strings(cond, out):
    """Collect string leaves from a boto3 condition tree (Key('pk').eq(...) & ...)."""
    for v in getattr(cond, "_values", ()) or ():
        if isinstance(v, str):
            out.append(v)
        else:
            _cond_strings(v, out)
    return out


def _fake_table(rows):
    """#1624: the handler now builds its queries in achievement_rules, which uses
    STRING KeyConditionExpressions + ExpressionAttributeValues rather than boto3
    Key() objects. Resolve the pk from either form so this harness keeps exercising
    the real handler instead of silently matching nothing (a pk of None matches no
    row, which would make every badge trivially unearned and these tests vacuous)."""

    def hook(table, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        if isinstance(cond, str):
            pk = (kwargs.get("ExpressionAttributeValues") or {}).get(":pk")
        else:
            strings = _cond_strings(cond, [])
            pk = next((s for s in strings if s.startswith("USER#")), None)
        assert pk is not None, f"harness could not resolve a pk from {cond!r}"
        items = [r for r in rows if r.get("pk") == pk]
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    return FakeDdbTable(query_hook=hook)


def _withings_row(latest_withings):
    """#1624: weight is read from the withings DATE# series now (the badge engine needs
    the dated series to derive first-earn dates), not via _latest_item. Materialise the
    single latest reading these tests supply as one dated row."""
    if not latest_withings:
        return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [{"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{today}", **latest_withings}]


def _call(monkeypatch, rows, latest_withings=None, profile=None):
    monkeypatch.setattr(vitals, "table", _fake_table(list(rows) + _withings_row(latest_withings)))
    monkeypatch.setattr(vitals, "_get_profile", lambda: profile or {})
    resp = vitals.handle_achievements()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def _habit_rows(n, streak):
    """n habit_score day-records inside the 365d count window, latest first
    (the handler's latest-streak query is ScanIndexForward=False, Limit=1)."""
    today = datetime.now(timezone.utc)
    rows = []
    for i in range(n):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append(
            {
                "pk": "USER#matthew#SOURCE#habit_scores",
                "sk": f"DATE#{d}",
                "t0_perfect_streak": Decimal(str(streak if i == 0 else max(0, streak - i))),
            }
        )
    return rows


# ── ADR-104: the genesis-day state — no records, nothing earned ──────────────


def test_genesis_day_nothing_earned(monkeypatch):
    body = _call(monkeypatch, rows=[], latest_withings=None, profile={})
    assert body["summary"]["earned"] == 0
    assert body["summary"]["total"] == len(body["achievements"])
    for a in body["achievements"]:
        assert a["earned"] is False, f"{a['id']} earned with zero records — ADR-104 violation"
        assert a["earned_date"] is None, f"{a['id']} carries an earned_date while unearned"


def test_unearned_never_carries_earned_date_even_with_data(monkeypatch):
    body = _call(
        monkeypatch,
        rows=_habit_rows(30, streak=14)
        + [{"pk": "USER#matthew#SOURCE#character_sheet", "sk": "DATE#2026-07-12", "character_level": Decimal("20")}],
        latest_withings={"weight_lbs": Decimal("295.0")},
        profile={"journey_start_weight_lbs": 300.8},
    )
    for a in body["achievements"]:
        if not a["earned"]:
            assert a["earned_date"] is None, f"{a['id']} carries an earned_date while unearned"


# ── the #1126 catalog additions earn at their thresholds ─────────────────────


def _by_id(body):
    return {a["id"]: a for a in body["achievements"]}


def test_streak_rungs_fortnight_and_half_year(monkeypatch):
    body = _by_id(_call(monkeypatch, rows=_habit_rows(14, streak=14)))
    assert body["week_warrior"]["earned"] is True
    assert body["fortnight"]["earned"] is True
    assert body["monthly_grind"]["earned"] is False
    assert body["half_year_hold"]["earned"] is False
    # honest countdown hints on the locked rungs
    assert body["monthly_grind"]["unlock_hint"] == "16 days to unlock"
    assert body["half_year_hold"]["unlock_hint"] == "166 days to unlock"

    below = _by_id(_call(monkeypatch, rows=_habit_rows(13, streak=13)))
    assert below["fortnight"]["earned"] is False
    assert below["fortnight"]["unlock_hint"] == "1 days to unlock"


def test_level_rungs_adept_and_master(monkeypatch):
    sheet = [{"pk": "USER#matthew#SOURCE#character_sheet", "sk": "DATE#2026-07-12", "character_level": Decimal("20")}]
    body = _by_id(_call(monkeypatch, rows=sheet))
    assert body["journeyman"]["earned"] is True
    assert body["adept"]["earned"] is True
    assert body["master_of_the_craft"]["earned"] is False
    assert body["master_of_the_craft"]["unlock_hint"] == "Level 20 → Level 40 needed"

    below = _by_id(_call(monkeypatch, rows=[dict(sheet[0], character_level=Decimal("19"))]))
    assert below["adept"]["earned"] is False
    assert below["adept"]["unlock_hint"] == "Level 19 → Level 20 needed"


def test_lost_5_first_weight_rung(monkeypatch):
    body = _by_id(
        _call(monkeypatch, rows=[], latest_withings={"weight_lbs": Decimal("295.0")}, profile={"journey_start_weight_lbs": 300.8})
    )
    assert body["lost_5"]["earned"] is True
    assert body["lost_10"]["earned"] is False

    below = _by_id(
        _call(monkeypatch, rows=[], latest_withings={"weight_lbs": Decimal("297.0")}, profile={"journey_start_weight_lbs": 300.8})
    )
    assert below["lost_5"]["earned"] is False
    assert below["lost_5"]["unlock_hint"] == "1 lbs to go"  # 3.8 rounds via :.0f


def test_month_of_data_rung(monkeypatch):
    body = _by_id(_call(monkeypatch, rows=_habit_rows(30, streak=3)))
    assert body["30_days"]["earned"] is True
    assert body["100_days"]["earned"] is False

    below = _by_id(_call(monkeypatch, rows=_habit_rows(29, streak=3)))
    assert below["30_days"]["earned"] is False
    assert below["30_days"]["unlock_hint"] == "1 days to unlock"


# ── structural contract for every badge surface ──────────────────────────────


def test_catalog_structure(monkeypatch):
    body = _call(monkeypatch, rows=[])
    ids = [a["id"] for a in body["achievements"]]
    assert len(ids) == len(set(ids)), "duplicate badge ids"
    assert NEW_IDS <= set(ids), f"missing #1126 additions: {NEW_IDS - set(ids)}"
    assert len(ids) >= 40  # 34 pre-#1126 + the 6 additions (>= so later additions don't red this)
    for a in body["achievements"]:
        assert set(a) == {"id", "label", "category", "description", "earned", "earned_date", "icon", "unlock_hint"}
        assert a["category"] in KNOWN_CATEGORIES, f"{a['id']}: unknown category {a['category']}"
        assert a["label"] and a["description"]
    # the additions use generative marks (badgeMark seeded by id) — no emoji icons
    for a in body["achievements"]:
        if a["id"] in NEW_IDS:
            assert a["icon"] is None, f"{a['id']} ships an icon glyph — the front-end draws generative marks"


def test_locked_marks_say_what_unlocks_them(monkeypatch):
    """#1126 acceptance: the unearned state is honest AND actionable — every new
    rung carries either an unlock_hint or a self-explanatory description."""
    body = _by_id(_call(monkeypatch, rows=[]))
    for bid in NEW_IDS:
        a = body[bid]
        assert a["unlock_hint"] or a["description"], f"{bid} locked with no path shown"
