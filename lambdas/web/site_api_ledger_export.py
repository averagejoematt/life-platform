"""site_api_ledger_export.py — GET /api/ledger_export?page=N&size=100: the whole ledger, paged (#5532).

WHY. The v9 ledger (`www/`, epic #5529) gives every prediction its own page. The two existing
reads cannot feed that: `/api/calls` serves the settled calls whose own sentence states what
was graded (63 of 214 graded on 2026-10-31), and `/api/predictions` serves at most 200 rows
and no id. This route pages EVERY row the season's record counts — one item per
prediction, under its stored id — so the build can render all of them from one producer.

WHAT IS COUNTED. Exactly the row-set `/api/predictions` counts as ``overall.total``: every
coach partition (retired seats included — a career record stays under its real byline),
re-writes removed (``coach_record.resolved_once``), rows of this cycle only
(``coach_record.counts_this_cycle`` — phase-visible, and a graded row resolved on or after
genesis). Observations are in (status ``observational``); diary claims are not — they live
under ``USER#…#SOURCE#diary_claims`` with ``coach_id=""`` and are never a coach's call.
``total`` therefore equals ``/api/predictions`` ``overall.total`` by construction, and
``tests/test_v9_api_routes_5532.py`` asserts it on the captured partition rows.

THE ITEM. Every field is read off the stored row or derived by the module that owns the
derivation — never a second copy: the four record kinds and the "nothing changes" verdict
from ``coach.coach_baseline``, the due day from ``coach.prediction_windows``, the grader's
reason in reader words from ``web.prediction_reason``, the simple-guess sentence from
``web.site_api_calls``. ``quality_flags`` and ``corrections`` are the grader's (#5533): read
off the row when present, ``[]`` otherwise — a row written before the grader stamped them is
an empty list, not a missing key.

    {items: [{prediction_id, coach_id, coach_name, retired, metric, claim, logged_date,
              due_date, settled_date, kind, status, confidence, sealed,
              grading: {how, actual_text, tolerance_text, outcome_notes},
              simple_guess, quality_flags: [], corrections: []}],
     total, page, size, pages, as_of}

PRIVACY. A claim is served only when the dossier filter clears it (``coach_dossier.dossier_safe``,
the same gate `/api/calls` and the docket apply); a withheld claim is ``""`` with
``withheld: true`` — the row keeps its place and its grade, its words do not travel.

THE JOURNAL'S SILENCE (#5131). The Lambda's last step before the wire drops every list element
whose subtree speaks of the journal's silence (``common.journal_silence.guard_api_response``), and
a ledger row carries that pattern in its claim AND in its stored id (``…_journaling_silence_…``),
so such a row cannot be served at all — not even as a held row. Measured 2026-11-01: twelve of
468 rows. The wire guard ran AFTER this handler had counted and paged, so ``total`` named rows
no page could reach and a 100-row page came back with 97 (#5532). The handler now applies the
SAME scrub to the item set BEFORE paging: ``total`` and ``pages`` count what is served, every
page is whole, and ``withheld.journal_silence`` names how many rows the record counts that this
ledger does not show — the coaches' record (`/api/predictions` ``overall``) still counts them.

THE READ. One concurrent, projected Query per coach partition — the `/api/predictions` sweep
(``site_api_coach_ledger._query_partition`` / ``_parallel_fetch``), paginated to the end of
each partition because this projection carries the claim text. Every partition failing is a
503; a partial failure is served with ``degraded`` naming the partitions that did not answer,
so a short list is never mistaken for a short ledger (ADR-104).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from coach import coach_baseline, coach_dossier, coach_record, prediction_windows
from common import journal_silence
from common.pacific_time import pacific_date_of, pacific_today

from web import claim_sourcing, prediction_reason, site_api_calls
from web.site_api_coach_ledger import (
    _CALIB_COACH_NAMES,
    _PREDICTION_PROJECTION_FIELDS,
    _RETIRED_SHORT_IDS,
    PRESENCE_JOB,
    _instrument_presence_safe,
    _parallel_fetch,
    _query_partition,
)
from web.site_api_common import EXPERIMENT_START, _error, _ok, logger, table

SOURCE = "/api/ledger_export"
CACHE_SECONDS = 900
DEFAULT_SIZE = 100
MAX_SIZE = 200
BAD_PAGE = "page and size must be positive integers (size at most 200)."
UNAVAILABLE = "The ledger is not served right now."

#: The `/api/predictions` sweep's projection plus what this export serves beside it.
PROJECTION = tuple(dict.fromkeys(_PREDICTION_PROJECTION_FIELDS + ("sk", "coach_id", "quality_flags", "corrections", "gradeable_by")))

#: The status buckets `/api/predictions` counts — one vocabulary (DIL-007: observational is its own).
BUCKETS = ("confirmed", "refuted", "pending", "inconclusive", "expired", "observational")


def _spec(row: dict) -> dict:
    """The row's evaluation spec as a dict — ``{}`` when absent or not a map (eight live docket rows carry none)."""
    ev = row.get("evaluation")
    return ev if isinstance(ev, dict) else {}


def bucket_status(row: dict) -> str:
    """The served status of one row — the same classification `/api/predictions` tallies."""
    ev = _spec(row)
    status = str(row.get("status") or "pending")
    if status == "observation" or (not prediction_windows.is_gradeable(ev) and status in ("pending", "confirming")):
        return "observational"
    return status if status in BUCKETS else "pending"


def _num_text(value: Any, metric: Any) -> str | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    text = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{text}{prediction_reason.metric_unit(metric) or ''}"


def grading_block(row: dict) -> dict:
    """How the call was (or will be) graded, in words a page can print, from the spec and the grader's notes."""
    ev = _spec(row)
    notes = prediction_reason._notes(row.get("outcome_notes"))
    metric = ev.get("metric")
    words = prediction_reason.metric_words(metric) or (str(metric) if metric else None)
    kind = str(ev.get("type") or "").strip().lower()
    tolerance_text = None
    if kind == "point":
        tol = ev.get("tolerance")
        how = f"{words} within ±{_num_text(tol, metric) or '?'} of {_num_text(ev.get('threshold'), metric)}"
        if ev.get("target_date"):
            how += f" on {ev['target_date']}"
        tolerance_text = str(ev.get("tolerance_rule") or "").strip() or (f"±{_num_text(tol, metric)}" if tol is not None else None)
    elif kind == "directional":
        how = f"{words} trend {ev.get('condition') or '?'} over {int(ev.get('evaluation_window_days') or 0) or '?'} days"
    elif kind in ("machine", "conditional") and ev.get("threshold") is not None:
        how = f"{words} {ev.get('condition') or '?'} {_num_text(ev.get('threshold'), metric)}"
    elif kind in ("machine", "conditional"):
        how = f"{words} trend {ev.get('condition') or '?'}"
    elif words:
        how = f"{words}: an observation, not graded"
    else:
        how = "an observation, not graded"
    reason, _ = prediction_reason.reason_words(row)
    return {
        "how": how,
        # A point or threshold grade's actual is the reading; a trend grade's is a slope, not a measurement — no unit, no text.
        "actual_text": (
            _num_text(notes.get("actual_value"), metric)
            if kind == "point" or (kind in ("machine", "conditional") and ev.get("threshold") is not None)
            else None
        ),
        "tolerance_text": tolerance_text,
        "outcome_notes": reason or (str(notes.get("reason") or "").strip() or None),
    }


def _due(row: dict, ev: dict) -> str | None:
    if ev.get("type") == "point" and ev.get("target_date"):
        return str(ev["target_date"])[:10]
    if not prediction_windows.is_gradeable(ev):
        return None
    return prediction_windows.due_date(row.get("created_date"), ev, row.get("subdomain", ""))


def _list(value: Any) -> list:
    return [v for v in value] if isinstance(value, (list, tuple)) else []


def _dossier_safe(text: str) -> bool:
    """The dossier filter, failing CLOSED: a vocabulary that cannot be loaded withholds the words."""
    try:
        return coach_dossier.dossier_safe(text)
    except Exception as e:  # noqa: BLE001 — privacy.content_filter_channel.ContentFilterUnavailable and kin
        logger.warning(f"[ledger_export] dossier filter unavailable ({type(e).__name__}) — claim withheld")
        return False


def export_item(short_id: str, row: dict, dark: list | None = None) -> dict:
    """One PREDICTION# row as a ledger item — pure. ``dark`` is the interval form of the instrument gaps (#4702)."""
    ev = _spec(row)
    status = bucket_status(row)
    sealed = bool(row.get("pre_registered"))
    claim = str(row.get("claim_natural") or "").strip()
    withheld = bool(claim) and not _dossier_safe(claim)
    kind = coach_baseline.record_of(row) or "observation"
    said_on = claim_sourcing.claim_day(row)  # created_date, or a docket row's opened day from its id
    logged = (pacific_date_of(row.get("pre_registered_at")) if sealed else None) or said_on
    # #4701: a claim resting on an instrument that had sent no reading by the day it was said is not quoted —
    # the same hold /api/predictions and /api/calls apply; the row keeps its place and its grade.
    held = claim_sourcing.unsourced([claim], said_on, dark or []) if claim and not withheld else None
    pid = coach_record.prediction_key(row) or None
    item = {
        # The stored id is unique within a coach's partition, not across them: a docket bet is stamped on both
        # sides' rows under one id, and two coaches filing the same sentence on one day share a slug (measured
        # on the 2026-10-04 capture). `item_id` is the coach-scoped identity a page can address.
        "item_id": f"{short_id}:{pid}" if pid else None,
        "prediction_id": pid,
        "coach_id": short_id,
        "coach_name": _CALIB_COACH_NAMES.get(short_id, short_id),
        "retired": short_id in _RETIRED_SHORT_IDS,
        "metric": ev.get("metric"),
        "claim": "" if (withheld or held) else claim,  # held words are removed, never edited (#4701)
        "logged_date": logged,
        "due_date": _due(row, ev),
        "settled_date": str(row.get("outcome_date") or "")[:10] or None,
        "kind": kind,
        "status": status,
        "confidence": row.get("confidence"),
        "sealed": sealed,
        "grading": grading_block(row),
        "simple_guess": site_api_calls.simple_guess(row.get("baseline"), kind, coach_right=status == "confirmed", metric=ev.get("metric")),
        "quality_flags": _list(row.get("quality_flags")),
        "corrections": _list(row.get("corrections")),
    }
    if withheld:
        item["withheld"] = True
    if held:
        item["unsourced"] = held  # the same note shape /api/predictions, /api/calls and the docket serve
    return item


def servable(items: list[dict]) -> tuple[list[dict], int]:
    """``(served, withheld)``: the items the wire guard (#5131) would let through, and how many it would
    drop. The guard works on the serialised body; running its payload form here, on the SAME items, is
    what keeps ``total`` honest — a row it drops is counted as withheld, never as a page's missing seat."""
    kept, _hits = journal_silence.scrub_payload(items)
    kept = [i for i in kept if isinstance(i, dict)]
    return kept, len(items) - len(kept)


def export_items(rows_by_short: dict[str, list], genesis: str | None = EXPERIMENT_START, dark: list | None = None) -> list[dict]:
    """Every item the season's record counts, newest logged first — the `/api/predictions` row-set."""
    items = []
    for short_id, rows in rows_by_short.items():
        for row in coach_record.resolved_once(rows):
            if not isinstance(row, dict) or row.get("coach_id") == "":
                continue  # a diary claim's shape, never a coach's call
            if not coach_record.counts_this_cycle(row, genesis):
                continue
            items.append(export_item(short_id, row, dark))
    items.sort(key=lambda i: (str(i.get("logged_date") or ""), str(i.get("prediction_id") or "")), reverse=True)
    return items


def _page_args(qs: dict) -> tuple[int, int] | None:
    try:
        page = int(str(qs.get("page", "1")).strip())
        size = int(str(qs.get("size", str(DEFAULT_SIZE))).strip())
    except (TypeError, ValueError):
        return None
    if page < 1 or size < 1 or size > MAX_SIZE:
        return None
    return page, size


def _partition_job(pk: str, g: dict) -> Callable[[], list]:
    """One partition read as a thunk for the concurrent round — the whole PREDICTION# prefix, paginated."""
    return lambda: _query_partition(pk, "PREDICTION#", PROJECTION, paginate=True, _g=g)


def fetch_rows(*, _table=None) -> tuple[dict[str, list], list, list]:
    """Every coach's PREDICTION# partition, read concurrently, with the instrument-presence read riding the
    SAME round (#4701, the `/api/predictions` pattern); ``(rows_by_short, failed_short_ids, dark)``."""
    g = {"table": _table if _table is not None else table}
    failures: list = []
    jobs: dict[str, Callable[[], Any]] = {cid: _partition_job(f"COACH#{cid}_coach", g) for cid in _CALIB_COACH_NAMES}
    jobs[PRESENCE_JOB] = lambda: _instrument_presence_safe(_g=g)  # never raises, so it is never counted as a failed partition
    fetched = _parallel_fetch(jobs, failures=failures)
    dark = fetched.pop(PRESENCE_JOB, None) or []
    return fetched, sorted(f for f in failures if f != PRESENCE_JOB), dark


def handle_ledger_export(event, *, fetch: Callable = fetch_rows, today: str | None = None):
    """GET /api/ledger_export — see the module docstring. ``fetch`` is the injectable partition reader."""
    qs = event.get("queryStringParameters") or {}
    args = _page_args(qs)
    if args is None:
        return _error(400, BAD_PAGE)
    page, size = args
    today = today or pacific_today()
    try:
        rows_by_short, failed, dark = fetch()
        if failed and len(failed) >= len(_CALIB_COACH_NAMES):
            raise RuntimeError(f"all {len(failed)} coach partition reads failed: {failed}")
        counted = export_items(rows_by_short, dark=dark)
        items, withheld = servable(counted)
    except Exception as e:  # noqa: BLE001 — a failed read is a 503, never a shorter ledger
        logger.error(f"[ledger_export] {type(e).__name__}: {e}")
        return _error(503, UNAVAILABLE)
    total = len(items)
    start = (page - 1) * size
    payload = {
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, math.ceil(total / size)),
        "as_of": today,
        "source": SOURCE,
        # The record counts `record_total` rows; `total` is what this ledger serves. The difference is named,
        # never silent: rows the journal-silence guard keeps off every public surface (#5131).
        "record_total": len(counted),
        "withheld": {"journal_silence": withheld},
    }
    degraded = {"partitions_failed": failed} if failed else None
    if failed:
        logger.error(f"[ledger_export] degraded — {len(failed)} partitions failed: {failed}")
    return _ok(payload, cache_seconds=CACHE_SECONDS, degraded=degraded)
