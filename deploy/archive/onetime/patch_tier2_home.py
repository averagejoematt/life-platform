#!/usr/bin/env python3
"""
patch_tier2_home.py — Add sparkline containers + count-up attributes to home page vital quadrants.
Idempotent: checks for existing sparkline containers before adding.

Changes:
1. Adds <canvas> sparkline placeholders in each vital quadrant
2. Adds data-count-up attributes to hero weight, progress %, stat chips
3. Adds JS to render 7-day SVG sparklines from public_stats.json trends
"""
import os, re

SITE = os.path.expanduser("~/Documents/Claude/life-platform/site")
HOME = os.path.join(SITE, "index.html")

with open(HOME, "r") as f:
    content = f.read()

changes = 0

# 1. Add sparkline containers to vital quadrants
# Each quadrant (q-body, q-rec, q-beh, q-mind) gets a sparkline <div>
SPARKLINE_DIV = '<div class="home-sparkline" id="spark-{key}" style="height:24px;margin-top:var(--space-2);"></div>'

for key in ['body', 'rec', 'beh', 'mind']:
    spark_id = f'spark-{key}'
    if spark_id in content:
        print(f"  SKIP: {spark_id} already exists")
        continue
    
    # Find the closing </div> of each quadrant's sub text
    # Pattern: id="q-{key}-sub"...>...</div> followed by </div> (end of quadrant)
    sub_id = f'q-{key}-sub'
    pattern = f'(id="{sub_id}"[^>]*>[^<]*</div>)'
    match = re.search(pattern, content)
    if match:
        replacement = match.group(1) + '\n        ' + SPARKLINE_DIV.format(key=key)
        content = content.replace(match.group(1), replacement, 1)
        changes += 1
        print(f"  ADD: sparkline container #{spark_id}")

# 2. Add sparkline renderer JS (after the vital signs loader)
SPARKLINE_JS = '''
<script>
// Tier 2: Home sparklines — render 7-day SVG sparklines in vital quadrants
(function() {
  function miniSpark(containerId, values, color) {
    var el = document.getElementById(containerId);
    if (!el || !values || values.length < 2) return;
    var clean = values.filter(function(v){ return v !== null && v !== undefined; });
    if (clean.length < 2) return;
    var W = el.offsetWidth || 120, H = 24;
    var min = Math.min.apply(null, clean), max = Math.max.apply(null, clean);
    var range = max - min || 1;
    var step = W / (clean.length - 1);
    var pts = clean.map(function(v, i) {
      return (i * step).toFixed(1) + ',' + (H - ((v - min) / range) * (H - 4) - 2).toFixed(1);
    });
    var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg">';
    svg += '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + color + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.6"/>';
    // Dot on last point
    var last = pts[pts.length - 1].split(',');
    svg += '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.5" fill="' + color + '"/>';
    svg += '</svg>';
    el.innerHTML = svg;
  }

  // Wait for public_stats to load, then render sparklines
  function tryRender() {
    var stats = window.__amjStats;
    if (!stats || !stats.trends) return false;
    var t = stats.trends;
    var C = { green: '#1D9E75', amber: '#BA7517', gray: '#4a6050' };
    
    // Body: weight trend
    if (t.weight_daily) {
      var wv = t.weight_daily.map(function(r){ return r.lbs; }).slice(-7);
      miniSpark('spark-body', wv, C.green);
    }
    // Recovery: HRV trend
    if (t.hrv_daily) {
      var hv = t.hrv_daily.map(function(r){ return r.ms; }).slice(-7);
      miniSpark('spark-rec', hv, C.green);
    }
    return true;
  }

  if (!tryRender()) {
    setTimeout(function() { tryRender(); }, 1500);
  }
})();
</script>
'''

if 'miniSpark' not in content:
    # Insert before closing </body>
    content = content.replace('</body>', SPARKLINE_JS + '\n</body>', 1)
    changes += 1
    print("  ADD: sparkline renderer JS")
else:
    print("  SKIP: sparkline JS already present")

# 3. Wire count-up on hero weight (already dynamically set by JS, but add fallback)
# The count-up in animations.js reads data-count-up attributes
# Hero weight is dynamically populated, so we wire it via JS after data loads
COUNTUP_JS = '''
<script>
// Tier 2: Wire count-up on hero values after data loads
(function() {
  function wireCountUp() {
    var stats = window.__amjStats;
    if (!stats) return false;
    var j = stats.journey || {};
    var p = stats.platform || {};
    // Hero stat chips — if they have numeric content, add count-up
    var chips = document.querySelectorAll('.chip-value, .j-stat__value');
    chips.forEach(function(el) {
      var val = parseFloat(el.textContent);
      if (!isNaN(val) && !el.hasAttribute('data-count-up')) {
        el.setAttribute('data-count-up', val);
        var suffix = el.textContent.replace(/[\\d.,-]/g, '').trim();
        if (suffix) el.setAttribute('data-count-suffix', ' ' + suffix);
        el.textContent = '0';
      }
    });
    // Re-init count-up observer if animations.js has loaded
    if (window.AMJ_REINIT_COUNTUP) window.AMJ_REINIT_COUNTUP();
    return true;
  }
  setTimeout(wireCountUp, 1200);
})();
</script>
'''

if 'wireCountUp' not in content:
    content = content.replace('</body>', COUNTUP_JS + '\n</body>', 1)
    changes += 1
    print("  ADD: count-up wiring JS")
else:
    print("  SKIP: count-up wiring already present")

with open(HOME, "w") as f:
    f.write(content)

print(f"\nHome page: {changes} changes applied")
