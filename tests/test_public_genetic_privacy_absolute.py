"""tests/test_public_genetic_privacy_absolute.py — no public route may publish a genetic identifier.

THE DEFECT. `GET /api/genome_risks` — unauthenticated, CloudFront-cached, live —
served **111 SNPs with 116 dbSNP `rsid` values and 93 `gene` names**, each paired
with the owner's personal risk classification, plus genotype calls leaking through
free-text fields. Found by the 2026-08-02 Fable delta review's security lens,
reproduced independently before any change was made.

WHY NOTHING CAUGHT IT — guard the instance, not the set (the 5th recurrence of
this class in this repo). When #920 found a genotype leak on `/api/labs`, the fix
was scoped to that ONE handler: `_strip_genetic_biomarkers` was written, wired
into `handle_labs`, and pinned by `tests/test_labs_privacy.py`. `handle_genome_risks`
lives in the SAME MODULE, ~900 lines from the comment that declares the absolute
("named genes / genotypes must NEVER reach the public labs payload"), reads the
same owner-only tier of data, and was simply never enumerated as in scope.

So this file does not test a handler. It tests the SET — every captured public
API payload — and it derives that set from disk rather than listing it.

WHAT IS STILL ALLOWED. Aggregate counts ("this category has 8 variants, 3 of them
unfavorable") are facts about the analysis. An identifier is a fact about the
person. Publishing per-variant detail is a PRE-13 decision that is still deferred,
and PRE-13 is the owner's to make — not something a code change should quietly
assume.
"""

import json
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SCHEMA_DIR = _REPO / "tests" / "api_schemas"

# The same vocabulary the labs absolute already uses (site_api_vitals._GENETIC_TEXT_RE),
# kept in sync deliberately: one definition of "genetic identifier" for the platform.
_GENETIC_KEY_RE = re.compile(r"genotype|\bgene\b|rsid|\brs\d+\b|allele|\bsnp_id\b", re.IGNORECASE)

# Keys that COUNT genetic material without identifying any of it. Aggregates are
# the sanctioned public shape; this is an allowlist of shapes, not of routes.
_AGGREGATE_KEYS = {"total_snps", "snp_count", "n_snps"}


def _schema_files():
    return sorted(p for p in _SCHEMA_DIR.glob("api_*.json") if p.name != "_exemptions.json")


def _walk_keys(node, path=""):
    """Yield (json_path, key) for every key in a captured shape tree.
    'optional' (#3354's array-union per-key optionality marker — a list of key
    NAMES, not a shape node) is structure, like 'keys'/'items'/'type'/
    'length_sample'."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("keys", "items", "type", "length_sample", "optional"):
                yield from _walk_keys(v, path)
            else:
                p = f"{path}.{k}" if path else k
                yield p, k
                yield from _walk_keys(v, p)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v, path)


def test_captured_schemas_exist():
    """A vacuous scan passes every assertion below — the #1908 lesson: assert the
    mechanism has something to check before trusting its verdict."""
    files = _schema_files()
    assert len(files) > 50, f"expected the full captured public surface, found {len(files)}"


@pytest.mark.parametrize("schema_path", _schema_files(), ids=lambda p: p.name)
def test_no_public_payload_declares_a_genetic_identifier_field(schema_path):
    shape = json.loads(schema_path.read_text())
    offenders = sorted(
        {f"{jp} ({key})" for jp, key in _walk_keys(shape.get("shape") or {}) if _GENETIC_KEY_RE.search(key) and key not in _AGGREGATE_KEYS}
    )
    assert not offenders, (
        f"{schema_path.name} publishes genetic identifier field(s): {offenders}\n"
        "An rsID or gene name identifies which variants a person carries — Tier 2, owner-only "
        "(docs/DATA_GOVERNANCE.md), and the absolute site_api_vitals._GENETIC_TEXT_RE already "
        "enforces for /api/labs. Publish aggregates instead, or take it to PRE-13."
    )


def test_the_genome_endpoint_serves_no_genetic_finding():
    """Direct guard on the handler that failed, independent of schema capture
    (a schema is only as fresh as its last run)."""
    import sys

    sys.path.insert(0, str(_REPO / "lambdas"))
    # #1654: the genome handler moved to web/site_api_biomarkers.py behind the
    # unchanged site_api_vitals facade. This is a PRIVACY absolute — a guard that
    # silently found nothing to object to would be the worst outcome — so it follows
    # the facade's own delegator to whichever module owns the body.
    from site_api_family import handler_source

    handler = handler_source("site_api_vitals", "handle_genome_risks")
    for forbidden in ('"gene"', '"rsid"', '"summary"', '"implications"'):
        assert forbidden not in handler, f"handle_genome_risks emits {forbidden} — that identifies the variant"
    # 2026-11-11 owner ruling: aggregates are genetic findings too. The handler
    # publishes a status and a disclosure and never reads the genome partition.
    for forbidden in (
        '"total_snps"',
        '"risk_summary"',
        '"risk_levels"',
        '"categories"',
        "table.query",
        "SOURCE#genome",
        "}genome",
        "_decimal_to_float",
    ):
        assert forbidden not in handler, f"handle_genome_risks still carries {forbidden}"
    assert "disclosure" in handler, "the payload must say WHY detail is absent, not just omit it"


def test_the_labs_absolute_is_still_enforced():
    """The sibling rule that already worked must not regress while fixing its twin."""
    # #1654: the strip moved to web/site_api_biomarkers.py behind the site_api_vitals
    # facade. Asserting the NAMES exist somewhere in the family is not enough — the
    # facade re-exports both, so deleting the real implementation would leave this
    # guard passing on a re-export that does nothing (verified: it did). Assert the
    # CALL SITE inside the labs handler, which only the real thing satisfies.
    from site_api_family import family_source, handler_source

    labs = handler_source("site_api_vitals", "handle_labs")
    assert "_strip_genetic_biomarkers(" in labs, "/api/labs no longer runs its panels through the genetic strip"

    src = family_source("site_api_vitals")
    assert "def _strip_genetic_biomarkers(" in src, "the genetic strip is gone from the serving family"
    assert "_GENETIC_TEXT_RE = " in src and "_GENETIC_TEXT_RE.search(" in src, "the genetic text pattern is defined-and-used nowhere"


def test_scanner_fires_on_an_injected_identifier_field(tmp_path):
    """Negative test: prove the walk actually reaches nested item keys — the
    genome payload nested them three levels deep under categories.<name>.items."""
    injected = {
        "path": "/api/injected",
        "shape": {"keys": {"genome": {"keys": {"categories": {"keys": {"cardio": {"items": {"keys": {"rsid": {"type": "string"}}}}}}}}}},
    }
    found = [k for _jp, k in _walk_keys(injected["shape"]) if _GENETIC_KEY_RE.search(k)]
    assert "rsid" in found, "the walker must reach identifier keys nested under items"


def test_aggregate_keys_are_not_flagged():
    ok = {"shape": {"keys": {"genome": {"keys": {"total_snps": {"type": "integer"}}}}}}
    offenders = [k for _jp, k in _walk_keys(ok["shape"]) if _GENETIC_KEY_RE.search(k) and k not in _AGGREGATE_KEYS]
    assert offenders == [], "a count of variants is not an identifier"


# ── 2026-11-11 owner ruling: /api/genome_risks publishes no genetic finding at all ──
#
# Individual variants, inferred outcomes, genetic risk categories and
# personalised risk summaries are private by default, and aggregation does not
# make them safe. The payload is {"genome": {"status", "disclosure"}} and nothing
# else. `_genome_violations` is the rule. It runs against the real handler, the
# captured schema, and two must-fail controls: the pre-fix {n, risk_levels}
# shape and the interim n>=5 counts-only shape. Both controls must be rejected.

_ALLOWED_GENOME_KEYS = {"status", "disclosure"}


def _genome_violations(genome) -> list[str]:
    out = []
    if not isinstance(genome, dict):
        return [f"genome is {type(genome).__name__}, not the status object"]
    extra = set(genome) - _ALLOWED_GENOME_KEYS
    if extra:
        out.append(f"genome serves keys beyond status/disclosure: {sorted(extra)}")

    def walk(node, path):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.append(f"numeric genetic field at {path}")
        elif isinstance(node, dict):
            for k, v in node.items():
                if k in ("categories", "risk_levels", "risk_summary", "other_categories_combined") or "statin" in k.lower():
                    out.append(f"category/risk key {k!r} at {path}")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(genome, "genome")
    for k in ("status", "disclosure"):
        if k in genome and not isinstance(genome[k], str):
            out.append(f"genome.{k} is not a string")
    return out


def _synthetic_genome_items():
    """Synthetic rows shaped like the live partition. No real variant data."""
    plan = {"caffeine": 1, "antioxidant": 2, "statin_response": 3, "exercise": 6, "longevity": 20}
    levels = ["unfavorable", "mixed", "neutral", "favorable"]
    items, i = [], 0
    for cat, n in plan.items():
        for _ in range(n):
            items.append({"pk": "USER#matthew#SOURCE#genome", "sk": f"SNP#{i}", "category": cat, "risk_level": levels[i % 4]})
            i += 1
    return items


class _FakeTable:
    def __init__(self, items):
        self._items = items
        self.queried = 0

    def query(self, **_kw):
        self.queried += 1
        return {"Items": list(self._items)}


def _serve_genome(table):
    import sys

    sys.path.insert(0, str(_REPO / "lambdas"))
    from web import site_api_biomarkers as bio

    resp = bio.genome_risks(_g={"table": table})
    body = resp["body"]
    return (json.loads(body) if isinstance(body, str) else body)["genome"]


def test_genome_handler_publishes_status_only_and_never_reads_the_partition():
    table = _FakeTable(_synthetic_genome_items())
    genome = _serve_genome(table)
    assert _genome_violations(genome) == [], _genome_violations(genome)
    assert genome["status"] == "private" and genome["disclosure"]
    assert table.queried == 0, "the public genome handler must not even read the owner-only partition"
    blob = json.dumps(genome).lower()
    for gone in ("caffeine", "antioxidant", "statin", "exercise", "longevity", "unfavorable", "favorable", "snp"):
        assert gone not in blob, f"{gone!r} reached the public genome payload"


def test_captured_genome_schema_declares_status_and_disclosure_only():
    shape = json.loads((_SCHEMA_DIR / "api_genome_risks.json").read_text())["shape"]
    genome = shape["keys"]["genome"]["keys"]
    assert set(genome) == _ALLOWED_GENOME_KEYS, f"captured schema declares {sorted(genome)}"
    assert all(node.get("type") == "string" for node in genome.values()), "a genome field is not a string"


def _old_shape():
    old = {"total_snps": 0, "risk_summary": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}, "categories": {}}
    for row in _synthetic_genome_items():
        old["total_snps"] += 1
        old["risk_summary"][row["risk_level"]] += 1
        b = old["categories"].setdefault(
            row["category"], {"n": 0, "risk_levels": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}}
        )
        b["n"] += 1
        b["risk_levels"][row["risk_level"]] += 1
    return old


def test_must_fail_control_the_pre_fix_shape_is_rejected():
    found = "\n".join(_genome_violations(_old_shape()))
    assert "numeric genetic field" in found and "risk_levels" in found and "statin" in found and "categories" in found


def test_must_fail_control_the_interim_counts_only_shape_is_rejected():
    """The n>=5 counts-only shape briefly proposed on 2026-11-11 (categories.<name>.n
    plus an unnamed combined count, total and risk_summary kept). The owner ruled
    aggregates private too, so the rule must reject it."""
    old = _old_shape()
    interim = {
        "total_snps": old["total_snps"],
        "risk_summary": old["risk_summary"],
        "categories": {k: {"n": v["n"]} for k, v in old["categories"].items() if v["n"] >= 5 and "statin" not in k},
        "other_categories_combined": {"n": sum(v["n"] for k, v in old["categories"].items() if v["n"] < 5 or "statin" in k)},
        "disclosure": "counts only",
    }
    found = "\n".join(_genome_violations(interim))
    assert "numeric genetic field" in found and "categories" in found and "risk_summary" in found
