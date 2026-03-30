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
    Stack,
    Duration,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp
from stacks.constants import REGION, ACCT, S3_BUCKET as _CONSTANTS_BUCKET  # CONF-01

BUCKET = _CONSTANTS_BUCKET

INGESTION_DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
ALERTS_TOPIC_ARN  = f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"

# ACM certificate for averagejoematt.com (us-east-1 — required for CloudFront)
# REQUEST THIS FIRST: see deploy/request_amj_cert.sh
# Then update this ARN and run: cdk deploy LifePlatformWeb
CERT_ARN_AMJ = "arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-e7d0-4403-a64c-c235bc57084c"

# S3 website endpoint (not the REST endpoint — required for static website hosting)
S3_WEBSITE_DOMAIN = f"{BUCKET}.s3-website-{REGION}.amazonaws.com"

# Existing ACM certificate ARNs (us-east-1, required for CloudFront)
CERT_ARN_DASH  = "arn:aws:acm:us-east-1:205930651321:certificate/8e560416-e5f6-4f87-82a6-17b5e7df25d0"
CERT_ARN_BLOG  = "arn:aws:acm:us-east-1:205930651321:certificate/952ddf18-d073-4d04-a0b7-42c7f5150dc2"
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

    def __init__(self, scope: Construct, construct_id: str,
                 table=None, bucket=None, dlq=None, alerts_topic=None,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Resolve shared resources (accept injected or import by name)
        local_table  = table  or dynamodb.Table.from_table_name(self, "LifePlatformTable", "life-platform")
        local_bucket = bucket or s3.Bucket.from_bucket_name(self, "LifePlatformBucket", BUCKET)
        local_dlq    = dlq    or sqs.Queue.from_queue_arn(self, "IngestionDLQ", INGESTION_DLQ_ARN)
        local_alerts = alerts_topic or sns.Topic.from_topic_arn(self, "AlertsTopic", ALERTS_TOPIC_ARN)

        # ══════════════════════════════════════════════════════════════
        # Dashboard — dash.averagejoematt.com  (EM5NPX6NJN095)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self, "DashboardDistribution",
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
                origins=[cloudfront.CfnDistribution.OriginProperty(
                    domain_name=S3_WEBSITE_DOMAIN,
                    id="S3WebsiteOrigin",
                    origin_path="/dashboard",
                    custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                        http_port=80,
                        https_port=443,
                        origin_protocol_policy="http-only",
                    ),
                )],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Blog — blog.averagejoematt.com  (E1JOC1V6E6DDYI)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self, "BlogDistribution",
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
                origins=[cloudfront.CfnDistribution.OriginProperty(
                    domain_name=S3_WEBSITE_DOMAIN,
                    id="S3WebsiteOrigin",
                    origin_path="/blog",
                    custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                        http_port=80,
                        https_port=443,
                        origin_protocol_policy="http-only",
                    ),
                )],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Buddy — buddy.averagejoematt.com  (ETTJ44FT0Z4GO)
        # ══════════════════════════════════════════════════════════════
        cloudfront.CfnDistribution(
            self, "BuddyDistribution",
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
                origins=[cloudfront.CfnDistribution.OriginProperty(
                    domain_name=S3_WEBSITE_DOMAIN,
                    id="S3WebsiteOrigin",
                    origin_path="/buddy",
                    custom_origin_config=cloudfront.CfnDistribution.CustomOriginConfigProperty(
                        http_port=80,
                        https_port=443,
                        origin_protocol_policy="http-only",
                    ),
                )],
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3WebsiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                    ),
                ),
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # Site API Lambda — life-platform-site-api
        # R17-09: Lambda moved to LifePlatformOperational (us-west-2) for same-region DynamoDB.
        # Migration Phase 2: once LifePlatformOperational is deployed, set context
        #   "site_api_fn_url_domain": "<domain-from-SiteApiFunctionUrlDomain-output>"
        # in cdk.json, then redeploy LifePlatformWeb. Until then, Lambda remains here.
        # ══════════════════════════════════════════════════════════════
        _site_api_ctx_domain = self.node.try_get_context("site_api_fn_url_domain")

        if not _site_api_ctx_domain:
            # Phase 1: Lambda still in web_stack until R17-09 migration is complete
            site_api_fn = create_platform_lambda(
                self, "SiteApiLambda",
                function_name="life-platform-site-api",
                source_file="lambdas/site_api_lambda.py",
                handler="site_api_lambda.lambda_handler",
                table=local_table,
                bucket=local_bucket,
                dlq=None,
                alerts_topic=None,
                custom_policies=rp.site_api(),
                timeout_seconds=15,
                memory_mb=256,
                environment={
                    "USER_ID":         "matthew",
                    "TABLE_NAME":      "life-platform",
                    "DYNAMODB_REGION": "us-west-2",  # DDB is us-west-2; Lambda runs in us-east-1
                    "AI_SECRET_NAME":  "life-platform/site-api-ai-key",
                },
            )

        # ══════════════════════════════════════════════════════════════
        # Email Subscriber Lambda — BS-03
        # Handles POST /api/subscribe, GET /api/subscribe?action=confirm,
        # GET /api/subscribe?action=unsubscribe
        # Separate origin from site-api: needs POST forwarding + no cache.
        # ══════════════════════════════════════════════════════════════
        # BUG-06: Subscriber DLQ must be us-east-1 (same region as Lambda).
        # The main ingestion DLQ is us-west-2 — not usable here.
        subscriber_dlq = sqs.Queue(
            self, "EmailSubscriberDlq",
            queue_name="life-platform-subscriber-dlq",
            retention_period=Duration.days(14),
        )

        subscriber_fn = create_platform_lambda(
            self, "EmailSubscriberLambda",
            function_name="email-subscriber",
            source_file="lambdas/email_subscriber_lambda.py",
            handler="email_subscriber_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=subscriber_dlq,
            alerts_topic=None,
            custom_policies=rp.operational_email_subscriber(),
            timeout_seconds=15,
            memory_mb=256,
            environment={
                "USER_ID":          "matthew",
                "TABLE_NAME":       "life-platform",
                "S3_BUCKET":        BUCKET,
                "EMAIL_SENDER":     "lifeplatform@mattsusername.com",
                "SITE_URL":         "https://averagejoematt.com",
                "DYNAMODB_REGION":  "us-west-2",  # DDB table is in us-west-2; Lambda runs in us-east-1
                "SES_REGION":       "us-west-2",  # SES verified identity is in us-west-2
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

        subscriber_url_domain = cdk.Fn.select(
            2, cdk.Fn.split("/", subscriber_url.url)
        )

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
        # ══════════════════════════════════════════════════════════════
        og_image_role = iam.Role(
            self, "OgImageLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )
        for stmt in rp.og_image():
            og_image_role.add_to_policy(stmt)

        og_image_fn = _lambda.Function(  # noqa: CDK_HANDLER_ORPHAN
            self, "OgImageLambda",
            function_name="life-platform-og-image",
            runtime=_lambda.Runtime.NODEJS_20_X,
            handler="og_image_lambda.handler",
            code=_lambda.Code.from_asset("../lambdas", exclude=[
                "*.py", "**/*.py", "__pycache__", "**/__pycache__/**",
                "*.pyc", "**/*.pyc", "*.md", "dashboard/**", "buddy/**",
                "cf-auth/**", "requirements/**", ".DS_Store",
            ]),
            role=og_image_role,
            timeout=Duration.seconds(10),
            memory_size=256,
        )

        og_image_url = og_image_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )

        og_image_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", og_image_url.url))

        if not _site_api_ctx_domain:
            site_api_url = site_api_fn.add_function_url(
                auth_type=_lambda.FunctionUrlAuthType.NONE,
                cors=_lambda.FunctionUrlCorsOptions(
                    allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                    allowed_methods=[_lambda.HttpMethod.GET, _lambda.HttpMethod.POST],
                    allowed_headers=["Content-Type"],
                ),
            )
            fn_url_domain = cdk.Fn.select(2, cdk.Fn.split("/", site_api_url.url))
            _site_api_fn_url_for_output = site_api_url.url
        else:
            # Phase 2 (R17-09 complete): Lambda is in LifePlatformOperational (us-west-2)
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
            self, "AmjSecurityHeadersPolicy",
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
                            "script-src 'self' 'unsafe-inline'; "
                            "style-src 'self' 'unsafe-inline'; "
                            "img-src 'self' data: https:; "
                            "connect-src 'self'; "
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
        # SEC-02: WAF WebACL ARN — defined here (before amj_dist) so CDK
        # tracks the association and a cdk deploy cannot accidentally
        # disassociate the WAF from the CloudFront distribution.
        # WebACL pre-existed in us-east-1 (id: 3d75472e-e18b-4d1c-b76b-8bbe63cb05e8).
        # Rules: SubscribeRateLimit (60/5min), GlobalRateLimit (1000/5min),
        #        RateLimitAsk (100/5min), RateLimitBoardAsk (100/5min).
        # ══════════════════════════════════════════════════════════════
        WAF_WEB_ACL_ARN = f"arn:aws:wafv2:us-east-1:{ACCT}:global/webacl/life-platform-amj-waf/3d75472e-e18b-4d1c-b76b-8bbe63cb05e8"

        # ══════════════════════════════════════════════════════════════
        # averagejoematt.com — main website
        # Two origins:
        #   1. S3 /site  → static pages (default behaviour)
        #   2. Lambda Function URL  → /api/* (real-time data, TTL-cached)
        # ══════════════════════════════════════════════════════════════

        amj_dist = cloudfront.CfnDistribution(
            self, "AmjDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="averagejoematt.com — main website",
                aliases=["averagejoematt.com", "www.averagejoematt.com"],
                price_class="PriceClass_100",
                default_root_object="index.html",
                web_acl_id=WAF_WEB_ACL_ARN,  # SEC-02: CDK now owns WAF association — prevents accidental disassociation on cdk deploy
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
                ],
                # Default behaviour: S3 static pages
                default_cache_behavior=cloudfront.CfnDistribution.DefaultCacheBehaviorProperty(
                    target_origin_id="S3SiteOrigin",
                    viewer_protocol_policy="redirect-to-https",
                    forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                        query_string=False,
                        cookies=cloudfront.CfnDistribution.CookiesProperty(forward="none"),
                    ),
                    default_ttl=3600,    # 1h for static assets
                    max_ttl=86400,
                    min_ttl=0,
                    response_headers_policy_id=amj_security_headers.ref,  # R17-15
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
                            query_string=True,   # confirm token + action param
                            headers=["Origin", "Content-Type"],
                            cookies=cloudfront.CfnDistribution.CookiesProperty(forward="none"),
                        ),
                        default_ttl=0,   # never cache subscribe responses
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=[
                            "GET", "HEAD", "OPTIONS",
                            "POST", "PUT", "PATCH", "DELETE",  # POST required for subscribe
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
                        default_ttl=3600,   # 1hr cache — stats update daily
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
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=True, headers=["Origin","Content-Type"]),
                        default_ttl=0, max_ttl=0, min_ttl=0,
                        allowed_methods=["GET","HEAD","OPTIONS"], cached_methods=["GET","HEAD"],
                    ),
                    # /api/board_ask — board persona AI. S2-T2-2. ADR-036: routed to AI Lambda.
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/board_ask",
                        target_origin_id="AiLambdaOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(query_string=False, headers=["Origin","Content-Type"]),
                        default_ttl=0, max_ttl=0, min_ttl=0,
                        allowed_methods=["GET","HEAD","OPTIONS","POST","PUT","PATCH","DELETE"], cached_methods=["GET","HEAD"],
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
                        default_ttl=0,   # never cache AI responses
                        max_ttl=0,
                        min_ttl=0,
                        allowed_methods=[
                            "GET", "HEAD", "OPTIONS",
                            "POST", "PUT", "PATCH", "DELETE",
                        ],
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
                            "GET", "HEAD", "OPTIONS",
                            "POST", "PUT", "PATCH", "DELETE",
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

        # WAF WebACL ARN output (WAF_WEB_ACL_ARN defined above, before amj_dist — SEC-02)
        cdk.CfnOutput(self, "AmjWafWebAclArn",
            value=WAF_WEB_ACL_ARN,
            description="WAF WebACL ARN for averagejoematt.com CloudFront distribution (R17-01/SEC-02)",
        )

        # ══════════════════════════════════════════════════════════════
        # R17-03: CloudWatch dashboard + alarms for life-platform-site-api
        # Lambda is in us-east-1 (WebStack); alarms must be in same region.
        # Alarms: error rate >5%, p95 latency >5s, invocations >1000/hr.
        # ══════════════════════════════════════════════════════════════
        GTE = cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD

        site_api_errors = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="Sum",
        )
        site_api_invocations = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Invocations",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="Sum",
        )
        site_api_duration_p95 = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="p95",
        )
        site_api_duration_p50 = cloudwatch.Metric(
            namespace="AWS/Lambda",
            metric_name="Duration",
            dimensions_map={"FunctionName": "life-platform-site-api"},
            period=Duration.minutes(5),
            statistic="p50",
        )

        # Alarm: error rate — any errors in 5-min window
        cloudwatch.Alarm(
            self, "SiteApiErrors",
            alarm_name="site-api-errors",
            metric=site_api_errors,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Alarm: p95 latency > 5000ms
        cloudwatch.Alarm(
            self, "SiteApiLatencyHigh",
            alarm_name="site-api-p95-latency-high",
            metric=site_api_duration_p95,
            threshold=5000,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Alarm: invocation spike > 1000/hr (200 per 5-min window)
        cloudwatch.Alarm(
            self, "SiteApiInvocationSpike",
            alarm_name="site-api-invocation-spike",
            metric=site_api_invocations,
            threshold=200,
            evaluation_periods=1,
            comparison_operator=GTE,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Dashboard: invocations, errors, p50/p95 latency, duration
        cloudwatch.Dashboard(
            self, "SiteApiDashboard",
            dashboard_name="life-platform-site-api",
            widgets=[
                [
                    cloudwatch.GraphWidget(
                        title="Invocations",
                        left=[site_api_invocations],
                        width=8,
                    ),
                    cloudwatch.GraphWidget(
                        title="Errors",
                        left=[site_api_errors],
                        width=8,
                    ),
                    cloudwatch.GraphWidget(
                        title="Duration (p50 / p95)",
                        left=[site_api_duration_p50, site_api_duration_p95],
                        width=8,
                    ),
                ],
            ],
        )

        # ── Outputs
        cdk.CfnOutput(self, "DashboardDistributionId",
            value="EM5NPX6NJN095",
            description="CloudFront distribution ID for dash.averagejoematt.com",
        )
        cdk.CfnOutput(self, "BlogDistributionId",
            value="E1JOC1V6E6DDYI",
            description="CloudFront distribution ID for blog.averagejoematt.com",
        )
        cdk.CfnOutput(self, "BuddyDistributionId",
            value="ETTJ44FT0Z4GO",
            description="CloudFront distribution ID for buddy.averagejoematt.com",
        )
        cdk.CfnOutput(self, "AmjDistributionId",
            value=amj_dist.ref,
            description="CloudFront distribution ID for averagejoematt.com",
        )
        cdk.CfnOutput(self, "AmjDistributionDomain",
            value=amj_dist.attr_domain_name,
            description="CloudFront domain to use in Route 53 alias record",
        )
        cdk.CfnOutput(self, "SiteApiFunctionUrl",
            value=_site_api_fn_url_for_output,
            description="Lambda Function URL for life-platform-site-api (CloudFront origin only)",
        )
        cdk.CfnOutput(self, "SubscriberFunctionUrl",
            value=subscriber_url.url,
            description="Lambda Function URL for email-subscriber (CloudFront /api/subscribe* origin only)",
        )
        cdk.CfnOutput(self, "SubscriberDlqUrl",
            value=subscriber_dlq.queue_url,
            description="DLQ for email-subscriber Lambda (us-east-1) — BUG-06",
        )

        # ══════════════════════════════════════════════════════════════
        # OBS-07: email-subscriber error alarm
        # Silent conversion failures would lose subscribers without any alert.
        # ══════════════════════════════════════════════════════════════
        cloudwatch.Alarm(
            self, "SubscriberErrors",
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
