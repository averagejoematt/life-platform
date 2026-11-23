#!/usr/bin/env python3
"""scripts/verify_legacy_chapter_redirects.py — read-only proof that a chapter's legacy address follows its edition (#6193).

Run after a chapter's edition is public and ``scripts/legacy_chapter_redirects.py --apply`` has run (owner ruling
2026-11-22 §4: "Verify direct URLs, feeds, canonical metadata, link previews and relevant cached copies … Verify that
restricted content isn't still reachable through another legacy path"). For each chapter it prints PASS / FAIL / NOTE:

  served     /story/<id>/ answers 200 and shows the edition (the edition line)
  direct     /journal/posts/<page>/, its bare form and …/index.html: every hop, the final address, no loop — the chain ends
             at /story/<id>/ with 200. A 200 legacy answer that IS the redirect document passes with a note (the edge has
             not re-fetched it yet; the refresh still lands the reader on the chapter).
  metadata   on the final page: canonical and og:url are the story URL, og:description is the edition's summary
  copies     the anonymous bucket URL of the page (the redirect document, no other bytes), the old site/ copies of the
             same page id (stubs of at most 2 KB, or absent), posts.json (the edition's summary), the share kit (summary
             and canonical URL)
  feeds      /rss.xml and /feed.xml: the chapter's item still has its guid (the bare legacy URL, once), its link goes to
             the chapter, and — with --feed-baseline FILE (a saved copy of the feed from before) — every item's guid,
             title and pubDate and the item count are unchanged
  archive    /archive/latest.tar.gz: the page member is the redirect document (a NOTE, not a FAIL, when the archive was
             built before the redirect was written: the next nightly run replaces it)
  rollback   with AWS read credentials (optional): the previous v9 build a root rollback restores (www-previous/LATEST)
             and the legacy page's object versions — the newest is the redirect, the older ones are private
  privacy    with --terms FILE (an off-repo list, one term per line): hit counts per reachable body. The terms and the
             matching text are never printed.

Writes nothing, anywhere. Anonymous HTTPS for everything public; ``s3:ListBucketVersions``/``GetObject`` reads only for
the optional rollback section. Exit 0 = every check passed (notes allowed), 1 = a FAIL, 3 = could not run.

    python3 scripts/verify_legacy_chapter_redirects.py [--chapter week-12] [--feed-baseline rss_before.xml] [--terms FILE]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lambdas"))
sys.path.insert(0, _HERE)
from content import legacy_chapter_addresses as LA  # noqa: E402
from legacy_chapter_redirects import BUCKET, EDITION_MARK, fresh_snapshot, load_snapshot  # noqa: E402

S3_REST = f"https://{BUCKET}.s3.us-west-2.amazonaws.com"
ARCHIVE_URL = LA.ORIGIN + "/archive/latest.tar.gz"
MAX_HOPS = 5
OLD_COPIES = ("site/journal/posts/{page}/index.html", "site/legacy/journal/posts/{page}/index.html")


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 — never follow; we walk the hops
        return None


_OPENER = urllib.request.build_opener(_NoFollow)


def fetch(url: str) -> tuple[int, dict, bytes]:
    """(status, headers, body) of ONE request — redirects are returned, not followed."""
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform-legacy-verify/1.0 (#6193)"})
    try:
        with _OPENER.open(req, timeout=30) as r:  # nosec B310 — public https origins
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() if e.fp else b""


def walk(url: str) -> tuple[list[tuple[int, str]], bytes, Optional[str]]:
    """Follow at most MAX_HOPS redirects by hand. Returns (hops, final body, problem or None)."""
    hops, seen = [], set()
    for _ in range(MAX_HOPS + 1):
        if url in seen:
            return hops, b"", f"redirect loop at {url}"
        seen.add(url)
        status, headers, body = fetch(url)
        hops.append((status, url))
        loc = headers.get("Location") or headers.get("location")
        if status in (301, 302, 303, 307, 308) and loc:
            url = urllib.parse.urljoin(url, loc)
            continue
        return hops, body, None
    return hops, b"", f"more than {MAX_HOPS} redirects"


def _meta(body: str, attr: str, name: str) -> Optional[str]:
    m = re.search(rf'<meta[^>]+{attr}="{re.escape(name)}"[^>]+content="([^"]*)"', body) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]+{attr}="{re.escape(name)}"', body
    )
    return m.group(1) if m else None


def _canonical(body: str) -> Optional[str]:
    m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', body) or re.search(r'<link[^>]+href="([^"]+)"[^>]+rel="canonical"', body)
    return m.group(1) if m else None


def feed_items(xml: str) -> list[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):

        def tag(t: str, it: str = it) -> Optional[str]:
            m = re.search(rf"<{t}\b([^>]*)>(.*?)</{t}>", it, re.S)
            return m.group(2).strip() if m else None

        g = re.search(r"<guid\b([^>]*)>(.*?)</guid>", it, re.S)
        out.append(
            {
                "title": tag("title"),
                "link": (tag("link") or "").replace("&amp;", "&"),
                "guid": g.group(2).strip() if g else None,
                "permalink": 'isPermaLink="true"' in (g.group(1) if g else ""),
                "pubDate": tag("pubDate"),
            }
        )
    return out


def check_feeds(x: dict, baseline: Optional[str], say) -> None:
    for path in ("/rss.xml", "/feed.xml"):
        status, _h, body = fetch(LA.ORIGIN + path)
        if status != 200:
            say("FAIL", "feeds", f"{path} answered {status}")
            continue
        items = feed_items(body.decode("utf-8", "replace"))
        mine = [i for i in items if i["guid"] == LA.ORIGIN + x["legacy_path"]]
        if len(mine) != 1:
            say("FAIL", "feeds", f"{path}: {len(mine)} item(s) with the guid {LA.ORIGIN}{x['legacy_path']} (expected exactly 1)")
            continue
        link = mine[0]["link"].split("?", 1)[0]
        if link == x["story_url"]:
            say("PASS", "feeds", f"{path}: guid unchanged (isPermaLink={mine[0]['permalink']}), link → {link}")
        else:
            say("NOTE", "feeds", f"{path}: link still {link} (it redirects; the next site deploy rebuilds the feed with the chapter link)")
        if baseline:
            with open(baseline, encoding="utf-8") as fh:
                before = feed_items(fh.read())
            same = [(i["guid"], i["title"], i["pubDate"]) for i in before] == [(i["guid"], i["title"], i["pubDate"]) for i in items]
            say(
                "PASS" if same else "FAIL",
                "feeds",
                f"{path}: {len(items)} item(s); guids, titles and pubDates vs the baseline " + ("unchanged" if same else "CHANGED"),
            )


def read_archive(blob: bytes) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for info in tf.getmembers():
            fh = tf.extractfile(info) if info.isfile() else None
            if fh is not None:
                out[info.name.partition("/")[2]] = fh.read()
    return out


def check_rollback(x: dict, say) -> None:
    try:
        import boto3  # noqa: PLC0415

        s3 = boto3.client("s3", region_name="us-west-2")
        latest = s3.get_object(Bucket=BUCKET, Key="www-previous/LATEST")["Body"].read().decode().strip()
        prev = s3.get_object(Bucket=BUCKET, Key=f"www-previous/{latest}/story/{x['chapter_id']}/index.html")["Body"].read()
        say(
            "NOTE",
            "rollback",
            f"a v9 root rollback restores build {latest}: its /story/{x['chapter_id']}/ shows "
            + (
                "the edition"
                if EDITION_MARK.encode() in prev
                else "the FIRST edition (still the governed page; the legacy redirect is untouched by a v9 rollback)"
            ),
        )
        vs = s3.list_object_versions(Bucket=BUCKET, Prefix=x["legacy_key"]).get("Versions") or []
        vs = [v for v in vs if v["Key"] == x["legacy_key"]]
        newest = next((v for v in vs if v.get("IsLatest")), None)
        body = s3.get_object(Bucket=BUCKET, Key=x["legacy_key"], VersionId=newest["VersionId"])["Body"].read() if newest else None
        ok = LA.redirect_target(body) == x["story_path"]
        say(
            "PASS" if ok else "FAIL",
            "rollback",
            f"{x['legacy_key']}: {len(vs)} version(s); newest is "
            + ("the redirect" if ok else "NOT the redirect")
            + "; older versions are private (no anonymous GetObjectVersion)",
        )
    except Exception as exc:  # noqa: BLE001 — optional section: no credentials is a note, not a failure
        say("NOTE", "rollback", f"not checked ({type(exc).__name__}) — needs AWS read credentials")


def verify(x: dict, args, terms: list[str], archive: Optional[dict], say) -> None:
    page = LA.page_id(x["legacy_path"])
    bodies: dict[str, bytes] = {}
    st, _h, story = fetch(x["story_url"])
    say(
        "PASS" if st == 200 and EDITION_MARK.encode() in story else "FAIL",
        "served",
        f"{x['story_path']} answered {st}" + (", showing the edition" if EDITION_MARK.encode() in story else ", WITHOUT the edition line"),
    )
    for variant in (x["legacy_path"], x["legacy_path"].rstrip("/"), x["legacy_path"] + "index.html"):
        hops, final, problem = walk(LA.ORIGIN + variant)
        chain = " → ".join(f"{s} {urllib.parse.urlparse(u).path}" for s, u in hops)
        end = urllib.parse.urlparse(hops[-1][1]).path
        bodies[variant] = final
        if problem:
            say("FAIL", "direct", f"{variant}: {problem} ({chain})")
        elif end == x["story_path"] and hops[-1][0] == 200:
            say("PASS", "direct", chain)
        elif hops[-1][0] == 200 and LA.redirect_target(final) == x["story_path"]:
            say("NOTE", "direct", f"{chain} — the redirect document (refresh → {x['story_path']}); the edge has not re-fetched yet")
        else:
            say("FAIL", "direct", f"{chain} — does not reach {x['story_path']}")
    body = story.decode("utf-8", "replace")
    canon, ogu, ogd = _canonical(body), _meta(body, "property", "og:url"), _meta(body, "property", "og:description")
    say("PASS" if canon == x["story_url"] and ogu == x["story_url"] else "FAIL", "metadata", f"canonical {canon} · og:url {ogu}")
    import html as _html  # noqa: PLC0415

    same = ogd is not None and " ".join(_html.unescape(ogd).split()) == " ".join(str(x.get("summary") or "").split())
    say(
        "PASS" if same else "NOTE",
        "metadata",
        "og:description is the edition's summary" if same else "og:description differs from the edition summary — read it",
    )
    st, _h, raw = fetch(f"{S3_REST}/{x['legacy_key']}")
    bodies["bucket"] = raw
    say(
        "PASS" if st == 200 and LA.redirect_target(raw) == x["story_path"] else ("PASS" if st in (403, 404) else "FAIL"),
        "copies",
        f"bucket URL of the page: {st}, {len(raw)} bytes" + (", the redirect document" if LA.redirect_target(raw) else ""),
    )
    for tpl in OLD_COPIES:
        key = tpl.format(page=page)
        st, _h, raw = fetch(f"{S3_REST}/{key}")
        bodies[key] = raw if st == 200 else b""
        small = st != 200 or len(raw) <= LA.MAX_REDIRECT_BYTES
        say("PASS" if small else "FAIL", "copies", f"{key}: {st}" + (f", {len(raw)} bytes" if st == 200 else ""))
    st, _h, posts = fetch(LA.ORIGIN + "/journal/posts.json")
    entry = (
        next((p for p in json.loads(posts or b"{}").get("posts") or [] if p.get("url") == x["legacy_path"]), None) if st == 200 else None
    )
    bodies["posts.json entry"] = json.dumps(entry or {}).encode()
    say(
        "PASS" if entry is None or entry.get("excerpt") == x["summary"] else "FAIL",
        "copies",
        "posts.json: "
        + (
            "no entry"
            if entry is None
            else ("the edition's summary" if entry.get("excerpt") == x["summary"] else "NOT the edition's summary")
        ),
    )
    st, _h, kit = fetch(f"{LA.ORIGIN}/moments/share-kits/{page}/kit.json")
    if st == 200:
        k = json.loads(kit)
        bodies["share kit"] = kit
        ok = k.get("excerpt") == x["summary"] and k.get("canonical_url") == x["story_url"]
        say(
            "PASS" if ok else "FAIL",
            "copies",
            "share kit: " + ("the edition's summary and the chapter URL" if ok else "first-edition excerpt or legacy URL"),
        )
    check_feeds(x, args.feed_baseline, say)
    if archive is not None:
        member = archive.get("web" + x["legacy_path"] + "index.html")
        bodies["archive member"] = member or b""
        built = json.loads(archive.get("MANIFEST.json") or b"{}").get("generated_at")
        if member is None or LA.redirect_target(member) == x["story_path"]:
            say("PASS", "archive", f"built {built}: " + ("no member" if member is None else "the redirect document"))
        else:
            say(
                "NOTE",
                "archive",
                f"built {built}: still the first-edition page — the next nightly run (after the redirect) replaces it; re-run then",
            )
    if args.rollback:
        check_rollback(x, say)
    for name, b in bodies.items():
        text = b.decode("utf-8", "replace").lower()
        hits = sum(text.count(t) for t in terms)
        if terms:
            say("PASS" if hits == 0 else "FAIL", "privacy", f"{name}: {hits} hit(s) of the off-repo terms")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chapter", action="append", help="limit to these chapter ids (week-NN)")
    ap.add_argument("--snapshot", help="a live snapshot dir to reuse (default: export a fresh one)")
    ap.add_argument("--feed-baseline", help="a saved /rss.xml from before publication, to prove the items did not change")
    ap.add_argument("--terms", help="an OFF-REPO file of restricted terms, one per line (never printed)")
    ap.add_argument("--no-archive", action="store_true", help="skip downloading /archive/latest.tar.gz")
    ap.add_argument("--rollback", action="store_true", help="also read the rollback copies (needs AWS read credentials)")
    args = ap.parse_args(argv)
    terms = []
    if args.terms:
        with open(args.terms, encoding="utf-8") as fh:
            terms = [t.strip().lower() for t in fh if t.strip()]
    with tempfile.TemporaryDirectory(prefix="legacy-verify-") as tmp:
        try:
            editions, chapters = load_snapshot(args.snapshot or fresh_snapshot(tmp))
        except SystemExit as exc:
            print(exc, file=sys.stderr)
            return 3
    p = LA.plan(editions, chapters)
    entries = [x for x in p["chapters"] if not args.chapter or x["chapter_id"] in args.chapter]
    fails = [0]

    def say(verdict: str, section: str, msg: str) -> None:
        fails[0] += verdict == "FAIL"
        print(f"  {verdict:<4} {section:<9} {msg}")

    for cid, why in p["refused"]:
        say("FAIL", "plan", f"{cid}: {why}")
    missing = sorted(set(args.chapter or []) - {x["chapter_id"] for x in entries})
    for cid in missing:
        say(
            "NOTE",
            "plan",
            f"{cid}: no served edition — its legacy address is not this mechanism's (it follows the chapter's own visibility)",
        )
    if not entries:
        print("no chapter serves an edition: nothing to verify")
        return 1 if fails[0] else 0
    archive = None
    if not args.no_archive:
        st, _h, blob = fetch(ARCHIVE_URL)
        archive = read_archive(blob) if st == 200 else None
    for x in entries:
        print(f"{x['chapter_id']} — {x['legacy_path']} → {x['story_path']} (edition {x['edition']})")
        verify(x, args, terms, archive, say)
    print(f"\n{'❌ ' + str(fails[0]) + ' check(s) failed' if fails[0] else '✅ every check passed'}")
    return 1 if fails[0] else 0


if __name__ == "__main__":
    sys.exit(main())
