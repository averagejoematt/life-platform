"""tests/test_reader_surface_sweep_4604.py — the start-count rule over every served page, the sitemap and the feed (#4604).

The owner ruled on 2026-09-26 that no count of earlier starts, attempts, cycles or resets appears on any reader
surface. #4538 enforces it at the story door's chokepoints (``content/story_checks.reader_surface``: chronicle,
recap, Panel); nothing swept the served static pages or the sitemap, so whole pages built around a cross-start
comparison stayed served and advertised to search engines. This is the set guard #4604 box 3 asks for, built on
the SAME shared check rather than a second vocabulary:

  * every served static page under ``site/`` (``site/legacy/`` excluded — the frozen pre-v4 archive, noindex and
    never linked, ADR-071), its visible text plus its head copy (title, description, the unfurl tags), through
    ``reader_surface`` — free prose, so the count rule only;
  * the sitemap: no held page is advertised, and every advertised path, read as words, passes ``reader_surface``
    in ``constructed`` mode (a slug has no prose, so the frame word itself is refused);
  * the posts-feed chapter titles the repo carries — the generators' committed fallback
    (``scripts/proof_snapshot.json``), the captured live feed (``tests/fixtures/kit_pages_4586/posts.json``) and
    the essay feed (``site/journal/blog.json``) — in ``constructed`` mode; the titles baked into ``/story/`` and
    ``/story/chronicle/`` are covered by the page sweep.

The known set — ``v4_chrome.HELD_UNTIL_RULED`` — is a ledger, not an allowance: those pages are skipped by the
count sweep but each must carry ``noindex`` and stay out of the sitemap, the ledger can only shrink
(``_FROZEN_AT_FILING_4604``) as the owner rules page by page, and a ruled page that is retired drops out.

Blind spot, named: most held pages render their count from the API at runtime, so a static sweep cannot see it;
the guard is the static surface plus the ledger's noindex/sitemap contract. The counts themselves are not
restated anywhere in this file (public repo; the ruling is the point) — the seeded fixtures use generic ordinals.
"""

# premerge-gate: rglob sweep of every served site/**/*.html + sitemap + committed feed titles for a start count — a NEW page or title inherits the ledger silently, so it must red on the PR that adds it
from __future__ import annotations

import html as _html
import json
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))

import v4_chrome  # noqa: E402
from content.story_checks import reader_surface  # noqa: E402

BASE = "https://averagejoematt.com"
NOINDEX = 'name="robots" content="noindex"'

# The nine served pages #4604 holds (the five filed + the four from the 2026-10-04 extension). Shrink-only: the
# live ledger must stay a subset of this, so a page leaves when the owner rules and nothing new joins it here — a
# new offender is fixed or brought to the owner, never quietly exempted.
_FROZEN_AT_FILING_4604 = frozenset(
    {
        "/data/wall/",
        "/method/cycles/",
        "/method/postmortems/",
        "/method/survival/",
        "/story/attempts/",
        "/method/fingerprint/",
        "/story/build/",
        "/story/diary/",
        "/journal/essays/org-chart-of-one/",
    }
)

# Committed copies of the feeds whose titles a reader sees: (repo-relative path, how to get the list of entries).
_FEEDS = (
    ("scripts/proof_snapshot.json", lambda d: d.get("chronicle", [])),
    ("tests/fixtures/kit_pages_4586/posts.json", lambda d: d.get("posts", []) if isinstance(d, dict) else d),
    ("site/journal/blog.json", lambda d: d.get("posts", []) if isinstance(d, dict) else d),
)

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_HEAD_COPY = re.compile(
    r'<meta\s+(?:name|property)="(?:description|og:title|og:description|twitter:title|twitter:description)"\s+content="([^"]*)"',
    re.I,
)
_LOC = re.compile(r"<loc>([^<]+)</loc>")


def _count_only(findings: list[str]) -> list[str]:
    """The start-count findings of ``reader_surface`` (its off-record and vocabulary halves belong to other gates)."""
    return [f for f in findings if f.startswith("story-door:")]


def page_text(raw: str) -> str:
    """What a reader (or an unfurl) sees: the head copy plus the visible text, scripts and styles removed."""
    head = " · ".join(_html.unescape(m) for m in _HEAD_COPY.findall(raw))
    body = _TAG.sub(" ", _COMMENT.sub(" ", _SCRIPT_STYLE.sub(" ", raw)))
    return re.sub(r"\s+", " ", head + " · " + _html.unescape(body))


def url_path(site: pathlib.Path, f: pathlib.Path) -> str:
    rel = f.relative_to(site).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def sweep(repo: pathlib.Path, held: dict | frozenset) -> list[str]:
    """Every start-count finding on the served static surface, the sitemap and the feed titles under ``repo``."""
    site = repo / "site"
    out: list[str] = []
    pages = sorted(p for p in site.rglob("*.html") if not p.relative_to(site).as_posix().startswith("legacy/"))
    for f in pages:
        path = url_path(site, f)
        if path in held:
            continue
        for finding in _count_only(reader_surface(page_text(f.read_text(encoding="utf-8", errors="replace")))):
            out.append(f"page {path}: {finding}")

    sitemap = site / "sitemap.xml"
    listed = [u[len(BASE) :] if u.startswith(BASE) else u for u in _LOC.findall(sitemap.read_text(encoding="utf-8"))]
    for path in listed:
        if path in held:
            out.append(f"sitemap: {path} is held until the owner rules (#4604) and must not be advertised")
            continue
        words = re.sub(r"[/_-]+", " ", path).strip()
        for finding in _count_only(reader_surface(words, constructed=True)):
            out.append(f"sitemap {path}: {finding}")

    for path in sorted(held):
        f = site / (path.strip("/") + "/index.html" if path != "/" else "index.html")
        if not f.exists():
            out.append(f"ledger: {path} is no longer served — the owner ruled it retired; drop it from HELD_UNTIL_RULED")
        elif NOINDEX not in f.read_text(encoding="utf-8"):
            out.append(f'held page {path}: missing <meta name="robots" content="noindex"> (#4604 conservative step)')

    for rel, entries in _FEEDS:
        feed = repo / rel
        if not feed.exists():
            continue
        for e in entries(json.loads(feed.read_text(encoding="utf-8"))):
            title = (e or {}).get("title") or ""
            for finding in _count_only(reader_surface(title, constructed=True)):
                out.append(f"feed {rel} {e.get('url', '?')}: chapter title: {finding}")
    return out


# ── the guard ──────────────────────────────────────────────────────────────────


def test_no_served_page_sitemap_entry_or_chapter_title_renders_a_start_count():
    findings = sweep(REPO, v4_chrome.HELD_UNTIL_RULED)
    assert not findings, (
        "the owner ruled (2026-09-26) that no count of earlier starts/attempts/cycles/resets appears on any reader "
        "surface (#4604, #4538). Remove the count, or bring the page to the owner — never widen the ledger:\n  " + "\n  ".join(findings)
    )


def test_the_held_ledger_only_shrinks_and_names_its_issue():
    ledger = v4_chrome.HELD_UNTIL_RULED
    grown = set(ledger) - _FROZEN_AT_FILING_4604
    assert not grown, f"HELD_UNTIL_RULED grew past the set #4604 filed: {sorted(grown)} — a new offender is fixed, not exempted"
    unnamed = [p for p, why in ledger.items() if "#4604" not in why]
    assert not unnamed, f"every held page names the issue that holds it: {unnamed}"


def test_the_sweep_is_not_blind():
    """Population floor: the sweep reads a real tree — pages, a non-empty sitemap and at least one feed."""
    site = REPO / "site"
    pages = [p for p in site.rglob("*.html") if not p.relative_to(site).as_posix().startswith("legacy/")]
    assert len(pages) >= 60, f"the page sweep sees only {len(pages)} pages — has site/ moved?"
    assert len(_LOC.findall((site / "sitemap.xml").read_text(encoding="utf-8"))) >= 40, "the sitemap sweep has gone blind"
    assert any((REPO / rel).exists() for rel, _ in _FEEDS), "no committed feed found — the chapter-title sweep has gone blind"


# ── mutation controls: each seeds a violation in a scratch copy and must go red ─────────────────────────────


def _scratch(tmp_path: pathlib.Path) -> pathlib.Path:
    """A minimal clean tree: one ordinary page, one held page with noindex, a sitemap and a feed."""
    site = tmp_path / "site"
    (site / "scratch").mkdir(parents=True)
    (site / "scratch" / "index.html").write_text("<html><head><title>Scratch</title></head><body><p>Day 3 starts cold.</p></body></html>")
    (site / "data" / "wall").mkdir(parents=True)
    (site / "data" / "wall" / "index.html").write_text(f"<html><head><meta {NOINDEX}></head><body><p>held</p></body></html>")
    (site / "sitemap.xml").write_text(f"<urlset><url><loc>{BASE}/scratch/</loc></url></urlset>")
    (site / "journal").mkdir()
    (site / "journal" / "blog.json").write_text(json.dumps({"posts": [{"title": "Before the Numbers", "url": "/journal/essays/x/"}]}))
    return tmp_path


_SCRATCH_HELD = frozenset({"/data/wall/"})


def test_mutation_control_clean_scratch_tree_is_green(tmp_path):
    """The false-positive control: a numbered label ("Day 3 starts") and an ordinary title pass."""
    assert sweep(_scratch(tmp_path), _SCRATCH_HELD) == []


def test_mutation_control_a_count_seeded_on_a_page_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    page = repo / "site" / "scratch" / "index.html"
    page.write_text(page.read_text().replace("Day 3 starts cold.", "This is his third restart."))
    findings = sweep(repo, _SCRATCH_HELD)
    assert any(f.startswith("page /scratch/:") for f in findings), findings


def test_mutation_control_a_count_in_head_copy_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    page = repo / "site" / "scratch" / "index.html"
    page.write_text(page.read_text().replace("<title>", '<meta name="description" content="the third reset, up close"><title>'))
    assert any(f.startswith("page /scratch/:") for f in sweep(repo, _SCRATCH_HELD))


def test_mutation_control_a_held_page_in_the_sitemap_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    sm = repo / "site" / "sitemap.xml"
    sm.write_text(sm.read_text().replace("</urlset>", f"<url><loc>{BASE}/data/wall/</loc></url></urlset>"))
    assert any(f.startswith("sitemap: /data/wall/") for f in sweep(repo, _SCRATCH_HELD))


def test_mutation_control_a_frame_word_slug_in_the_sitemap_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    shutil.copytree(repo / "site" / "scratch", repo / "site" / "story" / "attempts")
    sm = repo / "site" / "sitemap.xml"
    sm.write_text(sm.read_text().replace("</urlset>", f"<url><loc>{BASE}/story/attempts/</loc></url></urlset>"))
    assert any(f.startswith("sitemap /story/attempts/:") for f in sweep(repo, _SCRATCH_HELD))


def test_mutation_control_a_held_page_without_noindex_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    wall = repo / "site" / "data" / "wall" / "index.html"
    wall.write_text(wall.read_text().replace(f"<meta {NOINDEX}>", ""))
    assert any(f.startswith("held page /data/wall/") for f in sweep(repo, _SCRATCH_HELD))


def test_mutation_control_a_counted_chapter_title_goes_red(tmp_path):
    repo = _scratch(tmp_path)
    blog = repo / "site" / "journal" / "blog.json"
    blog.write_text(json.dumps({"posts": [{"title": "The Third Reset, or: Again", "url": "/journal/posts/x/"}]}))
    assert any(f.startswith("feed site/journal/blog.json") for f in sweep(repo, _SCRATCH_HELD))


def test_mutation_control_a_retired_held_page_reds_the_stale_ledger(tmp_path):
    repo = _scratch(tmp_path)
    shutil.rmtree(repo / "site" / "data" / "wall")
    assert any(f.startswith("ledger: /data/wall/") for f in sweep(repo, _SCRATCH_HELD))
