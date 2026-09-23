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
        # Upper bound raised 49 -> 50 (2026-09-05, #3503): the 50th proof is
        # `structural::test_composite_alarm_lookup_3390.py` — the #3390 one-file pin widened
        # into a family-5 tree sweep requiring every describe_alarms/describe_alarm_history
        # call in first-party source to state its AlarmTypes. Mutation-backed via the
        # re-runnable harness (`gate_census_mutations.py --run --gate
        # test_composite_alarm_lookup_3390.py`: ARMED 1/1, planting an untracked
        # deploy/_census_probe_3503.py whose whole-estate sweep omits AlarmTypes).
        # Upper bound raised 50 -> 51 (2026-09-06, #3568): the 51st proof is
        # `structural::test_email_sender_identity_3568.py` — the sending-vocabulary census,
        # which checks every code default and every CDK EMAIL_SENDER literal against the
        # committed set of SES-verified domains, and additionally pins reader mail to the
        # site domain. Mutation-backed via the re-runnable harness
        # (`gate_census_mutations.py --run --gate test_email_sender_identity_3568.py`:
        # ARMED 1/1, planting an untracked lambdas/common/_census_probe_3568.py whose
        # sender default names a .invalid domain SES can never have verified).
        # BASELINE_TOTAL_GATES is deliberately NOT moved: #3588/#3629 net-removed one gate
        # in the same window, so the live total stays at the committed 597.
        # Upper bound raised 71 -> 79 (2026-09-06, #3645): eight new proofs, one per
        # tests/test_no_tool_attribution_3005.py::ALLOWLIST entrant the widened sweep-1
        # mention pattern turned into a new gate — REGISTRY_PROOFS in
        # scripts/gate_census_proofs.py, each proven load-bearing (delete the entry ->
        # the guard reds naming exactly that file; reverted -> exit 0). Watched
        # 2026-09-06 for all eight (see PR #3658).
        3
        <= len(proven)
        # Upper bound raised 79 -> 88 (2026-09-06, #3544's derived second pass): the nine new proofs are the nine
        # rows of `tests/test_token_contrast.py::DERIVED_OPACITY_EXEMPT`. Each is mutation-backed PER ENTRY and in
        # BOTH directions by tests that ship with it: delete the row and
        # `test_every_derived_exemption_is_load_bearing[<selector>]` watches the measured half red in all three
        # palette blocks; strip the opacity out of the rule and
        # `test_derived_scan_is_live_and_its_exemptions_are_not_stale` reds naming the selector. Two of the nine
        # were additionally watched as whole-file mutations of the real working tree (`.wf-arrow` direction a,
        # `.wf-sep` direction b), each red at exit 1 and reverted to 38 passed.
        # Upper bound raised 88 -> 89 (2026-09-07, #3548/#3676): the 89th proof is
        # `structural::test_a11y_ledger_3548.py` — STRUCTURAL_HAND_PROOFS in
        # scripts/gate_census_proofs.py, mutation-backed against a real historical specimen:
        # site/coaching/read/index.html's `<div data-dx-read>` reverted in place to the
        # pre-#3548 `<article data-dx-read>` (the retired tabpanel-host shape all 18 dx-read
        # hosts carried). Watched RED: test_no_dx_read_panel_is_an_article failed naming the
        # file. REVERTED: 11 passed.
        # Upper bound raised 89 -> 90 (2026-09-07, #3678): the 90th proof is
        # `guard::scripts/check_job_timeout_headroom.py` — GUARD_PROOFS in
        # scripts/gate_census_proofs.py, watched RED live against the real repo's own
        # then-unmodified pr-checks.yml (timeout-minutes: 15 vs. measured p95 14.87min x
        # 1.2 = 17.84min required), then OK against the same live measurement once the
        # ceiling was raised to 18 in this same PR — plus the offline synthetic-fixture
        # twin in tests/test_check_job_timeout_headroom_3678.py.
        # Upper bound raised 90 -> 91 (2026-09-07, #3690): the 91st proof is
        # `structural::test_platform_stats_honesty_3690.py`. No synthetic mutation was
        # needed — the ARMED condition was the LIVE production defect: /api/platform_stats
        # served review_grade "A" against a newest review (2026-09-05, 17 lenses) that
        # graded B+ 9 / B 3 / B- 3 / C+ 2 and awarded A to nothing, plus site_pages 77
        # against 93 registered and active_secrets 21 against 28 in the model. Restoring
        # those three literals: 4 of 6 FAILED. Corrected: 6 passed.
        # Upper bound raised 91 -> 92 (2026-09-13, #3741): the 92nd proof is
        # `guard::lambdas/content/recap_gate.py`, the daily recap card's publish gate.
        # Three defects planted one at a time in the real module and each watched RED:
        # the step-1 fail-closed return replaced by an empty vocabulary (1 failed);
        # screen_items replaced by set() (1 failed); the step-3 PrivacyViolation handler
        # returning CLEARED instead of HELD (3 failed). Restored between each, 11 passed
        # again after the third. Recorded honestly in GUARD_PROOFS: M1 did NOT fail the
        # way the plant intended — with step 1's refusal gone, privacy_guard independently
        # requires the same vocabulary and raises uncaught, so deleting the explicit
        # refusal produces a failed invocation rather than a card. Layered, not single.
        # 92 -> 94 on 2026-09-14: TWO new proofs this session, and the bound is set to
        # cover both so it holds whichever merges first.
        #   structural::test_bundle_boot_pil_baseline_3784.py — M1 restores the exact
        #     baseline state that failed #3737's Deploy job (1 failed / 14); M2 parks a
        #     fabricated non-PIL entry (2 failed / 13).
        #   structural::test_recap_coach_line_3749.py (#3786) — M1 restores the placement
        #     bug that shipped (1 failed / 50, and only dense-session); M2 swaps the read
        #     seam to served_summary, the owner-register fallback (9 failed / 42).
        # Both are mutation-backed against REAL failure modes, which is the property this
        # band exists to protect. Unproven UNCHANGED — neither is a new unproven entrant.
        # Both have now landed (#3789 then #3786), so the band is exact: slack 0.
        # Upper bound raised 94 -> 95 (2026-09-14, #3642/#3799): the 95th proof is
        # `guard::scripts/check_no_verify_sites.py`, the --no-verify commit-bypass SET
        # guard. Two real-tree mutations, each watched RED live against the actual
        # tracked files (not a copy) and reverted: moving .claude/settings.json's
        # `Bash(git commit --no-verify:*)` entry from `ask` to `allow` (POSTURE
        # ESCALATION, exit 1; reverted, exit 0), and separately blanking `--no-verify`
        # off deploy/agent_commit.sh's own commit line (EXECUTION site vanishes, exit 1;
        # reverted, exit 0). Unproven UNCHANGED — a proven entrant, not a new unproven one.
        # Upper bound raised 95 -> 96 (2026-09-14/15, #3662, rebased atop #3799's 95th):
        # the 96th proof is `guard::scripts/check_ingestion_hardcoded_literals.py` —
        # GUARD_PROOFS in scripts/gate_census_proofs.py. Two mutations, each planted
        # directly in the real tracked tree and reverted with `git checkout --` right
        # after: (1) the #3662 defect itself — measurements_ingestion_lambda.py's fixed
        # `"measured_by": measured_by,` write replaced with the old unconditional
        # `"measured_by": "partner",` literal — ARMED: exit 1, printing the finding;
        # RESTORED: exit 0. (2) exemption load-bearingness — deleted the
        # `EXEMPTIONS["habitify_lambda.py"]["source"]` entry from the guard script itself
        # — ARMED: exit 1, printing the `source`/`supplements` finding it normally
        # suppresses; RESTORED: exit 0. Not a new unproven entrant (the census's
        # per-entrant test now sees it as proven, not ledgered).
        # Upper bound raised 96 -> 97 (2026-09-15, #3804, PR #3811, rebased atop #3809's
        # 96th): the 97th proof is `guard::scripts/check_repo_level_git_ops.py`. Not a
        # synthetic plant — the real prohibition sentence in
        # .claude/agents/worktree-implementer.md's item 3b was softened (the reason
        # sentence right after it left untouched — the realistic drift mode) and watched
        # RED (`python3 -m pytest tests/test_repo_level_git_ops_3804.py -q`: 2 failed, 18
        # passed; CLI exit 1), then reverted and watched GREEN (20 passed; CLI exit 0).
        # That run FOUND a real bug in the checker's own first cut — a too-coarse
        # blank-line-only paragraph split let an unrelated bullet's "never" satisfy a
        # completely different bullet's missing prohibition — fixed in the same PR before
        # this proof was recorded. Full record in `scripts/gate_census_proofs.py`.
        # Upper bound raised 97 -> 98 (2026-09-15, #3688, PR #3807, rebased atop #3804's
        # 97th): the 98th proof is `structural::test_judge_verdict_retry_3688.py`, a
        # MutationSpec ARMED 1/1 in scripts/gate_census_mutations.py. Its record is worth
        # reading rather than counting: THE MUTATION RUN WIDENED THE DETECTOR IT WAS
        # PROVING. M4 rewrote the covered call site to the membership form — semantically
        # identical code — and the first-draft pattern reported it as a phantom NEW judge
        # while the real one sat untouched. The rule now requires the two names on one line
        # with a comparison between them and strips trailing comments first; re-measured over
        # the whole scan surface it returns the SAME three sites with no new false positives.
        # M1 planted an unregistered judge under lambdas/operational/ (1 failed of 32;
        # reverted 32 passed); M2/M2b re-planted under mcp/ and in SUBSCRIPT form under
        # scripts/ (1 failed each — the subscript form is what the first draft missed);
        # M3/M3b are negative controls, the same idiom as a leading and as a trailing comment
        # (32 passed, no cry-wolf); M4b stripped truncation handling from the covered site in
        # tests/visual_ai_qa.py (3 failed). Three gaps are STATED in the record rather than
        # papered over — a two-line bind-then-compare form, a helper that returns the stop
        # reason, and a parse failure reached without reading it at all — which is why both
        # covered sites ALSO carry behavioural tests. It judges SOURCE SHAPE, never the live
        # gate: whether a Visual QA run actually retries is an observation no offline gate can
        # make, so #3688 closes on a run, not on this test.
        # Upper bound raised 98 -> 99 (2026-09-16, #3812): the 99th proof is
        # `guard::scripts/check_unlinked_closures.py`, closure-contract detector C — a merged
        # commit that names an open issue in its SUBJECT with no closing keyword. Its proof is
        # NOT a synthetic plant but a LIVE STATE TRANSITION on real data, which is the strongest
        # form available to a gate reading git history + the issue tracker: the run quoted in commit 255466389's own
        # message (committed 03:38:16Z) reported 14 findings INCLUDING #3642; that issue was then verified and closed
        # at 03:42:00Z; the same command on the same ref (20a597d07) and the same window returned
        # findings=13 with #3642 absent. Commit cf281a65e, its subject, the ref and the window
        # are byte-identical across both runs — the ONLY variable changed is the issue's state,
        # so the gate demonstrably measures OPEN-ness against the merge record rather than the
        # presence of a subject ref. That is precisely the property no static read of the source
        # can establish. The offline must-fail control (a planted merge commit naming an open
        # issue IS reported) and its MATCHED positive control (the same commit with `Fixes #N`
        # goes SILENT) are carried in tests/test_unlinked_closures_3812.py, 20 cases including a
        # MUTATION of the DISPOSITIONED ledger that surfaces the issue it was hiding. Full
        # record in scripts/gate_census_proofs.py::GUARD_PROOFS.
        # 99 -> 100 (2026-09-16, #3812): the 100th proof is
        # registry::scripts/closure_contract.py::CODE_KEYWORD_EXEMPTIONS::partial-acceptance-close,
        # proved by deleting the entry from the REAL tracked file and watching
        # test_no_finding_code_ends_in_a_GITHUB_CLOSING_KEYWORD red naming
        # {'partial-acceptance-close': 'close'} (1 failed / 24 passed), then restoring (25 passed).
        # 100 -> 101 (2026-09-16, #3830): the 101st proof is
        # guard::deploy/lib/canary_gate_retry.py, the deploy gate whose false NEGATIVE is a
        # fleet rollback. Proved by TWO real-tree mutations, not a monkeypatch: removing
        # "FAIL" from GATING_VERDICTS reds 7 of 15 including the must-fail control, and
        # reverting ci-cd.yml's Verify canary step to the single un-retried call reds the
        # seam test by name. Both restored to 15 passed, git diff empty.
        # 101 -> 102 (2026-09-16, #3785 box 3): the 102nd proof is
        # guard::deploy/config_provenance_audit.py, the generated-config provenance dead-man.
        # Proved by TWO real-tree mutations run against LIVE S3, not a fixture: repointing the
        # producer's INDEX_KEY at a non-existent object exits 1 (and the inverse arm
        # simultaneously flags the real object as "ageing unwatched" — unplanned, and the
        # better half of the result), and removing the config key from the EventBridge rule's
        # description exits 1 with "cadence UNDERIVABLE" rather than a guessed ceiling. Both
        # reverted to exit 0, git diff empty. Its no-stamp arm carries a REPLAY of the real
        # 2026-09-14 incident bytes fetched from S3 version history, not a synthetic case.
        # Worth recording: the offline mutation M3 caught the guard's OWN ratchet passing when
        # it should have failed — the enrolment stamp leg was a substring read over the file
        # and `_built_at` survived on a comment line; it reads the AST now.
        # 2026-09-17 (#3860/#3863): 102 -> 104. Two entrants, both arriving PROVEN rather than
        # ledgered unproven — the #3860 nightly totality census (QA_PROOFS, three arms incl. the
        # vacuous-scan trap) and #3863's detector D (GUARD_PROOFS, proven on the real d681aecc6
        # merge rather than a plant). Measured, not incremented: the branch census reported
        # {can-fail (proven) 104, unproven 537, not-applicable 6, attempted-unproven 3}.
        # 2026-09-17 (#3785 boxes 1+2): 104 -> 105. The 105th proof is
        # guard::deploy/config_ownership_audit.py, the config/ ownership registry — every
        # `config/**.json` ruled generated-vs-hand-owned, with the not-uploadable classes held
        # out of the twin set site-deploy syncs. Proved by FOUR real-tree mutations, each
        # plant's own md5 compared before/after so a no-op plant could not read as green:
        # the stale-twin branch disabled while the incident's own file was planted back; the
        # producer repointed at another key; the twin-set exclusion disabled; the sync's
        # put_object refusal disabled. Measured, not incremented: the branch census reported
        # {can-fail (proven) 105, unproven 537, not-applicable 6, attempted-unproven 3},
        # against 650/104 on a disposable `git archive` export of the merge-base.
        # 2026-09-18 (#3514): 105 -> 106. ONE entrant, arriving PROVEN rather than ledgered
        # unproven — structural::test_phase_provenance_3514.py, the write-time provenance gate.
        # Its mutation is not synthetic: coach_state_updater._put_item reverted to the shipped
        # pre-#3514 `experiment_stamp()` line, i.e. the literal state of main at 4b115435e,
        # under which 22 live rows (7 RELATIONSHIP#state, 15 CHAT#) were measured carrying
        # cycle-17 provenance on CROSS_PHASE partitions the same day. The file's md5 was
        # asserted CHANGED before the verdict was read, and the observed 5-failed split across
        # its behavioural and AST legs is in the proof record. Measured on the COMMITTED,
        # rebased tree: {can-fail (proven) 106, unproven 537, not-applicable 6,
        # attempted-unproven 3} over 652 rows.
        # 2026-09-18 (#3511): 106 -> 107. ONE entrant, arriving PROVEN —
        # guard::deploy/prereg_provenance_gate.py, the pre-genesis prediction provenance
        # contract. Its four mutations are planted in the real tracked module one at a time
        # (write-instant clause disarmed; unstamped rows treated as out-of-season; the
        # shapeless-artifact vacuity guard softened to `set()`; the mirror clause deleted),
        # each reverted before the next, and the stronger half is not a plant at all: on its
        # first live run it reported 26 blocking findings against the real table, 16 of them
        # every cycle-17 sealed bet stranded at phase=pilot/cycle=16. Measured on the MERGED,
        # COMMITTED tree: {can-fail (proven) 107, unproven 537, not-applicable 6,
        # attempted-unproven 3} over 653 rows, against 652/106 on a `git archive origin/main`
        # export.
        # 2026-09-18 (#3614 boxes 3+4): 107 -> 108. ONE entrant, arriving PROVEN rather than
        # ledgered unproven — structural::test_grounding_sets_3614.py, the two SETs the #1967
        # grounding registry did not carry: the per-surface audience/fail-mode facet, AST-read
        # at each surface's own disposition site, and the derived phase-prose census over every
        # prompt builder. It carries TWO controls, one per box, and neither is a monkeypatch.
        # (1) The phase census is mechanised as a MutationSpec, re-runnable by anyone:
        # `python3 scripts/gate_census_mutations.py --run --gate test_grounding_sets_3614.py`
        # plants a synthetic narrative door under lambdas/web that hand-types 'Today is Day {n}
        # of the experiment, restarted on {start}' instead of obtaining the phase from
        # ai_context — ARMED 1/1, baseline 27 passed, mutated 3 failed, reverted 27 passed, the
        # plant removed before the verdict was recorded. (2) The facet control is a DECLARATION
        # rather than a file, so it cannot be a plant: flipping
        # lambdas/web/site_api_ai_lambda.py::_handle_explain from fail_closed to keep_best in the
        # real tests/grounding_wiring.py (diff against a pre-mutation copy asserted CHANGED first
        # — one line, FAIL_CLOSED -> KEEP_BEST) gave 2 failed / 25 passed on two independent
        # edges (the pinned public keep-best residual gained a member it does not name, AND the
        # AST reported the call site still branching and holding), then reverted byte-for-byte to
        # 27 passed. Both controls also run on every build against a deepcopy of the registry,
        # including the INVERSE flip — which is the assertion that matters most: the derivation
        # reads acts=False on 4 of the 32 surfaces, so it is not a constant-true detector.
        # Measured on the REBASED, COMMITTED tree (a0cfa6a91, rebased onto 9258da37f):
        # {can-fail (proven) 108, unproven 537, not-applicable 6, attempted-unproven 3} over 654
        # rows, against 653/107 on a disposable `git archive origin/main` export. Unproven is
        # UNCHANGED at 537 and BASELINE_UNPROVEN_GATES is not touched — the entrant spends no
        # headroom.
        # 2026-09-18 (#3599 box 3): 108 -> 109. ONE entrant, arriving PROVEN —
        # guard::deploy/prereg_truth_gate.py, the pre-seal truth contract: a frozen
        # pre-registration whose coach roster, asserted starting weight or min_effect derivation
        # disagrees with the platform's own facts may not acquire a hash. Four mutations planted
        # one at a time in the real tracked module, each reverted byte-identical before the next,
        # and the stronger half is again not a plant: on its first run against the LIVE published
        # cycle-17 seal (sha256 bd225d24…) it reported 7 blocking findings — a retired coach, a
        # byline the registry does not use, three assertions of a superseded 326.2 lb baseline
        # against a 327.34 constant, and two bare-literal minimum effects. Worth recording,
        # because it is the failure mode this ceiling exists for: mutation M3 reported GREEN on
        # its first run and the HARNESS was wrong, not the gate — an md5 on the source proves the
        # FILE changed, never that the code under test did, and `100.0` -> `400.0` is byte-length
        # preserving, so CPython's (mtime, size) pyc validation re-ran the original module. The
        # general form of that trap, and the purge + `-B` fix, is written up for the next author
        # of a mutation control in scripts/gate_census_mutations.py's docstring.
        # FIRST measured at 107 -> 108 over 653 -> 654 against origin/main 56c6c4e7a; #3882's
        # #3614 entrant above merged first, so this was RE-MEASURED after rebasing onto
        # 63c7fc335 rather than incremented: {can-fail (proven) 109, unproven 537,
        # not-applicable 6, attempted-unproven 3} over 655 rows on the rebased, COMMITTED tree,
        # against 654/108 on a disposable `git archive origin/main` export. id-set diff between
        # the two --json dumps: exactly {guard::deploy/prereg_truth_gate.py} enters, {} leaves.
        # 2026-09-19 (#3731): 109 -> 113. FOUR entrants, all arriving PROVEN — the newly-
        # discovered structural:: gates found when tests/repo_scan_cache.py gained a
        # disk-backed, tree-state-keyed cache: its `_tree_fingerprint()` calls `os.walk`,
        # which makes it match premerge_derivation.py's `_SWEEP_PATTERN` for the first time,
        # so every test file that imports it (test_doc_facts_ops_1957.py,
        # test_doc_facts_ops_2003.py, test_wiki_checkers.py, test_repo_scan_cache_3224.py) is
        # newly classified as a tree-sweeping gate — correctly, since the module genuinely
        # sweeps the tree now. Each proved with the SAME real plant
        # (docs/_census_probe_3731.md, a wrong CloudWatch alarm-count claim that is
        # simultaneously a wiki-index/header violation), run through the harness one at a
        # time: `python3 scripts/gate_census_mutations.py --run --gate structural::test_X.py`
        # for each of the four, ARMED 4/4. The record's own point: the mutated run for each
        # paid the real scan cost (the plant changes the cache's tree-state key, so none of
        # the three real-scan readers served a pre-plant disk answer), while a same-tree-state
        # baseline that ran in a LATER, separate OS process read the FIRST process's disk
        # write in under a second — the cross-process sharing this PR ships, and the
        # never-stale property it depends on, both observed on the live tree in one batch.
        # {can-fail (proven) 113, unproven 537, not-applicable 6, attempted-unproven 3} over
        # 659 rows, measured on this branch after rebasing onto origin/main (#3889, #3894).
        # 2026-09-20 (#3625 + #3772): 113 -> 115. TWO entrants, both PROVEN in gate_census_proofs —
        # the bundle-reproducibility gate and the orphan-drafts nightly leg; one ceiling so the two
        # PRs land in either order.
        # Upper bound raised 114 -> 115 (2026-09-20, #3609 box 3, merged onto the #3625/#3772
        # tree): ONE new proof — structural::test_gsi_set_premerge_3609.py, the premerge
        # GSI-set gate (ADR-097's {GSI1, GSI2} asserted against reading_keys.py's constants,
        # every literal IndexName= on lambdas/+mcp/, and deploy_reading_gsis.sh's add_gsi call
        # list). MutationSpec in scripts/gate_census_mutations.py: an untracked
        # lambdas/coach/_census_probe_3609.py plants `table.query(IndexName="GSI9", ...)`.
        # ARMED 1/1: baseline 7 passed in 4.54s, mutated 1 failed (
        # test_every_indexname_literal_on_the_live_surface_is_sanctioned) + 6 passed in
        # 5.24s, reverted 7 passed in 5.26s. RE-MEASURED on the MERGED tree AFTER `git add`-ing
        # the merge's two resolved conflicts (a mid-merge tracked-file listing lists a conflicted
        # path 3x, once per stage, which briefly triple-counted every registry:: gate keyed on
        # this file — the prior 113->115 note above is main's OWN prior comment and was not
        # re-verified here, so this line does not depend on it being exact): a disposable
        # `git archive origin/main` export at c32e58c31 measures 114 proven, this lane merged
        # measures 115 (unproven UNCHANGED at 540 — a proven entrant, not a new unproven one).
        # 115 -> 116 (2026-09-20, Session AN, third merge of main into this lane): main itself reached
        # 115 via #3625 + #3772 while this lane was open, so this lane's ONE proven entrant (the GSI-set
        # gate above) lands at 116 on the merged tree. CI's premerge lane measured n=116 on a3ffd27c.
        # 116 -> 117 (2026-09-20, #3755): the 117th proof is
        # `structural::test_program_structure_3755.py` — the week-grid seam gate (exactly ONE reader of
        # config/training_week.json across lambdas/+mcp/, and both consumers reaching it through
        # training.program_seam.resolve_week_grid). Mutation-backed via the same re-runnable harness
        # (`gate_census_mutations.py --run --gate test_program_structure_3755.py`: ARMED 1/1 — an
        # untracked lambdas/training/_census_probe_3755.py planting a second direct
        # `_load_json("training_week.json")` read; baseline 24 passed, mutated 1 failed
        # (test_only_the_seam_names_the_week_config_filename) + 23 passed, reverted 24 passed).
        # Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 667 rows
        # {proven 117, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable
        # `git archive origin/main` export at d7bbecdd5 -> 666 {116, 540, 6, 4}. Exactly
        # {structural::test_program_structure_3755.py} enters, {} leaves — so unproven does NOT move
        # and BASELINE_UNPROVEN_GATES is untouched.
        # 117 -> 118 (2026-09-20, #3754): the 118th proof is
        # `structural::test_prior_cut_disclosure_3754.py` — the ADR-104 "not comparable to the
        # prior cut" sentence-uniqueness sweep (an os.walk of lambdas/+mcp/ asserting the sentence
        # is a literal string in exactly one file). Mutation-backed via the same re-runnable harness
        # (`gate_census_mutations.py --run --gate test_prior_cut_disclosure_3754.py`: ARMED 1/1 — an
        # untracked lambdas/health/_census_probe_3754.py planting a second, hand-typed copy of the
        # sentence; baseline 3 passed in 0.17s, mutated 1 failed
        # (test_the_adr104_sentence_is_defined_in_exactly_one_file) + 2 passed in 0.18s, reverted 3
        # passed in 0.15s). Measured by id-set diff on COMMITTED trees, never by arithmetic: this
        # lane -> 668 rows {proven 118, unproven 540, not-applicable 6, attempted-unproven 4}; a
        # disposable `git archive origin/main` export -> 667 {117, 540, 6, 4}. Exactly
        # {structural::test_prior_cut_disclosure_3754.py} enters, {} leaves — so unproven does NOT
        # move and BASELINE_UNPROVEN_GATES is untouched.
        # 118 -> 119 (2026-09-20, #3620): the 119th proof is
        # `structural::test_ip_hash_salt_sweep_3620.py` — the repo-wide sha256(ip) sweep (an
        # os.walk of lambdas/+mcp/ for any `.sha256(...)` call whose argument mentions `ip`,
        # triaged against an explicit allowlist). Mutation-backed via the same re-runnable harness
        # (`gate_census_mutations.py --run --gate test_ip_hash_salt_sweep_3620.py`: ARMED 1/1 — an
        # untracked lambdas/common/_census_probe_2999.py planting
        # `hashlib.sha256(source_ip.encode())`; baseline 4 passed in 0.30s, mutated 1 failed
        # (test_every_sha256_ip_call_site_is_triaged) + 3 passed in 0.31s, reverted 4 passed in
        # 0.28s). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane ->
        # 669 rows {proven 119, unproven 540, not-applicable 6, attempted-unproven 4}; a
        # disposable `git archive origin/main` export -> 668 {118, 540, 6, 4}. Exactly
        # {structural::test_ip_hash_salt_sweep_3620.py} enters, {} leaves — so unproven does NOT
        # move and BASELINE_UNPROVEN_GATES is untouched.
        # Upper bound 119 -> 120 (2026-09-21, #3005 fix-forward merged after #4006): the install_hooks.sh ALLOWLIST entrant, proven.
        # Upper bound 120 -> 121 (2026-09-21, #3621 box 4 re-merged onto main AFTER #4007): guard::scripts/verify_citations.py arrives
        # proven (GUARD_PROOFS); MEASURED on the merged tree by this test (`proven verdicts n=121`), not carried from the lane's 120.
        # Upper bound 121 -> 122 (2026-09-21, #3971 re-merged onto main AFTER #4005): guard::mcp/hevy_prescription_gate.py arrives
        # proven (GUARD_PROOFS); MEASURED on the merged tree by this test (`proven verdicts n=122`), not carried from the lane's 120.
        # Upper bound 122 -> 123 (2026-09-21, #3615 re-merged onto main AFTER #4014): structural::test_hook_registry_3615.py arrives
        # proven (STRUCTURAL_PROOFS, ARMED 1/1); MEASURED on the merged tree by this test (`proven verdicts n=123`), not carried from the lane's 120.
        # Upper bound 123 -> 124 (2026-09-20 PT, #3599 box 2, resolved on top of #3615's 123): structural::test_scoped_writer_provenance_guard_3599.py arrives
        # PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1 — an untracked
        # lambdas/emails/_census_probe_3599.py planting an unstamped put_item on USER#matthew#SOURCE#insights: baseline 13 passed
        # + 1 xfailed, mutated 1 failed, reverted 13 passed). Measured by id-set diff on COMMITTED trees, never by arithmetic:
        # the MERGE RESOLUTION tree (origin/main 3f9f73886 + this lane) -> 675 rows {proven 124,
        # unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export -> 674
        # {123, 540, 6, 5}. Exactly {structural::test_scoped_writer_provenance_guard_3599.py} enters, {} leaves — unproven does NOT move.
        # Upper bound 124 -> 125 (2026-09-21, #3621 boxes 2+5 re-merged onto main AFTER #4019): structural::test_protocol_lever_contract_3621.py
        # arrives proven (STRUCTURAL_HAND_PROOFS); MEASURED on the merged tree by this test (`proven verdicts n=125`), not carried from the lane's 124.
        # Upper bound 125 -> 126 (2026-09-21, #3615 boxes 4+5): structural::test_podcast_feed_link_3615.py arrives proven
        # (STRUCTURAL_PROOFS, ARMED 1/1 via the re-runnable harness — an untracked site/ page advertising the dark podcast feed:
        # baseline 8 passed, mutated 1 failed + 7 passed, reverted 8 passed). MEASURED by id-set diff against a disposable
        # `git archive origin/main` export at e2dac0e7e: lane {proven 126, unproven 540, not-applicable 6, attempted-unproven 5}
        # vs main {125, 540, 6, 5} — exactly one entrant, and unproven does not move.
        # Upper bound 126 -> 127 (2026-09-21, #3754 boxes 3+4): structural::test_nutrition_critics_3754.py arrives proven
        # (STRUCTURAL_PROOFS, ARMED 1/1 via the re-runnable harness — an untracked lambdas/web/ module importing the owner-only
        # nutrition critics: baseline 62 passed, mutated 1 failed + 61 passed, reverted 62 passed). MEASURED by id-set diff
        # against a disposable `git archive origin/main` export at 2c3b47d48: lane {proven 127, unproven 540, not-applicable 6,
        # attempted-unproven 5} vs main {126, 540, 6, 5} — exactly one entrant, and unproven does not move.
        # Upper bound 127 -> 128 (2026-09-21, #3913 box 3): structural::test_day_key_frame_declaration_guard_3913.py
        # arrives proven (STRUCTURAL_PROOFS, ARMED 1/1 via the re-runnable harness — an untracked
        # lambdas/ingestion/ module carrying a Zulu-anchored fetch window, the signature that makes a source's
        # DATE# key name a UTC day with nothing in the module going near a clock: baseline 16 passed, mutated
        # 5 failed + 11 passed, reverted 16 passed). MEASURED by id-set diff against a disposable
        # `git archive origin/main` export at bfb163388: lane {proven 128, unproven 540, not-applicable 6,
        # attempted-unproven 5} vs main {127, 540, 6, 5} — exactly one entrant, and unproven does not move.
        # Re-measured after merging origin/main into the lane (tip had moved to 5c729ec9c): merged lane
        # {128, 540, 6, 5} vs a fresh export {127, 540, 6, 5} — same one entrant, same verdicts.
        # Upper bound 128 -> 129 (2026-09-21, #3760, resolved on top of #3913's 128): structural::test_progress_viewer_privacy_3760.py
        # arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1 — an untracked
        # site/_census_probe_3760.html linking the owner-only viewer: baseline 16 passed, mutated 1 failed :: test_no_site_file_mentions_the_route,
        # reverted 16 passed). MEASURED by id-set diff on the MERGE RESOLUTION tree, never by arithmetic: lane {proven 129, unproven 540,
        # not-applicable 6, attempted-unproven 5} vs a disposable `git archive origin/main` export {128, 540, 6, 5} — exactly one entrant,
        # and unproven does not move.
        # Upper bound 129 -> 130 (2026-09-22, #4071): structural::test_muscle_volume_working_sets_4071.py — the AST derivation guard
        # that training.muscle_volume.working_sets_by_muscle is the ONE per-muscle set computation in mcp/ + lambdas/training/ —
        # arrives PROVEN via the re-runnable harness (MutationSpec, ARMED 1/1: an untracked lambdas/training/_census_probe_4071.py
        # carrying the pre-#4071 loop shape; baseline 63 passed | mutated 1 failed :: test_no_second_per_muscle_set_computation_in_mcp_or_training
        # | reverted 63 passed). MEASURED by id-set diff: lane {proven 130, unproven 540, not-applicable 6, attempted-unproven 5} vs a
        # disposable `git archive origin/main` export at 24996c6c2 {129, 540, 6, 5} — exactly one entrant, none leaves.
        # Upper bound 131 -> 132 (2026-09-23, #4075): structural::test_training_load.py, the TRIMP-exponent sweep, PROVEN
        # (ARMED 1/1) via the harness. PRIOR: Upper bound 130 -> 131 (2026-09-22, #4068): structural::test_shared_quantities_4068.py — the AST derivation guard that
        # weekly walking hours and the loss rate reach every named critic/tool (get_benchmark included) through mcp.shared_quantities
        # and that nothing else builds the walking layer — arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS,
        # ARMED 1/1: an untracked mcp/_census_probe_4068.py calling walking_volume.build; baseline 24 passed | mutated 1 failed ::
        # test_only_the_shared_module_builds_the_walking_layer | reverted 24 passed). Unproven stays 540; exactly one entrant.
        # Upper bound 131 -> 132 (2026-09-23, #4107): structural::test_v03_nearest_band_anchor_4107.py — the AST derivation guard
        # that load_ramp.v03_floor is the ONE v0.3 load path (nothing else calls ramp_floor / nearest_band_anchor; the generator,
        # planner and chat commit gate each name it) — arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS,
        # ARMED 1/1: an untracked lambdas/training/_census_probe_4107.py calling ramp_floor; baseline 24 passed | mutated 1 failed ::
        # test_derivation_guard_only_v03_floor_calls_the_ramp_and_the_fallback | reverted 24 passed). Unproven stays; one entrant.
        # 132 -> 133 (2026-09-23, #4075 on top of #4107): structural::test_training_load.py, PROVEN (ARMED 1/1).
        # Upper bound 133 -> 134 (2026-09-23, #4063, re-merged on top of #4075's 133): structural::test_named_human_contact_4063.py — the named-human contact
        # path's no-health-data body contract + the tracked-tree grep for a contact-shaped address — arrives PROVEN via a hand
        # Proof in scripts/gate_census.PROVEN_CAN_FAIL (a digit planted in the body: 10 failed / 74 passed; a contact address
        # appended to a tracked doc: 1 failed / 83 passed; baseline and reverted 84 passed). Unproven stays 540; one entrant.
        # Upper bound 134 -> 135 (2026-09-23, #3597, re-merged on top of #4063's 134): structural::test_obligation_carriers_3597.py — the residue-registry
        # derivation guard (every `*_RESIDUE` binding and tests/*_baseline.json registered with carrier + condition + expiry +
        # shrink consumer) — arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS, ARMED 1/1: a git-added
        # tests/_census_probe_3597.py binding PROBE_RESIDUE; baseline 32 passed | mutated 1 failed ::
        # test_the_live_residue_registry_meets_its_contract | reverted 32 passed). Unproven stays; one entrant.
        # 135 -> 136 (2026-09-23, #3528, re-merged on top of #3597's 135): structural::test_ci_stand_ins_derive.py — the git-push-caller enumeration
        # (every scripts/ + deploy/ pusher derives its CI stand-in from ci_gate_commands) — arrives PROVEN by a GUARD_PROOFS record
        # in scripts/gate_census_proofs.py (mutated: direct_push_gate.py stops importing ci_gate_commands -> 2 failed; reverted
        # -> 2 passed). Unproven stays. Same PR, 136 -> 140: guard::deploy/direct_push_gate.py, guard::scripts/ci_gate_commands.py
        # and the two PUSHER_EXEMPT registry entries, each proven by a watched mutation (records in gate_census_proofs.py).
        <= 140
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
