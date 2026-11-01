"""site_api_series.py — GET /api/series?metric=<key>&from=&to=: one metric, every day (#5532, epic #5529).

The v9 data room (`www/`, #5530) draws from one producer. Before this route a daily series
existed only inside the page bodies that happened to carry it (`/api/pulse_history` for the
weigh-in, `/api/sleep_detail`, `/api/nutrition_overview`, …), each over its own window and
with its own idea of an empty day. This is THE per-metric reader: one key, one window, one
row per calendar day, and two flags that keep absence honest (ADR-104):

    {metric, unit, source_id, method_ids, as_of, window: {from, to},
     days: [{date, value | null, present, gap}]}

  * ``present``  — a measured value is served for the day.
  * ``gap``      — a BEHAVIORAL source (the food diary) has a row for the day that records
                   no entries. The stored stub (#5519: ``entries_count=0``, ``food_log=[]``,
                   80 kcal / 15 g from a pre-filled scheduled item) is not a measurement, so
                   the value is withheld and the day is marked a logging gap — distinct from a
                   day the source has no row for at all (``present: false, gap: false``).

WHICH KEYS. The offered keys are the ones the data room charts and the coaches are graded on;
each resolves to the SAME source partition the grader reads
(``experiment.measurable_metrics.METRIC_SOURCES`` — the #813 invariant that the key IS the
stored attribute name), and steps resolve per day through the one read-side resolver
(``common.metric_truth``, #4630) so this route never re-decides whose count a day is.

PRIVACY. Every served key passes ``privacy.field_tiers.is_publishable`` on its source + field
at request time; a key that does not — and a key this module has never heard of — is the same
404, so the response cannot say which restricted fields exist. The daily nutrition TOTALS are
already published on `/api/nutrition_overview` and the character sheet; the MacroFactor
partition's owner-only SOURCE tier covers the meal-level log (``food_log``, food names —
``privacy.food_names``), which this route never projects.

The bare route (no ``metric``) answers the catalogue of offered keys, so the #2652 API sweep
has a 200 to probe. A ``from``/``to`` that is not a calendar day is a 400.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from common import metric_truth
from common.pacific_time import pacific_today, parse_day_key
from experiment.measurable_metrics import METRIC_SOURCES
from ingestion.source_registry import SOURCE_REGISTRY
from privacy.field_tiers import is_publishable, tier_of

from web.prediction_reason import metric_unit
from web.site_api_common import EXPERIMENT_START, _error, _ok, _query_source, logger

SOURCE = "/api/series"
CACHE_SECONDS = 600
#: The longest window one request serves (days). The experiment is weeks long; a year of
#: daily rows is the generous bound, not a working limit.
MAX_SPAN_DAYS = 400
EARLIEST_DAY = "2024-01-01"
NOT_SERVED = "No series is served under that key."
BAD_DAY = "from/to must be calendar days (YYYY-MM-DD)."
UNAVAILABLE = "The series is not served right now."


@dataclass(frozen=True)
class SeriesSpec:
    """One offered key: where its value is read from, and in what unit."""

    key: str
    source: str  # the partition read — `METRIC_SOURCES`' answer, or the resolver's id for steps
    field: str  # the stored attribute on that partition (the #813 invariant)
    unit: str | None
    resolver: str | None = None  # a metric_truth metric id when the value is resolved per day (steps)

    @property
    def behavioral(self) -> bool:
        """A record exists only when he does something (logs food) — the source registry's facet."""
        return bool((SOURCE_REGISTRY.get(self.source) or {}).get("behavioral"))


def _spec(key: str, metric_key: str | None = None) -> SeriesSpec:
    metric_key = metric_key or key
    source = METRIC_SOURCES[metric_key]
    unit = (metric_unit(metric_key) or "").strip() or None  # the registry's display suffix (" lb") as a bare unit
    return SeriesSpec(key, source, metric_key, unit, metric_truth.resolved_metric(source))


#: The offered keys. `resting_hr` is the data room's name for the grader's `resting_heart_rate`.
SERIES: dict[str, SeriesSpec] = {
    "weight_lbs": _spec("weight_lbs"),
    "sleep_duration_hours": _spec("sleep_duration_hours"),
    "hrv": _spec("hrv"),
    "resting_hr": _spec("resting_hr", "resting_heart_rate"),
    "recovery_score": _spec("recovery_score"),
    "deep_pct": _spec("deep_pct"),
    "rem_pct": _spec("rem_pct"),
    "total_protein_g": _spec("total_protein_g"),
    "total_calories_kcal": _spec("total_calories_kcal"),
    "steps": _spec("steps"),
}

#: The attributes a behavioral source's row needs for the logging-gap test, beside the value.
_GAP_FIELDS = ("entries_count", "food_log", "_format")


def publishable(spec: SeriesSpec) -> bool:
    """May this key appear on a public surface? Every source the value can come from must pass."""
    sources = metric_truth.sources_for(spec.resolver) if spec.resolver else (spec.source,)
    if spec.resolver:
        facet = metric_truth.metric_truth(spec.resolver)
        return all(is_publishable(tier_of(src, facet["field_by_source"][src])) for src in sources)
    return is_publishable(tier_of(spec.source, spec.field))


def offered() -> list[dict]:
    """The catalogue: every publishable offered key with its unit and source."""
    return [{"metric": k, "unit": s.unit, "source_id": s.source, "behavioral": s.behavioral} for k, s in SERIES.items() if publishable(s)]


def _num(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _row_day(row: dict) -> str | None:
    d = row.get("date")
    if isinstance(d, str) and len(d) >= 10:
        return d[:10]
    sk = row.get("sk")
    if isinstance(sk, str) and sk.startswith("DATE#") and len(sk) == 15:
        return sk[5:]
    return None


def logging_gap(row: dict) -> bool:
    """A behavioral row that records no entries (#5519's stub class): ``entries_count == 0``, or an
    explicitly empty ``food_log`` with no count saying otherwise."""
    count = row.get("entries_count")
    if count is not None:
        return _num(count) == 0
    log = row.get("food_log")
    return isinstance(log, list) and not log


def days_between(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _resolved_days(spec: SeriesSpec, start: str, end: str, query: Callable) -> tuple[dict[str, float], dict[str, str]]:
    rows_by_source = {src: query(src, start, end) for src in metric_truth.sources_for(spec.resolver)}
    resolved = metric_truth.resolve_by_date(spec.resolver, rows_by_source)
    values = {d: r.value for d, r in resolved.items() if r.value is not None}
    sources = {d: r.source for d, r in resolved.items() if r.value is not None and r.source}
    return values, sources


def series_days(spec: SeriesSpec, start: str, end: str, *, query: Callable = _query_source) -> list[dict]:
    """Every calendar day in ``start..end`` as ``{date, value, present, gap}`` — pure given ``query``."""
    gaps: set[str] = set()
    sources: dict[str, str] = {}
    if spec.resolver:
        values, sources = _resolved_days(spec, start, end, query)
    else:
        projection = ("date", spec.field) + (_GAP_FIELDS if spec.behavioral else ())
        values = {}
        for row in query(spec.source, start, end, projection=projection):
            d = _row_day(row)
            if not d:
                continue
            if spec.behavioral and logging_gap(row):
                gaps.add(d)
                continue
            v = _num(row.get(spec.field))
            if v is not None and (d not in values or v > values[d]):
                values[d] = v
    out = []
    for d in days_between(start, end):
        v = values.get(d)
        day = {"date": d, "value": v, "present": v is not None, "gap": d in gaps and v is None}
        if spec.resolver and d in sources:
            day["source_id"] = sources[d]
        out.append(day)
    return out


def _window(qs: dict, today: str) -> tuple[str, str] | None:
    start = str(qs.get("from") or EXPERIMENT_START).strip()
    end = str(qs.get("to") or today).strip()
    if parse_day_key(start) is None or parse_day_key(end) is None:
        return None
    start, end = max(start, EARLIEST_DAY), min(end, today)
    if start > end:
        return None
    if (date.fromisoformat(end) - date.fromisoformat(start)).days >= MAX_SPAN_DAYS:
        start = (date.fromisoformat(end) - timedelta(days=MAX_SPAN_DAYS - 1)).isoformat()
    return start, end


def handle_series(event, *, query: Callable = _query_source, today: str | None = None):
    """GET /api/series — see the module docstring. ``query`` is the injectable row reader."""
    qs = event.get("queryStringParameters") or {}
    today = today or pacific_today()
    key = str(qs.get("metric") or "").strip()
    if not key:
        return _ok({"metrics": offered(), "as_of": today, "source": SOURCE}, cache_seconds=CACHE_SECONDS)
    spec = SERIES.get(key)
    if spec is None or not publishable(spec):
        return _error(404, NOT_SERVED)  # one answer for "unknown" and "restricted": nothing to enumerate
    window = _window(qs, today)
    if window is None:
        return _error(400, BAD_DAY)
    start, end = window
    try:
        days = series_days(spec, start, end, query=query)
    except Exception as e:  # noqa: BLE001 — a failed read is a 503, never an empty series
        logger.error(f"[series] {key} {start}..{end}: {type(e).__name__}: {e}")
        return _error(503, UNAVAILABLE)
    return _ok(
        {
            "metric": key,
            "unit": spec.unit,
            "source_id": spec.source,
            "method_ids": [],  # a raw daily series carries no statistic; the pair table (/api/pairs) names its methods
            "as_of": today,
            "window": {"from": start, "to": end},
            "behavioral": spec.behavioral,
            "days": days,
            "n_present": sum(1 for d in days if d["present"]),
            "n_gap": sum(1 for d in days if d["gap"]),
        },
        cache_seconds=CACHE_SECONDS,
    )
