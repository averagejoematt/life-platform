#!/usr/bin/env python3
"""
hash_site_assets.py — content-hash the site's CSS/JS and rewrite EVERY reference to
them, across HTML <link>/<script> tags, intra-module `import ... from "/assets/js/*"`
statements, and CSS.

Why this exists (the "frozen page" bug, 2026-07-03):
  The old bash hashing rewrote references ONLY in *.html. It hashed the entry module
  (evidence.js -> evidence.<hash>.js, served immutable/1yr) but left the
  `import ... from "/assets/js/charts.js"` statements INSIDE the modules pointing at
  the UNHASHED, mutable, 24h-cached URL. When a deploy changed both evidence.js and
  charts.js, a returning browser could pair a fresh entry module with a stale cached
  dependency; the ES module graph threw at load time and the page rendered only its
  static shell (the "freeze"). A hard reload bypassed the cache and fixed it until the
  next restart.

  The fix: hash the WHOLE module graph in dependency order (leaves first) and rewrite
  the intra-module imports too, so every asset URL is content-hashed and immutable.
  A given entry module then pins the exact hashed bytes of every transitive dependency
  forever — no version skew is possible.

Behavior:
  - Globs assets/css/*.css and assets/js/*.js under <build_dir> (NOT legacy/assets —
    legacy is served verbatim with unhashed assets).
  - Orders files leaves-first via the module-import graph, so a dependency's hash is
    known before its dependents are hashed (dependent content, and thus its hash,
    reflects the dependency hash — textbook cache-correct hashing).
  - Writes `name.<hash>.ext` alongside each file AND rewrites the original in place
    (kept as a short-cache fallback upload) so both are self-consistent.
  - Rewrites references in all non-legacy *.html.

Usage:  python3 deploy/hash_site_assets.py <build_dir>
Exits non-zero on any error (import cycle, dangling ref) so a bad graph fails the
deploy loudly instead of shipping.
"""
import glob
import hashlib
import os
import re
import sys

# Matches a reference to a hashable asset: /assets/js/foo.js or /assets/css/foo.css.
# Anchored on the /assets/(js|css)/ path so it never touches fonts, images, or the
# SVG sprite. Group 1 = subdir, group 2 = basename-with-extension.
ASSET_REF_RE = re.compile(r"/assets/(js|css)/([A-Za-z0-9_.-]+\.(?:js|css))")


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _rewrite(text, mapping):
    """Replace every /assets/{js,css}/<orig> with its hashed name from `mapping`."""

    def repl(m):
        base = m.group(2)
        if base in mapping:
            return "/assets/%s/%s" % (m.group(1), mapping[base])
        return m.group(0)

    return ASSET_REF_RE.sub(repl, text)


def _toposort(deps):
    """Return basenames ordered dependencies-before-dependents. Raises on a cycle."""
    order = []
    state = {}  # 0=unvisited, 1=visiting, 2=done

    def visit(node, stack):
        st = state.get(node, 0)
        if st == 2:
            return
        if st == 1:
            raise SystemExit("❌ asset import cycle: %s" % " -> ".join(stack + [node]))
        state[node] = 1
        for dep in sorted(deps.get(node, ())):
            visit(dep, stack + [node])
        state[node] = 2
        order.append(node)

    for node in sorted(deps):
        visit(node, [])
    return order


def main(build_dir):
    assets = []
    for sub, ext in (("css", "css"), ("js", "js")):
        assets.extend(sorted(glob.glob(os.path.join(build_dir, "assets", sub, "*.%s" % ext))))
    if not assets:
        print("  (no hashable assets found — nothing to do)")
        return 0

    by_base = {os.path.basename(p): p for p in assets}

    # Dependency edges from the ORIGINAL content (before any rewriting).
    deps = {}
    for path in assets:
        base = os.path.basename(path)
        refs = {m.group(2) for m in ASSET_REF_RE.finditer(_read(path))}
        deps[base] = {r for r in refs if r in by_base and r != base}

    mapping = {}  # orig basename -> hashed basename
    for base in _toposort(deps):
        path = by_base[base]
        text = _rewrite(_read(path), mapping)  # point at already-hashed deps
        digest = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        name, ext = base.rsplit(".", 1)
        hashed = "%s.%s.%s" % (name, digest, ext)
        mapping[base] = hashed
        _write(os.path.join(os.path.dirname(path), hashed), text)  # immutable copy
        _write(path, text)  # fallback original, refs rewritten too
        print("  %s → %s" % (base, hashed))

    # Rewrite references in every non-legacy HTML page.
    html_count = 0
    for root, _dirs, files in os.walk(build_dir):
        if (os.sep + "legacy" + os.sep) in (root + os.sep):
            continue
        for fn in files:
            if not fn.endswith(".html"):
                continue
            fp = os.path.join(root, fn)
            original = _read(fp)
            rewritten = _rewrite(original, mapping)
            if rewritten != original:
                _write(fp, rewritten)
                html_count += 1

    print("  Hashed %d assets; rewrote %d HTML files." % (len(mapping), html_count))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: hash_site_assets.py <build_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
