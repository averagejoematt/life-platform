#!/usr/bin/env python3
"""
deploy_sprint8_nav.py — Sprint 8: Mobile nav + content filter + footer

WHAT IT DOES:
  1. Appends mobile nav CSS to base.css (hamburger, bottom nav, overlay, grouped footer)
  2. Patches all site HTML pages with:
     - Updated top nav (Story, Live, Journal, Platform, About + Subscribe CTA + hamburger)
     - Full-page overlay menu (grouped: Journey, Data, Platform, Follow)
     - Persistent bottom nav (mobile: Home, Ask, Score, Journal, More)
     - Grouped footer (3 columns + Follow)
     - nav.js script tag
  3. Uploads content_filter.json to S3

RUN:
  python3 deploy/deploy_sprint8_nav.py
  python3 deploy/deploy_sprint8_nav.py --dry-run   # preview only
  
AFTER:
  bash deploy/deploy_lambda.sh site_api   # redeploy Lambda with content filter
  aws s3 sync site/ s3://matthew-life-platform/site/ --delete
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
"""
import os
import re
import sys
import json

DRY_RUN = '--dry-run' in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')

# ── Discover all HTML pages ──────────────────────────────────
def find_html_pages():
    pages = []
    for dirpath, dirnames, filenames in os.walk(SITE):
        for f in filenames:
            if f.endswith('.html'):
                pages.append(os.path.join(dirpath, f))
    return sorted(pages)

# ── Determine active page from file path ─────────────────────
def get_active_href(filepath):
    rel = os.path.relpath(filepath, SITE)
    if rel == 'index.html': return '/'
    # e.g. story/index.html -> /story/
    parts = rel.replace('\\', '/').split('/')
    if parts[-1] == 'index.html':
        return '/' + '/'.join(parts[:-1]) + '/'
    return '/' + rel

# ── New nav HTML ─────────────────────────────────────────────
def build_nav(active_href):
    items = [
        ('/story/',    'Story'),
        ('/live/',     'Live'),
        ('/journal/',  'Journal'),
        ('/platform/', 'Platform'),
        ('/about/',    'About'),
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

# ── Overlay menu HTML ────────────────────────────────────────
OVERLAY_HTML = '''<!-- Mobile overlay menu -->
<div class="nav-overlay">
  <div class="nav-overlay__panel">
    <button class="nav-overlay__close" aria-label="Close menu">&times;</button>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The journey</div>
      <a href="/story/" class="nav-overlay__link">Story</a>
      <a href="/live/" class="nav-overlay__link">Live</a>
      <a href="/journal/" class="nav-overlay__link">Journal</a>
      <a href="/about/" class="nav-overlay__link">About</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The data</div>
      <a href="/character/" class="nav-overlay__link">Character</a>
      <a href="/explorer/" class="nav-overlay__link">Explorer</a>
      <a href="/experiments/" class="nav-overlay__link">Experiments</a>
      <a href="/biology/" class="nav-overlay__link">Biology</a>
      <a href="/protocols/" class="nav-overlay__link">Protocols</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">The platform</div>
      <a href="/platform/" class="nav-overlay__link">Platform</a>
      <a href="/ask/" class="nav-overlay__link">Ask</a>
      <a href="/board/" class="nav-overlay__link">Board</a>
      <a href="/data/" class="nav-overlay__link">Data</a>
    </div>
    <div class="nav-overlay__section">
      <div class="nav-overlay__heading">Follow</div>
      <a href="/subscribe/" class="nav-overlay__link nav-overlay__link--cta">Subscribe</a>
      <a href="/rss.xml" class="nav-overlay__link">RSS</a>
    </div>
  </div>
</div>'''

# ── Bottom nav HTML (mobile) ─────────────────────────────────
BOTTOM_NAV_HTML = '''<!-- Mobile bottom nav -->
<nav class="bottom-nav" aria-label="Mobile navigation">
  <a href="/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l9-9 9 9"/><path d="M5 10v10a1 1 0 001 1h3a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1h3a1 1 0 001-1V10"/></svg>
    <span>Home</span>
  </a>
  <a href="/ask/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
    <span>Ask</span>
  </a>
  <a href="/character/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
    <span>Score</span>
  </a>
  <a href="/journal/" class="bottom-nav__link">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>
    <span>Journal</span>
  </a>
  <button class="bottom-nav__link bottom-nav__more" onclick="document.querySelector('.nav__hamburger').click()">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>
    <span>More</span>
  </button>
</nav>'''

# ── Grouped footer HTML ──────────────────────────────────────
FOOTER_HTML = '''<footer class="footer-v2">
  <div class="footer-v2__grid">
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The journey</div>
      <a href="/story/" class="footer-v2__link">Story</a>
      <a href="/live/" class="footer-v2__link">Live</a>
      <a href="/journal/" class="footer-v2__link">Journal</a>
      <a href="/about/" class="footer-v2__link">About</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The data</div>
      <a href="/character/" class="footer-v2__link">Character</a>
      <a href="/explorer/" class="footer-v2__link">Explorer</a>
      <a href="/experiments/" class="footer-v2__link">Experiments</a>
      <a href="/biology/" class="footer-v2__link">Biology</a>
      <a href="/protocols/" class="footer-v2__link">Protocols</a>
    </div>
    <div class="footer-v2__col">
      <div class="footer-v2__heading">The platform</div>
      <a href="/platform/" class="footer-v2__link">Platform</a>
      <a href="/ask/" class="footer-v2__link">Ask</a>
      <a href="/board/" class="footer-v2__link">Board</a>
      <a href="/data/" class="footer-v2__link">Data</a>
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

# ── CSS to append to base.css ────────────────────────────────
MOBILE_NAV_CSS = '''

/* ══════════════════════════════════════════════════════════════
   Sprint 8 — Mobile hamburger, bottom nav, overlay, grouped footer
   Added: 2026-03-21
   ══════════════════════════════════════════════════════════════ */

/* ── Hamburger button (mobile only) ──────────────────────── */
.nav__hamburger {
  display: none;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  cursor: pointer;
  z-index: calc(var(--z-nav) + 1);
}
.nav__hamburger span {
  display: block;
  width: 18px;
  height: 1.5px;
  background: var(--text-muted);
  transition: all 0.2s var(--ease-out);
}
.nav__hamburger:hover span { background: var(--accent); }

/* ── Full-page overlay menu ──────────────────────────────── */
.nav-overlay {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-nav) + 10);
  background: rgba(8, 12, 10, 0.96);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s var(--ease-out);
}
.nav-overlay.is-open {
  opacity: 1;
  pointer-events: auto;
}
.nav-overlay__panel {
  max-width: 480px;
  margin: 0 auto;
  padding: calc(var(--nav-height) + var(--space-8)) var(--page-padding) var(--space-16);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.nav-overlay__close {
  position: absolute;
  top: var(--space-5);
  right: var(--space-6);
  font-size: 28px;
  color: var(--text-muted);
  cursor: pointer;
  background: none;
  border: none;
  line-height: 1;
  padding: 4px 8px;
  transition: color 0.15s;
}
.nav-overlay__close:hover { color: var(--accent); }
.nav-overlay__section { display: flex; flex-direction: column; gap: var(--space-3); }
.nav-overlay__heading {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--ls-tag);
  text-transform: uppercase;
  color: var(--accent-dim);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border-subtle);
}
.nav-overlay__link {
  font-family: var(--font-mono);
  font-size: var(--text-base);
  color: var(--text-muted);
  padding: var(--space-2) 0;
  transition: color 0.15s;
}
.nav-overlay__link:hover,
.nav-overlay__link.active { color: var(--accent); }
.nav-overlay__link--cta {
  color: var(--accent);
  font-weight: 700;
}

/* ── Bottom nav (mobile only) ────────────────────────────── */
.bottom-nav {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: calc(var(--z-nav) - 1);
  height: 60px;
  background: rgba(8, 12, 10, 0.95);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-top: 1px solid var(--border);
  align-items: center;
  justify-content: space-around;
  padding: 0 var(--space-2);
}
.bottom-nav__link {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: var(--ls-tag);
  text-transform: uppercase;
  color: var(--text-faint);
  text-decoration: none;
  padding: 6px 8px;
  transition: color 0.15s;
  -webkit-tap-highlight-color: transparent;
  background: none;
  border: none;
  cursor: pointer;
}
.bottom-nav__link svg {
  opacity: 0.5;
  transition: opacity 0.15s;
}
.bottom-nav__link.active,
.bottom-nav__link:hover {
  color: var(--accent);
}
.bottom-nav__link.active svg,
.bottom-nav__link:hover svg {
  opacity: 1;
  stroke: var(--accent);
}

/* ── Grouped footer v2 ───────────────────────────────────── */
.footer-v2 {
  border-top: 1px solid var(--border);
  padding: var(--space-12) var(--page-padding) var(--space-8);
}
.footer-v2__grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-8);
  margin-bottom: var(--space-10);
}
.footer-v2__heading {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--ls-tag);
  text-transform: uppercase;
  color: var(--accent-dim);
  margin-bottom: var(--space-4);
}
.footer-v2__col {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.footer-v2__link {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
  transition: color 0.15s;
}
.footer-v2__link:hover { color: var(--accent); }
.footer-v2__bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: var(--space-6);
  border-top: 1px solid var(--border-subtle);
}
.footer-v2__brand {
  font-family: var(--font-display);
  font-size: 18px;
  letter-spacing: var(--ls-label);
  color: var(--accent);
}
.footer-v2__copy {
  font-size: var(--text-2xs);
  color: var(--text-faint);
  letter-spacing: var(--ls-tag);
}

/* ── Mobile overrides ────────────────────────────────────── */
@media (max-width: 768px) {
  .nav__hamburger { display: flex; }
  .nav__links { display: none; }
  .nav__status { display: none; }
  .bottom-nav { display: flex; }
  /* Shift challenge bar above bottom nav */
  .challenge-bar { bottom: 60px; }
  body { padding-bottom: 96px; } /* 60px bottom-nav + 36px challenge-bar */
  /* Footer responsive */
  .footer-v2__grid { grid-template-columns: repeat(2, 1fr); gap: var(--space-6); }
  .footer-v2__bottom { flex-direction: column; gap: var(--space-3); text-align: center; }
  /* Hide old footer if present */
  .footer { display: none; }
}
'''

# ── Patch functions ──────────────────────────────────────────

def patch_nav(html, active_href):
    """Replace <nav class="nav">...</nav> with new nav."""
    pattern = r'<nav\s+class="nav"[^>]*>.*?</nav>'
    new_nav = build_nav(active_href)
    result = re.sub(pattern, new_nav, html, count=1, flags=re.DOTALL)
    return result

def inject_overlay(html):
    """Inject overlay HTML after </nav> if not already present."""
    if 'nav-overlay' in html:
        return html
    return html.replace('</nav>', '</nav>\n' + OVERLAY_HTML, 1)

def inject_bottom_nav(html):
    """Inject bottom nav before footer if not already present."""
    if 'bottom-nav' in html:
        return html
    # Try to inject before new footer
    if '<footer class="footer-v2">' in html:
        return html.replace('<footer class="footer-v2">', BOTTOM_NAV_HTML + '\n<footer class="footer-v2">', 1)
    # Or before old footer
    if '<footer class="footer">' in html:
        return html.replace('<footer class="footer">', BOTTOM_NAV_HTML + '\n<footer class="footer">', 1)
    # Or before </body>
    return html.replace('</body>', BOTTOM_NAV_HTML + '\n</body>', 1)

def patch_footer(html):
    """Replace old footer with grouped footer v2."""
    pattern = r'<footer\s+class="footer">.*?</footer>'
    result = re.sub(pattern, FOOTER_HTML, html, count=1, flags=re.DOTALL)
    return result

def inject_nav_js(html):
    """Add nav.js script tag if not present."""
    if 'nav.js' in html:
        return html
    return html.replace('</body>', '<script src="/assets/js/nav.js"></script>\n</body>', 1)

# ── Main ─────────────────────────────────────────────────────

def main():
    pages = find_html_pages()
    print(f"Found {len(pages)} HTML pages")
    
    # 1. Append CSS to base.css
    css_path = os.path.join(SITE, 'assets', 'css', 'base.css')
    if os.path.exists(css_path):
        with open(css_path, 'r') as f:
            css = f.read()
        if 'Sprint 8' not in css:
            if DRY_RUN:
                print(f"[DRY RUN] Would append {len(MOBILE_NAV_CSS)} chars to base.css")
            else:
                with open(css_path, 'a') as f:
                    f.write(MOBILE_NAV_CSS)
                print(f"✓ Appended mobile nav CSS to base.css")
        else:
            print("  base.css already has Sprint 8 CSS, skipping")
    
    # 2. Patch each HTML page
    patched = 0
    for page_path in pages:
        active = get_active_href(page_path)
        with open(page_path, 'r') as f:
            original = f.read()
        
        html = original
        
        # Only patch pages that have our nav structure
        if '<nav' in html:
            html = patch_nav(html, active)
            html = inject_overlay(html)
        
        html = inject_bottom_nav(html)
        
        if '<footer class="footer">' in html:
            html = patch_footer(html)
        
        html = inject_nav_js(html)
        
        if html != original:
            if DRY_RUN:
                print(f"  [DRY RUN] Would update: {os.path.relpath(page_path, ROOT)}")
            else:
                with open(page_path, 'w') as f:
                    f.write(html)
                print(f"  ✓ {os.path.relpath(page_path, ROOT)}")
            patched += 1
        else:
            print(f"  - {os.path.relpath(page_path, ROOT)} (no changes)")
    
    print(f"\n{'[DRY RUN] Would patch' if DRY_RUN else 'Patched'} {patched} of {len(pages)} pages")
    
    # 3. Upload content filter to S3
    filter_path = os.path.join(ROOT, 'seeds', 'content_filter.json')
    if os.path.exists(filter_path):
        if DRY_RUN:
            print("[DRY RUN] Would upload content_filter.json to S3")
        else:
            print("\n── Next steps ──")
            print("1. Upload content filter to S3:")
            print("   aws s3 cp seeds/content_filter.json s3://matthew-life-platform/config/content_filter.json")
            print("2. Sync site to S3:")
            print("   aws s3 sync site/ s3://matthew-life-platform/site/ --delete")
            print("3. Invalidate CloudFront:")
            print("   aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*'")
            print("4. Deploy site-api Lambda (content filter):")
            print("   bash deploy/deploy_lambda.sh site_api")

if __name__ == '__main__':
    main()
