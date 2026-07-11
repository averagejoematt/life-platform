"""tests/test_restart_wipe_coverage.py — taxonomy ↔ wipe drift fails in CI, never at reset time.

The 2026-07-10 clean-sweep audit found six EXPERIMENT_SCOPED sources (forecast,
state_of_matthew, engagement_state, scenarios, what_changed, panelcast) that had
been added to lambdas/phase_taxonomy.py without a matching PARTITIONS entry in
deploy/restart_intelligence_wipe.py. The wipe's own assert_registry_coverage()
correctly refused to run — which meant restart_pipeline's wipe step performed
ZERO writes, discovered only when someone ran the wipe by hand. This test runs
the exact same assertion (plus the reverse phantom-entry check) on every CI run
so the gap is caught at PR time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The wipe script self-manages sys.path (repo root + lambdas/) at import time.
_spec = importlib.util.spec_from_file_location("restart_intelligence_wipe", REPO_ROOT / "deploy" / "restart_intelligence_wipe.py")
wipe = importlib.util.module_from_spec(_spec)
sys.modules["restart_intelligence_wipe"] = wipe
_spec.loader.exec_module(wipe)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
import phase_taxonomy as taxonomy  # noqa: E402


def test_registry_coverage_assertion_passes():
    """The wipe's own gate: every EXPERIMENT_SCOPED source + scoped non-SOURCE pk
    is covered, and no phantom PARTITIONS entries exist. SystemExit here means the
    live wipe would refuse to run (and the reset would silently wipe nothing)."""
    wipe.assert_registry_coverage()


def test_every_scoped_source_has_a_partition():
    """Redundant explicit form of the forward direction, with a readable diff."""
    covered = {src for src, _mode, _extra in wipe.PARTITIONS}
    missing = sorted(s for s in taxonomy.SCOPED_SOURCES if s not in covered)
    assert not missing, f"EXPERIMENT_SCOPED sources missing from the wipe PARTITIONS: {missing}"


def test_no_phantom_partitions():
    """Reverse direction: every PARTITIONS source is a real EXPERIMENT_SCOPED
    taxonomy source (platform_memory is the sanctioned category-split exception)."""
    covered = {src for src, _mode, _extra in wipe.PARTITIONS}
    phantom = sorted(s for s in covered if s not in taxonomy.SCOPED_SOURCES and s != "platform_memory")
    assert not phantom, f"Phantom PARTITIONS entries (not EXPERIMENT_SCOPED in the taxonomy): {phantom}"


def test_scoped_ensemble_pks_covered():
    """Every ENSEMBLE#* pk the taxonomy scopes must appear in FULL_PK_PARTITIONS
    (ENSEMBLE#dispute was scoped in the taxonomy but absent from the wipe)."""
    covered_pks = {pk for pk, *_ in wipe.FULL_PK_PARTITIONS}
    for pk in ("ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "NARRATIVE#arc"):
        assert taxonomy.classify(pk, "X#1") == taxonomy.EXPERIMENT_SCOPED
        assert pk in covered_pks, f"scoped pk {pk} missing from FULL_PK_PARTITIONS"


def test_partition_modes_are_valid():
    valid_modes = {"all", "pregenesis", "by_category"}
    for src, mode, _extra in wipe.PARTITIONS:
        assert mode in valid_modes, f"PARTITIONS[{src}] has invalid mode {mode!r}"
    for _pk, label, mode, _extra, _skp in wipe.FULL_PK_PARTITIONS:
        assert mode in valid_modes, f"FULL_PK_PARTITIONS[{label}] has invalid mode {mode!r}"
    for _pk, label, mode, _extra in wipe.COACH_PARTITIONS:
        assert mode in valid_modes, f"COACH_PARTITIONS[{label}] has invalid mode {mode!r}"
