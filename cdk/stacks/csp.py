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


def build_site_csp(*, connect_src: str, native_social_embeds: bool = False) -> str:
    """Assemble the CSP header value for a CloudFront ResponseHeadersPolicy.

    `connect_src` is the only directive that legitimately differs between the two
    policies (the subdomains additionally reach the wildcard subdomain origin).

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
        # SEC-05: 'unsafe-inline' kept intentionally — all JS/CSS is first-party
        # and server-rendered with no user-controlled content. Nonce-based CSP
        # would require per-request Lambda changes for a static S3 site.
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
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
