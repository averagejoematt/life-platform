"""tests/test_prereg_pregenesis_contract_3511.py — #3511 box 3, the CI half.

THE BOX: "A contract test in restart_verify + CI: every non-tombstoned season
PREDICTION# row with created_date ≤ genesis has its prediction_id in the frozen
artifact, else the seal cannot publish."

WHY THIS FILE IS NOT A CREDENTIAL-GATED NO-OP
─────────────────────────────────────────────
CI has no AWS credentials, and a contract test that reaches for DynamoDB and skips
when it cannot is the shape that reports green for months while asserting nothing.
So the rule is split at the seam where credentials actually become necessary:

  `deploy/prereg_provenance_gate.audit_prereg_provenance()` is PURE — rows in,
  findings out. Fetching the rows is the only credentialed step, and it lives in a
  separate function. Everything below runs the REAL predicate over (a) the REAL
  committed frozen artifact and (b) a REAL committed capture of the live ledger
  (`tests/fixtures/prereg_season_rows_2026-09-17.json`, a read-only DynamoDB query
  whose command is recorded inside the fixture). No network, no credentials, no skip.

  The credentialed half is `restart_verify.py` check 20 and the `--apply` path of
  `genesis_prereg_stamp.py`, both of which call the same function on live rows.

The founding-incident control (`test_the_founding_specimen_is_reported`) runs the new
predicate against the exact 2026-09-04 rows the issue was filed about, because a gate
that has never been shown catching its own incident is a gate nobody has watched work.

BOTH mutation controls below mutate a REAL file on disk (a copy of the committed
artifact / fixture) and assert the file's md5 CHANGED before any verdict is read — a
no-op edit reporting "the guard still passes" is not a control, it is a coin flip
that always lands the same way.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "deploy"), str(REPO / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prereg_provenance_gate as gate  # noqa: E402

FROZEN_PATH = REPO / "deploy" / "generated" / "genesis_preregistration.json"
FIXTURE_PATH = REPO / "tests" / "fixtures" / "prereg_season_rows_2026-09-17.json"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


@pytest.fixture(scope="module")
def frozen() -> dict:
    return json.loads(FROZEN_PATH.read_text())


@pytest.fixture(scope="module")
def live_capture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


# ── the derivation is ONE function, and the seeder routes through it ──────────


def test_the_seeder_uses_the_gates_id_derivation_not_a_copy():
    """If the seeder re-stated the slug rule, the gate would reconstruct different ids
    from the frozen claims and report every sealed bet as missing — a gate that reds
    on correct data. Asserted as function IDENTITY, not by reading the source."""
    os.environ.setdefault("TABLE_NAME", "life-platform")
    spec = importlib.util.spec_from_file_location("_seed_3511", REPO / "deploy" / "seed_genesis_preregistration.py")
    seeder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seeder)
    assert seeder._slug is gate.prereg_slug, "the seeder no longer routes its slug through prereg_provenance_gate"
    assert seeder.prereg_provenance_gate is gate


def test_frozen_ids_are_derived_from_the_committed_artifact_and_are_unique(frozen):
    ids = gate.frozen_prediction_ids(frozen)
    claims = [p["claim_natural"] for b in frozen["coaches"].values() for p in b["predictions"]]
    assert len(ids) == len(claims) == 16, f"16 sealed claims expected for genesis {frozen['genesis']}, got {len(claims)}/{len(ids)}"
    for claim in claims:
        assert gate.prediction_id_for(claim, frozen["genesis"]) in ids


def test_a_shapeless_artifact_raises_rather_than_sealing_nothing():
    """An empty id set would invert the gate: every pre-genesis row unsealed, every
    sealed row present. It must be an error, never a quiet zero."""
    for bad in ({}, {"genesis": "2026-09-06"}, {"genesis": "2026-09-06", "coaches": {}}):
        with pytest.raises(ValueError):
            gate.frozen_prediction_ids(bad)


# ── the founding incident (2026-09-04, review QS-1) ───────────────────────────


def _specimen_rows():
    """The two gradeable bets the issue was filed about, in their live shape at the
    time (verified against DynamoDB 2026-09-17: created_at 2026-09-04T17:09Z, status
    pending, directional/14-day, no `pre_registered`). Genesis was 2026-09-05."""
    return [
        {
            "pk": "COACH#explorer_coach",
            "sk": "PREDICTION#pred_20260904_recovery_score_will_be_approximately_53",
            "prediction_id": "pred_20260904_recovery_score_will_be_approximately_53",
            "created_at": "2026-09-04T17:09:00.353508+00:00",
            "created_date": "2026-09-04",
            "phase": "experiment",
            "cycle": 16,
            "status": "pending",
        },
        {
            "pk": "COACH#explorer_coach",
            "sk": "PREDICTION#pred_20260904_under_the_conservative_ramp_protocol_7",
            "prediction_id": "pred_20260904_under_the_conservative_ramp_protocol_7",
            "created_at": "2026-09-04T17:09:00.252877+00:00",
            "created_date": "2026-09-04",
            "phase": "experiment",
            "cycle": 16,
            "status": "pending",
        },
    ]


def _specimen_artifact():
    return {
        "genesis": "2026-09-05",
        "coaches": {"explorer_coach": {"predictions": [{"claim_natural": "A sealed opening claim about recovery."}]}},
    }


def test_the_founding_specimen_is_reported():
    """Run the new rule against the incident it was written for (the #3863 lesson: an
    acceptance box can be vacuous on its own incident)."""
    artifact = _specimen_artifact()
    findings = gate.audit_prereg_provenance(_specimen_rows(), artifact, as_of="2026-09-05")
    kinds = gate.summarize(findings)
    assert kinds[gate.PRE_GENESIS_WRITE] == 2, f"the two Day-0 bets must be reported: {kinds}"
    reported = {f.prediction_id for f in findings if f.kind == gate.PRE_GENESIS_WRITE}
    assert reported == {r["prediction_id"] for r in _specimen_rows()}


def test_sealing_the_specimen_clears_it_the_positive_control():
    """The same rows, with the artifact actually sealing them, produce no write-class
    finding — so the report above is about provenance, not about being pre-genesis."""
    # A seeded row's id carries the GENESIS date, so the sealed twins of the specimen
    # are the same claims at `pred_20260905_…`. Everything else about the rows — the
    # pre-genesis 17:09Z write instant included — is held identical, which is what makes
    # this a control on PROVENANCE rather than on being pre-genesis.
    artifact = {
        "genesis": "2026-09-05",
        "coaches": {
            "explorer_coach": {
                "predictions": [
                    {"claim_natural": "Recovery score will be approximately 53.5% on September 5th."},
                    {"claim_natural": "Under the conservative ramp protocol, 7-day rolling HRV will trend modestly upward."},
                ]
            }
        },
    }
    sealed_ids = sorted(gate.frozen_prediction_ids(artifact))
    rows = [{**r, "prediction_id": pid, "sk": f"PREDICTION#{pid}"} for r, pid in zip(_specimen_rows(), sealed_ids)]
    assert all(r["created_at"].startswith("2026-09-04T17:09") for r in rows)
    findings = gate.audit_prereg_provenance(rows, artifact, as_of="2026-09-05")
    assert gate.summarize(findings)[gate.PRE_GENESIS_WRITE] == 0
    assert gate.summarize(findings)[gate.SEALED_ROW_MISSING] == 0


def test_a_tombstoned_or_out_of_phase_specimen_is_not_reported():
    """How the two bets were actually disposed of (tombstoned to phase=pilot by
    `countdown_gap_reconcile_2026-09-05`): the gate must go quiet once they are."""
    for disposal in ({"tombstone": True, "phase": "pilot"}, {"phase": "pilot"}):
        rows = [{**r, **disposal} for r in _specimen_rows()]
        findings = gate.audit_prereg_provenance(rows, _specimen_artifact(), as_of="2026-09-05")
        assert gate.summarize(findings)[gate.PRE_GENESIS_WRITE] == 0, disposal


# ── the two ways a row presents as pre-genesis, and the Day-1 negative control ─


def test_a_day_one_call_dated_on_genesis_is_not_a_violation():
    """The measured reason the box's literal `created_date <= genesis` is not what was
    implemented. Live on 2026-09-17, nine season rows have created_date == genesis and
    created_at 17:0xZ — 10am PT on Day 1. Flagging those every cycle would make the
    gate unsatisfiable by correct behaviour."""
    row = {
        "pk": "COACH#sleep_coach",
        "sk": "PREDICTION#pred_20260906_as_training_volume_builds_from_the_curre",
        "prediction_id": "pred_20260906_as_training_volume_builds_from_the_curre",
        "created_at": "2026-09-06T17:01:32.539051+00:00",
        "created_date": "2026-09-06",
        "phase": "experiment",
    }
    findings = gate.audit_prereg_provenance([row], _artifact_for("2026-09-06"), as_of="2026-09-06")
    assert [f for f in findings if f.kind != gate.SEALED_ROW_MISSING] == []


def test_a_backdated_row_written_after_the_boundary_is_still_reported():
    """The clause the write-instant rule would otherwise lose: a Day-3 write stamped
    with a pre-genesis created_date READS as pre-registered on /api/predictions, whose
    `date` column is created_date."""
    row = {
        "pk": "COACH#sleep_coach",
        "sk": "PREDICTION#pred_backdated",
        "prediction_id": "pred_backdated",
        "created_at": "2026-09-09T17:01:32+00:00",
        "created_date": "2026-09-05",
        "phase": "experiment",
    }
    findings = gate.audit_prereg_provenance([row], _artifact_for("2026-09-06"), as_of="2026-09-09")
    assert gate.summarize(findings)[gate.BACKDATED_UNSEALED] == 1


def test_the_boundary_is_pacific_midnight_not_utc_midnight():
    """A UTC boundary would put the whole 00:00-07:00Z stretch of genesis day on the
    wrong side of the line — the exact window the countdown-gap sweep exists for."""
    assert gate.genesis_boundary_utc("2026-09-06").isoformat() == "2026-09-06T07:00:00+00:00"
    just_before = {
        "pk": "COACH#x",
        "sk": "PREDICTION#a",
        "prediction_id": "a",
        "created_at": "2026-09-06T06:59:00+00:00",
        "phase": "experiment",
    }
    just_after = {**just_before, "sk": "PREDICTION#b", "prediction_id": "b", "created_at": "2026-09-06T07:00:01+00:00"}
    findings = gate.audit_prereg_provenance([just_before, just_after], _artifact_for("2026-09-06"), as_of="2026-09-06")
    assert {f.prediction_id for f in findings if f.kind == gate.PRE_GENESIS_WRITE} == {"a"}


def test_an_unstamped_row_counts_as_in_season():
    """`attribute_not_exists(phase)` passes PHASE_FILTER_EXPRESSION forever, so a row
    with no phase IS served and must be audited, never waved through."""
    row = {"pk": "COACH#x", "sk": "PREDICTION#a", "prediction_id": "a", "created_at": "2026-09-01T00:00:00+00:00"}
    findings = gate.audit_prereg_provenance([row], _artifact_for("2026-09-06"), as_of="2026-09-06")
    assert gate.summarize(findings)[gate.PRE_GENESIS_WRITE] == 1


def _artifact_for(genesis: str) -> dict:
    return {"genesis": genesis, "coaches": {"sleep_coach": {"predictions": [{"claim_natural": "A sealed claim."}]}}}


# ── the missing-seal clause, and why it is dated ──────────────────────────────


def test_missing_seal_is_only_blocking_from_genesis_onward():
    """The attended seed runs the EVENING BEFORE Day 1, so at publish time the sealed
    rows legitimately are not in the season yet. Without the date test the publish gate
    could never be satisfied — an unclearable gate is one readers learn to skip."""
    artifact = _artifact_for("2026-09-06")
    before = gate.audit_prereg_provenance([], artifact, as_of="2026-09-05")
    after = gate.audit_prereg_provenance([], artifact, as_of="2026-09-06")
    assert [f.kind for f in before] == [gate.SEALED_ROW_MISSING] and not before[0].blocking
    assert [f.kind for f in after] == [gate.SEALED_ROW_MISSING] and after[0].blocking
    assert gate.blocking(before) == [] and len(gate.blocking(after)) == 1


def test_a_sealed_row_stranded_out_of_phase_is_reported_missing():
    """The live cycle-17 shape: the row EXISTS, carries pre_registered=True, and is
    stamped phase=pilot — so it can never be graded and the reader never sees it.
    "Present in the table" is not "in the season"."""
    artifact = _artifact_for("2026-09-06")
    pid = next(iter(gate.frozen_prediction_ids(artifact)))
    stranded = {
        "pk": "COACH#sleep_coach",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "phase": "pilot",
        "cycle": 16,
        "pre_registered": True,
    }
    findings = gate.audit_prereg_provenance([stranded], artifact, as_of="2026-09-08")
    assert gate.summarize(findings)[gate.SEALED_ROW_MISSING] == 1
    in_season = {**stranded, "phase": "experiment", "cycle": 17}
    assert gate.audit_prereg_provenance([in_season], artifact, as_of="2026-09-08") == []


# ── the live capture: the predicate against real wire rows, no credentials ────


def test_the_committed_capture_reproduces_the_live_verdict(frozen, live_capture):
    """The 2026-09-17 read-only capture of the real ledger. Recorded here as EXACT
    numbers rather than "non-empty", so a change in either direction is a decision
    somebody has to make in a diff."""
    assert live_capture["_genesis"] == frozen["genesis"]
    findings = gate.audit_prereg_provenance(live_capture["rows"], frozen, as_of="2026-09-17")
    assert gate.summarize(findings) == {
        gate.PRE_GENESIS_WRITE: 10,  # stale PREDICTION#docket-…-2026-08-03 rows, phase=experiment
        gate.BACKDATED_UNSEALED: 0,
        gate.SEALED_ROW_MISSING: 16,  # ALL of cycle 17's sealed bets, stranded at phase=pilot
    }
    assert len(gate.blocking(findings)) == 26
    docket = [f for f in findings if f.kind == gate.PRE_GENESIS_WRITE]
    assert all("docket-" in f.sk for f in docket), "the write-class findings should all be the docket survivors"
    # Reported per ROW, not per id: the docket writer emits five rows per coach that all
    # carry the SAME prediction_id (sks `…`, `…-2` … `…-5`), across two coach partitions.
    assert len({(f.pk, f.sk) for f in docket}) == 10, "each row must be reported separately"
    assert len({f.prediction_id for f in docket}) == 1, "…and they do in fact share one prediction_id"


def test_the_nine_day_one_rows_in_the_live_capture_are_not_reported(frozen, live_capture):
    """The negative control ON REAL DATA: the capture contains nine rows dated on
    genesis and written at 17:0xZ that day. None of them may be a finding."""
    day_one = [
        r
        for r in live_capture["rows"]
        if r.get("phase") == "experiment"
        and r.get("created_date") == frozen["genesis"]
        and str(r.get("created_at", "")) > frozen["genesis"] + "T07:00:00"
    ]
    assert len(day_one) == 9, f"the capture should hold the nine Day-1 rows, found {len(day_one)}"
    findings = gate.audit_prereg_provenance(day_one, frozen, as_of="2026-09-17")
    assert [f for f in findings if f.kind != gate.SEALED_ROW_MISSING] == []


# ── mutation controls (real files on disk, md5-asserted) ──────────────────────


def test_mutation_control_unsealing_a_claim_in_the_real_artifact_reds_the_gate(tmp_path, frozen, live_capture):
    """Delete one claim from a COPY of the committed frozen artifact on disk. The live
    row for it must flip from "sealed" to a finding. If it does not, the gate is not
    reading the artifact it claims to read."""
    work = tmp_path / "genesis_preregistration.json"
    work.write_bytes(FROZEN_PATH.read_bytes())
    before_md5 = _md5(work)

    mutated = json.loads(work.read_text())
    victim_coach = "sleep_coach"
    dropped = mutated["coaches"][victim_coach]["predictions"].pop(0)
    work.write_text(json.dumps(mutated, indent=1))
    after_md5 = _md5(work)
    assert after_md5 != before_md5, "the mutation did not change the file — refusing to read a no-op verdict"

    dropped_id = gate.prediction_id_for(dropped["claim_natural"], frozen["genesis"])
    assert dropped_id in gate.frozen_prediction_ids(frozen)
    assert dropped_id not in gate.frozen_prediction_ids(gate.load_frozen(work))

    # The row exists live, in the season (as it will be after the repair), and is now
    # unsealed by the mutated artifact → a write-class finding naming it.
    row = {
        "pk": f"COACH#{victim_coach}",
        "sk": f"PREDICTION#{dropped_id}",
        "prediction_id": dropped_id,
        "created_at": "2026-09-06T02:13:38+00:00",
        "created_date": frozen["genesis"],
        "phase": "experiment",
        "pre_registered": True,
    }
    clean = gate.audit_prereg_provenance([row], frozen, as_of="2026-09-17")
    assert [f for f in clean if f.prediction_id == dropped_id and f.kind != gate.SEALED_ROW_MISSING] == []
    reds = gate.audit_prereg_provenance([row], gate.load_frozen(work), as_of="2026-09-17")
    assert [f.kind for f in reds if f.prediction_id == dropped_id] == [gate.PRE_GENESIS_WRITE]

    # And the real tree is untouched — the mutation lived only in tmp_path.
    assert _md5(FROZEN_PATH) == before_md5


def test_mutation_control_planting_an_unsealed_row_in_the_real_capture_reds_the_gate(tmp_path, frozen, live_capture):
    """Plant one unsealed pre-genesis row into a COPY of the committed live capture on
    disk and watch the finding count move by exactly one, naming the plant."""
    work = tmp_path / "capture.json"
    work.write_bytes(FIXTURE_PATH.read_bytes())
    before_md5 = _md5(work)
    baseline = len(gate.audit_prereg_provenance(json.loads(work.read_text())["rows"], frozen, as_of="2026-09-17"))

    planted_id = "pred_MUTATION_CONTROL_3511_unsealed_pre_genesis_bet"
    doc = json.loads(work.read_text())
    doc["rows"].append(
        {
            "pk": "COACH#explorer_coach",
            "sk": f"PREDICTION#{planted_id}",
            "prediction_id": planted_id,
            "created_at": "2026-09-05T17:09:00+00:00",  # the QS-1 hour, one day pre-genesis
            "created_date": "2026-09-05",
            "phase": "experiment",
            "status": "pending",
        }
    )
    work.write_text(json.dumps(doc, indent=1))
    assert _md5(work) != before_md5, "the mutation did not change the file — refusing to read a no-op verdict"

    mutated = gate.audit_prereg_provenance(json.loads(work.read_text())["rows"], frozen, as_of="2026-09-17")
    assert len(mutated) == baseline + 1
    hit = [f for f in mutated if f.prediction_id == planted_id]
    assert [f.kind for f in hit] == [gate.PRE_GENESIS_WRITE]
    assert hit[0].blocking

    # Not a blanket rule: the SAME planted row, sealed by the artifact, is clean.
    sealed_artifact = json.loads(FROZEN_PATH.read_text())
    sealed_artifact["genesis"] = "2026-09-05"
    sealed_artifact["coaches"] = {"explorer_coach": {"predictions": [{"claim_natural": "MUTATION CONTROL 3511 unsealed pre genesis bet"}]}}
    # The derived id is the slug of the claim, which is NOT the planted sk — so seal it
    # by its own derived id rather than asserting a hand-typed string.
    sealed_id = gate.prediction_id_for("MUTATION CONTROL 3511 unsealed pre genesis bet", "2026-09-05")
    assert gate.frozen_prediction_ids(sealed_artifact) == {sealed_id}
    sealed_row = {**doc["rows"][-1], "prediction_id": sealed_id, "sk": f"PREDICTION#{sealed_id}"}
    cleared = gate.audit_prereg_provenance([sealed_row], sealed_artifact, as_of="2026-09-17")
    assert cleared == [], f"the same pre-genesis row, sealed, must be clean: {cleared}"

    assert planted_id not in FIXTURE_PATH.read_text(), "the plant must not exist in the real committed capture"


# ── the wiring: both callers reach the same function ─────────────────────────


def test_restart_verify_and_the_seal_publisher_both_call_this_predicate():
    """A pure predicate nothing calls is a library, not a gate. Asserted on the source
    of both callers, because importing restart_verify runs module-level AWS setup."""
    rv = (REPO / "deploy" / "restart_verify.py").read_text()
    assert "prereg_provenance_gate" in rv and "audit_live" in rv
    assert "Live prediction ledger agrees with the frozen pre-registration (#3511)" in rv
    stamp = (REPO / "deploy" / "genesis_prereg_stamp.py").read_text()
    assert "require_clean_for_publish" in stamp
    assert "Refusing to publish" in stamp


def test_the_finding_classes_are_a_closed_set():
    assert gate.FINDING_CLASSES == ("PRE_GENESIS_WRITE", "BACKDATED_UNSEALED", "SEALED_ROW_MISSING")
    assert set(gate.summarize([])) == set(gate.FINDING_CLASSES)


def test_the_partition_list_unions_the_registry_and_the_artifact(frozen):
    """training_coach is sealed in the 2026-09-06 artifact and is NOT in the live
    operational roster (retired at the cycle-13 genesis, ADR-153). Reading only the
    roster would report its two sealed bets as missing forever."""
    parts = gate.season_partitions(frozen)
    assert "COACH#training_coach" in parts
    from coach import persona_registry

    assert "training_coach" not in persona_registry.OPERATIONAL_COACH_IDS
    assert all(f"COACH#{cid}" in parts for cid in persona_registry.OPERATIONAL_COACH_IDS)


def test_as_of_accepts_a_date_object_too():
    artifact = _artifact_for("2026-09-06")
    d = date(2026, 9, 6)
    assert gate.audit_prereg_provenance([], artifact, as_of=d)[0].blocking
    assert not gate.audit_prereg_provenance([], artifact, as_of=d - timedelta(days=1))[0].blocking
