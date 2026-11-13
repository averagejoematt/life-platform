"""#5861 L6 — THE NO-LIVE-CHANGE PROOF for the validation lane: while the exercise library is `proposed`, every drafted week
SERVES exactly what the base tree served (base: the integration branch at ea3906604, before any L6 commit).

Two halves:
  1. PINNED DIGESTS — `scripts/sample_weeks_5861.served_digest("proposed")`: per synthetic profile, sha256 of everything a
     drafted week serves (titles, every lift's sets, reps and Hevy note, the compiled Hevy body, the cardio block, the
     rationale, the minutes). The world is built from the #5075 pools (`prior="pools"`), so it does not move when the library
     or the catalog is regenerated. The pins were computed by running this same harness against a `git archive` export of
     ea3906604 and against this branch: identical. The selection's SHADOW record (`inputs_snapshot.selection_shadow`) is not
     served and is not pinned — L6's catalog entries and cue sheets change what the shadow ranks, by design.
  2. LIVE CODE NEVER RUNS IN SHADOW — L6's live-only entry points are replaced by functions that FAIL the test, and every
     profile's week drafts clean in proposed mode.

Must-fail controls (run on the lane, recorded on the PR): `live_session.drop_accessories` ignoring its live mark (the
shadow red-day rule changed) -> half 1 red for the red-readiness profiles and half 2 red; `live_session.for_live_draft`
skipping its mode check -> half 2 red.
"""

from __future__ import annotations

import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts"):
    sys.path.insert(0, str(_p))

import sample_weeks_5861 as sw  # noqa: E402

PINNED = {
    "a_large_deficit_experienced": "482036aa60a4ad1e",
    "b_shoulder_flag_low_recovery": "c44c886a72aa40c0",
    "c_equipment_limited": "482036aa60a4ad1e",
    "d_stalled_anchor_adherence_dip": "f9f775a9435653f1",
    "e_short_week": "8ae572edb08aac5c",
    "f_high_fatigue_poor_sleep": "696de7e8a021a19a",
}
"""Computed on the base tree (ea3906604) and on this branch — identical. (a) and (c) agree because today's path ignores the
equipment profile: the gap the live session fit closes."""


def test_the_proposed_drafts_serve_exactly_what_the_base_tree_served():
    assert sw.served_digest("proposed") == PINNED


def _poisoned():
    from training import live_session, selection_live

    def boom(name):
        def _f(*a, **k):
            pytest.fail(f"live-only {name} ran while the library is proposed")

        return _f

    targets = [
        (live_session, "fit_exposures"),
        (live_session, "_replacement"),
        (live_session, "_refit"),
        (live_session, "_unpair"),
        (selection_live, "build_policy"),
        (selection_live, "select_slot"),
    ]
    return [patch.object(mod, name, boom(f"{mod.__name__}.{name}")) for mod, name in targets]


def test_no_l6_live_only_code_runs_in_shadow():
    with ExitStack() as stack:
        for p in _poisoned():
            stack.enter_context(p)
        for name, prof in sw.load_profiles().items():
            world = sw.build_world(prof, "proposed", prior="pools")
            week = sw.generate_week(prof, "proposed", world)
            for s in week["sessions"]:
                assert s["live_fit"] is None and s["fatigue"] is None, name
                assert not any(
                    ln.startswith(("swapped (live)", "skipped (live)", "time (live)", "fatigue (live)")) for ln in s["rationale"]
                )
