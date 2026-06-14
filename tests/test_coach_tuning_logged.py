"""tests/test_coach_tuning_logged.py — CC-03 coach-tuning change discipline.

Two jobs:

1. Validate config/coaches/tuning_log.json structurally (always runs).
2. Enforce the change-discipline: any diff to a coach's voice block
   (structural_voice_rules / few_shot_examples / decision_style /
   anti_pattern_detection / display_name / domain) must be accompanied by a new
   tuning_log entry whose date >= the current tip. Runs against origin/main;
   skips gracefully when origin/main isn't available (offline dev).

The detector logic is also unit-tested against fixtures so the gate is proven
deterministically, independent of git state.
"""

import datetime as dt
import json
import os
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_REL = "config/coaches/tuning_log.json"
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import persona_registry  # noqa: E402

VOICE_KEYS = {
    "structural_voice_rules",
    "few_shot_examples",
    "decision_style",
    "anti_pattern_detection",
    "display_name",
    "domain",
}
VALID_CHANGE_TYPES = {"prompt", "voice", "persona", "few_shot", "model"}


# ── detector logic (pure, unit-tested) ───────────────────────────────────────


def _voice_blocks_changed(old, new):
    """True if any voice-relevant key differs between two coach-config dicts."""
    return any(old.get(k) != new.get(k) for k in VOICE_KEYS)


def _entry_key(e):
    return (e.get("date"), e.get("coach"), e.get("summary"))


def _new_entries(old_entries, new_entries):
    old_keys = {_entry_key(e) for e in old_entries}
    return [e for e in new_entries if _entry_key(e) not in old_keys]


def _max_date(entries):
    dates = [e["date"] for e in entries if e.get("date")]
    return max(dates) if dates else None


# ── git helpers ──────────────────────────────────────────────────────────────


def _git(*args):
    try:
        out = subprocess.run(
            ["git", "-C", _REPO, *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def _base_ref():
    return "origin/main" if _git("rev-parse", "--verify", "origin/main") is not None else None


def _show_json(ref, rel_path):
    raw = _git("show", f"{ref}:{rel_path}")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── structural validation (always) ───────────────────────────────────────────


def _load_log():
    with open(os.path.join(_REPO, _LOG_REL), encoding="utf-8") as fh:
        return json.load(fh)


def test_tuning_log_is_shaped():
    log = _load_log()
    assert isinstance(log.get("entries"), list) and log["entries"]


def test_every_entry_is_valid():
    valid_coaches = set(persona_registry.OPERATIONAL_COACH_IDS) | {"all"}
    for e in _load_log()["entries"]:
        assert e.get("coach") in valid_coaches, f"unknown coach {e.get('coach')!r}"
        assert e.get("change_type") in VALID_CHANGE_TYPES, f"bad change_type {e.get('change_type')!r}"
        assert e.get("summary"), "entry missing summary"
        assert e.get("rationale"), "entry missing rationale"
        # date parses as ISO YYYY-MM-DD
        dt.date.fromisoformat(e["date"])
        assert "observed_effect" in e, "entry missing observed_effect (use null if unknown)"


def test_entries_are_date_ordered():
    dates = [e["date"] for e in _load_log()["entries"]]
    assert dates == sorted(dates), "entries must be append-only / ascending by date"


# ── detector unit tests (deterministic, no git) ──────────────────────────────


def test_detector_flags_voice_change():
    old = {"display_name": "Dr. X", "structural_voice_rules": ["a"], "domain": "d"}
    assert _voice_blocks_changed(old, {**old, "structural_voice_rules": ["a", "b"]}) is True
    assert _voice_blocks_changed(old, {**old, "few_shot_examples": ["new"]}) is True


def test_detector_ignores_non_voice_change():
    old = {"display_name": "Dr. X", "structural_voice_rules": ["a"], "coach_id": "x_coach"}
    assert _voice_blocks_changed(old, {**old, "coach_id": "x_coach", "unrelated": 1}) is False


def test_new_entries_and_tip_logic():
    old = [{"date": "2026-01-01", "coach": "all", "summary": "a"}]
    new = old + [{"date": "2026-02-01", "coach": "all", "summary": "b"}]
    added = _new_entries(old, new)
    assert len(added) == 1 and added[0]["summary"] == "b"
    assert _max_date(added) >= _max_date(old)
    assert _new_entries(old, old) == []


def test_gate_fails_steady_state_when_voice_changed_but_log_untouched():
    """The load-bearing path: once tuning_log.json is on main, a voice edit with
    no NEW entry yields added==[] -> the gate's `assert added` fires. (The git
    integration test below can't show this on the introductory PR, because the
    whole backfilled log reads as 'new' relative to origin/main.)"""
    log_on_main = _load_log()["entries"]  # stands in for the base version
    log_in_pr = list(log_on_main)  # a voice edit shipped without appending
    assert _new_entries(log_on_main, log_in_pr) == []  # => gate fails, as intended


# ── the change-discipline gate (vs origin/main; skips offline) ────────────────


def test_voice_diffs_require_a_tuning_log_entry():
    base = _base_ref()
    if base is None:
        pytest.skip("origin/main not available — discipline gate runs in CI")

    changed = _git("diff", "--name-only", base, "--", "config/coaches/") or ""
    coach_files = [
        ln.strip() for ln in changed.splitlines() if ln.strip().endswith("_coach.json")  # excludes tuning_log.json + influence_graph.json
    ]

    voice_changed = []
    for rel in coach_files:
        old = _show_json(base, rel)
        path = os.path.join(_REPO, rel)
        if old is None or not os.path.isfile(path):
            continue  # newly added or deleted coach file — not a voice *edit*
        with open(path, encoding="utf-8") as fh:
            new = json.load(fh)
        if _voice_blocks_changed(old, new):
            voice_changed.append(rel)

    if not voice_changed:
        return  # nothing to enforce

    old_log = _show_json(base, _LOG_REL) or {"entries": []}
    new_log = _load_log()
    added = _new_entries(old_log["entries"], new_log["entries"])
    assert added, (
        f"Voice block(s) changed without a tuning_log entry: {voice_changed}. " f"Append an entry to {_LOG_REL} (CC-03 change discipline)."
    )
    if _max_date(old_log["entries"]):
        assert _max_date(added) >= _max_date(old_log["entries"]), "new tuning_log entry predates the current tip"
