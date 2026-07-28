"""lambdas/theme_river.py — deterministic "theme river" over enriched journal themes (#1381).

The journal enrichment pass (journal_enrichment_lambda, ADR-104) codes up to four
`enriched_themes` per entry — life themes like "work pressure" or "personal
growth". Until now nothing rendered their EVOLUTION across the attempt.

This module is the ONE deterministic aggregation of those theme labels into a
weekly "river": a pure, no-AI, byte-stable rollup that /story/theme-river renders
as monochrome small-multiples (design-system honest — neutral ink carries the
shape, the ember accent is reserved for the single RISING theme; a fading theme
is just neutral ink, never red).

Provenance (ADR-104/105): these are a language model's reading of prose, never
sensor data. Every artifact carries the enrichment model + schema version that
coded the entries, and n on every count. Below the warming-up floor the page
shows the "still forming" grammar and never fabricates density.

Read-only over the notion journal partition (`USER#matthew#SOURCE#notion`,
`SK DATE#…#journal#…`); no writes, re-derivable at any time. The aggregation
functions here take plain dicts and are import-light (stdlib only) so the build
script and the unit test can call them without any AWS or LLM dependency.
"""

from __future__ import annotations

from datetime import date, timedelta

# The enriched field this river is built from.
THEME_FIELD = "enriched_themes"

# Distinct theme bands surfaced as their own small-multiple; everything past the
# top-N (by total count) folds into a single honest "other" band so the grid
# stays readable without dropping any signal.
MAX_BANDS = 8
OTHER_LABEL = "other"

# Below this many ENRICHED days the river is still "warming up" — the page shows
# what exists but in the forming grammar and never claims a shape (AC4).
WARMING_UP_MIN_DAYS = 14

# Provenance defaults for the honest empty/offline baseline. Keep in sync with
# journal_enrichment_lambda.MODEL / SCHEMA_VERSION — the --live build overrides
# both from the flourishing partition's stored provenance (data-driven).
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_SCHEMA_VERSION = 2

ARTIFACT_SCHEMA = "theme_river/1"


def _iso(d: date) -> str:
    return d.isoformat()


def _parse(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def normalize_theme(raw) -> str | None:
    """A theme label → its canonical counting key (lowercased, whitespace-collapsed).

    The LLM emits free text; "Personal Growth" and "personal  growth" are the same
    theme. Returns None for anything that isn't a non-empty string so junk never
    becomes a band.
    """
    if not isinstance(raw, str):
        return None
    key = " ".join(raw.split()).strip().lower()
    return key or None


def entry_date(entry: dict) -> str | None:
    """The YYYY-MM-DD an entry belongs to — prefers the explicit `date`, else the SK."""
    d = entry.get("date")
    if isinstance(d, str) and d.strip():
        return d.strip()[:10]
    sk = entry.get("sk")
    if isinstance(sk, str) and sk.startswith("DATE#"):
        return sk[len("DATE#") : len("DATE#") + 10]
    return None


def _week_index(d: date, start: date) -> int:
    return (d - start).days // 7


def build_river(
    entries,
    start_date: str,
    end_date: str,
    model: str | None = None,
    schema_version=None,
) -> dict:
    """Aggregate enriched-theme counts into the weekly river artifact (PURE).

    Deterministic and byte-stable for a fixed input: no wall-clock, no set
    iteration leaking into output ordering, all lists sorted by explicit keys.
    The build script adds the mutable `generated_at`/window-end wrapper OUTSIDE
    this function so the aggregation itself stays a fixed-point of its inputs.

    entries: iterable of dicts with a date (`date` or `sk`) and `enriched_themes`
             (a list of strings). Entries outside [start_date, end_date] or with
             no usable themes are ignored.
    """
    start = _parse(start_date)
    end = _parse(end_date)
    n_weeks = max(0, (end - start).days // 7) + 1

    # ── First pass: per-day theme occurrences, within the window ──────────────
    # counts_by_week[week][theme] = occurrences; days_by_week[week] = {dates}
    counts_by_week: list[dict] = [dict() for _ in range(n_weeks)]
    days_by_week: list[set] = [set() for _ in range(n_weeks)]
    entries_by_week: list[int] = [0] * n_weeks
    totals: dict = {}
    enriched_days: set = set()
    n_entries = 0

    for e in entries or []:
        ds = entry_date(e)
        if not ds:
            continue
        try:
            d = _parse(ds)
        except ValueError:
            continue
        if d < start or d > end:
            continue
        themes: list[str] = []
        for raw_theme in e.get(THEME_FIELD) or []:
            norm = normalize_theme(raw_theme)
            if norm is not None:
                themes.append(norm)
        if not themes:
            continue
        wk = _week_index(d, start)
        if wk < 0 or wk >= n_weeks:
            continue
        enriched_days.add(ds)
        days_by_week[wk].add(ds)
        entries_by_week[wk] += 1
        n_entries += 1
        # De-dupe within a single entry so one entry can't inflate a theme's
        # count by repeating it; each theme counts once per entry.
        for t in sorted(set(themes)):
            counts_by_week[wk][t] = counts_by_week[wk].get(t, 0) + 1
            totals[t] = totals.get(t, 0) + 1

    n_days = len(enriched_days)

    # ── Choose the bands: top MAX_BANDS by total, tie-break by name; fold rest ─
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[:MAX_BANDS]
    remainder = ranked[MAX_BANDS:]
    band_names = [name for name, _ in top]
    fold = {name for name, _ in remainder}
    has_other = bool(fold)

    def _fold(theme: str) -> str:
        return theme if theme in band_names else OTHER_LABEL

    # ── Rebuild weekly counts against the (possibly folded) band set ──────────
    weeks_out = []
    band_weekly: dict = {name: [0] * n_weeks for name in band_names}
    if has_other:
        band_weekly[OTHER_LABEL] = [0] * n_weeks
    for wk in range(n_weeks):
        wcounts: dict = {}
        for theme, c in counts_by_week[wk].items():
            band = _fold(theme)
            wcounts[band] = wcounts.get(band, 0) + c
            band_weekly[band][wk] += c
        w_start = start + timedelta(days=wk * 7)
        w_end = min(end, w_start + timedelta(days=6))
        weeks_out.append(
            {
                "week": wk,
                "start": _iso(w_start),
                "end": _iso(w_end),
                "n_days": len(days_by_week[wk]),
                "n_entries": entries_by_week[wk],
                "counts": {k: wcounts[k] for k in sorted(wcounts)},
            }
        )

    # ── Ordered bands (with 'other' pinned last) ──────────────────────────────
    ordered_band_names = list(band_names)
    if has_other:
        ordered_band_names.append(OTHER_LABEL)

    # ── State + the single 'earned glow' rising theme ─────────────────────────
    if n_days == 0:
        state = "empty"
    elif n_days < WARMING_UP_MIN_DAYS:
        state = "warming_up"
    else:
        state = "flowing"

    rising = None
    if state == "flowing" and n_weeks >= 2:
        # Greatest positive last-week-vs-prior-week delta among real bands
        # (never 'other'); tie-break higher total, then name. Deterministic.
        candidates = []
        for name in band_names:
            series = band_weekly[name]
            delta = series[-1] - series[-2]
            if delta > 0:
                candidates.append((-delta, -totals.get(name, 0), name))
        if candidates:
            candidates.sort()
            rising = candidates[0][2]

    bands = [
        {"theme": name, "total": (sum(band_weekly[name]) if name == OTHER_LABEL else totals.get(name, 0)), "rising": name == rising}
        for name in ordered_band_names
    ]

    return {
        "schema": ARTIFACT_SCHEMA,
        "state": state,
        "window": {"start": _iso(start), "end": _iso(end), "weeks": n_weeks},
        "warming_up_min_days": WARMING_UP_MIN_DAYS,
        "n_days": n_days,
        "n_entries": n_entries,
        "n_themes": len(totals),
        "bands": bands,
        "weeks": weeks_out,
        "rising_theme": rising,
        "provenance": {
            "source": "journal_enrichment",
            "field": THEME_FIELD,
            "model": model or DEFAULT_MODEL,
            "schema_version": int(schema_version) if schema_version is not None else DEFAULT_SCHEMA_VERSION,
        },
    }


# ── DDB read (the only impure part; kept out of build_river) ──────────────────
def list_enriched_entries(table, start_date: str, end_date: str):
    """Query the notion journal partition for enriched entries in the attempt window.

    Returns a list of {"date", "enriched_themes"} dicts (Decimals already absent
    — themes are strings). The SK upper bound uses '#~' so every per-day suffix
    (…#journal#1, #2, …) sorts inside the range.
    """
    from boto3.dynamodb.conditions import Key

    pk = "USER#matthew#SOURCE#notion"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}#~"),
        "ScanIndexForward": True,
    }
    out = []
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            if "#journal#" not in str(item.get("sk", "")):
                continue
            themes = item.get(THEME_FIELD)
            if not themes:
                continue
            out.append({"date": entry_date(item), THEME_FIELD: [str(t) for t in themes]})
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return out


def latest_provenance(table):
    """(model, schema_version) from the most recent flourishing row, else defaults.

    The flourishing partition (lambdas/flourishing.py) stamps every day it writes
    with the enrichment model + schema that coded it — the honest, data-driven
    provenance for the river when live records exist.
    """
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#flourishing"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            row = items[0]
            model = row.get("enrichment_model") or DEFAULT_MODEL
            sv = row.get("enrichment_schema_version")
            return str(model), int(sv) if sv is not None else DEFAULT_SCHEMA_VERSION
    except Exception:
        pass
    return DEFAULT_MODEL, DEFAULT_SCHEMA_VERSION
