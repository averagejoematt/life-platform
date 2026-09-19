#!/usr/bin/env python3
"""lambdas/experiment/pk_census.py — the ADR-077 pk-family totality census (#1234, #3860).

THE GUARANTEE
  `phase_taxonomy` claims TOTALITY: every live pk family classifies into exactly one of the
  four ADR-077 classes, so a reset can never let a partition silently survive. That claim is
  only as good as the check that enumerates the families. This module IS that enumeration:
  scan the live table (pk+sk only), reduce to distinct pk families, and run
  `phase_taxonomy.classify()` on a representative of each. Any family classify() cannot
  resolve is a totality violation.

WHY IT LIVES HERE AND NOT IN deploy/ (#3860)
  It was born inside `deploy/restart_pipeline.py`, which is a script and is NOT staged into
  the Lambda bundle — so the only thing that could ever run it was an operator typing a
  reset command. That is exactly how #3860 happened: `SOURCE#recap_cards` was created
  2026-09-06 and went unclassified for TEN DAYS with nothing saying so, because the only
  instrument that could see it ran only at reset time, and the reset it finally blocked was
  the first one attempted since.

  Moving it into `lambdas/experiment/` gives it ONE home with two callers:
    * `deploy/restart_pipeline.py` Step [0] — a hard preflight that ABORTS the reset.
    * `lambdas/operational/qa_smoke_lambda.py` — a nightly WARN, so an unclassified family
      is reported the day after it appears rather than at the moment someone needs a reset.
  Both delegate; neither reimplements. `tests/test_pk_census_one_home_3860.py` asserts the
  delegation rather than the mere presence of a call (the #3792 lesson: a caller that reads
  the shared helper and then re-derives beside it is the same drift with an import in front).

COST, MEASURED (not asserted)
  A full Scan consumes read units by the size of the items SCANNED, not by the projection —
  so the pk+sk ProjectionExpression keeps the payload small but not the RCU. Measured
  2026-09-17: 44,397 items / 65,385,373 bytes => ~7,982 eventually-consistent read request
  units => ~$0.001 per run at on-demand us-west-2 pricing. Nightly that is ~$0.03/month,
  which is why the scheduled leg is affordable at all; see docs/PROPORTIONALITY.md.

THE VACUOUS-SCAN TRAP
  A scan that returns nothing must NEVER be certified as "all families covered" — that is a
  check that cannot fail, reporting success. An empty census raises.
"""

from __future__ import annotations

import os

from experiment import phase_taxonomy as taxonomy

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")


class CensusPreflightError(RuntimeError):
    """A live pk family that phase_taxonomy.classify() cannot resolve (or an empty
    scan that cannot certify totality). Raised to FAIL the reset before any step."""


def pk_family(pk: str) -> str:
    """The family key at the granularity classify() itself decides at.

    Mirrors classify()'s keying WITHOUT importing its private helper: a
    USER#…#SOURCE#<source> pk folds to its base <source> (the part before the first '#'
    after the marker — sub-keys like email_log#<type> or training_notes#EXERCISE#<id>
    collapse to the base); every other pk folds to its top-level prefix (segment before the
    first '#'). So a NEW source OR a NEW top-level family (the next COACH#-like tier) each
    surface as a distinct family whose representative classify() must resolve.
    """
    marker = "#SOURCE#"
    idx = pk.find(marker)
    if idx != -1:
        base = pk[idx + len(marker) :].split("#", 1)[0]
        return f"SOURCE#{base}"
    return pk.split("#", 1)[0]


def scan_pk_sk_pages(table):
    """Yield each page of a FULL-table scan projecting ONLY pk + sk. Paginated and
    kept a generator so a unit test can feed synthetic pages with no AWS. The
    projection keeps the payload cheap (two string attributes per item)."""
    kwargs = {"ProjectionExpression": "pk, sk"}
    while True:
        resp = table.scan(**kwargs)
        yield resp.get("Items", [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek


def census_families(pages) -> dict:
    """Reduce scanned (pk, sk) items to distinct pk families → one representative
    (pk, sk) each (first seen wins). `pages` is an iterable of item-lists (the
    scan_pk_sk_pages generator, or synthetic pages in a test)."""
    reps: dict = {}
    for page in pages:
        for item in page:
            fam = pk_family(item.get("pk", ""))
            reps.setdefault(fam, (item.get("pk", ""), item.get("sk", "")))
    return reps


def census_pks_with_prefix(pages, prefix: str) -> dict:
    """Distinct FULL pks under `prefix` -> a representative sk (first seen wins).

    `pk_family()` above deliberately folds every `COACH#*` pk to the single family
    "COACH". That is the right granularity for the TOTALITY question ("does classify()
    resolve this family?") and the wrong one for the COVERAGE question ("is this
    PARTITION in the wipe's covered set?"): a partition can classify perfectly and still
    be one nothing wipes.

    #3514 (DA-2) is exactly that gap. `COACH#nudge_ledger` and `COACH#outbound_ledger`
    classified fine — the blanket `COACH#*` rule answered for them — and sat outside
    COACH_PARTITIONS for three cycles, because the only live enumeration the reset ran
    folded them into the same "COACH" family as the eight real coaches. This function is
    the finer enumeration, over the SAME scan pages, so it costs no extra read units.

    `pages` is the `scan_pk_sk_pages` generator or synthetic pages in a test.
    """
    reps: dict = {}
    for page in pages:
        for item in page:
            pk = item.get("pk", "")
            if pk.startswith(prefix):
                reps.setdefault(pk, item.get("sk", ""))
    return reps


def live_scoped_pks(prefix: str, table=None) -> dict:
    """The live pks under `prefix` whose class is EXPERIMENT_SCOPED -> representative sk.

    The derivation `assert_registry_coverage` consumes: a partition in here that the wipe
    does not cover is a partition a reset would silently leave behind. READ-ONLY.

    A pk the taxonomy cannot classify is NOT silently dropped — it is left out of the
    scoped set here (the totality census above is the instrument that reports it, and it
    aborts the same reset), so this function never has to decide what an unknown class
    means. Two instruments, one scan, neither guessing for the other.
    """
    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    reps = census_pks_with_prefix(scan_pk_sk_pages(table), prefix)
    if not reps:
        raise CensusPreflightError(
            f"pk census: the pk+sk scan returned ZERO pks under {prefix!r}. Refusing to certify "
            "wipe coverage on an empty enumeration (the vacuous-scan trap)."
        )
    out: dict = {}
    for pk, sk in sorted(reps.items()):
        try:
            if taxonomy.classify(pk, sk) == taxonomy.EXPERIMENT_SCOPED:
                out[pk] = sk
        except KeyError:
            continue
    return out


def unresolved_families(table=None) -> tuple[list[tuple[str, str, str, str]], int]:
    """The census as DATA rather than as an exception: return
    ``(unresolved, family_count)`` where each unresolved entry is
    ``(family, rep_pk, rep_sk, classify_error)``.

    This is the shared core. `run_census_preflight()` below turns a non-empty
    `unresolved` into the reset-aborting CensusPreflightError; the nightly QA check turns
    the same list into a WARN. Two verdicts, ONE derivation — so the nightly check can
    never disagree with the reset gate about what is classified.

    Raises CensusPreflightError on an EMPTY census in BOTH callers deliberately: a
    vacuous scan is a failure of the instrument, not a clean bill of health, and a
    nightly check that reports "all clear" on a broken scan is worse than no check.
    READ-ONLY (never writes).
    """
    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    reps = census_families(scan_pk_sk_pages(table))
    if not reps:
        raise CensusPreflightError(
            "pk-family census: the pk+sk scan returned ZERO pk families. "
            "Refusing to certify taxonomy totality on an empty census (the vacuous-scan trap) — "
            "the scan must actually classify live families, not silently pass an empty set."
        )
    unresolved: list[tuple[str, str, str, str]] = []
    for fam, (pk, sk) in sorted(reps.items()):
        try:
            taxonomy.classify(pk, sk)
        except KeyError as e:
            unresolved.append((fam, pk, sk, str(e)))
    return unresolved, len(reps)


def census_snapshot(table=None) -> dict:
    """The census AS A COMMITTABLE ARTIFACT — `{generated_at, family_count, families}`
    where each family carries its representative row and the class it resolved to.

    #3514 (DA-10): `docs/SCHEMA.md` is named "authoritative" in CLAUDE.md and drifts from
    the live table with nothing to stop it — the 2026-08-22 pass (#2810) hand-closed the
    same gap and left no ratchet, so it reopened. A CI gate cannot ask DynamoDB (no
    credentials at PR time), so the derivation is split: this writes the live family list
    to `deploy/generated/pk_family_census.json` when someone HAS credentials (the reset's
    Step [0], or `python3 deploy/write_pk_family_census.py`), and CI grades SCHEMA.md
    against that committed artifact. The gate's number is therefore always a MEASURED one,
    just not a live one — and the artifact carries `generated_at` so a reader can see how
    old the measurement is instead of trusting a hand-typed list.

    READ-ONLY against DynamoDB (the caller writes the file).
    """
    from datetime import datetime, timezone

    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    # #3669: `item_count` is the artifact's anti-vacuity signal and it can only be taken
    # HERE, while the pages stream past — `census_families` reduces them to one
    # representative per family, so by the time it returns the scan's size is gone. A
    # family_count alone cannot distinguish a healthy table from a scan truncated after
    # its first page, because both can surface the same handful of families.
    _scanned = [0]

    def _counting(pages):
        for page in pages:
            _scanned[0] += len(page)
            yield page

    reps = census_families(_counting(scan_pk_sk_pages(table)))
    if not reps:
        raise CensusPreflightError(
            "pk-family census snapshot: the pk+sk scan returned ZERO pk families. Refusing to "
            "write an empty census artifact (the vacuous-scan trap) — a gate graded against it "
            "would pass by having nothing to check."
        )
    families = {}
    for fam, (pk, sk) in sorted(reps.items()):
        try:
            cls = taxonomy.classify(pk, sk)
        except KeyError:
            cls = None  # unresolved; run_census_preflight is the instrument that RULES on this
        families[fam] = {"rep_pk": pk, "rep_sk": sk, "class": cls}
    n_families = len(families)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Live pk-family census (#3514). Regenerate with deploy/write_pk_family_census.py.",
        "family_count": n_families,
        "families": families,
        # #3669: the provenance block. `family_count` is repeated inside `_meta` rather
        # than cross-referenced because the two are one expression evaluated once, so they
        # cannot drift; a reader grading the artifact should not have to know which of the
        # two levels is authoritative. `table`/`region` catch the "right shape, wrong
        # table" failure that reads as all-clear, and `item_count` catches the truncated
        # scan that `family_count` alone cannot see.
        "_meta": {
            "generated_by": (
                "lambdas/experiment/pk_census.py::census_snapshot via " "deploy/write_pk_family_census.py — never hand-edit this artifact"
            ),
            "table": TABLE,
            "region": REGION,
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "item_count": _scanned[0],
            "family_count": n_families,
        },
    }


def format_unresolved(unresolved: list[tuple[str, str, str, str]]) -> str:
    """One line per unresolved family, naming the family, its representative row and the
    classifier's own message — so the reader is told WHICH partition and WHAT to add."""
    return "\n".join(f"    family={f!r}  rep_pk={p!r}  sk={s!r}  ::  {msg}" for f, p, s, msg in unresolved)


def run_census_preflight(table=None) -> int:
    """The RESET-TIME verdict: raise CensusPreflightError on any unresolved family (or an
    empty census), else return the number of families verified. READ-ONLY (never writes)."""
    unresolved, count = unresolved_families(table)
    if unresolved:
        raise CensusPreflightError(
            f"restart_pipeline census preflight: {len(unresolved)} live pk family/families are "
            "UNCLASSIFIED by phase_taxonomy — a reset would let them silently survive (ADR-077 "
            "totality violation). Add each to phase_taxonomy (SOURCE_CLASS or _PK_RULES) AND the "
            "wipe's PARTITIONS/coverage before re-running:\n" + format_unresolved(unresolved)
        )
    return count
