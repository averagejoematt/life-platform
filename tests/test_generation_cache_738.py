"""
#738 / ADR-126 — hash-and-reuse for coach generation briefs.

Pins the two contracts that matter:
  1. STABILITY: identical semantic inputs fingerprint identically even when pure
     bookkeeping (timestamps, `_`-prefixed keys) differs run-to-run — so reuse can
     actually trigger on a quiet day.
  2. THE HONESTY INVARIANT: any semantic change — a vitals number, a stance edit,
     even a staleness day-count ticking up — changes the fingerprint, so reuse can
     never serve stale-but-claiming-fresh output.

Plus the fail-soft DDB helpers (a broken table degrades to "regenerate", never raises).
"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import generation_cache as gc  # noqa: E402


# ── fingerprint stability ─────────────────────────────────────────────────────


def test_dict_key_order_does_not_change_fingerprint():
    a = {"recovery": 62, "hrv": 48, "weight": 214.2}
    b = {"weight": 214.2, "hrv": 48, "recovery": 62}
    assert gc.brief_fingerprint(a) == gc.brief_fingerprint(b)


def test_bookkeeping_keys_are_ignored():
    """Two briefs identical in substance but stamped at different times/runs must
    fingerprint the same — otherwise reuse never triggers."""
    monday = {"stance": "focus on sleep", "gap_days": 0, "_generated_at": "2026-07-06", "as_of": "2026-07-06T04:00:00"}
    tuesday = {"stance": "focus on sleep", "gap_days": 0, "_generated_at": "2026-07-07", "as_of": "2026-07-07T04:00:00"}
    assert gc.brief_fingerprint(monday) == gc.brief_fingerprint(tuesday)


def test_underscore_and_volatile_stripped_at_any_depth():
    nested = {"outer": {"real": 1, "_fallback": True, "created_at": "x", "inner": {"v": 2, "run_id": "abc"}}}
    clean = {"outer": {"real": 1, "inner": {"v": 2}}}
    assert gc.brief_fingerprint(nested) == gc.brief_fingerprint(clean)


def test_decimal_and_native_number_fingerprint_equal():
    """DDB reads come back as Decimal; the same value from a fresh compute is a
    float/int. They must not spuriously bust the cache."""
    assert gc.brief_fingerprint({"weight": Decimal("214.2")}) == gc.brief_fingerprint({"weight": 214.2})


# ── the honesty invariant: semantic change MUST bust the fingerprint ───────────


def test_changed_number_busts_fingerprint():
    assert gc.brief_fingerprint({"recovery": 62}) != gc.brief_fingerprint({"recovery": 63})


def test_staleness_day_count_ticking_busts_fingerprint():
    """The explicit honesty guard from the issue: a staleness counter advancing is
    a real change and must force a fresh generation."""
    day3 = {"engagement_signal": {"gap_days": 3, "last_food_log_date": "2026-07-03"}}
    day4 = {"engagement_signal": {"gap_days": 4, "last_food_log_date": "2026-07-03"}}
    assert gc.brief_fingerprint(day3) != gc.brief_fingerprint(day4)


def test_stance_edit_busts_fingerprint():
    a = gc.brief_fingerprint({"current_stance": "watching HRV recover"})
    b = gc.brief_fingerprint({"current_stance": "shifting focus to protein"})
    assert a != b


def test_new_list_item_busts_fingerprint():
    assert gc.brief_fingerprint({"open_threads": ["sleep"]}) != gc.brief_fingerprint({"open_threads": ["sleep", "protein"]})


def test_all_parts_participate_in_the_hash():
    """system_prompt + user_message are hashed together; a change in EITHER busts it."""
    base = gc.brief_fingerprint("SYS voice rules", "USER brief A")
    assert base != gc.brief_fingerprint("SYS voice rules CHANGED", "USER brief A")
    assert base != gc.brief_fingerprint("SYS voice rules", "USER brief B")


# ── DDB helpers (fake table) ──────────────────────────────────────────────────


class _FakeTable:
    def __init__(self):
        self.store = {}
        self.updates = []

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = Item

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        self.updates.append((Key, ExpressionAttributeValues))


class _BrokenTable:
    def get_item(self, **_):
        raise RuntimeError("ddb down")

    def put_item(self, **_):
        raise RuntimeError("ddb down")

    def update_item(self, **_):
        raise RuntimeError("ddb down")


def test_store_then_reuse_on_matching_hash():
    t = _FakeTable()
    fp = gc.brief_fingerprint({"recovery": 62})
    assert gc.store_entry(t, "sleep_coach", "daily_brief_sleep", fp, "You slept well.", "2026-07-06")
    out, since = gc.check_reuse(t, "sleep_coach", "daily_brief_sleep", fp)
    assert out == "You slept well."
    assert since == "2026-07-06"


def test_no_reuse_on_hash_mismatch():
    t = _FakeTable()
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "hash_old", "old text", "2026-07-06")
    out, since = gc.check_reuse(t, "sleep_coach", "daily_brief_sleep", "hash_new")
    assert out is None and since is None


def test_no_reuse_when_absent():
    t = _FakeTable()
    out, since = gc.check_reuse(t, "nobody", "daily_brief_sleep", "anyhash")
    assert out is None and since is None


def test_record_reuse_bumps_bookkeeping():
    t = _FakeTable()
    gc.record_reuse(t, "sleep_coach", "daily_brief_sleep", "2026-07-07")
    assert len(t.updates) == 1
    key, vals = t.updates[0]
    assert key["sk"] == gc.cache_sk("sleep_coach", "daily_brief_sleep")
    assert vals[":d"] == "2026-07-07" and vals[":one"] == 1


def test_helpers_are_fail_soft():
    bt = _BrokenTable()
    assert gc.check_reuse(bt, "c", "o", "h") == (None, None)
    assert gc.store_entry(bt, "c", "o", "h", "txt", "2026-07-06") is False
    gc.record_reuse(bt, "c", "o", "2026-07-06")  # must not raise


def test_store_shape_resets_unchanged_clock():
    t = _FakeTable()
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-07-06")
    item = t.store[(gc.CACHE_PK, gc.cache_sk("sleep_coach", "daily_brief_sleep"))]
    assert item["first_generated"] == "2026-07-06"
    assert item["reuse_count"] == 0
    assert item["brief_hash"] == "fp"
