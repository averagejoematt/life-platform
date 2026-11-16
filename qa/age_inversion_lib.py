"""qa/age_inversion_lib.py — the age-inversion attack, as a reusable instrument (owner ruling 2026-11-14).

A public output that is a function of the owner's chronological age is a published age, at whatever precision the
function and its other inputs allow. This module is the attacker: given what a reader can see, it returns the set of
ages consistent with it. ``tests/test_age_inversion.py`` runs it offline against the handlers; run this file to aim
it at the live public surface (anonymous GETs only, no credentials, no private input):

    python3 qa/age_inversion_lib.py --live

Nothing here knows, reads or prints the owner's age: the offline tests use synthetic ages, and the live mode reports
only the WIDTH of the window a reader could reach.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

#: The floor the owner set: no public output may let a reader reconstruct the age "at approximately one-year
#: precision". Held with a wide margin — a window under this many years fails.
MIN_WINDOW_YEARS = 10.0
AGE_LO, AGE_HI, AGE_STEP = 18.0, 90.0, 0.01
ORIGIN = "https://averagejoematt.com"

#: Driver label (as served) -> the formula's input key and the unit conversion the handler applies.
_DRIVER_TO_FORMULA = {
    "Albumin": ("albumin_gL", lambda v: v * 10.0),
    "Creatinine": ("creatinine_umolL", lambda v: v * 88.42),
    "Glucose": ("glucose_mmolL", lambda v: v / 18.0182),
    "hs-CRP": ("crp_mgdL", lambda v: v / 10.0),
    "Lymphocyte %": ("lymphocyte_pct", lambda v: v),
    "MCV": ("mcv_fL", lambda v: v),
    "RDW": ("rdw_pct", lambda v: v),
    "Alkaline phosphatase": ("alp_UL", lambda v: v),
    "WBC": ("wbc_1000", lambda v: v),
}


def formula_inputs(drivers: list) -> dict | None:
    """The Levine inputs a reader can rebuild from the served drivers (None when a marker is missing)."""
    vals = {}
    for d in drivers or []:
        hit = _DRIVER_TO_FORMULA.get(str(d.get("name")))
        if hit and isinstance(d.get("value"), (int, float)):
            vals[hit[0]] = hit[1](float(d["value"]))
    return vals if len(vals) == len(_DRIVER_TO_FORMULA) else None


def feasible_window(consistent, lo: float = AGE_LO, hi: float = AGE_HI, step: float = AGE_STEP) -> tuple[float, float, float] | None:
    """``(low, high, width)`` of the ages ``a`` in [lo, hi] for which ``consistent(a)`` holds; None when no age fits.

    ``consistent`` is the reader's test: "would the public output look exactly like this if he were ``a`` years old?"
    A width near ``hi - lo`` means the output says nothing about the age; a narrow one is a published age."""
    n = int(round((hi - lo) / step))
    ages = [lo + i * step for i in range(n + 1)]
    ok = [a for a in ages if consistent(a)]
    if not ok:
        return None
    return ok[0], ok[-1], ok[-1] - ok[0] + step


def phenoage_statistics(payload: dict) -> list[tuple[str, object]]:
    """Every field of an /api/phenoage (or journey.json ``phenoage``) payload that states HIS phenotypic age in any
    form — a number, a band, a direction. Each is a function of his age and so an inversion handle."""
    out = []
    for key in ("phenoage", "years", "phenoage_band", "band", "band_low", "band_high", "gap", "gap_direction", "vs_chronological"):
        v = payload.get(key)
        if v is not None:
            out.append((key, v))
    return out


def invert_phenoage(payload: dict) -> dict:
    """What a reader learns about the age from one phenoage payload: ``{"statistics", "window_years", "verdict"}``."""
    from web.site_api_biomarkers import _compute_phenoage

    stats = phenoage_statistics(payload)
    if not stats:
        return {"statistics": [], "window_years": AGE_HI - AGE_LO, "verdict": "no statistic of his age is served"}
    vals = formula_inputs(payload.get("drivers") or [])
    if vals is None:
        return {
            "statistics": stats,
            "window_years": None,
            "verdict": "a statistic is served but the markers are not: cannot be scored here — treat as a leak",
        }
    width = AGE_HI - AGE_LO
    for key, v in stats:
        if key in ("phenoage", "years") and isinstance(v, (int, float)):
            w = feasible_window(lambda a: round(_compute_phenoage(vals, a) or -1) == round(v))
            width = min(width, w[2] if w else 0.0)
        else:
            width = min(width, 0.0)  # an unrecognised statistic of his age: fail closed
    return {"statistics": stats, "window_years": width, "verdict": "INVERTIBLE" if width < MIN_WINDOW_YEARS else "wide"}


def _get(path: str) -> dict:
    req = urllib.request.Request(ORIGIN + path, headers={"accept": "application/json", "user-agent": "age-inversion-audit"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


def audit(get) -> list[tuple[str, bool]]:
    """Aim the attack at one copy of the public surface. ``get(path)`` returns the JSON body a reader receives at that
    path (``{}`` when the copy does not carry it): the live origin, or a downloaded archive's ``api/`` members
    (scripts/check_public_copies.py, #6083). Returns ``(line, bad)`` per output read; ``bad`` = it narrows the age."""
    rows: list[tuple[str, bool]] = []
    r = invert_phenoage(get("/api/phenoage"))
    served = [k for k, _ in r["statistics"]]
    rows.append(
        (
            f"/api/phenoage: {r['verdict']} — window {r['window_years']} y (floor {MIN_WINDOW_YEARS} y); statistics served: {served}",
            r["verdict"] != "no statistic of his age is served" and (r["window_years"] is None or r["window_years"] < MIN_WINDOW_YEARS),
        )
    )
    j = (get("/api/journey").get("journey") or {}).get("phenoage") or {}
    if j:
        r = invert_phenoage(j)
        rows.append(
            (
                f"/api/journey phenoage: {r['verdict']} — window {r['window_years']} y",
                r["window_years"] is None or r["window_years"] < MIN_WINDOW_YEARS,
            )
        )

    # The Mifflin-St Jeor estimate carries -5 kcal per year of age. With the weight, the height and the exercise log
    # public, a TDEE served to the kcal is the age to about (1 + 2U) / 5 years, U = the reader's error on the
    # exercise term in kcal/day — and exactly 0.2 y on a week with no exercise logged.
    for path, pick in (
        ("/api/deficit_sustainability", lambda d: (d.get("deficit_sustainability") or {}).get("deficit") or {}),
        ("/api/nutrition_overview", lambda d: d.get("nutrition") or {}),
    ):
        blk = pick(get(path))
        src, method = blk.get("tdee_source"), blk.get("tdee_method")
        if src == "estimate_mifflin" and "reference_age" not in str(method):
            rows.append((f"{path}: INVERTIBLE — a Mifflin estimate computed with his age is served to the kcal (method {method})", True))
        else:
            rows.append((f"{path}: no age-derived estimate served (tdee_source {src}, method {method})", False))
    return rows


def live() -> int:
    """Aim the attack at the live public surface. Exit 1 when any output narrows the age below the floor."""
    rows = audit(_get)
    for line, _bad in rows:
        print(line)
    return 1 if any(bad for _line, bad in rows) else 0


def main() -> int:
    if "--live" in sys.argv:
        return live()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
