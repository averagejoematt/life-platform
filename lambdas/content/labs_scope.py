"""labs_scope.py — the denominator `/api/labs` serves beside its counts (#3728).

`write_clinical_json` served `total_draws: 8` with no scope on it. That number is a
LIFETIME count — labs is CROSS_PHASE, so `include_pilot=True` and no restart ever trims
it — and it was rendered next to a coach narrating its own, much shorter window, with
neither surface naming one. What a reader saw was "8" beside "I have zero lab draws to
interpret yet", and one of those had to be lying.

Neither was. The coach's window was `build_data_inventory`'s rolling 90 days (fixed at
source in `intelligence/inventory_window.py`); `/api/labs` had no window at all. The
missing thing on this side is not a number, it is the frame around the number — the
precedent class `web/site_api_phase_frame.py` was built for (#2957), whose docstring
names it: *"the numbers were true, the frame was missing."*

Lives beside `output_writers` rather than inside it because that module is FULL at its
#1665 ceiling, and because "what window is this labs count over" is a cohesive question
with a cohesive answer — including the part no shared helper could supply: the in-cycle
companion count. `cycle_read_floor` is a deliberate NO-OP for a CROSS_PHASE partition,
so there is no taxonomy read that produces it; it is an explicit date comparison against
`EXPERIMENT_START_DATE` and has to stay one.
"""

import logging
from decimal import Decimal

from common.constants import EXPERIMENT_START_DATE
from common.digest_utils import d2f as _d2f  # shared bundled helper (#970/#2816), same import output_writers uses
from web.site_api_phase_frame import archival_frame, lifetime_scope  # #2957 — the shared framing vocabulary

logger = logging.getLogger(__name__)


def count_draws_this_cycle(table, pk: str, with_phase_filter) -> int:
    """Draws keyed on or after the live genesis. `with_phase_filter` is passed in so
    this module holds no ADR-058 opinion of its own — the caller's `include_pilot`
    decision is the one that applies."""
    resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
                "ExpressionAttributeValues": {
                    ":pk": pk,
                    ":lo": "DATE#" + EXPERIMENT_START_DATE,
                    ":hi": "DATE#9999-12-31",
                },
                "Select": "COUNT",
            },
            include_pilot=True,
        )
    )
    return resp.get("Count", 0)


def scope_fields(latest_draw_date, cycle_draws: int) -> dict:
    """The additive scope block. Existing keys keep their meaning and shape — a reader
    (or a stored artifact) that predates this sees exactly what it saw before."""
    return {
        "total_draws_scope": lifetime_scope(),
        "draws_this_cycle": cycle_draws,
        "cycle_genesis": EXPERIMENT_START_DATE,
        "latest_draw_archival": archival_frame(latest_draw_date, EXPERIMENT_START_DATE),
    }


def build_labs_block(table, pk: str) -> dict:
    """The whole `/api/labs` `labs` object: the newest draw's biomarkers, the counts,
    and the window those counts are taken over.

    Moved here whole from `output_writers.write_clinical_json` (#3728). It was the
    largest thing in that function, it is cohesive on its own, and that module is FULL
    at its #1665 ceiling — so the scope fields this issue adds are paid for out of what
    came with them rather than out of a raised number.

    Fail-soft exactly as before: any read or shape problem yields `{}` and the endpoint
    serves no labs object, which is what every consumer already handles.
    """
    labs: dict = {}
    try:
        from experiment.phase_filter import with_phase_filter

        # ADR-058 include_pilot=True: clinical archive — labs/DEXA are date-independent
        # (owner decision 2026-06-06; filtering would empty the public labs page)
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk)",
                    "ExpressionAttributeValues": {":pk": pk, ":sk": "DATE#"},
                    "ScanIndexForward": False,
                    "Limit": 1,
                },
                include_pilot=True,
            )
        )
        all_draws = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk)",
                    "ExpressionAttributeValues": {":pk": pk, ":sk": "DATE#"},
                    "Select": "COUNT",
                },
                include_pilot=True,
            )
        )
        total_draws = all_draws.get("Count", 0)
        # #3728: the in-cycle companion to the lifetime count above.
        cycle_draws = count_draws_this_cycle(table, pk, with_phase_filter)

        if resp.get("Items"):
            lab_rec = resp["Items"][0]
            biomarkers_raw = lab_rec.get("biomarkers", {})
            out_of_range = lab_rec.get("out_of_range", [])

            cat_order = [
                "lipids",
                "lipids_advanced",
                "cardiovascular",
                "metabolic",
                "cbc",
                "cbc_differential",
                "liver",
                "kidney",
                "thyroid",
                "hormones",
                "inflammation",
                "iron",
                "vitamins",
                "minerals",
                "electrolytes",
                "immune",
                "omega_fatty_acids",
                "prostate",
                "toxicology",
                "genetics",
                "blood_type",
                "digestive",
            ]
            cat_names = {
                "lipids": "Lipids",
                "lipids_advanced": "Advanced Lipids",
                "cardiovascular": "Cardiovascular",
                "metabolic": "Metabolic",
                "cbc": "Complete Blood Count",
                "cbc_differential": "CBC Differential",
                "liver": "Liver",
                "kidney": "Kidney",
                "thyroid": "Thyroid",
                "hormones": "Hormones",
                "inflammation": "Inflammation",
                "iron": "Iron Studies",
                "vitamins": "Vitamins",
                "minerals": "Minerals",
                "electrolytes": "Electrolytes",
                "immune": "Immune",
                "omega_fatty_acids": "Omega Fatty Acids",
                "prostate": "Prostate",
                "toxicology": "Toxicology",
                "genetics": "Genetics",
                "blood_type": "Blood Type",
                "digestive": "Digestive",
            }

            by_cat: dict = {}
            for key, bm in biomarkers_raw.items():
                cat = bm.get("category", "other")
                if cat not in by_cat:
                    by_cat[cat] = []
                flag = bm.get("flag", "normal")
                flag_code = None
                if flag == "high":
                    flag_code = "H"
                elif flag == "low":
                    flag_code = "L"

                val = bm.get("value_numeric")
                if val is None:
                    val = bm.get("value")
                decimals = 0
                is_numeric_val = isinstance(val, (int, float, Decimal))
                if is_numeric_val:
                    if val != 0 and abs(val) < 1:
                        decimals = 2
                    elif abs(val) < 10:
                        decimals = 1

                by_cat[cat].append(
                    {
                        "name": key.replace("_", " ").title(),
                        "value": _d2f(val) if is_numeric_val else val,
                        "unit": bm.get("unit", ""),
                        "range": bm.get("ref_text", ""),
                        "flag": flag_code,
                        "decimals": decimals,
                        "category": cat_names.get(cat, cat.replace("_", " ").title()),
                    }
                )

            biomarker_list = []
            for cat in cat_order:
                if cat in by_cat:
                    biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))
            for cat in sorted(by_cat.keys()):
                if cat not in cat_order:
                    biomarker_list.extend(sorted(by_cat[cat], key=lambda x: x["name"]))

            labs = {
                "latest_draw_date": lab_rec.get("draw_date"),
                "lab_provider": lab_rec.get("lab_provider"),
                "total_draws": total_draws,
                "biomarkers": biomarker_list,
                "flagged_count": len(out_of_range),
                **scope_fields(lab_rec.get("draw_date"), cycle_draws),  # #3728
            }
    except Exception as e:
        # Carried from output_writers, but converted: a NEW lambda file uses
        # platform_logger, not print (tests/test_logger_discipline.py). Same fail-soft
        # semantics — the endpoint serves no labs object and every consumer already
        # handles that.
        logger.warning("Clinical: labs query failed: %s", e)
    return labs
