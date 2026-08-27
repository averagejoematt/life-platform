"""lambdas/web/site_api_biomarkers.py — labs, glucose, PhenoAge, genome aggregates.

Split out of ``site_api_vitals.py`` (#1654 — god-module breakup). One seam: **the
measured chemistry**, and it is the module carrying the platform's hardest privacy
absolutes:

  * `/api/genome_risks` publishes AGGREGATES ONLY (counts + risk levels + the
    disclosure saying why detail is absent). Named genes, rsids, per-variant
    summaries and implications must NEVER reach the response — a Tier-2 owner-only
    boundary, and any per-variant publication is a PRE-13 decision.
  * `/api/labs` runs every panel through ``_strip_genetic_biomarkers``
    (``_GENETIC_CATEGORY_RE`` / ``_GENETIC_TEXT_RE``) so a pharmacogenomic marker
    filed as an ordinary lab cannot leak through the labs door instead.
  * `/api/phenoage` follows Option A: chronological age is NEVER returned.

``tests/test_public_genetic_privacy_absolute.py`` guards all three by reading this
module's source; it scans the whole site_api_vitals family, so the guard follows
the code rather than a filename.

The routed handler entrypoints stay in the ``site_api_vitals`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the injectable state (``table``, ``_query_source``,
``_experiment_date``, ``EXPERIMENT_START``, ``datetime``) via ``_g["<name>"]``.

This module does NOT import the facade; no import cycle. Every other shared helper
comes straight from ``site_api_common`` (identical binding semantics to the
pre-split module).
"""

import json
import os
import re as _re  # genetic-biomarker strip regexes (labs)
from datetime import timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from health.sensor_absence import absence_verdict, is_stale

from web.site_api_common import (
    PT,
    S3_REGION,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _get_profile,
    _ok,
    _window_span,
    logger,
)

# ════════════════════════════════════════════════════════════════════════
# #1240: vitals-adjacent domain handlers — moved verbatim from site_api_data.py
# (glucose / sleep / circadian / phenoage / labs / genome). Behavior-identical;
# the router (site_api_lambda.py) now imports these from here.
# ════════════════════════════════════════════════════════════════════════


def genome_risks(*, _g) -> dict:
    """
    GET /api/genome_risks
    Returns genome risk AGGREGATES grouped by category. Cache: 86400s (24h).

    PRIVACY ABSOLUTE — no genetic IDENTIFIER may reach this public payload.
    The docstring here used to say "no raw genotypes exposed", which was true
    and beside the point: this endpoint served 111 dbSNP `rsid` values and 93
    `gene` names, each paired with the owner's personal risk classification, to
    any unauthenticated caller. An rsID IS the identifier — it is what
    `_GENETIC_TEXT_RE` (line ~2450 of this same file) exists to keep out of the
    public labs payload, what `docs/DATA_GOVERNANCE.md` classes Tier 2
    owner-only, and what #920/#945 purged from three other surfaces. This
    handler was simply never brought under the rule (guard-the-instance, not
    the set), and PRE-13 — the review that would decide whether ANY of this may
    be published — is still deferred. Until that decision is Matthew's to make
    explicitly, the public shape is aggregate-only:

      per category: how many variants, and the risk-level distribution.

    That keeps the honest reader-facing fact ("the genome has been analysed and
    here is the shape of it") without publishing which variants he carries.
    Restoring per-variant detail is a PRE-13 decision, not a code change.
    """
    table = _g["table"]

    pk = f"{USER_PREFIX}genome"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk))
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        # No genome uploaded yet — shaped-empty 200 so the page shows "not yet published".
        return _ok(
            {"genome": {"total_snps": 0, "risk_summary": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}, "categories": {}}},
            cache_seconds=3600,
        )

    categories: dict[str, dict[str, Any]] = {}
    risk_summary = {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}

    for snp in items:
        cat = snp.get("category", "other")
        risk = snp.get("risk_level", "neutral")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1
        # Aggregate ONLY — never the rsid, the gene, or the per-variant free
        # text (summary/implications carried genotype calls). Counting a
        # category is a fact about the analysis; naming a variant is a fact
        # about the person.
        bucket = categories.setdefault(cat, {"n": 0, "risk_levels": {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}})
        bucket["n"] += 1
        bucket["risk_levels"][risk] = bucket["risk_levels"].get(risk, 0) + 1

    return _ok(
        {
            "genome": {
                "total_snps": len(items),
                "risk_summary": risk_summary,
                "categories": dict(sorted(categories.items())),
                "disclosure": (
                    "Per-variant detail (identifiers, genes, and their individual readouts) is deliberately "
                    "not published: genome variants are owner-only under this platform's data-governance tiers. "
                    "These are counts of what was analysed, not which variants he carries."
                ),
            }
        },
        cache_seconds=86400,
    )


def glucose(*, _g) -> dict:
    """
    GET /api/glucose
    Returns: 30-day CGM stats — time-in-range, variability, daily trend.
    Source: apple_health DynamoDB records.
    Cache: 3600s (1h).
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _experiment_date = _g["_experiment_date"]
    _query_source = _g["_query_source"]
    datetime = _g["datetime"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    _w30 = _window_span(d30, today, 30)  # #1917: is "30d" a true name today?

    records = _query_source("apple_health", d30, today)
    cgm_days = [r for r in records if r.get("blood_glucose_avg") is not None and r.get("sk", "").replace("DATE#", "") >= EXPERIMENT_START]
    cgm_days.sort(key=lambda x: x.get("sk", ""))

    if not cgm_days:
        return _ok({"glucose": None, "glucose_trend": []}, cache_seconds=3600)

    latest = cgm_days[-1]

    # 30-day averages
    avg_vals = [float(r["blood_glucose_avg"]) for r in cgm_days if r.get("blood_glucose_avg")]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_range_pct")]
    opt_vals = [float(r["blood_glucose_time_in_optimal_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_optimal_pct")]
    std_vals = [float(r["blood_glucose_std_dev"]) for r in cgm_days if r.get("blood_glucose_std_dev")]

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend array for chart
    trend = [
        {
            "date": r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(r["blood_glucose_avg"]), 1) if r.get("blood_glucose_avg") else None,
            "tir": round(float(r["blood_glucose_time_in_range_pct"]), 1) if r.get("blood_glucose_time_in_range_pct") else None,
            "std": round(float(r["blood_glucose_std_dev"]), 1) if r.get("blood_glucose_std_dev") else None,
        }
        for r in cgm_days
    ]

    tir_today = float(latest.get("blood_glucose_time_in_range_pct", 0))
    tir_status = "excellent" if tir_today >= 90 else ("good" if tir_today >= 70 else "needs_attention")
    std_today = float(latest.get("blood_glucose_std_dev", 99))
    variability_status = "low" if std_today < 15 else ("moderate" if std_today < 25 else "high")

    # Best/worst day by TIR (or avg glucose if all 100% TIR)
    best_day = None
    worst_day = None
    if len(cgm_days) >= 2:
        sorted_by_tir = sorted(
            cgm_days, key=lambda r: (float(r.get("blood_glucose_time_in_range_pct", 0)), -float(r.get("blood_glucose_std_dev", 99)))
        )
        worst_r = sorted_by_tir[0]
        best_r = sorted_by_tir[-1]
        worst_day = {
            "date": worst_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(worst_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(worst_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }
        best_day = {
            "date": best_r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(best_r.get("blood_glucose_avg", 0)), 1),
            "tir": round(float(best_r.get("blood_glucose_time_in_range_pct", 0)), 1),
        }

    # #3204 — ADR-104: is `latest` still TODAY's reading, or did the sensor session end?
    # `apple_health` stays fresh on steps/water when the CGM stops, so partition
    # freshness proves nothing here. The bar is the registry's `reader_surface` facet
    # (source_registry: cgm -> max_days_behind 1), not a number invented at this call
    # site, so the label a reader sees and the operator-side liveness view agree.
    as_of = latest.get("sk", "").replace("DATE#", "")
    sensor = absence_verdict("cgm", as_of or None, today)
    dark = is_stale(sensor)

    # When the sensor is dark, the day-scalar fields are the ones that lie: they are
    # named as the current reading and there is no current reading. They go null and
    # the numbers move, DATED, to `last_reading` — so a consumer binding `avg_mg_dl`
    # gets absence rather than a stale figure, and no future key rename can restore
    # the lie. `as_of_date` goes null with them: it stamps the currency of THIS
    # object's values, and with those values absent there is nothing to stamp (the
    # dark window is fully described by `sensor`). The window aggregates below are
    # untouched — they are honestly window-named and a 30-day mean is still a 30-day
    # mean once the sensor stops. `glucose_trend` is likewise per-point dated.
    last_reading = {
        "date": as_of or None,
        "avg_mg_dl": round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None,
        "std_dev": round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None,
        "time_in_range_pct": round(tir_today, 1),
    }

    def _cur(value):
        """A day-scalar: the value while the sensor is live, absence once it is dark."""
        return None if dark else value

    return _ok(
        {
            "glucose": {
                "avg_mg_dl": _cur(round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None),
                "std_dev": _cur(round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None),
                "time_in_range_pct": _cur(round(tir_today, 1)),
                "time_in_optimal_pct": _cur(
                    round(float(latest.get("blood_glucose_time_in_optimal_pct", 0)), 1)
                    if latest.get("blood_glucose_time_in_optimal_pct")
                    else None
                ),
                "time_above_140_pct": _cur(
                    round(float(latest.get("blood_glucose_time_above_140_pct", 0)), 1)
                    if latest.get("blood_glucose_time_above_140_pct")
                    else None
                ),
                "cgm_source": latest.get("cgm_source", "unknown"),
                # A *_status verdict is a judgement ON a current reading ("excellent"
                # time-in-range). With no current reading there is no verdict to render
                # — absence, not a grade earned days ago (ADR-104).
                "tir_status": _cur(tir_status),
                "variability_status": _cur(variability_status),
                # #1917: truthful-or-absent — these are MEANS, so a genesis-clamped
                # window makes "30d" a false name, not merely an understatement.
                # The real values ship under window-generic names beside their span.
                "avg_mg_dl_window": avg(avg_vals),
                "avg_tir_window": avg(tir_vals),
                "avg_optimal_window": avg(opt_vals),
                "avg_std_window": avg(std_vals),
                "avg_window_days": _w30["actual_days"],
                "30d_avg_mg_dl": avg(avg_vals) if _w30["full"] else None,
                "30d_avg_tir": avg(tir_vals) if _w30["full"] else None,
                "30d_avg_optimal": avg(opt_vals) if _w30["full"] else None,
                "30d_avg_std": avg(std_vals) if _w30["full"] else None,
                "days_tracked": len(cgm_days),
                "as_of_date": None if dark else (as_of or None),
                "sensor": sensor,
                "last_reading": last_reading,
                "best_day": best_day,
                "worst_day": worst_day,
            },
            "glucose_trend": trend,
        },
        cache_seconds=3600,
    )


# labs page, so a determined reader applying this formula could approximate age from a precise
# phenotypic number — flagged for review.) Population-level, correlative, NOT the DNAm clock.
_PHENOAGE_COEF = {  # (coefficient, reference value in formula units) — ref = healthy midpoint
    "albumin_gL": (-0.0336, 45.0),
    "creatinine_umolL": (0.0095, 80.0),
    "glucose_mmolL": (0.1953, 5.0),
    "lncrp": (0.0954, None),  # ln(CRP mg/dL); handled separately
    "lymphocyte_pct": (-0.0120, 32.0),
    "mcv_fL": (0.0268, 90.0),
    "rdw_pct": (0.3306, 13.0),
    "alp_UL": (0.00188, 65.0),
    "wbc_1000": (0.0554, 6.0),
}

_PHENOAGE_LABELS = {
    "albumin_gL": "Albumin",
    "creatinine_umolL": "Creatinine",
    "glucose_mmolL": "Glucose",
    "lncrp": "hs-CRP",
    "lymphocyte_pct": "Lymphocyte %",
    "mcv_fL": "MCV",
    "rdw_pct": "RDW",
    "alp_UL": "Alkaline phosphatase",
    "wbc_1000": "WBC",
}


def _compute_phenoage(vals: dict, age_years: float):
    """Levine Phenotypic Age from the 9 converted markers (formula units) + chronological age.
    Returns the exact phenotypic age in years, or None on bad inputs. Age is an INPUT only."""
    import math

    try:
        g = 0.0076927
        xb = (
            -19.9067
            - 0.0336 * vals["albumin_gL"]
            + 0.0095 * vals["creatinine_umolL"]
            + 0.1953 * vals["glucose_mmolL"]
            + 0.0954 * math.log(max(0.01, vals["crp_mgdL"]))
            - 0.0120 * vals["lymphocyte_pct"]
            + 0.0268 * vals["mcv_fL"]
            + 0.3306 * vals["rdw_pct"]
            + 0.00188 * vals["alp_UL"]
            + 0.0554 * vals["wbc_1000"]
            + 0.0804 * age_years
        )
        mort = 1.0 - math.exp(-math.exp(xb) * (math.exp(120.0 * g) - 1.0) / g)
        if mort <= 0 or mort >= 1:
            return None
        pheno = 141.50225 + math.log(-0.00553 * math.log(1.0 - mort)) / 0.090165
        return pheno
    except (ValueError, KeyError, ZeroDivisionError, OverflowError):
        return None


def phenoage(*, _g) -> dict:
    """GET /api/phenoage — transparent Levine Phenotypic Age. Option A privacy: returns the
    phenotypic age + the 9 driver markers ONLY; never chronological age or the gap."""
    datetime = _g["datetime"]

    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        markers = labs.get("biomarkers", []) or []
        by = {}
        for m in markers:
            nm = str(m.get("name", "")).strip().lower()
            if nm and nm not in by:
                by[nm] = m

        def _num(name):
            m = by.get(name)
            if not m:
                return None
            try:
                return float(str(m.get("value")).replace("<", "").replace(">", "").strip())
            except (TypeError, ValueError):
                return None

        raw = {
            "albumin": _num("albumin"),
            "creatinine": _num("creatinine"),
            "glucose": _num("glucose"),
            "crp": _num("crp hs"),
            "mcv": _num("mcv"),
            "rdw": _num("rdw"),
            "alp": _num("alkaline phosphatase"),
            "wbc": _num("wbc"),
            "abs_lymph": _num("absolute lymphocytes"),
        }
        # Lymphocyte % derived from absolute lymphocytes ÷ WBC (2a — exact, labeled).
        lymph_pct = None
        lymph_derived = False
        if raw["abs_lymph"] is not None and raw["wbc"]:
            lymph_pct = round(raw["abs_lymph"] / (raw["wbc"] * 1000.0) * 100.0, 1)
            lymph_derived = True

        required = {
            "Albumin": raw["albumin"],
            "Creatinine": raw["creatinine"],
            "Glucose": raw["glucose"],
            "hs-CRP": raw["crp"],
            "Lymphocyte %": lymph_pct,
            "MCV": raw["mcv"],
            "RDW": raw["rdw"],
            "Alkaline phosphatase": raw["alp"],
            "WBC": raw["wbc"],
        }
        missing = [k for k, v in required.items() if v is None]
        # Chronological age (compute-only; never returned). From profile DOB.
        prof = _get_profile() or {}
        dob = prof.get("date_of_birth")
        age_years = None
        if dob:
            try:
                d = datetime.strptime(str(dob)[:10], "%Y-%m-%d")
                age_years = (datetime.now(timezone.utc).replace(tzinfo=None) - d).days / 365.25
            except (ValueError, TypeError):
                age_years = None

        if missing or age_years is None:
            return _ok(
                {
                    "phenoage": None,
                    "missing": missing or (["chronological age (profile)"] if age_years is None else []),
                    "as_of": labs.get("latest_draw_date"),
                    "lymphocyte_derived": lymph_derived,
                },
                cache_seconds=3600,
            )

        # Convert to formula units.
        vals = {
            "albumin_gL": raw["albumin"] * 10.0,  # g/dL → g/L
            "creatinine_umolL": raw["creatinine"] * 88.42,  # mg/dL → µmol/L
            "glucose_mmolL": raw["glucose"] / 18.0182,  # mg/dL → mmol/L
            "crp_mgdL": raw["crp"] / 10.0,  # mg/L → mg/dL
            "lymphocyte_pct": lymph_pct,
            "mcv_fL": raw["mcv"],
            "rdw_pct": raw["rdw"],
            "alp_UL": raw["alp"],
            "wbc_1000": raw["wbc"],
        }
        pheno = _compute_phenoage(vals, age_years)
        if pheno is None:
            return _ok({"phenoage": None, "missing": ["computation failed"], "as_of": labs.get("latest_draw_date")}, cache_seconds=3600)

        # Per-marker driver direction (younger/older) vs healthy reference — transparent, but
        # NOT the raw contribution (keeps the published surface from adding inversion precision).
        import math

        drivers = []
        for key, (coef, ref) in _PHENOAGE_COEF.items():
            if key == "lncrp":
                val_f = math.log(max(0.01, vals["crp_mgdL"]))
                ref_f = math.log(0.1)
                disp_val, disp_unit = raw["crp"], "mg/L"
            else:
                val_f = vals[key]
                ref_f = ref
                disp_val, disp_unit = {
                    "albumin_gL": (raw["albumin"], "g/dL"),
                    "creatinine_umolL": (raw["creatinine"], "mg/dL"),
                    "glucose_mmolL": (raw["glucose"], "mg/dL"),
                    "lymphocyte_pct": (lymph_pct, "%"),
                    "mcv_fL": (raw["mcv"], "fL"),
                    "rdw_pct": (raw["rdw"], "%"),
                    "alp_UL": (raw["alp"], "U/L"),
                    "wbc_1000": (raw["wbc"], "K/µL"),
                }[key]
            push = coef * (val_f - ref_f)  # >0 raises pheno (older), <0 lowers (younger)
            direction = "older" if push > 0.02 else ("younger" if push < -0.02 else "neutral")
            drivers.append(
                {
                    "name": _PHENOAGE_LABELS[key],
                    "value": disp_val,
                    "unit": disp_unit,
                    "direction": direction,
                    "derived": (key == "lymphocyte_pct" and lymph_derived),
                }
            )

        # Round to the nearest year for display; chronological age and the gap are NOT returned.
        return _ok(
            {
                "phenoage": round(pheno),
                "as_of": labs.get("latest_draw_date"),
                "drivers": drivers,
                "lymphocyte_derived": lymph_derived,
                "missing": [],
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[phenoage] failed: {e}")
        return _error(503, "Phenotypic age temporarily unavailable.")


# Privacy absolute (PRE-13 pending): named genes / genotypes must NEVER reach the
# public labs payload. Matched case-insensitively against category + name/notes/range/value.
_GENETIC_CATEGORY_RE = _re.compile(r"pharmacogenomic|genetic|genomic", _re.IGNORECASE)

_GENETIC_TEXT_RE = _re.compile(r"genotype|\bgene\b|\brs\d+\b|variant|allele|\bsnp\b", _re.IGNORECASE)


def _strip_genetic_biomarkers(labs: dict) -> dict:
    """Drop any biomarker that is genetic (pharmacogenomics category, or genotype/gene/rsID/variant
    language in its fields) and recompute served counts so the page header stays consistent."""
    kept = []
    for b in labs.get("biomarkers") or []:
        if _GENETIC_CATEGORY_RE.search(str(b.get("category") or "")):
            continue
        text = " ".join(str(b.get(k) or "") for k in ("name", "notes", "range", "value"))
        if _GENETIC_TEXT_RE.search(text):
            continue
        kept.append(b)
    sanitized = dict(labs)
    sanitized["biomarkers"] = kept
    # Same flag semantics as the front-end (evidence_body.js): truthy and not the string "null".
    sanitized["flagged_count"] = sum(1 for b in kept if b.get("flag") and str(b.get("flag")).lower() != "null")
    for count_key in ("biomarker_count", "total_biomarkers"):
        if count_key in sanitized:
            sanitized[count_key] = len(kept)
    return sanitized


def labs() -> dict:
    """GET /api/labs — Returns lab biomarkers from clinical.json in S3 (genetic entries stripped)."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        if not labs or not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        labs = _strip_genetic_biomarkers(labs)
        if not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        return _ok({"labs": labs}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[labs] Failed to load clinical.json: {e}")
        return _error(503, "Lab data temporarily unavailable.")
