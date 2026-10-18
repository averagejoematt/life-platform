"""lab_units.py — the marker and unit contract a lab draw or DEXA scan must satisfy to be written (#4639).

WHY
  Until #4639 nothing wrote `SOURCE#labs` or `SOURCE#dexa`: every stored draw and scan was
  typed in by a session, with no validator, no unit contract and no provenance. The owner
  ruled (Q37 on #4644, 2026-10-17) that a repeatable upload -> review -> store path is
  wanted before the next draw. `scripts/ingest_lab_report.py` is that path; THIS module is
  the schema it refuses against. A marker key or unit that is not here is not written —
  the table grows by a reviewed PR, never by whatever a report happened to call a thing.

WHERE THE VOCABULARY COMES FROM
  Read from the live partitions on 2026-10-17 (DynamoDB `USER#matthew#SOURCE#labs`, 8 draw
  records, 189 distinct marker keys, 442 marker objects; `SOURCE#dexa`, 2 scan records).
  Only the NAMES, UNITS, CATEGORIES and value KINDS were taken — no value appears here or
  anywhere in the repo (the issue's own rule). Where a marker was stored under more than
  one unit spelling across draws (`alt`: "U/L" and "IU/L"; `egfr`: "mL/min/1.73m2" and
  "mL/min/1.73"), every spelling that has been stored is accepted, most-frequent first —
  the stored history is the contract, not a tidied version of it.

SHAPE
  LAB_UNITS:   marker_key -> (accepted_units, category, kind)
               accepted_units: tuple of unit strings; ("",) means the marker carries no
               unit (genetics, blood type, qualitative screens).
               kind: "numeric" (value_numeric expected) | "qualitative" (string value).
  DEXA_FIELDS: dotted leaf path -> "number" | "str", the union of every leaf the two live
               scan records hold. The unit of a DEXA number is carried by the path's own
               suffix (`_lb`, `_pct`, `_g`, `_kg_m2`, `t_score`...) — `dexa_unit_for()`.

Consumers: `scripts/ingest_lab_report.py` (the writer), `tests/test_lab_report_ingest_4639.py`.
Bundled with the rest of `health/` (#781); no lambda imports it today.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

LabRow = Tuple[Tuple[str, ...], str, str]

#: marker_key -> (accepted units, category, kind). See the module docstring for provenance.
LAB_UNITS: Dict[str, LabRow] = {
    "4q25_rs10033464": (("",), "genetics", "qualitative"),
    "4q25_rs2200733": (("",), "genetics", "qualitative"),
    "9p21_rs10757278": (("",), "genetics", "qualitative"),
    "9p21_rs1333049": (("",), "genetics", "qualitative"),
    "aalp_apo_a1": (("nmol/L",), "lipids", "numeric"),
    "aalp_apo_c1": (("nmol/L",), "lipids", "numeric"),
    "aalp_apo_c2": (("nmol/L",), "lipids", "numeric"),
    "aalp_apo_c3": (("nmol/L",), "lipids", "numeric"),
    "aalp_apo_c4": (("nmol/L",), "lipids", "numeric"),
    "abo_group": (("",), "blood_type", "qualitative"),
    "abs_basophils": (("cells/uL",), "cbc_differential", "numeric"),
    "abs_eosinophils": (("cells/uL",), "cbc_differential", "numeric"),
    "abs_lymphocytes": (("cells/uL",), "cbc_differential", "numeric"),
    "abs_monocytes": (("cells/uL",), "cbc_differential", "numeric"),
    "abs_neutrophils": (("cells/uL",), "cbc_differential", "numeric"),
    "absolute_basophils": (("cells/uL",), "cbc", "numeric"),
    "absolute_eosinophils": (("cells/uL",), "cbc", "numeric"),
    "absolute_lymphocytes": (("cells/uL",), "cbc", "numeric"),
    "absolute_monocytes": (("cells/uL",), "cbc", "numeric"),
    "absolute_neutrophils": (("cells/uL",), "cbc", "numeric"),
    "adiponectin": (("ug/mL",), "metabolic", "numeric"),
    "ag_ratio": (("",), "metabolic", "numeric"),
    "albumin": (("g/dL",), "metabolic", "numeric"),
    "albumin_globulin_ratio": (("ratio",), "metabolic", "numeric"),
    "albumin_urine": (("mg/dL",), "kidney", "numeric"),
    "alkaline_phosphatase": (("IU/L", "U/L"), "liver", "numeric"),
    "allergy_alder": (("kU/L",), "allergies", "numeric"),
    "allergy_alternaria_alternata": (("kU/L",), "allergies", "numeric"),
    "allergy_aspergillus_fumigatus": (("kU/L",), "allergies", "numeric"),
    "allergy_birch": (("kU/L",), "allergies", "numeric"),
    "allergy_cat_dander": (("kU/L",), "allergies", "numeric"),
    "allergy_cladosporium_herbarum": (("kU/L",), "allergies", "numeric"),
    "allergy_cockroach": (("kU/L",), "allergies", "numeric"),
    "allergy_common_ragweed": (("kU/L",), "allergies", "numeric"),
    "allergy_cottonwood": (("kU/L",), "allergies", "numeric"),
    "allergy_dog_dander": (("kU/L",), "allergies", "numeric"),
    "allergy_dust_mite_d_farinae": (("kU/L",), "allergies", "numeric"),
    "allergy_dust_mite_d_pteronyssinus": (("kU/L",), "allergies", "numeric"),
    "allergy_elm": (("kU/L",), "allergies", "numeric"),
    "allergy_maple_box_elder": (("kU/L",), "allergies", "numeric"),
    "allergy_mountain_cedar": (("kU/L",), "allergies", "numeric"),
    "allergy_mouse_urine_proteins": (("kU/L",), "allergies", "numeric"),
    "allergy_nettle": (("kU/L",), "allergies", "numeric"),
    "allergy_oak": (("kU/L",), "allergies", "numeric"),
    "allergy_penicillium_notatum": (("kU/L",), "allergies", "numeric"),
    "allergy_rough_pigweed": (("kU/L",), "allergies", "numeric"),
    "allergy_sheep_sorrel": (("kU/L",), "allergies", "numeric"),
    "allergy_timothy_grass": (("kU/L",), "allergies", "numeric"),
    "allergy_total_ige": (("kU/L",), "allergies", "numeric"),
    "allergy_walnut_tree": (("kU/L",), "allergies", "numeric"),
    "allergy_white_ash": (("kU/L",), "allergies", "numeric"),
    "alt": (("IU/L", "U/L"), "liver", "numeric"),
    "amylase": (("U/L",), "digestive", "numeric"),
    "ana_screen": (("",), "immune", "qualitative"),
    "apob": (("mg/dL",), "lipids", "numeric"),
    "apob_apoa1_ratio": (("ratio",), "lipids", "numeric"),
    "apob_cardio_iq": (("mg/dL",), "lipids", "numeric"),
    "apolipoprotein_a1": (("mg/dL",), "lipids", "numeric"),
    "arachidonic_acid": (("% by wt",), "omega_fatty_acids", "numeric"),
    "arachidonic_acid_epa_ratio": (("",), "omega_fatty_acids", "numeric"),
    "arachidonic_epa_ratio": (("ratio",), "fatty_acids", "numeric"),
    "ast": (("IU/L", "U/L"), "liver", "numeric"),
    "basophils_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "basophils_pct": (("%",), "cbc_differential", "numeric"),
    "bilirubin_total": (("mg/dL",), "liver", "numeric"),
    "bun": (("mg/dL",), "kidney", "numeric"),
    "bun_creatinine_ratio": (("",), "kidney", "numeric"),
    "c_peptide": (("ng/mL",), "metabolic", "numeric"),
    "calcium": (("mg/dL",), "minerals", "numeric"),
    "carbon_dioxide": (("mmol/L",), "electrolytes", "numeric"),
    "chloride": (("mmol/L",), "electrolytes", "numeric"),
    "chol_hdl_ratio": (("ratio", ""), "lipids", "numeric"),
    "cholesterol_total": (("mg/dL",), "lipids", "numeric"),
    "co2": (("mmol/L",), "electrolytes", "numeric"),
    "cortisol_total": (("mcg/dL",), "hormones", "numeric"),
    "creatinine": (("mg/dL",), "kidney", "numeric"),
    "crp_hs": (("mg/L",), "inflammation", "numeric"),
    "cystatin_c": (("mg/L",), "kidney", "numeric"),
    "dha": (("% by wt",), "omega_fatty_acids", "numeric"),
    "dhea_sulfate": (("mcg/dL",), "hormones", "numeric"),
    "dpa": (("% by wt",), "omega_fatty_acids", "numeric"),
    "egfr": (("mL/min/1.73", "mL/min/1.73m2"), "kidney", "numeric"),
    "eosinophils_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "eosinophils_pct": (("%",), "cbc_differential", "numeric"),
    "epa": (("% by wt",), "omega_fatty_acids", "numeric"),
    "estradiol": (("pg/mL",), "hormones", "numeric"),
    "ferritin": (("ng/mL",), "iron", "numeric"),
    "fibrinogen": (("mg/dL",), "inflammation", "numeric"),
    "fsh": (("mIU/mL",), "hormones", "numeric"),
    "galleri_cancer_signal": (("",), "cancer_screening", "qualitative"),
    "galleri_predicted_signal_origin": (("",), "cancer_screening", "qualitative"),
    "ggt": (("U/L",), "liver", "numeric"),
    "globulin": (("g/dL",), "metabolic", "numeric"),
    "glucose": (("mg/dL",), "metabolic", "numeric"),
    "hba1c": (("%",), "diabetes", "numeric"),
    "hdl": (("mg/dL",), "lipids", "numeric"),
    "hdl_large": (("nmol/L",), "lipids_advanced", "numeric"),
    "hdlfx_pcad_score": (("score",), "lipids", "numeric"),
    "hdlfx_pcec": (("% efflux/4hr",), "lipids", "numeric"),
    "hematocrit": (("%",), "cbc", "numeric"),
    "hemoglobin": (("g/dL",), "cbc", "numeric"),
    "homocysteine": (("umol/L",), "cardiovascular", "numeric"),
    "hs_crp": (("mg/L",), "inflammation", "numeric"),
    "immature_cells_pct": (("%",), "cbc_differential", "numeric"),
    "immature_granulocytes_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "insulin": (("uIU/mL",), "metabolic", "numeric"),
    "insulin_fasting": (("uIU/mL",), "metabolic", "numeric"),
    "insulin_intact_lcms": (("uIU/mL",), "metabolic", "numeric"),
    "insulin_resistance_score": (("score",), "metabolic", "numeric"),
    "iron_binding_capacity": (("mcg/dL",), "iron_metabolism", "numeric"),
    "iron_saturation": (("%",), "iron", "numeric"),
    "iron_saturation_pct": (("%",), "iron_metabolism", "numeric"),
    "iron_total": (("mcg/dL",), "iron", "numeric"),
    "ldl_c": (("mg/dL",), "lipids", "numeric"),
    "ldl_medium": (("nmol/L",), "lipids_advanced", "numeric"),
    "ldl_particle_number": (("nmol/L",), "lipids_advanced", "numeric"),
    "ldl_pattern": (("",), "lipids_advanced", "qualitative"),
    "ldl_peak_size": (("Angstrom",), "lipids_advanced", "numeric"),
    "ldl_small": (("nmol/L",), "lipids_advanced", "numeric"),
    "lead_venous": (("mcg/dL",), "toxicology", "numeric"),
    "leptin": (("ng/mL",), "metabolic", "numeric"),
    "lh": (("mIU/mL",), "hormones", "numeric"),
    "linoleic_acid": (("% by wt",), "omega_fatty_acids", "numeric"),
    "lipase": (("U/L",), "digestive", "numeric"),
    "lipoprotein_a": (("nmol/L",), "lipids", "numeric"),
    "lp_pla2_activity": (("nmol/min/mL",), "inflammation", "numeric"),
    "lpa": (("nmol/L",), "cardiovascular", "numeric"),
    "lpa_aspirin_genotype": (("",), "genetics", "qualitative"),
    "lymphocytes_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "lymphocytes_pct": (("%",), "cbc_differential", "numeric"),
    "magnesium_rbc": (("mg/dL",), "minerals", "numeric"),
    "mch": (("pg",), "cbc", "numeric"),
    "mchc": (("g/dL",), "cbc", "numeric"),
    "mcv": (("fL",), "cbc", "numeric"),
    "mercury_blood": (("mcg/L",), "toxicology", "numeric"),
    "methylmalonic_acid": (("nmol/L",), "metabolic", "numeric"),
    "monocytes_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "monocytes_pct": (("%",), "cbc_differential", "numeric"),
    "mpv": (("fL",), "cbc", "numeric"),
    "myeloperoxidase": (("pmol/L",), "inflammation", "numeric"),
    "neutrophils_abs": (("x10E3/uL",), "cbc_differential", "numeric"),
    "neutrophils_pct": (("%",), "cbc_differential", "numeric"),
    "nfl_neurofilament_light_chain": (("pg/mL",), "neurodegeneration", "numeric"),
    "non_hdl_c": (("mg/dL",), "lipids", "numeric"),
    "omega3_total": (("% by wt",), "omega_fatty_acids", "numeric"),
    "omega6_omega3_ratio": (("",), "omega_fatty_acids", "numeric"),
    "omega6_total": (("% by wt",), "omega_fatty_acids", "numeric"),
    "omega_3_index": (("% by wt",), "fatty_acids", "numeric"),
    "omega_3_total_pct": (("% by wt",), "fatty_acids", "numeric"),
    "omega_6_omega_3_ratio": (("ratio",), "fatty_acids", "numeric"),
    "omega_6_total_pct": (("% by wt",), "fatty_acids", "numeric"),
    "omegacheck": (("% by wt",), "omega_fatty_acids", "numeric"),
    "platelet_count": (("Thousand/uL",), "cbc", "numeric"),
    "platelets": (("x10E3/uL", "K/uL"), "cbc", "numeric"),
    "potassium": (("mmol/L",), "electrolytes", "numeric"),
    "prolactin": (("ng/mL",), "hormones", "numeric"),
    "protein_total": (("g/dL",), "metabolic", "numeric"),
    "psa_free": (("ng/mL",), "prostate", "numeric"),
    "psa_pct_free": (("%",), "prostate", "numeric"),
    "psa_total": (("ng/mL",), "prostate", "numeric"),
    "rbc": (("x10E6/uL", "M/uL", "Million/uL"), "cbc", "numeric"),
    "rdw": (("%",), "cbc", "numeric"),
    "rh_type": (("",), "blood_type", "qualitative"),
    "rheumatoid_factor": (("IU/mL",), "immune", "numeric"),
    "shbg": (("nmol/L",), "hormones", "numeric"),
    "sodium": (("mmol/L",), "electrolytes", "numeric"),
    "t3_free": (("pg/mL",), "thyroid", "numeric"),
    "t4_free": (("ng/dL",), "thyroid", "numeric"),
    "testosterone_free": (("pg/mL",), "hormones", "numeric"),
    "testosterone_total": (("ng/dL",), "hormones", "numeric"),
    "thyroglobulin_antibodies": (("IU/mL",), "thyroid", "numeric"),
    "thyroid_peroxidase_antibodies": (("IU/mL",), "thyroid", "numeric"),
    "tibc": (("mcg/dL",), "iron", "numeric"),
    "tmao": (("uM",), "metabolic", "numeric"),
    "triglycerides": (("mg/dL",), "lipids", "numeric"),
    "tsh": (("uIU/mL", "mIU/L"), "thyroid", "numeric"),
    "uric_acid": (("mg/dL",), "metabolic", "numeric"),
    "urine_appearance": (("",), "urinalysis", "qualitative"),
    "urine_blood": (("",), "urinalysis", "qualitative"),
    "urine_color": (("",), "urinalysis", "qualitative"),
    "urine_glucose": (("",), "urinalysis", "qualitative"),
    "urine_ketones": (("",), "urinalysis", "qualitative"),
    "urine_ph": (("",), "urinalysis", "numeric"),
    "urine_protein": (("",), "urinalysis", "qualitative"),
    "urine_specific_gravity": (("",), "urinalysis", "numeric"),
    "vitamin_d_25oh": (("ng/mL",), "vitamins", "numeric"),
    "vldl": (("mg/dL",), "lipids", "numeric"),
    "wbc": (("x10E3/uL", "K/uL", "Thousand/uL"), "cbc", "numeric"),
    "zinc": (("mcg/dL",), "minerals", "numeric"),
}

#: Every leaf path a live DEXA scan record holds, with the value kind it stores.
DEXA_FIELDS: Dict[str, str] = {
    "body_composition.ag_ratio": "number",
    "body_composition.android_fat_pct": "number",
    "body_composition.body_fat_pct": "number",
    "body_composition.bone_mineral_content_lb": "number",
    "body_composition.fat_mass_lb": "number",
    "body_composition.gynoid_fat_pct": "number",
    "body_composition.lean_mass_lb": "number",
    "body_composition.total_mass_lb": "number",
    "body_composition.visceral_fat_g": "number",
    "body_composition.visceral_fat_lb": "number",
    "body_score.grade": "str",
    "body_score.numeric": "number",
    "body_score.percentile": "number",
    "body_score.rating": "str",
    "body_score.suggested_next_visit_days": "number",
    "bone.bmc_lb": "number",
    "bone.bmd_by_region.arms.bmd": "number",
    "bone.bmd_by_region.arms.percentile": "number",
    "bone.bmd_by_region.head.bmd": "number",
    "bone.bmd_by_region.head.percentile": "number",
    "bone.bmd_by_region.legs.bmd": "number",
    "bone.bmd_by_region.legs.percentile": "number",
    "bone.bmd_by_region.pelvis.bmd": "number",
    "bone.bmd_by_region.pelvis.percentile": "number",
    "bone.bmd_by_region.ribs.bmd": "number",
    "bone.bmd_by_region.ribs.percentile": "number",
    "bone.bmd_by_region.spine.bmd": "number",
    "bone.bmd_by_region.spine.percentile": "number",
    "bone.bmd_by_region.total_body.bmd": "number",
    "bone.bmd_by_region.total_body.percentile": "number",
    "bone.bmd_by_region.trunk.bmd": "number",
    "bone.bmd_by_region.trunk.percentile": "number",
    "bone.t_score": "number",
    "bone.t_score_change": "number",
    "bone.z_score": "number",
    "changes_vs_baseline.almi_kg_m2": "number",
    "changes_vs_baseline.fat_mass_lb": "number",
    "changes_vs_baseline.ffmi_kg_m2": "number",
    "changes_vs_baseline.lean_mass_lb": "number",
    "changes_vs_baseline.t_score": "number",
    "changes_vs_baseline.total_mass_lb": "number",
    "changes_vs_baseline.visceral_fat_lb": "number",
    "indices.almi_kg_m2": "number",
    "indices.almi_percentile": "number",
    "indices.ffmi_kg_m2": "number",
    "indices.ffmi_rating": "str",
    "indices.fmi_kg_m2": "number",
    "indices.fmi_rating": "str",
    "interpretations.areas_for_focus": "number",
    "interpretations.goals_6mo.ag_ratio_target": "str",
    "interpretations.goals_6mo.body_fat_target_pct": "str",
    "interpretations.goals_6mo.fat_loss_target_lb": "str",
    "interpretations.goals_6mo.lean_mass": "str",
    "interpretations.strengths": "number",
    "limbs.arm_symmetry": "number",
    "limbs.left_arm.fat_lb": "number",
    "limbs.left_arm.fat_pct": "number",
    "limbs.left_arm.lean_lb": "number",
    "limbs.left_arm.lean_pct": "number",
    "limbs.left_arm.mbr": "number",
    "limbs.left_arm.total_lb": "number",
    "limbs.left_leg.fat_lb": "number",
    "limbs.left_leg.fat_pct": "number",
    "limbs.left_leg.lean_lb": "number",
    "limbs.left_leg.lean_pct": "number",
    "limbs.left_leg.mbr": "number",
    "limbs.left_leg.total_lb": "number",
    "limbs.leg_symmetry": "number",
    "limbs.right_arm.fat_lb": "number",
    "limbs.right_arm.fat_pct": "number",
    "limbs.right_arm.lean_lb": "number",
    "limbs.right_arm.lean_pct": "number",
    "limbs.right_arm.mbr": "number",
    "limbs.right_arm.total_lb": "number",
    "limbs.right_leg.fat_lb": "number",
    "limbs.right_leg.fat_pct": "number",
    "limbs.right_leg.lean_lb": "number",
    "limbs.right_leg.lean_pct": "number",
    "limbs.right_leg.mbr": "number",
    "limbs.right_leg.total_lb": "number",
    "posture.method": "str",
    "posture.notes": "str",
    "score_360.bio_age_rating": "str",
    "score_360.bio_age_vs_peer": "str",
    "score_360.biological_age": "number",
    "score_360.biological_age_delta": "number",
    "score_360.change": "number",
    "score_360.chronological_age": "number",
    "score_360.rating": "str",
    "score_360.score": "number",
    "segmental_fat.arms_lb": "number",
    "segmental_fat.arms_left_lb": "number",
    "segmental_fat.arms_pct": "number",
    "segmental_fat.arms_right_lb": "number",
    "segmental_fat.legs_lb": "number",
    "segmental_fat.legs_left_lb": "number",
    "segmental_fat.legs_pct": "number",
    "segmental_fat.legs_right_lb": "number",
    "segmental_fat.total_lb": "number",
    "segmental_fat.total_pct": "number",
    "segmental_fat.trunk_lb": "number",
    "segmental_fat.trunk_left_lb": "number",
    "segmental_fat.trunk_pct": "number",
    "segmental_fat.trunk_right_lb": "number",
    "segmental_lean.arms_lb": "number",
    "segmental_lean.arms_left_lb": "number",
    "segmental_lean.arms_pct": "number",
    "segmental_lean.arms_right_lb": "number",
    "segmental_lean.legs_lb": "number",
    "segmental_lean.legs_left_lb": "number",
    "segmental_lean.legs_pct": "number",
    "segmental_lean.legs_right_lb": "number",
    "segmental_lean.total_lb": "number",
    "segmental_lean.trunk_lb": "number",
    "segmental_lean.trunk_left_lb": "number",
    "segmental_lean.trunk_pct": "number",
    "segmental_lean.trunk_right_lb": "number",
    "targets.almi_kg_m2": "number",
    "targets.body_fat_pct": "number",
    "targets.ffmi_kg_m2": "number",
    "targets.lean_mass_lb": "number",
    "targets.t_score": "number",
    "targets.total_mass_lb": "number",
    "targets.visceral_fat_lb": "number",
}

#: The four DEXA leaves every reader depends on (`ai/ai_context.py` `_build_physical_data`,
#: `content/output_writers.py` physical surface, the #4166 training derivation): a scan
#: without them is not a scan the platform can use.
DEXA_REQUIRED: Tuple[str, ...] = (
    "body_composition.body_fat_pct",
    "body_composition.lean_mass_lb",
    "body_composition.fat_mass_lb",
    "body_composition.total_mass_lb",
)

#: The unit a DEXA leaf carries, read off its own suffix. Order matters: longer suffixes first.
_DEXA_SUFFIX_UNITS: Tuple[Tuple[str, str], ...] = (
    ("_kg_m2", "kg/m2"),
    ("_percentile", "percentile"),
    ("percentile", "percentile"),
    ("_pct", "%"),
    ("_lb", "lb"),
    ("_g", "g"),
    ("t_score", "SD"),
    ("z_score", "SD"),
    ("t_score_change", "SD"),
    ("biological_age", "years"),
    ("suggested_next_visit_days", "days"),
)

#: The flags a marker object may carry (SCHEMA.md `flag`), plus "" for "not flagged".
LAB_FLAGS: Tuple[str, ...] = ("normal", "high", "low", "carrier", "noncarrier", "")

_NON_KEY = re.compile(r"[^a-z0-9]+")


def marker_key(name: str) -> str:
    """A report's marker label -> the snake_case key the schema uses ("LDL-C" -> "ldl_c")."""
    return _NON_KEY.sub("_", str(name or "").strip().lower()).strip("_")


def _unit_norm(unit: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(unit or "")).lower()


def unit_accepted(marker: str, unit: Optional[str]) -> bool:
    """True when `unit` is one of the spellings the schema has stored for `marker`.

    Whitespace- and case-insensitive ("mg/dL" == "mg/dl"), because a report's typography
    is not a different unit; "mg/dL" vs "mmol/L" IS, and is refused.
    """
    row = LAB_UNITS.get(marker)
    if row is None:
        return False
    return _unit_norm(unit) in {_unit_norm(u) for u in row[0]}


def canonical_unit(marker: str, unit: Optional[str]) -> str:
    """The stored spelling that `unit` matches, so a draw never introduces a new one."""
    for stored in LAB_UNITS[marker][0]:
        if _unit_norm(stored) == _unit_norm(unit):
            return stored
    raise KeyError(f"{marker}: unit {unit!r} not accepted")


def dexa_unit_for(path: str) -> Optional[str]:
    """The unit a DEXA leaf carries, by its suffix; None for a string leaf or a bare ratio/score."""
    if DEXA_FIELDS.get(path) != "number":
        return None
    leaf = path.rsplit(".", 1)[-1]
    for suffix, unit in _DEXA_SUFFIX_UNITS:
        if leaf.endswith(suffix):
            return unit
    return None
