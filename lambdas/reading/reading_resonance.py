"""reading_resonance.py — the WRITER for `journal_resonance` (#2349, epic #1080).

`reading_recommender.score_one` has always read `state["journal_resonance"]` and
multiplied it by `w_res` (0.10–0.15 depending on curriculum phase). **Nothing ever
wrote that key.** Measured on main 2026-08-10: three live references to the name, all
reads (the objective docstring, the `score_one` lookup, one test injection). So the
production path computed `w_res * 0.0` on every call and the term was decoration.

This module is the missing half. Deliberately kept OUT of `reading_recommender` so the
recommender stays pure/no-I/O and unit-testable, and out of `mcp/tools_reading` so the
gather logic is testable without the MCP surface — the same split `semantic_recall`
(read) / `recall_indexer` (write) already uses.

WHAT IT COMPARES. Both sides are already-derived THEME vocabularies, never prose:
  - the journal side is `enriched_themes` on the `SOURCE#notion` journal rows (written
    by the existing journal enrichment pass), fetched with a DynamoDB
    **ProjectionExpression** so `raw_text`/`body_text` are never even transferred out
    of the table (AC2 — the strongest available form of "no journal text");
  - the book side is `BOOK#.themes` from `reading_enrich`.
Cosine over Titan-v2 embeddings via the `bedrock_client` chokepoint (ADR-062), with the
codec/cosine reused from `ai.semantic_recall` rather than reimplemented.

NOTHING IS PERSISTED BY THIS MODULE (AC2). It has no write path at all: no journal
text, no snippet, no journal embedding, no cached vector — the score is computed per
call, handed to the recommender in memory, and surfaces only as the `resonance` number
already returned by `score_one` plus the provenance block the tool renders. There is
therefore no partition, reader-facing or otherwise, for journal-derived content to leak
from, and #2347's corpus-scope decision is not pre-empted.

CALIBRATION (ADR-105 — the threshold is measured, not invented). Titan-v2 cosine over
SHORT theme lists occupies a narrow low band, so the raw number is not a 0–1 "fit" and
must not be used as one. Measured 2026-08-10 against the live corpus — every themed
journal entry x every book in the live shelf, **n = 270 pairs**:

    min -0.114 | p05 0.039 | p10 0.066 | p50 0.160 | p90 0.278 | p95 0.308 | max 0.434
    mean 0.164 | sd 0.084

`calibrate()` is the affine map of that operating band onto 0–1, exactly the shape
`reading_recommender._composite` already uses to put difficulty 1–5 on a 0–1 scale.
The floor is p10 and the ceiling p95 of that distribution: below the floor there is NO
resonance (0.0 — honest absence, ADR-104), above the ceiling it saturates at 1.0. The
RAW cosine is reported alongside every calibrated score, so the map is inspectable and
re-derivable rather than a silent nudge (AC3).

REVISIT TRIGGER (so the band cannot rot silently): re-measure and re-fit when the themed
journal corpus grows past ~150 entries or the shelf past ~30 books — a band fitted on
n=270 pairs from 45 entries x 6 books is honest about what it is, and stops being so
once the corpus it describes has changed shape.

FAIL-SOFT, ALWAYS (AC1). Budget pause (band 2, reusing the `semantic_recall` feature —
same mechanism, same audience), no journal themes, no book themes, an oversized queue,
a missing module or any Bedrock error all return an EMPTY score map. An empty map means
`state["journal_resonance"]` is absent/empty, which is bit-for-bit today's behavior:
`score_one` falls back to 0.0 and the recommendation reads exactly as it did before this
module existed. Nothing here can raise into the recommendation path.

COST / CALL COUNT. There is no pre-existing Bedrock call on the
`get_reading_recommendation` path to fold into, so this adds `1 + len(candidates)` Titan
embeds per invocation (1 journal digest + 1 per book). Measured live: 6 embeds, ~200
input tokens total, ~1.3 s cold wall-clock, ~$0.000004 at Titan-v2's $0.02/1M. Caching
the per-book vector on `BOOK#` META (books are enriched once) is the obvious next
optimization and is DELIBERATELY not built: it buys a fraction of a cent and one second
on a manually-invoked owner tool, at the cost of a write path plus an idempotency key
(ADR-103 proportionality). `MAX_CANDIDATES` is the guard that keeps the unbounded case
from ever becoming the expensive one.
"""

from __future__ import annotations

from datetime import date as _date, timedelta

# ── calibration band (see the module docstring for the measurement + its n) ────
COSINE_FLOOR = 0.07  # p10 of the measured pair distribution — below this: no resonance
COSINE_CEILING = 0.31  # p95 — at/above this the term saturates at 1.0
CALIBRATION_N = 270  # pairs the band was fitted on (ADR-105: state n with the threshold)

# ── gather bounds ─────────────────────────────────────────────────────────────
# "what your journal's been circling" is RECENT, but the themed corpus is sparse
# (45 themed entries across 2.5 years, 1 in the trailing 90 days as of 2026-08-10),
# so a pure day-window manufactures emptiness. The bound is therefore both: entries
# within LOOKBACK_DAYS, capped at the most recent MAX_ENTRIES of those.
LOOKBACK_DAYS = 180
MAX_ENTRIES = 12
# Above this candidate count the per-book embed cost stops being negligible. The whole
# map is then withheld rather than scoring a prefix — a partial map would silently
# zero the un-embedded tail, which is the exact "dead term" failure this issue fixes.
MAX_CANDIDATES = 40

JOURNAL_SOURCE = "notion"
_JOURNAL_SK_MARKER = "#journal#"

# Status strings on the returned envelope. Callers log/surface these; only OK means a
# score map was produced. They are distinct on purpose — "the budget paused it" and
# "he has written nothing thematic lately" are different facts about the same 0.0.
OK = "ok"
SKIPPED_BUDGET = "skipped:budget"
SKIPPED_NO_CANDIDATES = "skipped:no-candidates"
SKIPPED_TOO_MANY_CANDIDATES = "skipped:too-many-candidates"
SKIPPED_NO_JOURNAL_THEMES = "skipped:no-journal-themes"
SKIPPED_NO_BOOK_THEMES = "skipped:no-book-themes"
UNAVAILABLE = "unavailable"

BUDGET_FEATURE = "semantic_recall"


def _empty(status: str, **extra) -> dict:
    """The honest-absence envelope: no scores, and a status naming WHY."""
    out = {"scores": {}, "raw": {}, "status": status, "n_entries": 0, "window": None, "calibration": None}
    out.update(extra)
    return out


# ── pure helpers ──────────────────────────────────────────────────────────────
def calibrate(cosine: float) -> float:
    """Map a raw Titan cosine onto the recommender's 0–1 component scale.

    Affine over the measured operating band (COSINE_FLOOR..COSINE_CEILING), clamped.
    At/below the floor the result is exactly 0.0 — a book that does not resonate
    contributes nothing, rather than a small universal nudge.
    """
    try:
        c = float(cosine)
    except (TypeError, ValueError):
        return 0.0
    span = COSINE_CEILING - COSINE_FLOOR
    if span <= 0:  # pragma: no cover — guarded so a bad edit can't divide by zero
        return 0.0
    return max(0.0, min(1.0, (c - COSINE_FLOOR) / span))


def theme_digest(entries) -> str:
    """The embeddable journal digest: the entries' themes, de-duplicated, newest first.

    Themes only — this function is never handed journal prose, and the caller's
    ProjectionExpression is what guarantees that upstream. Empty in, empty out.
    """
    seen: set = set()
    ordered: list = []
    for e in entries or []:
        for t in (e or {}).get("themes") or []:
            token = str(t).strip().lower()
            if token and token not in seen:
                seen.add(token)
                ordered.append(token)
    return "; ".join(ordered)


def book_theme_text(book) -> str:
    """The embeddable text for one candidate: its `BOOK#.themes`, normalized.

    Themes ONLY (spec §5). `domainTags` are already carried by `breadth_gain` and
    `momentum_fit`; folding them in here would double-count genre as resonance.
    """
    themes = [str(t).strip().lower() for t in ((book or {}).get("themes") or []) if str(t).strip()]
    return "; ".join(themes)


# ── DynamoDB gather (injected table — no module-level client) ─────────────────
def journal_theme_entries(table, *, today: str = "", lookback_days: int = LOOKBACK_DAYS, max_entries: int = MAX_ENTRIES) -> list:
    """The recent journal entries' THEMES, newest-first — `[{date, themes}]`.

    Reads `USER#matthew#SOURCE#notion` with a ProjectionExpression of exactly
    `sk`, `date`, `enriched_themes`, so no journal prose is transferred (AC2). No
    phase filter: the journal archive is cross-phase by design (ADR-058), so a reset
    must not blind the term.

    An entry with no `enriched_themes` (not yet enriched, or nothing thematic found)
    is skipped rather than represented by an empty string.
    """
    from boto3.dynamodb.conditions import Key

    end = today or _date.today().isoformat()
    try:
        start = (_date.fromisoformat(end) - timedelta(days=int(lookback_days))).isoformat()
    except ValueError:
        return []

    pk = f"USER#matthew#SOURCE#{JOURNAL_SOURCE}"
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{end}#~"),
        "ProjectionExpression": "sk, #d, enriched_themes",
        "ExpressionAttributeNames": {"#d": "date"},
        "ScanIndexForward": True,
    }
    items: list = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []) or [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    entries: list = []
    for it in items:
        if _JOURNAL_SK_MARKER not in (it.get("sk") or ""):
            continue
        themes = [str(t).strip().lower() for t in (it.get("enriched_themes") or []) if str(t).strip()]
        if not themes:
            continue
        entries.append({"date": it.get("date") or "", "themes": themes})
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[: max(0, int(max_entries))]


# ── the writer ────────────────────────────────────────────────────────────────
def compute(table, candidates, *, today: str = "", embed=None, budget_allow=None, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """Compute `journal_resonance` for `candidates` → the envelope the tool consumes.

    Returns ``{"scores": {bookId: 0..1}, "raw": {bookId: cosine}, "status": ...,
    "n_entries": int, "window": [oldest, newest] | None, "calibration": {...}}``.
    `scores` is what goes on the recommender state; everything else is provenance so a
    resonance-driven ranking can be explained (AC3).

    `embed` / `budget_allow` are injectable for tests; production resolves them lazily
    so `reading/` carries no import-time dependency on `ai/`.

    NEVER RAISES (AC1). Every failure mode returns an empty score map, which the
    recommender treats identically to today's missing key.
    """
    try:
        if not candidates:
            return _empty(SKIPPED_NO_CANDIDATES)
        if len(candidates) > MAX_CANDIDATES:
            return _empty(SKIPPED_TOO_MANY_CANDIDATES)

        if budget_allow is None:
            try:
                from ai.budget_guard import allow as budget_allow
            except ImportError:
                budget_allow = None
        if budget_allow is not None and not budget_allow(BUDGET_FEATURE):
            return _empty(SKIPPED_BUDGET)

        texts = {}
        for book in candidates:
            bid = (book or {}).get("bookId")
            text = book_theme_text(book)
            if bid and text:
                texts[bid] = text
        if not texts:
            return _empty(SKIPPED_NO_BOOK_THEMES)

        entries = journal_theme_entries(table, today=today, lookback_days=lookback_days)
        digest = theme_digest(entries)
        if not digest:
            return _empty(SKIPPED_NO_JOURNAL_THEMES)

        if embed is None:
            from ai.bedrock_client import embed_text as embed
        from ai.semantic_recall import cosine

        journal_vector = embed(digest)
        if not journal_vector:
            return _empty(UNAVAILABLE)

        scores: dict = {}
        raw: dict = {}
        for bid, text in texts.items():
            sim = cosine(journal_vector, embed(text))
            raw[bid] = round(float(sim), 4)
            scores[bid] = round(calibrate(sim), 4)

        dates = [e["date"] for e in entries if e.get("date")]
        return {
            "scores": scores,
            "raw": raw,
            "status": OK,
            "n_entries": len(entries),
            "window": [min(dates), max(dates)] if dates else None,
            "calibration": {"floor": COSINE_FLOOR, "ceiling": COSINE_CEILING, "fitted_on_n_pairs": CALIBRATION_N},
        }
    except Exception as e:  # noqa: BLE001 — resonance is NEVER load-bearing (AC1)
        return _empty(f"{UNAVAILABLE}:{type(e).__name__}")
