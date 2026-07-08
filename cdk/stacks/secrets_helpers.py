"""
cdk/stacks/secrets_helpers.py — synth-time secret-value token helper (#815 / R22-SEC-03).

One factored read so the site-api origin-header guard secret (SEC-04,
lambdas/web/site_api_common.py::SITE_API_ORIGIN_SECRET) can never drift between
its two consumers:
  - serve_stack.py (us-west-2)  → Lambda environment variable on site-api / site-api-ai
  - web_stack.py    (us-east-1) → CloudFront custom origin header on
                                   LambdaApiOrigin / AiLambdaOrigin

Both stacks call site_api_origin_secret_value() and get back the identical
CloudFormation dynamic-reference token ("{{resolve:secretsmanager:...}}"),
resolved by CloudFormation itself at deploy time — NOT at `cdk synth`, so no
AWS credentials or network access are needed to synth locally, and a missing
secret fails loudly at deploy (CloudFormation error) rather than silently
degrading to an empty/disabled guard.

Cross-region safe: Secret.from_secret_partial_arn accepts a full-region ARN,
so WebStack (us-east-1) can resolve a secret that physically lives in
us-west-2 — the same trick stacks/constants.py::CF_AUTH_VERSION_ARN uses for a
fixed-region ARN independent of the stack's own deploy region.
"""

from aws_cdk import aws_secretsmanager as secretsmanager

from stacks.constants import SITE_API_ORIGIN_SECRET_ARN


def site_api_origin_secret_value(scope, construct_id: str = "SiteApiOriginSecret") -> str:
    """Return the SITE_API_ORIGIN_SECRET value as a deploy-time-resolved string token.

    Call once per stack (construct ids are scoped per-stack, so the default id
    is safe to reuse across ServeStack and WebStack without collision).
    """
    secret = secretsmanager.Secret.from_secret_partial_arn(scope, construct_id, SITE_API_ORIGIN_SECRET_ARN)
    return secret.secret_value.unsafe_unwrap()
