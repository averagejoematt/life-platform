"""development_profile.py — a PRIVATE personal-development profile: per-domain status, its evidence, no roll-up (#6294).

WHAT IT IS. A pure assembly over records the platform already holds. Nine life domains (`DOMAINS`); for each one a
plain status, the basis it rests on, the evidence items behind it (each with its date, source and evidence kind),
what was NOT observed, his last stated view of the line, and the exact call that records a disagreement. There is
no overall score, level, percentage or ranking across domains, and nothing here moves a score, an XP figure, a
Walker effect, a page or a coach prompt. The one caller is the owner's MCP read tool `get_development_profile`.

Owner rulings 2026-11-26 this module encodes:
  * "Use direct self-report, documented actions, owner-confirmed insights and appropriate established measures.
    Allow unknown, mixed and contradictory results. Do not invent objective psychological scores."
  * "Do not create unvalidated psychological scores or diagnose conditions from journal language."
  * "Missing qualitative information must not automatically mean deterioration."
  * "My explicit self-reports take precedence over AI-inferred ratings." Here the model's reading is not a
    fallback at all: a model's reading of his prose is never evidence in this profile. Only the self-report fields
    of `common.inferred_fields.SELF_REPORT_FIELDS` are read; the model score beside them is never touched.
  * Optional questionnaires (WHO-5, a loneliness scale) are DEFERRED. `OWNER_SELF_REPORT_MEASURES` is the named,
    empty seam for them; nothing fills it and no rule reads a value from it.

STATUSES: improving · steady · harder · mixed · not_enough_to_say. Each domain's status is the combination of its
indicators' directions (`combine`): no sufficient indicator -> not_enough_to_say; an indicator that is itself mixed,
or one better and one worse -> mixed; otherwise better -> improving, worse -> harder, all same -> steady.

THE RULES (deterministic; the windows end on `today`, inclusive; a recent window and the equal window before it)

  MEASURED (physical capacity, behavioural consistency) — 28-day windows, minimum 14 eligible days in EACH.
    An eligible day is an OBSERVED day (a wearable row, or a recorded session) that is not a planned pause — a sick
    day or a travel day, the same two causes `content.engagement_core` excuses. A day with no wearable row and no
    session is not observed: it is out of the denominator, never a zero.
      zone 2 minutes / observed week     better/worse when the change is >= max(10 min, 15% of the prior figure)
      strength (best Epley e1RM per lift, lifts performed in both windows, at least 3 lifts): a lift moved when
                                         its best changed >= 2.5%; better/worse when lifts up - lifts down >= 2
                                         (or the reverse); up and down both present inside that margin -> mixed
      training days / eligible week      better/worse at a change >= 0.5 days per week
      habit completion (days with a habit row, planned pauses excluded): better/worse at >= 5 points
      body weight                        SHOWN, never scored: whether a change is progress depends on his goal
  COUNTED (learning and experimentation, self-understanding) — 56-day windows, COUNTS ONLY.
    Learning: experiments started, experiments concluded, recommendations he answered, recommendation outcomes
    recorded, decisions with a recorded outcome. Self-understanding: hypotheses he confirmed, corrected, rejected or
    marked not interested; reviewed personal records he confirmed as insights or kept as rejected interpretations.
    better only when the recent total exceeds the prior total by >= max(3, 50% of the prior). A recent total that
    is LOWER by that margin is not read as decline (fewer records is not evidence of less learning): it reads
    not_enough_to_say and says so. Inside the margin: not_enough_to_say. Journaling volume, conversation counts
    and entry counts are never counted. Open hypotheses are LISTED under self-understanding as open questions,
    labelled as such; they are never evidence.
  OWN REPORT / OWNER-CONFIRMED (emotional wellbeing, social connection, meaning, confidence, coping)
    Ratings (emotional wellbeing only): his own journal ratings (mood, energy, stress; 1-5) and his evening
    check-in ratings (mood, stress; 0-4), one value per day (the day's mean). 28-day windows, at least 8 rated days
    in EACH; better/worse at a mean change >= 0.5 (stress: lower is better).
    Statements: reviewed personal records (`owner_reviewed_at` stamped, evidence_kind in
    `platform_memory.LIFE_DOMAIN_TAGGABLE_KINDS`) he tagged to the domain (`life_domains`), dated to the day by their
    `event_date`. 90-day windows, at least 3 dated statements in EACH. His `life_direction` on the recent window's
    statements decides: better and harder both present -> mixed (both shown); better -> better; harder -> worse;
    only same/unclear -> same. A record dated coarser than a day is shown but not windowed.
    ai_interpretation, competing_hypothesis, rejected_interpretation and observed_pattern are never evidence here.

ABSENCE NEVER PRODUCES `harder`. Every "worse" above needs the minimum observations in both windows, or his own
statement that it was harder. A failed read is named in `not_observed` and contributes nothing, never a zero.

NOT INPUTS, EVER: journaling frequency, number of entries or conversations, sentiment, and every `enriched_*`
field. The assembly reads named fields only (`tests/test_development_profile_6294.py` plants them and proves the
profile does not change).

Pure: no I/O, no clock — `today` and every input are passed in.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional

from ai.platform_memory import LIFE_DIRECTIONS, LIFE_DOMAIN_TAGGABLE_KINDS, LIFE_DOMAINS
from common.inferred_fields import SELF_REPORT_FIELDS
from common.pacific_time import parse_day_key

ISSUE = "#6294"
RULES_VERSION = 1

# ── statuses, bases, directions ───────────────────────────────────────────────────────────────
IMPROVING, STEADY, HARDER, MIXED, NOT_ENOUGH = "improving", "steady", "harder", "mixed", "not_enough_to_say"
STATUSES: tuple[str, ...] = (IMPROVING, STEADY, HARDER, MIXED, NOT_ENOUGH)

MEASURED, COUNTED, OWN_REPORT, OWNER_CONFIRMED = "measured", "counted_from_records", "own_report", "owner_confirmed_records"
BASES: tuple[str, ...] = (MEASURED, COUNTED, OWN_REPORT, OWNER_CONFIRMED)

BETTER, SAME, WORSE, MIXED_DIR, INSUFFICIENT = "better", "same", "worse", "mixed", "insufficient"

# ── the stated windows, minimums and margins ──────────────────────────────────────────────────
MEASURED_WINDOW_DAYS = 28
MEASURED_MIN_DAYS = 14
ZONE2_MARGIN_MIN = 10.0
ZONE2_MARGIN_FRACTION = 0.15
STRENGTH_MIN_LIFTS = 3
STRENGTH_MOVE_FRACTION = 0.025
STRENGTH_NET_LIFTS = 2
TRAINING_DAYS_MARGIN = 0.5
HABIT_MARGIN = 0.05

COUNT_WINDOW_DAYS = 56
COUNT_MARGIN_MIN = 3
COUNT_MARGIN_FRACTION = 0.5

RATING_WINDOW_DAYS = 28
RATING_MIN_DAYS = 8
RATING_MARGIN = 0.5

STATEMENT_WINDOW_DAYS = 90
STATEMENT_MIN = 3

STATEMENT_CHARS = 240

#: The seam for owner self-report measures (WHO-5, a loneliness scale): DEFERRED by owner ruling 2026-11-26.
#: Empty on purpose. Filling it is its own reviewed change; no rule below reads a value from it.
OWNER_SELF_REPORT_MEASURES: dict[str, tuple[str, ...]] = {}

#: Where a disagreement (or agreement) with one profile line is stored: the corrections ledger, on a surface no
#: coach prompt reads (`coach.coach_corrections.OWNER_FACING_SURFACES` does not include it).
PROFILE_SURFACE = "development_profile"
SIGNAL_PREFIX = "development_profile:"
AGREE_ERROR_CLASS = "defense-held"  # the ledger's "reviewed, and the claim held up"
DISAGREE_ERROR_CLASS = "framing"

# ── the domain registry ───────────────────────────────────────────────────────────────────────
DOMAINS: dict[str, dict[str, Any]] = {
    "physical_capacity": {
        "name": "Physical capacity",
        "definition": "What his body can do: strength on the lifts he repeats, aerobic work in zone 2, body weight shown.",
        "basis": MEASURED,
        "sources": ("hevy lifts (best e1RM per lift)", "zone 2 minutes (training.zone2_minutes)", "withings weight (shown only)"),
    },
    "behavioural_consistency": {
        "name": "Behavioural consistency",
        "definition": "Whether he does what he set out to do: days trained and habits completed, planned pauses excluded.",
        "basis": MEASURED,
        "sources": ("recorded training sessions", "habitify completion"),
    },
    "learning_and_experimentation": {
        "name": "Learning and experimentation",
        "definition": "Trying things on purpose and closing the loop: experiments run and concluded, advice answered, outcomes recorded.",
        "basis": COUNTED,
        "sources": ("experiments", "recommendation record (answers, outcomes)", "decisions with an outcome"),
    },
    "self_understanding": {
        "name": "Self-understanding",
        "definition": "Interpretations about him that he has looked at and confirmed, corrected or rejected.",
        "basis": COUNTED,
        "sources": ("personal hypotheses (his views)", "reviewed personal records (confirmed insights, rejected interpretations)"),
    },
    "emotional_wellbeing": {
        "name": "Emotional wellbeing",
        "definition": "How he says he feels: his own mood, energy and stress ratings, and his own statements.",
        "basis": OWN_REPORT,
        "sources": ("journal self-ratings (never the model's)", "evening check-in ratings", "reviewed personal records he tagged"),
    },
    "social_connection": {
        "name": "Social connection and belonging",
        "definition": "Relationships and belonging, in his own account and in events he confirmed.",
        "basis": OWNER_CONFIRMED,
        "sources": ("reviewed personal records he tagged",),
    },
    "meaning_and_fulfilment": {
        "name": "Meaning and fulfilment",
        "definition": "Whether what he does feels worthwhile, in his own dated account.",
        "basis": OWNER_CONFIRMED,
        "sources": ("reviewed personal records he tagged",),
    },
    "confidence_and_agency": {
        "name": "Confidence and agency",
        "definition": "Situations he approached and decisions he made, as he describes them.",
        "basis": OWNER_CONFIRMED,
        "sources": ("reviewed personal records he tagged",),
    },
    "coping_and_flexibility": {
        "name": "Coping and flexibility",
        "definition": "Real examples he describes of handling a hard moment or adapting a plan.",
        "basis": OWNER_CONFIRMED,
        "sources": ("reviewed personal records he tagged",),
    },
}
assert tuple(DOMAINS) == LIFE_DOMAINS, "the domain registry and platform_memory.LIFE_DOMAINS must be the same keys, in order"

SELF_REPORT_DOMAINS = tuple(k for k, d in DOMAINS.items() if d["basis"] in (OWN_REPORT, OWNER_CONFIRMED))


# ── small helpers ─────────────────────────────────────────────────────────────────────────────


def _day(value: Any) -> Optional[date]:
    s = str(value or "")[:10]
    return parse_day_key(s) if len(s) == 10 else None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _require_day(value: str) -> date:
    d = parse_day_key(value)
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {value!r}")
    return d


def windows(today: str, days: int) -> dict[str, tuple[str, str]]:
    """The recent window (ending on `today`, inclusive) and the equal window before it, as day keys."""
    t = _require_day(today)
    return {
        "recent": ((t - timedelta(days=days - 1)).isoformat(), t.isoformat()),
        "prior": ((t - timedelta(days=2 * days - 1)).isoformat(), (t - timedelta(days=days)).isoformat()),
    }


def _which(d: Optional[date], wins: Mapping[str, tuple[str, str]]) -> Optional[str]:
    if d is None:
        return None
    s = d.isoformat()
    for name, (lo, hi) in wins.items():
        if lo <= s <= hi:
            return name
    return None


def _days_in(lo: str, hi: str) -> list[str]:
    a, b = _require_day(lo), _require_day(hi)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _clip(text: Any) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= STATEMENT_CHARS else s[: STATEMENT_CHARS - 1] + "…"


def _indicator(key: str, label: str, direction: str, reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"key": key, "label": label, "direction": direction, "reason": reason, "evidence": evidence}


def _compare(recent: float, prior: float, margin: float, *, lower_is_better: bool = False) -> str:
    delta = recent - prior
    if abs(delta) < margin:
        return SAME
    up = delta > 0
    return BETTER if up != lower_is_better else WORSE


def combine(directions: Iterable[str]) -> str:
    """The domain status from its indicators' directions. Insufficient indicators are ignored; none left -> not enough."""
    got = [d for d in directions if d != INSUFFICIENT]
    if not got:
        return NOT_ENOUGH
    if MIXED_DIR in got or (BETTER in got and WORSE in got):
        return MIXED
    if BETTER in got:
        return IMPROVING
    if WORSE in got:
        return HARDER
    return STEADY


# ── measured indicators ───────────────────────────────────────────────────────────────────────


def _excluded(inputs: Mapping[str, Any]) -> dict[str, set[str]]:
    ex = inputs.get("excluded_days") or {}
    return {k: {str(d)[:10] for d in (ex.get(k) or [])} for k in ("sick", "travel")}


def _eligible_days(
    inputs: Mapping[str, Any], wins: Mapping[str, tuple[str, str]], extra_observed: Iterable[str]
) -> dict[str, dict[str, Any]]:
    observed = {str(d)[:10] for d in (inputs.get("observed_days") or [])} | {str(d)[:10] for d in extra_observed}
    ex = _excluded(inputs)
    paused = ex["sick"] | ex["travel"]
    out = {}
    for name, (lo, hi) in wins.items():
        span = _days_in(lo, hi)
        obs = [d for d in span if d in observed]
        out[name] = {
            "days": [d for d in obs if d not in paused],
            "observed": len(obs),
            "excluded_sick": sum(1 for d in obs if d in ex["sick"]),
            "excluded_travel": sum(1 for d in obs if d in ex["travel"] and d not in ex["sick"]),
        }
    return out


def _read_failed(inputs: Mapping[str, Any], *names: str) -> list[str]:
    failed = inputs.get("read_failed") or {}
    return [n for n in names if n in failed]


def _failed_indicator(key: str, label: str, failed: list[str]) -> dict[str, Any]:
    return _indicator(key, label, INSUFFICIENT, f"read failed: {', '.join(failed)} — not observed, never a zero", {})


def _zone2(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "zone2_minutes_per_week", "Zone 2 minutes per observed week"
    failed = _read_failed(inputs, "zone2_sessions", "observed_days")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    sessions = [(str(s.get("date"))[:10], _num(s.get("minutes")) or 0.0) for s in inputs.get("zone2_sessions") or []]
    elig = _eligible_days(inputs, wins, (d for d, _m in sessions))
    fig, n = {}, {}
    for name in wins:
        days = set(elig[name]["days"])
        n[name] = len(days)
        fig[name] = round(sum(m for d, m in sessions if d in days) / len(days) * 7, 1) if days else None
    ev = _measured_evidence(today, wins, n, fig, "min/week", "training.zone2_minutes counted sessions", elig, label)
    if min(n.values()) < MEASURED_MIN_DAYS:
        return _indicator(key, label, INSUFFICIENT, f"fewer than {MEASURED_MIN_DAYS} eligible observed days in a window ({n})", ev)
    margin = max(ZONE2_MARGIN_MIN, ZONE2_MARGIN_FRACTION * float(fig["prior"] or 0.0))
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), margin)
    return _indicator(key, label, direction, f"change against a margin of {round(margin, 1)} min/week", ev)


def _training_days(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "training_days_per_week", "Training days per eligible week"
    failed = _read_failed(inputs, "training_days", "observed_days")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    trained = {str(d)[:10] for d in inputs.get("training_days") or []}
    elig = _eligible_days(inputs, wins, trained)
    fig, n = {}, {}
    for name in wins:
        days = set(elig[name]["days"])
        n[name] = len(days)
        fig[name] = round(len(days & trained) / len(days) * 7, 2) if days else None
    ev = _measured_evidence(today, wins, n, fig, "days/week", "recorded training sessions (hevy + counted sessions)", elig, label)
    if min(n.values()) < MEASURED_MIN_DAYS:
        return _indicator(key, label, INSUFFICIENT, f"fewer than {MEASURED_MIN_DAYS} eligible observed days in a window ({n})", ev)
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), TRAINING_DAYS_MARGIN)
    return _indicator(key, label, direction, f"change against a margin of {TRAINING_DAYS_MARGIN} days/week", ev)


def _habits(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "habit_completion", "Habit completion on days with a habit record"
    failed = _read_failed(inputs, "habit_days")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    ex = _excluded(inputs)
    paused = ex["sick"] | ex["travel"]
    per_day: dict[str, list[float]] = {}
    for row in inputs.get("habit_days") or []:
        d = _day(row.get("date"))
        v = _num(row.get("completion_pct"))
        if d is None or v is None or _which(d, wins) is None or d.isoformat() in paused:
            continue
        per_day.setdefault(d.isoformat(), []).append(v)
    vals: dict[str, list[float]] = {name: [] for name in wins}
    for day, vs in per_day.items():  # one value per day: two rows for one day are one observation
        vals[str(_which(_day(day), wins))].append(sum(vs) / len(vs))
    n = {name: len(v) for name, v in vals.items()}
    fig = {name: (round(sum(v) / len(v), 3) if v else None) for name, v in vals.items()}
    ev = {
        "date": today,
        "source": "habitify completion_pct (pending-aware), sick and travel days excluded",
        "evidence_kind": "measured",
        "statement": f"{label}: recent {fig['recent']} over {n['recent']} days, prior {fig['prior']} over {n['prior']} days (0-1)",
        "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
        "n": n,
        "figure": {**fig, "unit": "completion fraction"},
        "counts_toward_status": True,
    }
    if min(n.values()) < MEASURED_MIN_DAYS:
        return _indicator(key, label, INSUFFICIENT, f"fewer than {MEASURED_MIN_DAYS} habit-record days in a window ({n})", ev)
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), HABIT_MARGIN)
    return _indicator(key, label, direction, f"change against a margin of {HABIT_MARGIN}", ev)


def _strength(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "strength_best_e1rm", "Best estimated 1RM per lift, lifts performed in both windows"
    failed = _read_failed(inputs, "lift_sessions")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    best: dict[str, dict[str, float]] = {}
    names: dict[str, str] = {}
    sessions = {name: 0 for name in wins}
    for s in inputs.get("lift_sessions") or []:
        w = _which(_day(s.get("date")), wins)
        v = _num(s.get("best_e1rm_lb"))
        ident = str(s.get("identity") or "")
        if w is None or v is None or v <= 0 or not ident:
            continue
        sessions[w] += 1
        names.setdefault(ident, str(s.get("name") or ident))
        slot = best.setdefault(ident, {})
        slot[w] = max(slot.get(w, 0.0), v)
    compared = []
    for ident, slot in sorted(best.items()):
        if "recent" in slot and "prior" in slot:
            change = (slot["recent"] - slot["prior"]) / slot["prior"]
            moved = "up" if change >= STRENGTH_MOVE_FRACTION else "down" if change <= -STRENGTH_MOVE_FRACTION else "flat"
            compared.append(
                {"lift": names[ident], "prior_lb": round(slot["prior"], 1), "recent_lb": round(slot["recent"], 1), "moved": moved}
            )
    ups = sum(1 for c in compared if c["moved"] == "up")
    downs = sum(1 for c in compared if c["moved"] == "down")
    ev = {
        "date": today,
        "source": "hevy (Epley e1RM, mcp.strength_helpers.extract_hevy_sessions)",
        "evidence_kind": "measured",
        "statement": f"{label}: {len(compared)} lifts compared — {ups} up, {downs} down, {len(compared) - ups - downs} within ±{STRENGTH_MOVE_FRACTION:.1%}",
        "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
        "n": {"lift_sessions": sessions, "lifts_compared": len(compared)},
        "figure": {"lifts": compared, "unit": "lb"},
        "counts_toward_status": True,
    }
    if len(compared) < STRENGTH_MIN_LIFTS:
        return _indicator(
            key, label, INSUFFICIENT, f"fewer than {STRENGTH_MIN_LIFTS} lifts performed in both windows ({len(compared)})", ev
        )
    if ups - downs >= STRENGTH_NET_LIFTS:
        direction = BETTER
    elif downs - ups >= STRENGTH_NET_LIFTS:
        direction = WORSE
    elif ups and downs:
        direction = MIXED_DIR
    else:
        direction = SAME
    return _indicator(key, label, direction, f"net lifts moved against a margin of {STRENGTH_NET_LIFTS}", ev)


def _weight_figure(inputs: Mapping[str, Any], today: str) -> Optional[dict[str, Any]]:
    """Body weight, shown beside the capacity figures and never scored (whether a change is progress is his goal's call)."""
    if _read_failed(inputs, "weight"):
        return None
    wins = windows(today, MEASURED_WINDOW_DAYS)
    vals: dict[str, list[float]] = {name: [] for name in wins}
    for row in inputs.get("weight") or []:
        w = _which(_day(row.get("date")), wins)
        v = _num(row.get("weight_lbs"))
        if w is not None and v is not None:
            vals[w].append(v)
    n = {k: len(v) for k, v in vals.items()}
    if not any(n.values()):
        return None
    fig = {k: (round(sum(v) / len(v), 1) if v else None) for k, v in vals.items()}
    return {
        "date": today,
        "source": "withings weight_lbs",
        "evidence_kind": "measured",
        "statement": f"Mean weigh-in: recent {fig['recent']} lb ({n['recent']} weigh-ins), prior {fig['prior']} lb ({n['prior']}) — shown, not scored",
        "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
        "n": n,
        "figure": {**fig, "unit": "lb"},
        "counts_toward_status": False,
    }


def _measured_evidence(today, wins, n, fig, unit, source, elig, label) -> dict[str, Any]:
    return {
        "date": today,
        "source": source,
        "evidence_kind": "measured",
        "statement": f"{label}: recent {fig['recent']} over {n['recent']} eligible days, prior {fig['prior']} over {n['prior']} eligible days",
        "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
        "n": n,
        "excluded": {k: {"sick": elig[k]["excluded_sick"], "travel": elig[k]["excluded_travel"]} for k in wins},
        "figure": {**fig, "unit": unit},
        "counts_toward_status": True,
    }


# ── counted indicators ────────────────────────────────────────────────────────────────────────


def _count_events(events: list[tuple[str, Optional[date]]], today: str) -> dict[str, dict[str, int]]:
    wins = windows(today, COUNT_WINDOW_DAYS)
    out: dict[str, dict[str, int]] = {}
    for what, d in events:
        w = _which(d, wins)
        slot = out.setdefault(what, {"recent": 0, "prior": 0})
        if w:
            slot[w] += 1
    return out


def _counted_indicator(
    key: str, label: str, counts: dict[str, dict[str, int]], today: str, source: str, failed: list[str]
) -> dict[str, Any]:
    wins = windows(today, COUNT_WINDOW_DAYS)
    recent = sum(c["recent"] for c in counts.values())
    prior = sum(c["prior"] for c in counts.values())
    margin = max(COUNT_MARGIN_MIN, COUNT_MARGIN_FRACTION * prior)
    ev = {
        "date": today,
        "source": source,
        "evidence_kind": "counted",
        "statement": f"{label}: {recent} in the recent {COUNT_WINDOW_DAYS} days, {prior} in the {COUNT_WINDOW_DAYS} before",
        "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
        "n": {"recent": recent, "prior": prior},
        "figure": {"by_kind": counts, "unit": "records"},
        "counts_toward_status": True,
    }
    if failed:
        return _indicator(key, label, INSUFFICIENT, f"read failed: {', '.join(failed)} — counts would be incomplete", ev)
    if recent - prior >= margin:
        return _indicator(key, label, BETTER, f"recent exceeds prior by >= {margin:g}", ev)
    if prior - recent >= margin:
        return _indicator(key, label, INSUFFICIENT, "fewer records recently — fewer records is not read as decline", ev)
    return _indicator(key, label, INSUFFICIENT, f"recent and prior within the margin of {margin:g} — counts alone cannot say more", ev)


def _learning(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    events: list[tuple[str, Optional[date]]] = []
    for e in inputs.get("experiments") or []:
        events.append(("experiments_started", _day(e.get("start_date"))))
        if e.get("end_date") and str(e.get("status") or "active") != "active":
            events.append(("experiments_concluded", _day(e.get("end_date"))))
    for r in inputs.get("recommendations") or []:
        if r.get("response") not in (None, "", "not_recorded"):
            events.append(("recommendations_answered", _day(r.get("response_recorded_at"))))
        outcome = r.get("outcome") or {}
        if outcome:
            events.append(("recommendation_outcomes_recorded", _day(outcome.get("recorded_at"))))
    for dcs in inputs.get("decisions") or []:
        if dcs.get("outcome_date"):
            events.append(("decisions_with_outcome", _day(dcs.get("outcome_date"))))
    counts = _count_events(events, today)
    failed = _read_failed(inputs, "experiments", "recommendations", "decisions")
    src = "experiments (EXP#), the recommendation record (answers, outcomes), decisions (outcome_date)"
    return _counted_indicator("learning_records", "Experiments, answered advice and recorded outcomes", counts, today, src, failed)


_VIEW_COUNT = {"confirm": "hypotheses_confirmed", "correct": "hypotheses_corrected", "reject": "hypotheses_rejected"}


def _self_understanding(inputs: Mapping[str, Any], today: str) -> tuple[dict[str, Any], list[dict[str, Any]], Optional[dict[str, Any]]]:
    events: list[tuple[str, Optional[date]]] = []
    open_questions = []
    for v in inputs.get("hypotheses") or []:
        for line in v.get("history") or []:
            if line.get("kind") == "owner_view" and line.get("view"):
                events.append((_VIEW_COUNT.get(str(line["view"]), "hypotheses_marked_not_interested"), _day(line.get("recorded_at"))))
        if v.get("open"):
            open_questions.append(
                {
                    "hypothesis_id": v.get("hypothesis_id"),
                    "question": _clip(v.get("question")),
                    "status": v.get("status"),
                    "evidence_kind": "open_question",
                    "label": "an open question about him — not evidence, not a finding",
                    "counts_toward_status": False,
                }
            )
    by_kind: dict[str, int] = {}
    for rec in _reviewed_records(inputs):
        kind = str(rec.get("evidence_kind"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind == "confirmed_insight":
            events.append(("insights_confirmed", _day(rec.get("owner_reviewed_at"))))
        elif kind == "rejected_interpretation":
            events.append(("interpretations_rejected", _day(rec.get("owner_reviewed_at"))))
    counts = _count_events(events, today)
    failed = _read_failed(inputs, "hypotheses", "personal_records")
    src = "personal hypotheses (his owner_view events), reviewed personal records (confirmed_insight, rejected_interpretation)"
    ind = _counted_indicator("interpretations_reviewed", "Interpretations he confirmed, corrected or rejected", counts, today, src, failed)
    tally = None
    if by_kind:
        tally = {
            "date": today,
            "source": "reviewed personal records (all time), by evidence kind",
            "evidence_kind": "counted",
            "statement": "Reviewed personal records by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items())),
            "n": sum(by_kind.values()),
            "figure": {"by_kind": by_kind, "unit": "records"},
            "counts_toward_status": False,
        }
    return ind, open_questions, tally


# ── own report and owner-confirmed records ────────────────────────────────────────────────────


def _reviewed_records(inputs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out = []
    for r in inputs.get("personal_records") or []:
        if not isinstance(r, Mapping) or r.get("deleted_at") or r.get("tombstone") or not r.get("owner_reviewed_at"):
            continue
        parts = str(r.get("sk") or "").split("#")
        cat = r.get("category") or (parts[1] if len(parts) > 1 else None)
        if cat != "personal_record":
            continue
        out.append(r)
    return out


def _statements(inputs: Mapping[str, Any], domain: str) -> list[Mapping[str, Any]]:
    """Records that may be evidence about `domain`: reviewed, his own words or confirmed, tagged to it."""
    return [
        r
        for r in _reviewed_records(inputs)
        if r.get("evidence_kind") in LIFE_DOMAIN_TAGGABLE_KINDS and domain in (r.get("life_domains") or [])
    ]


def _statement_item(r: Mapping[str, Any], dated: bool) -> dict[str, Any]:
    direction = r.get("life_direction") if r.get("life_direction") in LIFE_DIRECTIONS else "unclear"
    return {
        "date": r.get("event_date") or "unknown",
        "date_precision": r.get("event_date_precision") or ("unknown" if not r.get("event_date") else None),
        "source": f"personal_record {r.get('sk')}",
        "evidence_kind": r.get("evidence_kind"),
        "statement": _clip(r.get("summary") or r.get("text")),
        "his_direction": direction,
        "owner_reviewed_at": r.get("owner_reviewed_at"),
        "counts_toward_status": dated,
    }


def _statement_indicator(inputs: Mapping[str, Any], domain: str, today: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    key, label = "his_statements", "His own reviewed statements tagged to this domain"
    wins = windows(today, STATEMENT_WINDOW_DAYS)
    items, by_win = [], {"recent": [], "prior": []}  # type: ignore[var-annotated]
    for r in _statements(inputs, domain):
        d = _day(r.get("event_date")) if (r.get("event_date_precision") or "day") == "day" else None
        w = _which(d, wins)
        items.append(_statement_item(r, w is not None))
        if w:
            by_win[w].append(items[-1])
    n = {k: len(v) for k, v in by_win.items()}
    failed = _read_failed(inputs, "personal_records")
    if failed:
        return _failed_indicator(key, label, failed), items
    if min(n.values()) < STATEMENT_MIN:
        return (
            _indicator(
                key,
                label,
                INSUFFICIENT,
                f"fewer than {STATEMENT_MIN} statements dated to the day in a {STATEMENT_WINDOW_DAYS}-day window ({n})",
                {},
            ),
            items,
        )
    dirs = {i["his_direction"] for i in by_win["recent"]}
    if "better" in dirs and "harder" in dirs:
        return _indicator(key, label, MIXED_DIR, "his recent statements point both ways — both are shown", {}), items
    if "better" in dirs:
        return _indicator(key, label, BETTER, "his recent statements say better", {}), items
    if "harder" in dirs:
        return _indicator(key, label, WORSE, "his recent statements say harder", {}), items
    return _indicator(key, label, SAME, "his recent statements say about the same, or do not say", {}), items


#: The rating indicators: (key, label, row family, metric or field, scale note, lower_is_better).
_RATINGS = (
    ("journal_mood", "Journal mood, his own rating (1-5)", "journal", "mood", False),
    ("journal_energy", "Journal energy, his own rating (1-5)", "journal", "energy", False),
    ("journal_stress", "Journal stress, his own rating (1-5; lower is better)", "journal", "stress", True),
    ("checkin_mood", "Evening check-in mood (0-4)", "evening", "mood", False),
    ("checkin_stress", "Evening check-in stress (0-4; lower is better)", "evening", "stress", True),
)


def _self_rating(row: Mapping[str, Any], family: str, metric: str) -> Optional[float]:
    """His own rating only. The journal's model score beside it is never read (owner ruling 2026-11-26)."""
    if family == "evening":
        return _num(row.get(metric))
    for field in SELF_REPORT_FIELDS[metric]:
        v = _num(row.get(field))
        if v is not None:
            return v
    return None


def _rating_indicators(inputs: Mapping[str, Any], today: str) -> list[dict[str, Any]]:
    wins = windows(today, RATING_WINDOW_DAYS)
    rows = {"journal": inputs.get("journal_entries") or [], "evening": inputs.get("evening_checkins") or []}
    read_name = {"journal": "journal_entries", "evening": "evening_checkins"}
    out = []
    for key, label, family, metric, lower in _RATINGS:
        failed = _read_failed(inputs, read_name[family])
        if failed:
            out.append(_failed_indicator(key, label, failed))
            continue
        per_day: dict[str, list[float]] = {}
        for r in rows[family]:
            d = _day(r.get("date") or str(r.get("sk") or "")[5:15])
            v = _self_rating(r, family, metric)
            if d is not None and v is not None and _which(d, wins):
                per_day.setdefault(d.isoformat(), []).append(v)
        vals: dict[str, list[float]] = {"recent": [], "prior": []}
        for day, vs in per_day.items():
            w = _which(_day(day), wins)
            if w:
                vals[w].append(sum(vs) / len(vs))
        n = {k: len(v) for k, v in vals.items()}
        if not any(n.values()):
            out.append(_indicator(key, label, INSUFFICIENT, "no rating of his in either window", {}))
            continue
        fig = {k: (round(sum(v) / len(v), 2) if v else None) for k, v in vals.items()}
        ev = {
            "date": today,
            "source": "notion journal self-rating fields" if family == "journal" else "evening check-in",
            "evidence_kind": "self_report",
            "statement": f"{label}: recent mean {fig['recent']} over {n['recent']} rated days, prior {fig['prior']} over {n['prior']}",
            "window": {k: {"start": lo, "end": hi} for k, (lo, hi) in wins.items()},
            "n": n,
            "figure": {**fig, "unit": "his rating"},
            "counts_toward_status": True,
        }
        if min(n.values()) < RATING_MIN_DAYS:
            out.append(_indicator(key, label, INSUFFICIENT, f"fewer than {RATING_MIN_DAYS} rated days in a window ({n})", ev))
            continue
        direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), RATING_MARGIN, lower_is_better=lower)
        out.append(_indicator(key, label, direction, f"mean change against a margin of {RATING_MARGIN}", ev))
    return out


# ── owner views and the disagreement door ─────────────────────────────────────────────────────


def signal_for(domain: str) -> str:
    return f"{SIGNAL_PREFIX}{domain}"


def how_to_disagree(domain: str) -> dict[str, Any]:
    return {
        "tool": "log_coach_correction",
        "arguments": {
            "signal": signal_for(domain),
            "surface": PROFILE_SURFACE,
            "correction": "<what is wrong with this line and what it should say, in his words>",
            "error_class": DISAGREE_ERROR_CLASS,
        },
        "to_agree_instead": {"error_class": AGREE_ERROR_CLASS, "correction": "<that the line is right, in his words>"},
        "where_it_goes": f"the corrections ledger on the '{PROFILE_SURFACE}' surface, which no coach prompt reads",
    }


def last_owner_view(corrections: Iterable[Mapping[str, Any]], domain: str) -> Optional[dict[str, Any]]:
    mine = [
        c
        for c in corrections or []
        if (c.get("item_ref") or {}).get("surface") == PROFILE_SURFACE and (c.get("item_ref") or {}).get("signal") == signal_for(domain)
    ]
    if not mine:
        return None
    c = max(mine, key=lambda r: (str(r.get("created_at") or ""), str(r.get("sk") or "")))
    sk = str(c.get("sk") or "")
    return {
        "date": sk.split("#")[1] if sk.count("#") >= 2 else str(c.get("created_at") or "")[:10],
        "view": "agree" if c.get("error_class") == AGREE_ERROR_CLASS else "disagree",
        "his_words": _clip(c.get("correction_text")),
        "correction_sk": sk,
    }


# ── assembly ──────────────────────────────────────────────────────────────────────────────────


def _not_observed(indicators: list[dict[str, Any]]) -> list[str]:
    return [f"{i['label']}: {i['reason']}" for i in indicators if i["direction"] == INSUFFICIENT]


def _status_reason(status: str, indicators: list[dict[str, Any]]) -> str:
    used = [f"{i['label']} → {i['direction']}" for i in indicators if i["direction"] != INSUFFICIENT]
    if status == NOT_ENOUGH:
        return "no indicator reached its minimum observations — missing evidence is not read as decline"
    return "; ".join(used)


def _domain(
    key: str, indicators: list[dict[str, Any]], extra_evidence: list[dict[str, Any]], inputs, extra_not_observed=()
) -> dict[str, Any]:
    spec = DOMAINS[key]
    status = combine(i["direction"] for i in indicators)
    evidence = [dict(i["evidence"], indicator=i["key"], direction=i["direction"]) for i in indicators if i["evidence"]]
    evidence.extend(extra_evidence)
    return {
        "domain": key,
        "name": spec["name"],
        "definition": spec["definition"],
        "basis": spec["basis"],
        "allowed_sources": list(spec["sources"]),
        "status": status,
        "status_reason": _status_reason(status, indicators),
        "evidence": evidence,
        "not_observed": _not_observed(indicators) + list(extra_not_observed),
        "last_owner_view": last_owner_view(inputs.get("profile_corrections") or [], key),
        "how_to_disagree": how_to_disagree(key),
    }


def _self_report_domain(key: str, inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    stmt, items = _statement_indicator(inputs, key, today)
    indicators = (_rating_indicators(inputs, today) if key == "emotional_wellbeing" else []) + [stmt]
    extra_not = []
    if not items:
        extra_not.append(f"no reviewed personal record of his is tagged '{key}'")
    if not OWNER_SELF_REPORT_MEASURES.get(key):
        extra_not.append("owner self-report measure: none in use (optional questionnaires deferred by owner ruling 2026-11-26)")
    return _domain(key, indicators, items, inputs, extra_not)


def assemble_profile(inputs: Mapping[str, Any], *, today: str) -> dict[str, Any]:
    """The whole profile for `today` from already-read `inputs` (see the module docstring for every rule).

    `inputs` keys (each optional; a key named in `read_failed` is treated as unread, never as empty):
      observed_days, excluded_days {sick, travel}, zone2_sessions [{date, minutes}], training_days [date],
      lift_sessions [{date, identity, name, best_e1rm_lb}], weight [{date, weight_lbs}], habit_days [{date,
      completion_pct}], experiments, recommendations (folded views), decisions, hypotheses (folded views),
      personal_records (platform_memory rows), journal_entries, evening_checkins, profile_corrections, read_failed."""
    _require_day(today)
    domains = []
    for key in DOMAINS:
        if key == "physical_capacity":
            weight = _weight_figure(inputs, today)
            extra = [weight] if weight else []
            no_weight = [] if weight else ["body weight: no weigh-in in either window (shown only, never scored)"]
            domains.append(_domain(key, [_strength(inputs, today), _zone2(inputs, today)], extra, inputs, no_weight))
        elif key == "behavioural_consistency":
            domains.append(_domain(key, [_training_days(inputs, today), _habits(inputs, today)], [], inputs))
        elif key == "learning_and_experimentation":
            domains.append(_domain(key, [_learning(inputs, today)], [], inputs))
        elif key == "self_understanding":
            ind, questions, tally = _self_understanding(inputs, today)
            d = _domain(key, [ind], [tally] if tally else [], inputs)
            d["open_questions"] = questions
            domains.append(d)
        else:
            domains.append(_self_report_domain(key, inputs, today))
    return {
        "profile": "development_profile",
        "issue": ISSUE,
        "rules_version": RULES_VERSION,
        "as_of": today,
        "owner_only": True,
        "reading_this": (
            "Each domain stands on its own: there is no overall score, level, percentage or ranking. A status is a plain "
            "reading of the evidence listed under it, by the stated rule; 'not_enough_to_say' is the honest answer when "
            "the evidence is thin, and missing evidence is never read as decline. A model's reading of his writing is "
            "never evidence here. To disagree with a line, use its how_to_disagree call; the disagreement is stored."
        ),
        "rules": {
            "measured": {
                "window_days": MEASURED_WINDOW_DAYS,
                "min_eligible_days_each_window": MEASURED_MIN_DAYS,
                "excluded": "sick and travel days (the planned-pause causes); a day with no wearable row and no session is not observed",
                "zone2_margin": f"max({ZONE2_MARGIN_MIN:g} min/week, {ZONE2_MARGIN_FRACTION:.0%} of prior)",
                "strength": f">= {STRENGTH_MIN_LIFTS} lifts in both windows; a lift moved at ±{STRENGTH_MOVE_FRACTION:.1%}; net {STRENGTH_NET_LIFTS}",
                "training_days_margin": f"{TRAINING_DAYS_MARGIN} days/week",
                "habit_margin": f"{HABIT_MARGIN} completion",
                "weight": "shown, never scored",
            },
            "counted": {
                "window_days": COUNT_WINDOW_DAYS,
                "improving_when": f"recent - prior >= max({COUNT_MARGIN_MIN}, {COUNT_MARGIN_FRACTION:.0%} of prior)",
                "otherwise": "not_enough_to_say — a lower count is never read as decline",
            },
            "own_report": {
                "ratings_window_days": RATING_WINDOW_DAYS,
                "ratings_min_days_each_window": RATING_MIN_DAYS,
                "ratings_margin": RATING_MARGIN,
                "statements_window_days": STATEMENT_WINDOW_DAYS,
                "statements_min_each_window": STATEMENT_MIN,
                "statement_kinds": sorted(LIFE_DOMAIN_TAGGABLE_KINDS),
                "never_evidence": ["ai_interpretation", "competing_hypothesis", "rejected_interpretation", "observed_pattern"],
            },
        },
        "domains": domains,
    }
