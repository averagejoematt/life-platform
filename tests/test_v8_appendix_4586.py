"""#4586 — the appendix at /next/v8/appendix/ is generator output, and its list is honest.

The appendix is the one plain list of every live page that is off the preview's usual path
(owner ruling 2026-10-04: nothing is deleted; pages off the path stay reachable from one
list at the foot of the site). `scripts/v8_build_appendix.py` writes the page from
`scripts/v8_appendix_pages.json`. What this file holds:

  * the checked-in HTML is exactly what the generator writes (a hand edit fails);
  * every listed address is a real, indexable page under site/ (and in the sitemap);
  * no page held for an owner ruling (#4604), and nothing under /legacy, is listed;
  * no row's words carry a count of earlier starts, or an honorific on a persona;
  * every sitemap address is in exactly one list — shown, or held with a reason — so a
    page cannot fall off the site by being forgotten;
  * the page is a kit page: clean.css only, `ck-` classes only, noindex, in the kit gate.

It reads named files only (the data file, the page, the sitemap and each listed page's own
index.html) — no tree walk.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = SITE / "next" / "v8" / "appendix" / "index.html"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load("v8_build_appendix", ROOT / "scripts" / "v8_build_appendix.py")
kit_gate = _load("kit_page_gate", ROOT / "tests" / "kit_page_gate.py")

#: The five pages #4604 holds for a per-page owner ruling. Stated here, not read from the
#: data file: the data file is the thing under test.
HELD_4604 = ("/data/wall/", "/method/cycles/", "/method/postmortems/", "/method/survival/", "/story/attempts/")

#: Words a row must not carry: a count of earlier starts in any spelling the site has used.
_START_COUNT = re.compile(
    r"\b(cycles?|attempts?|resets?|restarts?|re-?starts?|17th|sixteen(th)?|seventeen(th)?|earlier starts?|prior runs?|every start)\b", re.I
)
_HONORIFIC = re.compile(r"\bDr\.")
_FIRST_PERSON = re.compile(r"\b(I|I’m|I'm|my|me|mine)\b")


def word_findings(pages: list[dict]) -> list[str]:
    out = []
    for row in pages:
        text = f"{row['title']} — {row['line']}"
        for rx, what in (
            (_START_COUNT, "a count of earlier starts"),
            (_HONORIFIC, "an honorific"),
            (_FIRST_PERSON, "first-person wording"),
        ):
            hit = rx.search(text)
            if hit:
                out.append(f"{row['url']}: {what} ({hit.group(0)!r}) in {text!r}")
    return out


def _sitemap_paths() -> list[str]:
    return re.findall(r"<loc>https://averagejoematt\.com([^<]*)</loc>", (SITE / "sitemap.xml").read_text(encoding="utf-8"))


def test_the_page_is_exactly_what_the_generator_writes():
    data = build.load()
    assert build.problems(data) == []
    assert PAGE.read_text(encoding="utf-8") == build.render(data), (
        "site/next/v8/appendix/index.html differs from the generator's output — change scripts/v8_appendix_pages.json "
        "and run python3 scripts/v8_build_appendix.py; never edit the page by hand"
    )
    # The control: a changed row changes the page, so the equality above can fail.
    mutated = {**data, "pages": [{**data["pages"][0], "title": "A different title"}, *data["pages"][1:]]}
    assert build.render(mutated) != build.render(data)


def test_every_listed_page_exists_is_indexable_and_is_in_the_sitemap():
    sitemap = set(_sitemap_paths())
    offenders = []
    for row in build.load()["pages"]:
        url = row["url"]
        index = SITE / url.strip("/") / "index.html"
        if not index.is_file():
            offenders.append(f"{url}: no page at site{url}index.html")
            continue
        head = index.read_text(encoding="utf-8")[:6000]
        if re.search(r'<meta\s+name="robots"[^>]*noindex', head):
            offenders.append(f"{url}: the page is noindex — an unlisted page is not a row in a reader's list")
        if 'http-equiv="refresh"' in head:
            offenders.append(f"{url}: the page is a redirect stub")
        if url not in sitemap:
            offenders.append(f"{url}: not in site/sitemap.xml")
    assert not offenders, "\n".join(offenders)


def test_no_held_page_and_nothing_legacy_or_preview_is_listed():
    urls = [row["url"] for row in build.load()["pages"]]
    offenders = [u for u in urls if u in HELD_4604 or u.startswith(("/legacy", "/next/", "/kit/"))]
    assert not offenders, f"listed but held or off-limits: {offenders}"
    html = PAGE.read_text(encoding="utf-8")
    for held in (*HELD_4604, "/legacy"):
        assert f'href="{held}' not in html, f"the page links {held}"


def test_no_row_carries_a_count_of_earlier_starts_or_an_honorific():
    assert word_findings(build.load()["pages"]) == []
    # Controls: each rule reds on a seeded row.
    seeded = [
        {"url": "/x/", "title": "Cycle vs cycle", "line": "A comparison."},
        {"url": "/y/", "title": "The start", "line": "The 17th start."},
        {"url": "/z/", "title": "Team", "line": "Dr. Example on sleep."},
        {"url": "/w/", "title": "Journal", "line": "What I wrote."},
    ]
    assert len(word_findings(seeded)) == 4


def test_every_sitemap_address_is_shown_or_held_with_a_reason():
    data = build.load()
    shown = {row["url"] for row in data["pages"]}
    held = {row["url"]: row["why"] for row in data["held"]}
    prefixes = {row["url"]: row["why"] for row in data["held_prefixes"]}
    assert not shown & set(held), f"both shown and held: {sorted(shown & set(held))}"
    assert all(why.strip() for why in (*held.values(), *prefixes.values())), "a held page carries its reason"
    assert set(HELD_4604) <= set(held), "the #4604 five stay held until the owner rules"
    orphans = [p for p in _sitemap_paths() if p not in shown and p not in held and not p.startswith(tuple(prefixes))]
    assert (
        not orphans
    ), f"in the sitemap but neither shown in the appendix nor held with a reason in scripts/v8_appendix_pages.json: {orphans}"


def test_the_page_is_a_quiet_kit_page():
    html = PAGE.read_text(encoding="utf-8")
    data = build.load()
    assert re.findall(r'<link rel="stylesheet" href="([^"]+)"', html) == ["/assets/css/clean.css"]
    assert "<style" not in html and " style=" not in html
    classes = {c for attr in re.findall(r'class="([^"]+)"', html) for c in attr.split()}
    assert all(c.startswith("ck-") for c in classes), sorted(c for c in classes if not c.startswith("ck-"))
    assert '<meta name="robots" content="noindex,nofollow">' in html
    assert html.count("<h1") == 1 and "<h1>Appendix</h1>" in html
    assert html.count(build.EARLIER_DESIGN) == 1
    assert len(data["kinds"]) <= build.MAX_KINDS
    assert html.count("<li>") == len(data["pages"])
    for label, rows in build.grouped(data):
        titles = [r["title"] for r in rows]
        assert titles == sorted(titles, key=str.lower), f"{label}: rows are in title order"
    assert "/next/v8/appendix/" in kit_gate.KIT_PAGES, "the appendix is held by tests/kit_page_gate.py"
