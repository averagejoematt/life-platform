"""tests/test_sentinel_canfail_2578.py — can-it-fail proofs for the drift-sentinel
per-check family (census family 6, #3129/#3160), epic #2578 box 2.

WHY A SIBLING FILE AND NOT MORE OF test_drift_sentinel.py
─────────────────────────────────────────────────────────
`tests/test_drift_sentinel.py` is 1,920 lines and already carries most of this
family's proofs. This file adds ONLY the halves that were missing, plus the coverage
registry that makes the family's proof state derivable rather than assumed. Splitting
keeps both files readable and keeps the additions greppable as one slice.

THE STANDARD, TAKEN FROM #3112
──────────────────────────────
The audit of 2026-08-25 called `check_codeql_alerts`' planted-alert proof "the model
for what box 2 should look like at scale". Its shape has TWO halves, and a check with
only the first is exactly the class this epic exists to catch:

  (a) DETECT — plant the condition the check exists to find, assert it reports drift.
  (b) CANNOT-OBSERVE — plant the state where the check cannot see (auth failure,
      empty API response, unreadable config) and assert it says so LOUDLY. Never
      `clean`. #3156's shape — swallow the exception, fall back to a constant, and
      compare while believing you measured — is the anti-pattern this half exists for.

WHAT THIS FILE FOUND (the honest yield, 2026-08-25)
───────────────────────────────────────────────────
Writing half (b) for `check_postflight` found a live instance. Every other check in
`drift_sentinel.run_sweep()` is fail-soft behind its own `try`; `check_postflight`'s
`import session_postflight` was not, and `run_sweep()` has no `try` of its own. So an
unimportable session_postflight raised out of `run_sweep()` entirely — and the
remediation workflow runs that step under `continue-on-error: true`, so the result was
ALL FIFTEEN checks dark, no drift-log record written, no red step, no summary line.
The same shape as #3112's defect (c), one layer up. Fixed in `drift_sentinel.py` by
this change; `test_postflight_unimportable_module_is_error_not_a_crashed_sweep` below
is the mutation proof, and it fails against the pre-fix code.

Everything here is offline: no AWS, no network, no `gh`. Transports are monkeypatched
or fed fakes on the real call shapes (fixture-must-be-the-wire).
"""

from __future__ import annotations

import ast
import builtins
import json
import os
import sys
import types
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import drift_sentinel as ds  # noqa: E402
import gate_census as gc  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# A. check_postflight — no proof of either half existed before this file
# ═════════════════════════════════════════════════════════════════════════════
def _install_fake_postflight(monkeypatch, *, layer=(0, []), config=(), asset=(), raise_on=()):
    """Stand a fake `session_postflight` in sys.modules on the REAL call shapes:
    check_layer_uniformity() -> (latest, [(fn, version), ...]),
    check_config_drift() -> [ {function_name, issue}, ... ],
    check_asset_completeness() -> [ (fn, [missing]), ... ]."""
    mod = types.ModuleType("session_postflight")

    def _maybe(name, value):
        def _fn():
            if name in raise_on:
                raise RuntimeError(f"planted: {name} cannot observe (AccessDenied: lambda:GetFunctionConfiguration)")
            return value

        return _fn

    mod.check_layer_uniformity = _maybe("check_layer_uniformity", layer)
    mod.check_config_drift = _maybe("check_config_drift", list(config))
    mod.check_asset_completeness = _maybe("check_asset_completeness", list(asset))
    monkeypatch.setitem(sys.modules, "session_postflight", mod)
    return mod


def test_postflight_clean_when_every_subcheck_reports_nothing(monkeypatch):
    """The baseline the mutations below are measured against — without it, a `drift`
    assertion proves nothing (the check could be reporting drift unconditionally)."""
    _install_fake_postflight(monkeypatch)
    res = ds.check_postflight()
    assert {k: v["status"] for k, v in res.items()} == {
        "layer_uniformity": "clean",
        "config_drift": "clean",
        "asset_completeness": "clean",
    }


def test_postflight_detects_a_planted_retired_layer_reference(monkeypatch):
    """(a) DETECT — #781's invariant is ZERO references to life-platform-shared-utils.
    Plant one function still on the retired layer."""
    _install_fake_postflight(monkeypatch, layer=(0, [("daily-brief-sender", 41)]))
    res = ds.check_postflight()
    assert res["layer_uniformity"]["status"] == "drift"
    assert res["layer_uniformity"]["behind"] == [{"function": "daily-brief-sender", "on": 41}]


def test_postflight_detects_planted_lambda_config_drift(monkeypatch):
    """(a) DETECT — a live Lambda whose config no longer matches its CDK declaration."""
    _install_fake_postflight(monkeypatch, config=[{"function_name": "site-api", "issue": "timeout 30s live vs 60s declared"}])
    res = ds.check_postflight()
    assert res["config_drift"]["status"] == "drift"
    assert res["config_drift"]["items"] == [{"function": "site-api", "issue": "timeout 30s live vs 60s declared"}]


def test_postflight_detects_a_planted_incomplete_bundle(monkeypatch):
    """(a) DETECT — the asset-staging trap: a deployed zip missing a root module."""
    _install_fake_postflight(monkeypatch, asset=[("character-sheet", ["constants"])])
    res = ds.check_postflight()
    assert res["asset_completeness"]["status"] == "drift"
    assert res["asset_completeness"]["incomplete"] == [{"function": "character-sheet", "missing": ["constants"]}]


@pytest.mark.parametrize(
    "fn_name,key",
    [
        ("check_layer_uniformity", "layer_uniformity"),
        ("check_config_drift", "config_drift"),
        ("check_asset_completeness", "asset_completeness"),
    ],
)
def test_postflight_subcheck_that_cannot_observe_reports_error_never_clean(monkeypatch, fn_name, key):
    """(b) CANNOT-OBSERVE — one sub-check raising must report `error` with the reason,
    and must NOT quietly report the other two as the whole answer."""
    _install_fake_postflight(monkeypatch, raise_on=(fn_name,))
    res = ds.check_postflight()
    assert res[key]["status"] == "error", f"{key} swallowed a cannot-observe into {res[key]['status']}"
    assert "planted" in res[key]["detail"]
    assert res[key]["status"] != "clean"


def test_postflight_unimportable_module_is_error_not_a_crashed_sweep(monkeypatch):
    """(b) CANNOT-OBSERVE, and the live defect this file found.

    PRE-FIX this raised ImportError straight out of `check_postflight` and therefore
    out of `run_sweep()`, which has no try of its own. Under the remediation
    workflow's `continue-on-error: true` that meant no record, no red step, and the
    other fourteen checks never ran — a whole sweep dark on one import. Now every
    sub-check reports `error` with the reason, so `_summary` names them in its
    "check(s) could not run" line."""
    monkeypatch.delitem(sys.modules, "session_postflight", raising=False)
    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "session_postflight":
            raise ImportError("planted: No module named 'session_postflight'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    res = ds.check_postflight()  # must NOT raise
    assert set(res) == set(ds.POSTFLIGHT_SUBCHECKS)
    for key, value in res.items():
        assert value["status"] == "error", f"{key} is {value['status']!r} — a dark sub-check must never read clean"
        assert "planted" in value["detail"]


def test_a_crashed_postflight_would_have_taken_the_whole_sweep_with_it(monkeypatch):
    """The blast radius, asserted rather than described: `run_sweep()` wraps nothing,
    so any check that raises kills all fifteen. This is why (b) above matters more for
    `check_postflight` than for a check whose own try-block already contains it."""
    src = ast.parse(Path(_ROOT, "deploy", "drift_sentinel.py").read_text(encoding="utf-8"))
    run_sweep = next(n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == "run_sweep")
    assert not [n for n in ast.walk(run_sweep) if isinstance(n, ast.Try)], (
        "run_sweep() has grown a try — re-read this family's cannot-observe proofs: they "
        "assume a raising check darks the entire sweep, which is what makes per-check "
        "fail-soft load-bearing rather than stylistic"
    )


# ═════════════════════════════════════════════════════════════════════════════
# B. check_orphan_functions — the allowlist constant was tested; the check was not
# ═════════════════════════════════════════════════════════════════════════════
class _FakeLambdaList:
    def __init__(self, names, raises=None):
        self._names, self._raises = names, raises

    def get_paginator(self, op):  # noqa: D401 — boto3 shape
        assert op == "list_functions"
        outer = self

        class _Pag:
            def paginate(self):
                if outer._raises:
                    raise outer._raises
                return [{"Functions": [{"FunctionName": n} for n in outer._names]}]

        return _Pag()


class _FakeCfnResources:
    def __init__(self, by_stack, raises=None):
        self._by_stack, self._raises = by_stack, raises

    def list_stack_resources(self, **kw):  # noqa: N803
        if self._raises:
            raise self._raises
        return {
            "StackResourceSummaries": [
                {"ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": p} for p in self._by_stack.get(kw["StackName"], [])
            ]
        }


def _orphan_clients(monkeypatch, *, live, managed, lam_raises=None, cfn_raises=None):
    def _factory(service, region=None):
        if service == "lambda":
            return _FakeLambdaList(live, lam_raises)
        if service == "cloudformation":
            return _FakeCfnResources(managed, cfn_raises)
        raise AssertionError(f"unexpected client in test: {service}")

    monkeypatch.setattr(ds, "_client", _factory)


def test_orphan_functions_clean_when_every_live_function_is_stack_managed(monkeypatch):
    """Baseline, including the two allowlisted CDK-toolkit prefixes — otherwise the
    drift assertion below could not distinguish 'detects orphans' from 'always red'."""
    _orphan_clients(
        monkeypatch,
        live=["daily-brief-sender", "site-api", "cdk-hnb659fds-assets", "StackSet-admin"],
        managed={"LifePlatformCore": ["daily-brief-sender", "site-api"]},
    )
    res = ds.check_orphan_functions()
    assert res["status"] == "clean" and res["orphans"] == []


def test_orphan_functions_detects_a_planted_out_of_band_function(monkeypatch):
    """(a) DETECT — a Lambda that exists live but belongs to no stack's resource list
    is the console-created / out-of-IaC defect this check exists for."""
    _orphan_clients(
        monkeypatch,
        live=["site-api", "console-made-hotfix"],
        managed={"LifePlatformCore": ["site-api"]},
    )
    res = ds.check_orphan_functions()
    assert res["status"] == "drift"
    assert res["orphans"] == ["console-made-hotfix"]


def test_orphan_functions_cannot_list_live_functions_is_error_not_clean(monkeypatch):
    """(b) CANNOT-OBSERVE, live side. An empty live set would otherwise compute
    `live - managed == set()` and read CLEAN — the vacuous pass this half rules out."""
    _orphan_clients(
        monkeypatch,
        live=[],
        managed={},
        lam_raises=RuntimeError("AccessDenied: not authorized to perform lambda:ListFunctions"),
    )
    res = ds.check_orphan_functions()
    assert res["status"] == "error"
    assert "list_functions" in res["detail"] and "AccessDenied" in res["detail"]


def test_orphan_functions_cannot_list_stack_resources_is_error_not_a_false_red(monkeypatch):
    """(b) CANNOT-OBSERVE, managed side. The failure mode here is the OPPOSITE
    vacuum: an empty managed set would make EVERY live function look like an orphan
    and page for a dozen false positives. `error` is the honest verdict for both."""
    _orphan_clients(
        monkeypatch,
        live=["site-api", "daily-brief-sender"],
        managed={},
        cfn_raises=RuntimeError("AccessDenied: not authorized to perform cloudformation:ListStackResources"),
    )
    res = ds.check_orphan_functions()
    assert res["status"] == "error"
    assert "list_stack_resources" in res["detail"]
    assert "orphans" not in res, "a check that could not read IaC must not publish an orphan list"


# ═════════════════════════════════════════════════════════════════════════════
# C. check_oidc_iam — the drift half was proved; the cannot-observe half was not
# ═════════════════════════════════════════════════════════════════════════════
class _Completed:
    def __init__(self, returncode, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def test_oidc_iam_cannot_run_the_comparator_is_error_not_clean(monkeypatch):
    """(b) CANNOT-OBSERVE — the delegated comparator not running at all (missing file,
    interpreter gone, timeout) must be `error`, never the `clean` that a returncode of
    0 would produce."""
    import subprocess

    def _boom(*a, **k):
        raise FileNotFoundError("planted: deploy/verify_oidc_iam.py is missing")

    monkeypatch.setattr(subprocess, "run", _boom)
    res = ds.check_oidc_iam()
    assert res["status"] == "error"
    assert "verify_oidc_iam" in res["detail"] and "planted" in res["detail"]


def test_oidc_iam_nonzero_exit_without_drift_lines_still_reports_drift(monkeypatch):
    """SCOPE, recorded as a test rather than as prose: the check maps ANY non-zero exit
    to `drift`, and only harvests `[DRIFT]`-prefixed stdout lines for the detail. A
    comparator that dies with a traceback (exit 1, no `[DRIFT]` lines) therefore reads
    as drift with an EMPTY mismatch list — loud, but mislabelled. Recorded so `drift`
    here is not read as 'a specific identity changed'."""
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(1, "Traceback (most recent call last):\nboto3 not installed\n"))
    res = ds.check_oidc_iam()
    assert res["status"] == "drift"
    assert res["mismatches"] == []


# ═════════════════════════════════════════════════════════════════════════════
# D. check_doc_literals — no proof of either half existed before this file
# ═════════════════════════════════════════════════════════════════════════════
class _FakeCloudWatch:
    def __init__(self, metric_pages, composite=0, raises=None):
        self._pages, self._composite, self._raises = metric_pages, composite, raises

    def describe_alarms(self, **kw):  # noqa: N803
        if self._raises:
            raise self._raises
        idx = 0 if not kw.get("NextToken") else int(kw["NextToken"])
        page = self._pages[idx]
        out = {
            "MetricAlarms": [{"AlarmName": f"alarm-{idx}-{i}"} for i in range(page)],
            "CompositeAlarms": [{"AlarmName": f"composite-{i}"} for i in range(self._composite if idx == 0 else 0)],
        }
        if idx + 1 < len(self._pages):
            out["NextToken"] = str(idx + 1)
        return out


def _documented_alarm_count():
    import sync_doc_metadata as sdm

    return dict(sdm.PLATFORM_FACTS)["alarm_count"]


def test_doc_literals_clean_when_live_alarm_count_matches_the_documented_fact(monkeypatch):
    """Baseline against the REAL documented literal (never a hand-typed number here —
    that is the drift this check exists to catch, reproduced in its own test)."""
    documented = _documented_alarm_count()
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCloudWatch([documented]))
    res = ds.check_doc_literals()
    assert res["status"] == "clean" and res["mismatches"] == []


def test_doc_literals_detects_a_planted_alarm_count_divergence(monkeypatch):
    """(a) DETECT — the R22 shape: live alarms silently outran the documented count.
    Plant exactly the documented count PLUS ONE."""
    documented = _documented_alarm_count()
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCloudWatch([documented + 1]))
    res = ds.check_doc_literals()
    assert res["status"] == "drift"
    assert res["mismatches"][0]["fact"] == "alarm_count"
    assert res["mismatches"][0]["documented"] == documented
    assert res["mismatches"][0]["live"] == documented + 1
    assert "sync_doc_metadata" in res["mismatches"][0]["fix"], "a drift finding nobody can act on is half a finding"


def test_doc_literals_counts_every_page_and_composite_alarms_too(monkeypatch):
    """Non-vacuity of the count itself: a check that read only page 1 would under-count
    and false-red forever. Two pages plus composites must sum."""
    monkeypatch.setattr(ds, "_client", lambda *a, **k: _FakeCloudWatch([100, 7], composite=3))
    res = ds.check_doc_literals()
    assert res["mismatches"][0]["live"] == 110


def test_doc_literals_cannot_read_cloudwatch_is_error_not_clean(monkeypatch):
    """(b) CANNOT-OBSERVE — an unreadable alarm list must be `error`. The #3156 shape
    would be to treat the exception as "0 alarms" or to fall back to the documented
    number and compare it against itself, reporting green while measuring nothing."""
    monkeypatch.setattr(
        ds,
        "_client",
        lambda *a, **k: _FakeCloudWatch([], raises=RuntimeError("AccessDenied: cloudwatch:DescribeAlarms")),
    )
    res = ds.check_doc_literals()
    assert res["status"] == "error"
    assert "describe_alarms" in res["detail"]
    assert res["status"] != "clean"


def test_doc_literals_unreadable_fact_source_is_error_not_clean(monkeypatch):
    """(b) CANNOT-OBSERVE, other side — the DOCUMENTED half unreadable. Since #3101 the
    literals are generated (`lambdas/web/platform_counts.py`); an import failure of the
    fact module must say so rather than compare against an empty dict and pass."""
    monkeypatch.delitem(sys.modules, "sync_doc_metadata", raising=False)
    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "sync_doc_metadata":
            raise ImportError("planted: sync_doc_metadata unimportable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    res = ds.check_doc_literals()
    assert res["status"] == "error"
    assert "import sync_doc_metadata" in res["detail"]


# ═════════════════════════════════════════════════════════════════════════════
# E. THE COVERAGE REGISTRY — derived from the census, so a NEW sentinel check
#    without proofs is visible instead of silently unproven
# ═════════════════════════════════════════════════════════════════════════════
#
# The index below is the only hand-written thing here, and deliberately so: which
# test proves which half is a claim a human makes and a reviewer checks. What is NOT
# hand-written is the POPULATION — it comes from `gate_census.discover_sentinel_gates`,
# so adding a `check_*` to drift_sentinel.py or one of its siblings fails
# `test_every_sentinel_gate_in_the_census_has_both_halves_indexed` until its proofs
# are written and named. That is the "recurring check keeps the inventory honest" box
# applied to one family.
#
# HONEST LIMIT of the resolver: it asserts each named test FUNCTION EXISTS in the
# named file (AST, no execution), which catches the realistic rot — a rename or a
# deletion silently emptying a cited proof. It does not re-run the assertion; the
# premerge lane does that by running the files themselves.

_DS = "tests/test_drift_sentinel.py"
_HERE = "tests/test_sentinel_canfail_2578.py"
_REPL = "tests/test_raw_replication_dil027.py"

PROOF_INDEX: dict[str, dict[str, object]] = {
    # ── the ten defined in deploy/drift_sentinel.py ───────────────────────────
    "sentinel::deploy/drift_sentinel.py::check_cfn_drift": {
        "detect": (_DS, "test_check_cfn_drift_real_drift_reports_alongside_filtered_noise"),
        "cannot_observe": (_DS, "test_cfn_drift_all_access_denied_escalates_to_error"),
        "note": "#1227: all-AccessDenied escalates to `error` (dead capability), a transient stays `degraded` — both directions proved.",
    },
    "sentinel::deploy/drift_sentinel.py::check_postflight": {
        "detect": (_HERE, "test_postflight_detects_a_planted_retired_layer_reference"),
        "cannot_observe": (_HERE, "test_postflight_unimportable_module_is_error_not_a_crashed_sweep"),
        "note": "NEW 2026-08-25. The cannot-observe half found a live defect: the import was unguarded and darked the whole sweep.",
    },
    "sentinel::deploy/drift_sentinel.py::check_orphan_functions": {
        "detect": (_HERE, "test_orphan_functions_detects_a_planted_out_of_band_function"),
        "cannot_observe": (_HERE, "test_orphan_functions_cannot_list_live_functions_is_error_not_clean"),
        "note": "NEW 2026-08-25. Both vacuum directions proved — an empty live set reads clean, an empty managed set reds everything.",
    },
    "sentinel::deploy/drift_sentinel.py::check_oidc_iam": {
        "detect": (_DS, "test_oidc_iam_drift_surfaces_mismatch_lines"),
        "cannot_observe": (_HERE, "test_oidc_iam_cannot_run_the_comparator_is_error_not_clean"),
        "note": "cannot-observe half NEW 2026-08-25; scope recorded separately (any non-zero exit maps to drift, even a traceback).",
    },
    "sentinel::deploy/drift_sentinel.py::check_bucket_policy": {
        "detect": (_DS, "test_bucket_policy_drift_when_a_prefix_is_dropped"),
        "cannot_observe": (_DS, "test_bucket_policy_error_is_soft"),
        "note": "Pre-existing. Detect proved on BOTH shapes: a dropped prefix and a missing Deny statement entirely.",
    },
    "sentinel::deploy/drift_sentinel.py::check_s3_lifecycle": {
        "detect": (_DS, "test_s3_lifecycle_drift_when_live_rule_weakened"),
        "cannot_observe": (_DS, "test_s3_lifecycle_error_when_declared_file_unreadable"),
        "note": "Pre-existing (DIL-026). Cannot-observe proved on BOTH sides — unreadable live config and unreadable declared JSON.",
    },
    "sentinel::deploy/drift_sentinel.py::check_dynamodb_ttl": {
        "detect": (_DS, "test_dynamodb_ttl_drift_when_live_attribute_is_the_951_mismatch"),
        "cannot_observe": (_DS, "test_dynamodb_ttl_error_is_soft"),
        "note": (
            "NEW 2026-08-25 (#2799 residual table-config-noop-ttl, #951 recurrence). Declared side is "
            "cdk/stacks/constants.py TABLE_TTL_ATTRIBUTE; live side is describe_time_to_live. Detect proves "
            "the exact #951 shape (ENABLED but on the wrong attribute), not just wholesale disablement."
        ),
    },
    "sentinel::deploy/drift_sentinel.py::check_site_sha_ancestry": {
        "detect": (_DS, "test_site_sha_ancestry_drift_when_sha_diverged"),
        "cannot_observe": (_DS, "test_site_sha_ancestry_error_on_fetch_failure"),
        "note": "Pre-existing (#751). A version.json with no `build` field is also proved to be `error`, not clean.",
    },
    "sentinel::deploy/drift_sentinel.py::check_doc_literals": {
        "detect": (_HERE, "test_doc_literals_detects_a_planted_alarm_count_divergence"),
        "cannot_observe": (_HERE, "test_doc_literals_cannot_read_cloudwatch_is_error_not_clean"),
        "note": "NEW 2026-08-25. Both halves of the comparison proved unreadable-loud: the live alarm list and the documented fact module.",
    },
    "sentinel::deploy/drift_sentinel.py::check_codeql_alerts": {
        "detect": (_DS, "test_planted_open_alert_reaches_the_triage_path"),
        "cannot_observe": (_DS, "test_unreadable_alert_list_also_reaches_the_triage_path"),
        "note": "#3112, cited not re-proved. The bar this family is measured against: both halves reach drift_report.as_signal, not just the record.",
    },
    "sentinel::deploy/drift_sentinel.py::check_hae_webhook_ingress": {
        "detect": (_DS, "test_hae_webhook_ingress_drift_when_orphan_grant_also_present"),
        "cannot_observe": (_DS, "test_hae_webhook_ingress_error_soft_on_get_policy_failure"),
        "note": "Pre-existing (#1946). Detect proved on all three shapes: a second grant, a widened SourceArn, and zero grants.",
    },
    # ── the five in the #1665-extracted siblings ──────────────────────────────
    "sentinel::deploy/sentinel_github.py::check_github_config": {
        "detect": (_DS, "test_github_config_fires_on_live_gateless_environment"),
        "cannot_observe": (_DS, "test_github_config_scope_gap_is_needs_owner_not_red"),
        "note": (
            "Pre-existing (#1320). SCOPE: cannot-observe reports the third status `unavailable`, which aggregates as CLEAN at sweep "
            "level and never reaches as_signal — deliberate fail-soft (a public fork must not red-wall), and honest because the "
            "status is distinct and print_summary emits a needs-owner line naming the exact PAT permission. It is NOT the #3156 "
            "shape: nothing falls back to a stale value while claiming it measured."
        ),
    },
    "sentinel::deploy/sentinel_github.py::check_github_push_runs": {
        "detect": (_DS, "test_push_runs_drift_when_head_stalled"),
        "cannot_observe": (_DS, "test_push_runs_scope_gap_is_needs_owner_not_red"),
        "note": "Pre-existing (#1544). Same `unavailable` scope as check_github_config above. False-positive suppression proved too.",
    },
    "sentinel::deploy/sentinel_quota.py::check_github_quota": {
        "detect": (_DS, "test_github_quota_billing_over_70pct_private_warns_and_drifts"),
        "cannot_observe": (_DS, "test_github_quota_billing_unavailable_falls_back_to_proxy"),
        "note": (
            "Pre-existing (#1334/#1453). SCOPE: the billing PAT is usually absent, so the STEADY STATE of this check is "
            "`unavailable` — its drift half is real but rarely armed live. The fallback is a labelled proxy that prints its own "
            "reason, never a silent substitution."
        ),
    },
    "sentinel::deploy/sentinel_replication.py::check_raw_replication": {
        "detect": (_REPL, "test_no_replication_configuration_is_loud_drift"),
        "cannot_observe": (_REPL, "test_nothing_observable_is_degraded_not_clean"),
        "note": "Pre-existing (DIL-027). The strongest pre-existing pair: eight distinct detect shapes and an explicit vacuous-pass guard.",
    },
    "sentinel::deploy/sentinel_cadence.py::check_sentinel_cadence": {
        "detect": (_DS, "test_sentinel_cadence_drift_on_a_planted_gap"),
        "cannot_observe": (_DS, "test_sentinel_cadence_fails_closed_when_the_log_is_unreadable"),
        "note": "#3130, cited not re-proved — arrived 2026-08-24 with nine mutation proofs including an unreadable log failing CLOSED.",
    },
}


def _census_sentinel_ids():
    return {g.id for g in gc.discover_sentinel_gates(Path(_ROOT))[0]}


def test_every_sentinel_gate_in_the_census_has_both_halves_indexed():
    """The derived-set assertion. Population from the census (family 6, #3160), never
    a hand list — so a new sentinel check enters this file's scope automatically."""
    live = _census_sentinel_ids()
    missing = sorted(live - set(PROOF_INDEX))
    assert not missing, (
        "sentinel check(s) with no can-it-fail proof recorded (epic #2578 box 2). Write both halves "
        "— plant the condition it detects, AND plant the state where it cannot observe — then index "
        "them here:\n  " + "\n  ".join(missing)
    )
    stale = sorted(set(PROOF_INDEX) - live)
    assert not stale, f"PROOF_INDEX names gate id(s) the census no longer finds — a check was renamed or removed:\n  {stale}"


@pytest.mark.parametrize("gate_id", sorted(PROOF_INDEX))
def test_each_indexed_proof_names_a_test_that_actually_exists(gate_id):
    """Resolve both halves to real test functions. This is what stops a cited proof
    from rotting into a name nobody notices is gone (the #2938 lesson: the census
    honestly said `unproven`, and nobody ever went and looked)."""
    entry = PROOF_INDEX[gate_id]
    for half in ("detect", "cannot_observe"):
        value = entry[half]
        if isinstance(value, str):
            # A structurally N/A half must state its reason and its date, never be blank.
            assert value.startswith("N/A "), f"{gate_id}/{half}: an exempted half must start with 'N/A ' and say why"
            assert len(value) > 60, f"{gate_id}/{half}: exemption reason too terse to review"
            continue
        rel, func = value
        path = Path(_ROOT, rel)
        assert path.exists(), f"{gate_id}/{half}: cited file {rel} does not exist"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert func in names, f"{gate_id}/{half}: cited proof {rel}::{func} no longer exists — renamed or deleted"


@pytest.mark.parametrize("gate_id", sorted(PROOF_INDEX))
def test_each_indexed_entry_carries_a_note_a_reviewer_can_use(gate_id):
    note = PROOF_INDEX[gate_id]["note"]
    assert isinstance(note, str) and len(note) > 60, f"{gate_id}: note too terse — scope and provenance are part of the verdict"


def test_the_coverage_assertion_itself_can_fail(monkeypatch):
    """Guard-the-SET, mutation-proved: plant a sentinel check the index does not know
    about and the coverage test must FAIL. Without this, an index that silently stopped
    reading the census would report full coverage forever — the exact shape of #3156."""
    planted = "sentinel::deploy/drift_sentinel.py::check_a_thing_nobody_indexed"

    class _Fake:
        id = planted

    monkeypatch.setattr(gc, "discover_sentinel_gates", lambda root: ([_Fake()], {}))
    with pytest.raises(AssertionError) as exc:
        test_every_sentinel_gate_in_the_census_has_both_halves_indexed()
    assert planted in str(exc.value)


# ═════════════════════════════════════════════════════════════════════════════
# F. The census must actually RECORD these verdicts — a proof the inventory
#    cannot see is the #3129 problem restated
# ═════════════════════════════════════════════════════════════════════════════
def test_every_indexed_sentinel_gate_carries_a_proven_verdict_in_the_census():
    """The audit derived "7 of 538" from `gate_census`'s own verdict field. A proof
    that lives only in a test file does not move that number, so each entry above is
    also recorded in `PROVEN_CAN_FAIL` and must come back as `can-fail (proven)`."""
    census = gc.build_census(Path(_ROOT), families=("sentinel",))
    verdicts = {g["id"]: g["verdict"] for g in census["gates"]}
    unproven = sorted(gid for gid in PROOF_INDEX if verdicts.get(gid) != "can-fail (proven)")
    assert not unproven, (
        "these sentinel gates have proofs in the test suite but the census still reports them "
        "unproven — the verdict fraction will not move:\n  " + "\n  ".join(f"{g} -> {verdicts.get(g)}" for g in unproven)
    )
    assert not census["orphan_proofs"], census["orphan_proofs"]


def test_the_recorded_sentinel_proofs_point_at_the_tests_in_this_index():
    """Cross-check the two hand-written registries against each other: every sentinel
    `Proof.command` must name the test file its proof actually lives in, so a reader
    who starts from the census lands on a runnable command."""
    for gate_id, entry in PROOF_INDEX.items():
        proof = gc.PROVEN_CAN_FAIL.get(gate_id)
        assert proof is not None, f"{gate_id}: indexed here but absent from gate_census.PROVEN_CAN_FAIL"
        cited_files = {v[0] for v in (entry["detect"], entry["cannot_observe"]) if isinstance(v, tuple)}
        assert any(f in proof.command for f in cited_files), (
            f"{gate_id}: the recorded command {proof.command!r} does not name any of the files "
            f"holding its proofs ({sorted(cited_files)})"
        )
        assert proof.gate_name == gate_id.rsplit("::", 1)[-1]


def test_the_sentinel_proofs_are_dated_after_the_family_became_visible():
    """#3160 made this family enumerable on 2026-08-25. A sentinel proof dated before
    that is a proof recorded against a gate the census could not see — the #2638
    stale-proof lesson, applied forwards."""
    for gate_id in PROOF_INDEX:
        proof = gc.PROVEN_CAN_FAIL[gate_id]
        assert proof.proved_on >= "2026-08-24", f"{gate_id}: proved_on {proof.proved_on} predates the family's own census entry"


def test_json_report_is_still_parseable_with_the_new_verdicts():
    """Cheap regression on the surface the audit actually reads."""
    census = gc.build_census(Path(_ROOT), families=("sentinel",))
    payload = json.loads(json.dumps(census, default=str))
    proven = [g for g in payload["gates"] if g["verdict"] == "can-fail (proven)"]
    assert len(proven) == len(PROOF_INDEX) == 16
