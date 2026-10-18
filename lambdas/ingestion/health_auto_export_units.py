"""Day-field unit normalisation and derived totals for the HAE webhook — a cohesive sibling.

Moved out of `health_auto_export_lambda.py` by #4970 (the #1665 size guard: that module is
FULL). The webhook keeps its names bound (`_water_ml_factor`, `_derive_day_fields`), so
every caller and test is unchanged. Contents: the reported-unit water factor (#483/D-9),
and the per-day pass that derives `total_calories_burned`, converts water to mL, weight to
lbs, distances to miles and the watch's wrist temperature to Celsius (#4970).
"""

import logging

from ingestion.health_auto_export_additive import to_miles
from ingestion.health_auto_export_watch import wrist_temp_to_celsius

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)


def water_ml_factor(units):
    """mL per reported water unit (#483/D-9). Historical payloads report fl-oz, which the
    old code hard-assumed; honor mL/L when tagged so a mL-reporting app isn't ×29.5735'd."""
    u = (units or "").lower().replace(" ", "").replace("_", "")
    if u in ("ml", "milliliter", "milliliters", "millilitre", "millilitres"):
        return 1.0
    if u in ("l", "liter", "liters", "litre", "litres"):
        return 1000.0
    if u in ("floz", "flozus", "fluidounce", "fluidounces", "oz", "ounce", "ounces"):
        return 29.5735
    if u:
        logger.warning(f"[HAE] unexpected water units {units!r}; assuming fl-oz")
    return 29.5735  # historical default


def derive_day_fields(daily_data, daily_timestamps, field_units):
    # Derived fields + unit normalisation per day, in place (#4970: out of process_generic_metrics, the #4880 guard).
    for date, fields in daily_data.items():
        ac = fields.get("active_calories")
        bc = fields.get("basal_calories")
        if ac is not None and bc is not None:
            fields["total_calories_burned"] = round(ac + bc, 2)

        # Water → mL, honoring the reported unit rather than assuming fl-oz (#483/D-9).
        # oz is derived from ml after dedup, not tracked independently.
        water_raw = fields.pop("water_intake_raw", None)
        if water_raw is not None:
            factor = water_ml_factor(field_units.get("water_intake_raw"))
            fields["water_intake_ml"] = round(water_raw * factor)
            # Carry dedup timestamps from water_intake_raw → water_intake_ml
            if date in daily_timestamps and "water_intake_raw" in daily_timestamps[date]:
                raw_ts = daily_timestamps[date].pop("water_intake_raw")
                daily_timestamps[date]["water_intake_ml"] = {ts: round(qty * factor) for ts, qty in raw_ts.items()}

        # Weight is stored as lbs (HAE is a Withings fallback). Convert kg if so tagged (#483/D-9).
        w = fields.get("weight_lbs")
        if w is not None:
            wu = (field_units.get("weight_lbs") or "").lower().strip()
            if wu in ("kg", "kilogram", "kilograms"):
                fields["weight_lbs"] = round(w * 2.20462, 2)
            elif wu and wu not in ("lb", "lbs", "pound", "pounds"):
                logger.warning(f"[HAE] unexpected weight units {wu!r} for {date}; assuming lbs")

        # #4970: wrist temperature is stored in Celsius; HAE reports the phone's unit.
        wrist_temp_to_celsius(fields, daily_timestamps.get(date), field_units.get("wrist_temp_sleep_c_apple"), date)

        # Distances are stored as miles. Convert km/m if so tagged; warn on anything else (#483/D-9).
        for dfield in [f for f in fields if f.endswith("_miles")]:
            if fields.get(dfield) is not None:
                fields[dfield] = to_miles(fields[dfield], field_units.get(dfield))
