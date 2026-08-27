"""tests/test_gate_census_mutations_2999.py — the guard on #2999's mutation harness.

`scripts/gate_census_mutations.py` generates census family 5's can-it-fail verdicts by
planting a defect, watching the target red, and reverting. That makes the verdicts
re-derivable instead of recorded-once, which is the whole point — and it also makes the
HARNESS the thing that can now silently stop working. A `run_spec` that returned "ARMED"
unconditionally would mint fifteen verdicts a run and prove nothing, which is the exact
instrument-shaped failure epic #2578 exists to hunt. So the decision function is
mutation-proved here over all four of its outcomes, on canned exit codes, with no pytest
subprocess involved.

Deliberately NOT a tree-sweeping file (no os.walk / rglob / git-listing idiom in its own
text and no sweeping tests/ helper imported), so it mints no census gate of its own and
needs no `_PREMERGE_EXTRA_FILES` ruling — see tests/test_premerge_extra_files_derivation_2372.py
for why that classification is load-bearing.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import gate_census  # noqa: E402
import gate_census_mutations as gcm  # noqa: E402
import gate_census_precision as gcp  # noqa: E402
import gate_census_report as gcr  # noqa: E402

_PROOF_FIELDS = {"gate_name", "command", "mutation", "observed", "scope", "proved_on"}


# ══════════════════════════════════════════════════════════════════════════════
# The registry and the verdicts stay in lockstep
# ══════════════════════════════════════════════════════════════════════════════


def test_every_spec_is_keyed_by_its_own_gate_id():
    """A spec filed under a different key than it names would run one gate's mutation
    and record another gate's verdict."""
    mismatched = [k for k, spec in gcm.MUTATION_SPECS.items() if spec.gate_id != k]
    assert not mismatched, f"spec key != spec.gate_id for {mismatched}"


def test_the_proof_set_and_the_spec_set_are_the_same_set():
    """A proof with no spec cannot be re-derived; a spec with no proof is a mutation
    nobody recorded the outcome of. Either way the pair has stopped meaning what it says."""
    proofs, specs = set(gcm.STRUCTURAL_PROOFS), set(gcm.MUTATION_SPECS)
    assert proofs == specs, (
        f"proofs without a spec: {sorted(proofs - specs)}; specs without a proof: {sorted(specs - proofs)} — "
        "every verdict in this module must be re-runnable by `gate_census_mutations.py --run`"
    )


def test_every_proof_carries_the_full_record():
    for gid, proof in gcm.STRUCTURAL_PROOFS.items():
        assert set(proof) == _PROOF_FIELDS, f"{gid}: field set {sorted(proof)} != gate_census.Proof's {sorted(_PROOF_FIELDS)}"
        empty = sorted(k for k, v in proof.items() if not str(v).strip())
        assert not empty, f"{gid}: empty proof field(s) {empty} — `scope` may be a stated 'no narrowing', never blank"
        gate_census.Proof(**proof)  # the constructor is the contract; a renamed field fails here


def test_every_observed_records_all_three_legs_of_the_control():
    """A RED with no GREEN on either side attributes nothing. The transcript must show
    the baseline, the mutated run, and the reverted run — the harness's own control."""
    for gid, proof in gcm.STRUCTURAL_PROOFS.items():
        observed = proof["observed"]
        for leg in ("baseline:", "mutated:", "reverted:"):
            assert leg in observed, f"{gid}: `observed` has no `{leg}` leg — {observed!r}"
        assert "failed" in observed, f"{gid}: `observed` records no failing run, so nothing was watched failing"


def test_every_proof_names_a_gate_the_census_can_actually_see():
    """#3129's orphan-proof problem: a verdict recorded against an id the inventory does
    not emit is invisible, and it inflates nothing while looking like progress."""
    census = gate_census.build_census()
    assert not census["orphan_proofs"], f"proofs attached to no live gate id: {census['orphan_proofs']}"
    live = {g["id"] for g in census["gates"]}
    missing = sorted(gid for gid in gcm.STRUCTURAL_PROOFS if gid not in live)
    assert not missing, f"{missing} are recorded as proven but are not in the census inventory"


def test_the_verdicts_reach_the_census_rather_than_only_this_module():
    """The import wiring in gate_census.py is what turns these dicts into verdicts."""
    for gid in gcm.STRUCTURAL_PROOFS:
        assert gid in gate_census.PROVEN_CAN_FAIL, f"{gid} is recorded here but never reaches gate_census.PROVEN_CAN_FAIL"


# ══════════════════════════════════════════════════════════════════════════════
# The measured blind spots
# ══════════════════════════════════════════════════════════════════════════════


def test_every_dark_control_sits_beside_the_armed_proof_for_the_same_gate():
    """A DARK result on its own is a broken plant, not a finding. It only means something
    next to a plant that DID red the same gate — that pairing is what turns "it did not
    fail" into "it cannot fail for this shape"."""
    assert gcm.DARK_CONTROLS, "the blind-spot set is empty — a measured DARK was recorded and then dropped"
    for key, spec in gcm.DARK_CONTROLS.items():
        assert spec.gate_id in gcm.STRUCTURAL_PROOFS, f"{key} names {spec.gate_id}, which has no ARMED proof to contrast it with"
        assert len(spec.detects) > 80, f"{key}: a blind spot needs the shape written out, not a label"


def test_the_recorded_blind_spot_is_named_in_the_gates_scope():
    """The scope field is what a census reader sees. A blind spot measured and then left
    out of the verdict is the green-board illusion in a new file."""
    for spec in gcm.DARK_CONTROLS.values():
        scope = gcm.STRUCTURAL_PROOFS[spec.gate_id]["scope"]
        assert "BLIND SPOT" in scope.upper(), f"{spec.gate_id}: a DARK control exists but its scope does not say so"


# ══════════════════════════════════════════════════════════════════════════════
# The harness itself — mutation-proved on its own decision function
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _spec():
    return gcm.MutationSpec(
        gate_id="structural::_synthetic_2999.py",
        target="tests/_synthetic_2999.py",
        detects="synthetic",
        plants=(("_never_written_2999.txt", "x"),),
        track=False,
    )


def _canned(monkeypatch, codes):
    """Drive run_spec with fixed exit codes and neuter its filesystem side effects."""
    seq = iter(codes)
    monkeypatch.setattr(gcm, "_pytest", lambda *a, **k: (next(seq), "canned"))
    monkeypatch.setattr(gcm, "_apply", lambda spec: None)
    monkeypatch.setattr(gcm, "_revert", lambda spec: None)
    monkeypatch.setattr(gcm, "_dirty", lambda spec: [])


@pytest.mark.parametrize(
    "codes,expected",
    [
        ((0, 1, 0), "ARMED"),  # green -> red -> green: the only shape that is a verdict
        ((0, 0, 0), "DARK"),  # the plant never redded the target
        ((1, 1, 1), "INDETERMINATE"),  # already red before the plant — attributes nothing
        ((0, 1, 1), "INDETERMINATE"),  # never recovered, so the red is not the plant's
    ],
)
def test_run_spec_reports_each_outcome_and_not_only_armed(monkeypatch, _spec, codes, expected):
    """THE control on the control. If this only ever returned ARMED, every verdict in
    this module would be a green tick with nothing behind it — the #2578 defect class,
    committed by the instrument built to measure it."""
    _canned(monkeypatch, codes)
    assert gcm.run_spec(_spec)["verdict"] == expected


def test_run_spec_refuses_to_run_over_an_existing_path(monkeypatch, _spec):
    """A leaked plant from an earlier run would make the next spec's baseline meaningless.
    The precondition is a refusal, never a silent overwrite."""
    monkeypatch.setattr(gcm, "_dirty", lambda spec: ["_never_written_2999.txt"])
    result = gcm.run_spec(_spec)
    assert result["verdict"] == "SKIPPED" and "already present" in result["reason"]


def test_no_plant_path_is_present_in_the_tree_right_now():
    """Every spec's plant must be absent between runs — a committed plant is both a
    leaked mutation and a permanently red gate."""
    leaked = []
    for spec in list(gcm.MUTATION_SPECS.values()) + list(gcm.DARK_CONTROLS.values()):
        for rel, _body in spec.plants:
            if os.path.exists(os.path.join(_REPO, rel)):
                leaked.append(rel)
    assert not leaked, f"planted mutation file(s) left in the tree: {sorted(set(leaked))}"


def test_the_runner_exits_non_zero_when_a_gate_goes_dark(monkeypatch, _spec):
    """A harness that always exits 0 reports success for a gate it just watched not fail."""
    monkeypatch.setattr(gcm, "MUTATION_SPECS", {_spec.gate_id: _spec})
    monkeypatch.setattr(gcm, "DARK_CONTROLS", {})
    _canned(monkeypatch, (0, 0, 0))
    assert gcm.main(["--run"]) == 1
    _canned(monkeypatch, (0, 1, 0))
    assert gcm.main(["--run"]) == 0


# ══════════════════════════════════════════════════════════════════════════════
# The re-sampled flag precision (#2999 box 2)
# ══════════════════════════════════════════════════════════════════════════════


def test_each_precision_sample_is_internally_coherent():
    for flag, s in gcp.FLAG_PRECISION.items():
        assert s.n_fp + s.n_tp == s.n_sampled, f"{flag}: {s.n_fp} FP + {s.n_tp} TP != {s.n_sampled} sampled"
        assert 0 < s.n_sampled <= s.n_flagged, f"{flag}: sampled {s.n_sampled} of a population of {s.n_flagged}"
        assert s.method.strip() and len(s.sampled_on) == 10, f"{flag}: method/date incomplete"


def test_every_sampled_flag_is_one_the_detector_can_still_emit():
    """A precision sample for a retired flag is a confident number about nothing."""
    emitted = set()
    for probe in (
        "import ast\nast.Assign\nx = []\n",
        "assert not violations\n",
        "if not rows:\n    continue\n",
        "except Exception:\n    pass\n",
    ):
        emitted |= set(gate_census._static_source_flags(probe))
    unknown = sorted(set(gcp.FLAG_PRECISION) - emitted)
    assert not unknown, f"FLAG_PRECISION samples flag(s) `_static_source_flags` no longer produces: {unknown}"


def test_the_prior_draw_is_kept_for_every_resampled_flag():
    """Box 2 asks for a LIVE interval. Keeping the superseded draw is what lets a reader
    see whether the estimate moved, instead of only where it now is."""
    assert set(gcp.PRIOR_FLAG_PRECISION) == set(gcp.FLAG_PRECISION)
    for flag, prior in gcp.PRIOR_FLAG_PRECISION.items():
        assert prior.sampled_on < gcp.FLAG_PRECISION[flag].sampled_on, f"{flag}: the 'prior' draw is not older than the current one"
        assert prior.n_flagged < gcp.FLAG_PRECISION[flag].n_flagged, f"{flag}: population did not grow — is the prior entry actually prior?"


# ══════════════════════════════════════════════════════════════════════════════
# The report prints the fraction (#2999 boxes 1 and 4)
# ══════════════════════════════════════════════════════════════════════════════


def _synthetic_census(n_proven: int, n_total: int) -> dict:
    gates = [
        {
            "id": f"g{i}",
            "family": "structural-test",
            "name": f"g{i}",
            "source": "tests/x.py",
            "screened": True,
            "risk_flags": [],
            "detail": {},
            "unscreened_reason": "",
            "evidence": "",
            "verdict": ("can-fail (proven)" if i < n_proven else "unproven"),
        }
        for i in range(n_total)
    ]
    return {
        "gates": gates,
        "counters": {"ci": {"steps_nongate": 1, "by_enforcement_only": 1, "by_verb_only": 1, "by_both": 1}},
        "shapes": {},
        "attempted_unproven": {},
        "orphan_proofs": [],
        "unattached_attempts": [],
        "name_only_candidates": [],
        "families_skipped": [],
        "families_run": ["structural"],
        "families_dropped": [],
        "annassign_exposure": {
            "n_blind_walkers": 0,
            "n_annotated_module_constants": 0,
            "blind_walkers": [],
            "annotated_module_constants": [],
        },
    }


def test_the_report_prints_the_verdict_fraction_with_its_denominator():
    out = gcr.render_report(_synthetic_census(3, 12))
    assert "VERDICT FRACTION" in out
    assert "3/12 proven (25.0%)" in out, "the fraction must carry its own n — a bare count is what read as progress for four months"


def test_the_fraction_line_tracks_the_census_rather_than_a_constant():
    """Mutation proof on the renderer: change the census, the printed fraction must move."""
    a = gcr.render_report(_synthetic_census(3, 12))
    b = gcr.render_report(_synthetic_census(6, 12))
    assert "3/12 proven" in a and "3/12 proven" not in b
    assert "6/12 proven (50.0%)" in b


def test_the_error_bar_section_prints_the_prior_draw():
    out = gcp._render_error_bars(_synthetic_census(1, 4))
    for flag, prior in gcp.PRIOR_FLAG_PRECISION.items():
        assert f"prior draw {prior.sampled_on}" in out, f"{flag}: the superseded interval is not printed"
