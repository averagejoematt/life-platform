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

Cross-region: CloudFormation dynamic references resolve secrets ONLY in the
stack's own region (a us-west-2 ARN from a us-east-1 stack fails with
ResourceNotFoundException at deploy — observed 2026-07-08). The secret is
therefore multi-region: primary in us-west-2, replica in us-east-1 (same name,
same value), and each stack resolves the copy in its own region.
"""

from aws_cdk import Stack, aws_secretsmanager as secretsmanager

from stacks.constants import ACCT, SITE_API_ORIGIN_SECRET_NAME


def site_api_origin_secret_value(scope, construct_id: str = "SiteApiOriginSecret") -> str:
    """Return the SITE_API_ORIGIN_SECRET value as a deploy-time-resolved string token.

    Call once per stack (construct ids are scoped per-stack, so the default id
    is safe to reuse across ServeStack and WebStack without collision).
    """
    region = Stack.of(scope).region
    arn = f"arn:aws:secretsmanager:{region}:{ACCT}:secret:{SITE_API_ORIGIN_SECRET_NAME}"
    secret = secretsmanager.Secret.from_secret_partial_arn(scope, construct_id, arn)
    return secret.secret_value.unsafe_unwrap()
