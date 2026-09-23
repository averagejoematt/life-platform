"""v4_glossary.py — the newcomer's glossary, applied at build time (#4035, re-filed
from #3618, Part 4 reader ROW1 of `docs/reviews/FORENSIC_RCA_2026-09-05.md`).

WHAT WAS MISSING. `find . -iname '*glossar*'` returned nothing; `grep -c '<abbr'` over
site/index.html, site/data/index.html and site/cockpit/index.html returned 0, 0, 0 while
"HRV" appeared across dozens of pages and "Brier" across dozens more — every term the
platform's own vocabulary coins or borrows, never once explained inline. This module is
the fix, kept a **build-time text transform** (per the RCA's own priced-FREE proposal):
no runtime cost, no new JS payload, no series, no tokens.

HOW IT WORKS. `site/config/glossary.json` is the committed term registry (exact-case,
word-boundary matched). `apply_glossary(html, page_path)` walks a page's HTML, skipping
every region that is not reader-visible PROSE — `<head>`, `<script>`, `<style>`, `<svg>`,
the shared `<nav class="doors">`, `<footer class="site-foot">` and `<aside
class="loop-forward">` chrome blocks (script blocks matter most: several `/data/*` pages
embed a JSON tile registry inside a `<script>` tag that JS renders into visible tile
blurbs at RUNTIME — that text is invisible to a build-time HTML pass by construction, and
injecting HTML markup into JSON would corrupt it outright; client-side first-appearance
glossing of that registry is a named, deliberate residual, not silently dropped) — and
wraps each registered term's FIRST appearance per page in
`<abbr class="gloss" title="...">`. Re-running is idempotent: every existing `.gloss`
wrap is stripped back to plain text before the fresh pass, so regenerating a canonical
page is a byte-identical no-op (the same contract `v4_apply_chrome.py` already holds for
the nav/footer/loop-forward).

TWO EXEMPT PAGES, DECLARED. `/method/registry/` and `/method/mirror/` are the platform's
own statistics-registry pages: every acronym there (RMSSD, BSTS, CUSUM, EWMA, OLS, SE,
AR, SD, MAPE, ACWR, SCED, FDR-as-used-there, ...) sits inside a `<p class="mr-formula">`
or a `<dl class="mr-fields">` that ALREADY defines it inline, formula and all — a second,
generic one-line gloss would duplicate the page's own more-precise definition, not help
it. `GLOSS_EXEMPT_PAGES` names this the same way `v4_chrome.dark_feeds()` names a
declared-dark feed: a dated, owned exemption, not a silent gap. Every other page is in
scope, chrome-bearing pages included (the same population `v4_apply_chrome.py` walks).

THE TWO-SIDED GATE lives in `tests/test_glossary_4035.py`, over the built (committed)
HTML — not here. This module owns the transform + the registry; the test owns the
assertion that the transform's output is what actually shipped.
"""

from __future__ import annotations

import html as _html
import json
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
GLOSSARY_PATH = os.path.join(REPO_ROOT, "site", "config", "glossary.json")

# Declared, dated exemption (see module docstring): the two statistics-registry pages
# already define every term they use inline, formula and all.
GLOSS_EXEMPT_PAGES = frozenset({"/method/registry/", "/method/mirror/"})

# Gate-(b) allowlist — tokens the ALL-CAPS acronym heuristic below would otherwise catch
# that are NOT platform jargon a newcomer needs explained. Three grounds, each real:
#   (1) roman numerals — chapter/part numbers ("Chapter II"), not acronyms at all.
#   (2) plain English words rendered ALL-CAPS for prose emphasis (a `<strong>` or a
#       sentence-initial capital caught by the same \b[A-Z]{2,6}\b heuristic that finds
#       real acronyms) — verified against the live non-legacy sweep, 2026-09-23.
#   (3) generic, already-widely-known tech/legal/infra abbreviations used once or twice
#       on the footer-tier "how it's built" pages (/method/*, /story/build/*, /gear/,
#       /privacy/, journal essays) aimed at a technically-curious reader who already
#       expects this vocabulary there — or, for CI/EMA, genuinely AMBIGUOUS across the
#       site (CI reads "continuous integration" in the build-log essay and "confidence
#       interval" in the stats registry; one global definition would misinform one of
#       the two, so it stays unglossed rather than fabricate a single answer).
GLOSS_ALLOWLIST = frozenset(
    {
        # the platform's own primary subject, already as widely known as a term gets —
        # registering it would force-gloss the FIRST word of most pages, hurting rather
        # than helping a newcomer's legibility (30+ pages, verified live 2026-09-23).
        "AI",
        # roman numerals (chapter/part numbers)
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
        "VIII",
        "IX",
        "X",
        # emphasis-caps / sentence-caps plain English, verified live 2026-09-23
        "NOT",
        "ONLY",
        "AND",
        "LAST",
        "FIRST",
        "ONE",
        "DRAWN",
        "DAILY",
        "WARM",
        "BLUNT",
        "FALSE",
        "FIXED",
        "SCOPE",
        "AM",
        "FROZEN",
        "SHIPS",
        "NOTE",
        "POLICY",
        "BRIEF",
        "YEAR",
        "DATE",
        "GET",
        "SOURCE",
        "CLAUDE",
        # generic / already-widely-known / cross-context-ambiguous tech & legal terms
        "AWS",
        "API",
        "CSV",
        "SHA",
        "JS",
        "PR",
        "IP",
        "UTC",
        "HR",
        "DDB",
        "IAM",
        "CDK",
        "SES",
        "CRM",
        "MIT",
        "README",
        "QA",
        "CI",
        "EMA",
    }
)

# The acronym-coinage heuristic (gate b, half 2): a bare 2-6 letter ALL-CAPS token. This
# is DELIBERATELY narrower than "any platform coinage" (a Title-Case coinage like an
# un-registered future term would not match) — it is the falsifiable half the RCA asked
# for, not an omniscient one; extending it to Title-Case coinages is a named follow-up.
ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")

# Regions that are never reader-visible prose: head metadata, script/style payloads
# (including the JSON tile-registry blobs — see module docstring), inline SVG (icon/sigil
# marks carry no prose text), and the three shared chrome partials `v4_apply_chrome.py`
# already owns verbatim. DOTALL so a block spanning multiple lines matches as one region.
EXCLUDE_RE = re.compile(
    r"<head\b.*?</head>"
    r'|<nav class="doors".*?</nav>'
    r'|<footer class="site-foot".*?</footer>'
    r'|<aside class="loop-forward".*?</aside>'
    r"|<script\b.*?</script>"
    r"|<style\b.*?</style>"
    r"|<svg\b.*?</svg>",
    re.DOTALL | re.IGNORECASE,
)

# A tag-vs-text splitter for whatever's LEFT after EXCLUDE_RE removes the regions above.
# Odd indices are tags (never touched); even indices are the actual text nodes.
TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")

GLOSS_WRAP_RE = re.compile(r'<abbr class="gloss"[^>]*>(.*?)</abbr>', re.DOTALL)


def load_glossary() -> dict:
    """The committed term -> definition map, in registry order."""
    with open(GLOSSARY_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return dict(data["terms"])


def _term_pattern(terms) -> re.Pattern:
    # Longest-first so no shorter term can pre-empt a longer one sharing a prefix
    # (none do today, but the ordering is cheap insurance as the registry grows).
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in ordered) + r")\b")


def strip_glossary(html_src: str) -> str:
    """Undo every `.gloss` wrap this module ever added, back to plain text.

    Idempotency anchor: `apply_glossary` always strips before it re-applies, so
    regenerating an already-canonical page is a byte-identical no-op — the same
    contract `v4_apply_chrome.py` holds for the nav/footer/loop-forward.
    """
    return GLOSS_WRAP_RE.sub(lambda m: m.group(1), html_src)


def apply_glossary(html_src: str, page_path: str | None = None) -> str:
    """Wrap each registered term's FIRST appearance in this page's prose in
    `<abbr class="gloss" title="...">`. `page_path` is the viewer path
    (`v4_apply_chrome.url_path()` form, e.g. "/data/physical/") used only to honor
    `GLOSS_EXEMPT_PAGES`. Idempotent (strips any prior wrap first).
    """
    html_src = strip_glossary(html_src)
    if page_path in GLOSS_EXEMPT_PAGES:
        return html_src

    terms = load_glossary()
    pattern = _term_pattern(terms.keys())
    seen: set[str] = set()

    def _sub(m: re.Match) -> str:
        term = m.group(0)
        if term in seen:
            return term
        seen.add(term)
        title = _html.escape(terms[term], quote=True)
        return f'<abbr class="gloss" title="{title}">{term}</abbr>'

    def process_chunk(chunk: str) -> str:
        parts = TAG_SPLIT_RE.split(chunk)
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:  # a tag, or an empty text node
                continue
            parts[i] = pattern.sub(_sub, part)
        return "".join(parts)

    out = []
    pos = 0
    for m in EXCLUDE_RE.finditer(html_src):
        out.append(process_chunk(html_src[pos : m.start()]))
        out.append(m.group(0))  # excluded region, byte-unchanged
        pos = m.end()
    out.append(process_chunk(html_src[pos:]))
    return "".join(out)


def scan_content_text(html_src: str, page_path: str | None = None) -> str:
    """The SAME prose-only region `apply_glossary` scans, concatenated as plain text
    (tags stripped). Used by the gate (`tests/test_glossary_4035.py`) so it checks
    exactly what the applier could see — never a false positive from JSON inside a
    `<script>` block or a title/alt attribute. Returns "" for an exempt page (the
    registry deliberately does not police it — see `GLOSS_EXEMPT_PAGES`).
    """
    if page_path in GLOSS_EXEMPT_PAGES:
        return ""

    def process_chunk(chunk: str) -> str:
        parts = TAG_SPLIT_RE.split(chunk)
        return "".join(p for i, p in enumerate(parts) if i % 2 == 0)

    out = []
    pos = 0
    for m in EXCLUDE_RE.finditer(html_src):
        out.append(process_chunk(html_src[pos : m.start()]))
        pos = m.end()
    out.append(process_chunk(html_src[pos:]))
    return "".join(out)
