#!/usr/bin/env python3
"""deploy/sentinel_github.py — the GitHub-side legs of the weekly drift sentinel.

Extracted verbatim from deploy/drift_sentinel.py (module-size ceiling #1665, the same
split that produced sentinel_quota.py). Same functions, same behaviour, same names;
drift_sentinel re-imports them so `ds.check_github_config` / `ds.check_github_push_runs`
and every existing caller keep working.

ONE THING TO KNOW IF YOU WRITE A TEST: a re-export is not a patch point. Fakes for the
helpers below (`_gh_api_result`, `_commit_files`, …) must be monkeypatched on THIS
module — patching the `drift_sentinel` alias binds a name these functions never read.
tests/test_drift_sentinel.py patches both, deliberately, so the mistake can't go silent.

Contents:
  * check_github_config()    — #1320/#1325/#1662: documented GitHub posture vs live
    (production environment protection, the force-push/deletion ruleset, the ADR-148
    fast-lane required-checks ruleset, repo merge settings, vulnerability alerts).
  * check_github_push_runs() — #1544/#1782: push-event workflow runs still QUEUE for
    trigger-matching merges to main.
Both are GET-only and never mutate GitHub.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 6/7. GitHub config posture (#1320) + main-push run liveness (#1544) ──────

GITHUB_POSTURE_FILE = os.path.join(_ROOT, "deploy", "github_posture.json")
DEFAULT_REPO = "averagejoematt/life-platform"

# The one-time owner fix for every scope-gapped surface below (#1320 gate:owner
# remainder): a fine-grained PAT scoped to this repo, stored as the repo secret
# GH_POSTURE_TOKEN (the sentinel prefers it over the ambient GH_TOKEN when set).
PAT_FIX = (
    "fix: create a fine-grained PAT scoped to this repo with repository permissions "
    "Administration:read + Actions:read + Contents:read (+ the implied Metadata:read) "
    "and store it as the GH_POSTURE_TOKEN repo secret — the workflow's built-in "
    "GITHUB_TOKEN can never carry Administration:read"
)

# Path globs that trigger push-event workflows on main. MAINTAINED LITERAL: the
# union of every push-triggered workflow's `on.push.paths` filters — a main
# commit matching NONE of these legitimately queues zero runs, so the #1544
# detector must not alarm on it. tests/test_drift_sentinel.py::
# test_push_trigger_globs_match_workflows parses the live workflow YAMLs and
# reds CI when this set drifts (the PLATFORM_FACTS maintained-literal pattern).
PUSH_TRIGGER_GLOBS = (
    # ci-cd.yml
    "lambdas/**",
    "mcp/**",
    "mcp_server.py",
    "tests/**",
    "cdk/**",
    "ci/**",
    "config/**",
    ".github/workflows/**",
    "requirements*.txt",
    "pyproject.toml",
    ".flake8",
    "deploy/**",  # #2881: gate scripts (smoke_test_site.sh et al.) are validated surface
    # docs-ci.yml
    "docs/**",
    "README.md",
    "CLAUDE.md",
    ".claude/commands/**",
    "deploy/sync_doc_metadata.py",
    "deploy/sync_census_fact.py",  # #3156 — the gate_census_count discoverer sync_doc_metadata.py's --check calls into
    "scripts/check_doc_*.py",
    "scripts/doc_facts_ops.py",
    "scripts/generate_adr_index.py",
    "scripts/generate_mcp_tool_catalog.py",
    "scripts/operating_calendar.py",  # #2832 — the calendar doc derives from its registry
    "scripts/gate_census.py",  # #3000 — docs/PROPORTIONALITY.md's gate_census_count fact
    "scripts/gate_census_precision.py",  # #3000 — gate_census.py's error-bar sibling module
    # site-deploy.yml (+ v4-gate.yml shares site/**; config/** shared with ci-cd.yml)
    "site/**",
    ".github/workflows/site-deploy.yml",
    "deploy/config_twin_sync.py",  # #2019 — bucket-root config/ deploy path
    "deploy/config_twin_registry.py",
    # v4-gate.yml
    "scripts/v4_*.py",
    "tests/js/**",
    "package.json",
)


def _load_github_posture():
    with open(GITHUB_POSTURE_FILE) as f:
        return json.load(f)


def _github_repo():
    return os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)


def _matches_push_trigger(path):
    """True if a changed file at `path` matches any push-workflow path filter.

    GitHub glob semantics, approximated for the actual pattern set: `x/**` is a
    prefix match, a bare filename is exact, anything else with a `*` is fnmatch."""
    import fnmatch

    for pat in PUSH_TRIGGER_GLOBS:
        if pat.endswith("/**"):
            if path.startswith(pat[:-2]):
                return True
        elif "*" in pat:
            if fnmatch.fnmatch(path, pat):
                return True
        elif path == pat:
            return True
    return False


def _gh_api_result(path, timeout=60):
    """GET-only `gh api <path>` → (data, None) on success, (None, errinfo) on failure.

    errinfo = {"classification": "scope"|"absent"|"error", "detail": "..."} — "scope"
    means the credential can't read the surface (403 / resource-not-accessible /
    missing-scope), "absent" is a semantic 404 (the thing doesn't exist / is off),
    "error" is everything else (transient, parse, gh missing). Never raises. This
    NEVER mutates GitHub: plain `gh api` issues a GET.

    Prefers the GH_POSTURE_TOKEN env var (the owner-supplied fine-grained PAT — see
    PAT_FIX) over the ambient GH_TOKEN when set and non-empty."""
    import subprocess

    env = dict(os.environ)
    posture_token = env.get("GH_POSTURE_TOKEN")
    if posture_token:
        env["GH_TOKEN"] = posture_token
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout, cwd=_ROOT, env=env)
    except Exception as e:  # noqa: BLE001
        return None, {"classification": "error", "detail": f"gh api {path}: {e}"[:300]}
    if out.returncode == 0:
        try:
            return (json.loads(out.stdout) if out.stdout.strip() else {}), None
        except Exception as e:  # noqa: BLE001
            return None, {"classification": "error", "detail": f"gh api {path}: parse: {e}"[:300]}
    text = ((out.stdout or "") + " " + (out.stderr or "")).strip()
    low = text.lower()
    if "http 403" in low or "resource not accessible" in low or "must have admin" in low or ("needs the" in low and "scope" in low):
        cls = "scope"
    elif "http 404" in low:
        cls = "absent"
    else:
        cls = "error"
    return None, {"classification": cls, "detail": text[:300]}


def _parse_gh_date(s):
    return datetime.fromisoformat((s or "").replace("Z", "+00:00"))


def _resolve_want_bypass_actor_id(b):
    """One posture bypass-actor entry → (live-comparable key, degraded?).

    #2198: the bypass actor is a `User` (the repo owner), not an `Integration` — the
    Integration shape 422s on a personal-account-owned repo. Both shapes are resolved
    the same way as the applier (`scripts/apply_branch_protection.py::
    resolve_bypass_actor_id`): `Integration` by app slug (`GET /apps/{slug}`, public),
    `User` by login (`GET /users/{login}`, also public). If the lookup is unavailable
    the comparison degrades to (actor_type, bypass_mode) and says so, rather than
    pretending a numeric match it could not make."""
    actor_type = b.get("actor_type", "Integration")
    if actor_type == "User":
        data, err = _gh_api_result(f"/users/{b.get('login')}")
    else:
        data, err = _gh_api_result(f"/apps/{b.get('app')}")
    if err or not (data or {}).get("id"):
        return None, True
    return (int(data["id"]), actor_type, b.get("bypass_mode", "always")), False


def _judge_required_checks(live, want):
    """Compare one live ruleset record against the `main_required_checks_ruleset` spec.

    Judges what actually decides whether the gate works: enforcement, the ref it covers,
    the exact required-context SET, the strict (branch-up-to-date) flag, and the presence
    of the bypass actor the reconcile bot's direct push to main depends on (a `User` —
    the repo owner — as of #2198; see `_resolve_want_bypass_actor_id`). Also fails LOUD
    if an approval-shaped rule ever appears — ADR-148 never applies one, so its presence
    means the ruleset was edited out of band."""
    problems = []
    if live.get("enforcement") != want.get("enforcement", "active"):
        problems.append(f"enforcement={live.get('enforcement')!r} (documented {want.get('enforcement', 'active')!r})")
    include = ((live.get("conditions", {}) or {}).get("ref_name", {}) or {}).get("include", [])
    for ref in want.get("include_refs", []):
        if ref not in include:
            problems.append(f"{ref} missing from ref_name.include={include}")

    rule = next((r for r in (live.get("rules") or []) if r.get("type") == "required_status_checks"), None)
    if rule is None:
        problems.append(f"no required_status_checks rule (live rule types: {sorted(r.get('type') for r in live.get('rules') or [])})")
    else:
        params = rule.get("parameters") or {}
        live_ctx = sorted(c.get("context") for c in params.get("required_status_checks") or [])
        want_ctx = sorted(c["context"] for c in want.get("required_status_checks", []))
        if live_ctx != want_ctx:
            problems.append(f"required contexts {live_ctx} (documented {want_ctx})")
        want_strict = bool(want.get("strict_required_status_checks_policy", False))
        if bool(params.get("strict_required_status_checks_policy")) != want_strict:
            problems.append(
                f"strict_required_status_checks_policy={params.get('strict_required_status_checks_policy')} (documented {want_strict})"
            )

    forbidden = sorted(r.get("type") for r in (live.get("rules") or []) if r.get("type") in ("pull_request", "required_signatures"))
    if forbidden:
        problems.append(f"approval-shaped rule(s) {forbidden} present — ADR-148 never applies one; edited out of band")

    want_bypass = want.get("bypass_actors", [])
    live_bypass = live.get("bypass_actors") or []
    degraded = False
    want_pairs = []
    for b in want_bypass:
        pair, one_degraded = _resolve_want_bypass_actor_id(b)
        if one_degraded:
            degraded = True
            want_pairs.append((b.get("actor_type", "Integration"), b.get("bypass_mode", "always")))
        else:
            want_pairs.append(pair)
    if degraded:
        live_pairs = sorted((b.get("actor_type"), b.get("bypass_mode")) for b in live_bypass)
        want_pairs = sorted((p if len(p) == 2 else (p[1], p[2])) for p in want_pairs)
    else:
        live_pairs = sorted((b.get("actor_id"), b.get("actor_type"), b.get("bypass_mode")) for b in live_bypass)
        want_pairs = sorted(want_pairs)
    if live_pairs != want_pairs:
        problems.append(
            f"bypass_actors={live_pairs} (documented {want_pairs}{' — app-id lookup unavailable, compared by type/mode only' if degraded else ''}) "
            "— ci-cd.yml's reconcile job pushes to main directly and is rejected without it"
        )

    if problems:
        return {"status": "drift", "detail": "; ".join(problems) + " (fix: python3 scripts/apply_branch_protection.py --apply)"}
    return {
        "status": "clean",
        "live_contexts": sorted(c.get("context") for c in (rule.get("parameters") or {}).get("required_status_checks") or []),
    }


def check_github_config():
    """#1320 — GET-only asserts of documented GitHub config vs. live state.

    Five surfaces, each compared against deploy/github_posture.json (the
    machine-readable mirror of the doc claims — never a hardcoded wish):

      * environment_production — the `production` environment's protection rules
        must include `required_reviewers` iff the posture says so. As of
        2026-07-19 the docs still claim the manual-approval gate while live has
        only branch_policy (the #1319 private-flip drop) — so this fires, by
        design, until #1319 reconciles docs + posture + live.
      * main_ruleset — ruleset 19162901 must be `active` with exactly the
        documented rule types (deletion + non_fast_forward) on refs/heads/main.
      * main_required_checks_ruleset (#1662, ADR-148) — the fast-lane
        required-status-checks ruleset, matched by NAME (its id only exists
        after the first apply). Judges enforcement, ref, the exact context set,
        the strict flag, and the bypass actor the reconcile bot needs (a `User` — the
        repo owner — as of #2198).
      * repo_settings (#1662, ADR-148) — repo-level merge toggles, currently
        `allow_auto_merge`, the mechanism that makes required checks cost the
        operator no wall-clock.
      * vulnerability_alerts — Dependabot/vulnerability alerts enablement must
        match the posture (docs claim Dependabot as the CVE remediation channel;
        live-disabled is the SDLC-review P2-4 finding).

    Fail-soft: a surface the credential can't read reports status "unavailable"
    plus a needs_owner line naming the exact fine-grained-PAT permission (see
    PAT_FIX) — never a red. Overall: drift > error > unavailable > clean."""
    try:
        posture = _load_github_posture()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read github_posture.json: {e}"}

    repo = _github_repo()
    surfaces = {}
    scope_gaps = []

    # 1. production environment protection (the #1319 class)
    want_env = posture.get("environment_production", {})
    data, err = _gh_api_result(f"repos/{repo}/environments/{want_env.get('name', 'production')}")
    if err:
        if err["classification"] == "scope":
            surfaces["environment_production"] = {"status": "unavailable", "detail": err["detail"]}
            scope_gaps.append("environments/production (needs fine-grained Actions:read)")
        elif err["classification"] == "absent":
            surfaces["environment_production"] = {"status": "drift", "detail": "the `production` environment does not exist live"}
        else:
            surfaces["environment_production"] = {"status": "error", "detail": err["detail"]}
    else:
        rule_types = sorted(r.get("type") for r in data.get("protection_rules", []) if r.get("type"))
        has_reviewers = "required_reviewers" in rule_types
        if bool(want_env.get("required_reviewers")) == has_reviewers:
            surfaces["environment_production"] = {"status": "clean", "live_protection_rule_types": rule_types}
        else:
            surfaces["environment_production"] = {
                "status": "drift",
                "documented": {"required_reviewers": bool(want_env.get("required_reviewers"))},
                "live_protection_rule_types": rule_types,
                "detail": f"documented posture requires_reviewers={bool(want_env.get('required_reviewers'))} "
                f"but live protection rules are {rule_types} (source: {want_env.get('source', 'github_posture.json')[:120]}…)",
            }

    # 2. main branch ruleset (#1325 posture)
    want_rs = posture.get("main_ruleset", {})
    data, err = _gh_api_result(f"repos/{repo}/rulesets/{want_rs.get('id')}")
    if err:
        if err["classification"] == "scope":
            surfaces["main_ruleset"] = {"status": "unavailable", "detail": err["detail"]}
            scope_gaps.append(f"rulesets/{want_rs.get('id')} (needs fine-grained Administration:read)")
        elif err["classification"] == "absent":
            surfaces["main_ruleset"] = {
                "status": "drift",
                "detail": f"ruleset {want_rs.get('id')} ({'/'.join(want_rs.get('rule_types', []))}) no longer exists — "
                "force-push/deletion protection on main is GONE",
            }
        else:
            surfaces["main_ruleset"] = {"status": "error", "detail": err["detail"]}
    else:
        problems = []
        if data.get("enforcement") != want_rs.get("enforcement", "active"):
            problems.append(f"enforcement={data.get('enforcement')!r} (documented {want_rs.get('enforcement', 'active')!r})")
        live_rules = sorted(r.get("type") for r in data.get("rules", []) if r.get("type"))
        want_rules = sorted(want_rs.get("rule_types", []))
        if live_rules != want_rules:
            problems.append(f"rules={live_rules} (documented exactly {want_rules})")
        include = (data.get("conditions", {}).get("ref_name", {}) or {}).get("include", [])
        for ref in want_rs.get("include_refs", []):
            if ref not in include:
                problems.append(f"{ref} missing from ref_name.include={include}")
        if problems:
            surfaces["main_ruleset"] = {"status": "drift", "detail": "; ".join(problems)}
        else:
            surfaces["main_ruleset"] = {"status": "clean", "live_rules": live_rules}

    # 2b. the fast-lane required-checks ruleset (#1662, ADR-148)
    #
    # Matched by NAME, not id: this ruleset is created by
    # scripts/apply_branch_protection.py and its id is only knowable after the first
    # apply, so pinning an id here would make the posture file un-writable ahead of
    # time. The preserved #1325 ruleset above is still matched by id — the two never
    # collide because a name match is required here and that name is refused there.
    want_rc = posture.get("main_required_checks_ruleset")
    if want_rc:
        data, err = _gh_api_result(f"repos/{repo}/rulesets")
        if err:
            if err["classification"] == "scope":
                surfaces["main_required_checks_ruleset"] = {"status": "unavailable", "detail": err["detail"]}
                scope_gaps.append("rulesets (needs fine-grained Administration:read)")
            else:
                surfaces["main_required_checks_ruleset"] = {"status": "error", "detail": err["detail"]}
        else:
            match = next((rs for rs in (data or []) if rs.get("name") == want_rc.get("name")), None)
            if match is None:
                surfaces["main_required_checks_ruleset"] = {
                    "status": "drift",
                    "detail": f"ruleset {want_rc.get('name')!r} is absent — `main` has NO required status checks "
                    "(fix: python3 scripts/apply_branch_protection.py --apply)",
                }
            else:
                full, err2 = _gh_api_result(f"repos/{repo}/rulesets/{match['id']}")
                if err2:
                    surfaces["main_required_checks_ruleset"] = {"status": "error", "detail": err2["detail"]}
                else:
                    surfaces["main_required_checks_ruleset"] = _judge_required_checks(full, want_rc)

    # 2c. repo-level merge settings — auto-merge is the mechanism ADR-148 depends on
    want_settings = posture.get("repo_settings")
    if want_settings:
        data, err = _gh_api_result(f"repos/{repo}")
        if err:
            surfaces["repo_settings"] = {"status": "error", "detail": err["detail"]}
        else:
            mismatches = {k: {"documented": v, "live": data.get(k)} for k, v in want_settings.items() if k != "source" and data.get(k) != v}
            if mismatches:
                surfaces["repo_settings"] = {
                    "status": "drift",
                    "detail": "; ".join(f"{k}: documented {m['documented']!r}, live {m['live']!r}" for k, m in mismatches.items())
                    + " (fix: python3 scripts/apply_branch_protection.py --apply)",
                }
            else:
                surfaces["repo_settings"] = {"status": "clean", "live": {k: data.get(k) for k in want_settings if k != "source"}}

    # 3. vulnerability / Dependabot alerts enablement (ADR-082's remediation channel)
    want_va = bool(posture.get("vulnerability_alerts", {}).get("enabled"))
    data, err = _gh_api_result(f"repos/{repo}/vulnerability-alerts")
    if err is None:
        live_va = True  # 204 No Content = enabled
    elif err["classification"] == "absent" and "disabled" in err["detail"].lower():
        live_va = False  # semantic 404: "Vulnerability alerts are disabled."
    elif err["classification"] in ("scope", "absent"):
        # A generic 404/403 here means the token lacks admin read (GitHub hides the
        # surface) — indistinguishable from disabled, so report it honestly as a gap.
        surfaces["vulnerability_alerts"] = {"status": "unavailable", "detail": err["detail"]}
        scope_gaps.append("vulnerability-alerts (needs fine-grained Administration:read)")
        live_va = None
    else:
        surfaces["vulnerability_alerts"] = {"status": "error", "detail": err["detail"]}
        live_va = None
    if live_va is not None:
        if live_va == want_va:
            surfaces["vulnerability_alerts"] = {"status": "clean", "enabled": live_va}
        else:
            surfaces["vulnerability_alerts"] = {
                "status": "drift",
                "documented": {"enabled": want_va},
                "live": {"enabled": live_va},
                "detail": f"documented posture enabled={want_va} but live enabled={live_va} "
                "(one-click owner toggle: repo Settings → Advanced Security)",
            }

    statuses = [s["status"] for s in surfaces.values()]
    if "drift" in statuses:
        status = "drift"
    elif "error" in statuses:
        status = "error"
    elif "unavailable" in statuses:
        status = "unavailable"
    else:
        status = "clean"
    result = {"status": status, "surfaces": surfaces}
    if scope_gaps:
        result["needs_owner"] = f"GitHub posture surface(s) unreadable with the current token: {'; '.join(scope_gaps)}. {PAT_FIX}."
    return result


def _is_bot_commit(c):
    """True for commits committed by a [bot] identity (e.g. github-actions[bot] —
    the ci-cd reconcile commits). GITHUB_TOKEN pushes structurally never trigger
    push-event workflows (GitHub's recursive-workflow prevention), so expecting a
    run for them would false-alarm on every merge-queue reconcile."""
    for login in ((c.get("author") or {}).get("login"), (c.get("committer") or {}).get("login")):
        if login and login.endswith("[bot]"):
            return True
    name = ((c.get("commit") or {}).get("committer") or {}).get("name", "")
    return bool(name) and name.endswith("[bot]")


def _commit_files(repo, sha):
    """Changed-file paths for one commit; None (soft) if unreadable."""
    data, err = _gh_api_result(f"repos/{repo}/commits/{sha}")
    if err:
        return None
    return [f.get("filename", "") for f in data.get("files", [])]


def check_github_push_runs(max_file_lookups=15):
    """#1544 — the "push-event runs stopped queuing" detector.

    Compares the last N commits on main against push-event workflow runs:

      * STALLED (drift, ≥1): a trigger-matching commit OLDER than the grace
        window, NEWER than the newest run-covered commit, with no push-event run
        whose head_sha matches — the live "merges are landing, nothing queues"
        state (six merges sat in exactly this state for ~3h on 2026-07-19).
      * HISTORICAL GAP (reported, NEVER alarmed — #1782): trigger-matching
        commits older than the newest covered commit that never got a run of
        their own. This is NOT evidence of a miss: a multi-commit `git push`
        produces exactly ONE push event, whose run's head_sha is the push HEAD
        — every OTHER commit in that same push structurally has zero runs, by
        GitHub design, no matter how many commits the push carries. The
        2026-07-26 sweep flagged 18 such commits from one solo-session batch
        push as "drift" before this fix. A real single-commit push that
        silently missed its own run is *indistinguishable* from a batch-push
        tail using only /commits + /actions/runs data (both look identical:
        "an uncovered commit sits just behind a covered one") — a count-based
        cluster threshold on this signal alone cannot safely alarm without
        false-positiving on every ordinary multi-commit push session, so it no
        longer tries to. `gap_commits` stays populated for visibility. The one
        alarm this check keeps is STALLED above — a push HEAD (the only commit
        GitHub could ever have run CI for) with no run past the grace window is
        unambiguous and stays load-bearing (#1544).

    Path-filter aware via PUSH_TRIGGER_GLOBS — commits touching only e.g.
    handovers/ trigger nothing and are never counted. Commits committed by a
    [bot] identity (the ci-cd reconcile commits, pushed with a workflow's
    GITHUB_TOKEN) are exempt: GitHub deliberately never creates push-event runs
    for GITHUB_TOKEN pushes (recursive-workflow prevention — ci-cd.yml documents
    this and compensates in-workflow), verified live 2026-07-19 on two reconcile
    commits. Commits younger than grace_minutes are never judged (runs may still
    be queuing). Commits older than the fetched runs window are skipped
    (coverage unknown, stated). All thresholds live in deploy/github_posture.json's
    push_run_detector block. GET-only; fail-soft "unavailable" (never red) when
    the token lacks Actions:read for /actions/runs."""
    try:
        cfg = _load_github_posture().get("push_run_detector", {})
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read github_posture.json: {e}"}
    grace_min = int(cfg.get("grace_minutes", 30))
    lookback_days = int(cfg.get("lookback_days", 7))
    max_commits = int(cfg.get("max_commits", 30))

    repo = _github_repo()
    commits, err = _gh_api_result(f"repos/{repo}/commits?sha=main&per_page={max_commits}")
    if err:
        if err["classification"] == "scope":
            return {
                "status": "unavailable",
                "detail": err["detail"],
                "needs_owner": f"commits on main unreadable with the current token (needs Contents:read). {PAT_FIX}.",
            }
        return {"status": "error", "detail": err["detail"]}

    runs_data, err = _gh_api_result(f"repos/{repo}/actions/runs?event=push&branch=main&per_page=100")
    if err:
        if err["classification"] == "scope":
            return {
                "status": "unavailable",
                "detail": err["detail"],
                "needs_owner": f"/actions/runs unreadable with the current token (needs Actions:read). {PAT_FIX}.",
            }
        return {"status": "error", "detail": err["detail"]}
    runs = runs_data.get("workflow_runs", [])
    covered_shas = {r.get("head_sha") for r in runs}
    oldest_run_dt = None
    if runs:
        try:
            oldest_run_dt = min(_parse_gh_date(r.get("created_at")) for r in runs if r.get("created_at"))
        except Exception:  # noqa: BLE001
            oldest_run_dt = None

    now = datetime.now(timezone.utc)
    window = []
    bots_skipped = 0
    for i, c in enumerate(commits or []):
        try:
            dt = _parse_gh_date(c["commit"]["committer"]["date"])
        except Exception:  # noqa: BLE001
            continue
        if i > 0 and (now - dt).total_seconds() > lookback_days * 86400:
            break  # past the lookback (the head commit is always considered)
        if _is_bot_commit(c):
            bots_skipped += 1  # GITHUB_TOKEN pushes never get push-event runs (GitHub rule)
            continue
        window.append({"sha": c["sha"], "date": dt, "age_min": (now - dt).total_seconds() / 60})

    newest_covered_idx = next((i for i, w in enumerate(window) if w["sha"] in covered_shas), None)

    stalled, gaps, notes = [], [], []
    file_lookups = 0
    for idx, w in enumerate(window):
        if w["sha"] in covered_shas or w["age_min"] < grace_min:
            continue
        if oldest_run_dt is not None and w["date"] < oldest_run_dt:
            notes.append(f"{w['sha'][:8]} predates the fetched runs window — coverage unknown, skipped")
            continue
        if file_lookups < max_file_lookups:
            file_lookups += 1
            files = _commit_files(repo, w["sha"])
        else:
            files = None
        if files is None:
            notes.append(f"{w['sha'][:8]} files unreadable/capped — conservatively treated as trigger-matching")
            triggers = True
        else:
            triggers = any(_matches_push_trigger(p) for p in files)
        if not triggers:
            continue  # e.g. a handovers/-only wrap commit — zero runs is correct
        entry = {"sha": w["sha"], "date": w["date"].isoformat(), "waiting_min": round(w["age_min"], 1)}
        if newest_covered_idx is None or idx < newest_covered_idx:
            stalled.append(entry)
        else:
            gaps.append(entry)

    detail_parts = []
    if stalled:
        detail_parts.append(
            f"push-event runs are NOT QUEUING: {len(stalled)} trigger-matching merge(s) on main newer than the last "
            f"run-covered commit have zero workflow runs after the {grace_min}-min grace window (the #1544 class) — "
            "check githubstatus.com + the Actions spending limit, and deploy manually from main until resolved"
        )
    # #1782: historical gaps are reported, never alarmed. A count-based cluster
    # threshold here false-positived on ordinary multi-commit pushes (18 non-head
    # commits from ONE batch push flagged "drift" on 2026-07-26) — GitHub gives
    # exactly one run per push, at the push HEAD, so N-1 uncovered predecessors is
    # the expected, healthy shape for a push of N commits, not evidence of anything
    # missed. STALLED above (a push HEAD itself with no run) is the one signal this
    # data can actually prove and remains the sole drift trigger.
    status = "drift" if detail_parts else "clean"
    result = {
        "status": status,
        "commits_checked": len(window),
        "bot_commits_exempt": bots_skipped,
        "runs_seen": len(runs),
        "stalled": stalled,
        "gap_commits": gaps,
    }
    if detail_parts:
        result["detail"] = "; ".join(detail_parts)
    if gaps:
        result["note"] = (
            f"{len(gaps)} uncovered historical commit(s) — non-head commits of a multi-commit push legitimately "
            "have no run of their own (only the push HEAD gets one); reported for visibility, never alarmed (#1782)"
        )
    if notes:
        result["skipped"] = notes[:10]
    return result
