"""tests/test_doc_literal_conflict_surface_3101.py — the counters keep exactly ONE
committed home, and the single-writer plumbing stays wired (#3101).

WHAT WENT WRONG. The repo-derived counters (`test_count` and its siblings) were
rewritten in place inside `PLATFORM_STATS` in `lambdas/web/site_api_common.py` — a
hot shared module 134 endpoints import — and, for `test_count`, inside
`docs/TESTING.md`. `test_count` moves on every PR that adds a test, so the counter
was a committed line INSIDE diffs branches were legitimately carrying: inseparable,
therefore a guaranteed conflict against every concurrent PR and against each
post-merge reconcile-bot commit. The 2026-08-23/24 merge train paid ~3-4h of serial
reconcile rounds to it across 15 PRs.

WHAT THIS FILE GUARDS. The move only helps while it stays a move. Two ways it could
quietly come undone, and both are asserted below:
  1. a counter grows a SECOND committed home (someone re-adds `"test_count": N` to
     site_api_common.py, or re-types the number into TESTING.md) — the conflict
     surface reopens with nothing red;
  2. the single-writer plumbing rots — agent_commit stops refusing the file, the
     pre-commit hook goes back to staging site_api_common.py, or the reconcile
     whitelist no longer permits the generated module, so the bot's own commit
     fails the job.

GUARD THE SET, NOT THE INSTANCE: every assertion derives its field list from
`sync._platform_counts_values()`, so a counter added there is covered automatically
rather than needing a second edit here.
"""

import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import sync_doc_metadata as sync  # noqa: E402
from web.platform_counts import DISCOVERED_COUNTS  # noqa: E402
from web.site_api_common import PLATFORM_STATS  # noqa: E402

_COUNTS_MODULE = os.path.join(_REPO, "lambdas", "web", "platform_counts.py")
_SITE_API_COMMON = os.path.join(_REPO, "lambdas", "web", "site_api_common.py")
_TESTING_DOC = os.path.join(_REPO, "docs", "TESTING.md")
_AGENT_COMMIT = os.path.join(_REPO, "deploy", "agent_commit.sh")
_INSTALL_HOOKS = os.path.join(_REPO, "scripts", "install_hooks.sh")
_CI_CD = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _counter_fields():
    """The discovered-counter SET, from the sync itself — never hand-listed here."""
    fields = sorted(sync._platform_counts_values(dict(sync.PLATFORM_FACTS)))
    assert fields, "the sync reported no discovered counters — the derivation drifted"
    return fields


# ── 1. ONE committed home ─────────────────────────────────────────────────────


def test_the_generated_module_is_the_only_writable_target_of_the_sync():
    assert sync._PLATFORM_COUNTS_PATH == sync.ROOT / "lambdas" / "web" / "platform_counts.py"
    assert os.path.exists(_COUNTS_MODULE)
    # …and nothing else in the sync still points at the old in-place target.
    assert not hasattr(sync, "_sync_platform_stats"), "the old site_api_common writer is still callable"
    assert not hasattr(sync, "_PLATFORM_STATS_PATH"), "the old site_api_common target constant survived the move"


def test_every_counter_has_its_literal_in_the_generated_module():
    src = _read(_COUNTS_MODULE)
    for field in _counter_fields():
        assert re.search(rf'"{field}":\s*\d+', src), f"{field!r} has no literal in platform_counts.py — the sync cannot stamp it"


def test_no_counter_has_a_second_home_in_site_api_common():
    """The regression that would silently reopen the conflict surface."""
    src = _read(_SITE_API_COMMON)
    strays = [f for f in _counter_fields() if re.search(rf'"{f}":\s*\d+', src)]
    assert not strays, (
        f"#3101: {strays} carry a hand-merged literal in lambdas/web/site_api_common.py again. "
        "The discovered counters belong in lambdas/web/platform_counts.py ONLY — a counter in a "
        "file branches edit for other reasons conflicts with every concurrent PR."
    )


def test_testing_doc_states_the_count_as_derived_not_as_a_number():
    line = [ln for ln in _read(_TESTING_DOC).splitlines() if ln.startswith("**Total tests:**")]
    assert len(line) == 1, "docs/TESTING.md must carry exactly one **Total tests:** line"
    assert "derived, never committed" in line[0], line[0]
    # #4250: the number lives in no committed file at all — it is stamped into the bundle.
    assert "deploy/build_bundle.py" in line[0], "the doc must name where the number actually comes from"
    # No standalone integer big enough to be a test count (the issue refs are fine).
    assert not re.search(r"\b\d{4,}\b", line[0].replace("#3101", "").replace("#4250", "")), f"a count was re-typed into the doc: {line[0]}"


def test_the_sync_rule_for_the_testing_doc_still_guards_that_line():
    """A removed rule would let anyone re-type a number with nothing red. The rule is
    kept as an identity replacement; process_doc() treats a non-matching rule as drift."""
    rules = [(p, t) for doc, p, t in sync.RULES if doc == "docs/TESTING.md"]
    assert len(rules) == 1, "docs/TESTING.md should have exactly one sync rule"
    pattern, template = rules[0]
    assert "{test_count}" not in template, "the rule must not stamp a number back into the doc"
    line = [ln for ln in _read(_TESTING_DOC).splitlines() if ln.startswith("**Total tests:**")][0]
    assert re.search(pattern, line), "the rule no longer matches the doc line it guards (it would report drift forever)"
    assert sync.apply_facts(template) == line, "rule replacement and doc line must be character-identical (else --check never converges)"


# ── 2. The served contract did not lose a field ───────────────────────────────


def test_platform_stats_still_exposes_every_counter():
    for field in _counter_fields():
        assert field in PLATFORM_STATS, f"/api/platform_stats lost {field!r} in the move"
        assert PLATFORM_STATS[field] == DISCOVERED_COUNTS[field]


def test_the_splice_does_not_collide_with_a_judgment_field():
    """`PLATFORM_STATS = {**DISCOVERED_COUNTS, ...}` would let a later judgment key
    silently override a discovered one — the truth tests would then pin a number the
    sync never wrote."""
    src = _read(_SITE_API_COMMON)
    block = src[src.index("PLATFORM_STATS = {") :]
    block = block[: block.index("\n}\n")]
    hand_keys = re.findall(r'^\s{4}"([a-z0-9_]+)":', block, re.MULTILINE)
    overlap = sorted(set(hand_keys) & set(DISCOVERED_COUNTS))
    assert not overlap, f"hand-maintained PLATFORM_STATS keys shadow discovered counters: {overlap}"


# ── 3. The single-writer plumbing ─────────────────────────────────────────────


def test_agent_commit_refuses_the_generated_module_with_no_override():
    src = _read(_AGENT_COMMIT)
    assert "is_generated_only_file" in src, "agent_commit.sh lost its generated-file refusal"
    m = re.search(r"is_generated_only_file\(\)\s*\{(.+?)\n\}", src, re.S)
    assert m and "lambdas/web/platform_counts.py" in m.group(1), "platform_counts.py is not in agent_commit.sh's no-override refusal"
    # …and the unnamed-file scan must watch it too, or the hook's sweep rides along.
    assert re.search(r"git diff --name-only -- docs/ CLAUDE\.md \.claude/README\.md lambdas/web/platform_counts\.py", src)


def test_the_pre_commit_hook_stages_the_generated_module_on_main_only_and_never_site_api_common():
    """#3984: TWO arms. On `main` the counter is staged; off main it is restored to HEAD and the
    pathspec omits it. site_api_common.py is in neither."""
    src = _read(_INSTALL_HOOKS)
    specs = re.findall(r"SYNCED_CHANGED=\$\(git -C \"\$PROJ_ROOT\" diff --name-only -- ([^)]+?)\|\|", src)
    assert len(specs) == 2, f"expected the main arm and the off-main arm of the hook's stage pathspec, found {len(specs)}"
    main_arm, off_main_arm = specs
    assert "lambdas/web/platform_counts.py" in main_arm, "on main the hook must stage the regenerated counter"
    assert "lambdas/web/platform_counts.py" not in off_main_arm, "off main the counter must never be staged (#3984)"
    assert re.search(
        r'git -C "\$PROJ_ROOT" checkout "\$RESTORE_FROM" -- lambdas/web/platform_counts\.py', src
    ), "off main the hook must restore the counter to HEAD before staging (#3984)"
    assert re.search(r'if \[\[ "\$HOOK_BRANCH" == "main" \]\]', src), "the two arms must key on the checked-out branch"
    for spec in specs:
        assert "site_api_common.py" not in spec, (
            "the sync no longer writes site_api_common.py, so staging it would sweep the committer's "
            "own unstaged edits to a hot shared module into their commit"
        )


def test_the_reconcile_whitelist_permits_the_generated_module():
    """The bot regenerates it on main; a whitelist that omits it fails the job with no
    commit, which is the doc-literal treadmill back in a louder costume."""
    src = _read(_CI_CD)
    allowed = re.search(r"^\s*ALLOWED='(.+)'\s*$", src, re.M)
    assert allowed, "could not find the reconcile job's ALLOWED whitelist"
    assert re.match(allowed.group(1), "lambdas/web/platform_counts.py"), "the reconcile whitelist would reject the generated counter module"


# ── 4. Mutation proof — the guard still reds on a genuinely wrong count ───────


def test_sync_reports_drift_when_a_counter_literal_is_wrong(tmp_path, monkeypatch):
    """Not a re-assertion of the plumbing: a real mutation of the literal, proving
    --check's data path still fails. Runs against a COPY so the repo is untouched."""
    mutated = tmp_path / "platform_counts.py"
    src = _read(_COUNTS_MODULE)
    # #4250: `alarms`, not `test_count` — test_count left the committed set (bundle-stamped).
    real = sync._auto_discover_alarm_count()
    assert real is not None
    # Substitute over the MATCHED literal, never over an assumed value: the committed
    # number is allowed to lag reality between the reconcile bot's runs, and a mutation
    # test that silently no-ops when it does is the vacuous-gate class this file exists
    # to prevent. `real + 1` is wrong by construction whatever was there before.
    wrong = f'"alarms": {real + 1}'
    body, n = re.subn(r'"alarms":\s*\d+', wrong, src, count=1)
    assert n == 1, "no alarms literal in platform_counts.py — the literal shape drifted"
    mutated.write_text(body, encoding="utf-8")

    monkeypatch.setattr(sync, "_PLATFORM_COUNTS_PATH", mutated)
    # Pin the ENFORCED path explicitly — under ambient CI env this test would otherwise
    # assert different behaviour on a PR run than on a push run (the time-dependent-gate class).
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    changes = sync._sync_platform_counts(dict(sync.PLATFORM_FACTS), dry_run=True)
    drift = [c for c in changes if c.startswith("  ~") and "alarms" in c]
    assert drift, f"--check would NOT have caught a wrong alarms count: {changes}"
    # dry_run must not write, or --check would silently "fix" the drift it reports (#389).
    assert wrong in mutated.read_text(encoding="utf-8"), "dry_run wrote to disk"


def test_sync_reports_a_missing_counter_rather_than_skipping_it():
    """A field deleted from the generated module must be loud, not absent — the
    'gate that silently passes' class."""
    import pathlib
    import tempfile

    src = _read(_COUNTS_MODULE)
    with tempfile.TemporaryDirectory() as d:
        stripped = pathlib.Path(d) / "platform_counts.py"
        stripped.write_text(re.sub(r'^\s*"alarms":\s*\d+,\s*$\n', "", src, flags=re.M), encoding="utf-8")
        original = sync._PLATFORM_COUNTS_PATH
        try:
            sync._PLATFORM_COUNTS_PATH = stripped
            changes = sync._sync_platform_counts(dict(sync.PLATFORM_FACTS), dry_run=True)
        finally:
            sync._PLATFORM_COUNTS_PATH = original
    assert any(c.startswith("  !") and "alarms" in c for c in changes), f"a deleted counter was not reported: {changes}"


# ── 5. #4250: test_count left the committed set — stamped into the bundle instead ──
#
# It moved on nearly every merge, so the reconcile bot committed a one-integer bump to main
# after nearly every merge (7 d to 2026-09-27: 120 of 125 reconcile commits touched it, 70
# changed nothing else), each push a second CI/CD run and a gated fleet deploy.


def _with_test_count_line(src: str, n: int = 12345) -> str:
    """The pre-#4250 module shape (a `"test_count": N,` line), whatever main holds today."""
    if re.search(r'^\s*"test_count":', src, re.M):
        return src
    return src.replace("DISCOVERED_COUNTS = {\n", f'DISCOVERED_COUNTS = {{\n    "test_count": {n},\n', 1)


def test_the_sync_no_longer_owns_test_count():
    assert "test_count" not in _counter_fields(), "#4250: the sync would commit test_count to main after every merge again"


def test_the_reconcile_removes_a_leftover_test_count_literal_once_and_then_converges(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    legacy = tmp_path / "platform_counts.py"
    legacy.write_text(_with_test_count_line(_read(_COUNTS_MODULE)), encoding="utf-8")
    # No other counter in play (`{}`): PLATFORM_FACTS' raw fallbacks are not discovered values.
    dry = sync._counts.sync({}, dry_run=True, path=legacy)
    assert any(c.startswith("  ~") and "test_count" in c and "#4250" in c for c in dry), dry
    assert '"test_count":' in legacy.read_text(encoding="utf-8"), "dry_run wrote to disk"
    sync._counts.sync({}, dry_run=False, path=legacy)
    after = legacy.read_text(encoding="utf-8")
    assert '"test_count":' not in after, "--apply did not retire the literal"
    import ast

    # still a valid module, carrying every other counter
    (assign,) = [n for n in ast.parse(after).body if isinstance(n, ast.Assign) and n.targets[0].id == "DISCOVERED_COUNTS"]
    assert set(ast.literal_eval(assign.value)) == set(_counter_fields())
    again = sync._counts.sync({}, dry_run=True, path=legacy)
    assert not any("test_count" in c for c in again), f"the retirement does not converge: {again}"


def test_a_pull_request_run_reports_the_leftover_literal_and_never_writes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    legacy = tmp_path / "platform_counts.py"
    body = _with_test_count_line(_read(_COUNTS_MODULE))
    legacy.write_text(body, encoding="utf-8")
    changes = sync._counts.sync({}, dry_run=False, path=legacy)
    assert any(c.startswith("  i") and "test_count" in c for c in changes), changes
    assert not any(c.startswith("  ~") and "test_count" in c for c in changes), changes
    assert legacy.read_text(encoding="utf-8") == body, "a branch run wrote the bot-owned module"


def test_platform_stats_serves_the_live_test_count_not_a_committed_one():
    """In a checkout the reader derives from tests/ itself; in a bundle it reads the stamp."""
    assert PLATFORM_STATS.get("test_count") == sync._count_test_functions()
