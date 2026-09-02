"""tests/test_platform_model_drift.py — the system-model drift gate (#2845, epic #2842).

Defect class owned (CONVENTIONS §9): the stale-dependency-picture class — the
committed ``model/platform_model.json`` or its rendering ``docs/DEPENDENCY_GRAPH.md``
disagreeing with what the code actually declares (the #2839 failure mode: false
edges surviving regenerations because the doc was prose). The gate regenerates
both artifacts from source on every CI run and diffs byte-for-byte, so a hand-edit
OR a stale commit reds the build — the #2844 pattern applied to the model.

Also pins a small set of KNOWN-TRUE edges (verified by reading the code, #2839's
corrected facts) so a regression in the extractor itself cannot pass as "the model
changed": if ``day_grade`` stops showing its two writers, the extractor broke.

Run:  python3 -m pytest tests/test_platform_model_drift.py -v
Fix:  python3 scripts/generate_platform_model.py   (then commit both artifacts)

#3265: `_built()` used to re-run `gen.build_model()` — a scan of the whole
lambdas/mcp/cdk tree — on EVERY call with no memoization: once per test (5 tests) plus
a SECOND time inside `test_generation_is_deterministic` itself (which exists purely to
prove the two builds are byte-identical), 6 full builds total against the unmutated
repo tree every run. None of the five tests below mutate `model`/`gen` state — the one
that plants a defect (`test_mutation_a_hand_edit_is_detected`) does so on a fresh
`json.loads()` copy, never on the cached object — so caching is sound. Measured locally
(this file alone, `-p no:randomly`, before vs after this change, 2-run mean before /
3-run mean after — durations under 0.005s round to 0 in pytest's own report):
file total 40.21s -> 6.91s (-33.30s, -82.8%). Only the first test to run pays the one
real build (~6.5-7.0s, six builds collapsed to one); the other four are cache hits
(<0.005s each, `--durations=0` confirms 14 of the file's 15 timed phases fall below
pytest's own reporting floor).
"""

import functools
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_platform_model as gen  # noqa: E402

_REGEN = "run: python3 scripts/generate_platform_model.py and commit the result"


@functools.lru_cache(maxsize=1)
def _built():
    model = gen.build_model()
    return model, gen.serialize(model), gen.render_doc(model)


def test_model_json_is_current():
    """The committed model must equal a fresh regeneration byte-for-byte."""
    _, model_text, _ = _built()
    committed = gen.MODEL_PATH.read_text(encoding="utf-8")
    assert committed == model_text, f"model/platform_model.json is stale or hand-edited — {_REGEN}"


def test_dependency_graph_is_current():
    """docs/DEPENDENCY_GRAPH.md is a RENDERING of the model — never hand-edited."""
    _, _, doc_text = _built()
    committed = gen.DOC_PATH.read_text(encoding="utf-8")
    assert committed == doc_text, f"docs/DEPENDENCY_GRAPH.md is stale or hand-edited — {_REGEN}"


def test_generation_is_deterministic():
    """Two builds serialize identically — the drift diff can never flap."""
    _, first, doc_first = _built()
    _, second, doc_second = _built()
    assert first == second and doc_first == doc_second


def test_known_true_edges_pin_the_extractor():
    """Extractor-regression tripwire: facts verified by reading the code.

    * day_grade has TWO writers (daily_metrics_compute + daily_brief store_day_grade
      — the #2214/#2839 dual-writer fact the old prose doc got wrong);
    * adaptive_mode writes engagement_state (the subsystem the old doc omitted);
    * whoop is written by its ingestion lambda and read broadly;
    * the census and CDK planes are non-trivially populated.
    """
    model, _, _ = _built()

    def modules(partition, direction):
        return {e["module"].rsplit("/", 1)[-1] for e in model["edges"] if e["partition"] == partition and e["direction"] == direction}

    assert {"daily_metrics_compute_lambda.py", "daily_brief_lambda.py"} <= modules("day_grade", "write")
    assert "adaptive_mode_lambda.py" in modules("engagement_state", "write")
    assert "whoop_lambda.py" in modules("whoop", "write")
    assert len(modules("whoop", "read")) >= 10
    assert len(model["partitions"]) >= 100, "the ADR-077 census went missing"
    assert len(model["lambdas"]) >= 90, "the CDK lambda plane collapsed"
    assert len(model["alarms"]) >= 30, "the CDK alarm plane collapsed"


# ── #3374 R1: the cost-bearing-surface baseline ratchet ──────────────────────
# model/cost_surface_baseline.json is HAND-OWNED (the generator never writes it);
# the model's cost_surface plane is derived. Exact-pinning the two means a PR that
# grows any of the five cost-bearing populations (schedules, alarms, EMF
# namespaces, secrets, budget-guard AI features) must bump the baseline in the
# SAME diff — a deliberate, reviewable act — and a shrink must ratchet it down,
# so the baseline can never quietly sit above the estate.

_BASELINE_PATH = ROOT / "model" / "cost_surface_baseline.json"


def _cost_surface_failures(derived: dict, baseline: dict) -> list:
    """Every way the committed baseline disagrees with the derived plane."""
    failures = []
    for key in sorted(set(derived) | set(baseline)):
        if key not in baseline:
            failures.append(f"cost surface {key!r} is derived but has no baseline entry — add it to model/cost_surface_baseline.json")
        elif key not in derived:
            failures.append(f"baseline entry {key!r} no longer derived — remove it from model/cost_surface_baseline.json")
        elif derived[key] > baseline[key]:
            failures.append(
                f"cost surface {key!r} GREW: {baseline[key]} -> {derived[key]}. A new cost-bearing surface may not appear "
                f"silently (#3374 R1) — bump model/cost_surface_baseline.json in this same diff, naming the surface in the PR"
            )
        elif derived[key] < baseline[key]:
            failures.append(
                f"cost surface {key!r} shrank: {baseline[key]} -> {derived[key]} — ratchet model/cost_surface_baseline.json "
                f"down to match (a baseline above the estate would let the next growth pass unseen)"
            )
    return failures


def test_cost_surface_baseline_is_exact():
    """#3374 R1: derived cost-surface counts == the committed baseline, key-for-key."""
    model, _, _ = _built()
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["counts"]
    failures = _cost_surface_failures(model["cost_surface"], baseline)
    assert not failures, "\n".join(failures)


def test_cost_surface_mutations_fail_both_directions():
    """Positive controls: the comparison can actually fail — on growth, shrink, a
    surface the baseline never heard of, and a baseline row for a dead surface."""
    model, _, _ = _built()
    derived = dict(model["cost_surface"])
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["counts"]
    victim = sorted(derived)[0]

    grown = dict(derived, **{victim: derived[victim] + 1})
    assert any("GREW" in f for f in _cost_surface_failures(grown, baseline))

    shrunk = dict(derived, **{victim: derived[victim] - 1})
    assert any("shrank" in f for f in _cost_surface_failures(shrunk, baseline))

    unlisted = dict(derived, phantom_surface=1)
    assert any("no baseline entry" in f for f in _cost_surface_failures(unlisted, baseline))

    dead = dict(baseline, phantom_surface=1)
    assert any("no longer derived" in f for f in _cost_surface_failures(derived, dead))

    # negative control: agreement is quiet
    assert _cost_surface_failures(derived, dict(derived)) == []


def test_cost_surface_derivation_dead_man():
    """A registry the extractor can no longer find must RAISE, never count 0 —
    a plausible zero would serialize and the ratchet would read it as a shrink to
    fix rather than a broken derivation (the absence-read-as-success class)."""
    import pytest

    with pytest.raises(ValueError, match="not found"):
        gen._count_registry_members(ROOT / "scripts" / "generate_platform_model.py", "NO_SUCH_REGISTRY_EXISTS_HERE")


def test_mutation_a_hand_edit_is_detected():
    """Mutation self-test: any single-field change to the model changes the
    serialization (what the byte diff gate keys on), and a mutated model renders
    a different doc — the gate can actually fail on both artifacts."""
    model, model_text, doc_text = _built()
    mutated = json.loads(model_text)
    victim = sorted(mutated["lambdas"])[0]
    mutated["lambdas"][victim]["stack"] = "hand-edited"
    assert json.dumps(mutated, indent=2, sort_keys=True) + "\n" != model_text
    edge_victim = mutated["edges"][0]
    edge_victim["partition"] = "hand-edited-partition"
    assert gen.render_doc(mutated) != doc_text
