"""
tests/test_routine_title_counters.py — Hevy title counters (2026-06-16 work order).

Pure-logic coverage of the N/Y counters (no AWS): type is resolved from PERFORMED
workouts (never by parsing titles), N counts performed-of-type since the phase
start, Y counts distinct performed since the reset epoch. Skipped/planned
sessions never inflate either; cross-source duplicates dedupe by workout_uid.

Also a contract test on the rendered wire-body title shape.

Run:  python3 -m pytest tests/test_routine_title_counters.py -v
"""

import os
import re
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import routine_title as rt  # noqa: E402

# ── resolve_archetype ────────────────────────────────────────────────────────

# Routine index as it actually looks post-reset: a push pushed 2026-06-15
# (target_date), plus a FUTURE-dated push planned for 2026-06-30 (must not leak).
INDEX = [
    {"archetype": "push", "target_date": "2026-06-15", "variant": "ideal"},
    {"archetype": "pull", "target_date": "2026-06-17", "variant": "ideal"},
    {"archetype": "push", "target_date": "2026-06-30", "variant": "ideal"},
]


def test_resolve_uses_stored_sticker_first():
    w = {"date": "2026-06-16", "archetype": "legs"}
    assert rt.resolve_archetype(w, INDEX) == "legs"


def test_resolve_falls_back_to_nearest_preceding_routine():
    # Performed 2026-06-16 → nearest routine with target_date <= date is the
    # 2026-06-15 push (NOT the future 2026-06-30 push).
    assert rt.resolve_archetype({"date": "2026-06-16"}, INDEX) == "push"


def test_resolve_picks_latest_not_first():
    # Performed 2026-06-18 → latest target_date <= date is the 2026-06-17 pull.
    assert rt.resolve_archetype({"date": "2026-06-18"}, INDEX) == "pull"


def test_resolve_none_when_no_preceding_routine():
    assert rt.resolve_archetype({"date": "2026-06-01"}, INDEX) is None


# Exact link: a performed workout carries the Hevy routine_id it came from.
INDEX_LINKED = [
    {"archetype": "push", "target_date": "2026-06-15", "variant": "ideal", "hevy_routine_id": "hr-push-1"},
    {"archetype": "legs", "target_date": "2026-06-16", "variant": "ideal", "hevy_routine_id": "hr-legs-1"},
]


def test_resolve_exact_hevy_routine_link_beats_date():
    # Performed 2026-06-17, but it was done from the LEGS routine (hr-legs-1).
    # Nearest-date would also pick legs here, so use a case where they'd differ:
    w = {"date": "2026-06-20", "hevy_routine_id": "hr-push-1"}
    # Nearest-date (2026-06-20) → legs (2026-06-16 is latest <= date). Exact link → push.
    assert rt.resolve_archetype(w, INDEX_LINKED) == "push"


def test_resolve_falls_back_to_date_when_link_unknown():
    # hevy_routine_id not in the index (e.g. ad-hoc/legacy) → nearest-date.
    w = {"date": "2026-06-20", "hevy_routine_id": "hr-unknown"}
    assert rt.resolve_archetype(w, INDEX_LINKED) == "legs"


def test_resolve_no_hevy_id_uses_date():
    assert rt.resolve_archetype({"date": "2026-06-20"}, INDEX_LINKED) == "legs"


# ── count_performed_of_type (N) ──────────────────────────────────────────────


def test_seed_next_push_counts_two():
    # The hand-named June-16 push is the only performed workout. The NEXT push's
    # N = performed pushes (1) + 1 = 2  →  the work order's "Push - 2 - 2".
    performed = [{"date": "2026-06-16", "workout_uid": "hevy:ca3e7725"}]
    n = rt.count_performed_of_type("push", performed, INDEX) + 1
    assert n == 2


def test_seed_next_pull_counts_one():
    # No pull performed yet → next pull N = 0 + 1 = 1  →  "Pull - 1 - 2".
    performed = [{"date": "2026-06-16", "workout_uid": "hevy:ca3e7725"}]
    n = rt.count_performed_of_type("pull", performed, INDEX) + 1
    assert n == 1


def test_planned_but_skipped_does_not_inflate_n():
    # The future 2026-06-30 push in INDEX is PLANNED, not performed — it must
    # never bump N. With zero performed pushes, next push is still N=1.
    assert rt.count_performed_of_type("push", [], INDEX) == 0


def test_cross_source_duplicate_counts_once_in_n():
    # Same session via Hevy + MacroFactor (same workout_uid) → counted once.
    performed = [
        {"date": "2026-06-16", "workout_uid": "hevy:x"},
        {"date": "2026-06-16", "workout_uid": "hevy:x"},
    ]
    assert rt.count_performed_of_type("push", performed, INDEX) == 1


# ── count_distinct_performed (Y) ─────────────────────────────────────────────


def test_y_counts_distinct_then_plus_one():
    performed = [
        {"date": "2026-06-16", "workout_uid": "hevy:a"},
        {"date": "2026-06-17", "workout_uid": "hevy:b"},
        {"date": "2026-06-17", "workout_uid": "hevy:b"},  # dup
    ]
    assert rt.count_distinct_performed(performed) + 1 == 3


def test_y_skipped_session_not_counted():
    # Y is performed-only; an empty performed list → next workout is Y=1.
    assert rt.count_distinct_performed([]) + 1 == 1


# ── format_title contract ────────────────────────────────────────────────────


def _ir(archetype, variant="ideal"):
    return types.SimpleNamespace(archetype=archetype, variant=variant, title="")


def test_title_contract_shape():
    ctx = {"phase": "Foundation", "type_count_in_phase": 2, "all_time_count": 2}
    title = rt.format_title(_ir("push"), ctx)
    assert title == "Foundation - Push - 2 - 2"
    assert re.match(r"^[A-Za-z]+ - [A-Za-z/]+ - \d+ - \d+$", title)


def test_title_contract_for_pull_legs():
    for arch, label in (("pull", "Pull"), ("legs", "Legs")):
        ctx = {"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 2}
        title = rt.format_title(_ir(arch), ctx)
        assert re.match(r"^[A-Za-z]+ - [A-Za-z/]+ - \d+ - \d+$", title), title


def test_re_entry_is_kind_no_counters():
    ctx = {"phase": "Foundation", "type_count_in_phase": 9, "all_time_count": 9}
    title = rt.format_title(_ir("push", variant="re_entry"), ctx)
    assert "Welcome back" in title
    assert "9" not in title  # never surface a "you missed N" count
