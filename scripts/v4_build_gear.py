#!/usr/bin/env python3
"""v4_build_gear.py — generate /gear/ : the devices behind the data, with affiliate slots (#904).

A dedicated gear page — every device and app that actually feeds this platform, what it
measures, how it's held to account (the cross-device agreement checks live on
/method/verify/), and where to get it. It is the site's first passive-monetization
surface, via affiliate links.

DELIBERATELY DISTINCT FROM /method/verify/ (issue #904): the verifiability links stay
honest and separate — this page LINKS to that one for accountability, it does not merge
the two. Verify answers "is this real?"; Gear answers "what produces it, and where do I
get it?".

THE DEVICE LIST IS DERIVED, NOT GUESSED. Every card comes from
`lambdas/source_registry.py::catalog_entries()` — the authoritative registry that also
backs /data/data_sources.json and the pipeline board. The GEAR dict below only augments
each registry source with its consumer-product identity + affiliate slot; a coverage
assert (see main()) fails the build if a new source appears in the registry without a
decision here, so this page can't silently drift from the pipeline.

Deliberately standalone — its own builder, its own static HTML, no client-side
`evidence.js` dependency (same posture as scripts/v4_build_methods.py). It borrows the
shared visual chrome (fonts/tokens/doors/footer/loop-ribbon) by copying the same static
markup — the cards are server-rendered, so the page renders fully with JS off; the only
JS is the shared theme toggle + motion reveal.

┌──────────────────────────────────────────────────────────────────────────────────┐
│  HOW MATTHEW ACTIVATES AN AFFILIATE LINK  (the whole point of the placeholder gate) │
│                                                                                    │
│  Each gear entry below has an "affiliate_url" field. It ships EMPTY ("") on         │
│  purpose — the affiliate programs don't exist yet (they depend on Matthew's         │
│  sign-ups). While empty, the card renders an honest, non-clickable "affiliate       │
│  link coming soon" chip (href="#affiliate-pending", data-affiliate="pending").      │
│                                                                                    │
│  To go live for one product:                                                        │
│    1. Sign up for that vendor's affiliate/referral program, get your link.          │
│    2. Paste the full https:// URL into that entry's "affiliate_url".                │
│    3. Re-run:  python3 scripts/v4_build_gear.py                                      │
│    4. Deploy the site (site-deploy runs on merge touching site/**).                 │
│                                                                                    │
│  A filled URL renders a real outbound CTA (data-affiliate="active",                 │
│  rel="sponsored nofollow noopener", target="_blank"). Nothing else needs editing —  │
│  the FTC disclosure banner is always shown regardless.                              │
└──────────────────────────────────────────────────────────────────────────────────┘

Run from repo root:  python3 scripts/v4_build_gear.py
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_registry import catalog_entries  # noqa: E402 — the authoritative device list
from v4_chrome import doors_nav, site_footer  # noqa: E402 — shared doors nav + footer (#1009)
from v4_kit import loop_ribbon  # noqa: E402 — shared .loop-ribbon (#578)

SLUG = "gear"
CANONICAL = "/gear/"
TITLE = "The Gear — the devices behind the data — averagejoematt"
DESCRIPTION = "Every device and app that feeds this platform — what it measures, how it's kept honest, and where to get it. Some links are affiliate links."

# ── The FTC disclosure. Shown prominently, always, regardless of whether any affiliate
#    slot is filled — clear, honest, and above the first card (16 CFR Part 255). ───────
DISCLOSURE = (
    "Some links on this page are affiliate links. If you buy through one, "
    "averagejoematt.com may earn a small commission &mdash; at no additional cost to you. "
    "Nothing here is a paid placement: every item is a device or app that genuinely feeds "
    "this platform&rsquo;s data, pulled straight from its source registry. If it isn&rsquo;t "
    "in the pipeline, it isn&rsquo;t on this page."
)

# ── Per-source product augmentation. Keyed by the registry `id`. Every id returned by
#    catalog_entries() MUST appear here (coverage assert in main()).
#
#    kind:  "gear"  → a consumer product a reader can buy/subscribe to → product card
#                     with an affiliate slot.
#           "other" → in the pipeline but not a purchasable product (a free API, a
#                     hand-logged behavioural signal, or a bridge over another device) →
#                     listed honestly in the "also in the pipeline" strip, no affiliate.
#    icon:  an existing icons.svg symbol id (without the "i-" prefix). Reuse the set —
#           never introduce emoji (DESIGN_SYSTEM_V5 §8).
#    affiliate_url:  ""  = honest placeholder (see the how-to banner above). A full
#                    https:// URL = a live outbound affiliate CTA.
#    accountability: {text, href} — how this source is kept honest; href points at the
#                    cross-device agreement page (/method/verify/) or the live pipeline
#                    board (/method/pipeline/). Never invent a check that doesn't exist.
GEAR: dict[str, dict] = {
    "whoop": {
        "kind": "gear",
        "product": "Whoop band + membership",
        "vendor": "Whoop",
        "icon": "vitals",
        "affiliate_url": "",  # ← drop the Whoop referral/affiliate URL here
        "accountability": {
            "text": "Recovery, HRV and resting heart rate are cross-checked night-by-night against an independent sensor on the verify page.",
            "href": "/method/verify/",
        },
    },
    "withings": {
        "kind": "gear",
        "product": "Withings smart scale",
        "vendor": "Withings",
        "icon": "vitals",
        "affiliate_url": "",  # ← Withings affiliate URL
        "accountability": {
            "text": "Weight and body-composition trend is the anchor the tape-measure check-ins are read against.",
            "href": "/method/verify/",
        },
    },
    "strava": {
        "kind": "gear",
        "product": "Strava (subscription)",
        "vendor": "Strava",
        "icon": "training",
        "affiliate_url": "",  # ← Strava affiliate/referral URL
        "accountability": {
            "text": "Activity heart rate and step counts overlap with the wearable feeds and are reconciled against the provider's own record.",
            "href": "/method/verify/",
        },
    },
    "eightsleep": {
        "kind": "gear",
        "product": "Eight Sleep Pod cover",
        "vendor": "Eight Sleep",
        "icon": "sleep",
        "affiliate_url": "",  # ← Eight Sleep affiliate URL
        "accountability": {
            "text": "Sleep stages, HR and HRV overlap with the Whoop feed — two independent bedside sensors on the same night.",
            "href": "/method/verify/",
        },
    },
    "apple_health": {
        "kind": "gear",
        "product": "Apple Watch + Health Auto Export",
        "vendor": "Apple / Health Auto Export",
        "icon": "vitals",
        "affiliate_url": "",  # ← Apple affiliate + / or Health Auto Export link
        "accountability": {
            "text": "Steps and active energy overlap with the other movement sensors; CGM, blood pressure and mood are hand-captured through the same webhook.",
            "href": "/method/verify/",
        },
    },
    "garmin": {
        "kind": "gear",
        "product": "Garmin watch",
        "vendor": "Garmin",
        "icon": "training",
        "affiliate_url": "",  # ← Garmin affiliate URL
        "accountability": {
            "text": "Resting-heart-rate and step readings are the independent sensor Whoop is cross-checked against — though server-side ingestion is paused (ADR-074, vendor anti-automation).",
            "href": "/method/verify/",
        },
        "note": "Ingestion is paused (ADR-074) — the device is real, the automated pull isn&rsquo;t running.",
    },
    "hevy": {
        "kind": "gear",
        "product": "Hevy (workout logger)",
        "vendor": "Hevy",
        "icon": "training",
        "affiliate_url": "",  # ← Hevy affiliate/referral URL
        "accountability": {
            "text": "Single-source strength log — its freshness (a rest week reads as behaviour, never an outage) is shown live on the pipeline board.",
            "href": "/method/pipeline/",
        },
    },
    "macrofactor": {
        "kind": "gear",
        "product": "MacroFactor (nutrition app)",
        "vendor": "MacroFactor",
        "icon": "nutrition",
        "affiliate_url": "",  # ← MacroFactor affiliate/referral URL
        "accountability": {
            "text": "Calories and macros are read alongside the CGM glucose response for the same meals — the nutrition and metabolic feeds check each other.",
            "href": "/method/verify/",
        },
    },
    "habitify": {
        "kind": "gear",
        "product": "Habitify (habit tracker)",
        "vendor": "Habitify",
        "icon": "habits",
        "affiliate_url": "",  # ← Habitify affiliate/referral URL
        "accountability": {
            "text": "Single-source habit and supplement adherence — freshness is monitored on the live pipeline board.",
            "href": "/method/pipeline/",
        },
    },
    "todoist": {
        "kind": "gear",
        "product": "Todoist (task manager)",
        "vendor": "Todoist",
        "icon": "habits",
        "affiliate_url": "",  # ← Todoist affiliate URL
        "accountability": {
            "text": "Single-source completed-task signal — freshness is monitored on the live pipeline board.",
            "href": "/method/pipeline/",
        },
    },
    "notion": {
        "kind": "gear",
        "product": "Notion (journal)",
        "vendor": "Notion",
        "icon": "mind",
        "affiliate_url": "",  # ← Notion affiliate URL
        "accountability": {
            "text": "The subjective layer — journal entries the AI reads but never invents. Freshness is surfaced honestly, never paged.",
            "href": "/method/pipeline/",
        },
    },
    "measurements": {
        "kind": "gear",
        "product": "Body tape measure",
        "vendor": "any spring-loaded body tape",
        "icon": "character",
        "affiliate_url": "",  # ← tape-measure affiliate URL (e.g. an Amazon Associates link)
        "accountability": {
            "text": "Read against the Withings body-composition trend — two independent takes on the same change.",
            "href": "/method/verify/",
        },
    },
    # ── Not purchasable products — in the pipeline, listed honestly, no affiliate. ──
    "weather": {
        "kind": "other",
        "product": "Weather",
        "vendor": "Open-Meteo",
        "icon": "vitals",
        "affiliate_url": "",
        "note": "A free public API (Open-Meteo) — environmental context, nothing to buy.",
    },
    "food_delivery": {
        "kind": "other",
        "product": "Food-delivery signal",
        "vendor": "hand-logged",
        "icon": "nutrition",
        "affiliate_url": "",
        "note": "A behavioural signal logged by hand, not a device — here for completeness.",
    },
    "supplements": {
        "kind": "other",
        "product": "Supplements & medication",
        "vendor": "via Habitify",
        "icon": "nutrition",
        "affiliate_url": "",
        "note": "Adherence rides the Habitify bridge above — no separate device or app.",
    },
}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ── Shared site chrome. Copied (not imported) from scripts/v4_build_methods.py so this
#    page has zero coupling to evidence.js — the same deliberate small duplication the
#    Methods Registry makes for independence. ─────────────────────────────────────────
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
# Wire the shared one-line theme toggle (the standalone Methods Registry omits this and
# ships a dead toggle — #904 does better with a real, self-wiring module init).
THEME_SCRIPT = '<script type="module">import { initTheme } from "/assets/js/theme.js"; initTheme();</script>'
# #1015 — the page runs ~9,500px tall at 390px: mount the shared mobile section-TOC
# (sticky "on this page" jump bar; section_toc.js self-injects its stylesheet and
# assigns shareable ids to each category head). Anchored before the first section so
# the affiliate disclosure stays above it.
TOC_SCRIPT = (
    '<script type="module">import { mountSectionToc } from "/assets/js/section_toc.js"; '
    'const w = document.querySelector(".gr-wrap"); '
    'mountSectionToc(w, { before: w.querySelector(".rd-sec") });</script>'
)


# Doors nav + footer are the shared chrome partial (#1009). /gear/ is a footer-tier page
# (not one of the five doors) — no door is marked current, and there's no follow pill.
def topbar() -> str:
    return (
        '<header class="ev-top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-name">averagejoematt</span> <span class="brand-door label">gear</span></a>'
        f"{doors_nav(None, with_follow=False)}</header>"
    )


FOOTER = site_footer()

# Page-specific styling only — scoped under .gr-*, tokens-only (no hardcoded colour/
# spacing), additive per DESIGN_SYSTEM_V5 §3 ("reuse what already exists" first: this
# borrows .page-hero/.ph-*/.rd-sec/.rd-h/.rd-prose/.correlative from evidence.css and
# only adds the device-card grid, the disclosure callout, and the affiliate CTA chip).
# Earned-glow rule (§7): the ember accent lives on the live affiliate CTA only; a
# pending chip is muted ink, never ember, never red.
STYLE = """
<style>
.gr-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.gr-disclosure { margin-top: var(--sp-5); border: var(--border-hair); border-left: 3px solid var(--ember); border-radius: var(--radius);
  background: var(--surface-raised); padding: var(--sp-4) var(--sp-5); }
.gr-disclosure p { margin: 0; color: var(--ink-muted); line-height: var(--lh-relaxed); max-width: var(--measure); }
.gr-disclosure .gr-disc-h { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label);
  text-transform: uppercase; color: var(--ink-faint); margin: 0 0 var(--sp-2); }
.gr-cat-head { display: flex; align-items: baseline; gap: var(--sp-3); margin-top: var(--sp-8); }
.gr-cat-head .rd-h { border-top: 0; padding-top: 0; margin-bottom: 0; }
.gr-cat-count { color: var(--ink-faint); font-family: var(--font-mono); font-size: var(--fs-small); }
.gr-grid { display: grid; gap: var(--sp-5); margin-top: var(--sp-4); min-width: 0; }
@media (min-width: 720px) { .gr-grid { grid-template-columns: 1fr 1fr; } }
.gr-card { display: flex; flex-direction: column; border: var(--border-hair); border-radius: var(--radius);
  padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.gr-card-top { display: flex; align-items: flex-start; gap: var(--sp-3); }
.gr-ico { flex: none; color: var(--ink-faint); }
.gr-ico svg { width: 24px; height: 24px; }
.gr-head { min-width: 0; }
.gr-name { font-family: var(--font-serif); font-weight: var(--weight-med); font-size: var(--fs-h3); color: var(--ink); margin: 0; }
.gr-vendor { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); margin: var(--sp-1) 0 0; }
.gr-badge { margin-left: auto; flex: none; font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label);
  text-transform: uppercase; color: var(--ink-faint); border: var(--border-hair); border-radius: var(--radius-xs); padding: 2px var(--sp-2); }
.gr-fields { margin: var(--sp-4) 0 0; display: grid; gap: var(--sp-3); }
.gr-field dt { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.gr-field dd { margin: var(--sp-1) 0 0; color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gr-field dd a { color: var(--ember); }
.gr-note { margin-top: var(--sp-3); font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); line-height: var(--lh-relaxed); }
.gr-cta-row { margin-top: var(--sp-5); padding-top: var(--sp-4); border-top: var(--border-hair); }
.gr-cta { display: inline-flex; align-items: center; gap: var(--sp-2); font-family: var(--font-mono); font-size: var(--fs-small);
  text-decoration: none; border: var(--border-hair); border-radius: var(--radius-xs); padding: var(--sp-2) var(--sp-4); }
a.gr-cta { color: var(--ember); border-color: var(--ember); }
a.gr-cta:hover { background: var(--ember-wash); }
.gr-cta-pending { color: var(--ink-faint); cursor: default; }
.gr-cta-note { display: block; margin-top: var(--sp-2); font-family: var(--font-mono); font-size: var(--fs-label);
  letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.gr-other { display: grid; gap: var(--sp-3); margin-top: var(--sp-4); }
.gr-other li { color: var(--ink-muted); line-height: var(--lh-relaxed); }
.gr-other strong { color: var(--ink); }
</style>
"""

# icons.svg lives inline via <use>; no JS needed for the card icons.
POSTURE_LABEL = {"load-bearing": "load-bearing", "portfolio": "portfolio", "paused": "paused", "archive": "archive"}


def _cta(entry: dict) -> str:
    """The affiliate CTA — an honest placeholder while affiliate_url is empty, a real
    outbound sponsored link once Matthew fills it in (see the how-to banner at top)."""
    url = (entry.get("affiliate_url") or "").strip()
    vendor = entry["vendor"]
    if url:
        return (
            '<div class="gr-cta-row">'
            f'<a class="gr-cta" href="{esc(url)}" data-affiliate="active" target="_blank" rel="sponsored nofollow noopener">'
            f"Get it from {esc(vendor)} &rarr;</a></div>"
        )
    # Placeholder: non-clickable chip, clearly marked, easy to find + swap.
    return (
        '<div class="gr-cta-row">'
        '<span class="gr-cta gr-cta-pending" data-affiliate="pending" data-affiliate-href="#affiliate-pending" '
        f'role="note" aria-label="Affiliate link for {esc(vendor)} coming soon">'
        f'Where to get it &rarr;<span class="gr-cta-note">affiliate link coming soon</span></span></div>'
    )


def _card(reg: dict, aug: dict) -> str:
    icon = aug.get("icon", "vitals")
    badge = POSTURE_LABEL.get(reg["posture"], reg["posture"])
    fields = [
        f'<div class="gr-field"><dt>Measures</dt><dd>{esc(reg["metrics"])}</dd></div>',
        f'<div class="gr-field"><dt>How it arrives</dt><dd>{esc(reg["method"])}</dd></div>',
    ]
    acc = aug.get("accountability")
    if acc:
        fields.append(
            '<div class="gr-field"><dt>Held to account by</dt>'
            f'<dd>{acc["text"]} <a href="{esc(acc["href"])}">See how &rarr;</a></dd></div>'
        )
    note = f'<p class="gr-note">{aug["note"]}</p>' if aug.get("note") else ""
    return (
        f'<article class="gr-card" id="gear-{esc(reg["id"])}">'
        '<div class="gr-card-top">'
        f'<span class="gr-ico" aria-hidden="true"><svg viewBox="0 0 24 24"><use href="/assets/icons/icons.svg#i-{esc(icon)}"></use></svg></span>'
        f'<div class="gr-head"><h3 class="gr-name">{esc(aug["product"])}</h3><p class="gr-vendor">{esc(aug["vendor"])}</p></div>'
        f'<span class="gr-badge">{esc(badge)}</span>'
        "</div>"
        f'<dl class="gr-fields">{"".join(fields)}</dl>'
        f"{note}"
        f"{_cta(aug)}"
        "</article>"
    )


def render(entries: list[dict]) -> str:
    by_id = {e["id"]: e for e in entries}
    # Group the purchasable gear by the registry category; preserve the registry order
    # within a category (load-bearing first — catalog_entries() already sorts that way).
    cats: dict[str, list[str]] = {}
    others: list[str] = []
    for e in entries:
        aug = GEAR[e["id"]]
        if aug["kind"] == "gear":
            cats.setdefault(e["category"], []).append(e["id"])
        else:
            others.append(e["id"])

    sections = []
    for cat, ids in cats.items():
        cards = "".join(_card(by_id[i], GEAR[i]) for i in ids)
        sections.append(
            f'<div class="gr-cat-head"><h2 class="rd-h">{esc(cat)}</h2>'
            f'<span class="gr-cat-count">{len(ids)} item{"s" if len(ids) != 1 else ""}</span></div>'
            f'<div class="gr-grid">{cards}</div>'
        )

    others_html = ""
    if others:
        items = "".join(f'<li><strong>{esc(GEAR[i]["product"])}</strong> — {GEAR[i].get("note", "")}</li>' for i in others)
        others_html = (
            '<section class="rd-sec"><h2 class="rd-h">Also in the pipeline — not gear</h2>'
            '<p class="rd-prose">These feed the platform too, but there&rsquo;s nothing to buy: a free public API, '
            "a signal logged by hand, or a bridge that rides a device already listed above. Included so the list stays "
            "honest and complete.</p>"
            f'<ul class="gr-other rd-tierlist">{items}</ul></section>'
        )

    body = f"""<!DOCTYPE html>
<html lang="en" data-door="gear">
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
  <a class="skip" href="#gr">Skip to the content</a>
  {topbar()}
  <main id="gr">
    <div class="page-hero">
      <p class="ph-kicker label">the gear &middot; the devices behind the data</p>
      <h1 class="ph-title">The Gear</h1>
      <p class="ph-promise">Every device and app that actually feeds this platform — what it measures, how it&rsquo;s kept honest, and where to get it. Derived straight from the pipeline&rsquo;s source registry, not a curated wishlist.</p>
      {loop_ribbon("gear")}
    </div>
    <div class="gr-wrap">
      <div class="gr-disclosure" role="note" aria-label="Affiliate disclosure">
        <p class="gr-disc-h">Affiliate disclosure</p>
        <p>{DISCLOSURE}</p>
      </div>
      <section class="rd-sec">
        <h2 class="rd-h">How this list stays honest</h2>
        <p class="rd-prose">This isn&rsquo;t a recommendations page dressed up as data — it&rsquo;s the literal input list. Each card below is generated from <code>lambdas/source_registry.py</code>, the same registry that drives the <a href="/method/pipeline/">live pipeline board</a> and the <a href="/data/">data pillar</a>. Where two devices measure the same thing, they&rsquo;re cross-checked against each other on the <a href="/method/verify/">verify page</a> — that accountability stays separate from this page&rsquo;s affiliate links on purpose.</p>
      </section>
      {"".join(sections)}
      {others_html}
      <p class="correlative">This page is generated by <code>scripts/v4_build_gear.py</code> from <code>lambdas/source_registry.py</code>. Affiliate links are marked &ldquo;coming soon&rdquo; until the programs are live; the disclosure above applies whether or not any link is active.</p>
    </div>
  </main>
  {FOOTER}
  {THEME_SCRIPT}
  {TOC_SCRIPT}
  {MOTION_SCRIPT}
</body>
</html>
"""
    return body


def main() -> int:
    entries = catalog_entries()
    # Coverage gate: every registry source must have a decision here, so a newly-added
    # source can't silently vanish from (or misrepresent) this page.
    missing = [e["id"] for e in entries if e["id"] not in GEAR]
    if missing:
        print(f"error: source(s) missing a GEAR entry in v4_build_gear.py: {missing}", file=sys.stderr)
        return 2
    out_dir = ROOT / "site" / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render(entries), encoding="utf-8")
    n_gear = sum(1 for e in entries if GEAR[e["id"]]["kind"] == "gear")
    n_live = sum(1 for e in entries if GEAR[e["id"]]["kind"] == "gear" and (GEAR[e["id"]].get("affiliate_url") or "").strip())
    print(f"{CANONICAL}: {n_gear} gear cards ({n_live} with live affiliate links), {len(entries) - n_gear} non-gear listed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
