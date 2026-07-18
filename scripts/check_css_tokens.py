#!/usr/bin/env python3
"""
check_css_tokens.py — the #1103/#1211/#1212 guard: the CONSUMER sheets stay on the
design system (type scale + colour tokens + the sanctioned breakpoints).

Four checks over the seven CONSUMER sheets in site/assets/css/ (#1212 extended the
sweep from the original three to all seven — story, evidence, cockpit, mind, fonts,
section_toc, subscribe). tokens.css is the DEFINITIONS / ALLOWLIST source — where the
--fs-* scale, the colour primitives and the breakpoint constants are *defined* — so it
is never a swept target (it would flag its own definitions); it only feeds the set of
known tokens.

1. RAW FONT-SIZES — every `font-size` must come from a token (`var(--fs-*)` etc.),
   be `inherit`, or carry an explicit inline `/* fs-ok: <reason> */` sanction on the
   same line (drop caps, geometry-fitted instrument text, deliberate relative em
   de-emphasis). Unsanctioned literals bypass the type triad and a future type-scale
   change silently misses them. (#1210) 'SVG viewBox units' ALONE is no longer a
   valid reason — that bare sanction is exactly what let inline-SVG <text> ship at
   7–9px effective (viewBox-unit text scales with rendered width). A viewBox-unit
   font-size must EITHER drop the literal for the shared floor-scaler
   (`font-size: var(--fs-*)`, floored >=11px effective per-svg by svgtype.js) OR keep
   a literal that documents why its minimum rendered scale stays >=11px effective;
   tests/visual_qa.py's getScreenCTM sweep is the arbiter.

2. UNDEFINED TOKENS — every `var(--x)` reference must resolve: defined in
   tokens.css, defined in the sheet itself, or set at runtime (JS setProperty /
   inline style attributes — the RUNTIME_PROPS allowlist). A reference to an
   undefined token means its fallback is silently ALWAYS active (the
   story.css:351 `var(--radius-2, 8px)` bug class) — or, with no fallback, the
   declaration is invalid at computed-value time.

3. RAW HEX COLOURS (#1211) — no `#rgb`/`#rrggbb`/`#rgba`/`#rrggbbaa` literal in the
   swept sheets. DESIGN_SYSTEM_V5 §4 forbids hardcoding a colour outside tokens.css
   (the single-ember rule + the sanctioned `--coach`/`--pillar-*`/`--tier-accent`
   channels). Colours live in tokens.css (the allowlist — never swept) and reach the
   sheets via `var(--…)`. A deliberate off-palette literal must carry an explicit
   inline `/* hex-ok: <reason> */` sanction on the same line — issue-number refs and
   any other hex inside a comment are ignored (comments are stripped first). This is
   what caught the live off-palette accents #0ea5e9 (lead-coach sky) and #16a34a
   (vice-hold green) that bypassed the ember channel.

4. BREAKPOINTS (#1212) — DESIGN_SYSTEM_V5 §10.1: the site has no CSS build step, so
   `@media` breakpoints are documented NAMED CONSTANTS. Every `(max|min)-width: Npx`
   across site/assets/css/** must be one of the nine sanctioned numbers — the six
   canonical `max-width` boundaries 360/480/600/760/820 plus the `min-width` token+1
   pairs 601/761/821/901 (so a min/max pair straddling a boundary never both fire at
   the same pixel). A tenth value is a rogue breakpoint (the story.css:582
   `(max-width: 520px)` class). The grep in §10.1 — the "(max|min)-width: Npx" sweep
   that returns only those nine numbers — is turned into this assertion.

Exit 0 clean, 1 with findings. Run:  python3 scripts/check_css_tokens.py
Enforced by tests/test_css_tokens.py.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSS_DIR = REPO / "site" / "assets" / "css"
TOKENS = CSS_DIR / "tokens.css"
# The CONSUMER sheets — swept for hex / font-size / undefined-var. tokens.css is the
# definitions/allowlist source (never swept — it *is* where the scale and palette live).
SWEPT = ["story.css", "evidence.css", "cockpit.css", "mind.css", "fonts.css", "section_toc.css", "subscribe.css"]

# DESIGN_SYSTEM_V5 §10.1: the six canonical max-width boundaries + their min-width
# token+1 pairs. These nine numbers are the ONLY breakpoints allowed in the CSS.
SANCTIONED_BREAKPOINTS = {360, 480, 600, 760, 820, 601, 761, 821, 901}

# Custom properties set at runtime — JS el.style.setProperty / inline style="--x: …"
# attributes in the renderers — or by generated/inline HTML. Not statically defined
# in any stylesheet, so the static check must not flag references to them.
RUNTIME_PROPS = {
    "--coach",  # coach signature color (coaching.js, style attr)
    "--vd-delay",  # verdict beat stagger (cockpit.js)
    "--cv-delay",  # convene-the-board stagger (coaching.js)
    "--emag",  # constellation edge magnitude (story.js)
    "--heat",  # heat-strip intensity (evidence renderers)
    "--o",  # generic opacity slot (charts.js)
    "--cbar-h",  # consistency-bar height (cockpit.js)
    "--fill",  # meter fill fraction (various renderers)
    "--delay",  # generic stagger slot
}

VAR_REF = re.compile(r"var\(\s*(--[\w-]+)")
PROP_DEF = re.compile(r"(--[\w-]+)\s*:")
FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}]+)")
# CSS hex colour literals only (3/4/6/8 digits) — not 5- or 7-digit runs.
HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
# §10.1 breakpoint literal — the doc's grep, with the pixel value captured.
BP_MEDIA = re.compile(r"\((?:max|min)-width:\s*([0-9]+)px\)")


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def code_lines(text: str) -> list:
    """Blank every /* … */ comment (incl. multi-line) while preserving line numbers,
    so a hex inside a comment — issue refs like `#1112`, a `hex-ok:` sanction note —
    is never mistaken for a live colour literal."""
    blanked = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return blanked.splitlines()


def raw_hex_findings(text: str) -> list:
    """(#1211) Line numbers of live raw-hex colour literals in `text`. A hex inside a
    comment is ignored (comments are blanked first); a line carrying `hex-ok:` is a
    sanctioned exception. Returns [(lineno, hex), …]."""
    raw = text.splitlines()
    stripped = code_lines(text)
    hits = []
    for i, line in enumerate(raw, 1):
        if "hex-ok:" in line:
            continue
        for hm in HEX_COLOR.finditer(stripped[i - 1]):
            hits.append((i, hm.group(0)))
    return hits


# (#1210) 'SVG viewBox units' alone is no longer a valid fs-ok reason — that bare
# sanction is exactly what let /data/vitals + /data/character ship 7–9px labels
# (viewBox-unit text scales with rendered width). A viewBox-unit font-size must now
# EITHER drop the literal for the shared floor-scaler (`font-size: var(--fs-*)`, set
# per-svg to >=11px effective by site/assets/js/svgtype.js — no literal, so it never
# reaches this check) OR keep a literal that DOCUMENTS why its minimum rendered scale
# stays >=11px effective. tests/visual_qa.py's getScreenCTM sweep is the arbiter that
# the floor actually holds; this static gate just closes the hand-wave loophole.
_FLOOR_JUSTIFY = ("floor", "effective", "11px")


def _viewbox_sanction_without_floor(line: str) -> bool:
    """True if an fs-ok reason invokes 'viewBox' but documents no >=11px floor —
    the retired sanction class (#1210). Such a line no longer sanctions a literal."""
    m = re.search(r"fs-ok:\s*(.*)", line)
    if not m:
        return False
    reason = m.group(1).split("*/")[0].lower()
    if "viewbox" not in reason:
        return False
    return not any(k in reason for k in _FLOOR_JUSTIFY)


def font_size_findings(name: str, text: str) -> list:
    """Raw / literal-fallback font-sizes in `text`. A line carrying `fs-ok:` is a
    sanctioned exception; per-line comments are stripped first. Returns finding strings."""
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        sanctioned = "fs-ok:" in line and not _viewbox_sanction_without_floor(line)
        code = re.sub(r"/\*.*?(\*/|$)", " ", line)  # per-line comment strip
        m = FONT_SIZE.search(code)
        if m and not sanctioned:
            val = m.group(1).strip()
            literal = re.search(r"(?<![\w-])\d*\.?\d+\s*(px|rem|em|%|vw|vh)", val)
            retired = _viewbox_sanction_without_floor(line)
            if literal and not val.startswith("var("):
                if retired:
                    findings.append(
                        f"{name}:{i}: retired sanction — 'SVG viewBox units' alone no longer sanctions raw font-size `{val}` (#1210). "
                        "Use the shared floor-scaler (font-size: var(--fs-*), floored >=11px effective by svgtype.js) or document why "
                        "the minimum rendered scale keeps it >=11px effective (mention 'floor'/'effective'/'11px')."
                    )
                else:
                    findings.append(f"{name}:{i}: raw font-size `{val}` — use a --fs-* token or sanction with /* fs-ok: reason */")
            elif literal and val.startswith("var("):
                findings.append(f"{name}:{i}: font-size var() with a literal fallback `{val}` — resolve the token instead")
    return findings


def undefined_var_findings(name: str, text: str, known: set) -> list:
    """var(--x) references that resolve to no known token. Returns finding strings."""
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        code = re.sub(r"/\*.*?(\*/|$)", " ", line)
        for vm in VAR_REF.finditer(code):
            if vm.group(1) not in known:
                findings.append(
                    f"{name}:{i}: reference to undefined token `{vm.group(1)}` — "
                    "define it in tokens.css or use a real token (silent always-active fallback)"
                )
    return findings


def breakpoint_findings_in(name: str, text: str) -> list:
    """(#1212) §10.1: every (max|min)-width value in `text` must be one of the nine
    sanctioned breakpoints. A breakpoint inside a comment is not a live query (comments
    are blanked first). Returns finding strings for any rogue value."""
    findings = []
    for i, line in enumerate(code_lines(text), 1):
        for m in BP_MEDIA.finditer(line):
            val = int(m.group(1))
            if val not in SANCTIONED_BREAKPOINTS:
                findings.append(
                    f"{name}:{i}: rogue breakpoint `{val}px` — DESIGN_SYSTEM_V5 §10.1 sanctions only "
                    f"{sorted(SANCTIONED_BREAKPOINTS)} (max 360/480/600/760/820 + min token+1 601/761/821/901)"
                )
    return findings


def defined_props(*files: Path) -> set:
    props = set()
    for f in files:
        for m in PROP_DEF.finditer(strip_comments(f.read_text())):
            props.add(m.group(1))
    return props


def check() -> list:
    findings = []
    base = defined_props(TOKENS)
    for name in SWEPT:
        sheet = CSS_DIR / name
        text = sheet.read_text()
        known = base | defined_props(sheet) | RUNTIME_PROPS
        # Raw hex colour (#1211) — comment refs stripped, `hex-ok:` lines sanctioned.
        for lineno, hexval in raw_hex_findings(text):
            findings.append(
                f"{name}:{lineno}: raw hex colour `{hexval}` — use a tokens.css "
                "colour (var(--…), e.g. --ember/--coach) or sanction with /* hex-ok: reason */"
            )
        findings.extend(font_size_findings(name, text))
        findings.extend(undefined_var_findings(name, text, known))
    # §10.1 breakpoint invariant (#1212) — swept across ALL sheets, tokens.css included
    # (breakpoints are constants used everywhere; there is no allowlist file for them).
    for sheet in sorted(CSS_DIR.glob("*.css")):
        findings.extend(breakpoint_findings_in(sheet.name, sheet.read_text()))
    return findings


def main() -> int:
    findings = check()
    if findings:
        print(f"check_css_tokens: {len(findings)} finding(s)")
        for f in findings:
            print("  " + f)
        return 1
    print("check_css_tokens: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
