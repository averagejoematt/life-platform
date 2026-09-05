"""tests/test_gate_census_2578.py — the census must not inherit the blindness it counts.

`scripts/gate_census.py` derives the armed-gate inventory from source (#2578 slice 1).
Every detector in it is a derivation, and every derivation in this repo has the same
failure mode: it returns an empty population and the assertion that reads it passes
vacuously. Taxonomy instance 5 is exactly that — one annotation on `SOURCE_REGISTRY`
silently disarmed three AST-walking gates, and one of the three was a test's
*deliberately independent* cross-check that had copied the same walk, so both sides
agreed on `None` and read green.

So this file does two separable things:

1. **Mutation proofs against a SYNTHETIC tree.** Each detector is shown flagging a
   planted positive and not flagging its negative control. A synthetic root (rather
   than the repo) is what makes these proofs stable — a repo-derived assertion can only
   ever say "the number did not change," which is the vacuous-empty shape again.

2. **A population floor on the REAL sweep.** The census over this repo must find gates
   in every family it claims to cover. If any family returns zero, the derivation has
   gone blind and this test says so by name — the floor is the thing that would have
   caught the AnnAssign instance.

The floors are deliberately far below the measured values (see each assertion). They
are blindness detectors, not ratchets: a legitimate refactor that removes gates must
not red main, but a derivation returning `[]` must.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# `gate_census.py` imports its own #1665 extraction siblings (gate_census_precision,
# _structural, _sentinel, _proofs) by bare module name, so scripts/ must be importable
# BEFORE exec_module. In a full-suite run some earlier test file happens to have put it
# there already — which made this module silently un-runnable in isolation (`pytest
# tests/test_gate_census_2578.py` alone errored at collection). Made explicit here so a
# `-k` rerun of the census tests works on its own.
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location("gate_census", REPO_ROOT / "scripts" / "gate_census.py")
assert _SPEC and _SPEC.loader
gc = importlib.util.module_from_spec(_SPEC)
sys.modules["gate_census"] = gc
_SPEC.loader.exec_module(gc)

import gate_census_enforcement as gce  # noqa: E402  — the #3220/#3329 extraction sibling, same address as the census's own import


# ── 1. the AnnAssign proof — taxonomy instance 5, made a mutation ────────────
class TestModuleLevelBindingsSeesAnnotations:
    """`X = {...}` and `X: T = {...}` must both be found.

    The mutation is the annotation itself: the same registry, one type hint added.
    A walker that only handles `ast.Assign` passes the first case and returns an empty
    set for the second — which is how three gates went dark at once on 2026-08-13.
    """

    PLAIN = "REGISTRY = {'a': 1, 'b': 2}\n"
    ANNOTATED = "REGISTRY: dict[str, int] = {'a': 1, 'b': 2}\n"

    def _names(self, src: str) -> set[str]:
        return {name for name, _value, _line in gc._module_level_bindings(ast.parse(src))}

    def test_plain_assignment_is_found(self):
        assert self._names(self.PLAIN) == {"REGISTRY"}

    def test_annotated_assignment_is_found(self):
        """THE proof. Pre-fix (ast.Assign only) this returns set() and every gate
        downstream of it reports a clean, empty, passing result."""
        assert self._names(self.ANNOTATED) == {"REGISTRY"}

    def test_annotated_registry_entries_are_enumerable(self):
        """End to end: the annotation must not cost us the entries either."""
        bindings = dict((n, v) for n, v, _ in gc._module_level_bindings(ast.parse(self.ANNOTATED)))
        assert gc._literal_entries(bindings["REGISTRY"]) == ["a", "b"]

    def test_bare_annotation_without_value_does_not_crash(self):
        """`X: dict[str, int]` with no value is legal and must not explode the sweep."""
        names = self._names("REGISTRY: dict[str, int]\n")
        assert names == {"REGISTRY"}


# ── 2. the entry extractor ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "src,expected",
    [
        ("X = {'a': 1}", ["a"]),
        ("X = {'a', 'b'}", ["a", "b"]),
        ("X = ['a']", ["a"]),
        ("X = ('a',)", ["a"]),
        ("X = frozenset({'a', 'b'})", ["a", "b"]),
        ("X: frozenset[str] = frozenset({'a'})", ["a"]),
    ],
)
def test_literal_entries_covers_every_registry_spelling(src, expected):
    value = gc._module_level_bindings(ast.parse(src))[0][1]
    assert sorted(gc._literal_entries(value) or []) == sorted(expected)


def test_non_literal_registry_is_reported_not_silently_empty():
    """A comprehension-built registry must return None (-> 'could not be screened'),
    never `[]`. `[]` would read as 'this registry has no entries' — a clean pass over
    a gate the census never actually looked at."""
    value = gc._module_level_bindings(ast.parse("X = {k: 1 for k in names}"))[0][1]
    assert gc._literal_entries(value) is None


# ── 3. the source-text detectors, each with a negative control ───────────────
class TestStaticSourceFlags:
    def test_ast_walk_without_annassign_is_flagged(self):
        assert "vacuous-empty" in gc._static_source_flags("for n in ast.walk(t):\n    isinstance(n, ast.Assign)\n")

    def test_ast_walk_handling_both_is_clean(self):
        """The negative control. Without this, the detector could be flagging every
        file and the census would still 'work'."""
        src = "isinstance(n, ast.Assign)\nisinstance(n, ast.AnnAssign)\n"
        assert "vacuous-empty" not in gc._static_source_flags(src)

    def test_emptiness_assertion_without_a_population_floor_is_flagged(self):
        assert "vacuous-empty" in gc._static_source_flags("assert not offenders\n")

    def test_emptiness_assertion_with_a_floor_is_clean(self):
        src = "assert len(found) >= 9, 'the derivation has gone blind'\nassert not offenders\n"
        assert "vacuous-empty" not in gc._static_source_flags(src)

    def test_skip_on_absence_is_flagged(self):
        """#2619: the only way to be exempt was to be incomplete."""
        assert "exempt-by-incompleteness" in gc._static_source_flags("for d in docs:\n    if not stamp:\n        continue\n")

    def test_discarded_exit_status_is_flagged(self):
        assert "swallowed-exit" in gc._static_source_flags("run_gate() || true\n")


# ── 3b. exemption data vs. behavioural registries ────────────────────────────
def _synthetic_repo(tmp_path: Path, rel: str, body: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


class TestExemptionDataIsNotJudgedAsWiring:
    """The first run of `declared-unwired` reported 39 hits, mostly a filename inside a
    size BASELINE — an entry that legitimately appears exactly once. Exemption data and
    behavioural registries fail differently and must be screened differently."""

    SRC = """
        BASELINE = {'lambdas/gone.py': 1200, 'scripts/reg.py': 900}
        GATE_CLASSES = {'orphan_class': {}}
        """

    def _gates(self, tmp_path):
        root = _synthetic_repo(tmp_path, "scripts/reg.py", self.SRC)
        files = [root / "scripts" / "reg.py"]
        gates, counters = gc.discover_registry_gates(root, files)
        return {g.name: g for g in gates}, counters

    def test_a_baseline_entry_is_not_called_unwired(self, tmp_path):
        gates, _ = self._gates(tmp_path)
        assert "declared-unwired" not in gates["BASELINE[scripts/reg.py]"].risk_flags

    def test_a_baseline_entry_whose_file_vanished_is_flagged_stale(self, tmp_path):
        """The planted positive that makes a census-wide `stale-exemption n = 0` mean
        something. Without this proof, zero is indistinguishable from a dead detector —
        which is the vacuous-empty shape, in the instrument built to find it."""
        gates, counters = self._gates(tmp_path)
        assert "stale-exemption" in gates["BASELINE[lambdas/gone.py]"].risk_flags
        assert counters["stale_exemptions"] == 1

    def test_an_existing_exempted_path_is_clean(self, tmp_path):
        gates, _ = self._gates(tmp_path)
        assert gates["BASELINE[scripts/reg.py]"].risk_flags == []

    def test_a_behavioural_registry_entry_nothing_references_is_flagged(self, tmp_path):
        """#2564's shape survives the narrowing."""
        gates, _ = self._gates(tmp_path)
        assert "declared-unwired" in gates["GATE_CLASSES[orphan_class]"].risk_flags


def test_a_guard_script_its_own_caller_imports_by_stem_is_not_called_unreferenced(tmp_path):
    """Two of the first three `unreferenced-entrypoint` hits were false: a python caller
    imports `check_css_tokens`, not `check_css_tokens.py`, and the corpus skipped
    `deploy/`. A caller-detector that does not read all the callers is the same defect
    this census exists to find."""
    root = _synthetic_repo(tmp_path, "scripts/check_thing.py", "import sys\nsys.exit(1)\n")
    _synthetic_repo(tmp_path, "deploy/runner.py", "from check_thing import main\n")
    _synthetic_repo(tmp_path, "scripts/check_lonely.py", "import sys\nsys.exit(1)\n")
    files = [root / "scripts" / "check_thing.py", root / "deploy" / "runner.py", root / "scripts" / "check_lonely.py"]
    gates = {g.name: g for g in gc.discover_guard_scripts(root, files)[0]}
    assert "unreferenced-entrypoint" not in gates["scripts/check_thing.py"].risk_flags
    assert "unreferenced-entrypoint" in gates["scripts/check_lonely.py"].risk_flags, "the detector no longer detects anything"


# ── 3c. the sentinel per-check family (#3129) ────────────────────────────────
# deploy/drift_sentinel.py's run_sweep() builds a `checks = {...}` dict that
# remediation/drift_report.py's as_signal() reads to route needs-human triage; each
# check_* function behind an entry is an armed gate none of the other five families
# ever walked. Mirrors Family 4's shape exactly: check_* naming finds candidates,
# "registered" means referenced beyond the def/import line, an unwired one is flagged
# `unreferenced-entrypoint` and still counted — never silently dropped.
def test_sentinel_extractor_flags_a_locally_defined_unwired_check(tmp_path):
    root = _synthetic_repo(
        tmp_path,
        "deploy/drift_sentinel.py",
        """
        def check_wired():
            return {"status": "clean"}


        def check_never_wired():
            return {"status": "clean"}


        def run_sweep():
            checks = {"wired": check_wired()}
            return checks
        """,
    )
    gates = {g.name: g for g in gc.discover_sentinel_gates(root)[0]}
    assert "unreferenced-entrypoint" not in gates["check_wired"].risk_flags
    assert "unreferenced-entrypoint" in gates["check_never_wired"].risk_flags, "an unwired check_* must still enter the census"


def test_sentinel_extractor_resolves_an_extracted_sibling_to_its_own_file(tmp_path):
    """The real per-check functions live in sentinel_github.py etc (#1665's split);
    the walker must resolve an imported check_* name back to the SIBLING's own
    file+line, not the drift_sentinel.py re-export line, while still judging
    'registered' against drift_sentinel's own checks dict — the thing
    remediation/drift_report.py actually reads."""
    _synthetic_repo(tmp_path, "deploy/sentinel_github.py", "def check_github_thing():\n    return {'status': 'clean'}\n")
    root = _synthetic_repo(
        tmp_path,
        "deploy/drift_sentinel.py",
        """
        from sentinel_github import check_github_thing


        def run_sweep():
            checks = {"github_thing": check_github_thing()}
            return checks
        """,
    )
    gates = {g.name: g for g in gc.discover_sentinel_gates(root)[0]}
    assert gates["check_github_thing"].source.startswith("deploy/sentinel_github.py")
    assert "unreferenced-entrypoint" not in gates["check_github_thing"].risk_flags


def test_sentinel_extractor_flags_an_imported_but_never_called_sibling_check(tmp_path):
    """The import-only half of the same shape: a sibling check_* pulled into the
    `from ... import (...)` list but never called anywhere in drift_sentinel.py's own
    checks dict — imported, never wired."""
    _synthetic_repo(tmp_path, "deploy/sentinel_cadence.py", "def check_cadence_thing():\n    return {'status': 'clean'}\n")
    root = _synthetic_repo(
        tmp_path,
        "deploy/drift_sentinel.py",
        """
        from sentinel_cadence import check_cadence_thing


        def run_sweep():
            return {}
        """,
    )
    gates = {g.name: g for g in gc.discover_sentinel_gates(root)[0]}
    assert "unreferenced-entrypoint" in gates["check_cadence_thing"].risk_flags


def test_sentinel_family_registers_the_named_can_it_fail_target(real_census):
    """The population floor lives in _FAMILY_FLOORS ('sentinel-check'); this checks the
    two names the issue is actually about: #3112's proof target must be registerable,
    and an extracted-sibling check_* (not just drift_sentinel.py's own defs) must
    resolve — a walker that only saw local defs would miss check_github_config."""
    names = {g["name"] for g in real_census["gates"] if g["family"] == "sentinel-check"}
    assert "check_codeql_alerts" in names, "#3112's can-it-fail proof target must be registerable"
    assert "check_github_config" in names, "an extracted-sibling check_* must resolve, not just drift_sentinel.py's own defs"


# ── 4. the CI extractor, against a synthetic workflow ────────────────────────
def _write_workflow(tmp_path: Path, body: str) -> Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "synthetic.yml").write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def test_ci_extractor_flags_a_piped_gate_and_spares_a_bare_one(tmp_path):
    """The memory-file incident 'a piped step exits with tail's status', as a mutation:
    the SAME gate command, once bare and once piped."""
    root = _write_workflow(
        tmp_path,
        """
        name: synthetic
        on: [push]
        jobs:
          j:
            runs-on: ubuntu-latest
            steps:
              - name: bare gate
                run: pytest tests/
              - name: piped gate
                run: pytest tests/ | tee out.txt
              - name: advisory gate
                continue-on-error: true
                run: pytest tests/
              - name: not a gate
                run: echo hello
        """,
    )
    gates, counters = gc.discover_ci_gates(root)
    by_name = {g.name.split(" / ")[-1]: g for g in gates}

    assert "not a gate" not in by_name, "a non-gate step entered the inventory"
    assert counters["steps_nongate"] == 1, "the dropped step must still be COUNTED, not silently skipped"
    assert by_name["bare gate"].risk_flags == []
    assert "swallowed-exit" in by_name["piped gate"].risk_flags
    assert "declared-advisory" in by_name["advisory gate"].risk_flags


def test_ci_extractor_counts_third_party_actions_as_unscreened_not_absent():
    """A `uses:` gate's logic is in someone else's repo. Reporting it as screened-and-clean
    would be the census asserting something it never looked at."""
    census = gc.build_census(families=("ci",))
    unscreened = [g for g in census["gates"] if not g["screened"]]
    assert unscreened, "no third-party gate reported unscreened — the extractor has gone blind"
    assert all(g["unscreened_reason"] for g in unscreened), "an unscreened gate with no stated reason is a silent skip"


# ── 5. the population floor on the REAL repo sweep ───────────────────────────
# Measured on 6cd30ebb8 (2026-08-13): ci-step 83, guard-script 61, qa-smoke-check 21,
# registry 196, structural-test 59 — 420 total. The floors below sit at roughly a third
# of measured. They are BLINDNESS detectors: a derivation returning [] reds; a refactor
# that legitimately deletes half the gates does not.
_FAMILY_FLOORS = {
    "ci-step": 20,
    "guard-script": 15,
    "qa-smoke-check": 5,
    "registry": 40,
    "structural-test": 20,
    # #3129: 15 measured 2026-08-24 (10 local check_* defs in drift_sentinel.py + 5
    # across the four #1665-extracted siblings). Floor set well below measured, same
    # blindness-detector shape as every other row here.
    "sentinel-check": 10,
}


@pytest.fixture(scope="module")
def real_census():
    return gc.build_census()


def test_every_family_finds_gates_in_this_repo(real_census):
    counts: dict[str, int] = {}
    for g in real_census["gates"]:
        counts[g["family"]] = counts.get(g["family"], 0) + 1
    blind = {fam: (counts.get(fam, 0), floor) for fam, floor in _FAMILY_FLOORS.items() if counts.get(fam, 0) < floor}
    assert not blind, f"family derivation(s) have gone blind (found, floor): {blind}"


def test_the_census_reports_its_own_unscreened_population(real_census):
    """ADR-104/105: the honest number includes what could not be measured. A census
    reporting 100% screened is either perfect or lying, and it is not perfect."""
    gates = real_census["gates"]
    unscreened = [g for g in gates if not g["screened"]]
    assert unscreened, "zero unscreened gates — shell gates and third-party actions exist, so this is a reporting bug"
    assert all(g["unscreened_reason"] for g in unscreened)


def test_undetectable_shapes_are_declared_rather_than_omitted(real_census):
    """#2573 (rubric scope) and #2590 (cross-gate falsehood) cannot be seen syntactically.
    Dropping them from the taxonomy would make this instrument the seventh instance of
    its own subject."""
    undetectable = [k for k, v in real_census["shapes"].items() if v["detectable"] == "no"]
    assert "rubric-scope-gap" in undetectable
    assert "cross-gate-falsehood" in undetectable


def test_annassign_exposure_is_a_real_measurement(real_census):
    """The product that makes instance 5 a class rather than an anecdote: N walkers that
    cannot see M annotated constants. Both populations must be non-empty for the number
    to mean anything; if either derivation breaks, the exposure silently reads zero."""
    exp = real_census["annassign_exposure"]
    assert exp["n_annotated_module_constants"] >= 10, "the annotated-constant walk found (almost) nothing — it has gone blind"
    assert exp["n_blind_walkers"] >= 1, "zero AST-Assign-only walkers found — implausible; the detector has gone blind"


def test_report_renders_with_n_on_every_coverage_line(real_census):
    text = gc.render_report(real_census)
    for required in ("gates found", "statically screened", "could NOT be screened", "verdict proven can-fail"):
        assert required in text, f"the coverage report dropped the '{required}' line"
    assert text.count("n = ") >= 10


# ── 4. slice 2: the verdict layer must not become a hand-list of claims ──────
#
# The whole point of `PROVEN_CAN_FAIL` is that it is NOT a table of assertions — each
# entry cites a mutation someone ran. Nothing in a test file can re-run a mutation
# against live CI, so these tests defend the two things that CAN rot without anyone
# noticing, both of which are instances of the epic's own taxonomy:
#
#   (a) a verdict silently attaching to the WRONG gate. A CI-step id is positional
#       (`ci::<wf>::<job>::<index>`), so inserting one step into ci-lint.yml slides
#       every later id. A stale proof re-attaching to whatever now sits at that index
#       is the cross-gate-falsehood shape (#2590) with a friendlier face — so the
#       collector refuses on a name mismatch, and that refusal is mutation-proved here.
#   (b) the record losing the field that makes it re-runnable. A verdict without a
#       command and an observed exit status is the reasoning this slice exists to
#       replace.


def test_every_recorded_proof_carries_a_rerunnable_record():
    """A proof must name the command, the mutation, what was observed, and when."""
    assert gc.PROVEN_CAN_FAIL, "PROVEN_CAN_FAIL is empty — slice 2 records verdicts"
    for gid, proof in gc.PROVEN_CAN_FAIL.items():
        assert isinstance(proof, gc.Proof), f"{gid}: verdicts are Proof records, not free prose"
        for fld in ("gate_name", "command", "mutation", "observed", "proved_on"):
            assert getattr(proof, fld).strip(), f"{gid}: proof field '{fld}' is empty — the record is not re-runnable"
        # An `observed` that never mentions an outcome is a claim, not an observation.
        assert any(tok in proof.observed.lower() for tok in ("exit", "failed", "fail")), f"{gid}: `observed` records no outcome"


def test_no_recorded_proof_is_stale_against_the_live_census(real_census):
    """The id a proof was recorded against must still be the gate it was recorded for.

    This is the assertion that would have caught a slice-1 id shift. It fires on BOTH
    halves: an id matching nothing, and an id matching a gate whose name has changed.
    """
    assert not real_census["orphan_proofs"], (
        "recorded verdict(s) no longer match the gate at their id — a positional CI-step "
        "id has shifted, or a gate was renamed. Re-run the mutation against the CURRENT "
        f"gate before re-pointing the proof:\n{real_census['orphan_proofs']}"
    )
    assert not real_census[
        "unattached_attempts"
    ], f"ATTEMPTED_UNPROVEN names gate id(s) the sweep no longer finds: {real_census['unattached_attempts']}"


def test_a_shifted_id_refuses_its_proof_rather_than_re_attaching(monkeypatch):
    """Mutation proof of the refusal itself — the planted positive for (a) above.

    Point a real gate id at a proof recorded under a DIFFERENT gate name and the
    collector must report it as stale, not silently stamp `can-fail (proven)` on it.
    """
    victim = "structural::test_lambdas_packaging_guard.py"
    forged = gc.Proof(
        gate_name="some other gate that used to live at this id",
        command="irrelevant",
        mutation="irrelevant",
        observed="exit 1",
        scope="",
        proved_on="2026-01-01",
    )
    monkeypatch.setattr(gc, "PROVEN_CAN_FAIL", {victim: forged})
    census = gc.build_census(families=("structural",))
    assert [o["id"] for o in census["orphan_proofs"]] == [victim]
    gate = next(g for g in census["gates"] if g["id"] == victim)
    assert gate["verdict"] == "unproven", "a name-mismatched proof was re-attached — the stale-proof guard is dark"


def test_the_verdict_counts_add_up_and_are_reported(real_census):
    """No silent caps and no silent EXCLUSIONS: proven + attempted + unproven +
    not-applicable must equal the population, and every number must appear in the human
    report.

    The fourth term arrived with #3329 (owner decision 2026-08-31, option B). Before it,
    the six name-only rows were held outside the total and the sum below was true of a
    denominator that had quietly dropped them — "570 gates, plus six we do not count".
    A partition that does not account for every row is the census committing its own
    subject, so the addition is asserted here rather than in the renderer's prose.
    """
    gates = real_census["gates"]
    proven = [g for g in gates if g["verdict"] == "can-fail (proven)"]
    attempted = [g for g in gates if g["verdict"] == "attempted-unproven"]
    unproven = [g for g in gates if g["verdict"] == "unproven"]
    not_applicable = [g for g in gates if g["verdict"] == "not-applicable"]
    assert len(proven) + len(attempted) + len(unproven) + len(not_applicable) == len(gates)
    assert not_applicable, "zero not-applicable rows — the third verdict has gone dark, or they are excluded again"
    # Upper band 40 → 41 on 2026-08-29: #3279 added sentinel::deploy/sentinel_events.py::
    # check_eventbridge_rules with both halves mutation-proved in tests/test_sentinel_events_3279.py.
    # This band catches BULK marking-proven-without-mutations; move it only with a new proof to cite.
    assert (
        # Upper bound raised 40 → 45 (2026-08-29, #3294): the 41st proof is
        # `structural::test_absence_coverage_3294.py`, mutation-backed via the
        # re-runnable harness (ARMED 1/1) — the bound exists to catch proofs that
        # stop being mutation-backed, and this one is. (#3279 adds the 42nd — the
        # sentinel events-client proof — still under the same bound.)
        # Upper bound raised 45 → 46 (2026-08-31, #3315): the 46th proof is
        # `structural::test_ci_dark_flag_sweep_3315.py` — mutation-backed via the same
        # re-runnable harness (`gate_census_mutations.py --run --gate
        # test_ci_dark_flag_sweep_3315.py`: ARMED 1/1, planted probe workflow carrying the
        # pre-#3315 fresh-eyes install line). The 45th was #3336's twin guard, landed via
        # PR #3338 the same night, also ARMED 1/1.
        # Upper bound raised 46 → 47 (2026-08-31, #2834): the 47th proof is
        # `guard::deploy/iam_additive_gate.py` — a two-direction mutation recorded in
        # gate_census_proofs.GUARD_PROOFS (six defects planted one at a time into a copy of
        # the committed synth slice → exit 1/1/1/1/2; clean baseline and revert exit 0; the
        # 2026-08-14 grant still ALLOW-ADDITIVE). Stacked on #3315's 46th.
        # Upper bound raised 47 → 48 (2026-08-31, #3324; rebased after #2834 took 47): the 48th proof is
        # `structural::test_api_schema_completeness.py` — mutation-backed via the same
        # re-runnable harness (`gate_census_mutations.py --run --gate
        # test_api_schema_completeness.py`: ARMED 1/1, planted a captured FIXTURE — a copy
        # of tests/api_schemas/api_vitals.json's real shape with one key hand-removed,
        # never the live site — proving the #3324 nullable-aware diff_shape() rule still
        # catches a genuine key removal).
        # Upper bound raised 48 -> 49 (2026-09-05, #3564): the 49th proof is
        # `qa::lambdas/operational/qa_check_subscriber_promise.py::check_subscriber_promise_cadence`
        # — and it needed no planted mutation, because its first run FAILED on the live
        # production /subscribe/, naming the stale "one email a week" claim against the
        # promise rendered from the senders' crons. Recorded in gate_census.PROVEN_CAN_FAIL
        # with the re-runnable command; the pass side and the contradiction case are
        # covered by tests/test_subscriber_cadence_promise_3564.py.
        3
        <= len(proven)
        <= 49
    ), f"proven verdicts n={len(proven)} — 0 means the layer is dark, a large number means it stopped being mutation-backed"
    assert attempted, "ATTEMPTED_UNPROVEN attached to no gate — the honest-failure record has gone dark"
    text = gc.render_report(real_census)
    assert "VERDICTS: proven able to fail" in text
    assert "ATTEMPTED and NOT proved" in text
    assert f"n = {len(proven)}" in text and f"n = {len(attempted)}" in text
    assert f"NOT-APPLICABLE (nothing to fail, reason recorded)   n = {len(not_applicable)}" in text
    assert "excluded from the total" not in text, "an exclusion line is back in the report — the total must be the whole population"


# ── the not-applicable verdict's own contract (#3329) ────────────────────────


def test_every_not_applicable_row_carries_a_reason_on_the_live_census(real_census):
    """A verdict of "nothing here can fail" is a CLAIM. Unaccompanied by the reason it
    is an exemption, and an unexplained exemption is the artifact this census counts."""
    violations = gce.audit_verdicts(real_census["gates"])
    assert not violations, "verdict-contract violations on the live inventory:\n  " + "\n  ".join(violations)


def test_a_not_applicable_row_without_a_reason_reds():
    """The mutation, on the PURE function and synthetic gates — never the live repo, so
    it can neither flake nor be satisfied by today's inventory happening to be clean."""
    clean = [{"id": "guard::x.py", "verdict": "not-applicable", "evidence": "", "detail": {"reason": "returns kwargs; nothing refuses"}}]
    assert gce.audit_verdicts(clean) == []

    mutated = [{"id": "guard::x.py", "verdict": "not-applicable", "evidence": "", "detail": {"reason": "   "}}]
    violations = gce.audit_verdicts(mutated)
    assert violations, "a not-applicable row with a blank reason must red"
    assert "guard::x.py" in violations[0] and "no recorded reason" in violations[0]


def test_a_verdict_outside_the_vocabulary_is_surfaced_not_absorbed():
    """The other direction: an invented verdict string must not fall out of the sum in
    silence — that is exactly how six rows lived outside the denominator."""
    rogue = [{"id": "guard::y.py", "verdict": "probably-fine", "evidence": "", "detail": {}}]
    part = gce.verdict_partition(rogue)
    assert part["unrecognised"] == 1 and sum(part.values()) == 1
    assert any("outside the vocabulary" in v for v in gce.audit_verdicts(rogue))


def test_each_recorded_reason_that_cites_a_census_row_cites_a_LIVE_one(real_census):
    """Two of the six reasons close their case by naming the row that already reports
    their verdict (the #3220 Q2 rule). A citation that no longer resolves turns a real
    adjudication into a claim about a gate that does not exist — so it is checked."""
    live = {g["id"] for g in real_census["gates"]}
    cited = set()
    for reason in gce.NOT_APPLICABLE_REASONS.values():
        cited |= set(re.findall(r"(?:structural|guard|registry|sentinel|qa|ci)::[^\s`,]+", reason))
    assert cited, "no reason cites a covering census row — the Q2 half of the ruling has gone unwritten"
    assert not (cited - live), f"recorded reason(s) cite census id(s) that no longer exist: {sorted(cited - live)}"


def test_at_least_one_verdict_is_on_a_blocking_ci_gate(real_census):
    """Cheap gates are easy to prove; the acceptance bar is a high-consequence one.

    A verdict set made only of pytest files would say nothing about whether the board
    being green means anything — the board is CI.
    """
    proven_ci = [g for g in real_census["gates"] if g["verdict"] == "can-fail (proven)" and g["family"] == "ci-step"]
    assert proven_ci, "no CI-step gate carries a proven verdict — the verdict set is all cheap gates"


def test_scope_is_recorded_as_a_field_not_folded_into_prose():
    """Three of the six proofs found a gate that fires only for a narrow class. `scope`
    must stay its own field: folding it into `observed` is how 'can-fail' quietly starts
    reading as 'fully armed'."""
    scoped = [gid for gid, p in gc.PROVEN_CAN_FAIL.items() if p.scope.strip()]
    assert scoped, "no proof records a scope — implausible; scope narrowing is the common case"
    for gid in scoped:
        assert len(gc.PROVEN_CAN_FAIL[gid].scope) > 40, f"{gid}: `scope` is too terse to tell a reader what green excludes"


def test_attempted_unproven_entries_say_why():
    """An honest 'could not prove' is only useful with the reason attached."""
    assert gc.ATTEMPTED_UNPROVEN, "the attempted-and-unproved record is empty"
    for gid, note in gc.ATTEMPTED_UNPROVEN.items():
        assert len(note) > 120, f"{gid}: 'could not prove' with no reason is the same silence it replaces"
        assert "PROVED" in note.upper() or "ATTEMPTED" in note.upper(), f"{gid}: the note must state its own status"
