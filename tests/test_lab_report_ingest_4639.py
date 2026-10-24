"""tests/test_lab_report_ingest_4639.py — the labs/DEXA ingest path (#4639, epic #4625).

The issue's boxes, as tests:
  * the write REFUSES a marker or unit not in the schema (and a DEXA leaf not in the schema);
  * the source document is archived BEFORE the row is written, under the registry's own
    `raw_layout` facet (mutation: move the facet, the key moves);
  * every row carries `provenance` (document keys + sha256, lab/scanner, date, method, reviewer);
  * the dry run writes nothing; `--apply` is the only writer;
  * what is written is the wire the existing readers consume (`health/labs_schema.py`
    accessors; the four DEXA leaves `ai/ai_context.py` and `content/output_writers.py` read).

FIXTURES CARRY NO REAL VALUES (the issue's own rule). Their SHAPE is the real one: the CSV
columns are the per-marker fields of the stored draw records (SCHEMA.md `labs`), the marker
keys and units are entries of `health.lab_units.LAB_UNITS` (read from the live partition),
and the DEXA leaves are paths of `DEXA_FIELDS` (the live scan record). Every number below is
a round placeholder.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from decimal import Decimal

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ingest_lab_report as ing  # noqa: E402
from health import lab_units, labs_schema  # noqa: E402
from ingestion.source_registry import SOURCE_REGISTRY  # noqa: E402

STAMP = "2026-10-17T20:00:00+00:00"

# The per-marker CSV shape: marker,value,unit,ref_text,flag[,category,panel,note]. Placeholder values.
LAB_ROWS = [
    {"marker": "LDL-C", "value": "110", "unit": "mg/dL", "ref_text": "<100", "flag": ""},
    {"marker": "hdl", "value": "50", "unit": "mg/dl", "ref_text": "40 - 60", "flag": ""},
    {"marker": "vitamin_d_25oh", "value": "40", "unit": "ng/mL", "ref_text": "30-100", "flag": "normal"},
    {"marker": "hs_crp", "value": "<0.2", "unit": "mg/L", "ref_text": "<1.0", "flag": ""},
    {"marker": "ALT", "value": "20", "unit": "IU/L", "ref_text": "9 - 46", "flag": "", "panel": "placeholder panel"},
]

DEXA_LEAVES = {
    "body_composition.total_mass_lb": ("200", "lb"),
    "body_composition.lean_mass_lb": ("150", "lb"),
    "body_composition.fat_mass_lb": ("50", ""),
    "body_composition.body_fat_pct": ("25", "%"),
    "body_composition.visceral_fat_lb": ("2", "lb"),
    "bone.t_score": ("1", ""),
    "indices.almi_kg_m2": ("9", "kg/m2"),
    "indices.ffmi_rating": ("placeholder", ""),
}


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    return str(path)


@pytest.fixture
def report_csv(tmp_path):
    return _write_csv(tmp_path / "panel.csv", LAB_ROWS, ["marker", "value", "unit", "ref_text", "flag", "panel"])


@pytest.fixture
def document(tmp_path):
    p = tmp_path / "standard_panel.pdf"
    p.write_bytes(b"%PDF-1.4 placeholder\n")
    return str(p)


def _labs_item(rows=LAB_ROWS, documents=(), previous=None, **kw):
    return ing.build_labs_item(
        list(rows),
        draw_date=kw.pop("draw_date", "2026-10-20"),
        lab_provider="function_health",
        lab_network="quest_diagnostics",
        documents=list(documents),
        unavailable_reason=kw.pop("unavailable_reason", None if documents else "placeholder: fixture draw"),
        extraction_method="csv",
        reviewer="matthew",
        previous=previous,
        now=STAMP,
        **kw,
    )


def _walk_numbers(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_numbers(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_numbers(v, f"{path}[{i}]")
    elif isinstance(node, (int, float, Decimal)) and not isinstance(node, bool):
        yield path, node


# ── the schema table itself ─────────────────────────────────────────────────────────────


def test_the_unit_table_is_the_live_vocabulary_not_a_stub():
    """Blindness floor: 189 marker keys and 124 DEXA leaves were read on 2026-10-17; a table
    that shrank to a handful would make every refusal below vacuous."""
    assert len(lab_units.LAB_UNITS) >= 150
    assert len(lab_units.DEXA_FIELDS) >= 100
    for key, (units, category, kind) in lab_units.LAB_UNITS.items():
        assert key == lab_units.marker_key(key), f"{key}: not a normalized marker key"
        assert units and category and kind in ("numeric", "qualitative"), key
    assert set(lab_units.DEXA_REQUIRED) <= set(lab_units.DEXA_FIELDS)


def test_marker_key_normalizes_report_labels():
    assert lab_units.marker_key("LDL-C") == "ldl_c"
    assert lab_units.marker_key(" Vitamin D (25-OH) ") == "vitamin_d_25_oh"


def test_units_match_case_and_space_insensitively_but_never_across_units():
    assert lab_units.unit_accepted("ldl_c", "mg/dl")
    assert lab_units.unit_accepted("ldl_c", "MG / DL")
    assert not lab_units.unit_accepted("ldl_c", "mmol/L")
    assert lab_units.canonical_unit("ldl_c", "mg/dl") == "mg/dL"


# ── refusals (acceptance box 2) ─────────────────────────────────────────────────────────


def test_an_unknown_marker_is_refused_by_name():
    with pytest.raises(ing.Refusal, match="made_up_marker: marker not in"):
        _labs_item(rows=[{"marker": "made_up_marker", "value": "1", "unit": "mg/dL"}])


def test_a_unit_not_in_the_schema_is_refused_by_name():
    with pytest.raises(ing.Refusal, match=r"ldl_c: unit 'mmol/L' not in the schema"):
        _labs_item(rows=[{"marker": "ldl_c", "value": "3", "unit": "mmol/L"}])


def test_a_non_numeric_value_on_a_numeric_marker_is_refused_but_a_censored_result_is_kept():
    with pytest.raises(ing.Refusal, match="ldl_c: numeric marker"):
        _labs_item(rows=[{"marker": "ldl_c", "value": "lots", "unit": "mg/dL"}])
    item = _labs_item(rows=[{"marker": "hs_crp", "value": "<0.2", "unit": "mg/L", "ref_text": "<1.0"}])
    entry = item["biomarkers"]["hs_crp"]
    assert entry["value"] == "<0.2" and "value_numeric" not in entry  # qualitative: None is dropped, never a fake number


def test_a_bad_flag_and_a_duplicate_marker_are_refused():
    with pytest.raises(ing.Refusal, match="flag 'weird'"):
        _labs_item(rows=[{"marker": "ldl_c", "value": "1", "unit": "mg/dL", "flag": "weird"}])
    with pytest.raises(ing.Refusal, match="listed twice"):
        _labs_item(rows=[LAB_ROWS[0], LAB_ROWS[0]])


def test_mutation_control_the_same_rows_with_schema_units_are_accepted():
    """The refusals above are not the parser failing on everything: the fixture rows pass."""
    item = _labs_item()
    assert item["total_biomarkers"] == 5 and set(item["biomarkers"]) == {"ldl_c", "hdl", "vitamin_d_25oh", "hs_crp", "alt"}


def test_dexa_refuses_an_unknown_leaf_a_wrong_unit_and_a_missing_core_field():
    with pytest.raises(ing.Refusal, match="body_composition.made_up: not a DEXA field"):
        ing.validate_dexa_leaves({**DEXA_LEAVES, "body_composition.made_up": ("1", "")})
    with pytest.raises(ing.Refusal, match=r"body_composition.body_fat_pct: unit 'lb'"):
        ing.validate_dexa_leaves({**DEXA_LEAVES, "body_composition.body_fat_pct": ("25", "lb")})
    with pytest.raises(ing.Refusal, match="missing the fields every reader depends on"):
        ing.validate_dexa_leaves({k: v for k, v in DEXA_LEAVES.items() if k != "body_composition.lean_mass_lb"})
    with pytest.raises(ing.Refusal, match="expected a number"):
        ing.validate_dexa_leaves({**DEXA_LEAVES, "bone.t_score": ("high", "")})


# ── the written wire (readers keep working) ─────────────────────────────────────────────


def test_the_labs_row_is_the_shape_the_accessor_reads_and_every_number_is_decimal():
    item = _labs_item()
    assert item["pk"] == "USER#matthew#SOURCE#labs" and item["sk"] == "DATE#2026-10-20"
    assert labs_schema.is_draw_record(item)
    markers = labs_schema.biomarker_map(item)
    assert labs_schema.marker_numeric(markers["ldl_c"]) == 110.0
    assert labs_schema.marker_numeric(markers["hs_crp"]) is None  # qualitative stays uncoachable, never 0
    assert markers["hdl"]["unit"] == "mg/dL" and markers["hdl"]["ref_low"] == Decimal("40") and markers["hdl"]["ref_high"] == Decimal("60")
    assert markers["hdl"]["flag"] == "normal" and markers["ldl_c"]["flag"] == "high"  # derived from ref_text when blank
    assert markers["alt"]["category"] == "liver" and markers["alt"]["panel"] == "placeholder panel"
    assert item["out_of_range"] == ["ldl_c"] and item["out_of_range_count"] == Decimal("1")
    for path, num in _walk_numbers(item):
        assert isinstance(num, Decimal), f"{path} is {type(num).__name__}, not Decimal — boto3 would reject the write"


def test_the_previous_draw_is_read_through_the_shared_accessor():
    previous = {
        "sk": "DATE#2026-04-03",
        "draw_date": "2026-04-03",
        "biomarkers": {"ldl_c": {"value_numeric": Decimal("90"), "unit": "mg/dL"}},
    }
    item = _labs_item(previous=previous)
    assert item["biomarkers"]["ldl_c"]["previous_value"] == Decimal("90") and item["biomarkers"]["ldl_c"]["previous_date"] == "2026-04-03"
    assert "previous_value" not in item["biomarkers"]["hdl"]


def test_the_dexa_row_carries_the_leaves_the_readers_read_and_every_number_is_decimal():
    item = ing.build_dexa_item(
        DEXA_LEAVES,
        scan_date="2026-11-01",
        provider="dexafit_seattle",
        documents=[],
        unavailable_reason="placeholder",
        extraction_method="csv",
        reviewer="matthew",
        now=STAMP,
    )
    assert item["pk"] == "USER#matthew#SOURCE#dexa" and item["sk"] == "DATE#2026-11-01" and item["scan_type"] == "dexa"
    bc = item["body_composition"]
    # ai/ai_context.py `_build_physical_data` and content/output_writers.py read exactly these leaves off `body_composition`
    assert {"body_fat_pct", "lean_mass_lb", "fat_mass_lb", "total_mass_lb", "visceral_fat_lb"} <= set(bc)
    assert bc["body_fat_pct"] == Decimal("25") and item["indices"]["ffmi_rating"] == "placeholder"
    for path, num in _walk_numbers(item):
        assert isinstance(num, Decimal), f"{path} is {type(num).__name__}, not Decimal"


# ── provenance (acceptance box 3) ───────────────────────────────────────────────────────


def test_every_row_carries_provenance_and_the_document_key_comes_from_the_registry_facet(document, monkeypatch):
    docs = ing.plan_documents("labs", "2026-10-20", [document])
    assert docs[0]["s3_key"] == "raw/matthew/labs/2026-10-20/standard_panel.pdf" and len(docs[0]["sha256"]) == 64
    item = _labs_item(documents=docs)
    prov = item["provenance"]
    assert prov["documents"][0]["s3_key"] == docs[0]["s3_key"] and "local" not in prov["documents"][0]
    assert prov["lab"] == "function_health" and prov["drawn_date"] == "2026-10-20" and prov["reviewer"] == "matthew"
    assert prov["extraction_method"].startswith("csv via scripts/ingest_lab_report.py") and prov["ingested_at"] == STAMP
    assert "documents_unavailable_reason" not in prov
    # MUTATION: move the registry facet and the key follows — the script reads the facet, it does not construct keys.
    monkeypatch.setitem(SOURCE_REGISTRY["labs"]["raw_layout"], "prefix", "raw/elsewhere/labs")
    assert ing.plan_documents("labs", "2026-10-20", [document])[0]["s3_key"] == "raw/elsewhere/labs/2026-10-20/standard_panel.pdf"
    monkeypatch.setitem(SOURCE_REGISTRY["labs"]["raw_layout"], "scheme", "date-tree")
    with pytest.raises(ing.Refusal, match="not date-folder"):
        ing.plan_documents("labs", "2026-10-20", [document])


def test_dexa_documents_archive_under_the_dexa_prefix(document):
    assert ing.plan_documents("dexa", "2026-11-01", [document])[0]["s3_key"] == "raw/matthew/dexa/2026-11-01/standard_panel.pdf"
    assert SOURCE_REGISTRY["dexa"]["raw_layout"]["prefix"] == "raw/matthew/dexa"


def test_a_back_fill_without_a_document_records_why():
    item = _labs_item(unavailable_reason="placeholder: the 2019 report was never kept")
    assert item["provenance"]["documents"] == [] and item["provenance"]["documents_unavailable_reason"].startswith("placeholder")


def test_a_missing_document_is_refused_before_anything_else(tmp_path):
    with pytest.raises(ing.Refusal, match="document not found"):
        ing.plan_documents("labs", "2026-10-20", [str(tmp_path / "nope.pdf")])


# ── the review step and the write order (acceptance boxes 1 + 3) ────────────────────────


class _FakeS3:
    def __init__(self, calls, existing=None):
        self.calls, self.existing = calls, existing or {}

    def head_object(self, Bucket, Key):
        if Key not in self.existing:
            raise Exception("404 Not Found")
        return {"Metadata": {"sha256": self.existing[Key]}}

    def put_object(self, **kw):
        self.calls.append(("s3.put_object", kw["Key"]))


class _FakeTable:
    def __init__(self, calls, existing=False):
        self.calls, self.existing = calls, existing

    def put_item(self, **kw):
        if self.existing and "ConditionExpression" in kw:
            raise Exception("ConditionalCheckFailedException")
        self.calls.append(("ddb.put_item", kw["Item"]["sk"]))


def test_dry_run_prints_the_review_table_and_writes_nothing(report_csv, document, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ing, "apply", lambda *a, **k: calls.append("apply") or 0)
    rc = ing.main(
        [
            "labs",
            report_csv,
            "--draw-date",
            "2026-10-20",
            "--lab-provider",
            "function_health",
            "--lab-network",
            "quest_diagnostics",
            "--document",
            document,
            "--no-previous",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and calls == []
    assert (
        "DRY RUN" in out
        and "ldl_c" in out
        and "raw/matthew/labs/2026-10-20/standard_panel.pdf" in out
        and "5 markers, 1 out of range" in out
    )


def test_no_document_and_no_reason_is_refused_up_front(report_csv, capsys):
    rc = ing.main(["labs", report_csv, "--draw-date", "2026-10-20", "--lab-provider", "x", "--lab-network", "y", "--no-previous"])
    assert rc == 2 and "REFUSING: no --document" in capsys.readouterr().out


def test_an_off_schema_report_exits_nonzero_without_writing(tmp_path, document, capsys, monkeypatch):
    bad = _write_csv(tmp_path / "bad.csv", [{"marker": "made_up_marker", "value": "1", "unit": "x"}], ["marker", "value", "unit"])
    monkeypatch.setattr(ing, "apply", lambda *a, **k: pytest.fail("apply must not run on a refused report"))
    rc = ing.main(
        [
            "labs",
            bad,
            "--draw-date",
            "2026-10-20",
            "--lab-provider",
            "x",
            "--lab-network",
            "y",
            "--document",
            document,
            "--no-previous",
            "--apply",
        ]
    )
    assert rc == 2 and "REFUSING: made_up_marker" in capsys.readouterr().out


def test_apply_archives_the_document_before_the_row_is_written(document):
    calls = []
    docs = ing.plan_documents("labs", "2026-10-20", [document])
    item = _labs_item(documents=docs)
    rc = ing.apply(item, docs, overwrite=False, s3=_FakeS3(calls), table=_FakeTable(calls))
    assert rc == 0
    assert calls == [("s3.put_object", "raw/matthew/labs/2026-10-20/standard_panel.pdf"), ("ddb.put_item", "DATE#2026-10-20")]


def test_apply_refuses_to_clobber_an_existing_row_or_a_changed_archive_without_overwrite(document, capsys):
    calls = []
    docs = ing.plan_documents("labs", "2026-10-20", [document])
    item = _labs_item(documents=docs)
    assert ing.apply(item, docs, overwrite=False, s3=_FakeS3(calls), table=_FakeTable(calls, existing=True)) == 1
    assert "already exists" in capsys.readouterr().out and ("ddb.put_item", "DATE#2026-10-20") not in calls
    calls.clear()
    changed = _FakeS3(calls, existing={docs[0]["s3_key"]: "0" * 64})
    assert ing.apply(item, docs, overwrite=False, s3=changed, table=_FakeTable(calls)) == 1 and calls == []
    # the same bytes already archived is not a conflict: the archive step is idempotent
    same = _FakeS3(calls, existing={docs[0]["s3_key"]: docs[0]["sha256"]})
    assert ing.apply(item, docs, overwrite=False, s3=same, table=_FakeTable(calls)) == 0 and calls == [("ddb.put_item", "DATE#2026-10-20")]


def test_json_input_is_the_stored_wire_shape(tmp_path, document):
    report = tmp_path / "draw.json"
    report.write_text(
        json.dumps(
            {"biomarkers": {"ldl_c": {"value": 100, "unit": "mg/dL", "ref_text": "<100"}, "hs_crp": {"value": "<0.2", "unit": "mg/L"}}}
        )
    )
    rows, method = ing.read_lab_rows(str(report))
    assert method == "json" and {r["marker"] for r in rows} == {"ldl_c", "hs_crp"}
    item = _labs_item(rows=rows)
    assert item["ingestion_method"] == "csv via scripts/ingest_lab_report.py"  # the method is what the caller names; build is pure
    scan = tmp_path / "scan.json"
    scan.write_text(
        json.dumps(
            {
                "scan_date": "2026-11-01",
                "body_composition": {k.split(".")[1]: float(v[0]) for k, v in DEXA_LEAVES.items() if k.startswith("body_composition.")},
            }
        )
    )
    leaves, method = ing.read_dexa_leaves(str(scan))
    assert method == "json" and "scan_date" not in leaves and "body_composition.body_fat_pct" in leaves


# ── the registry side (the paved road) ──────────────────────────────────────────────────


def test_both_sources_are_registered_with_the_facets_the_road_requires():
    for source, months in (("labs", 6), ("dexa", 3)):  # dexa 3 since #5061 (the charter's ~12 weeks)
        row = SOURCE_REGISTRY[source]
        assert row["cadence_months"] == months and row["stale_hours"] == months * 30 * 24
        assert row["raw_layout"]["scheme"] == "date-folder" and "ingest_lab_report.py" in row["method"]
        assert row.get("paused") is not True and row["capture_channel"] is None and row["capture_channel_reason"]


# ── one analyte, two stored spellings (epic #4625 row: crp_hs / hs_crp) ─────────────────────


def test_alias_table_points_every_spelling_at_a_marker_the_contract_knows():
    for alias, canon in lab_units.MARKER_ALIASES.items():
        assert alias in lab_units.LAB_UNITS and canon in lab_units.LAB_UNITS, "stored history is the contract: both spellings stay"
        assert lab_units.LAB_UNITS[alias] == lab_units.LAB_UNITS[canon], "an alias is the same analyte: same unit, category, kind"
        assert lab_units.canonical_marker(canon) == canon


def test_ingest_accepts_either_spelling_and_stores_the_canonical_one():
    for spelling in ("crp_hs", "CRP-HS", "hs_crp", "hs-crp"):
        item = _labs_item(rows=[{"marker": spelling, "value": "0.4", "unit": "mg/L", "ref_text": "<1.0"}])
        assert set(item["biomarkers"]) == {"hs_crp"}, spelling


def test_ingest_refuses_the_same_analyte_listed_under_both_spellings():
    rows = [
        {"marker": "crp_hs", "value": "0.4", "unit": "mg/L"},
        {"marker": "hs_crp", "value": "0.5", "unit": "mg/L"},
    ]
    with pytest.raises(ing.Refusal, match="listed twice"):
        _labs_item(rows=rows)


def test_previous_value_is_found_under_the_other_spelling():
    previous = {
        "sk": "DATE#2026-04-03",
        "draw_date": "2026-04-03",
        "biomarkers": {"crp_hs": {"value": 0.3, "value_numeric": 0.3, "unit": "mg/L"}},
    }
    item = _labs_item(rows=[{"marker": "hs_crp", "value": "0.4", "unit": "mg/L"}], previous=previous)
    assert (
        item["biomarkers"]["hs_crp"]["previous_value"] == Decimal("0.3") and item["biomarkers"]["hs_crp"]["previous_date"] == "2026-04-03"
    )


def test_reader_resolves_either_spelling_off_a_stored_draw():
    old = {"sk": "DATE#2025-04-17", "biomarkers": {"hs_crp": {"value_numeric": 1.0}}}
    new = {"sk": "DATE#2026-04-03", "biomarkers": {"crp_hs": {"value_numeric": 2.0}}}
    for want in ("hs_crp", "crp_hs"):
        assert labs_schema.marker_numeric(labs_schema.biomarker_entry(old, want)) == 1.0
        assert labs_schema.marker_numeric(labs_schema.biomarker_entry(new, want)) == 2.0
    assert labs_schema.biomarker_entry(new, "ldl_c") is None


def test_coaching_sees_the_draw_that_spelled_it_crp_hs():
    from health import labs_coaching

    class _T:
        def query(self, **kw):
            return {"Items": [{"sk": "DATE#2026-04-03", "biomarkers": {"crp_hs": {"value_numeric": 5.0, "unit": "mg/L"}}}]}

    assert "hs-CRP elevated" in labs_coaching.build_labs_coaching_context(_T(), "USER#matthew#SOURCE#")


def test_mcp_genome_xref_holds_every_spelling():
    import re

    src = open(os.path.join(REPO, "mcp", "labs_helpers.py"), encoding="utf-8").read()
    for alias, canon in lab_units.MARKER_ALIASES.items():
        assert re.search(rf'"{alias}":', src) and re.search(rf'"{canon}":', src)
