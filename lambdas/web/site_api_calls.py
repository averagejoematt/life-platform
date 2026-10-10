"""site_api_calls.py — GET /api/calls: one page per settled coach call (#4586, epic #4580).

WHAT IT SERVES
--------------
Every SETTLED call of this experiment that a reader can check for themselves, newest
settled first, each under a stable id that is its address (``/next/v8/call/?id=<id>``):
who called it and when, the claim verbatim, what was called in plain words, what happened,
right or wrong, what the simple guess ("nothing changes", #4585) said — and that coach's
running record. Plus ``next``: the next call or bet due to settle, and its day.

``?id=<id>`` returns one call under ``call``; an id that names no settled call is a 404
whose body carries ``state: "absent"`` and a sentence.

WHICH CALLS GET A PAGE
----------------------
A page says "X called this, here is what happened, right or wrong". That is only honest
when the coach's own sentence states the thing that was measured. The grader's spec (a
measure and a direction or a number) is attached to a coach's sentence by a model, and for
commentary it is an inference: "If dinner is missed, the protein target will not be met"
was graded on whether protein went down, with the condition never checked. So:

  * **number** — a ``point`` call. The sentence must name the measure and state the
    number that was graded, and must not be conditional or hedged. It must also have been
    graded on the day after it was filed. The coaches' number calls are next-day forecasts
    ("recovery will be about 61 tomorrow"); some were stored with a target fourteen days
    out, so "about 59 tomorrow" filed September 14 was graded right on September 28's
    reading. A verdict about a day the sentence never named is not printed.
  * **direction** — only a call SEALED before day one. Those were written as a measure, a
    direction and a window. The sentence must name the measure and state the direction
    that was graded. A direction read out of in-experiment commentary gets no page.
    Nor does a direction call the grader read as FLAT: its trend check compares the latest
    readings with the few before them (``coach_prediction_evaluator._get_ewma_trend``), not
    the first day of the window with the last, so "held flat" can sit beside a measure that
    moved a long way over the window. Measured 2026-10-04: two sealed "weight will trend
    downward" calls were graded flat, and so wrong, on a 28-day window in which the served
    weight series fell from 327.3 lb to 312.1 lb. Until that grade is re-examined the page
    would print a sentence the site's own chart contradicts, so it is not printed.
  * **bet** — a resolved dispute-docket entry with a graded verdict: the criterion was
    frozen when the bet opened. One page per bet, never one per side.

A coach's words that cite a sensor which had sent no reading by the day they were said
are never quoted (#4673, ``web.claim_sourcing``): a call whose sentence does is counted under
``excluded``; a bet keeps its page and the held side carries ``unsourced`` — the reason and
one sentence — in place of its words.

Everything else is counted under ``excluded`` with its reason, and says so in a sentence.
Excluded calls STAY in each coach's record: the record is ``coach_record``'s, the one
producer every other surface prints, and this module never re-counts it.

THE READ
--------
The same concurrent, projected fetch ``/api/predictions`` makes (one Query per coach
partition, through the facade's ``_parallel_fetch``), with the two docket prefixes riding
in the same pool. No new index, no write, no Lambda. Measured 2026-10-04: the uncached
``/api/predictions`` — the same eight partition reads — answers in about one second; this
route is deliberately NOT an upstream of ``/api/edition`` (#4607).

Honest numbers (ADR-104): counts only — no percentage is served here at any n; absence is
a sentence, never a zero; a call the simple guess has not been scored on says exactly that.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from coach import coach_baseline, coach_dossier, coach_record, prediction_windows
from coach.persona_registry import plain_name
from common.pacific_time import day_in_words, pacific_date_of, shift_day_key
from experiment.measurable_metrics import AGG_SUFFIXES, base_metric
from experiment.phase_filter import singleton_visible
from health import instrument_presence  # #4217/#4673: which instruments are dark, and since when

from web import claim_sourcing, prediction_reason
from web.site_api_common import PT, _decimal_to_float, _error, _ok, logger

SOURCE = "/api/calls"
ID_RE = re.compile(r"^[a-z]+-\d{8}-[0-9a-f]{10}$")

ABSENT_NONE = "No call has been checked against the data yet."
ABSENT_UNAVAILABLE = "The settled calls are not served right now."
ABSENT_ID = "No settled call has this address."
ABSENT_NEXT = "No call or bet has a settle date right now."
GUESS_WORDS = "The simple guess is that nothing changes: the measure stays where it was when the call was made."

# Why a graded call has no page. Served as counts beside one sentence, never hidden.
CONDITIONAL = "the sentence was conditional or hedged"
INFERRED_DIRECTION = "a direction read out of commentary, not a call sealed before day one"
MEASURE_NOT_NAMED = "the sentence does not name the measure that was graded"
CALL_NOT_STATED = "the sentence does not state the number or direction that was graded"
OTHER_DAY = "graded on a day the sentence does not name"
FLAT_READ = "graded as no movement by a trend check that reads only the most recent readings"
NO_READER_WORDS = "no plain-words sentence exists for the measure or the result"
WITHHELD = "withheld by the privacy filter"
NO_IDENTITY = "the stored row has no stable identity"
UNSOURCED = "the sentence rests on a sensor that had sent no reading by the day it was said"

#: A conditional or hedged sentence is not falsifiable by the measure alone.
_CONDITIONAL_RE = re.compile(r"\b(if|unless|once|when|whenever|assuming|provided|until|may|might|could)\b", re.IGNORECASE)
_UP_RE = re.compile(r"\b(up|upward|upwards|increas\w+|ris\w+|climb\w*|higher)\b", re.IGNORECASE)
_DOWN_RE = re.compile(r"\b(down|downward|downwards|decreas\w+|declin\w+|drop\w*|lower)\b", re.IGNORECASE)

#: How a coach's sentence names each measure (lower-case substrings). The key-set is
#: ``prediction_reason.METRIC_WORDS``' — a measure with no entry here never gets a page.
_NAMED_AS = {
    "hrv": ("hrv", "heart rate variability", "heart-rate variability"),
    "recovery_score": ("recovery",),
    "resting_heart_rate": ("resting heart rate", "rhr"),
    "sleep_duration_hours": ("sleep",),
    "sleep_score": ("sleep score",),
    "deep_pct": ("deep sleep", "deep-sleep", "slow-wave", "slow wave"),
    "rem_pct": ("rem sleep", "rem-sleep", "rem share"),
    "weight_lbs": ("weight", "scale"),
    "total_calories_kcal": ("calori", "kcal"),
    "total_protein_g": ("protein",),
    "steps": ("step",),
    "blood_glucose_avg": ("glucose",),
    "blood_glucose_std_dev": ("glucose",),
    "body_fat_pct": ("body fat", "body-fat"),
}

#: The plain gloss that rides in the sentence beside a measure a cold reader may not know.
_GLOSS = {
    "recovery_score": "his wrist strap’s morning score out of 100",
    "hrv": "the beat-to-beat variation in his pulse overnight, in milliseconds; higher is generally better",
    "sleep_score": "a score for the night out of 100",
    "deep_pct": "the part of the night spent in deep sleep, as a percentage",
    "rem_pct": "the part of the night spent in dreaming sleep, as a percentage",
    "blood_glucose_avg": "blood sugar, from a sensor worn on the arm",
    "blood_glucose_std_dev": "how much his blood sugar moves around",
}
_COMPARE_WORDS = {"lt": "below", "lte": "at or below", "gt": "above", "gte": "at or above"}
_DIRECTION_WORDS = {"up": "up", "down": "down"}


def _iso_day(value: Any) -> str | None:
    text = str(value or "")[:10]
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def _words(day: str | None, weekday: bool = False) -> str:
    return day_in_words(day, weekday=weekday) if day else ""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def call_id(short_id: str, row: dict) -> str | None:
    """The stable address of one coach call: ``<coach>-<day filed>-<digest>``.

    Every part is read off the stored row and none of it moves when other calls arrive:
    the coach's short id, the row's ``created_date`` and a digest of the coach id plus the
    ``prediction_id`` (the identity a re-written row shares with its original, #4216)."""
    pid = str(row.get("prediction_id") or "").strip()
    day = _iso_day(row.get("created_date"))
    if not pid or not day or not re.fullmatch(r"[a-z]+", str(short_id or "")):
        return None
    return f"{short_id}-{day.replace('-', '')}-{_digest(f'{short_id}_coach|{pid}')}"


def bet_id(docket: dict) -> str | None:
    """The stable address of one resolved bet: ``bet-<day resolved>-<digest of its key>``."""
    sk = str(docket.get("sk") or "")
    day = _iso_day(docket.get("resolved_date")) or _iso_day(sk.replace("RESOLVED#", "", 1))
    if not sk.startswith("RESOLVED#") or not day:
        return None
    return f"bet-{day.replace('-', '')}-{_digest(sk)}"


def _subject(metric: Any, gloss: bool = True) -> str | None:
    """'recovery_score_7day_avg' -> 'the 7-day average of his morning recovery score (…)'."""
    key = str(metric or "").strip()
    base = base_metric(key)
    words = prediction_reason.METRIC_WORDS.get(base)
    if not key or words is None:
        return None
    noun = f"his {words}"
    if gloss and base in _GLOSS:
        noun += f" ({_GLOSS[base]})"
    for suffix in AGG_SUFFIXES:
        if key != base and key.endswith(suffix):
            return f"the {suffix.strip('_').split('day')[0]}-day average of {noun}"
    return noun


def _amount(value: Any, metric: Any) -> str | None:
    num = prediction_reason._num(value)
    if num is None:
        return None
    return f"{num}{prediction_reason._UNITS.get(base_metric(str(metric or '')), '')}"


def _names_measure(text: str, metric: Any) -> bool:
    low = text.lower()
    return any(name in low for name in _NAMED_AS.get(base_metric(str(metric or "")), ()))


def page_kind(row: dict) -> tuple[str | None, str | None]:
    """``(kind, None)`` when a graded PREDICTION# row gets a page, else ``(None, why_not)``.

    See the module docstring: the test is whether the coach's OWN sentence states what the
    grader measured."""
    text = str(row.get("claim_natural") or "").strip()
    raw = row.get("evaluation")
    spec: dict = raw if isinstance(raw, dict) else {}
    kind = coach_baseline.rule_kind(spec)
    if kind not in ("number", "direction") or not text or _subject(spec.get("metric")) is None:
        return None, NO_READER_WORDS
    if kind == "direction" and not row.get("pre_registered"):
        return None, INFERRED_DIRECTION
    if _CONDITIONAL_RE.search(text):
        return None, CONDITIONAL
    if not _names_measure(text, spec.get("metric")):
        return None, MEASURE_NOT_NAMED
    if kind == "number":
        want = prediction_reason._num(spec.get("threshold"))
        if want is None or want not in text:
            return None, CALL_NOT_STATED
        filed, target = _iso_day(row.get("created_date")), _iso_day(spec.get("target_date"))
        if not filed or not target or target != shift_day_key(filed, 1):
            return None, OTHER_DAY
    else:
        called = str(spec.get("condition") or "").strip().lower()
        if called not in _DIRECTION_WORDS or not (_UP_RE if called == "up" else _DOWN_RE).search(text):
            return None, CALL_NOT_STATED
    if not coach_dossier.dossier_safe(text):
        return None, WITHHELD
    return kind, None


def record_block(name: str, record: dict | None, decided: list | None = None) -> dict:
    """A coach's running record as counts and one sentence — never a percentage, and never
    alone (#4585): ``comparison`` is what a simple guess scored on the SAME decided rows,
    as the one sentence a page prints beside the count."""
    if record is None:
        return {
            "state": "unavailable",
            "right": None,
            "n": None,
            "through": None,
            "text": f"{name}: record not served right now.",
            "comparison": None,
        }
    block = coach_baseline.comparison_block(decided or [])
    comparison = {k: block[k] for k in ("rule", "rule_words", "scored_complete", "sentence")}
    n, k = int(record.get("n") or 0), int(record.get("confirmed") or 0)
    if n == 0:
        return {"state": "absent", "right": 0, "n": 0, "through": None, "text": f"{name}: no checked call yet.", "comparison": comparison}
    calls = "checked call" if n == 1 else "checked calls"
    return {
        "state": "ok",
        "right": k,
        "n": n,
        "through": record.get("through"),
        "text": f"{name}: {k} of {n} {calls} right.",
        "comparison": comparison,
    }


def simple_guess(baseline: Any, kind: str | None, *, coach_right: bool, metric: Any = None) -> dict:
    """What the "nothing changes" rule said on ONE call, from the verdict frozen on its row.

    A row with no frozen verdict is ``not_yet_scored`` and says so — the verdict is never
    recomputed here and never invented."""
    if not isinstance(baseline, dict) or baseline.get("rule") != coach_baseline.RULE_ID:
        return {
            "state": "not_yet_scored",
            "right": None,
            "text": "The simple guess, that nothing changes, has not been checked against this call yet.",
            "short": "not checked on this call yet",
        }
    if baseline.get("right") is None:
        why = str(baseline.get("unscorable") or coach_baseline.NO_RULE)
        return {
            "state": "unscorable",
            "right": None,
            "text": f"The simple guess, that nothing changes, could not be checked on this call: {why}.",
            "short": "could not be checked on this call",
        }
    right = bool(baseline["right"])
    filed = _amount(baseline.get("filed_value"), metric)
    if kind == "direction":
        said = "The simple guess was that it would not move."
    elif kind == "number" and filed:
        said = f"The simple guess was that it would stay at {filed}, the last reading before the call."
    elif kind == "yes_no":
        said = "The simple guess was that the answer would be the same as on the day before the bet opened."
    else:
        said = "The simple guess was that nothing would change."
    also = "also " if right == coach_right else ""
    outcome = "right" if right else "wrong"
    return {"state": "scored", "right": right, "text": f"{said} That guess was {also}{outcome}.", "short": f"{also}{outcome}"}


def _went(reason: str) -> str | None:
    if "held flat" in reason:
        return "It held flat."
    if "went up" in reason:
        return "It went up."
    if "went down" in reason:
        return "It went down."
    return None


def build_call(short_id: str, name: str, row: dict, record: dict, dark: list | None = None) -> tuple[dict | None, str | None]:
    """One settled PREDICTION# row as a page body, or ``(None, why_not)``."""
    kind, why = page_kind(row)
    if kind is None:
        return None, why
    if claim_sourcing.unsourced([row.get("claim_natural")], row.get("created_date"), dark or []):
        return None, UNSOURCED
    cid = call_id(short_id, row)
    if cid is None:
        return None, NO_IDENTITY
    spec = row["evaluation"]
    status = coach_record.graded_status(row)
    reason, _ = prediction_reason.reason_words(row)
    notes = prediction_reason._notes(row.get("outcome_notes"))
    if not reason or reason == str(notes.get("reason") or "").strip():
        return None, NO_READER_WORDS  # the grader's working, not a reader's sentence
    metric = spec.get("metric")
    subject, plain = _subject(metric), _subject(metric, gloss=False)
    actual = None
    if kind == "number":
        want, seen = _amount(spec.get("threshold"), metric), _amount(notes.get("actual_value"), metric)
        if not want or not seen:
            return None, NO_READER_WORDS
        target = _iso_day(spec.get("target_date"))
        on = f" for {_words(target)}" if target else ""
        margin = _amount(spec.get("tolerance"), metric)
        called = f"{name} called {subject} at about {want}{on}."
        if margin:
            called += f" A call like this counts as right within {margin} either way, his usual day-to-day swing."
        called_short = f"{name} called {plain} at about {want}."
        happened_short = f"It came in at {seen}."
        actual = {"value": notes.get("actual_value"), "text": seen}
    else:
        direction = _DIRECTION_WORDS[str(spec.get("condition")).strip().lower()]
        happened_short = _went(reason)
        if happened_short is None:
            return None, NO_READER_WORDS
        if "flat" in happened_short:
            return None, FLAT_READ
        checked = _words(_iso_day(row.get("outcome_date")))
        called = f"{name} called {subject} to go {direction}, in a prediction sealed before day one."
        if checked:
            called += f" It was checked on {checked} against the trend in his most recent readings."
        called_short = f"{name} called {plain} to go {direction}."
    sealed = bool(row.get("pre_registered"))
    logged = (pacific_date_of(row.get("pre_registered_at")) if sealed else None) or _iso_day(row.get("created_date"))
    coach_right = status == "confirmed"
    guess = simple_guess(row.get("baseline"), kind, coach_right=coach_right, metric=metric)
    return (
        {
            "id": cid,
            "kind": kind,
            "coach_id": short_id,
            "coach_name": name,
            "claim": str(row.get("claim_natural") or "").strip(),
            "logged_date": logged,
            "sealed": sealed,
            "settled_date": _iso_day(row.get("outcome_date")),
            "called": called,
            "called_short": called_short,
            "happened": f"{reason}.",
            "happened_short": happened_short,
            "actual": actual,
            "verdict": "right" if coach_right else "wrong",
            "verdict_text": f"{name} was {'right' if coach_right else 'wrong'}.",
            "simple_guess": guess,
            "records": [record],
            "title": f"{name} called {plain} {'at about ' + _amount(spec.get('threshold'), metric) if kind == 'number' else 'to go ' + direction}: {'right' if coach_right else 'wrong'}",
        },
        None,
    )


def _criterion_question(criterion: dict, gloss: bool = True, verb: str = "would") -> str | None:
    """'<subject> would be below 70' for a docket criterion; None when it has no plain words."""
    subject = _subject(criterion.get("metric"), gloss=gloss)
    compare = _COMPARE_WORDS.get(str(criterion.get("condition") or "").strip().lower())
    threshold = _amount(criterion.get("threshold"), criterion.get("metric"))
    if not subject or not compare or not threshold:
        return None
    return f"{subject} {verb} be {compare} {threshold}"


def _bet_baseline(docket: dict, rows_by_coach: dict) -> Any:
    """The rule's frozen verdict for a bet, read off either side's docket PREDICTION# row
    (``dispute_docket._write_docket_prediction`` stamps the same verdict on both)."""
    opened, slug = str(docket.get("opened_date") or ""), str(docket.get("topic_slug") or "")
    for coach in (docket.get("coach_a"), docket.get("coach_b")):
        for row in rows_by_coach.get(str(coach or "").removesuffix("_coach"), []):
            pid = str(row.get("prediction_id") or "")
            if row.get("source") == "dispute_docket" and pid.startswith("docket-") and slug and slug in pid and pid.endswith(opened):
                if isinstance(row.get("baseline"), dict):
                    return row["baseline"]
    return None


def build_bet(docket: dict, names: dict, records: dict, rows_by_coach: dict, dark: list | None = None) -> tuple[dict | None, str | None]:
    """One resolved, graded dispute-docket entry as a page body, or ``(None, why_not)``.

    #4673: a side whose words cite a sensor with no reading on the day the bet opened is
    served with ``claim: ""`` and ``unsourced`` (the reason and the sentence a page prints
    beside its name). The bet itself, its question and its verdict stand."""
    verdict = docket.get("verdict") or {}
    winner, loser = verdict.get("winner") or docket.get("winner"), verdict.get("loser") or docket.get("loser")
    if verdict.get("outcome") != "graded" or not winner or not loser:
        return None, coach_baseline.NOT_GRADED
    bid = bet_id(docket)
    if bid is None:
        return None, NO_IDENTITY
    criterion = docket.get("criterion") or {}
    claims = docket.get("claims") or {}
    if not coach_dossier.dossier_safe(*claims.values(), docket.get("topic")):
        return None, WITHHELD
    question = _criterion_question(criterion)
    plain_question = _criterion_question(criterion, gloss=False)
    seen = _amount(verdict.get("actual_value", docket.get("actual_value")), criterion.get("metric"))
    short = {c: str(c).removesuffix("_coach") for c in (winner, loser)}
    if not question or not seen or any(s not in names for s in short.values()):
        return None, NO_READER_WORDS
    sides = docket.get("sides") or {}
    quotable, held = claim_sourcing.split_claims(claims, docket.get("opened_date"), dark or [])
    day = _iso_day(docket.get("resolution_date")) or _iso_day(docket.get("resolved_date"))
    won, lost = names[short[winner]], names[short[loser]]
    yes_no = {c: ("yes" if sides.get(c) else "no") for c in (winner, loser)}
    called = (
        f"{won} and {lost} bet on one question, fixed the day the bet opened: whether {question} on {_words(day)}. "
        f"{won} said {yes_no[winner]}; {lost} said {yes_no[loser]}."
    )
    guess = simple_guess(_bet_baseline(docket, rows_by_coach), "yes_no", coach_right=True, metric=criterion.get("metric"))
    return (
        {
            "id": bid,
            "kind": "bet",
            "coach_id": short[winner],
            "coach_name": won,
            "claim": str(quotable.get(winner) or "").strip(),
            "sides": [
                {
                    "coach_id": short[c],
                    "coach_name": names[short[c]],
                    "claim": str(quotable.get(c) or "").strip(),
                    "said": yes_no[c],
                    "right": c == winner,
                    **({"unsourced": held[c]} if c in held else {}),
                }
                for c in (winner, loser)
            ],
            "topic": docket.get("topic"),
            "logged_date": _iso_day(docket.get("opened_date")),
            "sealed": False,
            "settled_date": _iso_day(docket.get("resolved_date")) or day,
            "called": called,
            "called_short": f"{won} and {lost} bet on whether {plain_question} on {_words(day)}.",
            "happened": f"It came in at {seen}.",
            "happened_short": f"It came in at {seen}.",
            "actual": {"value": verdict.get("actual_value", docket.get("actual_value")), "text": seen},
            "verdict": "right",
            "verdict_text": f"{won} was right; {lost} was wrong.",
            "simple_guess": guess,
            "records": [records.get(short[winner]), records.get(short[loser])],
            "title": f"{won} and {lost} bet on whether {plain_question}: {won} was right",
        },
        None,
    )


def _next_text(question: str, due: str) -> str:
    return f"Next: {question} settles {_words(due, weekday=True)}."


def next_block(today: str, open_dockets: list, pending: list, names: dict) -> dict:
    """The next call or bet due to settle on or after ``today``. A bet wins a tie."""
    candidates: list[tuple[str, int, dict]] = []
    for docket in open_dockets:
        due = _iso_day(docket.get("resolution_date"))
        criterion = docket.get("criterion") or {}
        question = _criterion_question(criterion, gloss=False, verb="will")
        a, b = (str(docket.get(k) or "").removesuffix("_coach") for k in ("coach_a", "coach_b"))
        if not due or due < today or not question or a not in names or b not in names:
            continue
        q = f"the bet between {names[a]} and {names[b]} on whether {question}"
        candidates.append((due, 0, {"kind": "bet", "coach_names": [names[a], names[b]], "question": q}))
    for short_id, row in pending:
        raw = row.get("evaluation")
        spec: dict = raw if isinstance(raw, dict) else {}
        due = prediction_windows.due_date(row.get("created_date"), spec, row.get("subdomain", ""))
        kind, _ = page_kind(row)
        plain = _subject(spec.get("metric"), gloss=False)
        if kind is None or not due or due < today or not plain or short_id not in names:
            continue
        if kind == "number":
            want = _amount(spec.get("threshold"), spec.get("metric"))
            if not want:
                continue
            q = f"{names[short_id]}’s call that {plain} will be about {want}"
        else:
            q = f"{names[short_id]}’s call that {plain} will go {_DIRECTION_WORDS[str(spec.get('condition')).strip().lower()]}"
        candidates.append((due, 1, {"kind": kind, "coach_names": [names[short_id]], "question": q}))
    if not candidates:
        return {"state": "absent", "as_of": None, "source": SOURCE, "absent_text": ABSENT_NEXT, "data": None}
    due, _, data = min(candidates, key=lambda c: (c[0], c[1], c[2]["question"]))
    data = {**data, "due_date": due, "text": _next_text(data["question"], due)}
    return {"state": "ok", "as_of": due, "source": SOURCE, "absent_text": ABSENT_NEXT, "data": data}


def compose(
    rows_by_coach: dict,
    names: dict,
    genesis: str | None,
    today: str,
    resolved_dockets: list,
    open_dockets: list,
    dark: list | None = None,
) -> dict:
    """The whole document from the fetched rows. Pure: no clock, no I/O.

    ``rows_by_coach`` is ``{short_id: [PREDICTION# rows]}`` exactly as the shared fetch
    returns them; ``names`` is ``{short_id: plain name}``; ``dark`` is
    ``claim_sourcing.dark_instruments(...)`` — the instruments with no reading now (#4673)."""
    calls: list[dict] = []
    excluded: dict[str, int] = {}
    records: dict[str, dict] = {}
    pending: list[tuple[str, dict]] = []
    for short_id, raw in rows_by_coach.items():
        if short_id not in names:
            continue
        rows = coach_record.resolved_once(raw or [])
        decided = coach_record.decided_rows(rows, genesis=genesis)
        records[short_id] = record_block(names[short_id], coach_record.record_from_rows(rows, genesis=genesis), decided)
        for row in decided:
            if row.get("source") == "dispute_docket":
                continue  # one page per BET, built from the docket row below — never one per side
            call, why = build_call(short_id, names[short_id], row, records[short_id], dark)
            if call is None:
                excluded[str(why)] = excluded.get(str(why), 0) + 1
            else:
                calls.append(call)
        for row in rows:
            if str(row.get("status") or "") == "pending" and coach_record.counts_this_cycle(row, genesis):
                pending.append((short_id, row))
    for docket in resolved_dockets:
        bet, why = build_bet(docket, names, records, rows_by_coach, dark)
        if bet is None:
            excluded[str(why)] = excluded.get(str(why), 0) + 1
        else:
            calls.append(bet)
    calls.sort(key=lambda c: (str(c.get("settled_date") or ""), c["id"]), reverse=True)
    n_out = sum(excluded.values())
    return {
        "state": "ok" if calls else "absent",
        "as_of": calls[0]["settled_date"] if calls else None,
        "source": SOURCE,
        "absent_text": ABSENT_NONE,
        "today": today,
        "count": len(calls),
        "calls": calls,
        "excluded": {
            "count": n_out,
            "reasons": excluded,
            "text": (
                ""
                if not n_out
                else f"{n_out} more checked {'call has' if n_out == 1 else 'calls have'} no page here: the coach’s sentence was conditional, "
                "did not state the number or direction that was measured, or was graded on a different day or by a check too coarse to print. "
                + ("Some rested on a sensor that had sent no reading by the day they were said. " if UNSOURCED in excluded else "")
                + "They still count in each coach’s record."
            ),
        },
        "simple_guess_words": GUESS_WORDS,
        "next": next_block(today, open_dockets, pending, names),
    }


def _absent(_g) -> dict:
    """#4673: ``{coach_id: instrument_state}`` for the dark instruments — the SAME derivation
    /api/source_freshness serves. Fail-open with a logged warning, as on /api/coach_docket
    (#4217): a sentinel read failing must not take the settled calls down."""
    try:
        return instrument_presence.absent_coaches(_g["table"])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[/api/calls] instrument presence check failed (fail-open): {exc}")
        return {}


def handle_calls(event, *, _g):
    """GET /api/calls — every settled, checkable call; ``?id=`` for one (see module docstring)."""
    qs = (event or {}).get("queryStringParameters") or {}
    wanted = str(qs.get("id") or "").strip()
    if wanted and not ID_RE.fullmatch(wanted):
        return _error(404, ABSENT_ID, state="absent", absent_text=ABSENT_ID)
    names = {cid: plain_name(name) for cid, name in _g["_CALIB_COACH_NAMES"].items()}
    fetch, docket_rows = _g["_fetch_prediction_partition"], _g["_docket_rows"]
    jobs: dict = {cid: (lambda pk=f"COACH#{cid}_coach": fetch(pk)) for cid in names}
    jobs["docket:resolved"] = lambda: docket_rows("RESOLVED#", _g["DOCKET_RESOLVED_LIMIT"], newest_first=True)
    jobs["docket:open"] = lambda: docket_rows("OPEN#", _g["DOCKET_OPEN_LIMIT"], newest_first=False)
    failures: list = []
    try:
        fetched = _g["_parallel_fetch"](jobs, failures=failures)
        if any(cid in failures for cid in names):
            # A missing partition would silently drop that coach's calls and unsettle the
            # "newest settled call"; the page prints a sentence instead of a partial list.
            raise RuntimeError(f"coach partition reads failed: {sorted(f for f in failures if f in names)}")
        dockets = {
            k: [_decimal_to_float(d) for d in fetched.get(k, []) if singleton_visible(d)] for k in ("docket:resolved", "docket:open")
        }
        rows_by_coach = {cid: [_decimal_to_float(r) for r in fetched.get(cid, [])] for cid in names}
        today = _g["datetime"].now(PT).strftime("%Y-%m-%d")  # the facade's clock hand-off
        dark = claim_sourcing.dark_instruments(_absent(_g))
        doc = compose(rows_by_coach, names, _g["EXPERIMENT_START"], today, dockets["docket:resolved"], dockets["docket:open"], dark)
        if "docket:resolved" in failures or "docket:open" in failures:
            doc["bets_state"] = "unavailable"
            logger.error(f"[/api/calls] degraded — docket reads failed: {sorted(f for f in failures if f.startswith('docket'))}")
    except Exception as exc:  # noqa: BLE001 — the honest degradation is a sentence, logged
        logger.error(f"[/api/calls] {exc}")
        body = {
            "state": "unavailable",
            "as_of": None,
            "source": SOURCE,
            "absent_text": ABSENT_UNAVAILABLE,
            "count": None,
            "calls": [],
            "next": None,
        }
        return _ok(body, cache_seconds=60, degraded=exc)
    if wanted:
        call = next((c for c in doc["calls"] if c["id"] == wanted), None)
        if call is None:
            return _error(404, ABSENT_ID, state="absent", absent_text=ABSENT_ID)
        keep = ("source", "today", "simple_guess_words", "next")
        return _ok(
            {"state": "ok", "as_of": call["settled_date"], "absent_text": ABSENT_ID, "call": call, **{k: doc[k] for k in keep}},
            cache_seconds=300,
        )
    return _ok(doc, cache_seconds=300)
