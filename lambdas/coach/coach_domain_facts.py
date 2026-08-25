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

Cycle-13 addition — **experiment awareness** (Act 1a). Every texting coach also
gets an EXPERIMENT FRAME: what day of which cycle it is, and — for the coaches
that actually make forecasts — their OWN still-open preregistered calls. The
head coach additionally gets the week's one priority from his team's integrator.
The same honesty contract applies: pre-genesis renders a countdown, never a fake
Day 1; the prereg rows are READ-ONLY here; a tombstoned integrator record from a
wiped cycle contributes nothing (``singleton_visible``, #946/#1969).

#2496 adds the two sections that make a coach sound like a colleague rather than a
service: its own GRADED calls (misses guaranteed a slot — see
``coach_team_texture.terminal_prediction_lines``) and the TEAM ROOM, the inter-coach
threads it was actually a party to. Both are grounded reads of existing rows, and
the team-room section renders even when EMPTY, because its heading is the evidence
``coach_team_texture.team_meeting_findings`` gates against.

Fail-soft everywhere: any storage/import surprise returns "" and the chat runs
on canonical facts alone, exactly as it did before this module existed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

from coach import coach_team_texture

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


# ── The experiment frame: what day of which cycle this is ────────────────────


def _week_number(day: int) -> int:
    """The experiment week for a 1-indexed Day-N.

    This mirrors ``ai_expert_analyzer_lambda`` VERBATIM (``max(1, days_in // 7 + 1)``,
    the expression that stamps ``week_number`` on the EXPERT#integrator record). It is
    deliberately NOT the Monday-anchored week the field-notes surface computes — the two
    disagree at week boundaries, and a coach who may cite the integrator's row has to
    name the same week that row names. Day 1–6 → week 1, Day 7–13 → week 2.
    """
    return max(1, day // 7 + 1)


def _current_cycle() -> Optional[int]:
    """The living cycle number, from the explicit CYCLE_GENESES ledger.

    Imported late so tests can patch it (the ``site_api_diary``/``site_api_fingerprint``
    idiom), and fail-soft: an unreadable ledger costs the cycle number, not the day.
    """
    try:
        from web.site_api_data import CYCLE_GENESES

        return max(CYCLE_GENESES) if CYCLE_GENESES else None
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[domain_facts] cycle ledger unavailable: %s", e)
        return None


def _experiment_frame_lines(today_iso: str) -> list:
    """ "Day N of cycle C (week W)" — or, before genesis, an honest countdown.

    ``day_n`` returns 0 for a pre-genesis date, and cycle 13's genesis was itself set
    in the future (#931/#939). Rendering "Day 1" during that window would be the exact
    fabrication class this platform exists to avoid, so the pre-start branch names the
    start date instead and claims no day at all.
    """
    from common.constants import EXPERIMENT_START_DATE, day_n

    day = day_n(today_iso)
    cycle = _current_cycle()
    subject = f"cycle {cycle}" if cycle is not None else "the current cycle"
    if day <= 0:
        return [f"Experiment: {subject} starts {EXPERIMENT_START_DATE} — pre-genesis, there is no Day 1 yet."]
    cycle_txt = f" of cycle {cycle}" if cycle is not None else ""
    return [f"Experiment: Day {day}{cycle_txt} (week {_week_number(day)})."]


# ── Today's conditions: the sky he is actually standing under ────────────────

WEATHER_SOURCE = "weather"


def _weather_lines(table, today: str) -> list:
    """Seattle's measured conditions for ``today`` — or nothing at all (#2493).

    Why this is a grounding change more than a texture change: a coach that says
    "nice break in the rain today" is either quoting a record or inventing one, and
    until now the coach package contained the word "weather" zero times, so there was
    no record to quote. Every figure below is read off the ``SOURCE#weather``
    ``DATE#`` row and rendered into the block the worker already feeds to
    ``build_grounder``'s ``extra_sources`` — which is what keeps a TRUE, sourced
    weather sentence from tripping the gate (#2517's exact failure mode: evidence the
    model has but the gate does not, read as fabrication).

    It is emphatically NOT a grounding bypass. Only the numbers ON the row enter the
    allow-list, so an invented temperature still fails ``fabricated_number``, and the
    night map stays canonical-facts-only (#2343) — this widens vocabulary, never
    vitals.

    Absence is absence (ADR-104): no row for ``today`` ⇒ no weather line at all. Never
    a seasonal default, never a guess, and never yesterday's sky relabelled as today's
    — which is why the window is the single day and the row is matched on its exact
    ``DATE#`` key rather than "the latest one we have".
    """
    rows = [i for i in _query_source(table, WEATHER_SOURCE, today, today) if str(i.get("sk", "")) == f"DATE#{today}"]
    row = rows[0] if rows else {}
    if not row:
        return []

    condition = " ".join(str(row.get("condition") or "").split())
    hi, lo = _num(row.get("temp_high_f")), _num(row.get("temp_low_f"))
    head: list = []
    if condition:
        head.append(condition)
    if hi is not None:
        head.append(f"high {round(hi)}F" + (f", low {round(lo)}F" if lo is not None else ""))
    elif lo is not None:
        head.append(f"low {round(lo)}F")
    if not head:
        return []
    lines = [f"Weather in Seattle today ({today}): " + ", ".join(head) + "."]

    detail: list = []
    precip = _num(row.get("precipitation_mm"))
    if precip is not None:
        # "0 mm" is a measurement, not an absence — say the measured zero.
        detail.append("no measurable precipitation" if precip == 0 else f"{round(precip, 1)} mm precipitation")
    humidity = _num(row.get("humidity_pct"))
    if humidity is not None:
        detail.append(f"humidity {round(humidity)}%")
    wind = _num(row.get("wind_speed_max_mph"))
    if wind is not None:
        detail.append(f"wind up to {round(wind)} mph")
    aqi = _num(row.get("aqi"))
    if aqi is not None:
        detail.append(f"AQI {round(aqi)}")
    if detail:
        lines.append("Also measured: " + ", ".join(detail) + ".")

    sunrise, sunset = str(row.get("sunrise_local") or "").strip(), str(row.get("sunset_local") or "").strip()
    daylight = _num(row.get("daylight_hours"))
    if sunrise and sunset:
        lines.append(f"Sunrise {sunrise}, sunset {sunset}" + (f" — {round(daylight, 1)} h of daylight." if daylight else "."))
    return lines


WEATHER_SECTION_HEADING = "TODAY'S CONDITIONS (Seattle, measured — these figures only, and only when they bear on what he asked)"


def _weather_section(lines: list) -> str:
    """The rendered conditions section, or "" when there is no row.

    Unlike the team room (#2496), absence here renders NOTHING rather than an
    "absent" heading. A heading is evidence, and a coach told "no weather record
    today" has been handed a fact about the pipeline it has no reason to text about;
    a coach told nothing simply has no weather in its vocabulary, which is the
    ADR-104 outcome this issue asks for.
    """
    return (WEATHER_SECTION_HEADING + ":\n" + "\n".join(f"- {ln}" for ln in lines)) if lines else ""


# ── The coach's own open preregistered calls ─────────────────────────────────

MAX_OWN_PREDICTIONS = 3
_OPEN_PREDICTION_STATUSES = ("pending", "confirming")
_MAX_PREDICTION_PAGES = 5  # a chat turn is latency-bound; the partition is small


def _fetch_own_predictions(coach_id: str, table) -> list:
    """Every visible PREDICTION# row in this coach's partition.

    Read-only: this surface never writes a prediction, never grades one, and never
    touches the frozen genesis prereg artifact. ``with_phase_filter`` is mandatory
    (ADR-058) — without it a reset's pilot-tagged calls keep being quoted as live.

    ONE fetch serves both the open calls and the graded ones (#2496). Splitting it
    into a query per renderer would double the round-trips on the platform's most
    latency-sensitive surface to read the same small partition twice.
    """
    from experiment.phase_filter import with_phase_filter

    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": f"COACH#{coach_id}", ":prefix": "PREDICTION#"},
    }
    items: list = []
    for _page in range(_MAX_PREDICTION_PAGES):
        resp = table.query(**with_phase_filter(kwargs))
        items.extend(resp.get("Items") or [])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _open_predictions_lines(items: list) -> list:
    """The coach's still-open PREDICTION# claims — at most three, newest first."""
    open_calls = [
        i
        for i in items
        if str(i.get("status") or "").strip().lower() in _OPEN_PREDICTION_STATUSES and str(i.get("claim_natural") or "").strip()
    ]
    open_calls.sort(key=lambda i: (str(i.get("created_date") or ""), str(i.get("sk") or "")), reverse=True)

    lines = []
    for rec in open_calls[:MAX_OWN_PREDICTIONS]:
        claim = " ".join(str(rec.get("claim_natural")).split())
        conf = _num(rec.get("confidence"))
        made = str(rec.get("created_date") or "").strip()
        detail = ", ".join(p for p in ((f"confidence {conf:g}" if conf is not None else ""), (f"made {made}" if made else "")) if p)
        lines.append(f'Your open call: "{claim}"' + (f" ({detail})." if detail else "."))
    return lines


# ── The head coach's week: the integrator's one priority ─────────────────────


MAX_PRIORITY_CHARS = 600


def _weekly_priority_lines(table) -> list:
    """The integrator's current cross-coach read — the head coach's week in one line.

    Guarded with ``singleton_visible``: the intelligence wipe tombstones every
    ai_analysis record in place, and a get_item bypasses the query-level phase filter,
    so an unguarded read narrates the WIPED cycle as this week's priority (#946/#1969).
    """
    from experiment.phase_filter import singleton_visible

    item = table.get_item(Key={"pk": _USER_PK.format(source="ai_analysis"), "sk": "EXPERT#integrator"}).get("Item")
    if not singleton_visible(item):
        return []
    analysis = " ".join(str(item.get("analysis") or "").split())
    if not analysis:
        return []
    if len(analysis) > MAX_PRIORITY_CHARS:
        analysis = analysis[:MAX_PRIORITY_CHARS].rstrip() + "…"
    week = _num(item.get("week_number"))
    label = "your team's integrator" + (f", week {int(week)}" if week else "")
    return [f"This week's one priority ({label}): {analysis}"]


def _lead_pack(table, today: str) -> list:  # noqa: ARG001 — pack signature
    """Eli Marsh (Principal Investigator): the week's one priority, nothing else."""
    return _weekly_priority_lines(table)


_PACKS = {
    "nutrition": _nutrition_pack,
    "sleep": _sleep_pack,
    "physical": _physical_pack,
    "training": _physical_pack,  # merged Performance seat serves both routes
    "eli_marsh": _lead_pack,  # chat-tier lead — pack key == persona id (no _coach suffix)
}


def _persona_id(coach_id: str) -> tuple:
    """(pack key, canonical persona id) for a route id, a short id, or a persona id."""
    raw = (coach_id or "").strip().lower()
    key = raw[: -len("_coach")] if raw.endswith("_coach") else raw
    try:
        from coach.persona_registry import OPERATIONAL_COACH_IDS

        operational = list(OPERATIONAL_COACH_IDS)
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[domain_facts] persona registry unavailable: %s", e)
        operational = []
    return key, (f"{key}_coach" if f"{key}_coach" in operational else raw)


def domain_facts_block(coach_id: str, table, today: Optional[str] = None) -> str:
    """The coach's experiment frame + domain extension, or "" (fail-soft, absence-honest).

    ``today`` must be the PACIFIC date — every other surface on this platform names the
    Pacific day, and a UTC date would put the coach a day ahead of the site after 5pm PT.
    """
    key, persona = _persona_id(coach_id)
    today = today or pacific_today()

    frame: list = []
    try:
        frame += _experiment_frame_lines(today)
    except Exception as e:
        logger.warning("[domain_facts] experiment frame failed: %s", e)

    # Weather is EVERY coach's texture, not one seat's domain fact (#2493) — the
    # sleep coach cares about a 5:57 sunrise, the performance coach about heat on a
    # long run — so it renders alongside the frame rather than inside a pack. Storage
    # trouble costs the section, never the block.
    weather: list = []
    try:
        weather = _weather_lines(table, today)
    except Exception as e:
        logger.warning("[domain_facts] weather unavailable (chat runs without it): %s", e)

    # The forecasting seats only. A chat-tier coach makes no preregistered calls and
    # is not a party to an inter-coach thread, so reading either partition for one
    # could only ever return nothing — and the absence sections below already tell
    # it, in words, that it has no record to claim.
    operational = False
    try:
        from coach.persona_registry import OPERATIONAL_COACH_IDS

        operational = persona in OPERATIONAL_COACH_IDS
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[domain_facts] persona registry unavailable: %s", e)

    track_lines: list = []
    if operational:
        try:
            predictions = _fetch_own_predictions(persona, table)
            frame += _open_predictions_lines(predictions)
            track_lines = coach_team_texture.terminal_prediction_lines(predictions)
        except Exception as e:
            logger.warning("[domain_facts] own predictions unavailable for %s: %s", persona, e)

    # The TEAM ROOM section renders for EVERY texting coach, with or without a
    # record. Its absence form is not decoration: ``team_meeting_findings`` reads
    # the heading as its evidence, and a coach told nothing about its team fills
    # the silence from the persona's general idea of what a coaching staff does.
    meeting_lines = coach_team_texture.team_meeting_lines(persona, table) if operational else []

    lines: list = []
    pack = _PACKS.get(key)
    if pack is not None:
        try:
            lines = pack(table, today)
        except Exception as e:
            logger.warning("[domain_facts] %s pack failed (chat runs on canonical facts): %s", key, e)
            lines = []

    sections = []
    if frame:
        sections.append("EXPERIMENT FRAME:\n" + "\n".join(f"- {ln}" for ln in frame))
    conditions = _weather_section(weather)
    if conditions:
        sections.append(conditions)
    track_section = coach_team_texture.track_record_section(track_lines)
    if track_section:
        sections.append(track_section)
    sections.append(coach_team_texture.team_room_section(meeting_lines))
    if lines:
        sections.append("YOUR DOMAIN FACTS (yours specifically, same sources as the site):\n" + "\n".join(f"- {ln}" for ln in lines))
    return "\n\n".join(sections)
