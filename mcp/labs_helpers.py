"""
Lab / DEXA / Genome query helpers.
"""
import json
import logging

from boto3.dynamodb.conditions import Key
from mcp.config import table, s3_client, S3_BUCKET, USER_PREFIX, logger
from mcp.core import decimal_to_float, query_source

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


def _query_all_lab_draws():
    """Query all blood draw items from labs source, sorted chronologically."""
    pk = f"{USER_PREFIX}labs"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(sorted(items, key=lambda x: x.get("sk", "")))


def _query_dexa_scans():
    """Query all DEXA scan items, sorted chronologically."""
    pk = f"{USER_PREFIX}dexa"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
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
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
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
    "ldl_c":             ["ABCG8", "SLCO1B1"],
    "cholesterol_total": ["ABCG8"],
    "triglycerides":     ["ADIPOQ"],
    "glucose":           ["FTO", "IRS1", "TCF7L2"],
    "hba1c":             ["FTO", "IRS1", "TCF7L2"],
    "vitamin_d_25oh":    ["VDR", "GC", "CYP2R1"],
    "homocysteine":      ["MTHFR", "MTRR"],
    "ferritin":          ["HFE"],
    "crp_hs":            ["CRP", "IL6"],
    "folate":            ["MTHFR", "MTRR"],
    "vitamin_b12":       ["MTHFR", "MTRR"],
    "omega_3_index":     ["FADS2"],
    "testosterone_total":["SHBG"],
    "apolipoprotein_b":  ["ABCG8", "SLCO1B1"],
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
            result[bk] = [{
                "gene": s.get("gene"), "rsid": s.get("rsid"),
                "genotype": s.get("genotype"), "risk_level": s.get("risk_level"),
                "summary": s.get("summary"),
            } for s in matches]
    return result
