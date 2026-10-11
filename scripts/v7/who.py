"""scripts/v7/who.py — the "Who he is" page body (#4182, plan §2a row 7; Prototype C screen V).

The page is the subject, in the first person: his own
paragraph (VERBATIM from the live about page's `ABOUT_FIRST` in site/assets/js/dispatches.js
— the site's one first-person page, by name; nothing here is rewritten), then the receipts
strip in one line, then the photographs — two, dated, in order (#3761; each re-saved with
no EXIF. OWNER RULING 2026-10-03: no shirtless photograph on any reader surface — the day-1
photograph is gone from the lead and from this list, and tests/test_site_chrome.py keeps
it gone) — then
the weigh-in line since the day it began, then how to check
(the repo, the same four plain sentences Home's "How it works" carries, the email address as
selectable text), then the dated return line. Every number is poured by
`site/assets/js/v7_who.js` from the served feeds — this module writes only the skeleton,
his words, and the honest not-yet-loaded state a no-JS reader sees.

OWNER RULING (2026-09-26). No reference to earlier starts, the attempt count, cycles or
resets anywhere on the page: it is about the man and this experiment, counted in days. No
authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page).
"""

from __future__ import annotations

CSS = "/assets/css/v7_who.css"
JS = "/assets/js/v7_who.js"

# The photographs (#3761), in order. Each: the file stem, its date (the file name carries it),
# the alt text, the words after the date in the caption, and the static caption a no-JS
# reader sees. v7_who.js pours the September captions with the day number computed from the
# served start date; April 2025 predates the experiment, so its caption is its own date.
PHOTOS = (
    (
        "/assets/images/photo-2025-04-before",
        "2025-04",
        "Matthew in April 2025, before the weight came back, sitting on a couch",
        "April 2025 — before the weight came back",
    ),
    ("/assets/images/photo-2026-09-24-gym", "2026-09-24", "Matthew in the gym on Thursday September 24, a mirror photo", "In the gym."),
)


def photo_img(stem: str, alt: str, sizes: str, loading: str = "eager") -> str:
    """One photograph as a responsive <img>: the 480-px `-sm` file and the 1200-px file (3:4, 900×1200)."""
    return (
        f'<img src="{stem}-sm.jpg" srcset="{stem}-sm.jpg 360w, {stem}.jpg 900w" sizes="{sizes}"'
        f' width="360" height="480" alt="{alt}" loading="{loading}" decoding="async">'
    )


def _photo_strip() -> str:
    figs = "".join(
        f'<figure class="who-shot">{photo_img(stem, alt, "(min-width: 601px) 180px, 30vw", "lazy")}'
        f'<figcaption class="who-cap" data-photo-date="{date}">{static}</figcaption></figure>'
        for stem, date, alt, static in PHOTOS
    )
    return f'<div class="who-shots">{figs}</div><p class="who-small" id="who-photo-next"></p>'


_PENDING = '<p class="who-note who-pending">Not loaded yet.</p>'

# His paragraph, byte-for-byte the live about page's ABOUT_FIRST (dispatches.js). Do not edit
# here — the about page is the source; a change lands there first and is copied verbatim.
FIRST_PERSON = (
    "I've spent two decades making complicated systems reliable and getting people to actually use them. "
    "In early 2026 I turned that same thinking on myself — not a challenge, not a 30-day hack, but a proper system: "
    "the wearables already on my body, an AI that reads the numbers back to me every morning, "
    "and the discipline to publish the down weeks too."
)

EMAIL = "matt@averagejoematt.com"
REPO_URL = "https://github.com/averagejoematt/life-platform"

# The two data-free sentences of Home's "How it works" paragraph, verbatim — the static
# fallback a no-JS reader sees; v7_who.js pours all four with the served counts.
HOW_STATIC = (
    "Every figure on this page is computed by code, not by an AI, and carries its date and its count. "
    "An AI drafts the weekly write-up and Matthew reviews it before it publishes."
)


def _entry(anchor: str, heading: str, inner: str = _PENDING, extra_class: str = "") -> str:
    cls = f"who-entry{(' ' + extra_class) if extra_class else ''}"
    return (
        f'    <section class="{cls}" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="who-m" data-margin></div>\n'
        f'      <div class="who-body">\n'
        f'        <h2 class="who-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /story/about/."""
    fold = (
        '<div class="who-fold-grid">'
        '<div class="who-words">'
        f'<p class="who-first">{FIRST_PERSON}</p>'
        '<p class="who-sig">Matthew, in his own words.</p>'
        "</div></div>"
        f'<p class="who-receipts" id="who-receipts"><a href="{REPO_URL}" rel="noopener">the code</a></p>'
    )
    check = (
        f'<p class="who-how" id="who-how">{HOW_STATIC}</p>'
        f'<p class="who-small">The code, in full: <a href="{REPO_URL}" rel="noopener">github.com/averagejoematt/life-platform</a>.</p>'
        f'<p class="who-small">Write to him: <span class="who-mail">{EMAIL}</span></p>'
    )
    return (
        "    <h1>Who he is</h1>\n"
        '    <p class="v7-job">In his own words, with the photo and the day count.</p>\n'
        # R7 fix 9: the JS-off sentence. His paragraph and the photographs are static; the counts are not.
        '    <noscript><p class="who-small">His paragraph and the photographs are on this page as written. The day count and the numbers are drawn '
        "from the site’s served data when scripts run; with scripts off they are not shown.</p></noscript>\n"
        + _entry("who-fold", "In his own words", fold, "who-fold")
        + _entry("who-photos", "The photographs", _photo_strip())
        + _entry("who-since", 'Since <span id="who-since-day" data-src="api_journey.journey.started_date">the day it began</span>')
        + _entry("who-check", "How to check", check)
        + '    <p class="who-return" id="who-return" data-src="api_content_cadence.chronicle.next_date"></p>\n'
    )
