"""tests/test_age_inversion.py — no public output is a function of the owner's age (owner ruling 2026-11-14).

THE DEFECT. /api/phenoage served the rounded Levine phenotypic age beside its nine markers ("Option A": the
chronological age and the gap withheld). The formula is public and LINEAR in age, the markers are public, so the
rounded figure was the age to a window of about 1.1 years. The first tests below reproduce that on synthetic data —
they are the proof this file's instrument (tests/age_inversion_lib.py) can see the mechanism — and show why a
five-year band or a younger/older flag was not adopted: each is still a function of his age, and windows from
successive draws intersect.

THE GUARD. The public handler reads no profile, no birth date and no clock: its response is the same bytes whatever
the age and whatever the day (invariance — the strongest form of "cannot be inverted"), it serves no statistic of
his age at all, and the publication snapshot refuses one. Synthetic ages only: nothing here knows the real one.
"""

# premerge-gate: the privacy ratchet on who may read the birth date, and on the public PhenoAge shape (owner ruling 2026-11-14)
import ast
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("lambdas", "tests", "scripts"):
    sys.path.insert(0, os.path.join(_REPO, p))

import age_inversion_lib as INV  # noqa: E402
from web import site_api_biomarkers as B  # noqa: E402

# A synthetic panel (formula units) and synthetic people. No real value is in this file.
_VALS = {
    "albumin_gL": 44.0,
    "creatinine_umolL": 88.4,
    "glucose_mmolL": 5.3,
    "crp_mgdL": 0.12,
    "lymphocyte_pct": 31.0,
    "mcv_fL": 90.0,
    "rdw_pct": 13.1,
    "alp_UL": 68.0,
    "wbc_1000": 5.9,
}
_VALS_SECOND_DRAW = {**_VALS, "glucose_mmolL": 5.9, "crp_mgdL": 0.31, "rdw_pct": 13.6}
_SYNTHETIC_AGES = (23.4, 41.75, 47.3, 66.1)


def _pheno(vals, age):
    return B._compute_phenoage(vals, age)


# ── the mechanism, reproduced (the controls: this file can see the leak) ─────────────────────────


@pytest.mark.parametrize("age", _SYNTHETIC_AGES)
def test_a_rounded_phenotypic_age_is_the_age_to_about_a_year(age):
    served = round(_pheno(_VALS, age))
    lo, hi, width = INV.feasible_window(lambda a: round(_pheno(_VALS, a)) == served)
    assert lo <= age <= hi
    assert width < 1.3, f"the old shape pinned a synthetic {age} to {width:.2f} y"
    assert abs(width - 1 / B.PHENOAGE_YEARS_PER_YEAR_OF_AGE) < 0.05, "the window is one rounding step over the formula's slope"


def test_the_formula_is_linear_in_age_which_is_the_whole_problem():
    slopes = {round(_pheno(_VALS, a + 1) - _pheno(_VALS, a), 6) for a in (25, 40, 55, 70)}
    assert slopes == {round(B.PHENOAGE_YEARS_PER_YEAR_OF_AGE, 6)}


def test_a_five_year_band_only_widens_the_window_and_a_second_draw_narrows_it_again():
    age = 47.3
    band = lambda v: int(v // 5)  # noqa: E731 — a fixed five-year grid
    one = INV.feasible_window(lambda a: band(_pheno(_VALS, a)) == band(_pheno(_VALS, age)))
    assert 5.0 < one[2] < 6.0, "one draw: five years over the slope"
    # the same person, a later draw (18 months on, different markers): the reader intersects the two windows
    later = 1.5
    both = INV.feasible_window(
        lambda a: band(_pheno(_VALS, a)) == band(_pheno(_VALS, age))
        and band(_pheno(_VALS_SECOND_DRAW, a + later)) == band(_pheno(_VALS_SECOND_DRAW, age + later))
    )
    assert both[2] < one[2], "every further draw can only shrink what the band hides"
    assert both[2] < INV.MIN_WINDOW_YEARS and one[2] < INV.MIN_WINDOW_YEARS, "a band never reaches the floor"


def test_a_younger_or_older_flag_is_a_bound_on_the_age():
    """ "Phenotypic age is below his age" holds exactly when his age is above a threshold a reader can compute from
    the markers alone — a one-sided bound on the age, and a second draw's flag can close the other side."""
    vals = _VALS_SECOND_DRAW
    threshold = _pheno(vals, 0.0) / (1 - B.PHENOAGE_YEARS_PER_YEAR_OF_AGE)
    assert INV.AGE_LO < threshold < INV.AGE_HI, "the synthetic panel puts the threshold inside the plausible range"
    age = 47.3
    flag = lambda a: _pheno(vals, a) < a  # noqa: E731
    lo, hi, width = INV.feasible_window(lambda a: flag(a) == flag(age))
    assert abs(lo - threshold) < 0.02 and width < (INV.AGE_HI - INV.AGE_LO) - 10


def test_the_instrument_flags_the_old_payload_and_passes_the_new_one():
    drivers = [
        {"name": "Albumin", "value": 4.4},
        {"name": "Creatinine", "value": 1.0},
        {"name": "Glucose", "value": 95.5},
        {"name": "hs-CRP", "value": 1.2},
        {"name": "Lymphocyte %", "value": 31.0},
        {"name": "MCV", "value": 90.0},
        {"name": "RDW", "value": 13.1},
        {"name": "Alkaline phosphatase", "value": 68.0},
        {"name": "WBC", "value": 5.9},
    ]
    vals = INV.formula_inputs(drivers)
    old = {"phenoage": round(_pheno(vals, 47.3)), "drivers": drivers}
    r = INV.invert_phenoage(old)
    assert r["verdict"] == "INVERTIBLE" and r["window_years"] < 1.3
    new = {"phenoage": None, "withheld": B.PHENOAGE_WITHHELD, "reference": B.phenoage_reference(vals), "drivers": drivers}
    assert INV.invert_phenoage(new)["statistics"] == []
    for leak in ({"band": "45-49"}, {"gap_direction": "younger"}, {"years": 46}):
        assert INV.invert_phenoage({**new, **leak})["window_years"] < INV.MIN_WINDOW_YEARS, f"{leak} must score as a leak"


# ── the guard: the public handler ────────────────────────────────────────────────────────────────


def _clinical(markers):
    return {"labs": {"latest_draw_date": "2026-04-03", "biomarkers": [{"name": k, "value": v} for k, v in markers.items()]}}


_MARKERS = {
    "Albumin": 4.4,
    "Creatinine": 1.0,
    "Glucose": 95.5,
    "CRP HS": 1.2,
    "MCV": 90.0,
    "RDW": 13.1,
    "Alkaline Phosphatase": 68.0,
    "WBC": 5.9,
    "Absolute Lymphocytes": 1829,
}


class _Boom(dict):
    """The handler's injected globals: touching ANY of them (the profile reader, the clock) fails the test."""

    def __getitem__(self, k):
        raise AssertionError(f"the public PhenoAge path reached for {k!r} — it must not read the profile or the clock")

    def get(self, k, default=None):
        raise AssertionError(f"the public PhenoAge path reached for {k!r}")


def _serve(monkeypatch, markers=None):
    body = json.dumps(_clinical(markers or _MARKERS)).encode()

    class _S3:
        def get_object(self, **kw):
            assert kw["Key"].endswith("/clinical.json")
            return {"Body": type("B", (), {"read": lambda self: body})()}

    monkeypatch.setattr(B.boto3, "client", lambda *a, **k: _S3())
    res = B.phenoage(_g=_Boom())
    assert res["statusCode"] == 200, res
    out = json.loads(res["body"])
    out.pop("_meta", None)
    return out


def test_the_public_handler_reads_no_profile_and_no_clock(monkeypatch):
    out = _serve(monkeypatch)  # _Boom raises on any injected-global access
    assert out["phenoage"] is None and out["withheld"] == B.PHENOAGE_WITHHELD
    assert INV.phenoage_statistics(out) == []
    src = open(B.__file__, encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "phenoage")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert not names & {"_get_profile", "date_of_birth", "age_years", "datetime", "now", "today", "utcnow"}, names


def test_the_response_is_the_same_bytes_whatever_the_birth_date(monkeypatch):
    """Invariance: the handler has no age input left, so there is nothing to invert. Measured, not assumed — the
    package's profile reader is replaced with ones that would move any age-derived output (the clock is covered by
    the test above: the handler's code names no clock and its injected globals raise on any access)."""
    seen = set()
    for dob in ("1950-01-01", "1995-06-15", "1979-02-28", None):
        monkeypatch.setattr("web.site_api_common._get_profile", lambda dob=dob: {"date_of_birth": dob} if dob else {})
        seen.add(json.dumps(_serve(monkeypatch), sort_keys=True))
    assert len(seen) == 1, "the public PhenoAge response moved with the birth date"


def test_the_reference_is_a_pure_function_of_the_public_markers(monkeypatch):
    out = _serve(monkeypatch)
    vals = INV.formula_inputs(out["drivers"])
    assert vals is not None, "the served drivers are enough to rebuild the formula inputs"
    assert out["reference"] == B.phenoage_reference(vals), "a reader can recompute every published number from the published markers"
    ref = out["reference"]
    assert ref["basis"] == "markers_only" and [pt["at_years"] for pt in ref["points"]] == list(B.PHENOAGE_REFERENCE_AGES)
    for pt in ref["points"]:
        assert abs(pt["reads_years"] - B._compute_phenoage(vals, pt["at_years"])) <= 0.05
        assert abs(pt["offset_years"] - (pt["reads_years"] - pt["at_years"])) <= 0.11
    assert ref["offset_low"] == min(pt["offset_years"] for pt in ref["points"]) and ref["offset_high"] == max(
        pt["offset_years"] for pt in ref["points"]
    )
    assert set(out) == {"phenoage", "withheld", "note", "reference", "as_of", "drivers", "lymphocyte_derived", "missing"}


def test_a_missing_marker_is_reported_and_nothing_is_approximated(monkeypatch):
    out = _serve(monkeypatch, {k: v for k, v in _MARKERS.items() if k != "RDW"})
    assert out["phenoage"] is None and out["missing"] == ["RDW"] and "reference" not in out


# ── the guard: the publication snapshot ──────────────────────────────────────────────────────────


def test_the_snapshot_carries_the_reference_and_refuses_a_figure_of_his_own(monkeypatch):
    import publish_snapshot_contract as C
    import publish_snapshot_journey as PJ

    served = _serve(monkeypatch)
    pa = PJ.phenoage(served)
    assert set(pa) == C.PHENOAGE_KEYS and "years" not in pa
    assert pa["reference"]["points"] == served["reference"]["points"] and set(pa["reference"]) == C.PHENOAGE_REFERENCE_KEYS
    # an old-shape response (a numeric figure of his own) is never carried into the build
    assert PJ.phenoage({**served, "phenoage": 46}) is None
    for leak in ({"years": 46}, {"band": "45-49"}, {"gap_direction": "younger"}, {"phenoage": 46}):
        with pytest.raises(C.SchemaError):
            C.validate_journey_body({"composition": None, "phenoage": {**pa, **leak}, "bp": None, "tape_date": None})


# ── the guard: the SET — who may read the birth date ─────────────────────────────────────────────

#: Modules on a PUBLIC path (the site API, and the coach facts that feed published prose) that read the birth date.
#: The list only shrinks. Each entry is dated and named for the PR that removes it.
_BIRTH_DATE_READERS_ALLOWED = {
    "lambdas/web/site_api_nutrition.py": "2026-11-14: the Mifflin TDEE estimate is computed with his age — the next PR moves it to a stated reference age",
    "lambdas/coach/coach_domain_facts.py": "2026-11-14: same estimate, fed to coach prose — moves with the PR above",
}


def test_no_other_public_path_reads_the_birth_date():
    readers = set()
    for root in ("lambdas/web", "lambdas/coach", "lambdas/content", "lambdas/emails"):
        for dirpath, _dirs, files in os.walk(os.path.join(_REPO, root)):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dirpath, f)
                tree = ast.parse(open(path, encoding="utf-8").read())
                # a string constant "date_of_birth" used as code (a key read), not a mention inside a docstring
                doc_ids = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
                if any(isinstance(n, ast.Constant) and n.value == "date_of_birth" and id(n) not in doc_ids for n in ast.walk(tree)):
                    readers.add(os.path.relpath(path, _REPO))
    new = readers - set(_BIRTH_DATE_READERS_ALLOWED)
    assert (
        not new
    ), f"a public path reads date_of_birth: {sorted(new)} — an output computed from it is a published age (tests/age_inversion_lib.py)"
    gone = set(_BIRTH_DATE_READERS_ALLOWED) - readers
    assert not gone, f"no longer reads the birth date — remove from the allow-list (it only shrinks): {sorted(gone)}"
