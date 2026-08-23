"""
cdk/stacks/csp.py — the Content-Security-Policy for every public averagejoematt.com
surface, in one place (ADR-149, #1678).

Why this is its own module and not a helper inside `web_stack.py`:

  1. **One source, two policies.** Two CloudFront ResponseHeadersPolicies carry a
     CSP — `life-platform-amj-security-headers` (the averagejoematt.com
     distribution) and `life-platform-subdomain-security-headers` (dash/blog/
     buddy). They used to be two independently-maintained string literals, which
     made "edit one, forget the other" the single likeliest way to ship an
     inconsistent public-surface policy. That is exactly the failure mode the
     #1678 owner sign-off called out. A builder makes the one-sided edit
     structurally impossible.

  2. **The guard must run offline.** CI's test job installs pytest + boto3 only —
     NOT `aws-cdk-lib`. A test that reaches the CSP through `web_stack.py` would
     ImportError at collection and red the whole suite. This module imports
     nothing but the standard library, so `tests/test_csp_native_embeds_1678.py`
     can pin the policy everywhere it runs.

Deploy surface: CloudFront response-headers policies ship ONLY via
`cdk deploy LifePlatformWeb` (us-east-1). CI deploys Lambda code, never CDK — so
editing this file changes nothing in production until someone runs that command.

#3048 (DIL-015, 2026-08-23): the main-domain policy dropped 'unsafe-inline' and
cdn.jsdelivr.net from script-src (SCRIPT_SRC_HARDENED below). NB the Plan-job
rule the #1678 block explains still applies: this change touches
AWS::CloudFront::ResponseHeadersPolicy, so merging it reds CI's Plan gate until
`cdk deploy LifePlatformWeb` runs — merge and deploy belong to the same sitting.
"""

# ══════════════════════════════════════════════════════════════════════════════
# ADR-149 (#1678) — the Content-Security-Policy is BUILT, not hand-copied.
#
# Two CloudFront ResponseHeadersPolicies carry a CSP: the main-domain one
# (`life-platform-amj-security-headers`, attached to the averagejoematt.com
# distribution) and the subdomain one (`life-platform-subdomain-security-headers`,
# attached to dash/blog/buddy). They were two independently-maintained string
# literals, which made "edit one, forget the other" the single likeliest way to
# ship an inconsistent public-surface policy — the failure mode the #1678 owner
# sign-off named explicitly. One builder makes that edit structurally impossible.
#
# NATIVE SOCIAL EMBEDS are OFF by default and the OFF output is byte-identical to
# what is live today, so merging this file produces a ZERO cdk diff. That is
# load-bearing, not cosmetic: ci-cd.yml's Plan job greps `cdk diff` for
# /iam|policy|role|permission/i and **exits 1** on a match. A CSP change touches
# `AWS::CloudFront::ResponseHeadersPolicy` — the word "Policy" — so a merged-but-
# undeployed widening would red the Plan job and strand every later CI deploy
# (the R8-ST6 class). Flipping the flag and running `cdk deploy LifePlatformWeb`
# therefore belong to the SAME sitting.
# ══════════════════════════════════════════════════════════════════════════════

# The complete set of third-party origins the owner approved for `frame-src`
# (issue #1678, sign-off 2026-08-02: "exactly youtube-nocookie.com … never a
# blanket https:, never a second origin added without returning here").
# `www.` only — YouTube's privacy-enhanced embed URL is
# https://www.youtube-nocookie.com/embed/<id>; the apex is not used and is not
# listed. Adding ANY entry here is a new owner decision, not a code change:
# tests/test_csp_native_embeds_1678.py pins this tuple.
NATIVE_EMBED_FRAME_SRC = ("https://www.youtube-nocookie.com",)

# CDK context key. Declared `false` in cdk/cdk.json so the mechanism is inert on
# merge and stays inert across every subsequent deploy until the owner edits that
# one line. A context value can arrive as a JSON bool (cdk.json) or as a string
# (`-c native_social_embeds=true` on the CLI), hence the coercion below.
NATIVE_EMBED_CONTEXT_KEY = "native_social_embeds"

# ── #3048 (DIL-015): the script-src profiles ─────────────────────────────────
#
# HARDENED — the production averagejoematt.com surface. No 'unsafe-inline'
# (every inline block was extracted to real /assets/js/ files or converted to
# non-executable type="application/json" data islands) and no third-party CDN
# (the only cdn.jsdelivr.net consumer was the a11y harness's axe-core, which is
# vendored at tests/vendor/axe.min.js and injected via CDP, outside the page
# CSP). Adding ANY origin or source keyword back here is an owner decision —
# tests/test_csp_hardening_3048.py pins this string.
SCRIPT_SRC_HARDENED = "script-src 'self'"
#
# COMPAT — the pre-#3048 policy, kept ONLY for surfaces whose HTML cannot be
# retrofitted: /legacy/* (the preserved old site, served verbatim from S3) and
# the dash/blog/buddy subdomain distributions (out of #3048's scope). Never
# attach this to the main-domain default behavior.
SCRIPT_SRC_COMPAT = "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"

# The main-domain policy's connect-src, hoisted here (from web_stack.py) so the
# expected production CSP is buildable without aws-cdk-lib — scripts/
# expected_csp.py derives the smoke test's expected header from this module.
AMJ_CONNECT_SRC = "'self' https://averagejoematt.com"


def native_embeds_enabled(raw_context_value) -> bool:
    """Coerce a CDK context value to the embed flag. Anything unrecognised is OFF.

    Fail-closed on purpose: a typo in cdk.json or on the CLI must not widen the
    public CSP. The only values that turn it on are an explicit JSON `true` or one
    of the usual truthy strings.
    """
    if isinstance(raw_context_value, bool):
        return raw_context_value
    if isinstance(raw_context_value, str):
        return raw_context_value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def build_site_csp(*, connect_src: str, hardened_scripts: bool, native_social_embeds: bool = False) -> str:
    """Assemble the CSP header value for a CloudFront ResponseHeadersPolicy.

    `connect_src` and `hardened_scripts` are the only inputs that legitimately
    differ between policies (the subdomains additionally reach the wildcard
    subdomain origin). `hardened_scripts` is REQUIRED — every call site chooses
    its script-src profile explicitly (#3048): True → SCRIPT_SRC_HARDENED (the
    production main-domain surface), False → SCRIPT_SRC_COMPAT (/legacy/* and
    the subdomain distributions only).

    When `native_social_embeds` is False the returned string is byte-identical to
    the policy deployed today — the OFF path is a pure refactor.

    Note there is deliberately NO `media-src`. The approval envelope covers it,
    but a `<iframe>` player needs only `frame-src`: the media the YouTube player
    fetches is governed by the *iframe document's* CSP, not ours. Adding a
    third-party `media-src` origin with no consumer would be strictly wider than
    the feature requires. `media-src` stays on the `default-src 'self'` fallback.
    See ADR-149.
    """
    directives = [
        "default-src 'self'",
        # #3048 (DIL-015): scripts are hardened on the production surface —
        # see the profile constants above. style-src keeps 'unsafe-inline'
        # (inline <style>/style= attributes are widespread and out of #3048's
        # scope; scripts were the injection-foothold risk the issue closes).
        SCRIPT_SRC_HARDENED if hardened_scripts else SCRIPT_SRC_COMPAT,
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        f"connect-src {connect_src}",
        "font-src 'self' data:",
    ]
    if native_social_embeds:
        directives.append("frame-src " + " ".join(NATIVE_EMBED_FRAME_SRC))
    directives += [
        # frame-ancestors governs who may frame US; it is unrelated to frame-src
        # (who WE may frame) and stays 'none' in both modes.
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    return "; ".join(directives)
