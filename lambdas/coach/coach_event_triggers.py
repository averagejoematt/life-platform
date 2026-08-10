"""coach_event_triggers.py — outbound that the DATA starts, not the calendar (#2490).

Act 1b gave the coaches two ways to text first, and both are schedule-shaped: a
referral fires off a conversation, a check-in fires off a cron. Neither of them
can notice anything. This module is the third shape — *a coach texts because
something happened* — and the whole file is an argument about what "happened"
is allowed to mean.

Three triggers, one per acceptance bullet on #2490:

  * **lift PR** (celebration) — a lift's best estimated 1RM clears its own
    previous best by more than that lift's own session-to-session noise.
  * **milestone** (celebration) — an announced ``MILESTONE#`` event, dated today.
  * **recovery slide** (soft concern) — three consecutive days below HIS OWN p25
    recovery band.

The rules the design is actually made of:

* **Thresholds come from personal variance, never from a round number**
  (ADR-105 rule 4). "Recovery under 33" is a magazine constant; "three days under
  the 25th percentile of his own trailing 60 days, n≥20" is a statement about
  Matthew. Same for the lift: a PR has to clear the standard deviation of that
  lift's own session-to-session change, so a 2.5 lb wobble on a lift that swings
  15 lb between sessions is not news. Thin history is never a licence to guess —
  under the minimum n, the trigger simply does not exist.
* **A number this platform already computes is never re-derived.** Weight
  milestones are NOT re-thresholded here: ``health.milestone_ledger`` already owns
  them, write-once, on a trailing 7-day mean with n≥3, spiral-breaker-gated and
  cooldown-governed. Re-deriving "he crossed 250" from a live comparison is the
  exact memoryless pattern that ledger exists to end, so this module *consumes*
  its announced events instead. That also means this trigger inherits, for free,
  every honesty property the ledger fought for.
* **One event, one text, forever.** Every candidate carries a deterministic
  ``event_id`` derived from the fact itself (the lift + its date, the milestone
  id, the day the slide STARTED). The write-once claim lives in
  ``coach_outbound.claim_event``. A slide that runs to day four re-derives the
  same id as day three and stays silent.
* **Celebration is gated by the spiral breaker** (#1627): during a suspected
  downturn the platform checks in on him, it does not congratulate him. Concern is
  deliberately NOT gated — it is the direction the breaker wants.
* **Everything fails dark, and evidence is mandatory.** No data, thin baselines, a
  stale row, an unreadable table, a coach whose bot does not exist yet, an empty
  evidence block — every one of them is "don't text". An unsolicited message with
  nothing behind it is precisely the notification these personas are written not
  to be.

Shape follows ``spiral_breaker``: a pure core (detection, ordering, evidence —
no I/O, no clock reads, no AWS) and a thin fetch half. The transport stays in
``telegram_worker_lambda``, which is deliberately given only a seat lookup and a
speak callback — that module is under a size ceiling and every outbound feature
that inlined itself there would spend it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from health.personal_baselines import percentile

from coach import coach_outbound

logger = logging.getLogger(__name__)

# ── Thresholds (ADR-105: every one of these is a window or an n, not a verdict) ─

# Recovery: the personal band and how much of it is needed.
RECOVERY_BASELINE_DAYS = 60  # trailing window the personal percentile is drawn from
RECOVERY_MIN_N = 20  # below this the band is not his baseline, it is noise
RECOVERY_PERCENTILE = 25  # "poor" = his own worst quartile, not a magazine number
RECOVERY_STREAK_DAYS = 3  # the acceptance bullet: three consecutive days

# Lift PR: the margin is the lift's own variability, not a fixed pound count.
PR_LOOKBACK_DAYS = 180
PR_MIN_SESSIONS = 6  # fewer sessions than this and there is no personal noise scale
PR_NOISE_K = 1.0  # a PR must clear the previous best by ≥ 1 SD of its own session deltas
PR_MIN_REPS = 1
PR_MAX_REPS = 12  # Epley degrades past ~12; the site's strength surface uses the same gate

# How old a triggering fact may be and still be worth a text. Ingestion lands
# through the morning, so "today only" would silently drop most real events.
EVENT_FRESH_DAYS = 2

KIND_LIFT_PR = "lift_pr"
KIND_MILESTONE = "milestone"
KIND_RECOVERY_SLIDE = "recovery_slide"

# ── Who owns the lane ─────────────────────────────────────────────────────────
# The ping comes from the DOMAIN-OWNING coach (the #2490 acceptance bullet), and
# the persona ids below are registry ids — tests/test_coach_outbound_behavior.py
# asserts every one of them is a persona that can actually text.
LIFT_OWNER = "physical_coach"  # Dr. Max Reyes — the merged Performance seat
RECOVERY_OWNER = "sleep_coach"  # Dr. Lisa Park — sleep/recovery
NUTRITION_OWNER = "nutrition_coach"  # Dr. Marcus Webb — weight + composition
LEAD_OWNER = "eli_marsh"  # the Principal Investigator: whole-program facts, and the
# honest default — an unmapped ladder belongs to the person who owns the whole thing,
# never to whichever specialist happens to be first in a dict.

MILESTONE_LADDER_OWNER = {
    "return_after_gap": LIFT_OWNER,
    "sustained_sessions": LIFT_OWNER,
    "strength_in_deficit": LIFT_OWNER,
    "zone2": LIFT_OWNER,
    "rhr_hrv_trend": RECOVERY_OWNER,
    "waist": NUTRITION_OWNER,
    "weight": NUTRITION_OWNER,
    "streak": LEAD_OWNER,
    "days_tracked": LEAD_OWNER,
    "level": LEAD_OWNER,
}

_USER_PK = "USER#matthew#SOURCE#{source}"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ── Small pure helpers ────────────────────────────────────────────────────────


def _num(v) -> Optional[float]:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _day(value) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _age_days(when: str, today: str) -> Optional[int]:
    a, b = _day(when), _day(today)
    return (b - a).days if a and b else None


def _fresh(when: str, today: str) -> bool:
    """A fact is worth a text only if it is recent AND not in the future."""
    age = _age_days(when, today)
    return age is not None and 0 <= age <= EVENT_FRESH_DAYS


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", str(text or "").strip().lower()).strip("-") or "unknown"


def _stdev(values: list) -> Optional[float]:
    """Population SD. None below two observations — a spread needs a spread."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5


def e1rm_lb(weight_kg, reps) -> Optional[float]:
    """Epley estimated 1RM in POUNDS — verbatim the site's strength surface.

    Same formula, same rep gate, same unit as ``site_api_training.strength_benchmarks``
    on purpose: the phone and the site are not allowed to tell two truths about the
    same lift, and a coach quoting a different 1RM than /cockpit/ is a trust bug, not
    a rounding one.
    """
    w = _num(weight_kg)
    r = _num(reps)
    if not w or w <= 0 or r is None:
        return None
    reps_i = int(r)
    if reps_i < PR_MIN_REPS or reps_i > PR_MAX_REPS:
        return None
    return (w * 2.2046226) * (1 + reps_i / 30.0)


# ── Trigger 1: the lift PR ────────────────────────────────────────────────────


def session_bests(workouts: list) -> dict:
    """{lift name: [{date, e1rm_lb, weight_kg, reps}]} — best set per lift per session.

    Keyed on the exercise NAME rather than the Hevy template id: the name is what a
    coach can actually say out loud, and a template swap for the same movement would
    otherwise reset a lift's whole history to "no baseline".
    """
    index: dict = {}
    for w in workouts or []:
        when = str(w.get("date") or str(w.get("sk", ""))[len("DATE#") :][:10] or "")[:10]
        if not _day(when):
            continue
        for ex in w.get("exercises") or []:
            name = str(ex.get("name") or ex.get("exercise_name") or "").strip()
            if not name:
                continue
            best = None
            for s in ex.get("sets") or []:
                est = e1rm_lb(s.get("weight_kg"), s.get("reps"))
                if est is not None and (best is None or est > best[0]):
                    best = (est, _num(s.get("weight_kg")), int(_num(s.get("reps")) or 0))
            if best is None:
                continue
            prior = index.setdefault(name, {})
            if when not in prior or best[0] > prior[when][0]:
                prior[when] = best
    return {
        name: [{"date": d, "e1rm_lb": v[0], "weight_kg": v[1], "reps": v[2]} for d, v in sorted(sessions.items())]
        for name, sessions in index.items()
    }


def detect_lift_pr(bests: dict, today: str) -> Optional[dict]:
    """The one lift whose latest session cleared its own noise band by the most.

    The threshold IS the personal variance: the standard deviation of that lift's
    session-to-session change in estimated 1RM, computed over the PRIOR sessions
    only (including the PR's own jump would let a big jump raise its own bar).
    """
    best_event = None
    for name, sessions in sorted((bests or {}).items()):
        if len(sessions) < PR_MIN_SESSIONS:
            continue
        latest = sessions[-1]
        if not _fresh(latest["date"], today):
            continue
        prior = sessions[:-1]
        prev_best = max(s["e1rm_lb"] for s in prior)
        prev_best_on = next(s["date"] for s in prior if s["e1rm_lb"] == prev_best)
        deltas = [prior[i + 1]["e1rm_lb"] - prior[i]["e1rm_lb"] for i in range(len(prior) - 1)]
        noise = _stdev(deltas) or 0.0
        margin = latest["e1rm_lb"] - prev_best
        if margin <= 0 or margin < PR_NOISE_K * noise:
            continue
        candidate = {
            "name": name,
            "margin": margin,
            "noise": noise,
            "prev_best": prev_best,
            "prev_best_on": prev_best_on,
            "latest": latest,
            "n": len(sessions),
        }
        if best_event is None or candidate["margin"] > best_event["margin"]:
            best_event = candidate
    if best_event is None:
        return None

    b = best_event
    latest = b["latest"]
    evidence = [
        f"Hevy, {latest['date']} — {b['name']}: top working set {round(latest['weight_kg'] or 0, 1)} kg "
        f"x {latest['reps']} reps, estimated 1RM {round(latest['e1rm_lb'])} lb (Epley).",
        f"His previous best estimated 1RM on {b['name']}: {round(b['prev_best'])} lb on {b['prev_best_on']}, "
        f"across {b['n']} logged sessions in the last {PR_LOOKBACK_DAYS} days.",
        f"Session-to-session variation in his own estimated 1RM on this lift: SD {round(b['noise'], 1)} lb "
        f"(n={b['n'] - 1} changes). Today clears the previous best by {round(b['margin'], 1)} lb — "
        f"more than that personal noise band, which is what makes it a real PR rather than a good day.",
    ]
    return _event(
        kind=KIND_LIFT_PR,
        event_id=f"{KIND_LIFT_PR}#{_slug(b['name'])}#{latest['date']}",
        provenance=coach_outbound.PROVENANCE_CELEBRATION,
        persona_id=LIFT_OWNER,
        evidence=evidence,
    )


# ── Trigger 2: an announced milestone (consumed, never re-derived) ─────────────


def detect_milestone(events: list, today: str) -> Optional[dict]:
    """The most recent announced ``MILESTONE#`` event that is still fresh.

    Read-only, and deliberately dumb: this function does not decide what a
    milestone is. ``health.milestone_ledger`` already did, with a trailing-mean
    window, a minimum n, a 12-day global cooldown, a write-once rung and its own
    spiral-breaker gate. Second-guessing it here would produce two platform
    opinions about the same crossing.
    """
    fresh = [e for e in (events or []) if e.get("event_date") and _fresh(str(e["event_date"]), today)]
    if not fresh:
        return None
    ev = sorted(fresh, key=lambda e: str(e["event_date"]))[-1]
    ladder = str(ev.get("ladder") or ev.get("category") or "")
    meas = ev.get("measurement") or {}
    evidence = [
        f"Milestone recorded {ev['event_date']}: {ev.get('label') or ev.get('milestone_id')} — {ev.get('description') or ''}".strip(),
    ]
    mean, n, window = _num(meas.get("mean")), _num(meas.get("n")), _num(meas.get("window_days"))
    if mean is not None and n is not None:
        evidence.append(
            f"The measurement behind it: trailing {int(window) if window else '?'}-day mean {round(mean, 1)} "
            f"over n={int(n)} readings. Quote the n if you quote the number."
        )
    return _event(
        kind=KIND_MILESTONE,
        event_id=f"{KIND_MILESTONE}#{ev.get('milestone_id') or _slug(str(ev.get('label')))}",
        provenance=coach_outbound.PROVENANCE_CELEBRATION,
        persona_id=MILESTONE_LADDER_OWNER.get(ladder, LEAD_OWNER),
        evidence=evidence,
    )


# ── Trigger 3: the recovery slide ─────────────────────────────────────────────


def detect_recovery_slide(recovery: dict, today: str) -> Optional[dict]:
    """Three consecutive days under HIS OWN p25 recovery band, or nothing.

    The event is keyed on the day the slide STARTED, which is what makes day four
    silent: a run that keeps running derives the same id it already spent.
    """
    series = sorted((d, v) for d, v in (recovery or {}).items() if _day(d) and _num(v) is not None)
    if len(series) < RECOVERY_MIN_N:
        return None  # no personal baseline ⇒ no personal threshold ⇒ no text
    band = percentile([_num(v) for _, v in series], RECOVERY_PERCENTILE)
    if band is None:
        return None
    if not _fresh(series[-1][0], today):
        return None  # the last thing Whoop recorded is too old to text about

    run: list = []
    for when, value in reversed(series):
        if _num(value) >= band:
            break
        if run and (_day(run[-1][0]) - _day(when)).days != 1:
            break  # a gap in the data is not a run of bad days
        run.append((when, _num(value)))
    if len(run) < RECOVERY_STREAK_DAYS:
        return None
    run.reverse()

    days = ", ".join(f"{d} {round(v)}%" for d, v in run)
    evidence = [
        f"Whoop recovery, the last {len(run)} recorded days: {days}.",
        f"His own {RECOVERY_PERCENTILE}th-percentile recovery over the trailing {RECOVERY_BASELINE_DAYS} days "
        f"is {round(band)}% (n={len(series)} recorded days) — that band is Matthew's, not a general threshold.",
        f"Every one of those {len(run)} consecutive days sits below it. Nothing here says WHY, and the data cannot.",
    ]
    return _event(
        kind=KIND_RECOVERY_SLIDE,
        event_id=f"{KIND_RECOVERY_SLIDE}#{run[0][0]}",
        provenance=coach_outbound.PROVENANCE_CONCERN,
        persona_id=RECOVERY_OWNER,
        evidence=evidence,
    )


# ── Candidates ────────────────────────────────────────────────────────────────


def _event(*, kind: str, event_id: str, provenance: str, persona_id: str, evidence: list) -> Optional[dict]:
    """Build one candidate — or None when there is nothing to stand on.

    The frame is rendered here so an evidence-less event cannot exist as a
    sendable object at all, rather than being caught by a check somebody later
    forgets to run.
    """
    body = "\n".join(f"- {line}" for line in evidence if line)
    frame = coach_outbound.event_frame(provenance, body)
    if not frame:
        return None
    return {
        "kind": kind,
        "event_id": event_id,
        "provenance": provenance,
        "persona_id": persona_id,
        "evidence": body,
        "frame": frame,
    }


def candidates(signals: dict, today: str) -> list:
    """Every event worth a text right now, highest provenance priority first.

    Ordering is the #2490 companion decision: five outbound features now contend
    for two daily slots, so a soft concern outranks a celebration inside one sweep
    and the last-to-fire feature is not permanently starved.
    """
    found = []
    for detector, arg in (
        (detect_recovery_slide, (signals or {}).get("recovery") or {}),
        (detect_lift_pr, (signals or {}).get("lift_bests") or {}),
        (detect_milestone, (signals or {}).get("milestones") or []),
    ):
        try:
            ev = detector(arg, today)
        except Exception as e:  # noqa: BLE001 — one bad detector must not silence the others
            logger.warning("[event-triggers] %s failed: %s", detector.__name__, e)
            ev = None
        if ev:
            found.append(ev)
    return sorted(found, key=lambda e: coach_outbound.priority(e["provenance"]))


# ── Fetch half (all the I/O lives here) ───────────────────────────────────────


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


def gather_signals(table, today: str) -> dict:
    """Read the three signal families. A family that fails to read is simply absent.

    Absent is safe here by construction: every detector above returns None on empty
    input, so a DynamoDB hiccup costs a text rather than producing a wrong one.
    """
    signals: dict = {"as_of": today}
    end = _day(today)
    if end is None:  # a date we cannot parse is a window we cannot draw — read nothing
        logger.warning("[event-triggers] unparseable evaluation date %r — no signals", today)
        return signals

    try:
        rows = _query_source(table, "whoop", (end - timedelta(days=RECOVERY_BASELINE_DAYS - 1)).isoformat(), today)
        signals["recovery"] = {
            str(r.get("sk", ""))[len("DATE#") :][:10]: _num(r.get("recovery_score"))
            for r in rows
            if _num(r.get("recovery_score")) is not None
        }
    except Exception as e:
        logger.warning("[event-triggers] recovery read failed: %s", e)

    try:
        workouts = _query_source(table, "hevy", (end - timedelta(days=PR_LOOKBACK_DAYS - 1)).isoformat(), today)
        signals["lift_bests"] = session_bests([w for w in workouts if w.get("source_workout_id") and not w.get("tombstone")])
    except Exception as e:
        logger.warning("[event-triggers] lift read failed: %s", e)

    try:
        from health.milestone_ledger import read_announced_events

        signals["milestones"] = read_announced_events(table, "USER#matthew")
    except Exception as e:
        logger.warning("[event-triggers] milestone ledger read failed: %s", e)

    return signals


def _celebration_allowed(table, today: str) -> bool:
    """The #1627 gate. Unreadable ⇒ not allowed: the breaker fails closed, always."""
    try:
        from coach import spiral_breaker

        allowed, _verdict = spiral_breaker.check_celebration_allowed("coach_event_outbound", now=_day(today), table=table)
        return bool(allowed)
    except Exception as e:
        logger.warning("[event-triggers] spiral breaker unavailable (holding celebration): %s", e)
        return False


# ── The sweep ─────────────────────────────────────────────────────────────────


def run_sweep(
    *,
    now_pt,
    table,
    seat: Callable,
    speak: Callable,
    chat_rows: Callable,
    tier: Optional[int] = None,
    signals: Optional[dict] = None,
) -> dict:
    """Detect → order → gate → claim → speak. At most ONE text per run.

    Every refusal below happens BEFORE the event is consumed and before the day's
    budget is spent, in deliberate order — a coach with no bot must not burn a slot,
    and a slide he is already ignoring must not consume its own event id. The two
    claims are the last thing that happens before inference (#1382's reserve-then-act
    idiom): a crash between generating and sending must never license a second send.

    EVERY return carries ``candidates`` — the number of events detected on this run,
    zero included. That count is what the caller emits as the sweep's liveness metric,
    and the reason it is on every branch rather than only the interesting ones: this
    feature's characteristic failure is INVISIBLE ABSENCE. A silently dead cron and a
    genuinely quiet Tuesday look identical from outside, and the difference between
    them is exactly "did this function report at all".
    """
    if coach_outbound.in_quiet_hours(now_pt):
        logger.info("[event-triggers] sweep suppressed — quiet hours (%s PT)", getattr(now_pt, "hour", "?"))
        return {"ok": True, "reason": "quiet hours", "candidates": 0}

    from coach import coach_chat

    if tier is not None and tier >= getattr(coach_chat, "_PAUSE_TIER", 2):
        return {"ok": True, "reason": "budget", "candidates": 0}

    today = now_pt.strftime("%Y-%m-%d")
    found = candidates(gather_signals(table, today) if signals is None else signals, today)
    n = len(found)
    if not found:
        return {"ok": True, "reason": "no events", "candidates": 0}

    for ev in found:
        token, chat_id = seat(ev["persona_id"])
        if not token or chat_id is None:
            logger.info("[event-triggers] %s dark — bot not registered for %s", ev["kind"], ev["persona_id"])
            continue
        if coach_outbound.two_consecutive_ignored(chat_rows(ev["persona_id"]), ev["provenance"]):
            logger.info("[event-triggers] %s skipped — his last two went unanswered", ev["kind"])
            continue
        if ev["provenance"] == coach_outbound.PROVENANCE_CELEBRATION and not _celebration_allowed(table, today):
            logger.info("[event-triggers] celebration held — spiral breaker is not clear")
            continue
        if not coach_outbound.claim_event(table, ev["event_id"]):
            continue  # this exact fact already produced a text (or the ledger is unreadable)
        if not coach_outbound.claim_outbound(table, today, provenance=ev["provenance"], now_pt=now_pt):
            return {"ok": True, "reason": "capped", "event_id": ev["event_id"], "candidates": n}
        return {**speak(ev, token, chat_id), "candidates": n}

    return {"ok": True, "reason": "nothing sendable", "candidates": n}
