"""
whole_life_context.py — the multi-cycle chronicle archive as a 1-hour cached
content block (#1385, epic #1080).

The chronicle (Elena Voss) and "State of Matthew" now reason over the ENTIRE
multi-cycle installment archive, not a trimmed 4-week window. The archive is
large and byte-stable within a run, so it rides as an Anthropic ``cache_control``
block with a **1-hour TTL** (reads at ~0.1x, writes at ~2x) instead of inline
uncached user text — the weekly run's several calls (first draft, the ADR-104
regen-once, Margaret's edit pass) all reuse the one cache write.

Prompt-caching invariant (see docs + the claude-api skill): caching is a prefix
match, render order is tools → system → messages. So the archive goes in the
``system`` block list, AFTER the (stable) persona prompt and BEFORE the volatile
per-week data packet (which stays in the user message, uncached). 1-hour TTL is
GA on Bedrock via the same wire format as the direct API — no beta header
(``bedrock_client`` docstring; the retired Sonnet-4.5 ``context-1m`` beta is NOT
used anywhere, verified #1385 AC1).

RIGOR (ADR-104/105): widening the context widens the fabrication surface, so the
archive text MUST also feed the grounded-generation allow-list — a real dated
callback ("he tried this in attempt 3") is grounded because Elena was actually
shown attempt 3; a fabricated one is still caught because it appears nowhere in
prompt + data packet + archive. This module only builds the block + the archive
text; the callers thread that same text into their grounding gate.
"""

# 1-hour cache TTL. Anthropic accepts "1h" | "5m"; ephemeral defaults to 5m, so
# the whole point of the archive block is the explicit 1h to survive a run.
ARCHIVE_TTL = "1h"

# Generous char cap so a decade of weekly installments still fits well inside the
# 1M window (≈150k tokens) without an unbounded prompt. When exceeded we keep the
# MOST RECENT installments (callbacks lean recent) and drop the oldest with a note.
DEFAULT_MAX_CHARS = 600_000


def cached_block(text: str, *, ttl: str = ARCHIVE_TTL) -> dict:
    """One Anthropic system content block carrying `text`, cached at `ttl`."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": ttl}}


def with_cached_archive(system, archive_text, *, ttl: str = ARCHIVE_TTL):
    """Return a `system` value that carries the persona prompt AND the multi-cycle
    archive as a **1-hour cached block** (the archive is its own breakpoint, placed
    after the persona prompt so both are a stable cacheable prefix).

    `system` may be a plain string (the persona prompt) or an already-built list of
    content blocks. Returns:
      - `system` unchanged when `archive_text` is falsy (no archive → no rewrite);
      - otherwise a list: [persona block(s) (cached), archive block (cached 1h)].

    A string persona prompt is wrapped as its own cached block so the archive block
    has a byte-stable prefix in front of it (a cache hit needs an unchanged prefix).
    """
    if not archive_text:
        return system
    if isinstance(system, list):
        base_blocks = list(system)
    elif system:
        base_blocks = [cached_block(system, ttl=ttl)]
    else:
        base_blocks = []
    return base_blocks + [cached_block(archive_text, ttl=ttl)]


def _sort_key(inst: dict):
    """Oldest-first ordering: (cycle, week_number, date). Missing/None sorts low so
    genesis/pre-genesis lead-ins lead."""
    cycle = inst.get("cycle")
    week = inst.get("week_number")
    date = inst.get("date") or inst.get("sk") or ""

    def _num(v):
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, 0.0)  # unknown sorts after known

    return (_num(cycle), _num(week), str(date))


def format_full_archive(installments, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Render the full multi-cycle installment archive as one plain-text block —
    oldest first, each installment un-truncated (the whole point vs the old
    2000-char/4-week window). Returns "" when there are no installments.

    If the total would exceed `max_chars`, keep the MOST RECENT installments and
    prepend a note that older ones were elided (callbacks lean recent; the cap only
    bites after many cycles).
    """
    items = [i for i in (installments or []) if isinstance(i, dict) and (i.get("content_markdown") or "").strip()]
    if not items:
        return ""
    items.sort(key=_sort_key)

    def _render(inst: dict) -> str:
        cyc = inst.get("cycle")
        wk = inst.get("week_number", "?")
        title = inst.get("title", "Untitled")
        date = inst.get("date") or (inst.get("sk", "") or "").replace("DATE#", "")
        cyc_txt = f"Cycle {cyc} · " if cyc not in (None, "") else ""
        md = (inst.get("content_markdown") or "").strip()
        return f'--- {cyc_txt}Week {wk}: "{title}" ({date}) ---\n{md}'

    rendered = [_render(i) for i in items]
    header = "=== THE MEASURED LIFE — FULL MULTI-CYCLE ARCHIVE (every prior installment, oldest first) ===\n"

    body = "\n\n".join(rendered)
    if len(header) + len(body) <= max_chars:
        return header + body

    # Over budget: keep the most recent installments that fit, note the elision.
    kept: list = []
    total = 0
    for r in reversed(rendered):  # newest first while filling
        if total + len(r) + 2 > max_chars:
            break
        kept.append(r)
        total += len(r) + 2
    dropped = len(rendered) - len(kept)
    kept.reverse()  # back to oldest-first
    note = f"[{dropped} older installment(s) elided to fit the context budget; the most recent {len(kept)} follow.]\n"
    return header + note + "\n\n".join(kept)


def fetch_full_installment_archive(table, pk: str, *, d2f=None, phase_filter=None, limit: int = 500) -> list:
    """Query EVERY chronicle installment for `pk` (all cycles) — fail-soft to [].

    `d2f` (decimals→float) is applied to the items if given; `phase_filter` is the
    ADR-058 `with_phase_filter` wrapper (default-deny pilot data) if the caller
    wants it. Returns a list of installment dicts (unsorted; `format_full_archive`
    orders them).
    """
    try:
        params = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {":pk": pk, ":prefix": "DATE#"},
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if phase_filter is not None:
            params = phase_filter(params)
        resp = table.query(**params)
    except Exception:  # noqa: BLE001 — the archive is context, never load-bearing
        return []
    items = resp.get("Items", []) or []
    return [d2f(i) for i in items] if d2f else list(items)
