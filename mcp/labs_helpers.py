"""
Lab / DEXA / Genome query helpers.
"""

import json
import logging
import os
from datetime import datetime

from boto3.dynamodb.conditions import Key

from mcp.config import USER_PREFIX, table
from mcp.core import _apply_phase_filter, decimal_to_float

logger = logging.getLogger(__name__)

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


# The biomarker -> gene cross-reference is PRIVATE (owner ruling 2026-11-11, item 5): which genes are mapped to which
# of the owner's biomarkers is personal genetic information, so the map lives off-repo, in the same private config
# prefix as ``common.user_goals`` (bucket-root ``config/private/`` -- no bucket-policy grant, no CloudFront origin, no
# repo twin). Locally: ``$LIFE_PLATFORM_GENOME_XREF_PATH``, else ``~/.config/life-platform/genome_lab_xref.json``.
# It fails SOFT to an empty map: no genome context is attached, nothing is guessed. Shape: {biomarker_key: [gene, ...]}.
GENOME_LAB_XREF_KEY = "config/private/genome_lab_xref.json"
GENOME_LAB_XREF_PATH_ENV = "LIFE_PLATFORM_GENOME_XREF_PATH"
_DEFAULT_XREF_PATH = os.path.join("~", ".config", "life-platform", "genome_lab_xref.json")
_GENOME_LAB_XREF_CACHE = None


def _valid_xref(doc):
    if not isinstance(doc, dict):
        return {}
    return {str(k): [str(g) for g in v] for k, v in doc.items() if isinstance(v, list)}


def _load_genome_lab_xref():
    """The private biomarker -> gene map; {} when it cannot be read (logged by exception TYPE only)."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        try:
            from mcp.config import S3_BUCKET, s3_client  # noqa: PLC0415 -- lazy: tests never touch S3

            body = s3_client.get_object(Bucket=S3_BUCKET, Key=GENOME_LAB_XREF_KEY)["Body"].read()
            return _valid_xref(json.loads(body))
        except Exception as e:  # noqa: BLE001 -- fail soft: no map, no genome context
            logger.warning("genome lab xref not read (%s)", type(e).__name__)
            return {}
    path = os.path.expanduser(os.environ.get(GENOME_LAB_XREF_PATH_ENV) or _DEFAULT_XREF_PATH)
    try:
        with open(path, encoding="utf-8") as fh:
            return _valid_xref(json.load(fh))
    except (OSError, ValueError):
        return {}


def _genome_lab_xref():
    """Cached per warm container, like the genome partition itself."""
    global _GENOME_LAB_XREF_CACHE
    if _GENOME_LAB_XREF_CACHE is None:
        _GENOME_LAB_XREF_CACHE = _load_genome_lab_xref()
    return _GENOME_LAB_XREF_CACHE


def _genome_context_for_biomarkers(biomarker_keys):
    """Return genome annotations relevant to a set of biomarker keys."""
    xref = _genome_lab_xref()
    genes_needed = set()
    for bk in biomarker_keys:
        genes_needed.update(xref.get(bk, []))
    if not genes_needed:
        return {}
    all_snps = _get_genome_cached()
    relevant = [s for s in all_snps if s.get("gene") in genes_needed]
    if not relevant:
        return {}
    result = {}
    for bk in biomarker_keys:
        genes = xref.get(bk, [])
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
