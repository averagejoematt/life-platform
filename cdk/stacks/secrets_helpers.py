"""
cdk/stacks/secrets_helpers.py — synth-time secret-value token helper (#815 / R22-SEC-03).

One factored read so the site-api origin-header guard secret (SEC-04,
lambdas/web/site_api_common.py::SITE_API_ORIGIN_SECRET) can never drift between
its consumers:
  - serve_stack.py (us-west-2)  → Lambda environment variable on site-api / site-api-ai
  - web_stack.py    (us-east-1) → CloudFront custom origin header on
                                   LambdaApiOrigin / AiLambdaOrigin /
                                   SubscriberLambdaOrigin (#885), plus the Lambda
                                   environment variable on email-subscriber (#885)

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

from aws_cdk import SecretValue

from stacks.constants import SITE_API_ORIGIN_SECRET_NAME


def site_api_origin_secret_value(scope, construct_id: str = "SiteApiOriginSecret") -> str:
    """Return the SITE_API_ORIGIN_SECRET value as a deploy-time-resolved string token.

    Referenced by NAME, not ARN: an ARN-based dynamic reference without the
    random suffix fails ResourceNotFoundException when the secret name ends in
    a hyphen + 6 chars ("…-secret" does — AWS partial-ARN matching quirk,
    observed 2026-07-08). A name reference resolves in the stack's own region
    (us-west-2 primary / us-east-1 replica) with no suffix ambiguity.

    Call once per stack (construct ids are scoped per-stack, so the default id
    is safe to reuse across ServeStack and WebStack without collision).
    """
    return SecretValue.secrets_manager(SITE_API_ORIGIN_SECRET_NAME).unsafe_unwrap()
