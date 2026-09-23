"""The newcomer's glossary — the two-sided gate (#4035, re-filed from #3618).

`site/config/glossary.json` is the committed term registry; `scripts/v4_glossary.py`
applies it at build time (first appearance per page, wrapped in `<abbr class="gloss">`);
`scripts/v4_apply_chrome.py` is the writer. This file is the gate over the BUILT
(committed) HTML — not the applier's own logic (that gets direct unit coverage below
too, but the gate itself must check what actually shipped):

1. `test_apply_chrome_check_is_green_for_glossary` — `v4_apply_chrome.py --check` sees
   no glossary drift (mirrors `test_site_chrome.py`'s chrome-drift assertion).
2. `test_every_registered_term_is_glossed_at_first_appearance` — gate (a): a registered
   term's first prose appearance on a page must be wrapped; a later plain-text
   appearance of the SAME term on the SAME page is fine (only the first one is glossed
   by design).
3. `test_no_unregistered_acronym_coinage` — gate (b): no capitalised 2-6 letter token in
   page prose may be neither a registered term nor an explicit, dated allowlist entry —
   the falsifiable half of "every term," not "the terms someone remembered."
4. Unit coverage for `apply_glossary`/`strip_glossary` idempotency and the exempt-page
   contract, isolated from the live site tree.
"""

from __future__ import annotations

import html as html_escape_mod
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_apply_chrome  # noqa: E402
import v4_glossary  # noqa: E402


def _non_legacy_content_pages():
    for path in sorted(SITE.rglob("*.html")):
        rel = path.relative_to(SITE)
        if "legacy" in rel.parts:
            continue
        html = path.read_text(encoding="utf-8")
        if '<nav class="doors"' not in html and '<footer class="site-foot"' not in html:
            continue  # chrome-free stub/fragment — not in the glossary's scope either
        yield rel, html


def test_apply_chrome_check_is_green_for_glossary():
    """No page's glossary wraps may drift from `v4_glossary.apply_glossary()`."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "v4_apply_chrome.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"chrome/glossary drift — run scripts/v4_apply_chrome.py and commit:\n{proc.stdout}\n{proc.stderr}"


def test_every_registered_term_is_glossed_at_first_appearance():
    """Gate (a): scanning the SAME prose region the applier scans, a registered term's
    first occurrence on a page must already be inside `<abbr class="gloss">` — never
    bare. Reds if a page is hand-edited (or a future generator emits raw HTML) without
    going through `v4_apply_chrome.py`, catching regression the drift check above would
    also catch but stating the FAILURE MODE explicitly by term.
    """
    terms = v4_glossary.load_glossary()
    checked_pages = 0
    for rel, html in _non_legacy_content_pages():
        page_path = v4_apply_chrome.url_path(str(rel))
        text = v4_glossary.scan_content_text(html, page_path=page_path)
        if not text:
            continue  # exempt page (declared in v4_glossary.GLOSS_EXEMPT_PAGES)
        checked_pages += 1
        for term in terms:
            first = text.find(term)
            if first == -1:
                continue  # term doesn't appear on this page at all
            # The glossed HTML wraps the term as `<abbr class="gloss" title="...">TERM`
            # immediately before its first plain-text appearance's position in the
            # STRIPPED content stream is identical (stripping removes only the wrapper
            # markup, not text) — so the live page must contain the wrap literally.
            wrapped = f'<abbr class="gloss" title="{html_escape_mod.escape(terms[term], quote=True)}">{term}</abbr>'
            assert wrapped in html, f"{rel}: {term!r} appears in prose but its first occurrence is not glossed"
    assert checked_pages > 0, "no non-exempt content pages found — the gate didn't run over anything"


def test_no_unregistered_acronym_coinage():
    """Gate (b), half 2: every capitalised 2-6 letter token found in page prose must be
    either a registered glossary term or an explicit, dated `GLOSS_ALLOWLIST` entry.
    Falsifiable — a new un-glossed acronym reds this by NAME, not just by count.
    """
    terms = set(v4_glossary.load_glossary())
    checked_pages = 0
    offenders: dict[str, set[str]] = {}
    for rel, html in _non_legacy_content_pages():
        page_path = v4_apply_chrome.url_path(str(rel))
        text = v4_glossary.scan_content_text(html, page_path=page_path)
        if not text:
            continue
        checked_pages += 1
        for m in v4_glossary.ACRONYM_RE.finditer(text):
            tok = m.group(0)
            if tok in terms or tok in v4_glossary.GLOSS_ALLOWLIST:
                continue
            offenders.setdefault(tok, set()).add(str(rel))
    assert checked_pages > 0, "no non-exempt content pages found — the gate didn't run over anything"
    assert not offenders, (
        "unregistered capitalised acronym(s) found in page prose — register each in "
        "site/config/glossary.json (with a real definition) or add a dated, reasoned "
        "entry to v4_glossary.GLOSS_ALLOWLIST:\n"
        + "\n".join(f"  {tok}: {', '.join(sorted(pages))}" for tok, pages in sorted(offenders.items()))
    )


# ── Unit coverage: the applier in isolation, off the live site tree ────────────────


def test_apply_glossary_wraps_first_occurrence_only():
    html = "<p>Track your HRV daily. HRV trends matter more than any single HRV reading.</p>"
    out = v4_glossary.apply_glossary(html)
    assert out.count('<abbr class="gloss"') == 1
    assert out.count(">HRV<") == 0  # the wrapped one has attrs between > and HRV
    assert "HRV trends matter" in out  # later occurrences stay plain
    assert "any single HRV reading" in out


def test_apply_glossary_skips_script_style_nav_footer():
    html = (
        "<head><title>HRV</title></head>"
        '<nav class="doors">HRV<button class="theme-toggle"></button></nav>'
        '<script>var x = "HRV";</script>'
        '<style>.x::before{content:"HRV"}</style>'
        "<svg><text>HRV</text></svg>"
        "<p>Real prose about HRV.</p>"
    )
    out = v4_glossary.apply_glossary(html)
    assert out.count('<abbr class="gloss"') == 1
    assert "Real prose about <abbr" in out


def test_apply_glossary_is_idempotent():
    html = "<p>Weekly HRV and Brier both matter.</p>"
    once = v4_glossary.apply_glossary(html)
    twice = v4_glossary.apply_glossary(once)
    assert once == twice


def test_strip_glossary_round_trips():
    html = "<p>Weekly HRV and Brier both matter.</p>"
    glossed = v4_glossary.apply_glossary(html)
    assert glossed != html
    assert v4_glossary.strip_glossary(glossed) == html


def test_exempt_page_is_never_glossed():
    html = "<p>RMSSD and SE and AR live here, already defined inline.</p>"
    out = v4_glossary.apply_glossary(html, page_path="/method/registry/")
    assert out == html
    assert v4_glossary.scan_content_text(html, page_path="/method/registry/") == ""
