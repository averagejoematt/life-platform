#!/usr/bin/env python3
"""setup/oauth_reauth_common.py — shared breaker-clear helper for oauth-facet
re-auth scripts (#2085).

## The gap this closes

Every oauth-facet source (`source_registry.oauth_source_ids()`) routes through
`common.auth_breaker`: on a 401/403 (or an explicit call-site classification,
#2069) the ingestion Lambda writes an `AUTH_FAILURE` marker with a 24h DDB TTL,
and every subsequent scheduled run short-circuits on it without even attempting
the API call — see `auth_breaker.check_breaker`. That's the right behavior
while the credential really is broken (it stops alarm spam and repeated failed
calls). But once the operator fixes the credential by hand — running a re-auth
setup script — nothing told the breaker the fix landed. The marker just sits
there for up to 24h, and the source stays dark even though the very next run
would have succeeded. Found live 2026-08-03: a manual re-auth of Whoop left the
source suppressed until a manual DDB delete + manual invoke proved the token
had been good the whole time.

## The fix

A re-auth script that has VERIFIED its fresh token works (however that
verification is shaped for that source — see call sites) calls
`clear_breaker_after_reauth(source_name)` right after the verified write. That
clears the same marker `auth_breaker.clear_failure` clears on a normal
successful ingestion run, so the very next scheduled run — not the next run
after the TTL — proceeds normally.

## Why this file, not a hand-rolled clear in each script

`clear_breaker_after_reauth` validates its `source_name` argument against
`source_registry.oauth_source_ids()` — the registry's oauth facet is the SET
of sources this applies to, not a hand-typed string per script (the "guard the
SET, not the instance" class of bug has recurred; see
`tests/test_oauth_reauth_breaker_clear.py`, which derives its own coverage
check from the same registry function rather than a fixed source list). A
typo'd source name raises immediately instead of silently deleting a DDB item
under the wrong partition key (or, worse, silently no-op'ing).

## Deploy note

This module runs LOCALLY as part of a re-auth setup script — it is never
bundled into a Lambda and never deployed. It reuses (imports, never
duplicates) `lambdas/common/auth_breaker.clear_failure`, the same bundled
function every ingestion Lambda already calls on a healthy run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3

_LAMBDAS_DIR = str(Path(__file__).resolve().parent.parent / "lambdas")
if _LAMBDAS_DIR not in sys.path:
    sys.path.insert(0, _LAMBDAS_DIR)

from common.auth_breaker import clear_failure  # noqa: E402
from ingestion.source_registry import oauth_source_ids  # noqa: E402

REGION = "us-west-2"
DEFAULT_USER_ID = "matthew"
DEFAULT_TABLE_NAME = "life-platform"


def clear_breaker_after_reauth(source_name: str, user_id: str = DEFAULT_USER_ID, table_name: str | None = None) -> bool:
    """Clear the AUTH_FAILURE breaker marker for `source_name` after a VERIFIED
    token write.

    Call this ONLY from the branch that has already confirmed the new
    credential works (the script's own verification step — a live API probe,
    or an OAuth token-exchange response that only returns tokens on success).
    Never call this unconditionally after a save; a save that later turns out
    to be bad must leave the marker alone so the breaker keeps suppressing
    calls until a REAL fix lands.

    Raises ValueError if `source_name` is not a registered oauth-facet source
    (see `source_registry.oauth_source_ids()`) — a loud failure beats a silent
    no-op against the wrong partition key.

    Returns True if the clear was attempted (best-effort past that point —
    `auth_breaker.clear_failure` itself swallows DDB errors, matching how
    every ingestion Lambda already treats this as non-fatal observability, not
    a hard dependency of the re-auth flow succeeding).
    """
    valid = oauth_source_ids()
    if source_name not in valid:
        raise ValueError(f"{source_name!r} is not a registered oauth-facet source (source_registry.oauth_source_ids(): {valid})")

    print(f"  Clearing auth-breaker marker for source={source_name} (if one is set)...")
    try:
        table = boto3.resource("dynamodb", region_name=REGION).Table(table_name or os.environ.get("TABLE_NAME", DEFAULT_TABLE_NAME))
        clear_failure(table, source_name=source_name, user_id=user_id, logger=None)
        print(f"  ✓ breaker marker cleared for source={source_name} — the next scheduled run will proceed normally.")
        return True
    except Exception as e:  # noqa: BLE001 — never let breaker cleanup fail an otherwise-successful re-auth
        print(f"  ⚠ could not clear the breaker marker for source={source_name}: {e}")
        print("    It will still self-expire via its 24h TTL, or delete it manually before then.")
        return False
