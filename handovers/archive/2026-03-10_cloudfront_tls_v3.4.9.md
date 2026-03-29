# Handover: CloudFront TLS Fix — v3.4.9
**Date:** 2026-03-10  
**Session goal:** Fix ERR_CERT_COMMON_NAME_INVALID on all three web properties

---

## Problem
All three URLs (dash, blog, buddy) showing browser TLS error:
> "its security certificate is from *.cloudfront.net"

## Root Cause
`cdk/stacks/web_stack.py` had `CERT_ARN_* = None` for all three distributions — the
`viewer_certificate` property was never added to the `CfnDistribution` definitions.
When LifePlatformWeb deployed during PROD-1, it created distributions without TLS certs,
causing CloudFront to fall back to its default `*.cloudfront.net` certificate.

## Fix
Added `ViewerCertificateProperty` to all three `CfnDistribution` definitions in `web_stack.py`:
- `ssl_support_method="sni-only"` (standard for custom domains)
- `minimum_protocol_version="TLSv1.2_2021"`
- ACM cert ARNs populated from `aws acm list-certificates --region us-east-1`

Deploy: `npx cdk deploy LifePlatformWeb --require-approval never`

CloudFront propagation: ~3–5 minutes after deploy completes.

---

## Lesson Learned
Add to INCIDENT_LOG: WebStack was deployed without `viewer_certificate` during PROD-1.
The `CERT_ARN_* = None` placeholder was never followed up on after the initial CDK import.
**Pattern:** Any CDK construct with a `None` placeholder for a security property is a latent P1.

---

## Platform State (end of session)
All items from the backlog are now closed. Platform is clean.

| Item | Status |
|------|--------|
| COST-B secrets consolidation | ✅ Done — $1.20/mo saved |
| COST-A alarm consolidation | ✅ Done — $4.60/mo saved |
| Habitify secret | ✅ Done — keys already in ingestion-keys |
| CloudFront TLS | ✅ Fixed — v3.4.9 |

**Next session:** Brittany weekly email feature build.

---

## Pending (calendar items only)
| Item | When |
|------|------|
| `life-platform/api-keys` permanent deletion | ~2026-04-07 (auto, recovery window) |
| `life-platform/todoist`/`notion`/`dropbox` permanent deletion | ~2026-04-10 (auto) |
| SIMP-1 MCP tool usage audit | ~2026-04-08 (needs 30 days data) |
