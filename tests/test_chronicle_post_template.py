"""tests/test_chronicle_post_template.py — #384: the individual chronicle post page
is on the v5 "The Measured Life" template.

Pins the five acceptance criteria of the story-hosted post page so a template
regression can't silently re-introduce the retired chrome:
  * AC1 — the live five-door story-top nav (no legacy /platform//character//#experiment links),
  * AC2 — og:image is the editorial cover when one exists (og-home fallback otherwise),
  * AC3 — rel=canonical + structured-data @id both point at the un-redirected /journal/posts/ URL
          (the retired /chronicle/posts/ path is gone),
  * AC4 — an end-of-read subscribe CTA linking /subscribe/,
  * (AC5 — "verified live on the newest post" is post-deploy + weekly-publish gated; not unit-testable.)

All offline — editorial_image is force-disabled so no S3/network fetch happens; the
template is rendered via publish_to_journal(write_to_s3=False).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import wednesday_chronicle_lambda as chron  # noqa: E402

_BODY = "<p>It was a quiet, steady week — nothing dramatic, everything trending the right way.</p><p>More.</p>"
_INSTALLMENTS = [
    {"date": "2026-06-24", "week_number": 3, "title": "Prior", "stats_line": ""},
    {"date": "2026-07-01", "week_number": 4, "title": "The weight of a steady week", "stats_line": "Weight 298 lb"},
]


class _NoS3:
    """Neutralize the prior-manifest read so the test is hermetic regardless of live
    AWS creds — publish_to_journal(write_to_s3=False) never writes, it only reads
    generated/journal/posts.json to carry covers forward; force that to miss."""

    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _render(monkeypatch, cur_image=None):
    """Render the post page HTML offline. editorial_image is force-off so no fetch runs;
    cur_image lets a test inject a cover to exercise the og:image path."""
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: bool(cur_image))
    if cur_image is not None:
        monkeypatch.setattr(editorial_image, "fetch_and_store", lambda *a, **k: cur_image)
    post_key, post_html, _posts_json = chron.publish_to_journal(
        title="The weight of a steady week",
        stats_line="Weight 298 lb · Recovery 64% · 5 workouts",
        body_html=_BODY,
        week_num=4,
        date_str="2026-07-01",
        all_installments=_INSTALLMENTS,
        write_to_s3=False,
    )
    return post_key, post_html


# ── AC1: the live five-door nav; legacy links gone ────────────────────────────


def test_ac1_five_door_story_top_nav(monkeypatch):
    _key, html = _render(monkeypatch)
    assert 'class="story-top"' in html
    for door in ('href="/cockpit/"', 'href="/data/"', 'href="/coaching/"', 'href="/protocols/"', 'href="/story/"'):
        assert door in html, door
    # the story door is the current one (the post lives under it)
    assert 'href="/story/" aria-current="page"' in html


def test_ac1_legacy_chrome_removed(monkeypatch):
    _key, html = _render(monkeypatch)
    for legacy in ('class="nav__link"', 'class="nav__brand"', 'href="/#experiment"', 'href="/platform/"', 'class="footer"', "base.css"):
        assert legacy not in html, legacy


# ── AC2: og:image is the editorial cover, with a graceful fallback ────────────


def test_ac2_og_image_is_editorial_cover(monkeypatch):
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-04.jpg", "image_credit": "Unsplash / X"}
    _key, html = _render(monkeypatch, cur_image=cover)
    assert f'<meta property="og:image" content="{cover["image_url"]}">' in html
    assert f'<meta name="twitter:image" content="{cover["image_url"]}">' in html
    # the cover also renders in the header art with its credit
    assert cover["image_url"] in html and cover["image_credit"] in html


def test_ac2_og_image_falls_back_when_no_cover(monkeypatch):
    _key, html = _render(monkeypatch)  # editorial disabled → no cover
    assert '<meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">' in html


# ── AC3: canonical + structured-data point at the un-redirected /journal/ URL ─


def test_ac3_canonical_and_structured_data_use_journal_path(monkeypatch):
    _key, html = _render(monkeypatch)
    # 2026-07-01 is the 2nd installment by date → sequential index week-02
    canon = "https://averagejoematt.com/journal/posts/week-02/"
    assert f'<link rel="canonical" href="{canon}">' in html
    assert f'"@id": "{canon}"' in html
    # the retired path must be gone everywhere in the document
    assert "/chronicle/posts/" not in html


# ── AC4: the end-of-read subscribe CTA ────────────────────────────────────────


def test_ac4_subscribe_cta_present(monkeypatch):
    _key, html = _render(monkeypatch)
    assert 'class="post-cta"' in html
    assert 'href="/subscribe/"' in html
    # the footer also carries a follow-by-email link (site-foot)
    assert 'class="site-foot"' in html


# ── the key still targets the sequential post path ────────────────────────────


def test_post_key_is_sequential_week_path(monkeypatch):
    key, _html = _render(monkeypatch)
    assert key == "generated/journal/posts/week-02/index.html"


# ── #1803: the cover image must land in posts.json on a FIRST-EVER publish ────
# Root cause: wednesday_chronicle_lambda synthesizes a placeholder dict for
# all_installments when the installment isn't in DDB yet (first publish of a new
# date). publish_to_journal's manifest loop decides "is this the post being
# published right now" (and therefore gets the freshly-fetched cur_image) via
# sk == f"DATE#{date_str}" (ac753774, tie-safe same-date ordering). The
# synthesized dict never set sk, so the freshly-fetched image never reached the
# manifest even though the post's own HTML/og:image rendered it fine.


def _publish_and_get_manifest_entry(monkeypatch, installments, cur_image, date_str="2026-07-01"):
    """Call publish_to_journal like _render does, but return the parsed posts.json
    manifest entry for date_str instead of the HTML (#1803 needs the manifest,
    not the post page, since the bug is manifest-only)."""
    import json as _json

    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: True)
    monkeypatch.setattr(editorial_image, "fetch_and_store", lambda *a, **k: cur_image)
    _post_key, _html, posts_json_str = chron.publish_to_journal(
        title="The weight of a steady week",
        stats_line="Weight 298 lb · Recovery 64% · 5 workouts",
        body_html=_BODY,
        week_num=1,
        date_str=date_str,
        all_installments=installments,
        write_to_s3=False,
    )
    manifest = _json.loads(posts_json_str)
    return next(p for p in manifest["posts"] if p["date"] == date_str)


def test_1803_cover_image_lands_on_first_ever_publish_with_sk_set(monkeypatch):
    """The FIXED shape: the synthesized installment carries sk (as
    wednesday_chronicle_lambda now stamps it) — the manifest entry for that date
    must carry the freshly-fetched cover, not an empty image_url."""
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-01.jpg", "image_credit": "Unsplash / Y"}
    installment = {
        "title": "The weight of a steady week",
        "week_number": 1,
        "date": "2026-07-01",
        "sk": "DATE#2026-07-01",  # the #1803 fix
        "stats_line": "Weight 298 lb",
        "word_count": 10,
        "content_markdown": "It was a quiet week.",
        "has_board_interview": False,
    }
    entry = _publish_and_get_manifest_entry(monkeypatch, [installment], cover)
    assert entry["image_url"] == cover["image_url"]
    assert entry["image_credit"] == cover["image_credit"]


def test_1803_missing_sk_reproduces_the_pre_fix_bug(monkeypatch):
    """Regression pin: WITHOUT sk (the pre-fix synthesized shape), the manifest
    entry's image_url stays empty even though a fresh cover was fetched — this
    reproduces the exact #1803 bug and guards against silently re-dropping the
    sk stamp from wednesday_chronicle_lambda's synthesis dicts."""
    cover = {"image_url": "https://averagejoematt.com/generated/editorial/chronicle/week-01.jpg", "image_credit": "Unsplash / Y"}
    installment = {
        "title": "The weight of a steady week",
        "week_number": 1,
        "date": "2026-07-01",
        # no "sk" key — the pre-fix shape
        "stats_line": "Weight 298 lb",
        "word_count": 10,
        "content_markdown": "It was a quiet week.",
        "has_board_interview": False,
    }
    entry = _publish_and_get_manifest_entry(monkeypatch, [installment], cover)
    assert entry["image_url"] == ""


# ── #4191: the write-up opens on its first sentence; the numbers travel as a field ──
#
# Fixture = the live 2026-09-22 installment as stored: content_markdown is the whole
# ENVELOPE (quoted title, blank, bracketed machine header, blank, body). posts.json's
# `excerpt` used to be that envelope truncated, so /story/ and the home teaser opened on
# `"The Silence and the Signal" [Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0
# days]`. The `stats_line` FIELD is the card engine's and v7_week.js's source and stays
# byte-exact; only the prose derivation changes.

_LIVE_TITLE = "The Silence and the Signal"
_LIVE_STATS = "Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days"
_LIVE_FIRST_SENTENCE = (
    "On Monday afternoon, Matthew logged what the platform’s daily brief called the biggest training day of the experiment."
)
_LIVE_ENVELOPE = f'"{_LIVE_TITLE}"\n\n[{_LIVE_STATS}]\n\n{_LIVE_FIRST_SENTENCE} A second sentence follows it.'
_LIVE_STATS_ROW = "315.0 lb that week · the engine's week score 74"  # the literal tests/js/chronicle_text_4191.test.mjs pins


def _live_installment():
    return {
        "title": _LIVE_TITLE,
        "week_number": 3,
        "date": "2026-09-22",
        "sk": "DATE#2026-09-22",
        "stats_line": _LIVE_STATS,
        "word_count": 1114,
        "content_markdown": _LIVE_ENVELOPE,
        "has_board_interview": True,
    }


def _publish_live(monkeypatch):
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: False)
    return chron.publish_to_journal(
        title=_LIVE_TITLE,
        stats_line=_LIVE_STATS,
        body_html=f"<p>{_LIVE_FIRST_SENTENCE}</p>",
        week_num=3,
        date_str="2026-09-22",
        all_installments=[_live_installment()],
        write_to_s3=False,
    )


def test_4191_manifest_excerpt_opens_on_the_first_sentence_and_the_field_stays_exact(monkeypatch):
    import json as _json

    _key, _html, posts_json_str = _publish_live(monkeypatch)
    entry = next(p for p in _json.loads(posts_json_str)["posts"] if p["date"] == "2026-09-22")
    assert entry["excerpt"].startswith("On Monday afternoon"), entry["excerpt"][:80]
    assert "[Weight:" not in entry["excerpt"]
    assert "T0 Streak" not in entry["excerpt"]
    assert _LIVE_TITLE not in entry["excerpt"]  # the title has its own field; the excerpt is prose
    # The machine line still travels — as the FIELD the card engine + v7_week.js parse, unchanged.
    assert entry["stats_line"] == _LIVE_STATS
    assert entry["title"] == _LIVE_TITLE


def test_4191_mutation_control_without_the_strip_the_bracket_reaches_the_manifest(monkeypatch):
    """The strip is load-bearing: with body_markdown made an identity, the pre-fix excerpt
    (the truncated envelope) comes back — so the test above cannot pass vacuously."""
    import json as _json

    from content import chronicle_schema

    monkeypatch.setattr(chronicle_schema, "body_markdown", lambda md, title="": md)
    _key, _html, posts_json_str = _publish_live(monkeypatch)
    entry = next(p for p in _json.loads(posts_json_str)["posts"] if p["date"] == "2026-09-22")
    assert "[Weight:" in entry["excerpt"]
    assert entry["excerpt"].startswith(f'"{_LIVE_TITLE}"')


def test_4191_post_dek_and_share_description_read_as_words_never_the_machine_line(monkeypatch):
    _key, html, _posts = _publish_live(monkeypatch)
    assert f'<div class="post-header__stats">{_LIVE_STATS_ROW}</div>' in html
    assert f'property="og:description" content="{_LIVE_STATS_ROW}"' in html
    assert f'name="twitter:description" content="{_LIVE_STATS_ROW}"' in html
    assert "T0 Streak" not in html
    assert "[Weight:" not in html
    assert _LIVE_FIRST_SENTENCE in html  # the served prose is untouched — a format fix, not a rewrite


def test_4191_stats_row_text_is_the_byte_twin_of_chronicle_text_js():
    """The Python dek and the JS statsRow (story.js / dispatches.js) must print the same
    words for the same field — pinned by literal against the JS test's own fixtures."""
    from content import chronicle_schema as cs

    assert cs.stats_row_text(_LIVE_STATS) == _LIVE_STATS_ROW
    assert cs.stats_row_text("[Weight: 300 lbs | Sleep: 7.1 h]") == "300 lb that week · Sleep: 7.1 h"
    assert cs.stats_row_text("") == ""
    assert cs.stats_row_text(None) == ""
    # a pre-genesis dek's prologue stamp (chronicle_render.display_stats_line) rides through verbatim
    assert cs.stats_row_text("Weight: — lbs | Prologue — the instrumented weeks before Day 1") == (
        "Weight: — lbs · Prologue — the instrumented weeks before Day 1"
    )
    js_test = open(os.path.join(_REPO, "tests", "js", "chronicle_text_4191.test.mjs"), encoding="utf-8").read()
    assert _LIVE_STATS_ROW in js_test
    assert "300 lb that week · Sleep: 7.1 h" in js_test


def test_4191_body_markdown_strips_only_the_envelope_head():
    from content import chronicle_schema as cs

    # the live envelope, with and without the title known
    assert cs.body_markdown(_LIVE_ENVELOPE, _LIVE_TITLE).startswith("On Monday afternoon")
    assert cs.body_markdown(_LIVE_ENVELOPE).startswith("On Monday afternoon")
    # a quoted first line that is NOT the title, with no header after it, is prose and stays
    assert cs.body_markdown('"Not the title"\n\nBody.', _LIVE_TITLE) == '"Not the title"\n\nBody.'
    # a bracketed line deep in the body is prose too — only the HEAD is a header
    deep = "First sentence.\n\n[an aside in brackets]\n\nMore."
    assert cs.body_markdown(deep, "T") == deep
    # the old assembled lead-in header (# heading / *By …* / ---) is stripped the same way
    assert cs.body_markdown("# The Night Before\n\n*By Elena Voss*\n\n---\n\nThe habit tracker logged.") == "The habit tracker logged."
    assert cs.body_markdown("") == ""
    assert cs.body_markdown(None) == ""


# ── #4363: the narrator is disclosed on the post page, and has no invented career ──
#
# The live week-01 paragraph verbatim — the specimen the detector must trip on.
_WEEK01_CREDITS = (
    "My name is Elena Voss. I'm a freelance journalist based in Brooklyn, and for the past decade I've made a career "
    "out of embedding myself in worlds I don't fully understand and staying long enough to find the story underneath "
    "the story. I spent six months in a longevity clinic in Marin for a piece in Harper's. I followed a competitive "
    "eater through three Nathan's qualifiers for The Ringer. I profiled a man who hadn't slept more than four hours a "
    "night in six years for Wired, and what I found had almost nothing to do with sleep."
)


def _load_deploy(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, "deploy", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_4363_every_post_template_carries_the_ai_narrator_note(monkeypatch):
    """Both writers of a chronicle post page — the weekly Lambda and the restart re-renderer —
    render the ONE shared narrator note in the post header, with its style rule."""
    from content import chronicle_schema as cs

    _key, lambda_html = _render(monkeypatch)
    leadin_html = _load_deploy("restart_leadin_pages").render_post_html(
        "Before the Numbers", "Prologue | Before Day 1", "<p>Body.</p>", "Prologue · Part I", "2026-08-31", 1
    )
    for name, html in (("chronicle_render", lambda_html), ("restart_leadin_pages", leadin_html)):
        assert cs.AI_NARRATOR_NOTE_HTML in html, name
        assert cs.AI_NARRATOR_NOTE_CSS in html, name
        header = html[html.find('class="post-header"') : html.find('class="post-body"')]
        assert "data-ai-narrator" in header and "AI narrator" in header, f"{name}: the note must sit in the post header"


def test_4363_credit_detector_trips_on_the_week01_paragraph_and_the_live_gate_surfaces_it():
    import chronicle_prompt
    from content import chronicle_schema as cs

    found = cs.real_publication_credit_findings(_WEEK01_CREDITS)
    assert sorted(f["publication"] for f in found) == ["Harper's", "Ringer", "Wired"], found
    assert cs.real_publication_credit_findings(f"<p>{_WEEK01_CREDITS.replace(chr(39), '&rsquo;')}</p>")  # stored html scans too
    gate = chronicle_prompt.installment_grounding_findings("prompt", "packet", _WEEK01_CREDITS)
    assert [f for f in gate if f["type"] == "real_publication_credit"], gate
    # Names without a career claim, and ordinary words that collide with a masthead, are prose.
    for clean in (
        "For the first time in years, he slept eight hours. Outside, the rain kept on.",
        "He listens to a podcast from The Ringer on the treadmill.",
        "It was time to work.",
    ):
        assert cs.real_publication_credit_findings(clean) == [], clean


def test_4363_mutation_control_without_the_binding_the_week01_paragraph_passes():
    """The detector is load-bearing: with the publication binding neutralised, the week-01
    paragraph comes back clean — so the test above cannot pass vacuously."""
    import re

    from content import chronicle_schema as cs

    real = cs._CREDIT_BINDING_RE
    try:
        cs._CREDIT_BINDING_RE = re.compile(r"(?!x)x(?P<pub>)")
        assert cs.real_publication_credit_findings(_WEEK01_CREDITS) == []
    finally:
        cs._CREDIT_BINDING_RE = real
    assert cs.real_publication_credit_findings(_WEEK01_CREDITS)


def test_4363_no_persona_or_prompt_claims_a_real_publication_credit():
    """Guard the SET: every persona the board config defines (coaches, the narrator, the
    editor, board members), Margaret's in-code fallback, and both Elena prompts. Margaret's
    voice read '22 years at the Times, before that the Atlantic' — the same invented-career
    pattern, one hop from her signed editor's notes."""
    import json

    from content import chronicle_schema as cs

    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}/{i}")
        elif isinstance(node, str):
            offenders.extend((path, f["claim"]) for f in cs.real_publication_credit_findings(node))

    with open(os.path.join(_REPO, "config", "board_of_directors.json"), encoding="utf-8") as fh:
        walk(json.load(fh).get("members", {}), "board_of_directors.json:members")
    from ai import margaret_editor_pass

    walk(margaret_editor_pass._FALLBACK_NARRATOR, "margaret_editor_pass._FALLBACK_NARRATOR")
    for rel in ("lambdas/emails/chronicle_prompt.py", "lambdas/emails/wednesday_chronicle_lambda.py"):
        with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "NO INVENTED CAREER (#4363)" in src, f"{rel}: the prompt must forbid invented real-world credits"
        walk(src, rel)
    assert offenders == [], "\n".join(f"{p}: {c}" for p, c in offenders)


def test_4363_prologue_repair_drops_the_credits_adds_the_note_and_is_idempotent():
    from content import chronicle_schema as cs

    fix = _load_deploy("fix_prologue_part1_narrator_credits")
    page = (
        "<html><head><style>\n  .x { }\n  </style></head><body>"
        '<div class="post-header__series">The Measured Life &middot; Prologue · Part I &middot; By Elena Voss</div>'
        f"<h1>t</h1><p>I'm not making fun of him.</p><hr><p>{_WEEK01_CREDITS}</p><p>I pitched this series.</p></body></html>"
    )
    repaired = fix.repair_page(page)
    assert cs.real_publication_credit_findings(repaired) == []
    assert repaired.count("data-ai-narrator") == 1 and cs.AI_NARRATOR_NOTE_CSS in repaired
    assert "an AI" in repaired and "<p>I pitched this series.</p>" in repaired
    assert fix.repair_page(repaired) == repaired
    md = fix.rewrite_paragraph(f"Before.\n\n{_WEEK01_CREDITS}\n\nAfter.", html_entities=False)
    assert "&mdash;" not in md and cs.real_publication_credit_findings(md) == [] and md.endswith("\n\nAfter.")
