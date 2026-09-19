"""#3599 acceptance box 3 — a seed naming a retired coach, or a baseline that disagrees
with constants, must refuse to seal.

THE POSITIVE CONTROL IS RE-MEASURED, NOT INHERITED
──────────────────────────────────────────────────
The issue says "today's cycle-16 artifact fails on two counts". That artifact is gone —
cycle 17 (genesis 2026-09-06) has been live since 2026-09-06 — so the control was
re-derived from the cycle-17 seal instead. It is not synthetic: the bytes in
`tests/fixtures/prereg_cycle17_2026-09-06.json` are byte-identical to the frozen file,
to its committed stamp, and to the artifact published at
https://averagejoematt.com/experiments/prereg/genesis-2026-09-06.json
(sha256 bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d, curled
2026-09-18). The first test in this file asserts that identity, so the control cannot
quietly become a synthetic one.

Measured verdict against the live seal: **7 blocking findings across all 4 kinds** —
not the two the issue predicted.

  COACH_NOT_OPERATIONAL  1  training_coach / "Dr. Sarah Chen", retired at the cycle-13
                            genesis (ADR-153)
  COACH_NAME_MISMATCH    1  physical_coach sealed as "Dr. Victor Reyes"; the registry
                            (and therefore /api/coaches and /api/predictions) says
                            "Dr. Max Reyes"
  BASELINE_MISMATCH      3  three start-weight assertions of 326.2 lbs against an
                            EXPERIMENT_BASELINE_WEIGHT_LBS of 327.34
  MIN_EFFECT_UNDERIVED   2  both hypotheses carry a bare literal bar with no metric,
                            sd, n or window — frozen 02:13Z on 2026-09-06, before
                            #3552's derivation shipped

WHAT THE NEGATIVE CONTROL IS
────────────────────────────
The SAME artifact with each violation repaired from the repo's own sources (the
registry's byline map, the constants baseline, a #3552-shaped derivation block) — so
"passes" is a property of the repair, not of a hand-built object that was never dirty.
Each clause is then re-broken ALONE against that repaired copy, so a clause cannot ride
another clause's finding.

MUTATION CONTROLS
─────────────────
Two, both against a REAL file on disk (a copy of the committed fixture in `tmp_path`,
never the shared tree — a lane is parallel), and both assert the file's md5 CHANGED
before any verdict is read. A no-op edit that reports "the guard still works" is not a
control; it is a coin flip that always lands the same way.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "deploy"), str(REPO / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prereg_truth_gate as gate  # noqa: E402

FIXTURE_PATH = REPO / "tests" / "fixtures" / "prereg_cycle17_2026-09-06.json"
FROZEN_PATH = REPO / "deploy" / "generated" / "genesis_preregistration.json"
STAMP_PATH = REPO / "deploy" / "generated" / "genesis_preregistration.sha256.json"

#: The seal the control is taken from. Curled from the public URL on 2026-09-18 and
#: equal to the committed stamp; asserted below rather than trusted.
CYCLE17_SEAL_SHA256 = "bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d"
CYCLE17_GENESIS = "2026-09-06"

#: The measured verdict, recorded so a silent change to the sealed bytes or to the
#: predicate reds rather than drifts.
CYCLE17_VERDICT = {
    gate.COACH_NOT_OPERATIONAL: 1,
    gate.COACH_NAME_MISMATCH: 1,
    gate.BASELINE_MISMATCH: 3,
    gate.MIN_EFFECT_UNDERIVED: 2,
}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def sealed() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture(scope="module")
def bylines() -> dict[str, str]:
    people, _retired = gate.repo_coach_bylines()
    return people


def _audit(artifact: dict, **over):
    people, retired = gate.repo_coach_bylines()
    kwargs = {"baseline_lbs": gate.repo_baseline_lbs(), "coach_bylines": people, "retired_ids": retired}
    kwargs.update(over)
    return gate.audit_prereg_truth(artifact, **kwargs)


def _repaired(artifact: dict) -> dict:
    """The sealed artifact with every measured violation repaired FROM THE REPO. Never
    a hand-built clean object: a negative control assembled independently of the
    positive one proves nothing about the repair."""
    people, _retired = gate.repo_coach_bylines()
    baseline = gate.repo_baseline_lbs()
    raw = json.dumps(artifact)
    # every start-weight assertion restated at the true baseline
    raw = raw.replace("326.2", f"{baseline:g}")
    fixed = json.loads(raw)
    fixed["coaches"] = {cid: block for cid, block in fixed["coaches"].items() if cid in people}
    for cid, block in fixed["coaches"].items():
        block["coach_name"] = people[cid]
    for h in fixed["hypotheses"]:
        spec = h["test_spec"]
        spec["min_effect_derivation"] = {
            "metric": spec["outcome_metric"],
            "unit": "lbs",
            "rule": "0.5 x SD of successive differences / sqrt(2)",
            "sd": 1.42,
            "n": 21,
            "window_days": 90,
        }
    return fixed


# ── the control is the real, published seal ──────────────────────────────────


def test_the_control_is_the_published_cycle17_seal_byte_for_byte():
    """If this ever fails the positive control has stopped being a live specimen, and
    every count recorded in this file is about something else."""
    assert _sha256(FIXTURE_PATH) == CYCLE17_SEAL_SHA256
    assert _sha256(FROZEN_PATH) == CYCLE17_SEAL_SHA256, "the frozen artifact no longer matches the sealed control"
    stamp = json.loads(STAMP_PATH.read_text())
    assert stamp["sha256"] == CYCLE17_SEAL_SHA256
    assert stamp["genesis"] == CYCLE17_GENESIS


# ── positive control ─────────────────────────────────────────────────────────


def test_the_published_cycle17_seal_fails_the_gate(sealed):
    findings = _audit(sealed)
    assert gate.summarize(findings) == CYCLE17_VERDICT
    assert len(gate.blocking(findings)) == 7


def test_the_live_specimen_exercises_every_finding_kind(sealed):
    """Guard-the-set: a kind nothing in the corpus reaches is a clause nobody has
    watched. All four are reached by one real artifact."""
    assert set(gate.summarize(_audit(sealed))) == set(gate.FINDING_KINDS)


def test_the_retired_coach_is_named_not_merely_counted(sealed):
    offenders = [f for f in _audit(sealed) if f.kind == gate.COACH_NOT_OPERATIONAL]
    assert [f.where for f in offenders] == ["coaches.training_coach"]
    assert "retired" in offenders[0].detail and "Dr. Sarah Chen" in offenders[0].detail


def test_the_mismatched_byline_names_both_spellings(sealed):
    offenders = [f for f in _audit(sealed) if f.kind == gate.COACH_NAME_MISMATCH]
    assert [f.where for f in offenders] == ["coaches.physical_coach"]
    assert "Dr. Victor Reyes" in offenders[0].detail and "Dr. Max Reyes" in offenders[0].detail


# ── negative control ─────────────────────────────────────────────────────────


def test_the_repaired_seal_passes_the_gate(sealed):
    assert _audit(_repaired(sealed)) == []


@pytest.mark.parametrize(
    "clause,break_it",
    [
        (
            gate.COACH_NOT_OPERATIONAL,
            lambda a: a["coaches"].__setitem__("training_coach", {"coach_name": "Dr. Sarah Chen", "predictions": []}),
        ),
        (gate.COACH_NAME_MISMATCH, lambda a: a["coaches"]["sleep_coach"].__setitem__("coach_name", "Dr. Lisa Parke")),
        (
            gate.BASELINE_MISMATCH,
            lambda a: a["hypotheses"][0].__setitem__("evidence", "Pre-registered from a 300.0 lb start weight."),
        ),
        (gate.MIN_EFFECT_UNDERIVED, lambda a: a["hypotheses"][0]["test_spec"].pop("min_effect_derivation")),
    ],
)
def test_each_clause_fires_alone_against_the_repaired_seal(sealed, clause, break_it):
    """Re-break ONE clause on the clean copy. Exactly that clause must fire — a clause
    that only ever reports alongside another has never been separately observed."""
    artifact = _repaired(sealed)
    assert _audit(artifact) == []
    break_it(artifact)
    assert gate.summarize(_audit(artifact)) == {clause: 1}


def test_a_seat_swap_of_two_live_bylines_is_caught_here_and_not_by_the_freeze_check(sealed):
    """The seeder's #3520 `assert_cast_is_operational` compares NAMES against the set of
    live operational names, so swapping two real coaches between two real seats passes
    it. The pairing is what this gate adds."""
    seeder_check = importlib.import_module("seed_genesis_preregistration").assert_cast_is_operational
    artifact = _repaired(sealed)
    people, _ = gate.repo_coach_bylines()
    artifact["coaches"]["sleep_coach"]["coach_name"] = people["mind_coach"]
    artifact["coaches"]["mind_coach"]["coach_name"] = people["sleep_coach"]

    seeder_check(artifact["coaches"])  # passes: both bylines are live operational names

    assert gate.summarize(_audit(artifact)) == {gate.COACH_NAME_MISMATCH: 2}


# ── the baseline clause: non-vacuity, discrimination, precision ───────────────


def test_the_baseline_clause_is_not_vacuous_on_the_real_specimen(sealed):
    """An artifact that asserts no start weight produces no BASELINE finding — correct,
    and a clause that could quietly have nothing to check. The live specimen asserts
    three, all of them the superseded number."""
    claims = gate.asserted_baselines(sealed)
    assert len(claims) == 3
    assert {c.literal for c in claims} == {"326.2"}
    assert {c.where for c in claims} == {
        "coaches.nutrition_coach.predictions[0].claim_natural",
        "coaches.physical_coach.predictions[0].claim_natural",
        "hypotheses[0].evidence",
    }


def test_a_weight_figure_with_no_start_anchor_is_not_a_baseline_claim(sealed):
    """The sealed bytes contain FOUR `326.2 lb` figures; only three sit next to a
    start-of-experiment word. The fourth ("relative to a 326.2-lb individual's
    maintenance needs") is a restatement, not a baseline assertion. If the anchor rule
    stopped discriminating, this count would be 4."""
    assert json.dumps(sealed).count("326.2") == 4
    assert len(gate.asserted_baselines(sealed)) == 3


def test_a_goal_weight_is_not_read_as_a_baseline():
    artifact = {"coaches": {}, "hypotheses": [], "note": "Goal weight is 185 lbs; the target is 185 pounds by June."}
    assert gate.asserted_baselines(artifact) == []


@pytest.mark.parametrize(
    "stated,agrees",
    [("327.34", True), ("327.3", True), ("327", True), ("326.2", False), ("327.4", False), ("328", False)],
)
def test_agreement_is_judged_at_the_precision_the_artifact_states(stated, agrees):
    """A claim is held to the precision it commits to. "327.3 lbs" is a correct
    rounding of 327.34 and must not red; "326.2 lbs" is a different number."""
    artifact = {"coaches": {}, "hypotheses": [], "note": f"Starting weight {stated} lbs."}
    findings = _audit(artifact, baseline_lbs=327.34)
    assert (findings == []) is agrees


def test_an_explicit_baseline_field_wins_over_prose():
    """Prose is the fallback for the shape that exists today. When a future artifact
    states the baseline structurally, that is the claim — and a WRONG field is not
    excused by correct prose."""
    artifact = {"coaches": {}, "hypotheses": [], "baseline_weight_lbs": 300.0, "note": "Starting weight 327.34 lbs."}
    assert gate.summarize(_audit(artifact, baseline_lbs=327.34)) == {gate.BASELINE_MISMATCH: 1}
    assert gate.asserted_baselines(artifact)[0].where == "baseline_weight_lbs"


# ── the min_effect clause ────────────────────────────────────────────────────


def test_the_shipped_3552_spelling_window_days_satisfies_the_window_field():
    """#3599 writes `window`; `prereg_effect.derive_min_effect` emits `window_days`.
    Requiring the issue's literal spelling would red the very shape #3552 shipped."""
    spec = {"min_effect": 0.7, "min_effect_derivation": {"metric": "weight_lbs", "sd": 1.4, "n": 21, "window_days": 90}}
    assert gate.missing_derivation_fields(spec) is None


def test_prereg_effects_own_return_shape_satisfies_the_clause():
    """Built by the shipped function, not by hand — the gate and the deriver cannot
    disagree about what a complete derivation looks like."""
    from experiment import prereg_effect

    derived = prereg_effect.derive_min_effect([326.0 + i * 0.3 - (i % 3) * 0.7 for i in range(30)], metric="weight_lbs", unit="lbs")
    assert derived is not None
    assert gate.missing_derivation_fields({"min_effect": derived["min_effect"], "derived_from": derived["derived_from"]}) is None


@pytest.mark.parametrize(
    "block,absent",
    [
        ({"metric": "w", "sd": 1.4, "n": 21, "window_days": None}, ["window"]),
        ({"metric": "w", "sd": None, "n": 21, "window_days": 90}, ["sd"]),
        ({"metric": "", "sd": 1.4, "n": 21, "window_days": 90}, ["metric"]),
        ({"sd": 1.4, "n": 21, "window_days": 90}, ["metric"]),
    ],
)
def test_a_null_derivation_field_is_the_same_defect_as_an_absent_one(block, absent):
    """`"sd": null` states the bar came from a variance nobody measured just as loudly
    as a missing key. A gate that read `in` would pass all four of these."""
    assert gate.missing_derivation_fields({"min_effect": 0.7, "min_effect_derivation": block}) == absent


def test_a_bare_literal_bar_reports_all_four_fields(sealed):
    spec = sealed["hypotheses"][0]["test_spec"]
    assert spec["min_effect"] == 0.1 and "min_effect_derivation" not in spec
    assert gate.missing_derivation_fields(spec) == ["metric", "sd", "n", "window"]


# ── the gate derives; it does not restate ────────────────────────────────────


def test_the_coach_clause_reads_the_registry_not_a_hand_list(sealed):
    """Hand the audit a registry in which training_coach IS operational and its finding
    must vanish. A hand-copied roster would keep reporting it — which is the R2 defect
    (#3520) reproduced inside the gate meant to catch it."""
    people, retired = gate.repo_coach_bylines()
    widened = dict(people, training_coach="Dr. Sarah Chen")
    assert gate.summarize(_audit(sealed, coach_bylines=widened)) == {
        gate.COACH_NAME_MISMATCH: 1,
        gate.BASELINE_MISMATCH: 3,
        gate.MIN_EFFECT_UNDERIVED: 2,
    }
    assert retired == ("training_coach",)


def test_the_baseline_clause_reads_the_constant_not_a_hand_number(sealed):
    assert gate.BASELINE_MISMATCH not in gate.summarize(_audit(sealed, baseline_lbs=326.2))


def test_an_id_absent_from_the_registry_is_refused_even_when_not_on_the_retirement_list():
    """A coach retired WITHOUT anyone recording it must still be refused — membership of
    the operational set is the test, the retirement list only enriches the message."""
    artifact = {"coaches": {"ghost_coach": {"coach_name": "Dr. Nobody"}}, "hypotheses": []}
    findings = _audit(artifact, retired_ids=())
    assert gate.summarize(findings) == {gate.COACH_NOT_OPERATIONAL: 1}
    assert "not in the operational persona set" in findings[0].detail


def test_an_empty_registry_raises_rather_than_vouching_for_nothing(monkeypatch):
    """Zero operational coaches means every id is "not operational" AND the byline check
    is inert — a verdict either way would be meaningless, so it refuses."""
    monkeypatch.setattr(gate, "repo_coach_bylines", lambda: ({}, ()))
    with pytest.raises(RuntimeError):
        gate.audit_frozen(artifact={"coaches": {}, "hypotheses": []})


def test_a_shapeless_artifact_raises_rather_than_sealing_nothing(tmp_path):
    bad = tmp_path / "not_a_prereg.json"
    bad.write_text(json.dumps({"hello": "world"}))
    with pytest.raises(ValueError):
        gate.load_frozen(bad)


# ── the wiring: write_stamp() is the seal, so that is where it binds ──────────


def _stamp_module(tmp_path, monkeypatch, artifact: dict):
    gps = importlib.import_module("genesis_prereg_stamp")
    frozen_p = tmp_path / "genesis_preregistration.json"
    frozen_p.write_text(json.dumps(artifact, indent=2) + "\n")
    monkeypatch.setattr(gps, "FROZEN_PATH", frozen_p)
    monkeypatch.setattr(gps, "STAMP_PATH", tmp_path / "genesis_preregistration.sha256.json")
    return gps, frozen_p


#: A freeze moment in the past — write_stamp never backdates, so the stamping instant
#: handed to it below must follow the artifact's own generated_at.
_TEST_GENESIS = "2026-09-13"
_TEST_FROZEN_AT = "2026-09-12T20:00:00+00:00"
_TEST_STAMPED_AT = datetime(2026, 9, 12, 20, 5, tzinfo=timezone.utc)


def test_write_stamp_refuses_to_mint_a_seal_over_the_cycle17_artifact(tmp_path, monkeypatch, sealed):
    """The whole box, end to end: the real seeded artifact, offered to the real seal
    chokepoint, is refused — and no stamp file is left behind."""
    artifact = dict(sealed, genesis=_TEST_GENESIS, generated_at=_TEST_FROZEN_AT)
    gps, _ = _stamp_module(tmp_path, monkeypatch, artifact)
    with pytest.raises(SystemExit) as excinfo:
        gps.write_stamp(now=_TEST_STAMPED_AT)
    assert "#3599" in str(excinfo.value) and "training_coach" in str(excinfo.value)
    assert not gps.STAMP_PATH.exists(), "a refused seal must leave no stamp"


def test_write_stamp_mints_a_seal_over_the_repaired_artifact(tmp_path, monkeypatch, sealed):
    artifact = dict(_repaired(sealed), genesis=_TEST_GENESIS, generated_at=_TEST_FROZEN_AT)
    gps, _ = _stamp_module(tmp_path, monkeypatch, artifact)
    stamp = gps.write_stamp(now=_TEST_STAMPED_AT)
    assert stamp["genesis"] == _TEST_GENESIS and gps.STAMP_PATH.exists()


def test_an_already_published_seal_is_never_re_vouched(tmp_path, monkeypatch, sealed):
    """#3552's lesson: a published pre-registration is amended in public, never edited.
    So the gate binds seals it MINTS — re-running the stamp over an existing, unchanged
    seal returns it untouched rather than refusing it into a rewrite. Simulated by
    stamping once with the gate lifted, then running the real gated path over the
    stamp that already exists."""
    artifact = dict(sealed, genesis=_TEST_GENESIS, generated_at=_TEST_FROZEN_AT)
    gps, _ = _stamp_module(tmp_path, monkeypatch, artifact)
    monkeypatch.setattr(gps, "_refuse_untrue_seal", lambda frozen: None)
    first = gps.write_stamp(now=_TEST_STAMPED_AT)
    monkeypatch.undo()

    gps, _ = _stamp_module(tmp_path, monkeypatch, artifact)
    again = gps.write_stamp(now=datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc))
    assert again["stamped_at"] == first["stamped_at"]


# ── the current frozen artifact: a ratchet in both directions ─────────────────


def test_the_current_frozen_artifact_is_the_cycle17_seal_or_else_is_clean():
    """Branch A (today): the frozen file IS the published cycle-17 seal, and its verdict
    must be exactly the recorded one — a silent edit to a sealed artifact reds here.
    Branch B (the next reset): a NEW freeze has landed, and it must pass the gate. That
    is the contract this issue ships — a dirty freeze must not reach the seal step."""
    current = json.loads(FROZEN_PATH.read_text())
    if _sha256(FROZEN_PATH) == CYCLE17_SEAL_SHA256:
        assert gate.summarize(_audit(current)) == CYCLE17_VERDICT
        return
    findings = _audit(current)
    assert (
        findings == []
    ), "a new frozen pre-registration must agree with the platform's own facts BEFORE it is sealed:\n  - " + "\n  - ".join(
        str(f) for f in findings
    )


# ── mutation controls (real files on disk, md5-asserted) ─────────────────────


def test_mutation_control_retiring_a_live_coach_in_a_real_artifact_reds_the_gate(tmp_path, sealed):
    """Rename `sleep_coach` to a seat the registry does not have, in a COPY of the
    committed fixture on disk. The gate must report a NEW not-operational finding. If
    the count does not move, the gate is not reading the file it claims to read."""
    work = tmp_path / "prereg.json"
    work.write_bytes(FIXTURE_PATH.read_bytes())
    before = _md5(work)
    assert gate.summarize(gate.audit_frozen(work))[gate.COACH_NOT_OPERATIONAL] == 1

    mutated = json.loads(work.read_text())
    mutated["coaches"]["dream_coach"] = mutated["coaches"].pop("sleep_coach")
    work.write_text(json.dumps(mutated, indent=2) + "\n")
    after = _md5(work)
    assert after != before, "the mutation did not change the file — refusing to read a no-op verdict"

    assert gate.summarize(gate.audit_frozen(work))[gate.COACH_NOT_OPERATIONAL] == 2

    work.write_bytes(FIXTURE_PATH.read_bytes())
    assert _md5(work) == before
    assert gate.summarize(gate.audit_frozen(work))[gate.COACH_NOT_OPERATIONAL] == 1


def test_mutation_control_repairing_the_baseline_in_a_real_artifact_greens_the_clause(tmp_path):
    """The other direction, which is the one a decorative gate fails: correcting the
    superseded weight in a real file on disk must make the BASELINE findings GO AWAY.
    A clause that reports three findings over any input is not measuring anything."""
    work = tmp_path / "prereg.json"
    work.write_bytes(FIXTURE_PATH.read_bytes())
    before = _md5(work)
    assert gate.summarize(gate.audit_frozen(work))[gate.BASELINE_MISMATCH] == 3

    baseline = gate.repo_baseline_lbs()
    work.write_text(work.read_text().replace("326.2", f"{baseline:g}"))
    after = _md5(work)
    assert after != before, "the mutation did not change the file — refusing to read a no-op verdict"

    assert gate.BASELINE_MISMATCH not in gate.summarize(gate.audit_frozen(work))

    work.write_bytes(FIXTURE_PATH.read_bytes())
    assert _md5(work) == before
    assert gate.summarize(gate.audit_frozen(work))[gate.BASELINE_MISMATCH] == 3
