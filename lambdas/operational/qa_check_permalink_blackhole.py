"""qa_check_permalink_blackhole.py — published permalinks must never be redirect sources (#3284).

The 2026-08-27 bug bash found the live cycle's Week 1 chronicle installment
unreachable at every URL: redirects.map (and the CloudFront v4-redirects
function generated 1:1 from it) still carried the #1805-era
`/journal/posts/week-04/ -> /story/journal/` 301, registered when week-04 was a
tombstoned orphan of the PREVIOUS cycle — and never removed when the new cycle
published a real article at the same slug. Every reader path (posts.json cards,
/story/chronicle/ static links, sitemap, semantic-recall citations) advertised
the URL; the edge 301'd all of them to a hub that does not contain the article.

Worse, the one redirect check that existed (redirect_spotcheck, #1430) verifies
that a mapped entry 301s WITH the declared Location — it *confirmed* the
blackhole as correct behaviour. The gap was the cross-check in the other
direction: **no URL published in the live /journal/posts.json may also be a
redirect source.** This module is that cross-check, in two legs:

  map leg  — every live posts.json `url` vs the redirects.map the bundle
             stages at its root (deploy/build_bundle.py — the same copy
             redirect_spotcheck reads). An overlap means the REPO still arms
             the 301: the register_permalink_redirect ratchet re-armed (its
             unregister pair now exists in deploy/restart_chronicle_handler.py,
             but this is the guard on the SET, not on one call site).
  live leg — every live posts.json `url` fetched with redirect-following
             DISABLED (redirect_spotcheck's verified opener pattern): a
             301/308 observed at the edge fails even when the repo map is
             clean, i.e. the regenerated CloudFront function body has not been
             re-published yet (an owner action — gate:owner on #3284). This
             leg is EXPECTED RED between the #3284 merge and Matthew's
             function publish, and goes green at publish.

Nightly, not weekly: the surface is the handful of currently-published posts
(not the 114-entry legacy map), so there is no edge-hammering concern, and a
freshly published installment landing on an armed 301 should red the NEXT
morning's sweep, not up to a week later.

Purely deterministic — no LLM/Bedrock, never budget-paused. Own module (the
module-size ceiling split idiom, #1665/#1944/#1972/#1993):
`assess_permalink_blackhole` is the pure assessor tests exercise offline;
`check_published_permalink_reachable` is the live wrapper qa_smoke_lambda
wires in.
"""

import json
import urllib.error
import urllib.request

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL
from operational.redirect_spotcheck import EXPECTED_REDIRECT_CODES, build_no_redirect_opener, load_redirects_map


def published_post_urls(posts_payload):
    """The url of every published post in a /journal/posts.json payload.
    Malformed shapes yield [] — the caller reports emptiness honestly."""
    if not isinstance(posts_payload, dict) or not isinstance(posts_payload.get("posts"), list):
        return []
    return [str(p["url"]) for p in posts_payload["posts"] if isinstance(p, dict) and p.get("url")]


def assess_permalink_blackhole(post_urls, redirect_entries):
    """Pure map-leg assessor: which published permalinks are ALSO redirect
    sources in the given (old, new) redirect entries. Returns a list of
    human-readable findings — empty means no overlap."""
    sources = {old: new for old, new in redirect_entries}
    return [
        f"{url} is published in posts.json AND a redirect source (-> {sources[url]}) — the 301 blackholes it (#3284)"
        for url in post_urls
        if url in sources
    ]


def probe_live_permalinks(post_urls, opener=None, base_url=None, timeout=10):
    """Live-leg probe: GET each permalink with redirect-following disabled.
    Returns (failures, errors): a 301/308 observed at the edge is a failure
    (the published CloudFront function still redirects it); any other
    non-redirect HTTP status passes THIS check (page-health sweeps own 404s);
    transport problems are errors (visible, fail-soft — never a verdict)."""
    if opener is None:
        opener = build_no_redirect_opener()
    base = (base_url or SITE_BASE_URL).rstrip("/")
    failures, errors = [], []
    for path in post_urls:
        try:
            opener.open(base + path, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in EXPECTED_REDIRECT_CODES:
                location = e.headers.get("Location")
                failures.append(
                    f"{path} -> HTTP {e.code} to {location!r} at the edge — a published permalink is being "
                    f"redirected (publish the regenerated v4-redirects function, #3284)"
                )
        except Exception as e:
            errors.append(f"{path} -> request error (fail-soft): {str(e)[:120]}")
    return failures, errors


def check_published_permalink_reachable():
    """CHECK — #3284: no URL served in the live /journal/posts.json may be a
    redirect source, in the bundled redirects.map (map leg) or at the live
    edge (live leg). Fail-soft only on transport; a real overlap or a live
    301 on a published permalink is an ALARMED content-truth FAIL — it means
    the flagship narrative artifact is unreachable for every reader."""
    check = Check("permalink_blackhole:published_vs_redirects", "Reader Truth", CONTENT_TRUTH)
    try:
        req = urllib.request.Request(SITE_BASE_URL + "/journal/posts.json", headers={"User-Agent": "life-platform-qa-smoke"})
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 — fixed trusted host
            posts_payload = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return [check.warn(f"/journal/posts.json fetch failed (fail-soft): {str(e)[:120]}")]

    post_urls = published_post_urls(posts_payload)
    if not post_urls:
        return [check.ok("no published posts in /journal/posts.json — nothing to cross-check (honest empty, e.g. fresh genesis)")]

    checks = []
    try:
        map_findings = assess_permalink_blackhole(post_urls, load_redirects_map())
    except FileNotFoundError as e:
        # Bundle didn't stage redirects.map — a packaging regression, not a
        # redirect regression (same posture as check_redirect_spotcheck #1430).
        # A fresh Check instance: the verdict Check below must not be pre-mutated.
        map_findings = []
        checks.append(
            Check("permalink_blackhole:map", "Reader Truth", CONTENT_TRUTH).warn(f"redirects.map not found (fail-soft): {str(e)[:150]}")
        )

    live_failures, live_errors = probe_live_permalinks(post_urls)
    for err in live_errors:
        checks.append(Check("permalink_blackhole:fetch", "Reader Truth", CONTENT_TRUTH).warn(err))

    findings = map_findings + live_failures
    if findings:
        checks.append(
            check.fail(f"{len(findings)} blackholed permalink(s) across {len(post_urls)} published post(s): " + "; ".join(findings[:5]))
        )
    else:
        checks.append(
            check.ok(f"all {len(post_urls)} published permalink(s) clear of redirects.map and serve without a redirect at the edge")
        )
    return checks
