"""tests/test_security_log_retention_3278.py — the security-tier log-retention parity
guard (#3278): the governance doc, the CDK derivation, the weekly sentinel check and the
apply script all read ONE declared value, and each seam is mutation-proved.

THE DEFECT (measured 2026-08-30, read-only, all 17 enabled regions)
  docs/DATA_GOVERNANCE.md:141 promised 90 days for canary / key-rotator / dlq-consumer /
  cf-auth since 2026-05-17. No log group anywhere carried 90: the CDK-owned three sat at
  30 (`lambda_helpers.py` set ONE_MONTH uniformly), and the two Lambda@Edge auth gates —
  never CDK-created — were 30 in us-east-1/us-west-2 (hand-set once) and NEVER_EXPIRE in
  eu-west-2, eu-west-1, eu-central-1, us-east-2, us-west-1 (replica groups nobody set),
  holding up to 2.5 MB of auth-gate output each. Nothing compared the doc to live.

WHAT IS PROVED HERE (family-6 two-half bar, #2578/#3112)
  A. the doc row is asserted against the registry — a "doc-down" reconcile (90→30 in
     prose) and a dropped function both RED; the number is a decision, not an inheritance
  B. CDK derives the tier from the registry by construction (no literal, no kwarg), and
     the regional/edge split in the registry matches which functions CDK actually creates
  C. `check_log_retention` — (a) DETECT on the exact live shape, each group named;
     (b) CANNOT-OBSERVE on an unlistable region set, an unreadable region, and a zero-group
     sweep → `error`, never `clean`; drift outranks a partial-observation caveat
  D. the apply script writes nothing on a dry run, writes exactly the drifted set with
     `--apply`, re-observes rather than trusting its own send, and is a no-op when clean

All offline: fakes are built to the real boto3 call shapes (fixture-must-be-the-wire);
the live fixture is the 2026-08-30 sweep verbatim.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "remediation"), os.path.join(_ROOT, "cdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import apply_log_retention as apply_cli  # noqa: E402
import drift_report  # noqa: E402
import drift_sentinel as ds  # noqa: E402
import sentinel_log_retention as slr  # noqa: E402  — the OWNING module; a re-export is NOT a patch point
from stacks import constants as C  # noqa: E402

ROOT = Path(_ROOT)
DOC = ROOT / "docs" / "DATA_GOVERNANCE.md"
HELPERS = ROOT / "cdk" / "stacks" / "lambda_helpers.py"

EDGE_FUNCTIONS = {"life-platform-cf-auth", "life-platform-buddy-auth"}
REGIONAL_FUNCTIONS = {"life-platform-canary", "life-platform-key-rotator", "life-platform-dlq-consumer"}


# ═════════════════════════════════════════════════════════════════════════════
# A. the doc row ↔ the registry
# ═════════════════════════════════════════════════════════════════════════════
def _log_rows(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("| Lambda CloudWatch Logs")]


def assert_doc_matches_registry(text: str) -> None:
    """The one assertion both the real-doc test and the mutation tests share."""
    rows = _log_rows(text)
    security = [r for r in rows if "security" in r.lower()]
    assert len(security) == 1, f"expected exactly one security-tier row in the Logs table, found {len(security)}"
    row = security[0]
    m = re.search(r"\*\*(\d+) days\*\*", row)
    assert m, "security-tier row names no bold day-count"
    assert int(m.group(1)) == C.LOG_RETENTION_SECURITY_DAYS, (
        f"docs/DATA_GOVERNANCE.md says {m.group(1)} days for the security tier; "
        f"cdk/stacks/constants.py declares {C.LOG_RETENTION_SECURITY_DAYS}. Move BOTH, never one (#3278)."
    )
    for fn in C.SECURITY_TIER_LOG_FUNCTIONS:
        short = fn.removeprefix("life-platform-")
        assert short in row, f"{fn} is in SECURITY_TIER_LOG_FUNCTIONS but the governance row does not name '{short}'"
    most = [r for r in rows if "(most)" in r]
    assert len(most) == 1, "expected exactly one '(most)' row"
    m2 = re.search(r"\*\*(\d+) days\*\*", most[0])
    assert m2 and int(m2.group(1)) == C.LOG_RETENTION_DEFAULT_DAYS


def test_doc_row_matches_the_registry():
    assert_doc_matches_registry(DOC.read_text(encoding="utf-8"))


def test_doc_guard_reds_on_a_planted_doc_down_reconcile():
    """The acceptance's named anti-outcome: silently editing the table down to match
    live. Plant 90 -> 30 in the security row only; the guard must fire."""
    text = DOC.read_text(encoding="utf-8")
    row = [r for r in _log_rows(text) if "security" in r.lower()][0]
    mutated = text.replace(row, row.replace(f"**{C.LOG_RETENTION_SECURITY_DAYS} days**", "**30 days**", 1), 1)
    assert mutated != text
    with pytest.raises(AssertionError, match="Move BOTH"):
        assert_doc_matches_registry(mutated)


def test_doc_guard_reds_when_a_registered_function_leaves_the_row():
    text = DOC.read_text(encoding="utf-8")
    row = [r for r in _log_rows(text) if "security" in r.lower()][0]
    mutated = text.replace(row, row.replace("buddy-auth", "", 1), 1)
    assert mutated != text
    with pytest.raises(AssertionError, match="buddy-auth"):
        assert_doc_matches_registry(mutated)


# ═════════════════════════════════════════════════════════════════════════════
# B. the registry and the CDK derivation
# ═════════════════════════════════════════════════════════════════════════════
def test_registry_covers_every_function_the_issue_enumerates():
    assert set(C.SECURITY_TIER_LOG_FUNCTIONS) == EDGE_FUNCTIONS | REGIONAL_FUNCTIONS
    assert set(C.SECURITY_TIER_LOG_FUNCTIONS.values()) <= {"regional", "edge"}
    assert (
        C.LOG_RETENTION_SECURITY_DAYS > C.LOG_RETENTION_DEFAULT_DAYS
    ), "a 'security tier' that retains less than the default is a misnomer"


def test_registry_kind_matches_what_cdk_actually_creates():
    """`regional` must be a real create_platform_lambda function_name in cdk/stacks/ (so
    the derivation in lambda_helpers reaches it); `edge` must NOT be (CDK genuinely cannot
    own it — the day cf-auth is adopted into CDK, flip the kind and this reds until then)."""
    cdk_src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "cdk" / "stacks").glob("*.py"))
    for fn, kind in C.SECURITY_TIER_LOG_FUNCTIONS.items():
        created = f'function_name="{fn}"' in cdk_src
        assert created == (kind == "regional"), f"{fn} is declared {kind!r} but CDK {'does' if created else 'does not'} create it"


def test_log_retention_days_for_derives_the_tier():
    for fn in C.SECURITY_TIER_LOG_FUNCTIONS:
        assert C.log_retention_days_for(fn) == C.LOG_RETENTION_SECURITY_DAYS
    assert C.log_retention_days_for("daily-brief") == C.LOG_RETENTION_DEFAULT_DAYS


def test_log_group_names_include_the_edge_replica_shape():
    names = C.security_tier_log_group_names()
    assert names["/aws/lambda/life-platform-canary"] == "life-platform-canary"
    assert names[f"/aws/lambda/{C.EDGE_HOME_REGION}.life-platform-cf-auth"] == "life-platform-cf-auth"
    assert names[f"/aws/lambda/{C.EDGE_HOME_REGION}.life-platform-buddy-auth"] == "life-platform-buddy-auth"
    assert f"/aws/lambda/{C.EDGE_HOME_REGION}.life-platform-canary" not in names


def test_lambda_helpers_derives_retention_from_the_registry_not_a_literal():
    src = HELPERS.read_text(encoding="utf-8")
    assert "log_retention_days_for(function_name)" in src, "#3278: lambda_helpers must derive the tier per function_name"
    assert "log_retention=logs.RetentionDays." not in src, "the uniform ONE_MONTH literal (the defect #3278 named) is back"


def test_lambda_helpers_enum_map_covers_every_declared_tier():
    """Synth fails CLOSED (KeyError) on an unmapped tier — so the map must cover both
    declared tiers, asserted offline without an aws_cdk import."""
    tree = ast.parse(HELPERS.read_text(encoding="utf-8"))
    keys = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_RETENTION_DAYS_TO_ENUM" for t in node.targets):
            keys = {ast.literal_eval(k) for k in node.value.keys}
    assert keys is not None, "_RETENTION_DAYS_TO_ENUM not found in lambda_helpers.py"
    assert {C.LOG_RETENTION_DEFAULT_DAYS, C.LOG_RETENTION_SECURITY_DAYS} <= keys


# ═════════════════════════════════════════════════════════════════════════════
# C. check_log_retention — the two halves
# ═════════════════════════════════════════════════════════════════════════════
_ALL_REGIONS = [
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3", "ap-south-1", "ap-southeast-1", "ap-southeast-2",
    "ca-central-1", "eu-central-1", "eu-north-1", "eu-west-1", "eu-west-2", "eu-west-3", "sa-east-1",
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
]  # fmt: skip
_CF = "/aws/lambda/us-east-1.life-platform-cf-auth"
_BUDDY = "/aws/lambda/us-east-1.life-platform-buddy-auth"


def _lg(name, retention=None, stored=0):
    """One describe_log_groups element, on the wire shape: `retentionInDays` is ABSENT
    (not null) when the group never expires."""
    d = {"logGroupName": name, "storedBytes": stored, "arn": f"arn:aws:logs:x:205930651321:log-group:{name}:*"}
    if retention is not None:
        d["retentionInDays"] = retention
    return d


def _live_2026_08_30():
    """The measured shape, verbatim: replicas NEVER_EXPIRE in five regions, 30 in the two
    home regions, the three regional functions at 30 in us-west-2."""
    state = {}
    for r, cf_b, bd_b in (("eu-west-2", 286673, 227567), ("eu-west-1", 182092, 1326), ("eu-central-1", 2552389, 102114),
                          ("us-east-2", 822330, 43957), ("us-west-1", 676063, 6264)):  # fmt: skip
        state[r] = {_CF: _lg(_CF, None, cf_b), _BUDDY: _lg(_BUDDY, None, bd_b)}
    state["us-east-1"] = {_CF: _lg(_CF, 30), _BUDDY: _lg(_BUDDY, 30)}
    state["us-west-2"] = {
        _CF: _lg(_CF, 30),
        _BUDDY: _lg(_BUDDY, 30),
        "/aws/lambda/life-platform-canary": _lg("/aws/lambda/life-platform-canary", 30, 3259572),
        "/aws/lambda/life-platform-key-rotator": _lg("/aws/lambda/life-platform-key-rotator", 30),
        "/aws/lambda/life-platform-dlq-consumer": _lg("/aws/lambda/life-platform-dlq-consumer", 30, 113783),
    }
    return state


def _all_at(days):
    state = _live_2026_08_30()
    for groups in state.values():
        for lg in groups.values():
            lg["retentionInDays"] = days
    return state


class _FakeEC2:
    def __init__(self, regions, raise_exc=None):
        self._regions, self._raise = regions, raise_exc

    def describe_regions(self, **kwargs):
        if self._raise:
            raise self._raise
        assert kwargs.get("Filters"), "must filter to enabled regions, never AllRegions"
        return {"Regions": [{"RegionName": r, "OptInStatus": "opt-in-not-required"} for r in self._regions]}


class _FakeLogs:
    """Prefix semantics on the wire: returns EVERY group whose name starts with the
    prefix (so an exact-name mismatch has to be filtered by the caller)."""

    def __init__(self, region, state, raise_exc=None, puts=None):
        self._region, self._state, self._raise, self._puts = region, state, raise_exc, puts

    def describe_log_groups(self, logGroupNamePrefix, nextToken=None):  # noqa: N803 — boto3 kwarg casing
        if self._raise:
            raise self._raise
        groups = [dict(v) for k, v in self._state.get(self._region, {}).items() if k.startswith(logGroupNamePrefix)]
        return {"logGroups": groups}

    def put_retention_policy(self, logGroupName, retentionInDays):  # noqa: N803
        if self._raise:
            raise self._raise
        self._state[self._region][logGroupName]["retentionInDays"] = retentionInDays
        if self._puts is not None:
            self._puts.append((self._region, logGroupName, retentionInDays))
        return {}


def _wire(monkeypatch, state, regions=None, ec2_raise=None, logs_raise_in=(), puts=None):
    regions = _ALL_REGIONS if regions is None else regions

    def _client(service, region=slr.REGION):
        if service == "ec2":
            return _FakeEC2(regions, ec2_raise)
        if service == "logs":
            exc = RuntimeError(f"planted: AccessDeniedException in {region}") if region in logs_raise_in else None
            return _FakeLogs(region, state, exc, puts)
        raise AssertionError(f"unexpected client {service}")

    monkeypatch.setattr(slr, "_client", _client)


def test_clean_when_every_group_is_at_the_declared_tier(monkeypatch):
    _wire(monkeypatch, _all_at(C.LOG_RETENTION_SECURITY_DAYS))
    res = slr.check_log_retention()
    assert res["status"] == "clean"
    assert res["groups_found"] == 17
    assert res["regions_swept"] == _ALL_REGIONS
    assert res["mismatches"] == [] and res["unreadable_regions"] == []


def test_detects_the_live_shape_every_group_named(monkeypatch):
    """(a) DETECT on the 2026-08-30 sweep: 17 groups, 17 mismatches, each named with its
    region and live value, NEVER_EXPIRE spelled out, and the fix command in the finding."""
    _wire(monkeypatch, _live_2026_08_30())
    res = slr.check_log_retention()
    assert res["status"] == "drift"
    assert len(res["mismatches"]) == 17
    never = {(m["region"], m["log_group"]) for m in res["mismatches"] if m["live"] is None}
    assert len(never) == 10 and ("eu-central-1", _CF) in never
    assert ("us-west-2", "/aws/lambda/life-platform-canary") in {(m["region"], m["log_group"]) for m in res["mismatches"]}
    assert "NEVER_EXPIRE" in res["detail"] and "eu-central-1" in res["detail"]
    assert slr.APPLY_COMMAND in res["detail"]


def test_detects_a_single_wrong_number_not_just_never_expire(monkeypatch):
    state = _all_at(C.LOG_RETENTION_SECURITY_DAYS)
    state["eu-west-1"][_BUDDY]["retentionInDays"] = 60
    _wire(monkeypatch, state)
    res = slr.check_log_retention()
    assert res["status"] == "drift"
    assert res["mismatches"] == [{"region": "eu-west-1", "log_group": _BUDDY, "live": 60, "declared": C.LOG_RETENTION_SECURITY_DAYS}]


def test_a_region_with_no_security_groups_is_not_drift(monkeypatch):
    """Absence is not a finding — most regions never served the edge functions. The
    check guards the SET of existing groups; a region without any simply contributes none."""
    state = _all_at(C.LOG_RETENTION_SECURITY_DAYS)
    _wire(monkeypatch, state)  # ap-*/ca-/sa- regions have no entries in state
    res = slr.check_log_retention()
    assert res["status"] == "clean"
    assert {g["region"] for g in res["groups"]} == set(state)


def test_prefix_read_never_matches_a_longer_name(monkeypatch):
    """describe_log_groups is a PREFIX read; `...-canary-v2` at NEVER_EXPIRE must not be
    counted as canary (false drift) nor as canary's own group (false clean)."""
    state = _all_at(C.LOG_RETENTION_SECURITY_DAYS)
    state["us-west-2"]["/aws/lambda/life-platform-canary-v2"] = _lg("/aws/lambda/life-platform-canary-v2", None)
    _wire(monkeypatch, state)
    res = slr.check_log_retention()
    assert res["status"] == "clean"
    assert all(g["log_group"] != "/aws/lambda/life-platform-canary-v2" for g in res["groups"])


def test_cannot_enumerate_regions_is_error_naming_the_grant(monkeypatch):
    """(b) CANNOT-OBSERVE: DescribeRegions denied. A region-less sweep would silently miss
    every replica group — so this is `error` naming the exact IAM action, never `clean`."""
    _wire(monkeypatch, _all_at(90), ec2_raise=RuntimeError("planted: UnauthorizedOperation ec2:DescribeRegions"))
    res = slr.check_log_retention()
    assert res["status"] == "error"
    assert slr.REGION_ENUMERATION_GRANT in res["detail"]
    assert "github-actions-remediation-role" in res["detail"]


def test_unreadable_region_is_error_not_clean(monkeypatch):
    """(b) one region's logs API refuses; every other region is clean. A partial sweep
    that reported clean would be the #3156 believe-you-measured shape."""
    _wire(monkeypatch, _all_at(C.LOG_RETENTION_SECURITY_DAYS), logs_raise_in=("eu-central-1",))
    res = slr.check_log_retention()
    assert res["status"] == "error"
    assert res["unreadable_regions"][0]["region"] == "eu-central-1"
    assert "eu-central-1" in res["detail"] and "not clean" in res["detail"]


def test_drift_outranks_an_unreadable_region_and_still_names_it(monkeypatch):
    _wire(monkeypatch, _live_2026_08_30(), logs_raise_in=("ap-south-1",))
    res = slr.check_log_retention()
    assert res["status"] == "drift"
    assert "ap-south-1" in res["detail"] and "unreadable" in res["detail"]


def test_zero_groups_anywhere_is_error_not_clean(monkeypatch):
    """(b) the vacuous sweep (#1189): the functions exist and log, so finding nothing
    means the candidate names or the region set are wrong — never a pass."""
    _wire(monkeypatch, {})
    res = slr.check_log_retention()
    assert res["status"] == "error"
    assert "ZERO" in res["detail"]


# ── the sweep seam: drift must reach the triage path, not just the record ────
_SWEEP_STUBS = {
    "check_cfn_drift": {"status": "clean", "stacks": {}},
    "check_orphan_functions": {"status": "clean", "orphans": []},
    "check_bucket_policy": {"status": "clean", "missing_prefixes": []},
    "check_s3_lifecycle": {"status": "clean", "missing_rule_ids": [], "extra_rule_ids": [], "changed_rule_ids": []},
    "check_dynamodb_ttl": {"status": "clean", "declared_attribute": "ttl", "live_attribute": "ttl", "live_status": "ENABLED"},
    "check_oidc_iam": {"status": "clean"},
    "check_doc_literals": {"status": "clean", "mismatches": []},
    "check_site_sha_ancestry": {"status": "clean", "live_sha": "deadbeef"},
    "check_github_config": {"status": "clean", "surfaces": {}},
    "check_github_push_runs": {"status": "clean", "stalled": [], "gap_commits": []},
    "check_github_quota": {"status": "unavailable", "billing_api": {"available": False, "detail": "test"}, "top_workflows_7d": []},
    "check_codeql_alerts": {"status": "clean", "open_count": 0, "sample": []},
    "check_hae_webhook_ingress": {"status": "clean", "cdk_api_id": "x", "invoke_statements": []},
    "check_raw_replication": {"status": "clean", "objects_confirmed": 2},
    "check_sentinel_cadence": {"status": "clean", "missing_dates": [], "latest_date": "2026-08-28", "days_stale": 1},
    "check_eventbridge_rules": {"status": "clean", "live_count": 96, "managed_count": 93, "enabled_targetless": [], "out_of_iac": []},
}


def test_sweep_log_retention_drift_reaches_the_triage_path(monkeypatch):
    for name, value in _SWEEP_STUBS.items():
        monkeypatch.setattr(ds, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(
        ds,
        "check_postflight",
        lambda: {"layer_uniformity": {"status": "clean"}, "config_drift": {"status": "clean"}, "asset_completeness": {"status": "clean"}},
    )
    _wire(monkeypatch, _live_2026_08_30())
    rec = ds.run_sweep()
    assert rec["status"] == "drift"
    assert "security-tier log retention diverges" in rec["summary"]
    sig = drift_report.as_signal(rec)
    assert sig is not None and sig["flagging"]["log_retention"]["status"] == "drift"
    assert sig["class"] == "needs-human"


# ═════════════════════════════════════════════════════════════════════════════
# D. the apply script
# ═════════════════════════════════════════════════════════════════════════════
def test_dry_run_writes_nothing_and_exits_nonzero_on_drift(monkeypatch, capsys):
    puts = []
    _wire(monkeypatch, _live_2026_08_30(), puts=puts)
    rc = apply_cli.main([])
    out = capsys.readouterr().out
    assert rc == 1 and puts == []
    assert out.count("FIX ") == 17 and "--apply" in out


def test_apply_writes_exactly_the_drifted_set_then_reobserves(monkeypatch, capsys):
    """Idempotent writer: puts land on the 17 drifted groups only, at the declared value,
    and the verdict comes from a RE-READ of the touched regions, not from the send."""
    puts = []
    state = _live_2026_08_30()
    _wire(monkeypatch, state, puts=puts)
    rc = apply_cli.main(["--apply"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert len(puts) == 17 and {p[2] for p in puts} == {C.LOG_RETENTION_SECURITY_DAYS}
    assert ("eu-central-1", _CF, C.LOG_RETENTION_SECURITY_DAYS) in puts
    assert all(lg["retentionInDays"] == C.LOG_RETENTION_SECURITY_DAYS for groups in state.values() for lg in groups.values())
    assert "every found group is at the declared tier" in out
    # second run: nothing left to write
    puts.clear()
    assert apply_cli.main(["--apply"]) == 0 and puts == []


def test_apply_reports_a_put_that_did_not_take(monkeypatch, capsys):
    """The send is not the verdict: a put that raises is printed FAILED and the exit stays
    non-zero because the re-read still shows the drift."""
    state = _live_2026_08_30()
    _wire(monkeypatch, state, puts=[])
    real_factory = slr._client

    def _flaky(service, region=slr.REGION):
        c = real_factory(service, region)
        if service == "logs" and region == "us-west-1":
            c._raise = None  # reads fine

            def _boom(logGroupName, retentionInDays):  # noqa: N803
                raise RuntimeError("planted: OperationAbortedException")

            c.put_retention_policy = _boom
        return c

    monkeypatch.setattr(slr, "_client", _flaky)
    rc = apply_cli.main(["--apply"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED us-west-1" in out


def test_apply_refuses_a_blind_sweep(monkeypatch, capsys):
    puts = []
    _wire(monkeypatch, {}, puts=puts)
    assert apply_cli.main(["--apply"]) == 1 and puts == []
    assert "blind sweep" in capsys.readouterr().out


def test_json_output_is_valid_json_with_the_observation(monkeypatch, capsys):
    _wire(monkeypatch, _live_2026_08_30())
    apply_cli.main(["--json"])
    out = capsys.readouterr().out
    doc = json.loads(out[: out.rindex("}") + 1])
    assert doc["declared_days"] == C.LOG_RETENTION_SECURITY_DAYS and len(doc["mismatches"]) == 17


# ═════════════════════════════════════════════════════════════════════════════
# E. the grant rode in the same PR (#2824 grant-with-consumer)
# ═════════════════════════════════════════════════════════════════════════════
def test_remediation_role_declares_the_region_enumeration_grant_in_both_twins():
    canonical = json.loads((ROOT / "infra" / "iam" / "github-actions-remediation-role.permissions.json").read_text())
    diag = [s for s in canonical["Statement"] if s.get("Sid") == "Diagnose"][0]
    assert slr.REGION_ENUMERATION_GRANT in diag["Action"]
    sh = (ROOT / "deploy" / "setup_remediation_role.sh").read_text(encoding="utf-8")
    assert f'"{slr.REGION_ENUMERATION_GRANT}"' in sh, "setup_remediation_role.sh must stay statement-identical to the canonical JSON"
