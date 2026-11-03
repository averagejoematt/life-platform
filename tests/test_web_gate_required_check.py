"""tests/test_web_gate_required_check.py — the web gate's REQUIRED verdict is honest.

web-gate.yml's `web-gate-verdict` job is a required context. It must (1) report on every
PR, (2) route exactly the files the push trigger filters on, and (3) fail on every build
outcome that is not a genuine pass. Each property is asserted against the real YAML / the
real router, with a planted negative beside each positive.
"""

import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".github", "workflows", "web-gate.yml")


def _router():
    spec = importlib.util.spec_from_file_location("check_web_gate_required", os.path.join(ROOT, "scripts", "check_web_gate_required.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


r = _router()


def _wf():
    yaml = pytest.importorskip("yaml")
    with open(WF, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc, (doc.get("on") or doc.get(True))


def test_scope_equals_the_push_filter_plus_the_workflow_and_router():
    _, on = _wf()
    want = set(on["push"]["paths"]) | {".github/workflows/web-gate.yml", "scripts/check_web_gate_required.py"}
    assert set(r.SCOPE) == want, f"router SCOPE drifted from on.push.paths: {sorted(set(r.SCOPE) ^ want)}"


def test_pull_request_trigger_is_unfiltered_and_the_verdict_cannot_be_skipped():
    doc, on = _wf()
    pr = on["pull_request"]
    assert not pr.get("paths") and not pr.get("paths-ignore"), "a PR path filter makes the required verdict never start"
    v = doc["jobs"]["web-gate-verdict"]
    assert v["if"] == "always()", "anything but always() lets a cancelled/failed upstream SKIP the verdict, and skipped reads as Success"
    assert set(v["needs"]) == {"scope", "web-gate"}
    assert doc["jobs"]["web-gate"]["if"] == "needs.scope.outputs.run == 'true'"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("www/src/components/SiteFooter.astro", True),
        ("www/package-lock.json", True),
        ("scripts/publish_snapshot_day.py", True),
        ("scripts/check_www_build.py", True),
        (".github/workflows/web-gate.yml", True),
        ("scripts/check_web_gate_required.py", True),
        ("docs/README.md", False),
        ("lambdas/web/site_api_lambda.py", False),
        ("site/index.html", False),
        ("scripts/publish_snapshot/nested.py", False),  # `*` does not cross `/` (GitHub semantics)
        ("wwwx/file", False),
    ],
)
def test_scope_routes_like_github_filters(path, expected):
    assert r.in_scope([path]) is expected


def test_scope_fails_safe():
    assert r.decide_scope("pull_request", None)[0] is True, "an unreadable diff must run the build, never skip it"
    assert r.decide_scope("push", ["docs/x.md"])[0] is True, "push is pre-filtered by the trigger"
    assert r.decide_scope("pull_request", ["docs/x.md"])[0] is False
    assert r.decide_scope("pull_request", ["docs/x.md", "www/a.css"])[0] is True


@pytest.mark.parametrize(
    "scope,in_scope,build,rc",
    [
        ("success", "true", "success", 0),
        ("success", "false", "skipped", 0),
        ("success", "true", "failure", 1),
        ("success", "true", "cancelled", 1),  # supersession AND timeout both land here
        ("success", "true", "skipped", 1),  # in scope but never ran = not a pass
        ("success", "false", "success", 1),  # inconsistent routing is not a pass either
        ("failure", "", "skipped", 1),
        ("failure", "false", "skipped", 1),  # a scope job that failed AFTER emitting run=false is still no answer
        ("cancelled", "", "skipped", 1),
        ("", "", "", 1),
    ],
)
def test_verdict_table(scope, in_scope, build, rc):
    assert r.decide_verdict(scope, in_scope, build)[0] == rc


def test_scope_refuses_to_answer_silently(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert r.main(["x", "scope"]) == 1, "inside Actions an unwritable answer must fail the scope job"
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert r.main(["x", "scope"]) == 0
    assert out.read_text() == "run=true\n"
