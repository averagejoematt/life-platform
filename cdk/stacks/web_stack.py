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
)
from constructs import Construct

from stacks.lambda_helpers import create_platform_lambda
from stacks import role_policies as rp

REGION = "us-west-2"
ACCT   = "205930651321"
BUCKET = "matthew-life-platform"

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
        # Read-only. Reserved concurrency = 20 (viral defence).
        # ══════════════════════════════════════════════════════════════
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
            },
        )

        # ══════════════════════════════════════════════════════════════
        # Email Subscriber Lambda — BS-03
        # Handles POST /api/subscribe, GET /api/subscribe?action=confirm,
        # GET /api/subscribe?action=unsubscribe
        # Separate origin from site-api: needs POST forwarding + no cache.
        # ══════════════════════════════════════════════════════════════
        subscriber_fn = create_platform_lambda(
            self, "EmailSubscriberLambda",
            function_name="email-subscriber",
            source_file="lambdas/email_subscriber_lambda.py",
            handler="email_subscriber_lambda.lambda_handler",
            table=local_table,
            bucket=local_bucket,
            dlq=None,          # DLQ omitted: web_stack deploys to us-east-1, DLQ is us-west-2
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
        # Imported by ARN — deployed separately via deploy/deploy_og_image.sh.
        # ══════════════════════════════════════════════════════════════
        og_image_fn = _lambda.Function.from_function_arn(
            self, "OgImageLambda",
            function_arn=f"arn:aws:lambda:us-east-1:{ACCT}:function:life-platform-og-image",
        )
        og_image_url_domain = "fj5u62xcm2bk2fwuiyvf3wzqqm0mwcmk.lambda-url.us-east-1.on.aws"

        site_api_url = site_api_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["https://averagejoematt.com", "https://www.averagejoematt.com"],
                allowed_methods=[_lambda.HttpMethod.GET, _lambda.HttpMethod.POST],
                allowed_headers=["Content-Type"],
            ),
        )

        # ══════════════════════════════════════════════════════════════
        # averagejoematt.com — main website
        # Two origins:
        #   1. S3 /site  → static pages (default behaviour)
        #   2. Lambda Function URL  → /api/* (real-time data, TTL-cached)
        # ══════════════════════════════════════════════════════════════

        # Extract hostname from Function URL (strips https:// prefix)
        fn_url_domain = cdk.Fn.select(
            2, cdk.Fn.split("/", site_api_url.url)
        )

        amj_dist = cloudfront.CfnDistribution(
            self, "AmjDistribution",
            distribution_config=cloudfront.CfnDistribution.DistributionConfigProperty(
                enabled=True,
                comment="averagejoematt.com — main website",
                aliases=["averagejoematt.com", "www.averagejoematt.com"],
                price_class="PriceClass_100",
                default_root_object="index.html",
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
                    # Origin 3: email-subscriber Lambda Function URL (write, no cache)
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
                    # /api/ask — site-api Lambda (AI Q&A, POST only, no cache).
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/ask",
                        target_origin_id="LambdaApiOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False,
                            headers=["Origin", "Content-Type"],
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
                    # /api/* — site-api Lambda (read-only, TTL-cached).
                    cloudfront.CfnDistribution.CacheBehaviorProperty(
                        path_pattern="/api/*",
                        target_origin_id="LambdaApiOrigin",
                        viewer_protocol_policy="https-only",
                        forwarded_values=cloudfront.CfnDistribution.ForwardedValuesProperty(
                            query_string=False,
                            headers=["Origin"],
                        ),
                        default_ttl=300,
                        max_ttl=3600,
                        min_ttl=0,
                        allowed_methods=["GET", "HEAD", "OPTIONS"],
                        cached_methods=["GET", "HEAD"],
                    ),
                ],
                # Custom error pages
                custom_error_responses=[
                    cloudfront.CfnDistribution.CustomErrorResponseProperty(
                        error_code=404,
                        response_code=404,
                        response_page_path="/index.html",  # SPA fallback
                        error_caching_min_ttl=30,
                    ),
                ],
            ),
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
            value=site_api_url.url,
            description="Lambda Function URL for life-platform-site-api (CloudFront origin only)",
        )
        cdk.CfnOutput(self, "SubscriberFunctionUrl",
            value=subscriber_url.url,
            description="Lambda Function URL for email-subscriber (CloudFront /api/subscribe* origin only)",
        )
