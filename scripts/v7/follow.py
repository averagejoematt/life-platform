"""scripts/v7/follow.py — the "Follow" page body (#4182, plan §2a row 9; Prototype C's Follow entry).

The page is the return: the ask in one line, the working double-opt-in form posting to the
existing subscribe door (`site/assets/js/subscribe_page.js`, reused as it is — the ids it
reads are the ids poured here), the honest count in words, what a subscriber gets and
when, the address as selectable text, the repo, and the dated return line. Every date is
poured by `site/assets/js/v7_follow.js` from the served feeds; this module writes only the
skeleton and the honest not-yet-loaded state a no-JS reader sees.

The cadence promise is NOT typed here. Every weekday and the count come from
`common.subscriber_cadence` — the one derivation from the senders' live crons that
`tests/test_subscriber_cadence_promise_3564.py` pins byte for byte on every subscriber
surface. The fold carries Prototype C's line in reader words, derived from the same
registry ("The numbers every Sunday; the write-up every Wednesday." + the fallback day and
the count); the exact `promise_sentence()` sits under "The exact terms", because the
nightly `qa_check_subscriber_promise` requires those bytes on the live /subscribe/ at the
cut-over and the sentence names the Chronicle by its product name (the vocabulary ledger
carries the one page it costs, dated). A driver finding on the live /next/subscribe/
(2026-09-26 19:56 PT) moved the long sentence off the fold: "Chronicle" and "Weekly
Signal" are brand words a reader meets first.

No authored copy here counts anything before day 1 or names a restart (the owner's ruling
on Prototype C, 2026-09-26), and the seven-network follow list is gone (CONCEPT §8).
"""

from __future__ import annotations

import html
import os
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "lambdas")
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)

from common import subscriber_cadence  # noqa: E402 — the ONE cadence derivation (#3564)

CSS = "/assets/css/v7_follow.css"
JS = "/assets/js/v7_follow.js"

EMAIL = "matt@averagejoematt.com"
REPO_URL = "https://github.com/averagejoematt/life-platform"

_MAIL_ICON = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' '<use href="/assets/icons/icons.svg#i-mail"></use></svg>'
)


def _entry(anchor: str, heading: str, inner: str, margin: str = "") -> str:
    return (
        f'    <section class="fo-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="fo-m" data-margin>{margin}</div>\n'
        f'      <div class="fo-body">\n'
        f'        <h2 class="fo-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


# The JS-off sentence (R7 fix 9): the form and the dated lines need scripts; the address does not.
_NOSCRIPT = (
    '    <noscript><p class="fo-note">The dated lines on this page are drawn from the site’s served data when scripts run, '
    "and the form needs them too. With scripts off, the address below still works.</p></noscript>\n"
)


def _static_margin(d: str, mo: str, w: str) -> str:
    return f'<span class="d">{d}</span><span class="mo">{mo}</span><span class="w">{w}</span>'


def _form(base: str) -> str:
    # The ids are subscribe_page.js's contract: #form-block #success-block #email #submit-btn
    # #form-status #source-field #sub-count-line. The source is the page itself (the reader
    # is not asked here); the count line's static text is the same fallback the live page
    # shows when /api/sub_count cannot be read.
    return (
        '<div id="form-block">\n'
        '          <label class="fo-label" for="email">Email address</label>\n'
        '          <div class="fo-row">\n'
        '            <input type="email" class="fo-input" id="email" placeholder="your@email.com" autocomplete="email" aria-invalid="false">\n'
        '            <button class="fo-btn" id="submit-btn" type="button">Follow by email</button>\n'
        "          </div>\n"
        '          <input type="hidden" id="source-field" value="next-subscribe">\n'
        '          <p class="fo-status" id="form-status" role="status" aria-live="polite"></p>\n'
        '          <p class="fo-note">Double opt-in, unsubscribe anytime. <a href="/privacy/">Privacy</a></p>\n'
        '          <p class="fo-count" id="sub-count-line" data-src="api_sub_count.count">Be one of the first to follow the experiment.</p>\n'
        "        </div>\n"
        '        <div class="fo-success" id="success-block">\n'
        f'          <div class="si" aria-hidden="true">{_MAIL_ICON}</div>\n'
        '          <p class="st">Check your inbox</p>\n'
        f'          <p class="sb">Confirmation email sent. Click the link to confirm and you are in.<br><br><a href="{base}">← back to the experiment</a></p>\n'
        "        </div>"
    )


def cadence_lines() -> tuple[str, str, str]:
    """(the fold line, the rest of the terms, the exact derived sentence) — every weekday and the
    count read from `common.subscriber_cadence`'s sender registry, none typed here, so the fold
    moves when a sender's cron moves exactly as `promise_sentence()` does."""
    sc = subscriber_cadence
    signal = sc.weekday_name(sc.signal_weekday())
    writeup = sc.weekday_name(sc.chronicle_weekday())
    fallback = sc.weekday_name(sc.chronicle_autopublish_weekday())
    note = sc.weekday_name(sc.required_weekday(sc.sender("between-chronicle").cron))
    lead = f"The numbers every {signal}; the write-up every {writeup}."
    rest = (
        f"Or {fallback}, when Matthew has not read the draft by then; now and then a short note on {note} "
        f"when there is something new. Never more than {sc.weekly_count_word()} emails a week."
    )
    return lead, rest, sc.promise_sentence()


def body(base: str) -> str:
    """The inner HTML of `<main>` for /subscribe/."""
    lead, rest, exact = (html.escape(s, quote=True) for s in cadence_lines())
    return (
        (
            "    <h1>Follow the experiment.</h1>\n"
            f'    <p class="fo-promise" data-src="subscriber_cadence.{{signal_weekday,chronicle_weekday}}">{lead}</p>\n'
            # R7 fix 10: one dated served fact in the fold — the next write-up's day, under the promise
            # (below the form it sat behind the bottom bar at 390×844).
            '    <p class="fo-count fo-fold-next fo-pending" id="fo-fold-next" data-src="api_content_cadence.chronicle.next_date">Not loaded yet.</p>\n'
            f'    <p class="fo-small fo-terms" data-src="subscriber_cadence.{{chronicle_autopublish_weekday,weekly_count_word}}">{rest}</p>\n'
            '    <details class="fo-fold"><summary>The exact terms</summary>'
            f'<p class="fo-note" data-src="subscriber_cadence.promise_sentence">{exact}</p></details>\n' + _NOSCRIPT
        )
        + _entry("fo-form", "By email", _form(base), _static_margin("§", "by", "email"))
        + _entry(
            "fo-get",
            "What you’d get",
            '<p class="fo-small fo-pending" id="fo-writeup" data-src="api_content_cadence.chronicle.next_date">Not loaded yet.</p>\n'
            '        <p class="fo-small fo-pending" id="fo-weighin" data-src="api_journey.journey.last_weighin_date">Not loaded yet.</p>',
        )
        + _entry(
            "fo-write",
            "Write to him",
            f'<p class="fo-small">The address, to copy: <span class="fo-addr">{EMAIL}</span></p>\n'
            f'        <p class="fo-note">The code, in full: <a href="{REPO_URL}" rel="noopener">github.com/averagejoematt/life-platform</a></p>',
            _static_margin("§", "write", "to him"),
        )
        + _entry(
            "fo-return",
            "Come back",
            '<p class="fo-return fo-pending" id="fo-return-line" data-src="api_content_cadence.chronicle.next_date">Not loaded yet.</p>',
        )
    )
