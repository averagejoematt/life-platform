"""tests/test_labs_privacy.py — /api/labs must never serve genetic data.

Privacy absolute (PRE-13 data-publication review pending): named genes and
genotypes must never reach the public labs payload. The 2026-07-10 truth audit
found a named-gene genotype entry (category "Pharmacogenomics") rendered raw on
/data/labs. These tests pin the server-side guard in
web.site_api_data._strip_genetic_biomarkers and prove genetic entries never
survive serialization through handle_labs.

The fixtures below use SYNTHETIC markers only — no real gene name or genotype is
reproduced here (this repo is public). Each synthetic entry exercises one branch
of the guard: the pharmacogenomics category, genotype/variant/allele wording, and
an rsID buried in a note. The assertion logic does not need the real values.
"""

from __future__ import annotations

import io
import json
import os
import re

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from web import site_api_data as sad  # noqa: E402

# Genetic "tells" the served payload must never contain. Synthetic-safe patterns —
# these are category/format words, not any real person's gene or genotype.
GENETIC_TELLS = re.compile(r"genotype|pharmacogenomic|\brs\d+\b|\ballele\b|\bsnp\b|variant", re.IGNORECASE)

# A synthetic sentinel: it must NEVER appear in served output, proving the strip
# runs on made-up genetic entries exactly as it would on real ones.
SYNTHETIC_GENE_MARKER = "SynthGene-QX7"


def _fixture_labs() -> dict:
    """Mirror of the live clinical.json labs shape (biomarker keys: name/value/unit/range/flag/decimals/category).

    Genetic entries are synthetic markers, not the real live findings.
    """
    return {
        "latest_draw_date": "2026-04-03",
        "lab_provider": "function_health",
        "total_draws": 8,
        "flagged_count": 2,
        "biomarkers": [
            # --- must survive ---
            {"name": "ApoB", "value": "72", "unit": "mg/dL", "range": "<90", "flag": None, "decimals": 0, "category": "Advanced Lipids"},
            {
                "name": "LDL Cholesterol",
                "value": "131",
                "unit": "mg/dL",
                "range": "<100",
                "flag": "High",
                "decimals": 0,
                "category": "Lipids",
            },
            {
                "name": "Ferritin",
                "value": "180",
                "unit": "ng/mL",
                "range": "30-400",
                "flag": None,
                "decimals": 0,
                "category": "Iron Metabolism",
            },
            # --- must be stripped ---
            # Synthetic named-gene genotype under a Pharmacogenomics category (category-match branch).
            {
                "name": f"{SYNTHETIC_GENE_MARKER} Genotype",
                "value": "AA/AA",
                "unit": None,
                "range": "Genotype variant — synthetic sentinel, not a real finding",
                "flag": None,
                "decimals": 0,
                "category": "Pharmacogenomics",
            },
            # Genetic language hiding under a non-genetic category (text-match: "variant").
            {
                "name": "Synthetic Clotting Marker",
                "value": "Not Detected",
                "unit": "",
                "range": "Gene variant screen (synthetic)",
                "flag": None,
                "decimals": 0,
                "category": "Coagulation",
            },
            # rsID in notes, flagged — must be stripped AND not counted in flagged_count.
            {
                "name": "Synthetic Methylation Panel",
                "value": "Reduced Activity",
                "unit": "",
                "range": "",
                "notes": "rs0000000 homozygous (synthetic)",
                "flag": "Abnormal",
                "decimals": 0,
                "category": "Vitamins",
            },
            # SNP / allele wording (text-match branch).
            {
                "name": "Synthetic Allele Marker",
                "value": "z9/z9",
                "unit": "",
                "range": "SNP result (synthetic)",
                "flag": None,
                "decimals": 0,
                "category": "Neurodegeneration",
            },
        ],
    }


def test_strip_removes_all_genetic_entries():
    out = sad._strip_genetic_biomarkers(_fixture_labs())
    names = [b["name"] for b in out["biomarkers"]]
    assert names == ["ApoB", "LDL Cholesterol", "Ferritin"]
    dumped = json.dumps(out)
    assert not GENETIC_TELLS.search(dumped)
    assert SYNTHETIC_GENE_MARKER not in dumped


def test_strip_recomputes_flagged_count():
    out = sad._strip_genetic_biomarkers(_fixture_labs())
    # The flagged genetic entry (Synthetic Methylation Panel) must not be counted.
    assert out["flagged_count"] == 1


def test_strip_recomputes_count_fields_when_present():
    labs = _fixture_labs()
    labs["biomarker_count"] = len(labs["biomarkers"])
    labs["total_biomarkers"] = len(labs["biomarkers"])
    out = sad._strip_genetic_biomarkers(labs)
    assert out["biomarker_count"] == 3
    assert out["total_biomarkers"] == 3


def test_strip_does_not_mutate_input():
    labs = _fixture_labs()
    before = json.dumps(labs, sort_keys=True)
    sad._strip_genetic_biomarkers(labs)
    assert json.dumps(labs, sort_keys=True) == before


def test_handle_labs_serialization_never_leaks_genetics(monkeypatch):
    """End-to-end: genetic entries never survive serialization through handle_labs."""

    class _FakeS3:
        def get_object(self, Bucket, Key):
            assert Key == "dashboard/matthew/clinical.json"
            return {"Body": io.BytesIO(json.dumps({"labs": _fixture_labs()}).encode())}

    monkeypatch.setattr(sad.boto3, "client", lambda *a, **k: _FakeS3())
    resp = sad.handle_labs()
    assert resp["statusCode"] == 200
    body = resp["body"]
    assert not GENETIC_TELLS.search(body)
    assert SYNTHETIC_GENE_MARKER not in body
    served = json.loads(body)["labs"]
    assert len(served["biomarkers"]) == 3
    assert served["flagged_count"] == 1
    # Header figures the page derives stay consistent with what's actually served.
    assert all(b["category"] != "Pharmacogenomics" for b in served["biomarkers"])


def test_handle_labs_404_when_only_genetic_entries(monkeypatch):
    """If everything is genetic, serve an honest empty state, not a leak."""
    only_genetic = {
        "flagged_count": 0,
        "biomarkers": [
            {
                "name": f"{SYNTHETIC_GENE_MARKER} Genotype",
                "value": "AA/AA",
                "range": "Genotype variant (synthetic)",
                "flag": None,
                "category": "Pharmacogenomics",
            }
        ],
    }

    class _FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(json.dumps({"labs": only_genetic}).encode())}

    monkeypatch.setattr(sad.boto3, "client", lambda *a, **k: _FakeS3())
    resp = sad.handle_labs()
    assert resp["statusCode"] == 404
