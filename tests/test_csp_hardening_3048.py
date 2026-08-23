"""
tests/test_csp_hardening_3048.py — the CSP hardening ratchet (#3048, DIL-015).

What this pins, and why:

  * **script-src has no 'unsafe-inline' and no third-party CDN on the production
    surface.** The diligence finding (DIL-015) was a script-injection foothold:
    any inline-script allowance turns one HTML-injection bug into arbitrary JS.
    Every inline block was extracted to /assets/js/ files or converted to
    non-executable type="application/json" data islands, so the allowance is
    retired. Re-adding either token to SCRIPT_SRC_HARDENED must red here first —
    it is an owner security decision, not a refactor.

  * **The site tree cannot regrow inline scripts.** Guard the SET, not the
    instance: a future page/generator that ships a new executable inline
    <script> would silently need 'unsafe-inline' back (the page would break in
    production while every other test stayed green). The tree sweep reds at
    commit time instead. /legacy is exempt — it is the frozen pre-v4 site,
    served under its own compat ResponseHeadersPolicy.

  * **The a11y harness stays off add_script_tag.** tests/a11y_audit.py used to
    inject axe via add_script_tag(content=…) — a real inline <script>, blocked
    under the hardened CSP. It now injects via page.evaluate (CDP, not governed
    by the page CSP). A revert would make the a11y gate raise on every page.

The LIVE distribution's header is asserted by deploy/smoke_test_site.sh against
scripts/expected_csp.py (source-derived) — that covers the "deployed
distribution" half of acceptance box 4; this file covers the source half, so a
drift in either direction reds something.

Offline: imports cdk/stacks/csp.py (stdlib-only by design). Run:
    python3 -m pytest tests/test_csp_hardening_3048.py -v
"""

import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CDK = os.path.join(_ROOT, "cdk")
if _CDK not in sys.path:
    sys.path.insert(0, _CDK)

from stacks.csp import (  # noqa: E402
    AMJ_CONNECT_SRC,
    SCRIPT_SRC_COMPAT,
    SCRIPT_SRC_HARDENED,
    build_site_csp,
)

_WEB_STACK = os.path.join(_CDK, "stacks", "web_stack.py")
_A11Y = os.path.join(_ROOT, "tests", "a11y_audit.py")
_SITE = os.path.join(_ROOT, "site")

# Inline (no src=) script blocks; type="application/json"/ld+json are exempt —
# they are data islands, not executable, and need no script-src allowance.
_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S | re.I)
_LOCAL_SRC_RE = re.compile(r"<script[^>]*\bsrc=[\"'](/assets/js/[^\"']+)[\"']", re.I)

# #2790 pattern: a sweep over an empty walk passes vacuously — floor the surface.
_MIN_SITE_HTML_FILES = 50


def _site_html_files():
    files = []
    for dirpath, dirnames, filenames in os.walk(_SITE):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", "legacy"}]
        files.extend(os.path.join(dirpath, n) for n in filenames if n.endswith(".html"))
    assert len(files) >= _MIN_SITE_HTML_FILES, (
        f"site HTML surface yielded only {len(files)} files (expected >= {_MIN_SITE_HTML_FILES}) — "
        "the os.walk root may have moved; the sweeps below cannot be trusted over an empty walk"
    )
    return files


# ══════════════════════════════════════════════════════════════════════════
# 1. The hardened policy — source pins (mutation-proof against a csp.py revert)
# ══════════════════════════════════════════════════════════════════════════


def test_hardened_script_src_is_self_only():
    assert SCRIPT_SRC_HARDENED == "script-src 'self'"


def test_hardened_policy_has_no_unsafe_inline_scripts_and_no_jsdelivr():
    csp = build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True)
    script_src = next(chunk.strip() for chunk in csp.split(";") if chunk.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in script_src, "script-src regained 'unsafe-inline' — that is DIL-015 reopening"
    assert "jsdelivr" not in csp, "the third-party CDN allowance was retired by #3048 (axe-core is vendored)"


def test_style_src_unchanged_by_the_hardening():
    """#3048 scopes to scripts; inline styles were not the injection foothold."""
    csp = build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True)
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_compat_profile_still_exists_for_legacy_and_subdomains():
    assert "'unsafe-inline'" in SCRIPT_SRC_COMPAT and "cdn.jsdelivr.net" in SCRIPT_SRC_COMPAT


def test_hardened_scripts_is_a_required_choice():
    """Every call site must choose its profile explicitly — no silent default."""
    try:
        build_site_csp(connect_src=AMJ_CONNECT_SRC)
    except TypeError:
        return
    raise AssertionError("build_site_csp() accepted a call without hardened_scripts — the profile must be an explicit choice")


# ══════════════════════════════════════════════════════════════════════════
# 2. web_stack wiring: hardened exactly where intended, /legacy/* carved out
# ══════════════════════════════════════════════════════════════════════════


def test_web_stack_hardens_exactly_the_main_domain_policy():
    src = open(_WEB_STACK, encoding="utf-8").read()
    assert len(re.findall(r"hardened_scripts=True\b", src)) == 1, "exactly ONE policy (the amj main-domain one) is hardened"
    assert len(re.findall(r"hardened_scripts=False\b", src)) == 2, "the subdomain + /legacy/* policies stay on the compat profile"


def test_web_stack_carves_out_a_legacy_behavior():
    src = open(_WEB_STACK, encoding="utf-8").read()
    assert '"/legacy/*"' in src, (
        "/legacy/* lost its dedicated cache behavior — the frozen old site would inherit the hardened default-behavior "
        "CSP and every legacy page's inline scripts would be blocked"
    )
    assert "legacy_security_headers" in src


# ══════════════════════════════════════════════════════════════════════════
# 3. The site tree stays inline-script-free (outside /legacy)
# ══════════════════════════════════════════════════════════════════════════


def test_no_executable_inline_scripts_in_site_tree():
    offenders = []
    for path in _site_html_files():
        for m in _SCRIPT_RE.finditer(open(path, encoding="utf-8", errors="ignore").read()):
            attrs = m.group(1)
            if "application/json" in attrs or "application/ld+json" in attrs:
                continue
            offenders.append(os.path.relpath(path, _ROOT))
            break
    assert not offenders, (
        "executable inline <script> blocks reappeared — under the hardened CSP (script-src 'self') these are BLOCKED in "
        'production. Extract to /assets/js/ or use a type="application/json" data island:\n  ' + "\n  ".join(offenders)
    )


def test_every_referenced_local_script_asset_exists():
    """An extraction typo (bad src path) would 404 and silently drop page JS."""
    missing = []
    for path in _site_html_files():
        for src in _LOCAL_SRC_RE.findall(open(path, encoding="utf-8", errors="ignore").read()):
            if not os.path.exists(os.path.join(_SITE, src.lstrip("/"))):
                missing.append(f"{os.path.relpath(path, _ROOT)} → {src}")
    assert not missing, "HTML references /assets/js/ files that do not exist:\n  " + "\n  ".join(missing)


def test_page_data_islands_parse_as_json():
    """The build-time data islands must be valid JSON (incl. the <\\/ escaping
    that keeps '</script>' inside payload strings from closing the tag)."""
    island_re = re.compile(r'<script type="application/json" id="page-data">(.*?)</script>', re.S)
    seen = 0
    for path in _site_html_files():
        for payload in island_re.findall(open(path, encoding="utf-8", errors="ignore").read()):
            json.loads(payload)  # raises on malformed emission
            seen += 1
    assert seen >= 50, f"expected >= 50 #page-data islands across the archive/coaching/story shells, found {seen}"


# ══════════════════════════════════════════════════════════════════════════
# 4. The a11y harness cannot regress to inline injection
# ══════════════════════════════════════════════════════════════════════════


def test_a11y_audit_does_not_call_add_script_tag():
    """AST, not grep — the docstring legitimately EXPLAINS why the call is
    forbidden; only a real call site is a regression."""
    import ast

    tree = ast.parse(open(_A11Y, encoding="utf-8").read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_script_tag"]
    assert not calls, (
        "tests/a11y_audit.py reverted to add_script_tag — that creates a real inline <script>, which the hardened CSP "
        "blocks; the audit would raise on every page. Inject via page.evaluate (CDP) instead."
    )
