"""#4182 — the cockpit opens on the three questions, not the level.

The 2026-09-25 red-team panel (epic #4182, rulings 2(ii), 2(iii), 2(v)) found the
cockpit's phone fold was a full-viewport "NEW HERE?" card and, once dismissed, a bare
"6 Foundation" under "a 1–100 score of Matthew's whole day" — a friend read it as a
failing grade ("He's a 6 out of 100?!", B1 newcomer audit). The rulings:

  2(ii)  the first screen is THE THREE QUESTIONS — How's the week? / Last night? /
         Today? — third person, every number dated; the rings return on screen two.
  2(iii) the level + seven areas move below the questions, the rings and the daily
         line, COLLAPSED under a plain heading with a key; the level NAME comes off the
         reader surface (the number stays).
  2(v)   the full-viewport onboarding cards become one dismissible line.

Source-level pins, in the style of tests/test_home_fold.py. The sentence builders are
pinned against the live payload in tests/js/three_questions_4182.test.mjs; the render
is checked by the Playwright harness pre-merge and tests/visual_qa.py post-deploy.

Pinned decisions this REVERSES (each named where it is asserted below): #578 ("the big
score below is the real headline"), #807 (the dismiss-once level hint), #1106 (the
instrument strip as the first screen), PG-02 (the first-run cards on /cockpit/ and /data/).

2026-09-27, the v7 cut-over (ADR-157): /cockpit/ is the v7 Today page (scripts/v7/today.py
+ site/assets/js/v7_today.js) — the three questions, the session, the one ask, what he
skips, nothing after it. The shell pins below read the v7 page; the cockpit.js / evidence.js
pins stay as they were (those modules still drive the archive pages).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "site/cockpit/index.html").read_text(encoding="utf-8")
JS = (ROOT / "site/assets/js/cockpit.js").read_text(encoding="utf-8")
CSS = (ROOT / "site/assets/css/cockpit.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "site/assets/css/tokens.css").read_text(encoding="utf-8")
EVIDENCE_JS = (ROOT / "site/assets/js/evidence.js").read_text(encoding="utf-8")
EVIDENCE_CSS = (ROOT / "site/assets/css/evidence.css").read_text(encoding="utf-8")
TQ = (ROOT / "site/assets/js/three_questions.js").read_text(encoding="utf-8")
ABSENCE = (ROOT / "site/assets/js/absence_read.js").read_text(encoding="utf-8")


def _main():
    return HTML[HTML.index("<main") : HTML.index("</main>")]


def _strip_comments(s: str) -> str:
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


def _code(s: str) -> str:
    """JS/CSS with block and line comments removed — assertions are about what ships to a
    reader, and the comments deliberately name what was retired."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", s)


TODAY_ORDER = ["td-week", "td-night", "td-today", "td-ask", "td-skips", "td-return"]


def test_three_questions_open_the_page_and_nothing_follows_the_return_line():
    """Ruling 2(ii)/(iii), in the v7 frame. Reverses #578 ("the big score below is the
    real headline") and #1106 (the ring strip as the first thing under the kicker): the
    three questions are the first three entries, the session/ask/skips follow, and the
    page ends on the dated return line — no rings, no level, no daily line, nothing after."""
    main = _strip_comments(_main())
    idx = [main.index(f'id="{s}"') for s in TODAY_ORDER]
    assert idx == sorted(idx), "Today's entries are out of order"
    for retired in ('class="hero-instruments"', 'class="dialogue"', 'class="hub"', 'class="engine"', 'class="three-q"'):
        assert retired not in main, f"the v4 cockpit surface is back: {retired}"
    tail = main[main.index("</section>", main.index('id="td-return"')) + len("</section>") :]
    assert re.sub(r"<script[^>]*></script>", "", tail).strip() == "", f"content after the return line: {tail.strip()[:120]!r}"


def test_the_three_questions_are_labelled_in_plain_words():
    main = _strip_comments(_main())
    heads = re.findall(r'<h2 class="td-h" id="[a-z-]+-h">([^<]+)</h2>', main)
    assert heads[:3] == ["How’s the week?", "Last night?", "Today?"], heads
    assert heads[3:] == ["The one ask", "What he skips", "This page"], heads


def test_kicker_reads_today_in_one_screen():
    # The kicker is where a newcomer first meets the word "cockpit", so since #4182 the
    # build glosses it there (<dfn class="gloss">, site/data/glossary.json). The words are
    # what this pins; the gloss wrap is stripped before comparing.
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import v4_glossary

    # 2026-09-27 (ADR-157): the kicker is the page's one-line job; the word "cockpit" left
    # the reader surface with the v4 page (the vocabulary ledger counts it down).
    assert '<p class="v7-job">Matthew’s morning screen, open to anyone.</p>' in v4_glossary.strip_glossary(HTML)
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<noscript>.*?</noscript>", "", _strip_comments(_main()), flags=re.S))
    assert "one life, measured live" not in visible and not re.search(r"\bcockpit\b", visible, re.I)


def test_the_engine_section_is_off_the_page():
    """Ruling 2(iii) went further at the cut-over (ADR-157): the level, the seven areas and
    the engine's key are not on Today at all (the number survives in the baked <noscript>
    proof only; the explainer stays on /method/character/, served and unlisted). Reverses
    #807's dismiss-once level hint for good."""
    main = _strip_comments(_main())
    for retired in ("<details", 'class="engine"', 'class="engine-key"', 'data-bind="level"', 'class="hub"', 'class="domains"'):
        assert retired not in main, f"the v4 engine section is back on Today: {retired}"
    assert "data-hub-hint" not in HTML and "wireLevelHint" not in JS
    assert '<script src="/assets/js/boot_sw.js"></script>' in main, "the PWA island lives on this page only (plan §1b item 6)"


def test_the_level_name_is_not_rendered_in_reader_copy():
    """Ruling 2(iii): the level NAME ("Foundation") and XP are off the reader surface;
    the number stays."""
    assert 'data-bind="tier"' not in HTML
    assert not re.search(r"""bind\(\s*["']tier["']\s*\)""", JS)
    assert "character.tier" not in JS and "p.tier" not in JS
    assert "Foundation" not in _code(JS)  # no literal fallback name
    assert "p.tier" not in _code(ABSENCE) and "Foundation" not in _code(ABSENCE)
    # the no-JS proof block and the share tags carry the number, never the name
    proof = HTML[HTML.index("<!-- cockpit-proof:start -->") : HTML.index("<!-- cockpit-proof:end -->")]
    assert "Character level" in proof and "Foundation" not in proof
    for tag in ('property="og:title"', 'name="twitter:title"', 'property="og:description"'):
        line = next(ln for ln in HTML.splitlines() if tag in ln)
        assert "Foundation" not in line, tag
    # no XP text on the reader surface of this page
    assert not re.search(r"\bXP\b", _strip_comments(_main()))
    # the builder vocabulary "earned glow" is not a caption a reader sees
    assert 'earned glow"' not in JS and "· earned glow" not in JS


def test_the_readiness_ring_is_omitted_while_unserved():
    """Tyrell's amendment: absence is absence — no blank ring while readiness is null."""
    body = JS[JS.index("function renderHeroInstruments") : JS.index("function isBad")]
    assert "rdy != null || pre" in body


def test_the_strip_replaces_the_card_on_both_doors():
    """Ruling 2(v). Reverses PG-02's full-viewport first-run cards."""
    for src, name in ((JS, "cockpit.js"), (EVIDENCE_JS, "evidence.js")):
        assert "mountOrientStrip(" in src, name
        assert 'createElement("aside")' not in src.split("wireFirstRun", 1)[1][:800], name
    assert 'const INTRO_KEY = "ajm-cockpit-intro-v1";' in JS  # same key: a dismissed card stays dismissed
    assert 'const INTRO_KEY = "ajm-data-intro-v1";' in EVIDENCE_JS
    assert 'what: "today, in one screen"' in JS and 'what: "his numbers"' in EVIDENCE_JS
    for sheet, name in ((CSS, "cockpit.css"), (EVIDENCE_CSS, "evidence.css"), (TOKENS, "tokens.css")):
        assert not re.search(r"\.(cockpit|ev)-intro(__[a-z]+)?\s*[{,]", _code(sheet)), name
    assert ".orient-strip {" in TOKENS and ".orient-x" in TOKENS


def test_the_card_definitions_moved_inline():
    """The cockpit's definitions sit where each term first appears.

    The Data door's half REVERSED by the L-DATA lane (#4182, the panel's promise ruling):
    the /data/ promise now reads in plain words ("Weight, sleep, training, eating, blood
    tests — what his devices and apps record."), so "Correlative" / "read-only" / "flagged
    when thin" have no term left to gloss and DATA_GLOSSES is gone. The one definition that
    still binds — not medical advice — moved to the bloodwork readout's note."""
    assert "DATA_GLOSSES" not in EVIDENCE_JS
    builder = (ROOT / "scripts/v4_build_evidence.py").read_text(encoding="utf-8")
    assert '"lede": "Weight, sleep, training, eating, blood tests — what his devices and apps record."' in builder
    body = (ROOT / "site/assets/js/evidence_body.js").read_text(encoding="utf-8")
    assert "Nothing here is medical advice" in body
    for term in ("provisional", "recovery", "HRV"):
        assert f'dfn("{term}"' in TQ, term


def test_only_the_two_named_fetches_are_new():
    """The brief's fetch budget: /api/nutrition_overview + /api/coaching-dashboard, once
    each; /api/routine is shared with the levers (one memoized request)."""
    assert JS.count("/nutrition_overview`") == 1
    assert JS.count("/coaching-dashboard`") == 1
    assert JS.count("/routine`") == 1
    assert "fetch(" not in TQ and "getJSON" not in TQ  # the builders are pure


def test_third_person_on_the_new_surface():
    """Panel §5: third person — the owner and ~1,100 readers see one page."""
    main = _strip_comments(_main())
    for anchor in ("td-week", "td-night", "td-today", "td-ask", "td-skips"):
        chunk = main[main.index(f'id="{anchor}"') : main.index("</section>", main.index(f'id="{anchor}"'))]
        visible = re.sub(r"<[^>]+>", " ", chunk)
        assert not re.search(r"\byou(r|rs)?\b", visible, re.I), visible
    # the one address to the reader is the page's own note ("you’re welcome to look") — never a read
    assert "where you stand" not in main
