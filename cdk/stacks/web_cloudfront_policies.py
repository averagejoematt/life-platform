"""cdk/stacks/web_cloudfront_policies.py — CloudFront cache + origin-request policies
for the `/api/*` behaviours (#1221).

WHY THIS MODULE EXISTS
======================
`lambdas/common/client_ip.py` derives a caller's rate-limit identity from
``CloudFront-Viewer-Address`` — a header CloudFront sets itself from the TCP peer
address, which a client cannot forge. **That header was never reaching the origin.**
All 21 cache behaviours used legacy ``ForwardedValues``, which forwards only the
headers it names, and ``CloudFront-Viewer-Address`` was not one of them. So the
helper always fell through to ``X-Forwarded-For`` — which THIS distribution forwards
unchanged from the client, making it attacker-controlled in every position — and
every IP-gated write (subscribe, votes, follows, nudges, checkins, board_ask) was
evadable by rotating one header.

``ForwardedValues`` and ``OriginRequestPolicy`` are **mutually exclusive** on a cache
behaviour, so fixing this is a migration, not a flag flip.

THE RULE THIS MODULE EXISTS TO ENFORCE
======================================
**``CloudFront-Viewer-Address`` belongs in the ORIGIN REQUEST policy and MUST NEVER
appear in a CACHE policy.**

Under legacy ``ForwardedValues`` one header list did both jobs: it decided what
reached the origin *and* what went into the cache key. Policies split those. The
header is unique per viewer, so putting it in a cache key turns one cached object
into one-per-client. `/api/*` caches at ``default_ttl=300`` and is the busiest read
path on the site; shattering that key would be a latency and cost regression shipped
in the name of a security fix. There is a guard for exactly this:
``tests/test_cloudfront_viewer_address_policies_1221.py``.

WHAT IS PRESERVED, EXACTLY
==========================
Measured from the live distribution (E3S424OXQZ8NBE) before the migration:

    behaviour                 TTL min/def/max   qs      headers
    /api/subscribe*           0/0/0             True    Origin, Content-Type
    /api/verify_subscriber    0/0/0             True    Origin, Content-Type
    /api/board_ask            0/0/0             False   Origin, Content-Type
    /api/explain              0/0/0             False   Origin, Content-Type, X-Subscriber-Token
    /api/ask                  0/0/0             False   Origin, Content-Type, X-Subscriber-Token
    /api/*                    0/300/3600        True    Origin, Content-Type

**A `cdk diff` that changes any TTL is a bug, not a detail.**

Two policies of each kind, and why not fewer:

* ``api_no_cache`` — TTL 0/0/0 for the five write paths. Their cache key is
  deliberately empty: with ``max_ttl=0`` CloudFront never caches, so the key is
  unobservable and carrying the old header list into it would be cargo cult.
* ``api_default_cache`` — reproduces `/api/*`'s 0/300/3600 with query strings and
  ``Origin``/``Content-Type`` in the key, byte for byte.
* ``api_origin_qs`` / ``api_origin_no_qs`` — identical header allow-lists, differing
  only in query-string forwarding, because three behaviours forwarded query strings
  to the origin and three did not. Collapsing them would silently start sending query
  strings to the AI endpoints.

The header allow-list is a **superset** (it includes ``X-Subscriber-Token`` even for
behaviours that never forwarded it). That is safe in an *origin request* policy —
forwarding a header the viewer did not send is a no-op — and it would NOT be safe in
a cache policy, which is the whole distinction above.

``OriginRequestHeaderBehavior.all()`` is deliberately NOT used: it forwards ``Host``,
and every origin here is a Lambda Function URL, which routes on its own host and
breaks when the viewer's is forwarded. That is what AWS's own
``AllViewerExceptHostHeader`` managed policy exists to avoid; an explicit allow-list
is the same idea, narrower.
"""

from aws_cdk import Duration, aws_cloudfront as cloudfront

# The one header this whole module exists to deliver. Named once so the guard test
# can assert it appears in every origin-request policy and in NO cache policy.
VIEWER_ADDRESS_HEADER = "CloudFront-Viewer-Address"

# Forwarded to the origin on every /api/* behaviour. Superset by design (see docstring).
_API_ORIGIN_HEADERS = ("Origin", "Content-Type", "X-Subscriber-Token", VIEWER_ADDRESS_HEADER)

# The /api/* cache key, preserved verbatim from the pre-migration ForwardedValues.
_API_CACHE_KEY_HEADERS = ("Origin", "Content-Type")


def build_api_policies(scope) -> dict:
    """Create the four policies and return them keyed for the behaviour table.

    Returns a dict with `no_cache`, `default_cache`, `origin_qs`, `origin_no_qs`.
    """
    no_cache = cloudfront.CachePolicy(
        scope,
        "ApiNoCachePolicy",
        cache_policy_name="life-platform-api-no-cache",
        comment="#1221: TTL 0 for the /api write paths. Empty cache key — max_ttl=0 means nothing caches.",
        min_ttl=Duration.seconds(0),
        default_ttl=Duration.seconds(0),
        max_ttl=Duration.seconds(0),
        header_behavior=cloudfront.CacheHeaderBehavior.none(),
        query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
        cookie_behavior=cloudfront.CacheCookieBehavior.none(),
    )

    default_cache = cloudfront.CachePolicy(
        scope,
        "ApiDefaultCachePolicy",
        cache_policy_name="life-platform-api-default-cache",
        comment="#1221: reproduces /api/*'s pre-migration 0/300/3600 cache key exactly. NO viewer-address here.",
        min_ttl=Duration.seconds(0),
        default_ttl=Duration.seconds(300),
        max_ttl=Duration.seconds(3600),
        header_behavior=cloudfront.CacheHeaderBehavior.allow_list(*_API_CACHE_KEY_HEADERS),
        query_string_behavior=cloudfront.CacheQueryStringBehavior.all(),
        cookie_behavior=cloudfront.CacheCookieBehavior.none(),
    )

    origin_qs = cloudfront.OriginRequestPolicy(
        scope,
        "ApiOriginRequestQsPolicy",
        origin_request_policy_name="life-platform-api-origin-qs",
        comment="#1221: forwards CloudFront-Viewer-Address (+ query strings) to the origin.",
        header_behavior=cloudfront.OriginRequestHeaderBehavior.allow_list(*_API_ORIGIN_HEADERS),
        query_string_behavior=cloudfront.OriginRequestQueryStringBehavior.all(),
        cookie_behavior=cloudfront.OriginRequestCookieBehavior.none(),
    )

    origin_no_qs = cloudfront.OriginRequestPolicy(
        scope,
        "ApiOriginRequestNoQsPolicy",
        origin_request_policy_name="life-platform-api-origin-no-qs",
        comment="#1221: forwards CloudFront-Viewer-Address; query strings withheld, as before the migration.",
        header_behavior=cloudfront.OriginRequestHeaderBehavior.allow_list(*_API_ORIGIN_HEADERS),
        query_string_behavior=cloudfront.OriginRequestQueryStringBehavior.none(),
        cookie_behavior=cloudfront.OriginRequestCookieBehavior.none(),
    )

    return {
        "no_cache": no_cache,
        "default_cache": default_cache,
        "origin_qs": origin_qs,
        "origin_no_qs": origin_no_qs,
    }
