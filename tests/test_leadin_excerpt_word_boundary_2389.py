"""#2389 — restart lead-in excerpts must end at a word boundary or with an ellipsis.

The standing excerpt writer (chronicle_render.py:~650) was fixed by #1284 to use the
ONE shared word-boundary helper (`common.text_utils.truncate_at_word`, #1224), but the
cycle-12 carried-forward lead-ins were written by deploy/restart_leadin_pages.py, whose
manifest build used a raw `[:300]` slice — every live lead-in excerpt was exactly 300
chars and hard-cut mid-word ("…before any data exists t") on the story door.

Mutation-proof: restoring `body_markdown_from_record(item)[:300].strip()` in
`excerpt_from_record` fails `test_excerpt_mid_word_cut_ends_at_boundary_with_ellipsis`
(the fixture's 300th char lands mid-word), and reintroducing a raw `[:300]` slice
anywhere in the module fails the source guard.
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import restart_leadin_pages as rlp  # noqa: E402
from common.text_utils import ELLIPSIS  # noqa: E402


def _record(body_markdown: str) -> dict:
    # Raw-installment header format that body_markdown_from_record strips.
    return {"content_markdown": '"A Title"\n[stats line]\n\n' + body_markdown}


def _mid_word_body() -> str:
    """Prose whose 300th character lands mid-word (the reported live failure mode)."""
    # 60 x "seven49 " = 480 chars of 8-char tokens; char index 299 (the 300th char)
    # falls inside a token, never on whitespace: 300 % 8 == 4 → mid-"seven49".
    body = "seven49 " * 60
    assert body[299] != " " and body[298] != " "  # the slice point is mid-word
    return body


def test_excerpt_mid_word_cut_ends_at_boundary_with_ellipsis():
    excerpt = rlp.excerpt_from_record(_record(_mid_word_body()))
    assert excerpt.endswith(ELLIPSIS), f"truncated excerpt must end with ellipsis, got: ...{excerpt[-20:]!r}"
    # The visible text before the ellipsis ends on a complete word, not a fragment.
    visible = excerpt[: -len(ELLIPSIS)]
    assert visible == visible.rstrip()
    assert visible.split()[-1] == "seven49", "cut must land on a word boundary, not mid-word"
    # And it actually truncated (limit honored).
    assert len(excerpt) <= 300 + len(ELLIPSIS)


def test_excerpt_short_body_untouched_no_ellipsis():
    excerpt = rlp.excerpt_from_record(_record("short prose, nothing cut."))
    assert excerpt == "short prose, nothing cut."


def test_no_raw_300_slice_in_module_source():
    """Source guard: the raw slice idiom must not return anywhere in the builder."""
    src_path = os.path.join(_REPO, "deploy", "restart_leadin_pages.py")
    with open(src_path) as f:
        src = f.read()
    assert not re.search(r"\[\s*:\s*300\s*\]", src), "raw [:300] slice reintroduced — use truncate_at_word (#1224/#2389)"
    assert "truncate_at_word" in src


# ── #4191: one derivation for both manifest writers ────────────────────────────────

_LIVE_TITLE = "The Silence and the Signal"
_LIVE_STATS = "Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days"
_LIVE_ENVELOPE = f'"{_LIVE_TITLE}"\n\n[{_LIVE_STATS}]\n\nOn Monday afternoon, Matthew logged the biggest training day of the experiment.'


def test_4191_excerpt_shares_the_standing_writers_derivation():
    """The two manifest builders had diverged — this script stripped the envelope head, the
    Lambda writer did not, and the live excerpts opened on the bracket. Both now call the
    ONE helper, so the re-render and the next publish derive the same excerpt."""
    import inspect

    from content import chronicle_schema

    rec = {"content_markdown": _LIVE_ENVELOPE, "title": _LIVE_TITLE}
    excerpt = rlp.excerpt_from_record(rec)
    assert excerpt.startswith("On Monday afternoon"), excerpt[:60]
    assert "[Weight:" not in excerpt
    assert excerpt == rlp.excerpt_from_record.__globals__["truncate_at_word"](
        chronicle_schema.body_markdown(_LIVE_ENVELOPE, _LIVE_TITLE), 300
    )
    assert "chronicle_schema.body_markdown(" in inspect.getsource(rlp.body_markdown_from_record)


def test_4191_re_rendered_page_dek_reads_as_words():
    page = rlp.render_post_html(_LIVE_TITLE, _LIVE_STATS, "<p>Body.</p>", "Week 3", "2026-09-22", 6)
    assert '<div class="post-header__stats">315.0 lb that week · the engine\'s week score 74</div>' in page
    assert 'property="og:description" content="315.0 lb that week · the engine\'s week score 74"' in page
    assert "T0 Streak" not in page
    assert "[Weight:" not in page
