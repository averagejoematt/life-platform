#!/usr/bin/env python3
"""
check_css_tokens.py — the #1103 guard: the swept sheets stay on the type scale.

Three checks over site/assets/css/{story,evidence,cockpit}.css:

1. RAW FONT-SIZES — every `font-size` must come from a token (`var(--fs-*)` etc.),
   be `inherit`, or carry an explicit inline `/* fs-ok: <reason> */` sanction on the
   same line (SVG viewBox coordinates, drop caps, geometry-fitted instrument text,
   deliberate relative em de-emphasis). Unsanctioned literals bypass the type triad
   and a future type-scale change silently misses them.

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

Exit 0 clean, 1 with findings. Run:  python3 scripts/check_css_tokens.py
Enforced by tests/test_css_tokens.py.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSS_DIR = REPO / "site" / "assets" / "css"
TOKENS = CSS_DIR / "tokens.css"
SWEPT = ["story.css", "evidence.css", "cockpit.css"]

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
        for i, line in enumerate(text.splitlines(), 1):
            sanctioned = "fs-ok:" in line
            code = re.sub(r"/\*.*?(\*/|$)", " ", line)  # per-line comment strip
            m = FONT_SIZE.search(code)
            if m and not sanctioned:
                val = m.group(1).strip()
                literal = re.search(r"(?<![\w-])\d*\.?\d+\s*(px|rem|em|%|vw|vh)", val)
                if literal and not val.startswith("var("):
                    findings.append(f"{name}:{i}: raw font-size `{val}` — use a --fs-* token or sanction with /* fs-ok: reason */")
                elif literal and val.startswith("var("):
                    findings.append(f"{name}:{i}: font-size var() with a literal fallback `{val}` — resolve the token instead")
            for vm in VAR_REF.finditer(code):
                if vm.group(1) not in known:
                    findings.append(
                        f"{name}:{i}: reference to undefined token `{vm.group(1)}` — "
                        "define it in tokens.css or use a real token (silent always-active fallback)"
                    )
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
