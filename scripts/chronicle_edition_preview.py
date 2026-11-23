#!/usr/bin/env python3
"""scripts/chronicle_edition_preview.py — render a PROPOSED edition on the real site, locally, before anything is public (#6193).

Owner ruling 2026-11-22 (final approval §1, §11): an edition is released only after "real-site rendering checks" — the
chapter rendered at phone and desktop width — and before publication. This builds the v9 site LOCALLY from a LIVE
snapshot of the public site (read-only HTTPS), with ONE proposed edition (and, optionally, its archival rendering)
placed in the snapshot as if approved, serves the build on 127.0.0.1 and screenshots the chapter page (and the
first-edition page) at 390 px and 1280 px. Nothing is written to AWS, nothing is synced, no record is created.

The edition text is read from a PRIVATE file (never commit it). The edition line's revision date is today's date as a
placeholder — the real one is stamped by the approval. The publication gates are run and printed (content filter,
truth checks, and the private-call record when the laptop's read-only credentials can open it); the page renders
either way, because this is a check, not a publication.

    python3 scripts/chronicle_edition_preview.py --chapter week-12 --text-file <private>/week10_second_edition.md \\
        [--archival-file <private>/week10_archival.md] [--out <private dir for screenshots>]

Leaves www/dist as the preview build (NEVER deploy it — rebuild before any deploy) and restores www/owned_paths.json
and www/reach.json byte for byte. Exit: 0 rendered · 2 bad input · 3 build or screenshot failed.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(REPO, "www")
SNAPSHOT = os.path.join(WWW, "content", "snapshot")
sys.path.insert(0, os.path.join(REPO, "lambdas"))
from content import chapter_editions as CE, private_call_check  # noqa: E402

WIDTHS = {"phone": (390, 844), "desktop": (1280, 900)}


def preview_records(chapter_id: str, text: str, first_published: str, archival: str | None, today: str, as_of: str | None = None) -> list:
    """In-memory records shaped as approved, for rendering ONLY (never written anywhere)."""
    now = f"{today}T00:00:00Z"
    original = CE.original_record(
        chapter_id=chapter_id,
        row_sk="DATE#preview",
        backup_prefix=f"{CE.BACKUP_ROOT}{chapter_id}/preview/",
        objects=[{"source": "ddb:DATE#preview", "backup_key": f"{CE.BACKUP_ROOT}{chapter_id}/preview/row.json", "sha256": "0" * 64}],
        backed_up_at="2000-01-01T00:00:00Z",
    )
    ed = CE.new_edition(chapter_id=chapter_id, edition=2, text=text, first_published=first_published, proposed_at=now)
    ed.update(
        approvals=[CE.approval(at=now, dated_on=today, sha256=ed["text_sha256"])],
        approved_at=now,
        revised_on=today,
        signature=CE.signature(2, today),
    )
    rows = [original, CE.restore_record(original=original, verified_at="2000-01-01T00:00:00Z"), ed]
    if archival:
        a = CE.new_archival(chapter_id=chapter_id, archival_id=1, text=archival, proposed_at=now, as_of=as_of)
        a.update(approvals=[CE.approval(at=now, dated_on=today, sha256=a["text_sha256"])], approved_at=now, approved_on=today)
        rows.append(a)
    return rows


def _tainted_or_none():
    try:
        import boto3  # noqa: PLC0415
        from web import narrative_publication as NPub, publication_snapshot as PS  # noqa: PLC0415

        NPub.begin_request()
        PS.begin_request(boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform"))
        PS.complete()
        return NPub.is_tainted
    except Exception as exc:  # noqa: BLE001
        print(f"  (the private-call record could not be opened read-only: {type(exc).__name__}; that gate is reported as unchecked)")
        return None


def _private_calls_or_none():
    """#6199: the calls the publication policy classifies, read-only; None (reported as a refusal) when unreadable."""
    try:
        import boto3  # noqa: PLC0415

        return private_call_check.load(boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform"))
    except Exception as exc:  # noqa: BLE001
        print(f"  (the coach calls could not be read: {type(exc).__name__}; the private-call check refuses)")
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render a proposed edition locally and screenshot it; publishes nothing.")
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--archival-file")
    ap.add_argument("--archival-as-of", default=None, help="the day the archival text stood (a chapter rewritten after publication)")
    ap.add_argument("--out", default=None, help="screenshot directory (default: a temp dir); keep it outside the repo")
    ap.add_argument("--base-url", default="https://averagejoematt.com")
    args = ap.parse_args(argv)
    text = open(args.text_file, encoding="utf-8").read()
    archival = open(args.archival_file, encoding="utf-8").read() if args.archival_file else None
    print(f"edition text sha256 {CE.text_sha256(text.replace(chr(13) + chr(10), chr(10)).strip())}")
    tainted = _tainted_or_none()
    calls = _private_calls_or_none()
    for what, t in (("edition", text), ("archival", archival)):
        if t is not None:
            from privacy import privacy_guard  # noqa: PLC0415 — the real content filter (local channel or read-only S3)

            findings = CE.gate_findings(
                t, tainted=tainted, private_calls=private_call_check.for_text(calls), filter_hits=privacy_guard.find_violations
            )
            print(f"gates on the {what}: {'clean' if not findings else ''}")
            for f in findings:
                print(f"  - {f}")
    saved = {p: open(p, "rb").read() for p in (os.path.join(WWW, "owned_paths.json"), os.path.join(WWW, "reach.json"))}
    try:
        cp = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO, "scripts", "publish_snapshot.py"),
                "--mode",
                "live",
                "--out",
                SNAPSHOT,
                "--base-url",
                args.base_url,
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            print(cp.stderr[-2000:], file=sys.stderr)
            return 3
        chapters = json.load(open(os.path.join(SNAPSHOT, "chapters.json"), encoding="utf-8"))
        chapter = next((c for c in chapters if c.get("id") == args.chapter and c.get("status") == "published"), None)
        if chapter is None:
            print(f"{args.chapter} is not a published chapter of the live snapshot", file=sys.stderr)
            return 2
        first = str(chapter.get("published_at") or "")[:10]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            rows = preview_records(args.chapter, text, first, archival, today, args.archival_as_of)
        except CE.EditionError as exc:
            print(f"bad input: {exc}", file=sys.stderr)
            return 2
        # rendering only; the gates (the private-call check included) ran above
        view = CE.public_view(
            rows, tainted=lambda _t: False, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: [], log=print
        )
        # the build's own per-edition holds (B4 title/summary, B9 archive address, as_of), exactly as a release would apply them
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import publish_snapshot_chapter_editions as exporter  # noqa: PLC0415

        try:
            corrections = json.load(open(os.path.join(SNAPSHOT, "chapter_corrections.json"), encoding="utf-8"))
        except (OSError, ValueError):
            corrections = None
        doc = exporter.validate({"state": "ok", "source": ["/api/chapters"], "editions": view}, {"chapter": chapters}, corrections)
        with open(os.path.join(SNAPSHOT, "chapter_editions.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        cp = subprocess.run(["npm", "run", "build", "--silent"], cwd=WWW, capture_output=True, text=True)
        if cp.returncode != 0:
            print(cp.stderr[-2000:], file=sys.stderr)
            return 3
    finally:
        for p, b in saved.items():
            open(p, "wb").write(b)
    out = args.out or os.path.join(os.environ.get("TMPDIR", "/tmp"), f"edition-preview-{args.chapter}")
    os.makedirs(out, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.path.join(WWW, "dist"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    paths = [f"/story/{args.chapter}/"] + ([f"/story/{args.chapter}/first-edition/"] if archival else [])
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        with sync_playwright() as p:
            browser = p.chromium.launch()
            for path in paths:
                for name, (w, h) in WIDTHS.items():
                    page = browser.new_page(viewport={"width": w, "height": h})
                    page.goto(f"http://127.0.0.1:{srv.server_port}{path}", wait_until="networkidle")
                    png = os.path.join(out, f"{path.strip('/').replace('/', '_')}_{name}.png")
                    page.screenshot(path=png, full_page=True)
                    print(f"screenshot {png}")
                    page.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"screenshots failed ({type(exc).__name__}: {exc}); the build is in www/dist", file=sys.stderr)
        return 3
    finally:
        srv.shutdown()
    print("rendered locally only. www/dist is a PREVIEW build — never deploy it; rebuild from the real snapshot first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
