#!/usr/bin/env python3
"""Re-flatten every v4 page's chrome to the single source in `v4_chrome.py` (#1009).

The doors nav and `.site-foot` footer were copy-pasted across ~75 site HTML files and
drifted. This regenerator detects each page's DELIBERATE per-page nav state — which door
is current (`aria-current="page"`) and whether the follow pill is present — then replaces
the page's `<nav class="doors">…</nav>` and `<footer class="site-foot">…</footer>` with
the canonical partial output for that state. Everything else on the page is untouched.

It is idempotent (running twice is a no-op) and is the AUTHORITATIVE post-build chrome
pass: run it after any `v4_build_*` build so generator-local chrome can't re-drift.

Footer standardization (#1104): a page that carries the doors nav is a content page and
must carry the canonical `.site-foot` footer. Pages that instead ship a historical slim
variant (`.story-foot` on home/404, `.dx-foot-bar` on privacy/subscribe/confirm) get the
variant REPLACED in place with the canonical footer; a chrome-bearing page with no footer
at all gets the canonical footer inserted before `</body>`. Home's live "updated" stamp
(`data-bind="asof"`) is a third deliberate axis — detected on the old footer (canonical
or variant) and preserved via `site_footer(with_asof=True)`. Pages with NO doors nav —
the `/mind/` and `/subscribe.html` redirect stubs — are untouched by construction.

Loop-forward close (#1468): every doors-nav page also gets a canonical `.loop-forward`
"next station on the loop" CTA inserted immediately before the footer, keyed off the SAME
detected door as the nav — see `v4_chrome.loop_forward` for the mapping and why it's the
right signal. This is what makes "zero dead-end pages" a structural guarantee rather than
a per-generator opt-in: any page with a doors nav gets one, full stop.

Head chrome (#1639): every content page's `<head>` icon/manifest/theme-color block is
flattened to `v4_chrome.head_chrome()` — the `.ico` fallback, the SVG favicon, the
manifest, apple-touch-icon, and the light/dark theme-color pair. Before this the block
was a copy-pasted f-string literal in ~10 generators and had drifted (only 21 of 79
pages shipped the manifest/apple-touch-icon, 24 the theme-color pair, none the vector
favicon). Now it gets the same single-source + `--check` gate the nav/footer already
have. Only chrome-bearing pages are touched, and a page is only given the block if it
already carries at least one head-chrome tag to anchor on, so the redirect stubs and
authoring fragments (which have none) can never be handed one.

  python3 scripts/v4_apply_chrome.py            # rewrite in place, print summary
  python3 scripts/v4_apply_chrome.py --check    # exit 1 if any page would change (CI)

Excludes `site/legacy/**` (the frozen old site — never touched).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v4_chrome  # noqa: E402

SITE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")

# The doors nav is terminated by its theme-toggle <button>, then (canonically) </nav>.
# We anchor on the toggle and make </nav> OPTIONAL because one page (now/index.html)
# ships a doors nav with no </nav> tag (the browser auto-closes it at the parent </div>);
# a plain `<nav class="doors">.*?</nav>` there over-matches into downstream markup.
NAV_RE = re.compile(r'<nav class="doors".*?<button class="theme-toggle"[^>]*>.*?</button>(?:\s*</nav>)?', re.DOTALL)
NAV_OPEN = '<nav class="doors"'
FOOT_RE = re.compile(r'<footer class="site-foot".*?</footer>', re.DOTALL)
# The retired slim variants (#1104): story-foot (home, 404) and dx-foot-bar (privacy,
# subscribe, subscribe/confirm). On a doors-nav page these are converted to the
# canonical footer; the regexes stay so a hand-authored regression gets re-flattened.
VARIANT_FOOT_RE = re.compile(r'<footer class="(?:story-foot|dx-foot-bar)".*?</footer>', re.DOTALL)
LOOP_FWD_RE = re.compile(r'<aside class="loop-forward".*?</aside>', re.DOTALL)
CURRENT_RE = re.compile(r'<a href="([^"]+)"[^>]*aria-current="page"')
FOLLOW_RE = re.compile(r'class="nav-follow"')
ASOF_RE = re.compile(r'data-bind="asof"')

# #1639: the <head> icon/manifest/theme-color chrome. This matches any ONE canonical
# head-chrome tag — the theme-color metas, and the icon/manifest/apple-touch-icon links
# in whatever attribute form they've drifted into (`sizes="180x180"`, the raster-only
# `.ico`, the SVG favicon) — INCLUDING its leading indentation and trailing newline, so
# a whole line is consumed cleanly. It deliberately does NOT match the apple-mobile-web-app
# metas or the service-worker registration (index-only PWA shell, not part of this block).
# `rel="icon"` and `rel="apple-touch-icon"` don't overlap: the alternation anchors on the
# closing quote, so `rel="icon"` cannot match inside `rel="apple-touch-icon"`.
HEAD_CHROME_TAG_RE = re.compile(
    r"[ \t]*(?:" r'<meta name="theme-color"[^>]*>' r'|<link\b[^>]*\brel="(?:icon|manifest|apple-touch-icon)"[^>]*>' r")[ \t]*\n?"
)
HEAD_OPEN_RE = re.compile(r"<head[^>]*>")
HEAD_CLOSE = "</head>"


def iter_html_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        # prune the frozen legacy tree
        dirnames[:] = [d for d in dirnames if not (dirpath == root and d == "legacy")]
        if os.sep + "legacy" + os.sep in dirpath + os.sep:
            continue
        for name in sorted(filenames):
            if name.endswith(".html"):
                yield os.path.join(dirpath, name)


def url_path(rel: str) -> str:
    """Map a site/-relative file path to its viewer URL path (mirrors S3/CloudFront)."""
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def detect_nav_state(nav_html: str):
    """Return (current_door, with_follow) for an existing doors nav."""
    m = CURRENT_RE.search(nav_html)
    current_door = m.group(1) if m else None
    with_follow = bool(FOLLOW_RE.search(nav_html))
    return current_door, with_follow


def apply_head_chrome(html: str):
    """Flatten the <head> icon/manifest/theme-color chrome to `v4_chrome.head_chrome()`.

    Every canonical head-chrome tag (theme-color pair, `.ico`, SVG favicon, manifest,
    apple-touch-icon) is stripped from `<head>` wherever it has drifted to, and the single
    canonical block is (re)inserted at the position of the FIRST such tag — the natural
    anchor, present on every content page as the pre-existing `.ico` link. Only the region
    between `<head>` and `</head>` is touched, so no `<body>` markup can be caught. Runs
    ONLY when the page already carries at least one head-chrome tag, so a chrome-free
    redirect stub or authoring fragment can never be handed a block. Idempotent: on an
    already-canonical head, strip-all-then-reinsert-at-the-same-anchor is a byte no-op.

    Returns (new_html, changed).
    """
    head_open = HEAD_OPEN_RE.search(html)
    if not head_open:
        return html, False
    head_start = head_open.end()
    head_end = html.find(HEAD_CLOSE, head_start)
    if head_end == -1:
        return html, False

    head = html[head_start:head_end]
    matches = list(HEAD_CHROME_TAG_RE.finditer(head))
    if not matches:
        # No existing head chrome — not even the `.ico`. By construction this is a
        # chrome-free stub/fragment; never inject a block into one.
        return html, False

    anchor = matches[0].start()
    new_head = head
    for m in reversed(matches):
        new_head = new_head[: m.start()] + new_head[m.end() :]
    block = v4_chrome.head_chrome() + "\n"
    new_head = new_head[:anchor] + block + new_head[anchor:]

    new_html = html[:head_start] + new_head + html[head_end:]
    return new_html, (new_html != html)


def rewrite(html: str, self_path: str | None = None):
    """Return (new_html, nav_changed, foot_changed, door, follow, gained_icons, foot_converted, lf_changed, head_changed)."""
    nav_changed = foot_changed = gained_icons = foot_converted = lf_changed = head_changed = False
    door = None
    follow = False

    nav_m = NAV_RE.search(html)
    if NAV_OPEN in html and not nav_m:
        raise RuntimeError('found a `<nav class="doors"` with no theme-toggle terminator — refusing to guess its boundary')
    if nav_m:
        old_nav = nav_m.group(0)
        door, follow = detect_nav_state(old_nav)
        new_nav = v4_chrome.doors_nav(door, follow)
        if new_nav != old_nav:
            nav_changed = True
            gained_icons = "ico-door" not in old_nav
            html = html[: nav_m.start()] + new_nav + html[nav_m.end() :]

    # #1468: the loop-forward close, keyed off the same detected door. Every doors-nav
    # page gets exactly one, inserted immediately before the footer (whichever form the
    # footer takes below) so no chrome-bearing page can be a dead end.
    if nav_m:
        new_lf = v4_chrome.loop_forward(door, self_path=self_path)
        lf_m = LOOP_FWD_RE.search(html)
        if lf_m:
            if lf_m.group(0) != new_lf:
                lf_changed = True
                html = html[: lf_m.start()] + new_lf + html[lf_m.end() :]
        else:
            anchor_m = FOOT_RE.search(html) or VARIANT_FOOT_RE.search(html)
            insert_at = anchor_m.start() if anchor_m else html.rfind("</body>")
            if insert_at == -1:
                raise RuntimeError("chrome-bearing page has no footer/</body> — refusing to guess the loop-forward insert point")
            html = html[:insert_at] + new_lf + html[insert_at:]
            lf_changed = True

    foot_m = FOOT_RE.search(html)
    if foot_m:
        old_foot = foot_m.group(0)
        new_foot = v4_chrome.site_footer(with_asof=bool(ASOF_RE.search(old_foot)))
        if new_foot != old_foot:
            foot_changed = True
            html = html[: foot_m.start()] + new_foot + html[foot_m.end() :]
    elif nav_m:
        # #1104: a doors-nav page is a content page — it must carry the canonical
        # footer. Convert a slim variant (story-foot / dx-foot-bar) in place — keeping
        # the live asof stamp if the old footer carried one — or, if the page has no
        # footer at all, insert the canonical one just before </body>.
        var_m = VARIANT_FOOT_RE.search(html)
        if var_m:
            new_foot = v4_chrome.site_footer(with_asof=bool(ASOF_RE.search(var_m.group(0))))
            html = html[: var_m.start()] + new_foot + html[var_m.end() :]
        else:
            body_at = html.rfind("</body>")
            if body_at == -1:
                raise RuntimeError("chrome-bearing page has no footer and no </body> — refusing to guess the insert point")
            html = html[:body_at] + v4_chrome.site_footer() + "\n" + html[body_at:]
        foot_changed = foot_converted = True

    # #1639: flatten the <head> icon/manifest/theme-color chrome. Gated on the same
    # signal as the rest of this pass — a page with a doors nav OR a canonical footer is
    # a content page and must carry the full head block; the 3 chrome-free stubs/fragments
    # never reach here (main() filters them) and carry no head-chrome tag to anchor on.
    html, head_changed = apply_head_chrome(html)

    return html, nav_changed, foot_changed, door, follow, gained_icons, foot_converted, lf_changed, head_changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Flatten site chrome to v4_chrome.py")
    ap.add_argument("--check", action="store_true", help="exit 1 if any page would change (no writes)")
    args = ap.parse_args()

    nav_changed = []
    foot_changed = []
    foot_converted = []
    gained_icons = []
    lf_changed = []
    head_changed = []
    by_door: dict[str | None, int] = {}
    follow_count = 0
    total = 0

    for path in iter_html_files(SITE_ROOT):
        original = open(path, encoding="utf-8").read()
        if '<nav class="doors"' not in original and '<footer class="site-foot"' not in original:
            continue
        total += 1
        rel = os.path.relpath(path, SITE_ROOT)
        new, nc, fc, door, follow, gi, conv, lf, hc = rewrite(original, self_path=url_path(rel))
        if '<nav class="doors"' in original:
            by_door[door] = by_door.get(door, 0) + 1
            if follow:
                follow_count += 1
        if nc:
            nav_changed.append(rel)
        if fc:
            foot_changed.append(rel)
        if conv:
            foot_converted.append(rel)
        if gi:
            gained_icons.append(rel)
        if lf:
            lf_changed.append(rel)
        if hc:
            head_changed.append(rel)
        if new != original and not args.check:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)

    print(f"Scanned {total} chrome-bearing pages under {SITE_ROOT} (legacy excluded).")
    print(f"  nav rewritten:    {len(nav_changed)}")
    print(f"  footer rewritten: {len(foot_changed)}")
    print(f"  loop-forward inserted/rewritten: {len(lf_changed)}")
    print(f"  head chrome flattened: {len(head_changed)}")
    print(f"  variant/missing footers converted to canonical: {len(foot_converted)}")
    for rel in foot_converted:
        print(f"      + {rel}")
    print(f"  icon-less navs that GAINED door icons: {len(gained_icons)}")
    for rel in gained_icons:
        print(f"      + {rel}")
    print("  nav current-door buckets (detected & preserved):")
    for door in sorted(by_door, key=lambda d: (d is None, d)):
        print(f"      {door if door is not None else '(none)':<12} {by_door[door]}")
    print(f"  follow-pill pages (detected & preserved): {follow_count}")

    if args.check and (nav_changed or foot_changed or lf_changed or head_changed):
        print("\nCHECK FAILED: chrome is out of sync with v4_chrome.py — run without --check.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
