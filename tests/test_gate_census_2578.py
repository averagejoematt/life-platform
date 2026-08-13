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
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("gate_census", REPO_ROOT / "scripts" / "gate_census.py")
assert _SPEC and _SPEC.loader
gc = importlib.util.module_from_spec(_SPEC)
sys.modules["gate_census"] = gc
_SPEC.loader.exec_module(gc)


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
