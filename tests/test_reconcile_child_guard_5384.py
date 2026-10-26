"""tests/test_reconcile_child_guard_5384.py — never reject the run that OWNS a reconcile child's deploy (#5384).

Incident 2026-10-26: PR #5383 merged at 3ead5f4ee; the bot's `chore(reconcile): ... [skip-reconcile]`
commit e43171b26 minted a second CI/CD run whose Plan deferred its deploy to the parent's run
(#4250); the parent's run was then rejected as "an ancestor of main" and nothing deployed.

Three layers are pinned:
  1. the pure classifier `find_reconcile_child` (protected / not);
  2. `deploy/reject_deployment.sh` END TO END against a stubbed `gh` on PATH — refuse, force,
     clear and indeterminate — asserting whether a rejecting POST was ever sent;
  3. the post-hoc detector `stranded_reconcile_shape` and its `check_main_green` rendering.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

import check_deploy_deadman as ddm  # noqa: E402
import check_main_green as cmg  # noqa: E402
import reconcile_child_guard as rcg  # noqa: E402

PARENT_SHA = "3ead5f4ee" + "0" * 31
CHILD_SHA = "e43171b26" + "0" * 31
OTHER_SHA = "9999aaaa0" + "0" * 31
PARENT_RUN, CHILD_RUN = 40263440771, 40263503459
RECONCILE_MSG = "chore(reconcile): regenerate derived artifacts after merge [skip-reconcile]\n\nbody"


def _run(rid, sha, created, msg, branch="main"):
    return {"id": rid, "head_sha": sha, "created_at": created, "head_branch": branch, "head_commit": {"message": msg}}


PARENT = _run(PARENT_RUN, PARENT_SHA, "2026-10-26T01:00:00Z", "feat: wave 1 (#5383)")
CHILD = _run(CHILD_RUN, CHILD_SHA, "2026-10-26T01:01:00Z", RECONCILE_MSG)


def _parents(mapping):
    return lambda sha: mapping[sha]


# ── 1. the pure classifier ───────────────────────────────────────────────────────


def test_subject_predicate_is_the_plan_sides_predicate():
    assert rcg.RECONCILE_SUBJECT_PREFIX == ddm.RECONCILE_SUBJECT_PREFIX
    assert rcg.RECONCILE_MARKER == ddm.RECONCILE_MARKER


def test_reconcile_child_protects_its_parent():
    child = rcg.find_reconcile_child(PARENT, [PARENT, CHILD], _parents({CHILD_SHA: [PARENT_SHA]}))
    assert child is not None and child["id"] == CHILD_RUN


def test_every_non_protecting_shape_is_clear():
    # (a) the newer run is an ordinary merge, not the bot's commit
    ordinary = _run(7, OTHER_SHA, "2026-10-26T01:02:00Z", "feat: another merge (#1)")
    assert rcg.find_reconcile_child(PARENT, [PARENT, ordinary], _parents({OTHER_SHA: [PARENT_SHA]})) is None
    # (b) the marker subject but a DIFFERENT parent — it does not carry this run's tree
    stacked = _run(8, OTHER_SHA, "2026-10-26T01:02:00Z", RECONCILE_MSG)
    assert rcg.find_reconcile_child(PARENT, [PARENT, stacked], _parents({OTHER_SHA: ["f" * 40]})) is None
    # (c) a merge commit (two parents) is never the single-parent bot commit
    assert rcg.find_reconcile_child(PARENT, [PARENT, stacked], _parents({OTHER_SHA: [PARENT_SHA, "f" * 40]})) is None
    # (d) the reconcile run is OLDER than the target — it cannot be waiting on it
    old_child = _run(9, CHILD_SHA, "2026-10-25T00:00:00Z", RECONCILE_MSG)
    assert rcg.find_reconcile_child(PARENT, [PARENT, old_child], _parents({CHILD_SHA: [PARENT_SHA]})) is None
    # (e) the subject alone (no marker) is not the bot's commit
    no_marker = _run(10, CHILD_SHA, "2026-10-26T01:03:00Z", "chore(reconcile): by hand")
    assert rcg.find_reconcile_child(PARENT, [PARENT, no_marker], _parents({CHILD_SHA: [PARENT_SHA]})) is None


# ── 2. reject_deployment.sh end to end, against a stubbed gh ─────────────────────

STUB = r"""#!/usr/bin/env python3
import json, os, sys
fx = json.load(open(os.environ["GH_STUB_FIXTURE"]))
log = os.environ["GH_STUB_LOG"]
args = sys.argv[1:]
open(log, "a").write(json.dumps(args) + "\n")
assert args[0] == "api", args
url = args[1]
if "--input" in args:
    open(log + ".post", "w").write(sys.stdin.read())
    sys.exit(0)
if url.endswith("/pending_deployments"):
    # --jq '[...] | @json' is the ENV_IDS read; the other --jq is the human listing.
    jq = args[args.index("--jq") + 1] if "--jq" in args else ""
    print("[1234]" if "@json" in jq else "  env=production id=1234 can_approve=true")
    sys.exit(0)
if "/commits/" in url:
    sha = url.rsplit("/", 1)[1]
    if sha in fx.get("commit_errors", []):
        sys.exit(1)
    print(json.dumps({"parents": [{"sha": p} for p in fx["parents"][sha]]}))
    sys.exit(0)
if "/actions/workflows/ci-cd.yml/runs" in url:
    print(json.dumps({"workflow_runs": fx["runs"]}))
    sys.exit(0)
if "/actions/runs/" in url:
    rid = int(url.rsplit("/", 1)[1])
    print(json.dumps(next(r for r in fx["runs"] if r["id"] == rid)))
    sys.exit(0)
sys.exit(f"stub gh: unhandled {args}")
"""


def _reject(tmp_path, runs, parents, extra_args=(), commit_errors=()):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"runs": runs, "parents": parents, "commit_errors": list(commit_errors)}))
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", GH_STUB_FIXTURE=str(fx), GH_STUB_LOG=str(tmp_path / "gh.log"))
    proc = subprocess.run(
        ["bash", str(_REPO / "deploy" / "reject_deployment.sh"), *extra_args, str(PARENT_RUN)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    post = tmp_path / "gh.log.post"
    return proc, (json.loads(post.read_text()) if post.exists() else None)


def test_script_refuses_to_reject_the_run_a_reconcile_child_defers_to(tmp_path):
    proc, post = _reject(tmp_path, [PARENT, CHILD], {CHILD_SHA: [PARENT_SHA]})
    out = proc.stdout + proc.stderr
    assert proc.returncode == rcg.EXIT_PROTECTED == 3, out
    assert post is None, "a rejecting POST was sent despite the guard"
    assert f"bash deploy/approve_deployment.sh {PARENT_RUN}" in out
    assert "--force-ancestor" in out and str(CHILD_RUN) in out


def test_force_ancestor_keeps_the_old_behaviour(tmp_path):
    proc, post = _reject(tmp_path, [PARENT, CHILD], {CHILD_SHA: [PARENT_SHA]}, extra_args=("--force-ancestor",))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert post is not None and post["state"] == "rejected" and post["environment_ids"] == [1234]


def test_an_ordinary_stale_run_is_still_rejected(tmp_path):
    ordinary = _run(7, OTHER_SHA, "2026-10-26T01:02:00Z", "feat: a later merge (#1)")
    proc, post = _reject(tmp_path, [PARENT, ordinary], {OTHER_SHA: [PARENT_SHA]})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert post is not None and post["state"] == "rejected"


def test_unreadable_verdict_refuses_rather_than_rejecting_blind(tmp_path):
    proc, post = _reject(tmp_path, [PARENT, CHILD], {}, commit_errors=[CHILD_SHA])
    assert proc.returncode == rcg.EXIT_INDETERMINATE, proc.stdout + proc.stderr
    assert post is None
    assert "--force-ancestor" in proc.stdout + proc.stderr


# ── 3. the post-hoc stranded shape ───────────────────────────────────────────────


def _gh_run(rid, sha, created, title, conclusion="success", status="completed"):
    return {"databaseId": rid, "headSha": sha, "createdAt": created, "displayTitle": title, "conclusion": conclusion, "status": status}


G_PARENT = _gh_run(PARENT_RUN, PARENT_SHA, "2026-10-26T01:00:00Z", "feat: wave 1 (#5383)", conclusion="failure")
G_CHILD = _gh_run(
    CHILD_RUN, CHILD_SHA, "2026-10-26T01:01:00Z", "chore(reconcile): regenerate derived artifacts after merge [skip-reconcile]"
)

# The REAL shapes of the incident: the rejected run's Deploy IAM gate is the red job; the
# child's Deploy was skipped by its own Plan's #4250 deferral.
PARENT_JOBS = [
    {"name": "Plan deployments", "conclusion": "success"},
    {"name": "Deploy", "conclusion": "skipped"},
    {"name": "Deploy IAM (production gate)", "conclusion": "failure"},
    {"name": "Notify failure", "conclusion": "success"},
]
CHILD_JOBS = [
    {"name": "Plan deployments", "conclusion": "success"},
    {"name": "Deploy", "conclusion": "skipped"},
    {"name": "Deploy IAM (production gate)", "conclusion": "skipped"},
]


def _shape(runs, parent_jobs=PARENT_JOBS, child_jobs=CHILD_JOBS, parents=None):
    by_id = {PARENT_RUN: parent_jobs, CHILD_RUN: child_jobs}
    return rcg.stranded_reconcile_shape(runs, lambda r: by_id.get(r["databaseId"]), _parents_of_map(parents or {CHILD_SHA: [PARENT_SHA]}))


def _parents_of_map(m):
    return lambda sha: m[sha]


def test_stranded_shape_is_named_with_the_one_recovery_command():
    found = _shape([G_CHILD, G_PARENT])
    assert found is not None
    assert found["recovery"] == f"gh run rerun {PARENT_RUN} && bash deploy/approve_deployment.sh {PARENT_RUN}"


def test_stranded_shape_requires_every_clause():
    # parent actually deployed / is green -> nothing stranded
    assert _shape([G_CHILD, dict(G_PARENT, conclusion="success")]) is None
    # the parent is red for a real validation failure (Plan red) -> ordinary red, not this shape
    red_plan = [{"name": "Plan deployments", "conclusion": "failure"}, {"name": "Deploy", "conclusion": "skipped"}]
    assert _shape([G_CHILD, G_PARENT], parent_jobs=red_plan) is None
    # the child deployed itself -> it shipped the tree
    assert _shape([G_CHILD, G_PARENT], child_jobs=[{"name": "Deploy", "conclusion": "success"}]) is None
    # the newest run is not the reconcile child (a later merge superseded the strand)
    later = _gh_run(5, OTHER_SHA, "2026-10-26T02:00:00Z", "feat: later merge (#9)")
    assert _shape([later, G_CHILD, G_PARENT]) is None
    # the child's parent is some other sha
    assert _shape([G_CHILD, G_PARENT], parents={CHILD_SHA: ["f" * 40]}) is None
    # unreadable parent jobs -> no claim
    assert _shape([G_CHILD, G_PARENT], parent_jobs=None) is None


def test_main_green_names_the_strand_and_is_not_green():
    found = _shape([G_CHILD, G_PARENT])
    state = cmg.classify_pipeline([G_CHILD, G_PARENT], stranded_reconcile=found, expected_jobs={}, completed_jobs=[])
    assert state["kind"] == cmg.STRANDED_RECONCILE
    code, message = cmg.render(state)
    assert code == 1
    assert "STRANDED RECONCILE DEPLOY" in message and found["recovery"] in message


def test_main_green_unchanged_without_the_shape():
    state = cmg.classify_pipeline([G_CHILD], stranded_reconcile=None, expected_jobs={}, completed_jobs=[])
    assert state["kind"] == cmg.GREEN
