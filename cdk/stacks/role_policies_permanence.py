"""role_policies_permanence.py — the Permanence Contract's IAM role (#1400).

A sibling of `role_policies.py` rather than another function inside it, on
purpose. `role_policies.py` sits **at** its recorded ceiling in
`tests/test_module_size_guard.py` (3,291 lines), and that registry is a
shrink-only ratchet: the sanctioned way to add policy is a cohesive module
beside it, not a raised number. This file is that module — one subsystem's
role, importable exactly like the rest.

It re-uses `role_policies`' own ARN constants rather than rebuilding them, so
there is still one definition of the table, bucket, key and SES identity.
"""

from aws_cdk import aws_iam as iam

from stacks.role_policies import BUCKET_ARN, KMS_KEY_ARN, SES_CONFIG_SET_ARN, SES_IDENTITY, TABLE_ARN, _s3, _secret_arn


def operational_permanence() -> list[iam.PolicyStatement]:
    """#1400 — the Permanence Contract's nightly run.

    Deliberately lopsided: broad READ over the two published prefixes (it has
    to enumerate the whole public surface to package it), and a WRITE scoped to
    a single sub-prefix — `generated/archive/*`, the four objects it publishes.
    It can read everything a reader can read and write nowhere a reader looks
    except its own shelf. There is no `s3:DeleteObject` at all: the archive is
    overwritten in place, and the one dated artefact it ever creates (the
    sealed final edition) must not be removable by the thing that wrote it.

    The DynamoDB grant is Query-only on the table (+ `kms:Decrypt` — the table
    is CMK-encrypted): the continuity clock reads one row per watched source
    and writes nothing, because the contract's own state lives in the published
    continuity document rather than in a private partition.

    SES is for the continuity transition notice; the recipient list comes from
    Secrets Manager and never from an environment variable, because this
    repository is public.
    """
    return [
        iam.PolicyStatement(
            sid="ContinuityClockRead",
            actions=["dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="TableKmsDecrypt",
            actions=["kms:Decrypt"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="ListPublishedSurface",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": ["site/*", "generated/*"]}},
        ),
        iam.PolicyStatement(
            sid="ReadPublishedSurface",
            actions=["s3:GetObject"],
            resources=_s3("site/*", "generated/*"),
        ),
        iam.PolicyStatement(
            sid="PublishArchiveOnly",
            actions=["s3:PutObject"],
            resources=_s3("generated/archive/*"),
        ),
        iam.PolicyStatement(
            sid="ContinuityContacts",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/continuity-contacts")],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]
