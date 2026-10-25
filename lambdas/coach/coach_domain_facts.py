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
  figure carries its source label. The CALORIE TARGET is not derived from that
  TDEE: it is the ONE resolver's (``health.calorie_target``, #5095).
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
from typing import Any, Optional

from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days
from common.strava_read_seam import strava_read_seam  # #4419: multi-device strava duplicates removed at the read

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
    return strava_read_seam(source, resp.get("Items") or [])


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
                # #3931: the Hevy set log is the worked-set input — the lifting term no
                # longer charges rest between sets at the cardio duration proxy.
                hevy = _query_source(table, "hevy", d7, today)
                ex = health_tdee.exercise_energy(strava, weight_lbs * health_tdee.LB_TO_KG, hevy)
                budget = health_tdee.energy_budget(
                    weight_lbs=weight_lbs,
                    height_inches=height_in,
                    age_years=age_years,
                    age_basis=age_basis,
                    sex=(profile.get("biological_sex") or "male"),
                    exercise_kcal=ex["kcal"],
                    exercise_energy_days=ex["days"],
                    exercise_energy_basis=ex["basis"],
                    lifting=ex.get("lifting"),
                )
            if budget:
                tdee, source = budget["tdee"], "estimate_mifflin"
        except Exception as e:
            logger.warning("[domain_facts] energy budget fallback failed: %s", e)

    if tdee:
        from health.tdee import METHOD as TDEE_METHOD

        label = (
            "MacroFactor adaptive expenditure (measured)"
            if source == "macrofactor_adaptive"
            else "Mifflin-St Jeor + WORKED-SET 7d exercise energy (estimate, #3931 — rest between sets is not charged)"
        )
        # #3931 box 4: the method name rides with the number, DERIVED from health.tdee so
        # a rename can never leave this surface publishing the old figure's old label.
        method_name = "macrofactor_adaptive_expenditure" if source == "macrofactor_adaptive" else TDEE_METHOD
        lines.append(f"TDEE (maintenance): {round(tdee)} kcal — source: {label}; method: {method_name}.")
    else:
        lines.append(
            "TDEE (maintenance): not computable right now (needs a recent weigh-in + profile height, or a MacroFactor expenditure record). Say so if asked."
        )
    # #5095: the calorie target is the ONE resolver's (health.calorie_target) — the same number scoring, the
    # emails, the macros tool and the critics use. It is no longer TDEE minus a flat 500 (a second target).
    from health.calorie_target import resolve as resolve_calorie_target

    ct = resolve_calorie_target(today)
    if ct["kcal"]:
        lines.append(
            f"Calorie target: {ct['kcal']} kcal/day (prescribed band {ct['band_low']}–{ct['band_high']}; "
            f"day floors {ct['floor_any_day_kcal']} any day / {ct['floor_lifting_day_kcal']} lifting day) — source: {ct['provenance']}."
        )
    else:
        lines.append("Calorie target: none resolved right now (the charter's nutrition.calories block is unreadable). Say so if asked.")

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
    return lines + _watch_lines(table, today, "sleep", rows)


def _watch_lines(table, today: str, domain: str, whoop_rows: list) -> list:
    """#4979: the Apple Watch's signals for this domain, source-labelled and dated, with Whoop beside it
    where both wrists measure the metric (`health.watch_signals`, audience OWNER_AI: this block feeds the
    owner's own thread, so INTERNAL fields may appear and no OWNER_ONLY field ever does). Fail-soft: []."""
    try:
        from health import watch_signals

        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=watch_signals.ARC_DAYS - 1)).strftime("%Y-%m-%d")
        apple = _query_source(table, watch_signals.APPLE, start, today)
        garmin = _query_source(table, "garmin", start, today) if domain == "training" else []
        return watch_signals.fact_lines(apple, whoop_rows, today, audience=watch_signals.OWNER_AI, domain=domain, garmin_rows=garmin)
    except Exception as e:  # noqa: BLE001 — the pack runs without the watch lines
        logger.warning("[domain_facts] watch signals unavailable: %s", e)
        return []


# ── Performance: recovery trend + the last real session ──────────────────────


def _physical_pack(table, today: str) -> list:
    d7 = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    lines: list = []
    whoop7 = _query_source(table, "whoop", d7, today)
    rec = [_num(i.get("recovery_score")) for i in whoop7]
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
    try:  # #4978: the owner-only illness/overload triad this seat weighs before the session (health.illness_triad)
        from health import illness_triad

        lines.extend(illness_triad.owner_lines(illness_triad.read_recent(table, today), today))
    except Exception as e:  # noqa: BLE001 — the thread runs without the triad line
        logger.warning("[domain_facts] illness triad unavailable: %s", type(e).__name__)
    return lines + _watch_lines(table, today, "training", whoop7)


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


def _labs_pack(table, today: str) -> list:  # noqa: ARG001 — pack signature
    """Adaeze Obi (labs): the real draw record, read from the SAME facts the analyzer uses.

    #3792: there was no `labs` entry in _PACKS at all, so the labs coach received NO domain
    facts and narrated its own window from persona memory. Live on 2026-09-15T17:07Z, five
    and a half months after the panel completed, it was still writing:

        "I'm coordinating a comprehensive April 3rd lab panel to establish clean baselines
         before any protein escalation ... the draw must fall at least 48 hours after"

    — present/future tense about a draw that happened on 2026-04-03. A reader lands on the
    coaching dashboard and is told a coach is *arranging* an appointment and *waiting* on
    blood that was taken in April.

    #3737 fixed the ANALYZER (`ai_expert_analyzer_lambda`) and is proven live there. It
    reached a different set of consumers: `coach_state_updater` imports none of its modules,
    so the corrected framing never arrived on this surface. This pack closes that by reading
    `intelligence.labs_facts.build_labs_fact_block` — the same builder, not a second
    derivation — so the window framing has ONE home (#3792 box 2).
    """
    lines: list = []
    try:
        from intelligence.labs_facts import build_labs_fact_block
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[domain_facts] labs facts unavailable: %s", e)
        return lines

    items = _query_source(table, "labs", "0000-00-00", "9999-99-99")
    block = build_labs_fact_block(items)

    if block.get("store_empty"):
        # The ONLY honest "no labs yet" — the builder's own words, not this module's guess.
        lines.append(str(block.get("note") or "The labs store holds zero draw records."))
        return lines

    draw_date = str(block.get("draw_date") or "")
    lines.append(
        f"Most recent draw: {draw_date} — it is COMPLETE and its results are below. "
        "Do not narrate it as upcoming, scheduled, or awaited."
    )
    if draw_date:
        try:
            age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(draw_date, "%Y-%m-%d")).days
            lines.append(f"That draw is {age} days old as of {today} — say its age rather than implying recency.")
        except ValueError:
            pass
    lines.append(f"Lifetime draws on record: {block.get('total_draws')} (labs is CROSS_PHASE — a reset never trims this).")
    flagged = block.get("flagged_markers") or []
    lines.append(f"Biomarkers on the latest draw: {block.get('total_biomarkers')}, of which {block.get('flagged_count')} out of range.")
    for marker in flagged[:6]:
        lines.append(f"Out of range: {marker}")
    if block.get("extraction_incomplete"):
        lines.append(str(block["extraction_incomplete"]))
    return lines


# ── Mind: the mood read (#5123), the last week of check-ins and the early-warning protocol it owns (#5126) ──
# The mind coach's OWN Telegram thread is an owner channel, so it reads the owner-only check-in (#5106) the way the
# character sheet's Mind pillar does (#5129: an owner-surface read, no carve-out) — ratings only, never the one
# word (#5123's rule for this thread), never on a published surface.
_CHECKIN_FIELDS = ("stress", "hunger", "cravings")
_CHECKIN_WINDOW_DAYS = 7


def _response_protocol() -> Optional[dict]:
    """#5126: the ONE early-warning owner and its protocol (`coach.response_protocol.current`), or None (fail-soft)."""
    try:
        from coach import response_protocol  # noqa: PLC0415

        return response_protocol.current()
    except Exception as e:  # noqa: BLE001 — the chat runs without the protocol line
        logger.warning("[domain_facts] response protocol unavailable: %s", type(e).__name__)
        return None


def _day_mode(table, today: str, response: Optional[dict] = None) -> Optional[dict]:
    """#5122: the whole-day disruption mode + the lapse offer (`training.life_disruption.current`), or None."""
    try:
        from training import life_disruption  # noqa: PLC0415

        return life_disruption.current(table, today, response=response if response is not None else _response_protocol())
    except Exception as e:  # noqa: BLE001 — the chat runs without the day-mode section
        logger.warning("[domain_facts] day mode unavailable: %s", type(e).__name__)
        return None


def life_disruption_lines(dm: Optional[dict], persona: Optional[str]) -> list:
    """`training.life_disruption.owner_lines` for one coach's thread ([] when the day is off or the read failed)."""
    if not dm:
        return []
    from training import life_disruption  # noqa: PLC0415

    return life_disruption.owner_lines(dm, persona)


def _checkin_lines(table, today: str) -> list:
    """The last seven evenings of the check-in (0-4 each): answered count, each rating's mean, the latest evening's
    ratings. The 21-day mood read (#5123) carries the trend; this is the recent week the early-warning protocol acts on."""
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=_CHECKIN_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
    rows = [r for r in _query_source(table, "evening_checkin", start, today) if any(_num(r.get(f)) is not None for f in _CHECKIN_FIELDS)]
    if not rows:
        return [f"Evening check-in: no answered evening in the last {_CHECKIN_WINDOW_DAYS} days — absent. Say so; never infer a rating."]
    lines = [f"Evening check-in (owner-only, 0-4 each): {len(rows)} of the last {_CHECKIN_WINDOW_DAYS} evenings answered."]
    for f in _CHECKIN_FIELDS:
        vals = [v for v in (_num(r.get(f)) for r in rows) if v is not None]
        if vals:
            lines.append(f"{f} mean {round(sum(vals) / len(vals), 1)} over {len(vals)} evening(s).")
    last = _latest(rows)
    rated = ", ".join(f"{f} {int(_num(last.get(f)))}" for f in _CHECKIN_FIELDS if _num(last.get(f)) is not None)
    lines.append(f"Latest evening {str(last.get('sk', ''))[len('DATE#'):]}: {rated}.")  # never the word (#5123)
    return lines


def _lead_pack(table, today: str) -> list:  # noqa: ARG001 — pack signature
    """Eli Marsh (Principal Investigator): the week's one priority, nothing else."""
    return _weekly_priority_lines(table)


def _mind_pack(table, today: str) -> list:
    """The mind coach (owner's Telegram thread only): THE mood read, journal first, the evening check-in behind it.

    #5123: the journal is mostly dark, so the mind thread had no read of how he feels. ``health.mood_read`` names its
    source (journal | evening_checkin | unavailable) and never supplies a default number. The check-in is owner-only
    (DATA_GOVERNANCE: no public projection), which is why it renders HERE — his own chat — and never in the
    orchestrator's published brief. Lines carry trends, means and counts; never the check-in's word, never journal text.

    #5126: Nathan Reeves (mind_coach) also owns the early-warning response, so the thread carries the last seven
    evenings (the recent week the protocol acts on, beside the 21-day read) and the protocol line.
    """
    from health import mood_read

    lines = mood_read.owner_lines(mood_read.owner_read(table, today))
    try:
        lines.extend(_checkin_lines(table, today))
    except Exception as e:  # noqa: BLE001 — the thread runs on the mood read alone
        logger.warning("[domain_facts] recent check-in unavailable: %s", type(e).__name__)
    try:  # #5121: the owner-only flag this coach answers (health.early_warning), beside the protocol it runs
        from health import early_warning

        lines.extend(early_warning.owner_lines(early_warning.read_recent(table, today), today))
    except Exception as e:  # noqa: BLE001 — the thread runs without the flag line
        logger.warning("[domain_facts] early-warning flag unavailable: %s", type(e).__name__)
    rp = _response_protocol()
    if rp and rp.get("owner"):
        lines.append(f"Early-warning response: {rp['line']}")
    return lines


_PACKS = {
    "mind": _mind_pack,  # #5123 the mood read + #5126 the recent check-in week and the early-warning protocol
    "nutrition": _nutrition_pack,
    "sleep": _sleep_pack,
    "physical": _physical_pack,
    "training": _physical_pack,  # merged Performance seat serves both routes
    "labs": _labs_pack,  # #3792 — was ABSENT, so the labs coach had no facts at all
    "eli_marsh": _lead_pack,  # chat-tier lead — pack key == persona id (no _coach suffix)
}


# The Performance seat's route keys: its thread reads the ONE planning context (#5071) — the charter, the
# panel synthesis, the clinical guidance as reference context and the May frame — instead of the bare clinical block.
_TRAINING_ROUTE_KEYS = frozenset({"physical", "training"})


def _training_context(today: str, clinical: str, table: Any = None) -> str:
    """`training.coach_context.assemble` for the owner's Telegram thread (published=False), the clinical block passed
    in as its guidance section and (#5200) the newest completed May-tracker week read from `table`. Fail-soft: on any
    trouble the bare clinical block, as before."""
    try:
        from training import coach_context, may_tracker

        tracker = may_tracker.latest_completed_row(table, today) if table is not None else None
        labs = _owner_labs(table, today)
        return coach_context.assemble(
            today,
            packet=None,
            constraint_block=None,
            tracker=tracker,
            guidance=clinical,
            lab_priorities=labs.get("priorities"),
            lab_followup=labs.get("followup"),
            published=False,
            response_protocol=_response_protocol(),
            day_mode=_day_mode(table, today),
        )["text"]
    except Exception as e:  # noqa: BLE001 — the chat runs on the clinical block alone
        logger.warning("[domain_facts] coach context unavailable: %s", e)
        return clinical


def _owner_labs(table: Any, today: str) -> dict:
    """#5111: the owner's lab-driven priorities and the next follow-up draw (`training.lab_priorities.read`) for an
    owner Telegram thread. Dates, a state and his own priority lines; never a result. Fail-soft: {} on any trouble."""
    if table is None:
        return {}
    try:
        from training import lab_priorities

        return lab_priorities.read(table, today)
    except Exception as e:  # noqa: BLE001 — the chat runs without the lab lines
        logger.warning("[domain_facts] lab follow-up unavailable: %s", type(e).__name__)
        return {}


def _nutrition_context(today: str, table: Any = None) -> str:
    """#5109: `training.coach_context.nutrition_context` for the owner's nutrition thread (published=False): the
    charter's nutrition block, the redlines' rules and the ONE calorie target with its provenance. The day grade is
    the brief's (this thread reads no single day row). #5111: plus the lab-driven priorities and the next follow-up
    draw (owner channel). Fail-soft: "" on any trouble."""
    try:
        from training import coach_context

        labs = _owner_labs(table, today)
        return coach_context.nutrition_context(
            today, published=False, lab_priorities=labs.get("priorities"), lab_followup=labs.get("followup")
        )["text"]
    except Exception as e:  # noqa: BLE001 — the chat runs on its domain facts alone
        logger.warning("[domain_facts] nutrition context unavailable: %s", e)
        return ""


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
    # ADR-155 amendment (2026-10-12): the owner clinical record is every coach's
    # constraint, like weather is every coach's texture. This block feeds ONLY the owner's
    # own Telegram thread (and rides `a["domain"]` into its grounder's vocabulary), so it
    # renders in owner-channel form. Fail-soft inside the renderer: "" on any trouble.
    clinical = ""
    try:
        from health.clinical_facts import clinical_context_block

        clinical = clinical_context_block(table, published=False)
    except Exception as e:  # pragma: no cover — bundle edge; the renderer is itself fail-soft
        logger.warning("[domain_facts] clinical context unavailable: %s", e)
    if key in _TRAINING_ROUTE_KEYS:
        clinical = _training_context(today, clinical, table)  # #5071: the one planning context, the clinical block inside it
    elif key == "nutrition":
        clinical = "\n\n".join(x for x in (clinical, _nutrition_context(today, table)) if x)  # #5109: the same assembly
    if key not in _TRAINING_ROUTE_KEYS:  # #5122: the whole-day mode + the lapse offer (routed to the response owner)
        dm_lines = life_disruption_lines(_day_mode(table, today), persona)  # the training route reads it in its context
        if dm_lines:
            sections.append("DAY MODE (owner-only):\n" + "\n".join(f"- {ln}" for ln in dm_lines))
    if clinical:
        sections.append(clinical)
    track_section = coach_team_texture.track_record_section(track_lines)
    if track_section:
        sections.append(track_section)
    sections.append(coach_team_texture.team_room_section(meeting_lines))
    if lines:
        sections.append("YOUR DOMAIN FACTS (yours specifically, same sources as the site):\n" + "\n".join(f"- {ln}" for ln in lines))
    return "\n\n".join(sections)
