#!/usr/bin/env python3
"""tests/test_daily_brief_inflight_guard_2860.py — #2860 the in-flight guard.

2026-08-17 15:54-15:56Z: a default-timeout SYNC `aws lambda invoke` of
daily-brief retried on its own client-side read timeout (the AWS SDK's
"standard" retry mode treats that as transient) — attempts=3, ~60s apart. Each
retry landed on a container with no memory of the first attempt and re-ran the
whole ~7.5min, 4-AI-call generation from scratch: three paid generations for
one scheduled run, and enough token spend in one window to trip the AI token
alarms. `DRY_RUN`/`dry_run:true` does NOT protect against this — per #2255 it
suppresses writes only, never AI spend.

The fix (`lambdas/emails/daily_brief_lock.py::acquire_daily_brief_lock`,
called from `daily_brief_lambda.lambda_handler` — split into its own module
to stay off `daily_brief_lambda.py`'s zero-headroom module-size baseline,
#1665/#2610) is a DynamoDB conditional-put LEASE — never a permanent
tombstone — keyed on `(date, dry_run)`:
  * the put only succeeds when no lease row exists yet for that key, OR the
    existing row's `ttl` has already passed;
  * a concurrent retry inside the TTL window is refused and `lambda_handler`
    short-circuits BEFORE `fetch_profile`/`gather_daily_data` even run, let
    alone any of the 4 AI calls (this is what makes it a spend guard and not
    just a dedup log line);
  * a genuine crash (Lambda killed, OOM, ...) still gets a real retry once the
    TTL — deliberately set well past daily-brief's own 900s configured Lambda
    timeout — elapses. The scheduled run's legitimate retry semantics are
    unaffected: this is a bounded lease, not a tombstone.

Pinned here:
  1. `acquire_daily_brief_lock`'s own contract (Decimal writes, independent
     keys per date/dry_run, lease-not-tombstone expiry, non-conflict errors
     fail OPEN rather than crashing the whole brief);
  2. the reuse seam in `daily_brief_lambda.lambda_handler`'s source
     (structural pin, same idiom as `test_chronicle_generation_cache_2669.py`'s
     #3): the lock check sits before the main-flow `fetch_profile()`, which
     sits before the AI pipeline call;
  3. the full-handler behavioral case the issue asks for by name: a simulated
     concurrent second invoke returns early with ZERO AI-section execution;
  4. `DAILY_BRIEF_LOCK_PK` is a `SYSTEM#` ops-namespace partition that
     `phase_taxonomy.classify()` resolves to SYSTEM_STATE via its existing
     generic `SYSTEM#` prefix rule — never tagged, never wiped, never
     phase-filtered, and not something a new SOURCE# partition classification
     was needed for.

Safety: no real Bedrock, DDB, S3, SES, or Lambda invoke anywhere in this file.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from common.pacific_time import pacific_now  # #2817: the frame the brief names

REPO_ROOT = Path(__file__).resolve().parent.parent

# The module validates these at import time and raises RuntimeError without them.
for _k, _v in [
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
    ("TABLE_NAME", "life-platform"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "brief@example.invalid"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
]:
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

from botocore.exceptions import ClientError  # noqa: E402

_import_err = None
try:
    import daily_brief_lambda as brief  # noqa: E402
    import daily_brief_lock as lock  # noqa: E402
    from experiment import phase_taxonomy as tax  # noqa: E402
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    brief = None  # type: ignore
    lock = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"daily_brief_lambda unavailable: {_import_err}")  # type: ignore

_LOG = logging.getLogger("test-2860")


def _g(table):
    """The facade hand-off `acquire_daily_brief_lock` reads — matches
    chronicle_store.py's own test idiom for the same shape (`_g(table)` in
    `test_chronicle_generation_cache_2669.py`)."""
    return {"table": table, "logger": _LOG}


# ══════════════════════════════════════════════════════════════════════════════
# A conditional-put-aware fake table
# ══════════════════════════════════════════════════════════════════════════════


class _FakeConditionalTable:
    """A DynamoDB stand-in narrow enough to exercise ONE thing faithfully: the
    conditional put `acquire_daily_brief_lock` issues
    (`attribute_not_exists(pk) OR #ttl < :now`). Every other put (the module's
    dozens of other write sites) is accepted unconditionally, matching the
    generic `FakeTable` in `test_daily_brief_behavior.py` — this class exists
    only where that one's unconditional writes would hide the exact bug this
    issue is about.
    """

    def __init__(self):
        self.store = {}
        self.put_calls = []
        self.conflicts = 0

    def put_item(self, Item=None, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        self.put_calls.append(Item)
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression and existing is not None:
            now = (ExpressionAttributeValues or {}).get(":now")
            existing_ttl = existing.get("ttl")
            lease_expired = existing_ttl is not None and now is not None and existing_ttl < now
            if not lease_expired:
                self.conflicts += 1
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}, "PutItem")
        self.store[key] = Item
        return {}

    def get_item(self, Key=None, **kw):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}


@pytest.fixture
def cond_table():
    return _FakeConditionalTable()


# ══════════════════════════════════════════════════════════════════════════════
# 1. acquire_daily_brief_lock — the mechanism
# ══════════════════════════════════════════════════════════════════════════════


class TestAcquireDailyBriefLock:
    def test_first_acquire_succeeds_and_writes_a_decimal_lease(self, cond_table):
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True
        (item,) = cond_table.store.values()
        assert item["pk"] == lock.DAILY_BRIEF_LOCK_PK
        assert item["sk"] == "LOCK#2026-08-16#False"
        # Decimal, not float/int — boto3 rejects float on a real DDB write.
        assert item["ttl"] == Decimal(1000 + lock.DAILY_BRIEF_LOCK_TTL_SECONDS)
        assert isinstance(item["ttl"], Decimal)
        assert isinstance(item["acquired_at"], Decimal)

    def test_a_concurrent_second_acquire_for_the_same_key_is_refused(self, cond_table):
        """The retry-storm case: a same-payload sync-invoke retry ~60s later,
        well inside the lease TTL, must NOT be allowed to proceed."""
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1060) is False
        assert cond_table.conflicts == 1

    def test_a_third_retry_is_also_refused(self, cond_table):
        """Mirrors the observed live incident: attempts=3, ~60s apart."""
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=0) is True
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=60) is False
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=120) is False

    def test_dry_run_and_a_real_run_are_independent_leases(self, cond_table):
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True
        assert lock.acquire_daily_brief_lock("2026-08-16", True, _g=_g(cond_table), now=1000) is True
        assert len(cond_table.store) == 2

    def test_a_different_date_is_a_different_lease(self, cond_table):
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True
        assert lock.acquire_daily_brief_lock("2026-08-17", False, _g=_g(cond_table), now=1000) is True

    def test_a_retry_after_a_real_crash_is_allowed_once_the_lease_expires(self, cond_table):
        """The acceptance criterion in its own words: a retry after a real
        crash must still be able to run — TTL/lease expiry, not a permanent
        tombstone."""
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True
        expiry = 1000 + lock.DAILY_BRIEF_LOCK_TTL_SECONDS
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=expiry - 1) is False
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=expiry + 1) is True

    def test_ttl_is_comfortably_longer_than_the_lambdas_own_configured_timeout(self):
        """900s is daily-brief's configured Lambda timeout
        (cdk/stacks/email_stack.py — "daily-brief timeout bumped 300s -> 900s").
        The lease must outlive it, or it could expire while a first attempt is
        still legitimately running."""
        assert lock.DAILY_BRIEF_LOCK_TTL_SECONDS > 900

    def test_a_non_conflict_ddb_error_fails_open_rather_than_crashing_the_brief(self, cond_table, monkeypatch, caplog):
        """The lock is a backstop against duplicate spend, not a new single
        point of failure — a lock-write hiccup must not cost the whole brief.
        (This is also why the existing `test_a_failing_grade_store_never_costs_
        the_email` in test_daily_brief_behavior.py still passes: the FIRST
        DynamoDB write `lambda_handler` makes is this lock's.)"""

        def _boom(**kw):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "PutItem")

        monkeypatch.setattr(cond_table, "put_item", _boom)
        with caplog.at_level(logging.ERROR):
            assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True

    def test_a_non_clienterror_exception_also_fails_open(self, cond_table, monkeypatch):
        """Not every DDB-adjacent failure surfaces as a botocore ClientError
        (a raw connection/config error, or — as in the test fixture above — a
        hand-rolled fake raising a plain exception)."""
        monkeypatch.setattr(cond_table, "put_item", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table), now=1000) is True

    def test_uses_the_real_wall_clock_when_now_is_not_given(self, cond_table):
        before = int(time.time())
        assert lock.acquire_daily_brief_lock("2026-08-16", False, _g=_g(cond_table)) is True
        (item,) = cond_table.store.values()
        assert item["acquired_at"] >= before


# ══════════════════════════════════════════════════════════════════════════════
# 2. phase_taxonomy classification
# ══════════════════════════════════════════════════════════════════════════════


def test_lock_partition_is_classified_system_state():
    """SYSTEM_STATE = 'Ops/infra/cache/TTL records... dedup trackers' — exactly
    what this lease is. Resolved via phase_taxonomy's existing generic
    `SYSTEM#` prefix rule (dlq-ledger's shape); no new taxonomy rule needed,
    but the classification must actually resolve and not raise."""
    assert lock.DAILY_BRIEF_LOCK_PK.startswith("SYSTEM#")
    assert tax.classify(lock.DAILY_BRIEF_LOCK_PK, "LOCK#2026-08-16#False") == tax.SYSTEM_STATE


# ══════════════════════════════════════════════════════════════════════════════
# 3. Structural pin — the guard sits before fetch_profile, before the AI call
# ══════════════════════════════════════════════════════════════════════════════


def test_lock_check_sits_before_fetch_profile_and_before_the_ai_pipeline_call():
    src = (REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text()
    guard_at = src.index("if not acquire_daily_brief_lock(yesterday, _dry_run")
    # Two `profile = fetch_profile()` sites exist: the regrade-mode one (its
    # own early-return branch, unaffected by this guard by design) and the
    # main-flow one. Anchor past the guard to find the main-flow one.
    fetch_profile_at = src.index("profile = fetch_profile()", guard_at)
    ai_call_at = src.index("_ai = _run_ai_coach_pipeline(")
    assert guard_at < fetch_profile_at, "the lease must be claimed before the profile is even fetched"
    assert fetch_profile_at < ai_call_at, "fetch_profile must run before the AI pipeline (sanity on the anchor itself)"


def test_daily_brief_lambda_imports_the_guard_from_the_split_out_module():
    """#2860 was split into its own module specifically to stay off
    daily_brief_lambda.py's zero-headroom module-size baseline (#1665/#2610,
    'never raise a baseline' — extract instead). Pin the import exists so the
    two files cannot silently drift apart."""
    src = (REPO_ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text()
    assert "from emails.daily_brief_lock import acquire_daily_brief_lock" in src


# ══════════════════════════════════════════════════════════════════════════════
# 4. lambda_handler — the full acceptance case
# ══════════════════════════════════════════════════════════════════════════════


class TestLambdaHandlerInFlightShortCircuit:
    def test_a_concurrent_second_invoke_returns_early_with_zero_ai_section_execution(self, monkeypatch):
        """The acceptance criterion in its own words: a simulated concurrent
        second invoke returns early with ZERO AI-section execution."""
        event = {"dry_run": True}
        yesterday = (pacific_now().date() - timedelta(days=1)).isoformat()  # #2817: the day the handler names

        t = _FakeConditionalTable()
        # Pre-seed an UNEXPIRED lease, as if a first invocation for the same
        # (date, dry_run) is already mid-generation — the exact shape of the
        # AWS SDK's own sync-invoke retry landing on a second container.
        now = int(time.time())
        lock_sk = f"LOCK#{yesterday}#True"
        t.store[(lock.DAILY_BRIEF_LOCK_PK, lock_sk)] = {
            "pk": lock.DAILY_BRIEF_LOCK_PK,
            "sk": lock_sk,
            "ttl": Decimal(now + lock.DAILY_BRIEF_LOCK_TTL_SECONDS),
            "acquired_at": Decimal(now),
        }
        monkeypatch.setattr(brief, "table", t)

        def _must_not_be_called(*a, **kw):
            raise AssertionError("reached past the #2860 in-flight guard — this is the exact spend the guard exists to prevent")

        # Everything between the guard and a shipped email — heavy reads,
        # rendering setup, and every one of the 4 paid AI calls — must be
        # unreachable on this invocation.
        monkeypatch.setattr(brief, "fetch_profile", _must_not_be_called)
        monkeypatch.setattr(brief, "gather_daily_data", _must_not_be_called)
        monkeypatch.setattr(brief, "_run_ai_coach_pipeline", _must_not_be_called)
        monkeypatch.setattr(brief.ai_calls, "call_board_of_directors", _must_not_be_called)
        monkeypatch.setattr(brief.ai_calls, "call_training_nutrition_coach", _must_not_be_called)
        monkeypatch.setattr(brief.ai_calls, "call_journal_coach", _must_not_be_called)
        monkeypatch.setattr(brief.ai_calls, "call_tldr_and_guidance", _must_not_be_called)

        out = brief.lambda_handler(event, None)

        assert out["statusCode"] == 200
        assert "already in flight" in out["body"]
        assert yesterday in out["body"]
        # The conditional put was actually exercised — this is not just a
        # short-circuit that happens to look the same for an unrelated reason.
        assert t.conflicts == 1

    def test_a_second_invoke_for_a_different_dry_run_value_is_not_blocked(self, cond_table):
        """The lease key is (date, dry_run) — a REAL scheduled run must not be
        blocked by a stale dry-run test lease for the same date, or vice
        versa."""
        yesterday = (pacific_now().date() - timedelta(days=1)).isoformat()  # #2817: the day the handler names
        now = int(time.time())
        # A lease held for the DRY-RUN key only.
        lock_sk = f"LOCK#{yesterday}#True"
        cond_table.store[(lock.DAILY_BRIEF_LOCK_PK, lock_sk)] = {
            "pk": lock.DAILY_BRIEF_LOCK_PK,
            "sk": lock_sk,
            "ttl": Decimal(now + lock.DAILY_BRIEF_LOCK_TTL_SECONDS),
            "acquired_at": Decimal(now),
        }

        # A REAL (non-dry-run) invocation for the same date must still be able
        # to claim its own lease — assert only on the guard's own decision,
        # not the rest of the (heavily-dependency-laden) pipeline.
        assert lock.acquire_daily_brief_lock(yesterday, False, _g=_g(cond_table), now=now) is True
