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
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The wipe script self-manages sys.path (repo root + lambdas/) at import time.
_spec = importlib.util.spec_from_file_location("restart_intelligence_wipe", REPO_ROOT / "deploy" / "restart_intelligence_wipe.py")
wipe = importlib.util.module_from_spec(_spec)
sys.modules["restart_intelligence_wipe"] = wipe
_spec.loader.exec_module(wipe)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
from experiment import (
    phase_taxonomy as taxonomy,  # noqa: E402
    pk_census,  # noqa: E402
)

CENSUS_ARTIFACT = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"


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
    for pk in ("ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket", "NARRATIVE#arc"):
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


# ── #946: narrative singletons must not survive the wipe ──────────────────────


def test_persona_elena_scoped_and_covered():
    """Elena's narrative running state (pending CALLBACKs, open THREADs, motifs,
    stance) is per-cycle story continuity — it survived the cycle-5 reset live
    because PERSONA#elena was unclassified and absent from the wipe."""
    assert taxonomy.classify("PERSONA#elena", "CALLBACK#2026-07-07#x") == taxonomy.EXPERIMENT_SCOPED
    covered_pks = {pk for pk, *_ in wipe.FULL_PK_PARTITIONS}
    assert "PERSONA#elena" in covered_pks


def test_narrative_arc_state_current_is_now_datable():
    """The wipe's pregenesis mode skipped NARRATIVE#arc STATE#current every time
    (no date in the sk) on the wrong assumption that the engine would recompute
    it — but _detect_arc_transition has no path back to early_baseline. The
    entered_date fallback makes the singleton datable so pregenesis catches it."""
    stale_arc = {
        "pk": "NARRATIVE#arc",
        "sk": "STATE#current",
        "phase": "setback",
        "entered_date": "2026-07-03",
        "previous_phase": "plateau",
    }
    assert wipe.extract_date(stale_arc) == "2026-07-03"


def test_wipe_never_retombstones_a_fresh_arc():
    """Idempotency across re-runs: once the engine writes a post-genesis arc,
    re-running the wipe (same genesis) must skip it, not re-tombstone it."""
    from datetime import date, timedelta

    genesis = date.fromisoformat(wipe.EXPERIMENT_START_DATE)
    stale = {"pk": "NARRATIVE#arc", "sk": "STATE#current", "entered_date": (genesis - timedelta(days=9)).isoformat()}
    fresh = {"pk": "NARRATIVE#arc", "sk": "STATE#current", "entered_date": (genesis + timedelta(days=3)).isoformat()}
    assert wipe.should_tombstone(stale, "pregenesis") is True
    assert wipe.should_tombstone(fresh, "pregenesis") is False


def test_elena_rows_all_datable_for_pregenesis():
    """Every PERSONA#elena row shape must be datable or pregenesis silently skips
    it (the exact bug this issue fixes for NARRATIVE#arc)."""
    rows = [
        {"sk": "THREAD#2026-07-07#silence-as-symptom", "status": "open"},
        {"sk": "CALLBACK#2026-07-07#zone-2-walks", "status": "pending"},
        {"sk": "STANCE#2026-07-08", "as_of": "2026-07-08", "generated_at": "2026-07-08T14:00:00+00:00"},
        {"sk": "STANCE#latest", "as_of": "2026-07-08", "generated_at": "2026-07-08T14:00:00+00:00"},
        {"sk": "MOTIF#state", "last_updated": "2026-07-08T14:00:00+00:00"},
    ]
    for row in rows:
        assert wipe.extract_date(row) is not None, f"undatable PERSONA#elena row: {row['sk']}"


# ── #3514 (DA-2): the LIVE-census leg of the coverage assertion ──────────────
#
# OPERATIONAL_COACH_IDS answers "which coaches exist", which is not the question the
# wipe needs answered. COACH#nudge_ledger and COACH#outbound_ledger are neither coaches
# nor sources, so nothing required them and nothing wiped them for three cycles, while
# the taxonomy called them wipeable. The reset now passes the live partition set
# (experiment.pk_census.live_scoped_pks("COACH#")) into the same assertion.
#
# These tests run OFFLINE — they inject a synthetic census rather than reaching AWS, so
# the positive control is a property of the assertion, not of whatever the table holds
# on the day CI runs.


def test_the_live_census_leg_is_a_positive_control_a_new_coach_partition_reds():
    """A brand-new EXPERIMENT_SCOPED COACH#* partition in the live census, absent from
    COACH_PARTITIONS, must FAIL the coverage assertion. This is the control for the whole
    census leg: without it, passing an empty or wrong census would read as a pass."""
    import pytest

    census = {"COACH#brand_new": "OUTPUT#2026-09-17"}
    with pytest.raises(SystemExit) as exc:
        wipe.assert_registry_coverage(census)
    assert "COACH#brand_new" in str(exc.value)


def test_the_census_leg_only_adds_it_never_subtracts():
    """An EMPTY census must not weaken the registry-derived floor — the eight coaches are
    still required. A check whose strictness depends on what a scan happened to return is
    one that goes quiet exactly when the table is unreadable."""
    wipe.assert_registry_coverage({})  # the offline floor still holds; no exception
    covered = {pk for pk, *_ in wipe.COACH_PARTITIONS}
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    assert {f"COACH#{c}" for c in OPERATIONAL_COACH_IDS} <= covered


def test_a_system_state_partition_in_the_census_is_not_required():
    """The two delivery ledgers this issue reclassified are SYSTEM_STATE, so
    live_scoped_pks filters them out before the assertion ever sees them — verified
    through classify() rather than by asserting the filter's own output, so this fails if
    the reclassification is reverted."""
    for pk in ("COACH#nudge_ledger", "COACH#outbound_ledger"):
        assert taxonomy.classify(pk, "DAY#2026-09-01") == taxonomy.SYSTEM_STATE, pk
    # and the partition they are modelled on, unchanged
    assert taxonomy.classify("COACH#outbound_events", "EVENT#x#2026-08-12") == taxonomy.SYSTEM_STATE


def test_the_commitments_rollup_is_covered():
    """#3514: found by the census leg on its FIRST run — COACH#commitments/TALLY#current,
    the singleton the public follow-through scorecard reads, was EXPERIMENT_SCOPED and
    uncovered. Pinned so it cannot fall back out."""
    covered = {pk for pk, *_ in wipe.COACH_PARTITIONS}
    assert "COACH#commitments" in covered
    assert taxonomy.classify("COACH#commitments", "TALLY#current") == taxonomy.EXPERIMENT_SCOPED


# ── #3599 box 1: the coverage assertion graded against the REAL census, in CI ──
#
# #3514's census leg is live-only: `main()` scans DynamoDB and passes the result in, so
# the claim "today's real partition set is covered" could only ever be made by an operator
# with credentials, at reset time, and its CI control was a HAND-BUILT one-key dict
# ({"COACH#brand_new": ...}). That control proves the assertion can fire; it says nothing
# about the live set.
#
# `deploy/generated/pk_family_census.json` now carries a `coverage_partitions` block —
# every live pk under `pk_census.COVERAGE_PREFIXES` with the class the taxonomy gives it,
# taken from the same scan the artifact already paid for. So the tests below run the SAME
# assertion the reset runs, against MEASURED rows (real pks, real representative sks),
# offline, on every PR. The fixture is the wire.


def _committed_scoped_partitions() -> dict:
    """The live EXPERIMENT_SCOPED partition set from the committed census, through
    pk_census's own reader (never re-derived here — see that function's docstring)."""
    snapshot = json.loads(CENSUS_ARTIFACT.read_text(encoding="utf-8"))
    scoped = pk_census.scoped_partitions_from_snapshot(snapshot)
    # Population floor: a truncated or filtered-to-nothing census must not read as "all
    # covered". Ten coach-tier partitions were live on 2026-09-21; the floor is the eight
    # operational coaches, which cannot drop without a roster change reviewing this line.
    assert len(scoped) >= 8, f"only {len(scoped)} scoped partitions in the committed census — a truncated scan, not the live table"
    return scoped


def test_the_committed_census_carries_the_coverage_granularity():
    """The artifact must enumerate FULL pks, not only the folded `COACH` family — the
    granularity gap #3514 found (`COACH#nudge_ledger` survived three cycles inside a
    family that classified fine). Absence here is a regenerate, not a skip."""
    snapshot = json.loads(CENSUS_ARTIFACT.read_text(encoding="utf-8"))
    block = snapshot.get("coverage_partitions")
    assert block, "the committed census has no coverage_partitions block — run python3 deploy/write_pk_family_census.py"
    assert set(block) == set(pk_census.COVERAGE_PREFIXES), f"census prefixes {sorted(block)} != {sorted(pk_census.COVERAGE_PREFIXES)}"
    assert len(block["COACH#"]) >= 10, f"only {len(block['COACH#'])} live COACH#* partitions recorded"


def test_todays_real_census_passes_the_coverage_assertion():
    """Box 1's second half: the live partition set — including the two delivery ledgers
    #3514 reclassified — is fully covered by the wipe TODAY. Verified live read-only on
    2026-09-21 (16 scoped partitions across the four prefixes, PASS) and pinned here so a
    new uncovered partition reds at PR time rather than at the next reset."""
    wipe.assert_registry_coverage(_committed_scoped_partitions())


def test_a_phantom_census_family_with_no_partitions_entry_reds():
    """Box 1's first half, on the real census rather than a one-key stand-in: plant
    `COACH#phantom_ledger` — the issue's own fixture name, shaped like the two ledgers
    that actually escaped (a `DAY#<date>` sk, not a coach brief) — into the measured set
    and the SAME assertion must SystemExit naming it. Without this the test above is just
    a green light with no proof it can go red."""
    census = dict(_committed_scoped_partitions())
    census["COACH#phantom_ledger"] = "DAY#2026-09-21"
    with pytest.raises(SystemExit) as exc:
        wipe.assert_registry_coverage(census)
    assert "COACH#phantom_ledger" in str(exc.value)


def test_the_reclassified_ledgers_are_live_and_system_state_in_the_measured_census():
    """Why the real census passes is a RULING, not an absence: both ledgers are live rows
    on the table right now, and they stay out of the required set because the taxonomy
    classifies them SYSTEM_STATE (#3514). Graded against the measured class in the
    artifact AND re-derived through classify() on the artifact's own representative row,
    so reverting the rule reds here rather than quietly re-arming the 2026-06 gap."""
    snapshot = json.loads(CENSUS_ARTIFACT.read_text(encoding="utf-8"))
    coach = snapshot["coverage_partitions"]["COACH#"]
    for pk in ("COACH#nudge_ledger", "COACH#outbound_ledger"):
        assert pk in coach, f"{pk} is not in the measured census — this test's premise is stale, re-measure"
        assert coach[pk]["class"] == taxonomy.SYSTEM_STATE, f"{pk} is {coach[pk]['class']} in the census"
        assert taxonomy.classify(pk, coach[pk]["rep_sk"]) == taxonomy.SYSTEM_STATE
    assert pk_census.scoped_partitions_from_snapshot(snapshot).keys().isdisjoint({"COACH#nudge_ledger", "COACH#outbound_ledger"})


def test_a_census_with_no_coverage_block_is_refused_not_treated_as_empty():
    """The vacuous-scan trap in JSON form: a snapshot missing the block must RAISE, never
    return {} — an empty coverage set would make the assertion above pass by having
    nothing to check."""
    with pytest.raises(pk_census.CensusPreflightError):
        pk_census.scoped_partitions_from_snapshot({"families": {}})
