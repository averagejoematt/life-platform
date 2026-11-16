"""tests/test_quest_report_4639.py — the Quest result PDF is the labs input, not a CSV the owner types (#4639).

#4981 built archive-first / refuse-off-schema / provenance / review-before-write, but its input
was a hand-typed CSV — and on 2026-10-18 the owner had no file to give it. A Function Health
draw arrives as a "Quest Result" print from the Health Gorilla network; `health/quest_report.py`
reads that print's `pdftotext -layout` text and `scripts/ingest_lab_report.py` takes the PDF
directly (and archives it as the source document).

THE FIXTURE IS THE WIRE'S SHAPE, NOT ITS VALUES. `tests/fixtures/quest_print_layout_4639.txt`
reproduces, line shape for line shape, every layout the two archived 2026-04 prints carry
(`raw/matthew/labs/2026-04-03/standard_panel.pdf`, `cardio_iq_nfl_panel.pdf` — read-only,
2026-11-08): a wrapped test name, a wrapped `(calc)` / `/uL` / `73m2` reference, a value glued
to its flag and reference, an H/L flag, the vendor's previous result + date + flag, the same
test name in two panels, an allergen's CLASS line after a page break, a name that wraps across
a page break, a wrapped result (`RH(D)` / `POSITIVE`), a "See Below" section label, a "SEE NOTE:"
non-result, a label row with a panel note, the patient block, and the duplicate "Enhanced PDF
Report" appendix. The repo is public: every value, name, date and identifier in it is a
placeholder. On the real prints the reader reproduces all 150 stored 2026-04-03 values it
overlaps (value and unit, by a read-only alignment on 2026-11-08 — run in a scratchpad, never
committed).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ingest_lab_report as ing  # noqa: E402
from health import lab_units, quest_report  # noqa: E402

FIXTURE = os.path.join(REPO, "tests", "fixtures", "quest_print_layout_4639.txt")
STAMP = "2030-01-03T00:00:00+00:00"


@pytest.fixture(scope="module")
def text():
    with open(FIXTURE, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def parsed(text):
    return quest_report.parse(text)


def _row(parsed, marker):
    hits = [r for r in parsed["rows"] if r["marker"] == marker]
    assert len(hits) == 1, f"{marker}: {len(hits)} rows"
    return hits[0]


# ── the reader ──────────────────────────────────────────────────────────────────────────


def test_the_fixture_is_recognised_and_a_csv_is_not(text):
    assert quest_report.is_quest_print(text)
    assert not quest_report.is_quest_print("marker,value,unit\nldl_c,100,mg/dL\n")


def test_every_line_shape_reads_to_the_schema_row(parsed):
    expect = {
        # marker: (vendor name joined across wraps, value, unit, ref_text, flag)
        "iron_total": ("IRON, TOTAL", "100", "mcg/dL", "50-180", ""),
        "iron_binding_capacity": ("IRON BINDING CAPACITY", "300", "mcg/dL", "250-425 (calc)", ""),
        "cholesterol_total": ("CHOLESTEROL, TOTAL", "250", "mg/dL", "<200", "high"),
        "ldl_c": ("LDL-CHOLESTEROL", "150", "mg/dL", "(calc)", "high"),
        "chol_hdl_ratio": ("CHOL/HDLC RATIO", "4.0", "ratio", "<5.0 (calc)", ""),
        "egfr": ("EGFR", "100", "mL/min/1.73m2", ">= 60", ""),
        "omega_3_index": ("EPA+DPA+DHA", "3.0", "% by wt", ">5.4", "low"),
        "urine_wbc": ("WBC", "NONE SEEN", "/HPF", "<= 5", ""),
        "urine_hyaline_casts": ("HYALINE CAST", "NONE SEEN", "/LPF", "NONE SEEN", ""),
        "wbc": ("WHITE BLOOD CELL COUNT", "5.0", "Thousand/uL", "3.8-10.8", ""),
        "allergy_common_ragweed": ("COMMON RAGWEED (SHORT) (W1) IGE", "<0.10", "kU/L", "", ""),
        "shbg": ("SEX HORMONE BINDING GLOBULIN", "30", "nmol/L", "10-50", ""),
        "rh_type": ("RH TYPE", "RH(D) POSITIVE", "", "", ""),
        "testosterone_free": ("TESTOSTERONE, FREE", "80", "pg/mL", "46.0-224.0", ""),
        "ldl_pattern": ("LDL PATTERN", "A", "", "A Pattern", ""),
        "9p21_rs10757278": ("rs10757278", "zz", "", "", ""),
        "egfr_cystatin_c": ("eGFR", "100", "mL/min/1.73m2", ">= 60", ""),
    }
    for marker, (name, value, unit, ref_text, flag) in expect.items():
        row = _row(parsed, marker)
        got = (row["vendor_name"], row["value"], row["unit"], row["ref_text"], row["flag"])
        assert got == (name, value, unit, ref_text, flag), marker
        assert lab_units.unit_accepted(marker, row["unit"]), f"{marker}: {row['unit']!r} not a schema unit"


def test_the_same_test_name_in_two_panels_is_two_analytes(parsed):
    """Mutation control for the panel-qualified map: drop the urinalysis key and urine GLUCOSE
    would be stored as blood glucose (and refused as a duplicate)."""
    assert _row(parsed, "glucose")["panel"] == "COMPREHENSIVE METABOLIC PANEL"
    assert _row(parsed, "urine_glucose")["value"] == "NEGATIVE"
    assert ("URINALYSIS, COMPLETE", "GLUCOSE") in quest_report.QUEST_TEST_NAMES


def test_every_vendor_field_on_the_line_is_kept(parsed):
    wbc = _row(parsed, "wbc")
    assert wbc["vendor_previous_value"] == "6.0" and wbc["vendor_previous_date"] == "2029-01-01"
    assert wbc["vendor_previous_flag"] == "low"
    assert wbc["lab_code"] == "NW" and wbc["collected"] == "2030-01-01 06:00 PM UTC"
    assert wbc["vendor_reference"] == "3.8-10.8 Thousand/uL"
    assert _row(parsed, "allergy_birch")["ige_class"] == "2"
    assert _row(parsed, "allergy_common_ragweed")["ige_class"] == "0", "a CLASS line after a page break still rides its allergen"
    assert "Fasting reference interval" in _row(parsed, "glucose")["report_note"]
    assert _row(parsed, "9p21_rs10757278")["report_note"].startswith("COMMENTS:")
    assert parsed["panel_notes"]["URINALYSIS, COMPLETE"].startswith("This urine was analyzed")
    assert parsed["report"] == {
        "status": "Final",
        "time_reported": "2030-01-02 06:09 PM UTC",
        "accession_number": "ZZ000000F",
        "fasting": True,
    }
    assert parsed["collected_dates"] == ["2029-12-30", "2030-01-01"]


def test_a_result_the_lab_did_not_report_is_never_a_value(parsed):
    assert not [r for r in parsed["rows"] if r["marker"] == "bun_creatinine_ratio"]
    (nr,) = parsed["not_reported"]
    assert (nr["marker"], nr["value"]) == ("bun_creatinine_ratio", "SEE NOTE:")
    assert "Not Reported" in nr["report_note"]


def test_the_enhanced_appendix_is_not_read_twice(parsed):
    """The print ends with Quest's own rendering of the same results; a FERRITIN line sits
    only there in the fixture. Mutation: delete the `_ENHANCED` break and it is read."""
    assert not [r for r in parsed["rows"] if r["marker"] == "ferritin"]


def test_nothing_that_identifies_the_patient_is_read(parsed):
    """Name, DOB, phone, patient id, AGE and the physician's address stay on the page — an age
    off a lab header is what the PhenoAge rule keeps off every surface."""
    blob = json.dumps(parsed)
    for needle in ("Test Patient", "1970", "555", "00000000", "Age", "71", "Placeholder Street", "Placeholder Physician"):
        assert needle not in blob, needle


def test_every_map_target_is_a_schema_key_with_a_schema_unit():
    for name, (marker, blank_unit) in quest_report.QUEST_TEST_NAMES.items():
        assert marker in lab_units.LAB_UNITS, f"{name!r} -> {marker}: not in LAB_UNITS"
        assert lab_units.canonical_marker(marker) == marker, f"{name!r}: maps to the alias {marker}, not the canonical key"
        if blank_unit is not None:
            assert lab_units.unit_accepted(marker, blank_unit), f"{name!r}: blank-unit {blank_unit!r} not a schema unit"


# ── the ingest script, end to end on the fixture (dry run: nothing archived, nothing written) ──


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_the_built_draw_carries_vendor_fields_reports_and_the_not_reported_list(text, tmp_path):
    rows, method, meta = ing.read_lab_report(_write(tmp_path, "standard_panel.txt", text))
    assert method == "quest-text"
    item = ing.build_labs_item(
        rows,
        draw_date="2030-01-01",
        lab_provider="function_health",
        lab_network="quest_diagnostics",
        documents=[],
        unavailable_reason="test",
        extraction_method=method,
        reviewer="matthew",
        reports=[meta],
        now=STAMP,
    )
    wbc = item["biomarkers"]["wbc"]
    assert wbc["vendor_name"] == "WHITE BLOOD CELL COUNT" and wbc["vendor_previous_value"] == "6.0"
    assert wbc["flag"] == "normal", "an unflagged result against a printed range is in range on a vendor print"
    assert item["biomarkers"]["rh_type"]["flag"] == "", "no printed range, no flag: never invented"
    assert "bun_creatinine_ratio" not in item["biomarkers"]
    assert item["not_reported"][0]["marker"] == "bun_creatinine_ratio"
    assert item["accession_numbers"] == ["ZZ000000F"] and item["fasting"] is True
    (report,) = item["provenance"]["reports"]
    assert report["format"] == "quest_health_gorilla_print" and report["file"] == "standard_panel.txt"
    assert "not_reported" not in report and "panel_notes" not in report
    assert item["panel_notes"]["URINALYSIS, COMPLETE"]


def test_an_unknown_test_name_refuses_the_draw_by_name(text, tmp_path):
    path = _write(tmp_path, "renamed.txt", text.replace(" IRON, TOTAL   ", " IRON, NEWNAME "))
    with pytest.raises(ing.Refusal, match="IRON, NEWNAME"):
        ing.read_lab_report(path)


def test_a_pdf_that_is_not_a_quest_print_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "pdf_text", lambda path: "some other lab's report\n")
    path = tmp_path / "other.pdf"
    path.write_bytes(b"%PDF-placeholder")
    with pytest.raises(ing.Refusal, match="not a Quest result print"):
        ing.read_lab_report(str(path))


def test_no_pdftotext_is_a_refusal_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(ing.shutil, "which", lambda name: None)
    monkeypatch.setattr(ing, "PDFTOTEXT_FALLBACK", str(tmp_path / "absent"))
    with pytest.raises(ing.Refusal, match="pdftotext not found"):
        ing.pdf_text(str(tmp_path / "x.pdf"))


def test_a_pdf_report_is_itself_archived_first_and_the_dry_run_writes_nothing(text, tmp_path, monkeypatch, capsys):
    """The PDF given as the report joins the documents (archive-first, box 2) without a
    separate --document; two prints make one draw, and a print collected on another day is
    named in the review table."""
    monkeypatch.setattr(ing, "pdf_text", lambda path: text)
    pdf = tmp_path / "standard_panel.pdf"
    pdf.write_bytes(b"%PDF-placeholder")

    def _no_aws(*a, **k):
        raise AssertionError("a dry run must not touch AWS")

    monkeypatch.setattr(ing, "apply", _no_aws)
    rc = ing.main(
        [
            "labs",
            str(pdf),
            "--draw-date",
            "2030-01-01",
            "--lab-provider",
            "function_health",
            "--lab-network",
            "quest_diagnostics",
            "--no-previous",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    prefix = ing.SOURCE_REGISTRY["labs"]["raw_layout"]["prefix"]
    assert f"archive  standard_panel.pdf -> s3://{ing.BUCKET}/{prefix}/2030-01-01/standard_panel.pdf" in out
    assert "not reported by the lab: BUN/CREATININE RATIO" in out
    assert "NOTE collected 2029-12-30 — not the draw date" in out
    assert "DRY RUN" in out


def test_a_csv_cannot_be_mixed_into_a_multi_report_draw(tmp_path, capsys):
    csv_path = _write(tmp_path, "a.csv", "marker,value,unit\nldl_c,100,mg/dL\n")
    rc = ing.main(
        [
            "labs",
            csv_path,
            csv_path,
            "--draw-date",
            "2030-01-01",
            "--lab-provider",
            "x",
            "--lab-network",
            "y",
            "--document-unavailable",
            "test",
            "--no-previous",
        ]
    )
    assert rc == 2
    assert "several reports in one draw" in capsys.readouterr().out
