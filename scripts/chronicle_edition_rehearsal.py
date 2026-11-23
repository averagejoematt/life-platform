#!/usr/bin/env python3
"""scripts/chronicle_edition_rehearsal.py — rehearse the whole second-edition release on the real publishing path (#6193).

Owner ruling 2026-11-22 (rehearsal §9): before publication, "rehearse the actual production publishing path again
against all eight exact final candidates" and report ten things. This runs EVERY given edition (and its archival text)
together through the code the release uses, writes nothing anywhere, and prints ONE table: edition -> pass, or blocked
with the precise reason, per check.

  1. gates      — the proposal gates with the REAL records (content filter, the withheld graded record AND withheld
                  coach outputs, the private-call policy, the truth checks), on the edition and its archival text;
  2. title      — the title line is the chapter's published title, and the text is in the presentation form;
  3. hash       — the text the tool would store hashes to the SHA-256 given for it (no unapproved prose changed);
  4. backup     — the backup's dry run (its journal page found, the row rebuilt in memory = the restore path);
  5. build      — the snapshot exporter's own per-edition holds (B4 title/summary, B9 archive address, as_of);
  6. verify     — the built chapter page against the approved bytes, by the documented transformation;
  7. surfaces   — the edition's summary on the story index, Moments and the og/description; the first edition's nowhere;
  8. feed       — the feed with every edition: the same item count, guids, titles and pubDates as without;
  9. archive    — the archival page (if offered): built, noindex, canonical, its note, its corrections, its anchors;
  10. withdraw  — in memory: withdrawing the edition serves the first edition, every other edition stays; a re-approval
                  as the next number serves again.
Screenshots of every chapter page and archival page at 390 px and 1280 px go to ``--out``.

    python3 scripts/chronicle_edition_rehearsal.py --manifest <private>/editions.json --out <private dir>

The manifest (PRIVATE, never committed) is a list of
``{"chapter": "week-NN", "row_sk": "DATE#…", "text_file": …, "sha256": <the stored text's hash>, "carries": [...],
"archival_file": … (optional), "archival_as_of": "YYYY-MM-DD" (optional)}``.

Read-only: public HTTPS reads, read-only DynamoDB/S3 reads with the laptop's credentials. Leaves ``www/dist`` as a
rehearsal build (NEVER deploy it) and restores ``www/owned_paths.json`` and ``www/reach.json``. Exit: 0 every edition
passed · 1 at least one blocked · 2 bad input · 3 the build failed.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(REPO, "www")
SNAPSHOT = os.path.join(WWW, "content", "snapshot")
DIST = os.path.join(WWW, "dist")
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from content import chapter_editions as CE  # noqa: E402

CHECKS = ("gates", "title", "hash", "backup", "build", "verify", "surfaces", "feed", "archive", "withdraw")


def records(entry: dict, text: str, archival: Optional[str], first: str, today: str, n: int = 2) -> list:
    """In-memory records shaped as approved, for rendering ONLY (never written anywhere)."""
    from chronicle_edition_preview import preview_records  # noqa: PLC0415

    rows = preview_records(entry["chapter"], text, first, archival, today, entry.get("archival_as_of"))
    for r in rows:
        if r.get("record_type") == CE.EDITION_TYPE:
            r["carries"] = list(entry.get("carries") or [])
            if n != 2:
                r.update(sk=CE.sk_edition(entry["chapter"], n), edition=n, signature=CE.signature(n, today))
    return rows


def simulate_withdrawal(rows_by_chapter: dict, chapter: str, today: str) -> Optional[str]:
    """None when withdrawing ``chapter``'s edition serves its first edition and leaves every other chapter's edition, and
    a re-approval as edition 3 serves again; else the reason."""
    view = lambda rows: {
        e["chapter_id"]
        for e in CE.public_view(rows, tainted=lambda _t: False, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: [])
    }  # noqa: E731
    everything = [r for rows in rows_by_chapter.values() for r in rows]
    before = view(everything)
    if chapter not in before:
        return "the edition is not served to begin with"
    gone = CE.new_withdrawal(chapter_id=chapter, kind="edition", number=2, at=f"{today}T12:00:00Z", dated_on=today)
    after = view(everything + [gone])
    if chapter in after:
        return "still served after the withdrawal"
    if after != before - {chapter}:
        return f"the withdrawal changed other chapters: {sorted(before - after - {chapter})}"
    ed2 = next(r for r in rows_by_chapter[chapter] if r.get("record_type") == CE.EDITION_TYPE)
    ed3 = {**ed2, "sk": CE.sk_edition(chapter, 3), "edition": 3, "signature": CE.signature(3, ed2["revised_on"])}
    if chapter not in view(everything + [gone, ed3]):
        return "a re-approval as edition 3 does not serve again"
    return None


def surfaces(dist: str, chapter: str, summary: str, first_summary: Optional[str]) -> Optional[str]:
    """None when the edition's summary is on every summary surface and the first edition's is on none."""
    read = lambda p: (
        html_lib.unescape(open(os.path.join(dist, p), encoding="utf-8").read()) if os.path.exists(os.path.join(dist, p)) else ""
    )  # noqa: E731
    page = read(os.path.join("story", chapter, "index.html"))
    problems = []
    for p, what in ((os.path.join("story", "index.html"), "the story index"), (os.path.join("story", chapter, "index.html"), "the header")):
        if summary not in read(p):
            problems.append(f"{what} does not carry the edition's summary")
    m = re.search(r'<meta property="og:description" content="([^"]*)"', page)
    if not m or html_lib.unescape(m.group(1)) != summary:
        problems.append("og:description is not the edition's summary")
    if first_summary and len(first_summary) >= 20 and first_summary != summary:
        for dirpath, _d, files in os.walk(dist):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), dist)
                if f.endswith(".html") and "first-edition" not in rel and first_summary in read(rel):
                    problems.append(f"{rel} still shows the first edition's summary")
    return "; ".join(problems) or None


def feed_items(xml: str) -> list:
    return [
        (re.search(r"<title>([^<]*)</title>", i).group(1), re.search(r"<guid[^>]*>([^<]*)</guid>", i).group(1), (re.search(r"<pubDate>([^<]*)</pubDate>", i) or [None, None])[1])  # type: ignore[union-attr,index]
        for i in re.findall(r"<item>([\s\S]*?)</item>", xml)
    ]


def feed_check(editions: list, tmp: str) -> Optional[str]:
    """The real feed builder over the live sources, without and with the editions: identical items save descriptions."""
    import urllib.request  # noqa: PLC0415

    import v4_build_rss as R  # noqa: PLC0415

    real = urllib.request.urlopen

    def build(extra: Optional[list]) -> str:
        def opener(url, timeout=0):
            r = real(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (edition-rehearsal)"}), timeout=timeout or 30)
            if url == R.CHAPTERS_SRC and extra is not None:
                body = json.loads(r.read())
                body["editions"] = extra
                import io  # noqa: PLC0415

                class _R(io.BytesIO):
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False

                return _R(json.dumps(body).encode())
            return r

        saved = (R.urlopen, R.OUT, R.OUT_ALIAS, R.build_broadcast_feed, R.build_wrong_feed)
        R.urlopen, R.OUT, R.OUT_ALIAS = opener, __import__("pathlib").Path(tmp, "rss.xml"), __import__("pathlib").Path(tmp, "feed.xml")
        R.build_broadcast_feed = R.build_wrong_feed = lambda: 0
        try:
            R.main()
            return open(os.path.join(tmp, "rss.xml"), encoding="utf-8").read()
        finally:
            R.urlopen, R.OUT, R.OUT_ALIAS, R.build_broadcast_feed, R.build_wrong_feed = saved

    before, after = feed_items(build(None)), feed_items(build(editions))
    if before != after:
        return f"the feed's items changed ({len(before)} -> {len(after)} items, or a guid/title/pubDate differs)"
    return None


def table(results: dict) -> str:
    """One row per edition: PASS, or BLOCKED with every check's reason."""
    lines = ["| edition | verdict | " + " | ".join(CHECKS) + " |", "|---|---|" + "---|" * len(CHECKS)]
    for chapter, res in results.items():
        blocked = [c for c in CHECKS if res.get(c) not in (None, "n/a")]
        cells = ["ok" if res.get(c) is None else ("n/a" if res.get(c) == "n/a" else f"BLOCKED: {res[c]}") for c in CHECKS]
        lines.append(f"| {chapter} | {'PASS' if not blocked else 'BLOCKED'} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _gates(texts: list) -> list:
    import boto3  # noqa: PLC0415
    from chronicle_edition_preview import _private_calls_or_none, _tainted_or_none  # noqa: PLC0415
    from content import private_call_check  # noqa: PLC0415
    from privacy import privacy_guard  # noqa: PLC0415

    del boto3
    tainted, calls = _tainted_or_none(), _private_calls_or_none()
    return [
        CE.gate_findings(t, tainted=tainted, private_calls=private_call_check.for_text(calls), filter_hits=privacy_guard.find_violations)
        for t in texts
    ]


def _backup(entry: dict) -> Optional[str]:
    import boto3  # noqa: PLC0415
    import chronicle_edition_backup as B  # noqa: PLC0415

    try:
        B.plan(
            entry["chapter"],
            entry["row_sk"],
            boto3.client("s3", region_name="us-west-2"),
            boto3.resource("dynamodb", region_name="us-west-2").Table(B.TABLE),
            now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except B.Refused as exc:
        if "already backed up" in str(exc):
            return None  # a backup on record: approve_edition reads it (and its restore rehearsal)
        return str(exc)
    return None


def _screens(paths: list, out: str) -> None:
    import functools  # noqa: PLC0415
    import http.server  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for path in paths:
                for name, (w, h) in {"phone": (390, 844), "desktop": (1280, 900)}.items():
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(f"http://127.0.0.1:{srv.server_port}{path}", wait_until="networkidle")
                    page.screenshot(path=os.path.join(out, f"{path.strip('/').replace('/', '_')}_{name}.png"), full_page=True)
                    page.close()
            browser.close()
    finally:
        srv.shutdown()


def live_verify(results: dict, served: dict, out: str, base_url: str, fetch: Optional[Callable[[str], str]] = None) -> None:
    """The deployed-page verifier itself (``chronicle_edition_verify.verify``), over the LIVE ``/api/chapters`` response —
    its real shape, retired and skipped weeks with ``"url": null`` included — with the rehearsed editions placed in it,
    the rehearsal's own built pages and its own feed. The snapshot the build reads is the exporter's view of that
    response, not the response, so a verifier that crashes on the live shape was invisible to every other check here
    (#6193: Week 10's first verify exited 3 on a null url)."""
    import chronicle_edition_verify as V  # noqa: PLC0415

    fetch = fetch or V.http_get
    try:
        live = json.loads(fetch(f"{base_url}/api/chapters"))
    except Exception as exc:  # noqa: BLE001
        for cid in served:
            results[cid]["verify"] = f"the live /api/chapters could not be read ({type(exc).__name__})"
        return
    live["editions"] = list(served.values())

    def get(url: str) -> str:
        path = url[len(base_url) :] if url.startswith(base_url) else url
        if path == "/api/chapters":
            return json.dumps(live)
        if path == "/rss.xml":
            return open(os.path.join(out, "rss.xml"), encoding="utf-8").read()
        return open(os.path.join(DIST, path.strip("/"), "index.html"), encoding="utf-8").read()

    for cid, e in served.items():
        a = e.get("archival") or {}
        try:
            problems = V.verify(get, cid, e["text_sha256"], archival_sha256=a.get("text_sha256"), base=base_url)
        except Exception as exc:  # noqa: BLE001 — exactly what the CLI would print as UNREADABLE
            problems = [f"the verifier crashed on the live response shape ({type(exc).__name__}: {exc})"]
        if problems:
            prior = results[cid].get("verify")
            results[cid]["verify"] = "; ".join(([prior] if prior else []) + problems)


def rehearse(manifest: list, out: str, base_url: str, log: Callable[[str], None] = print) -> dict:
    import publish_snapshot_chapter_editions as exporter  # noqa: PLC0415
    from chronicle_edition_verify import _dek, _h1  # noqa: PLC0415

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results: dict = {}
    cp = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "publish_snapshot.py"), "--mode", "live", "--out", SNAPSHOT, "--base-url", base_url],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"live snapshot failed: {cp.stderr[-1500:]}")
    chapters = json.load(open(os.path.join(SNAPSHOT, "chapters.json"), encoding="utf-8"))
    by_id = {c.get("id"): c for c in chapters}
    try:
        corrections = json.load(open(os.path.join(SNAPSHOT, "chapter_corrections.json"), encoding="utf-8"))
    except (OSError, ValueError):
        corrections = None
    rows_by_chapter: dict = {}
    texts: dict = {}
    for entry in manifest:
        cid = entry["chapter"]
        res = results.setdefault(cid, {c: None for c in CHECKS})
        text = open(entry["text_file"], encoding="utf-8").read()
        archival = open(entry["archival_file"], encoding="utf-8").read() if entry.get("archival_file") else None
        stored = CE._text(text)
        texts[cid] = (stored, archival)
        findings = _gates([stored] + ([archival] if archival else []))
        if any(findings):
            res["gates"] = "; ".join(
                f"{'edition' if i == 0 else 'archival'}: {len(f)} finding(s) ({f[0][:90]})" for i, f in enumerate(findings) if f
            )
        res["title"] = CE.title_problem(stored, (by_id.get(cid) or {}).get("title"))
        if entry.get("sha256") and CE.text_sha256(stored) != entry["sha256"]:
            res["hash"] = f"the stored text hashes to {CE.text_sha256(stored)[:12]}…, not the given {entry['sha256'][:12]}…"
        res["backup"] = _backup(entry)
        res["archive"] = None if archival else "n/a"
        first = str((by_id.get(cid) or {}).get("published_at") or "")[:10] or "2000-01-01"
        try:
            rows_by_chapter[cid] = records(entry, stored, archival, first, today)
        except CE.EditionError as exc:
            res["build"] = str(exc)
    view = CE.public_view(
        [r for rows in rows_by_chapter.values() for r in rows],
        tainted=lambda _t: False,
        private_calls=CE.PRIVATE_CALLS_NOT_WIRED,
        filter_hits=lambda _t: [],
        log=log,
    )
    held: list = []
    doc = exporter.validate(
        {"state": "ok", "source": ["/api/chapters"], "editions": view}, {"chapter": chapters}, corrections, log=log, held=held
    )
    served = {e["chapter_id"]: e for e in doc["editions"]}
    for cid, res in results.items():
        if cid not in served and res["build"] is None:
            res["build"] = "held by the build (see the log above)"
        if f"{cid}#archival" in held and res["archive"] is None:
            res["archive"] = "the archival rendering was held by the build"
        res["withdraw"] = simulate_withdrawal(rows_by_chapter, cid, today) if cid in rows_by_chapter else "n/a"
    saved = {p: open(p, "rb").read() for p in (os.path.join(WWW, "owned_paths.json"), os.path.join(WWW, "reach.json"))}
    try:
        with open(os.path.join(SNAPSHOT, "chapter_editions.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        cp = subprocess.run(["npm", "run", "build", "--silent"], cwd=WWW, capture_output=True, text=True)
        if cp.returncode != 0:
            raise RuntimeError(f"build failed: {cp.stderr[-1500:]}")
    finally:
        for p, b in saved.items():
            open(p, "wb").write(b)
    paths = []
    for cid, e in served.items():
        res = results[cid]
        page = open(os.path.join(DIST, "story", cid, "index.html"), encoding="utf-8").read()
        problems = CE.verify_page(page, e["text"], e["text_sha256"], dek=_dek(page), h1=_h1(page))
        res["verify"] = "; ".join(problems) or None
        res["surfaces"] = surfaces(DIST, cid, e["summary"], (by_id.get(cid) or {}).get("excerpt"))
        paths.append(f"/story/{cid}/")
        if e.get("archival"):
            arch_path = os.path.join(DIST, "story", cid, "first-edition", "index.html")
            arch = open(arch_path, encoding="utf-8").read() if os.path.exists(arch_path) else ""
            bad = CE.verify_archival_page(arch, e["archival"]["text"], h1=_h1(arch)) if arch else ["no page built"]
            if arch and 'name="robots" content="noindex' not in arch:
                bad.append("not noindex")
            if arch and CE._norm(e["archival"]["note"]) not in CE._norm(arch):
                bad.append("the platform's note is missing")
            placed = arch.count("data-anchored")
            if placed != len(e["archival"].get("anchors") or []):
                bad.append(f"{placed} of {len(e['archival'].get('anchors') or [])} anchored correction(s) placed")
            res["archive"] = "; ".join(bad) or None
            paths.append(f"/story/{cid}/first-edition/")
    for cid, res in results.items():
        if cid not in served:
            res["verify"] = res["surfaces"] = "not built (held)"
    try:
        why = feed_check(list(served.values()), out)
    except Exception as exc:  # noqa: BLE001
        why = f"the feed could not be built ({type(exc).__name__})"
    for res in results.values():
        res["feed"] = why
    live_verify(results, served, out, base_url)
    try:
        _screens(paths, out)
    except Exception as exc:  # noqa: BLE001
        log(f"screenshots failed ({type(exc).__name__}: {exc}); the build is in www/dist")
    return results


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Rehearse every given edition on the real publishing path; writes nothing.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True, help="a PRIVATE directory for the table and screenshots (outside the repo)")
    ap.add_argument("--base-url", default="https://averagejoematt.com")
    args = ap.parse_args(argv)
    try:
        manifest: Any = json.load(open(args.manifest, encoding="utf-8"))
        assert isinstance(manifest, list) and all(isinstance(e, dict) and CE.CHAPTER_ID.match(str(e.get("chapter"))) for e in manifest)
    except (OSError, ValueError, AssertionError) as exc:
        print(f"bad manifest: {exc}", file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)
    try:
        results = rehearse(manifest, args.out, args.base_url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    t = table(results)
    open(os.path.join(args.out, "REHEARSAL_TABLE.md"), "w", encoding="utf-8").write(t + "\n")
    print(t)
    print("rehearsal only: nothing was written. www/dist is a REHEARSAL build — never deploy it.")
    return 0 if all(all(res.get(c) in (None, "n/a") for c in CHECKS) for res in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
