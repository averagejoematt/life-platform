"""tests/cdk_constants_env.py — import a deploy module against the COMMITTED CDK constants.

`cdk/stacks/constants.py` lets an environment variable override each identifier
(CONF-01: a second environment needs env vars, not code edits), and dozens of test
modules set `S3_BUCKET` / `TABLE_NAME` to fakes at IMPORT time. A deploy module that
loads those constants at its own import (deploy/iam_additive_registry.py derives its
S3 protection set from deploy/bucket_policy.json, which names the real bucket) then
reads whichever fake happened to be set by the last test module collected before it.

Under the full `tests/` collection the registry was always first imported early, by
test_cfn_exec_boundary_3340.py, so nothing ever showed. #4252 splits the post-merge
pass by file across runners, which changes collection order, and two modules failed to
COLLECT (`deploy/bucket_policy.json yielded no Deny (action, prefix) pairs`): the
registry had loaded with a polluted S3_BUCKET. Importing through this context manager
makes those modules order-independent.
"""

from __future__ import annotations

import contextlib
import os

# Every env override cdk/stacks/constants.py reads that the deploy registries consume.
CDK_CONSTANT_ENV_KEYS = ("CDK_REGION", "CDK_ACCOUNT", "TABLE_NAME", "S3_BUCKET", "CF_DIST_ID")


@contextlib.contextmanager
def committed_cdk_constants():
    """Hide the CDK-constant env overrides for the body, then restore them exactly."""
    saved = {k: os.environ.pop(k) for k in CDK_CONSTANT_ENV_KEYS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)
