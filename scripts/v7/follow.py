"""scripts/v7/follow.py — the "Follow" page body (#4182, plan §2a row 9; Prototype C's Follow entry).

The page is the return: the ask in one line, the working double-opt-in form posting to the
existing subscribe door (`site/assets/js/subscribe_page.js`, reused as it is — the ids it
reads are the ids poured here), the honest count in words, what a subscriber gets and
when, the address as selectable text, the repo, and the dated return line. Every date is
poured by `site/assets/js/v7_follow.js` from the served feeds; this module writes only the
skeleton and the honest not-yet-loaded state a no-JS reader sees.

The cadence promise is NOT typed here. It is `subscriber_cadence.promise_sentence()` —
the one derivation from the senders' live crons that `tests/test_subscriber_cadence_promise_3564.py`
pins byte for byte on every subscriber surface — rendered at build time, so the preview
page cannot carry a cadence the senders do not keep. (That sentence names the Chronicle
by its product name; the vocabulary ledger carries the one page it costs, dated.)

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


def body(base: str) -> str:
    """The inner HTML of `<main>` for /subscribe/."""
    promise = html.escape(subscriber_cadence.promise_sentence(), quote=True)
    return "    <h1>Follow the experiment.</h1>\n" f'    <p class="fo-promise" data-src="subscriber_cadence.promise_sentence">{promise}</p>\n' + _entry(
        "fo-form", "By email", _form(base), _static_margin("§", "by", "email")
    ) + _entry(
        "fo-get",
        "What you’d get",
        '<p class="fo-small" id="fo-writeup">The numbers every Sunday; the write-up every Wednesday.</p>\n'
        '        <p class="fo-small fo-pending" id="fo-weighin" data-src="api_journey.journey.last_weighin_date + 1 day">Not loaded yet.</p>',
    ) + _entry(
        "fo-write",
        "Write to him",
        f'<p class="fo-small">The address, to copy: <span class="fo-addr">{EMAIL}</span></p>\n'
        f'        <p class="fo-note">The code, in full: <a href="{REPO_URL}" rel="noopener">github.com/averagejoematt/life-platform</a></p>',
        _static_margin("§", "write", "to him"),
    ) + _entry(
        "fo-return",
        "Come back",
        '<p class="fo-return fo-pending" id="fo-return-line" data-src="api_content_cadence.chronicle.next_date">Not loaded yet.</p>',
    )
