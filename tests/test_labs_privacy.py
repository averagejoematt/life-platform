"""tests/test_labs_privacy.py — /api/labs must never serve genetic data.

Privacy absolute (PRE-13 data-publication review pending): named genes and
genotypes must never reach the public labs payload. The 2026-07-10 truth audit
found "Lpa Aspirin Genotype — Ile/Ile" (category "Pharmacogenomics") rendered
raw on /data/labs. These tests pin the server-side guard in
web.site_api_data._strip_genetic_biomarkers and prove genetic entries never
survive serialization through handle_labs.
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

GENETIC_TELLS = re.compile(r"genotype|pharmacogenomic|\brs\d+\b|ile/ile", re.IGNORECASE)


def _fixture_labs() -> dict:
    """Mirror of the live clinical.json labs shape (biomarker keys: name/value/unit/range/flag/decimals/category)."""
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
            # The exact live finding: named gene + genotype under Pharmacogenomics.
            {
                "name": "Lpa Aspirin Genotype",
                "value": "Ile/Ile",
                "unit": None,
                "range": "Genotype variant — affects aspirin response",
                "flag": None,
                "decimals": 0,
                "category": "Pharmacogenomics",
            },
            # Genetic language hiding under a non-genetic category.
            {
                "name": "Factor V Leiden",
                "value": "Not Detected",
                "unit": "",
                "range": "Gene mutation screen",
                "flag": None,
                "decimals": 0,
                "category": "Coagulation",
            },
            # rsID in notes, flagged — must be stripped AND not counted in flagged_count.
            {
                "name": "Methylation Panel",
                "value": "Reduced Activity",
                "unit": "",
                "range": "",
                "notes": "rs1801133 homozygous",
                "flag": "Abnormal",
                "decimals": 0,
                "category": "Vitamins",
            },
            # SNP / allele wording.
            {
                "name": "APOE Allele",
                "value": "e3/e3",
                "unit": "",
                "range": "SNP result",
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
    assert not GENETIC_TELLS.search(json.dumps(out))


def test_strip_recomputes_flagged_count():
    out = sad._strip_genetic_biomarkers(_fixture_labs())
    # The flagged genetic entry (Methylation Panel) must not be counted.
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
            {"name": "Lpa Aspirin Genotype", "value": "Ile/Ile", "range": "Genotype variant", "flag": None, "category": "Pharmacogenomics"}
        ],
    }

    class _FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(json.dumps({"labs": only_genetic}).encode())}

    monkeypatch.setattr(sad.boto3, "client", lambda *a, **k: _FakeS3())
    resp = sad.handle_labs()
    assert resp["statusCode"] == 404
