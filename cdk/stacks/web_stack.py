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
    aws_cloudfront as cloudfront,
    aws_s3 as s3,
)
from constructs import Construct

REGION = "us-west-2"
ACCT   = "205930651321"
BUCKET = "matthew-life-platform"

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

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
