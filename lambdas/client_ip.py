"""lambdas/client_ip.py — the ONE client-IP extraction helper.

Shipped in every function bundle (#781), so both the site-api social handlers
(web/site_api_social.py) and the subscriber Function URL (web/email_subscriber_lambda.py)
key their per-IP rate limits off the identical, correct derivation.

Security (#1221): the `/api/*` surface is CloudFront-fronted and WAF was removed
2026-06, so there is NO upstream sanitization of the forwarded chain. CloudFront
appends the edge-observed viewer IP as the LAST entry of `X-Forwarded-For`; every
earlier entry is supplied by the client and is therefore spoofable. Keying a
rate-limit bucket on the LEFTMOST entry (the prior bug here and in the subscriber
lambda) lets an attacker forge an arbitrary per-IP bucket per request and evade
every IP-gated write (subscribe, votes, follows, nudges, checkins, board_ask).
We MUST take the last (edge-appended) hop.

`requestContext…sourceIp` (the CloudFront edge IP for the API-Gateway path, or the
direct caller for a Function URL) is the ONLY fallback, used solely when the
`X-Forwarded-For` header is absent.
"""


def extract_client_ip(event: dict, default: str = "unknown") -> str:
    """Return the CloudFront edge-observed client IP for rate-limiting.

    Takes the LAST `X-Forwarded-For` hop (the entry CloudFront appends and the
    client cannot forge). Each hop is whitespace-stripped. Falls back to
    `requestContext.http.sourceIp` / `requestContext.identity.sourceIp` only when
    no `X-Forwarded-For` header is present, then to `default`.
    """
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    hops = [hop.strip() for hop in (headers.get("x-forwarded-for") or "").split(",") if hop.strip()]
    if hops:
        return hops[-1]
    ctx = event.get("requestContext") or {}
    return ctx.get("http", {}).get("sourceIp") or ctx.get("identity", {}).get("sourceIp") or default
