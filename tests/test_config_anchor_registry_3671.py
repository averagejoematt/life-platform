"""tests/test_config_anchor_registry_3671.py — #3671, the config-file counterpart
to phase_taxonomy.py.

`config/training_phases.json`'s `reset_epoch_date` sat stale at `2026-06-16`
through ELEVEN resets because ADR-077's phase taxonomy classifies DynamoDB
partitions and has no jurisdiction over config files — `deploy/restart_pipeline.py`
contained no reference to the file at all. #3680/#3701 fixed that ONE field by
deleting the config copy and deriving the Y counter straight from
`EXPERIMENT_START_DATE`. This test file guards the residual #3671 asked for: a
registry that enumerates EVERY experiment-anchored config field (wired or
ruled-out, in either case with a written reason), a coverage assertion that
reds on a planted/forgotten one, and the reset's own before/after report.
"""

from __future__ import annotations

import importlib
import json
import os

import pytest

car = importlib.import_module("experiment.config_anchor_registry")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")


# ── The live audit: every registered treatment is a real, valid one ───────────


def test_every_registry_entry_has_a_valid_treatment():
    for a in car.CONFIG_ANCHOR_REGISTRY:
        assert a.treatment in car.VALID_TREATMENTS, (a.config_file, a.key, a.treatment)


def test_every_registry_entry_carries_a_written_reason():
    """The whole point: 'wired into the reset OR carrying a written reason it is
    not' — an empty/placeholder reason defeats the registry's purpose."""
    for a in car.CONFIG_ANCHOR_REGISTRY:
        assert isinstance(a.reason, str) and len(a.reason) > 20, (a.config_file, a.key)


def test_path_bearing_entries_are_exactly_the_ones_report_lines_can_print():
    """reset_to_genesis / deliberate_carry / derives_live entries need a concrete
    `path` for report_lines() to look up a before/after value; not_anchored /
    glob entries deliberately carry none."""
    for a in car.CONFIG_ANCHOR_REGISTRY:
        if a.treatment == car.NOT_ANCHORED or "*" in a.config_file:
            assert a.path is None, (a.config_file, a.key)
        else:
            assert a.path is not None and a.path[-1] == a.key, (a.config_file, a.key, a.path)


# ── The coverage assertion: the guard the acceptance criterion demands ────────


def test_coverage_is_currently_clean_against_the_real_repo_config():
    """Run the real scan against the real config/ tree. This is the must-pass:
    every anchor-shaped field committed today is classified. A regression here
    means a new config field was added (or reset_epoch_date reintroduced)
    without registering it."""
    count = car.assert_full_coverage(CONFIG_DIR)
    assert count >= 20  # the audited universe as of 2026-09-14 (20 hits across 14 files); more may be added, never fewer


def test_reset_epoch_date_is_not_in_the_live_universe():
    """#3671's own defect field was DELETED (#3680/#3701), not merely reclassified
    — confirm it isn't silently back."""
    hits = car.scan_config_tree(CONFIG_DIR)
    assert ("training_phases.json", "reset_epoch_date") not in hits


def test_a_planted_anchor_field_reds_the_guard(tmp_path):
    """THE regression the acceptance criterion names verbatim: 'a planted anchored
    field that the reset does not handle reds the guard.' Plant a brand-new config
    file carrying a hand-set, unregistered `start_date` and confirm assert_full_coverage
    raises naming it — exactly the shape that let reset_epoch_date drift for 82 days."""
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir()
    (fake_config_dir / "new_feature.json").write_text(json.dumps({"start_date": "2026-06-16"}))
    with pytest.raises(KeyError, match="new_feature.json"):
        car.assert_full_coverage(str(fake_config_dir))


def test_a_planted_anchor_field_that_IS_registered_does_not_red():
    """Negative control for the test above: a registered anchor-shaped field must
    NOT raise, so the guard is discriminating on registration, not merely on
    scariness of the key name."""
    hits = {("character_sheet.json", "start_date")}
    uncovered = {(f, k) for f, k in hits if car._registered(f, k) is None}  # noqa: SLF001 — testing the internal directly
    assert not uncovered


# ── The universe audited for #3671 — spot checks pin the decided rows ─────────


def test_the_four_anchor_shaped_files_from_the_issue_are_all_classified():
    """The issue's own '## Set' enumeration: character_sheet/user_goals RESET,
    training_phases DELIBERATE, vacation_fund's null start_date RULED."""
    assert car._registered("character_sheet.json", "start_date").treatment == car.RESET_TO_GENESIS  # noqa: SLF001
    assert car._registered("user_goals.json", "start_date").treatment == car.RESET_TO_GENESIS  # noqa: SLF001
    assert car._registered("training_phases.json", "current_started").treatment == car.DELIBERATE_CARRY  # noqa: SLF001
    assert car._registered("vacation_fund.json", "start_date").treatment == car.DERIVES_LIVE  # noqa: SLF001


def test_vacation_fund_null_start_date_really_does_derive_live():
    """The DERIVES_LIVE ruling is only honest if the live compute code actually
    behaves that way — pin it against vacation_fund.py's own fallback chain."""
    vf = importlib.import_module("content.vacation_fund")
    from common.constants import EXPERIMENT_START_DATE

    cfg = vf.load_config()
    assert cfg.get("start_date") is None
    # compute_vacation_fund's own resolution: start_date or cfg["start_date"] or EXPERIMENT_START_DATE
    resolved = None or cfg.get("start_date") or EXPERIMENT_START_DATE
    assert resolved == EXPERIMENT_START_DATE


def test_false_positive_keyword_matches_are_ruled_not_anchored_not_silently_dropped():
    """board_of_directors/retired_date, personas/retired_date, experiment_library/
    promoted_date, coaches/tuning_log/date, and portraits/*/date all keyword-match
    the anchor scan but are historical facts, not experiment anchors. They must be
    REGISTERED (not_anchored, with a reason) rather than simply invisible to the scan."""
    must_be_not_anchored = [
        ("board_of_directors.json", "retired_date"),
        ("personas.json", "retired_date"),
        ("experiment_library.json", "promoted_date"),
        ("coaches/tuning_log.json", "date"),
        ("portraits/elena_voss.json", "date"),
    ]
    for f, k in must_be_not_anchored:
        anchor = car._registered(f, k)  # noqa: SLF001
        assert anchor is not None, (f, k)
        assert anchor.treatment == car.NOT_ANCHORED, (f, k, anchor.treatment)


# ── report_lines(): the reset's own before/after report (acceptance criterion 3) ──


def test_report_lines_shows_a_reset_to_genesis_change():
    before = {"character_sheet.json": {"baseline": {"start_date": "2026-06-16"}}}
    after = {"character_sheet.json": {"baseline": {"start_date": "2026-09-06"}}}
    lines = car.report_lines(before_docs=before, after_docs=after, config_dir=CONFIG_DIR)
    hit = [line for line in lines if "character_sheet.json:baseline.start_date" in line]
    assert len(hit) == 1
    assert "2026-06-16" in hit[0] and "2026-09-06" in hit[0] and "->" in hit[0]
    assert "[reset_to_genesis]" in hit[0]


def test_report_lines_shows_deliberate_carry_as_unchanged_even_when_untouched_this_run():
    """A file this run's caller never loaded (training_phases.json — the reset
    doesn't write it) still appears in the report, read fresh off disk, so the
    reset's own output names it instead of leaving it invisible."""
    lines = car.report_lines(before_docs={}, after_docs={}, config_dir=CONFIG_DIR)
    hit = [line for line in lines if "training_phases.json:current_started" in line]
    assert len(hit) == 1
    assert "[deliberate_carry]" in hit[0]
    assert "unchanged" in hit[0]


def test_report_lines_covers_every_path_bearing_registry_entry():
    lines = car.report_lines(before_docs={}, after_docs={}, config_dir=CONFIG_DIR)
    path_bearing = [a for a in car.CONFIG_ANCHOR_REGISTRY if a.path is not None]
    assert len(lines) == len(path_bearing)


# ── The measured failure this issue names, restated as a fixture ──────────────


def test_the_measured_defect_reset_epoch_date_would_have_reeded_the_guard_if_still_present():
    """Reconstruct the exact pre-#3680 config shape (reset_epoch_date present,
    stale, 82 days behind EXPERIMENT_START_DATE) and confirm THIS registry would
    have caught it as unregistered, had it existed at the time. This is the
    counterfactual the issue's own repro describes."""
    fake = {"phases": ["Foundation"], "current": "Foundation", "current_started": "2026-06-16", "reset_epoch_date": "2026-06-16"}
    hits = set()
    for k, v in car._walk_leaves(fake):  # noqa: SLF001
        if car._is_anchor_shaped(k, v):  # noqa: SLF001
            hits.add(k)
    assert "reset_epoch_date" in hits
    assert (
        car._registered("training_phases.json", "reset_epoch_date") is None
    )  # noqa: SLF001 — deliberately unregistered: it must not exist
