"""tests/pair_seam_guard_lib.py — the must-agree seam sweep (#2847 box 4, epic #2842).

The fleet-wide form of **charter standing rule 3** — *every new "must agree" pair
gets a contract test at birth* — and the peer of #2844, which is the fleet-wide
form of standing rule 1. Same three mechanics, different derivation:

    #2844   derivation = AST sweep for hand-typed registry vocabulary
            ledger     = tests/conformance_residue.py (dated, shrink-only)
            verdict    = a NEW hand-typed enumeration reds

    this    derivation = the #2845 model's edge plane -> must-agree seams
            ledger     = tests/pair_seam_residue.py (dated, shrink-only)
            verdict    = a NEW must-agree seam with no contract reds

WHY A SEAM AND NOT A PAIR
-------------------------
A "pair" is (partition, writer, reader). Taking the cross-product gives 627 pairs
today, and one new reader on a partition with ten writers would raise ten findings
for one code change. The minimal generator of new pairs is the **seam**:

    seam = (partition, module, direction)   with direction in {write, read}

A seam is *pair-forming* when the partition has at least one counterpart module on
the other side — i.e. the moment this module joined, real pairs came into being.
One new seam is one code change; the failure message enumerates the concrete pairs
it created. Enrolling a ``PairContract`` whose producer/consumer names that module
on that partition **covers** the seam, so enrolling a contract takes rows OUT of
the ledger — that is the ratchet's countdown path, and it is what makes this the
enforcement of box 4 rather than a bystander gate.

THE BASELINE IS A PIN, NOT A DEBT CLAIM
---------------------------------------
``tests/pair_seam_residue.py`` grandfathers the seams that existed on 2026-08-25.
It is deliberately NOT framed as debt: contracting all 286 of them is neither the
goal nor proportionate (ADR-103/144). The instrument's whole job is that the 287th
is a **decision** — enroll it, or write one dated line saying why the two sides
cannot disagree. That is exactly what standing rule 3 asks for, and nothing more.

Why this is not #3169's rejected shape: PR #3169 declined *"a per-candidate
exemption ledger — 299 rows of ceremony written by a model that cannot ground a
single one of them"*, i.e. a **reason per candidate**. The baseline below carries
no reasons; every row is one grounded model edge, and reasons are demanded only at
the delta. And it is not "a gate that fires on partition adjacency" either: it
fires on a partition adjacency that **did not exist before this change**, which is
the birth event standing rule 3 names.

WHAT IT CANNOT SEE (stated, and blind-green-guarded)
----------------------------------------------------
The model resolves 824 of 1138 edge sites; the remaining ~28% are dynamic (a read
routed through a ``fetch_date(src, ...)``-style helper resolves to no literal
partition). A new seam behind such a helper is invisible here — the same posture
#2844 takes when it says field names wait on the #2797 wiring registry. The blind-
green guard in the test module pins that resolution ratio, so an extractor
regression that quietly widened the blind spot reds instead of greening.

THE MODEL IS BUILT LIVE, NEVER READ FROM THE COMMIT
----------------------------------------------------
``model/platform_model.json`` is regenerated in batches — ``git log`` on it shows
``chore(model): regenerate the platform model after tonight's 20 merges``. A guard
reading the committed file would therefore be DARK on precisely the PR that
introduces the seam and would red on the unrelated reconcile commit days later.
So the sweep calls ``generate_platform_model.build_model()`` itself (~6s, cached
per process). ``test_platform_model_drift.py`` keeps the committed artifact honest;
this guard does not depend on it having run.
"""

from __future__ import annotations

import collections
import functools
import os
import sys
from typing import Any, Dict, Iterable, List, Set, Tuple

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "scripts"), os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

WRITE = "write"
READ = "read"


@functools.lru_cache(maxsize=1)
def live_model() -> Dict[str, Any]:
    """Build the #2845 model from source (never the committed artifact — see module docstring)."""
    import generate_platform_model as gen

    return gen.build_model()


def writers_and_readers(model: Dict[str, Any]) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """{partition: {module}} for each direction. ``unknown`` edges are not seams."""
    writers: Dict[str, Set[str]] = collections.defaultdict(set)
    readers: Dict[str, Set[str]] = collections.defaultdict(set)
    for edge in model["edges"]:
        if edge["direction"] == WRITE:
            writers[edge["partition"]].add(edge["module"])
        elif edge["direction"] == READ:
            readers[edge["partition"]].add(edge["module"])
    return writers, readers


def seam_key(partition: str, module: str, direction: str) -> str:
    """Content-keyed seam identity — moving/renaming the module is a NEW seam, deliberately."""
    return f"{partition}::{module}::{direction}"


def pair_forming_seams(model: Dict[str, Any] | None = None) -> Dict[str, List[str]]:
    """{seam_key: sorted counterpart modules} for every seam that creates real pairs.

    A module that both writes and reads a partition nobody else touches forms no
    pair with anyone — ``{m} - {m}`` is empty and it never appears here.
    """
    writers, readers = writers_and_readers(model if model is not None else live_model())
    seams: Dict[str, List[str]] = {}
    for partition in sorted(set(writers) | set(readers)):
        wr, rd = writers.get(partition, set()), readers.get(partition, set())
        for module in sorted(wr):
            counterparts = rd - {module}
            if counterparts:
                seams[seam_key(partition, module, WRITE)] = sorted(counterparts)
        for module in sorted(rd):
            counterparts = wr - {module}
            if counterparts:
                seams[seam_key(partition, module, READ)] = sorted(counterparts)
    return seams


def module_path(qualname: str) -> str:
    """``compute.adaptive_mode_lambda::store_adaptive_mode`` -> ``lambdas/compute/adaptive_mode_lambda.py``.

    ``PairContract`` names its two sides the way the runtime imports them (the
    bundle stages ``lambdas/`` at the zip root, ADR-146); the model names modules
    by repo-relative path. This is the one translation between them, and a silent
    mismatch here would make ``enrolled_coverage`` match nothing — the ratchet
    would lose its downward gear with no test noticing. Two guards in the test
    module pin it: the two known translations, and "every enrolled contract's two
    sides resolve to real files".

    ``mcp.tools_x`` is handled because the model spans ``mcp/`` too (its modules
    appear in the seam census today); no contract names one yet, and if one does,
    it must not silently resolve under ``lambdas/``.
    """
    dotted = qualname.split("::")[0]
    root = "" if dotted.split(".")[0] == "mcp" else "lambdas/"
    return root + dotted.replace(".", "/") + ".py"


def enrolled_coverage(registry: Iterable[Any]) -> Set[str]:
    """Seam keys already carried by an enrolled ``PairContract``.

    A contract covers its producer's WRITE seam and its consumer's READ seam on its
    partition. Contracts with ``partition=None`` (S3 artifacts, ledger rows) travel
    over no modeled partition and cover nothing here — by design, not by omission.
    """
    covered: Set[str] = set()
    for pair in registry:
        if not getattr(pair, "partition", None):
            continue
        covered.add(seam_key(pair.partition, module_path(pair.producer), WRITE))
        covered.add(seam_key(pair.partition, module_path(pair.consumer), READ))
    return covered


def sweep(model: Dict[str, Any] | None = None, registry: Iterable[Any] | None = None) -> Dict[str, List[str]]:
    """{seam_key: counterparts} for every pair-forming seam NOT covered by a contract.

    The ledger is subtracted by the guard test, not here — so the sweep's own
    result stays the honest census and the two ratchet directions can both be
    asserted against it.
    """
    if registry is None:
        import pair_contract_registry  # noqa: F401 — importing populates the registry
        from pair_contract import PAIR_CONTRACT_REGISTRY

        registry = PAIR_CONTRACT_REGISTRY
    seams = pair_forming_seams(model)
    covered = enrolled_coverage(registry)
    return {key: counterparts for key, counterparts in seams.items() if key not in covered}


def ledger_defects(
    baseline: Dict[str, str],
    exemptions: Dict[str, Tuple[str, str]],
    seed_date: str,
    reason_floor: int,
    ceiling: int,
) -> List[str]:
    """Everything wrong with the ledger's OWN shape, as human lines.

    Lives here rather than inline in the guard test on purpose: on a healthy
    ledger every branch below is unreachable, so asserted inline it would be a
    check nobody has ever seen run. As a function it is driven by synthetic
    ledgers in the self-tests, which is the difference between a rule and a
    rule-shaped comment.
    """
    out: List[str] = []
    if len(baseline) > ceiling:
        out.append(f"the frozen baseline grew to {len(baseline)} rows (ceiling {ceiling}) — it may only shrink")
    for key, date in sorted(baseline.items()):
        if date != seed_date:
            out.append(
                f"{key}: baseline row dated {date}, not the frozen seed date {seed_date} — a later seam needs an exemption, not a baseline row"
            )
    for key, value in sorted(exemptions.items()):
        if not (isinstance(value, tuple) and len(value) == 2):
            out.append(f"{key}: exemptions are (date, reason) tuples, got {value!r}")
            continue
        date, reason = value
        if date < seed_date:
            out.append(f"{key}: exemption dated {date} predates the seed date — it belongs in the baseline")
        if len(str(reason).strip()) < reason_floor:
            out.append(
                f"{key}: reason is {len(str(reason).strip())} chars, under the {reason_floor}-char floor — state WHY the two sides cannot disagree"
            )
    return out


def describe(key: str, counterparts: List[str]) -> str:
    """One human line: what this seam is and who it now has to agree with."""
    partition, module, direction = key.split("::")
    verb = "writes" if direction == WRITE else "reads"
    other = "read by" if direction == WRITE else "written by"
    shown = ", ".join(counterparts[:4]) + (f" (+{len(counterparts) - 4} more)" if len(counterparts) > 4 else "")
    return f"  {module} {verb} `{partition}`, {other}: {shown}\n      key: {key}"


if __name__ == "__main__":  # pragma: no cover — re-seeding aid, see pair_seam_residue.py
    print("PAIR_SEAM_BASELINE: dict[str, str] = {")
    for _key in sorted(sweep()):
        print(f'    "{_key}": "SEED_DATE",')
    print("}")
