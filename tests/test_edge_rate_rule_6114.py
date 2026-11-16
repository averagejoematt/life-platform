"""tests/test_edge_rate_rule_6114.py — the ONE edge rate rule covers exactly the reader write doors (#6114).

Owner ruling 2026-11-16: a narrowly scoped AWS WAF rate rule on the reader-submission endpoints, not on
ordinary browsing. `cdk/stacks/web_edge_rate_rule.py` holds the rule as plain CloudFormation data; this file
proves three things about it.

  SCOPE      Derived from the REAL route tables, both ways: every POST a reader can make without the owner
             token is inside the rule's scope (site-api `_SIMPLE_ROUTES`, the site-api-ai handler's path
             literals, the CloudFront `/api/subscribe*` behaviour), and nothing else is — no GET-only route,
             no owner-token door, no read route, no path nothing routes (a pending PR's door excepted, by
             name). A new public POST door that the rule misses reds here, as does a scoped path that rots.
  SHAPE      Default ALLOW; one rate-based rule keyed on IP; the method leg is exactly POST; the limit and
             window sit inside what AWS accepts; the block is a 429 whose JSON body carries the backend
             limiter's `error` key plus the edge marker the nightly `ratelimit:edge_429` check reads.
  TEMPLATE   (wherever aws-cdk-lib is importable) the synthesized LifePlatformWeb template carries exactly
             one WebACL, equal to the spec, associated by GetAtt to the main distribution only — the three
             subdomain distributions carry none, and there is no WAF logging configuration.

Each scope leg runs the same pure function on the real tables and on planted tables, so it cannot pass by
going blind.
"""

# premerge-gate: #6114: reads the site-api handler family (lambdas/web/site_api*.py) to derive every public POST door the edge rule must cover

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "lambdas" / "web"
SPEC_PATH = ROOT / "cdk" / "stacks" / "web_edge_rate_rule.py"


def _load_spec():
    """Load the spec by path: it imports nothing from aws_cdk, so this runs on every CI lane."""
    spec = importlib.util.spec_from_file_location("web_edge_rate_rule_6114", SPEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_spec()
_REGEX = re.compile(R.READER_WRITE_REGEX)

# _SIMPLE_ROUTES entries whose method set is None (any verb reaches the handler). Each is a read, by
# decision; a new None-method route must be classified here before the scope test can pass.
ANY_METHOD_READS = {"/api/experiment_detail": "the experiment drill-down read; a POST is answered as the GET"}


# ── derivations from the real route tables (AST, no import of the AWS-wired handlers) ───────────────────


def _dict_literal(tree: ast.Module, name: str) -> ast.Dict:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and isinstance(node.value, ast.Dict):
            return node.value
    raise AssertionError(f"{name} dict literal not found")


def simple_routes() -> dict:
    """{path: methods-set or None} from site_api_lambda._SIMPLE_ROUTES."""
    tree = ast.parse((WEB / "site_api_lambda.py").read_text(encoding="utf-8"))
    out = {}
    for k, v in zip(_dict_literal(tree, "_SIMPLE_ROUTES").keys, _dict_literal(tree, "_SIMPLE_ROUTES").values):
        methods = v.elts[0]
        out[k.value] = None if isinstance(methods, ast.Constant) and methods.value is None else {e.value for e in methods.elts}
    return out


def read_routes() -> set:
    """ROUTES keys bound to a real handler (the None placeholders are doors served elsewhere)."""
    tree = ast.parse((WEB / "site_api_lambda.py").read_text(encoding="utf-8"))
    d = _dict_literal(tree, "ROUTES")
    return {k.value for k, v in zip(d.keys, d.values) if not (isinstance(v, ast.Constant) and v.value is None)}


def ai_post_paths() -> set:
    """Every `path == "<literal>"` the site-api-ai lambda_handler answers (each is POST-only there)."""
    tree = ast.parse((WEB / "site_api_ai_lambda.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "path" and isinstance(n.ops[0], ast.Eq):
            c = n.comparators[0]
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                out.add(c.value)
    return out


def subscriber_behaviour_prefix() -> str:
    """The CloudFront path pattern that routes to the subscriber origin (which subscribes on ANY POST)."""
    src = (ROOT / "cdk" / "stacks" / "web_stack.py").read_text(encoding="utf-8")
    m = re.findall(r'path_pattern="([^"]+)",\s*\n\s*target_origin_id="SubscriberLambdaOrigin"', src)
    assert len(m) == 1, m
    assert m[0].endswith("*")
    return m[0][:-1]


def owner_token_functions() -> set:
    """Names of functions in the site-api handler family that call a `verify_*token` before acting."""
    out = set()
    for path in sorted(WEB.glob("site_api*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call):
                        name = c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
                        if re.fullmatch(r"verify_\w*token", name or ""):
                            out.add(fn.name)
    return out


# ── the decision function (pure; the planted controls run through it too) ──────────────────────────────


def scope_findings(*, routes: dict, ai_paths: set, reads: set, scoped_exact: set, owner_doors: dict, pending: dict, regex) -> list:
    bad = []
    unclassified_any = sorted(p for p, m in routes.items() if m is None and p not in ANY_METHOD_READS)
    bad += [f"{p}: route accepts ANY method — classify it (ANY_METHOD_READS or the scope)" for p in unclassified_any]
    public_posts = {p for p, m in routes.items() if m and "POST" in m} - set(owner_doors)
    public_posts |= set(ai_paths)
    bad += [f"{p}: a public POST door the edge rule's scope misses" for p in sorted(public_posts - scoped_exact)]
    for p in sorted(scoped_exact - public_posts):
        if p in pending:
            if p in routes and "POST" not in (routes[p] or set()):
                bad += [f"{p}: pending door is routed but not as POST"]
            continue
        bad += [f"{p}: scoped, but not a routed public POST door (GET-only, owner, or unrouted)"]
    for p in sorted(public_posts):
        if not regex.search(p):
            bad += [f"{p}: in the scope list but the regex does not match it"]
    never = set(owner_doors) | {p for p, m in routes.items() if m is not None and "POST" not in m} | (reads - public_posts)
    never |= set(ANY_METHOD_READS)
    for p in sorted(never):
        if regex.search(p):
            bad += [f"{p}: the regex covers a route that is not a reader write door"]
    return bad


def _real_inputs() -> dict:
    return dict(
        routes=simple_routes(),
        ai_paths=ai_post_paths(),
        reads=read_routes(),
        scoped_exact=set(R.SITE_API_READER_POSTS) | set(R.AI_READER_POSTS),
        owner_doors=R.OWNER_TOKEN_POST_DOORS,
        pending=R.PENDING_DOORS,
        regex=_REGEX,
    )


# ── SCOPE ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_scope_is_exactly_the_public_post_doors():
    bad = scope_findings(**_real_inputs())
    assert not bad, "the edge rate rule's scope disagrees with the route tables (#6114):\n  " + "\n  ".join(bad)


def test_the_derivation_is_not_vacuous():
    routes, ai = simple_routes(), ai_post_paths()
    assert "POST" in routes["/api/experiment_vote"] and "POST" in routes["/api/predict_week"]
    assert routes["/api/series"] == {"GET"}
    assert ai == {"/api/ask", "/api/board_ask", "/api/explain"}
    assert len({p for p, m in routes.items() if m and "POST" in m}) >= 14
    assert "/api/vitals" in read_routes()


def test_owner_token_doors_really_verify_an_owner_token():
    gated = owner_token_functions()
    routes = simple_routes()
    for path, handler in R.OWNER_TOKEN_POST_DOORS.items():
        assert "POST" in (routes.get(path) or set()), f"{path}: not a routed POST door — prune OWNER_TOKEN_POST_DOORS"
        assert handler in gated, f"{path}: {handler} does not call verify_*token — it is a PUBLIC door and belongs in the scope"


def test_the_subscriber_prefix_matches_the_cloudfront_behaviour():
    prefix = subscriber_behaviour_prefix()
    assert prefix == R.SUBSCRIBER_POST_PREFIX
    for p in (prefix, prefix + "/", prefix + "X", prefix + "r_count"):
        assert _REGEX.search(p), p


def test_the_regex_is_anchored_and_inside_the_aws_length_limit():
    assert len(R.READER_WRITE_REGEX) <= 512  # AWS::WAFv2 RegexMatchStatement.RegexString maxLength
    for p in ("/", "/index.html", "/archive/x", "/api/ask_more", "/api/askx", "/xapi/ask", "/api/vitals", "/api/edition", "/api"):
        assert not _REGEX.search(p), p
    for p in ("/api/ask", "/api/experiment_vote", "/api/reader_call", "/api/subscribe"):
        assert _REGEX.search(p), p


def test_planted_public_post_door_outside_the_scope_reds():
    inputs = _real_inputs()
    inputs["routes"] = {**inputs["routes"], "/api/new_reader_door": {"POST"}}
    assert any("new_reader_door" in b and "misses" in b for b in scope_findings(**inputs))


def test_planted_get_route_inside_the_scope_reds():
    inputs = _real_inputs()
    inputs["scoped_exact"] = inputs["scoped_exact"] | {"/api/series"}
    inputs["regex"] = re.compile(r"^/api/(series|" + R.READER_WRITE_REGEX[len("^/api/(") :])
    bad = scope_findings(**inputs)
    assert any("/api/series" in b and "not a routed public POST door" in b for b in bad)
    assert any("/api/series" in b and "not a reader write door" in b for b in bad)


def test_planted_owner_door_inside_the_scope_reds():
    inputs = _real_inputs()
    inputs["regex"] = re.compile(R.READER_WRITE_REGEX + "|^/api/morning_note$")
    assert any("morning_note" in b for b in scope_findings(**inputs))


def test_planted_unclassified_any_method_route_reds():
    inputs = _real_inputs()
    inputs["routes"] = {**inputs["routes"], "/api/new_any": None}
    assert any("new_any" in b and "ANY method" in b for b in scope_findings(**inputs))


# ── SHAPE ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_acl_is_one_rate_rule_default_allow():
    acl = R.web_acl_properties()
    assert acl["Scope"] == "CLOUDFRONT" and acl["DefaultAction"] == {"Allow": {}}
    assert len(acl["Rules"]) == 1
    rbs = acl["Rules"][0]["Statement"]["RateBasedStatement"]
    assert rbs["AggregateKeyType"] == "IP"
    assert R.WAF_LIMIT_FLOOR <= rbs["Limit"] == R.LIMIT
    assert rbs["EvaluationWindowSec"] in R.WAF_EVALUATION_WINDOWS
    method, path = rbs["ScopeDownStatement"]["AndStatement"]["Statements"]
    bm = method["ByteMatchStatement"]
    assert bm["FieldToMatch"] == {"Method": {}} and bm["PositionalConstraint"] == "EXACTLY" and bm["SearchString"] == "POST"
    assert path["RegexMatchStatement"]["FieldToMatch"] == {"UriPath": {}}
    assert path["RegexMatchStatement"]["RegexString"] == R.READER_WRITE_REGEX


def test_the_block_answers_like_the_backend_limiter_and_is_marked_as_the_edge():
    acl = R.web_acl_properties()
    resp = acl["Rules"][0]["Action"]["Block"]["CustomResponse"]
    assert resp["ResponseCode"] == 429
    body = acl["CustomResponseBodies"][resp["CustomResponseBodyKey"]]
    assert body["ContentType"] == "APPLICATION_JSON"
    parsed = json.loads(body["Content"])
    assert isinstance(parsed.get("error"), str) and parsed["error"]  # the key every page's 429 handler reads
    assert parsed.get("limiter") == "edge"
    headers = {h["Name"]: h["Value"] for h in resp["ResponseHeaders"]}
    assert headers[R.EDGE_MARKER_HEADER] == R.EDGE_MARKER_VALUE
    assert headers["Retry-After"] == str(R.EVALUATION_WINDOW_SEC)


def test_metrics_and_samples_on_no_logging():
    acl = R.web_acl_properties()
    for vc in (acl["VisibilityConfig"], acl["Rules"][0]["VisibilityConfig"]):
        assert vc["CloudWatchMetricsEnabled"] is True and vc["SampledRequestsEnabled"] is True


# ── TEMPLATE (wherever aws-cdk-lib is importable) ────────────────────────────────────────────────────────

_SYNTH = """
import json, sys
sys.path.insert(0, sys.argv[1])
import aws_cdk as cdk
from aws_cdk.assertions import Template
from stacks.web_stack import WebStack
ctx = json.load(open(sys.argv[1] + "/cdk.json"))["context"]
app = cdk.App(context=ctx, outdir=sys.argv[2])
stack = WebStack(app, "Web6114", env=cdk.Environment(account="205930651321", region="us-east-1"))
print(json.dumps(Template.from_stack(stack).to_json()["Resources"]))
"""


@pytest.fixture(scope="module")
def web_resources(tmp_path_factory):
    probe = subprocess.run([sys.executable, "-c", "import aws_cdk"], capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        pytest.skip("aws_cdk is not importable here; the spec tests above are the gate, the CDK job synthesizes for real")
    tmp = tmp_path_factory.mktemp("synth6114")
    script = tmp / "synth_6114.py"
    script.write_text(_SYNTH, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(ROOT / "cdk"), str(tmp / "out")],
        cwd=str(ROOT / "cdk"),
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1"},
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_template_carries_one_acl_on_the_main_distribution_only(web_resources):
    acls = {k: v for k, v in web_resources.items() if v["Type"] == "AWS::WAFv2::WebACL"}
    assert len(acls) == 1
    ((acl_id, acl),) = acls.items()
    assert acl["Properties"] == R.web_acl_properties()
    assert not [k for k, v in web_resources.items() if v["Type"] in ("AWS::WAFv2::WebACLAssociation", "AWS::WAFv2::LoggingConfiguration")]
    dists = {k: v["Properties"]["DistributionConfig"] for k, v in web_resources.items() if v["Type"] == "AWS::CloudFront::Distribution"}
    assert dists["AmjDistribution"]["WebACLId"] == {"Fn::GetAtt": [acl_id, "Arn"]}
    others = {k: d.get("WebACLId") for k, d in dists.items() if k != "AmjDistribution"}
    assert others and all(v is None for v in others.values()), others


def test_every_post_behaviour_routes_to_an_origin_the_scope_covers(web_resources):
    """GET-only behaviours (the archive, generated assets, og) are untouched by construction; the POST-capable
    ones are exactly the three origins the scope derives from."""
    dist = web_resources["AmjDistribution"]["Properties"]["DistributionConfig"]
    post_capable = {b["PathPattern"]: b["TargetOriginId"] for b in dist["CacheBehaviors"] if "POST" in (b.get("AllowedMethods") or [])}
    assert post_capable == {
        "/api/subscribe*": "SubscriberLambdaOrigin",
        "/api/board_ask": "AiLambdaOrigin",
        "/api/explain": "AiLambdaOrigin",
        "/api/ask": "AiLambdaOrigin",
        "/api/*": "LambdaApiOrigin",
    }
    assert "/archive/*" not in post_capable
