"""#4632 — a habit is its vendor habit id; names are aliases; only an explicit correction un-ticks.

HELD on #4644 Q26/Q27 — built on the recommended answers:
  Q26: "same habit keeps its streak (id-keyed), applied to the history too"
  Q27: "b (explicit correction only)"

Box 1: the ingest stamps `aliases` (every other name the same vendor id carried on the prior
stored day) on each `habit_statuses` entry, and the tiered scoring lookup + the streaks resolve
a registry habit by id, then name, then alias — so a rename mid-history is ONE streak.

Box 3: a vendor-authored `failed`, decided on a successful logs read, withdraws a stored
`completed` only on an explicit `{"date_override": D, "correction": true}` run; a fetch failure
(journal fallback, a vanished habit) or a platform-inferred miss never does, flag or not.

Fixture = the wire: `tests/fixtures/habitify/habitify_2026-09-06_wire.json` (LIVE Habitify
journal + logs, captured read-only for #3666). The archived raw object
`raw/matthew/habitify/2026/10/2026-10-15.json` (registry `raw_layout`: date-tree) was read
read-only to confirm the same shape is still on the wire: `raw.journal[*].id` on all 61
entries, unique, and `logs[*][*].habit_id`. Only public supplement names are renamed here.

Run:  python3 -m pytest tests/test_habit_identity_4632.py -v
"""

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import habitify_lambda  # noqa: E402
import pytest  # noqa: E402
from habitify_lambda import (  # noqa: E402
    _bridge_entries,
    correction_dates_from_event,
    identity_from_record,
    reset_identity_cache,
    transform,
    upgrade_only_merge,
)
from health.habit_streaks import compute_habit_streaks  # noqa: E402
from health.scoring_engine import habitify_reading, score_habits_registry  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "habitify", "habitify_2026-09-06_wire.json")
DAY = "2026-09-06"
OLD, NEW = "Collagen", "Collagen Peptides"  # a public supplement habit (#4333)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # A fixed clock: the wire day is CLOSED (the day after), never "today" by the live clock.
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-09-07")
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", [])  # no registry aliases at all
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset())
    reset_identity_cache()
    yield
    reset_identity_cache()


def _wire():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def _raw(wire):
    return {"date": DAY, "area_map": wire["area_map"], "journal": wire["journal"], "moods": [], "logs": wire["logs"]}


def _renamed(wire, old=OLD, new=NEW):
    w = copy.deepcopy(wire)
    for e in w["journal"]:
        if e["name"] == old:
            e["name"] = new
    w["logs"][new] = w["logs"].pop(old)
    return w


def _entry(wire, name):
    return next(e for e in wire["journal"] if e["name"] == name)


def _stored_day():
    return transform(_raw(_wire()), DAY)[0]


# ── Box 1: identity by vendor id, names as aliases ───────────────────────────────────────


def test_the_ingest_derives_the_old_name_as_an_alias_from_id_continuity():
    before = _stored_day()
    assert before["habit_statuses"][OLD]["status"] == "completed"
    habit_id = before["habit_statuses"][OLD]["habit_id"]
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    assert OLD not in after["habit_statuses"]
    renamed = after["habit_statuses"][NEW]
    assert renamed["habit_id"] == habit_id
    assert renamed["aliases"] == [OLD]
    # A habit that was NOT renamed carries no aliases.
    assert "aliases" not in after["habit_statuses"]["Creatine"]


def test_the_alias_chain_carries_every_earlier_name_forward():
    first = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(first))
    second = transform(_raw(_renamed(_wire())), DAY)[0]
    reset_identity_cache(lambda _d: identity_from_record(second))
    third = transform(_raw(_renamed(_wire(), OLD, "Collagen (Marine)")), DAY)[0]
    assert third["habit_statuses"]["Collagen (Marine)"]["aliases"] == [OLD, NEW]


def test_a_rename_mid_history_is_one_streak():
    """Three days under the old name, two under the new one: ONE Tier-0 streak of five."""
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    rows = {"2026-09-10": after, "2026-09-09": after, "2026-09-08": before, "2026-09-07": before, "2026-09-06": before}
    profile = {"habit_registry": {OLD: {"status": "active", "tier": 0}}}
    out = compute_habit_streaks(profile, "2026-09-10", lambda _src, d: rows.get(d))
    assert out["tier0_streak"] == 5


def test_the_tiered_scoring_lookup_reads_the_renamed_habit_under_its_registry_key():
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire())), DAY)[0]
    profile = {"habit_registry": {OLD: {"status": "active", "tier": 0}}}
    score, details = score_habits_registry({"habitify": after, "date": "2026-09-10"}, profile)
    assert details["tier_status"][0] == {OLD: True}
    assert OLD not in details.get("unobserved", [])
    assert score == 100


def test_a_registry_habitify_id_keys_the_lookup_with_no_name_in_common():
    day = _stored_day()
    habit_id = day["habit_statuses"][OLD]["habit_id"]
    meta = {"status": "active", "tier": 0, "habitify_id": habit_id}
    assert habitify_reading(day["habits"], "A Name Habitify Never Used", meta, day["habit_statuses"]) == 1.0
    # Without the day's statuses it is the #4362 name lookup: unobserved, never a miss.
    assert habitify_reading(day["habits"], "A Name Habitify Never Used", meta) is None


def test_a_same_day_rename_by_id_is_one_row_and_keeps_the_stored_completion(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: DAY)  # the day is still open
    renamed_wire = _renamed(_wire())
    renamed_wire["logs"][NEW] = []  # this run cannot see the tick (no log attributed yet)
    fresh = transform(_raw(renamed_wire), DAY)[0]
    assert fresh["habit_statuses"][NEW]["status"] == "pending"
    merged = upgrade_only_merge(stored, fresh)
    statuses = merged["habit_statuses"]
    assert OLD not in statuses
    assert statuses[NEW]["status"] == "completed"
    assert statuses[NEW]["aliases"] == [OLD]
    assert len(statuses) == len(stored["habit_statuses"])
    assert merged["total_completed"] == stored["total_completed"]


def test_an_unreadable_prior_day_yields_no_aliases_never_a_lost_day():
    def _boom(_d):
        raise RuntimeError("throttled")

    reset_identity_cache(_boom)
    rec = transform(_raw(_renamed(_wire())), DAY)[0]
    assert NEW in rec["habit_statuses"] and "aliases" not in rec["habit_statuses"][NEW]


def test_the_ddb_reader_takes_the_nearest_earlier_day_that_has_statuses(monkeypatch):
    calls = []
    good = _stored_day()

    class _Table:
        def query(self, **kw):
            calls.append(kw)
            return {"Items": [{"sk": "DATE#2026-09-05", "absent": True}, good]}

    monkeypatch.setattr(habitify_lambda, "_table", _Table())
    ids = habitify_lambda._ddb_prior_identity(DAY)
    assert ids[good["habit_statuses"][OLD]["habit_id"]] == {OLD}
    assert calls[0]["ScanIndexForward"] is False


def test_the_bridge_resolves_a_renamed_supplement_through_its_alias():
    before = _stored_day()
    reset_identity_cache(lambda _d: identity_from_record(before))
    after = transform(_raw(_renamed(_wire(), OLD, "Marine Collagen")), DAY)[0]
    names = {e["name"] for e in _bridge_entries(after, [])}
    assert "Marine Collagen" in names


# ── Box 3: only an explicit correction lets the vendor's failed withdraw a completion ─────


def _unticked(wire, name=OLD, logs_fetched=True):
    """The vendor's view after the owner un-ticks `name`: no log, and the journal says failed."""
    w = copy.deepcopy(wire)
    _entry(w, name)["status"] = "failed"
    if logs_fetched:
        w["logs"][name] = []
    else:
        w["logs"].pop(name)  # the logs GET for this habit failed (journal fallback)
    return w


def test_without_a_correction_a_vendor_failed_never_downgrades_a_completion():
    stored = _stored_day()
    fresh = transform(_raw(_unticked(_wire())), DAY)[0]
    assert fresh["habit_statuses"][OLD]["status"] == "failed"
    assert fresh["habit_statuses"][OLD]["miss_source"] == "vendor"
    merged = upgrade_only_merge(stored, fresh)
    assert merged["habit_statuses"][OLD]["status"] == "completed"
    assert "corrections" not in merged


def test_an_explicit_correction_lets_the_vendors_failed_withdraw_a_completion(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", correction_dates_from_event({"date_override": DAY, "correction": True}))
    fresh = transform(_raw(_unticked(_wire())), DAY)[0]
    merged = upgrade_only_merge(stored, fresh)
    assert merged["habit_statuses"][OLD]["status"] == "failed"
    assert merged["habits"][OLD] == 0
    assert merged["total_completed"] == stored["total_completed"] - 1
    assert merged["corrections"] == [f"{OLD}:completed->failed"]
    # The supplements bridge follows the stored record: the un-ticked supplement is retracted.
    prior_bridge = _bridge_entries(stored, [])
    assert OLD in {e["name"] for e in prior_bridge}
    assert OLD not in {e["name"] for e in _bridge_entries(merged, prior_bridge)}


def test_a_fetch_failure_cannot_downgrade_a_completion_even_under_a_correction(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset({DAY}))
    # (a) the logs GET failed: the journal's failed is not per-day truth (#3666's UTC bucketing).
    fresh = transform(_raw(_unticked(_wire(), logs_fetched=False)), DAY)[0]
    assert fresh["habit_statuses"][OLD]["status_channel"] == "journal"
    assert upgrade_only_merge(stored, fresh)["habit_statuses"][OLD]["status"] == "completed"
    # (b) the habit vanished from the journal altogether.
    gone = copy.deepcopy(_wire())
    gone["journal"] = [e for e in gone["journal"] if e["name"] != OLD]
    gone["logs"].pop(OLD)
    assert upgrade_only_merge(stored, transform(_raw(gone), DAY)[0])["habit_statuses"][OLD]["status"] == "completed"
    # (c) nobody said failed: the platform resolved an in_progress habit at day close.
    platform = copy.deepcopy(_wire())
    platform["logs"][OLD] = []
    fresh_p = transform(_raw(platform), DAY)[0]
    assert fresh_p["habit_statuses"][OLD]["miss_source"] == "platform"
    assert upgrade_only_merge(stored, fresh_p)["habit_statuses"][OLD]["status"] == "completed"


def test_the_correction_trail_survives_a_later_ordinary_run(monkeypatch):
    stored = _stored_day()
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset({DAY}))
    corrected = upgrade_only_merge(stored, transform(_raw(_unticked(_wire())), DAY)[0])
    monkeypatch.setattr(habitify_lambda, "_CORRECTION_DATES", frozenset())
    later = upgrade_only_merge(corrected, transform(_raw(_unticked(_wire())), DAY)[0])
    assert later["habit_statuses"][OLD]["status"] == "failed"
    assert later["corrections"] == [f"{OLD}:completed->failed"]


def test_a_correction_needs_an_explicit_date_and_an_explicit_flag():
    assert correction_dates_from_event({"date_override": DAY, "correction": True}) == frozenset({DAY})
    assert correction_dates_from_event({"date_override": DAY}) == frozenset()
    assert correction_dates_from_event({"date_override": DAY, "correction": "yes"}) == frozenset()
    assert correction_dates_from_event({"date_override": "today", "correction": True}) == frozenset()
    assert correction_dates_from_event({"correction": True}) == frozenset()


def test_the_handler_arms_the_correction_for_that_invocation_only(monkeypatch):
    seen = []
    monkeypatch.setattr(habitify_lambda, "run_ingestion", lambda *a, **k: seen.append(habitify_lambda._CORRECTION_DATES) or {})
    habitify_lambda.lambda_handler({"date_override": DAY, "correction": True}, None)
    habitify_lambda.lambda_handler({}, None)
    assert seen == [frozenset({DAY}), frozenset()]
