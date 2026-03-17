#!/usr/bin/env python3
"""
add_email_cta.py — Sprint 5, S2-T1-8
Inject the amber email CTA section before <footer class="footer"> on all
site pages that don't already have it.

Run from project root:
    python3 deploy/add_email_cta.py
"""

import os
import re
import sys

SITE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "site")

# Pages to update (relative to SITE_DIR) — about and story already have CTAs
PAGES = [
    "index.html",
    "platform/index.html",
    "journal/index.html",
    "character/index.html",
    "experiments/index.html",
    "biology/index.html",
    "live/index.html",
    "explorer/index.html",
]

# ── CTA block to inject ───────────────────────────────────────────────────────
# Amber accent (journal color), self-contained subscribe form.
# Uses a unique element ID per page (derived from page slug) to avoid collisions
# when multiple pages might someday share JS.

CTA_TEMPLATE = """\
<!-- S2-T1-8: Email CTA footer — injected by add_email_cta.py -->
<section class="email-cta-footer" style="
  padding: var(--space-16) var(--page-padding);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  text-align: center;
">
  <p style="font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--c-amber-500);margin-bottom:var(--space-4)">// the weekly signal</p>
  <h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-4)">Get the data, every week.</h3>
  <p style="font-size:var(--text-base);color:var(--text-muted);max-width:480px;margin:0 auto var(--space-8);line-height:var(--lh-body)">
    Real numbers from 19 data sources. No highlight reel. Every Wednesday, in your inbox.
  </p>
  <div style="display:flex;gap:var(--space-2);max-width:400px;margin:0 auto">
    <input id="cta-email-{SLUG}" type="email" placeholder="your@email.com" style="
      flex:1;background:var(--bg);border:1px solid var(--c-amber-500);color:var(--text);
      font-family:var(--font-mono);font-size:var(--text-xs);padding:var(--space-3) var(--space-4);
      outline:none;transition:border-color var(--dur-fast);
    " onfocus="this.style.borderColor='var(--c-amber-400)'" onblur="this.style.borderColor='var(--c-amber-500)'">
    <button
      onclick="amjSubscribe('{SLUG}')"
      class="btn btn--primary"
      style="background:var(--c-amber-500);border-color:var(--c-amber-500);white-space:nowrap;color:var(--bg)">
      Subscribe
    </button>
  </div>
  <p id="cta-msg-{SLUG}" style="font-size:var(--text-2xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3);min-height:1em"></p>
</section>
<script>
(function() {
  // S2-T1-8: Shared subscribe helper (idempotent — safe to include multiple times)
  if (!window.amjSubscribe) {
    window.amjSubscribe = async function(slug) {
      var email = document.getElementById('cta-email-' + slug).value.trim();
      var msg   = document.getElementById('cta-msg-'   + slug);
      if (!email || !email.includes('@')) {
        msg.textContent = 'Enter a valid email address.';
        msg.style.color = 'var(--c-yellow-status)';
        return;
      }
      msg.textContent = 'Subscribing…';
      msg.style.color = 'var(--text-muted)';
      try {
        var res  = await fetch('/api/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email, source: slug + '_cta' }),
        });
        var data = await res.json();
        if (res.ok) {
          msg.textContent = '✓ Check your inbox to confirm.';
          msg.style.color = 'var(--c-amber-500)';
          document.getElementById('cta-email-' + slug).value = '';
        } else {
          msg.textContent = data.error || 'Something went wrong.';
          msg.style.color = 'var(--c-yellow-status)';
        }
      } catch(e) {
        msg.textContent = 'Network error — try again.';
        msg.style.color = 'var(--c-yellow-status)';
      }
    };
  }
  // Enter key support for this page's input
  var inp = document.getElementById('cta-email-{SLUG}');
  if (inp) inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') window.amjSubscribe('{SLUG}'); });
})();
</script>
"""

FOOTER_PATTERN = re.compile(r'(<footer\s+class="footer")', re.IGNORECASE)
ALREADY_INJECTED = "email-cta-footer"


def slug_for(page_path):
    """Turn 'platform/index.html' → 'platform', 'index.html' → 'home'."""
    parts = page_path.replace("\\", "/").split("/")
    if len(parts) == 1:
        return "home"
    return parts[0]


def inject(page_rel_path):
    abs_path = os.path.join(SITE_DIR, page_rel_path)
    if not os.path.exists(abs_path):
        print(f"  [SKIP] {page_rel_path} — file not found")
        return False

    with open(abs_path, "r", encoding="utf-8") as f:
        html = f.read()

    if ALREADY_INJECTED in html:
        print(f"  [SKIP] {page_rel_path} — CTA already present")
        return False

    slug = slug_for(page_rel_path)
    cta  = CTA_TEMPLATE.replace("{SLUG}", slug)

    new_html, n = FOOTER_PATTERN.subn(cta + r"\1", html, count=1)
    if n == 0:
        print(f"  [WARN] {page_rel_path} — no <footer class=\"footer\"> found, skipping")
        return False

    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"  [OK]   {page_rel_path} — CTA injected (slug={slug})")
    return True


def main():
    print("=== add_email_cta.py — Sprint 5 S2-T1-8 ===")
    print(f"Site dir: {SITE_DIR}")
    print()

    updated = 0
    for page in PAGES:
        if inject(page):
            updated += 1

    print()
    print(f"Done. {updated}/{len(PAGES)} pages updated.")
    if updated > 0:
        print()
        print("Next steps:")
        print("  1. aws s3 sync site/ s3://matthew-life-platform/site/ --exclude '*.DS_Store' --region us-west-2")
        print("  2. aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*' --region us-east-1")


if __name__ == "__main__":
    main()
