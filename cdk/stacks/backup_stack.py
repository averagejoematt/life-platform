"""
BackupStack — the isolated backup of the irreplaceable `raw/` zone (DIL-027, #3042).

WHAT THIS PROTECTS, HONESTLY
────────────────────────────
`raw/` is the only unrecomputable data the platform holds: the original wearable
and API captures. DynamoDB metrics, every derived artifact, the whole site and
every narrative are recomputable FROM it. Before this stack the zone had exactly
one protection — bucket versioning — which survives an accidental overwrite and
nothing else. `docs/DISASTER_RECOVERY.md` scored "S3 bucket deletion" as
**NOT RECOVERABLE** and "us-west-2 region outage" as **hours-days, no DR region**.

This closes two of the three failure modes:

  ✅ regional failure — the replica lives in us-east-2, independent of us-west-2
     AND of us-east-1 (where the site's ACM certs + CloudFront config already
     live; putting the only backup there would have coupled the platform and its
     backup to one region's bad day)
  ✅ primary-bucket destruction — the replica is a separate bucket with its own
     versioning, its own delete-protection Deny, and delete-marker replication
     DISABLED, so a delete on the source does not propagate
  ❌ **account-level compromise — NOT covered.** Same account, same root, same
     credentials. `aws organizations list-accounts` returns exactly one account
     (verified 2026-08-24), so a true cross-account destination has no home to go
     to today. That residual is priced, dated and revisit-triggered in
     `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` — it is an accepted risk on
     the record, not an omission.

DESIGN DECISIONS WORTH THE INK
──────────────────────────────
* **Delete markers are NOT replicated** (`DeleteMarkerReplication: Disabled` in
  `deploy/s3_replication.json`) and the replication role is deliberately NOT
  granted `s3:ReplicateDelete`. Both halves say the same thing so neither can be
  loosened alone. A backup that faithfully mirrors deletions is not a backup.
* **The bucket is CDK-owned** (unlike the primary, which is imported via
  `Bucket.from_bucket_name` and therefore cannot carry CDK-managed policy or
  lifecycle — see `docs/MANAGED_WHERE_LEDGER.md`). So its policy, versioning and
  lifecycle are all in IaC here. Only the SOURCE-side replication configuration
  has to live out-of-IaC, for exactly the imported-bucket reason, and it follows
  the established `deploy/apply_s3_lifecycle.sh` pattern.
* **`RemovalPolicy.RETAIN`** — a `cdk destroy` must never be able to take the
  backup with it. That is the entire point of the resource.
* **S3 Standard, not Standard-IA.** Measured 2026-08-24: raw/ is 37,665 objects /
  541,451,065 bytes — a **14.4 KB mean object size**. Standard-IA bills a 128 KB
  minimum per object, so IA would bill ~4.8 GB for 0.50 GB of data and cost MORE
  than Standard (~$0.06/mo vs ~$0.012/mo). The cheap-tier reflex is wrong at this
  object size; the measurement is why (ADR-105).
* **The IAM role is created here** even though the source bucket is in us-west-2.
  IAM is global; the role only needs to exist in the account.

DEPLOY ORDER MATTERS — see the PR body / `deploy/apply_s3_replication.sh` header.
The source-side configuration references this stack's bucket ARN and role ARN, so
this stack deploys FIRST. Replication is also NOT retroactive: the 37,665 objects
already in raw/ need one S3 Batch Replication job, which is a separate owner step.
"""

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct

from stacks.constants import (
    ACCT,
    RAW_BACKUP_BUCKET,
    RAW_REPLICATION_PREFIX,
    RAW_REPLICATION_ROLE_NAME,
    S3_BUCKET,
)

# The principal the primary bucket's `ProtectDataFromDeployScripts` Deny already
# names (deploy/bucket_policy.json). The backup mirrors that protection rather
# than inventing a new shape — one pattern, two buckets.
_ADMIN_PRINCIPAL_ARN = f"arn:aws:iam::{ACCT}:user/matthew-admin"

_SOURCE_BUCKET_ARN = f"arn:aws:s3:::{S3_BUCKET}"
_SOURCE_PREFIX_ARN = f"{_SOURCE_BUCKET_ARN}/{RAW_REPLICATION_PREFIX}*"


class BackupStack(Stack):
    """The cross-region replica of `raw/` + the role S3 assumes to write it."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── The replica bucket ────────────────────────────────────────────────
        # Versioning is required by S3 for a replication DESTINATION, and is also
        # the second line of defence here: an object that somehow gets overwritten
        # on the replica still has its prior generation.
        self.backup_bucket = s3.Bucket(
            self,
            "RawBackupBucket",
            bucket_name=RAW_BACKUP_BUCKET,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="raw-backup-noncurrent-30d",
                    enabled=True,
                    # Own noncurrent expiry, deliberately NOT the primary bucket's
                    # (raw/ there is noncurrent-7d, keep-1, in
                    # deploy/apply_s3_lifecycle.sh). This bucket is managed by CDK
                    # and that script must never be pointed at it — a longer window
                    # here is intentional: on the primary a bad overwrite is caught
                    # within a day, but a replicated bad overwrite may not be
                    # noticed until someone actually needs the backup.
                    noncurrent_version_expiration=Duration.days(30),
                    noncurrent_versions_to_retain=1,
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
        )

        # ── Delete-protection, mirroring the primary's pattern ────────────────
        # Same principal, same shape as `ProtectDataFromDeployScripts` on
        # matthew-life-platform, extended to the bucket itself: a backup that the
        # everyday admin credential can empty or drop is not a backup. Lifecycle
        # expiry is unaffected — S3 runs lifecycle as the service, not as this
        # principal.
        self.backup_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="ProtectRawBackupFromDeployScripts",
                effect=iam.Effect.DENY,
                principals=[iam.ArnPrincipal(_ADMIN_PRINCIPAL_ARN)],
                actions=[
                    "s3:DeleteObject",
                    "s3:DeleteObjectVersion",
                    "s3:DeleteBucket",
                    "s3:PutBucketVersioning",
                    "s3:PutLifecycleConfiguration",
                ],
                resources=[
                    self.backup_bucket.bucket_arn,
                    self.backup_bucket.arn_for_objects("*"),
                ],
            )
        )

        # ── The replication role ──────────────────────────────────────────────
        # Scoped to raw/* on the source and to this bucket on the destination.
        # `s3:ReplicateDelete` is ABSENT on purpose (see module docstring) — the
        # IAM half of the "deletions do not propagate" guarantee.
        self.replication_role = iam.Role(
            self,
            "RawReplicationRole",
            role_name=RAW_REPLICATION_ROLE_NAME,
            assumed_by=iam.ServicePrincipal("s3.amazonaws.com"),
            description="S3 CRR: matthew-life-platform/raw/* to the us-east-2 backup bucket (DIL-027)",
        )
        self.replication_role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSourceReplicationConfig",
                actions=["s3:GetReplicationConfiguration", "s3:ListBucket"],
                resources=[_SOURCE_BUCKET_ARN],
            )
        )
        self.replication_role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSourceRawObjects",
                actions=[
                    "s3:GetObjectVersionForReplication",
                    "s3:GetObjectVersionAcl",
                    "s3:GetObjectVersionTagging",
                ],
                # Narrower than the bucket: raw/* only. Widening this needs the
                # constants.py decision, not an edit here.
                resources=[_SOURCE_PREFIX_ARN],
            )
        )
        self.replication_role.add_to_policy(
            iam.PolicyStatement(
                sid="WriteReplica",
                actions=["s3:ReplicateObject", "s3:ReplicateTags"],
                resources=[self.backup_bucket.arn_for_objects("*")],
            )
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        # deploy/apply_s3_replication.sh cross-checks these against
        # deploy/s3_replication.json before it puts anything.
        cdk.CfnOutput(self, "RawBackupBucketName", value=self.backup_bucket.bucket_name)
        cdk.CfnOutput(self, "RawBackupBucketArn", value=self.backup_bucket.bucket_arn)
        cdk.CfnOutput(self, "RawReplicationRoleArn", value=self.replication_role.role_arn)
