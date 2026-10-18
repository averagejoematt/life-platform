"""dexa_fields.py — the clinical.json `body_comp` block read off a DEXA scan row (epic #4625).

Split out of output_writers.py (module-size ceiling, #1665). Pure; no I/O.
"""

from common.digest_utils import d2f as _d2f


def dexa_body_comp(dexa):
    """The clinical.json `body_comp` block off a DEXA scan row, read from the LIVE field names.

    The live rows (`SOURCE#dexa`, SCHEMA.md) hold `body_composition.{lean_mass_lb, fat_mass_lb,
    visceral_fat_g}`, `bone.t_score` and — on the newer scan only — `indices.ffmi_kg_m2`. This reader
    once looked for `bone_density`, `interpretations.ffmi` and `*_lbs`, none of which any row holds
    (epic #4625), so every figure but body fat read null. A field the scan does not hold is None —
    never a fabricated 0 and never a neighbour's value (the 2025 scan has no FFMI).
    """
    bc = dexa.get("body_composition") or {}
    return {
        "scan_date": dexa.get("scan_date"),
        "body_fat_pct": _d2f(bc.get("body_fat_pct")),
        "ffmi": _d2f((dexa.get("indices") or {}).get("ffmi_kg_m2")),
        "lean_mass_lbs": _d2f(bc.get("lean_mass_lb")),
        "fat_mass_lbs": _d2f(bc.get("fat_mass_lb")),
        "visceral_fat_g": _d2f(bc.get("visceral_fat_g")),
        "bmd_t_score": _d2f((dexa.get("bone") or {}).get("t_score")),
    }
