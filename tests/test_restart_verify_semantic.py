"""tests/test_restart_verify_semantic.py — the #1093 semantic pre-start verify.

Pure-assertion units over fixture payloads (no AWS, no network): the pre_start
contract on snapshot/journey, the zeroed character, the empty-findings
discoveries state, the null-or-current-cycle dispute, the prologue-only journal
manifest, and the ingestion-poisoning detector (the whoop DATE#2026-07-08
re-stamp class). Dates are PINNED — never wall-clock (the golden-tests lesson).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENESIS = "2026-07-12"  # pinned cycle-5 genesis


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sem = _load("restart_verify_semantic")


# ── 1. snapshot / journey pre_start contract ──────────────────────────────────


def test_snapshot_pre_start_flag_passes():
    assert sem.check_snapshot_pre_start({"pre_start": True, "journey": None}) == []


def test_snapshot_day_one_passes_without_flag():
    payload = {"pre_start": False, "journey": {"journey": {"day_n": 1}}}
    assert sem.check_snapshot_pre_start(payload) == []


def test_snapshot_mid_experiment_fails():
    payload = {"pre_start": False, "journey": {"journey": {"day_n": 30}}}
    problems = sem.check_snapshot_pre_start(payload)
    assert len(problems) == 1 and "day_n is 30" in problems[0]


def test_snapshot_missing_everything_fails():
    assert sem.check_snapshot_pre_start({}) != []


def test_journey_pre_start_flag_passes():
    assert sem.check_journey_pre_start({"journey": {"pre_start": True, "day_n": 0}}) == []


def test_journey_stale_day_counter_fails():
    problems = sem.check_journey_pre_start({"journey": {"pre_start": False, "day_n": 12}})
    assert problems and "/api/journey" in problems[0]


# ── 2. zeroed character ────────────────────────────────────────────────────────


def test_character_zeroed_passes():
    payload = {"character": {"level": 1, "xp_total": 0, "pre_experiment": True}}
    assert sem.check_character_zeroed(payload) == []


def test_character_leveled_sheet_fails_both_fields():
    problems = sem.check_character_zeroed({"character": {"level": 21, "xp_total": 48210}})
    assert len(problems) == 2
    assert any("level is 21" in p for p in problems)
    assert any("xp_total is 48210" in p for p in problems)


def test_character_missing_payload_fails():
    assert sem.check_character_zeroed({}) != []


# ── 3. discoveries: no current-cycle findings ─────────────────────────────────


def test_discoveries_carried_protocols_only_passes():
    payload = {
        "active_hypotheses": [{"name": "Tongkat Ali", "carried_over": True, "protocol_kind": "ongoing_protocol"}],
        "inner_life": [],
        "ai_findings": [],
    }
    assert sem.check_discoveries_clean(payload) == []


def test_discoveries_inner_life_leak_fails():
    payload = {"inner_life": [{"title": "Journal Breakthrough — sleep"}], "ai_findings": []}
    problems = sem.check_discoveries_clean(payload)
    assert len(problems) == 1 and "inner_life" in problems[0]


def test_discoveries_ai_findings_leak_fails():
    problems = sem.check_discoveries_clean({"inner_life": [], "ai_findings": [{"pair": "hrv~sleep"}]})
    assert len(problems) == 1 and "ai_findings" in problems[0]


# ── 4. coach_team dispute null-or-current-cycle ───────────────────────────────


def test_dispute_null_passes():
    assert sem.check_dispute_current({"dispute": None}, GENESIS) == []


def test_dispute_current_cycle_passes():
    payload = {"dispute": {"topic": "ramp speed", "created_at": "2026-07-13T10:00:00+00:00"}}
    assert sem.check_dispute_current(payload, GENESIS) == []


def test_dispute_wiped_cycle_fails():
    payload = {"dispute": {"topic": "deficit size", "created_at": "2026-07-01T10:00:00+00:00"}}
    problems = sem.check_dispute_current(payload, GENESIS)
    assert problems and "pre-genesis" in problems[0]


def test_dispute_missing_created_at_fails():
    # No provenance = cannot prove current-cycle → honest fail, not a pass.
    assert sem.check_dispute_current({"dispute": {"topic": "?"}}, GENESIS) != []


# ── 5. journal posts: prologue-only, backed by live chronicle records ─────────

_LIVE_CHRONICLE = [
    {"sk": "DATE#2026-07-06", "date": "2026-07-06", "title": "Before the Numbers", "phase": "experiment"},
    {"sk": "DATE#2026-07-11", "date": "2026-07-11", "title": "The Plan, On the Record", "phase": "experiment"},
    # A wiped (tombstoned) cycle-4 installment — must NOT count as live.
    {"sk": "DATE#2026-06-24", "date": "2026-06-24", "title": "Week 2 — Holding the Line", "phase": "pilot", "tombstone": True},
]


def test_posts_curated_prologues_pass():
    posts = {
        "posts": [
            {"date": "2026-07-11", "title": "The Plan, On the Record"},
            {"date": "2026-07-06", "title": "Before the Numbers"},
        ]
    }
    assert sem.check_journal_posts(posts, _LIVE_CHRONICLE, GENESIS) == []


def test_posts_wiped_installment_leak_fails():
    posts = {"posts": [{"date": "2026-06-24", "title": "Week 2 — Holding the Line"}]}
    problems = sem.check_journal_posts(posts, _LIVE_CHRONICLE, GENESIS)
    assert len(problems) == 1 and "wiped-cycle leak" in problems[0]


def test_posts_post_genesis_entry_fails_pre_start():
    posts = {"posts": [{"date": "2026-07-15", "title": "Week 1 — Underway"}]}
    problems = sem.check_journal_posts(posts, _LIVE_CHRONICLE, GENESIS)
    assert len(problems) == 1 and "not pre-genesis" in problems[0]


def test_posts_unbacked_title_fails():
    posts = {"posts": [{"date": "2026-07-06", "title": "A Title Nobody Wrote"}]}
    assert sem.check_journal_posts(posts, _LIVE_CHRONICLE, GENESIS) != []


def test_live_chronicle_keys_excludes_tombstoned_and_pilot():
    keys = sem.live_chronicle_keys(_LIVE_CHRONICLE)
    assert ("2026-07-06", "Before the Numbers") in keys
    assert all(date != "2026-06-24" for date, _ in keys)


# ── 6. the ingestion-poisoning detector ───────────────────────────────────────


def test_find_poisoned_flags_the_whoop_restamp_class():
    # The motivating instance: whoop DATE#2026-07-08 re-stamped phase=experiment
    # by a warm ingestion lambda holding stale constants.
    rows = [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-07-08", "phase": "experiment"}]
    violations = sem.find_poisoned(rows, GENESIS)
    assert len(violations) == 1 and "DATE#2026-07-08" in violations[0]


def test_find_poisoned_ignores_pilot_and_genesis_day_rows():
    rows = [
        {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-07-08", "phase": "pilot"},
        {"pk": "USER#matthew#SOURCE#whoop", "sk": f"DATE#{GENESIS}", "phase": "experiment"},
        {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-07-20", "phase": "experiment"},
    ]
    assert sem.find_poisoned(rows, GENESIS) == []
