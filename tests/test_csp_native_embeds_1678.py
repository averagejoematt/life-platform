"""
tests/test_csp_native_embeds_1678.py — the CSP allow-list ratchet (#1678, ADR-149).

What this pins, and why each pin exists rather than being a matter of care:

  * **The OFF path is byte-identical to production.** The two CSP string literals
    that used to live in `web_stack.py` were replaced by one builder. The frozen
    literals below were captured from the LIVE response headers of
    `https://averagejoematt.com/` on 2026-08-06, not copied out of the source, so
    this is a real refactor-safety net: if the builder ever drifts from what is
    deployed, this reds before a `cdk deploy` discovers it.

  * **The allow-list cannot silently widen.** The owner's 2026-08-02 sign-off on
    #1678 approves exactly one third-party origin, `youtube-nocookie.com`, and
    says "never a blanket `https:`, never a second origin added without returning
    here." A tuple in source is a suggestion; a test that names the approved set
    is the enforcement. Adding an origin must red this file, which is the prompt
    to go back to the issue.

  * **The two policies cannot drift apart.** `web_stack.py` must reach the CSP
    only through the builder — no re-hardcoded literal, in either block. Checked
    by reading the source, so it holds even for a block this test never synths.

  * **The mechanism is inert on merge.** `cdk.json` must declare the flag `false`.
    This is not belt-and-braces: ci-cd.yml's Plan job greps `cdk diff` for
    /iam|policy|role|permission/i and exits 1 on a match, and a CSP change touches
    `AWS::CloudFront::ResponseHeadersPolicy`. A merged-but-undeployed widening
    would red Plan and strand every later CI deploy (the R8-ST6 class).

  * **The facade fallback is still the truth on the site.** ADR-149 landed the
    mechanism, not the players. Until the owner flips the flag AND runs
    `cdk deploy LifePlatformWeb`, a third-party `<iframe>` in `site/` would render
    as a blocked blank box. The last test keeps `site/` honest about that.

Offline: imports `cdk/stacks/csp.py`, which is stdlib-only by design (CI's test
job does not install `aws-cdk-lib` — see that module's docstring).

Run: python3 -m pytest tests/test_csp_native_embeds_1678.py -v
"""

import ast
import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CDK = os.path.join(_ROOT, "cdk")
if _CDK not in sys.path:
    sys.path.insert(0, _CDK)

from stacks.csp import (  # noqa: E402
    AMJ_CONNECT_SRC,
    NATIVE_EMBED_CONTEXT_KEY,
    NATIVE_EMBED_FRAME_SRC,
    build_site_csp,
    native_embeds_enabled,
)

_WEB_STACK = os.path.join(_CDK, "stacks", "web_stack.py")
_CDK_JSON = os.path.join(_CDK, "cdk.json")

# The connect-src the subdomain policy legitimately differs by (the amj value
# is now the source of truth in stacks.csp — #3048).
SUBDOMAIN_CONNECT_SRC = "'self' https://averagejoematt.com https://*.averagejoematt.com"

# #3048 (DIL-015): the main-domain policy HARDENED — script-src 'self' only.
# This is the string the deployed distribution must serve after
# `cdk deploy LifePlatformWeb`; deploy/smoke_test_site.sh asserts it live.
LIVE_AMJ_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self' https://averagejoematt.com; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# The COMPAT policy (pre-#3048 script-src) — /legacy/* and the subdomains only.
COMPAT_LEGACY_CSP = LIVE_AMJ_CSP.replace(
    "script-src 'self';",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;",
)

# The subdomain policy: compat script-src + the wider connect-src
# (dash/blog/buddy are not on the public smoke path, so this one is source-frozen).
PRE_ADR149_SUBDOMAIN_CSP = COMPAT_LEGACY_CSP.replace(
    "connect-src 'self' https://averagejoematt.com;",
    "connect-src 'self' https://averagejoematt.com https://*.averagejoematt.com;",
)

# The exact allow-list the owner approved on #1678 (2026-08-02). Changing this
# constant is a security decision, not a refactor.
OWNER_APPROVED_FRAME_SRC = ("https://www.youtube-nocookie.com",)

# Origins that were floated in the earlier (2026-07-25) comment on #1678 and are
# NOT in the final sign-off. ADR-149 rejects the script-based embeds outright.
REJECTED_ORIGINS = (
    "https://www.youtube.com",
    "https://youtube.com",
    "https://platform.twitter.com",
    "https://x.com",
    "https://twitter.com",
    "https://www.instagram.com",
    "https://bsky.app",
    "https://embed.bsky.app",
    "https://player.vimeo.com",
    "https://www.tiktok.com",
)


def _directives(csp: str) -> dict:
    """Split a CSP string into {name: [tokens]}."""
    out = {}
    for chunk in csp.split(";"):
        parts = chunk.strip().split()
        if parts:
            out[parts[0]] = parts[1:]
    return out


# ══════════════════════════════════════════════════════════════════════════
# 1. The OFF path is a pure refactor
# ══════════════════════════════════════════════════════════════════════════


def test_off_matches_the_hardened_main_domain_policy_byte_for_byte():
    assert build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True) == LIVE_AMJ_CSP


def test_legacy_compat_policy_byte_for_byte():
    assert build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=False) == COMPAT_LEGACY_CSP


def test_off_matches_the_pre_adr149_subdomain_policy_byte_for_byte():
    assert build_site_csp(connect_src=SUBDOMAIN_CONNECT_SRC, hardened_scripts=False) == PRE_ADR149_SUBDOMAIN_CSP


def test_off_emits_no_frame_src_at_all():
    """No directive means media/frame fall back to `default-src 'self'`."""
    for connect_src in (AMJ_CONNECT_SRC, SUBDOMAIN_CONNECT_SRC):
        for hardened in (True, False):
            assert "frame-src" not in _directives(build_site_csp(connect_src=connect_src, hardened_scripts=hardened))


# ══════════════════════════════════════════════════════════════════════════
# 2. The ON path adds exactly the approved allow-list and nothing else
# ══════════════════════════════════════════════════════════════════════════


def test_allowlist_constant_is_exactly_the_owner_approved_set():
    """#1678 sign-off: 'exactly youtube-nocookie.com … never a second origin
    added without returning here.' If this reds, go back to the issue."""
    assert tuple(NATIVE_EMBED_FRAME_SRC) == OWNER_APPROVED_FRAME_SRC


def test_on_adds_frame_src_with_only_the_approved_origins():
    csp = build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True, native_social_embeds=True)
    assert _directives(csp)["frame-src"] == list(OWNER_APPROVED_FRAME_SRC)


def test_on_differs_from_off_by_the_frame_src_directive_only():
    off = _directives(build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True))
    on = _directives(build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True, native_social_embeds=True))
    assert set(on) - set(off) == {"frame-src"}
    for name, tokens in off.items():
        assert on[name] == tokens, f"{name} changed when native embeds were enabled"


def test_no_wildcards_or_bare_schemes_in_the_allowlist():
    """A blanket `https:` or any `*` is the exact thing the sign-off forbids."""
    for origin in NATIVE_EMBED_FRAME_SRC:
        assert "*" not in origin, f"wildcard origin: {origin}"
        assert origin.startswith("https://"), f"non-https origin: {origin}"
        host = origin[len("https://") :]
        assert host and "/" not in host, f"frame-src takes a bare origin, not a path: {origin}"


def test_media_src_is_never_widened_to_a_third_party():
    """ADR-149 deliberately ships frame-src only — an iframe player's own media
    is governed by the iframe document's CSP, not ours."""
    for enabled in (False, True):
        directives = _directives(build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True, native_social_embeds=enabled))
        assert "media-src" not in directives


def test_rejected_origins_appear_nowhere_in_either_mode():
    for enabled in (False, True):
        csp = build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True, native_social_embeds=enabled)
        for origin in REJECTED_ORIGINS:
            assert origin not in csp, f"{origin} is not owner-approved (ADR-149) but appears in the CSP"


def test_frame_ancestors_stays_none_in_both_modes():
    """frame-src (who we may frame) must never be confused with frame-ancestors
    (who may frame us) — widening one must not touch the other."""
    for enabled in (False, True):
        directives = _directives(build_site_csp(connect_src=AMJ_CONNECT_SRC, hardened_scripts=True, native_social_embeds=enabled))
        assert directives["frame-ancestors"] == ["'none'"]


# ══════════════════════════════════════════════════════════════════════════
# 3. The flag is inert by default and fails closed
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("raw", [True, "true", "TRUE", " True ", "1", "yes", "on"])
def test_flag_coercion_on(raw):
    assert native_embeds_enabled(raw) is True


@pytest.mark.parametrize("raw", [False, "false", "0", "no", "", None, 1, ["true"], {"a": 1}])
def test_flag_coercion_fails_closed(raw):
    """Anything not explicitly, recognisably true is OFF — a typo must not widen
    the public CSP."""
    assert native_embeds_enabled(raw) is False


def test_cdk_json_declares_the_flag_false():
    """Inert on merge. See the module docstring for why this protects the CI
    Plan job, not just the reader."""
    ctx = json.load(open(_CDK_JSON, encoding="utf-8"))["context"]
    assert NATIVE_EMBED_CONTEXT_KEY in ctx, f"{NATIVE_EMBED_CONTEXT_KEY} must be declared in cdk/cdk.json"
    assert ctx[NATIVE_EMBED_CONTEXT_KEY] is False, (
        "Native social embeds are OFF until the owner flips this AND runs " "`cdk deploy LifePlatformWeb` in the same sitting (ADR-149)."
    )


# ══════════════════════════════════════════════════════════════════════════
# 4. Both CSP blocks reach the policy through the builder
# ══════════════════════════════════════════════════════════════════════════


def test_web_stack_has_no_hand_written_csp_literal_left():
    src = open(_WEB_STACK, encoding="utf-8").read()
    assert "default-src" not in src, (
        "A CSP string literal reappeared in web_stack.py. Both response-headers "
        "policies must call stacks.csp.build_site_csp() — that is what makes a "
        "one-sided edit impossible (#1678 sign-off condition)."
    )


def test_web_stack_calls_the_builder_once_per_policy():
    """AST, not grep — the source also *mentions* build_site_csp() in comments,
    and a comment is not a call site."""
    tree = ast.parse(open(_WEB_STACK, encoding="utf-8").read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "build_site_csp"]
    assert len(calls) == 3, f"expected exactly 3 build_site_csp() call sites (amj + subdomain + legacy, #3048), found {len(calls)}"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert kwargs == {
            "connect_src",
            "hardened_scripts",
            "native_social_embeds",
        }, f"call site passes {kwargs} — all three args are required at every site (#3048)"


def test_web_stack_reads_the_flag_once_and_shares_it():
    """One read, one variable, both policies — so the two can't be given
    different values by a later edit."""
    src = open(_WEB_STACK, encoding="utf-8").read()
    assert len(re.findall(r"native_embeds_enabled\(", src)) == 1
    assert len(re.findall(r"native_social_embeds=native_embeds\b", src)) == 3  # amj + subdomain + legacy (#3048)


# ══════════════════════════════════════════════════════════════════════════
# 5. The site stays on facades until the CSP is actually deployed
# ══════════════════════════════════════════════════════════════════════════

_IFRAME_SRC_RE = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
_JS_IFRAME_RE = re.compile(r"""createElement\(\s*["']iframe["']\s*\)""", re.IGNORECASE)


def _site_files(*exts):
    for dirpath, dirnames, filenames in os.walk(os.path.join(_ROOT, "site")):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", "legacy"}]
        for name in filenames:
            if name.endswith(exts):
                yield os.path.join(dirpath, name)


# The floor for the two extensions the offender sweeps below actually scan.
# #2790: a bare os.walk that silently yields zero files (site/ renamed, root
# derivation broken, CI checkout shallow-cloned wrong) makes both sweeps pass
# vacuously — `assert not offenders` is trivially true over an empty list.
# These minimums are well under the live counts (93 .html / 60 .js as of
# 2026-08-19) so ordinary content growth/shrinkage never flakes this floor.
_MIN_SITE_HTML_FILES = 50
_MIN_SITE_JS_FILES = 20


def _floored_site_files(*exts, minimum):
    """Materialize `_site_files(*exts)` and assert the surface is real before
    any offender sweep is allowed to trust it (in the style of
    test_pacific_today_guard_2414.py:195-209 — GUARD THE SET, NOT THE INSTANCE)."""
    files = list(_site_files(*exts))
    assert len(files) >= minimum, (
        f"site file surface for {exts} yielded only {len(files)} files (expected "
        f">= {minimum}) — the os.walk root may have moved, been renamed, or gone "
        "missing; the offender sweeps below cannot be trusted over an empty walk (#2790)"
    )
    return files


def test_site_html_surface_is_derived_and_nonempty():
    files = _floored_site_files(".html", minimum=_MIN_SITE_HTML_FILES)
    rels = {os.path.relpath(p, _ROOT) for p in files}
    for expected in ("site/index.html", "site/cockpit/index.html", "site/coaching/index.html"):
        assert expected in rels, f"derived site HTML surface lost {expected}"


def test_site_js_surface_is_derived_and_nonempty():
    files = _floored_site_files(".js", minimum=_MIN_SITE_JS_FILES)
    rels = {os.path.relpath(p, _ROOT) for p in files}
    assert "site/assets/js/ask.js" in rels, "derived site JS surface lost site/assets/js/ask.js"


def test_no_site_iframe_points_at_a_non_allowlisted_origin():
    """A third-party `<iframe>` whose origin is not in NATIVE_EMBED_FRAME_SRC is
    blocked by the CSP and renders as a blank box. Relative/same-origin frames
    are fine."""
    offenders = []
    for path in _floored_site_files(".html", minimum=_MIN_SITE_HTML_FILES):
        for src in _IFRAME_SRC_RE.findall(open(path, encoding="utf-8", errors="ignore").read()):
            if not src.lower().startswith(("http://", "https://")):
                continue  # relative → same-origin → covered by default-src 'self'
            if not any(src.startswith(origin + "/") or src == origin for origin in NATIVE_EMBED_FRAME_SRC):
                offenders.append(f"{os.path.relpath(path, _ROOT)} → {src}")
    assert not offenders, "iframe origins outside the ADR-149 allow-list:\n  " + "\n  ".join(offenders)


def test_site_js_builds_no_iframes_yet():
    """The facade card (thumbnail + caption + link-out) is the shipped pattern and
    the documented rollback target. When #1674's native-player follow-up lands, it
    lands WITH the owner's `cdk deploy LifePlatformWeb` — update this test then,
    deliberately, not as a drive-by."""
    offenders = [
        os.path.relpath(p, _ROOT)
        for p in _floored_site_files(".js", minimum=_MIN_SITE_JS_FILES)
        if _JS_IFRAME_RE.search(open(p, encoding="utf-8", errors="ignore").read())
    ]
    assert not offenders, (
        "site JS now creates an <iframe>. Native players require ADR-149's CSP to be "
        "DEPLOYED (cdk deploy LifePlatformWeb) — otherwise the frame is blocked and the "
        "reader sees a blank box. Offenders:\n  " + "\n  ".join(offenders)
    )
