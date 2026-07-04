"""
WebStack — CloudFront distributions for all three web properties.

Distributions (all import existing; CDK manages config going forward):
  EM5NPX6NJN095  dash.averagejoematt.com    → S3 /dashboard  (Life Platform Dashboard)
  E1JOC1V6E6DDYI blog.averagejoematt.com    → S3 /blog       (The Measured Life Blog)
  ETTJ44FT0Z4GO  buddy.averagejoematt.com   → S3 /buddy      (Buddy Accountability Page)

All distributions:
  - Origin: matthew-life-platform.s3-website-us-west-2.amazonaws.com (S3 website endpoint)
  - Viewer protocol: redirect-to-https
  - PriceClass: PriceClass_100

Note: ACM certificates are in us-east-1 (required for CloudFront). They are
referenced by ARN, not managed by this stack. CDK WebStack must be deployed
in us-east-1 for ACM OR use the us-west-2 env with pre-existing cert ARNs.
Since we're importing existing distributions, we reference existing cert ARNs.

CDK does not own the S3 bucket origin (in LifePlatformCore). Origin is wired
via bucket website URL, not S3 bucket construct reference, so no cross-stack
dependency is needed.

ImportNote: CloudFront L2 import is via Distribution.from_distribution_attributes().
Since CDK cannot fully reconstruct L2 CloudFront from attributes alone (L2 import
is not supported for CloudFront), we use L1 CfnDistribution for import.
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudwatch as cloudwatch,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct

from stacks import role_policies as rp
from stacks.constants import (
    ACCT,
    CF_AUTH_VERSION_ARN,
    PRIVACY_MODE,
    REGION,
    S3_BUCKET as _CONSTANTS_BUCKET,  # CONF-01
)
from stacks.lambda_helpers import create_platform_lambda

BUCKET = _CONSTANTS_BUCKET

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
ALERTS_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

# ACM certificate for averagejoematt.com (us-east-1 — required for CloudFront)
# REQUEST THIS FIRST: see deploy/request_amj_cert.sh
# Then update this ARN and run: cdk deploy LifePlatformWeb
CERT_ARN_AMJ = "arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-e7d0-4403-a64c-c235bc57084c"

# S3 website endpoint (not the REST endpoint — required for static website hosting)
S3_WEBSITE_DOMAIN = f"{BUCKET}.s3-website-{REGION}.amazonaws.com"

# Existing ACM certificate ARNs (us-east-1, required for CloudFront)
CERT_ARN_DASH = "arn:aws:acm:us-east-1:205930651321:certificate/8e560416-e5f6-4f87-82a6-17b5e7df25d0"
CERT_ARN_BLOG = "arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2"
CERT_ARN_BUDDY = "arn:aws:acm:us-east-1:205930651321:certificate/cfaf8364-1353-48d3-8522-6892a5aef680"


def _s3_origin(origin_path: str) -> dict:
    """CloudFormation Origin config for S3 static website with origin path."""
    return {
        "domainName": S3_WEBSITE_DOMAIN,
        "id": "S3WebsiteOrigin",
        "originPath": origin_path,
        "customOriginConfig": {
            "httpPort": 80,
            "httpsPort": 443,
            "originProtocolPolicy": "http-only",  # S3 website endpoint only supports HTTP
        },
    }


class WebStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, table=None, bucket=None, dlq=None, alerts_topic=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Resolve shared resources (accept injected or import by name)
        local_table = table or dynamodb.Table.from_table_name(self, "LifePlatformTable", "life-platform")
        local_bucket = bucket or s3.Bucket.from_bucket_name(self, "LifePlatformBucket", BUCKET)
        local_dlq = dlq or sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_alerts = alerts_topic or sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ══════════════════════════════════════════════════════════════
        # Phase 2.3 (2026-05-16): Shared security headers policy for all
        # subdomain distributions (dash, blog, buddy). Originally only the
        # main averagejoematt.com distribution had this (R17-15 added below).
        # Hoisted up here so dash/blog/buddy can reference it via .ref.
        # ══════════════════════════════════════════════════════════════
        subdomain_security_headers = cloudfront.CfnResponseHeadersPolicy(
            self,
            "SubdomainSecurityHeadersPolicy",
            response_headers_policy_config=cloudfront.CfnResponseHeadersPolicy.ResponseHeadersPolicyConfigProperty(
                name="life-platform-subdomain-security-headers",
                comment="CSP + HSTS + X-Frame-Options for dash/blog/buddy subdomains",
                security_headers_config=cloudfront.CfnResponseHeadersPolicy.SecurityHeadersConfigProperty(
                    content_security_policy=cloudfront.CfnResponseHeadersPolicy.ContentSecurityPolicyProperty(
                        # Dashboard pages fetch only relative paths (/public_stats.json,
                        # /api/*) — 'self' is sufficient. Allow main domain too for any
                        # cross-subdomain inclusion (e.g., shared site_api endpoints).
                        content_security_policy=(
                            "default-src 'self'; "
                            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                            "style-src 'self' 'unsafe-inline'; "
                            "img-src 'self' data: https:; "
                            "connect-src 'self' https://averagejoematt.com https://*.averagejoematt.com; "
                            "font-src 'self' data:; "
                            "frame-ancestors 'none'; "
                            "base-uri 'self'; "
                            "form-action 'self'"
                        ),
                        override=True,
                    ),
                    frame_options=cloudfront.CfnResponseHeadersPolicy.FrameOptionsProperty(
                        frame_option="DENY",
                        override=True,
                    ),
                    content_type_options=cloudfront.CfnResponseHeadersPolicy.ContentTypeOptionsProperty(
                        override=True,
                    ),
                    referrer_policy=cloudfront.CfnResponseHeadersPolicy.ReferrerPolicyProperty(
                        referrer_policy="strict-origin-when-cross-origin",
                        override=True,
                    ),
                    strict_transport_security=cloudfront.CfnResponseHeadersPolicy.StrictTransportSecurityProperty(
                        access_control_max_age_sec=31536000,
                        include_subdomains=True,
                        override=True,
                    ),
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Dashboard — dash.averagejoematt.com  (EM5NPX6NJN095)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self,
            "DashboardDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="Life Platform Dashboard — dash.averagejoematt.com",
                aliases=["dash.averagejoematt.com"],
                price_class="PriceClass_100",
                viewer_certificate=cloudfront.CfnDistribution.ViewerCertificateProperty(
                    acm_certificate_arn=CERT_ARN_DASH,
                    ssl_support_method="sni-only",
                    minimum_protocol_version="TLSv1.2_2021",
                ),
                origins=[
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=S3_WEBSITE_DOMAIN,
                        id="S3WebsiteOrigin",
                        origin_path="/dashboard",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="http-only",
                        ),
                    )
                ],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                    response_headers_policy_id=subdomain_security_headers.ref,  # Phase 2.3
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Blog — blog.averagejoematt.com  (E1JOC1V6E6DDYI)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self,
            "BlogDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="The Measured Life Blog — blog.averagejoematt.com",
                aliases=["blog.averagejoematt.com"],
                price_class="PriceClass_100",
                viewer_certificate=cloudfront.CfnDistribution.ViewerCertificateProperty(
                    acm_certificate_arn=CERT_ARN_BLOG,
                    ssl_support_method="sni-only",
                    minimum_protocol_version="TLSv1.2_2021",
                ),
                origins=[
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=S3_WEBSITE_DOMAIN,
                        id="S3WebsiteOrigin",
                        origin_path="/blog",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="http-only",
                        ),
                    )
                ],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                    response_headers_policy_id=subdomain_security_headers.ref,  # Phase 2.3
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Buddy — buddy.averagejoematt.com  (ETTJ44FT0Z4GO)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self,
            "BuddyDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="Buddy Accountability Page — buddy.averagejoematt.com",
                aliases=["buddy.averagejoematt.com"],
                price_class="PriceClass_100",
                viewer_certificate=cloudfront.CfnDistribution.ViewerCertificateProperty(
                    acm_certificate_arn=CERT_ARN_BUDDY,
                    ssl_support_method="sni-only",
                    minimum_protocol_version="TLSv1.2_2021",
                ),
                origins=[
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=S3_WEBSITE_DOMAIN,
                        id="S3WebsiteOrigin",
                        origin_path="/buddy",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="http-only",
                        ),
                    )
                ],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                    response_headers_policy_id=subdomain_security_headers.ref,  # Phase 2.3
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Site API Lambda — life-platform-site-api
        # R17-09 complete: Lambda lives in LifePlatformOperational (us-west-2).
        # Function URL domain is passed via cdk.json context "site_api_fn_url_domain".
        # ══════════════════════════════════════════════════════════════
        _site_api_ctx_domain = self.node.try_get_context("site_api_fn_url_domain")

        # ══════════════════════════════════════════════════════════════
        # Email Subscriber Lambda — BS-03
        # Handles POST /api/subscribe, GET /api/subscribe?action=confirm,
        # GET /api/subscribe?action=unsubscribe
        # Separate origin from site-api: needs POST forwarding + no cache.
        # ══════════════════════════════════════════════════════════════
        # BUG-06: Subscriber DLQ must be us-east-1 (same region as Lambda).
        # The main ingestion DLQ is us-west-2 — not usable here.
        subscriber_dlq = sqs.Queue(
            self,
            "EmailSubscriberDlq",
            queue_name="life-platform-subscriber-dlq",
            retention_period=Duration.days(14),
        )

        subscriber_fn = create_platform_lambda(
            self,
            "EmailSubscriberLambda",
            function_name="email-subscriber",
            source_file="lambdas/web/email_subscriber_lambda.py",
            handler="web.email_subscriber_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=subscriber_dlq,
            alerts_topic=None,
            custom_policies=rp.operational_email_subscriber(),
            # 30s matches the live value (was bumped from 15s — the SES send + DDB
            # write path needs headroom). CDK now reflects reality; no deploy needed,
            # and session_postflight's config-drift check goes green.
            timeout_seconds=30,
            memory_mb=256,
            environment={
                "USER_ID": "matthew",
                "TABLE_NAME": "life-platform",
                "S3_BUCKET": BUCKET,
                "EMAIL_SENDER": "lifeplatform@mattsusername.com",
                "SITE_URL": "https://averagejoematt.com",
                "DYNAMODB_REGION": "us-west-2",  # DDB table is in us-west-2; Lambda runs in us-east-1
                "SES_REGION": "us-west-2",  # SES verified identity is in us-west-2
            },
        )

        subscriber_url = subscriber_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.ALL],
                allowed_headers=["Content-Type"],
            ),
        )

        subscriber_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", subscriber_url.url))

        # Viral defence note: Reserved concurrency removed — us-east-1 account
        # concurrency headroom is limited (cf-auth Lambda@Edge functions already
        # consume reserved slots). Primary defence is CloudFront TTL caching
        # (300s-3600s per endpoint) which caps Lambda invocations regardless of
        # traffic volume. Secondary: add WAF rate limiting after go-live.

        # Function URL (AuthType NONE — CloudFront is the only public caller).
        # No direct URL exposure: CloudFront strips and adds a secret origin header
        # (add that hardening in a follow-up once the cert is live).
        # ══════════════════════════════════════════════════════════════
        # OG Image Lambda — life-platform-og-image (WR-17)
        # Dynamic SVG social preview image with live stats.
        # CDK-managed Lambda with proper Function URL permissions.
        # Handler is `og_image_lambda.handler` (the .mjs sits at lambdas/ root,
        # i.e. the zip root — NOT web/). Was web.og_image_lambda.handler, which
        # MODULE_NOT_FOUND'd on every invoke from 2026-03-20 until 2026-06-08.
        # ══════════════════════════════════════════════════════════════
        og_image_role = iam.Role(
            self,
            "OgImageLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        for stmt in rp.og_image():
            og_image_role.add_to_policy(stmt)

        og_image_fn = _lambda.Function(  # noqa: CDK_HANDLER_ORPHAN
            self,
            "OgImageLambda",
            function_name="life-platform-og-image",
            runtime=_lambda.Runtime.NODEJS_20_X,
            handler="og_image_lambda.handler",  # see block comment above (fixed 2026-06-08)
            code=_lambda.Code.from_asset(
                "../lambdas",
                exclude=[
                    "*.py",
                    "**/*.py",
                    "__pycache__",
                    "**/__pycache__/**",
                    "*.pyc",
                    "**/*.pyc",
                    "*.md",
                    "dashboard/**",
                    "buddy/**",
                    "cf-auth/**",
                    "requirements/**",
                    ".DS_Store",
                ],
            ),
            role=og_image_role,
            timeout=Duration.seconds(10),
            memory_size=256,
        )

        og_image_url = og_image_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )

        og_image_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", og_image_url.url))

        fn_url_domain = _site_api_ctx_domain
        _site_api_fn_url_for_output = f"https://{_site_api_ctx_domain}/"

        # ADR-036 fix: AI Lambda split — separate origin for /api/ask and /api/board_ask
        # Set context "site_api_ai_fn_url_domain" from LifePlatformOperational output SiteApiAiFunctionUrlDomain
        ai_fn_url_domain = self.node.try_get_context("site_api_ai_fn_url_domain") or fn_url_domain

        # ══════════════════════════════════════════════════════════════
        # R17-15: Security headers via CloudFront ResponseHeadersPolicy.
        # Defined here (before amj_dist) so .ref is available in distribution.
        # ══════════════════════════════════════════════════════════════
        amj_security_headers = cloudfront.CfnResponseHeadersPolicy(
            self,
            "AmjSecurityHeadersPolicy",
            response_headers_policy_config=cloudfront.CfnResponseHeadersPolicy.ResponseHeadersPolicyConfigProperty(
                name="life-platform-amj-security-headers",
                security_headers_config=cloudfront.CfnResponseHeadersPolicy.SecurityHeadersConfigProperty(
                    content_security_policy=cloudfront.CfnResponseHeadersPolicy.ContentSecurityPolicyProperty(
                        content_security_policy=(
                            # SEC-05: 'unsafe-inline' kept intentionally — all JS/CSS is
                            # first-party and server-rendered with no user-controlled content.
                            # Nonce-based CSP would require per-request Lambda changes for a
                            # static S3 site. Risk: low (no XSS vectors today). Revisit if
                            # user-generated content is ever added.
                            "default-src 'self'; "
                            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                            "style-src 'self' 'unsafe-inline'; "
                            "img-src 'self' data: https:; "
                            "connect-src 'self' https://averagejoematt.com; "
                            "font-src 'self' data:; "
                            "frame-ancestors 'none'; "
                            "base-uri 'self'; "
                            "form-action 'self'"
                        ),
                        override=True,
                    ),
                    frame_options=cloudfront.CfnResponseHeadersPolicy.FrameOptionsProperty(
                        frame_option="DENY",
                        override=True,
                    ),
                    content_type_options=cloudfront.CfnResponseHeadersPolicy.ContentTypeOptionsProperty(
                        override=True,
                    ),
                    referrer_policy=cloudfront.CfnResponseHeadersPolicy.ReferrerPolicyProperty(
                        referrer_policy="strict-origin-when-cross-origin",
                        override=True,
                    ),
                    strict_transport_security=cloudfront.CfnResponseHeadersPolicy.StrictTransportSecurityProperty(
                        access_control_max_age_sec=31536000,
                        include_subdomains=True,
                        override=True,
                    ),
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # WAF REMOVED (2026-06). `life-platform-amj-waf` was deleted (~−$8/mo;
        # the WebACL no longer exists in us-east-1). Rate limiting is now done
        # in-Lambda (DDB-backed, PG-10) on /api/ask, /api/board_ask, /api/subscribe,
        # plus the cost-governor tier-2 pause — so the CloudFront WAF association
        # is intentionally gone. Do NOT re-add a `web_acl_id` pointing at a
        # non-existent WebACL: cdk deploy would fail associating a dead ARN.
        # (Original SEC-02 WAF: SubscribeRateLimit/GlobalRateLimit/RateLimitAsk/
        # RateLimitBoardAsk — superseded by the in-Lambda limiters.)
        # ══════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════
        # averagejoematt.com — main website
        # Two origins:
        #   1. S3 /site  → static pages (default behaviour)
        #   2. Lambda Function URL  → /api/* (real-time data, TTL-cached)
        # ══════════════════════════════════════════════════════════════

        amj_dist = cloudfront.CfnDistribution(
            self,
            "AmjDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="averagejoematt.com — main website",
                aliases=["averagejoematt.com", "www.averagejoematt.com"],
                price_class="PriceClass_100",
                default_root_object="index.html",
                # Access logging → matthew-life-platform-cf-logs/cf/ (ADR-099 #349).
                # Declared in CDK so any future redeploy preserves it.  The log bucket
                # was created by LifePlatformOperational and is retained independently.
                logging=cloudfront.CfnDistribution.LoggingProperty(
                    bucket="matthew-life-platform-cf-logs.s3.amazonaws.com",
                    prefix="cf/",
                    include_cookies=False,
                ),
                # web_acl_id intentionally omitted — WAF removed (2026-06); see note above.
                viewer_certificate=cloudfront.CfnDistribution.ViewerCertificateProperty(
                    acm_certificate_arn=CERT_ARN_AMJ,
                    ssl_support_method="sni-only",
                    minimum_protocol_version="TLSv1.2_2021",
                ),
                # Three origins
                origins=[
                    # Origin 1: S3 static site (default)
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=S3_WEBSITE_DOMAIN,
                        id="S3SiteOrigin",
                        origin_path="/site",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="http-only",
                        ),
                    ),
                    # Origin 2: og-image Lambda Function URL (dynamic SVG, 1hr cache)
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=og_image_url_domain,
                        id="OgImageOrigin",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="https-only",
                            origin_ssl_protocols=["TLSv1.2"],
                        ),
                    ),
                    # Origin 3: site-api Lambda Function URL (read-only, cacheable)
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=fn_url_domain,
                        id="LambdaApiOrigin",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="https-only",
                            origin_ssl_protocols=["TLSv1.2"],
                        ),
                    ),
                    # Origin 4: site-api-ai Lambda Function URL (AI endpoints, no cache)
                    # ADR-036 fix: separate origin isolates AI concurrency from data endpoints
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=ai_fn_url_domain,
                        id="AiLambdaOrigin",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="https-only",
                            origin_ssl_protocols=["TLSv1.2"],
                        ),
                    ),
                    # Origin 5: email-subscriber Lambda Function URL (write, no cache)
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=subscriber_url_domain,
                        id="SubscriberLambdaOrigin",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="https-only",
                            origin_ssl_protocols=["TLSv1.2"],
                        ),
                    ),
                    # Origin 6: S3 generated content (Lambda-written files)
                    # ADR-046: separate prefix prevents deploy --delete from removing
                    # Lambda-generated files (public_stats, character_stats, OG images, etc.)
                    cloudfront.CfnDistribution.OriginProperty(
                        domain_name=S3_WEBSITE_DOMAIN,
                        id="S3GeneratedOrigin",
                        origin_path="/generated",
                        custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                            http_port=80,
                            https_port=443,
                            origin_protocol_policy="http-only",
                        ),
                    ),
                ],
                # Default behaviour: S3 static pages
                # PRIVACY_MODE: when True, cf-auth Lambda@Edge gates HTML with a cookie.
                # Cookies must be forwarded so the auth cookie reaches the Lambda@Edge.
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3SiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                        cookies=cloudfront.CfnDistribution.CookiesProperty(
                            forward="whitelist" if PRIVACY_MODE else "none",
                            whitelisted_names=["__lp_auth"] if PRIVACY_MODE else None,
                        ),
                    ),
                    default_ttl=0 if PRIVACY_MODE else 3600,  # skip cache while gated so cookie checks always run
                    max_ttl=0 if PRIVACY_MODE else 86400,
                    min_ttl=0,
                    allowed_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"] if PRIVACY_MODE else None,
                    cached_methods=["GET", "HEAD"] if PRIVACY_MODE else None,
                    response_headers_policy_id=amj_security_headers.ref,  # R17-15
                    lambda_function_associations=(
                        [
                            cloudfront.CfnDistribution.LambdaFunctionAssociationProperty(
                                event_type="viewer-request",
                                lambda_function_arn=CF_AUTH_VERSION_ARN,
                                include_body=True,  # POST /__auth body carries the password
                            ),
                        ]
                        if PRIVACY_MODE
                        else None
                    ),
                    # v4 legacy-URL 301s (ADR-071). The cutover left this as a manual
                    # "attach via console" step that never happened — the function sat
                    # published-but-unassociated and every old URL kept serving stale
                    # old-site objects from S3 (found 2026-06-12). CloudFront allows
                    # only one of {Function, Lambda@Edge} per viewer-request, so this
                    # yields to the privacy-gate Lambda when PRIVACY_MODE is on.
                    function_associations=(
                        None
                        if PRIVACY_MODE
                        else [
                            cloudfront.CfnDistribution.FunctionAssociationProperty(
                                event_type="viewer-request",
                                function_arn=f"arn:aws:cloudfront::{ACCT}:function/v4-redirects",
                            ),
                        ]
                    ),
                ),
                # Cache behaviors — ORDER MATTERS: most-specific first.
                cache_behaviors=[
                    # /api/subscribe* — email-subscriber Lambda.
                    # POST body must be forwarded; responses must NOT be cached.
                    # Query strings forwarded for ?action=confirm&token=... flow.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/subscribe*",
                        target_origin_id="SubscriberLambdaOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=True,  # confirm token + action param
                            headers=["Origin", "Content-Type"],
                            cookies=cloudfront.CfnDistribution.CookiesProperty(forward="none"),
                        ),
                        default_ttl=0,  # never cache subscribe responses
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=[
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "POST",
                            "PUT",
                            "PATCH",
                            "DELETE",  # POST required for subscribe
                        ],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /og — dynamic SVG OG image with live stats (WR-17).
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/og",
                        target_origin_id="OgImageOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False,
                        ),
                        default_ttl=3600,  # 1hr cache — stats update daily
                        max_ttl=3600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /api/verify_subscriber — subscriber token verify. WR-24.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/verify_subscriber",
                        target_origin_id="LambdaApiOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=True, headers=["Origin", "Content-Type"]
                        ),
                        default_ttl=0,
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD", "OPTIONS"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /api/board_ask — board persona AI. S2-T2-2. ADR-036: routed to AI Lambda.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/board_ask",
                        target_origin_id="AiLambdaOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False, headers=["Origin", "Content-Type"]
                        ),
                        default_ttl=0,
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /api/explain (#403) — one-tap server-grounded page explainer.
                    # Same AI Lambda, same never-cache posture as /api/ask.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/explain",
                        target_origin_id="AiLambdaOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False,
                            headers=["Origin", "Content-Type", "X-Subscriber-Token"],
                        ),
                        default_ttl=0,
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /api/ask — AI Q&A (POST only, no cache). ADR-036: routed to AI Lambda.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/ask",
                        target_origin_id="AiLambdaOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False,
                            headers=["Origin", "Content-Type", "X-Subscriber-Token"],
                        ),
                        default_ttl=0,  # never cache AI responses
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=[
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "POST",
                            "PUT",
                            "PATCH",
                            "DELETE",
                        ],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # ── ADR-046: Generated content behaviors (Lambda-written files) ──
                    # These route specific file patterns to S3GeneratedOrigin (/generated prefix)
                    # instead of the default S3SiteOrigin (/site prefix), so deploy --delete
                    # on /site can never touch Lambda-generated content.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/podcast/*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=3600,
                        max_ttl=86400,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # "The Panel" two-host show — generated/panelcast/* (CC podcast)
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/panelcast/*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=3600,
                        max_ttl=86400,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # #397: the Reader Q&A payoff feed — publish_board_answer.py writes
                    # generated/board_answers/answers.json and the coaching qa tab reads
                    # /board_answers/answers.json. Without this behavior the fetch fell
                    # through to the site origin and 404'd: readers could ask but the
                    # answered-questions surface never existed. Short TTL — a freshly
                    # published answer should land within minutes.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/board_answers/*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=300,
                        max_ttl=900,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/public_stats.json",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=300,
                        max_ttl=600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/pulse.json",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=300,
                        max_ttl=600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/data/character_stats.json",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=3600,
                        max_ttl=86400,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/journal/posts.json",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=300,
                        max_ttl=3600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/journal/posts/week-*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=300,
                        max_ttl=3600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/assets/images/og-*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=86400,
                        max_ttl=86400,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # Editorial cover art (Part II) — Lambda-written to generated/assets/images/editorial/*.
                    # Must precede any generic /assets/* (site origin) behaviour so these route to generated.
                    # 30-day TTL: an image never changes once chosen for a post.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/assets/images/editorial/*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=2592000,
                        max_ttl=2592000,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # Book cover art (ADR-097, Mind pillar) — reading-cover-pipeline writes to
                    # generated/covers/<bookId>.jpg; the /mind/ front-end strips the `generated/`
                    # prefix and requests /covers/<bookId>.jpg. Without this behaviour the request
                    # falls through to the site origin → 404 (the broken-image bug). 30-day TTL:
                    # a cover is immutable once cached for a book.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/covers/*",
                        target_origin_id="S3GeneratedOrigin",
                        viewer_protocol_policy="redirect-to-https",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False),
                        default_ttl=2592000,
                        max_ttl=2592000,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD"],
                        cached_methods=["GET", "HEAD"],
                    ),
                    # /api/* — site-api Lambda (all methods, query strings forwarded).
                    # POST endpoints (nudge, vote, follow, submit_finding) need POST.
                    # GET endpoints (experiment_detail) need query_string=True.
                    # Lambda sets its own Cache-Control headers; CloudFront respects them.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/*",
                        target_origin_id="LambdaApiOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=True,
                            headers=["Origin", "Content-Type"],
                        ),
                        default_ttl=300,
                        max_ttl=3600,
                        min_ttl=0,
                        allowed_methods=[
                            "GET",
                            "HEAD",
                            "OPTIONS",
                            "POST",
                            "PUT",
                            "PATCH",
                            "DELETE",
                        ],
                        cached_methods=["GET", "HEAD"],
                    ),
                ],
                # Custom error pages
                # WR-28: Custom error responses for subpage routing.
                # S3 website hosting handles /story/ → /story/index.html normally,
                # but if a path doesn't exist (e.g. /nonexistent), serve 404 page
                # with proper 404 status. The 403 response handles S3 access denied
                # (which S3 returns for some missing-file scenarios).
                custom_error_responses=[
                    cloudfront.CfnDistribution.CustomErrorResponseProperty(
                        error_code=404,
                        response_code=404,
                        response_page_path="/404.html",
                        error_caching_min_ttl=10,
                    ),
                    cloudfront.CfnDistribution.CustomErrorResponseProperty(
                        error_code=403,
                        response_code=200,
                        response_page_path="/index.html",  # S3 returns 403 for missing dirs
                        error_caching_min_ttl=10,
                    ),
                ],
            ),
        )

        # ── Outputs
        cdk.CfnOutput(
            self,
            "DashboardDistributionId",
            value="EM5NPX6NJN095",
            description="CloudFront distribution ID for dash.averagejoematt.com",
        )
        cdk.CfnOutput(
            self,
            "BlogDistributionId",
            value="E1JOC1V6E6DDYI",
            description="CloudFront distribution ID for blog.averagejoematt.com",
        )
        cdk.CfnOutput(
            self,
            "BuddyDistributionId",
            value="ETTJ44FT0Z4GO",
            description="CloudFront distribution ID for buddy.averagejoematt.com",
        )
        cdk.CfnOutput(
            self,
            "AmjDistributionId",
            value=amj_dist.ref,
            description="CloudFront distribution ID for averagejoematt.com",
        )
        cdk.CfnOutput(
            self,
            "AmjDistributionDomain",
            value=amj_dist.attr_domain_name,
            description="CloudFront domain to use in Route 53 alias record",
        )
        cdk.CfnOutput(
            self,
            "SiteApiFunctionUrl",
            value=_site_api_fn_url_for_output,
            description="Lambda Function URL for life-platform-site-api (CloudFront origin only)",
        )
        cdk.CfnOutput(
            self,
            "SubscriberFunctionUrl",
            value=subscriber_url.url,
            description="Lambda Function URL for email-subscriber (CloudFront /api/subscribe* origin only)",
        )
        cdk.CfnOutput(
            self,
            "SubscriberDlqUrl",
            value=subscriber_dlq.queue_url,
            description="DLQ for email-subscriber Lambda (us-east-1) — BUG-06",
        )

        # ══════════════════════════════════════════════════════════════
        # OBS-07: email-subscriber error alarm
        # Silent conversion failures would lose subscribers without any alert.
        # ══════════════════════════════════════════════════════════════
        GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD

        cloudwatch.Alarm(
            self,
            "SubscriberErrors",
            alarm_name="email-subscriber-errors",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": "email-subscriber"},
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
