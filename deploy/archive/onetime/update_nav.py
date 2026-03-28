#!/usr/bin/env python3
"""
update_nav.py — Standardise nav + footer across all 12 site pages.

NEW NAV (primary — 5 items + Subscribe CTA):
  AMJ | Story · Live · Journal · Platform · Character | [Subscribe →]  [Live ●]

NEW FOOTER (secondary — all pages):
  Brand | Story · Journal · Platform · Character · Explorer · Experiments · Biology · Ask · Board · About · Subscribe
  // updated daily by life-platform · Privacy

Run from project root:
  python3 deploy/update_nav.py
  python3 deploy/update_nav.py --dry-run   (preview only)
"""
import re
import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), '..')
SITE = os.path.join(ROOT, 'site')
DRY_RUN = '--dry-run' in sys.argv

PAGES = {
    'index.html':                 '/',
    'story/index.html':           '/story/',
    'live/index.html':            '/live/',
    'journal/index.html':         '/journal/',
    'platform/index.html':        '/platform/',
    'character/index.html':       '/character/',
    'ask/index.html':             '/ask/',
    'board/index.html':           '/board/',
    'experiments/index.html':     '/experiments/',
    'explorer/index.html':        '/explorer/',
    'biology/index.html':         '/biology/',
    'about/index.html':           '/about/',
}

# ── New nav HTML ──────────────────────────────────────────────────────────────
# {ACTIVE} will be replaced with the active page's href for .active class marking

def build_nav(active_href):
    items = [
        ('/story/',        'Story'),
        ('/live/',         'Live'),
        ('/journal/',      'Journal'),
        ('/platform/',     'Platform'),
        ('/character/',    'Character'),
    ]
    links = '\n    '.join(
        f'<a href="{href}" class="nav__link{" active" if href == active_href else ""}">{label}</a>'
        for href, label in items
    )
    return f'''<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    {links}
    <a href="/subscribe/" class="nav__link nav__cta">Subscribe</a>
  </div>
  <div class="nav__status">
    <div class="pulse"></div>
    <span>Live</span>
  </div>
</nav>'''

# ── New footer HTML ───────────────────────────────────────────────────────────

NEW_FOOTER = '''<footer class="footer">
  <div class="footer__brand">AMJ</div>
  <div class="footer__links">
    <a href="/story/" class="footer__link">Story</a>
    <a href="/live/" class="footer__link">Live</a>
    <a href="/journal/" class="footer__link">Journal</a>
    <a href="/platform/" class="footer__link">Platform</a>
    <a href="/character/" class="footer__link">Character</a>
    <a href="/experiments/" class="footer__link">Experiments</a>
    <a href="/explorer/" class="footer__link">Explorer</a>
    <a href="/biology/" class="footer__link">Biology</a>
    <a href="/ask/" class="footer__link">Ask</a>
    <a href="/board/" class="footer__link">Board</a>
    <a href="/about/" class="footer__link">About</a>
    <a href="/subscribe/" class="footer__link">Subscribe</a>
  </div>
  <div class="footer__copy">// updated daily by life-platform · <a href="/privacy/" class="footer__link">Privacy</a></div>
</footer>'''

# ── Patterns to replace ───────────────────────────────────────────────────────

NAV_PATTERN = re.compile(
    r'<nav\s+class=["\'](?:nav|site-nav)["\'][^>]*>.*?</nav>',
    re.DOTALL
)
FOOTER_PATTERN = re.compile(
    r'<footer\s+class=["\'](?:footer|site-footer)["\'][^>]*>.*?</footer>',
    re.DOTALL
)

# ── Process pages ─────────────────────────────────────────────────────────────

total_nav     = 0
total_footer  = 0
total_skipped = 0

for rel_path, active_href in PAGES.items():
    full_path = os.path.join(SITE, rel_path)
    if not os.path.exists(full_path):
        print(f'  SKIP  /{rel_path} (not found)')
        total_skipped += 1
        continue

    content = open(full_path, encoding='utf-8').read()
    original = content
    changes = []

    # Replace nav
    new_nav = build_nav(active_href)
    new_content, n = NAV_PATTERN.subn(new_nav, content)
    if n:
        content = new_content
        changes.append(f'nav ({n}x)')
        total_nav += 1
    else:
        changes.append('nav NOT FOUND')

    # Replace footer
    new_content, n = FOOTER_PATTERN.subn(NEW_FOOTER, content)
    if n:
        content = new_content
        changes.append(f'footer ({n}x)')
        total_footer += 1
    else:
        changes.append('footer NOT FOUND')

    status = '✓' if content != original else '='
    print(f'  {status}  {rel_path:<35} [{", ".join(changes)}]')

    if not DRY_RUN and content != original:
        open(full_path, 'w', encoding='utf-8').write(content)

print()
if DRY_RUN:
    print(f'DRY RUN — no files written.')
else:
    print(f'✅  Done: {total_nav} navs updated, {total_footer} footers updated, {total_skipped} skipped.')
    print()
    print('Next: bash deploy/deploy_site_all.sh')
