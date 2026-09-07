"""#3666 — Habitify completions are attributed to the PACIFIC day they were made.

THE BUG, MEASURED ON THE WIRE (2026-09-06, the fixture in this directory)
------------------------------------------------------------------------
`GET /journal?target_date=D` buckets by the **UTC date of the tick**; the record is
filed under a **Pacific** `DATE#` key. Those disagree for the 7-8 evening PT hours that
are already tomorrow in UTC, so ONE Pacific day was split across TWO `DATE#` rows at
17:00 PT and neither was ever right:

    target_date=2026-09-06  ->  38 failed · 23 in_progress ·  0 completed
    target_date=2026-09-07  ->                              15 completed

Then `resolved = "pending" if date_str >= today_utc else "failed"` rewrote the earlier
row's still-open habits to `failed`. `DATE#2026-09-06` stored 61 failed / 0 completed on
a day the owner completed fifteen habits, and `habit_scores` read `composite=0,
tier0_done=0` — a total-failure narrative on every coach and reader surface.

THE FIX: `GET /logs/{habit_id}` -> `created_date` -> Pacific day. Correct in both real
cases, both present in the fixture verbatim:

    same-day evening tick   "2026-09-07T02:11:22.363Z" -> Pacific 2026-09-06 (19:11:22 PT)
    back-dated two days     "2026-09-04T07:00:00.000Z" -> Pacific 2026-09-04 (00:00 PDT)

Every date-dependent test here pins `pacific_today` explicitly. A test that read the real
clock would be the same class of defect as the bug: `test_in_progress_past_day_resolves_
to_failed` in the sibling file passed for months precisely because it derived "yesterday"
in the wrong frame.

Run:  python3 -m pytest tests/test_habitify_pacific_attribution_3666.py -v
"""

import ast
import copy
import json
import os
import re
import sys
import types
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

if "ingestion.ingestion_framework" not in sys.modules:  # same shim as the sibling file
    _fake = types.ModuleType("ingestion_framework")
    _fake.IngestionConfig = lambda **kw: kw
    _fake.run_ingestion = lambda *a, **kw: {}
    sys.modules["ingestion.ingestion_framework"] = _fake

import habitify_lambda  # noqa: E402
from habitify_lambda import logs_on_pacific_day, logs_window, transform, upgrade_only_merge  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "habitify", "habitify_2026-09-06_wire.json")

# The fifteen real completions of Pacific 2026-09-06, ticked 19:11:22-19:13:39 PT — i.e.
# 02:11-02:13 UTC on 2026-09-07, which is why the pre-fix code filed them on the wrong day.
EXPECTED_0906 = {
    "Cold Shower",
    "Collagen",
    "Creatine",
    "Electrolytes",
    "Food Journal",
    "Intermittent Fast 16:8",
    "L Glutamine",
    "No Fried Food",
    "No alcohol",
    "No solo takeout",
    "No sweets",
    "Social Gratitude Touchpoint",
    "Vice Habit (name withheld)",
    "Walk Outdoor >2mi",
    "Weigh In",
}


def _wire():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _raw(wire=None, with_logs=True):
    wire = wire or _wire()
    raw = {
        "date": "2026-09-06",
        "area_map": wire["area_map"],
        "journal": wire["journal"],
        "moods": [],
    }
    if with_logs:
        raw["logs"] = wire["logs"]
    return raw


def _run(monkeypatch, date_str, today_pt, raw=None, wire=None, with_logs=True):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: today_pt)
    return transform(raw if raw is not None else _raw(wire, with_logs), date_str)[0]


def _completed(record):
    return {n for n, hs in record["habit_statuses"].items() if hs["status"] == "completed"}


def _daily_completed(record):
    """Completions of DAILY habits — the set the attribution rule decides.

    `Sauna` is `periodicity: monthly` and is deliberately excluded: its journal
    `completed` is a PERIOD judgement the vendor owns, preserved verbatim rather than
    re-derived per day (see `test_a_non_daily_habits_period_judgement_is_preserved`).
    """
    return {n for n, hs in record["habit_statuses"].items() if hs["status"] == "completed" and hs["periodicity"] == "daily"}


# ── 1. THE ATTRIBUTION RULE ──────────────────────────────────────────────────────────


def test_the_fifteen_evening_ticks_land_on_the_pacific_day_they_were_made(monkeypatch):
    """The headline assertion, replayed off the live wire capture.

    Fifteen ticks whose `created_date` is 2026-09-**07** UTC belong to Pacific
    2026-09-**06**, and that is where they must be stored.
    """
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07")
    assert _daily_completed(rec) == EXPECTED_0906
    assert rec["total_completed"] == 16  # the fifteen + the monthly Sauna's period judgement
    assert rec["attribution"] == "logs"
    assert rec["habits"]["Weigh In"] == Decimal("1")
    assert rec["habits"]["Walk Outdoor >2mi"] == Decimal("1")


def test_the_same_wire_stored_zero_completions_before_the_fix(monkeypatch):
    """Control: the journal-status path on the SAME payload is the live defect.

    This is what the pre-#3666 code did with exactly these bytes — 0 completed, 61
    resolved as failure — so the fixture is proven to contain the bug, not merely to be
    consistent with the fix.
    """
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07", with_logs=False)
    assert _daily_completed(rec) == set()  # zero daily completions on a fifteen-habit day
    assert rec["total_completed"] == 1  # the monthly Sauna alone

    assert rec["attribution"] == "journal_fallback"
    assert sum(1 for hs in rec["habit_statuses"].values() if hs["status"] == "failed") == 60


def test_the_completion_instant_stored_is_the_real_tap_not_the_ingest_time(monkeypatch):
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07")
    assert rec["habit_statuses"]["Weigh In"]["completed_at"] == "2026-09-07T02:11:22.363Z"


def test_a_backdated_monthly_habit_attributes_to_the_day_it_was_marked_for(monkeypatch):
    """Sauna: marked on Sep 6 FOR Sep 4. Habitify anchors it at 00:00 LOCAL of Sep 4
    (`2026-09-04T07:00:00.000Z` — exact PDT midnight, zero sub-second, against
    millisecond precision on a real tap). The log lands on 09-04 and nowhere else.

    Sauna is `periodicity: monthly`, so its journal STATUS reads `completed` on every
    date inside the month — which is exactly why the log, not the status, is the
    attribution key. The `completed_at` stamp is the day-level evidence.
    """
    on_04 = _run(monkeypatch, "2026-09-04", "2026-09-07")
    assert on_04["habit_statuses"]["Sauna"]["completed_at"] == "2026-09-04T07:00:00.000Z"
    for day in ("2026-09-05", "2026-09-06"):
        rec = _run(monkeypatch, day, "2026-09-07")
        assert "completed_at" not in rec["habit_statuses"]["Sauna"], f"Sauna's log leaked onto {day}"


def test_a_non_daily_habits_period_judgement_is_preserved(monkeypatch):
    """Scope line, stated so the next reader does not mistake it for an oversight.

    A weekly/monthly habit's journal `completed` is the VENDOR's period-level answer.
    #3666 replaces the per-DAY attribution key; it does not re-derive period goals, and
    turning "the month's sauna is done" into "failed on the other 30 days" would be a
    second, unrelated behaviour change. The day-level evidence is `completed_at`, which
    is present only on the day the log actually attributes to.
    """
    rec = _run(monkeypatch, "2026-09-05", "2026-09-07")
    assert rec["habit_statuses"]["Sauna"]["periodicity"] == "monthly"
    assert rec["habit_statuses"]["Sauna"]["status"] == "completed"
    assert "completed_at" not in rec["habit_statuses"]["Sauna"]


def test_a_backdated_daily_habit_attributes_to_the_day_it_was_marked_for(monkeypatch):
    """The cleaner assertion the monthly case cannot make (#3666's second comment).

    Same midnight-anchor shape, on a DAILY habit, where status — not just the stamp —
    has to move. Built from the real Sauna log's shape onto a real daily habit whose
    journal status for 09-04 is `failed`, so the log is the only thing that can flip it.
    """
    wire = _wire()
    cold_shower_id = next(e["id"] for e in wire["journal"] if e["name"] == "Cold Shower")
    wire["logs"]["Cold Shower"] = [
        {
            "id": "-P0tiGZecIgU8d0oUgM6",
            "value": 1,
            "created_date": "2026-09-04T07:00:00.000Z",  # 00:00:00 PDT on Sep 4 — the back-date anchor
            "unit_type": "rep",
            "habit_id": cold_shower_id,
        }
    ]
    on_04 = _run(monkeypatch, "2026-09-04", "2026-09-07", wire=wire)
    assert on_04["habit_statuses"]["Cold Shower"]["status"] == "completed"
    assert on_04["habit_statuses"]["Cold Shower"]["completed_at"] == "2026-09-04T07:00:00.000Z"
    on_05 = _run(monkeypatch, "2026-09-05", "2026-09-07", wire=wire)
    assert on_05["habit_statuses"]["Cold Shower"]["status"] == "failed"


def test_logs_on_pacific_day_is_the_one_attribution_helper():
    logs = [
        {"created_date": "2026-09-07T02:11:22.363Z"},  # 19:11 PT Sep 6
        {"created_date": "2026-09-07T07:00:00.000Z"},  # 00:00 PT Sep 7
        {"created_date": "2026-09-04T07:00:00.000Z"},  # 00:00 PT Sep 4
        {"created_date": ""},
        "not-a-dict",
    ]
    assert [x["created_date"] for x in logs_on_pacific_day(logs, "2026-09-06")] == ["2026-09-07T02:11:22.363Z"]
    assert [x["created_date"] for x in logs_on_pacific_day(logs, "2026-09-07")] == ["2026-09-07T07:00:00.000Z"]
    assert logs_on_pacific_day(None, "2026-09-06") == []


# ── 2. reference_date CARRIES NO INTENT AND MUST STAY UNREAD ─────────────────────────


def test_progress_reference_date_is_never_read(monkeypatch):
    """It merely echoes the `target_date` that was queried — the same monthly habit
    returns 09-04, 09-05, 09-06 and 09-07 for the four respective queries. Corrupting
    every one of them must not move a single stored value.
    """
    poisoned = _wire()
    for entry in poisoned["journal"]:
        (entry.get("progress") or {})["reference_date"] = "1999-12-31T00:00:00.000Z"
    clean = _run(monkeypatch, "2026-09-06", "2026-09-07")
    dirty = _run(monkeypatch, "2026-09-06", "2026-09-07", wire=poisoned)
    for rec in (clean, dirty):
        rec.pop("updated_at")
    assert clean == dirty


def test_the_source_does_not_mention_reference_date_outside_its_own_disclaimer():
    """A prose rule nobody enforces is how this field gets reached for again.

    AST rather than grep: the module docstring and the inline comments both NAME the
    field on purpose, and a text scan cannot tell a warning from a read.
    """
    src = open(os.path.join(ROOT, "lambdas", "ingestion", "habitify_lambda.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    reads = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Constant) and node.value == "reference_date")
        or (isinstance(node, ast.Attribute) and node.attr == "reference_date")
    ]
    assert reads == [], "reference_date is read by CODE — it echoes the query parameter and carries no intent (#3666)"


# ── 3. pending MUST SURVIVE THE WHOLE PACIFIC DAY ────────────────────────────────────


def test_pending_survives_a_pacific_day_that_is_still_open(monkeypatch):
    """19:00 PT on Sep 6 — two hours past the old UTC rollover, where every open habit
    used to be rewritten `failed`. It must read `pending`, and the day's completions must
    be in the SAME record rather than split onto tomorrow's.
    """
    rec = _run(monkeypatch, "2026-09-06", "2026-09-06")
    # 22 habits read `in_progress` in the wire capture; 15 of them are the evening ticks
    # the logs attribute to this day, leaving 7 genuinely open at 19:00 PT.
    assert rec["pending_count"] == 7
    assert rec["habit_statuses"]["Floss"]["status"] == "pending"
    assert _daily_completed(rec) == EXPECTED_0906
    # Not one `failed` was manufactured by the platform on a day that had not closed.
    assert rec["failed_platform_count"] == 0
    assert all(hs.get("miss_source") == "vendor" for hs in rec["habit_statuses"].values() if hs["status"] == "failed")


def test_pending_resolves_to_failed_once_the_pacific_day_has_closed(monkeypatch):
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07")
    assert rec["pending_count"] == 0
    assert rec["habit_statuses"]["Floss"]["status"] == "failed"
    # …and it says WHO decided that. This one is the platform's inference, not a report.
    assert rec["habit_statuses"]["Floss"]["miss_source"] == "platform"


def test_a_utc_today_would_still_red_this(monkeypatch):
    """The regression pin, stated in the frame the bug lived in.

    At 19:11 PT on Sep 6 the UTC date is already 2026-09-07, so the retired
    `date_str >= today_utc` test made `"2026-09-06" >= "2026-09-07"` FALSE and every
    open habit `failed`. With both sides in Pacific the comparison is
    `"2026-09-06" >= "2026-09-06"` — the day is open, as it in fact was.
    """
    rec = _run(monkeypatch, "2026-09-06", "2026-09-06")
    assert rec["habit_statuses"]["Floss"]["status"] == "pending"


def test_the_retired_utc_exemption_is_gone_from_the_source():
    """#2811's `utc-exempt` valve on this file argued the vendor's boundary is UTC (true)
    and never noticed the other side of the comparison was a Pacific `DATE#` key. The
    exemption is retired, not reworded — a marker left behind would re-licence the site.
    """
    src = open(os.path.join(ROOT, "lambdas", "ingestion", "habitify_lambda.py"), encoding="utf-8").read()
    assert "utc-exempt" not in src
    # AST, not grep: the retired line is QUOTED in a comment on purpose so the next reader
    # can see what was removed. What must be gone is the NAME being bound or read.
    tree = ast.parse(src)
    live = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "today_utc"]
    assert live == [], "today_utc is live again — both sides of the day comparison must be Pacific (#3666)"


# ── 3b. A REPORTED MISS AND AN ASSUMED ONE ARE DIFFERENT FACTS ───────────────────────


def test_a_vendor_miss_and_a_platform_assumption_stay_distinguishable(monkeypatch):
    """THE distinction the retired line destroyed.

    Habitify reports a MISS (`failed`) separately from an UNRESOLVED habit
    (`in_progress`). `"pending" if date_str >= today_utc else "failed"` made them
    byte-identical in the stored row from 17:00 PT onward. A mis-dated write can be
    re-derived from the vendor later; a destroyed distinction cannot be recovered from the
    record at all — and a reported lapse is the behavioural signal ADR-104 protects.

    Both statuses ride the SAME Pacific day here, which is the case the old code could
    not represent at all.
    """
    wire = _wire()
    for entry in wire["journal"]:
        if entry["name"] == "Collagen":
            entry["status"] = "failed"  # marked missed in the app
        if entry["name"] == "Floss":
            entry["status"] = "in_progress"  # never touched
    wire["logs"]["Collagen"] = []
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07", wire=wire)  # the day has CLOSED
    statuses = rec["habit_statuses"]
    assert statuses["Collagen"]["status"] == "failed"
    assert statuses["Collagen"]["miss_source"] == "vendor"
    assert statuses["Floss"]["status"] == "failed"
    assert statuses["Floss"]["miss_source"] == "platform"
    assert statuses["Collagen"] != statuses["Floss"]
    assert rec["failed_vendor_count"] and rec["failed_platform_count"]


def test_a_collapse_of_the_two_reds_this(monkeypatch):
    """The mutation. Strip `miss_source` — i.e. restore the pre-#3666 record shape — and
    the two rows become indistinguishable, which is precisely the loss."""
    wire = _wire()
    for entry in wire["journal"]:
        if entry["name"] == "Collagen":
            entry["status"] = "failed"
        if entry["name"] == "Floss":
            entry["status"] = "in_progress"
    wire["logs"]["Collagen"] = []
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07", wire=wire)
    # The pre-#3666 record shape: status + the numeric facets, with no provenance. (Group
    # is excluded because these two habits sit in different areas — that is registry
    # metadata, not a statement about the day, and it is not what the old code collapsed.)
    shape = ("status", "current_value", "target_value", "periodicity", "scheduled_today")
    collapsed = {n: {k: hs.get(k) for k in shape} for n, hs in rec["habit_statuses"].items()}
    assert collapsed["Collagen"] == collapsed["Floss"], "if this ever differs, the mutation has stopped testing the collapse"
    assert rec["habit_statuses"]["Collagen"] != rec["habit_statuses"]["Floss"]


def test_a_vendor_miss_is_never_rewritten_pending_on_an_open_day(monkeypatch):
    """`pending` is reserved for `in_progress`. Nothing else may be mapped onto it —
    including by the upgrade-only merge, whose open-day clamp must skip a reported miss."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    stored = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "pending", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "failed", "miss_source": "vendor", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Collagen"]["status"] == "failed"
    assert merged["habit_statuses"]["Collagen"]["miss_source"] == "vendor"


def test_a_platform_assumption_is_still_clamped_on_an_open_day(monkeypatch):
    """The other side of the same clamp — an inference may not finalise an open day."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    stored = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "pending", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "failed", "miss_source": "platform", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Collagen"]["status"] == "pending"


def test_a_later_completion_clears_the_miss_marker(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    stored = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "completed", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "failed", "miss_source": "platform", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Collagen"]["status"] == "completed"
    assert "miss_source" not in merged["habit_statuses"]["Collagen"]


# ── 4. RE-INGEST IS UPGRADE-ONLY ─────────────────────────────────────────────────────


def _stored(monkeypatch, date_str, today_pt, **kw):
    return copy.deepcopy(_run(monkeypatch, date_str, today_pt, **kw))


def test_a_later_run_may_not_downgrade_a_stored_completion(monkeypatch):
    """THE mutation. The Lambda re-writes each day 24x/day and every write is a full
    `put_item` REPLACE, so one degraded fetch could erase a real completion for good.
    """
    stored = _stored(monkeypatch, "2026-09-06", "2026-09-07")
    degraded = _run(monkeypatch, "2026-09-06", "2026-09-07", with_logs=False)  # logs GET failed
    assert degraded["habit_statuses"]["Weigh In"]["status"] == "failed"  # the loss, un-merged
    merged = upgrade_only_merge(stored, degraded)
    assert merged["habit_statuses"]["Weigh In"]["status"] == "completed"
    assert merged["habit_statuses"]["Weigh In"]["completed_at"] == "2026-09-07T02:11:22.363Z"
    assert _daily_completed(merged) == EXPECTED_0906
    assert merged["total_completed"] == 16  # the roll-ups were rebuilt, not left stale


def test_a_later_run_may_not_finalise_pending_while_the_pacific_day_is_open(monkeypatch):
    """A 17:05 PT run stores `pending`; nothing may turn that into `failed` before the
    day actually ends. Simulated by a later pass that resolves the day early.
    """
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    stored = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "pending", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "failed", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Breathwork"]["status"] == "pending"


def test_pending_may_resolve_to_failed_once_the_day_has_closed(monkeypatch):
    """The other half of the same rule: a closed day ending is not data loss."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    stored = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "pending", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "failed", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Breathwork"]["status"] == "failed"


def test_a_late_tick_is_never_lost_by_an_earlier_runs_write(monkeypatch):
    """The mirror hazard: the merge must not resurrect the EARLIER record over a real
    new completion. An upgrade is one-directional.
    """
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    stored = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "pending", "group": "Core"}}}
    later = {
        "date": "2026-09-06",
        "habit_statuses": {"Breathwork": {"status": "completed", "group": "Core", "completed_at": "2026-09-07T04:30:00.000Z"}},
    }
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Breathwork"]["status"] == "completed"
    assert merged["habit_statuses"]["Breathwork"]["completed_at"] == "2026-09-07T04:30:00.000Z"
    assert "upgrade_only_merges" not in merged  # nothing was restored — the later run won


def test_a_habit_that_vanishes_upstream_keeps_its_recorded_decision(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    stored = {"date": "2026-09-06", "habit_statuses": {"Retired Habit": {"status": "completed", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "failed", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Retired Habit"]["status"] == "completed"
    assert merged["total_completed"] == 1


def test_the_merge_carries_notes_and_mood_forward(monkeypatch):
    """Both fetches are non-fatal by contract, so an empty one means "not fetched",
    never "retracted"."""
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    stored = {
        "date": "2026-09-06",
        "mood": 4,
        "mood_label": "Good",
        "habit_statuses": {"Breathwork": {"status": "completed", "group": "Core", "notes": ["trigger: after coffee"]}},
    }
    later = {"date": "2026-09-06", "habit_statuses": {"Breathwork": {"status": "failed", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Breathwork"]["notes"] == ["trigger: after coffee"]
    assert merged["mood"] == 4


def test_the_merge_is_a_no_op_when_nothing_was_lost(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    stored = _stored(monkeypatch, "2026-09-06", "2026-09-07")
    fresh = _run(monkeypatch, "2026-09-06", "2026-09-07")
    merged = upgrade_only_merge(stored, fresh)
    assert "upgrade_only_merges" not in merged
    assert merged["total_completed"] == 16


def test_the_merge_is_wired_into_the_ingestion_config():
    """A guard nobody registered is a guard that never runs."""
    src = open(os.path.join(ROOT, "lambdas", "ingestion", "habitify_lambda.py"), encoding="utf-8").read()
    assert "carry_forward_fn=upgrade_only_merge" in src


# ── 5. THE GROUP REGISTRY IS DERIVED, NOT HAND-STATED ────────────────────────────────


def test_the_group_registry_comes_from_the_live_areas_response(monkeypatch):
    """The owner reorganised Habitify into Core / Optimize / Vice. None of those is in
    the hand-written P40_GROUPS list, so `by_group` was empty and `total_possible` was
    **0 on every stored day** — which pins `completion_pct` at 0 however well the
    completions are attributed, and makes `ai_context`'s habit block (gated on
    `total_possible > 0`) hand every narrative surface nothing at all.
    """
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07")
    assert set(rec["by_group"]) == {"Core", "Optimize", "Vice"}
    assert rec["total_possible"] == 61
    assert float(rec["completion_pct"]) > 0
    assert not set(rec["by_group"]) & set(habitify_lambda.P40_GROUPS)


def test_p40_groups_still_backs_an_empty_areas_response(monkeypatch):
    """Fail-soft, not fail-open: an unusable /areas payload falls back to the old list
    rather than silently classifying every habit as ungrouped."""
    wire = _wire()
    wire["area_map"] = {}
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07", wire=wire)
    assert rec["total_possible"] == 0  # every habit is "Other" — visible, not pretended


# ── 6. THE CRON HOLE OVER THE OWNER'S EVENING ────────────────────────────────────────


def test_habitify_is_scheduled_every_hour_including_the_pacific_evening():
    """`INGEST_HOURLY` skips UTC 6-11 as a "10pm-4am PT maintenance window". That window
    is 23:00-04:00 PT — exactly when the owner ticks evening pills and breathwork, so a
    23:30 PT tick sat unread until 05:05 PT. Habitify opts out of the window.
    """
    src = open(os.path.join(ROOT, "cdk", "stacks", "ingestion_stack.py"), encoding="utf-8").read()
    assert re.search(r'^HABITIFY_HOURLY = "\*"', src, re.M), "HABITIFY_HOURLY must cover all 24 hours"
    block = src[src.index('function_name="habitify-data-ingestion"') :][:900]
    assert "cron(5 {HABITIFY_HOURLY} * * ? *)" in block, "habitify must not be back on INGEST_HOURLY"
    ingest_hourly = re.search(r'^INGEST_HOURLY = "([\d,]+)"', src, re.M).group(1)
    assert not {"6", "7", "8", "9", "10", "11"} & set(ingest_hourly.split(",")), "INGEST_HOURLY grew the hole shut — retire HABITIFY_HOURLY"


def test_logs_window_spans_the_whole_ingest_lookback():
    start, end = logs_window("2026-09-06", 7)
    assert start.startswith("2026-08-28")  # 7 lookback + 2 pad
    assert end.startswith("2026-09-08")  # 2 pad forward, so a back-date is visible


def test_the_logs_fetch_is_memoised_across_the_dates_one_run_ingests(monkeypatch):
    """One GET per habit per INVOCATION, not per habit per date. The window is anchored
    on Pacific today rather than the target date precisely so the second date is free."""
    calls = []

    def fake_api_get(endpoint, api_key, params=None):
        calls.append(endpoint)
        if endpoint == "/areas":
            return [{"id": "A1", "name": "Core"}]
        if endpoint == "/journal":
            return [{"id": "H1", "name": "Breathwork", "is_archived": False, "status": "in_progress", "area": {"id": "A1"}}]
        if endpoint == "/moods":
            return []
        return []

    monkeypatch.setattr(habitify_lambda, "api_get", fake_api_get)
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-06")
    monkeypatch.setattr(habitify_lambda, "FETCH_NOTES", False)
    habitify_lambda.reset_logs_cache()
    habitify_lambda.fetch_day({"api_key": "k"}, "2026-09-06")
    habitify_lambda.fetch_day({"api_key": "k"}, "2026-09-05")
    assert calls.count("/logs/H1") == 1, calls
    habitify_lambda.reset_logs_cache()
    habitify_lambda.fetch_day({"api_key": "k"}, "2026-09-06")
    assert calls.count("/logs/H1") == 2, "a warm container must not serve a stale memo"


def test_a_failed_logs_fetch_degrades_that_habit_alone_and_says_so(monkeypatch):
    """Fail-soft, but never silently: the record itself records which channel decided it."""

    def fake_api_get(endpoint, api_key, params=None):
        if endpoint == "/areas":
            return [{"id": "A1", "name": "Core"}]
        if endpoint == "/journal":
            return [
                {"id": "H1", "name": "Breathwork", "is_archived": False, "status": "in_progress", "area": {"id": "A1"}},
                {"id": "H2", "name": "Stretch", "is_archived": False, "status": "in_progress", "area": {"id": "A1"}},
            ]
        if endpoint == "/moods":
            return []
        if endpoint == "/logs/H1":
            raise RuntimeError("429 from the vendor")
        return [{"id": "L1", "value": 1, "created_date": "2026-09-07T02:11:22.363Z", "unit_type": "rep", "habit_id": "H2"}]

    monkeypatch.setattr(habitify_lambda, "api_get", fake_api_get)
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    monkeypatch.setattr(habitify_lambda, "FETCH_NOTES", False)
    habitify_lambda.reset_logs_cache()
    raw = habitify_lambda.fetch_day({"api_key": "k"}, "2026-09-06")
    assert set(raw["logs"]) == {"Stretch"}
    rec = transform(raw, "2026-09-06")[0]
    assert rec["habit_statuses"]["Stretch"]["status"] == "completed"
    assert rec["habit_statuses"]["Breathwork"]["status"] == "failed"  # journal fallback
    assert rec["attribution"] == "mixed"


# ── 7. THE SUPPLEMENT BRIDGE — THE SECOND PARTITION THIS BUG ZEROED ──────────────────
#
# `USER#matthew#SOURCE#supplements` is not an external source. It is a bridge: the
# post-store hook reads THIS record's completions, name-matches SUPPLEMENT_MAP, and
# writes one dose row per completed habit. It writes on completions only — so a habitify
# day that reads 0 completed silently produces an EMPTY supplement day, and every
# consumer downstream of that partition inherits the zero without a single error.
#
# Other readers of `SOURCE#habitify` (enumerated so a second silent zero cannot hide
# behind the first): health/scoring_engine (habit_scores composite + tier0),
# health/habit_streaks, health/pillar_absence, compute/daily_metrics_compute (streaks),
# emails/daily_brief, emails/weekly_digest, emails/partner_email, emails/chronicle_data,
# emails/anomaly_detector, emails/freshness_checker (DAILY_SOURCES + total_completed),
# intelligence/ai_expert_analyzer, intelligence/intelligence_common, content/output_writers,
# content/html_builder, web/site_api_habits, web/site_api_nutrition, web/site_api_vitals_depth,
# web/site_api_status, mcp/tools_habits + mcp/helpers. All of them read `habits` /
# `habit_statuses` / `completion_pct` from the record this module writes, so all of them
# are fixed by fixing the record — none needs its own change, and none had a check that
# would have noticed. That is what the #3666 cross-source contract adds.


def test_the_supplement_bridge_recovers_the_day_it_was_silently_zeroing(monkeypatch):
    """2026-09-06: four supplements taken and ticked, zero written. This is the second
    corrupted partition, and it comes back purely from the attribution fix."""
    written = {}

    class _Table:
        def get_item(self, Key):  # noqa: N803
            return {}

        def put_item(self, Item):  # noqa: N803
            written.update(Item)

    monkeypatch.setattr(habitify_lambda, "_table", _Table())
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07")
    habitify_lambda.supplement_bridge([rec], "2026-09-06")
    assert {e["name"] for e in written["supplements"]} == {"Collagen", "Creatine", "Electrolytes", "L Glutamine"}
    assert written["sk"] == "DATE#2026-09-06"
    assert all(e["source"] == "habitify_bridge" for e in written["supplements"])


def test_the_supplement_bridge_wrote_nothing_before_the_fix(monkeypatch):
    """The control, on the same wire bytes: the journal-status path hands the bridge a
    day with no completions, and the bridge correctly writes nothing at all."""
    calls = []

    class _Table:
        def get_item(self, Key):  # noqa: N803
            return {}

        def put_item(self, Item):  # noqa: N803
            calls.append(Item)

    monkeypatch.setattr(habitify_lambda, "_table", _Table())
    rec = _run(monkeypatch, "2026-09-06", "2026-09-07", with_logs=False)
    habitify_lambda.supplement_bridge([rec], "2026-09-06")
    assert calls == []


def test_the_bridge_sees_the_merged_record_not_the_pre_merge_one(monkeypatch):
    """The framework appends the SAME object it passed to `_store_item` to `stored_items`,
    and hands that list to the post-store hook. So `upgrade_only_merge` must mutate in
    place and return that identical object — if it ever returned a copy, a restored
    completion would land in DynamoDB and still be invisible to the bridge.
    """
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    stored = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "completed", "group": "Core"}}}
    later = {"date": "2026-09-06", "habit_statuses": {"Collagen": {"status": "failed", "miss_source": "vendor", "group": "Core"}}}
    merged = upgrade_only_merge(stored, later)
    assert merged is later, "the merge must mutate the framework's own item object"
    assert merged["habits"]["Collagen"] == Decimal("1")
