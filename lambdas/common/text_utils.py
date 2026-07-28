"""
text_utils.py — tiny stdlib-only text helpers shared across the fleet.

Bundled into every function's deploy package (#781 retired the shared layer), so it
is importable from any Lambda at the top level (`from text_utils import ...`). No
boto3 / no heavy imports — safe to import anywhere, including the stdlib-only
reader-truth QA module and the CI-side test harness.

#1224 — reader-facing AI excerpts/summaries were hard-cut mid-word (a fixed-length
`text[:N]` slice), which reads as a rendering bug on the doors aimed at friends and
family. `truncate_at_word` is the ONE word-boundary truncation helper reused at every
generator site so the cut always lands on a word boundary with an ellipsis — and never
appends an ellipsis to text that was not actually shortened.
"""

# Terminal ellipsis appended when text is truncated. A single-character ellipsis (U+2026)
# so downstream length checks / reader-truth regexes treat the field as intentionally cut.
ELLIPSIS = "…"


def truncate_at_word(text, limit, ellipsis=ELLIPSIS):
    """Truncate `text` to at most ~`limit` characters at a word boundary.

    Rules (preserving reader intent, #1224):
      - Falsy/empty `text` → returns "".
      - If the stripped text is already <= `limit` chars, it is returned stripped with
        NO ellipsis — nothing was cut, so nothing signals a cut.
      - Otherwise cut at the last whitespace at or before `limit`, right-strip, and
        append `ellipsis`. If there is no whitespace in that window (a single very long
        token), hard-cut at `limit` and still append `ellipsis` so the field never ends
        on a bare mid-word fragment.

    Idempotent for already-truncated input: a value that already ends in `ellipsis` and
    is within `limit` is returned unchanged.
    """
    if not text:
        return ""
    s = str(text).strip()
    if len(s) <= limit:
        return s
    head = s[:limit]
    # Last whitespace boundary within the window (space, newline, or tab).
    cut = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if cut > 0:
        head = head[:cut]
    return head.rstrip() + ellipsis
