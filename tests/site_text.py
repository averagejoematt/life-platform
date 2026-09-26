"""tests/site_text.py — the reader-page census the site's vocabulary and reach guards derive from (#4182).

Two pure helpers over the STATIC HTML under site/ (legacy/ excluded by standing policy):

  reader_pages()        every site/**/index.html a reader can be served
  main_text(path)       that page's main-content text — <script>/<style>/<svg> dropped,
                        <nav>/<header>/<footer> and the chrome classes (wayfinder, doors,
                        mega, menu, app-bar, loop-forward) excluded, everything else kept
  static_reach()        the set of reader pages reachable from "/" by following <a href>
                        links in the whole page (chrome included — the nav IS reach)

Known limit, stated so no one over-reads a green: this is the STATIC surface. Text and
links that JS injects at runtime (the cockpit's level name, evidence.js's topic rail) are
invisible here; the render harness and tests/visual_qa.py see those. A term that leaves
the static HTML but survives in a renderer is still on the page.
"""

from __future__ import annotations

import glob
import os
from collections import deque
from html.parser import HTMLParser

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
SITE = os.path.join(REPO, "site")

HARD_SKIP_TAGS = {"script", "style", "svg"}
CHROME_TAGS = {"nav", "header", "footer"}
CHROME_CLASS_KEYWORDS = ("wayfinder", "doors", "mega", "menu", "app-bar", "loop-forward")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def reader_pages() -> list[str]:
    """Repo-relative paths of every reader-facing page (site/**/index.html, no legacy)."""
    out = []
    for p in sorted(glob.glob(os.path.join(SITE, "**", "index.html"), recursive=True)):
        rel = os.path.relpath(p, REPO)
        if "/legacy/" in rel:
            continue
        out.append(rel)
    return out


def page_url(rel: str) -> str:
    """site/coaching/index.html -> /coaching/ ; site/index.html -> /"""
    d = os.path.dirname(rel)[len("site") :]
    return (d or "") + "/"


class _MainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []

    def _skipping(self) -> bool:
        return any(s for _, s in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        cls = (dict(attrs).get("class") or "").lower()
        skip = tag in HARD_SKIP_TAGS or tag in CHROME_TAGS or any(k in cls for k in CHROME_CLASS_KEYWORDS)
        self.stack.append((tag, skip))

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self._skipping() and data.strip():
            self.parts.append(data)


def main_text(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        html = f.read()
    p = _MainText()
    p.feed(html)
    return " ".join(" ".join(p.parts).split())


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h)

    handle_startendtag = handle_starttag


def _local_page(href: str, current_rel: str, pages: set[str]) -> str | None:
    href = href.strip()
    if not href or href.startswith(("#", "http://", "https://", "//", "mailto:", "tel:", "javascript:")):
        return None
    href = href.split("#", 1)[0].split("?", 1)[0]
    if not href:
        return None
    if href.startswith("/"):
        path = href
    else:
        cur = "/" + os.path.dirname(current_rel)[len("site") :].lstrip("/")
        path = os.path.normpath(os.path.join(cur, href))
    if path.endswith(".html"):
        cand = "site" + path
        return cand if cand in pages else None
    if not path.endswith("/"):
        path += "/"
    cand = "site" + path + "index.html"
    return cand if cand in pages else None


def static_reach(start: str = "site/index.html") -> set[str]:
    """Every reader page reachable from `start` by static <a href> links (any depth)."""
    pages = set(reader_pages())
    seen = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        with open(os.path.join(REPO, cur), encoding="utf-8") as f:
            html = f.read()
        lp = _Links()
        lp.feed(html)
        for h in lp.hrefs:
            t = _local_page(h, cur, pages)
            if t and t not in seen:
                seen.add(t)
                q.append(t)
    return seen
