"""metric_truth.py — THE read-side resolver for a metric carried by more than one source (#4630).

The owner rule of 2026-10-04 ("capture all, interpret later", docs/CONVENTIONS.md): each
ingestion writer stores its own source's value under that source and never picks a winner;
combining lives in ONE read-side resolver. This is that resolver. The precedence it applies
is the `METRIC_TRUTH` facet in `lambdas/ingestion/source_registry.py` — nothing here names a
source or a field, so changing the truth for a metric is a one-line registry edit.

Every reader of the day's step count calls `resolve_steps` (one day) or `steps_by_date`
(a range) instead of reading `steps` / `step_count` off a row;
`tests/test_steps_truth_resolver_4630.py` fails on a direct read anywhere else.

Pure functions only — no AWS. The caller fetches the rows for `sources_for(metric)` and hands
them in keyed by source id; a source it did not fetch is simply absent from the input, which
the resolver reports in its `reason` rather than hiding.

Reproduce one day from the stored rows (read-only): `python3 scripts/resolve_steps_day_4630.py --date YYYY-MM-DD`.

Truth modes (#4975). A facet's optional `mode` says how its sources combine, and `resolve` is
the ONE function every reader already goes through, so a mode change is a registry edit:
  * `primary` (the default, today's behaviour) — the facet's `overlap_rule` over `fallback_order`;
  * `primary_backup` — the truth source when it has a usable value, else the ONE named `backup`;
    `source_used` names which answered;
  * `mean` — the mean of the sources with a usable value, `n_sources` and the per-source
    `values` returned (a zero report joins only when no source has a positive value — the
    same rule that keeps a device's 0 from zeroing a day another device counted).
Which mode a metric gets is the owner's ruling (#4975 gate:owner, after the #4974 agreement
study); every facet on main is on `primary`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from ingestion.source_registry import metric_truth, source_label

STEPS = "steps"
VO2_MAX = "vo2_max"


@dataclass(frozen=True)
class Resolution:
    """One day's resolved value for a metric, with the evidence for it."""

    metric: str
    value: Optional[float]
    source: Optional[str]
    field: Optional[str]
    reason: str
    candidates: dict[str, Optional[float]] = dataclasses.field(default_factory=dict)
    mode: str = "primary"
    sources_used: tuple[str, ...] = ()

    @property
    def count(self) -> Optional[int]:
        """The value as an integer count (steps are counts), or None."""
        return None if self.value is None else int(round(self.value))

    @property
    def source_used(self) -> Optional[str]:
        """The ONE source that answered (primary / primary_backup, or a mean over one source);
        None for a mean over several — read `sources_used` / `values` then."""
        return self.source

    @property
    def n_sources(self) -> int:
        """How many sources the value was computed from (0 when nothing resolved)."""
        return len(self.sources_used)

    @property
    def values(self) -> dict[str, float]:
        """The per-source usable values the resolver saw (absent sources left out)."""
        return {s: v for s, v in self.candidates.items() if v is not None}


def sources_for(metric: str) -> tuple[str, ...]:
    """The source ids a caller must fetch for `metric`, in precedence order."""
    return tuple(metric_truth(metric)["fallback_order"])


def _num(raw: Any) -> Optional[float]:
    """A stored numeric (Decimal from DynamoDB, int, float or numeric string) as float.

    A bool is refused (True is not one step); anything non-numeric is absent."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            v = float(raw)
        except (InvalidOperation, ValueError, OverflowError):
            return None
        return v if v == v else None  # NaN is absent
    if isinstance(raw, str):
        try:
            v = float(raw.strip())
        except ValueError:
            return None
        return v if v == v else None
    return None


def source_value(metric: str, source: str, row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """`source`'s usable value for `metric` on one stored row, or None.

    0 is kept (a zero REPORT — see `resolve`); a negative value, a non-number, or a positive
    value below the source's `min_by_source` floor (Garmin's ~298 partial-sync row) is None."""
    if not row:
        return None
    facet = metric_truth(metric)
    fld = facet["field_by_source"].get(source)
    if fld is None:
        return None
    v = _num(row.get(fld))
    if v is None or v < 0:
        return None
    if v == 0:
        return 0.0
    floor = facet["min_by_source"].get(source, 0)
    return v if v >= floor else None


def _why_skipped(facet: Mapping[str, Any], rows: Mapping[str, Any], candidates: Mapping[str, Optional[float]], src: str) -> str:
    if src not in rows:
        return f"{src} (not fetched)"
    if candidates.get(src) == 0:
        return f"{src} (reported 0)"
    return f"{src} (no usable {facet['field_by_source'][src]})"


def resolve(metric: str, rows: Mapping[str, Optional[Mapping[str, Any]]]) -> Resolution:
    """Resolve one day of `metric` from `{source_id: stored DATE# row or None}`.

    The overlap rule is the facet's `first_positive_else_first_zero`: the first source in
    `fallback_order` with a POSITIVE value wins. Only when no source has one does a zero
    report count — the highest-precedence source that reported 0 — so a genuine 0-step day
    is a reading, not an absence (#1658), while a device that reports 0 on a day another
    device counted steps never zeroes the day. The losers ride in `candidates` so a reader
    (or the reproduce command) can show what lost and by how much."""
    facet = metric_truth(metric)
    order = facet["fallback_order"]
    candidates: dict[str, Optional[float]] = {src: source_value(metric, src, rows.get(src)) for src in order}
    mode = facet.get("mode", "primary")
    if mode == "primary_backup":
        return _resolve_primary_backup(metric, facet, rows, candidates)
    if mode == "mean":
        return _resolve_mean(metric, facet, candidates)
    return _resolve_primary(metric, facet, rows, candidates)


def _resolve_primary(metric: str, facet: Mapping[str, Any], rows: Mapping[str, Any], candidates: dict[str, Optional[float]]) -> Resolution:
    """Mode `primary` — the facet's overlap_rule (first_positive_else_first_zero), unchanged."""
    order = facet["fallback_order"]
    fields = facet["field_by_source"]
    for rank, src in enumerate(order):
        v = candidates[src]
        if v is None or v == 0:
            continue
        if rank == 0:
            why = f"{src} is the truth source and has a count"
        else:
            why = f"fallback #{rank + 1}: {', '.join(_why_skipped(facet, rows, candidates, s) for s in order[:rank])} → {src}"
        return Resolution(metric, v, src, fields[src], why, candidates, "primary", (src,))
    for src in order:
        if candidates[src] == 0:
            return Resolution(
                metric, 0.0, src, fields[src], f"no source has a positive count; {src} reported 0", candidates, "primary", (src,)
            )
    return Resolution(metric, None, None, None, "no source has a usable count", candidates, "primary")


def _resolve_primary_backup(
    metric: str, facet: Mapping[str, Any], rows: Mapping[str, Any], candidates: dict[str, Optional[float]]
) -> Resolution:
    """Mode `primary_backup` — the truth source when it has a usable value (0 included: a
    reading is a reading), else the facet's ONE `backup`. No third source is ever consulted."""
    fields = facet["field_by_source"]
    primary, backup = facet["truth_source"], facet["backup"]
    seen = {s: candidates.get(s) for s in (primary, backup)}
    if seen[primary] is not None:
        return Resolution(
            metric, seen[primary], primary, fields[primary], f"{primary} is the primary and has a value", seen, "primary_backup", (primary,)
        )
    if seen[backup] is not None:
        why = f"backup: {_why_skipped(facet, rows, seen, primary)} → {backup}"
        return Resolution(metric, seen[backup], backup, fields[backup], why, seen, "primary_backup", (backup,))
    return Resolution(metric, None, None, None, "neither the primary nor the backup has a usable value", seen, "primary_backup")


def _resolve_mean(metric: str, facet: Mapping[str, Any], candidates: dict[str, Optional[float]]) -> Resolution:
    """Mode `mean` — the mean of the usable values. Positives only while any source has one;
    when none does, the zero reports stand (a mean of zeros is 0)."""
    fields = facet["field_by_source"]
    present = [(s, v) for s, v in candidates.items() if v is not None]
    positive = [(s, v) for s, v in present if v > 0]
    used = positive or present
    if not used:
        return Resolution(metric, None, None, None, "no source has a usable value", candidates, "mean")
    srcs = tuple(s for s, _ in used)
    value = sum(v for _, v in used) / len(used)
    if len(used) == 1:
        return Resolution(metric, value, srcs[0], fields[srcs[0]], f"mean over one source: {srcs[0]}", candidates, "mean", srcs)
    return Resolution(metric, value, None, None, f"mean of {len(used)} sources: {', '.join(srcs)}", candidates, "mean", srcs)


def _row_date(row: Mapping[str, Any]) -> Optional[str]:
    """The DATE# day a row belongs to, or None. A sub-row (`DATE#d#WORKOUT#…`, #3442) is
    not a day row and never answers for the day."""
    sk = row.get("sk")
    if isinstance(sk, str) and sk.startswith("DATE#") and len(sk) > 15:
        return None
    d = row.get("date")
    if isinstance(d, str) and len(d) >= 10:
        return d[:10]
    if isinstance(sk, str) and sk.startswith("DATE#"):
        return sk[5:15]
    return None


def resolve_by_date(metric: str, rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Resolution]:
    """Resolve every date present in `{source_id: [stored DATE# rows]}`.

    When a source carries more than one row for a date, the row with the larger usable
    value is the source's row for that date (the site readers' long-standing per-date max)."""
    per_source: dict[str, dict[str, Mapping[str, Any]]] = {}
    for src, rows in rows_by_source.items():
        by_date: dict[str, Mapping[str, Any]] = {}
        for row in rows or ():
            d = _row_date(row)
            if not d:
                continue
            prev = by_date.get(d)
            if prev is None or (source_value(metric, src, row) or -1.0) > (source_value(metric, src, prev) or -1.0):
                by_date[d] = row
        per_source[src] = by_date
    dates = sorted({d for by_date in per_source.values() for d in by_date})
    out: dict[str, Resolution] = {}
    for d in dates:
        day_rows: dict[str, Optional[Mapping[str, Any]]] = {src: per_source[src].get(d) for src in per_source}
        out[d] = resolve(metric, day_rows)
    return out


# ── resolved pseudo-sources: a metric→source map that must name ONE id ─────────────
#
# Some tables map a metric to the partition a grader reads (experiment.measurable_metrics
# METRIC_SOURCES). For a resolved metric that id is `resolved:<metric>`; the reader's fetch
# seam recognises it, reads every source in the facet's fallback_order and hands back the
# resolved day rows from `resolved_rows`. No such partition exists in DynamoDB.

RESOLVED_PREFIX = "resolved:"


def resolved_source_id(metric: str) -> str:
    """The pseudo-source id a metric→source table uses for a resolved metric."""
    metric_truth(metric)  # KeyError for a metric with no facet — never mint an id for one
    return RESOLVED_PREFIX + metric


def resolved_metric(source_id: Any) -> Optional[str]:
    """The metric a `resolved:<metric>` id names, or None for an ordinary source id."""
    if isinstance(source_id, str) and source_id.startswith(RESOLVED_PREFIX):
        return source_id[len(RESOLVED_PREFIX) :]
    return None


def resolved_rows(metric: str, rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Day rows `{date, sk, <metric>, source}` — the resolved value per date, oldest first —
    so a reader that extracts `<metric>` from rows reads the resolved truth unchanged."""
    out: list[dict[str, Any]] = []
    for d, r in sorted(resolve_by_date(metric, rows_by_source).items()):
        if r.value is not None:
            out.append({"date": d, "sk": "DATE#" + d, metric: r.value, "source": r.source})
    return out


# ── steps: the first metric resolved (#4630) ─────────────────────────────────────


def steps_sources() -> tuple[str, ...]:
    """The source ids a steps reader fetches, in precedence order."""
    return sources_for(STEPS)


def resolve_steps(rows: Mapping[str, Optional[Mapping[str, Any]]]) -> Resolution:
    """One day's steps from `{source_id: row}`."""
    return resolve(STEPS, rows)


def steps_by_date(rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, int]:
    """`{date: resolved step count}` for every date with a POSITIVE resolved count — the
    site readers' long-standing per-day map (a zero-report day is left out, as it always was)."""
    return {d: c for d, r in resolve_by_date(STEPS, rows_by_source).items() if (c := r.count)}


def steps_series(rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[float]:
    """The resolved daily step counts in date order — a zero-report day is IN (#1658: a genuine
    0-step day is a reading), a day with no usable count from any source is out."""
    return [r.value for _, r in sorted(resolve_by_date(STEPS, rows_by_source).items()) if r.value is not None]


def steps_label() -> str:
    """Human label for the precedence, derived from the facet (e.g. for a 'source' caption)."""
    order = sources_for(STEPS)
    return ", else ".join(source_label(s) for s in order)
