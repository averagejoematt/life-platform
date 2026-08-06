"""Tests for deploy/teardown_hae_orphan_api.py — the owner-run HAE orphan-API
cleanup (#1946). All hermetic (no AWS): every AWS-touching call is monkeypatched
onto a fake client, matching tests/test_drift_sentinel.py's pattern (the module
under test imports and reuses drift_sentinel.get_cdk_managed_hae_api_id, so both
share one derivation).

Covers: orphan detection (guard-the-SET — never a hand-pasted API id), the
zero-traffic re-measurement gate, dry-run vs --apply, and idempotency (a second
--apply run against an already-clean state is a no-op, not an error)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))

import drift_sentinel as ds  # noqa: E402
import teardown_hae_orphan_api as td  # noqa: E402

# ── fakes ─────────────────────────────────────────────────────────────────────


class _FakeCfn:
    def __init__(self, api_ids):
        self._api_ids = api_ids

    def list_stack_resources(self, StackName, NextToken=None):  # noqa: N803
        return {"StackResourceSummaries": [{"ResourceType": "AWS::ApiGatewayV2::Api", "PhysicalResourceId": aid} for aid in self._api_ids]}


class _FakeApiGw:
    def __init__(self, apis, deleted=None):
        self._apis = apis  # list of {"ApiId":..., "Name":..., "CreatedDate":..., "Tags":...}
        self.deleted = deleted if deleted is not None else []

    def get_apis(self, NextToken=None):  # noqa: N803
        return {"Items": self._apis}

    def delete_api(self, ApiId):  # noqa: N803
        match = [a for a in self._apis if a["ApiId"] == ApiId]
        if not match:
            raise Exception("NotFoundException: no such api")
        self._apis = [a for a in self._apis if a["ApiId"] != ApiId]
        self.deleted.append(ApiId)


class _FakeCloudWatch:
    def __init__(self, totals):
        self._totals = totals  # {api_id: total_count}

    def get_metric_statistics(self, Namespace, MetricName, Dimensions, StartTime, EndTime, Period, Statistics):  # noqa: N803
        api_id = next(d["Value"] for d in Dimensions if d["Name"] == "ApiId")
        total = self._totals.get(api_id, 0)
        if total == 0:
            return {"Datapoints": []}
        return {"Datapoints": [{"Timestamp": StartTime, "Sum": total, "Unit": "None"}]}


class _FakeLambda:
    def __init__(self, statements, removed=None):
        self._policy = {"Version": "2012-10-17", "Statement": list(statements)}
        self.removed = removed if removed is not None else []

    def get_policy(self, FunctionName):  # noqa: N803
        if not self._policy["Statement"]:
            raise Exception("ResourceNotFoundException: no policy")
        return {"Policy": json.dumps(self._policy)}

    def remove_permission(self, FunctionName, StatementId):  # noqa: N803
        before = len(self._policy["Statement"])
        self._policy["Statement"] = [s for s in self._policy["Statement"] if s.get("Sid") != StatementId]
        if len(self._policy["Statement"]) == before:
            raise Exception("ResourceNotFoundException: no such statement")
        self.removed.append(StatementId)


def _dispatch(apigw=None, cfn=None, cw=None, lam=None):
    def _c(service, region=ds.REGION):
        return {"apigatewayv2": apigw, "cloudformation": cfn, "cloudwatch": cw, "lambda": lam}[service]

    return _c


_CDK_API = {"ApiId": "p6clybdkkc", "Name": "health-auto-export-api", "CreatedDate": "2026-07-05", "Tags": {"ManagedBy": "cdk"}}
_ORPHAN_API = {"ApiId": "a76xwxt2wa", "Name": "health-auto-export-api", "CreatedDate": "2026-02-24", "Tags": {}}


def _orphan_stmt(api_id="a76xwxt2wa", sid="ApiGatewayInvoke"):
    return {
        "Sid": sid,
        "Effect": "Allow",
        "Principal": {"Service": "apigateway.amazonaws.com"},
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:health-auto-export-webhook",
        "Condition": {"ArnLike": {"AWS:SourceArn": f"arn:aws:execute-api:us-west-2:205930651321:{api_id}/*/*"}},
    }


def _cdk_stmt(api_id="p6clybdkkc"):
    return {
        "Sid": "CdkGrant",
        "Effect": "Allow",
        "Principal": {"Service": "apigateway.amazonaws.com"},
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:health-auto-export-webhook",
        "Condition": {"ArnLike": {"AWS:SourceArn": f"arn:aws:execute-api:us-west-2:205930651321:{api_id}/*/*/ingest"}},
    }


# ── find_orphan_apis ─────────────────────────────────────────────────────────


def test_find_orphan_apis_excludes_the_cdk_managed_one(monkeypatch):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    orphans, cdk_id = td.find_orphan_apis(apigw=apigw, cfn=cfn)
    assert cdk_id == "p6clybdkkc"
    assert [o["ApiId"] for o in orphans] == ["a76xwxt2wa"]


def test_find_orphan_apis_empty_when_only_cdk_api_exists(monkeypatch):
    apigw = _FakeApiGw([_CDK_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    orphans, cdk_id = td.find_orphan_apis(apigw=apigw, cfn=cfn)
    assert orphans == []
    assert cdk_id == "p6clybdkkc"


def test_find_orphan_apis_aborts_when_cdk_id_cannot_be_derived():
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn([])  # zero AWS::ApiGatewayV2::Api resources — unexpected shape
    try:
        td.find_orphan_apis(apigw=apigw, cfn=cfn)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "could not derive" in str(e)


# ── measure_traffic ───────────────────────────────────────────────────────────


def test_measure_traffic_zero_when_no_datapoints():
    cw = _FakeCloudWatch({})
    total, n = td.measure_traffic("a76xwxt2wa", days=7, cw=cw)
    assert total == 0
    assert n == 0


def test_measure_traffic_nonzero_when_requests_seen():
    cw = _FakeCloudWatch({"p6clybdkkc": 137})
    total, n = td.measure_traffic("p6clybdkkc", days=7, cw=cw)
    assert total == 137
    assert n == 1


# ── find_orphan_lambda_grants ─────────────────────────────────────────────────


def test_find_orphan_lambda_grants_finds_the_orphan_statement():
    lam = _FakeLambda([_cdk_stmt(), _orphan_stmt()])
    hits = td.find_orphan_lambda_grants("health-auto-export-webhook", ["a76xwxt2wa"], lam=lam)
    assert len(hits) == 1
    assert hits[0]["sid"] == "ApiGatewayInvoke"


def test_find_orphan_lambda_grants_empty_when_no_policy():
    lam = _FakeLambda([])
    hits = td.find_orphan_lambda_grants("health-auto-export-webhook", ["a76xwxt2wa"], lam=lam)
    assert hits == []


def test_find_orphan_lambda_grants_ignores_grants_for_other_apis():
    lam = _FakeLambda([_cdk_stmt()])
    hits = td.find_orphan_lambda_grants("health-auto-export-webhook", ["a76xwxt2wa"], lam=lam)
    assert hits == []


# ── main(): dry-run vs --apply, zero-traffic gate, idempotency ───────────────


def test_main_dry_run_deletes_nothing(monkeypatch, capsys):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    cw = _FakeCloudWatch({"a76xwxt2wa": 0})
    lam = _FakeLambda([_cdk_stmt(), _orphan_stmt()])
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(ds, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py"])

    rc = td.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "would delete API a76xwxt2wa" in out
    assert apigw.deleted == []
    assert lam.removed == []


def test_main_apply_deletes_zero_traffic_orphan_and_revokes_grant(monkeypatch, capsys):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    cw = _FakeCloudWatch({"a76xwxt2wa": 0})
    lam = _FakeLambda([_cdk_stmt(), _orphan_stmt()])
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(ds, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py", "--apply"])

    rc = td.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "deleted API a76xwxt2wa" in out
    assert apigw.deleted == ["a76xwxt2wa"]
    assert lam.removed == ["ApiGatewayInvoke"]
    # the CDK-managed grant must survive
    assert any(s.get("Sid") == "CdkGrant" for s in lam._policy["Statement"])


def test_main_skips_deletion_when_traffic_seen_without_force(monkeypatch, capsys):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    cw = _FakeCloudWatch({"a76xwxt2wa": 3})  # non-zero — cutover NOT actually complete
    lam = _FakeLambda([_cdk_stmt(), _orphan_stmt()])
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(ds, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py", "--apply"])

    rc = td.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "SKIP: non-zero traffic" in out
    assert apigw.deleted == []
    assert lam.removed == []


def test_main_force_deletes_despite_traffic(monkeypatch, capsys):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    cw = _FakeCloudWatch({"a76xwxt2wa": 3})
    lam = _FakeLambda([_cdk_stmt(), _orphan_stmt()])
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(ds, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py", "--apply", "--force"])

    rc = td.main()
    assert rc == 0
    assert apigw.deleted == ["a76xwxt2wa"]


def test_main_idempotent_when_already_torn_down(monkeypatch, capsys):
    # Second run: the orphan is already gone from both the API list and the
    # resource policy — the exact state right after a successful --apply.
    apigw = _FakeApiGw([_CDK_API])
    cfn = _FakeCfn(["p6clybdkkc"])
    cw = _FakeCloudWatch({})
    lam = _FakeLambda([_cdk_stmt()])
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(ds, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=cw, lam=lam))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py", "--apply"])

    rc = td.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Nothing to do" in out
    assert apigw.deleted == []
    assert lam.removed == []


def test_main_aborts_when_cdk_api_derivation_fails(monkeypatch, capsys):
    apigw = _FakeApiGw([_CDK_API, _ORPHAN_API])
    cfn = _FakeCfn([])  # unexpected: zero CDK-managed APIs found
    monkeypatch.setattr(td, "_client", _dispatch(apigw=apigw, cfn=cfn, cw=_FakeCloudWatch({}), lam=_FakeLambda([])))
    monkeypatch.setattr(sys, "argv", ["teardown_hae_orphan_api.py", "--apply"])

    rc = td.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "ABORT" in out
    assert apigw.deleted == []
