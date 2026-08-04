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
    payload = abp.build_ruleset_payload(spec, {"github-actions": 15368})
    assert [r["type"] for r in payload["rules"]] == ["required_status_checks"]
    params = payload["rules"][0]["parameters"]
    assert params["strict_required_status_checks_policy"] is False, "strict forces a rebase on every sibling merge"
    assert {c["context"] for c in params["required_status_checks"]} == {c["context"] for c in spec["required_status_checks"]}
    assert all(
        c["integration_id"] == 15368 for c in params["required_status_checks"]
    ), "pin the producing app or any app can satisfy the check"
    assert payload["bypass_actors"] == [{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"}]
    assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/main"]


def test_empty_required_set_is_refused():
    with pytest.raises(abp.SpecError, match="zero required status checks"):
        abp.build_ruleset_payload({"name": "x", "required_status_checks": [], "bypass_actors": []}, {"github-actions": 1})


def test_diff_reports_absence_and_weakening(spec):
    desired = abp.build_ruleset_payload(spec, {"github-actions": 15368})
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
