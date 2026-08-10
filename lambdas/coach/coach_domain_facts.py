"""coach_domain_facts.py — per-coach domain fact packs for the chat surface (Wave 2.0).

The canonical facts record answers "how is Matthew today" (recovery, HRV, weight
trend, protein). It does NOT answer the first question each specialist actually
gets asked — the nutrition coach didn't know the calorie target, which is the
screenshot that opened this epic. This module adds a SMALL per-domain extension,
derived from rows that already exist, rendered as its own labeled block.

The honesty contract, in order of importance:

* **Nutrition reuses the site's exact assembly** (ADR-152/#2310): MacroFactor's
  adaptive expenditure primary when a windowed record carries one (the same
  ``_resolve_mf_tdee`` the site calls), else ``health.tdee.energy_budget`` from
  profile height/DOB + the latest Withings weigh-in + measured trailing-7d Strava
  exercise energy. The phone and the site cannot tell two truths, and every
  figure carries its source label.
* Absence stays absent: a pack that cannot be computed contributes NOTHING —
  never a default, never an assumed height (ADR-104). The renderer says what is
  missing out loud so the coach can too.
* The rendered block joins the grounder's ``extra_sources``, so a coach citing
  its own domain numbers is never flagged as fabricating them — while the night
  map stays canonical-facts-only (#2343's day-correspondence class unweakened).

Fail-soft everywhere: any storage/import surprise returns "" and the chat runs
on canonical facts alone, exactly as it did before this module existed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

_USER_PK = "USER#matthew#SOURCE#{source}"


def _num(v) -> Optional[float]:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _query_source(table, source: str, start: str, end: str) -> list:
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
        ExpressionAttributeValues={
            ":pk": _USER_PK.format(source=source),
            ":lo": f"DATE#{start}",
            ":hi": f"DATE#{end}~",
        },
    )
    return resp.get("Items") or []


def _latest(items: list) -> dict:
    return sorted(items, key=lambda i: str(i.get("sk", "")))[-1] if items else {}


# ── Nutrition: the ADR-152 energy budget, site-parity ────────────────────────


def _nutrition_pack(table, today: str) -> list:
    d30 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
    d7 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    lines: list = []

    mf = _query_source(table, "macrofactor", d30, today)
    tdee, source = None, None
    try:
        from web.site_api_nutrition import _resolve_mf_tdee

        tdee, source = _resolve_mf_tdee(mf)
    except Exception as e:  # pragma: no cover — bundle edge; Mifflin path below still runs
        logger.warning("[domain_facts] site tdee resolver unavailable: %s", e)

    budget = None
    if tdee is None:
        try:
            from health import tdee as health_tdee

            profile = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"}).get("Item") or {}
            wt_items = _query_source(
                table, "withings", (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=13)).strftime("%Y-%m-%d"), today
            )
            weight_lbs = _num(_latest(wt_items).get("weight_lbs"))
            height_in = _num(profile.get("height_inches"))
            if weight_lbs and height_in:
                age_years, age_basis, _ = health_tdee.resolve_age(profile.get("date_of_birth"))
                strava = _query_source(table, "strava", d7, today)
                ex = health_tdee.exercise_energy(strava, weight_lbs * health_tdee.LB_TO_KG)
                budget = health_tdee.energy_budget(
                    weight_lbs=weight_lbs,
                    height_inches=height_in,
                    age_years=age_years,
                    age_basis=age_basis,
                    sex=(profile.get("biological_sex") or "male"),
                    exercise_kcal=ex["kcal"],
                    exercise_energy_days=ex["days"],
                    exercise_energy_basis=ex["basis"],
                )
            if budget:
                tdee, source = budget["tdee"], "estimate_mifflin"
        except Exception as e:
            logger.warning("[domain_facts] energy budget fallback failed: %s", e)

    if tdee:
        from health.tdee import DEFAULT_DEFICIT_KCAL

        target = round(tdee - DEFAULT_DEFICIT_KCAL)
        label = (
            "MacroFactor adaptive expenditure (measured)"
            if source == "macrofactor_adaptive"
            else "Mifflin-St Jeor + measured 7d exercise energy (estimate)"
        )
        lines.append(f"TDEE (maintenance): {round(tdee)} kcal — source: {label}.")
        lines.append(
            f"ADR-152 calorie target: {target} kcal (TDEE minus the {DEFAULT_DEFICIT_KCAL} kcal deficit — the deficit lives in the target, never in TDEE)."
        )
    else:
        lines.append(
            "Calorie target: not computable right now (needs a recent weigh-in + profile height, or a MacroFactor expenditure record). Say so if asked."
        )

    logged = [i for i in mf if _num(i.get("calories") or i.get("total_calories_kcal")) is not None]
    if logged:
        recent = _latest(logged)
        lines.append(
            f"Most recent food log: {str(recent.get('sk', ''))[len('DATE#'):]} ({round(_num(recent.get('calories') or recent.get('total_calories_kcal')))} kcal)."
        )
    else:
        lines.append("No food logs in the last 30 days — nutrition adherence data is absent, not zero.")
    return lines


# ── Sleep: last night + the trend ────────────────────────────────────────────


def _sleep_pack(table, today: str) -> list:
    d8 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = _query_source(table, "whoop", d8, today)
    raw = [(str(i.get("sk", ""))[len("DATE#") :], _num(i.get("sleep_duration_hours"))) for i in rows]
    durations: list[tuple[str, float]] = [(d, float(v)) for d, v in raw if v]
    if not durations:
        return ["No Whoop sleep records in the last 8 days — duration data is absent. Say so rather than estimating."]
    last_date, last_v = durations[-1]
    lines = [f"Sleep duration, night ending {last_date}: {round(last_v, 1)} h."]
    if len(durations) >= 3:
        avg = sum(v for _, v in durations) / len(durations)
        lines.append(f"Average over the last {len(durations)} recorded nights: {round(avg, 1)} h.")
    return lines


# ── Performance: recovery trend + the last real session ──────────────────────


def _physical_pack(table, today: str) -> list:
    d7 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    lines: list = []
    rec = [_num(i.get("recovery_score")) for i in _query_source(table, "whoop", d7, today)]
    rec = [r for r in rec if r is not None]
    if len(rec) >= 3:
        lines.append(f"Whoop recovery, 7-day average: {round(sum(rec) / len(rec))}% over {len(rec)} recorded days.")
    d14 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=13)).strftime("%Y-%m-%d")
    workouts = _query_source(table, "hevy", d14, today)
    if workouts:
        last = _latest(workouts)
        when = str(last.get("sk", ""))[len("DATE#") :].split("#")[0]
        name = str(last.get("title") or last.get("workout_name") or "").strip()
        lines.append(f"Last logged lift: {when}" + (f" ({name})." if name else "."))
    else:
        lines.append("No logged lifts in the last 14 days — absence of logs, not proof of rest days.")
    return lines


_PACKS = {
    "nutrition": _nutrition_pack,
    "sleep": _sleep_pack,
    "physical": _physical_pack,
    "training": _physical_pack,  # merged Performance seat serves both routes
}


def domain_facts_block(coach_id: str, table, today: Optional[str] = None) -> str:
    """The coach's domain extension block, or "" (fail-soft, absence-honest)."""
    key = (coach_id or "").strip().lower()
    key = key[: -len("_coach")] if key.endswith("_coach") else key
    pack = _PACKS.get(key)
    if pack is None:
        return ""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        lines = pack(table, today)
    except Exception as e:
        logger.warning("[domain_facts] %s pack failed (chat runs on canonical facts): %s", key, e)
        return ""
    if not lines:
        return ""
    return "YOUR DOMAIN FACTS (yours specifically, same sources as the site):\n" + "\n".join(f"- {ln}" for ln in lines)
