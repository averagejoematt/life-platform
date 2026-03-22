#!/usr/bin/env python3
"""
deploy_sprint11_nav.py — Phase 1 IA: 5-section dropdown nav + /chronicle/ rename

CHANGES:
  1. Desktop top nav: 5-section dropdown (The Story / The Data / The Science / The Build / Follow)
  2. Mobile overlay: 5 grouped sections matching new IA
  3. Footer: 5 columns matching new IA
  4. Bottom nav: Journal → Chronicle
  5. Reading path CTAs reference /chronicle/ not /journal/

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

# Maps page path → section key for active state detection
SECTION_MAP = {
    '/':               'story',
    '/story/':         'story',
    '/about/':         'story',
    '/live/':          'data',
    '/character/':     'data',
    '/habits/':        'data',
    '/accountability/':'data',
    '/protocols/':     'science',
    '/experiments/':   'science',
    '/discoveries/':   'science',
    '/sleep/':         'science',
    '/glucose/':       'science',
    '/supplements/':   'science',
    '/benchmarks/':    'science',
    '/platform/':      'build',
    '/intelligence/':  'build',
    '/board/':         'build',
    '/cost/':          'build',
    '/methodology/':   'build',
    '/tools/':         'build',
    '/data/':          'build',
    '/platform/reviews/': 'build',
    '/chronicle/':     'follow',
    '/chronicle/archive/': 'follow',
    '/week/':          'follow',
    '/subscribe/':     'follow',
    '/ask/':           'follow',
}

SECTIONS = [
    ('story',   'The Story',   [
        ('/',         'Home'),
        ('/story/',   'My Story'),
        ('/about/',   'About'),
    ]),
    ('data',    'The Data',    [
        ('/live/',            'Live'),
        ('/character/',       'Character'),
        ('/habits/',          'Habits'),
        ('/accountability/',  'Accountability'),
    ]),
    ('science', 'The Science', [
        ('/protocols/',    'Protocols'),
        ('/experiments/',  'Experiments'),
        ('/discoveries/',  'Discoveries'),
        ('/sleep/',        'Sleep'),
        ('/glucose/',      'Glucose'),
        ('/supplements/',  'Supplements'),
        ('/benchmarks/',   'Benchmarks'),
    ]),
    ('build',   'The Build',   [
        ('/platform/',     'Platform'),
        ('/intelligence/', 'Intelligence'),
        ('/board/',        'Board'),
        ('/cost/',         'Cost'),
        ('/methodology/',  'Methodology'),
        ('/tools/',        'Tools'),
    ]),
    ('follow',  'Follow',      [
        ('/chronicle/', 'Chronicle'),
        ('/subscribe/', 'Subscribe'),
        ('/ask/',       'Ask'),
    ]),
]


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


def get_active_section(active_href):
    # exact match first
    if active_href in SECTION_MAP:
        return SECTION_MAP[active_href]
    # prefix match for sub-paths (e.g. /journal/posts/week-01/)
    for path, section in sorted(SECTION_MAP.items(), key=lambda x: -len(x[0])):
        if active_href.startswith(path) and path != '/':
            return section
    return None


def build_nav(active_href):
    active_section = get_active_section(active_href)
    dropdowns = []
    for key, label, items in SECTIONS:
        active_cls = ' is-active' if key == active_section else ''
        items_html = '\n'.join(
            '        <a href="{}" class="nav__dropdown-item{}">{}</a>'.format(
                href,
                ' active' if href == active_href else '',
                name
            )
            for href, name in items
        )
        dropdowns.append(
            '    <div class="nav__dropdown{active}">\n'
            '      <button class="nav__dropdown-btn">{label}</button>\n'
            '      <div class="nav__dropdown-menu">\n'
            '{items}\n'
            '      </div>\n'
            '    </div>'.format(active=active_cls, label=label, items=items_html)
        )
    return '''<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
{dropdowns}
    <a href="/subscribe/" class="nav__link nav__cta">Subscribe →</a>
  </div>
  <button class="nav__hamburger" aria-label="Open menu">
    <span></span><span></span><span></span>
  </button>
  <div class="nav__status">
    <div class="pulse"></div>
    <span id="nav-date"></span>
  </div>
</nav>'''.format(dropdowns='\n'.join(dropdowns))


OVERLAY_HTML = '''<!-- Mobile overlay menu -->
<div class="nav-overlay">
  <div class="nav-overlay__panel">
    <button class="nav-overlay__close" aria-label="Close menu">&times;</button>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The Story</div>
      <a href="/" class="nav-overlay__link">Home</a>
      <a href="/story/" class="nav-overlay__link">My Story</a>
      <a href="/about/" class="nav-overlay__link">About</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The Data</div>
      <a href="/live/" class="nav-overlay__link">Live</a>
      <a href="/character/" class="nav-overlay__link">Character</a>
      <a href="/habits/" class="nav-overlay__link">Habits</a>
      <a href="/accountability/" class="nav-overlay__link">Accountability</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The Science</div>
      <a href="/protocols/" class="nav-overlay__link">Protocols</a>
      <a href="/experiments/" class="nav-overlay__link">Experiments</a>
      <a href="/discoveries/" class="nav-overlay__link">Discoveries</a>
      <a href="/sleep/" class="nav-overlay__link">Sleep</a>
      <a href="/glucose/" class="nav-overlay__link">Glucose</a>
      <a href="/supplements/" class="nav-overlay__link">Supplements</a>
      <a href="/benchmarks/" class="nav-overlay__link">Benchmarks</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The Build</div>
      <a href="/platform/" class="nav-overlay__link">Platform</a>
      <a href="/intelligence/" class="nav-overlay__link">Intelligence</a>
      <a href="/board/" class="nav-overlay__link">Board</a>
      <a href="/cost/" class="nav-overlay__link">Cost</a>
      <a href="/methodology/" class="nav-overlay__link">Methodology</a>
      <a href="/tools/" class="nav-overlay__link">Tools</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">Follow</div>
      <a href="/chronicle/" class="nav-overlay__link">Chronicle</a>
      <a href="/subscribe/" class="nav-overlay__link nav-overlay__link--cta">Subscribe</a>
      <a href="/ask/" class="nav-overlay__link">Ask</a>
      <a href="/rss.xml" class="nav-overlay__link">RSS</a>
      <a href="/privacy/" class="nav-overlay__link">Privacy</a>
    </div>
  </div>
</div>'''


FOOTER_HTML = '''<footer class="footer-v2">
  <div class="footer-v2__grid">
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The Story</div>
      <a href="/" class="footer-v2__link">Home</a>
      <a href="/story/" class="footer-v2__link">My Story</a>
      <a href="/about/" class="footer-v2__link">About</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The Data</div>
      <a href="/live/" class="footer-v2__link">Live</a>
      <a href="/character/" class="footer-v2__link">Character</a>
      <a href="/habits/" class="footer-v2__link">Habits</a>
      <a href="/accountability/" class="footer-v2__link">Accountability</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The Science</div>
      <a href="/protocols/" class="footer-v2__link">Protocols</a>
      <a href="/experiments/" class="footer-v2__link">Experiments</a>
      <a href="/discoveries/" class="footer-v2__link">Discoveries</a>
      <a href="/sleep/" class="footer-v2__link">Sleep</a>
      <a href="/glucose/" class="footer-v2__link">Glucose</a>
      <a href="/supplements/" class="footer-v2__link">Supplements</a>
      <a href="/benchmarks/" class="footer-v2__link">Benchmarks</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The Build</div>
      <a href="/platform/" class="footer-v2__link">Platform</a>
      <a href="/intelligence/" class="footer-v2__link">Intelligence</a>
      <a href="/board/" class="footer-v2__link">Board</a>
      <a href="/cost/" class="footer-v2__link">Cost</a>
      <a href="/methodology/" class="footer-v2__link">Methodology</a>
      <a href="/tools/" class="footer-v2__link">Tools</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">Follow</div>
      <a href="/chronicle/" class="footer-v2__link">Chronicle</a>
      <a href="/subscribe/" class="footer-v2__link">Subscribe</a>
      <a href="/ask/" class="footer-v2__link">Ask</a>
      <a href="/rss.xml" class="footer-v2__link">RSS</a>
      <a href="/privacy/" class="footer-v2__link">Privacy</a>
    </div>
  </div>
  <div class="footer-v2__bottom">
    <span class="footer-v2__brand">AMJ</span>
    <span class="footer-v2__copy">// updated daily by life-platform</span>
  </div>
</footer>'''


BOTTOM_NAV_HTML = '''<!-- Mobile bottom nav -->
<nav class="bottom-nav" aria-label="Mobile navigation">
  <a href="/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
    <span>Home</span>
  </a>
  <a href="/live/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor"/><circle cx="12" cy="12" r="7"/></svg>
    <span>Live</span>
  </a>
  <a href="/character/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
    <span>Character</span>
  </a>
  <a href="/chronicle/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
    <span>Chronicle</span>
  </a>
  <a href="/ask/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    <span>Ask</span>
  </a>
</nav>'''


# ── Regex patterns for replacement ───────────────────────────

NAV_RE = re.compile(
    r'<nav class="nav">.*?</nav>',
    re.DOTALL
)

OVERLAY_RE = re.compile(
    r'<!-- Mobile overlay menu -->.*?\n</div>',
    re.DOTALL
)

FOOTER_RE = re.compile(
    r'<footer class="footer-v2">.*?</footer>',
    re.DOTALL
)

BOTTOM_NAV_RE = re.compile(
    r'<!-- Mobile bottom nav -->.*?</nav>',
    re.DOTALL
)


def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()

    active_href = get_active_href(filepath)
    content = original

    # 1. Top nav (with dropdowns, active-section aware)
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

    # 4. Bottom nav (Journal → Chronicle)
    content, n = BOTTOM_NAV_RE.subn(BOTTOM_NAV_HTML, content, count=1)
    bottom_changed = n > 0

    changed = nav_changed or overlay_changed or footer_changed or bottom_changed

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
    if bottom_changed: changes.append('bottom-nav')
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
