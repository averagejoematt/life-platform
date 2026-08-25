"""tests/pair_contract.py — the #2847 producer/consumer contract framework (epic #2842).

WHY THIS EXISTS
---------------
Charter primitive 4 says: *every pair of things that must agree gets a test that
fails when they diverge, written against the real wire shape.* #2813 built that
for exactly ONE agreement — "what day is it" — and the class it kills is much
wider than timezones. The general defect is the **fixture-not-the-wire** failure:

    the producer has a test, written against the producer's idea of the shape;
    the consumer has a test, written against the consumer's idea of the shape;
    both are green; the WIRE disagrees, and nobody finds out until an incident.

Two live examples found while seeding this registry, both of which were green in
every existing test:

  * ``lambdas/web/site_stats_refresh_lambda.py`` reads ``tier0_streak`` off the
    ``habit_scores`` partition. ``store_habit_scores`` writes ``t0_perfect_streak``
    there; ``tier0_streak`` lives on ``computed_metrics``. The read is a
    permanent ``None`` and no test noticed (#2804's dead-zone-read class).
  * ``coach_observatory_renderer`` reads ``journaling_prompt`` and
    ``generated_at`` off ``OUTPUT#`` rows. No ``OUTPUT#`` writer emits either.

Neither is a bug in the producer OR in the consumer taken alone. It is a bug in
the PAIR, and a pair has no owner until something like this registry gives it one.

THE INJECTION IS TWO-SIDED — THAT IS THE WHOLE POINT
-----------------------------------------------------
A one-sided contract test is how this class survives. "The consumer handles a
missing field gracefully" is not a contract; neither is "the producer emits these
keys". The harness therefore drives every registered mutation through BOTH sides
and requires BOTH to react:

  PRODUCER SIDE  the mutated path must EXIST in what the real producer emitted.
                 A ``drop`` of a key the producer never writes is a no-op, and a
                 no-op mutation reds — that is precisely the consumer-reads-a-
                 field-nobody-writes half of the class.

  CONSUMER SIDE  feeding the mutated payload to the real consumer must CHANGE its
                 answer (or raise). A consumer whose output is byte-identical
                 with the field removed is not reading it — that is the
                 producer-writes-a-field-nobody-reads half.

So a pair that agrees only on paper fails in a named direction:
``PRODUCER SIDE`` or ``CONSUMER SIDE``, never a vague "contract broken".

THE PAYLOAD IS THE REAL PRODUCER'S OUTPUT, NEVER A LITERAL
-----------------------------------------------------------
``PairContract.produce`` must call the actual shipped producer (stubbing only the
transport — a fake ``table``/``s3_client`` that captures the item it was handed).
Hand-writing the payload is the defect this framework exists to catch, wearing a
test's costume: the fixture would then agree with the consumer by construction
while the wire went on disagreeing.

USAGE — enrollment is ONE registry entry
-----------------------------------------
    from pair_contract import Mutation, PairContract, register

    register(
        PairContract(
            name="input_manifest -> character page",
            producer="common.input_manifest::build_input_manifest",
            consumer="web.site_api_character::_public_input_manifest",
            partition="computed_metrics",       # or None for S3/ledger shapes
            produce=_produce_input_manifest,    # real producer -> real payload
            consume=_consume_input_manifest,    # real consumer over that payload
            agree=_agree_input_manifest,        # the round-trip invariant
            mutations=(
                Mutation(("status",), "drop", why="the manifest verdict itself"),
                Mutation(("sources", "whoop", "latest_day"), "retype", to="?"),
            ),
            note="#3049 / DIL-024 — the compute run's own input-freshness sheet.",
        )
    )

Seed entries live in ``tests/pair_contract_registry.py``; the sweep that drives
them is ``tests/test_pair_contract_sweep_2847.py``.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Tuple

#: Mutation kinds the harness knows how to apply. Deliberately small: every one
#: of them PERTURBS AN EXISTING PATH, so "the path was not there" is always a
#: producer-side finding rather than a silently-added key that fakes a diff.
DROP = "drop"
RENAME = "rename"
RETYPE = "retype"
KINDS = (DROP, RENAME, RETYPE)


class MutationNotApplicable(AssertionError):
    """The producer's real output has no such path — the PRODUCER SIDE red."""


class _Raised:
    """Sentinel for "the consumer raised" — a legitimate consumer-side reaction."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return f"<raised {type(self.exc).__name__}: {self.exc}>"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _Raised) and type(other.exc) is type(self.exc) and str(other.exc) == str(self.exc)

    def __hash__(self) -> int:  # pragma: no cover
        return hash((type(self.exc), str(self.exc)))


@dataclass(frozen=True)
class Mutation:
    """One disagreement, injected at a real path in the real producer output.

    ``path`` is a tuple of dict keys (``("sources", "whoop", "status")``). It must
    resolve in what the producer actually emitted — that requirement IS the
    producer-side half of the contract, not a convenience.
    """

    path: Tuple[Any, ...]
    kind: str = DROP
    to: Any = None
    why: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown mutation kind {self.kind!r}; expected one of {KINDS}")
        if not self.path:
            raise ValueError("a mutation needs a non-empty path")

    @property
    def label(self) -> str:
        dotted = ".".join(str(p) for p in self.path)
        return f"{self.kind}:{dotted}"


@dataclass(frozen=True)
class PairContract:
    """One producer/consumer pair that must agree about a shape.

    ``producer``/``consumer`` are ``module::qualname`` strings naming the REAL
    shipped functions — they are what the system model records and what a reader
    greps for. ``partition`` is the DDB partition the pair travels over when
    there is one, so the coverage walk can line the registry up against the
    #2845 model's edge plane; ``None`` for S3 artifacts and ledger rows that the
    partition census does not cover.
    """

    name: str
    producer: str
    consumer: str
    produce: Callable[[], Any]
    consume: Callable[[Any], Any]
    agree: Callable[[Any, Any], None]
    mutations: Sequence[Mutation] = field(default_factory=tuple)
    partition: Optional[str] = None
    note: str = ""

    @property
    def id(self) -> str:
        return self.name


#: The registry. Populated by ``register()`` from
#: ``tests/pair_contract_registry.py`` — one entry per enrolled pair.
PAIR_CONTRACT_REGISTRY: List[PairContract] = []


def register(pair: PairContract) -> PairContract:
    """Enroll a pair. Duplicate names are a registry error, not a silent overwrite."""
    if any(p.name == pair.name for p in PAIR_CONTRACT_REGISTRY):
        raise ValueError(f"duplicate pair contract name: {pair.name!r}")
    if not pair.mutations:
        raise ValueError(f"{pair.name!r} registered with no mutations — an unfalsifiable contract is not a contract")
    PAIR_CONTRACT_REGISTRY.append(pair)
    return pair


# ── the harness ──────────────────────────────────────────────────────────────


def _resolve(payload: Any, path: Tuple[Any, ...]) -> Tuple[Any, Any]:
    """(container, last_key) for ``path``, or raise MutationNotApplicable.

    Deliberately strict about the LAST key's presence: the whole producer-side
    assertion is "this path is really in the wire shape".
    """
    node = payload
    for key in path[:-1]:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise MutationNotApplicable(f"path {'.'.join(str(p) for p in path)} does not resolve at {key!r}: {exc}")
    last = path[-1]
    try:
        _present = last in node
    except TypeError as exc:
        raise MutationNotApplicable(f"path {'.'.join(str(p) for p in path)}: {type(node).__name__} is not a mapping ({exc})")
    if not _present:
        raise MutationNotApplicable(f"path {'.'.join(str(p) for p in path)}: {last!r} absent from the producer's output")
    return node, last


def apply_mutation(payload: Any, mutation: Mutation) -> Any:
    """Return a mutated deep copy. Raises MutationNotApplicable = PRODUCER SIDE red."""
    mutated = copy.deepcopy(payload)
    node, last = _resolve(mutated, mutation.path)
    if mutation.kind == DROP:
        del node[last]
    elif mutation.kind == RENAME:
        if not mutation.to:
            raise ValueError(f"{mutation.label}: a rename needs `to`")
        node[mutation.to] = node.pop(last)
    else:  # RETYPE
        if node[last] == mutation.to and type(node[last]) is type(mutation.to):
            raise ValueError(f"{mutation.label}: `to` equals the producer's own value — the mutation would be a no-op")
        node[last] = mutation.to
    return mutated


def consume_safely(pair: PairContract, payload: Any) -> Any:
    """Run the real consumer, capturing a raise as a first-class reaction.

    A consumer that RAISES on a broken shape is reacting correctly (see
    ``fingerprint_broadcast.build_broadcast``'s ``public["platform.days_in"]``);
    a consumer that returns the same answer is not reacting at all.
    """
    try:
        return pair.consume(payload)
    except Exception as exc:  # noqa: BLE001 — a raise IS the consumer-side signal
        return _Raised(exc)


def round_trip(pair: PairContract) -> Tuple[Any, Any]:
    """(real producer output, real consumer output over it)."""
    produced = pair.produce()
    consumed = pair.consume(produced)
    return produced, consumed
