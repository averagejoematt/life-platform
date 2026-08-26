"""tests/test_pair_seam_conformance_2847.py — box 4 of #2847 (epic #2842).

*"Adding a pair without a contract test is a conformance finding (the kernel
conformance guard)."*

WHAT THIS IS, AND WHY IT IS HERE RATHER THAN INSIDE #2844
---------------------------------------------------------
PR #3169 shipped the #2847 framework and left box 4 partial with a stated blocker:
routing new-pair detection into ``tests/test_conformance_guard_2844.py`` would be a
**category error**. That reading is correct and stands — #2844's derivation is an
AST sweep for literal string sequences drawn from a registry *vocabulary*. "These
two modules must agree about a shape" is not a vocabulary-membership question;
there is no token to match, and bolting a fifth "vocabulary" onto that sweep would
have distorted the guard to host something it does not mechanise.

But "the kernel conformance guard" in the box's language is the **fleet-wide
enforcement of a charter standing rule**, and #2844 is one instance of it, not the
whole of it:

    standing rule 1  no hand-maintained enumeration of registry vocabulary
                     -> #2844   tests/test_conformance_guard_2844.py
    standing rule 3  every new "must agree" pair gets a contract test AT BIRTH
                     -> THIS     tests/test_pair_seam_conformance_2847.py

#2846 already set that precedent (``tests/lambda_enrollment_ledger.py``: same three
mechanics, own derivation, own file, peer of #2844 rather than a row inside it).
So box 4 is routable — as a peer in the guard family, on a derivation the #2845
model can actually ground. The mechanics are identical and deliberately so: a
derived sweep, a dated shrink-only ledger, and both ratchet directions asserted.

THE DERIVATION (tests/pair_seam_guard_lib.py)
----------------------------------------------
A **seam** is ``(partition, module, direction)``. It is *pair-forming* when the
partition has a counterpart module on the other side — the moment that module
joined, real must-agree pairs came into being. The seam, not the pair, is the unit:
one new reader on a partition with ten writers is ONE code change, and would
otherwise raise ten findings. Enrolling a ``PairContract`` naming that module on
that partition COVERS the seam and takes its row out — which is what makes this the
enforcement of box 4 and not a bystander gate standing next to the registry.

WHAT IT CANNOT SEE
------------------
The model resolves 824 of 1138 edge sites; a read routed through a
``fetch_date(src, ...)``-style helper resolves to no literal partition and its seam
is invisible here. Stated, not hidden — and ``test_the_model_edge_resolution_has_
not_collapsed`` pins the ratio so the blind spot cannot quietly widen. Same posture
#2844 takes about field names waiting on #2797.

MUTATION EVIDENCE (CONVENTIONS §9: a gate that cannot fail is a green light wired
to nothing) — the synthetic-model proofs at the bottom drive the SAME sweep the
fleet uses and assert it reds on a new reader, reds on a new writer, and goes quiet
the moment a contract covers the seam. The end-to-end proof against a real module +
a live model regeneration is in the PR body.

Run:  python3 -m pytest tests/test_pair_seam_conformance_2847.py -v
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "tests"), os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pair_contract_registry  # noqa: E402,F401 — importing populates the registry
import pair_seam_guard_lib as lib  # noqa: E402
from pair_contract import PAIR_CONTRACT_REGISTRY  # noqa: E402
from pair_seam_residue import PAIR_SEAM_BASELINE, PAIR_SEAM_EXEMPTIONS, SEED_DATE  # noqa: E402

_REASON_FLOOR = 40  # the #2846 bar: a dated exemption's reason must be an argument
_BASELINE_CEILING = 286  # the seed census — the frozen baseline may only shrink

_FIX = (
    "Enroll the pair in tests/pair_contract_registry.py (one register(PairContract(...)) call,\n"
    "two-sided mutation proof — see tests/pair_contract.py), or add the seam key to\n"
    "PAIR_SEAM_EXEMPTIONS in tests/pair_seam_residue.py with the date and the VERIFIED\n"
    "reason the two sides cannot disagree about the shape."
)


# ══════════════════════════════════════════════════════════════════════════════
# The ratchet — both directions
# ══════════════════════════════════════════════════════════════════════════════


def test_no_new_must_agree_seam_lands_without_a_contract_or_a_dated_reason():
    """Ratchet direction 1 — charter standing rule 3, enforced fleet-wide.

    A red here means this change made a module a new participant in a shape another
    module already depends on. That is the birth event the rule names; the green
    path is a contract, not a bigger baseline.
    """
    findings = lib.sweep()
    dispositioned = set(PAIR_SEAM_BASELINE) | set(PAIR_SEAM_EXEMPTIONS)
    new = sorted(set(findings) - dispositioned)
    assert not new, (
        f"{len(new)} new must-agree seam(s) with no producer/consumer contract (#2847 box 4).\n"
        + _FIX
        + "\n\n"
        + "\n".join(lib.describe(key, findings[key]) for key in new)
    )


def test_ledger_has_no_dead_entries():
    """Ratchet direction 2 — a seam that is gone (or now contracted) must leave the ledger.

    This is the countdown half. Enrolling a ``PairContract`` covers its two seams,
    which drops them out of the sweep, which reds HERE until the baseline rows come
    out — so enrollment is forced to shrink the ledger rather than sit beside it.
    """
    findings = lib.sweep()
    dead = sorted((set(PAIR_SEAM_BASELINE) | set(PAIR_SEAM_EXEMPTIONS)) - set(findings))
    assert not dead, (
        "tests/pair_seam_residue.py pins seam(s) the sweep no longer finds — delete them "
        "(the ratchet counts down; a contracted seam's row comes OUT):\n  " + "\n  ".join(dead)
    )


def test_the_ledger_itself_is_well_formed():
    """The baseline is a grandfather PIN, not a growable escape hatch.

    Two rules, one check: every baseline value is the frozen seed date and the
    count may only shrink (otherwise "add a row to PAIR_SEAM_BASELINE" is a
    reasonless green path around ratchet direction 1 — the move #2844's
    content-keying exists to make impossible), and every post-seed exemption
    carries an argued reason (#2846's 40-character floor).

    The rules live in ``lib.ledger_defects`` so they can be mutation-proved on
    synthetic ledgers below; on a healthy ledger they are all unreachable, and an
    unreachable assertion asserted inline is a check nobody has seen run.
    """
    defects = lib.ledger_defects(PAIR_SEAM_BASELINE, PAIR_SEAM_EXEMPTIONS, SEED_DATE, _REASON_FLOOR, _BASELINE_CEILING)
    assert not defects, "tests/pair_seam_residue.py is malformed:\n  " + "\n  ".join(defects)


def test_enrolling_a_contract_really_does_remove_seam_rows():
    """The countdown path, proven on the LIVE registry rather than asserted in prose.

    If ``enrolled_coverage`` matched nothing, every test above would still be green
    and the ledger would simply never shrink — a ratchet with no downward gear.
    """
    covered = lib.enrolled_coverage(PAIR_CONTRACT_REGISTRY)
    seams = lib.pair_forming_seams()
    live = covered & set(seams)
    assert live, "no enrolled PairContract covers a modeled seam — the coverage join is dead"
    assert not (live & set(lib.sweep())), "a seam covered by an enrolled contract still appears in the sweep"
    assert not (live & set(PAIR_SEAM_BASELINE)), "a contracted seam is still pinned in the baseline — prune it"


# ══════════════════════════════════════════════════════════════════════════════
# Blind-green guards (#2640) — the derivation must be real and must stay real
# ══════════════════════════════════════════════════════════════════════════════


def test_the_seam_derivation_is_not_vacuous():
    """A sweep that silently found nothing would green every ratchet above."""
    seams = lib.pair_forming_seams()
    partitions = {key.split("::")[0] for key in seams}
    assert len(seams) >= 200, f"the must-agree seam census collapsed to {len(seams)} seams"
    assert len(partitions) >= 30, f"only {len(partitions)} partitions have a cross-module seam"


def test_the_model_edge_resolution_has_not_collapsed():
    """Pin the known blind spot so it cannot quietly widen.

    Every unresolved edge site is a seam this guard cannot see. 824/1138 = 72% on
    2026-08-25; an extractor regression that dropped resolution would make the sweep
    progressively darker while every assertion above stayed green.
    """
    sites = lib.live_model()["meta"]["coverage"]["edge_sites"]
    ratio = sites["sites_resolved"] / sites["sites_total"]
    assert ratio >= 0.65, f"the model resolves only {ratio:.0%} of edge sites (was 72% when this guard landed)"


# ══════════════════════════════════════════════════════════════════════════════
# Mutation proof — synthetic models through the SAME sweep the fleet uses
# ══════════════════════════════════════════════════════════════════════════════


def _model(*edges):
    return {"edges": [{"partition": p, "module": m, "direction": d} for p, m, d in edges]}


class _Pair:
    def __init__(self, partition, producer, consumer):
        self.partition, self.producer, self.consumer = partition, producer, consumer


_EXISTING = ("widgets", "lambdas/compute/widget_writer.py", "write")


def test_a_new_reader_on_a_written_partition_is_a_finding():
    """The #2804 dead-zone-read birth event: a consumer joins a shape it did not before."""
    found = lib.sweep(_model(_EXISTING, ("widgets", "lambdas/web/site_api_new.py", "read")), registry=[])
    assert lib.seam_key("widgets", "lambdas/web/site_api_new.py", "read") in found
    assert lib.seam_key(*_EXISTING) in found, "the existing writer becomes pair-forming at the same moment"


def test_a_new_writer_on_a_read_partition_is_a_finding():
    """The #2214 dual-writer birth event, generalised past the contracted partitions."""
    base = (("widgets", "lambdas/web/site_api_new.py", "read"), _EXISTING)
    found = lib.sweep(_model(*base, ("widgets", "lambdas/compute/second_writer.py", "write")), registry=[])
    assert lib.seam_key("widgets", "lambdas/compute/second_writer.py", "write") in found


def test_an_enrolled_contract_silences_exactly_its_two_seams():
    """The other half of the mutation: enrolled -> quiet. Only the contracted seams go."""
    edges = (_EXISTING, ("widgets", "lambdas/web/site_api_new.py", "read"), ("widgets", "lambdas/web/other.py", "read"))
    contract = _Pair("widgets", "compute.widget_writer::store", "web.site_api_new::render")
    found = lib.sweep(_model(*edges), registry=[contract])
    assert lib.seam_key("widgets", "lambdas/compute/widget_writer.py", "write") not in found
    assert lib.seam_key("widgets", "lambdas/web/site_api_new.py", "read") not in found
    assert lib.seam_key("widgets", "lambdas/web/other.py", "read") in found, "an uncontracted third party must still red"


def test_a_partition_one_module_writes_and_reads_alone_forms_no_pair():
    """No counterpart, no agreement to break — a private partition is not a seam."""
    solo = (("scratch", "lambdas/compute/solo.py", "write"), ("scratch", "lambdas/compute/solo.py", "read"))
    assert lib.sweep(_model(*solo), registry=[]) == {}


def test_a_write_only_or_read_only_partition_forms_no_pair():
    """Nobody on the other side yet — the pair is born when the counterpart arrives."""
    assert lib.sweep(_model(_EXISTING), registry=[]) == {}
    assert lib.sweep(_model(("widgets", "lambdas/web/only_reader.py", "read")), registry=[]) == {}


def test_unknown_direction_edges_are_never_seams():
    """The model's ``unknown`` direction is 'a partition reference outside a recognised
    read/write' — treating it as either side would invent agreements that do not exist."""
    edges = (_EXISTING, ("widgets", "lambdas/web/vague.py", "unknown"))
    assert lib.sweep(_model(*edges), registry=[]) == {}


def test_moving_a_module_re_reds_its_seam():
    """Content-keyed like #2844: relocating a participant is a new participant.

    ADR-146's packaging moves are exactly when a consumer quietly stops matching the
    shape it was written against, so an inherited exemption is the wrong default.
    """
    edges = (_EXISTING, ("widgets", "lambdas/web/site_api_new.py", "read"))
    moved = (_EXISTING, ("widgets", "lambdas/content/site_api_new.py", "read"))
    assert set(lib.sweep(_model(*edges), registry=[])) != set(lib.sweep(_model(*moved), registry=[]))


def test_a_contract_with_no_partition_covers_nothing():
    """S3-artifact and ledger-row pairs travel over no modeled partition — by design."""
    contract = _Pair(None, "content.site_writer::write_public_stats", "content.fingerprint_broadcast::project_public")
    assert lib.enrolled_coverage([contract]) == set()


def _defects(baseline, exemptions, ceiling=10):
    return lib.ledger_defects(baseline, exemptions, SEED_DATE, _REASON_FLOOR, ceiling)


def test_ledger_rules_red_on_a_baseline_row_smuggled_in_with_a_later_date():
    """The escape hatch, closed: a new seam cannot be grandfathered after the fact."""
    assert _defects({"p::m::read": "2026-09-01"}, {}) and not _defects({"p::m::read": SEED_DATE}, {})


def test_ledger_rules_red_when_the_frozen_baseline_grows():
    """A pin that could grow is not a pin."""
    rows = {f"p{i}::m::read": SEED_DATE for i in range(11)}
    assert _defects(rows, {}, ceiling=10)
    assert not _defects(rows, {}, ceiling=11)


def test_ledger_rules_red_on_a_label_instead_of_an_argument():
    """#2846's floor: "not load-bearing" is a label, not a reason."""
    assert _defects({}, {"p::m::read": ("2026-09-01", "not load-bearing")})
    long_enough = "the consumer re-derives every field it reads from the raw row, so a producer rename cannot reach it"
    assert not _defects({}, {"p::m::read": ("2026-09-01", long_enough)})


def test_ledger_rules_red_on_a_malformed_or_backdated_exemption():
    assert _defects({}, {"p::m::read": "2026-09-01"}), "a bare string is not a (date, reason) row"
    backdated = ("2026-08-01", "a reason long enough to clear the forty character argued-reason floor easily")
    assert _defects({}, {"p::m::read": backdated}), "an exemption predating the seed date belongs in the baseline"


def test_every_enrolled_contract_resolves_to_real_modules():
    """A contract whose sides do not resolve would cover nothing, silently.

    ``enrolled_coverage`` is a set-membership join on strings: a translation that
    produced ``lambdas/mcp/tools_x.py`` for an mcp-side contract would simply match
    no seam, and the only symptom would be a ledger that never counts down. This
    turns that into a red on the PR that adds such a contract.
    """
    unresolved = []
    for pair in PAIR_CONTRACT_REGISTRY:
        for role, qualname in (("producer", pair.producer), ("consumer", pair.consumer)):
            rel = lib.module_path(qualname)
            if not os.path.isfile(os.path.join(_REPO, rel)):
                unresolved.append(f"  {pair.name} [{role}] {qualname} -> {rel} (no such file)")
    assert not unresolved, "enrolled contract side(s) that do not resolve to a real module:\n" + "\n".join(unresolved)


@pytest.mark.parametrize(
    "qualname,expected",
    [
        ("compute.adaptive_mode_lambda::store_adaptive_mode", "lambdas/compute/adaptive_mode_lambda.py"),
        ("web.site_api_freshness::presence", "lambdas/web/site_api_freshness.py"),
        ("mcp.tools_health::get_daily_snapshot", "mcp/tools_health.py"),
    ],
)
def test_the_qualname_to_model_path_translation_is_exact(qualname, expected):
    """The one translation between the registry's import names and the model's paths.

    A silent mismatch here would make ``enrolled_coverage`` match nothing and the
    countdown gear would vanish without any test noticing.
    """
    assert lib.module_path(qualname) == expected
    assert os.path.isfile(os.path.join(_REPO, expected)), f"{expected} is not a real module"
