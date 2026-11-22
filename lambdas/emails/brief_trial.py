"""brief_trial.py — the Morning Brief hybrid-format trial's reads and writes (#6175, owner ruling 2026-11-22 §2).

ONE switch, a DynamoDB item (no new IAM: the daily-brief role already reads and writes the table):

    USER#matthew#SOURCE#brief_trial / SWITCH#format   {"value": "off" | "hybrid" | "measure"}

  * absent, unreadable, or any other value -> OFF: `daily_brief_lambda` does exactly what it did before
    this module existed — this module's `read_switch` is the only call it makes, and it is a read.
  * "hybrid"  -> the hybrid block (`content.brief_hybrid`) above the full current brief, its subject, and
    one SEND# measurement row per send (+ one response token when a recommendation is shown).
  * "measure" -> the current brief, byte for byte, plus the SEND# measurement row: the comparison arm,
    so a before/after can be read from rows rather than reconstructed.

Same send time, schedule, recipient and sender: this module never sends, and the switch changes no
EventBridge schedule or permission.

Every function is fail-soft: a trial failure costs the trial, never the brief (the handler falls back
to the current render). Writes happen only when the handler's `_persist` gate is open (a dry run or a
demo writes nothing, and its response link is shown un-armed).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from coach import brief_recommendations as rr
from common.digest_utils import safe_float
from common.habit_registry import habit_tier
from common.numeric import floats_to_decimal
from common.pacific_time import day_in_words, shift_day_key
from content import brief_editorial, brief_hybrid
from content.brief_hybrid import SWITCH_HYBRID, SWITCH_MEASURE, SWITCH_OFF, SWITCH_VALUES

HISTORY_DAYS = 30
SENDS_LOOKBACK = 40
_WAITING_DAYS = 60


def read_switch(table, user_prefix: str, logger=None) -> str:
    """The trial switch. Anything but an exact known value is OFF; a failed read is OFF."""
    try:
        item = table.get_item(Key={"pk": rr.trial_pk(user_prefix), "sk": rr.SWITCH_SK}).get("Item") or {}
    except Exception as e:  # noqa: BLE001 — fail closed to today's brief
        if logger:
            logger.warning("brief trial switch read failed (treated as off): %s", e)
        return SWITCH_OFF
    val = str(item.get("value") or "").strip().lower()
    return val if val in SWITCH_VALUES else SWITCH_OFF


@dataclass
class Trial:
    variant: str
    data_day: str
    view: brief_hybrid.View | None = None
    block_html: str = ""
    text: str = ""
    subject: str | None = None
    token: str | None = None
    token_row: dict | None = None
    measurement: dict = field(default_factory=dict)


# ── reads ────────────────────────────────────────────────────────────────────────────────────────


def _recent_sends(table, user_prefix: str, data_day: str) -> list:
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(rr.trial_pk(user_prefix))
        & Key("sk").between("SEND#" + shift_day_key(data_day, -SENDS_LOOKBACK), "SEND#" + shift_day_key(data_day, -1) + "~"),
    )
    return resp.get("Items") or []


def waiting_on_you(table, user_prefix: str, data_day: str) -> list:
    """Owner approvals the platform is holding: chronicle weeks stored as drafts (status "draft" is the
    preview route's awaiting-approval state, `chronicle_store.store_installment`). Week number + the day
    it was drafted — never the draft's title or prose."""
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(user_prefix + "chronicle")
        & Key("sk").between("DATE#" + shift_day_key(data_day, -_WAITING_DAYS), "DATE#" + data_day + "~"),
        ProjectionExpression="sk, #s, week_number",
        ExpressionAttributeNames={"#s": "status"},
    )
    out = []
    for row in resp.get("Items") or []:
        if row.get("status") != "draft":
            continue
        wk = row.get("week_number")
        label = ("Week " + str(int(wk)) + " chronicle draft") if wk is not None else "a chronicle draft"
        out.append(label + " (drafted " + day_in_words(str(row.get("sk", ""))[5:15], weekday=False) + ")")
    return out


def _habits(component_details, profile) -> dict:
    hd = (component_details or {}).get("habits_mvp") or {}
    ts = hd.get("tier_status") or {}
    t0 = ts.get(0, ts.get("0", {})) or {}
    registry = (profile or {}).get("habit_registry", {}) or {}
    names = [n for n, m in registry.items() if habit_tier(m) == 0 and m.get("status") == "active"] or list(
        (profile or {}).get("mvp_habits", [])
    )
    evaluated = [n for n in names if n in t0]
    return {
        "habits_total": len(evaluated),
        "habits_done": sum(1 for n in evaluated if bool(t0.get(n))),
        "habits_missed": [n for n in evaluated if not bool(t0.get(n))],
    }


def _training(data) -> dict:
    day = data.get("date")
    try:
        from training import session_count

        strava = data.get("strava")
        tot = session_count.count(strava=[strava] if strava else [], hevy=data.get("hevy") or [], start_date=day, end_date=day)
        by_sport = {k: v.get("minutes", 0) for k, v in (tot.get("by_sport") or {}).items()}
        return {"sessions": tot.get("sessions"), "minutes": tot.get("minutes"), "by_sport": by_sport}
    except Exception:  # noqa: BLE001 — the line then says "unknown"
        return {"sessions": None}


def status_inputs(
    data, computed, component_details, profile, readiness_score, readiness_colour, mvp_streak, day_grade_score, grade, waiting
) -> dict:
    from content import brief_hr_regime

    data = data or {}
    whoop = data.get("whoop") or {}
    sleep = data.get("sleep") or {}
    mf = data.get("macrofactor") or {}
    cm = data.get("computed_metrics") or computed or {}
    wr = data.get("weight_recency") or {}
    nut = ((data.get("brief_editorial") or {}).get("nutrition")) or {}
    s = {
        "data_day": data.get("date"),
        "morning_day": data.get("date"),
        "weight_lbs": data.get("latest_weight"),
        "weight_day": wr.get("current_weight_as_of"),
        "weekly_rate_lbs": data.get("weekly_rate_lbs"),
        "rate_ci_low": data.get("weekly_rate_ci_low"),
        "rate_ci_high": data.get("weekly_rate_ci_high"),
        "rate_provisional": data.get("rate_provisional"),
        "rebaselining": brief_hr_regime.rebaselining(data),
        "readiness_score": readiness_score,
        "readiness_colour": readiness_colour,
        "recovery": safe_float(whoop, "recovery_score"),
        "hrv": (data.get("hrv") or {}).get("hrv_yesterday"),
        "hrv_30d": (data.get("hrv") or {}).get("hrv_30d"),
        "sleep_hours": safe_float(sleep, "sleep_duration_hours") or safe_float(whoop, "sleep_duration_hours"),
        "today_recovery": safe_float(data.get("whoop_today") or {}, "recovery_score"),
        "acwr": safe_float(cm, "acwr"),
        "kcal": safe_float(mf, "total_calories_kcal"),
        "protein_g": safe_float(mf, "total_protein_g"),
        "arrival": brief_editorial.nutrition_arrival(data),
        "last_arrival_day": nut.get("last_arrival_day"),
        "streak": mvp_streak,
        "grade_score": day_grade_score,
        "grade_letter": grade,
        "grade_provisional": grade_provisional(data, day_grade_score),
        "waiting": waiting,
    }
    s.update(_habits(component_details, profile))
    s.update(_training(data))
    return s


def grade_provisional(data, day_grade_score) -> bool:
    """The same rule as `brief_editorial.grade_provisional_html` (#6163): a grade computed without the
    day's food log is provisional."""
    return bool(brief_editorial.grade_provisional_html(data, day_grade_score))


def _readiness_run(fetch_range, data_day: str, colour) -> list:
    rows = fetch_range("computed_metrics", shift_day_key(data_day, -6), data_day) or []
    by_day = {str(r.get("sk", ""))[5:15]: r for r in rows}
    scores, d = [], data_day
    while d in by_day and by_day[d].get("readiness_colour") == colour:
        sc = by_day[d].get("readiness_score")
        scores.append(int(float(sc)) if sc is not None else "—")
        d = shift_day_key(d, -1)
    return list(reversed(scores))


# ── build ────────────────────────────────────────────────────────────────────────────────────────


def build_view(
    *, data, status, readiness_score, readiness_colour, guidance_items, history, readiness_scores, waiting_read_ok=True
) -> brief_hybrid.View:
    """Pure assembly of the hybrid view from already-read inputs (the tests drive this directly)."""
    day = data.get("date")
    food_pending = brief_editorial.nutrition_arrival(data) == "not_arrived" and status.get("kcal") is None
    recs = []
    if not status.get("rebaselining"):
        r = brief_hybrid.readiness_rec(readiness_colour, readiness_score, readiness_scores, day)
        if r:
            recs.append(r)
    g, held = brief_hybrid.guidance_recs(guidance_items, day, food_pending)
    recs += [x for x in g if not (x.key == "recovery_day" and any(y.source == "readiness" for y in recs) and readiness_colour == "red")]
    if food_pending:
        recs.append(brief_hybrid.export_rec(day, status.get("last_arrival_day")))
    brief_hybrid.label_recs(recs, day, history)
    decision = brief_hybrid.pick_decision(recs)
    # the decision leads; the rest keep their order
    unknown = []
    if status.get("today_recovery") is None:
        unknown.append("This morning's recovery (" + day_in_words(shift_day_key(day, 1)) + "): not scored when this brief was built.")
    if food_pending:
        last = status.get("last_arrival_day")
        unknown.append(
            "Food for "
            + day_in_words(day)
            + ": the MacroFactor export has not arrived"
            + ((" (last export " + day_in_words(last, weekday=False) + ")") if last else "")
            + ". This is pending data, not a missed log."
        )
    elif status.get("arrival") is None and status.get("kcal") is None:
        unknown.append("Food for " + day_in_words(day) + ": whether an export has arrived could not be read.")
    if status.get("rebaselining"):
        unknown.append("Readiness colour: heart-rate numbers are re-baselining, so no readiness call is made.")
    elif readiness_colour not in ("green", "yellow", "red"):
        unknown.append("Readiness: no score for the morning of " + day_in_words(day) + ".")
    if status.get("weight_lbs") is None:
        unknown.append("Body weight: no weigh-in on record.")
    if status.get("sessions") is None:
        unknown.append("Training: the day's sessions could not be read.")
    if not guidance_items:
        unknown.append("Coach guidance: none was generated for this brief.")
    if not waiting_read_ok:
        unknown.append("Waiting on you: the approvals list could not be read.")
    return brief_hybrid.View(
        data_day=day,
        status=brief_hybrid.status_lines(status),
        recs=recs,
        decision=decision,
        unknown=unknown,
        held_back=held,
    )


def prepare(
    *,
    variant,
    table,
    fetch_range,
    user_prefix,
    data,
    profile,
    computed,
    component_details,
    readiness_score,
    readiness_colour,
    mvp_streak,
    day_grade_score,
    grade,
    tldr_guidance,
    editorial,
    today_short,
    site_url,
    recipient,
    logger,
) -> Trial | None:
    """Everything the trial needs before the send. None on any failure (the brief then goes out as today's)."""
    if variant not in (SWITCH_HYBRID, SWITCH_MEASURE):
        return None
    day = (data or {}).get("date")
    try:
        data = {**data, "brief_editorial": editorial or {}}
        try:
            waiting, waiting_ok = waiting_on_you(table, user_prefix, day), True
        except Exception as e:  # noqa: BLE001
            logger.warning("brief trial: waiting read failed: %s", e)
            waiting, waiting_ok = [], False
        try:
            sends = _recent_sends(table, user_prefix, day)
        except Exception as e:  # noqa: BLE001
            logger.warning("brief trial: send history read failed: %s", e)
            sends = []
        status = status_inputs(
            data, computed, component_details, profile, readiness_score, readiness_colour, mvp_streak, day_grade_score, grade, waiting
        )
        history = rr.shown_history(fetch_range, sends, shift_day_key(day, -HISTORY_DAYS), shift_day_key(day, -1))
        guidance = list((tldr_guidance or {}).get("guidance") or [])
        view = build_view(
            data=data,
            status=status,
            readiness_score=readiness_score,
            readiness_colour=readiness_colour,
            guidance_items=guidance,
            history=history,
            readiness_scores=_readiness_run(fetch_range, day, readiness_colour),
            waiting_read_ok=waiting_ok,
        )
        trial = Trial(variant=variant, data_day=day, view=view)
        respond = brief_hybrid.pick_respond(view.recs, view.decision)
        if variant == SWITCH_HYBRID and respond is not None:
            token = rr.new_token()
            now = int(time.time())
            trial.token = token
            trial.token_row = {
                "rec_id": respond.rec_id,
                "rec_key": respond.key,
                "send_day": day,
                "recipient_hash": rr.recipient_hash(recipient),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": now + rr.TOKEN_TTL_SECONDS,
            }
            view.respond_url = rr.response_url(site_url, token)
            view.respond_rec = respond
        if variant == SWITCH_HYBRID:
            trial.block_html = brief_hybrid.render_html(view)
            trial.text = brief_hybrid.render_text(view)
            trial.subject = brief_hybrid.subject(view, today_short, day_grade_score, grade, status["grade_provisional"], readiness_colour)
        trial.measurement = {
            "variant": variant,
            "format_version": brief_hybrid.FORMAT_VERSION if variant == SWITCH_HYBRID else "current",
            "recs": [
                {"id": r.rec_id, "key": r.key, "source": r.source, "status": r.status, "run_day": r.day_n, "kind": r.kind}
                for r in view.recs
            ],
            "n_recs": len(view.recs),
            "n_new": sum(1 for r in view.recs if r.status == "NEW"),
            "n_repeat": sum(1 for r in view.recs if r.status == "REPEAT"),
            "decision": view.decision.rec_id if view.decision else None,
            "food_pending": any(r.source == "food_export" for r in view.recs),
            "food_held_back": view.held_back,
            "grade_provisional": bool(status["grade_provisional"]),
            "hybrid_words": brief_hybrid.word_count(trial.text) if trial.text else 0,
            "respond_rec_id": trial.token_row["rec_id"] if trial.token_row else None,
            "response": rr.NOT_RECORDED,
        }
        return trial
    except Exception as e:  # noqa: BLE001 — the trial never costs the brief
        logger.warning("brief trial prepare failed (sending the current brief): %s", e)
        return None


# The handler locals `run` reads, by name — and nothing else (never the rendered `html`: the email body reaches
# only the sanitiser, the banner/trial `_re.sub`, `len` and SES, tests/test_rhythm_owner_4972.py).
HANDLER_NAMES = (
    "data",
    "profile",
    "day_grade_score",
    "grade",
    "readiness_score",
    "readiness_colour",
    "mvp_streak",
    "component_details",
    "tldr_guidance",
    "today_short",
    "demo_mode",
)


def run(g: dict, handler_locals: dict, subject: str) -> tuple:
    """The handler's one call: ``(trial | None, block_html, subject)``. ``g`` is the handler module's globals (its
    table, fetch_range/fetch_date, USER_PREFIX, RECIPIENT, logger); ``handler_locals`` is read for HANDLER_NAMES
    only. Off — or a demo brief — returns ``(None, "", subject)`` after at most one read, so the handler's
    block injection is the identity and the brief is byte for byte today's."""
    v = {k: handler_locals.get(k) for k in HANDLER_NAMES}
    if v["demo_mode"]:
        return None, "", subject
    table, logger = g["table"], g["logger"]
    variant = read_switch(table, g["USER_PREFIX"], logger)
    if variant == SWITCH_OFF:
        return None, "", subject
    data = v["data"] or {}
    try:
        from emails import brief_editorial_inputs

        editorial = brief_editorial_inputs.gather(table, g["fetch_date"], g["USER_PREFIX"], data.get("date"), logger)
    except Exception as e:  # noqa: BLE001
        logger.warning("brief trial: editorial inputs failed: %s", e)
        editorial = {}
    trial = prepare(
        variant=variant,
        table=table,
        fetch_range=g["fetch_range"],
        user_prefix=g["USER_PREFIX"],
        data=data,
        profile=v["profile"],
        computed=data.get("computed_metrics"),
        component_details=v["component_details"],
        readiness_score=v["readiness_score"],
        readiness_colour=v["readiness_colour"],
        mvp_streak=v["mvp_streak"],
        day_grade_score=v["day_grade_score"],
        grade=v["grade"],
        tldr_guidance=v["tldr_guidance"],
        editorial=editorial,
        today_short=v["today_short"],
        site_url=os.environ.get("SITE_URL", "https://averagejoematt.com"),
        recipient=g.get("RECIPIENT", ""),
        logger=logger,
    )
    if trial is None or trial.variant != SWITCH_HYBRID or not trial.block_html:
        return trial, "", subject
    return trial, trial.block_html, (trial.subject or subject)


def apply(trial: Trial | None, html: str, subject: str) -> tuple:
    """(html, subject) to send. Unchanged unless the trial is hybrid and prepared."""
    if trial is None or trial.variant != SWITCH_HYBRID or not trial.block_html:
        return html, subject
    return brief_hybrid.inject(html, trial.block_html), (trial.subject or subject)


def _ddb(item: dict) -> dict:
    """Top-level None fields dropped; floats to Decimal via the shared walker (NaN/Inf -> None, #5524)."""
    return floats_to_decimal({k: v for k, v in item.items() if v is not None})


def record(table, user_prefix: str, trial: Trial | None, html_chars: int, persist: bool, logger) -> None:
    """After the send: the token row (so the link works) and the SEND# measurement row. Fail-soft.
    `persist` False (dry run / demo) writes nothing."""
    if trial is None or not persist:
        return
    pk = rr.trial_pk(user_prefix)
    try:
        if trial.token and trial.token_row:
            table.put_item(
                Item=_ddb({"pk": pk, "sk": "TOKEN#" + rr.token_hash(trial.token), **trial.token_row}),
                ConditionExpression="attribute_not_exists(sk)",
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("brief trial token write failed (the response link will say 'not valid'): %s", e)
    try:
        m = dict(trial.measurement)
        m["total_html_chars"] = int(html_chars)  # the whole sent email's length (the handler hands `len(html)`, never the html)
        m["sent_at"] = datetime.now(timezone.utc).isoformat()
        table.put_item(Item=_ddb({"pk": pk, "sk": "SEND#" + trial.data_day, "date": trial.data_day, **m}))
    except Exception as e:  # noqa: BLE001
        logger.warning("brief trial measurement write failed (non-fatal): %s", e)
