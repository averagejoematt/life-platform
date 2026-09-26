"""The newcomer's glossary — the two-sided gate (#4035, re-filed from #3618).

`site/data/glossary.json` is the ONE term registry (#4182 folded #4035's retired
`site/config/glossary.json` into it); `scripts/v4_glossary.py` applies it at build time
(first ELIGIBLE appearance per page, wrapped in `<dfn class="gloss" tabindex="0" title
data-gloss>` — eligible = outside links, buttons, h1/h2, code, labels and `<noscript>`);
`scripts/v4_apply_chrome.py` is the writer. This file is the gate over the BUILT
(committed) HTML — not the applier's own logic (that gets direct unit coverage below
too, but the gate itself must check what actually shipped):

1. `test_apply_chrome_check_is_green_for_glossary` — `v4_apply_chrome.py --check` sees
   no glossary drift (mirrors `test_site_chrome.py`'s chrome-drift assertion).
2. `test_every_registered_term_is_glossed_at_first_appearance` — gate (a): every
   registered term with an eligible appearance on a page must be wrapped there, exactly
   once; a later plain-text appearance of the SAME term is fine (only the first is glossed).
3. `test_no_unregistered_acronym_coinage` — gate (b): no capitalised 2-6 letter token in
   page prose may be neither a registered term nor an explicit, dated allowlist entry —
   the falsifiable half of "every term," not "the terms someone remembered."
4. Unit coverage for `apply_glossary`/`strip_glossary` idempotency and the exempt-page
   contract, isolated from the live site tree.
5. (#4182) the word-ci terms + the skipped contexts + the legacy-wrap convergence, and the
   runtime half: `glossary_terms.js` is the registry's generated copy, and served coach
   prose is fenced `data-verbatim` so the runtime pass never touches it.
"""

from __future__ import annotations

import html as html_escape_mod
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    """Gate (a): every registered term that has an ELIGIBLE appearance on a page (the same
    text the applier walks — `v4_glossary.eligible_terms`) must carry exactly one
    `<dfn class="gloss">` wrap with its registry definition, never zero. Reds if a page is
    hand-edited (or a generator emits raw HTML) without going through `v4_apply_chrome.py`,
    stating the failure by term — the drift check above would also catch it, by page only.
    """
    terms = v4_glossary.load_glossary()
    checked_pages = 0
    for rel, html in _non_legacy_content_pages():
        page_path = v4_apply_chrome.url_path(str(rel))
        if page_path in v4_glossary.GLOSS_EXEMPT_PAGES:
            continue  # exempt page (declared in v4_glossary.GLOSS_EXEMPT_PAGES)
        checked_pages += 1
        for term in v4_glossary.eligible_terms(html, page_path=page_path):
            d = html_escape_mod.escape(terms[term], quote=True)
            wraps = re.findall(rf'<dfn class="gloss" tabindex="0" title="{re.escape(d)}" data-gloss="{re.escape(d)}">([^<]*)</dfn>', html)
            wraps = [w for w in wraps if w.lower() == term.lower()]
            assert len(wraps) == 1, f"{rel}: {term!r} appears in eligible prose but is wrapped {len(wraps)} times (want exactly 1)"
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
        "site/data/glossary.json (kind acronym, match exact, a real definition) or add a dated, reasoned "
        "entry to v4_glossary.GLOSS_ALLOWLIST:\n"
        + "\n".join(f"  {tok}: {', '.join(sorted(pages))}" for tok, pages in sorted(offenders.items()))
    )


# ── registry entries as gates (#3536/gate_census): each GLOSS_ALLOWLIST / GLOSS_EXEMPT_
# PAGES entry is proved BOTH directions — (a) LOAD-BEARING: remove the entry and the real
# gate (b) logic must catch a regression it would otherwise silently pass; (b) NOT A
# BLANKET EXEMPTION: with the entry present, a DIFFERENT off-list token/page is still
# caught. Exercises the ACTUAL production regex/constants against synthetic input, never
# a re-implementation — the same proof shape tests/gate_census_proofs.py's
# PROMPT_LITERAL_ALLOWLIST / RECEDE_TEXT_RULES entries use. Offline, no live-page
# dependency: an allowlist entry that currently appears nowhere on the real site would
# otherwise be unprovable by a live-tree scan alone.
_OFF_LIST_PLANT = "ZQXVK"  # never a registered term, never an allowlist entry, matches ACRONYM_RE


@pytest.mark.parametrize("term", sorted(v4_glossary.GLOSS_ALLOWLIST))
def test_each_allowlist_entry_is_load_bearing_and_not_blanket(term):
    terms = set(v4_glossary.load_glossary())
    assert term not in terms, f"{term} is both a registered term AND an allowlist entry — the allowlist entry is dead weight"
    assert _OFF_LIST_PLANT not in terms and _OFF_LIST_PLANT not in v4_glossary.GLOSS_ALLOWLIST

    # (a) LOAD-BEARING: remove this ONE entry from a copy of the allowlist; the real
    # ACRONYM_RE must still match the term, and the gate's own offender predicate
    # (mirrors test_no_unregistered_acronym_coinage's loop body exactly) must now flag it.
    found = [m.group(0) for m in v4_glossary.ACRONYM_RE.finditer(f"{term} appears in prose.")]
    assert term in found, f"{term} does not match ACRONYM_RE — the allowlist entry can never fire"
    allowlist_without = v4_glossary.GLOSS_ALLOWLIST - {term}
    offenders_without = [t for t in found if t not in terms and t not in allowlist_without]
    assert offenders_without == [term], f"removing {term} from GLOSS_ALLOWLIST did not red — dead entry"

    # (b) NOT A BLANKET EXEMPTION: with the FULL allowlist intact (this entry present),
    # a different off-list token in the SAME prose is still caught — the entry excuses
    # only itself, not every acronym on the page.
    found_both = [m.group(0) for m in v4_glossary.ACRONYM_RE.finditer(f"{term} and {_OFF_LIST_PLANT} both appear here.")]
    offenders_with_full = [t for t in found_both if t not in terms and t not in v4_glossary.GLOSS_ALLOWLIST]
    assert offenders_with_full == [_OFF_LIST_PLANT], f"{term}'s allowlist entry swallowed an unrelated off-list token"


@pytest.mark.parametrize("page_path", sorted(v4_glossary.GLOSS_EXEMPT_PAGES))
def test_each_exempt_page_entry_is_load_bearing_and_not_blanket(monkeypatch, page_path):
    html = "<p>RMSSD lives here, already defined inline.</p>"

    # (a) LOAD-BEARING: remove this ONE entry from a copy of GLOSS_EXEMPT_PAGES; the
    # real scan_content_text() must now SCAN the page instead of skipping it.
    remaining = v4_glossary.GLOSS_EXEMPT_PAGES - {page_path}
    monkeypatch.setattr(v4_glossary, "GLOSS_EXEMPT_PAGES", remaining)
    scanned = v4_glossary.scan_content_text(html, page_path=page_path)
    assert scanned != "", f"{page_path} is still exempt after its own GLOSS_EXEMPT_PAGES entry was removed — dead entry"
    monkeypatch.undo()

    # (b) NOT A BLANKET EXEMPTION: with the full exempt set restored, a DIFFERENT,
    # non-exempt page path is still scanned normally.
    assert v4_glossary.scan_content_text(html, page_path="/data/vitals/") != ""


# ── Unit coverage: the applier in isolation, off the live site tree ────────────────


def test_apply_glossary_wraps_first_occurrence_only():
    html = "<p>Track your HRV daily. HRV trends matter more than any single HRV reading.</p>"
    out = v4_glossary.apply_glossary(html)
    assert out.count('<dfn class="gloss"') == 1
    assert out.count("HRV") == 3  # 1 wrapped + 2 bare occurrences; wrapping doesn't touch the text itself
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
    assert out.count('<dfn class="gloss"') == 1
    assert "Real prose about <dfn" in out


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


# ── #4035 regression guard: a build-time gloss is only real if a browser keeps it ──


def test_evidence_js_never_blindly_overwrites_the_glossed_topic_lede():
    """A gate over the BUILT HTML string (the ones above) cannot see that a browser
    then runs JS over it. `evidence.js` drives ~30 /data/ + /protocols/ + /method/
    topic pages (the same population this glossary targets), and used to run
    `main.querySelector("[data-blurb]").textContent = t.blurb;` unconditionally on
    EVERY render call, including the initial page load — discarding the server's
    already-glossed `<p class="topic-lede" data-blurb>` (v4_glossary.py's own build-
    time gloss wrap) for a live reader before they ever saw it. A
    Playwright render pass (`tests/pr_render_gate.py`) is what actually caught this —
    this regression test pins the fix at the source level so it can't quietly revert:
    the unconditional overwrite must not reappear, and a same-content guard must.
    """
    src = (SITE / "assets" / "js" / "evidence.js").read_text(encoding="utf-8")
    assert 'querySelector("[data-blurb]").textContent = t.blurb' not in src, (
        "evidence.js reintroduced an unconditional data-blurb overwrite — this discards "
        "the server-rendered glossary wrap on the topic-lede for every real reader, even "
        "though every offline gate above stays green (they never run a browser)"
    )
    assert "be.textContent.trim() !== String(t.blurb" in src, (
        "the same-content guard that preserves the server's glossed topic-lede on first " "paint is missing from evidence.js"
    )


# ── #4182: one registry, build-time <dfn>, word-ci terms, and the runtime half ──────────


def test_word_ci_terms_gloss_prose_but_never_links_headings_or_noscript():
    """The keep-with-gloss words match case-insensitively, word-bounded, and only where a
    reader meets them as prose: never inside a link, a button, an h1/h2, code, a label or
    the no-JS copy. The first ELIGIBLE appearance wins, in its own casing, and a page built
    under #4035's <abbr> generation converges on the same output (idempotent both ways)."""
    html = (
        "<h1>The cockpit</h1><noscript><p>cockpit</p></noscript>"
        '<p><a href="/cockpit/">the cockpit</a> and <code>cockpit</code></p>'
        "<p>Cockpit reads come first; the cockpit again; cockpits never match.</p>"
        "<p>His HRV and his hrv.</p>"
    )
    out = v4_glossary.apply_glossary(html)
    g = v4_glossary.load_glossary()
    d = html_escape_mod.escape(g["cockpit"], quote=True)
    assert f'<p><dfn class="gloss" tabindex="0" title="{d}" data-gloss="{d}">Cockpit</dfn> reads' in out
    assert out.count("<dfn") == 2  # cockpit once (prose) + HRV once (exact case only)
    assert "<h1>The cockpit</h1>" in out and '<a href="/cockpit/">the cockpit</a>' in out and "<code>cockpit</code>" in out
    assert "<noscript><p>cockpit</p></noscript>" in out
    assert "his hrv." in out  # HRV is exact-case: the lowercase form is not the acronym
    legacy = html.replace("His HRV", '<p>His <abbr class="gloss" title="old">HRV</abbr>'.replace("<p>", ""))
    assert v4_glossary.apply_glossary(legacy) == out
    assert v4_glossary.apply_glossary(out) == out
    assert v4_glossary.eligible_terms(html) == {"cockpit", "HRV"}


def test_runtime_half_is_the_registry_and_never_touches_served_coach_text():
    """The runtime pass (gloss_runtime.js) glosses JS-rendered text from
    `glossary_terms.js`, which must be the registry's GENERATED copy — a hand edit, or a
    registry edit without `--emit-js`, reds here. It skips `[data-verbatim]`, and the
    served coach prose containers carry that fence ("the page may gloss a coach; it may
    not rewrite one" — and a tooltip spliced into a quote is an edit a reader sees)."""
    js = (SITE / "assets" / "js" / "glossary_terms.js").read_text(encoding="utf-8")
    assert js == v4_glossary.render_terms_js(), "glossary_terms.js is stale — run: python3 scripts/v4_glossary.py --emit-js"
    assert not (SITE / "config" / "glossary.json").exists(), "the retired second registry is back — site/data/glossary.json is the one"
    runtime = (SITE / "assets" / "js" / "gloss_runtime.js").read_text(encoding="utf-8")
    assert 'from "/assets/js/glossary_terms.js"' in runtime and "glossFirst(" in runtime
    assert "[data-verbatim]" in (SITE / "assets" / "js" / "orient.js").read_text(encoding="utf-8")
    assert "gloss_runtime.js" in v4_apply_chrome.v4_chrome.site_footer(), "the runtime pass is not loaded from the canonical footer"
    for name in ("coaching.js", "three_questions.js"):
        assert "data-verbatim" in (SITE / "assets" / "js" / name).read_text(
            encoding="utf-8"
        ), f"{name} renders served coach text without the data-verbatim fence"
