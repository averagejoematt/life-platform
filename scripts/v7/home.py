"""scripts/v7/home.py — the v7 Home body: the log's front page (#4182, Prototype C screen I).

THE FRAME. A logbook kept in public: every block is a dated entry with the day in the
margin. Home is "the case so far", in the design source's order — the fold (the honest
day-1 photograph beside the number, its day and range, and the this-week line), the lead
sentence (day N of an experiment run in public, with the day-only branches), the alive
line (data through · the coaches' checked calls K of N · next write-up), every weigh-in
so far, in his words, is he okay this week, also on the record, how it works, what
resolves next, follow.

WHAT IS STATIC. The headings, the entry order, the day-1 photograph (#3761 — the owner
chose it and said yes to publishing it on 2026-09-26; re-saved with no EXIF) with its alt
text, and one "loading the numbers" line per slot. The photo's caption is poured by JS
(`photoCaption`: the date from `journey.started_date`, the weight from
`journey.start_weight_lbs`). Every number, date and served sentence is poured by
`site/assets/js/v7_home.js` from the served endpoints — nothing here is a number, so the
static page can never go stale, and it reads correctly with scripts off (the slots say
plainly that the numbers load from the site's served data).

OWNER RULING (2026-09-26, 14:00 PT). No reference to earlier starts, attempts, cycles or
resets anywhere on the page; the frame is the experiment and the day. The static copy
below carries none of those words, and `tests/js/v7_home.test.mjs` holds the rendered
copy to the same rule.

The `<!-- home-proof:start/end -->` pair is the cut-over anchor for
`scripts/v4_build_home_proof.py` (plan §3c): empty in the preview, filled with the
`<noscript>` proof bake when this template is poured at `/`.
"""

from __future__ import annotations

CSS = "/assets/css/v7_home.css"
JS = "/assets/js/v7_home.js"

# The day-1 photograph (#3761): two widths, the reader's browser picks by the frame's size.
DAY1_PHOTO = "/assets/images/photo-2026-09-06-day1"
DAY1_ALT = "Matthew on day 1, Sunday September 6, front view"


def photo_img(stem: str, alt: str, sizes: str, loading: str = "eager") -> str:
    """One photograph as a responsive <img>: the 480-px `-sm` file and the 1200-px file (3:4, 900×1200)."""
    return (
        f'<img src="{stem}-sm.jpg" srcset="{stem}-sm.jpg 360w, {stem}.jpg 900w" sizes="{sizes}"'
        f' width="360" height="480" alt="{alt}" loading="{loading}" decoding="async">'
    )


_PENDING = '<p class="v7h-pending">Loading the numbers — this line fills from the site’s served data.</p>'


def _entry(slot: str, heading: str | None, inner: str, margin_kind: str = "date") -> str:
    """One dated entry: the margin (JS writes the day), the body."""
    h = f"<h2>{heading}</h2>" if heading else ""
    return (
        f'    <div class="v7h-entry" id="v7h-{slot}">\n'
        f'      <div class="v7h-m" data-margin="{margin_kind}"><span class="v7h-d">—</span><span class="v7h-mo"></span><span class="v7h-w"></span></div>\n'
        f'      <div class="v7h-body">{h}{inner}</div>\n'
        "    </div>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every link on Home is off-site (the repo, mail); no page link, by the reach rule
    fold = (
        '<div class="v7h-fold">'
        f'<figure class="v7h-photo" id="v7h-photo">{photo_img(DAY1_PHOTO, DAY1_ALT, "(min-width: 601px) 150px, 116px")}'
        '<figcaption class="v7h-cap" id="v7h-photo-cap">Day one, front view.</figcaption></figure>'
        f'<div id="v7h-number">{_PENDING}</div>'
        "</div>"
        f'<div id="v7h-lead">{_PENDING}</div>'
        f'<div id="v7h-alive">{_PENDING}</div>'
    )
    return (
        '    <h1 class="v7h-sr">The log — the case so far</h1>\n'
        "    <!-- home-proof:start -->\n"
        "    <!-- home-proof:end -->\n"
        '    <noscript><p class="v7h-noscript">Every number on this page is drawn from the site’s served data when scripts run. With scripts off the entries below name what each one holds, not the numbers.</p></noscript>\n'
        + _entry("fold", None, fold)
        + _entry("weighins", "Every weigh-in so far", f'<div id="v7h-weighins-body">{_PENDING}</div>', "span")
        + _entry("words", "In his words", f'<div id="v7h-words-body">{_PENDING}</div>')
        + _entry("okay", "Is he okay this week?", f'<div id="v7h-okay-body">{_PENDING}</div>')
        + _entry("record", "Also on the record", f'<div id="v7h-record-body">{_PENDING}</div>')
        + _entry("how", "How it works", f'<div id="v7h-how-body">{_PENDING}</div>', "how")
        + _entry("next", "What resolves next", f'<div id="v7h-next-body">{_PENDING}</div>')
        + _entry("follow", "Follow", f'<div id="v7h-follow-body">{_PENDING}</div>', "next")
    )
