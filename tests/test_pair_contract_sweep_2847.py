"""tests/test_pair_contract_sweep_2847.py — the producer/consumer contract sweep (#2847, epic #2842).

WHAT THIS GUARDS
----------------
Charter primitive 4 standing rule 3: *every new "must agree" pair gets a contract
test at birth, on the real wire shape.* #2813 instantiated that primitive for one
agreement (what day is it). This is the general form: a registry of producer↔consumer
pairs plus a harness that, for each pair, round-trips the REAL producer's output
through the REAL consumer and then injects a disagreement into BOTH sides.

The defect class is fixture-not-the-wire: producer and consumer each pass their own
tests against their own idea of the shape, and the wire disagrees. Two live instances
found while seeding the registry, both green in every existing test — both root-caused,
fixed, and enrolled by #3172 (pairs 7 and 8 in ``tests/pair_contract_registry.py``):
``site_stats_refresh_lambda`` read ``tier0_streak`` off the raw ``habitify`` partition
(which has no such field — it lives on ``computed_metrics``), and
``coach_observatory_renderer`` read ``journaling_prompt`` off ``OUTPUT#`` rows (which no
writer ever emitted — it lives on the ``ai_analysis`` ``EXPERT#`` row).

THE TWO SIDES, NAMED
--------------------
For every registered mutation the sweep asserts, separately and with distinct failure
messages:

  PRODUCER SIDE  the mutated path exists in what the real producer emitted. A drop of a
                 field nobody writes is a no-op — and a no-op mutation is the
                 consumer-reads-a-dead-field half of the class.
  CONSUMER SIDE  the real consumer's answer CHANGES (or it raises). A consumer whose
                 output is identical without the field is not reading it — the
                 producer-writes-a-dead-field half.

So a one-sided contract cannot hide: it fails in a named direction.

DISCOVERY: A LIVE CANDIDATE UNIVERSE + AN ENROLLMENT RATCHET (the choice, and why)
----------------------------------------------------------------------------------
A hand-registry with no discovery is how registries rot, so the candidate universe is
DERIVED, not typed: ``_candidate_pairs()`` reads the #2845 system model's edge plane and
returns every partition written by one module and read by a different one — 299 pairs
over 46 partitions as of this commit.

Full enrollment discovery is nevertheless NOT decidable here, and the model says so
itself: ``meta.scope_cuts`` records "field-level edges wait on the #2797 per-field wiring
registry". Without per-field edges, "these two modules must agree about a SHAPE" cannot be
told apart from "these two modules both touch a partition" — so a per-candidate exemption
ledger would be 299 rows of ceremony written by a model that cannot ground them.

The coverage instrument is therefore a **pinned floor with an explicit ratchet**, in three
parts, each of which reds:

  1. ``KNOWN_MUST_AGREE_PAIRS`` — the named floor (the #2813 follow-up list plus the two
     contracts built this week). A known pair missing from the registry reds.
  2. ``ENROLLED_FLOOR`` — the count may only grow. Deleting a pair to make CI green reds.
  3. ``PARTITION_WRITER_LEDGER`` — for every partition an enrolled pair travels over, the
     pinned set of modules that WRITE it. A new writer to a contracted shape must either
     be enrolled or written into the ledger with a REASON. The second-writer-with-a-
     different-field-set class (#2214/#2804) is exactly how these shapes have actually
     diverged, so a contracted partition keeps the higher bar.

BOX 4 ("adding a pair without a contract test is a conformance finding") LIVES NEXT DOOR
-----------------------------------------------------------------------------------------
Ratchet 3 above is the *reasoned* gate over CONTRACTED partitions. The fleet-wide form —
every must-agree seam on every partition, contracted or not — is
``tests/test_pair_seam_conformance_2847.py`` (sweep ``pair_seam_guard_lib``, ledger
``pair_seam_residue``): charter standing rule 3's counterpart to #2844's rule 1. The two
overlap on contracted partitions by design; ratchet 3 is the strict subset with the higher
bar. Enrolling a pair HERE removes rows from THAT ledger, which is the link that makes the
seam guard an enforcement of this registry rather than a bystander standing beside it.

BOX 2 ("the registry of known pairs lives in the system model")
---------------------------------------------------------------
``scripts/generate_platform_model.py::extract_contracts`` lifts this registry into the
#2845 model's ``contracts`` plane by AST — the enrolled ``PairContract(...)`` declarations
UNIONED with the ``KNOWN_MUST_AGREE_PAIRS`` floor, each row flagged ``floor`` / ``enrolled``,
with ``ENROLLED_FLOOR`` carried as ``meta.counts.contracts_ratchet``. So the committed
``model/platform_model.json`` (and its ``docs/DEPENDENCY_GRAPH.md`` §4b rendering) is the
readable index of which pairs this platform knows must agree, and a floor name whose
registry entry rotted away is visible in the ARTIFACT as ``enrolled: false``.

``test_platform_model_drift.py`` keeps that artifact byte-current against a fresh
regeneration; what it cannot catch is a projection that regenerates FAITHFULLY into
something wrong (an extractor that quietly stopped lifting ``mutations`` would regenerate,
commit clean, and stay green forever). ``_contract_plane_findings`` therefore joins the
committed plane to the LIVE registry objects field by field, and is mutation-proved in
both directions — ten single-field corruptions of the real committed model, plus a
registry and a floor that grow past it.

Plus the #2640 blind-green guards: the derivation must be non-vacuous, and every
registered ``partition`` must be a real modeled partition with both a writer and a
cross-module reader — so a registry entry cannot name a fiction.

MUTATION PROOF
--------------
``test_harness_reds_on_a_consumer_that_ignores_the_field`` and
``test_harness_reds_on_a_producer_that_never_writes_the_field`` drive the same harness
over synthetic pairs and assert it fails in each named direction. Without these, a
harness that silently matched nothing would green every assertion above.

Run:  python3 -m pytest tests/test_pair_contract_sweep_2847.py -v
"""

import collections
import copy
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.join(_REPO, "tests")
_MODEL_PATH = os.path.join(_REPO, "model", "platform_model.json")
for _p in (_TESTS, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pair_contract_registry as seed  # noqa: E402,F401 — import populates the registry
from pair_contract import (  # noqa: E402
    PAIR_CONTRACT_REGISTRY,
    MutationNotApplicable,
    apply_mutation,
    consume_safely,
)

# ══════════════════════════════════════════════════════════════════════════════
# The pinned writer sets for every contracted partition (ratchet part 3).
#
# Verified 2026-08-24 against the #2845 model's write edges. A NEW module writing
# one of these partitions is a producer joining a shape that already has a
# contract — enroll it as a pair, or add it here with the reason it cannot
# disagree. Entries only ever come OUT (when the writer is gone).
# ══════════════════════════════════════════════════════════════════════════════

PARTITION_WRITER_LEDGER = {
    "computed_metrics": {
        "lambdas/compute/daily_metrics_compute_lambda.py": "enrolled — the pair below",
        "lambdas/compute/acwr_compute_lambda.py": (
            "second writer, verified 2026-08-24: updates the ACWR fields on the SAME DATE# row and "
            "touches none of the ten NUMERIC_FIELDS canonical_facts extracts."
        ),
    },
    "engagement_state": {
        "lambdas/compute/adaptive_mode_lambda.py": "enrolled — the pair below",
    },
    "adaptive_mode": {
        "lambdas/compute/adaptive_mode_lambda.py": "enrolled — the pair below",
    },
    # #3172
    "ai_analysis": {
        "lambdas/intelligence/ai_expert_analyzer_lambda.py": "enrolled — the pair below",
    },
}


# ── the model-derived candidate universe ─────────────────────────────────────


def _model():
    with open(_MODEL_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _writers_and_readers():
    writers, readers = collections.defaultdict(set), collections.defaultdict(set)
    for edge in _model()["edges"]:
        if edge["direction"] == "write":
            writers[edge["partition"]].add(edge["module"])
        elif edge["direction"] == "read":
            readers[edge["partition"]].add(edge["module"])
    return writers, readers


def _candidate_pairs():
    """Every (partition, writer module, reader module) with writer != reader.

    The honest candidate universe for "these two must agree about a shape" at the
    granularity the system model can actually derive.
    """
    writers, readers = _writers_and_readers()
    out = []
    for partition in sorted(set(writers) & set(readers)):
        for writer in sorted(writers[partition]):
            for reader in sorted(readers[partition]):
                if writer != reader:
                    out.append((partition, writer, reader))
    return out


def _pair_id(pair):
    return pair.name


def _mutation_cases():
    return [(pair, mutation) for pair in PAIR_CONTRACT_REGISTRY for mutation in pair.mutations]


def _mutation_id(case):
    pair, mutation = case
    return f"{pair.name} | {mutation.label}"


# ══════════════════════════════════════════════════════════════════════════════
# The sweep
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("pair", PAIR_CONTRACT_REGISTRY, ids=_pair_id)
def test_real_producer_output_round_trips_through_the_real_consumer(pair):
    """The wire, end to end: the shipped producer's own output, read by the shipped consumer."""
    produced = pair.produce()
    consumed = pair.consume(produced)
    pair.agree(produced, consumed)


@pytest.mark.parametrize("case", _mutation_cases(), ids=_mutation_id)
def test_injected_disagreement_reds_on_both_sides(case):
    """One disagreement, injected into BOTH sides, each asserted by name."""
    pair, mutation = case
    produced = pair.produce()
    baseline = pair.consume(produced)

    # ── PRODUCER SIDE ────────────────────────────────────────────────────────
    try:
        mutated = apply_mutation(produced, mutation)
    except MutationNotApplicable as exc:
        pytest.fail(
            f"PRODUCER SIDE — {pair.name}: {pair.producer} does not emit the path this contract "
            f"claims ({mutation.label}). Either the producer dropped it (a live dead-zone read in "
            f"{pair.consumer}) or the registry entry is describing a shape that never existed. {exc}"
        )
    assert mutated != produced, f"PRODUCER SIDE — {pair.name}: {mutation.label} did not change the payload at all"

    # ── CONSUMER SIDE ────────────────────────────────────────────────────────
    after = consume_safely(pair, mutated)
    assert after != baseline, (
        f"CONSUMER SIDE — {pair.name}: {pair.consumer} returned an IDENTICAL answer with "
        f"{mutation.label} applied, so it is not actually reading that field ({mutation.why}). "
        f"Either the consumer moved off it — in which case the producer is writing a dead field — "
        f"or this mutation is not load-bearing and the registry entry should say so."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Coverage — the three ratchets
# ══════════════════════════════════════════════════════════════════════════════


def test_every_known_must_agree_pair_is_enrolled():
    """Ratchet 1 — the named floor. A known pair missing from the registry reds."""
    enrolled = {p.name for p in PAIR_CONTRACT_REGISTRY}
    missing = sorted(set(seed.KNOWN_MUST_AGREE_PAIRS) - enrolled)
    assert not missing, (
        "must-agree pair(s) named in KNOWN_MUST_AGREE_PAIRS but absent from the registry — "
        "re-enroll them in tests/pair_contract_registry.py rather than deleting the floor entry:\n"
        + "\n".join(f"  {name}" for name in missing)
    )


def test_enrollment_only_ever_grows():
    """Ratchet 2 — the count floor. Deleting a pair to green the build reds."""
    assert len(PAIR_CONTRACT_REGISTRY) >= seed.ENROLLED_FLOOR, (
        f"{len(PAIR_CONTRACT_REGISTRY)} pairs enrolled but ENROLLED_FLOOR is {seed.ENROLLED_FLOOR} — "
        "the registry shrank. Raise the floor only when you ADD a pair; never lower it."
    )


def test_no_unregistered_writer_joins_a_contracted_partition():
    """Ratchet 3 — a new producer on a shape that already has a contract is a finding.

    This is #2847's "adding a pair without a contract test is a conformance finding",
    scoped to where the #2845 model can ground it: the second-writer-with-a-different-
    field-set class (#2214 day_grade, #2804's dead-zone read) is how these shapes have
    actually diverged in production.
    """
    writers, _readers = _writers_and_readers()
    findings = []
    for partition, ledger in sorted(PARTITION_WRITER_LEDGER.items()):
        for module in sorted(writers.get(partition, set()) - set(ledger)):
            findings.append(f"  {partition} <- {module}")
    assert not findings, (
        "new writer(s) on a partition that already carries a producer/consumer contract (#2847).\n"
        "Enroll the writer as a pair in tests/pair_contract_registry.py, or add it to "
        "PARTITION_WRITER_LEDGER with the VERIFIED reason it cannot disagree about the shape:\n" + "\n".join(findings)
    )


def test_writer_ledger_has_no_dead_entries():
    """The ledger's own shrink half — a pinned writer that no longer writes must be pruned."""
    writers, _readers = _writers_and_readers()
    dead = []
    for partition, ledger in sorted(PARTITION_WRITER_LEDGER.items()):
        for module in sorted(set(ledger) - writers.get(partition, set())):
            dead.append(f"  {partition} <- {module}")
    assert not dead, "PARTITION_WRITER_LEDGER pins writer(s) the model no longer sees; delete them:\n" + "\n".join(dead)


# ══════════════════════════════════════════════════════════════════════════════
# Blind-green guards (#2640) — the derivation and the registry must be real
# ══════════════════════════════════════════════════════════════════════════════


def test_the_candidate_derivation_is_not_vacuous():
    """A discovery walk that silently found nothing would green every ratchet above."""
    candidates = _candidate_pairs()
    partitions = {p for p, _w, _r in candidates}
    assert len(candidates) >= 100, f"the model-derived candidate universe collapsed to {len(candidates)} pairs"
    assert len(partitions) >= 30, f"only {len(partitions)} partitions have both a writer and a cross-module reader"


def test_every_registered_partition_is_a_real_contracted_partition():
    """A registry entry cannot name a partition the model does not see written AND read."""
    writers, readers = _writers_and_readers()
    bogus = []
    for pair in PAIR_CONTRACT_REGISTRY:
        if pair.partition is None:
            continue  # S3 artifacts and ledger rows are outside the ADR-077 census by design
        if not writers.get(pair.partition) or not readers.get(pair.partition):
            bogus.append(f"  {pair.name}: partition {pair.partition!r} has no modeled writer/reader")
    assert not bogus, "registry entr(ies) naming a partition the #2845 model cannot ground:\n" + "\n".join(bogus)


# ══════════════════════════════════════════════════════════════════════════════
# Box 2 — the registry of known pairs LIVES IN the #2845 system model
#
# The generator lifts the literal declarations out of tests/pair_contract_registry.py
# by AST (never by import — the model's stated method: the entries carry live test
# closures the generator must never construct). The plane is the union of the ENROLLED
# PairContract(...) declarations and the KNOWN_MUST_AGREE_PAIRS floor, so a floor name
# whose registry entry rotted away shows up in the ARTIFACT as `enrolled: false` rather
# than only as a red test.
#
# test_platform_model_drift.py keeps the committed model byte-current against a fresh
# regeneration. What THAT cannot catch is a projection that regenerated faithfully into
# something wrong — an extractor that quietly stopped lifting `mutations`, or a floor
# tuple the plane no longer reflects, would regenerate, commit clean, and stay green.
# So the join is checked here against the LIVE registry objects, field by field, and the
# checker is mutation-proved below on the real committed model.
# ══════════════════════════════════════════════════════════════════════════════


def _contract_plane_findings(model, registry, known, ratchet):
    """Every disagreement between the model's contracts plane and the live registry.

    Returns a list of human-readable findings — empty means the model IS the registry.
    Pure over its four arguments so the mutation proofs can drive it with perturbed
    copies of the real committed model.
    """
    plane = model.get("contracts") or []
    counts = (model.get("meta") or {}).get("counts") or {}
    findings = []
    if not plane:
        findings.append("the model has no `contracts` plane at all")
        return findings

    by_name = {}
    for rec in plane:
        if rec["name"] in by_name:
            findings.append(f"{rec['name']}: duplicated in the model's contracts plane")
        by_name[rec["name"]] = rec

    expected = {p.name for p in registry} | set(known)
    for name in sorted(expected - set(by_name)):
        findings.append(f"{name}: known/enrolled in the registry but ABSENT from the model plane")
    for name in sorted(set(by_name) - expected):
        findings.append(f"{name}: in the model plane but neither enrolled nor on the floor")

    for pair in registry:
        rec = by_name.get(pair.name)
        if rec is None:
            continue
        for field, live in (("producer", pair.producer), ("consumer", pair.consumer), ("partition", pair.partition)):
            if rec.get(field) != live:
                findings.append(f"{pair.name}: model {field}={rec.get(field)!r} but the registry says {live!r}")
        if rec.get("mutations") != len(pair.mutations):
            findings.append(f"{pair.name}: model records {rec.get('mutations')} mutation(s), the registry declares {len(pair.mutations)}")
        if rec.get("enrolled") is not True:
            findings.append(f"{pair.name}: enrolled in the registry but the model marks it enrolled={rec.get('enrolled')!r}")

    for name, rec in sorted(by_name.items()):
        if rec.get("floor") is not (name in known):
            findings.append(f"{name}: model floor={rec.get('floor')!r} but KNOWN_MUST_AGREE_PAIRS membership is {name in known}")
        if not rec.get("enrolled") and rec.get("floor"):
            findings.append(f"{name}: on the KNOWN floor with NO live PairContract — the registry entry rotted away")

    for key, live in (
        ("contracts_enrolled", len(registry)),
        ("contracts_known", len(set(known))),
        ("contracts_ratchet", ratchet),
    ):
        if counts.get(key) != live:
            findings.append(f"meta.counts.{key}={counts.get(key)!r} but the registry says {live!r}")
    return findings


def test_the_known_pair_registry_lives_in_the_system_model():
    """#2847 box 2 acceptance, on the real committed model."""
    findings = _contract_plane_findings(_model(), PAIR_CONTRACT_REGISTRY, seed.KNOWN_MUST_AGREE_PAIRS, seed.ENROLLED_FLOOR)
    assert not findings, (
        "the #2845 model's contracts plane and the live pair registry disagree — "
        "run: python3 scripts/generate_platform_model.py and commit the result:\n" + "\n".join(f"  {f}" for f in findings)
    )


def _plane_mutations():
    """Single-field corruptions of the REAL committed plane, each of which must red.

    Every one of these regenerates and commits cleanly as far as the byte-diff drift gate
    is concerned — they are exactly the faithful-looking-but-wrong projections this
    checker exists to catch.
    """
    victim = sorted(p.name for p in PAIR_CONTRACT_REGISTRY)[0]

    def find(model):
        return next(c for c in model["contracts"] if c["name"] == victim)

    def drop_entry(model):
        model["contracts"] = [c for c in model["contracts"] if c["name"] != victim]

    def rename_producer(model):
        find(model)["producer"] = "somewhere.else::moved"

    def forget_partition(model):
        find(model)["partition"] = None

    def zero_mutations(model):
        find(model)["mutations"] = 0

    def unset_floor(model):
        find(model)["floor"] = False

    def unenroll(model):
        find(model)["enrolled"] = False

    def invent_a_pair(model):
        model["contracts"] = model["contracts"] + [dict(find(model), name="a pair nobody registered")]

    def lower_the_ratchet(model):
        model["meta"]["counts"]["contracts_ratchet"] = 1

    def stale_enrolled_count(model):
        model["meta"]["counts"]["contracts_enrolled"] = 99

    def empty_the_plane(model):
        model["contracts"] = []

    return [
        (fn.__name__, fn)
        for fn in (
            drop_entry,
            rename_producer,
            forget_partition,
            zero_mutations,
            unset_floor,
            unenroll,
            invent_a_pair,
            lower_the_ratchet,
            stale_enrolled_count,
            empty_the_plane,
        )
    ]


@pytest.mark.parametrize("case", _plane_mutations(), ids=lambda case: case[0])
def test_the_plane_checker_reds_on_every_single_field_corruption(case):
    """Mutation proof, model side — a guard that cannot fail is not a guard."""
    label, mutate = case
    model = copy.deepcopy(_model())
    mutate(model)
    findings = _contract_plane_findings(model, PAIR_CONTRACT_REGISTRY, seed.KNOWN_MUST_AGREE_PAIRS, seed.ENROLLED_FLOOR)
    assert findings, f"{label}: the contracts-plane checker stayed GREEN on a corrupted model"


def test_the_plane_checker_reds_when_the_registry_grows_past_the_model():
    """Mutation proof, registry side — enrolling a pair without regenerating must red.

    The real failure mode in this direction: a PR adds a PairContract and forgets
    `python3 scripts/generate_platform_model.py`, so the model silently under-reports.
    """
    from pair_contract import Mutation, PairContract

    grown = list(PAIR_CONTRACT_REGISTRY) + [
        PairContract(
            name="an unregenerated newcomer",
            producer="new.producer::write",
            consumer="new.consumer::read",
            produce=dict,
            consume=lambda p: p,
            agree=lambda _p, _c: None,
            mutations=(Mutation(("x",), "drop"),),
        )
    ]
    findings = _contract_plane_findings(_model(), grown, seed.KNOWN_MUST_AGREE_PAIRS, seed.ENROLLED_FLOOR)
    assert any("an unregenerated newcomer" in f for f in findings), findings


def test_the_plane_checker_reds_when_the_floor_grows_past_the_model():
    """Mutation proof, floor side — naming a new KNOWN pair without regenerating must red."""
    findings = _contract_plane_findings(
        _model(), PAIR_CONTRACT_REGISTRY, tuple(seed.KNOWN_MUST_AGREE_PAIRS) + ("a pair we know must agree",), seed.ENROLLED_FLOOR
    )
    assert any("a pair we know must agree" in f for f in findings), findings


def test_the_plane_checker_is_green_on_the_real_model_after_a_no_op_roundtrip():
    """The other direction of the proof: deep-copying the real model changes nothing."""
    assert not _contract_plane_findings(copy.deepcopy(_model()), PAIR_CONTRACT_REGISTRY, seed.KNOWN_MUST_AGREE_PAIRS, seed.ENROLLED_FLOOR)


def test_status_page_email_log_derivation_is_still_the_mirrored_one():
    """Pin for the one mirrored consumer half in the registry.

    ``site_api_status.status()`` builds its per-sender freshness row from a LOCAL closure
    (``_last_sync``) that cannot be imported, so the send-ledger pair mirrors its two
    load-bearing derivations. A mirror that nobody pins is a fixture, not the wire — this
    reds the moment the real construction changes, forcing the mirror to follow.
    """
    with open(os.path.join(_REPO, "lambdas", "web", "site_api_status.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert 'f"email_log#{lid}"' in src, "site_api_status no longer builds its email-log source id as f'email_log#{lid}'"
    assert (
        'Key("pk").eq(f"{USER_PREFIX}{source_id}")' in src
    ), "site_api_status no longer keys email-log freshness on USER_PREFIX + source_id"
    assert 'items[0]["sk"].replace("DATE#", "")[:10]' in src, "site_api_status no longer slices the DATE#-prefixed sk the ledger writes"


# ══════════════════════════════════════════════════════════════════════════════
# Mutation proof of the HARNESS ITSELF
# ══════════════════════════════════════════════════════════════════════════════


def _synthetic(produce, consume, mutation):
    from pair_contract import PairContract

    return PairContract(
        name="synthetic",
        producer="synthetic::produce",
        consumer="synthetic::consume",
        produce=produce,
        consume=consume,
        agree=lambda _p, _c: None,
        mutations=(mutation,),
    )


def test_harness_reds_on_a_producer_that_never_writes_the_field():
    """The consumer-reads-a-dead-field half: the mutation cannot even be applied."""
    from pair_contract import Mutation

    pair = _synthetic(lambda: {"written": 1}, lambda p: p.get("read_but_never_written"), Mutation(("read_but_never_written",), "drop"))
    with pytest.raises(MutationNotApplicable):
        apply_mutation(pair.produce(), pair.mutations[0])


def test_harness_reds_on_a_consumer_that_ignores_the_field():
    """The producer-writes-a-dead-field half: the consumer's answer never moves."""
    from pair_contract import Mutation

    pair = _synthetic(lambda: {"written": 1, "ignored": 2}, lambda p: {"echo": p["written"]}, Mutation(("ignored",), "drop"))
    produced = pair.produce()
    baseline = pair.consume(produced)
    assert consume_safely(pair, apply_mutation(produced, pair.mutations[0])) == baseline


def test_harness_treats_a_raise_as_a_consumer_side_reaction():
    """A consumer that raises on a broken shape IS reacting — never a false red."""
    from pair_contract import Mutation

    pair = _synthetic(lambda: {"needed": 1}, lambda p: {"echo": p["needed"]}, Mutation(("needed",), "drop"))
    produced = pair.produce()
    assert consume_safely(pair, apply_mutation(produced, pair.mutations[0])) != pair.consume(produced)


def test_a_mutation_that_restates_the_producers_own_value_is_rejected():
    """A retype `to` equal to what the producer already wrote would be a silent no-op."""
    from pair_contract import Mutation

    with pytest.raises(ValueError):
        apply_mutation({"n": 3}, Mutation(("n",), "retype", to=3))


def test_a_pair_with_no_mutations_cannot_be_registered():
    """An unfalsifiable contract is not a contract."""
    from pair_contract import PairContract, register

    with pytest.raises(ValueError):
        register(
            PairContract(
                name="unfalsifiable",
                producer="a::b",
                consumer="c::d",
                produce=dict,
                consume=lambda p: p,
                agree=lambda _p, _c: None,
            )
        )
