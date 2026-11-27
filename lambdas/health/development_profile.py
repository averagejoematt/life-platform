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

STATUSES: improving · steady · harder · mixed · not_enough_to_say · owner_disputed. Each domain's status combines its
COUNTING indicators' directions (`combine`): no sufficient one -> not_enough_to_say; one itself mixed, or one better and
one worse -> mixed; otherwise better -> improving, worse -> harder, all same -> steady. A CONTEXT indicator (zone 2
volume, training days) is shown with its evidence and never enters the status. Every domain carries `scope`: what the
status rests on, what is not established, what his correction excluded, what is shown but not counted — so a
domain-level "improving" can never be read as covering an indicator it does not rest on.

NOT ENOUGH TO SAY means: the platform holds too few structured records to form a view. It says nothing about what has
actually happened in his life (`NOT_ENOUGH_MEANS`, owner ruling 2026-11-26). The thresholds are not lowered to fill a domain.

HIS CORRECTIONS ARE CONSEQUENTIAL (owner ruling 2026-11-26; the existing corrections ledger, no other store). An OPEN
disagreement on `development_profile:<domain>` -> status `owner_disputed`, his correction shown first, the rule's value
kept as `rule_status`, the evidence still shown. An OPEN disagreement on `development_profile:<domain>:<indicator>` ->
that indicator is shown, marked excluded by his correction, and the status is recomputed without it. A CLOSED one no
longer changes the reading and stays visible as `last_owner_view`. An agreement (`defense-held`) changes nothing.

THE RULES (deterministic; the windows end on `today`, inclusive; a recent window and the equal window before it)

  MEASURED (physical capacity, behavioural consistency) — `health.development_profile_measured` states each rule: estimated
    strength and (where a reliable record exists) the VO2 max device estimate count for capacity; zone 2 minutes are
    volume, shown only. Program adherence (credited against intended sessions, planned rest never a miss, sick and
    travel weeks left out) and the core habit set count for consistency; training days are shown only.
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

from datetime import date
from typing import Any, Iterable, Mapping, Optional

from ai.platform_memory import LIFE_DIRECTIONS, LIFE_DOMAIN_TAGGABLE_KINDS, LIFE_DOMAINS
from common.inferred_fields import SELF_REPORT_FIELDS

from health import development_profile_measured as measured
from health.development_profile_base import (  # noqa: F401 — the profile's vocabulary, re-exported for its readers
    BASES,
    BETTER,
    COUNTED,
    HARDER,
    IMPROVING,
    INSUFFICIENT,
    MEASURED,
    MEASURED_MIN_DAYS,
    MEASURED_WINDOW_DAYS,
    MIXED,
    MIXED_DIR,
    NOT_ENOUGH,
    NOT_ENOUGH_MEANS,
    OWN_REPORT,
    OWNER_CONFIRMED,
    OWNER_DISPUTED,
    SAME,
    STATUSES,
    STEADY,
    WORSE,
    _clip,
    _compare,
    _day,
    _failed_indicator,
    _indicator,
    _num,
    _read_failed,
    _require_day,
    _which,
    combine,
    windows,
)

ISSUE = "#6294"
RULES_VERSION = 2  # 2: the owner's #6317 corrections (aerobic result vs volume, adherence, core set, consequential corrections)

COUNT_WINDOW_DAYS = 56
COUNT_MARGIN_MIN = 3
COUNT_MARGIN_FRACTION = 0.5

RATING_WINDOW_DAYS = 28
RATING_MIN_DAYS = 8
RATING_MARGIN = 0.5

STATEMENT_WINDOW_DAYS = 90
STATEMENT_MIN = 3

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
        "definition": (
            "What his body can do, from RESULT measures: estimated strength on the lifts he repeats and, where a reliable "
            "record exists, demonstrated aerobic fitness. Training volume and body weight are shown, not counted."
        ),
        "basis": MEASURED,
        "sources": (
            "hevy lifts (best e1RM per lift)",
            "VO2 max device estimate (aerobic result)",
            "zone 2 minutes (volume, shown only)",
            "withings weight (shown only)",
        ),
    },
    "behavioural_consistency": {
        "name": "Behavioural consistency",
        "definition": (
            "Whether he does what he set out to do: program sessions done against the sessions the program intended, and "
            "the core habit set. Planned rest, sick and travel are never misses; training frequency is shown, not counted."
        ),
        "basis": MEASURED,
        "sources": (
            "session sequence: credited vs intended program sessions",
            "core habit set (habit_scores)",
            "training days (shown only)",
        ),
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


# ── owner views, his corrections, and the disagreement door ───────────────────────────────────


def signal_for(domain: str, indicator: Optional[str] = None) -> str:
    return f"{SIGNAL_PREFIX}{domain}" + (f":{indicator}" if indicator else "")


def how_to_disagree(domain: str, indicator_keys: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "tool": "log_coach_correction",
        "arguments": {
            "signal": signal_for(domain),
            "surface": PROFILE_SURFACE,
            "correction": "<what is wrong with this line and what it should say, in his words>",
            "error_class": DISAGREE_ERROR_CLASS,
        },
        "per_indicator": {k: signal_for(domain, k) for k in indicator_keys},
        "to_agree_instead": {"error_class": AGREE_ERROR_CLASS, "correction": "<that the line is right, in his words>"},
        "what_it_does": (
            "an OPEN disagreement on the domain makes the profile stop asserting its own status (owner_disputed, the rule's "
            "value kept as rule_status); one on an indicator takes that indicator out of the status. Closing it "
            "(log_coach_correction action='close') restores the rule; it stays visible as history."
        ),
        "where_it_goes": f"the corrections ledger on the '{PROFILE_SURFACE}' surface",
    }


def _profile_rows(corrections: Iterable[Mapping[str, Any]], domain: str) -> list[Mapping[str, Any]]:
    """Ledger rows on the profile surface about `domain` itself or one of its indicators (`<domain>:<indicator>`)."""
    mine = signal_for(domain)
    out = []
    for c in corrections or []:
        ref = c.get("item_ref") or {}
        signal = str(ref.get("signal") or "")
        if ref.get("surface") == PROFILE_SURFACE and (signal == mine or signal.startswith(mine + ":")):
            out.append(c)
    return out


def _when(c: Mapping[str, Any]) -> tuple[str, str]:
    return (str(c.get("created_at") or ""), str(c.get("sk") or ""))


def _view(c: Mapping[str, Any]) -> dict[str, Any]:
    sk = str(c.get("sk") or "")
    signal = str((c.get("item_ref") or {}).get("signal") or "")
    return {
        "date": sk.split("#")[1] if sk.count("#") >= 2 else str(c.get("created_at") or "")[:10],
        "view": "agree" if c.get("error_class") == AGREE_ERROR_CLASS else "disagree",
        "about": signal[len(SIGNAL_PREFIX) :],
        "his_words": _clip(c.get("correction_text")),
        "state": "closed" if c.get("status") == "closed" else "open",
        "correction_sk": sk,
    }


def last_owner_view(corrections: Iterable[Mapping[str, Any]], domain: str) -> Optional[dict[str, Any]]:
    """His newest recorded view on this domain or one of its indicators — open or closed (a closed one is history)."""
    rows = _profile_rows(corrections, domain)
    return _view(max(rows, key=_when)) if rows else None


def open_disputes(corrections: Iterable[Mapping[str, Any]], domain: str) -> dict[str, Any]:
    """His OPEN disagreements: {"domain": newest domain-level view or None, "indicators": {indicator: newest view}}.
    An agreement is never a dispute, and a closed correction no longer changes the reading."""
    out: dict[str, Any] = {"domain": None, "indicators": {}}
    for c in sorted(_profile_rows(corrections, domain), key=_when):
        if c.get("status") == "closed" or c.get("error_class") == AGREE_ERROR_CLASS:
            continue
        v = _view(c)
        parts = v["about"].split(":")
        if len(parts) == 1:
            out["domain"] = v
        else:
            out["indicators"][parts[1]] = v
    return out


# ── assembly ──────────────────────────────────────────────────────────────────────────────────


def _scope(indicators: list[dict[str, Any]], excluded: Mapping[str, Any]) -> dict[str, list[str]]:
    counting = [i for i in indicators if i["counts"]]
    return {
        "status_rests_on": [i["label"] for i in counting if i["key"] not in excluded and i["direction"] != INSUFFICIENT],
        "not_established": [
            f"{i['label']}: {i['reason']}" for i in counting if i["key"] not in excluded and i["direction"] == INSUFFICIENT
        ],
        "excluded_by_his_correction": [i["label"] for i in counting if i["key"] in excluded],
        "shown_not_counted": [i["label"] for i in indicators if not i["counts"]],
    }


def _status_reason(status: str, rule_status: str, scope: Mapping[str, list[str]], dispute: Optional[Mapping[str, Any]]) -> str:
    if dispute:
        return (
            f"he disputes this line ({dispute['date']}): \"{dispute['his_words']}\". The profile does not assert its own status "
            f"while that correction is open; the rules alone would read {rule_status}."
        )
    if status == NOT_ENOUGH:
        return f"not enough to say: {NOT_ENOUGH_MEANS}. Missing evidence is never read as decline."
    rests = "; ".join(scope["status_rests_on"])
    gaps = scope["not_established"] + [f"{lab}: excluded by his correction" for lab in scope["excluded_by_his_correction"]]
    text = f"{status} on the basis of {rests}" + (" only" if gaps else "")
    if gaps:
        text += ". Not established: " + "; ".join(gaps)
    if scope["shown_not_counted"]:
        text += ". Shown, not counted: " + "; ".join(scope["shown_not_counted"])
    return text + "."


def _domain(
    key: str, indicators: list[dict[str, Any]], extra_evidence: list[dict[str, Any]], inputs, extra_not_observed=()
) -> dict[str, Any]:
    spec = DOMAINS[key]
    corrections = inputs.get("profile_corrections") or []
    disputes = open_disputes(corrections, key)
    excluded = {k: v for k, v in disputes["indicators"].items() if any(i["key"] == k and i["counts"] for i in indicators)}
    rule_status = combine(i["direction"] for i in indicators if i["counts"] and i["key"] not in excluded)
    scope = _scope(indicators, excluded)
    status = OWNER_DISPUTED if disputes["domain"] else rule_status
    evidence = []
    for i in indicators:
        if not i["evidence"]:
            continue
        item = dict(i["evidence"], indicator=i["key"], direction=i["direction"])
        item["counts_toward_status"] = bool(i["counts"]) and i["key"] not in excluded and item.get("counts_toward_status", True)
        if i["key"] in excluded:
            item["excluded_by_his_correction"] = excluded[i["key"]]
        evidence.append(item)
    evidence.extend(extra_evidence)
    out: dict[str, Any] = {"domain": key, "name": spec["name"]}
    if disputes["domain"]:
        out["owner_correction"] = disputes["domain"]  # his words first: the profile does not assert over them
    out.update(
        {
            "definition": spec["definition"],
            "basis": spec["basis"],
            "allowed_sources": list(spec["sources"]),
            "status": status,
            "rule_status": rule_status,
            "scope": scope,
            "status_reason": _status_reason(status, rule_status, scope, disputes["domain"]),
            "evidence": evidence,
            "not_observed": [f"{i['label']}: {i['reason']}" for i in indicators if i["counts"] and i["direction"] == INSUFFICIENT]
            + list(extra_not_observed),
            "last_owner_view": last_owner_view(corrections, key),
            "how_to_disagree": how_to_disagree(key, [i["key"] for i in indicators if i["counts"]]),
        }
    )
    return out


def _self_report_domain(key: str, inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    stmt, items = _statement_indicator(inputs, key, today)
    indicators = (_rating_indicators(inputs, today) if key == "emotional_wellbeing" else []) + [stmt]
    extra_not = []
    if not items:
        extra_not.append(f"no reviewed personal record of his is tagged '{key}'")
    if not OWNER_SELF_REPORT_MEASURES.get(key):
        extra_not.append("owner self-report measure: none in use (optional questionnaires deferred by owner ruling 2026-11-26)")
    return _domain(key, indicators, items, inputs, extra_not)


def _physical(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    weight = measured.weight_figure(inputs, today)
    no_weight = [] if weight else ["body weight: no weigh-in in either window (shown only, never scored)"]
    indicators = [
        measured.strength(inputs, today),
        measured.aerobic_tests(inputs, today),
        measured.aerobic(inputs, today),
        measured.zone2_volume(inputs, today),
    ]
    return _domain("physical_capacity", indicators, [weight] if weight else [], inputs, no_weight)


def _behavioural(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    indicators = [measured.adherence(inputs, today), measured.core_habits(inputs, today), measured.training_days(inputs, today)]
    return _domain("behavioural_consistency", indicators, [], inputs)


def assemble_profile(inputs: Mapping[str, Any], *, today: str) -> dict[str, Any]:
    """The whole profile for `today` from already-read `inputs` (see the module docstrings for every rule).

    `inputs` keys (each optional; a key named in `read_failed` is treated as unread, never as empty):
      observed_days, excluded_days {sick, travel}, zone2_sessions [{date, minutes}], training_days [date],
      lift_sessions [{date, identity, name, best_e1rm_lb}], fitness_trend (the battery's trend), vo2_estimates [{date, value, source}], weight [{date,
      weight_lbs}], adherence_weeks [{week_start, intended, credited, program_version}], adherence_intent (str),
      core_habit_days [{date, core_done, core_known}], experiments, recommendations (folded views), decisions,
      hypotheses (folded views), personal_records (platform_memory rows), journal_entries, evening_checkins,
      profile_corrections (corrections-ledger rows on the development_profile surface), read_failed."""
    _require_day(today)
    domains = []
    for key in DOMAINS:
        if key == "physical_capacity":
            domains.append(_physical(inputs, today))
        elif key == "behavioural_consistency":
            domains.append(_behavioural(inputs, today))
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
            "reading of the evidence listed under it, by the stated rule, and its `scope` says what it rests on and what "
            "it does not establish. 'not_enough_to_say' means " + NOT_ENOUGH_MEANS + "; missing evidence is never read "
            "as decline. A model's reading of his writing is never evidence here. To disagree with a line, use its "
            "how_to_disagree call: an open disagreement changes what the profile asserts until he closes it."
        ),
        "rules": {
            "measured": {
                "window_days": MEASURED_WINDOW_DAYS,
                "min_eligible_days_each_window": MEASURED_MIN_DAYS,
                "excluded": "sick and travel days (the planned-pause causes); a day with no habit record and no session is not observed",
                "strength": (
                    f">= {measured.STRENGTH_MIN_LIFTS} lifts in both windows; a lift moved at ±{measured.STRENGTH_MOVE_FRACTION:.1%}; "
                    f"net {measured.STRENGTH_NET_LIFTS}"
                ),
                "aerobic_tests": f"fitness battery aerobic tests: latest vs previous in each series, latest <= {measured.AEROBIC_TEST_MAX_AGE_DAYS} days old",
                "aerobic": (
                    f"VO2 max device estimate: >= {measured.AEROBIC_MIN_ESTIMATES} estimates in each window from one device; "
                    f"margin {measured.AEROBIC_MARGIN} ml/kg/min"
                ),
                "zone2": "training volume — shown, never counted as physical capacity",
                "adherence": (
                    f"credited program sessions / intended, {measured.ADHERENCE_WEEKS} complete weeks a window, >= "
                    f"{measured.ADHERENCE_MIN_WEEKS} counted weeks each, margin {measured.ADHERENCE_MARGIN}, ceiling "
                    f"{measured.ADHERENCE_CEILING}; planned rest never a miss, sick or travel weeks left out"
                ),
                "core_habits": f"core_done / core_known, >= {measured.CORE_MIN_DAYS} known days each window, margin {measured.CORE_MARGIN}",
                "training_days": "frequency — shown as context, never counted as consistency",
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
            "his_corrections": "open disagreement on a domain -> owner_disputed (rule_status kept); on an indicator -> that indicator excluded; closed -> history only",
        },
        "domains": domains,
    }
