#!/usr/bin/env python3
"""
deploy_sprint11_nav.py — Sprint 11: Nav restructure + /glucose/ + /sleep/ discovery

CHANGES:
  1. Top nav: replace "About" with "Explore" (→ /start/)
     About moves to overlay + footer only — it's the lowest-click nav item.
     "Explore" gives first-time visitors 2-click access to all 30+ pages.
  2. Mobile overlay: add Progress, Benchmarks, Supplements, Glucose, Sleep to
     The Data section (B05 fix + new pages).
  3. Footer-v2: add Glucose, Sleep to The Data column.
  4. About added to overlay Journey section (was missing after nav change).

RUN:
  python3 deploy/deploy_sprint11_nav.py
  python3 deploy/deploy_sprint11_nav.py --dry-run   # preview only

AFTER:
  bash deploy/sync_site_to_s3.sh
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
"""
import os
import re
import sys

DRY_RUN = '--dry-run' in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')


def find_html_pages():
    pages = []
    for dirpath, dirnames, filenames in os.walk(SITE):
        for f in filenames:
            if f.endswith('.html'):
                pages.append(os.path.join(dirpath, f))
    return sorted(pages)


def get_active_href(filepath):
    rel = os.path.relpath(filepath, SITE).replace('\\', '/')
    if rel == 'index.html':
        return '/'
    parts = rel.split('/')
    if parts[-1] == 'index.html':
        return '/' + '/'.join(parts[:-1]) + '/'
    return '/' + rel


def build_nav(active_href):
    items = [
        ('/story/',    'Story'),
        ('/live/',     'Live'),
        ('/journal/',  'Journal'),
        ('/platform/', 'Platform'),
        ('/start/',    'Explore'),
    ]
    links = '\n    '.join(
        '<a href="{}" class="nav__link{}">{}</a>'.format(
            href, ' active' if href == active_href else '', label
        )
        for href, label in items
    )
    return '''<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    {links}
    <a href="/subscribe/" class="nav__link nav__cta">Subscribe</a>
  </div>
  <button class="nav__hamburger" aria-label="Open menu">
    <span></span><span></span><span></span>
  </button>
  <div class="nav__status">
    <div class="pulse"></div>
    <span id="nav-date"></span>
  </div>
</nav>'''.format(links=links)


OVERLAY_HTML = '''<!-- Mobile overlay menu -->
<div class="nav-overlay">
  <div class="nav-overlay__panel">
    <button class="nav-overlay__close" aria-label="Close menu">&times;</button>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The journey</div>
      <a href="/story/" class="nav-overlay__link">Story</a>
      <a href="/live/" class="nav-overlay__link">Live</a>
      <a href="/journal/" class="nav-overlay__link">Journal</a>
      <a href="/week/" class="nav-overlay__link">This Week</a>
      <a href="/about/" class="nav-overlay__link">About</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The data</div>
      <a href="/character/" class="nav-overlay__link">Character</a>
      <a href="/habits/" class="nav-overlay__link">Habits</a>
      <a href="/achievements/" class="nav-overlay__link">Achievements</a>
      <a href="/discoveries/" class="nav-overlay__link">Discoveries</a>
      <a href="/results/" class="nav-overlay__link">Results</a>
      <a href="/progress/" class="nav-overlay__link">Progress</a>
      <a href="/benchmarks/" class="nav-overlay__link">Benchmarks</a>
      <a href="/supplements/" class="nav-overlay__link">Supplements</a>
      <a href="/glucose/" class="nav-overlay__link">Glucose</a>
      <a href="/sleep/" class="nav-overlay__link">Sleep</a>
      <a href="/explorer/" class="nav-overlay__link">Explorer</a>
      <a href="/experiments/" class="nav-overlay__link">Experiments</a>
      <a href="/protocols/" class="nav-overlay__link">Protocols</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The platform</div>
      <a href="/platform/" class="nav-overlay__link">Platform</a>
      <a href="/intelligence/" class="nav-overlay__link">Intelligence</a>
      <a href="/accountability/" class="nav-overlay__link">Accountability</a>
      <a href="/methodology/" class="nav-overlay__link">Methodology</a>
      <a href="/ask/" class="nav-overlay__link">Ask</a>
      <a href="/board/" class="nav-overlay__link">Board</a>
      <a href="/data/" class="nav-overlay__link">Data</a>
      <a href="/cost/" class="nav-overlay__link">Cost</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">Follow</div>
      <a href="/subscribe/" class="nav-overlay__link nav-overlay__link--cta">Subscribe</a>
      <a href="/rss.xml" class="nav-overlay__link">RSS</a>
    </div>
  </div>
</div>'''


FOOTER_HTML = '''<footer class="footer-v2">
  <div class="footer-v2__grid">
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The journey</div>
      <a href="/story/" class="footer-v2__link">Story</a>
      <a href="/live/" class="footer-v2__link">Live</a>
      <a href="/journal/" class="footer-v2__link">Journal</a>
      <a href="/week/" class="footer-v2__link">This Week</a>
      <a href="/about/" class="footer-v2__link">About</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The data</div>
      <a href="/character/" class="footer-v2__link">Character</a>
      <a href="/habits/" class="footer-v2__link">Habits</a>
      <a href="/achievements/" class="footer-v2__link">Achievements</a>
      <a href="/discoveries/" class="footer-v2__link">Discoveries</a>
      <a href="/results/" class="footer-v2__link">Results</a>
      <a href="/progress/" class="footer-v2__link">Progress</a>
      <a href="/benchmarks/" class="footer-v2__link">Benchmarks</a>
      <a href="/supplements/" class="footer-v2__link">Supplements</a>
      <a href="/glucose/" class="footer-v2__link">Glucose</a>
      <a href="/sleep/" class="footer-v2__link">Sleep</a>
      <a href="/experiments/" class="footer-v2__link">Experiments</a>
      <a href="/protocols/" class="footer-v2__link">Protocols</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The platform</div>
      <a href="/platform/" class="footer-v2__link">Platform</a>
      <a href="/intelligence/" class="footer-v2__link">Intelligence</a>
      <a href="/accountability/" class="footer-v2__link">Accountability</a>
      <a href="/methodology/" class="footer-v2__link">Methodology</a>
      <a href="/ask/" class="footer-v2__link">Ask</a>
      <a href="/board/" class="footer-v2__link">Board</a>
      <a href="/data/" class="footer-v2__link">Data</a>
      <a href="/cost/" class="footer-v2__link">Cost</a>
      <a href="/tools/" class="footer-v2__link">Tools</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">Follow</div>
      <a href="/subscribe/" class="footer-v2__link">Subscribe</a>
      <a href="/rss.xml" class="footer-v2__link">RSS</a>
      <a href="/privacy/" class="footer-v2__link">Privacy</a>
    </div>
  </div>
  <div class="footer-v2__bottom">
    <span class="footer-v2__brand">AMJ</span>
    <span class="footer-v2__copy">// updated daily by life-platform</span>
  </div>
</footer>'''


# ── Regex patterns for replacement ───────────────────────────

# Matches the entire <nav class="nav"> ... </nav> block
NAV_RE = re.compile(
    r'<nav class="nav">.*?</nav>',
    re.DOTALL
)

# Matches the overlay block (outer div is unindented; all inner divs are indented)
OVERLAY_RE = re.compile(
    r'<!-- Mobile overlay menu -->.*?\n</div>',
    re.DOTALL
)

# Matches footer-v2 block
FOOTER_RE = re.compile(
    r'<footer class="footer-v2">.*?</footer>',
    re.DOTALL
)


def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()

    active_href = get_active_href(filepath)
    content = original

    # 1. Top nav
    new_nav = build_nav(active_href)
    content, n = NAV_RE.subn(new_nav, content, count=1)
    nav_changed = n > 0

    # 2. Overlay
    new_overlay = OVERLAY_HTML + '\n'
    content, n = OVERLAY_RE.subn(new_overlay, content, count=1)
    overlay_changed = n > 0

    # 3. Footer
    content, n = FOOTER_RE.subn(FOOTER_HTML, content, count=1)
    footer_changed = n > 0

    changed = nav_changed or overlay_changed or footer_changed

    if not changed:
        return False, 'no patterns matched'

    if not DRY_RUN:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    rel = os.path.relpath(filepath, ROOT)
    changes = []
    if nav_changed: changes.append('nav')
    if overlay_changed: changes.append('overlay')
    if footer_changed: changes.append('footer')
    return True, ', '.join(changes)


def main():
    pages = find_html_pages()
    print(f"{'DRY RUN — ' if DRY_RUN else ''}Patching {len(pages)} HTML files\n")

    updated = 0
    skipped = 0
    for filepath in pages:
        changed, reason = patch_file(filepath)
        rel = os.path.relpath(filepath, ROOT)
        if changed:
            print(f'  ✅ {rel} ({reason})')
            updated += 1
        else:
            print(f'  ⏭  {rel} — {reason}')
            skipped += 1

    print(f'\n{"[DRY RUN] " if DRY_RUN else ""}Updated {updated}, skipped {skipped}')
    if not DRY_RUN and updated > 0:
        print('\nNext steps:')
        print('  bash deploy/sync_site_to_s3.sh')
        print('  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"')


if __name__ == '__main__':
    main()
