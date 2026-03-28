#!/usr/bin/env python3
"""
patch_character_ring.py — Add 7-segment pillar ring chart to character page
Design Brief: "Character page pillar ring chart (SVG — 7-segment ring in pillar colors, animated fill on load)"

Run: python3 deploy/patch_character_ring.py
"""
import os

PROJECT_ROOT = os.path.expanduser("~/Documents/Claude/life-platform")
CHAR_PAGE = os.path.join(PROJECT_ROOT, "site", "character", "index.html")

# CSS for the pillar ring chart
RING_CSS = """
    /* ── DB-RING: 7-Segment Pillar Ring Chart ────────────── */
    .pillar-ring-wrap {
      width: 180px; height: 180px;
      margin: 0 auto;
      position: relative;
    }
    .pillar-ring-wrap svg { width: 100%; height: 100%; }
    .pillar-ring__segment {
      fill: none;
      stroke-width: 10;
      stroke-linecap: butt;
      opacity: 0.15;
    }
    .pillar-ring__fill {
      fill: none;
      stroke-width: 10;
      stroke-linecap: butt;
      transition: stroke-dashoffset 1.4s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .pillar-ring__center {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      text-align: center;
    }
    .pillar-ring__score {
      font-family: var(--font-display);
      font-size: 44px;
      color: var(--tier-accent);
      line-height: 1;
    }
    .pillar-ring__label {
      font-family: var(--font-mono);
      font-size: var(--text-2xs);
      letter-spacing: var(--ls-tag);
      text-transform: uppercase;
      color: var(--text-faint);
      margin-top: 2px;
    }
    @media (max-width: 600px) {
      .pillar-ring-wrap { width: 140px; height: 140px; }
      .pillar-ring__score { font-size: 36px; }
    }
"""

# JS function to render the ring chart
RING_JS = """
/* ── DB-RING: 7-Segment Pillar Ring Chart ──────────────────── */
function renderPillarRing(pillars, composite) {
  var container = document.getElementById('pillar-ring-mount');
  if (!container) return;

  var COLORS = {
    sleep:         'var(--pillar-sleep)',
    movement:      'var(--pillar-movement)',
    nutrition:     'var(--pillar-nutrition)',
    metabolic:     'var(--pillar-body)',
    mind:          'var(--pillar-mind)',
    relationships: 'var(--pillar-social)',
    consistency:   'var(--pillar-discipline)'
  };

  var R = 75, CX = 90, CY = 90;
  var GAP_DEG = 4;  // gap between segments
  var N = pillars.length || 7;
  var SEGMENT_DEG = (360 - N * GAP_DEG) / N;
  var circ = 2 * Math.PI * R;

  var svg = '<svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg">';

  pillars.forEach(function(p, i) {
    var startAngle = i * (SEGMENT_DEG + GAP_DEG) - 90;
    var segLen = (SEGMENT_DEG / 360) * circ;
    var gapLen = circ - segLen;
    var color = COLORS[p.name] || 'var(--accent)';
    var fillPct = Math.min(p.raw_score, 100) / 100;
    var fillLen = segLen * fillPct;
    var fillGap = circ - fillLen;

    // Background track
    svg += '<circle cx="' + CX + '" cy="' + CY + '" r="' + R + '" ' +
      'class="pillar-ring__segment" stroke="' + color + '" ' +
      'stroke-dasharray="' + segLen + ' ' + gapLen + '" ' +
      'stroke-dashoffset="' + (-i * (SEGMENT_DEG + GAP_DEG) * circ / 360) + '" ' +
      'transform="rotate(-90 ' + CX + ' ' + CY + ')"/>';

    // Filled arc (animated)
    svg += '<circle cx="' + CX + '" cy="' + CY + '" r="' + R + '" ' +
      'class="pillar-ring__fill" stroke="' + color + '" ' +
      'stroke-dasharray="' + fillLen + ' ' + fillGap + '" ' +
      'stroke-dashoffset="' + (-i * (SEGMENT_DEG + GAP_DEG) * circ / 360) + '" ' +
      'transform="rotate(-90 ' + CX + ' ' + CY + ')" ' +
      'style="stroke-dashoffset:' + circ + ';transition-delay:' + (0.2 + i * 0.1) + 's"/>';
  });

  svg += '</svg>';
  svg += '<div class="pillar-ring__center">';
  svg += '<div class="pillar-ring__score">' + composite.toFixed(0) + '</div>';
  svg += '<div class="pillar-ring__label">Score</div>';
  svg += '</div>';

  container.innerHTML = svg;

  // Animate: set correct dashoffset after render
  requestAnimationFrame(function() {
    requestAnimationFrame(function() {
      container.querySelectorAll('.pillar-ring__fill').forEach(function(el, i) {
        var p = pillars[i];
        var segLen = (SEGMENT_DEG / 360) * circ;
        var fillPct = Math.min(p.raw_score, 100) / 100;
        var fillLen = segLen * fillPct;
        var fillGap = circ - fillLen;
        var offset = -i * (SEGMENT_DEG + GAP_DEG) * circ / 360;
        el.style.strokeDashoffset = offset;
      });
    });
  });
}
"""

def patch():
    with open(CHAR_PAGE, "r", encoding="utf-8") as f:
        content = f.read()

    if "pillar-ring-wrap" in content:
        print("  · Character ring chart already present — skipping")
        return

    changes = []

    # 1. Add ring CSS before closing </style> in the page's <style> block
    # Find the last </style> in the <head>
    style_end = content.rfind("</style>", 0, content.find("</head>"))
    if style_end > 0:
        content = content[:style_end] + RING_CSS + "\n  " + content[style_end:]
        changes.append("CSS")

    # 2. Add mount point — replace the static tc-composite div with ring mount
    # Current: <div class="tc-composite">...<div class="tc-composite__num" id="tc-score">—</div>...
    # Replace inner content with ring mount
    old_composite = '''<div class="tc-composite">
        <div class="tc-composite__num" id="tc-score">—</div>
        <div class="tc-composite__label">Score</div>
      </div>'''
    new_composite = '''<div class="tc-composite" style="padding:var(--space-2);border-left:1px solid var(--border-subtle)">
        <div class="pillar-ring-wrap" id="pillar-ring-mount">
          <div class="pillar-ring__center">
            <div class="pillar-ring__score" id="tc-score">—</div>
            <div class="pillar-ring__label">Score</div>
          </div>
        </div>
      </div>'''

    if old_composite in content:
        content = content.replace(old_composite, new_composite)
        changes.append("mount point")

    # 3. Add JS function before the hydrate() function
    marker = "/* ── Main hydrate ──"
    if marker in content and "renderPillarRing" not in content:
        content = content.replace(marker, RING_JS + "\n" + marker)
        changes.append("JS function")

    # 4. Add renderPillarRing call inside hydrate()
    call_marker = "// Composite score\n    const scores = pillars.map(p => p.raw_score);"
    if call_marker in content and "renderPillarRing" not in content:
        content = content.replace(
            call_marker,
            call_marker + "\n    renderPillarRing(pillars, scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0);"
        )
        changes.append("hydrate call")

    if changes:
        with open(CHAR_PAGE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ Character ring chart added [{', '.join(changes)}]")
    else:
        print("  ⚠ Could not find expected markers — manual patch needed")


if __name__ == "__main__":
    print("\n═══ Character Page — Pillar Ring Chart ═══\n")
    patch()
    print("\nDeploy: aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude '.DS_Store'")
