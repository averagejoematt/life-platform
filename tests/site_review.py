#!/usr/bin/env python3
"""
site_review.py — capture + corroborate harness for the holistic /site-review.

The companion to the gating tests/visual_qa.py. visual_qa answers "did it render";
this builds the REVIEW PACKET a human-in-the-loop reviewer (Claude Code, via the
/site-review skill) reads to judge whether each page's STORY lands and whether the
DATA shown corroborates the source of truth.

Per run it produces  qa-screenshots/<YYYY-MM-DD>/  containing:
  • <slug>.png / <slug>-mobile.png / <slug>-chart*.png  — same capture as visual_qa
    (reuses visual_qa.capture_page — no fork of the CI harness)
  • api/<endpoint>.json   — the JSON each page is built from (deduped across pages)
  • consistency.json      — deterministic cross-page metric agreement (weight, level…)
  • manifest.json         — the index the skill reads first (pages in narrative order,
                            screenshots, inline metric values, render status)
  • annotations/          — drop-zone: the user drops marked-up <slug>-*.png here and
                            the skill treats them as directed, top-priority findings

This is NOT wired into CI (visual_qa stays the gate). Phase 1 runs no Bedrock — $0;
Claude Code's own vision reads the PNGs. The --no-ai flag is an inert hook so the
Phase-2 panel Lambda can share this module.

Usage:
    python3 tests/site_review.py                     # full site, today's folder
    python3 tests/site_review.py --door story        # one door (weekly cadence default)
    python3 tests/site_review.py --page /now/         # single page deep-dive
    python3 tests/site_review.py --from-report qa-screenshots   # augment a prior CI capture
    python3 tests/site_review.py --date 2026-06-20    # explicit run folder
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import site_review_bindings as B  # noqa: E402
import visual_qa  # noqa: E402

SITE_URL = visual_qa.SITE_URL
ROOT = os.path.abspath(os.path.join(HERE, ".."))


# ── small utilities ───────────────────────────────────────────────────────────
def _slug_for_path(path):
    """Screenshot slug — identical formula to visual_qa.capture_page."""
    return path.strip("/").replace("/", "-") or "home"


def _slug_for_endpoint(url):
    """Stable filename stem for a captured endpoint JSON."""
    s = url.lstrip("/")
    for ch in "/?=&":
        s = s.replace(ch, "-")
    return s.strip("-")


def _dig(obj, dotted):
    """Read a dotted path (e.g. 'journey.journey.current_weight_lbs'); None if absent."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _selected_pages(args):
    """visual_qa.PAGES filtered to --page / --door, else all."""
    pages = visual_qa.PAGES
    if args.page:
        pages = [p for p in pages if p["path"] == args.page]
        if not pages:
            sys.exit(f"Unknown page {args.page!r}. Known: {', '.join(p['path'] for p in visual_qa.PAGES)}")
    elif args.door:
        want = {b["path"] for b in B.PAGE_BINDINGS if b["door"] == args.door}
        pages = [p for p in pages if p["path"] in want]
        if not pages:
            sys.exit(f"No pages for door {args.door!r}. Doors: home, cockpit, story, evidence")
    return pages


# ── capture ─────────────────────────────────────────────────────────────────────
def capture_screenshots(pages, run_dir):
    """Drive visual_qa.capture_page over `pages` into run_dir. Returns results list."""
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        for page_def in pages:
            r = visual_qa.capture_page(context, page_def, run_dir, save_screenshots=True)
            results.append(r)
            icon = "✅" if not r["issues"] else "❌"
            print(f"  {icon} {r['page']} ({r['path']})")
            for x in r["issues"]:
                print(f"      → {x}")
        browser.close()
    return results


def fetch_api(pages, run_dir):
    """Fetch every bound endpoint for the selected pages (deduped) into run_dir/api/.

    Uses stdlib urllib (project convention — no requests). The site is public and
    CloudFront serves the same bytes the page itself fetches. Returns
    {url: {"file","status","ok"}}.
    """
    api_dir = os.path.join(run_dir, "api")
    os.makedirs(api_dir, exist_ok=True)
    wanted = []
    for b in pages_bindings(pages):
        for ep in b["endpoints"]:
            if ep["url"] not in [w["url"] for w in wanted]:
                wanted.append(ep)
    out = {}
    for ep in wanted:
        url = ep["url"]
        fname = _slug_for_endpoint(url) + ".json"
        fpath = os.path.join(api_dir, fname)
        status, ok = None, False
        try:
            req = urllib.request.Request(SITE_URL + url, headers={"User-Agent": "site-review/1.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
                with open(fpath, "w") as f:
                    json.dump(parsed, f, indent=2)
                ok = True
            except json.JSONDecodeError:
                with open(fpath, "w") as f:
                    f.write(raw)
                ok = False
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:  # noqa: BLE001
            status = f"ERR:{type(e).__name__}"
        out[url] = {"file": f"api/{fname}", "status": status, "ok": ok}
        print(f"  {'✅' if ok else '⚠️ '} {url} → {status}")
    return out


def pages_bindings(pages):
    """The binding records matching the selected visual_qa page defs (order preserved)."""
    out = []
    for pg in pages:
        b = B.bindings_for(pg["path"])
        if b:
            out.append(b)
    return out


# ── cross-page consistency ──────────────────────────────────────────────────────
def cross_page_consistency(run_dir, api_index):
    """Compare each canonical metric across the endpoints that should agree.

    Loads the captured JSON for each (metric, endpoint) observation, digs the value,
    and flags any metric whose distinct-endpoint values differ beyond tolerance.
    A disagreement is a HIGH data-integrity finding (the "weight = 305 on Home but
    306 on Cockpit" class nobody catches today).
    """
    api_dir = os.path.join(run_dir, "api")
    checks = []
    for name, observations in B.metric_observations().items():
        by_endpoint = {}  # url -> value (dedupe; same endpoint = same value)
        for _page_path, url, json_path in observations:
            if url in by_endpoint:
                continue
            meta = api_index.get(url)
            if not meta or not meta.get("ok"):
                continue
            fpath = os.path.join(api_dir, os.path.basename(meta["file"]))
            try:
                with open(fpath) as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            val = _dig(data, json_path)
            if isinstance(val, (int, float)):
                by_endpoint[url] = float(val)
        if len(by_endpoint) < 2:
            continue  # nothing to cross-check
        vals = list(by_endpoint.values())
        max_delta = max(vals) - min(vals)
        tol = B.METRIC_TOLERANCE.get(name, 0.0)
        agree = max_delta <= tol
        checks.append(
            {
                "metric": name,
                "sources": [{"endpoint": u, "value": v} for u, v in by_endpoint.items()],
                "max_delta": round(max_delta, 4),
                "tolerance": tol,
                "agree": agree,
                "severity": "ok" if agree else "high",
            }
        )
    disagreements = [c for c in checks if not c["agree"]]
    return {"checked": len(checks), "disagreements": len(disagreements), "checks": checks}


# ── manifest ──────────────────────────────────────────────────────────────────
def build_manifest(run_dir, pages, results, api_index, consistency, run_date):
    """Assemble the index the skill reads first."""
    by_path = {r["path"]: r for r in results}
    page_records = []
    for b in sorted(pages_bindings(pages), key=lambda x: x["narrative_order"]):
        slug = _slug_for_path(b["path"])
        shots = {}
        full = f"{slug}.png"
        mobile = f"{slug}-mobile.png"
        if os.path.exists(os.path.join(run_dir, full)):
            shots["full"] = full
        if os.path.exists(os.path.join(run_dir, mobile)):
            shots["mobile"] = mobile
        charts = []
        for i in range(6):
            c = f"{slug}-chart{i}.png"
            if os.path.exists(os.path.join(run_dir, c)):
                charts.append(c)
        if charts:
            shots["charts"] = charts

        api_records = []
        for ep in b["endpoints"]:
            meta = api_index.get(ep["url"], {})
            metric_vals = {}
            if meta.get("ok") and ep.get("metrics"):
                try:
                    with open(os.path.join(run_dir, "api", os.path.basename(meta["file"]))) as f:
                        data = json.load(f)
                    for m in ep["metrics"]:
                        metric_vals[m["name"]] = _dig(data, m["path"])
                except Exception:  # noqa: BLE001
                    pass
            api_records.append(
                {
                    "url": ep["url"],
                    "role": ep["role"],
                    "file": meta.get("file"),
                    "status": meta.get("status"),
                    "metrics": metric_vals,
                }
            )

        r = by_path.get(b["path"], {})
        page_records.append(
            {
                "path": b["path"],
                "name": b["name"],
                "door": b["door"],
                "narrative_order": b["narrative_order"],
                "story_intent": b["story_intent"],
                "screenshots": shots,
                "api": api_records,
                "render_status": r.get("status", "n/a"),
                "render_issues": r.get("issues", []),
                "render_warnings": r.get("warnings", []),
            }
        )

    return {
        "date": run_date,
        "site": SITE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_count": len(page_records),
        "pages": page_records,
        "consistency_summary": {"checked": consistency["checked"], "disagreements": consistency["disagreements"]},
    }


# ── main ────────────────────────────────────────────────────────────────────────
def run(args):
    run_date = args.date or date.today().isoformat()
    if args.from_report:
        run_dir = os.path.abspath(args.from_report)
        if not os.path.isdir(run_dir):
            sys.exit(f"--from-report dir not found: {run_dir}")
    else:
        run_dir = os.path.join(ROOT, "qa-screenshots", run_date)
    os.makedirs(run_dir, exist_ok=True)
    annotations = os.path.join(run_dir, "annotations")
    os.makedirs(annotations, exist_ok=True)
    open(os.path.join(annotations, ".gitkeep"), "a").close()

    pages = _selected_pages(args)
    print(f"\nSite review packet → {run_dir}\n{'=' * 60}")

    if args.from_report:
        print(f"Augmenting existing capture in {run_dir} (no re-screenshot).")
        report = os.path.join(run_dir, "report.json")
        results = json.load(open(report))["results"] if os.path.exists(report) else []
    else:
        print(f"Capturing {len(pages)} page(s)…")
        results = capture_screenshots(pages, run_dir)

    print("\nFetching bound API endpoints…")
    api_index = fetch_api(pages, run_dir)

    print("\nCross-page consistency…")
    consistency = cross_page_consistency(run_dir, api_index)
    with open(os.path.join(run_dir, "consistency.json"), "w") as f:
        json.dump(consistency, f, indent=2)
    for c in consistency["checks"]:
        icon = "✅" if c["agree"] else "🔴"
        srcs = ", ".join(f"{s['endpoint']}={s['value']}" for s in c["sources"])
        print(f"  {icon} {c['metric']}: {srcs} (Δ{c['max_delta']} tol {c['tolerance']})")

    manifest = build_manifest(run_dir, pages, results, api_index, consistency, run_date)
    with open(os.path.join(run_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    n_png = len([x for x in os.listdir(run_dir) if x.endswith(".png")])
    print(f"\n{'=' * 60}")
    print(f"Packet ready: {manifest['page_count']} pages · {n_png} PNGs · {len(api_index)} endpoints")
    print(f"Consistency: {consistency['checked']} checked, {consistency['disagreements']} disagreement(s)")
    print(f"Review with:  /site-review review {run_date}")
    return consistency["disagreements"] == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Capture + corroborate a site-review packet for averagejoematt.com")
    ap.add_argument("--date", help="Run folder date (YYYY-MM-DD); default today")
    ap.add_argument("--page", help="Single page path, e.g. /now/")
    ap.add_argument("--door", choices=["home", "cockpit", "story", "evidence"], help="Limit to one door")
    ap.add_argument("--from-report", help="Augment an existing capture dir (skip Playwright)")
    ap.add_argument("--no-ai", action="store_true", help="(inert in Phase 1; reserved for the Phase-2 panel)")
    sys.exit(0 if run(ap.parse_args()) else 1)
