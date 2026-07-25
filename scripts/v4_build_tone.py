#!/usr/bin/env python3
"""v4_build_tone.py — generate /method/tone/ from lambdas/coach_register.py (#1390).

The tone-dial page: publishes the three coach registers (clinical / blunt / warm) and their
phrasing-layer prompts VERBATIM (AC#2), rendered straight from `coach_register.REGISTERS` so
the page cannot drift from the prompt actually used. The differentiation the story ships is
exactly this receipt — a reader can read the three prompts side by side and see that each one
only changes phrasing, never the numbers/verdicts/citations (the deterministic payload, which
is byte-identical across registers by construction — see coach_register.compose_coach_prompt).

Deliberately standalone (mirrors scripts/v4_build_methods.py): its own builder, its own static
HTML, no evidence.js coupling, no /api dependency — so it can ship independently.

Run from repo root:  python3 scripts/v4_build_tone.py
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import coach_register as cr  # noqa: E402
from v4_chrome import doors_nav, site_footer  # noqa: E402
from v4_kit import loop_ribbon  # noqa: E402

SLUG = "tone"
CANONICAL = f"/method/{SLUG}/"
TITLE = "The tone dial — The Method — averagejoematt"
DESCRIPTION = (
    "Three coach registers — clinical, blunt, warm — with their prompts published verbatim. The dial changes the phrasing, never the facts."
)


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ── Shared chrome, copied from v4_build_methods.py for zero coupling. ─────────────
FONTS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/6NU58FyLNQOQZAnv9ZwNjucMHVn85Ni7emAe9lKqZTnbB-gzTK0K1ChjeveQ7ZXk8g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="stylesheet" href="/assets/css/fonts.css">'
)
THEME = (
    '<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
    'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>'
)
MOTION_HEAD = (
    '<script>(function(){try{if(!("IntersectionObserver" in window))return;'
    'if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'document.documentElement.classList.add("mo");'
    'window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();</script>'
)
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'


def topbar() -> str:
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">method</span></a>'
        f'{doors_nav("/data/", with_follow=False)}</header>'
    )


FOOTER = site_footer()

STYLE = """
<style>
.td-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.td-grid { display: grid; gap: var(--sp-5); margin-top: var(--sp-5); min-width: 0; }
@media (min-width: 900px) { .td-grid { grid-template-columns: repeat(3, 1fr); } }
.td-card { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; display: flex; flex-direction: column; }
.td-name { font-family: var(--font-serif); font-weight: var(--weight-med); font-size: var(--fs-h3); color: var(--ink); margin: 0; }
.td-summary { margin-top: var(--sp-2); color: var(--ink-muted); line-height: var(--lh-relaxed); }
.td-prompt-label { margin-top: var(--sp-4); font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.td-prompt { margin-top: var(--sp-2); padding: var(--sp-4); border-radius: var(--radius-xs); background: var(--surface-sunken);
  font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink); line-height: var(--lh-relaxed);
  white-space: pre-wrap; overflow-wrap: break-word; overflow-x: auto; }
.td-payload { margin-top: var(--sp-6); border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); }
.td-payload h2 { margin-top: 0; }
.td-payload pre { margin-top: var(--sp-3); padding: var(--sp-4); border-radius: var(--radius-xs); background: var(--surface-sunken);
  font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink); line-height: var(--lh-relaxed);
  white-space: pre-wrap; overflow-wrap: break-word; overflow-x: auto; }
</style>
"""

# A small, fixed example payload so the reader sees the exact bytes that stay constant across
# the three registers. Built through the real code path (not hand-authored).
_EXAMPLE_FACTS = {
    "metrics": [
        {"name": "hrv_7d_avg", "value": 48, "unit": "ms", "confidence": "moderate"},
        {"name": "sleep_debt", "value": 3.4, "unit": "h"},
    ],
    "verdicts": [{"claim": "hrv_vs_baseline", "verdict": "below baseline", "n": 47, "p": 0.03}],
    "citations": [{"source": "whoop", "ref": "recovery 2026-07-24"}],
}


def _register_card(key: str, reg: dict) -> str:
    return (
        '<article class="td-card">'
        f'<h3 class="td-name">{esc(reg["label"])}</h3>'
        f'<p class="td-summary">{esc(reg["summary"])}</p>'
        '<p class="td-prompt-label">Phrasing prompt (verbatim)</p>'
        f'<div class="td-prompt">{esc(reg["phrasing"])}</div>'
        "</article>"
    )


def render() -> str:
    cards = "".join(_register_card(k, cr.REGISTERS[k]) for k in cr.registers())
    example_payload = cr.serialize_payload(cr.build_deterministic_payload(_EXAMPLE_FACTS))

    body = f"""<!DOCTYPE html>
<html lang="en" data-door="method">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(TITLE)}</title>
  <meta name="description" content="{esc(DESCRIPTION)}">
  <link rel="canonical" href="https://averagejoematt.com{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{CANONICAL}">
  <meta property="og:title" content="{esc(TITLE)}">
  <meta property="og:description" content="{esc(DESCRIPTION)}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-home.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(TITLE)}">
  <meta name="twitter:description" content="{esc(DESCRIPTION)}">
  <link rel="icon" href="/favicon.ico">
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/evidence.css">
  {STYLE}
  {THEME}
  {MOTION_HEAD}
</head>
<body>
  <a class="skip" href="#td">Skip to the content</a>
  {topbar()}
  <main id="td">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; the coach voice</p>
      <h1 class="ph-title">The tone dial</h1>
      <p class="ph-promise">A coach should be able to sound clinical, blunt, or warm — without any of those changing what's true. The dial only rewrites the phrasing; the numbers, verdicts, and citations underneath are computed in Python before the model is called, and are <strong>byte-identical</strong> across all three registers. Here are the three prompts, published verbatim, so you can check.</p>
      {loop_ribbon("method")}
    </div>
    <div class="td-wrap">
      <section class="rd-sec" style="margin-top:0">
        <h2 class="rd-h">The three registers</h2>
        <p class="rd-prose">Each register is nothing more than a phrasing instruction appended <em>after</em> the deterministic payload. It is never handed the raw data to recompute, so it structurally cannot change a verdict — the same guarantee the whole platform gives (<code>bedrock_client.py</code>), applied one level down to the coach voice.</p>
        <div class="td-grid">{cards}</div>
      </section>
      <section class="td-payload">
        <h2 class="rd-h">What stays constant</h2>
        <p class="rd-prose">Whichever register is selected, the model receives this exact deterministic payload — the numbers, verdicts, and citations — bracketed by sentinels it is told to treat as read-only. Only the phrasing tail above differs. A unit test (<code>tests/test_coach_register_1390.py</code>) diffs the payload region of the composed prompt across all three registers and fails if a single byte moves.</p>
        <pre>{esc(example_payload)}</pre>
      </section>
      <p class="correlative">This page is generated by <code>scripts/v4_build_tone.py</code> from <code>lambdas/coach_register.py</code> — the same module the coach surfaces call — so the prompts shown here are the prompts actually used. <span class="confidence conf-low">generated, not authored</span></p>
    </div>
  </main>
  {FOOTER}
  {MOTION_SCRIPT}
</body>
</html>
"""
    return body


def main() -> int:
    out_dir = ROOT / "site" / "method" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render(), encoding="utf-8")
    print(f"{CANONICAL}: {len(cr.registers())} registers published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
