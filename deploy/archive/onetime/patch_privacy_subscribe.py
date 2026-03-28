#!/usr/bin/env python3
"""
patch_privacy_subscribe.py — Add privacy policy link to subscribe.html

Adds a visible privacy policy link to the subscribe form as required by Yael (R13).
Also adds /privacy/ to the site footer links.

Run from project root:
    python3 deploy/patch_privacy_subscribe.py
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent

SUBSCRIBE = ROOT / "site" / "subscribe.html"


OLD_NOTE = '        <div class="form-note">You\'ll get a confirmation email. Double opt-in — no surprises. Unsubscribe anytime, no questions asked.</div>'

NEW_NOTE = ('        <div class="form-note">You\'ll get a confirmation email. Double opt-in — no surprises. '
            'Unsubscribe anytime, no questions asked. '
            '<a href="/privacy/" style="color:var(--text-muted);text-decoration:underline;">Privacy policy →</a></div>')


OLD_FOOTER_LINKS = (
    '  <div class="footer__links">\n'
    '    <a href="/" class="footer__link">Home</a>\n'
    '    <a href="/journal/" class="footer__link">Journal</a>\n'
    '    <a href="/character/" class="footer__link">Character</a>\n'
    '  </div>'
)

NEW_FOOTER_LINKS = (
    '  <div class="footer__links">\n'
    '    <a href="/" class="footer__link">Home</a>\n'
    '    <a href="/journal/" class="footer__link">Journal</a>\n'
    '    <a href="/character/" class="footer__link">Character</a>\n'
    '    <a href="/privacy/" class="footer__link">Privacy</a>\n'
    '  </div>'
)


def patch():
    src = SUBSCRIBE.read_text(encoding="utf-8")
    changed = False

    if 'Privacy policy' in src or '/privacy/' in src:
        print("[INFO] subscribe.html: privacy link already present — skipping")
    else:
        if OLD_NOTE not in src:
            print("[WARN] subscribe.html: form-note anchor not found — trying stripped whitespace match")
            stripped_old = OLD_NOTE.strip()
            if stripped_old in src:
                src = src.replace(stripped_old, NEW_NOTE.strip(), 1)
                print("[OK]   subscribe.html: privacy link added to form-note (stripped match)")
                changed = True
            else:
                print("[ERROR] subscribe.html: cannot find form-note — update manually")
                print("  Add to the .form-note div:")
                print('  <a href="/privacy/" style="color:var(--text-muted);text-decoration:underline;">Privacy policy →</a>')
        else:
            src = src.replace(OLD_NOTE, NEW_NOTE, 1)
            print("[OK]   subscribe.html: privacy link added to form-note")
            changed = True

    if OLD_FOOTER_LINKS in src:
        src = src.replace(OLD_FOOTER_LINKS, NEW_FOOTER_LINKS, 1)
        print("[OK]   subscribe.html: /privacy/ added to footer")
        changed = True
    else:
        print("[INFO] subscribe.html: footer links anchor not found — skipping footer update")

    if changed:
        SUBSCRIBE.write_text(src, encoding="utf-8")
        print("[OK]   subscribe.html written")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Privacy policy patch — subscribe.html")
    print("=" * 60)
    patch()
    print()
    print("Next steps:")
    print("  1. Sync site/ to S3:")
    print("     aws s3 sync site/ s3://matthew-life-platform/site/ --delete --no-cli-pager")
    print("  2. Invalidate CloudFront:")
    print("     aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/subscribe*' '/privacy/*' --no-cli-pager")
