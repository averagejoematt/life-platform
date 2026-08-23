"""#2993 — the Plan job's config-drift classifier, mutation-proved at the function level.

The live incident (run 32637512129, wrap-tip 18dfa1e4c, 2026-08-23; same class as the
issue's measured run 5f5069f6): both flagged stacks' Lambda diffs were Code.S3Key-only
except a single `[~] Runtime nodejs22.x → nodejs24.x` on the CDK-internal LogRetention
singleton — toolchain skew (aws-cdk-lib regionalFact, #2468), not a merged config
change — yet the operator was told to run manual production cdk deploys.

Fixtures reproduce the exact `cdk diff` transcript shape from that run's Plan job log.
Both directions are proved: asset-hash-only churn classifies code-only, and a genuine
config-property change still fires, including when riding alongside asset churn.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))

from classify_cdk_diff import CONFIG_PROPS, classify, emit  # noqa: E402

pytestmark = pytest.mark.deploy_critical

S3KEY_ONLY = """\
Stack LifePlatformOperational
Resources
[~] AWS::Lambda::Function SiteStatsRefresh SiteStatsRefreshEC9E3CF9
 └─ [~] Code
     └─ [~] .S3Key:
         ├─ [-] e0647105aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip
         └─ [+] 7044ba80bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.zip
[~] AWS::Lambda::Function OGImageGenerator OGImageGenerator610E0B88
 └─ [~] Code
     └─ [~] .S3Key:
         ├─ [-] e0647105aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip
         └─ [+] 7044ba80bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.zip
"""

S3KEY_PLUS_ENV = """\
Stack LifePlatformEmail
Resources
[~] AWS::Lambda::Function DailyBrief DailyBrief22B24B58
 ├─ [~] Code
 │   └─ [~] .S3Key:
 │       ├─ [-] e0647105aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip
 │       └─ [+] 7044ba80bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.zip
 └─ [~] Environment
     └─ [~] .Variables:
         └─ [~] .BRIEF_MODE:
             ├─ [-] daily
             └─ [+] weekly
"""

ENV_ONLY = """\
Stack LifePlatformEmail
Resources
[~] AWS::Lambda::Function DailyBrief DailyBrief22B24B58
 └─ [~] Environment
     └─ [~] .Variables:
         └─ [~] .BRIEF_MODE:
             ├─ [-] daily
             └─ [+] weekly
"""

# The live-case transcript shape: 7 functions S3Key-only + the LogRetention Runtime skew.
LOGRETENTION_SKEW = """\
Stack LifePlatformOperational
Resources
[~] AWS::Lambda::Function SiteStatsRefresh SiteStatsRefreshEC9E3CF9
 └─ [~] Code
     └─ [~] .S3Key:
         ├─ [-] e0647105aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip
         └─ [+] 7044ba80bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.zip
[~] AWS::Lambda::Function LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8aFD4BFC8A
 └─ [~] Runtime
     ├─ [-] nodejs22.x
     └─ [+] nodejs24.x
[~] AWS::Lambda::Function PipelineHealthCheck PipelineHealthCheck6679D827
 └─ [~] Code
     └─ [~] .S3Key:
         ├─ [-] e0647105aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.zip
         └─ [+] 7044ba80bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.zip
"""

NON_LAMBDA_PROP = """\
Stack LifePlatformMonitoring
Resources
[~] AWS::CloudWatch::Alarm QaSmokeAlarm QaSmokeAlarm1234ABCD
 └─ [~] Timeout
     ├─ [-] 60
     └─ [+] 120
"""


def test_s3key_only_is_code_only():
    """(a) Asset-hash-only diff → clean: no stack flagged, no warning emitted."""
    verdicts = classify(S3KEY_ONLY)
    assert verdicts == {}
    lines = emit(verdicts)
    assert not any("::warning" in ln for ln in lines)
    assert any("code-only" in ln for ln in lines)


def test_s3key_plus_env_still_flags():
    """(b) S3Key churn riding with an env-var change → the config warning still fires."""
    verdicts = classify(S3KEY_PLUS_ENV)
    assert verdicts["LifePlatformEmail"].config_changes == [("DailyBrief", "Environment")]
    lines = emit(verdicts)
    warning = next(ln for ln in lines if ln.startswith("::warning"))
    assert "cdk deploy LifePlatformEmail" in warning
    assert "DailyBrief.Environment" in warning


def test_env_only_flags():
    """(c) Env-var-only diff → flags, exactly as before."""
    verdicts = classify(ENV_ONLY)
    assert verdicts["LifePlatformEmail"].config_changes == [("DailyBrief", "Environment")]
    assert any("::warning" in ln for ln in emit(verdicts))


def test_live_case_logretention_skew_is_notice_not_warning():
    """The #2993 live case: LogRetention Runtime skew → ::notice, never the manual-deploy warning."""
    verdicts = classify(LOGRETENTION_SKEW)
    verdict = verdicts["LifePlatformOperational"]
    assert verdict.config_changes == []
    assert verdict.toolchain_skew == [("LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a", "Runtime")]
    lines = emit(verdicts)
    assert not any("::warning" in ln for ln in lines)
    notice = next(ln for ln in lines if ln.startswith("::notice"))
    assert "regionalFact" in notice
    assert "no action required" in notice


def test_logretention_skew_plus_real_config_still_warns():
    """Skew must not mask a genuine config change in the same stack."""
    combined = LOGRETENTION_SKEW + (
        "[~] AWS::Lambda::Function QaSmoke QaSmoke0A2982C1\n" " └─ [~] Timeout\n" "     ├─ [-] 60\n" "     └─ [+] 120\n"
    )
    verdicts = classify(combined)
    verdict = verdicts["LifePlatformOperational"]
    assert verdict.config_changes == [("QaSmoke", "Timeout")]
    lines = emit(verdicts)
    warning = next(ln for ln in lines if ln.startswith("::warning"))
    assert "QaSmoke.Timeout" in warning


def test_logretention_non_runtime_config_still_warns():
    """Only Runtime on LogRetention is toolchain-chosen; any other property stays a config change."""
    diff = (
        "Stack LifePlatformCore\n"
        "Resources\n"
        "[~] AWS::Lambda::Function LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a LogRetentionFD4BFC8A\n"
        " └─ [~] Timeout\n"
        "     ├─ [-] 60\n"
        "     └─ [+] 900\n"
    )
    verdicts = classify(diff)
    assert verdicts["LifePlatformCore"].config_changes == [("LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a", "Timeout")]


def test_property_under_non_lambda_resource_never_classifies():
    """A Timeout-named property on a non-Lambda resource must not fire (the awk it replaces would)."""
    assert classify(NON_LAMBDA_PROP) == {}


def test_trigger_set_unchanged_from_awk():
    """Guard the SET: the trigger property list is exactly R20-F02's — a drift here is a
    deliberate widening/narrowing of what demands a manual prod deploy, not a refactor."""
    assert CONFIG_PROPS == {"Handler", "Runtime", "MemorySize", "Timeout", "Environment", "Layers", "Architectures"}
