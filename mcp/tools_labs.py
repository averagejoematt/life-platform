"""
Lab results, genome, DEXA tools.
"""

# ── SEC-GENOME: Privacy guardrail for public content ─────────────────────────
# Raw genome identifiers (gene names, rsIDs, genotypes) must NEVER appear
# in any public-facing content: chronicle posts, daily brief excerpts,
# public_stats.json, site API responses, or email digests.
#
# ALLOWED in public content:
#   "genetic predisposition to obesity"
#   "variants affecting vitamin D metabolism"
#   "genomic data suggests elevated LDL baseline"
#
# NEVER in public content:
#   "FTO rs9939609 A;T"
#   "MTHFR compound heterozygous"
#   "SLCO1B1 C;T — 4.5x statin myopathy risk"
#
# This notice is appended to all genome-bearing tool outputs — wired at the
# `tool_get_labs` dispatcher via `_attach_genome_privacy_notice` (#2241), which
# DETECTS the identifier fields structurally rather than listing the response
# keys that happen to carry them today. A future view that ships genome
# identifiers under a new key is covered without editing this module.
# ─────────────────────────────────────────────────────────────────────────────
_GENOME_PRIVACY_NOTICE = (
    "PRIVACY GUARDRAIL: This data contains raw genome identifiers (gene names, "
    "rsIDs, genotypes). These must NEVER appear in any public-facing content "
    "including chronicle posts, daily briefs, emails, site API responses, or "
    "public_stats.json. When referencing genome insights in public content, use "
    "non-specific language only (e.g. 'genetic predisposition to X', 'genomic "
    "variants affecting Y metabolism'). Never publish specific gene names, "
    "rsID numbers, or genotype strings (e.g. 'A;T', 'C;C'). This data is for "
    "private MCP use and Matthew's personal reference only."
)

# The response key the notice is attached under.
_GENOME_PRIVACY_NOTICE_KEY = "privacy_notice"

# The raw genome identifier fields produced by `labs_helpers._genome_context_for_biomarkers`.
# Presence of ANY of these anywhere in a response is what makes it "genome-bearing" —
# the detection is on the identifiers themselves, not on the container key, so a new
# view/response shape cannot silently ship them un-noticed.
_GENOME_IDENTIFIER_FIELDS = ("gene", "rsid", "genotype")

# Recursion guard only. Today's genome identifiers sit at depth 3
# (response → genome_context → biomarker list → snp dict).
_GENOME_SCAN_MAX_DEPTH = 12

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common.pacific_time import PACIFIC

from mcp.config import logger, table
from mcp.helpers import _linear_regression
from mcp.labs_helpers import _draw_date_of, _genome_context_for_biomarkers, _measured_value, _query_all_lab_draws
from mcp.utils import mcp_error

# One year, used for BOTH `slope_per_year` and the 1-year projection. They used to
# disagree (365.25 vs 365), so `latest + slope_per_year` never reconciled with
# `projected_1yr` and the residual looked like a data problem.
YEAR_DAYS = 365.25

# ADR-105: a rate needs a denominator before it is a rate. A biomarker flagged on
# the one and only draw it has ever appeared in scores 100% — "chronic" is a
# clinical word and a single observation has not earned it.
MIN_DRAWS_FOR_PERSISTENCE = 2


def _carries_genome_identifiers(node, _depth=0):
    """True when `node` contains a raw genome identifier anywhere inside it.

    Structural, not key-name based: any nested mapping carrying a truthy
    `gene` / `rsid` / `genotype` counts, wherever it sits in the response.
    """
    if _depth > _GENOME_SCAN_MAX_DEPTH:
        return False
    if isinstance(node, dict):
        if any(node.get(f) for f in _GENOME_IDENTIFIER_FIELDS):
            return True
        return any(_carries_genome_identifiers(v, _depth + 1) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_carries_genome_identifiers(v, _depth + 1) for v in node)
    return False


def _attach_genome_privacy_notice(out):
    """Attach `_GENOME_PRIVACY_NOTICE` to any response that actually ships genome identifiers.

    SEC-GENOME (#2241): this is the single chokepoint that makes the module's
    declared control real. It is applied at the `tool_get_labs` dispatcher, so
    every view — including ones added later — is covered; the notice is attached
    only when identifiers are genuinely present, so it never becomes noise on a
    response that carries none.
    """
    if not isinstance(out, dict):
        return out
    if _carries_genome_identifiers(out):
        out[_GENOME_PRIVACY_NOTICE_KEY] = _GENOME_PRIVACY_NOTICE
    return out


def _get_lab_results(args):
    """Single draw detail with genome annotations, or summary of all draws."""
    draw_date = args.get("draw_date")
    category = args.get("category")
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found in DynamoDB"}

    if not draw_date:
        summaries = []
        for d in draws:
            summaries.append(
                {
                    "draw_date": _draw_date_of(d),
                    "provider": d.get("lab_provider"),
                    "lab_network": d.get("lab_network"),
                    "fasting": d.get("fasting"),
                    "total_biomarkers": d.get("total_biomarkers"),
                    "out_of_range_count": d.get("out_of_range_count"),
                    "out_of_range": d.get("out_of_range", []),
                }
            )
        return {"total_draws": len(draws), "draws": summaries, "hint": "Pass draw_date to see full biomarkers for a specific draw."}

    draw = next((d for d in draws if _draw_date_of(d) == draw_date), None)
    if not draw:
        return {"error": f"No draw for {draw_date}", "available_dates": [_draw_date_of(d) for d in draws]}

    biomarkers = draw.get("biomarkers", {})
    total_biomarkers = draw.get("total_biomarkers")
    out_of_range_count = draw.get("out_of_range_count")
    out_of_range = draw.get("out_of_range", [])
    if category:
        biomarkers = {k: v for k, v in biomarkers.items() if v.get("category") == category}
        # The counts must describe the set actually on screen. Copying the WHOLE
        # draw's totals beside a narrowed panel names a flag for a biomarker that is
        # not shown and not in the category that was asked for.
        out_of_range = [k for k, v in biomarkers.items() if v.get("flag") in ("high", "low")]
        total_biomarkers = len(biomarkers)
        out_of_range_count = len(out_of_range)

    genome_ctx = _genome_context_for_biomarkers(list(biomarkers.keys()))
    categories = sorted(set(v.get("category", "") for v in draw.get("biomarkers", {}).values()))

    result = {
        "draw_date": draw_date,
        "provider": draw.get("lab_provider"),
        "lab_network": draw.get("lab_network"),
        "physician": draw.get("physician"),
        "fasting": draw.get("fasting"),
        "total_biomarkers": total_biomarkers,
        "out_of_range_count": out_of_range_count,
        "out_of_range": out_of_range,
        "biomarkers": biomarkers,
        "genome_context": genome_ctx if genome_ctx else None,
        "categories_in_draw": categories,
    }
    if category:
        result["category_filter"] = category
        result["draw_total_biomarkers"] = draw.get("total_biomarkers")
        result["draw_out_of_range"] = draw.get("out_of_range", [])
    return result


def _within_window(date_str, start_date, end_date):
    """Inclusive [start_date, end_date] membership for an ISO date, or False if undatable."""
    if not date_str:
        return False
    if start_date and date_str < start_date:
        return False
    if end_date and date_str > end_date:
        return False
    return True


def _resolve_biomarker_keys(requested, draws):
    """Map each requested biomarker name onto the keys actually present in the draws.

    The registry advertises the `biomarker` property as "partial match"; the loop
    below used to do an exact dict-key lookup, so "cholesterol" came back as
    "No data for 'cholesterol'" while `cholesterol_total` sat in every draw — a
    present biomarker reading as never measured.

    Returns `([(response_key, actual_key), ...], ambiguity_notes)`. An exact key
    always wins. A token resolving to exactly one biomarker keeps the *requested*
    name as its response key (the caller reads back the name it asked with) and
    carries `resolved_biomarker`. An ambiguous token is never silently narrowed to
    one guess: it expands to one entry per match under the real keys, with a note
    under the requested name naming every match.
    """
    present: set = set()
    for d in draws:
        present.update(d.get("biomarkers", {}) or {})

    resolved: list = []
    notes: dict = {}
    for name in requested:
        if name in present:
            resolved.append((name, name))
            continue
        token = str(name).lower()
        matches = sorted(k for k in present if token in str(k).lower())
        if len(matches) == 1:
            resolved.append((name, matches[0]))
        elif matches:
            notes[name] = {
                "matched_biomarkers": matches,
                "hint": f"'{name}' matched {len(matches)} biomarkers; each is reported under its own key.",
            }
            resolved.extend((m, m) for m in matches)
        else:
            # No match at all — kept so the loop emits the usual "No data" envelope.
            resolved.append((name, name))
    # De-dupe while preserving order (a token can expand onto an explicitly named key).
    seen: set = set()
    return [rk_ak for rk_ak in resolved if not (rk_ak in seen or seen.add(rk_ak))], notes


def _get_lab_trends(args):
    """Biomarker trajectory across all draws with slope, projection, derived ratios."""
    biomarkers_req = args.get("biomarkers", [])
    single = args.get("biomarker")
    if single:
        biomarkers_req = [single]
    include_derived = args.get("include_derived_ratios", True)
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    # The registry declares start_date/end_date for this view; honour them rather
    # than regressing over every draw ever taken and answering a question that was
    # not asked ("how has my LDL moved since March" must not start in 2019).
    start_date, end_date = args.get("start_date"), args.get("end_date")
    window = None
    if start_date or end_date:
        window = {"start_date": start_date, "end_date": end_date}
        draws = [d for d in draws if _within_window(_draw_date_of(d), start_date, end_date)]
        if not draws:
            return {
                "trends": {},
                "error": f"No lab draws between {start_date or 'the first draw'} and {end_date or 'today'}",
                "window": window,
            }

    if not biomarkers_req:
        return {
            "trends": {},
            "error": "No biomarker requested for the trends view.",
            "hint": "Pass biomarker='ldl_c' (partial names are matched), or use view='results' for the whole panel.",
            "total_draws": len(draws),
            **({"window": window} if window else {}),
        }

    from datetime import datetime as _dt

    resolved, ambiguous = _resolve_biomarker_keys(biomarkers_req, draws)
    trends: dict = dict(ambiguous)
    for resp_key, bm_key in resolved:
        points = []
        undated = 0
        for d in draws:
            bms = d.get("biomarkers", {})
            if bm_key not in bms:
                continue
            val = _measured_value(bms[bm_key])
            if not isinstance(val, (int, float)):
                continue
            date = _draw_date_of(d)
            if not date:
                # An undatable draw has no place on a time axis, and crashing the
                # whole view on one bad import row is not degrading gracefully.
                undated += 1
                continue
            points.append(
                {
                    "date": date,
                    "value": round(val, 2),
                    "flag": bms[bm_key].get("flag", "normal"),
                    "ref": bms[bm_key].get("ref_text", ""),
                    "unit": bms[bm_key].get("unit", ""),
                }
            )
        if not points:
            trends[resp_key] = {"error": f"No data for '{resp_key}'", "hint": "Use search_biomarker to find valid names."}
            if undated:
                trends[resp_key]["undated_draws_skipped"] = undated
            continue

        base = _dt.strptime(points[0]["date"], "%Y-%m-%d")
        reg_pts = [((_dt.strptime(p["date"], "%Y-%m-%d") - base).days, p["value"]) for p in points]
        slope, intercept, r_sq = _linear_regression(reg_pts)

        if slope is not None:
            direction = "rising" if slope > 0.001 else ("falling" if slope < -0.001 else "stable")
            slope_per_year = round(slope * YEAR_DAYS, 2)
        else:
            direction, slope_per_year = "insufficient_data", None

        projected_1yr, projection_note = None, None
        if slope is not None and len(reg_pts) >= 2:
            raw = round(intercept + slope * (reg_pts[-1][0] + YEAR_DAYS), 2)
            # A straight line extrapolated a year past two draws leaves the
            # biomarker's physical domain long before it leaves the arithmetic:
            # 130 -> 110 mg/dL LDL over 60 days projects to a NEGATIVE cholesterol.
            # The floor is derived from this biomarker's own observed range rather
            # than a literature default — negative is out of domain unless this
            # marker has actually been measured negative.
            if raw < 0 and min(p["value"] for p in points) >= 0:
                projection_note = (
                    f"Withheld: the linear extrapolation lands at {raw}, outside the physical domain of "
                    f"'{bm_key}' (never measured below 0 in {len(points)} draws). A straight line is not a "
                    "physiological model over a year."
                )
            else:
                projected_1yr = raw

        entry = {
            "values": points,
            "data_points": len(points),
            "direction": direction,
            "slope_per_year": slope_per_year,
            "r_squared": r_sq,
            "projected_1yr": projected_1yr,
            "latest": points[-1]["value"],
            "earliest": points[0]["value"],
            "total_change": round(points[-1]["value"] - points[0]["value"], 2),
        }
        if projection_note:
            entry["projection_note"] = projection_note
        elif projected_1yr is not None and len(points) < 3:
            # ADR-105: the forecast ships with its n and with what that n cannot buy.
            entry["projection_caveat"] = (
                f"Projected from n={len(points)}: no prediction interval is computable " "(zero residual degrees of freedom below n=3)."
            )
        if bm_key != resp_key:
            entry["resolved_biomarker"] = bm_key
        if undated:
            entry["undated_draws_skipped"] = undated
        trends[resp_key] = entry

    derived: dict = {}
    if include_derived:
        for d in draws:
            bms = d.get("biomarkers", {})
            date = _draw_date_of(d)
            tg_v = _measured_value(bms.get("triglycerides"))
            hdl_v = _measured_value(bms.get("hdl"))
            tc_v = _measured_value(bms.get("cholesterol_total"))
            # `hdl_v > 0` on ALL THREE: an HDL of 0 is not a physiologic measurement,
            # so non-HDL derived from it would be a fabricated number, not just an
            # un-dividable one. (Before the honest-zero fix above this fell out by
            # accident, because a stored 0 was silently turned into None.)
            hdl_ok = isinstance(hdl_v, (int, float)) and hdl_v > 0

            if isinstance(tg_v, (int, float)) and hdl_ok:
                derived.setdefault("tg_hdl_ratio", []).append(
                    {
                        "date": date,
                        "value": round(tg_v / hdl_v, 2),
                        "interpretation": "optimal <1.0, good <2.0, elevated >=2.0 (insulin resistance proxy)",
                    }
                )
            if isinstance(tc_v, (int, float)) and hdl_ok:
                derived.setdefault("non_hdl_cholesterol", []).append(
                    {"date": date, "value": round(tc_v - hdl_v, 1), "interpretation": "optimal <130, borderline 130-159, high >=160"}
                )
                derived.setdefault("tc_hdl_ratio", []).append(
                    {"date": date, "value": round(tc_v / hdl_v, 2), "interpretation": "optimal <3.5, good <5.0, elevated >=5.0"}
                )

    genome_ctx = _genome_context_for_biomarkers([actual for _, actual in resolved])
    result = {
        "trends": trends,
        "total_draws": len(draws),
        "date_range": f"{_draw_date_of(draws[0]) or 'unknown'} to {_draw_date_of(draws[-1]) or 'unknown'}",
    }
    if window:
        result["window"] = window
    if derived:
        result["derived_ratios"] = derived
    if genome_ctx:
        result["genome_context"] = genome_ctx
    return result


def _persistence_class(times_tested, flag_rate_pct):
    """Persistence label for a flagged biomarker, or `single_observation` below the min n.

    A rate computed over one draw is not a rate: a first-ever high ferritin scores
    100% and used to come back labelled "chronic" — a clinical word — and the same
    field feeds `chronic_flags`, which drives the "genetic baseline rather than
    lifestyle failure" narrative. ADR-105: publish the class only once there is a
    denominator behind it.
    """
    if times_tested < MIN_DRAWS_FOR_PERSISTENCE:
        return "single_observation"
    return "chronic" if flag_rate_pct >= 60 else ("recurring" if flag_rate_pct >= 30 else "occasional")


def _get_out_of_range_history(args):
    """Every flagged biomarker across all draws with persistence and genome drivers."""
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    oor_map = defaultdict(list)
    for d in draws:
        date = _draw_date_of(d)
        bms = d.get("biomarkers", {})
        for key, bm_data in bms.items():
            if bm_data.get("flag") in ("high", "low"):
                val = _measured_value(bm_data)
                oor_map[key].append(
                    {
                        "date": date,
                        "value": val,
                        "flag": bm_data["flag"],
                        "unit": bm_data.get("unit", ""),
                        "ref_text": bm_data.get("ref_text", ""),
                        "category": bm_data.get("category", ""),
                    }
                )

    total_draws = len(draws)
    flagged = []
    for key, occurrences in sorted(oor_map.items(), key=lambda x: -len(x[1])):
        tested_count = sum(1 for d in draws if key in d.get("biomarkers", {}))
        flagged_rate = round(100 * len(occurrences) / max(tested_count, 1), 1)
        flagged.append(
            {
                "biomarker": key,
                "category": occurrences[0]["category"],
                "times_flagged": len(occurrences),
                "times_tested": tested_count,
                "flag_rate_pct": flagged_rate,
                "persistence": _persistence_class(tested_count, flagged_rate),
                "occurrences": occurrences,
            }
        )

    chronic_keys = [f["biomarker"] for f in flagged if f["persistence"] == "chronic"]
    genome_ctx = _genome_context_for_biomarkers(chronic_keys)

    return {
        "total_draws": total_draws,
        "date_range": f"{_draw_date_of(draws[0]) or 'unknown'} to {_draw_date_of(draws[-1]) or 'unknown'}",
        "flagged_biomarkers": flagged,
        "total_unique_flags": len(flagged),
        "chronic_flags": chronic_keys,
        "genome_drivers": genome_ctx if genome_ctx else None,
        "insight": (
            ("Chronic out-of-range biomarkers with genome drivers suggest genetic baseline " "rather than lifestyle failure.")
            if genome_ctx
            else None
        ),
    }


def tool_get_labs(args):
    """Unified lab intelligence dispatcher."""
    VALID_VIEWS = {
        "results": _get_lab_results,
        "trends": _get_lab_trends,
        "out_of_range": _get_out_of_range_history,
    }
    view = (args.get("view") or "results").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'results' for latest draws, 'trends' for trajectory, 'out_of_range' for persistent flags.",
        }
    out = VALID_VIEWS[view](args)
    # FH v2 augment (PR 4a, 2026-05-03): always attach cadence_trackers for the
    # annual-or-rarer sentinel panels (NfL, Galleri). Surfaced on every view so
    # callers don't have to remember a separate query.
    if isinstance(out, dict) and "cadence_trackers" not in out:
        try:
            out["cadence_trackers"] = _build_cadence_trackers()
        except Exception as e:
            logger.warning(f"cadence_trackers build failed: {e}")
    # SEC-GENOME (#2241): last step, so it sees every augment above it too.
    return _attach_genome_privacy_notice(out)


# ── FH v2 augments (PR 4a, 2026-05-03) ───────────────────────────────────────
# Tonight decisions per Matthew's docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md:
#   NfL cadence = 180 days (sensitive neurodegeneration baseline; warrants
#                            6-month tracking even though Galleri is annual)
#   Galleri cadence = 365 days (per GRAIL recommendation)
# Galleri framing wording borrowed from the Technical Board version:
#   "No signal detected at 24-month early-detection threshold"
#   instead of the raw "NO CANCER SIGNAL DETECTED" — Viktor's adversarial
#   pushback on framing absence-of-evidence as evidence-of-absence.

NFL_CADENCE_DAYS = 180
GALLERI_CADENCE_DAYS = 365

# ImmunoCAP IgE class boundaries (kU/L). Class 0 = no sensitization; 6 = max.
_IGE_CLASS_BOUNDARIES = [
    (0.10, 0),  # < 0.10 → Class 0
    (0.35, 1),  # 0.10–0.34 → Class 1
    (0.70, 2),  # 0.35–0.69 → Class 2
    (3.50, 3),  # 0.70–3.49 → Class 3
    (17.5, 4),  # 3.50–17.4 → Class 4
    (50.0, 5),  # 17.5–49.9 → Class 5
    # ≥ 50.0 → Class 6
]
_IGE_CLASS_LABELS = {
    0: "No detectable",
    1: "Low",
    2: "Moderate",
    3: "High",
    4: "Very High",
    5: "Extremely High",
    6: "Maximum",
}

# Allergen → category map. Categories used in the get_allergies response.
_ALLERGEN_CATEGORIES = {
    # dust mite
    "dust_mite_d_pteronyssinus": "dust_mite",
    "dust_mite_d_farinae": "dust_mite",
    # environmental pollen
    "alder": "environmental_pollen",
    "birch": "environmental_pollen",
    "oak": "environmental_pollen",
    "elm": "environmental_pollen",
    "mountain_cedar": "environmental_pollen",
    "cottonwood": "environmental_pollen",
    "maple_box_elder": "environmental_pollen",
    "walnut_tree": "environmental_pollen",
    "white_ash": "environmental_pollen",
    "sheep_sorrel": "environmental_pollen",
    "rough_pigweed": "environmental_pollen",
    "common_ragweed": "environmental_pollen",
    "nettle": "environmental_pollen",
    "timothy_grass": "environmental_pollen",
    # dander
    "cat_dander": "dander",
    "dog_dander": "dander",
    "mouse_urine_proteins": "dander",
    # mold
    "aspergillus_fumigatus": "mold",
    "cladosporium_herbarum": "mold",
    "penicillium_notatum": "mold",
    "alternaria_alternata": "mold",
    # other
    "cockroach": "other",
}


def _ige_class(value_kU_L):
    """Map an IgE value (kU/L) to ImmunoCAP class 0–6."""
    if value_kU_L is None:
        return None
    try:
        v = float(value_kU_L)
    except (TypeError, ValueError):
        return None
    for boundary, cls in _IGE_CLASS_BOUNDARIES:
        if v < boundary:
            return cls
    return 6


def _allergen_meta(biomarker_key):
    """Strip 'allergy_' prefix and look up category."""
    base = biomarker_key.replace("allergy_", "", 1)
    return base, _ALLERGEN_CATEGORIES.get(base, "other")


def _frame_galleri_signal(raw):
    """Reframe an all-clear Galleri result; anything else passes through verbatim.

    Technical Board (Viktor): absence of evidence is not evidence of absence. The
    reframe is applied at EVERY point the signal is published — the tracker head and
    each history entry — because a reframe that leaves the shoutier raw string one
    key away is advisory, not enforced: an LLM summarising the payload will quote
    "NO CANCER SIGNAL DETECTED".
    """
    if "NO CANCER" in str(raw or "").upper() or "NO SIGNAL" in str(raw or "").upper():
        return "No signal detected at 24-month early-detection threshold"
    return raw


def _build_cadence_trackers():
    """Return cadence-tracker dict for NfL + Galleri. Returns {} if no draws."""
    draws = _query_all_lab_draws()
    if not draws:
        return {}
    # The platform keys its data by the PACIFIC calendar day, and this module already
    # runs a UTC clock in tool_get_freshness_status; a bare `datetime.now()` here was
    # a third clock — naive LOCAL time (UTC on the Lambda host), off by one for the
    # whole UTC-evening window every day.
    today = datetime.now(timezone.utc).astimezone(PACIFIC).date()

    def _latest_for(biomarker_key):
        """Find the latest draw containing this biomarker; return (date_str, value, unit) or None."""
        for d in reversed(draws):  # latest-first
            bms = d.get("biomarkers", {})
            if biomarker_key in bms:
                bm = bms[biomarker_key]
                return (
                    d.get("draw_date"),
                    _measured_value(bm),
                    bm.get("unit", ""),
                )
        return None

    def _history_for(biomarker_key, value_field):
        """Return chronological history of a biomarker."""
        out = []
        for d in draws:
            bm = d.get("biomarkers", {}).get(biomarker_key)
            if bm:
                entry = {"date": d.get("draw_date")}
                if value_field == "numeric":
                    entry["value"] = _measured_value(bm)
                    entry["unit"] = bm.get("unit", "")
                else:
                    entry["signal"] = _frame_galleri_signal(bm.get("value"))
                out.append(entry)
        return out

    out = {}

    # NfL — neurodegeneration baseline; 180-day cadence per Matthew tonight
    nfl_latest = _latest_for("nfl_neurofilament_light_chain")
    if nfl_latest:
        last_date_str, last_value, last_unit = nfl_latest
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since = (today - last_date).days
            next_due = (last_date + timedelta(days=NFL_CADENCE_DAYS)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            days_since = None
            next_due = None
        out["nfl"] = {
            "last_drawn": last_date_str,
            "days_since_last": days_since,
            "recommended_cadence_days": NFL_CADENCE_DAYS,
            "next_due": next_due,
            "history": _history_for("nfl_neurofilament_light_chain", "numeric"),
        }

    # Galleri — annual cancer screen
    gal_latest = _latest_for("galleri_cancer_signal")
    if gal_latest:
        last_date_str, last_signal, _ = gal_latest
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since = (today - last_date).days
            next_due = (last_date + timedelta(days=GALLERI_CADENCE_DAYS)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            days_since = None
            next_due = None
        out["galleri"] = {
            "last_drawn": last_date_str,
            "days_since_last": days_since,
            "recommended_cadence_days": GALLERI_CADENCE_DAYS,
            "next_due": next_due,
            # Reframe per Technical Board (Viktor). The raw string is NOT republished
            # beside it — see _frame_galleri_signal.
            "last_signal": _frame_galleri_signal(last_signal),
            "history": _history_for("galleri_cancer_signal", "signal"),
        }

    return out


# ── DI-2b parity: interior-gap detection (B3) ──
# The staleness check below only sees the newest DATE# per source (the high-water
# mark), so a hole *behind* it — a daily source going dead mid-window then resuming
# — reads green. This mirrors find_interior_gaps in emails/freshness_checker_lambda.py
# (TD-14 parity discipline: keep the two in sync). Sparse sources (strava, withings,
# food_delivery, measurements) have legitimate empty days → excluded here.
DAILY_SOURCES_INTERIOR = {"whoop", "apple_health", "eightsleep", "habitify"}
INTERIOR_GAP_WINDOW_DAYS = 14


def find_interior_gaps(present_dates, window_start: str, window_end: str) -> list:
    """Missing dates strictly inside the [first, last] present span in the window.

    Only the span between the earliest and latest present date is judged — a
    trailing or leading absence is recency (handled by the staleness check), not
    an interior hole. Returns a sorted list of 'YYYY-MM-DD'. Needs >=2 present
    dates to define an interior at all. Pure function — no AWS, no network.
    """
    present = sorted(d for d in present_dates if window_start <= d <= window_end)
    if len(present) < 2:
        return []
    pset = set(present)
    cur = datetime.strptime(present[0], "%Y-%m-%d").date()
    hi = datetime.strptime(present[-1], "%Y-%m-%d").date()
    gaps = []
    while cur <= hi:
        s = cur.isoformat()
        if s not in pset:  # lo/hi are present, so anything missing here is interior
            gaps.append(s)
        cur += timedelta(days=1)
    return gaps


def tool_get_freshness_status(args):
    """Per-source data freshness summary (WR-48 Enhancement 4, PR-reentry-4).

    Independently computes staleness per source by querying the latest DATE# sk
    from each source partition — does NOT depend on the freshness-checker Lambda
    having run recently. Returns a status (green / yellow / orange / red) plus
    per-source last-date / age-days / threshold.

    Mirror of lambdas/freshness_checker_lambda.py SOURCES + SOURCE_STALE_HOURS
    (kept in sync manually; see TD-14 parity discipline).

    Args (all optional):
        sources: list[str] — restrict to these source keys; default = all 11
    """

    # #392: derive from the canonical registry (bundled lambdas/ tree) instead of a third
    # hand-rolled mirror — this one had drifted worst (food_delivery still 90d,
    # the pre-triage masking value; hevy missing entirely).
    from ingestion.source_registry import DEFAULT_STALE_HOURS, mcp_sources, stale_hours_overrides

    # DI-1.1: legible source-state (live/paused/rate_limited/stale) so a deliberately-off
    # source (Strava) or a rate-limited one (Garmin) is never mistaken for silent breakage.
    from ingestion.source_state import has_rate_limit_marker, resolve_source_state

    SOURCES = mcp_sources()
    SOURCE_STALE_HOURS = stale_hours_overrides(SOURCES)

    # #2662: an unrecognised source name used to be dropped here by the `if s in SOURCES`
    # filter, and the tool then answered green over what was LEFT. Asking about
    # ["whoop", "not_a_real_source"] returned status green / fresh_count 1 / stale_count 0
    # — a typo'd or renamed source read as "everything is fresh", from the one tool whose
    # entire job is answering "are we OK?". This is exactly the class `_unreadable` below
    # was written to close ("a source we could not read is a NOT-OK answer, never a silent
    # omission"); the unknown-name path simply sat one line above it and was missed.
    #
    # The valid set is derived from `mcp_sources()` — the same registry the evaluation
    # uses — so a source added or renamed there is accepted or rejected correctly on the
    # same commit, with no second list to keep in sync.
    requested = args.get("sources") if args else None
    if requested is not None and not isinstance(requested, list):
        return mcp_error(
            f"'sources' must be a list of source keys, got {type(requested).__name__}.",
            error_code="MISSING_ARG",
            suggestions=[f"Valid sources: {sorted(SOURCES)}", "Omit 'sources' entirely to check them all."],
        )
    if requested is not None:
        unknown = [s for s in requested if s not in SOURCES]
        if unknown:
            return mcp_error(
                f"Unrecognised source name(s): {sorted(unknown)}. Nothing was evaluated — "
                f"a freshness verdict over the sources that happened to be spelled correctly would be misleading.",
                error_code="SOURCE_UNAVAIL",
                suggestions=[f"Valid sources: {sorted(SOURCES)}", "Omit 'sources' entirely to check them all."],
            )
        if not requested:
            return mcp_error(
                "'sources' was an empty list — no source was named, so there is nothing to report on.",
                error_code="MISSING_ARG",
                suggestions=["Omit 'sources' entirely to check them all.", f"Valid sources: {sorted(SOURCES)}"],
            )
    keys = list(requested) if requested else list(SOURCES.keys())

    today = datetime.now(timezone.utc).date()
    per_source = []
    stale_count = 0
    unreadable_count = 0

    def _unreadable(src, reason, threshold_days):
        """A source we could not read is a NOT-OK answer, never a silent omission.

        This tool's whole job is "are we OK?". Three paths used to exit without a
        trace — a failed partition read built a `status: unknown` row that neither
        output bucket selected, and a non-DATE# or unparseable sk hit a bare
        `continue` — so asking about two sources with one unreadable answered
        `green, fresh_count: 1, stale_count: 0` and the unreadable source vanished.
        Unreadable rows count toward `stale_count` (which is really "sources not
        confirmed fresh") so the existing escalation tiers cover them.
        """
        return {
            "source": src,
            "label": SOURCES[src],
            "status": "unreadable",
            "reason": reason,
            "threshold_days": threshold_days,
        }

    for src in keys:
        threshold_hours = SOURCE_STALE_HOURS.get(src, DEFAULT_STALE_HOURS)
        threshold_days = threshold_hours / 24
        # Latest sk for this partition
        from boto3.dynamodb.conditions import Key as DDBKey

        pk = f"USER#matthew#SOURCE#{src}"
        try:
            resp = table.query(
                KeyConditionExpression=DDBKey("pk").eq(pk) & DDBKey("sk").begins_with("DATE#"),
                Limit=1,
                ScanIndexForward=False,
            )
        except Exception as e:
            row = _unreadable(src, f"partition read failed: {e}", int(threshold_days))
            row["error"] = str(e)
            per_source.append(row)
            stale_count += 1
            unreadable_count += 1
            continue
        _rl = has_rate_limit_marker(table, "matthew", src)
        items = resp.get("Items", [])
        if not items:
            per_source.append(
                {
                    "source": src,
                    "label": SOURCES[src],
                    "status": "no_data",
                    "source_state": resolve_source_state(src, None, today.isoformat(), rate_limited=_rl),
                    "threshold_days": threshold_days,
                }
            )
            stale_count += 1
            continue
        sk = items[0].get("sk", "")
        if not sk.startswith("DATE#"):
            per_source.append(_unreadable(src, f"newest row has a non-DATE# sort key ({sk!r})", int(threshold_days)))
            stale_count += 1
            unreadable_count += 1
            continue
        try:
            d = datetime.strptime(sk.split("DATE#", 1)[1][:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            per_source.append(_unreadable(src, f"newest sort key does not carry a calendar date ({sk!r})", int(threshold_days)))
            stale_count += 1
            unreadable_count += 1
            continue
        age_days = (today - d).days
        is_stale = age_days >= threshold_days
        if is_stale:
            stale_count += 1
        per_source.append(
            {
                "source": src,
                "label": SOURCES[src],
                "last_date": d.isoformat(),
                "age_days": age_days,
                "threshold_days": int(threshold_days),
                "status": "stale" if is_stale else "fresh",
                "source_state": resolve_source_state(src, d.isoformat(), today.isoformat(), rate_limited=_rl),
            }
        )

    # Status escalation tiers (WR-48 Enhancement 2 logic, used here for reporting only)
    max_age_stale = max(
        (s["age_days"] for s in per_source if s.get("status") == "stale"),
        default=0,
    )
    if stale_count == 0:
        overall = "green"
    elif stale_count == 1 and max_age_stale < 7:
        overall = "yellow"
    elif stale_count >= 3 or max_age_stale > 14:
        overall = "red"
    else:
        overall = "orange"

    # "stale_sources" is the needs-attention bucket; an unreadable source belongs in
    # it, because the one thing it must never do is disappear from the answer.
    stale_sources = [s for s in per_source if s.get("status") in ("stale", "no_data", "unreadable")]
    fresh_sources = [s for s in per_source if s.get("status") == "fresh"]

    # ── MacroFactor format-drift (meal-grouping guard) ──
    # The diary export carries per-food timestamps (entries_count > 0); the daily-
    # summary export is one row/day with an empty food_log (entries_count == 0). When
    # MacroFactor silently reverts to summary format, the meal grouper has no input
    # and the meal view goes stale without a staleness alert (the date is still fresh).
    # Flag when the last N records all have entries_count == 0.
    macro_drift = None
    if "macrofactor" in keys:
        from boto3.dynamodb.conditions import Key as _DDBKey

        try:
            _resp = table.query(
                KeyConditionExpression=_DDBKey("pk").eq("USER#matthew#SOURCE#macrofactor") & _DDBKey("sk").begins_with("DATE#"),
                ScanIndexForward=False,
                Limit=5,
                ProjectionExpression="#d, entries_count",
                ExpressionAttributeNames={"#d": "date"},
            )
            recs = _resp.get("Items", [])
            empties = [r for r in recs if int(r.get("entries_count", 0) or 0) == 0]
            last_with_log = next((r.get("date") for r in recs if int(r.get("entries_count", 0) or 0) > 0), None)
            drifted = bool(recs) and len(empties) == len(recs)
            macro_drift = {
                "drifted": drifted,
                "records_checked": len(recs),
                "consecutive_empty": len(empties),
                "last_food_log_date": last_with_log,
                "note": (
                    "MacroFactor diary export appears to have reverted to daily-summary (empty food_log) — "
                    "the meal grouper is starved. Re-export the diary format."
                    if drifted
                    else "Diary export healthy (recent records carry a food_log)."
                ),
            }
        except Exception as _e:  # noqa: BLE001
            macro_drift = {"drifted": None, "error": str(_e)}

    # ── Training-notes extractor silent-failure guard (notes feedback loop §8) ──
    # Notes present but no derived records (or all degraded) = the extractor went dark.
    training_notes_health = None
    try:
        from training.training_notes import training_notes_health as _tnh

        training_notes_health = _tnh(table)
    except Exception as _e:  # noqa: BLE001
        training_notes_health = {"checked": False, "error": str(_e)}

    # ── B3: interior-gap scan (daily sources only) ──
    # A daily source can read "fresh" (newest record present) while a mid-window day
    # is silently missing behind the high-water mark — the exact blindness that hid
    # the Strava walks. Scan the trailing window for each daily source and surface
    # holes inside its present span.
    from boto3.dynamodb.conditions import Key as _GapKey

    _gap_end = today.isoformat()
    _gap_start = (today - timedelta(days=INTERIOR_GAP_WINDOW_DAYS)).isoformat()
    interior_gaps: dict[str, list] = {}
    for _src in keys:
        if _src not in DAILY_SOURCES_INTERIOR:
            continue
        try:
            _gresp = table.query(
                KeyConditionExpression=(
                    _GapKey("pk").eq(f"USER#matthew#SOURCE#{_src}") & _GapKey("sk").between(f"DATE#{_gap_start}", f"DATE#{_gap_end}~")
                ),
                ProjectionExpression="sk",
            )
            _present = []
            for _it in _gresp.get("Items", []):
                _sk = _it.get("sk", "")
                if _sk.startswith("DATE#"):
                    _present.append(_sk.split("DATE#", 1)[1][:10])
            _gaps = find_interior_gaps(_present, _gap_start, _gap_end)
            if _gaps:
                interior_gaps[_src] = _gaps
        except Exception as _e:  # noqa: BLE001
            logger.warning("interior-gap scan failed for %s: %s", _src, _e)
    interior_gap_count = sum(len(v) for v in interior_gaps.values())

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        # #2662: name the set the verdict covers. `status: green` over an unstated subset
        # is the shape that made the dropped-name bug invisible — the answer looked total.
        "evaluated_sources": keys,
        "stale_count": stale_count,
        "unreadable_count": unreadable_count,
        "fresh_count": len(fresh_sources),
        "stale_sources": stale_sources,
        "fresh_sources": fresh_sources,
        "interior_gaps": interior_gaps,
        "interior_gap_count": interior_gap_count,
        "macrofactor_format_drift": macro_drift,
        "training_notes_health": training_notes_health,
        "thresholds_note": (
            f"Default threshold {DEFAULT_STALE_HOURS}h. "
            f"food_delivery={SOURCE_STALE_HOURS['food_delivery']//24}d, "
            f"measurements={SOURCE_STALE_HOURS['measurements']//24}d. "
            "Mirrors freshness_checker_lambda.py."
        ),
        "context": (
            "Status tiers: green (all fresh) / yellow (1 stale <7d) / orange (mixed) / red (3+ stale OR any >14d). "
            "stale_count counts every source not confirmed fresh — stale, no_data and unreadable alike; "
            "unreadable_count is the subset we could not read at all, and is never reported as green."
        ),
    }
