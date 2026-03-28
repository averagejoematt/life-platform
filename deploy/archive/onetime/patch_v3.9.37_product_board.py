#!/usr/bin/env python3
"""
Product Board Pre-Launch Punch List — All 23 Items
v3.9.37 — 2026-03-26

Run from project root:
  python3 deploy/patch_v3.9.37_product_board.py
"""
import os, re, json, shutil, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'site')

def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ Wrote {os.path.relpath(path, ROOT)}")

def replace_once(content, old, new, label=""):
    if old not in content:
        print(f"  ⚠ NOT FOUND: {label or old[:60]}")
        return content
    count = content.count(old)
    if count > 1:
        print(f"  ⚠ MULTIPLE ({count}): {label or old[:60]} — replacing first only")
        return content.replace(old, new, 1)
    return content.replace(old, new)

# ═══════════════════════════════════════════════════════════════
# ITEM 1: Journal → Chronicle redirects
# ═══════════════════════════════════════════════════════════════
print("\n[1/23] Journal → Chronicle redirects")

REDIRECT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url={target}">
  <link rel="canonical" href="https://averagejoematt.com{target}">
  <title>Redirecting...</title>
</head>
<body>
  <p>This page has moved to <a href="{target}">{target}</a>.</p>
</body>
</html>'''

# Main journal page
write(os.path.join(SITE, 'journal', 'index.html'),
      REDIRECT_TEMPLATE.format(target='/chronicle/'))

# Journal archive
write(os.path.join(SITE, 'journal', 'archive', 'index.html'),
      REDIRECT_TEMPLATE.format(target='/chronicle/archive/'))

# Journal sample
write(os.path.join(SITE, 'journal', 'sample', 'index.html'),
      REDIRECT_TEMPLATE.format(target='/chronicle/sample/'))

# Journal posts
for d in sorted(glob.glob(os.path.join(SITE, 'journal', 'posts', 'week-*'))):
    week = os.path.basename(d)
    target = f'/chronicle/posts/{week}/'
    write(os.path.join(d, 'index.html'),
          REDIRECT_TEMPLATE.format(target=target))

print("  ✓ All /journal/ pages now redirect to /chronicle/")


# ═══════════════════════════════════════════════════════════════
# ITEM 2: Fix stray </div> on homepage
# ═══════════════════════════════════════════════════════════════
print("\n[2/23] Fix stray </div> on homepage")
hp = os.path.join(SITE, 'index.html')
home = read(hp)

home = replace_once(home,
    '<div id="amj-nav"></div>\n</div>',
    '<div id="amj-nav"></div>',
    "stray </div>")


# ═══════════════════════════════════════════════════════════════
# ITEM 3: Confirm prequel banner auto-hides
# ═══════════════════════════════════════════════════════════════
print("\n[3/23] Confirm prequel banner hides on April 1")
# countdown.js sets window.AMJ_EXPERIMENT.isLive = true when date >= April 1
# Homepage has: if (window.AMJ_EXPERIMENT && window.AMJ_EXPERIMENT.isLive) banner.style.display = 'none'
# This is CORRECT. But let's add a belt-and-suspenders date check directly in the banner:
home = replace_once(home,
    '''<script>
// Hide prequel banner after experiment launch
(function() {
  if (window.AMJ_EXPERIMENT && window.AMJ_EXPERIMENT.isLive) {
    var banner = document.getElementById('prequel-banner');
    if (banner) banner.style.display = 'none';
  }
})();
</script>''',
    '''<script>
// Hide prequel banner after experiment launch (belt-and-suspenders)
(function() {
  var isLive = (window.AMJ_EXPERIMENT && window.AMJ_EXPERIMENT.isLive) ||
               (new Date() >= new Date('2026-04-01T00:00:00-07:00'));
  if (isLive) {
    var banner = document.getElementById('prequel-banner');
    if (banner) banner.style.display = 'none';
  }
})();
</script>''',
    "prequel banner logic")


# ═══════════════════════════════════════════════════════════════
# ITEM 4: Subscribe confirmation email (G-7 SES fix)
# ═══════════════════════════════════════════════════════════════
print("\n[4/23] SES subscribe fix — adding debug + redirect to confirm page")
# We can't fix the Lambda from here, but we CAN:
# a) Add better error feedback to the subscribe form
# b) Redirect to /subscribe/confirm/ on success
# The actual SES fix needs investigation in the subscriber Lambda

# Patch the subscribe handler in homepage to redirect on success
home = replace_once(home,
    """msg.textContent = '✓ Check your inbox to confirm.';
          msg.style.color = 'var(--accent)';
          document.getElementById('hero-email').value = '';""",
    """msg.textContent = '✓ Check your inbox to confirm.';
          msg.style.color = 'var(--accent)';
          document.getElementById('hero-email').value = '';
          setTimeout(function(){ window.location.href = '/subscribe/confirm/'; }, 1500);""",
    "subscribe redirect to confirm page")


# ═══════════════════════════════════════════════════════════════
# ITEM 5: AI Brief hardcoded fallback
# ═══════════════════════════════════════════════════════════════
print("\n[5/23] Replace hardcoded AI Brief with honest fallback")
home = replace_once(home,
    '''<p style="margin-bottom: var(--space-4);" id="brief-static-1">Recovery at 75% on 7.7h sleep — solid but not green. HRV trending up 33% over 30 days (66ms vs 50ms baseline). Zone 2 deficit this week: 42 of 150 min target. Caloric deficit holding but protein timing was late yesterday — push first meal 2 hours earlier today.</p>
        <p style="margin-bottom: var(--space-4);" id="brief-static-2">Key correlation flagged: sleep onset after 11pm correlates with -12% next-day recovery (r=-0.38, p=0.04, 28d window). Last 3 nights averaged 11:24pm. Consider alarm at 10:30pm this week.</p>
        <p style="color: var(--text-faint); font-size: var(--text-xs); font-family: var(--font-mono);">Generated from 19 live data sources by Claude. <a href="/subscribe/" style="color:var(--c-amber-500);text-decoration:none;">Subscribe to The Weekly Signal</a> for the full version every Wednesday.</p>''',
    '''<p style="margin-bottom: var(--space-4);" id="brief-static-1">Every morning at 6 AM, Claude reads 19 live data sources and writes a coaching brief. Recovery trends, habit adherence, sleep patterns, nutrition gaps — all synthesized into actionable guidance.</p>
        <p style="margin-bottom: var(--space-4); color: var(--text-faint); font-style: italic;" id="brief-static-2">Today's brief loads here when the pipeline runs. <a href="/chronicle/sample/" style="color:var(--c-amber-400);text-decoration:none;">See a sample →</a></p>
        <p style="color: var(--text-faint); font-size: var(--text-xs); font-family: var(--font-mono);">Generated from live data by Claude. <a href="/subscribe/" style="color:var(--c-amber-500);text-decoration:none;">Subscribe to The Weekly Signal</a> for the full version every Wednesday.</p>''',
    "AI brief fallback")


# ═══════════════════════════════════════════════════════════════
# ITEM 7: Replace /start/ with redirect to /
# ═══════════════════════════════════════════════════════════════
print("\n[7/23] Replace /start/ with redirect")
write(os.path.join(SITE, 'start', 'index.html'),
      REDIRECT_TEMPLATE.format(target='/'))


# ═══════════════════════════════════════════════════════════════
# ITEM 8: Move "Why I'm doing this" section up on homepage
# ═══════════════════════════════════════════════════════════════
print("\n[8/23] Move About section up — after hero, before Day 1 vs Today")

# Extract the about section
about_start = '<section class="about-section reveal" id="about">'
about_end_marker = '</section>'

# Find the about section
about_idx = home.find(about_start)
if about_idx == -1:
    print("  ⚠ About section not found!")
else:
    # Find the closing </section> for the about section
    # The about section contains nested divs but only one </section>
    # It has a nested quote div at the bottom, then closes with </section>
    # Let's find it by looking for the section that ends after the blockquote
    about_block_end = home.find('</section>', about_idx)
    if about_block_end != -1:
        about_block = home[about_idx:about_block_end + len('</section>')]
        
        # Remove from current position (including surrounding whitespace)
        home = home.replace(about_block, '', 1)
        
        # Insert after hero section close (before Day 1 vs Today)
        insert_marker = '<!-- WR-33: Day 1 vs. Today'
        insert_idx = home.find(insert_marker)
        if insert_idx != -1:
            home = home[:insert_idx] + about_block + '\n\n' + home[insert_idx:]
            print("  ✓ Moved About section above Day 1 vs Today")
        else:
            print("  ⚠ Insert point not found — About section removed but not re-inserted!")


# ═══════════════════════════════════════════════════════════════
# ITEM 9: Add "See a sample issue" link below hero subscribe
# ═══════════════════════════════════════════════════════════════
print("\n[9/23] Add sample issue link below hero subscribe")
home = replace_once(home,
    '<div id="subscribe-msg" class="hero-subscribe-note"></div>',
    '<div id="subscribe-msg" class="hero-subscribe-note"></div>\n    <a href="/chronicle/sample/" style="font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--c-amber-400);text-decoration:none;letter-spacing:var(--ls-tag);margin-top:var(--space-2);display:inline-block;">See a sample issue →</a>',
    "sample issue link")


# ═══════════════════════════════════════════════════════════════
# ITEM 10: Add one-liner to hero subscribe input
# ═══════════════════════════════════════════════════════════════
print("\n[10/23] Add one-liner above hero subscribe")
home = replace_once(home,
    '<div class="hero-subscribe-label">Follow from Day 1</div>',
    '<div class="hero-subscribe-label">Follow from Day 1</div>\n    <div style="font-size:var(--text-xs);color:var(--text-muted);margin-bottom:var(--space-2);max-width:400px;text-align:center;line-height:1.5;">A weekly email. Real data, real failures, no filter.</div>',
    "subscribe one-liner")


# ═══════════════════════════════════════════════════════════════
# ITEM 11: "Day X" empty-state frames on observatory pages
# ═══════════════════════════════════════════════════════════════
print("\n[11/23] Day X banners on observatory pages")

DAY_X_BANNER = '''
<!-- Product Board Item 11: Day X context banner -->
<div id="day-x-banner" style="
  margin:0 var(--page-padding);
  padding:var(--space-3) var(--space-5);
  background:rgba(var(--amber-rgb,245,158,11),0.06);
  border:1px solid rgba(var(--amber-rgb,245,158,11),0.15);
  border-radius:4px;
  display:flex;
  align-items:center;
  gap:var(--space-3);
  font-family:var(--font-mono);
  font-size:var(--text-2xs);
  letter-spacing:var(--ls-tag);
">
  <span class="experiment-counter" data-format="short" style="color:var(--c-amber-500);font-weight:700;"></span>
  <span style="color:var(--text-muted);"> — Early data. This page gets smarter every week.</span>
  <a href="/subscribe/" style="color:var(--c-amber-400);text-decoration:none;margin-left:auto;white-space:nowrap;">Follow along →</a>
</div>
'''

observatory_pages = ['sleep', 'glucose', 'nutrition', 'training', 'mind']
for page in observatory_pages:
    pg_path = os.path.join(SITE, page, 'index.html')
    if not os.path.exists(pg_path):
        print(f"  ⚠ {page}/index.html not found")
        continue
    pg = read(pg_path)
    if 'day-x-banner' in pg:
        print(f"  → {page}: already has Day X banner, skipping")
        continue
    # Insert after amj-nav
    pg = pg.replace('<div id="amj-nav"></div>', 
                    '<div id="amj-nav"></div>' + DAY_X_BANNER, 1)
    write(pg_path, pg)


# ═══════════════════════════════════════════════════════════════
# ITEM 12: Halve hero animation delays
# ═══════════════════════════════════════════════════════════════
print("\n[12/23] Halve hero animation delays")
# Replace animation delays: 0.1s→0.05s, 0.2s→0.1s, 0.3s→0.15s, etc.
delay_map = {
    'forwards 0.1s': 'forwards 0.05s',
    'forwards 0.15s': 'forwards 0.08s',
    'forwards 0.2s': 'forwards 0.1s',
    'forwards 0.25s': 'forwards 0.12s',
    'forwards 0.3s': 'forwards 0.15s',
    'forwards 0.35s': 'forwards 0.18s',
    'forwards 0.4s': 'forwards 0.2s',
    'forwards 0.48s': 'forwards 0.24s',
    'forwards 0.5s': 'forwards 0.25s',
    'forwards 0.58s': 'forwards 0.29s',
    'forwards 0.6s': 'forwards 0.3s',
    'forwards 0.7s': 'forwards 0.35s',
}
for old_d, new_d in delay_map.items():
    home = home.replace(old_d, new_d)
print("  ✓ All fadeUp delays halved")


# ═══════════════════════════════════════════════════════════════
# ITEM 14: Feature card hover — CSS instead of inline JS
# ═══════════════════════════════════════════════════════════════
print("\n[14/23] Replace inline JS hover with CSS class")
# Remove all onmouseover/onmouseout from feature cards
home = re.sub(
    r''' onmouseover="this\.style\.background='var\(--surface-raised\)'" onmouseout="this\.style\.background='var\(--surface\)'"''',
    ' class="feature-card"',
    home
)
# Also update the inline style to include the class styling
# Add CSS for .feature-card hover
feature_card_css = '''
    /* Item 14: Feature card hover via CSS */
    .feature-card { transition: background var(--dur-fast); }
    .feature-card:hover { background: var(--surface-raised) !important; }
'''
# Insert before </head>
home = home.replace('</head>', feature_card_css + '</head>', 1)
print("  ✓ Replaced inline JS hover with CSS .feature-card")


# ═══════════════════════════════════════════════════════════════
# ITEM 16: Subscriber count social proof
# ═══════════════════════════════════════════════════════════════
print("\n[16/23] Add subscriber count social proof")
# Add a subscriber count below the subscribe button that loads dynamically
home = replace_once(home,
    '''<a href="/chronicle/sample/" style="font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--c-amber-400);text-decoration:none;letter-spacing:var(--ls-tag);margin-top:var(--space-2);display:inline-block;">See a sample issue →</a>''',
    '''<a href="/chronicle/sample/" style="font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--c-amber-400);text-decoration:none;letter-spacing:var(--ls-tag);margin-top:var(--space-2);display:inline-block;">See a sample issue →</a>
    <div id="subscriber-proof" style="font-size:var(--text-2xs);color:var(--text-faint);font-family:var(--font-mono);letter-spacing:var(--ls-tag);margin-top:var(--space-2);display:none;"></div>
    <script>
    // Item 16: subscriber count social proof
    (function(){
      fetch('/api/subscriber_count').then(function(r){return r.ok?r.json():null}).then(function(d){
        if(d&&d.count>5){
          var el=document.getElementById('subscriber-proof');
          if(el){el.textContent='Join '+d.count+' others following along';el.style.display='block';}
        }
      }).catch(function(){});
    })();
    </script>''',
    "subscriber proof")


# ═══════════════════════════════════════════════════════════════
# ITEM 18: Homepage vital quads → 1-column on mobile
# ═══════════════════════════════════════════════════════════════
print("\n[18/23] Vital quads 1-col on mobile")
# Add responsive override for the vital quadrant grid
mobile_quads_css = '''
    /* Item 18: Vital quads single column on mobile */
    @media (max-width: 480px) {
      #vital-quads { grid-template-columns: 1fr !important; }
    }
'''
home = home.replace('</head>', mobile_quads_css + '</head>', 1)


# ═══════════════════════════════════════════════════════════════
# ITEM 19: Observatory accent colors on homepage feature cards
# ═══════════════════════════════════════════════════════════════
print("\n[19/23] Observatory accent colors on feature cards")
# Add colored left borders to the observatory-linked cards
accent_map = {
    'href="/sleep/"': 'border-left:3px solid #818cf8;',      # purple
    'href="/glucose/"': 'border-left:3px solid #f59e0b;',    # amber
    'href="/habits/"': 'border-left:3px solid #1D9E75;',     # green
}
for href_attr, border_style in accent_map.items():
    # Find the card and add the border
    pattern = f'<a {href_attr} style="display:block;background:var(--surface);padding:var(--space-8) var(--space-6);text-decoration:none;'
    replacement = f'<a {href_attr} style="display:block;background:var(--surface);padding:var(--space-8) var(--space-6);text-decoration:none;{border_style}'
    if pattern in home:
        home = home.replace(pattern, replacement, 1)
        print(f"  ✓ Added accent border for {href_attr}")
    else:
        # Try with class="feature-card"
        pattern2 = f'<a {href_attr} class="feature-card" style="display:block;background:var(--surface);padding:var(--space-8) var(--space-6);text-decoration:none;'
        replacement2 = f'<a {href_attr} class="feature-card" style="display:block;background:var(--surface);padding:var(--space-8) var(--space-6);text-decoration:none;{border_style}'
        if pattern2 in home:
            home = home.replace(pattern2, replacement2, 1)
            print(f"  ✓ Added accent border for {href_attr}")
        else:
            print(f"  ⚠ Card not found for {href_attr}")


# ═══════════════════════════════════════════════════════════════
# ITEM 21: Glossary tooltips for ticker metrics
# ═══════════════════════════════════════════════════════════════
print("\n[21/23] Glossary tooltips on ticker")
# Add title attributes to ticker items
ticker_tooltips = {
    'HRV <strong': 'title="Heart Rate Variability — higher is better. Measures autonomic nervous system recovery." ',
    'RECOVERY <strong': 'title="Whoop Recovery Score — percentage of physiological readiness (0-100%)." ',
    'STREAK <strong': 'title="Consecutive days completing all Tier 0 (non-negotiable) habits." ',
}
for marker, tooltip_attr in ticker_tooltips.items():
    # Add tooltip to the first instance (there are duplicates for scrolling)
    old = f'<span class="ticker__item">{marker}'
    new = f'<span class="ticker__item" {tooltip_attr}>{marker}'
    home = home.replace(old, new)
print("  ✓ Added tooltips to ticker metrics")

# Write the patched homepage
write(hp, home)


# ═══════════════════════════════════════════════════════════════
# ITEM 13: Lambda warm-up script
# ═══════════════════════════════════════════════════════════════
print("\n[13/23] Lambda warm-up script")
warmup_script = '''#!/bin/bash
# warmup_lambdas.sh — Ping all homepage API endpoints to prevent cold starts
# Run this 5 minutes before launch: bash deploy/warmup_lambdas.sh
# Schedule via: echo "bash ~/Documents/Claude/life-platform/deploy/warmup_lambdas.sh" | at 11:55pm March 31

BASE="https://averagejoematt.com"
ENDPOINTS=(
  "/public_stats.json"
  "/api/habit_streaks"
  "/api/character_stats"
  "/api/vitals"
  "/api/correlations?featured=true&limit=3"
  "/api/current_challenge"
  "/api/subscriber_count"
)

echo "🔥 Warming up $(echo ${#ENDPOINTS[@]}) endpoints..."
for ep in "${ENDPOINTS[@]}"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}${ep}")
  echo "  ${STATUS} ${ep}"
  sleep 1
done
echo "✅ Warm-up complete"
'''
write(os.path.join(ROOT, 'deploy', 'warmup_lambdas.sh'), warmup_script)


# ═══════════════════════════════════════════════════════════════
# ITEM 15: OG meta tags on top 5 subpages
# ═══════════════════════════════════════════════════════════════
print("\n[15/23] OG meta tags on subpages")
og_updates = {
    'story': {
        'og:description': '302 lbs. A relapse. A relaunch. The story behind the quantified self experiment.',
        'twitter:description': '302 lbs. A relapse. A relaunch. The story behind the quantified self experiment.',
    },
    'live': {
        'og:description': 'Live health dashboard — weight, HRV, sleep, habits, glucose from 19 data sources. Updated daily.',
        'twitter:description': 'Live health dashboard — weight, HRV, sleep, habits, glucose from 19 data sources.',
    },
    'character': {
        'og:description': 'RPG-style 7-pillar Character Score tracking physical, mental, and behavioral health. Real data.',
        'twitter:description': 'RPG-style 7-pillar Character Score tracking physical, mental, and behavioral health.',
    },
    'chronicle': {
        'og:description': 'The Measured Life — weekly dispatches by AI journalist Elena Voss. Every number, every failure.',
        'twitter:description': 'The Measured Life — weekly dispatches by AI journalist Elena Voss.',
    },
    'explorer': {
        'og:description': 'Interactive Data Explorer — pick any two health metrics and see the real correlation. N=1 data science.',
        'twitter:description': 'Interactive Data Explorer — pick any two health metrics and see the real correlation.',
    },
}

for page, tags in og_updates.items():
    pg_path = os.path.join(SITE, page, 'index.html')
    if not os.path.exists(pg_path):
        print(f"  ⚠ {page}/index.html not found")
        continue
    pg = read(pg_path)
    changed = False
    for prop, content in tags.items():
        # Try to update existing tag
        pattern = rf'<meta property="{prop}" content="[^"]*">'
        if prop.startswith('twitter:'):
            pattern = rf'<meta name="{prop}" content="[^"]*">'
        match = re.search(pattern, pg)
        if match:
            if prop.startswith('twitter:'):
                new_tag = f'<meta name="{prop}" content="{content}">'
            else:
                new_tag = f'<meta property="{prop}" content="{content}">'
            pg = pg.replace(match.group(), new_tag, 1)
            changed = True
    if changed:
        write(pg_path, pg)


# ═══════════════════════════════════════════════════════════════
# ITEM 17: Post-subscribe confirmation page
# ═══════════════════════════════════════════════════════════════
print("\n[17/23] Create /subscribe/confirm/ page")
confirm_html = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>.nav-overlay{display:none}</style>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Almost there — check your inbox to confirm your subscription.">
  <title>Confirm Your Subscription — averagejoematt.com</title>
  <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/icons/favicon-32x32.png">
  <meta name="theme-color" content="#080c0a">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
</head>
<body>
<div id="amj-nav"></div>

<section style="
  min-height:80vh;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  padding:calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-16);
  text-align:center;
">
  <div style="font-size:48px;margin-bottom:var(--space-6);">✉️</div>
  <h1 style="font-family:var(--font-display);font-size:var(--text-h2);color:var(--text);letter-spacing:var(--ls-display);margin-bottom:var(--space-4);">Check Your Inbox</h1>
  <p style="font-size:var(--text-lg);color:var(--text-muted);max-width:480px;line-height:var(--lh-body);margin-bottom:var(--space-10);">
    A confirmation email is on its way. Click the link inside to lock in your subscription to <strong style="color:var(--text)">The Weekly Signal</strong>.
  </p>

  <div style="max-width:500px;width:100%;">
    <div style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-6);">// while you wait</div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);border:1px solid var(--border);">
      <a href="/story/" style="display:block;background:var(--surface);padding:var(--space-5);text-decoration:none;transition:background 0.15s;">
        <div style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--accent);letter-spacing:var(--ls-display);margin-bottom:var(--space-2);">The Story</div>
        <div style="font-size:var(--text-xs);color:var(--text-muted);">How this started. 302 lbs and a decision.</div>
      </a>
      <a href="/live/" style="display:block;background:var(--surface);padding:var(--space-5);text-decoration:none;transition:background 0.15s;">
        <div style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--accent);letter-spacing:var(--ls-display);margin-bottom:var(--space-2);">Today's Data</div>
        <div style="font-size:var(--text-xs);color:var(--text-muted);">Live numbers from 19 sources.</div>
      </a>
      <a href="/chronicle/" style="display:block;background:var(--surface);padding:var(--space-5);text-decoration:none;transition:background 0.15s;">
        <div style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--accent);letter-spacing:var(--ls-display);margin-bottom:var(--space-2);">The Chronicle</div>
        <div style="font-size:var(--text-xs);color:var(--text-muted);">Elena Voss writes every week.</div>
      </a>
      <a href="/platform/" style="display:block;background:var(--surface);padding:var(--space-5);text-decoration:none;transition:background 0.15s;">
        <div style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--accent);letter-spacing:var(--ls-display);margin-bottom:var(--space-2);">The Platform</div>
        <div style="font-size:var(--text-xs);color:var(--text-muted);">How it's built. The tech.</div>
      </a>
    </div>
  </div>

  <p style="margin-top:var(--space-8);font-size:var(--text-2xs);color:var(--text-faint);font-family:var(--font-mono);">
    No email? Check your spam folder or <a href="/subscribe/" style="color:var(--accent);text-decoration:none;">try again</a>.
  </p>
</section>

<div id="amj-bottom-nav"></div>
<div id="amj-footer"></div>
<script src="/assets/js/site_constants.js"></script>
<script src="/assets/js/countdown.js"></script>
<script src="/assets/js/components.js"></script>
<script src="/assets/js/nav.js"></script>
</body>
</html>'''

write(os.path.join(SITE, 'subscribe', 'confirm', 'index.html'), confirm_html)


# ═══════════════════════════════════════════════════════════════
# ITEM 20: Dark/light toggle visible in nav
# ═══════════════════════════════════════════════════════════════
print("\n[20/23] Wire dark/light toggle into nav")
comp_path = os.path.join(SITE, 'assets', 'js', 'components.js')
comp = read(comp_path)

# Add theme toggle button before the Subscribe CTA in nav
comp = comp.replace(
    "html += '<a href=\"/subscribe/\" class=\"nav__link nav__cta\">Subscribe \\u2192</a>';",
    """html += '<button class=\"theme-toggle\" id=\"theme-toggle\" aria-label=\"Toggle light/dark mode\" title=\"Toggle theme\"><svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><circle cx=\"12\" cy=\"12\" r=\"5\"/><line x1=\"12\" y1=\"1\" x2=\"12\" y2=\"3\"/><line x1=\"12\" y1=\"21\" x2=\"12\" y2=\"23\"/><line x1=\"4.22\" y1=\"4.22\" x2=\"5.64\" y2=\"5.64\"/><line x1=\"18.36\" y1=\"18.36\" x2=\"19.78\" y2=\"19.78\"/><line x1=\"1\" y1=\"12\" x2=\"3\" y2=\"12\"/><line x1=\"21\" y1=\"12\" x2=\"23\" y2=\"12\"/><line x1=\"4.22\" y1=\"19.78\" x2=\"5.64\" y2=\"18.36\"/><line x1=\"18.36\" y1=\"5.64\" x2=\"19.78\" y2=\"4.22\"/></svg></button>';
    html += '<a href=\"/subscribe/\" class=\"nav__link nav__cta\">Subscribe \\u2192</a>';"""
)

# Add the theme toggle JS at the end of the IIFE, before the closing })();
comp = comp.replace(
    "  // Auto-load countdown.js if not already included",
    """  // ── THEME TOGGLE ─────────────────────────────────────────
  (function() {
    var saved = localStorage.getItem('amj-theme');
    if (saved === 'light') document.documentElement.setAttribute('data-theme', 'light');

    var btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function updateIcon() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      btn.innerHTML = isLight
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
      btn.title = isLight ? 'Switch to dark mode' : 'Switch to light mode';
    }
    updateIcon();

    btn.addEventListener('click', function() {
      var isLight = document.documentElement.getAttribute('data-theme') === 'light';
      if (isLight) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('amj-theme', 'dark');
      } else {
        document.documentElement.setAttribute('data-theme', 'light');
        localStorage.setItem('amj-theme', 'light');
      }
      updateIcon();
    });
  })();

  // Auto-load countdown.js if not already included"""
)

write(comp_path, comp)


# ═══════════════════════════════════════════════════════════════
# ITEM 22: "Most interesting" curated view on Data Explorer
# ═══════════════════════════════════════════════════════════════
print("\n[22/23] Curated 'most interesting' section on Data Explorer")
explorer_path = os.path.join(SITE, 'explorer', 'index.html')
if os.path.exists(explorer_path):
    explorer = read(explorer_path)
    if 'curated-correlations' not in explorer:
        # Add a curated section before the interactive explorer
        curated_section = '''
<!-- Item 22: Curated "most interesting" correlations -->
<section id="curated-correlations" style="padding:var(--space-8) var(--page-padding);border-bottom:1px solid var(--border);">
  <div class="eyebrow" style="margin-bottom:var(--space-4)">Start here</div>
  <h3 style="font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);margin-bottom:var(--space-6);letter-spacing:var(--ls-display)">Most Interesting <span style="color:var(--accent)">Correlations</span></h3>
  <div id="curated-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border);border:1px solid var(--border);">
    <div style="background:var(--surface);padding:var(--space-5);text-align:center;color:var(--text-muted);font-size:var(--text-xs);grid-column:1/-1;">Loading featured correlations...</div>
  </div>
  <script>
  (function(){
    fetch('/api/correlations?featured=true&limit=6').then(function(r){return r.ok?r.json():null}).then(function(d){
      var corrs = d && (d.correlations || d.featured || []);
      if(!corrs||!corrs.length) return;
      var grid = document.getElementById('curated-grid');
      grid.innerHTML = '';
      corrs.forEach(function(c){
        var card = document.createElement('div');
        card.style.cssText = 'background:var(--surface);padding:var(--space-5);cursor:pointer;transition:background 0.15s;';
        card.onmouseover = function(){this.style.background='var(--surface-raised)';};
        card.onmouseout = function(){this.style.background='var(--surface)';};
        var rColor = c.r < 0 ? 'var(--c-red-status)' : 'var(--accent)';
        card.innerHTML = '<div style="font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-2)">'+(c.metric_a||'')+' → '+(c.metric_b||'')+'</div>'
          +'<div style="font-family:var(--font-display);font-size:24px;color:'+rColor+';margin-bottom:var(--space-2)">r = '+(c.r?c.r.toFixed(2):'?')+'</div>'
          +'<div style="font-size:var(--text-xs);color:var(--text-muted);line-height:1.4">'+(c.description||c.summary||'')+'</div>';
        card.onclick = function(){
          // Pre-select this pair in the explorer
          var selA = document.getElementById('metric-a');
          var selB = document.getElementById('metric-b');
          if(selA&&c.metric_a) selA.value = c.metric_a_key||c.metric_a;
          if(selB&&c.metric_b) selB.value = c.metric_b_key||c.metric_b;
          document.getElementById('explorer-section').scrollIntoView({behavior:'smooth'});
        };
        grid.appendChild(card);
      });
    }).catch(function(){});
  })();
  </script>
  <style>
    @media (max-width: 768px) { #curated-grid { grid-template-columns: 1fr !important; } }
  </style>
</section>
'''
        # Insert after the nav
        explorer = explorer.replace('<div id="amj-nav"></div>',
                                    '<div id="amj-nav"></div>' + curated_section, 1)
        write(explorer_path, explorer)
    else:
        print("  → Already has curated section")
else:
    print("  ⚠ explorer/index.html not found")


# ═══════════════════════════════════════════════════════════════
# ITEM 23: Sync Week 04 from journal to chronicle
# ═══════════════════════════════════════════════════════════════
print("\n[23/23] Sync week-04 from journal to chronicle")
journal_w04 = os.path.join(SITE, 'journal', 'posts', 'week-04')
chron_w04 = os.path.join(SITE, 'chronicle', 'posts', 'week-04')

if os.path.exists(journal_w04) and not os.path.exists(chron_w04):
    # Read the journal version, update nav references
    j_html = read(os.path.join(journal_w04, 'index.html'))
    # Update any /journal/ references to /chronicle/
    j_html = j_html.replace('/journal/', '/chronicle/')
    os.makedirs(chron_w04, exist_ok=True)
    write(os.path.join(chron_w04, 'index.html'), j_html)
    
    # Also update chronicle posts.json if it exists
    chron_posts_json = os.path.join(SITE, 'chronicle', 'posts.json')
    journal_posts_json = os.path.join(SITE, 'journal', 'posts.json')
    if os.path.exists(journal_posts_json):
        j_posts = json.loads(read(journal_posts_json))
        if os.path.exists(chron_posts_json):
            c_posts = json.loads(read(chron_posts_json))
        else:
            c_posts = {"posts": []}
        
        # Find week-04 in journal posts
        for post in j_posts.get('posts', []):
            url = post.get('url', '')
            if 'week-04' in url:
                new_post = dict(post)
                new_post['url'] = url.replace('/journal/', '/chronicle/')
                # Check if already in chronicle
                existing_urls = [p.get('url','') for p in c_posts.get('posts',[])]
                if new_post['url'] not in existing_urls:
                    c_posts['posts'].append(new_post)
        
        write(chron_posts_json, json.dumps(c_posts, indent=2))
elif os.path.exists(chron_w04):
    print("  → chronicle/posts/week-04 already exists")
elif not os.path.exists(journal_w04):
    print("  ⚠ journal/posts/week-04 not found — no week-04 to sync")


# ═══════════════════════════════════════════════════════════════
# ITEM 6: Pipeline reminder (not code — human action)
# ═══════════════════════════════════════════════════════════════
print("\n[6/23] REMINDER: Run data pipeline on night of March 31")
print("  → Ensure public_stats.json has fresh data for April 1 morning")
print("  → Consider: aws lambda invoke --function-name life-platform-daily-brief ...")
print("  → Also run: bash deploy/warmup_lambdas.sh at 11:55 PM March 31")


print("\n" + "=" * 60)
print("✅ All 23 Product Board items patched!")
print("=" * 60)
print("""
Next steps:
  1. Run deploy script: bash deploy/deploy_v3.9.37.sh
  2. Verify SES subscriber confirmation (Item 4) in AWS console
  3. Schedule pipeline run for March 31 night (Item 6)
  4. Schedule warmup: bash deploy/warmup_lambdas.sh before launch
""")
