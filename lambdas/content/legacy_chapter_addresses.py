"""content/legacy_chapter_addresses.py — a chapter's legacy address follows its served edition (#6193).

THE RULING (owner, 2026-11-22, final edition rehearsal §4). "The legacy pages and feed links must not continue serving
uncorrected material indefinitely after the canonical editions are published." Redirect a legacy article URL to the
canonical chapter once its corrected edition is public; keep every feed item's identity and GUID; no loop and no wrong
week mapping; follow each chapter's actual visibility; keep the original privately; and leave no other legacy path that
still serves the first edition.

WHAT A LEGACY ADDRESS IS. ``/journal/posts/<page>/`` is served from ``generated/journal/posts/<page>/index.html`` (the
CloudFront generated origin, an S3 website endpoint). The chronicle publisher wrote it once, when the chapter was
approved, and never rewrites it. The same first-edition words also sit in two other public objects keyed by the same page
id: the chapter's entry in ``generated/journal/posts.json`` (its ``excerpt``) and its share kit,
``generated/moments/share-kits/<page>/kit.json`` (its ``excerpt`` and ``canonical_url``). The nightly archive packages
the page and the manifest (``operational.public_archive_registry``).

THE MAPPING. A page id is not a chapter number (program week 1 is page ``week-04``). The legacy address of a chapter is
its OWN ``url_legacy`` as the snapshot producer served it (``scripts/publish_snapshot.py`` reads it off
``/journal/posts.json`` and derives the chapter id from it with ``publish_snapshot_chapters.week_id``). Nothing here
computes a page from a chapter number. ``scripts/legacy_chapter_redirects.py --apply`` also requires the chapter's
first-edition backup pointer (``CHAPTER_EDITION#<id>#01``) to name the same journal page, so two independent records
agree before anything is replaced.

THE MECHANISM (why object replacement, not an edge rule). The legacy object is overwritten with a small redirect document
(``redirect_page``) whose S3 ``WebsiteRedirectLocation`` is the story path. The website endpoint then answers 301, and a
client that reads the object any other way (the anonymous S3 REST URL, the nightly archive) gets a page that names
only the canonical address. An edge redirect alone (``redirects.map`` → the hand-published ``v4-redirects`` function)
would leave the first edition readable at the bucket URL and in ``/archive/latest.tar.gz``, and would not follow edition
state without a republish. The writer is the attended ``--apply`` run. The CI deploy role cannot write
``generated/journal/*`` (``infra/iam/github-actions-deploy-role.permissions.json``), and widening it is an IAM change.

VISIBILITY.
  * A served edition (an entry in the snapshot's ``chapter_editions.json``: approved, gated, validated by the build): the
    legacy page becomes the redirect, the manifest excerpt and the share kit take the edition's own summary.
  * A withdrawn edition: the canonical page serves the first edition again, and it is still the governed page. The legacy
    address KEEPS redirecting there (a redirect to the canonical chapter is right whichever edition it serves, and
    re-publishing the old page would re-expose exactly what the edition removed). The manifest excerpt and the share kit
    go back to what they were before the first replacement (the private backup), as the site's summary does.
  * A retired, held, skipped, withdrawn-as-chapter or never-published week has no served edition, so it is never in the
    plan: nothing is created at its address, and an address that 404s today keeps 404ing.

THE SWITCH. ``content.chapter_editions.LIVE``. Off, or with no served edition, the plan is empty and nothing anywhere
changes (the feed builder, the copy guard and the apply run all read this plan).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any, Iterable, Optional

from content import chapter_editions as CE

ORIGIN = "https://averagejoematt.com"
LEGACY_PATH = re.compile(r"^/journal/posts/(week-\d{2,})/$")
STORY_PATH = re.compile(r"^/story/week-\d{2}/$")
POSTS_KEY = "generated/journal/posts.json"
#: Private, write-once copies this mechanism takes before it replaces anything (never under site/ or generated/).
BACKUP_ROOT = "backups/legacy-chapter-addresses/"
#: The marker a redirect document carries; its content is the story path. Readers find it with ``redirect_target``.
MARKER = "lp-legacy-chapter-redirect"
#: The most a redirect document may weigh. A first-edition journal page is 17–20 KB; the document is under 1 KB.
MAX_REDIRECT_BYTES = 2048


class PlanError(Exception):
    """The plan cannot be built as asked."""


def story_path(chapter_id: str) -> str:
    return f"/story/{chapter_id}/"


def page_id(legacy_path: str) -> str:
    m = LEGACY_PATH.match(legacy_path or "")
    if not m:
        raise PlanError(f"{legacy_path!r} is not a journal permalink (/journal/posts/week-NN/)")
    return m.group(1)


def legacy_key(legacy_path: str) -> str:
    return f"generated/journal/posts/{page_id(legacy_path)}/index.html"


def share_kit_key(legacy_path: str) -> str:
    return f"generated/moments/share-kits/{page_id(legacy_path)}/kit.json"


def plan(editions: Optional[Iterable[dict]], chapters: Optional[Iterable[dict]]) -> dict:
    """``{"chapters": [entry, …], "refused": [(chapter_id, why), …]}`` for the served editions.

    ``editions`` is the snapshot's ``chapter_editions.json`` ``editions`` list (what the build serves), ``chapters`` its
    ``chapters.json``. An entry: chapter_id · edition · title · summary · legacy_path · legacy_key · share_kit_key ·
    story_path · story_url. A chapter is refused (left out, named) when it is not a published chapter of the snapshot,
    has no journal permalink, or shares its permalink with another chapter — never guessed."""
    if not CE.LIVE:
        return {"chapters": [], "refused": []}
    published = {str(c.get("id")): c for c in chapters or [] if isinstance(c, dict) and c.get("status") == "published"}
    out: list[dict] = []
    refused: list[tuple[str, str]] = []
    for e in editions or []:
        if not isinstance(e, dict):
            continue
        cid = str(e.get("chapter_id") or "")
        if not CE.CHAPTER_ID.match(cid):
            refused.append((cid, "not a chapter id"))
            continue
        ch = published.get(cid)
        if ch is None:
            refused.append((cid, "not a published chapter of this snapshot (its address follows its visibility: nothing is created)"))
            continue
        legacy = str(ch.get("url_legacy") or "")
        if not LEGACY_PATH.match(legacy):
            refused.append((cid, f"no journal permalink to redirect ({legacy or 'none'})"))
            continue
        target = story_path(cid)
        if not STORY_PATH.match(target) or target.startswith("/journal/"):
            refused.append((cid, f"the canonical address {target!r} is not a story page"))
            continue
        out.append(
            {
                "chapter_id": cid,
                "edition": e.get("edition"),
                "title": str(ch.get("title") or e.get("title") or cid),
                "summary": e.get("summary"),
                "legacy_path": legacy,
                "legacy_key": legacy_key(legacy),
                "share_kit_key": share_kit_key(legacy),
                "story_path": target,
                "story_url": ORIGIN + target,
            }
        )
    seen: dict[str, list[str]] = {}
    for x in out:
        seen.setdefault(x["legacy_path"], []).append(x["chapter_id"])
    shared = {p for p, ids in seen.items() if len(ids) > 1}
    for x in [x for x in out if x["legacy_path"] in shared]:
        refused.append((x["chapter_id"], f"{x['legacy_path']} is claimed by {seen[x['legacy_path']]}; a page maps to one chapter"))
    return {"chapters": [x for x in out if x["legacy_path"] not in shared], "refused": refused}


def redirect_page(entry: dict) -> str:
    """The document that replaces a legacy page: no word of any edition (the title only), canonical and og:url → the story
    URL, noindex, an immediate refresh and a plain link. The S3 object also carries ``WebsiteRedirectLocation``."""
    path, url = entry["story_path"], entry["story_url"]
    if not STORY_PATH.match(path) or url != ORIGIN + path:
        raise PlanError(f"refusing a redirect document to {url!r}")
    t = html.escape(str(entry.get("title") or ""), quote=True)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{t} — The Measured Life</title>\n"
        '<meta name="robots" content="noindex">\n'
        f'<meta name="{MARKER}" content="{path}">\n'
        f'<link rel="canonical" href="{url}">\n'
        f'<meta property="og:url" content="{url}">\n'
        f'<meta http-equiv="refresh" content="0; url={path}">\n'
        "</head>\n"
        f'<body><p>This chapter is at <a href="{path}">{url}</a>.</p></body>\n'
        "</html>\n"
    )


_MARKER_RE = re.compile(r'<meta name="' + MARKER + r'" content="([^"]+)">')


def redirect_target(body: Optional[bytes]) -> Optional[str]:
    """The story path a redirect document names, or None when ``body`` is not one (too large, or no marker)."""
    if body is None or len(body) > MAX_REDIRECT_BYTES:
        return None
    m = _MARKER_RE.search(body.decode("utf-8", "replace"))
    return m.group(1) if m and STORY_PATH.match(m.group(1)) else None


def manifest_update(
    posts_doc: dict, entries: list[dict], originals: dict[str, str], now: str, keep: Iterable[str] = ()
) -> tuple[dict, list[str]]:
    """``posts.json`` with each planned chapter's excerpt set to its edition's summary and marked ``edition``; an entry
    marked by an earlier run whose edition is no longer served gets its ORIGINAL excerpt back (``originals``: url →
    excerpt, read from the private backup) and loses the mark. Order, every other entry and every other field unchanged.
    ``keep``: urls still served but not in this run (``--chapter``) — left exactly as they are.
    Returns ``(doc, changed urls)``; raises PlanError when a mark must be undone and no original was kept."""
    by_url = {x["legacy_path"]: x for x in entries}
    keep = set(keep) - set(by_url)
    posts: list = []
    changed: list[str] = []
    for p in posts_doc.get("posts") or []:
        url = p.get("url") if isinstance(p, dict) else None
        q = dict(p) if isinstance(p, dict) else p
        if url in by_url and by_url[url].get("summary"):
            x = by_url[url]
            if q.get("excerpt") != x["summary"] or q.get("edition") != x["edition"]:
                q["excerpt"], q["edition"] = x["summary"], x["edition"]
                changed.append(url)
        elif isinstance(q, dict) and "edition" in q and url not in keep:
            if url not in originals:
                raise PlanError(f"{url}: its edition is no longer served and no original excerpt was kept to restore")
            q["excerpt"] = originals[url]
            del q["edition"]
            changed.append(url)
        posts.append(q)
    doc = dict(posts_doc)
    doc["posts"] = posts
    if changed:
        doc["updated_at"] = now
    return doc, changed


def share_kit_update(kit: dict, entry: dict) -> dict:
    """The share kit with the edition's summary as its excerpt and the canonical chapter as its URL; nothing else moves."""
    out = dict(kit)
    out["excerpt"] = entry["summary"]
    out["canonical_url"] = entry["story_url"]
    return out


def copy_issues(
    entries: list[dict],
    read: Any,
    posts_doc: Optional[dict],
    archive: Optional[dict[str, bytes]] = None,
    archive_built: Optional[datetime] = None,
    modified: Optional[dict[str, datetime]] = None,
) -> list[tuple[str, str, str]]:
    """Rule G of ``scripts/check_public_copies.py``: for each chapter with a served edition, every public object keyed by
    its legacy page carries no first-edition text. ``read(key)`` returns an object's bytes or None when absent;
    ``modified`` maps key → its LastModified, so an archive built before the redirect was written is not yet due.
    Keys and chapter ids only in the messages — never a word of the page (the CI log is public)."""
    out: list[tuple[str, str, str]] = []
    posts = {p.get("url"): p for p in (posts_doc or {}).get("posts") or [] if isinstance(p, dict)}
    for x in entries:
        cid, key = x["chapter_id"], x["legacy_key"]
        body = read(key)
        if body is not None and redirect_target(body) != x["story_path"]:
            out.append(("chapters", "G", f"{key} — {cid} serves an edition at {x['story_path']}; its legacy page is not the redirect"))
        p = posts.get(x["legacy_path"])
        if p is not None and p.get("excerpt") != x["summary"]:
            out.append(("chapters", "G", f"{POSTS_KEY} — the {x['legacy_path']} entry does not carry {cid}'s edition summary"))
        kit = read(x["share_kit_key"])
        if kit is not None:
            try:
                k = json.loads(kit)
            except ValueError:
                k = {}
            if k.get("excerpt") != x["summary"] or k.get("canonical_url") != x["story_url"]:
                out.append(("chapters", "G", f"{x['share_kit_key']} — not {cid}'s edition summary and canonical address"))
        member = (archive or {}).get("web" + x["legacy_path"] + "index.html")
        due = not archive_built or not (modified or {}).get(key) or archive_built >= (modified or {})[key]
        if member is not None and redirect_target(member) != x["story_path"] and due:
            out.append(("archive", "G", f"web{x['legacy_path']}index.html — {cid}'s first-edition page is still archived"))
    return out
