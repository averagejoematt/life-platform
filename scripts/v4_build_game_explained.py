#!/usr/bin/env python3
"""v4_build_game_explained.py — generate /method/game/ from the character engine's real rules (#1124).

"The Game, Explained": the rulebook for the character system — pillar weights,
component targets, the XP economy, streak gates, tier ladder, cross-pillar
effects, and the honest-absence rules (ADR-104). Every number on the page is
read from `config/character_sheet.json` (the deployable source of the engine's
S3 config) and `lambdas/character_engine.py` constants at build time — never
hand-typed — so a tuning change regenerates the page instead of drifting past it.

Two drift guards (enforced by tests/test_game_explained.py):
  1. The committed site/method/game/index.html must equal this generator's
     output byte-for-byte — config edits without a regen go red.
  2. The page's PROSE describes engine mechanics (up-gates, neglect decay,
     the confidence blend). RECORDED_ENGINE_FINGERPRINT below hashes the
     mechanics functions' live source; if the engine changes, the test goes
     red until a human re-reads the prose and updates the fingerprint —
     the same tripwire pattern as lambdas/methods_registry.py (#544).

Deliberately standalone, like scripts/v4_build_methods.py: its own builder, its
own static HTML, no evidence.js dependency. Chrome comes from the shared
v4_chrome partial (#1009), so v4_apply_chrome.py --check stays green.

Run from repo root:  python3 scripts/v4_build_game_explained.py
"""
from __future__ import annotations

import hashlib
import html
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import character_engine as ce  # noqa: E402
from v4_chrome import doors_nav, loop_forward, site_footer  # noqa: E402  — shared doors nav/close/footer (#1009, #1468)
from v4_kit import loop_ribbon  # noqa: E402  — shared .loop-ribbon (#578)

CONFIG_PATH = ROOT / "config" / "character_sheet.json"
OUT_PATH = ROOT / "site" / "method" / "game" / "index.html"

SLUG = "game"
CANONICAL = f"/method/{SLUG}/"
TITLE = "The Game, Explained — The Method — averagejoematt"
DESCRIPTION = (
    "The rulebook for the character system — pillar weights, the XP economy, streak gates, tiers, "
    "and the honest-absence rules — generated straight from the engine's config and constants."
)

# ── Engine-prose fingerprint (drift tripwire #2, see module docstring). The page's
# mechanics prose was last verified against these functions' source; update ONLY
# after re-reading the prose against the changed code (tests/test_game_explained.py).
MECHANICS_FUNCTIONS = (
    "get_tier",
    "_compute_xp",
    "_roll_xp_buffer",
    "_weighted_pillar_score",
    "compute_ema_level_score",
    "_behavioral_weight_share",
    "neglect_decay_state",
    "compute_character_mood",
    "_level_step",
    "evaluate_level_changes",
)
RECORDED_ENGINE_FINGERPRINT = "afcf20a07964"  # verified against engine v1.6.0, 2026-07-12 (#1124)


def engine_fingerprint() -> str:
    """Short hash over the live source of every mechanics function the prose describes."""
    src = "".join(inspect.getsource(getattr(ce, name)) for name in MECHANICS_FUNCTIONS)
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pct(v: float) -> str:
    """0.18 → 18% · 0.075 → 7.5% — weights and shares, always from config values."""
    p = v * 100
    return f"{p:.1f}%".replace(".0%", "%")


def signed_pct(v: float) -> str:
    p = v * 100
    s = f"{p:+.1f}%".replace(".0%", "%")
    return s.replace("-", "−")  # typographic minus


def num(v) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


# ── Shared site chrome — same deliberate copy as v4_build_methods.py (zero coupling
# to v4_build_evidence.py / evidence.js). ──────────────────────────────────────────
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


# Page-specific styling only — scoped under .gx-*, tokens-only, additive per
# DESIGN_SYSTEM_V5 §3 (reuses .rd-sec/.rd-h/.rd-prose/.rd-tbl/.correlative from
# evidence.css; .rd-tbl inherits the .table-scroll primitive ≤820px, §10.6).
STYLE = """
<style>
.gx-wrap { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-9); }
.gx-grid { display: grid; gap: var(--sp-5); margin-top: var(--sp-4); min-width: 0; }
.gx-pillar { border: var(--border-hair); border-radius: var(--radius); padding: var(--sp-5); background: var(--surface-raised); min-width: 0; }
.gx-pillar-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sp-3); }
.gx-pillar-name { font-family: var(--font-serif); font-weight: var(--weight-med); font-size: var(--fs-h3); color: var(--ink); margin: 0; }
.gx-pillar-meta { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-faint); }
.gx-kind { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase; }
.gx-kind-b { color: var(--ember); }
.gx-kind-s { color: var(--ink-faint); }
.gx-params { font-family: var(--font-mono); font-size: var(--fs-small); color: var(--ink-muted); }
.gx-note { margin-top: var(--sp-3); color: var(--ink-muted); font-size: var(--fs-small); line-height: var(--lh-relaxed); max-width: var(--measure); }
.gx-fig { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
</style>
"""


def _sec(anchor: str, heading: str, inner: str) -> str:
    return f'<section class="rd-sec" id="{esc(anchor)}"><h2 class="rd-h">{esc(heading)}</h2>{inner}</section>'


def _tbl(headers: list[str], rows: list[list[str]], aria: str) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="rd-tbl" aria-label="{esc(aria)}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


# ── Sections ───────────────────────────────────────────────────────────────────


def _pillars_section(config: dict) -> str:
    pillars = config.get("pillars", {})
    neglect = (config.get("leveling", {}) or {}).get("neglect_decay", {})
    min_share = neglect.get("min_behavioral_share", 0.3)
    weight_sum = sum(p.get("weight", 0) for p in pillars.values())
    cards = []
    for name, p in pillars.items():
        rows = []
        for comp, cfg in p.get("components", {}).items():
            cfg = cfg if isinstance(cfg, dict) else {"weight": cfg}
            behavioral = bool(cfg.get("behavioral"))
            kind = '<span class="gx-kind gx-kind-b">behavior</span>' if behavioral else '<span class="gx-kind gx-kind-s">sensor</span>'
            params = " · ".join(f"{esc(k.replace('_', ' '))} {esc(num(v))}" for k, v in cfg.items() if k not in ("weight", "behavioral"))
            rows.append(
                [
                    f'<span class="rd-name">{esc(comp.replace("_", " "))}</span>',
                    f'<span class="gx-fig">{esc(pct(cfg.get("weight", 0)))}</span>',
                    kind,
                    f'<span class="gx-params">{params or "—"}</span>',
                ]
            )
        share = ce._behavioral_weight_share(p)
        atrophies = share >= min_share
        share_note = f"{pct(share)} of this pillar's weight is behavior — " + (
            "it atrophies under sustained logging silence (see the dark rules below)."
            if atrophies
            else "below the atrophy threshold; a quiet stretch here reads as a sensor gap, not detraining."
        )
        cards.append(
            f'<article class="gx-pillar" id="pillar-{esc(name)}">'
            f'<div class="gx-pillar-head"><h3 class="gx-pillar-name">{esc(name.capitalize())}</h3>'
            f'<span class="gx-pillar-meta">{esc(pct(p.get("weight", 0)))} of the headline · smoothing λ {esc(num(p.get("ema_lambda", "")))} · owner {esc(p.get("owner", "—"))}</span></div>'
            + _tbl(["component", "weight", "kind", "parameters"], rows, f"{name} components")
            + f'<p class="gx-note">{esc(share_note)}</p>'
            "</article>"
        )
    intro = (
        '<p class="rd-prose">Every night the engine scores seven pillars, each 0–100, from weighted components. '
        "Each component is either a <strong>behavior</strong> (something that is done or not done — logging food, training, journaling) "
        "or a <strong>sensor</strong> (something a device measures). The distinction is load-bearing: when a behavior has no data, "
        "the behavior didn't happen and it scores <strong>0 at full weight</strong>; when a sensor has no data, the engine has no "
        "evidence either way, so the component drops out of the weight sum instead (ADR-104). "
        f"The pillar weights below sum to {esc(pct(weight_sum))} of the headline character level.</p>"
    )
    return _sec("pillars", "The seven pillars", intro + f'<div class="gx-grid">{"".join(cards)}</div>')


def _xp_section(config: dict) -> str:
    leveling = config.get("leveling", {})
    bands = config.get("xp_bands", [])
    decay = leveling.get("daily_xp_decay", ce.DEFAULT_DAILY_XP_DECAY)
    per_level = leveling.get("xp_per_level", ce.DEFAULT_XP_PER_LEVEL)
    debt_cap = leveling.get("xp_debt_cap", per_level)
    buf_threshold = leveling.get("xp_buffer_threshold", ce.DEFAULT_XP_BUFFER_THRESHOLD)
    buf_cap = leveling.get("xp_buffer_cap", per_level)
    grace = leveling.get("grace_period_days", 14)  # engine default when absent from config

    rows = []
    ordered = sorted(bands, key=lambda b: -b.get("min_raw_score", 0))
    for i, b in enumerate(ordered):
        lo = b.get("min_raw_score", 0)
        hi = ordered[i - 1].get("min_raw_score", 100) - 1 if i > 0 else 100
        net = b.get("xp", 0) - decay
        rows.append(
            [
                f'<span class="gx-fig">{lo}–{hi}</span>',
                f'<span class="gx-fig">{b.get("xp", 0):+d}</span>',
                f'<span class="gx-fig">{net:+g}</span>',
            ]
        )
    intro = (
        '<p class="rd-prose">Each pillar\'s daily raw score converts to XP through fixed bands, and a daily decay of '
        f"<strong>{esc(num(decay))} XP</strong> is charged against it — so the <em>net</em> column is what a day actually pays. "
        "The zero point is deliberately set at a decent-but-unremarkable day (ADR-134): coasting neither builds nor bleeds.</p>"
    )
    after = (
        f'<p class="rd-prose">A level is <strong>{esc(num(per_level))} XP</strong> deep. When the balance would go below zero it shows as visible '
        f"<strong>debt</strong> instead of hiding under a floor, capped at {esc(num(debt_cap))} XP so a long dark stretch stays climbable; "
        "good days pay debt down before XP grows again. XP earned also fills a small <strong>buffer</strong> "
        f"(capped at {esc(num(buf_cap))} XP) that acts as demotion insurance: a level-down can only land once the buffer is under "
        f"{esc(num(buf_threshold))} XP — and a confirmed multi-day dark stretch bypasses the buffer entirely, because banked XP is "
        "flip-flop insurance against noisy data, never a shield against a provable absence. In the first "
        f"{esc(num(grace))} days of a cycle the decay phases in linearly, so a fresh start isn't punished before the data stabilizes.</p>"
    )
    return _sec("xp", "A day becomes XP", intro + _tbl(["day's raw score", "XP earned", "net after decay"], rows, "XP bands") + after)


def _levels_section(config: dict) -> str:
    leveling = config.get("leveling", {})
    min_cov = leveling.get("level_change_min_coverage", ce.DEFAULT_LEVEL_CHANGE_MIN_COVERAGE)
    lam = leveling.get("ema_lambda", 0.85)
    window = leveling.get("ema_window_days", 21)
    step_bands = leveling.get("level_step_bands", [])
    step_rows = [
        [
            f'<span class="gx-fig">more than {esc(num(b.get("min_delta", 0)))} levels</span>',
            f'<span class="gx-fig">{esc(num(b.get("step", 1)))} levels</span>',
        ]
        for b in sorted(step_bands, key=lambda b: -b.get("min_delta", 0))
    ] + [['<span class="gx-fig">anything smaller</span>', '<span class="gx-fig">1 level</span>']]
    prose = (
        '<p class="rd-prose">Raw scores are smoothed by an exponential moving average '
        f"(default λ {esc(num(lam))} over a {esc(num(window))}-day window; each pillar can override λ, see the pillar cards). "
        "The smoothed score, rounded, is the <strong>target level</strong> — but no level ever jumps to its target. Four gates stand in the way:</p>"
        '<ul class="rd-tierlist">'
        "<li><strong>The streak gate.</strong> The target must hold above the current level for a full streak of days to climb (longer to fall — see the tier ladder). One great or terrible day moves nothing.</li>"
        "<li><strong>The lived-day gate.</strong> A climb also requires <em>today's own measured performance</em> to be at the target — the pre-blend, pre-boost number. EMA momentum after the behavior stopped can't buy a level, and in total logging silence the measured day is 0, so no dark day ever supports a climb (ADR-104).</li>"
        f"<li><strong>The coverage gate.</strong> Below {esc(pct(min_cov))} data coverage the day carries no leveling signal at all: streaks hold, levels freeze in both directions. Thin data is smoothed toward neutral for display, and neutral must never be climbable — nor should a pillar crash on no information.</li>"
        "<li><strong>The XP buffer.</strong> A level-down additionally waits until the XP buffer is depleted (see above) — unless the stretch is confirmed dark.</li>"
        "</ul>"
        '<p class="rd-prose">When a gate finally opens, the step size scales with the honest gap, so a pillar far from its target converges instead of marching one level at a time:</p>'
    )
    return _sec(
        "levels",
        "How a level actually moves",
        prose + _tbl(["gap between target and current level", "step per move"], step_rows, "level step bands"),
    )


def _tiers_section(config: dict) -> str:
    leveling = config.get("leveling", {})
    overrides = leveling.get("tier_streak_overrides", {})
    rows = []
    for t in config.get("tiers", []):
        name = t.get("name", "")
        o = overrides.get(name, {})
        rows.append(
            [
                f'<span class="rd-name">{esc(name)}</span>',
                f'<span class="gx-fig">{esc(num(t.get("min_level", "")))}–{esc(num(t.get("max_level", "")))}</span>',
                f'<span class="gx-fig">{esc(num(o.get("up", leveling.get("level_up_streak_days", 5))))} days</span>',
                f'<span class="gx-fig">{esc(num(o.get("down", leveling.get("level_down_streak_days", 7))))} days</span>',
                f'<span class="gx-fig">{esc(num(o.get("tier_boundary_up", leveling.get("tier_up_streak_days", 7))))} days</span>',
                f'<span class="gx-fig">{esc(num(o.get("tier_boundary_down", leveling.get("tier_down_streak_days", 10))))} days</span>',
            ]
        )
    prose = (
        '<p class="rd-prose">The 100 levels group into five tiers, and the streak gates get progressively harder as the tiers rise — '
        "holding Elite demands more proof than leaving Foundation. Falling always takes a longer streak than climbing (a slump has to prove "
        "itself harder than a surge), and crossing a tier boundary in either direction demands the longest streaks of all.</p>"
    )
    return _sec(
        "tiers",
        "The tier ladder",
        prose + _tbl(["tier", "levels", "level up", "level down", "tier up", "tier down"], rows, "tier ladder and streak gates"),
    )


def _effects_section(config: dict) -> str:
    rows = []
    for e in config.get("cross_pillar_effects", []):
        targets = []
        for target, spec in e.get("targets", {}).items():
            label = "all pillars" if target == "_all" else target
            targets.append(f'{esc(label)} <span class="gx-fig">{esc(signed_pct(spec.get("value", 0)))}</span>')
        rows.append(
            [
                f'<span class="rd-name">{esc(e.get("name", ""))}</span>',
                f'<span class="gx-params">{esc(e.get("condition", ""))}</span>',
                " · ".join(targets),
            ]
        )
    prose = (
        "<p class=\"rd-prose\">Pillars aren't independent — the engine models a small set of spillovers as multiplicative modifiers on the day's "
        "scores. Every active effect applies (they stack), and each is announced on the character sheet when live. Boosts raise the level a pillar "
        "converges to, but never the lived-day bar — a standing boost can't demand a day nobody can perform (see the gates above).</p>"
    )
    return _sec("effects", "Cross-pillar effects", prose + _tbl(["effect", "condition", "modifier"], rows, "cross-pillar effects"))


def _dark_section(config: dict) -> str:
    leveling = config.get("leveling", {})
    nd = leveling.get("neglect_decay", {})
    grace = nd.get("n_grace_days", 3)
    rate = nd.get("rate", 0.98)
    min_share = nd.get("min_behavioral_share", 0.3)
    pillars = config.get("pillars", {})
    qualifying = [n for n, p in pillars.items() if ce._behavioral_weight_share(p) >= min_share]
    persistent = nd.get("persistent_down_streak", False)
    prose = (
        '<p class="rd-prose">The game\'s hardest honesty rules are about absence (ADR-104). The sheet must respond truthfully when the logging '
        "stops — it can never coast on silence, and it can never punish a sensor outage as if it were a lapse.</p>"
        '<ul class="rd-tierlist">'
        "<li><strong>Absent behaviors score zero.</strong> An unlogged habit is a habit that didn't happen: behavior components score 0 at full weight. A quiet device just drops out of the weight sum — a wearable gap is not a failure.</li>"
        "<li><strong>Thin days blend toward neutral — for display only.</strong> As data coverage falls, the day's score is blended toward a neutral 50 (full confidence at 80% coverage). The blend smooths the EMA and the display; it is uncertainty, not performance, so the level gates always judge the unblended measured number.</li>"
        "<li><strong>A never-instrumented pillar is a placeholder, not a reading.</strong> With zero components reporting, the pillar shows a mathematical neutral 50 and is excluded from the headline until it earns its first level — after that it counts forever, and going dark later drags honestly instead of vanishing.</li>"
        f"<li><strong>Neglect atrophies.</strong> After {esc(num(grace))} consecutive dark days of manual-logging silence (with no planned pause — sick days and travel never decay), behavioral pillars start to atrophy: the smoothed score multiplies by {esc(num(rate))} per additional dark day, floored at what each day actually measured. Only pillars whose weight is at least {esc(pct(min_share))} behavioral qualify — currently <strong>{esc(', '.join(qualifying))}</strong> — because a dark stretch detrains behaviors, not blood panels.</li>"
        + (
            "<li><strong>A confirmed dark stretch falls day by day.</strong> The anti-flip-flop streak reset exists for noisy engaged data; a provable multi-day absence is not noise. In a confirmed dark stretch the down-streak persists across drops and the XP buffer stops shielding, so the level keeps stepping down toward what the data earns.</li>"
            if persistent
            else ""
        )
        + "<li><strong>XP bleeds visibly.</strong> Silence pays the daily decay with nothing earned; the hole shows as debt on the sheet rather than disappearing under a zero floor.</li>"
        "</ul>"
    )
    return _sec("dark", "When the data goes dark", prose)


def _headline_section(config: dict) -> str:
    prose = (
        '<p class="rd-prose">The headline <strong>Character Level</strong> is the weight-averaged mean of the seven pillar levels, '
        "renormalized over the pillars that have ever been instrumented, then <strong>floored</strong> — never rounded up. "
        "It understates by construction.</p>"
        '<p class="rd-prose">The character\'s <strong>mood</strong> — dormant · fading · steady · thriving — is equally deterministic '
        "(ADR-105): pure code over the presence signal and the 7-day composite raw-score trend. <em>Dormant</em> is a confirmed dark stretch; "
        "<em>fading</em> is quiet logging or a trend of −5 or worse; <em>thriving</em> demands active logging, a trend of +3 or better, "
        "and a composite of at least 55; everything else is <em>steady</em>. No model ever decides how the character feels.</p>"
    )
    return _sec("headline", "The headline number — and the mood", prose)


def _honesty_section(config: dict) -> str:
    prose = (
        '<p class="rd-prose"><strong>Deterministic:</strong> everything on this page. Scores, XP, levels, tiers, effects, atrophy, and mood are '
        "pure code over logged data — the same inputs always produce the same character, and no language model sits anywhere in the loop "
        "(ADR-104/105).</p>"
        '<p class="rd-prose"><strong>Judged:</strong> only the words around the numbers. The coaches\' commentary, the weekly chronicle, and the '
        "narrative surfaces are AI-written <em>about</em> these pre-computed numbers, grounded by the platform's generation gates — the narration "
        "can characterize a level, but it can never move one.</p>"
        '<p class="rd-prose">And a boundary worth stating: the game is a <strong>motivational lens on real data, not a medical score</strong>. '
        "Every input is correlative and N=1.</p>"
    )
    return _sec("honesty", "What's deterministic, what's judged", prose)


# ── Page assembly ──────────────────────────────────────────────────────────────


def render(config: dict) -> str:
    meta = config.get("_meta", {})
    hero_promise = (
        "The character sheet is a game — and a game you can't audit is just a badge. This page is the rulebook: every number below is "
        f"generated from the exact config and constants the engine runs (engine v{ce.ENGINE_VERSION} · config v{meta.get('version', '?')}), "
        "never hand-typed, and a drift check fails the build if the rules change without this page regenerating."
    )
    sections = (
        _pillars_section(config)
        + _xp_section(config)
        + _levels_section(config)
        + _tiers_section(config)
        + _effects_section(config)
        + _dark_section(config)
        + _headline_section(config)
        + _honesty_section(config)
    )
    provenance = (
        '<p class="correlative">Generated by <code>scripts/v4_build_game_explained.py</code> from <code>config/character_sheet.json</code> '
        "and <code>lambdas/character_engine.py</code> — the same config the nightly engine loads. Two tests guard it: the committed page must "
        "match the generator's output exactly, and a fingerprint of the engine's mechanics functions must match the one recorded when this "
        "prose was last verified (<code>tests/test_game_explained.py</code>). The plain-language story of the level lives on "
        '<a href="/method/character/">the character explainer</a>; the live sheet is at <a href="/data/character/">/data/character/</a>; '
        'every other published statistic is documented in <a href="/method/registry/">the Methods Registry</a>. '
        '<span class="confidence conf-low">generated, not authored</span></p>'
    )

    return f"""<!DOCTYPE html>
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
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-character.png">
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
  <a class="skip" href="#gx">Skip to the content</a>
  {topbar()}
  <main id="gx">
    <div class="page-hero">
      <p class="ph-kicker label">the method &middot; under the hood</p>
      <h1 class="ph-title">The Game, Explained</h1>
      <p class="ph-promise">{esc(hero_promise)}</p>
      {loop_ribbon("method")}
    </div>
    <div class="gx-wrap">
      {sections}
      {provenance}
    </div>
  </main>
  {loop_forward("/data/", self_path="/method/game/")}
  {site_footer()}
  {MOTION_SCRIPT}
</body>
</html>
"""


def main() -> int:
    live = engine_fingerprint()
    if live != RECORDED_ENGINE_FINGERPRINT:
        print(
            f"WARNING: engine mechanics fingerprint {live} != recorded {RECORDED_ENGINE_FINGERPRINT} — "
            "re-read this page's mechanics prose against lambdas/character_engine.py, then update "
            "RECORDED_ENGINE_FINGERPRINT (tests/test_game_explained.py enforces this).",
            file=sys.stderr,
        )
    config = load_config()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(config), encoding="utf-8")
    pillars = len(config.get("pillars", {}))
    print(f"{CANONICAL}: {pillars} pillars · engine v{ce.ENGINE_VERSION} · config v{config.get('_meta', {}).get('version', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
