"""coach_correction_resolver.py — the shared "#N → archived generation" resolver for
the two correction feedback channels (#1690, foundation story S3 of epic #1687
"The Coach Correction Loop").

Matthew reads the weekly ranked review pack (#1688) and corrects items by NUMBER.
Two channels land the SAME rows in the corrections ledger (#1689):
  - an MCP tool (`log_coach_correction`)   — mcp/tools_coach_corrections.py
  - an email-reply parser (`#N <text>` lines) — lambdas/emails/insight_email_parser_lambda.py

BOTH must map a pack item NUMBER back to the SAME archived generation the reader saw
numbered in the email — so this is the ONE resolver both import. The number a reader
sees == the number that resolves; there is deliberately NO second numbering scheme
(the #1690 MUST-REUSE constraint).

Reuse (imported, never re-implemented):
  - `review_pack_ranker.numbered_entries` — THE numbering (same week → same numbers,
    independent of any prior in-place ordering; it re-derives the canonical order).
  - `ai_review_pack_lambda.gather_week` / `week_dates` — THE canonical week assembly, so
    the resolver's week matches the pack that was sent. Imported LAZILY (inside the
    resolve call) so this root-bundled module (#781) stays light and import-order-robust
    in the MCP bundle, where `ai_review_pack_lambda` lives under the `emails` subpackage.
  - `qa_archive` entry schema — the resolved entry yields the `item_ref` fields.
  - `coach_corrections.write_correction` — the single ledger writer (callers write; this
    module only RESOLVES, it never touches DynamoDB).

Reported-not-dropped (AC3): `resolve_number` returns an explicit error dict for an
unknown/out-of-range number (never raises for a bad number), and `parse_correction_reply`
collects lines that lead with '#' but don't parse as `#<digits> <text>` — a malformed
correction is surfaced, never silently swallowed.

v1.0.0 — 2026-07-22 (#1690)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import review_pack_ranker

logger = logging.getLogger()

# A correction line in an email reply, e.g.
#   "#3 the 315 lbs baseline is stale — I'm 321.4 as of genesis"
# Leading whitespace tolerated; a run of digits; then at least one non-space char of
# correction text. `#3` with no text, `#abc fix`, do NOT match here (→ malformed).
_CORRECTION_LINE_RE = re.compile(r"^\s*#\s*(\d+)\s+(.*\S)\s*$")
# A line that LEADS like a correction ('#' then a word/digit) but didn't parse above —
# collected as malformed so a typo'd correction is reported, never dropped.
_HASH_LEAD_RE = re.compile(r"^\s*#\s*\w")


def _load_week_assembly():
    """Lazily import the pack's canonical week-assembly helpers. Returns
    ``(gather_week, week_dates, surface_order)``.

    Deferred so this root bundle stays light and robust to import order. The flat name
    resolves in tests (conftest puts lambdas/emails on sys.path) and in the email-stack
    runtime; the packaged name resolves in the MCP bundle, where ai_review_pack_lambda
    lives under the `emails` subpackage.
    """
    try:
        from ai_review_pack_lambda import SURFACE_ORDER, gather_week, week_dates
    except Exception:  # pragma: no cover — bundle-shape dependent
        from emails.ai_review_pack_lambda import SURFACE_ORDER, gather_week, week_dates
    return gather_week, week_dates, SURFACE_ORDER


def build_by_surface(*, end_date=None):
    """Rebuild the pack week's ``{surface: [entry, ...]}`` from the S3 archive — exactly
    the assembly `ai_review_pack_lambda.gather_week` performs over the same trailing
    window (`week_dates`). Reads S3 (`qa_archive.list_day`/`read_entry`); raises on AWS
    errors (loud, like the pack — a broken archive must be visible, not a silent empty
    week). `end_date` overrides the window end (defaults to today UTC)."""
    gather_week, week_dates, _ = _load_week_assembly()
    dates = week_dates(end=end_date) if end_date is not None else week_dates()
    by_surface, _screens, _errs = gather_week(dates)
    return by_surface


def numbered_for_week(*, end_date=None, by_surface=None):
    """``[(n, entry), ...]`` — the STABLE numbering for the pack week (via
    `review_pack_ranker.numbered_entries`, with the pack's SURFACE_ORDER). Pass a
    prebuilt `by_surface` to resolve several `#N` against ONE archive read (the email
    path resolves a whole reply from a single listing)."""
    _, _, surface_order = _load_week_assembly()
    if by_surface is None:
        by_surface = build_by_surface(end_date=end_date)
    return review_pack_ranker.numbered_entries(by_surface, surface_order=surface_order)


def build_item_ref(n: int, entry: dict) -> dict:
    """The durable `item_ref` for one corrected generation — what `write_correction`
    stores so a correction points back at the exact archived object. Fields per
    #1687/#1688: the stable pack number, the surface, the coach (= the archive
    `variant`), the generation date, and the archive S3 `_key` gather_week attaches."""
    return {
        "pack_number": n,
        "surface": entry.get("surface"),
        "coach": entry.get("variant"),
        "date": entry.get("date"),
        "archive_key": entry.get("_key"),
    }


def resolve_number(n, *, end_date=None, numbered=None, by_surface=None) -> dict:
    """Resolve a pack item NUMBER to its archived generation + `item_ref`.

    Success → ``{"ok": True, "n": <int>, "entry": <entry>, "item_ref": {...}, "total": T}``
    Unknown / out-of-range / non-numeric → ``{"ok": False, "n": <n>, "error": "...", "total": T}``

    NEVER raises for a bad number (AC3 — a malformed/unknown number is REPORTED, not
    dropped). AWS/archive read errors DO propagate — a broken read must not masquerade as
    "unknown #N". Pass `numbered` (or `by_surface`) to resolve many numbers against one
    archive read.
    """
    if numbered is None:
        numbered = numbered_for_week(end_date=end_date, by_surface=by_surface)
    total = len(numbered)
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        return {"ok": False, "n": n, "error": f"'{n}' is not a valid item number", "total": total}
    for num, entry in numbered:
        if num == n_int:
            return {"ok": True, "n": n_int, "entry": entry, "item_ref": build_item_ref(n_int, entry), "total": total}
    if total == 0:
        msg = f"no item #{n_int}: this week's review pack has no generations to correct"
    else:
        plural = "s" if total != 1 else ""
        msg = f"no item #{n_int} in this week's review pack (it has {total} item{plural}, #1-#{total})"
    return {"ok": False, "n": n_int, "error": msg, "total": total}


def parse_correction_reply(reply_text: Optional[str]) -> dict:
    """Pure: extract ``#N <correction text>`` lines from an email reply body. One
    correction per line; several lines allowed. Returns::

        {"corrections": [(n:int, text:str), ...], "malformed": [raw_line, ...]}

    A line that LEADS with '#' but doesn't match the ``#<digits> <text>`` shape
    (e.g. ``#3`` with no text, ``#abc fix``) is collected as `malformed` — never
    silently dropped (AC3). Non-'#' lines (a greeting, or quoted context already
    stripped upstream) are ignored.
    """
    corrections = []
    malformed = []
    for raw in (reply_text or "").splitlines():
        if not raw.strip():
            continue
        m = _CORRECTION_LINE_RE.match(raw)
        if m:
            corrections.append((int(m.group(1)), m.group(2).strip()))
        elif _HASH_LEAD_RE.match(raw):
            malformed.append(raw.strip())
    return {"corrections": corrections, "malformed": malformed}
