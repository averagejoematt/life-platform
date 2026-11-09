"""The public-safe coaching brief's publication policy (owner ruling 2026-11-09, third, section E).

THE RULING (verbatim). "Standardized public-safe brief for future cycles; only explicitly publication-eligible inputs;
clearly distinguish: observations/interpretations; specific falsifiable prospective predictions; frozen evaluation
criteria + windows; recommendations/proposed actions; what the owner actually did (recorded evidence); later
corrections/changes in position. Preserve private process separately. Don't fabricate historical advice or reconstruct
older private conversations."

WHY A SEPARATE BRIEF. The coaches' existing words are written from a context that includes private families (almost
every coach v2 read carries ``journal_presence``), so ``common.narrative_provenance`` withholds them and the Coaching
Room's CR2/CR3 layers are nearly empty. The brief is a SECOND, separate product of the coaching cycle whose input set
is decided before generation, from the registries, and can only be public. The private process is untouched.

THE INPUT WHITELIST (``eligible_metrics``) is DERIVED, never hand-listed:

  * a measured metric is a candidate only if it is in ``experiment.measurable_metrics.METRIC_SOURCES`` — the ONE
    registry the prediction grader reads, so every brief call is gradeable by the existing evaluator;
  * it is eligible only if EVERY source it is read from (``prediction_publication.metric_sources``, which follows the
    source registry's ``METRIC_TRUTH`` fallback order for a resolved metric) is classified PUBLIC by
    ``common.activity_publication.source_class`` — the one source classification every public surface uses, which
    itself derives every owner-only partition of ``privacy.field_tiers.SOURCE_TIERS`` as private;
  * so the decision is the same one ``prediction_publication`` makes for a call graded on that metric. Unclassified,
    private or unresolvable -> not an input (fail closed). The journal, State of Mind, the video diary, check-in answers
    and every family derived from them are never in ``METRIC_SOURCES`` and, if one were added, would be refused here.

THE SWITCH (``PUBLICATION_LIVE``). The brief is built dark. While it is False:
  * ``/api/coach_brief`` answers 404 (``web.site_api_coach_brief``);
  * a call the brief files into the prediction ledger (``source == BRIEF_CALL_SOURCE``) is classified PRIVATE by
    ``common.prediction_publication`` — graded normally, kept in full, left out of every public list and number.
Turning it on is the owner's act (one reviewed line, with the Coaching Room switches); ``tests/test_public_brief.py``
pins it off.

NO BACKFILL. ``FIRST_CYCLE`` is the first cycle a brief may exist for; the producer refuses any earlier cycle and any
cycle other than the one that contains its run day, so no historical advice can be written.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from common import activity_publication as AP, narrative_provenance as NP

# ── the dark switch ─────────────────────────────────────────────────────────────────────────
PUBLICATION_LIVE = False

# ── identity ────────────────────────────────────────────────────────────────────────────────
POLICY_VERSION = 1
BRIEF_SK_PREFIX = "PUBLIC_BRIEF#"  # COACH#<id> / PUBLIC_BRIEF#<cycle>            — the brief (immutable)
EVIDENCE_TAG = "#EVIDENCE#"  # COACH#<id> / PUBLIC_BRIEF#<cycle>#EVIDENCE#<rec>   — what he did (append-only)
REVISION_TAG = "#REVISION#"  # COACH#<id> / PUBLIC_BRIEF#<cycle>#REVISION#<ts>    — a later change (append-only)
BRIEF_CALL_SOURCE = "public_brief"  # PREDICTION#.source of a call the brief files

# A cycle is the Monday-to-Sunday week (platform time) that opens on the run's Monday.
FIRST_CYCLE = "2026-11-16"
CYCLE_DAYS = 7

# Families a brief's provenance may carry besides its metrics' sources (all PUBLIC in narrative_provenance).
PERSONA_FAMILY = "persona"
LEDGER_FAMILY = "prediction_ledger"


def metric_sources(metric: Any) -> Optional[list]:
    """The sources a measured metric is read from (None when it resolves to none)."""
    from common import prediction_publication as PP

    return PP.metric_sources(metric)


def metric_is_eligible(metric: Any) -> bool:
    """True only when the metric is graded by the ledger AND every source it reads is classified PUBLIC."""
    from experiment.measurable_metrics import METRIC_SOURCES, base_metric

    if not isinstance(metric, str) or base_metric(metric) not in METRIC_SOURCES or metric != base_metric(metric):
        return False
    srcs = metric_sources(metric) or []
    return bool(srcs) and all(AP.source_class(s) == NP.PUBLIC for s in srcs)


def eligible_metrics() -> list:
    """Every measured metric a brief may read, sorted. Derived from the registries on every call (no cache)."""
    from experiment.measurable_metrics import METRIC_SOURCES

    return sorted(m for m in METRIC_SOURCES if metric_is_eligible(m))


def families_for(metrics: Iterable[Any]) -> list:
    """The source families a set of metrics is read from (the provenance a brief built on them carries)."""
    out = set()
    for m in metrics or ():
        out |= set(metric_sources(m) or ("unclassified_metric:" + str(m),))
    return sorted(out)


def is_brief_call(row: Any) -> bool:
    return isinstance(row, dict) and str(row.get("source") or "") == BRIEF_CALL_SOURCE


# ── cycles ──────────────────────────────────────────────────────────────────────────────────
def cycle_of(day: Any) -> str:
    """The cycle id (its Monday, ISO) that contains ``day``."""
    d = day if isinstance(day, date) else datetime.strptime(str(day)[:10], "%Y-%m-%d").date()
    return (d - timedelta(days=d.weekday())).isoformat()


def cycle_end(cycle: str) -> str:
    return (datetime.strptime(cycle, "%Y-%m-%d").date() + timedelta(days=CYCLE_DAYS - 1)).isoformat()


def cycle_allowed(cycle: Any, today: Any) -> tuple:
    """``(ok, reason)``: a brief may be written only for the cycle containing ``today``, never before FIRST_CYCLE."""
    try:
        c = str(cycle)
        if cycle_of(c) != c:
            return False, "not_a_cycle_start"
    except (TypeError, ValueError):
        return False, "malformed_cycle"
    if c < FIRST_CYCLE:
        return False, "before_first_cycle"
    if c != cycle_of(today):
        return False, "not_the_current_cycle"
    return True, "ok"


def brief_sk(cycle: str) -> str:
    return f"{BRIEF_SK_PREFIX}{cycle}"


def evidence_sk(cycle: str, rec_id: str) -> str:
    return f"{brief_sk(cycle)}{EVIDENCE_TAG}{rec_id}"


def revision_sk(cycle: str, at_iso: str) -> str:
    return f"{brief_sk(cycle)}{REVISION_TAG}{at_iso}"


def method_block() -> dict:
    """What every served brief is built under (served beside it)."""
    return {
        "version": POLICY_VERSION,
        "first_cycle": FIRST_CYCLE,
        "inputs": eligible_metrics(),
        "note": (
            "Each brief is written from measured, publishable data only: the metrics listed here, whose every source is "
            "classified public. The private journal, mood and State of Mind, the video diary, check-in answers and "
            "anything derived from them are never inputs. The coach's private conversations are kept separately and are "
            "not shown. Predictions are filed in the same ledger and graded by the same rules as every other call; their "
            "test is frozen when they are filed. Briefs begin with the cycle of " + FIRST_CYCLE + "; nothing earlier is "
            "reconstructed."
        ),
    }
