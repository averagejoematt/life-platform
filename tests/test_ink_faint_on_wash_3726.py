#!/usr/bin/env python3
"""tests/test_ink_faint_on_wash_3726.py — the ground under the ground (#3726).

`--ink-faint` has been bumped twice for contrast (#579, #1470) and both times it was
tuned against the BARE paper ramp: `--page`, `--surface`, `--surface-2`,
`--surface-raised`. `tests/test_paper_ramp_contrast.py` pins exactly that, and it
passes — at 4.53:1 (dark, `--surface-raised`) and 4.61:1 (light, `--surface-2`).
Those are hairline passes, and they were spent.

`--ember-wash` is `color-mix(in oklch, var(--ember) 9%, transparent)` — a TRANSPARENT
tint. It does not replace a ramp step, it composites OVER it, and it takes that
remaining margin away. Measured through this file's own engine, pre-fix:

    dark   --ink-faint on wash over --surface-raised   4.01:1   FAIL
    light  --ink-faint on wash over --surface-2        4.11:1   FAIL
    light  --ink-muted on wash over --surface-2        4.16:1   FAIL

The light half is what the nightly Visual QA had been reporting for NINE consecutive
nights (2026-09-04 → 09-12) as three axe `color-contrast` findings, on three pages,
under three different selectors:

    /coaching/lab-notes/  @390px   .human > .who                          3 nodes
    /data/habits/         @390px   .st-hold.st-chip:nth-child(1) > .st-pct 21 nodes
    /data/badges/         both     .is-earned > .ch-badge-h.label          1 node

One cause. And a DATA-DEPENDENT one: an earned badge, a held habit chip and a quoted
human line are all `--ember-wash` containers, and cycle 17's 2026-09-06 reset is what
put all three back on the page. That is why #3650's class appeared to "come back"
five days after it was closed — it never left, the elements simply were not
rendering when it was verified. A contrast defect visible only when the data
cooperates needs a computed pin, not a screenshot.

WHY THE FIX IS SCOPED AND NOT A PALETTE BUMP. Two cheaper levers were measured and
rejected rather than assumed:

  * lowering the wash weight — at 0% ember the worst pair is still ~4.5:1, so there
    is no weight at which the base token survives a tint;
  * bumping `--ink-faint` globally — in light theme the compliant value is darker
    than `--ink-muted` already is, which INVERTS the muted/faint hierarchy across
    every page to fix a defect that only exists inside the tint.

So a wash-backed container re-states the two inks that sit on it, one step further
from its own tinted ground. The global ramp and the hierarchy are untouched, and the
shift is only visible inside the tint that caused it — where the tint hides it.

THE SELECTOR LIST IS DERIVED, NOT CURATED. `test_every_wash_ground_compensates`
re-reads every `background: var(--ember-wash)` rule out of `site/assets/css/*.css`
and fails if one is missing from the compensation block, so the 34th wash container
cannot land uncompensated the way the first 33 did.

MUTATION PROOF: delete the compensation block from tokens.css, or drop one selector
from it, and this module reds while `test_paper_ramp_contrast.py` stays green — which
is the point. It is the dimension that was missing, not a duplicate of one.

Offline, stdlib-only, repo-only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# The resolver, the oklch mixer and the ramp definition are the ramp test's. Importing
# them rather than re-deriving them is deliberate: two copies of a contrast engine is
# how the two dimensions drift apart again.
from test_paper_ramp_contrast import (  # noqa: E402
    AA,
    RAMP_STEPS,
    TOKENS,
    _hex_to_rgb,
    _mix_oklch,
    _palettes,
    _resolve,
    _strip_comments,
    contrast,
)

CSS_DIR = TOKENS.parent

# The inks a wash-backed container re-states, and the base token each one covers.
ON_WASH = {"--ink-faint": "--ink-faint-on-wash", "--ink-muted": "--ink-muted-on-wash"}

# A working floor above the 4.5 AA line. 4.51:1 is a pass the next unrelated nudge
# silently removes — the #1470 bump left exactly that margin, which is why this
# defect existed at all.
MARGIN = 4.7


def _blocks(text):
    text = _strip_comments(text)
    return [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", text)]


def _norm(sel):
    return " ".join(sel.split())


def _wash_grounds():
    """Every selector in the shipped CSS that paints an --ember-wash background."""
    out = []
    for path in sorted(CSS_DIR.glob("*.css")):
        for sel_group, body in _blocks(path.read_text()):
            if re.search(r"background(-color)?:\s*var\(--ember-wash", body):
                for sel in sel_group.split(","):
                    sel = _norm(sel)
                    if sel and sel not in out:
                        out.append(sel)
    assert out, "no --ember-wash grounds found at all — the extractor has gone blind"
    return out


def _compensating_selectors():
    """Every selector whose block re-states BOTH on-wash inks."""
    out = []
    for sel_group, body in _blocks(TOKENS.read_text()):
        decls = {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}
        if all(decls.get(base) == f"var({alias})" for base, alias in ON_WASH.items()):
            out.extend(_norm(s) for s in sel_group.split(",") if _norm(s))
    return set(out)


def _wash_recipe():
    """(accent_token, accent_pct) read from the CSS, so a re-weighted wash is
    measured at its NEW weight rather than the one this test was written against."""
    css = _strip_comments(TOKENS.read_text())
    m = re.search(r"--ember-wash\s*:\s*color-mix\(in oklch,\s*var\(\s*(--[\w-]+)\s*\)\s+([\d.]+)%,\s*transparent\s*\)", css)
    assert m, "tokens.css: --ember-wash is no longer a `<accent> N%, transparent` wash — re-read this test's premise"
    return m.group(1), float(m.group(2))


def _themes():
    dark, light_media, light_explicit = _palettes()
    assert light_media == light_explicit, "the two light blocks drifted — test_paper_ramp_contrast owns that contract"
    return {"dark": ({}, dark), "light": (light_media, dark)}


def _wash_over(step, theme, dark):
    accent_token, pct = _wash_recipe()
    accent = _resolve(accent_token, theme, dark)
    return _mix_oklch(accent, pct, _resolve(step, theme, dark), 100.0 - pct)


# ── the contract ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("theme_name", ["dark", "light"])
@pytest.mark.parametrize("alias", sorted(ON_WASH.values()))
def test_each_on_wash_ink_holds_aa_on_every_ramp_step(theme_name, alias):
    """The whole point: the re-stated ink clears AA on the tint over EVERY step of the
    ramp, because a wash container can land on any of them."""
    theme, dark = _themes()[theme_name]
    ink = _resolve(alias, theme, dark)
    worst = min((contrast(ink, _wash_over(step, theme, dark)), step) for step in RAMP_STEPS)
    assert (
        worst[0] >= MARGIN
    ), f"{theme_name}: {alias} measures {worst[0]:.2f}:1 on wash over {worst[1]} — under the {MARGIN}:1 working floor"


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_the_on_wash_inks_keep_the_muted_over_faint_hierarchy(theme_name):
    """Compensating must not flatten the two inks into each other. Muted is the
    CLEARER of the pair on bare paper; it stays the clearer one on a wash."""
    theme, dark = _themes()[theme_name]
    step = "--surface"
    ground = _wash_over(step, theme, dark)
    faint = contrast(_resolve("--ink-faint-on-wash", theme, dark), ground)
    muted = contrast(_resolve("--ink-muted-on-wash", theme, dark), ground)
    assert muted > faint, f"{theme_name}: on-wash muted {muted:.2f}:1 is not clearer than faint {faint:.2f}:1 — the hierarchy inverted"


def test_every_wash_ground_compensates():
    """THE DERIVATION GUARD. The compensation block's selector list is re-derived from
    the shipped CSS on every run, so the next `background: var(--ember-wash)` rule
    cannot land uncompensated — the exact way the first 33 did."""
    missing = [s for s in _wash_grounds() if s not in _compensating_selectors()]
    assert not missing, "these --ember-wash grounds do not re-state their inks (#3726):\n  " + "\n  ".join(missing)


def test_the_compensation_block_names_no_selector_that_is_not_a_wash_ground():
    """The other direction: a stale entry for a rule that no longer paints a wash is a
    silent, permanent ink shift on an untinted element."""
    grounds = set(_wash_grounds())
    stale = [s for s in _compensating_selectors() if s not in grounds]
    assert not stale, "the #3726 block compensates selectors that no longer paint an --ember-wash:\n  " + "\n  ".join(stale)


@pytest.mark.parametrize(
    "theme_name,pre_fix_hex,step",
    [("dark", "#988D78", "--surface-raised"), ("light", "#6F6757", "--surface-2"), ("light", "#6E665A", "--surface-2")],
)
def test_the_pre_fix_values_would_still_fail(theme_name, pre_fix_hex, step):
    """A negative control with teeth: the EXACT base hexes this fix works around must
    still measure below AA through this file's own engine. If one of these ever
    passes, the engine has gone soft and the assertions above prove nothing."""
    theme, dark = _themes()[theme_name]
    r = contrast(_hex_to_rgb(pre_fix_hex), _wash_over(step, theme, dark))
    assert r < AA, f"{theme_name}: {pre_fix_hex} now measures {r:.2f}:1 on wash over {step} — the control has gone blind"


def test_lowering_the_wash_weight_could_not_have_fixed_this():
    """States the premise the scoped fix rests on, so a future reader does not re-try
    the cheaper lever: even at ZERO tint the base ink has no AA headroom to give."""
    theme, dark = _themes()["dark"]
    bare = contrast(_resolve("--ink-faint", theme, dark), _resolve("--surface-raised", theme, dark))
    assert bare < MARGIN, f"--ink-faint now measures {bare:.2f}:1 on BARE --surface-raised — the base ramp gained headroom, re-derive #3726"


def test_the_three_reported_selectors_are_wash_grounds_painted_with_faint_ink():
    """Ties the computed contract back to the three axe findings, so a reader can
    confirm the cause is the one the sweep actually reported."""
    grounds = set(_wash_grounds())
    for sel in (".st-chip.st-hold", ".ch-badge.is-earned", ".rd-card .voice.human.his-words"):
        assert sel in grounds, f"{sel} no longer paints an --ember-wash background — re-derive the #3726 cause"
    css = _strip_comments("\n".join(p.read_text() for p in sorted(CSS_DIR.glob("*.css"))))
    for faint_sel in (r"\.st-pct", r"\.ch-badge-h", r"\.who"):
        assert re.search(faint_sel + r"[^{]*\{[^}]*color:\s*var\(--ink-faint\)", css), f"{faint_sel} no longer paints with --ink-faint"
