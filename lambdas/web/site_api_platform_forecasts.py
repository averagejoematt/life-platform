"""site_api_platform_forecasts.py — GET /api/platform_forecasts: the rules-based platform forecasts, as a reader sees them (#6170).

WHAT. Every rules-based platform forecast of this cycle that the publication policy lets out (``coach.public_forecast``
files them into ``USER#matthew#SOURCE#public_forecast``; ``common.prediction_publication`` keeps EVERY one private while
``common.public_forecast_policy.STREAM_LIVE`` is off, so until the owner's switch this route serves an empty list), in
the shape the call page prints (``www/src/pages/system/forecasts/[id].astro``) and the reader-call door addresses
(``call`` = ``forecast:<id>``, ``web.site_api_reader_call.load_forecast``).

WHAT IT IS NOT. Never a coach's call: the author is the machine's own label ("Rules-based platform forecast"), never a
coach name. Never part of any coach's record, ``/api/ledger_export``, ``/api/predictions`` or ``/api/calibration``: those
read ``COACH#`` partitions only, and this route reads only the forecast partition. The "nothing changes" guess graded
beside each forecast is served as its own field (``guess``), under its own rule id.

READ-ONLY. One ``Query`` of one partition through the governed table; no write, no AI. The ids are a date and a rule
name (``pred_<YYYYMMDD>_forecast_<rule>``), never words, and are served under ``id`` / ``call`` — not the
``prediction_id`` / ``item_id`` keys ``web.public_call_id.publicize`` rewrites for coach calls.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from boto3.dynamodb.conditions import Key
from coach import coach_record, prediction_windows
from common import public_forecast_policy as FPOL
from common.pacific_time import pacific_today

from web import reader_call_rules as R

CACHE_SECONDS = 300
SOURCE = "/api/platform_forecasts"
UNAVAILABLE = "Platform forecasts are unavailable right now."
_GRADED = ("confirmed", "refuted")
#: The fields a served forecast carries (the snapshot producer checks the same set: scripts/publish_snapshot_forecasts.py).
FIELDS = (
    "id",
    "call",
    "label",
    "author_words",
    "rule",
    "metric",
    "measure",
    "unit",
    "claim",
    "made",
    "target_date",
    "reader_calls_close",
    "result_due",
    "status",
    "evaluation_rule",
    "scoring",
    "forecast",
    "guess",
    "inputs",
    "graded",
)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def served(row: dict, genesis: Optional[str]) -> Optional[dict]:
    """One forecast row in its public shape, or None when it is not a forecast this route serves."""
    from web.prediction_reason import _notes, metric_unit, metric_words

    if not isinstance(row, dict) or row.get("coach_id") != "" or row.get("record") != FPOL.RECORD:
        return None
    if row.get("source") != FPOL.FORECAST_SOURCE or not coach_record.counts_this_cycle(row, genesis):
        return None
    ev = row.get("evaluation")
    spec: dict = ev if isinstance(ev, dict) else {}
    pid = coach_record.prediction_key(row)
    status = str(row.get("status") or "")
    if R.call_kind(spec) != R.CLOSER or not pid or status not in ("pending", *_GRADED):
        return None
    made = str(row.get("created_date") or "")[:10]
    due = prediction_windows.due_date(made, spec, row.get("subdomain", ""))
    eff = prediction_windows.effective_window_days(spec, row.get("subdomain", ""))
    m, li = row.get("model"), row.get("lineage")
    model: dict = m if isinstance(m, dict) else {}
    lin: dict = li if isinstance(li, dict) else {}
    w = lin.get("window")
    window: dict = w if isinstance(w, dict) else {}
    notes = _notes(row.get("outcome_notes")) if status in _GRADED else {}
    side = R.reading_side(spec, notes) if status in _GRADED else None
    return {
        "id": pid,
        "call": f"{FPOL.READER_SHORT}:{pid}",
        "label": FPOL.LABEL,
        "author_words": FPOL.AUTHOR_WORDS,
        "rule": {"id": str(model.get("id") or ""), "version": model.get("version"), "words": str(model.get("words") or "")},
        "metric": spec.get("metric"),
        "measure": metric_words(spec.get("metric")),
        "unit": metric_unit(spec.get("metric")),
        "claim": str(row.get("claim_natural") or ""),
        "made": made,
        "target_date": spec.get("target_date"),
        "reader_calls_close": R.open_until(spec, made, eff, due),
        "result_due": due,
        "status": status,
        "evaluation_rule": str(row.get("evaluation_rule") or ""),
        "scoring": {"rule": spec.get("scoring"), "version": spec.get("scoring_version"), "words": FPOL.SCORING_WORDS},
        "forecast": _num(spec.get("threshold")),
        "guess": {"value": _num(spec.get("baseline_value")), "on": spec.get("baseline_on"), "words": "a guess that nothing changes"},
        "inputs": {
            "route": lin.get("route"),
            "url": lin.get("url"),
            "from": window.get("from"),
            "to": window.get("to"),
            "n": lin.get("n"),
            "sha256": lin.get("sha256"),
        },
        "graded": (
            {
                "status": status,
                "actual": _num(notes.get("actual_value")),
                "reading_side": side,
                "on": str(row.get("outcome_date") or "")[:10] or None,
            }
            if status in _GRADED
            else None
        ),
    }


def _query_forecasts(table: Any) -> list:
    items: list = []
    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(FPOL.FORECAST_PK) & Key("sk").begins_with(FPOL.SK_PREFIX)}
    while True:
        resp = table.query(**kwargs)
        items += resp.get("Items") or []
        if not resp.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def handle_platform_forecasts(event, *, table: Any = None, today: Optional[str] = None, query: Optional[Callable] = None):
    """GET /api/platform_forecasts — see the module docstring."""
    from web.site_api_common import EXPERIMENT_START, _error, _ok, logger, table as default_table

    today = today or pacific_today()
    try:
        rows = (query or _query_forecasts)(default_table if table is None else table)
    except Exception as e:  # noqa: BLE001 — a failed read is a 503, never an empty list
        logger.error(f"[platform_forecasts] read failed: {type(e).__name__}")
        return _error(503, UNAVAILABLE)
    out = [f for f in (served(r, EXPERIMENT_START) for r in rows) if f is not None]
    out.sort(key=lambda f: (f["made"], f["id"]), reverse=True)
    return _ok({"as_of": today, "source": SOURCE, "label": FPOL.LABEL, "forecasts": out}, cache_seconds=CACHE_SECONDS)
