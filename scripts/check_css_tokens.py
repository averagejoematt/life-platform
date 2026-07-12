#!/usr/bin/env python3
"""
check_css_tokens.py — the #1103 guard: the swept sheets stay on the type scale.

Two checks over site/assets/css/{story,evidence,cockpit}.css:

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


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


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
