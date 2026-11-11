"""quest_report.py — read a Quest result report (the Health Gorilla print) into the per-marker rows `scripts/ingest_lab_report.py` validates (#4639).

WHY
  #4981 built the labs path (archive-first, schema-refusing, provenance, review before write),
  but its input was a CSV the owner had to type from the PDF — and the one time he went to
  use it (2026-10-18) there was no file to give it. What a draw actually produces is a PDF:
  Function Health's draws are Quest panels, delivered as a "Quest Result" print from the
  Health Gorilla network (the two archived 2026-04 documents, `standard_panel.pdf` and
  `cardio_iq_nfl_panel.pdf` under the labs `raw_layout` prefix, are both this format).
  This module turns that print's text (`pdftotext -layout`) into the rows the existing
  validator already refuses against, so the PDF the owner downloads IS the input.

WHAT IT READS (and what it deliberately leaves on the page)
  * per result line: the vendor test name, the result, the H/L flag, the reference range
    and its unit (including the `(calc)` and `/uL`-style continuation lines), the vendor's
    own previous result + date + flag, the performing-lab code, the panel and its
    collection timestamp, an allergen's `CLASS` line (-> `ige_class`) and the prose notes
    printed under the result (-> `report_note`). Capture-all: every one of those is kept on
    the row (owner rule 2026-10-04, epic #4625) — interpretation is a reader's job.
  * per report: accession number, report status, time reported, fasting.
  * NOT read: patient name, date of birth, phone, patient id, age, the physician's address.
    They identify a person, not a measurement; the stored draw never needs them, and an
    age off a lab header is exactly what the PhenoAge rule keeps off every surface.
  * the "Enhanced PDF Report" appended after the Health Gorilla pages is Quest's own
    rendering of the SAME results; reading stops there so no result is read twice.

NAME MAP
  `QUEST_TEST_NAMES` maps the vendor's printed test name (after continuation lines are
  joined) to the schema key in `health.lab_units.LAB_UNITS`. It was built by aligning the
  two archived 2026-04 reports with the hand-extracted 2026-04-03 draw row (names only —
  no value appears in the repo, the issue's rule). A name not in the map is NOT guessed:
  `parse()` returns it in `unmapped`, and the ingest refuses the draw by name until a
  reviewed PR adds it. The same test name means different analytes in different panels
  ("GLUCOSE" in a metabolic panel vs. a urinalysis), so a key may be panel-qualified:
  `("URINALYSIS, COMPLETE", "GLUCOSE")` wins over a bare `"GLUCOSE"`.

Pure text in, dicts out: no AWS, no subprocess. `scripts/ingest_lab_report.py` owns the
`pdftotext` call (a laptop tool — this path runs where the owner reviews, never in a Lambda).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from health.lab_units import LAB_UNITS, unit_accepted

#: The text a Health Gorilla Quest print carries on every page — how the format is recognised.
FORMAT_MARKERS: Tuple[str, ...] = ("Quest Result", "Health Gorilla")

_PANEL = re.compile(r"^\s*(?P<panel>\S.*?)\s+Collected:\s*(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)(?:\s+(?P<tz>UTC))?")
_ENHANCED = re.compile(r"^\s*Enhanced PDF Report\b")
_COLUMN_HEADER = re.compile(r"^\s*Test\s+In Range\s+Out Of Range\s+Reference Range", re.MULTILINE)
_BOILER_START = re.compile(r"Printed from Health Gorilla")
_LAB_CODE = re.compile(r"\s+(?P<lab>[A-Z][A-Z0-9]{1,3})$")
_NUMERIC_CELL = re.compile(
    r"^(?P<v>(?:<\s*OR\s*=|>\s*OR\s*=|<=|>=|<|>)?\s*-?\d[\d,]*(?:\.\d+)?)" r"(?:\s+(?P<flag>HH|LL|H|L|A))?(?:\s+(?P<tail>\S.*))?$",
    re.IGNORECASE,
)
_PREVIOUS = re.compile(r"(?:^|\s)(?P<pv>[<>]?-?\d[\d,]*(?:\.\d+)?)(?:\s+(?P<pf>HH|LL|H|L|A))?\s+(?P<pd>\d{2}/\d{2}/\d{4})$")
_UTC_FRAGMENT = re.compile(r"^[\d/:\sAPM]*UTC$")
_RANGE_PREFIX = re.compile(
    r"^(?:(?:<|>)\s*OR\s*=\s*|<=|>=|<|>|≤|≥)?\s*-?\d[\d,]*(?:\.\d+)?(?:\s*-\s*-?\d[\d,]*(?:\.\d+)?)?\s*",
    re.IGNORECASE,
)
_LOWER = re.compile(r"[a-z]")
_LAB_CODE_CELL = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
_QUALITATIVE_REF = re.compile(r"^([A-Z][A-Z ]*?)(?:\s+(/\S+))?$")
_NOT_REPORTED = re.compile(r"^(?:SEE NOTE:?|NOT REPORTED|TNP|DNR|QNS)$", re.IGNORECASE)
_ACCESSION = re.compile(r"\bAccession\b\s+(?P<acc>[A-Z]{2}\d{5,}[A-Z]?)\b")
_STATUS = re.compile(r"\bSTATUS:\s*(?P<status>\w+)")
_REPORTED = re.compile(r"Time Reported:\s+(?P<ts>\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)")
_FASTING = re.compile(r"^\s*FASTING:\s*(?P<f>YES|NO)\b", re.IGNORECASE)

_FLAGS = {"H": "high", "HH": "high", "L": "low", "LL": "low"}

MapKey = Union[str, Tuple[str, str]]

#: vendor test name (continuation lines joined) -> (schema marker key, unit to record when the report prints none — or None).
#: A panel-qualified key `(panel, test)` wins over a bare one. Built by aligning the archived 2026-04 reports with the
#: hand-extracted 2026-04-03 draw (names only); see the module docstring. Grows by reviewed PR, like `LAB_UNITS`.
QUEST_TEST_NAMES: Dict[MapKey, Tuple[str, Optional[str]]] = {
    # iron
    "IRON, TOTAL": ("iron_total", None),
    "IRON BINDING CAPACITY": ("iron_binding_capacity", None),
    "% SATURATION": ("iron_saturation_pct", None),
    "FERRITIN": ("ferritin", None),
    # lipids
    "CHOLESTEROL, TOTAL": ("cholesterol_total", None),
    "HDL CHOLESTEROL": ("hdl", None),
    "TRIGLYCERIDES": ("triglycerides", None),
    "LDL-CHOLESTEROL": ("ldl_c", None),
    "CHOL/HDLC RATIO": ("chol_hdl_ratio", "ratio"),
    "NON HDL CHOLESTEROL": ("non_hdl_c", None),
    "LIPOPROTEIN (a)": ("lipoprotein_a", None),
    "APOLIPOPROTEIN B": ("apob", None),
    ("APOLIPOPROTEIN EVALUATION", "APOLIPOPROTEIN B"): ("apob_cardio_iq", None),
    "APOLIPOPROTEIN A1": ("apolipoprotein_a1", None),
    "APOLIPOPROTEIN B/A1 RATIO": ("apob_apoa1_ratio", "ratio"),
    "LDL PARTICLE NUMBER": ("ldl_particle_number", None),
    "LDL SMALL": ("ldl_small", None),
    "LDL MEDIUM": ("ldl_medium", None),
    "HDL LARGE": ("hdl_large", None),
    "LDL PATTERN": ("ldl_pattern", None),
    "LDL PEAK SIZE": ("ldl_peak_size", None),
    "OXIDIZED LDL": ("oxidized_ldl", None),
    "AALP APO A1": ("aalp_apo_a1", None),
    "AALP APO C1": ("aalp_apo_c1", None),
    "AALP APO C2": ("aalp_apo_c2", None),
    "AALP APO C3": ("aalp_apo_c3", None),
    "AALP APO C4": ("aalp_apo_c4", None),
    "HDLFX PCEC": ("hdlfx_pcec", None),
    "HDLFX PCAD SCORE": ("hdlfx_pcad_score", "score"),
    "LP PLA2 ACTIVITY": ("lp_pla2_activity", None),
    # metabolic panel
    "GGT": ("ggt", None),
    "URIC ACID": ("uric_acid", None),
    "GLUCOSE": ("glucose", None),
    "UREA NITROGEN (BUN)": ("bun", None),
    "CREATININE": ("creatinine", None),
    "EGFR": ("egfr", None),
    "BUN/CREATININE RATIO": ("bun_creatinine_ratio", None),
    "SODIUM": ("sodium", None),
    "POTASSIUM": ("potassium", None),
    "CHLORIDE": ("chloride", None),
    "CARBON DIOXIDE": ("carbon_dioxide", None),
    "CALCIUM": ("calcium", None),
    "PROTEIN, TOTAL": ("protein_total", None),
    "ALBUMIN": ("albumin", None),
    "GLOBULIN": ("globulin", None),
    "ALBUMIN/GLOBULIN RATIO": ("albumin_globulin_ratio", "ratio"),
    "BILIRUBIN, TOTAL": ("bilirubin_total", None),
    "ALKALINE PHOSPHATASE": ("alkaline_phosphatase", None),
    "AST": ("ast", None),
    "ALT": ("alt", None),
    "AMYLASE": ("amylase", None),
    "LIPASE": ("lipase", None),
    "HEMOGLOBIN A1c": ("hba1c", None),
    "INSULIN": ("insulin_fasting", None),
    "INSULIN, INTACT, LC/MS/MS": ("insulin_intact_lcms", None),
    "C-PEPTIDE, LC/MS/MS": ("c_peptide", None),
    "INSULIN RESISTANCE SCORE": ("insulin_resistance_score", "score"),
    "LEPTIN": ("leptin", None),
    "ADIPONECTIN": ("adiponectin", None),
    "TMAO (TRIMETHYLAMINE N OXIDE)": ("tmao", None),
    # kidney
    "ALBUMIN, URINE": ("albumin_urine", None),
    "CYSTATIN C": ("cystatin_c", None),
    ("CYSTATIN C WITH eGFR", "eGFR"): ("egfr_cystatin_c", None),
    # minerals, vitamins, metals
    "MAGNESIUM, RBC": ("magnesium_rbc", None),
    "ZINC": ("zinc", None),
    "MERCURY, BLOOD": ("mercury_blood", None),
    "LEAD (VENOUS)": ("lead_venous", None),
    "VITAMIN D,25-OH, TOTAL,IA": ("vitamin_d_25oh", None),
    "METHYLMALONIC ACID": ("methylmalonic_acid", None),
    "HOMOCYSTEINE": ("homocysteine", None),
    # fatty acids (OmegaCheck)
    "EPA+DPA+DHA": ("omega_3_index", None),
    "ARACHIDONIC ACID /EPA RATIO": ("arachidonic_epa_ratio", "ratio"),
    "OMEGA-6/OMEGA-3 RATIO": ("omega_6_omega_3_ratio", "ratio"),
    "OMEGA-3 TOTAL": ("omega_3_total_pct", None),
    "EPA": ("epa", None),
    "DPA": ("dpa", None),
    "DHA": ("dha", None),
    "OMEGA-6 TOTAL": ("omega_6_total_pct", None),
    "ARACHIDONIC ACID": ("arachidonic_acid", None),
    "LINOLEIC ACID": ("linoleic_acid", None),
    # urinalysis — panel-qualified, because GLUCOSE/PROTEIN/WBC/RBC also name blood analytes
    ("URINALYSIS, COMPLETE", "COLOR"): ("urine_color", None),
    ("URINALYSIS, COMPLETE", "APPEARANCE"): ("urine_appearance", None),
    ("URINALYSIS, COMPLETE", "SPECIFIC GRAVITY"): ("urine_specific_gravity", None),
    ("URINALYSIS, COMPLETE", "PH"): ("urine_ph", None),
    ("URINALYSIS, COMPLETE", "GLUCOSE"): ("urine_glucose", None),
    ("URINALYSIS, COMPLETE", "BILIRUBIN"): ("urine_bilirubin", None),
    ("URINALYSIS, COMPLETE", "KETONES"): ("urine_ketones", None),
    ("URINALYSIS, COMPLETE", "OCCULT BLOOD"): ("urine_blood", None),
    ("URINALYSIS, COMPLETE", "PROTEIN"): ("urine_protein", None),
    ("URINALYSIS, COMPLETE", "NITRITE"): ("urine_nitrite", None),
    ("URINALYSIS, COMPLETE", "LEUKOCYTE ESTERASE"): ("urine_leukocyte_esterase", None),
    ("URINALYSIS, COMPLETE", "WBC"): ("urine_wbc", None),
    ("URINALYSIS, COMPLETE", "RBC"): ("urine_rbc", None),
    ("URINALYSIS, COMPLETE", "SQUAMOUS EPITHELIAL CELLS"): ("urine_squamous_epithelial_cells", None),
    ("URINALYSIS, COMPLETE", "BACTERIA"): ("urine_bacteria", None),
    ("URINALYSIS, COMPLETE", "HYALINE CAST"): ("urine_hyaline_casts", None),
    # CBC
    "WHITE BLOOD CELL COUNT": ("wbc", None),
    "RED BLOOD CELL COUNT": ("rbc", None),
    "HEMOGLOBIN": ("hemoglobin", None),
    "HEMATOCRIT": ("hematocrit", None),
    "MCV": ("mcv", None),
    "MCH": ("mch", None),
    "MCHC": ("mchc", None),
    "RDW": ("rdw", None),
    "PLATELET COUNT": ("platelet_count", None),
    "MPV": ("mpv", None),
    "ABSOLUTE NEUTROPHILS": ("absolute_neutrophils", None),
    "ABSOLUTE LYMPHOCYTES": ("absolute_lymphocytes", None),
    "ABSOLUTE MONOCYTES": ("absolute_monocytes", None),
    "ABSOLUTE EOSINOPHILS": ("absolute_eosinophils", None),
    "ABSOLUTE BASOPHILS": ("absolute_basophils", None),
    "NEUTROPHILS": ("neutrophils_pct", None),
    "LYMPHOCYTES": ("lymphocytes_pct", None),
    "MONOCYTES": ("monocytes_pct", None),
    "EOSINOPHILS": ("eosinophils_pct", None),
    "BASOPHILS": ("basophils_pct", None),
    "FIBRINOGEN ANTIGEN, NEPHELOMETRY": ("fibrinogen", None),
    # inflammation, autoimmune
    "HS CRP": ("hs_crp", None),
    "RHEUMATOID FACTOR": ("rheumatoid_factor", None),
    "ANA SCREEN, IFA": ("ana_screen", None),
    "THYROGLOBULIN ANTIBODIES": ("thyroglobulin_antibodies", None),
    "THYROID PEROXIDASE ANTIBODIES": ("thyroid_peroxidase_antibodies", None),
    "MYELOPEROXIDASE": ("myeloperoxidase", None),
    "NEUROFILAMENT LIGHT CHAIN": ("nfl_neurofilament_light_chain", None),
    # hormones
    "CORTISOL, TOTAL": ("cortisol_total", None),
    "DHEA SULFATE": ("dhea_sulfate", None),
    "FSH": ("fsh", None),
    "LH": ("lh", None),
    "PROLACTIN": ("prolactin", None),
    "T4, FREE": ("t4_free", None),
    "T3, FREE": ("t3_free", None),
    "TSH": ("tsh", None),
    "ESTRADIOL": ("estradiol", None),
    "SEX HORMONE BINDING GLOBULIN": ("shbg", None),
    "TESTOSTERONE, TOTAL, MS": ("testosterone_total", None),
    "TESTOSTERONE, FREE": ("testosterone_free", None),
    "PSA, TOTAL": ("psa_total", None),
    "PSA, FREE": ("psa_free", None),
    "PSA, % FREE": ("psa_pct_free", None),
    # blood type, genetics
    "ABO GROUP": ("abo_group", None),
    "RH TYPE": ("rh_type", None),
    "LPA ASPIRIN GENOTYPE": ("lpa_aspirin_genotype", None),
    ("9p21 GENOTYPE", "rs10757278"): ("9p21_rs10757278", None),
    ("9p21 GENOTYPE", "rs1333049"): ("9p21_rs1333049", None),
    ("4q25 AF RISK GENOTYPE", "rs2200733"): ("4q25_rs2200733", None),
    ("4q25 AF RISK GENOTYPE", "rs10033464"): ("4q25_rs10033464", None),
    # respiratory allergy profile (each allergen's CLASS line rides on its row as `ige_class`)
    "DERMATOPHAGOIDES PTERONYSSINUS (D1) IGE": ("allergy_dust_mite_d_pteronyssinus", None),
    "DERMATOPHAGOIDES FARINAE (D2) IGE": ("allergy_dust_mite_d_farinae", None),
    "PENICILLIUM NOTATUM (M1) IGE": ("allergy_penicillium_notatum", None),
    "CLADOSPORIUM HERBARUM (M2) IGE": ("allergy_cladosporium_herbarum", None),
    "ASPERGILLUS FUMIGATUS (M3) IGE": ("allergy_aspergillus_fumigatus", None),
    "ALTERNARIA ALTERNATA (M6) IGE": ("allergy_alternaria_alternata", None),
    "CAT DANDER (E1) IGE": ("allergy_cat_dander", None),
    "DOG DANDER (E5) IGE": ("allergy_dog_dander", None),
    "COCKROACH (I6) IGE": ("allergy_cockroach", None),
    "MAPLE (BOX ELDER) (T1) IGE": ("allergy_maple_box_elder", None),
    "ALDER (T2) IGE": ("allergy_alder", None),
    "BIRCH (T3) IGE": ("allergy_birch", None),
    "MOUNTAIN CEDAR (T6) IGE": ("allergy_mountain_cedar", None),
    "WALNUT TREE (T10) IGE": ("allergy_walnut_tree", None),
    "COTTONWOOD (T14) IGE": ("allergy_cottonwood", None),
    "WHITE ASH (T15) IGE": ("allergy_white_ash", None),
    "OAK (T7) IGE": ("allergy_oak", None),
    "ELM (T8) IGE": ("allergy_elm", None),
    "TIMOTHY GRASS (G6) IGE": ("allergy_timothy_grass", None),
    "COMMON RAGWEED (SHORT) (W1) IGE": ("allergy_common_ragweed", None),
    "ROUGH PIGWEED (W14) IGE": ("allergy_rough_pigweed", None),
    "SHEEP SORREL (W18) IGE": ("allergy_sheep_sorrel", None),
    "NETTLE (W20) IGE": ("allergy_nettle", None),
    "MOUSE URINE PROTEINS (E72) IGE": ("allergy_mouse_urine_proteins", None),
    "IMMUNOGLOBULIN E": ("allergy_total_ige", None),
}


def is_quest_print(text: str) -> bool:
    """True when `text` is a Health Gorilla Quest result print (the format this module reads)."""
    return all(marker in text for marker in FORMAT_MARKERS) and _COLUMN_HEADER.search(text) is not None


def _iso(mdy: str) -> str:
    m, d, y = mdy.split("/")
    return f"{y}-{m}-{d}"


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().rstrip(",").strip()


def normalize_ref(ref: str) -> str:
    """'> OR = 40' -> '>= 40', '< or = 5' -> '<= 5', '<OR=100' -> '<= 100'; whitespace collapsed."""
    text = re.sub(r"<\s*OR\s*=\s*", "<= ", ref, flags=re.IGNORECASE)
    text = re.sub(r">\s*OR\s*=\s*", ">= ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def split_reference(cell: str) -> Tuple[str, str]:
    """A printed reference cell -> (range text, unit).

    '50-180 mcg/dL' -> ('50-180', 'mcg/dL') · '20-48 % (calc)' -> ('20-48 (calc)', '%') ·
    'mg/dL (calc)' -> ('(calc)', 'mg/dL') · '> OR = 40 mg/dL' -> ('>= 40', 'mg/dL') ·
    'See Note: mg/dL' -> ('See Note:', 'mg/dL') · 'NONE SEEN /HPF' -> ('NONE SEEN', '/HPF') ·
    'NEGATIVE' -> ('NEGATIVE', '').
    """
    text = normalize_ref(cell)
    calc = "(calc)" if "(calc)" in text else ""
    text = re.sub(r"\s*\(calc\)\s*", " ", text).strip()
    if text.lower().startswith("see note:"):
        rng, rest = "See Note:", text[len("see note:") :].strip()
    else:
        m = _RANGE_PREFIX.match(text)
        if m and m.group(0).strip():
            rng, rest = m.group(0).strip(), text[m.end() :].strip()
        else:
            rng, rest = "", text
    if rest and not rng:
        qual = _QUALITATIVE_REF.match(rest)
        if qual:
            rng, rest = qual.group(1), qual.group(2) or ""
    return " ".join(p for p in (rng, calc) if p), rest.strip()


def _cells(line: str) -> List[Tuple[int, str]]:
    """(start column, text) per printed cell — words one space apart are one cell, two or more spaces split cells."""
    return [(m.start(), m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", line)]


def _parse_result(line: str) -> Optional[Dict[str, Any]]:
    """One printed result line -> its fields, or None when the line is not a result row."""
    m = _LAB_CODE.search(line.rstrip())
    if not m:
        return None
    cells = _cells(line[: m.start()])
    if len(cells) < 2:
        return None
    name_col, name = cells[0]
    value_col, value_cell = cells[1]
    rest = [c for _, c in cells[2:]]
    ref_col: Optional[int] = cells[2][0] if len(cells) > 2 else None
    num = _NUMERIC_CELL.match(value_cell)
    flag = ""
    if num:
        raw_v = num.group("v").strip()
        value = normalize_ref(raw_v).replace(" ", "") if raw_v[:1] in "<>" else raw_v
        flag = _FLAGS.get((num.group("flag") or "").upper(), "")
        if num.group("tail"):
            rest = [num.group("tail")] + rest
            ref_col = value_col + value_cell.index(num.group("tail"))
    else:
        value = value_cell.strip()
    remainder = "  ".join(rest).strip()
    prev: Dict[str, Any] = {}
    pm = _PREVIOUS.search(remainder)
    if pm:
        prev = {"vendor_previous_value": pm.group("pv"), "vendor_previous_date": _iso(pm.group("pd"))}
        if pm.group("pf"):
            prev["vendor_previous_flag"] = _FLAGS.get(pm.group("pf").upper(), pm.group("pf"))
        remainder = remainder[: pm.start()].strip()
    return {
        "vendor_name": name,
        "value": value,
        "vendor_flag": flag,
        "vendor_reference": re.sub(r"\s+", " ", remainder).strip(),
        "lab_code": m.group("lab"),
        **prev,
        "_name_col": name_col,
        "_value_col": value_col,
        "_ref_col": ref_col,
    }


def _continuation(row: Dict[str, Any], cells: List[Tuple[int, str]]) -> Optional[List[Tuple[str, str]]]:
    """The wrapped pieces of `row` on this line, as [(field, text)], or None when the line is not a continuation.

    A wrapped test name starts at the name's own column and is upper-case ("CAPACITY", "(BUN)",
    "FARINAE (D2) IGE"); a wrapped result sits between the name and the reference ("RH(D)" /
    "POSITIVE", printed a few columns left of the first half); a
    wrapped reference sits in the reference column and is one short token ("(calc)", "/uL", "73m2").
    Anything else (prose, a second sentence) is a note, not a continuation.
    """
    out: List[Tuple[str, str]] = []
    name_col: int = row["_name_col"]
    ref_col: Optional[int] = row["_ref_col"]
    for col, text in cells:
        if col <= name_col + 3:
            if _LOWER.search(text):
                return None
            out.append(("vendor_name", text))
        elif len(text) > 15 or " " in text:
            return None
        elif ref_col is None or col < ref_col - 1:
            if _LOWER.search(text):
                return None  # "(Note)" — a note heading, not a wrapped result
            out.append(("value", text))
        else:
            out.append(("vendor_reference", text))
    return out or None


def _lookup(panel: str, name: str) -> Optional[Tuple[str, Optional[str]]]:
    return QUEST_TEST_NAMES.get((panel, name)) or QUEST_TEST_NAMES.get(name)


def _finish(row: Dict[str, Any], unmapped: List[Tuple[str, str]]) -> None:
    """Resolve the joined name to a schema key and split the reference into range + unit."""
    row.pop("_name_col", None)
    row.pop("_value_col", None)
    row.pop("_ref_col", None)
    row.pop("_noted", None)
    row["vendor_name"] = _norm_name(row["vendor_name"])
    raw_ref = row.pop("vendor_reference")
    ref_text, unit = split_reference(raw_ref)
    row["vendor_reference"] = normalize_ref(raw_ref)
    hit = _lookup(row["panel"], row["vendor_name"])
    if hit is None:
        unmapped.append((row["panel"], row["vendor_name"]))
        row["marker"] = ""
    else:
        row["marker"], blank_unit = hit
        if not unit and blank_unit is not None:
            unit = blank_unit
        spec = LAB_UNITS.get(row["marker"])
        if spec and spec[2] == "qualitative" and "" in spec[0] and unit and not unit_accepted(row["marker"], unit):
            # a qualitative marker's printed reference is words ("A Pattern"), not a unit
            ref_text, unit = f"{ref_text} {unit}".strip(), ""
    row["unit"] = unit
    row["ref_text"] = ref_text
    row["flag"] = row["vendor_flag"]


def parse(text: str) -> Dict[str, Any]:
    """The report's results and metadata.

    Returns {"rows", "not_reported", "unmapped", "collected_dates", "panel_notes", "report"}.
    Each row carries `marker` (the schema key, or "" when unmapped), `unit`, `ref_text`,
    `flag`, `panel`, `collected` and every vendor field read (module docstring). A line whose
    result is "SEE NOTE:" / "Not Reported" is listed in `not_reported`, never stored as a
    value. Pure.
    """
    rows: List[Dict[str, Any]] = []
    not_reported: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {}
    panel_notes: Dict[str, str] = {}
    panel = ""
    collected = ""
    in_header = True  # the patient/physician block a page opens with, up to the column header line
    attached: Optional[Dict[str, Any]] = None  # the row continuation lines and notes still belong to
    last_row: Optional[Dict[str, Any]] = None  # the last stored row (an allergen's CLASS line follows it)
    note_lines: List[str] = []

    def flush_note() -> None:
        if note_lines:
            joined = re.sub(r"\s+", " ", " ".join(n.strip() for n in note_lines))
            if attached is not None:
                attached["report_note"] = (attached.get("report_note", "") + " " + joined).strip()
            elif panel:
                panel_notes[panel] = (panel_notes.get(panel, "") + " " + joined).strip()
        note_lines.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if _ENHANCED.match(line):
            break
        if in_header:
            for rx, key in ((_ACCESSION, "accession_number"), (_STATUS, "status"), (_REPORTED, "time_reported")):
                hit = rx.search(line)
                if hit and key not in report:
                    report[key] = hit.group(1)
            if _COLUMN_HEADER.match(line):
                in_header = False
            continue
        if _BOILER_START.search(line):
            # a page break: the row above may still wrap onto the next page ("SEX HORMONE" / "BINDING GLOBULIN")
            flush_note()
            in_header = True
            continue
        if not line.strip():
            continue
        fasting = _FASTING.match(line)
        if fasting:
            report["fasting"] = fasting.group("f").upper() == "YES"
            continue
        ph = _PANEL.match(line)
        if ph:
            flush_note()
            attached = None
            panel = _norm_name(ph.group("panel"))
            collected = f"{_iso(ph.group('date'))} {ph.group('time')}{' UTC' if ph.group('tz') else ''}"
            continue
        if _UTC_FRAGMENT.match(line.strip()):
            continue
        result = _parse_result(line)
        if result is not None:
            flush_note()
            if result["vendor_name"].upper() == "CLASS" and last_row is not None:
                last_row["ige_class"] = result["value"]
                continue
            if result["value"].strip().lower() == "see below":
                # a section label (COMMENTS, METHOD, LIMITATIONS...) whose text belongs to the result above it
                if attached is not None:
                    attached["_noted"] = True
                    note_lines.append(f"{_norm_name(result['vendor_name'])}:")
                continue
            result["panel"] = panel
            result["collected"] = collected
            if _NOT_REPORTED.match(result["value"]):
                not_reported.append(result)
            else:
                rows.append(result)
                last_row = result
            attached = result
            continue
        cells = _cells(line)
        if len(cells) == 2 and _LAB_CODE_CELL.match(cells[1][1]) and not _LOWER.search(cells[0][1]):
            # a label row with no result ("NOTE  NW", "INTERPRETATION  NW"): what follows is the panel's
            flush_note()
            attached = None
            continue
        if attached is not None and not attached.get("_noted") and not note_lines:
            pieces = _continuation(attached, cells)
            if pieces is not None:
                for field, piece in pieces:
                    if field == "vendor_reference":
                        ref = attached[field]
                        glue = "" if piece.startswith("/") or ref.endswith(("/", ".")) else " "
                        attached[field] = f"{ref}{glue}{piece}".strip()
                    else:
                        attached[field] = f"{attached[field]} {piece}".strip()
                continue
        if attached is not None:
            attached["_noted"] = True
        note_lines.append(line)
    flush_note()

    if "time_reported" in report:
        stamp = report["time_reported"].split(None, 1)
        report["time_reported"] = f"{_iso(stamp[0])} {stamp[1]} UTC" if len(stamp) == 2 else report["time_reported"]
    unmapped: List[Tuple[str, str]] = []
    for row in rows:
        _finish(row, unmapped)
    for row in not_reported:
        _finish(row, [])
    return {
        "rows": rows,
        "not_reported": not_reported,
        "unmapped": unmapped,
        "collected_dates": sorted({r["collected"][:10] for r in rows if r.get("collected")}),
        "panel_notes": panel_notes,
        "report": report,
    }
