"""journal_row_contract.py — the co-owned attribute contract for a Notion journal row (#4677).

A journal row (`USER#<u>#SOURCE#notion` / `DATE#<d>#journal#<channel>[#<suffix>]`) has more
than one writer:

  - notion-journal-ingestion builds the row FROM SCRATCH out of what Notion sent and
    put_items it — on first sight of a page and again every time the page is edited;
  - other pipelines then MERGE their own attributes onto that row with a narrow
    update_item, after ingestion.

A from-scratch put erases everything a merging writer added. #502 found that for the
enricher, #4631 for a page changing key, and #4677 for the vocal metrics: the carried set
was a hand list of two prefixes inside the ingest function, so the third writer onto the
row was erased by the next edit of the page — and nothing recomputes those fields, their
input lives outside the repo. Same class as `compute/computed_metrics_contract.py` (#3443).

THE CONTRACT. Every pipeline that adds attributes to a journal row after ingestion is
declared in `JOURNAL_ROW_COWRITERS`, once, with the attribute families it owns. The
ingester carries exactly the union of those families across every rewrite of a row; it
holds no list of its own. `tests/test_journal_row_cowriters_4677.py` holds both sides:

  - the SET guard — a module that names the journal partition and issues a DynamoDB write
    must be a declared co-writer or carry a stated reason why it is not one;
  - the derivation guard — each declared co-writer's REAL update expression is driven and
    every attribute it writes must fall inside the families declared for it here.

Carrying is preservation, not merging. Only an attribute the fresh item does NOT hold is
copied, so a value Notion just sent is never replaced by a stored one, and nothing outside
the declared families is copied at all: a vendor field Notion stopped sending disappears
from the row, exactly as the vendor now states it.

NOT CARRIED, deliberately: `phase`. The phase taggers (`deploy/restart_phase_tag.py`,
`deploy/phase_stamp_sweep.py`) set it on rows of every raw partition, but it is a pure
function of the row's date, and the ingester re-derives it on each write (`_stamp_phase`).

Pure: no boto3, no I/O, no clock.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CoWriter:
    """One pipeline that merges attributes onto a journal row after ingestion.

    ``module`` is the repo-relative file holding the write, or None for a writer that no
    longer runs but whose attributes stored rows still carry. ``families`` are attribute
    name prefixes; the writer owns every attribute that starts with one of them.
    """

    name: str
    module: str | None
    families: tuple[str, ...]
    recomputed_by: str


JOURNAL_ROW_COWRITERS = (
    CoWriter(
        name="journal-enrichment",
        module="lambdas/ingestion/journal_enrichment_lambda.py",
        families=("enriched_",),
        recomputed_by="the enricher itself, on its next run after an edit (enriched_at older than notion_last_edited)",
    ),
    CoWriter(
        name="vocal-metrics-backfill",
        module="scripts/backfill_vocal_metrics.py",
        families=("vocal_",),
        recomputed_by="nothing automatic — an owner-run script whose input files live outside the repo",
    ),
    CoWriter(
        name="defense-pass (retired; folded into journal-enrichment by #505)",
        module=None,
        families=("defense_",),
        recomputed_by="nothing — the pass no longer runs, so a stored value is the only copy",
    ),
)


def coowned_families():
    """Every attribute family a co-writer owns, in declaration order — the carried set."""
    return tuple(family for writer in JOURNAL_ROW_COWRITERS for family in writer.families)


def is_coowned(attribute):
    """True when a co-writer, not the ingester, owns this attribute name."""
    return str(attribute).startswith(coowned_families())


def carry_coowned(item, stored):
    """Copy the co-writers' attributes from a stored row into a freshly built item, filling
    only what the fresh item lacks. Mutates ``item``; returns how many attributes were copied."""
    carried = 0
    for key, value in stored.items():
        if key not in item and is_coowned(key):
            item[key] = value
            carried += 1
    return carried
