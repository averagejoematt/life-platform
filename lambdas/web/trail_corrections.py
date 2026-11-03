"""trail_corrections.py — the coach page's learning trail, read against the ledger it came from (#5626).

WHY. A coach's LEARNING# rows are written ONCE, by the evaluator, at the moment a call is first graded.
A grade correction (``coach.grade_corrections``, the 1 November #5533 batch, the owner-ruled retirement of
2026-11-03) rewrites the PREDICTION# row — ``status``, ``outcome_notes``, ``corrections[]`` — and never the
LEARNING# row. So ``/api/coach/<id>`` kept serving the first grade: on 2026-11-03 the explorer's page showed
``pred_20261015_if_october_5_6_protein_dropped_below_150`` as "confirmed … 98 → 15 g" while
``/api/ledger_export`` served the same call as refuted, corrected on 1 November. And the mind coach's page
served a call the ledger withholds by the journal-silence rule (#5131).

THE FIX IS AT READ TIME. The LEARNING# rows are history and stay exactly as written (owner: a change must
never silently rewrite history); nothing in this module writes. For each trail entry tied to a prediction the
page now reads that prediction's row and:

* **withheld** — a row the ledger cannot serve (``site_api_ledger_export.servable``: the journal-silence scrub
  of its ledger item, the SAME rule ``/api/ledger_export`` applies before paging) drops the trail entry too;
* **corrected** — a current status (``site_api_ledger_export.bucket_status``, the ledger's own vocabulary) that
  differs from the trail's grade serves the CURRENT verdict as ``status``, the grader's current reason as
  ``reason``, and ``grade_correction``: the trail's original verdict and reason, the corrected verdict, the
  correction's recorded instant and its plain-words explanation — both from ``web.correction_history`` /
  ``web.correction_rules`` through ``site_api_ledger_export.corrections_of``, never a second copy. A row whose
  status moved with no correction recorded serves ``corrected_at: None`` and ``explanation: None`` (never
  invented);
* **unchanged** — everything else passes through untouched.

THE READ. One GetItem per DISTINCT prediction the candidate trail names, run concurrently
(``site_api_coach_ledger._parallel_fetch``); the trail is at most 60 rows. GetItem, not BatchGetItem: the
site-api role grants ``GetItem``/``Query`` only, and a code fix should not ride an IAM change. A read that
FAILS withholds the entries tied to it (it cannot be checked, so it is not served as if it had been); a row
that does not exist leaves its entry unchanged (there is nothing to contradict it).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from coach import coach_dossier

from web import site_api_ledger_export
from web.site_api_coach_ledger import _parallel_fetch
from web.site_api_common import _decimal_to_float, logger

#: Bound on the distinct predictions one trail read may fetch (the callers query 60 LEARNING# rows).
MAX_FETCH = 60


def prediction_id_of(entry: dict) -> str:
    """The prediction a trail entry names: a raw LEARNING# row's ``prediction_id`` or a dossier entry's evidence."""
    pid = entry.get("prediction_id")
    if not pid and isinstance(entry.get("evidence"), dict):
        pid = entry["evidence"].get("prediction_id")
    return str(pid or "").strip()


def short_id_of(coach_id: str) -> str:
    """``explorer_coach`` → ``explorer`` — the ledger's coach id."""
    return coach_id[: -len("_coach")] if coach_id.endswith("_coach") else coach_id


def fetch_predictions(table: Any, coach_id: str, pids: Iterable[str]) -> tuple[dict[str, dict | None], set[str]]:
    """``({pid: row or None}, failed_pids)`` — one concurrent GetItem per distinct pid (at most ``MAX_FETCH``)."""
    wanted = list(dict.fromkeys(p for p in pids if p))[:MAX_FETCH]
    pk = f"COACH#{coach_id}"

    def _job(pid: str) -> Callable[[], Any]:
        return lambda: table.get_item(Key={"pk": pk, "sk": f"PREDICTION#{pid}"}).get("Item") or {}

    failures: list = []
    fetched = _parallel_fetch({pid: _job(pid) for pid in wanted}, failures=failures)
    rows = {pid: (_decimal_to_float(fetched.get(pid)) or None) for pid in wanted if pid not in failures}
    if failures:
        logger.warning(f"[trail_corrections] {coach_id}: {len(failures)} prediction reads failed — their trail entries are withheld")
    return rows, set(failures)


def ledger_withholds(coach_id: str, row: dict) -> bool:
    """True when ``/api/ledger_export`` cannot serve this row: its ledger item fails the #5131 journal-silence scrub."""
    item = site_api_ledger_export.export_item(short_id_of(coach_id), row)
    _kept, withheld = site_api_ledger_export.servable([item])
    return withheld > 0


def _correction_of(row: dict, current: str) -> dict:
    """The recorded correction that produced ``current`` — the newest whose corrected verdict is ``current``,
    else the newest of all; ``{}`` when the row stores none."""
    history = site_api_ledger_export.corrections_of(row, None)
    for c in reversed(history):
        if c.get("corrected_status") == current:
            return c
    return history[-1] if history else {}


def _current_reason(row: dict, translate: Callable[[str], str]) -> str | None:
    """The grader's current reason, as the ledger serves it, through the page's reader translation and the
    dossier filter (fail-closed: a filter that cannot load withholds the words)."""
    text = site_api_ledger_export.grading_block(row).get("outcome_notes")
    text = str(translate(text) if text else "").strip()
    if not text:
        return None
    try:
        return text if coach_dossier.dossier_safe(text) else None
    except Exception as e:  # noqa: BLE001 — the vocabulary channel failing withholds, never serves
        logger.warning(f"[trail_corrections] dossier filter unavailable ({type(e).__name__}) — current reason withheld")
        return None


def reconcile_entry(entry: dict, row: dict | None, coach_id: str, translate: Callable[[str], str] = lambda s: s) -> dict | None:
    """One trail entry against its prediction row — pure. ``None`` = withheld; otherwise the entry to serve
    (a NEW dict when corrected; the input is never mutated)."""
    if not row:
        return entry
    if ledger_withholds(coach_id, row):
        return None
    original = str(entry.get("status") or "")
    current = site_api_ledger_export.bucket_status(row)
    if not original or current == original:
        return entry
    c = _correction_of(row, current)
    out = dict(entry)
    out["status"] = current
    out["reason"] = _current_reason(row, translate)
    out["grade_correction"] = {
        "original_status": original,
        "original_reason": entry.get("reason"),
        "corrected_status": current,
        "corrected_at": c.get("corrected_at"),  # the stored instant, verbatim; None when none was recorded
        "explanation": c.get("explanation"),
    }
    return out


def reconcile(
    entries: list[dict],
    table: Any,
    coach_id: str,
    *,
    translate: Callable[[str], str] = lambda s: s,
    fetch: Callable[..., tuple[dict, set]] = fetch_predictions,
) -> tuple[list[dict], dict]:
    """``(served_entries, counts)`` — every entry tied to a prediction read against it (one bounded fetch).
    ``counts`` = ``{corrected, withheld, unverified}``; order is preserved."""
    pids = [prediction_id_of(e) for e in entries]
    rows, failed = fetch(table, coach_id, [p for p in pids if p]) if any(pids) else ({}, set())
    out: list[dict] = []
    counts = {"corrected": 0, "withheld": 0, "unverified": 0}
    for entry, pid in zip(entries, pids):
        if not pid:
            out.append(entry)
            continue
        if pid in failed or (pid not in rows):
            counts["unverified"] += 1  # a failed read, or past the fetch bound: not served as if checked
            continue
        served = reconcile_entry(entry, rows.get(pid), coach_id, translate)
        if served is None:
            counts["withheld"] += 1
            continue
        if served is not entry:
            counts["corrected"] += 1
        out.append(served)
    return out, counts


def reconcile_until(
    entries: list[dict],
    want: int,
    table: Any,
    coach_id: str,
    *,
    chunk: int = 30,
    translate: Callable[[str], str] = lambda s: s,
    fetch: Callable[..., tuple[dict, set]] = fetch_predictions,
) -> tuple[list[dict], dict]:
    """``reconcile`` over the trail in order, a chunk at a time, until ``want`` entries are served — so a page
    that shows six lines reads about six predictions, not sixty. ``counts`` sum over the chunks read."""
    out: list[dict] = []
    counts = {"corrected": 0, "withheld": 0, "unverified": 0}
    i = 0
    while len(out) < want and i < len(entries):
        served, c = reconcile(entries[i : i + chunk], table, coach_id, translate=translate, fetch=fetch)
        out.extend(served)
        for k in counts:
            counts[k] += c[k]
        i += chunk
    return out[:want], counts
