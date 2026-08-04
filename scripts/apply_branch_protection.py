#!/usr/bin/env python3
"""scripts/apply_branch_protection.py — settings-as-code for `main`'s required checks (#1662, ADR-148).

WHAT THIS OWNS
  Two GitHub repo-config surfaces, both declared in deploy/github_posture.json (the
  existing machine-readable posture mirror, #1320) and both GET-asserted weekly by
  deploy/drift_sentinel.py::check_github_config():

    * `main_required_checks_ruleset` — a SECOND repository ruleset on refs/heads/main
      carrying exactly one rule: required_status_checks, scoped to the FAST lane.
    * `repo_settings.allow_auto_merge` — the repo-level toggle that lets the operator
      arm a PR once and have GitHub land it the moment the required checks go green.

WHY A RULESET AND NOT CLASSIC BRANCH PROTECTION
  Classic protection (`/branches/main/protection`) has no per-actor bypass. ci-cd.yml's
  `reconcile` job pushes a regenerated-artifact commit DIRECTLY to main as
  github-actions[bot], which is not an admin — under classic protection with required
  checks that push is rejected on every merge day, and `enforce_admins:false` does not
  help a bot. Rulesets carry `bypass_actors`, so the bot keeps its push and humans stay
  gated. It also leaves `gh api .../branches/main/protection` at its documented 404
  (docs/CONVENTIONS.md drift-discovery table) — nothing about the classic surface moves.

WHAT IT WILL NEVER DO
  * It never enables required reviews. Solo operator: a `pull_request` rule (or classic
    `required_pull_request_reviews`) would make every merge un-landable by its author.
    Enforced structurally by `assert_no_review_requirement()` — a spec that grows one
    fails here before any network call, and tests/test_branch_protection_spec.py pins it.
  * It never touches the pre-existing `main-block-force-push-and-deletion` ruleset
    (id 19162901, #1325). Selection is by NAME, and the preserved ruleset's name/id is a
    hard refusal.
  * It never mutates anything without `--apply`. Default is a printed plan.

USAGE
  python3 scripts/apply_branch_protection.py            # dry run — print the plan, no writes
  python3 scripts/apply_branch_protection.py --apply    # create/update ruleset + repo toggle
  python3 scripts/apply_branch_protection.py --check    # drift gate: exit 1 if live != spec
  python3 scripts/apply_branch_protection.py --preflight-only   # offline: validate the spec

  `--check` is the on-demand form of the weekly sentinel leg; both read the same spec.

THE LOAD-BEARING PART: the required contexts must run on EVERY PR
  A required check that some PR class never reports blocks that class forever (a
  path-filtered gate on a docs-only PR; an `if:`-gated job that reports `skipped`).
  So the spec names workflow + job for each context, and `preflight_contexts()` parses
  the real workflow YAML and refuses a context whose emitting job is path-filtered,
  `if:`-gated, not triggered by `pull_request` on main, or whose job `name:` does not
  equal the declared context string (the check-run name IS the job name — a rename
  silently un-requires the check). `--apply` will not proceed if preflight fails, and
  the same function runs offline in the test suite, so a later workflow edit that adds
  a `paths:` filter to the fast lane reds CI instead of wedging PRs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTURE_FILE = os.path.join(_ROOT, "deploy", "github_posture.json")
WORKFLOW_DIR = os.path.join(_ROOT, ".github", "workflows")

# Kept identical to deploy/drift_sentinel.py::DEFAULT_REPO — the two tools read the same
# spec and must resolve the same repo. Parity is pinned by tests/test_branch_protection_spec.py.
DEFAULT_REPO = "averagejoematt/life-platform"

# The ruleset this tool must never select, update, or delete (#1325).
PRESERVED_RULESET_NAME = "main-block-force-push-and-deletion"
PRESERVED_RULESET_ID = 19162901

# Rule types that would put a human approval in the loop. Solo operator — see ADR-148.
FORBIDDEN_RULE_TYPES = ("pull_request", "required_deployments", "required_signatures")


class SpecError(RuntimeError):
    """The declared spec is internally invalid — raised before any network call."""


# ── spec ─────────────────────────────────────────────────────────────────────


def load_spec(path: str = POSTURE_FILE) -> dict:
    with open(path) as f:
        posture = json.load(f)
    for key in ("main_required_checks_ruleset", "repo_settings"):
        if key not in posture:
            raise SpecError(f"{os.path.basename(path)} is missing the `{key}` entry (#1662)")
    return posture


def assert_no_review_requirement(record: dict) -> None:
    """Refuse any spec OR built payload that would put a human approval in the loop.

    Structural, not a substring scan: the spec's prose fields legitimately contain the
    string "pull_request" (they quote workflow triggers), so this reads declared rule
    types and the classic review knobs by key."""
    for rule in record.get("rules") or []:
        rt = rule.get("type") if isinstance(rule, dict) else rule
        if rt in FORBIDDEN_RULE_TYPES:
            raise SpecError(
                f"rule type `{rt}` is present — this tool never enables review/approval requirements on a "
                "solo-operator repo (ADR-148); remove it from deploy/github_posture.json"
            )
    for key in ("required_approving_review_count", "require_review", "required_reviewers", "required_pull_request_reviews"):
        if record.get(key):
            raise SpecError(f"`{key}` is present — required reviews are refused (ADR-148, solo operator)")


def assert_preserves_existing_ruleset(spec: dict) -> None:
    name = spec.get("name")
    if name == PRESERVED_RULESET_NAME or spec.get("id") == PRESERVED_RULESET_ID:
        raise SpecError(
            f"the spec targets `{PRESERVED_RULESET_NAME}` (id {PRESERVED_RULESET_ID}) — that ruleset is the "
            "force-push/deletion block from #1325 and is never managed by this tool; use a distinct name"
        )


# ── workflow preflight (the load-bearing check) ──────────────────────────────


def _load_workflow(filename: str) -> dict:
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise SpecError(f"PyYAML is required to preflight the required contexts ({e}); pip install pyyaml") from e
    path = os.path.join(WORKFLOW_DIR, filename)
    if not os.path.exists(path):
        raise SpecError(f"spec names workflow `{filename}` which does not exist in .github/workflows/")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def preflight_contexts(spec: dict) -> list[str]:
    """Validate every declared required context against the live workflow YAML.

    Returns a list of human-readable problems (empty == good). Never raises for a
    content problem — only for a structurally unusable spec/environment."""
    problems: list[str] = []
    for entry in spec.get("required_status_checks", []):
        context = entry.get("context")
        wf_name = entry.get("workflow")
        job_id = entry.get("job")
        if not (context and wf_name and job_id):
            problems.append(f"required_status_checks entry {entry!r} must declare context + workflow + job")
            continue
        doc = _load_workflow(wf_name)
        # PyYAML parses a bare `on:` key as the boolean True (the Norway problem).
        on = doc.get("on")
        if on is None:
            on = doc.get(True) or {}
        pr = on.get("pull_request") if isinstance(on, dict) else None
        if not isinstance(pr, dict):
            problems.append(f"{context!r}: {wf_name} has no `on.pull_request` trigger — it can never report on a PR")
            continue
        branches = pr.get("branches") or []
        if "main" not in branches:
            problems.append(f"{context!r}: {wf_name}'s pull_request trigger does not target `main` (branches={branches})")
        if pr.get("paths") or pr.get("paths-ignore"):
            problems.append(
                f"{context!r}: {wf_name}'s pull_request trigger is PATH-FILTERED — it does not report on every PR, "
                "so requiring it would block unrelated PRs forever (ADR-148)"
            )
        job = (doc.get("jobs") or {}).get(job_id)
        if job is None:
            problems.append(f"{context!r}: {wf_name} has no job `{job_id}`")
            continue
        if job.get("if"):
            problems.append(
                f"{context!r}: job `{job_id}` in {wf_name} is `if:`-gated ({job['if']!r}) — it reports `skipped` on "
                "the PR classes it does not match, and a skipped check never satisfies a required check (ADR-148)"
            )
        strategy = job.get("strategy")
        if isinstance(strategy, dict) and strategy.get("matrix"):
            problems.append(
                f"{context!r}: job `{job_id}` in {wf_name} is a MATRIX job — it emits one check-run per matrix leg, "
                "so a single context string cannot name it"
            )
        job_name = job.get("name")
        if job_name != context:
            problems.append(
                f"{context!r}: job `{job_id}` in {wf_name} reports as {job_name!r} — the check-run name IS the job "
                "`name:`, so the required context would never be satisfied"
            )
    return problems


# ── gh plumbing ──────────────────────────────────────────────────────────────


def gh_json(path: str, method: str = "GET", payload: dict | None = None) -> tuple[dict | list | None, str | None]:
    """`gh api` → (parsed, None) or (None, error text). GET unless `method` says otherwise."""
    args = ["api", "-X", method, path]
    input_json = None
    if payload is not None:
        args += ["--input", "-"]
        input_json = json.dumps(payload)
    env = dict(os.environ)
    token = env.get("GH_POSTURE_TOKEN")
    if token:
        env["GH_TOKEN"] = token
    try:
        out = subprocess.run(["gh", *args], input=input_json, capture_output=True, text=True, timeout=120, cwd=_ROOT, env=env)
    except Exception as e:  # noqa: BLE001
        return None, f"gh api {method} {path}: {e}"
    if out.returncode != 0:
        return None, ((out.stdout or "") + " " + (out.stderr or "")).strip()[:500]
    try:
        return (json.loads(out.stdout) if out.stdout.strip() else {}), None
    except Exception as e:  # noqa: BLE001
        return None, f"gh api {method} {path}: parse: {e}"


def repo_slug() -> str:
    return os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)


def resolve_app_id(slug: str, cache: dict | None = None) -> int:
    """App slug → integration id, resolved LIVE (`GET /apps/{slug}` is public).

    Never hardcoded: the id is a GitHub-side fact, and a wrong literal here would
    silently produce a bypass actor that matches nothing."""
    if cache is not None and slug in cache:
        return cache[slug]
    data, err = gh_json(f"/apps/{slug}")
    if err or not isinstance(data, dict) or not data.get("id"):
        raise SpecError(f"could not resolve GitHub App `{slug}` to an integration id: {err or data}")
    app_id = int(data["id"])
    if cache is not None:
        cache[slug] = app_id
    return app_id


# ── desired payload ──────────────────────────────────────────────────────────


def build_ruleset_payload(spec: dict, app_ids: dict) -> dict:
    """The exact POST/PUT body for the required-checks ruleset."""
    assert_no_review_requirement(spec)
    assert_preserves_existing_ruleset(spec)
    producer = app_ids[spec.get("producer_app", "github-actions")]
    checks = [{"context": c["context"], "integration_id": producer} for c in spec["required_status_checks"]]
    if not checks:
        raise SpecError("the spec declares zero required status checks — an empty required-checks ruleset is a no-op")
    payload = {
        "name": spec["name"],
        "target": spec.get("target", "branch"),
        "enforcement": spec.get("enforcement", "active"),
        "bypass_actors": [
            {"actor_id": app_ids[b["app"]], "actor_type": "Integration", "bypass_mode": b.get("bypass_mode", "always")}
            for b in spec.get("bypass_actors", [])
        ],
        "conditions": {"ref_name": {"include": list(spec.get("include_refs", [])), "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": bool(spec.get("strict_required_status_checks_policy", False)),
                    "do_not_enforce_on_create": bool(spec.get("do_not_enforce_on_create", True)),
                    "required_status_checks": checks,
                },
            }
        ],
    }
    # belt-and-braces: the BUILT payload is re-checked, so a future edit to this
    # function can't smuggle an approval rule past the spec-level assertion.
    assert_no_review_requirement(payload)
    return payload


# ── diffing live vs desired ──────────────────────────────────────────────────


def diff_ruleset(live: dict | None, desired: dict) -> list[str]:
    """Human-readable differences between a live ruleset record and the desired payload."""
    if live is None:
        return [f"ruleset `{desired['name']}` does not exist — main has NO required status checks"]
    problems = []
    if live.get("enforcement") != desired["enforcement"]:
        problems.append(f"enforcement={live.get('enforcement')!r} (want {desired['enforcement']!r})")
    live_include = ((live.get("conditions") or {}).get("ref_name") or {}).get("include") or []
    want_include = desired["conditions"]["ref_name"]["include"]
    if sorted(live_include) != sorted(want_include):
        problems.append(f"ref_name.include={live_include} (want {want_include})")
    live_rules = [r for r in (live.get("rules") or []) if r.get("type") == "required_status_checks"]
    if not live_rules:
        problems.append(f"no required_status_checks rule (live rule types: {[r.get('type') for r in live.get('rules') or []]})")
    else:
        params = live_rules[0].get("parameters") or {}
        live_ctx = sorted(c.get("context") for c in params.get("required_status_checks") or [])
        want_ctx = sorted(c["context"] for c in desired["rules"][0]["parameters"]["required_status_checks"])
        if live_ctx != want_ctx:
            problems.append(f"required contexts {live_ctx} (want {want_ctx})")
        want_strict = desired["rules"][0]["parameters"]["strict_required_status_checks_policy"]
        if bool(params.get("strict_required_status_checks_policy")) != want_strict:
            problems.append(
                f"strict_required_status_checks_policy={params.get('strict_required_status_checks_policy')} (want {want_strict})"
            )
    live_bypass = sorted((b.get("actor_id"), b.get("actor_type"), b.get("bypass_mode")) for b in live.get("bypass_actors") or [])
    want_bypass = sorted((b["actor_id"], b["actor_type"], b["bypass_mode"]) for b in desired["bypass_actors"])
    if live_bypass != want_bypass:
        problems.append(f"bypass_actors={live_bypass} (want {want_bypass}) — the reconcile bot's direct push to main depends on this")
    forbidden = [r.get("type") for r in (live.get("rules") or []) if r.get("type") in FORBIDDEN_RULE_TYPES]
    if forbidden:
        problems.append(f"live ruleset carries approval-shaped rule(s) {forbidden} — never applied by this tool (ADR-148)")
    return problems


def diff_repo_settings(live: dict, want: dict) -> list[str]:
    problems = []
    for key, value in want.items():
        if key == "source":
            continue
        if live.get(key) != value:
            problems.append(f"{key}={live.get(key)!r} (want {value!r})")
    return problems


def find_ruleset(rulesets: list, name: str) -> dict | None:
    for rs in rulesets or []:
        if rs.get("name") == name:
            return rs
    return None


# ── driver ───────────────────────────────────────────────────────────────────


def _print_plan(spec: dict, desired: dict, ruleset_problems: list[str], settings_problems: list[str]) -> None:
    print("── plan: GitHub `main` required checks + auto-merge (#1662, ADR-148) ──")
    print(f"ruleset          : {desired['name']} (target {desired['target']}, enforcement {desired['enforcement']})")
    print(f"preserved as-is  : {PRESERVED_RULESET_NAME} (id {PRESERVED_RULESET_ID}) — never read-modify-written here")
    print("required checks  :")
    for entry in spec["required_status_checks"]:
        print(f"  · {entry['context']}")
        print(f"      from {entry['workflow']} job `{entry['job']}` · ~{entry.get('typical_seconds', '?')}s · runs on EVERY PR to main")
    print(f"strict (branch up to date): {desired['rules'][0]['parameters']['strict_required_status_checks_policy']}")
    print("bypass           :")
    for b in spec.get("bypass_actors", []):
        print(f"  · app `{b['app']}` ({b.get('bypass_mode', 'always')}) — {b.get('why', '')[:120]}")
    print("required reviews : NONE (solo operator — structurally refused by this tool)")
    print()
    print("ruleset drift    : " + ("; ".join(ruleset_problems) if ruleset_problems else "none (live matches spec)"))
    print("repo settings    : " + ("; ".join(settings_problems) if settings_problems else "none (live matches spec)"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually create/update the ruleset + repo toggle")
    ap.add_argument("--check", action="store_true", help="drift gate: exit 1 when live state differs from the spec")
    ap.add_argument("--preflight-only", action="store_true", help="offline: validate the spec against the workflow YAML and exit")
    ap.add_argument("--repo", default=None, help=f"owner/repo (default {DEFAULT_REPO} or $GITHUB_REPOSITORY)")
    args = ap.parse_args(argv)

    try:
        posture = load_spec()
    except (SpecError, OSError, ValueError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    spec = posture["main_required_checks_ruleset"]
    want_settings = posture["repo_settings"]

    try:
        problems = preflight_contexts(spec)
    except SpecError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    if problems:
        print(
            "FAIL: required-context preflight (a required check that does not run on every PR blocks that PR class forever):",
            file=sys.stderr,
        )
        for p in problems:
            print(f"  · {p}", file=sys.stderr)
        return 2
    print(
        f"preflight OK: {len(spec['required_status_checks'])} context(s) verified against .github/workflows/ — unfiltered, un-gated, name-matched"
    )
    if args.preflight_only:
        return 0

    repo = args.repo or repo_slug()
    app_cache: dict = {}
    try:
        needed = {spec.get("producer_app", "github-actions")} | {b["app"] for b in spec.get("bypass_actors", [])}
        for slug in sorted(needed):
            resolve_app_id(slug, app_cache)
        desired = build_ruleset_payload(spec, app_cache)
    except SpecError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    rulesets, err = gh_json(f"/repos/{repo}/rulesets")
    if err:
        print(f"FAIL: cannot read rulesets for {repo}: {err}", file=sys.stderr)
        return 2
    live = find_ruleset(rulesets if isinstance(rulesets, list) else [], desired["name"])
    if live is not None:
        # the list endpoint omits rules/bypass_actors — re-read the full record
        full, err = gh_json(f"/repos/{repo}/rulesets/{live['id']}")
        if err:
            print(f"FAIL: cannot read ruleset {live['id']}: {err}", file=sys.stderr)
            return 2
        live = full if isinstance(full, dict) else live
    ruleset_problems = diff_ruleset(live, desired)

    repo_rec, err = gh_json(f"/repos/{repo}")
    if err:
        print(f"FAIL: cannot read repo settings for {repo}: {err}", file=sys.stderr)
        return 2
    settings_problems = diff_repo_settings(repo_rec if isinstance(repo_rec, dict) else {}, want_settings)

    _print_plan(spec, desired, ruleset_problems, settings_problems)

    if args.check:
        if ruleset_problems or settings_problems:
            print("\nDRIFT: live GitHub state does not match deploy/github_posture.json — run with --apply", file=sys.stderr)
            return 1
        print("\nclean: live GitHub state matches the documented posture")
        return 0

    if not args.apply:
        print("\ndry run — nothing mutated. Re-run with --apply to make it so.")
        return 0

    # ── mutations, only past here ──
    if ruleset_problems:
        if live is None:
            _, err = gh_json(f"/repos/{repo}/rulesets", method="POST", payload=desired)
            action = "created"
        else:
            _, err = gh_json(f"/repos/{repo}/rulesets/{live['id']}", method="PUT", payload=desired)
            action = f"updated (id {live['id']})"
        if err:
            print(f"FAIL: ruleset write: {err}", file=sys.stderr)
            return 2
        print(f"applied: ruleset {desired['name']} {action}")
    else:
        print("ruleset already matches — no write")

    if settings_problems:
        body = {k: v for k, v in want_settings.items() if k != "source"}
        _, err = gh_json(f"/repos/{repo}", method="PATCH", payload=body)
        if err:
            print(f"FAIL: repo settings write: {err}", file=sys.stderr)
            return 2
        print(f"applied: repo settings {body}")
    else:
        print("repo settings already match — no write")

    print("\ndone. Re-verify: python3 scripts/apply_branch_protection.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
