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


def test_three_questions_precede_the_hub_the_rings_and_the_daily_line():
    """Ruling 2(ii)/(iii). Reverses #578 ("the big score below is the real headline")
    and #1106 (the ring strip as the first thing under the kicker)."""
    main = _strip_comments(_main())
    tq = main.index('class="three-q"')
    assert tq < main.index('class="hero-instruments"'), "the rings are screen two"
    assert tq < main.index('class="dialogue"'), "the daily line follows the questions"
    assert tq < main.index('class="hub"'), "the level follows the questions"
    # …and the hub sits below the daily line too, inside the collapsed engine section.
    assert main.index('class="dialogue"') < main.index('class="engine"') < main.index('class="hub"')


def test_the_three_questions_are_labelled_in_plain_words():
    main = _strip_comments(_main())
    sec = main[main.index('class="three-q"') : main.index("</section>", main.index('class="three-q"'))]
    heads = re.findall(r'<h2 class="tq-h">([^<]+)</h2>', sec)
    assert heads == ["How's the week?", "Last night?", "Today?"]
    for key in ("tq-week", "tq-night", "tq-today", "tq-ask", "tq-fresh"):
        assert f'data-bind="{key}"' in sec, key


def test_kicker_reads_today_in_one_screen():
    assert '<p class="ph-kicker label">the cockpit · today, in one screen</p>' in HTML
    assert "one life, measured live</p>" not in _strip_comments(_main().split("<noscript>")[0])


def test_engine_section_is_collapsed_and_keyed():
    """Ruling 2(iii): collapsed (<details> without `open`), a plain-English heading, the
    key printed before the number. Reverses #807's dismiss-once level hint."""
    main = _strip_comments(_main())
    m = re.search(r"<details([^>]*)>", main)
    assert m and 'class="engine"' in m.group(1) and " open" not in m.group(1)
    engine = main[m.start() : main.index("</details>", m.start())]
    assert "The engine&rsquo;s score for yesterday &mdash; what built it" in engine
    key = engine[engine.index('class="engine-key"') :]
    assert key.index("Score</strong>") < key.index('class="hub"') if 'class="hub"' in key else True
    assert "no evidence of the behavior" in engine and "its rule, not him" in engine
    for inside in ('class="hub"', 'data-bind="level"', 'class="domains"', 'class="band"', 'class="cap label cap-today"'):
        assert inside in engine, inside
    assert "data-hub-hint" not in HTML and "wireLevelHint" not in JS


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
    for chunk in (
        main[main.index('class="three-q"') : main.index("</section>", main.index('class="three-q"'))],
        main[main.index('class="engine"') : main.index("</details>")],
    ):
        visible = re.sub(r"<[^>]+>", " ", chunk)
        assert not re.search(r"\byou(r|rs)?\b", visible, re.I), visible
    assert "where you stand" not in main
