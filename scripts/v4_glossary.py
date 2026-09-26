"""v4_glossary.py — the newcomer's glossary, applied at build time (#4035, re-filed
from #3618, Part 4 reader ROW1 of `docs/reviews/FORENSIC_RCA_2026-09-05.md`).

WHAT WAS MISSING. `find . -iname '*glossar*'` returned nothing; `grep -c '<abbr'` over
site/index.html, site/data/index.html and site/cockpit/index.html returned 0, 0, 0 while
"HRV" appeared across dozens of pages and "Brier" across dozens more — every term the
platform's own vocabulary coins or borrows, never once explained inline. This module is
the fix, kept a **build-time text transform** (per the RCA's own priced-FREE proposal):
no runtime cost, no new JS payload, no series, no tokens.

HOW IT WORKS. `site/data/glossary.json` is the ONE term registry (#4182 folded #4035's
`site/config/glossary.json` into it and retired that file). Every entry with a `match`
is glossed: `exact` entries (the acronyms — HRV, DEXA, Brier, …) match case-sensitively,
`word-ci` entries (the keep-with-gloss words the 2026-09-26 panel ruled — cockpit, cycle,
correlation, protocol, glucose, Whoop) match case-insensitively; both word-bounded.
`apply_glossary(html, page_path)` walks a page's HTML, skipping every region that is not
reader-visible PROSE — `<head>`, `<script>`, `<style>`, `<svg>`, HTML comments, the shared
`<nav class="doors">`, `<footer class="site-foot">` and `<aside class="loop-forward">`
chrome blocks (script blocks matter most: several `/data/*` pages embed a JSON tile
registry inside a `<script>` tag that JS renders into visible tile blurbs at RUNTIME —
that text is invisible to a build-time HTML pass by construction, and injecting markup
into JSON would corrupt it; `site/assets/js/gloss_runtime.js` is the runtime half, fed by
the generated `site/assets/js/glossary_terms.js`) — and wraps each registered term's
FIRST ELIGIBLE appearance per page in
`<dfn class="gloss" tabindex="0" title="…" data-gloss="…">` (`title` for hover and
assistive tech, `data-gloss` for the tap reveal `tokens.css` draws on `:focus`, since a
phone has no hover). "Eligible" skips text inside `a`, `button`, `h1`, `h2`, `code`,
`label`, form controls, an existing `dfn`/`abbr`, and `<noscript>` (the no-JS copy a JS
reader never sees — a gloss parked there would be lost to them). Re-running is
idempotent: every existing `.gloss` wrap — the legacy `<abbr class="gloss">` and the
`<dfn class="gloss">` alike — is stripped back to plain text before the fresh pass, so
regenerating a canonical page is a byte-identical no-op (the same contract
`v4_apply_chrome.py` holds for the nav/footer/loop-forward).

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
GLOSSARY_PATH = os.path.join(REPO_ROOT, "site", "data", "glossary.json")
# The runtime half's generated copy (#4182) — a repo-relative literal so
# tests/derived_artifact_registry.py's discovery names it and the registry must classify it.
JS_TERMS_REL = "site/assets/js/glossary_terms.js"
JS_TERMS_PATH = os.path.join(REPO_ROOT, *JS_TERMS_REL.split("/"))

# Declared, dated exemption (see module docstring): the two statistics-registry pages
# already define every term they use inline, formula and all.
GLOSS_EXEMPT_PAGES = frozenset({"/method/registry/", "/method/mirror/"})

# Gate-(b) allowlist — tokens the ALL-CAPS acronym heuristic below would otherwise catch
# that are NOT platform jargon a newcomer needs explained. Three grounds, each real:
#   (1) roman numerals, 2+ CHARACTERS ONLY — chapter/part numbers ("Chapter II"), not
#       acronyms at all. Single-letter I/V/X are never listed here: ACRONYM_RE's own
#       `{2,6}` floor cannot match a 1-character token, so an entry for one would be
#       decoration the heuristic could never reach — found and removed 2026-09-23 while
#       proving this allowlist load-bearing entry-by-entry (#3536/gate_census): each was
#       "declared-unwired" by construction, the exact defect class this census exists
#       to catch, one layer up from the gate it was sitting beside.
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
        # roman numerals (chapter/part numbers), 2+ characters only — see the header note
        "II",
        "III",
        "IV",
        "VI",
        "VII",
        "VIII",
        "IX",
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
# Closing tags allow whitespace/attributes before `>` (`</script >` and `</script\t\n bar>`
# are end tags a browser honours — CodeQL py/bad-tag-filter on PR #4128, twice; a payload written that way would otherwise leak into the
# "prose" the acronym gate scans).
EXCLUDE_RE = re.compile(
    r"<!--.*?-->"
    r"|<head\b.*?</head\b[^>]*>"
    r'|<nav class="doors".*?</nav\b[^>]*>'
    r'|<footer class="site-foot".*?</footer\b[^>]*>'
    r'|<aside class="loop-forward".*?</aside\b[^>]*>'
    r"|<script\b.*?</script\b[^>]*>"
    r"|<style\b.*?</style\b[^>]*>"
    r"|<svg\b.*?</svg\b[^>]*>",
    re.DOTALL | re.IGNORECASE,
)

# A tag-vs-text splitter for whatever's LEFT after EXCLUDE_RE removes the regions above.
# Odd indices are tags (never touched); even indices are the actual text nodes.
TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")

# Both wrap forms this module has ever emitted: #4035's `<abbr class="gloss">` and #4182's
# `<dfn class="gloss">`. Stripping both is what keeps a page built under either generation
# converging on one canonical output.
GLOSS_WRAP_RE = re.compile(r'<(abbr|dfn) class="gloss"[^>]*>(.*?)</\1>', re.DOTALL)

# Text inside these elements is never glossed (a gloss inside a link or a button nests one
# focusable inside another; a heading or a label is a name, not prose; `code` is literal).
# `noscript` is the no-JS copy — see the module docstring.
SKIP_TAGS = frozenset({"a", "button", "h1", "h2", "code", "label", "abbr", "dfn", "noscript", "option", "select", "textarea", "title"})
_TAG_NAME_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9-]*)")
_WORD = "A-Za-z0-9_"


def load_entries() -> list[dict]:
    """Every registry entry that is glossed (carries a `match`), in registry order."""
    with open(GLOSSARY_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return [t for t in data["terms"] if t.get("match") in ("exact", "word-ci")]


def load_glossary() -> dict:
    """The glossed term -> definition map, in registry order."""
    return {t["term"]: t["gloss"] for t in load_entries()}


def _term_pattern(entries) -> re.Pattern:
    # Longest-first so no shorter term can pre-empt a longer one sharing a prefix.
    # Word-ci terms carry a scoped (?i:…) flag; exact terms stay case-sensitive.
    alts = []
    for t in sorted(entries, key=lambda e: len(e["term"]), reverse=True):
        body = re.escape(t["term"])
        alts.append(f"(?i:{body})" if t["match"] == "word-ci" else body)
    return re.compile(rf"(?<![{_WORD}])(?:" + "|".join(alts) + rf")(?![{_WORD}])")


def _canonical(entries):
    """matched text -> entry (exact by text, word-ci by lowercase)."""
    exact = {t["term"]: t for t in entries if t["match"] == "exact"}
    ci = {t["term"].lower(): t for t in entries if t["match"] == "word-ci"}
    return lambda text: exact.get(text) or ci.get(text.lower())


def strip_glossary(html_src: str) -> str:
    """Undo every `.gloss` wrap this module ever added (abbr or dfn), back to plain text.

    Idempotency anchor: `apply_glossary` always strips before it re-applies, so
    regenerating an already-canonical page is a byte-identical no-op.
    """
    return GLOSS_WRAP_RE.sub(lambda m: m.group(2), html_src)


def dfn_html(text: str, definition: str) -> str:
    """The one gloss element — the SAME markup `orient.js::dfn` renders at runtime."""
    d = _html.escape(definition, quote=True)
    return f'<dfn class="gloss" tabindex="0" title="{d}" data-gloss="{d}">{text}</dfn>'


def _walk(html_src: str, page_path: str | None, on_text):
    """Feed every ELIGIBLE text node (outside EXCLUDE_RE regions and SKIP_TAGS) to
    `on_text(text) -> text`; return the reassembled page. Shared by the applier and the
    gate helper so both see exactly the same text."""
    depth = [0]

    def process_chunk(chunk: str) -> str:
        parts = TAG_SPLIT_RE.split(chunk)
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 1:  # a tag — track entry/exit of the skipped elements
                m = _TAG_NAME_RE.match(part)
                if m and m.group(2).lower() in SKIP_TAGS and not part.endswith("/>"):
                    depth[0] += -1 if m.group(1) else 1
                    depth[0] = max(depth[0], 0)
                continue
            if depth[0] == 0:
                parts[i] = on_text(part)
        return "".join(parts)

    out = []
    pos = 0
    for m in EXCLUDE_RE.finditer(html_src):
        out.append(process_chunk(html_src[pos : m.start()]))
        out.append(m.group(0))  # excluded region, byte-unchanged
        pos = m.end()
    out.append(process_chunk(html_src[pos:]))
    return "".join(out)


def apply_glossary(html_src: str, page_path: str | None = None) -> str:
    """Wrap each glossed term's FIRST eligible appearance in this page's prose in a
    `<dfn class="gloss">`. `page_path` is the viewer path (`v4_apply_chrome.url_path()`
    form, e.g. "/data/physical/") used only to honor `GLOSS_EXEMPT_PAGES`. Idempotent
    (strips any prior wrap first).
    """
    html_src = strip_glossary(html_src)
    if page_path in GLOSS_EXEMPT_PAGES:
        return html_src
    entries = load_entries()
    pattern = _term_pattern(entries)
    lookup = _canonical(entries)
    seen: set[str] = set()

    def _sub(m: re.Match) -> str:
        entry = lookup(m.group(0))
        if entry is None or entry["term"] in seen:
            return m.group(0)
        seen.add(entry["term"])
        return dfn_html(m.group(0), entry["gloss"])

    return _walk(html_src, page_path, lambda text: pattern.sub(_sub, text))


def eligible_terms(html_src: str, page_path: str | None = None) -> set[str]:
    """The registry terms that have at least one ELIGIBLE appearance on this page — the
    set `apply_glossary` must have wrapped. Used by the gate so it asks exactly what the
    applier could see."""
    if page_path in GLOSS_EXEMPT_PAGES:
        return set()
    entries = load_entries()
    pattern = _term_pattern(entries)
    lookup = _canonical(entries)
    found: set[str] = set()

    def _scan(text: str) -> str:
        for m in pattern.finditer(text):
            entry = lookup(m.group(0))
            if entry is not None:
                found.add(entry["term"])
        return text

    _walk(strip_glossary(html_src), page_path, _scan)
    return found


def scan_content_text(html_src: str, page_path: str | None = None) -> str:
    """The prose-only region the gate's acronym heuristic scans (tags stripped, EXCLUDE_RE
    regions dropped — never a false positive from JSON inside a `<script>` block or a
    title/alt attribute). Returns "" for an exempt page (the registry deliberately does not
    police it — see `GLOSS_EXEMPT_PAGES`).
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


def render_terms_js() -> str:
    """`site/assets/js/glossary_terms.js` — the runtime half's copy of the registry.

    GENERATED (`python3 scripts/v4_glossary.py --emit-js`); tests/derived_artifact_registry.py
    holds it byte-equal to this function's output, so it can never drift from the JSON.
    """
    rows = [{"term": t["term"], "gloss": t["gloss"], "ci": t["match"] == "word-ci"} for t in load_entries()]
    body = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows)
    return (
        "// GENERATED by scripts/v4_glossary.py --emit-js from site/data/glossary.json (#4182) — never hand-edit.\n"
        "// The runtime gloss pass (gloss_runtime.js) wraps each term's first appearance in JS-rendered text.\n"
        f"export const GLOSSARY_TERMS = [\n{body},\n];\n"
    )


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="The site glossary (#4035/#4182).")
    ap.add_argument("--emit-js", action="store_true", help="write site/assets/js/glossary_terms.js from site/data/glossary.json")
    ap.add_argument("--check", action="store_true", help="with --emit-js: exit 1 if the committed file is stale (no write)")
    args = ap.parse_args(argv)
    if not args.emit_js:
        ap.print_help()
        return 2
    want = render_terms_js()
    have = open(JS_TERMS_PATH, encoding="utf-8").read() if os.path.exists(JS_TERMS_PATH) else None
    if args.check:
        if have != want:
            print(f"{JS_TERMS_PATH} is stale — run: python3 scripts/v4_glossary.py --emit-js")
            return 1
        return 0
    if have != want:
        with open(JS_TERMS_PATH, "w", encoding="utf-8") as fh:
            fh.write(want)
        print(f"wrote {JS_TERMS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
