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
  2. The page's PROSE describes engine mechanics (up-gates, the held-day rule,
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v4_apply_chrome as _apply_chrome  # noqa: E402 — the post-build chrome normalizer (#3721)

sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach import persona_registry  # noqa: E402  — canonical public roster (#1891)
from health import (
    character_engine as ce,  # noqa: E402
    personal_baselines as pb,  # noqa: E402  — the #5056 charter steps overlay
)
from privacy import privacy_guard  # noqa: E402  — real-public-figure gate (#1891)
from privacy.content_filter_channel import ContentFilterUnavailable  # noqa: E402  — #2370 hold-not-crash
from v4_chrome import (
    doors_nav,
    head_chrome,
    loop_forward,
    site_footer,
)  # noqa: E402  — shared doors nav/close/footer/head (#1009, #1468, #1639)
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
    "xp_day_verdict",
    "xp_shield_delta",
    "_weighted_pillar_score",
    "day_is_held",
    "compute_ema_level_score",
    "compute_character_mood",
    "planned_rest_in_window",
    "lab_evidence_factor",
    "data_completeness_pct",
    "_level_step",
    "evaluate_level_changes",
)
RECORDED_ENGINE_FINGERPRINT = "9520396c988f"  # re-read 2026-11-26 (#6293 final amendments: planned rest, lab ageing as weight, rest-day completeness, mood 'unavailable'); prior b75287942475 (#6293 amendment: no XP decay/debt, shield on measured verdicts, held days, no neglect atrophy, only habits two-state); prior f1d96247c11a, re-read 2026-10-23 (#5129: owner-only components held out of _weighted_pillar_score — the table labels them); prior e56973e1c2ee, engine v1.7.0 + #1412, 2026-07-19


def engine_fingerprint() -> str:
    """Short hash over the live source of every mechanics function the prose describes."""
    src = "".join(inspect.getsource(getattr(ce, name)) for name in MECHANICS_FUNCTIONS)
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def load_config() -> dict:
    """The authored config with the charter-owned targets the engine actually runs under (#5056).

    `daily_steps` is a protocol commitment: `personal_baselines.protocol_targets` sets its target
    to the training charter's floor and its perfect point to the charter's target, so the page
    states those, never the authored prior the engine no longer scores against. Only the two
    numbers are copied (the provenance dict is not a page parameter)."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for metric, overlay in pb.protocol_targets().items():
        spec = pb.CHARACTER_TARGET_SPECS.get(metric) or {}
        comp = ((config.get("pillars") or {}).get(spec.get("pillar"), {}).get("components") or {}).get(spec.get("component"))
        if isinstance(comp, dict):
            comp.update({k: v for k, v in overlay.items() if k != "target_provenance"})
    return config


# ── Cast guard (drift tripwire #3 — #1891) ──────────────────────────────────
# The pillar `owner` fields are the only place this page names coaching staff.
# They were authored in the pilot era and never got the cast rename that mapped
# peter_attia → Victor Reyes in config/personas.json, so /method/game/
# published "owner Dr. Peter Attia" — a real, non-consenting clinician presented
# as platform staff — while /api/coaches one door away named Amara Patel.
# Two fail-closed checks now run at render time, so a stale owner cannot ship:
#
#   1. Every owner resolves to the LIVE PUBLIC ROSTER (persona_registry's
#      operational personas + the lead) or is an explicit role label. The
#      registry as a whole is deliberately NOT the allowed set — it still
#      carries retired pilot personas like maya_rodriguez, which is precisely
#      the dead cast this guards against.
#   2. The rendered page passes privacy_guard — the same deterministic gate the
#      AI publish/serve chokepoints use, which already bans "peter attia" et al.
#      This page is generated rather than AI-written, so it never passed that
#      gate before; wiring it here closes the class, not just the instance.

# Owners naming a role or concept rather than a member of the public roster.
OWNER_ROLE_LABELS = frozenset(
    {
        "Social Connection",  # relationships — the domain owns it; no staff coach
        "The Chair",  # consistency — the governance role, not a named coach
    }
)


def public_roster() -> set[str]:
    """Display names the public sees on /api/coaches: the 8 operational coaches + the lead."""
    names = {p.get("name") for p in persona_registry.operational_personas().values()}
    lead = persona_registry.resolve(persona_registry.LEAD_PERSONA_ID)
    if lead:
        names.add(lead.get("name"))
    return {n for n in names if n}


def assert_cast_current(config: dict) -> None:
    """Fail-closed: no pillar owner may name anyone off the live public roster."""
    roster = public_roster()
    if not roster:  # registry unreadable — refuse rather than validate against nothing
        raise SystemExit("cast guard: persona registry resolved to an empty roster; refusing to build")
    stale = {
        name: p["owner"]
        for name, p in config.get("pillars", {}).items()
        if (owner := p.get("owner")) and owner not in roster and owner not in OWNER_ROLE_LABELS
    }
    if stale:
        raise SystemExit(
            "cast guard (#1891): pillar owner(s) name someone off the live roster — "
            + "; ".join(f"{k} → {v!r}" for k, v in sorted(stale.items()))
            + f". Allowed: {sorted(roster | OWNER_ROLE_LABELS)}. "
            "Update config/character_sheet.json to the current cast (config/personas.json holds the rename map)."
        )


def assert_no_real_figures(page: str) -> None:
    """Fail-closed: the rendered page passes the same privacy gate as AI-published content."""
    privacy_guard.assert_clean(page, context="/method/game/")


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
# #3048: extracted to a real asset so the site CSP can drop 'unsafe-inline' for
# scripts — synchronous head script, so theme still applies before first paint.
THEME = '<script src="/assets/js/boot_theme.js"></script>'
MOTION_HEAD = '<script src="/assets/js/boot_motion.js"></script>'
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


_UNRENDERED_KEYS = ("weight", "behavioral", "owner_only_input", "in_pillar_score")


def _weight_label(name: str, p: dict) -> str:
    """#6293: an uninstrumented pillar's configured weight is not part of the headline — never print it as if it were."""
    if name in ce.UNINSTRUMENTED_PILLARS:
        return "not instrumented — out of the headline"
    return f"{pct(p.get('weight', 0))} of the headline"


def _pillars_section(config: dict) -> str:
    pillars = config.get("pillars", {})
    weight_sum = sum(p.get("weight", 0) for n, p in pillars.items() if n not in ce.UNINSTRUMENTED_PILLARS)
    cards = []
    for name, p in pillars.items():
        rows = []
        for comp, cfg in p.get("components", {}).items():
            cfg = cfg if isinstance(cfg, dict) else {"weight": cfg}
            behavioral = bool(cfg.get("behavioral"))
            # #6293: only the T0/T1 habits are two-state (absent = 0); any other logged behavior with no input is unknown
            if behavioral and comp in ce.HABIT_TWO_STATE_COMPONENTS:
                kind = '<span class="gx-kind gx-kind-b">habit — unlogged scores 0</span>'
            elif behavioral:
                kind = '<span class="gx-kind gx-kind-b">behavior</span>'
            else:
                kind = '<span class="gx-kind gx-kind-s">sensor</span>'
            # #5129: an owner-only input is held out of the published score — say so, never as a parameter dump
            if ce.character_privacy.component_visibility(comp, cfg)[1]:
                kind = '<span class="gx-kind gx-kind-s">held out — owner-only input</span>'
            params = " · ".join(f"{esc(k.replace('_', ' '))} {esc(num(v))}" for k, v in cfg.items() if k not in _UNRENDERED_KEYS)
            rows.append(
                [
                    f'<span class="rd-name">{esc(comp.replace("_", " "))}</span>',
                    f'<span class="gx-fig">{esc(pct(cfg.get("weight", 0)))}</span>',
                    kind,
                    f'<span class="gx-params">{params or "—"}</span>',
                ]
            )
        # #6293: a pillar with no components (Relationships) is not instrumented — its note, never an empty table
        body = (
            _tbl(["component", "weight", "kind", "parameters"], rows, f"{name} components")
            if rows
            else f'<p class="gx-note">{esc(p.get("not_instrumented_note") or "Not instrumented: no component is scored.")}</p>'
        )
        cards.append(
            f'<article class="gx-pillar" id="pillar-{esc(name)}">'
            f'<div class="gx-pillar-head"><h3 class="gx-pillar-name">{esc(name.capitalize())}</h3>'
            f'<span class="gx-pillar-meta">{esc(_weight_label(name, p))} · smoothing λ {esc(num(p.get("ema_lambda", "")))} · owner {esc(p.get("owner", "—"))}</span></div>'
            + body
            + "</article>"
        )
    intro = (
        '<p class="rd-prose">Every night the engine scores the instrumented pillars, each 0–100, from weighted components. '
        "Each component is a <strong>habit</strong>, another <strong>behavior</strong> (training, logging food, reading) or a "
        "<strong>sensor</strong> (something a device measures). Only the daily habits are two-state: an unlogged habit is a habit that "
        "didn't happen, so it scores <strong>0 at full weight</strong>. Any other component with no data is <strong>unknown</strong> — "
        "the engine has no evidence either way, so it drops out of the weight sum and lowers the day's coverage instead (ADR-104, "
        "narrowed in 2026-11). Missing information is never read as decline. "
        f"The instrumented pillars' weights below sum to {esc(pct(weight_sum))}; the headline renormalizes over them.</p>"
        '<p class="rd-prose">A handful of component targets — sleep duration, deep and REM share — are not fixed '
        "opinions: once at least 30 observations of Matthew's own history exist, the target is re-derived monthly as the 75th "
        "percentile of his own distribution, clamped inside documented safety bounds (ADR-105 rule 4: thresholds come from "
        "personal variance, not authored taste). Until a metric clears that floor, the numbers below stand — explicitly labeled "
        "a population prior. Every derived target carries its provenance: method, window, and sample size.</p>"
        '<p class="rd-prose">Daily steps is the exception, because it is a commitment rather than a habit to measure: its target '
        "is the training plan's every-day floor and it scores full marks at the plan's step target, the same two numbers the "
        "morning coaching line states. Deriving it from his own history would let a run of low days lower the bar.</p>"
    )
    return _sec("pillars", "The seven pillars", intro + f'<div class="gx-grid">{"".join(cards)}</div>')


def _xp_section(config: dict) -> str:
    leveling = config.get("leveling", {})
    bands = config.get("xp_bands", ce.DEFAULT_XP_BANDS)
    per_level = leveling.get("xp_per_level", ce.DEFAULT_XP_PER_LEVEL)
    buf_threshold = leveling.get("xp_buffer_threshold", ce.DEFAULT_XP_BUFFER_THRESHOLD)
    buf_cap = leveling.get("xp_buffer_cap", per_level)

    rows = []
    ordered = sorted(bands, key=lambda b: -b.get("min_raw_score", 0))
    for i, b in enumerate(ordered):
        lo = b.get("min_raw_score", 0)
        hi = ordered[i - 1].get("min_raw_score", 100) - 1 if i > 0 else 100
        verdict = ce.xp_day_verdict(lo, config)
        rows.append(
            [
                f'<span class="gx-fig">{lo}–{hi}</span>',
                f'<span class="gx-fig">{max(0, verdict):+d}</span>',
                f'<span class="gx-fig">{verdict:+g}</span>',
            ]
        )
    intro = (
        '<p class="rd-prose">On a day the engine could actually judge, each pillar\'s raw score lands in a fixed band. A good day '
        "<strong>earns</strong> XP; a decent-but-unremarkable day earns nothing (ADR-134's zero point); a low day also earns nothing. "
        "<strong>XP never goes down</strong>: there is no daily decay, no negative balance and no debt — missing data, inactivity and rest "
        "cost no XP at all, and a day with too little evidence carries no XP judgment in either direction.</p>"
    )
    after = (
        f'<p class="rd-prose">A level is <strong>{esc(num(per_level))} XP</strong> deep. The band\'s signed value — the '
        "<em>shield</em> column — moves a small <strong>shield</strong> (capped at "
        f"{esc(num(buf_cap))}) that acts as demotion insurance: good days fill it, measured low days drain it, and a day without "
        f"evidence leaves it alone. A level-down can only land once the shield is under {esc(num(buf_threshold))}. It is "
        "flip-flop insurance against noisy data; silence never drains it.</p>"
    )
    return _sec("xp", "A day becomes XP", intro + _tbl(["day's raw score", "XP earned", "shield"], rows, "XP bands") + after)


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
        "<li><strong>The shield.</strong> A level-down additionally waits until the shield is depleted (see above) — which only measured low days can do.</li>"
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
        # #1411 (ADR-105): the declared evidence status. The config can only ever
        # declare the authored prior — "fitted" is earned from data by the
        # quarterly re-fit and served LIVE (with n_eff + CI) on the character
        # sheet and /api/character_config; this static rulebook shows the
        # declaration, never a hand-written promotion.
        status = e.get("fit_status", "authored-prior")
        status_txt = "fitted from the data" if status == "fitted" else "authored prior"
        rows.append(
            [
                f'<span class="rd-name">{esc(e.get("name", ""))}</span>',
                f'<span class="gx-params">{esc(e.get("condition", ""))}</span>',
                " · ".join(targets),
                f'<span class="gx-params">{esc(status_txt)}</span>',
            ]
        )
    prose = (
        "<p class=\"rd-prose\">Pillars aren't independent — the engine models a small set of spillovers as multiplicative modifiers on the day's "
        "scores. Every active effect applies (they stack), and each is announced on the character sheet when live. Boosts raise the level a pillar "
        "converges to, but never the lived-day bar — a standing boost can't demand a day nobody can perform (see the gates above).</p>"
        '<p class="rd-prose">These effects started life as <strong>authored priors</strong> — plausible physiology, written by hand, not measured. '
        "Every quarter the engine re-fits each one against the lived data as a lagged driver&rarr;next-day-target relationship (moving-block "
        "bootstrap 95% CI, false-discovery-rate corrected, autocorrelation-honest n). An effect earns the badge <em>fitted</em> only when its "
        "interval excludes no-effect in the claimed direction — and can lose it again at the next fit. The live badge (with its n and interval) is "
        'on <a href="/data/character/">the character sheet</a>; a prior that fails to confirm is published on <a href="/method/wrong/">the wrong '
        "page</a> as a finding (#1411, ADR-105).</p>"
    )
    return _sec(
        "effects",
        "Cross-pillar effects",
        prose + _tbl(["effect", "condition", "modifier", "evidence status"], rows, "cross-pillar effects"),
    )


def _dark_section(config: dict) -> str:
    uninstrumented = ", ".join(n.capitalize() for n in ce.UNINSTRUMENTED_PILLARS)
    prose = (
        '<p class="rd-prose">The game\'s hardest honesty rules are about absence (ADR-104, amended 2026-11). The sheet can never coast on '
        "silence — and it can never read silence, inactivity or rest as decline.</p>"
        '<ul class="rd-tierlist">'
        "<li><strong>Unlogged habits score zero; everything else missing is unknown.</strong> A daily habit not logged is a habit that "
        "didn't happen. Any other missing input — a quiet wearable, an unlogged meal, no reading session, no workout log — drops out of the "
        "weight sum instead of scoring zero.</li>"
        "<li><strong>Missing qualitative information is unknown, not decline.</strong> How often the journal is written is not scored, and "
        "nothing a language model reads into the journal is scored: a day without an entry moves no score.</li>"
        "<li><strong>A day with no evidence moves nothing.</strong> When a pillar has no data, or too little to judge, that day is "
        "<em>held</em>: it is left out of the smoothed score, the cross-pillar variance, the all-pillars streak and the mood, and it earns "
        "or costs no XP. Thin days still show a value blended toward neutral, for display only.</li>"
        "<li><strong>No neglect decay.</strong> A quiet stretch — a planned rest, a trip, a week off logging — does not shrink any score "
        "and does not push a level down. A level falls only when measured days, sustained over the streak gate, say it should.</li>"
        "<li><strong>Planned rest is not inactivity.</strong> A day recorded as a sick day or a travel day leaves Movement's weekly "
        "windows: the week's session, strength, Zone 2 and variety targets shrink to the days that were not planned rest, and a week of "
        "nothing but planned rest is unknown, not zero. An unplanned week off still counts as a week without training.</li>"
        "<li><strong>A rest day is not missing data.</strong> The day's data completeness expects a Strava row only when another source "
        "(Hevy, Whoop, the watch) shows a session that day.</li>"
        "<li><strong>Old lab results fade as evidence, not as health.</strong> As a blood panel ages its weight in Metabolic tapers — "
        "full for 30 days, half at 90, none at 180 — and the aged share is unknown; the markers' score itself never drops with age.</li>"
        f"<li><strong>An uninstrumented pillar is out, not a placeholder.</strong> {esc(uninstrumented)} has no defensible, approved "
        "assessment yet, so it is not scored: no number stands in for it anywhere — not in the headline, the consistency variance, the "
        "effects or the mood.</li>"
        "</ul>"
    )
    return _sec("dark", "When the data goes dark", prose)


def _headline_section(config: dict) -> str:
    prose = (
        '<p class="rd-prose">The headline <strong>Character Level</strong> is the weight-averaged mean of the pillar levels, '
        "renormalized over the pillars that are instrumented and have earned a level, then <strong>floored</strong> — never rounded up. "
        "It understates by construction.</p>"
        '<p class="rd-prose">The character\'s <strong>mood</strong> — unavailable · fading · steady · thriving — is equally deterministic '
        "(ADR-105): pure code over the presence signal and the 7-day composite raw-score trend of the measured days. <em>Fading</em> "
        "needs the measured days themselves to fall (a trend of −5 or worse); when logging has simply gone quiet the mood is "
        "<em>unavailable</em> — not observed, never read as decline; <em>thriving</em> demands active logging, a trend of +3 or better, "
        "and a composite of at least 55; everything else is <em>steady</em>. No model ever decides how the character feels.</p>"
    )
    return _sec("headline", "The headline number — and the mood", prose)


def _honesty_section(config: dict) -> str:
    prose = (
        '<p class="rd-prose"><strong>Deterministic:</strong> everything on this page. Scores, XP, levels, tiers, effects and mood are '
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
    """Render the page, fail-closed on a stale cast or any real public figure (#1891)."""
    assert_cast_current(config)
    page = _render_page(config)
    assert_no_real_figures(page)
    return page


def _render_page(config: dict) -> str:
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
{head_chrome()}
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
  {site_footer(current_door="/data/")}
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
    try:
        page = render(config)
    except ContentFilterUnavailable as e:
        # #2370 fail-closed, correctly scoped: no vocabulary means this PUBLIC page
        # cannot be screened, so it must not REGENERATE — but the committed artifact
        # was screened when it was written, so keeping it is safe. Crashing here took
        # down the whole reconcile lane (2026-08-10, three red main runs) over a
        # missing CI secret; holding the regen is the fail-closed posture without the
        # collateral.
        print(f"HOLD: {CANONICAL} not regenerated — {e}", file=sys.stderr)
        return 0
    _apply_chrome.write_page(OUT_PATH, page)  # #3721
    pillars = len(config.get("pillars", {}))
    print(f"{CANONICAL}: {pillars} pillars · engine v{ce.ENGINE_VERSION} · config v{config.get('_meta', {}).get('version', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
