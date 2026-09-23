"""tests/test_countdown_gap_sweep.py — regression guard for the wipe-to-genesis
countdown gap (#1947).

The cycle-11 reset wiped a full day before genesis; the daily writers kept
running and ~397 EXPERIMENT_SCOPED rows written in the window escaped the
archive forever (they carry the current phase or none, no cycle, no tombstone —
so PHASE_FILTER_EXPRESSION admits them as live state). These tests pin the
sweep that closes it:

  - a write landing AFTER the wipe timestamp is caught (acceptance 3);
  - windowing works by timestamp attribute AND by sk-embedded ISO timestamp
    (attribute-only windowing undercounted by ~28 rows — the COMPRESSED#/VOICE#
    class has no timestamp anywhere and must be FLAGGED, never silently skipped);
  - the partition list is DERIVED from the wipe registries (guard-the-set): a
    new EXPERIMENT_SCOPED taxonomy source that isn't swept fails loudly;
  - sanctioned reset-pipeline writes (ledger reset rows, chronicle
    keep-resurrections, genesis prereg seeds) are never classified escapees;
  - genuine post-genesis (new-cycle) rows are never touched.

All offline — DDB is a fake; dates derive from the live EXPERIMENT_START_DATE
so a future re-anchor can't turn these into wall-clock time bombs.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import countdown_gap_sweep as sweep  # noqa: E402
import reconcile_countdown_gap as reconcile  # noqa: E402
import restart_intelligence_wipe as wipe  # noqa: E402
from experiment import phase_taxonomy as taxonomy  # noqa: E402

GENESIS = wipe.EXPERIMENT_START_DATE
PHASE_CURRENT = sweep.EXPERIMENT_PHASE_CURRENT
BOUNDARY = sweep.genesis_boundary_utc(GENESIS)  # midnight PT of genesis, as UTC
WIPE_TS = BOUNDARY - timedelta(hours=15)  # a future-genesis countdown window
IN_WINDOW = BOUNDARY - timedelta(hours=14)  # the 17:00 UTC daily run, post-wipe
CYCLE = 99  # explicit current cycle for every offline call — never the SSM read
COACH_PK = wipe.COACH_PARTITIONS[0][0]  # derived, never hand-written
INSIGHTS_PK = f"{wipe.USER_PK_PREFIX}insights"
LEDGER_PK = f"{wipe.USER_PK_PREFIX}ledger"
CHRONICLE_PK = f"{wipe.USER_PK_PREFIX}chronicle"


class FakeTable:
    """Minimal DDB table: query by pk (+ optional begins_with sk prefix)."""

    def __init__(self, items):
        self.items = items

    def query(self, **kwargs):
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk, skp = vals[":pk"], vals.get(":skp")
        return {"Items": [i for i in self.items if i["pk"] == pk and (skp is None or i["sk"].startswith(skp))]}


def _wipe_evidence_row():
    """A row the wipe archived — the evidence run_sweep derives its window from."""
    return {
        "pk": INSIGHTS_PK,
        "sk": "INSIGHT#pre-wipe",
        "tombstone": True,
        "tombstoned_at": WIPE_TS.isoformat(),
        "tombstoned_reason": wipe.TOMBSTONE_REASON,
    }


# ── acceptance 3: a write landing after the wipe timestamp is caught ──────────


def test_write_after_wipe_is_caught_as_escapee():
    row = {"pk": COACH_PK, "sk": "THREAD#topic-x", "status": "open", "created_at": IN_WINDOW.isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE


def test_end_to_end_sweep_catches_the_simulated_write():
    escapee = {"pk": COACH_PK, "sk": "THREAD#topic-x", "status": "open", "created_at": IN_WINDOW.isoformat()}
    res = sweep.run_sweep(FakeTable([_wipe_evidence_row(), escapee]), current_cycle=CYCLE, served_keys=set())
    assert res["totals"][sweep.ESCAPEE] == 1
    assert (wipe.COACH_PARTITIONS[0][1], COACH_PK, "THREAD#topic-x", IN_WINDOW.isoformat()) in [tuple(e) for e in res["escapees"]]
    # window was DERIVED from the wipe's own tombstoned_at evidence
    assert res["window_start"] == WIPE_TS
    assert "derived" in res["wipe_ts_source"]


def test_sweep_without_wipe_evidence_fails_loud():
    with pytest.raises(sweep.SweepError):
        sweep.run_sweep(
            FakeTable([{"pk": COACH_PK, "sk": "THREAD#x", "created_at": IN_WINDOW.isoformat()}]),
            current_cycle=CYCLE,
            served_keys=set(),
        )


# ── both windowing tiers + the flag contract (the driver's ~28-row undercount) ─


def test_sk_embedded_iso_timestamp_windows_without_any_attribute():
    """INSIGHT# escapees have NO timestamp attribute — the sk carries the ISO ts."""
    row = {"pk": INSIGHTS_PK, "sk": f"INSIGHT#{IN_WINDOW.isoformat()}"}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE


def test_no_timestamp_anywhere_is_flagged_never_skipped():
    row = {"pk": COACH_PK, "sk": "COMPRESSED#history"}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.FLAG_UNDATABLE
    res = sweep.run_sweep(FakeTable([_wipe_evidence_row(), row]), current_cycle=CYCLE, served_keys=set())
    assert (wipe.COACH_PARTITIONS[0][1], COACH_PK, "COMPRESSED#history", sweep.FLAG_UNDATABLE) in [tuple(f) for f in res["flagged"]]


def test_date_only_overlapping_the_window_is_ambiguous():
    row = {"pk": COACH_PK, "sk": f"STANCE#{WIPE_TS.date().isoformat()}"}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.FLAG_AMBIGUOUS


def test_pre_window_untombstoned_on_an_all_partition_is_flagged():
    """Un-tombstoned but write-dated before the wipe on a mode-'all' partition:
    either the wipe missed it or a countdown put_item clobbered its tombstone."""
    row = {"pk": COACH_PK, "sk": "THREAD#old", "created_at": (WIPE_TS - timedelta(days=3)).isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.FLAG_PRE_WINDOW


# ── never touch genuine new-cycle rows ─────────────────────────────────────────


def test_post_genesis_write_is_outside_the_window():
    row = {"pk": COACH_PK, "sk": "THREAD#new", "created_at": (BOUNDARY + timedelta(hours=2)).isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.OUTSIDE_AFTER


def test_boundary_semantics_are_start_inclusive_end_exclusive():
    at_start = {"pk": COACH_PK, "sk": "OUTPUT#a", "created_at": WIPE_TS.isoformat()}
    at_end = {"pk": COACH_PK, "sk": "OUTPUT#b", "created_at": BOUNDARY.isoformat()}
    assert sweep.classify_item(at_start, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE
    assert sweep.classify_item(at_end, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.OUTSIDE_AFTER


def test_already_tombstoned_rows_are_skipped():
    row = {"pk": COACH_PK, "sk": "THREAD#done", "tombstone": True, "created_at": IN_WINDOW.isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ALREADY_TOMBSTONED


# ── sanctioned reset-pipeline writes are never escapees ────────────────────────


def test_ledger_reset_rows_are_mode_skipped_like_the_wipe_would():
    """TOTALS#current / LIFETIME# / CYCLE_TOTALS# carry no wipe-extractable date,
    so the wipe's own should_tombstone predicate excludes them (mode pregenesis)."""
    for sk, attrs in (
        ("TOTALS#current", {"reset_at": IN_WINDOW.isoformat(), "reset_cycle": 10}),
        ("CYCLE_TOTALS#010", {"closed_at": IN_WINDOW.isoformat(), "cycle": 10}),
    ):
        row = {"pk": LEDGER_PK, "sk": sk, **attrs}
        assert sweep.classify_item(row, "pregenesis", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.MODE_SKIP, sk


def test_chronicle_keep_resurrection_is_sanctioned():
    row = {
        "pk": CHRONICLE_PK,
        "sk": "DATE#2026-02-28",
        "date": (BOUNDARY.date() - timedelta(days=3)).isoformat(),  # lead-ins are pre-genesis-dated
        "redated_from_sk": "DATE#2026-02-28",
        "last_updated": IN_WINDOW.isoformat(),
    }
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.SANCTIONED


def test_genesis_prereg_seed_is_sanctioned_by_content_date():
    """seed_genesis_preregistration writes COACH# PREDICTION# rows in-window with
    created_at=now but created_date=genesis — new-cycle state, never an escapee."""
    row = {
        "pk": COACH_PK,
        "sk": "PREDICTION#pred_20260727_x",
        "created_at": IN_WINDOW.isoformat(),
        "created_date": GENESIS,
        "pre_registered": True,
    }
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.SANCTIONED


def test_utc_dated_countdown_write_is_still_an_escapee():
    """The measured miss (live cycle-11 data): countdown writers running in the
    00:00–07:00Z pre-genesis stretch stamp UTC content dates that already read
    as the genesis date — a bare content date >= genesis must NOT exempt them
    (that looseness swallowed ~50 real COMMITMENT#/PREDICTION# escapees)."""
    row = {
        "pk": COACH_PK,
        "sk": "COMMITMENT#commit_x",
        "phase": PHASE_CURRENT,
        "created_date": GENESIS,  # UTC-stamped "genesis" date, but content is the closing cycle's
        "created_at": (BOUNDARY - timedelta(hours=5)).isoformat(),  # in-window
    }
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE


def test_current_cycle_stamp_alone_is_not_provenance():
    """The 2026-09-04 specimen (review QS-1): the 17:09Z coach-state-updater run wrote a
    gradeable PREDICTION# on Day 0 stamped cycle=<current> — every live writer stamps the
    cycle since #1233 and the reset bumps SSM BEFORE genesis, so the stamp proves nothing
    about who wrote the row. The old rule sanctioned it and check 14 could never fail on
    the partitions #1947 was written for. A stale cycle stamp is still an escapee."""
    row = {
        "pk": COACH_PK,
        "sk": "PREDICTION#pred_20260904_recovery_score",
        "phase": PHASE_CURRENT,
        "cycle": CYCLE,
        "status": "pending",
        "created_date": (date.fromisoformat(GENESIS) - timedelta(days=1)).isoformat(),
        "created_at": IN_WINDOW.isoformat(),
    }
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE
    assert sweep.classify_item({**row, "cycle": CYCLE - 1}, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE


def test_reset_seed_marker_is_sanctioned_the_same_row_without_it_is_not():
    """Positive control on the replacement rule: the reset tooling's own marker is the
    only general exemption; strip it and the identical row is an escapee."""
    base = {"pk": CHRONICLE_PK, "sk": "DATE#x", "phase": PHASE_CURRENT, "cycle": CYCLE, "generated_at": IN_WINDOW.isoformat()}
    assert sweep.classify_item({**base, "reset_seed": True}, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.SANCTIONED
    assert sweep.classify_item(base, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE


def test_seeder_hypothesis_id_is_sanctioned():
    row = {
        "pk": f"{wipe.USER_PK_PREFIX}hypotheses",
        "sk": f"HYPOTHESIS#{IN_WINDOW.isoformat()}",
        "phase": PHASE_CURRENT,
        "hypothesis_id": "genesis_prereg_h1",
        "created_at": IN_WINDOW.isoformat(),
    }
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.SANCTIONED


def test_non_current_phase_rows_are_already_hidden_not_escapees():
    """The rebuild steps write phase="pilot" rows in-window — those fail
    PHASE_FILTER_EXPRESSION / singleton_visible today, so they are not leaking
    and must never be mutated."""
    row = {"pk": f"{wipe.USER_PK_PREFIX}character_sheet", "sk": "DATE#x", "phase": "pilot", "computed_at": IN_WINDOW.isoformat()}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ALREADY_HIDDEN


# ── guard-the-set: the partition list is derived, and the chain fails loud ─────


def test_sweep_partitions_cover_every_scoped_taxonomy_source_and_pk():
    parts = sweep.scoped_partitions()
    labels = {label for _pk, label, _m, _e, _s in parts}
    pks = {pk for pk, _l, _m, _e, _s in parts}
    missing_sources = [s for s in taxonomy.SCOPED_SOURCES if s not in labels]
    assert not missing_sources, f"scoped sources not swept: {missing_sources}"
    for pk in ("ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket", "NARRATIVE#arc", "PERSONA#elena"):
        assert pk in pks, f"scoped pk not swept: {pk}"
    coach_pks = {pk for pk, *_ in wipe.COACH_PARTITIONS}
    assert coach_pks <= pks and len(coach_pks) >= 9  # 8 coaches + COACH#computation


def test_new_scoped_source_without_wipe_coverage_fails_the_sweep(monkeypatch):
    """The negative proof: add a scoped source to the taxonomy without wipe
    coverage and the sweep must refuse to run (never silently under-sweep)."""
    monkeypatch.setattr(taxonomy, "SCOPED_SOURCES", tuple(taxonomy.SCOPED_SOURCES) + ("brand_new_scoped_source",))
    with pytest.raises(SystemExit):
        sweep.scoped_partitions()


# ── the reconcile's stamp mirrors the wipe's #1202 defence-in-depth ────────────


def test_reconcile_update_uses_if_not_exists_and_its_own_reason():
    expr, names, values = reconcile.build_reconcile_update({"hidden": True}, "2026-08-02T00:00:00+00:00", 10)
    assert "tombstoned_reason = if_not_exists(tombstoned_reason, :reason)" in expr
    assert "#cyc = if_not_exists(#cyc, :cycle)" in expr
    assert "tombstoned_at = if_not_exists(tombstoned_at, :ts)" in expr
    assert values[":reason"] == f"countdown_gap_reconcile_{GENESIS}"
    assert values[":phase"] == "pilot" and values[":cycle"] == 10
    assert names["#x_hidden"] == "hidden" and values[":val_hidden"] is True


def test_reconcile_reason_is_distinct_from_the_wipe_reason():
    assert reconcile.RECONCILE_REASON != wipe.TOMBSTONE_REASON


# ── #3643: the cycle's own pre-registration post is not an escapee; a prior cycle's is ──

_CURRENT_SHA = "bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d"


def _prereg_post(sha: str) -> dict:
    """The Day-1 specimen shape (2026-09-05 → cycle 17): published, in-window, sha-stamped."""
    return {
        "pk": CHRONICLE_PK,
        "sk": "DATE#" + (BOUNDARY.date() - timedelta(days=1)).isoformat(),
        "status": "published",
        "title": "The Plan, On the Record",
        "pre_registration": True,
        "prereg_sha256": sha,
        "cycle": CYCLE,
        "created_at": IN_WINDOW.isoformat(),
        "last_updated": IN_WINDOW.isoformat(),
    }


def test_the_cycles_own_prereg_post_is_sanctioned_by_its_sealed_sha():
    """The specimen check 14 reported on 2026-09-06 Day 1. Mutation control: delete the
    `pre_registration`/`prereg_sha256` branch in sanctioned_reason → this reads ESCAPEE."""
    row = _prereg_post(_CURRENT_SHA)
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE, current_prereg_sha=_CURRENT_SHA) == sweep.SANCTIONED
    assert "pre-registration" in (sweep.sanctioned_reason(row, GENESIS, CYCLE, _CURRENT_SHA) or "")


def test_a_prior_cycles_prereg_post_is_still_an_escapee():
    row = _prereg_post("0" * 64)
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE, current_prereg_sha=_CURRENT_SHA) == sweep.ESCAPEE


def test_no_stamp_to_compare_against_sanctions_nothing():
    """Fail-closed: the marker alone never sanctions — the sha must match a stamp the sweep could read."""
    row = _prereg_post(_CURRENT_SHA)
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE, current_prereg_sha=None) == sweep.ESCAPEE


def test_the_stamp_reader_only_answers_for_its_own_genesis(monkeypatch, tmp_path):
    import genesis_prereg_stamp as gps

    stamp = tmp_path / "s.json"
    stamp.write_text('{"genesis": "%s", "sha256": "%s"}' % (GENESIS, _CURRENT_SHA))
    monkeypatch.setattr(gps, "STAMP_PATH", stamp)
    assert sweep.current_prereg_sha_for(GENESIS) == _CURRENT_SHA
    assert sweep.current_prereg_sha_for("2001-01-01") is None
    monkeypatch.setattr(gps, "STAMP_PATH", tmp_path / "missing.json")
    assert sweep.current_prereg_sha_for(GENESIS) is None


# ── #4055: the served-manifest lead-in exemption ────────────────────────────
#
# A reset re-dates a carried-forward chronicle lead-in by writing a new `date`
# ATTRIBUTE and leaving its `sk` alone (#3650) — so the row's `sk` can predate
# the wipe by months while it is the CURRENT, served post. Before this
# exemption existed, `reconcile_countdown_gap.py --apply` tombstoned exactly
# such a row (`DATE#2026-09-05`, "The Plan, On the Record") on 2026-09-22,
# breaking two nightly dead-men 14h later. These tests plant the same shape.

SERVED_LEAD_IN_SK = "DATE#2026-07-21"  # the live #4040/#4055 specimen's own sk


def _served_lead_in_row():
    """Shaped to be classified an escapee by EVERY OTHER sanctioned_reason() rule: no
    redated_from_sk, no reset_seed marker, no pre_registration, and a write timestamp
    inside the countdown window — only the served-manifest exemption can save it."""
    return {
        "pk": CHRONICLE_PK,
        "sk": SERVED_LEAD_IN_SK,
        "title": "The Night Before Everything",
        "date": WIPE_TS.date().isoformat(),  # reset re-dated the ATTRIBUTE; sk untouched
        "created_at": IN_WINDOW.isoformat(),  # write-dated inside [wipe, genesis)
    }


def test_a_served_lead_in_is_sanctioned_not_an_escapee():
    """Fixture: a served lead-in dated inside the countdown gap is SANCTIONED."""
    row = _served_lead_in_row()
    served = {(CHRONICLE_PK, SERVED_LEAD_IN_SK)}
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE, served_keys=served) == sweep.SANCTIONED
    reason = sweep.sanctioned_reason(row, GENESIS, CYCLE, served_keys=served)
    assert reason is not None and "served journal manifest" in reason


def test_mutation_control_removing_the_exemption_the_row_reappears_as_an_escapee():
    """MUTATION CONTROL (#4055 acceptance box 3): the identical row, with the exemption
    removed, reads ESCAPEE — proving the SANCTIONED result above is the served-manifest
    check doing work, not some other rule silently covering the same row."""
    row = _served_lead_in_row()
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE, served_keys=set()) == sweep.ESCAPEE
    assert sweep.classify_item(row, "all", WIPE_TS, BOUNDARY, GENESIS, CYCLE) == sweep.ESCAPEE  # default = unexempted
    assert sweep.sanctioned_reason(row, GENESIS, CYCLE, served_keys=set()) is None


def test_run_sweep_end_to_end_never_lists_a_served_lead_in_as_an_escapee():
    """The tool surface both check 14 and reconcile_countdown_gap.py read: with the
    served key passed, the row lands in `sanctioned` (audited, never mutated) and NOT
    in `escapees` (what reconcile_countdown_gap.py --apply would stamp)."""
    row = _served_lead_in_row()
    served = {(CHRONICLE_PK, SERVED_LEAD_IN_SK)}
    res = sweep.run_sweep(FakeTable([_wipe_evidence_row(), row]), current_cycle=CYCLE, served_keys=served)
    assert res["totals"].get(sweep.ESCAPEE, 0) == 0
    assert not any(pk == CHRONICLE_PK and sk == SERVED_LEAD_IN_SK for _l, pk, sk, _v in res["escapees"])
    sanctioned_hit = [(pk, sk, why) for _l, pk, sk, why in res["sanctioned"] if pk == CHRONICLE_PK and sk == SERVED_LEAD_IN_SK]
    assert len(sanctioned_hit) == 1
    assert "served journal manifest" in sanctioned_hit[0][2]


def test_run_sweep_without_the_served_key_the_same_row_is_an_escapee():
    """The other half of the mutation control, at the run_sweep surface reconcile_
    countdown_gap.py and restart_verify check 14 both consume."""
    row = _served_lead_in_row()
    res = sweep.run_sweep(FakeTable([_wipe_evidence_row(), row]), current_cycle=CYCLE, served_keys=set())
    assert res["totals"].get(sweep.ESCAPEE, 0) == 1
    assert any(pk == CHRONICLE_PK and sk == SERVED_LEAD_IN_SK for _l, pk, sk, _v in res["escapees"])


class _ServedManifestFakeTable(FakeTable):
    """Extends FakeTable's sweep-shaped `query` (pk [+ begins_with sk]) so the SAME fake
    also answers `chronicle_manifest_qa._chronicle_rows`'s boto3.dynamodb.conditions
    Key-based partition query (no ExpressionAttributeValues) — used only by the
    auto-derivation test below, to prove `run_sweep`'s default exemption really is the
    manifest dead-man's OWN `served_chronicle_keys`, not a second hand-rolled matcher."""

    def query(self, **kwargs):
        if "ExpressionAttributeValues" in kwargs:
            return super().query(**kwargs)
        return {"Items": [i for i in self.items if i["pk"] == CHRONICLE_PK and str(i.get("sk", "")).startswith("DATE#")]}


class _FakeManifestS3:
    def __init__(self, posts):
        import json

        self._body = json.dumps({"posts": posts}).encode()

    def get_object(self, Bucket, Key):
        return {"Body": type("B", (), {"read": lambda s: self._body})()}


def test_run_sweep_auto_derives_the_served_exemption_via_the_manifest_qa_matcher(monkeypatch):
    """No `served_keys` passed at all (the shape both real callers use): `run_sweep`
    derives the exemption itself from `chronicle_manifest_qa.served_chronicle_keys` —
    proving it is ONE derivation, never a second hand list, per the #4055 acceptance."""
    import boto3

    row = _served_lead_in_row()
    fake_s3 = _FakeManifestS3([{"date": row["date"], "title": row["title"]}])
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake_s3)

    table = _ServedManifestFakeTable([_wipe_evidence_row(), row])
    res = sweep.run_sweep(table, current_cycle=CYCLE)  # served_keys defaults to None -> auto-derived
    assert res["served_keys"] == {(CHRONICLE_PK, SERVED_LEAD_IN_SK)}
    assert res["totals"].get(sweep.ESCAPEE, 0) == 0
    assert any(pk == CHRONICLE_PK and sk == SERVED_LEAD_IN_SK for _l, pk, sk, _why in res["sanctioned"])


def test_run_sweep_auto_derivation_degrades_to_no_exemption_on_an_unreadable_manifest(monkeypatch):
    """An unreadable manifest/partition exempts nothing — MORE conservative, never less
    (the row shows up loudly as an escapee rather than silently vanishing)."""
    import boto3

    row = _served_lead_in_row()

    class _BrokenS3:
        def get_object(self, Bucket, Key):
            raise RuntimeError("no object")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _BrokenS3())
    table = _ServedManifestFakeTable([_wipe_evidence_row(), row])
    res = sweep.run_sweep(table, current_cycle=CYCLE)
    assert res["served_keys"] == set()
    assert res["totals"].get(sweep.ESCAPEE, 0) == 1
