"""common/reader_email.py — the ONE envelope for mail sent to readers (#6151).

Every reader send (the Weekly Signal, the chronicle installment, the between-chronicle note, the
day-2 onboarding bridge, the double-opt-in confirmation and the welcome) builds its body itself;
this module owns what a mail client needs AROUND that body, so five senders cannot drift into five
copies of it:

  * ``head_meta()`` — the ``color-scheme`` declaration. The reader templates are dark-only; without
    the declaration Apple Mail / iOS / Outlook auto-invert them in light mode, and the inversion is
    what made the old footers unreadable (``content/html_builder.py`` makes the same call for the
    owner's brief).
  * ``preheader_html(text)`` — the inbox-preview line, hidden in the rendered body.
  * ``FOOTER_TEXT`` — a footer colour that meets WCAG 4.5:1 on the templates' ``#0D1117`` /
    ``#161b22`` backgrounds (6.15:1 / 5.62:1). The old ``#30363d`` was 1.55:1 and ``#484f58`` 2.28:1.
  * ``html_to_text(html)`` — the plain-text alternative, derived from the SAME (already
    journal-silence-scrubbed) HTML, so the two parts can never say different things.
  * ``list_unsubscribe_headers(url)`` — RFC 2369 ``List-Unsubscribe`` with the subscriber's existing
    signed link, plus RFC 8058 ``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` ONLY when the link
    is the tokenized ``/api/subscribe?action=unsubscribe&t=`` URL: ``email_subscriber_lambda`` resolves
    ``action=unsubscribe`` before it looks at the HTTP method, so a one-click POST to that URL performs
    the same idempotent, token-verified anonymize-at-unsubscribe as the GET. The ``/privacy/`` fallback
    (signing key unavailable) is a page, not an endpoint — it gets the plain header only.
  * ``simple_content(...)`` — the SESv2 ``Content.Simple`` block with both body parts and the headers
    (``Simple.Headers`` is the SESv2 field; the IAM action is still ``ses:SendEmail``, no raw MIME).

Nothing here sends, reads AWS, or decides who is mailed.
"""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from typing import Optional

#: Footer text/link colour on the dark reader templates (WCAG AA 4.5:1 — see the module docstring).
FOOTER_TEXT = "#8b949e"

ONE_CLICK_VALUE = "List-Unsubscribe=One-Click"
#: The tokenized unsubscribe endpoint (common.unsubscribe_token.build_unsub_url) — the only URL that honours a POST.
_ONE_CLICK_URL = re.compile(r"^https://[^/\s]+/api/subscribe\?action=unsubscribe&t=[A-Za-z0-9.]+$")

_PREHEADER_MAX = 140
#: Zero-width padding after the preheader keeps clients from pulling body text into the preview line.
_PREHEADER_PAD = "&#8199;&#847;" * 40


def head_meta() -> str:
    """The ``<head>`` lines every reader template carries (charset, viewport, dark colour scheme)."""
    return (
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">'
        "<style>:root{color-scheme:dark;supported-color-schemes:dark;}</style>"
    )


def preheader_html(text: str) -> str:
    """The hidden inbox-preview line. Escaped; clipped at a word to ``_PREHEADER_MAX`` characters."""
    text = " ".join(str(text or "").split())
    if len(text) > _PREHEADER_MAX:
        text = text[:_PREHEADER_MAX].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return (
        '<div data-preheader="1" style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
        'font-size:1px;line-height:1px;color:transparent;opacity:0;">'
        f"{_html.escape(text)}{_PREHEADER_PAD}</div>"
    )


class _TextExtractor(HTMLParser):
    """HTML -> readable plain text: block elements break lines, a link keeps its URL, and anything
    hidden (``<head>``, ``<style>``, ``<title>``, the preheader) is dropped."""

    _BLOCK = frozenset({"p", "div", "h1", "h2", "h3", "h4", "tr", "table", "li", "ul", "ol", "blockquote"})
    _SKIP = frozenset({"head", "style", "title", "script"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0
        self._hidden_stack: list[bool] = []
        self._href: list[Optional[str]] = []

    def _hidden(self) -> bool:
        return self._skip_depth > 0 or any(self._hidden_stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag in ("div", "span", "p", "td", "table"):
            style = (a.get("style") or "").replace(" ", "").lower()
            self._hidden_stack.append("display:none" in style or "data-preheader" in a)
        if self._hidden():
            return
        if tag == "br":
            self.out.append("\n")
        elif tag in self._BLOCK:
            self.out.append("\n\n" if tag in ("p", "h1", "h2", "h3", "h4", "table") else "\n")
        elif tag == "td":
            self.out.append(" ")
        elif tag == "a":
            self._href.append(a.get("href"))

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        was_hidden = self._hidden()
        if tag in ("div", "span", "p", "td", "table") and self._hidden_stack:
            self._hidden_stack.pop()
        if was_hidden:
            return
        if tag == "a" and self._href:
            href = self._href.pop()
            if href and href.startswith(("http://", "https://", "mailto:")):
                self.out.append(f" ({href})")
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._hidden():
            self.out.append(data)


def html_to_text(html: str) -> str:
    """The plain-text alternative of a reader email's HTML."""
    parser = _TextExtractor()
    parser.feed(str(html or ""))
    parser.close()
    raw = "".join(parser.out).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def one_click_capable(unsub_url: str) -> bool:
    """True when ``unsub_url`` is the signed endpoint that performs the unsubscribe on a POST."""
    return bool(_ONE_CLICK_URL.match(str(unsub_url or "")))


def list_unsubscribe_headers(unsub_url: str) -> list:
    """SESv2 ``Headers`` entries for one subscriber's unsubscribe link (empty when there is no link)."""
    if not unsub_url:
        return []
    headers = [{"Name": "List-Unsubscribe", "Value": f"<{unsub_url}>"}]
    if one_click_capable(unsub_url):
        headers.append({"Name": "List-Unsubscribe-Post", "Value": ONE_CLICK_VALUE})
    return headers


def simple_content(subject: str, *, html: Optional[str] = None, text: Optional[str] = None, unsub_url: str = "") -> dict:
    """The SESv2 ``Content`` for one reader send: subject, the HTML part (when given), the text part
    (derived from the HTML when not given) and the List-Unsubscribe headers."""
    body: dict = {}
    if html is not None:
        body["Html"] = {"Data": html, "Charset": "UTF-8"}
        if text is None:
            text = html_to_text(html)
    if text is not None:
        body["Text"] = {"Data": text, "Charset": "UTF-8"}
    simple: dict = {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body}
    headers = list_unsubscribe_headers(unsub_url)
    if headers:
        simple["Headers"] = headers
    return {"Simple": simple}
