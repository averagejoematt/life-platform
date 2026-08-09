"""#2377 — bundle commit fingerprint + deploy ancestry gate.

Two halves, both offline (no AWS, no network, and no reliance on this
checkout's real git history for the classification tests — the ancestry oracle
is injected):

  1. `build_bundle.stage_build_info` / `git_fingerprint` produce a readable
     `build_info.json` at the bundle root, in BOTH bundle shapes.
  2. `bundle_ancestry.classify` turns (deployed sha, shipping sha) into a
     deploy verdict — including the 2026-08-08 replay: an older CI run's bundle
     landing after a newer merge must come back REFUSED, not green.
"""

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEPLOY_DIR = os.path.join(REPO_ROOT, "deploy")
sys.path.insert(0, DEPLOY_DIR)

import build_bundle  # noqa: E402
import bundle_ancestry as ba  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# A toy commit graph for the ancestry oracle. main is linear; `fork` hangs off
# an older commit so it is neither ancestor nor descendant of the tip.
#
#   c1 ── c2 ── c3 ── c4        (main)
#          └──── f1             (fork)
# ══════════════════════════════════════════════════════════════════════════
_PARENTS = {
    "c1": [],
    "c2": ["c1"],
    "c3": ["c2"],
    "c4": ["c3"],
    "f1": ["c2"],
}


def _ancestors(sha):
    seen, stack = set(), list(_PARENTS.get(sha, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(_PARENTS.get(cur, []))
    return seen


def fake_is_ancestor(a, b):
    """True/False/None oracle over the toy graph; None = 'commit unknown here'."""
    if a not in _PARENTS or b not in _PARENTS:
        return None
    return a in _ancestors(b)


@pytest.fixture(scope="module")
def real_repo(tmp_path_factory):
    """A throwaway git repo with the same shape as the toy graph.

    The CLI resolves ancestry through real `git merge-base --is-ancestor`, so the
    end-to-end exit-code assertions need real commits — this also mutation-proves
    `git_is_ancestor` itself rather than only the injected oracle.

    Returns {"c1": <sha>, …}.
    """
    root = tmp_path_factory.mktemp("ancestry_repo")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*args):
        out = subprocess.run(["git"] + list(args), cwd=str(root), env=env, capture_output=True, text=True)
        assert out.returncode == 0, f"git {' '.join(args)} failed: {out.stderr}"
        return out.stdout.strip()

    def commit(name):
        (root / f"{name}.txt").write_text(name)
        git("add", "-A")
        git("commit", "-q", "-m", name)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    shas = {}
    for name in ("c1", "c2", "c3", "c4"):
        shas[name] = commit(name)
    git("checkout", "-q", "-b", "fork", shas["c2"])
    shas["f1"] = commit("f1")
    git("checkout", "-q", "main")
    shas["repo"] = str(root)
    return shas


# ══════════════════════════════════════════════════════════════════════════
# 1. build_info.json generation
# ══════════════════════════════════════════════════════════════════════════


def test_git_fingerprint_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("BUNDLE_GIT_SHA", "ABCDEF1234567890abcdef1234567890abcdef12")
    monkeypatch.setenv("GITHUB_SHA", "9999999999999999999999999999999999999999")
    info = build_bundle.git_fingerprint()
    assert info["git_sha"] == "abcdef1234567890abcdef1234567890abcdef12", "override must win and be normalised lowercase"
    assert info["git_short_sha"] == "abcdef12"
    # An env-supplied sha describes THAT commit, not this worktree — claiming
    # dirty/clean about it would be a fabricated field.
    assert info["dirty"] is None


def test_git_fingerprint_falls_back_to_github_sha(monkeypatch):
    monkeypatch.delenv("BUNDLE_GIT_SHA", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert build_bundle.git_fingerprint()["git_sha"] == "0123456789abcdef0123456789abcdef01234567"


def test_git_fingerprint_survives_a_non_git_directory(monkeypatch, tmp_path):
    """A bundle built outside a checkout must stage an honest null, not crash."""
    monkeypatch.delenv("BUNDLE_GIT_SHA", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    info = build_bundle.git_fingerprint(repo_root=str(tmp_path))
    assert info["git_sha"] is None
    assert info["built_at"].endswith("Z")


def test_stage_build_info_writes_readable_json(tmp_path):
    out = tmp_path / "stage"
    out.mkdir()
    path = build_bundle.stage_build_info(str(out), info={"git_sha": "c4" * 20, "built_at": "2026-08-09T00:00:00Z"})
    assert os.path.basename(path) == build_bundle.BUILD_INFO_NAME
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["git_sha"] == "c4" * 20


@pytest.mark.parametrize("mcp", [False, True])
def test_every_bundle_shape_carries_the_fingerprint(tmp_path, monkeypatch, mcp):
    """Acceptance box 1: build_bundle.py writes build_info.json into EVERY bundle."""
    monkeypatch.setenv("BUNDLE_GIT_SHA", "feedface" * 5)
    out = str(tmp_path / ("mcp" if mcp else "tree"))
    build_bundle.stage_mcp(out) if mcp else build_bundle.stage_tree(out)
    info_path = os.path.join(out, "build_info.json")
    assert os.path.isfile(info_path), "bundle root has no build_info.json — the fingerprint is not shipping"
    with open(info_path, encoding="utf-8") as f:
        assert json.load(f)["git_sha"] == "feedface" * 5


# ══════════════════════════════════════════════════════════════════════════
# 2. parse_build_info — must degrade, never raise
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json at all",
        '{"git_sha": null}',
        '{"git_sha": ""}',
        '{"git_sha": 12345}',
        '["a", "list"]',
        '{"built_at": "2026-08-09T00:00:00Z"}',
    ],
)
def test_parse_build_info_returns_none_for_unusable_input(raw):
    assert ba.parse_build_info(raw) is None


def test_parse_build_info_normalises():
    assert ba.parse_build_info('{"git_sha": "  ABCDEF  "}') == "abcdef"


# ══════════════════════════════════════════════════════════════════════════
# 3. classify — the deploy verdict
# ══════════════════════════════════════════════════════════════════════════


def test_same_sha_is_idempotent_redeploy():
    assert ba.classify("c3", "c3", is_ancestor=fake_is_ancestor) == ba.SAME


def test_forward_deploy_is_a_fast_forward():
    assert ba.classify("c2", "c4", is_ancestor=fake_is_ancestor) == ba.FAST_FORWARD


def test_diverged_history_is_refused():
    verdict = ba.classify("c4", "f1", is_ancestor=fake_is_ancestor)
    assert verdict == ba.DIVERGED
    assert verdict in ba.REFUSING


def test_missing_fingerprint_is_unknown_not_green():
    # A function deployed before #2377 landed carries no build_info.json.
    assert ba.classify(None, "c4", is_ancestor=fake_is_ancestor) == ba.UNKNOWN
    assert ba.classify("c4", None, is_ancestor=fake_is_ancestor) == ba.UNKNOWN
    # ...and unknown must NOT be in the refusing set, or day one bricks deploys.
    assert ba.UNKNOWN not in ba.REFUSING


def test_unresolvable_sha_is_unknown_not_diverged():
    """git can't answer (shallow clone / unfetched branch) → UNKNOWN, never a
    bogus `diverged` refusal. This is the difference between 'I can't tell' and
    'these are unrelated'."""
    assert ba.classify("c4", "deadbeef", is_ancestor=fake_is_ancestor) == ba.UNKNOWN


def test_short_sha_on_one_side_still_matches_identity():
    long = "abcdef1234567890abcdef1234567890abcdef12"
    assert ba.classify(long, long[:8], is_ancestor=lambda a, b: None) == ba.SAME
    # A 4-char prefix is too weak to claim identity — must not be read as SAME.
    assert ba.classify(long, long[:4], is_ancestor=lambda a, b: None) == ba.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════
# 4. Acceptance box 3 — replay the 2026-08-08 race
# ══════════════════════════════════════════════════════════════════════════


def test_git_is_ancestor_answers_real_history(real_repo):
    """The oracle the CLI actually uses, against real commits."""
    repo = real_repo["repo"]
    assert ba.git_is_ancestor(real_repo["c2"], real_repo["c4"], repo_root=repo) is True
    assert ba.git_is_ancestor(real_repo["c4"], real_repo["c2"], repo_root=repo) is False
    assert ba.git_is_ancestor(real_repo["f1"], real_repo["c4"], repo_root=repo) is False
    # A commit this checkout has never seen → None ("can't tell"), not False.
    assert ba.git_is_ancestor("0" * 40, real_repo["c4"], repo_root=repo) is None


def test_replays_the_2026_08_08_race_as_a_refusal(real_repo):
    """The incident, mechanised.

    Run A is queued at c2. Run B merges c4 and deploys it. Run A is then
    approved and ships its OLD tree over the newer one. Every check we had at
    the time passed: the zip uploaded fine, LastModified went fresh, and the
    smoke test hit a working site. The ONLY structural tell is that run A's
    shipping sha is an ancestor of what is already live.
    """
    live_after_run_b = "c4"
    run_a_shipping = "c2"

    verdict = ba.classify(live_after_run_b, run_a_shipping, is_ancestor=fake_is_ancestor)
    assert verdict == ba.STALE, "the 08-08 race must classify as a stale overwrite"
    assert verdict in ba.REFUSING, "a stale overwrite must be REFUSED, not merely logged"

    message = ba.explain(verdict, live_after_run_b, run_a_shipping, function_name="daily-brief")
    assert "REFUSING" in message
    assert ba.OVERRIDE_ENV in message, "the refusal must name its own escape hatch"

    # And the CLI, over REAL git history, exits non-zero — which is what actually
    # stops the deploy script (`if ! bash verify_bundle_ancestry.sh …`).
    repo, live, ships = real_repo["repo"], real_repo["c4"], real_repo["c2"]
    assert ba.main(["--deployed", live, "--shipping", ships, "--function", "daily-brief", "--repo", repo]) == 2

    # Control: the same two runs in the correct order are allowed.
    assert ba.main(["--deployed", ships, "--shipping", live, "--repo", repo]) == 0


def test_rollback_override_downgrades_the_refusal(monkeypatch, real_repo):
    """Shipping older code ON PURPOSE (a rollback) must stay possible."""
    args = ["--deployed", real_repo["c4"], "--shipping", real_repo["c2"], "--repo", real_repo["repo"]]
    assert ba.main(args) == 2
    monkeypatch.setenv(ba.OVERRIDE_ENV, "1")
    assert ba.main(args) == 0, "ALLOW_NON_FAST_FORWARD=1 must downgrade the refusal, or rollbacks are impossible"


def test_diverged_history_is_refused_end_to_end(real_repo):
    assert ba.main(["--deployed", real_repo["c4"], "--shipping", real_repo["f1"], "--repo", real_repo["repo"]]) == 2


# ══════════════════════════════════════════════════════════════════════════
# 5. Postflight is stricter than preflight
# ══════════════════════════════════════════════════════════════════════════


def test_postflight_rejects_a_descendant_landing_on_top_of_us(real_repo):
    """Preflight allows c2→c4. Postflight after shipping c2 must NOT accept a
    live c4 — that means someone else's deploy overwrote ours mid-flight."""
    ok, verdict = ba.postflight_ok("c4", "c2", is_ancestor=fake_is_ancestor)
    assert ok is False and verdict == ba.STALE
    args = ["--deployed", real_repo["c4"], "--shipping", real_repo["c2"], "--mode", "postflight", "--repo", real_repo["repo"]]
    assert ba.main(args) == 2


def test_postflight_accepts_exactly_what_we_shipped(real_repo):
    ok, verdict = ba.postflight_ok("c4", "c4", is_ancestor=fake_is_ancestor)
    assert ok is True and verdict == ba.SAME
    args = ["--deployed", real_repo["c4"], "--shipping", real_repo["c4"], "--mode", "postflight", "--repo", real_repo["repo"]]
    assert ba.main(args) == 0


def test_postflight_on_an_unfingerprinted_function_is_allowed_but_loud():
    ok, verdict = ba.postflight_ok(None, "c4", is_ancestor=fake_is_ancestor)
    assert ok is True and verdict == ba.UNKNOWN
    assert "UNKNOWN" in ba.explain(verdict, None, "c4", mode="postflight")


# ══════════════════════════════════════════════════════════════════════════
# 6. The gate is actually wired into the deploy paths
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("script", ["deploy_lambda.sh", "deploy_fleet.sh", "deploy_site_api.sh"])
def test_deploy_paths_call_the_ancestry_gate(script):
    with open(os.path.join(DEPLOY_DIR, script), encoding="utf-8") as f:
        text = f.read()
    assert "verify_bundle_ancestry.sh" in text, f"{script} does not run the #2377 ancestry gate"
    assert "preflight" in text, f"{script} has no preflight refusal — a stale overwrite would land before anyone looked"


def test_ancestry_gate_script_is_executable_and_fail_soft():
    path = os.path.join(DEPLOY_DIR, "verify_bundle_ancestry.sh")
    assert os.access(path, os.X_OK), "verify_bundle_ancestry.sh must be executable"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # An AWS/network failure must not block a deploy — it must be visible instead.
    assert "unverified, allowing" in text
    assert "SKIP_ANCESTRY_CHECK" in text
