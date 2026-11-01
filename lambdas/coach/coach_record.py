"""coach_record.py — ONE producer of a coach's record: "K of N through <day>" (#4220, epic #4182).

THE DEFECT THIS CLOSES
----------------------
On 2026-09-26 one coach's record was served three ways on one day. ``/api/coaches``
counted ``LEARNING#`` rows and printed Webb "80% hit-rate · n=25"; ``/api/calibration``
and ``/api/predictions`` counted ``PREDICTION#`` rows and printed 0 of 5; ``/api/wrong``
counted ``LEARNING#`` rows again and printed 20 confirmed / 5 refuted. Twenty of Webb's
twenty-five learnings were ONE dispute docket re-recorded daily (#4216 — the resolver
re-grades a stranded pre-cycle ``OPEN#`` row every run). Nothing asserted the producers
agreed, so nothing noticed.

THE RULE
--------
The ``PREDICTION#`` partition is the ledger — the row the grader writes its verdict on
(``coach_prediction_evaluator._update_prediction_status``) and the row the Brier score is
computed from (``experiment.calibration_core``). A coach's record is counted from it and
from nothing else:

  * **A prediction resolves once.** Its record entry is the EARLIEST graded row that
    carries its ``prediction_id``; every later same-id row is a re-write (the
    ``_put_unique`` ``-2``…``-5`` suffix trail #4216 documents — measured live on Webb's
    partition 2026-09-27: five ``PREDICTION#docket-…`` rows, one ``prediction_id``) and
    never counts. ``resolved_once`` is the partition as if that were always so.
  * **It belongs to the cycle it resolved in.** A resolution counts in the current record
    only when its row is phase-visible (ADR-058 ``singleton_visible`` — the reset's
    tombstone/pilot stamp hides an archived cycle) AND its ``outcome_date`` is not before
    genesis. A docket that resolved before Day 1 is therefore in its own cycle's career
    record at most once and in this cycle's record never.
  * **Graded means confirmed or refuted.** Pending, observational, inconclusive and
    expired calls are not checked calls (the same vocabulary as ``latest_checked``).
  * **Absence is absence** (ADR-104). n = 0 → "no checked call yet"; a failed read → None,
    never a zero that reads as a clean slate. Below ``PERCENT_FLOOR`` decided calls the
    headline prints counts, never a percentage.

Every public surface that prints a coach's record — ``/api/coaches`` (``record`` +
``headline_stat``), ``/api/calibration.coaches[]`` (``record`` beside the Brier numbers,
whose season pairs are built from the SAME row-set), ``/api/predictions.by_coach``
(``record``, and its graded season counts walk the same row-set) and
``/api/wrong.predictions.by_coach`` — derives from ``record_from_rows`` /
``resolved_once`` / ``counts_this_cycle`` here. The cross-endpoint contract is pinned in
``tests/test_coaches_api.py`` and the producer/consumer pair is enrolled in
``tests/pair_contract_registry.py`` (charter rule 3).

Pure over an injected table handle: no write, one Query on the coach's own partition
(unfiltered — the tombstoned original of a re-written row is exactly what decides which
cycle the resolution belongs to). ONE clock read, behind the ``today_pt`` seam, and only
when a caller names no ``as_of`` day (#5356 — the day the record is complete through).

WHAT "THROUGH <day>" SAYS (#5356)
---------------------------------
``through`` used to be the ``outcome_date`` of the coach's LATEST decided call. That is a
fact about one call, not about the record: on 2026-10-24 (Day 49) Lisa Park's record read
"19 of 47 checked calls right (40%) through October 18" while every other coach read
"through October 23". Grading was not behind — her next call fell due October 26, so no
call of hers had come due since the 18th — but "through October 18" claims the record
stops a week ago, and the reader-truth judge flagged it high (finding e8f2c1). ``through``
is now the day the record is COMPLETE through: every call of this coach that fell due on
or before it has been checked. That is ``as_of`` (today, Pacific) unless an open call fell
due on or before ``as_of`` and is still unchecked, in which case it is the day before the
earliest such call's due date — so a stalled grader shows as a record that stops
advancing, never as a current one. It is never earlier than the latest decided call.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from boto3.dynamodb.conditions import Key
from common import pacific_time
from common.pacific_time import shift_day_key
from experiment.phase_filter import singleton_visible

from coach.prediction_windows import due_date

logger = logging.getLogger(__name__)

#: The terminal verdicts a record counts. Anything else is not a checked call.
GRADED_STATUSES = ("confirmed", "refuted")

#: The statuses the grader still owes a verdict (``coach_prediction_evaluator.EVALUABLE_STATUSES``).
OPEN_STATUSES = ("pending", "confirming")

#: Below this many decided calls the headline prints counts, never a percentage
#: (#4220 acceptance: "below n = 10 the page prints counts").
PERCENT_FLOOR = 10

#: Hard ceiling on pages walked; a coach's partition is a few hundred rows (one page).
_MAX_PAGES = 5

_PROJECTION_NAMES = {
    "#pid": "prediction_id",
    "#st": "status",
    "#oc": "outcome",
    "#od": "outcome_date",
    "#ph": "phase",
    "#tomb": "tombstone",
    "#sk": "sk",
    # #4585: what the "nothing changes" comparison (coach.coach_baseline) reads off the SAME
    # rows the record counts — its frozen verdict, which of the four records a call is, and
    # the stated confidence the engine's skill score uses. Never a second query.
    "#bl": "baseline",
    "#ev": "evaluation",
    "#pr": "pre_registered",
    "#src": "source",
    "#conf": "confidence",
    "#cn": "claim_natural",  # #4617: what the record counts (``call_class``) reads the sentence
    # #5356: an open call's due day (``prediction_windows.due_date``) bounds ``through``.
    "#cd": "created_date",
    "#sd": "subdomain",
    # #5533: the grader's own flags on a graded row — ``quality_counts`` reads them off the
    # SAME projected rows, so the clean count beside K of N can never come from a second read.
    "#qf": "quality_flags",
}


def graded_status(row: dict) -> str | None:
    """'confirmed' / 'refuted' for a graded row, else None."""
    status = str(row.get("status") or row.get("outcome") or "").strip().lower()
    return status if status in GRADED_STATUSES else None


def prediction_key(row: dict) -> str:
    """The identity a re-write shares with its original: ``prediction_id``, or the sk with
    the ``PREDICTION#`` prefix removed. Empty when the row carries neither."""
    pid = str(row.get("prediction_id") or "").strip()
    if pid:
        return pid
    return str(row.get("sk") or "").replace("PREDICTION#", "", 1).strip()


def resolved_once(rows: Iterable[Any]) -> list[dict]:
    """The partition with every re-write removed.

    Every ungraded row passes through unchanged; for each prediction that carries a grade,
    exactly ONE row survives — the earliest ``outcome_date`` (a missing date sorts first:
    the original, if any, is older than any re-write that stamped one). Order of the input
    is preserved for the survivors. A graded row with no identity at all is its own
    resolution — de-duplication never collapses rows it cannot prove are the same call.
    """
    first: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or graded_status(row) is None:
            continue
        key = prediction_key(row)
        if not key:
            continue
        held = first.get(key)
        if held is None or str(row.get("outcome_date") or "") < str(held.get("outcome_date") or ""):
            first[key] = row
    survivors = set(id(r) for r in first.values())
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if graded_status(row) is None or not prediction_key(row) or id(row) in survivors:
            out.append(row)
    return out


def counts_this_cycle(row: dict, genesis: str | None) -> bool:
    """Is this row part of the CURRENT cycle's record?

    Phase-visible per ADR-058, and — for a graded row — resolved on or after ``genesis``
    (an ISO ``YYYY-MM-DD``; ``None`` skips the date test). An ungraded row is judged by
    visibility alone, the same predicate every season count already applied.
    """
    if not singleton_visible(row):
        return False
    if genesis and graded_status(row) is not None:
        outcome_date = str(row.get("outcome_date") or "")[:10]
        if outcome_date and outcome_date < genesis:
            return False
    return True


def decided_rows(rows: Iterable[Any], *, genesis: str | None, career: bool = False) -> list[dict]:
    """The graded rows a record counts — one per resolution, in this cycle unless ``career``.

    This IS the record's row-set: ``record_from_rows`` tallies it, and ``/api/wrong``'s
    obituary cards are drawn from its refuted members (#4220 — the obituaries were a
    second derivation over ``LEARNING#`` that printed 23 explorer refutations beside a
    record of 3, twenty of them one pre-genesis docket re-recorded daily).
    """
    out: list[dict] = []
    for row in resolved_once(rows):
        if graded_status(row) is None:
            continue
        if not career and not counts_this_cycle(row, genesis):
            continue
        out.append(row)
    return out


def today_pt() -> str:
    """The Pacific day — the module's ONE clock read (#5356). Read through the module so a
    ``freeze_pacific`` of ``common.pacific_time`` reaches it; tests may also patch this."""
    return pacific_time.pacific_today()


def complete_through(rows: Iterable[Any], *, latest_decided: str, as_of: str) -> str:
    """The day a coach's record is complete through (#5356): ``as_of``, pulled back to the
    day before the earliest still-open call that fell due on or before ``as_of``, never
    earlier than ``latest_decided``. Lexical on ISO days, no parse beyond ``due_date``.

    Only phase-visible open rows bound it (an archived cycle's leftovers are not this
    record's debt), and a row whose due day cannot be computed is one the grader cannot
    grade either (it skips a row with no ``created_date``), so it bounds nothing.
    """
    bound = str(as_of or "")[:10]
    for row in rows or []:
        if not isinstance(row, dict) or not singleton_visible(row):
            continue
        if str(row.get("status") or "").strip().lower() not in OPEN_STATUSES:
            continue
        raw_spec = row.get("evaluation")
        try:
            due = due_date(row.get("created_date"), raw_spec if isinstance(raw_spec, dict) else {}, row.get("subdomain") or "")
        except (ValueError, TypeError):  # a non-numeric stated window: the grader cannot date it either
            continue
        if due and due <= bound:
            bound = shift_day_key(due, -1)
    return max(bound, latest_decided)


def record_from_rows(rows: Iterable[Any], *, genesis: str | None, career: bool = False, as_of: str | None = None) -> dict:
    """``{confirmed, refuted, n, through}`` over a coach's PREDICTION# rows.

    ``through`` is the day the current-cycle record is complete through (``complete_through``
    at ``as_of``, today Pacific when None — #5356), or None when nothing is counted. A
    ``career=True`` record counts every cycle (each resolution once) and keeps the latest
    counted ``outcome_date``: past cycles owe nothing, so there is no open call to bound it.
    """
    rows = list(rows or [])
    confirmed = refuted = 0
    through = ""
    for row in decided_rows(rows, genesis=genesis, career=career):
        status = graded_status(row)
        if status == "confirmed":
            confirmed += 1
        else:
            refuted += 1
        outcome_date = str(row.get("outcome_date") or "")[:10]
        if outcome_date > through:
            through = outcome_date
    if through and not career:
        through = complete_through(rows, latest_decided=through, as_of=as_of or today_pt())
    return {"confirmed": confirmed, "refuted": refuted, "n": confirmed + refuted, "through": through or None}


# ── #5533: the grader's own flags, counted beside the record ─────────────────────────────
# The record is ``K of N`` and stays ``K of N`` (ADR-157: the full count is never replaced).
# Beside it a reader can see how many of the N were graded clean — no logging gap in the
# window, no low-power band, no proxy metric — and how many predate the flags altogether.


def quality_counts(decided: Iterable[Any]) -> dict:
    """``{clean, flagged, unassessed, n}`` over DECIDED rows (``decided_rows``).

    ``clean`` counts rows the grader assessed and left unflagged; ``flagged`` rows carry at
    least one flag; ``unassessed`` rows were graded before the flags existed (no
    ``quality_flags`` attribute) and are NEVER counted as clean. ``by_flag`` carries each
    flag's own count. ``clean + flagged + unassessed == n``.
    """
    from coach.grading_quality import FLAGS, is_clean  # local: coach_record is imported by the grader's own helpers

    out: dict = {"clean": 0, "flagged": 0, "unassessed": 0, "n": 0, "by_flag": {f: 0 for f in FLAGS}}
    for row in decided or []:
        if not isinstance(row, dict) or graded_status(row) is None:
            continue
        out["n"] += 1
        verdict = is_clean(row)
        if verdict is None:
            out["unassessed"] += 1
            continue
        if verdict:
            out["clean"] += 1
            continue
        out["flagged"] += 1
        for f in row.get("quality_flags") or []:
            if f in out["by_flag"]:
                out["by_flag"][f] += 1
    return out


# ── #4617: what the record counts ─────────────────────────────────────────────────────────
# "N of M checked calls right" counted three different things as one: calls sealed before
# day one, calls whose measure and direction a model read out of in-experiment commentary,
# and conditional/hedged sentences graded on their outcome with the condition never checked.
# Nothing is dropped from the count; every decided row is exactly ONE of these classes, and
# the served sentence names each class's count so the reader knows what the number is.

#: Every decided call is exactly one of these, in the order a sentence names them.
CALL_KINDS = ("sealed", "bet", "commentary", "conditional")
CALL_KIND_WORDS = {
    "sealed": ("sealed before day one", "sealed before day one"),
    "bet": ("side of a bet between two coaches", "sides of bets between two coaches"),
    "commentary": ("read out of the coaches' running commentary", "read out of the coaches' running commentary"),
    "conditional": ("conditional or hedged sentence", "conditional or hedged sentences"),
}
#: A conditional or hedged sentence is not falsifiable by the measure alone (the one
#: definition — ``web.site_api_calls`` reads it from here).
CONDITIONAL_RE = re.compile(r"\b(if|unless|once|when|whenever|assuming|provided|until|may|might|could)\b", re.IGNORECASE)


def call_class(row: dict) -> str:
    """Which of ``CALL_KINDS`` a graded PREDICTION# row is (never None — nothing is dropped).

    sealed  — ``pre_registered`` (frozen before Day 1 as a measure, a direction and a window);
    bet     — a dispute-docket position (its criterion was frozen when the bet opened);
    conditional — a ``conditional`` spec, or a coach sentence that is conditional/hedged;
    commentary  — everything else: a call a model read out of in-experiment commentary.
    """
    if row.get("pre_registered"):
        return "sealed"
    if row.get("source") == "dispute_docket":
        return "bet"
    raw_spec = row.get("evaluation")
    spec: dict = raw_spec if isinstance(raw_spec, dict) else {}
    if spec.get("type") == "conditional" or CONDITIONAL_RE.search(str(row.get("claim_natural") or "")):
        return "conditional"
    return "commentary"


def class_counts(decided: Iterable[Any]) -> dict:
    """``{class: {"n", "right"}}`` over DECIDED rows, every class present (zeros included)."""
    out = {k: {"n": 0, "right": 0} for k in CALL_KINDS}
    for row in decided or []:
        if not isinstance(row, dict) or graded_status(row) is None:
            continue
        c = out[call_class(row)]
        c["n"] += 1
        c["right"] += graded_status(row) == "confirmed"
    return out


def counted_text(counts: dict | None) -> str | None:
    """ "Counted: 9 sealed before day one, 59 read out of the coaches' running commentary and 6
    conditional or hedged sentences." — every non-empty class, in order; None when empty."""
    parts = []
    for key in CALL_KINDS:
        n = int(((counts or {}).get(key) or {}).get("n") or 0)
        if n:
            parts.append(f"{n} {CALL_KIND_WORDS[key][0 if n == 1 else 1]}")
    if not parts:
        return None
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Counted: {listed}."


_MONTH_WORDS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def day_words(iso: str | None) -> str:
    """'2026-09-26' -> 'September 26' (no ISO date reaches a reader sentence).

    A calendar day, read from the string's own slices — never parsed to an instant
    (#3609: a YYYY-MM-DD day needs no parser; every date comparison in this module is
    likewise lexical on the ISO string).
    """
    text = str(iso or "")[:10]
    if len(text) != 10 or not (text[5:7].isdigit() and text[8:10].isdigit()):
        return ""
    month, day = int(text[5:7]), int(text[8:10])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{_MONTH_WORDS[month - 1]} {day}"


def headline(record: dict | None) -> str:
    """The one-line record a roster prints.

    None (read failed) → "record unavailable"; n = 0 → "no checked call yet"; below
    ``PERCENT_FLOOR`` → "0 of 5 checked calls right through September 26"; at or above it
    the percentage rides beside the counts, never instead of them.
    """
    if record is None:
        return "record unavailable"
    n = int(record.get("n") or 0)
    if n == 0:
        return "no checked call yet"
    k = int(record.get("confirmed") or 0)
    calls = "checked call" if n == 1 else "checked calls"
    through = day_words(record.get("through"))
    tail = f" through {through}" if through else ""
    if n < PERCENT_FLOOR:
        return f"{k} of {n} {calls} right{tail}"
    return f"{k} of {n} {calls} right ({round(k / n * 100):.0f}%){tail}"


def _query_rows(table: Any, coach_id: str) -> list:
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"),
        "ExpressionAttributeNames": dict(_PROJECTION_NAMES),
        "ProjectionExpression": ", ".join(_PROJECTION_NAMES),
    }
    rows: list = []
    for _ in range(_MAX_PAGES):
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = dict(kwargs, ExclusiveStartKey=last)
    return rows


def for_coach(table: Any, coach_id: str, *, genesis: str | None, as_of: str | None = None) -> dict | None:
    """The current-cycle record for one coach, or None when the read failed."""
    return for_coach_with_rows(table, coach_id, genesis=genesis, as_of=as_of)[0]


def for_coach_with_rows(table: Any, coach_id: str, *, genesis: str | None, as_of: str | None = None) -> tuple[dict | None, list[dict]]:
    """``(record, decided_rows)`` from ONE read — the record and the exact rows it counted.

    ``(None, [])`` when the read failed: a consumer drawing cards from the rows draws none
    rather than falling back to a second derivation.
    """
    if not coach_id or table is None:
        return None, []
    try:
        rows = _query_rows(table, coach_id)
        return record_from_rows(rows, genesis=genesis, as_of=as_of), decided_rows(rows, genesis=genesis)
    except Exception as exc:  # noqa: BLE001 — absence is the honest degradation, logged
        logger.warning("[coach_record] %s: %s", coach_id, exc)
        return None, []
