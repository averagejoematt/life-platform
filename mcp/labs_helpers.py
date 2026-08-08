"""
Lab / DEXA / Genome query helpers.
"""

from datetime import datetime

from boto3.dynamodb.conditions import Key

from mcp.config import USER_PREFIX, table
from mcp.core import _apply_phase_filter, decimal_to_float

_GENOME_CACHE_V2 = None


def _get_genome_cached():
    """Query all genome SNPs once per Lambda invocation."""
    global _GENOME_CACHE_V2
    if _GENOME_CACHE_V2 is not None:
        return _GENOME_CACHE_V2
    pk = f"{USER_PREFIX}genome"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    _GENOME_CACHE_V2 = decimal_to_float(items)
    return _GENOME_CACHE_V2


def _measured_value(bm):
    """The measured value of one biomarker cell, honouring a real zero (ADR-104).

    The idiom this replaces — ``bm.get("value_numeric") or bm.get("value")`` — is a
    TRUTHINESS fallback: a biomarker genuinely measured at 0.0 (a non-detectable
    assay result, e.g. hs-CRP below the limit of quantitation) is falsy, so it falls
    through to ``value`` and, when that is absent, is dropped from the series
    entirely. A measured 0 then reads as "never measured", losing the most
    clinically interesting point in the trend. Absence is ``None``; zero is a number.
    """
    if not isinstance(bm, dict):
        return None
    numeric = bm.get("value_numeric")
    return bm.get("value") if numeric is None else numeric


def _draw_date_of(row):
    """The date the blood was actually taken, as ``YYYY-MM-DD``, or ``None``.

    ``draw_date`` is the clinical truth; the ``sk`` is the *import* key. They agree
    on every row in the archive today, so this is a latent divergence rather than a
    live wrong number — but every reader downstream indexes ``[0]``/``[-1]`` as
    "earliest"/"latest", and a panel backfilled after a later draw files under a
    LATER sk than the draw it contains. Sorting on the import key then narrates the
    trend backwards (the shape #2300 found live in ``tools_cgm``).

    The sk is the fallback, not the primary: an importer that dropped ``draw_date``
    still keyed the row by its date, so the chronology is recoverable rather than
    lost. Returns ``None`` only when NEITHER parses — an undatable draw, which the
    callers must then treat as absent rather than as day zero (ADR-104).
    """
    if not isinstance(row, dict):
        return None
    for candidate in (row.get("draw_date"), str(row.get("sk") or "").replace("DATE#", "", 1)[:10]):
        if isinstance(candidate, str) and len(candidate) == 10:
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
            except ValueError:
                continue
            return candidate
    return None


def _query_all_lab_draws():
    """Query all blood draw items from labs source, sorted chronologically.

    Chronological means *by draw date* — see ``_draw_date_of``. An undatable row
    sorts first (it cannot be the newest thing we know) and keeps its sk as the
    tiebreak so the order stays stable.
    """
    pk = f"{USER_PREFIX}labs"
    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    kwargs = _apply_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")},
        include_pilot=True,
    )
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(sorted(items, key=lambda x: (_draw_date_of(x) or "", x.get("sk", ""))))


def _query_dexa_scans():
    """Query all DEXA scan items, sorted chronologically."""
    pk = f"{USER_PREFIX}dexa"
    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    kwargs = _apply_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")},
        include_pilot=True,
    )
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(items)


def _query_lab_meta():
    """Query labs provider metadata items (non-DATE# SKs)."""
    pk = f"{USER_PREFIX}labs"
    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    kwargs = _apply_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(pk)},
        include_pilot=True,
    )
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    all_items = decimal_to_float(items)
    return [i for i in all_items if not i.get("sk", "").startswith("DATE#")]


_GENOME_LAB_XREF = {
    "ldl_c": ["ABCG8", "SLCO1B1"],
    "cholesterol_total": ["ABCG8"],
    "triglycerides": ["ADIPOQ"],
    "glucose": ["FTO", "IRS1", "TCF7L2"],
    "hba1c": ["FTO", "IRS1", "TCF7L2"],
    "vitamin_d_25oh": ["VDR", "GC", "CYP2R1"],
    "homocysteine": ["MTHFR", "MTRR"],
    "ferritin": ["HFE"],
    "crp_hs": ["CRP", "IL6"],
    "folate": ["MTHFR", "MTRR"],
    "vitamin_b12": ["MTHFR", "MTRR"],
    "omega_3_index": ["FADS2"],
    "testosterone_total": ["SHBG"],
    "apolipoprotein_b": ["ABCG8", "SLCO1B1"],
}


def _genome_context_for_biomarkers(biomarker_keys):
    """Return genome annotations relevant to a set of biomarker keys."""
    genes_needed = set()
    for bk in biomarker_keys:
        genes_needed.update(_GENOME_LAB_XREF.get(bk, []))
    if not genes_needed:
        return {}
    all_snps = _get_genome_cached()
    relevant = [s for s in all_snps if s.get("gene") in genes_needed]
    if not relevant:
        return {}
    result = {}
    for bk in biomarker_keys:
        genes = _GENOME_LAB_XREF.get(bk, [])
        if not genes:
            continue
        matches = [s for s in relevant if s.get("gene") in genes]
        if matches:
            result[bk] = [
                {
                    "gene": s.get("gene"),
                    "rsid": s.get("rsid"),
                    "genotype": s.get("genotype"),
                    "risk_level": s.get("risk_level"),
                    "summary": s.get("summary"),
                }
                for s in matches
            ]
    return result
