"""tests/test_branch_protection_spec.py — the offline half of #1662 / ADR-148.

The applier (`scripts/apply_branch_protection.py`) writes two GitHub repo-config
surfaces from `deploy/github_posture.json`; the weekly drift sentinel GET-asserts the
LIVE half. This file asserts everything that can be decided WITHOUT a network call —
which is, deliberately, the part that has historically been wrong:

  1. **Every required context is emitted by a job that runs on EVERY PR.** A required
     check that some PR class never reports blocks that class *forever* — a
     path-filtered gate on a docs-only PR, or an `if:`-gated job that reports `skipped`
     (a skipped check never satisfies a required check). `preflight_contexts()` reads
     the real workflow YAML; this test runs it against the checked-in spec.
  2. **The check-run name IS the job's `name:`.** Rename the job, and the required
     context silently stops being reported.
  3. **No approval requirement is ever applied.** Solo operator (ADR-148).
  4. **The #1325 force-push/deletion ruleset is never the applier's target.**

SYMPTOM AND CURE IF THIS TEST GOES RED. Something under `.github/workflows/` changed
so a required context no longer reports on every PR. Live effect after the driver has
applied the ruleset: PRs sit forever with "Expected — Waiting for status to be
reported". Fix by either restoring the workflow's trigger/job name, or editing
`deploy/github_posture.json` and re-running `python3 scripts/apply_branch_protection.py
--apply`. Emergency escape: `gh api -X DELETE /repos/<owner>/<repo>/rulesets/<id>` for
the `main-required-fast-lane` ruleset (the drift sentinel then reports it absent).

NOT `deploy_critical`: per docs/CONVENTIONS.md §4a the lane is the deploy-artifact /
wiring contract, and this is repo-config drift. It runs in the exhaustive suite, which
ci-cd.yml triggers on any push touching `tests/**` or `.github/workflows/**`.
"""

import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_applier():
    path = os.path.join(ROOT, "scripts", "apply_branch_protection.py")
    spec = importlib.util.spec_from_file_location("apply_branch_protection", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


abp = _load_applier()


@pytest.fixture(scope="module")
def spec():
    return abp.load_spec()["main_required_checks_ruleset"]


# ── 1/2. the load-bearing check: every required context reports on every PR ──


def test_required_contexts_run_on_every_pull_request(spec):
    pytest.importorskip("yaml")
    problems = abp.preflight_contexts(spec)
    assert not problems, "required-context preflight failed:\n  · " + "\n  · ".join(problems)


def test_preflight_rejects_a_path_filtered_workflow(tmp_path, monkeypatch):
    # Proof the guard FIRES (guard-the-set discipline): surface-drift.yml is real, is
    # path-filtered, and must be rejected if anyone ever adds it to the required set.
    pytest.importorskip("yaml")
    bad = {
        "required_status_checks": [
            {
                "context": "Surface-drift gate (new pages/routes/crons/JS land registered)",
                "workflow": "surface-drift.yml",
                "job": "surface-drift",
            }
        ]
    }
    problems = abp.preflight_contexts(bad)
    assert any("PATH-FILTERED" in p for p in problems), problems


def test_preflight_rejects_an_if_gated_job():
    # dependabot-validate.yml's `validate` job is `if:`-gated to dependabot[bot] — it
    # reports `skipped` on every human PR, and a skipped check never satisfies a
    # required check. This is the exact class the issue's review flagged.
    pytest.importorskip("yaml")
    bad = {"required_status_checks": [{"context": "validate", "workflow": "dependabot-validate.yml", "job": "validate"}]}
    problems = abp.preflight_contexts(bad)
    assert any("`if:`-gated" in p for p in problems), problems


def test_preflight_rejects_a_matrix_job():
    # codeql.yml's `analyze` is a matrix job — it emits one check-run per language, so
    # a single context string can never name it (and it is advisory by design, ADR-148).
    pytest.importorskip("yaml")
    bad = {"required_status_checks": [{"context": "CodeQL analysis (python)", "workflow": "codeql.yml", "job": "analyze"}]}
    problems = abp.preflight_contexts(bad)
    assert any("MATRIX" in p for p in problems), problems


def test_preflight_rejects_a_renamed_job():
    pytest.importorskip("yaml")
    bad = {"required_status_checks": [{"context": "Collect + deploy critical + format", "workflow": "pr-checks.yml", "job": "fast-lane"}]}
    problems = abp.preflight_contexts(bad)
    assert any("reports as" in p for p in problems), problems


def test_advisory_gates_are_named_and_reasoned(spec):
    # The excluded set is documented in the spec itself, so the next person can see WHY
    # a gate they expected to be required isn't — the #1662 review's actual question.
    advisory = " ".join(spec["advisory_not_required"])
    for expected in ("CodeQL", "Dependabot", "Surface-drift", "docs-ci.yml", "v4-gate.yml"):
        assert expected in advisory, f"{expected} isn't accounted for in advisory_not_required"


# ── 3/4. the applier's structural refusals ──────────────────────────────────


def test_applier_refuses_a_review_requirement(spec):
    with pytest.raises(abp.SpecError, match="pull_request"):
        abp.assert_no_review_requirement({"rules": [{"type": "pull_request"}]})
    with pytest.raises(abp.SpecError, match="required_approving_review_count"):
        abp.assert_no_review_requirement({"required_approving_review_count": 1})
    # the checked-in spec is clean, and its prose legitimately contains the substring
    # "pull_request" (it quotes workflow triggers) — a substring scan would false-fire
    abp.assert_no_review_requirement(spec)


def test_applier_refuses_to_manage_the_1325_ruleset():
    with pytest.raises(abp.SpecError, match="never managed"):
        abp.assert_preserves_existing_ruleset({"name": abp.PRESERVED_RULESET_NAME})
    with pytest.raises(abp.SpecError, match="never managed"):
        abp.assert_preserves_existing_ruleset({"name": "something-else", "id": abp.PRESERVED_RULESET_ID})


def test_built_payload_has_exactly_one_required_checks_rule(spec):
    payload = abp.build_ruleset_payload(spec, {"github-actions": 15368}, {"averagejoematt": 174924761})
    assert [r["type"] for r in payload["rules"]] == ["required_status_checks"]
    params = payload["rules"][0]["parameters"]
    assert params["strict_required_status_checks_policy"] is False, "strict forces a rebase on every sibling merge"
    assert {c["context"] for c in params["required_status_checks"]} == {c["context"] for c in spec["required_status_checks"]}
    assert all(
        c["integration_id"] == 15368 for c in params["required_status_checks"]
    ), "pin the producing app or any app can satisfy the check"
    # #2198: the bypass actor is a `User` (the repo owner), not an `Integration` — the
    # Integration shape 422s on this personal-account-owned repo (measured, see the
    # ADR-148 amendment). This is the EXACT payload shape the applier will POST/PUT.
    assert payload["bypass_actors"] == [{"actor_id": 174924761, "actor_type": "User", "bypass_mode": "always"}]
    assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/main"]


def test_bypass_actor_resolver_dispatches_by_actor_type():
    # Proof the generalized resolver actually routes each declared shape to the right
    # lookup (guard-the-set: Integration by app slug, User by login) rather than only
    # exercising whichever one the checked-in spec happens to declare today.
    app_ids, user_ids = {"github-actions": 15368}, {"averagejoematt": 174924761}
    assert abp.resolve_bypass_actor_id({"actor_type": "Integration", "app": "github-actions"}, app_ids, user_ids) == 15368
    assert abp.resolve_bypass_actor_id({"actor_type": "User", "login": "averagejoematt"}, app_ids, user_ids) == 174924761
    with pytest.raises(abp.SpecError, match="has no resolver"):
        abp.resolve_bypass_actor_id({"actor_type": "Team", "id": 1}, app_ids, user_ids)


def test_empty_required_set_is_refused():
    with pytest.raises(abp.SpecError, match="zero required status checks"):
        abp.build_ruleset_payload({"name": "x", "required_status_checks": [], "bypass_actors": []}, {"github-actions": 1})


def test_diff_reports_absence_and_weakening(spec):
    desired = abp.build_ruleset_payload(spec, {"github-actions": 15368}, {"averagejoematt": 174924761})
    assert "does not exist" in " ".join(abp.diff_ruleset(None, desired))
    live = json.loads(json.dumps(desired)) | {"id": 1}
    assert abp.diff_ruleset(live, desired) == [], "an identical live record must diff clean (idempotency)"
    weakened = json.loads(json.dumps(live))
    weakened["rules"][0]["parameters"]["required_status_checks"] = []
    assert abp.diff_ruleset(weakened, desired), "an emptied required set must be reported"
    no_bypass = json.loads(json.dumps(live))
    no_bypass["bypass_actors"] = []
    assert any("reconcile bot" in p for p in abp.diff_ruleset(no_bypass, desired))


def test_repo_settings_diff_ignores_the_source_field():
    want = {"allow_auto_merge": True, "source": "ADR-148"}
    assert abp.diff_repo_settings({"allow_auto_merge": True}, want) == []
    assert abp.diff_repo_settings({"allow_auto_merge": False}, want) == ["allow_auto_merge=False (want True)"]


def test_repo_constant_matches_the_drift_sentinel():
    # Both tools read the same spec; a divergent default repo would let one of them
    # assert against a repo the other never writes.
    sys.path.insert(0, os.path.join(ROOT, "deploy"))  # drift_sentinel imports its siblings by bare name
    import drift_sentinel

    assert abp.DEFAULT_REPO == drift_sentinel.DEFAULT_REPO


# ── #2198: the `User` bypass actor + the reconcile-push-secret preflight ─────


def test_reconcile_push_secret_provisioned_reads_the_secret_list(monkeypatch):
    def fake_present(path, method="GET", payload=None):
        assert path == "/repos/averagejoematt/life-platform/actions/secrets"
        return {"secrets": [{"name": "GH_BILLING_TOKEN"}, {"name": "RECONCILE_PUSH_TOKEN"}]}, None

    monkeypatch.setattr(abp, "gh_json", fake_present)
    assert abp.reconcile_push_secret_provisioned("averagejoematt/life-platform", "RECONCILE_PUSH_TOKEN") is True

    def fake_absent(path, method="GET", payload=None):
        return {"secrets": [{"name": "GH_BILLING_TOKEN"}]}, None

    monkeypatch.setattr(abp, "gh_json", fake_absent)
    assert abp.reconcile_push_secret_provisioned("averagejoematt/life-platform", "RECONCILE_PUSH_TOKEN") is False

    def fake_error(path, method="GET", payload=None):
        return None, "gh: HTTP 403"

    monkeypatch.setattr(abp, "gh_json", fake_error)
    assert abp.reconcile_push_secret_provisioned("averagejoematt/life-platform", "RECONCILE_PUSH_TOKEN") is None


class _FakeGh:
    """Records every `gh_json` call `main()` makes and answers deterministically, so the
    apply path can be exercised end-to-end (payload construction included) with zero
    live network access — this is what "verified without a write" means for #2198: the
    exact request `--apply` WOULD send is asserted, never actually POSTed."""

    def __init__(self, secret_present, live_ruleset=None, repo_settings=None):
        self.secret_present = secret_present
        self.live_ruleset = live_ruleset
        self.repo_settings = repo_settings or {"allow_auto_merge": True}
        self.calls = []

    def __call__(self, path, method="GET", payload=None):
        self.calls.append((path, method, payload))
        if path == "/apps/github-actions":
            return {"id": 15368, "slug": "github-actions"}, None
        if path == "/users/averagejoematt":
            return {"id": 174924761, "login": "averagejoematt"}, None
        if path.endswith("/actions/secrets"):
            names = [{"name": "RECONCILE_PUSH_TOKEN"}] if self.secret_present else []
            return {"secrets": names}, None
        if path.endswith("/rulesets") and method == "GET":
            return ([self.live_ruleset] if self.live_ruleset else []), None
        if "/rulesets/" in path and method == "GET":
            return self.live_ruleset, None
        if path.endswith("/rulesets") and method == "POST":
            return {"id": 999}, None
        if "/rulesets/" in path and method == "PUT":
            return {}, None
        if path == "/repos/averagejoematt/life-platform" and method == "GET":
            return self.repo_settings, None
        if path == "/repos/averagejoematt/life-platform" and method == "PATCH":
            return {}, None
        raise AssertionError(f"unrouted gh_json call in test: {path} {method}")


def _applied_posture():
    """The checked-in posture with the #3207 `applied: false` markers flipped to true.

    The shipped file marks `main_required_checks_ruleset` + `repo_settings` as declared
    but NOT YET APPLIED (D0.6, blocked on RECONCILE_PUSH_TOKEN), and `--apply` refuses
    outright on that marker — so the tests below, which exercise what a real apply
    WOULD send, have to run against the post-D0.6 shape of the same file. The refusal
    itself is proved in tests/test_posture_pending_marker.py."""
    with open(abp.POSTURE_FILE) as f:  # read the file directly — load_spec is patched
        posture = json.load(f)
    posture["main_required_checks_ruleset"]["applied"] = True
    posture["repo_settings"]["applied"] = True
    return posture


def test_apply_refuses_when_reconcile_secret_is_missing(monkeypatch, capsys):
    fake = _FakeGh(secret_present=False, live_ruleset=None)
    monkeypatch.setattr(abp, "load_spec", lambda path=abp.POSTURE_FILE: _applied_posture())
    monkeypatch.setattr(abp, "gh_json", fake)
    rc = abp.main(["--apply", "--repo", "averagejoematt/life-platform"])
    assert rc == 2
    assert "does not exist yet" in capsys.readouterr().err
    # the load-bearing assertion: applying without the secret must never reach a write
    assert not any(method in ("POST", "PUT", "PATCH") for _, method, _ in fake.calls)


def test_apply_sends_the_exact_ruleset_payload_when_secret_is_present(monkeypatch):
    fake = _FakeGh(secret_present=True, live_ruleset=None)
    monkeypatch.setattr(abp, "load_spec", lambda path=abp.POSTURE_FILE: _applied_posture())
    monkeypatch.setattr(abp, "gh_json", fake)
    rc = abp.main(["--apply", "--repo", "averagejoematt/life-platform"])
    assert rc == 0

    posts = [(p, m, payload) for p, m, payload in fake.calls if m == "POST" and p.endswith("/rulesets")]
    assert len(posts) == 1, f"expected exactly one ruleset POST, got {fake.calls}"
    _, _, sent = posts[0]
    assert sent["name"] == "main-required-fast-lane"
    assert sent["bypass_actors"] == [{"actor_id": 174924761, "actor_type": "User", "bypass_mode": "always"}]
    assert sent["conditions"] == {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}
    assert {c["context"] for c in sent["rules"][0]["parameters"]["required_status_checks"]} == {
        "Collect + deploy-critical + format",
        "gitleaks (PR commit range only, not full history)",
    }
    assert sent["rules"][0]["parameters"]["strict_required_status_checks_policy"] is False
    # PATCH for repo settings must NOT fire — the fake's repo settings already match
    assert not any(m == "PATCH" for _, m, _ in fake.calls)
