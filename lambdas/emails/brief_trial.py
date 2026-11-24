"""brief_trial.py — the Morning Brief hybrid-format trial's reads and writes (#6175, owner ruling 2026-11-22 §2).

ONE switch, a DynamoDB item (no new IAM: the daily-brief role already reads and writes the table):

    USER#matthew#SOURCE#brief_trial / SWITCH#format   {"value": "off" | "hybrid" | "measure" | "compact"}

  * absent, unreadable, or any other value -> OFF: `daily_brief_lambda` does exactly what it did before
    this module existed — this module's `read_switch` is the only call it makes, and it is a read.
    Compact is never a default: only the exact word selects it (#6240, owner ruling 2026-11-23 §3).
  * "hybrid"  -> the hybrid block (`content.brief_hybrid`) above the full current brief, its subject, and
    one SEND# measurement row per send (+ one response token when a recommendation is shown).
  * "measure" -> the current brief, byte for byte, plus the SEND# measurement row: the comparison arm,
    so a before/after can be read from rows rather than reconstructed.
  * "compact" -> (#6240) the compact brief (`content.brief_compact`) REPLACES the whole email — html, a plain-text
    part and the subject; the legacy render is still built (so the coach pipeline and its model calls are unchanged)
    but not sent. Checked by `content.brief_budget` before the send. A render failure or a HARD budget violation
    sends a short failure notice instead — never the legacy report — keeps the verified alerts in it, records
    `fallback` on the SEND# row, logs `COMPACT_FALLBACK_TOKEN`, and the handler raises AFTER the send and every
    post-send write, so the daily-brief Errors alarms see it (`life-platform-daily-brief-errors`,
    `slo-daily-brief-delivery`). A DIL-025 replay refuses the retry, so it is never a second email.

Same send time, schedule, recipient and sender: this module never sends, and the switch changes no
EventBridge schedule or permission.

#6158 pilot (dark: `coach.brief_recommendations.CANONICAL_INTAKE_LIVE`): `_pilot_plan` / `_pilot_record` hand the
brief's one linked recommendation to `coach.brief_rec_intake` — imported only there, only while the switch is on.

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
from content import brief_budget, brief_compact, brief_editorial, brief_hybrid, brief_trends
from content.brief_hybrid import SWITCH_COMPACT, SWITCH_HYBRID, SWITCH_MEASURE, SWITCH_OFF, SWITCH_VALUES

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
    view: brief_hybrid.View | brief_compact.CompactView | None = None
    block_html: str = ""
    text: str = ""
    subject: str | None = None
    token: str | None = None
    token_row: dict | None = None
    measurement: dict = field(default_factory=dict)
    pilot: dict | None = None  # #6158 (dark): set only while rr.CANONICAL_INTAKE_LIVE
    follow_token: str | None = None
    follow_token_row: dict | None = None
    document: str = ""  # #6240 compact: the WHOLE email's html (the handler sends it instead of the legacy render)
    document_text: str = ""  # #6240 compact: the plain-text part
    fallback: bool = False  # #6240: the compact render failed and the short failure notice is what goes out
    fallback_reason: str | None = None


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
        if variant == SWITCH_HYBRID and rr.CANONICAL_INTAKE_LIVE:  # #6158 pilot, dark: off = this line is the whole cost
            trial.pilot = _pilot_plan(table, user_prefix, trial, respond, site_url, recipient, logger)
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
# only the sanitiser, the banner/trial `_re.sub`, `len` and SES — the owner-only heart-rhythm section rides in it).
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
    # #6240: the owner-only heart-rhythm lines the handler already computed for this email (demo excluded) — read
    # ONLY by `content.brief_compact.critical_alerts`, into the compact email to the owner; never data, a log or a row.
    "_rhythm_lines",
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
    if variant == SWITCH_COMPACT:  # #6240: never returns None — a failure is the short notice, never the legacy report
        trial = compact_trial(g, v, editorial)
        return trial, "", (trial.subject or subject)
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


def _pilot_plan(table, user_prefix, trial: Trial, respond, site_url, recipient, logger) -> dict:
    """#6158 pilot, BEFORE the send (reads only): plan the offer, stamp the link's token with its canonical id,
    and attach the one due brief follow-up. Record unreadable -> the brief goes out as the trial's, and nothing
    is stamped, so nothing from this send can ever reach the record."""
    from coach import brief_rec_intake as intake

    try:
        offer, why = intake.plan_offer(table, respond, trial.data_day)
        fu = intake.due_follow_up(table, rr.trial_pk(user_prefix), intake.brief_day(trial.data_day))
    except Exception as e:  # noqa: BLE001 — the record's absence never costs the brief
        logger.warning("[brief_rec_pilot] record unavailable; the brief goes out, nothing will be recorded: %s", type(e).__name__)
        return {"state": "record_unavailable"}
    shown = True
    if offer and trial.token_row:
        trial.token_row["canonical_rec_id"] = offer.canonical_rec_id  # the activation marker
        if offer.settled and trial.view is not None:  # a repeat he already answered: show his answer, ask nothing new
            shown = False
            trial.view.respond_url = None
            trial.view.respond_note = (
                "You answered “" + offer.answer_label + "”" + (" on " + str(offer.answered_at)[:10] if offer.answered_at else "") + "."
            )
        elif not offer.new and offer.answer != "not_recorded" and trial.view is not None:
            trial.view.respond_note = "Your last answer: “" + offer.answer_label + "”. A new answer replaces it."
    if fu and not (offer and fu["rec_id"] == offer.canonical_rec_id) and trial.view is not None:
        trial.follow_token = rr.new_token()
        trial.follow_token_row = {
            "rec_id": "follow_up#" + fu["rec_id"],
            "rec_key": "follow_up",
            "send_day": shift_day_key(fu["date"], -1),  # the data day of the brief that OFFERED it: the page names that brief
            "recipient_hash": rr.recipient_hash(recipient),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": int(time.time()) + rr.TOKEN_TTL_SECONDS,
            "canonical_rec_id": fu["rec_id"],
        }
        trial.view.follow_up = fu
        trial.view.follow_up_url = rr.response_url(site_url, trial.follow_token)
    return {"state": "planned", "offer": offer, "skip": why, "follow_up_rec_id": fu["rec_id"] if fu else None, "link_shown": shown}


def _pilot_record(table, pk: str, trial: Trial, sent, logger) -> dict:
    """#6158 pilot, AFTER the send: invoke the recommendation writer (the brief's role cannot write the record), then
    the SEND# row's pilot fields. The offer is sent to the writer only with the mail service's MessageId."""
    from coach import brief_rec_intake as intake

    p = trial.pilot or {}
    out: dict = {"rec_pilot_state": p.get("state")}
    if p.get("state") != "planned":
        return out
    msg = sent.get("MessageId") if isinstance(sent, dict) else None
    out["ses_message_id"] = msg
    out["delivery_state"] = "accepted_by_mail_service" if msg else "not_accepted_by_mail_service"
    offer = p.get("offer")
    tokens: dict = {}  # hash -> canonical id: the tokens THIS send minted, so the writer can bind a press to its send
    if offer is None:
        out.update(rec_offer="not_eligible", rec_offer_reason=p.get("skip"))
    elif not msg:
        out.update(canonical_rec_id=offer.canonical_rec_id, rec_offer="not_accepted_by_mail_service")
    else:
        out["canonical_rec_id"] = offer.canonical_rec_id
        th = rr.token_hash(trial.token) if trial.token else ""
        if th and p.get("link_shown"):
            tokens[th] = offer.canonical_rec_id
        payload = intake.offer_payload(
            offer, send_day=trial.data_day, token_hash=th, ses_message_id=msg, accepted_at=datetime.now(timezone.utc).isoformat()
        )
        try:
            res = intake.invoke_writer(payload)
            out["rec_offer"] = res.get("state")
            if res.get("reason"):
                out["rec_offer_reason"] = res["reason"]
                logger.warning("[brief_rec_pilot] offer refused by the writer rec=%s: %s", offer.canonical_rec_id, res["reason"])
        except Exception as e:  # noqa: BLE001 — logged + on the SEND# row; never retried, never reconstructed later
            out["rec_offer"], out["rec_offer_error"] = "writer_failed", intake.failure_class(e)
            logger.warning("[brief_rec_pilot] offer not recorded rec=%s: %s", offer.canonical_rec_id, out["rec_offer_error"])
    if msg and p.get("follow_up_rec_id"):
        out["follow_up_rec_id"] = p["follow_up_rec_id"]  # asked once: this row is the proof it was asked
        if trial.follow_token and trial.follow_token_row:
            try:
                table.put_item(
                    Item=_ddb({"pk": pk, "sk": "TOKEN#" + rr.token_hash(trial.follow_token), **trial.follow_token_row}),
                    ConditionExpression="attribute_not_exists(sk)",
                )
                tokens[rr.token_hash(trial.follow_token)] = p["follow_up_rec_id"]
            except Exception as e:  # noqa: BLE001
                logger.warning("[brief_rec_pilot] follow-up token write failed: %s", type(e).__name__)
    if tokens:
        out["pilot_tokens"] = tokens
    try:
        out["rec_answers"] = (intake.invoke_writer({"action": "carry"}) or {}).get("counts") or "writer_failed"
    except Exception as e:  # noqa: BLE001
        out["rec_answers"], out["rec_answers_error"] = "writer_failed", intake.failure_class(e)
        logger.warning("[brief_rec_pilot] answers not carried this run (they stay on their token rows): %s", out["rec_answers_error"])
    return out


def record(table, user_prefix: str, trial: Trial | None, html_chars: int, persist: bool, logger, sent=None) -> None:
    """After the send: the token row (so the link works) and the SEND# measurement row. Fail-soft.
    `persist` False (dry run / demo) writes nothing. `sent` is SES's reply to the send (#6158 pilot only)."""
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
        if trial.pilot is not None:
            m.update(_pilot_record(table, pk, trial, sent, logger))
        table.put_item(Item=_ddb({"pk": pk, "sk": "SEND#" + trial.data_day, "date": trial.data_day, **m}))
    except Exception as e:  # noqa: BLE001
        logger.warning("brief trial measurement write failed (non-fatal): %s", e)


# ── #6240: the compact brief ─────────────────────────────────────────────────────────────────────────────────────

# The literal the fallback logs (ERROR level), for a future MetricFilter; the alarm that sees it TODAY is the Lambda's
# own Errors metric, from `raise_if_fallback`.
COMPACT_FALLBACK_TOKEN = "MORNING-BRIEF-COMPACT-FALLBACK"  # noqa: S105 — a log token, not a secret
_PREV_WEIGHT_DAYS = 14


class CompactBriefFallback(RuntimeError):
    """Raised by the handler's last statement after a compact failure notice went out (never before the send)."""


def _previous_weight(fetch_range, day: str, as_of) -> tuple | None:
    """(day, lb) of the weigh-in before the newest one, from the brief's own Withings read shape."""
    rows = fetch_range("withings", shift_day_key(day, -_PREV_WEIGHT_DAYS), day) or []
    weighed = sorted((str(r.get("sk", ""))[5:15], safe_float(r, "weight_lbs")) for r in rows if safe_float(r, "weight_lbs") is not None)
    before = [(d, w) for d, w in weighed if as_of and d < str(as_of)]
    return before[-1] if before else None


def _previous_acwr(fetch_range, day: str):
    prev = shift_day_key(day, -1)
    rows = fetch_range("computed_metrics", prev, prev) or []
    return safe_float(rows[0], "acwr") if rows else None


def compact_view(*, data, status, guidance_items, history, alerts, previous_weight, previous_acwr, site_url, persona, trends=()):
    """Pure: the hybrid's own recommendation rules (one per action class, food asks held back while the export is
    pending, NEW/REPEAT from the shown history), then `brief_compact.build`. The tests drive this directly."""
    day = data.get("date")
    arrival = brief_editorial.nutrition_arrival(data)
    no_intake = status.get("kcal") is None
    recs, _held = brief_hybrid.guidance_recs(guidance_items, day, arrival == "not_arrived" and no_intake)
    brief_hybrid.label_recs(recs, day, history)
    view = brief_compact.build(
        data=data,
        status=status,
        recs=recs,
        alerts=alerts,
        food_pending=arrival == "not_arrived" and no_intake,
        food_unknown=arrival is None and no_intake,
        previous_weight=previous_weight,
        previous_acwr=previous_acwr,
        site_url=site_url,
        persona=persona,
        trends=trends,
    )
    origin = {r.rec_id: r for r in recs}
    for c in view.recs:
        c.origin = origin.get(c.rec_id)  # the hybrid Rec, for the response token and the (dark) #6158 pilot
    return view


def _compact_prepare(trial: Trial, g: dict, v: dict, data: dict, alerts: list, site_url: str, persona: tuple) -> None:
    table, logger, fetch_range, user_prefix = g["table"], g["logger"], g["fetch_range"], g["USER_PREFIX"]
    day = trial.data_day
    try:
        sends = _recent_sends(table, user_prefix, day)
    except Exception as e:  # noqa: BLE001 — no history: every recommendation reads as NEW, none is suppressed by mistake
        logger.warning("compact brief: send history read failed: %s", type(e).__name__)
        sends = []
    status = status_inputs(
        data, data.get("computed_metrics"), v["component_details"], v["profile"], v["readiness_score"], v["readiness_colour"],
        v["mvp_streak"], v["day_grade_score"], v["grade"], [],
    )  # fmt: skip
    wr = data.get("weight_recency") or {}
    trends = brief_trends.apply_cadence(_trend_items(table, data, status, logger), sends, day)
    view = compact_view(
        data=data,
        status=status,
        guidance_items=list((v["tldr_guidance"] or {}).get("guidance") or []),
        history=rr.shown_history(fetch_range, sends, shift_day_key(day, -HISTORY_DAYS), shift_day_key(day, -1)),
        alerts=alerts,
        previous_weight=_previous_weight(fetch_range, day, wr.get("current_weight_as_of")),
        previous_acwr=_previous_acwr(fetch_range, day),
        site_url=site_url,
        persona=persona,
        trends=tuple(trends),
    )
    trial.view = view  # carries the same respond/follow-up fields as brief_hybrid.View, for the #6158 pilot hook
    respond = getattr(view.recs[0], "origin", None) if view.recs else None
    if respond is not None:  # the response mechanism, reused (owner ruling §8): one link, on the shown recommendation
        trial.token = rr.new_token()
        trial.token_row = {
            "rec_id": respond.rec_id,
            "rec_key": respond.key,
            "send_day": day,
            "recipient_hash": rr.recipient_hash(g.get("RECIPIENT", "")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": int(time.time()) + rr.TOKEN_TTL_SECONDS,
        }
        view.respond_url, view.respond_rec = rr.response_url(site_url, trial.token), respond
    if rr.CANONICAL_INTAKE_LIVE:  # #6158 pilot, dark: off = this line is the whole cost
        trial.pilot = _pilot_plan(table, user_prefix, trial, respond, site_url, g.get("RECIPIENT", ""), logger)
    _fit_follow_up(view)
    today_short = v["today_short"] or ""
    html, text, violations = _render_checked(view, today_short, persona)
    # A long model-written recommendation must not turn a good brief into a failure notice: past the word ceiling the
    # LAST recommendation is dropped (counted), down to the one that leads. Alerts and metrics are never trimmed here.
    while len(view.recs) > 1 and {x.code for x in violations if x.hard} and {x.code for x in violations if x.hard} <= _LENGTH_CODES:
        view.recs = view.recs[:-1]
        view.dropped_for_length += 1
        html, text, violations = _render_checked(view, today_short, persona)
    trial.measurement = {
        "variant": SWITCH_COMPACT,
        "format_version": brief_compact.FORMAT_VERSION,
        **brief_budget.measure(html, text),
        "lead_kind": view.lead_kind,
        "recs": [{"id": r.rec_id, "key": r.key, "status": r.status, "changed_because": bool(r.changed_because)} for r in view.recs],
        "n_new": sum(1 for r in view.recs if r.status == "NEW"),
        "n_repeat": sum(1 for r in view.recs if r.status == "REPEAT"),
        "repeats_suppressed": view.repeats_suppressed,
        "dropped_voice": view.dropped_voice,
        "dropped_clearance": view.dropped_clearance,
        "dropped_for_length": view.dropped_for_length,
        # #6241 §2: a held high-stakes recommendation keeps its ORIGINAL text here, on this private row, for
        # investigation — never in a log line (the log carries the count only)
        "held_recs": list(view.held_recs),
        "n_held_medical": len(view.held_recs),
        "context_state": brief_trends.state(view.trends),
        "trend_notes": brief_trends.notes(view.trends),  # tomorrow's cadence reads this (no new store)
        "pending_inputs": list(view.pending_inputs),
        "food_pending": "food" in view.pending_inputs,
        "grade_provisional": bool(status["grade_provisional"]),
        "budget_violations": sorted({x.code for x in violations}),
        "fallback": False,
        "respond_rec_id": trial.token_row["rec_id"] if trial.token_row else None,
        "response": rr.NOT_RECORDED,
    }
    if view.held_recs:  # counts and classes only — the text stays on the private SEND# row (#6241 §2)
        classes = sorted({c for h in view.held_recs for c in h["classes"]})
        logger.info("compact brief: held %d high-stakes recommendation(s), classes=%s", len(view.held_recs), ",".join(classes))
    hard = sorted({x.code for x in violations if x.hard})
    if hard:
        raise ValueError("budget:" + ",".join(hard))
    trial.document, trial.document_text, trial.subject = html, text, brief_compact.subject(view, today_short)


_LENGTH_CODES = frozenset({"words_over", "text_words_over"})


def _render_checked(view, today_short: str, persona: tuple) -> tuple:
    html, text = brief_compact.render_html(view, today_short), brief_compact.render_text(view, today_short)
    return html, text, brief_budget.check(html, text, persona_names=persona, pending_inputs=tuple(view.pending_inputs))


def _trend_items(table, data: dict, status: dict, logger) -> list:
    """#6241 §3: the open multi-week items from verdicts the platform already computes (content.brief_trends)."""
    from training import rate_band

    band_error, cap = False, None
    try:
        cap = rate_band.guidance_cap_for(table)
    except rate_band.GuidanceReadError:
        band_error = True  # logged by class inside rate_band; never the record
    weight, rate = status.get("weight_lbs"), status.get("weekly_rate_lbs")
    band = None
    try:
        band = rate_band.band_view(float(weight), -float(rate), cap) if weight is not None and rate is not None else None
    except Exception as e:  # noqa: BLE001 — the item then says the band could not be read
        logger.warning("compact brief: rate band unreadable: %s", type(e).__name__)
    items = []
    if band is None or band.get("governs") is not False:  # below the landing weight his schedule, not the band, governs
        item = brief_trends.weight_rate_item(status, band, band_error)
        if item:
            items.append(item)
    items += brief_trends.sustained_items(data.get("anomaly") or {}, brief_compact.ANOMALY_PHYSIOLOGICAL_FIELDS)
    return items


def _fit_follow_up(view) -> None:
    """A due follow-up (the #6158 pilot's, dark) is a recommendation slot: with one, at most REC_CEILING - 1 others."""
    if view.follow_up:
        view.recs = view.recs[: brief_compact.REC_CEILING - 1]


def _compact_fallback(trial: Trial, alerts, site_url: str, today_short: str, reason: str, logger) -> None:
    """The short failure notice (owner ruling §4): says the brief could not be prepared, keeps the verified alerts
    (or says the alert check could not run), links the day, and is recorded. Never the legacy report."""
    day = trial.data_day
    url = site_url.rstrip("/") + "/data/day/" + day + "/"
    trial.token = trial.token_row = trial.pilot = None  # no recommendation is shown, so no answer link is armed
    try:
        trial.document = brief_compact.fallback_html(day, alerts, url, today_short)
        trial.document_text = brief_compact.fallback_text(day, alerts, url, today_short)
    except Exception:  # noqa: BLE001 — the last resort is a constant: it still says the brief failed
        trial.document = "<!DOCTYPE html><html><body><p>" + brief_compact.FALLBACK_LEAD + "</p></body></html>"
        trial.document_text = brief_compact.FALLBACK_LEAD
    trial.subject = brief_compact.fallback_subject(today_short)
    trial.fallback, trial.fallback_reason = True, reason
    trial.measurement = {
        **(trial.measurement or {}),
        "variant": SWITCH_COMPACT,
        "format_version": brief_compact.FORMAT_VERSION,
        "fallback": True,
        "fallback_reason": reason,
        "alert_check": "failed" if alerts is None else "ok",
        "n_critical_alerts": len(alerts or []),
        "fallback_words": brief_budget.words(trial.document_text),
        "response": rr.NOT_RECORDED,
    }
    logger.error("%s data_day=%s reason=%s", COMPACT_FALLBACK_TOKEN, day, reason)


def compact_trial(g: dict, v: dict, editorial: dict) -> Trial:
    """The compact email for the handler. Never raises and never returns None: any failure -> the failure notice."""
    logger = g["logger"]
    data = {**(v["data"] or {}), "brief_editorial": editorial or {}}
    trial = Trial(variant=SWITCH_COMPACT, data_day=str(data.get("date") or ""))
    site_url = os.environ.get("SITE_URL", "https://averagejoematt.com")
    today_short = v["today_short"] or ""
    try:
        alerts = brief_compact.critical_alerts(data, v.get("_rhythm_lines"))
    except Exception as e:  # noqa: BLE001 — an alert check that cannot run must not let a brief claim there is none
        _compact_fallback(trial, None, site_url, today_short, "alert_check:" + type(e).__name__, logger)
        return trial
    try:
        _compact_prepare(trial, g, v, data, alerts, site_url, brief_compact.persona_names())
    except Exception as e:  # noqa: BLE001 — the notice, never the legacy report
        reason = str(e) if str(e).startswith("budget:") else "render:" + type(e).__name__
        _compact_fallback(trial, alerts, site_url, today_short, reason, logger)
    return trial


def text_part(trial: Trial | None) -> dict:
    """The SES Body's plain-text entry for a compact send; {} otherwise (so the legacy Body is byte for byte today's)."""
    if trial is None or not trial.document_text:
        return {}
    return {"Text": {"Data": trial.document_text, "Charset": "UTF-8"}}


def raise_if_fallback(trial: Trial | None, dry_run: bool) -> None:
    """The handler's last statement: a compact failure that SENT its notice becomes a Lambda error, so the existing
    daily-brief Errors alarms record it (owner ruling §4 — observable, never disguised as a normal brief)."""
    if trial is not None and trial.fallback and not dry_run:
        raise CompactBriefFallback(
            COMPACT_FALLBACK_TOKEN + ": the compact brief failed (" + str(trial.fallback_reason) + "); the notice was sent"
        )
