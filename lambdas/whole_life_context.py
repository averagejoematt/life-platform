"""
whole_life_context.py — the multi-cycle chronicle archive as a 1-hour cached
content block (#1385, epic #1080).

The chronicle (Elena Voss) and "State of Matthew" reason over the whole installment
archive that is IN SCOPE for the run, not a trimmed 4-week window. The archive is
large and byte-stable within a run, so it rides as an Anthropic ``cache_control``
block with a **1-hour TTL** (reads at ~0.1x, writes at ~2x) instead of inline
uncached user text — the weekly run's several calls (first draft, the ADR-104
regen-once, Margaret's edit pass) all reuse the one cache write.

SCOPE, STATED HONESTLY (#1829). Both callers pass ADR-058's ``with_phase_filter``,
so the query returns the PHASE-VISIBLE installments: the current experiment cycle
plus whatever was deliberately carried forward (ADR-077 ``--keep-chronicle``).
Installments from wiped/archived prior cycles are NOT included — after the cycle-11
reset that was 3 of 18. That default-deny read is the sanctioned reset posture and
is kept; what was WRONG was the label. The block used to open with "FULL MULTI-CYCLE
ARCHIVE (every prior installment, oldest first)", handing the model a false
completeness claim inside a 1h-cached system block — and a digit-free universal
("across every week on record he has never…") is fabricated-by-omission that the
number/date grounding gate cannot catch. The header is now DERIVED from the items
actually present (count + the cycles they carry) and explicitly forbids completeness
claims beyond them; ``archive_scope()`` gives the callers the same facts to log, so
the real scope is visible in CloudWatch instead of a bare count.

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


def archive_scope(installments) -> dict:
    """#1829: what this archive ACTUALLY contains — `{count, cycles, unlabeled}`.

    `cycles` is the sorted list of distinct cycle stamps present; `unlabeled` counts
    installments with no stamp. Callers log this (never a bare count) so a run whose
    archive collapsed to the current cycle is visible in CloudWatch rather than silent.
    """
    items = [i for i in (installments or []) if isinstance(i, dict) and (i.get("content_markdown") or "").strip()]
    cycles = set()
    unlabeled = 0
    for i in items:
        raw = i.get("cycle")
        try:
            if raw in (None, ""):
                raise ValueError
            cycles.add(int(raw))
        except (TypeError, ValueError):
            unlabeled += 1  # missing or unparseable ⇒ counted, never guessed
    return {"count": len(items), "cycles": sorted(cycles), "unlabeled": unlabeled}


def _scope_phrase(scope: dict) -> str:
    """ "cycle 11" / "cycles 10-11" / "cycle 11 + 2 unlabeled" — no invented numbers."""
    cycles = scope.get("cycles") or []
    if not cycles:
        base = "no cycle stamps"
    elif len(cycles) == 1:
        base = f"cycle {cycles[0]}"
    else:
        base = "cycles " + ", ".join(str(c) for c in cycles)
    if scope.get("unlabeled"):
        base += f" + {scope['unlabeled']} unlabeled"
    return base


def archive_header(installments) -> str:
    """The block's opening lines — DERIVED from the items present (#1829).

    Two jobs: say what is here (count + cycles), and forbid the claim the old header
    invited. The old text ("every prior installment") let a phase-filtered 3-installment
    archive license "across every week on record he has never…" — a universal with no
    digits, invisible to the number/date grounding gate. The scope caveat is the only
    defense the gate cannot provide.
    """
    scope = archive_scope(installments)
    plural = "s" if scope["count"] != 1 else ""
    return (
        f"=== THE MEASURED LIFE — INSTALLMENT ARCHIVE IN SCOPE FOR THIS RUN "
        f"({scope['count']} installment{plural}, {_scope_phrase(scope)}; oldest first) ===\n"
        "SCOPE — READ BEFORE MAKING ANY CLAIM ABOUT THE WHOLE HISTORY: these are the "
        "installments currently in scope — the current experiment cycle plus any "
        "deliberately carried forward. Installments from wiped or archived prior cycles "
        "are NOT here, and this is NOT necessarily every installment ever written. "
        "Reason freely across what is below; do NOT make completeness claims beyond it "
        '("every week on record", "he has never once…", "in all the time I have been '
        'writing this"). If you want to speak to the sweep of the archive, say it about '
        "the installments listed here and name their date range.\n"
    )


def format_full_archive(installments, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Render the in-scope installment archive as one plain-text block — oldest first,
    each installment un-truncated (the whole point vs the old 2000-char/4-week window).
    Returns "" when there are no installments.

    The header states the REAL scope (count + cycles present) and forbids completeness
    claims beyond it (#1829) — see `archive_header`.

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
    header = archive_header(items)

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
    """Query the chronicle installments for `pk` — fail-soft to [].

    `d2f` (decimals→float) is applied to the items if given. `phase_filter` is the
    ADR-058 `with_phase_filter` wrapper: pass it (both live callers do) and the read is
    DEFAULT-DENY — wiped prior-cycle installments are excluded, so the result is the
    current cycle plus ADR-077 carry-forwards, NOT the whole multi-cycle history
    (#1829: the block's header now says so instead of claiming completeness). Pass
    `phase_filter=None` for an unfiltered read.

    Returns a list of installment dicts (unsorted; `format_full_archive` orders them).
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
