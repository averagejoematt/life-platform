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

5. GENERATED INLINE `<style>` (#1974) — checks 1 and 4 again, over the page-scoped
   `<style>` blocks the v4 page generators emit, and over the built pages themselves.
   The stylesheet sweep above was a partial gate: the same drift class simply moved to
   the surface it never reached, and six generators shipped five rogue breakpoints
   (560/620/640/720/900) plus a `font-size:64px` drop cap to live pages. Both halves of
   the surface are swept, and both are DERIVED, never enumerated:
     * every `scripts/v4_build_*.py` (glob) — the generator, the real source of truth;
     * every non-legacy `site/**/*.html` (rglob) — the built page, so a hand-edit that
       drifts from its generator is caught too.
   Only the breakpoint + font-size checks run here (the two whose sanctioned vocabulary
   — the §10.1 nine numbers, the --fs-* triad — is unambiguous in a page-scoped block).
   The hex/undefined-token checks stay stylesheet-only for now: generated blocks legitimately
   reference runtime-set props, and retiring a live undefined-token reference is a palette
   decision, not a mechanical retarget.

6. SANCTION ISSUE REFS (#1976) — a `hex-ok:`/`fs-ok:` sanction's reason must be either
   a self-contained, verifiable design rationale (geometry, a measured floor, a
   deliberate relative de-emphasis — the reader can check it without leaving the file)
   OR name the OPEN issue tracking deferred work as `#NNNN`. Free text with no schema
   was exactly how the designer-2 hex-ok grandfathering happened invisibly: eight
   `hex-ok: a separate finding`-style comments that `gh` could never find — untracked
   forward work the backlog never saw. Two rules, offline (grammar-shape only, no
   network — safe in the pytest gate):
     * every `hex-ok:` sanction must carry a `#NNNN` ref. Hex has no legitimate
       self-contained form — DESIGN_SYSTEM_V5 §4 forbids an off-palette literal
       outright, so any surviving one is BY DEFINITION a tracked exception, never a
       standing design decision.
     * an `fs-ok:` sanction only needs a ref when its reason READS AS A DEFERRAL —
       "a separate finding", "follow-up", "TODO", "pending", etc. (`_DEFERRAL_MARKERS`)
       — so the ~30 existing self-contained fs-ok reasons (drop caps, book-spine
       geometry, the #1210 SVG floor) keep working unchanged.
   A THIRD, separate, live check — `verify_sanction_issue_refs()` / `main()`'s
   `--verify-issues` — confirms every cited `#NNNN` is still an OPEN issue (`gh issue
   list`, same graceful-skip-when-unreachable shape as check_backlog_hygiene.py's
   `_fetch_live_issues`). That half needs network, so it is NEVER called from `check()`
   (what the offline pytest gate runs) — only from `main()`, run directly.

Exit 0 clean, 1 with findings. Run:  python3 scripts/check_css_tokens.py
                                      python3 scripts/check_css_tokens.py --verify-issues  (+network)
Enforced by tests/test_css_tokens.py.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
REPO_SLUG = "averagejoematt/life-platform"
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

# (#1974) The generated-CSS surface, DERIVED not enumerated — a new page generator or a
# new built page joins the sweep the moment it lands, which is the whole point of the gate.
GENERATOR_GLOB = "v4_build_*.py"
BUILT_GLOB = "*.html"
# site/legacy is the frozen pre-v4 site (private rollback, never linked) — out of scope.
BUILT_EXCLUDE_DIRS = {"legacy"}

STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)

VAR_REF = re.compile(r"var\(\s*(--[\w-]+)")
PROP_DEF = re.compile(r"(--[\w-]+)\s*:")
FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}]+)")
# CSS hex colour literals only (3/4/6/8 digits) — not 5- or 7-digit runs.
HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
# §10.1 breakpoint literal — the doc's grep, with the pixel value captured.
BP_MEDIA = re.compile(r"\((?:max|min)-width:\s*([0-9]+)px\)")

# (#1976) A hex-ok/fs-ok sanction's reason text — everything after the marker up to
# the comment close (or end of line, for a one-line-comment `<style>` block).
SANCTION_REASON = re.compile(r"(hex-ok|fs-ok):\s*(.*?)(?:\*/|$)")
# An issue reference inside a sanction reason. Deliberately bare `#\d+` (not anchored
# to word boundaries beyond \d) — a reason is free prose, not CSS, so there is no hex
# literal to confuse it with.
ISSUE_REF = re.compile(r"#(\d+)")

# (#1976) Deferral language: a reason that points to work happening SOMEWHERE ELSE
# rather than documenting its own rationale in place. This is the exact shape of the
# designer-2 grandfathering — "a separate finding" that `gh` could never find. A
# deferral-style reason with no #NNNN is a promise nobody filed; the gate must not
# bless it silently. A self-contained reason (geometry, a measured floor, "deliberate
# relative de-emphasis") needs no ref — it can be checked without leaving the file.
_DEFERRAL_MARKERS = (
    "separate finding",
    "separate issue",
    "follow-up",
    "followup",
    "future work",
    "future fix",
    " todo",
    "todo:",
    "fixme",
    "will fix",
    "to be fixed",
    "pending",
    "tbd",
    "revisit",
    "deferred",
    "defer to",
)


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


def _sanction_reason(line: str) -> Optional[Tuple[str, str]]:
    """(kind, reason) for the first hex-ok/fs-ok sanction on `line`, or None. `kind`
    is the literal marker text ("hex-ok" or "fs-ok"); `reason` is trimmed prose."""
    m = SANCTION_REASON.search(line)
    if not m:
        return None
    return m.group(1), m.group(2).strip()


def _is_deferral_reason(reason: str) -> bool:
    low = f" {reason.lower()} "
    return any(marker in low for marker in _DEFERRAL_MARKERS)


def sanction_issue_ref_findings(name: str, text: str) -> list:
    """(#1976) Offline grammar half: every `hex-ok:` sanction, and every `fs-ok:`
    sanction whose reason reads as a deferral, must cite an issue as `#NNNN`. Live
    open/closed state of any cited issue is verified separately by
    `verify_sanction_issue_refs` (network — never called from here or from `check()`,
    so this stays safe in the offline pytest gate)."""
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        parsed = _sanction_reason(line)
        if not parsed:
            continue
        kind, reason = parsed
        if not reason:
            continue
        deferral = _is_deferral_reason(reason)
        if kind == "hex-ok":
            requires_ref, why = True, "hex-ok always needs one — no off-palette literal has a self-contained rationale"
        else:
            requires_ref, why = deferral, "reads as a deferral to work tracked elsewhere"
        if requires_ref and not ISSUE_REF.search(reason):
            findings.append(
                f"{name}:{i}: {kind} sanction with no issue reference ({why}): '{reason}' — "
                "cite the OPEN issue as `#NNNN` in the reason, or rewrite as a self-contained, "
                "verifiable reason that needs no ref (#1976)"
            )
    return findings


def sanction_issue_refs(name: str, text: str) -> Dict[int, List[str]]:
    """(#1976) {issue_number: ["name:line", …]} for every #NNNN cited inside a
    hex-ok/fs-ok sanction reason in `text`. Feeds the live open/closed check."""
    refs: Dict[int, List[str]] = {}
    for i, line in enumerate(text.splitlines(), 1):
        parsed = _sanction_reason(line)
        if not parsed:
            continue
        _, reason = parsed
        for m in ISSUE_REF.finditer(reason):
            refs.setdefault(int(m.group(1)), []).append(f"{name}:{i}")
    return refs


def verify_sanction_issue_refs(refs: Dict[int, List[str]], open_issue_numbers: Set[int]) -> list:
    """(#1976) Live half, but a PURE function — takes the open-issue set so it is
    unit-testable with no network. A sanction citing #NNNN where NNNN is not open
    (closed, or `gh` never heard of it) is a promise the backlog no longer honours;
    the gate must not stay silent about that either. `main()` supplies the real set
    from `gh issue list` (skipped, advisory, if `gh` can't be reached)."""
    findings = []
    for number in sorted(refs):
        if number in open_issue_numbers:
            continue
        for loc in refs[number]:
            findings.append(f"{loc}: sanction cites #{number}, which is not an OPEN issue — closed, or `gh` could not find it")
    return findings


def _fetch_open_issue_numbers() -> Optional[Set[int]]:
    """`gh issue list --state open` numbers, or None if `gh` is unreachable/unauth'd —
    graceful-skip, same shape as check_backlog_hygiene.py's _fetch_live_issues."""
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "-R", REPO_SLUG, "--state", "open", "--json", "number", "--limit", "1000"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"check_css_tokens: gh issue list exited {result.returncode}: {result.stderr[:300]}; skipping live issue-ref check.")
            return None
        return {item["number"] for item in json.loads(result.stdout or "[]")}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"check_css_tokens: could not fetch live issues via gh ({e}); skipping live issue-ref check.")
        return None


def all_sanction_issue_refs() -> Dict[int, List[str]]:
    """(#1976) sanction_issue_refs, merged across every swept sheet AND the generated
    inline-<style> surface — the same two halves check() and the #1974 sweep cover."""
    refs: Dict[int, List[str]] = {}
    for name in SWEPT:
        for number, locs in sanction_issue_refs(name, (CSS_DIR / name).read_text()).items():
            refs.setdefault(number, []).extend(locs)
    for label, path in generated_style_sources():
        masked = style_block_mask(path.read_text(errors="replace"))
        for number, locs in sanction_issue_refs(label, masked).items():
            refs.setdefault(number, []).extend(locs)
    return refs


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


def style_block_mask(text: str) -> str:
    """(#1974) `text` with everything OUTSIDE a `<style>…</style>` body blanked, line
    numbers preserved. Feeding this to the existing per-line checks makes them scan the
    generated CSS only — a `font-size: 12px` in a Python comment or a `(max-width: 520px)`
    in prose is not a live declaration — while every reported line number stays the real
    line number in the real file."""
    pieces = []
    cursor = 0
    for m in STYLE_BLOCK.finditer(text):
        pieces.append("\n" * text.count("\n", cursor, m.start(1)))
        pieces.append(m.group(1))
        cursor = m.end(1)
    pieces.append("\n" * text.count("\n", cursor, len(text)))
    return "".join(pieces)


def generated_style_sources() -> list:
    """(#1974) Both halves of the generated surface, derived: every v4 page generator and
    every non-legacy built page. Returned as (label, path) with a repo-relative label."""
    sources = [(f"scripts/{p.name}", p) for p in sorted((REPO / "scripts").glob(GENERATOR_GLOB))]
    for p in sorted((REPO / "site").rglob(BUILT_GLOB)):
        if BUILT_EXCLUDE_DIRS & set(p.relative_to(REPO).parts):
            continue
        sources.append((str(p.relative_to(REPO)), p))
    return sources


def inline_style_findings(name: str, text: str) -> list:
    """(#1974) The §10.1 breakpoint + type-scale checks over the `<style>` blocks in
    `text` (a generator source or a built page). Returns finding strings with real
    file line numbers."""
    masked = style_block_mask(text)
    if not STYLE_BLOCK.search(text):
        return []
    return breakpoint_findings_in(name, masked) + font_size_findings(name, masked) + sanction_issue_ref_findings(name, masked)


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
        # (#1976) A sanction that defers work must name an OPEN issue — offline
        # grammar half only; live open/closed state is verify_sanction_issue_refs.
        findings.extend(sanction_issue_ref_findings(name, text))
    # §10.1 breakpoint invariant (#1212) — swept across ALL sheets, tokens.css included
    # (breakpoints are constants used everywhere; there is no allowlist file for them).
    for sheet in sorted(CSS_DIR.glob("*.css")):
        findings.extend(breakpoint_findings_in(sheet.name, sheet.read_text()))
    # (#1974) …and across the GENERATED surface the stylesheet sweep never reached: the
    # inline <style> blocks the v4 generators emit, plus the built pages they write.
    for label, path in generated_style_sources():
        findings.extend(inline_style_findings(label, path.read_text(errors="replace")))
    return findings


def main() -> int:
    findings = check()
    exit_code = 0
    if findings:
        print(f"check_css_tokens: {len(findings)} finding(s)")
        for f in findings:
            print("  " + f)
        exit_code = 1
    else:
        print("check_css_tokens: clean")

    # (#1976) Live half — opt-in (needs network + gh auth), so it stays out of the
    # default offline run and out of the pytest gate entirely. Skips (advisory,
    # exit unaffected) when gh is unreachable — a sanction citing a real, open issue
    # must never be blocked by a CI runner with no `gh` auth.
    if "--verify-issues" in sys.argv:
        open_numbers = _fetch_open_issue_numbers()
        if open_numbers is not None:
            live_findings = verify_sanction_issue_refs(all_sanction_issue_refs(), open_numbers)
            if live_findings:
                print(f"check_css_tokens: {len(live_findings)} sanction issue-ref finding(s) (live)")
                for f in live_findings:
                    print("  " + f)
                exit_code = 1
            else:
                print("check_css_tokens: all cited sanction issue refs are OPEN")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
