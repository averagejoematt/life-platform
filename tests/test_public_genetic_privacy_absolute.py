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


def test_the_genome_endpoint_serves_aggregates_only():
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
    assert '"total_snps"' in handler and '"risk_levels"' in handler, "the aggregate shape must survive"
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
