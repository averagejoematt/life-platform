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
    assert "lambdas/web/platform_counts.py" in line[0], "the doc must name where the number actually lives"
    # No standalone integer big enough to be a test count (the issue ref #3101 is fine).
    assert not re.search(r"\b\d{4,}\b", line[0].replace("#3101", "")), f"a count was re-typed into the doc: {line[0]}"


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


def test_the_pre_commit_hook_stages_the_generated_module_and_not_site_api_common():
    src = _read(_INSTALL_HOOKS)
    stage = re.search(r"SYNCED_CHANGED=\$\(git -C \"\$PROJ_ROOT\" diff --name-only -- ([^)]+?)\|\|", src)
    assert stage, "could not find the hook's doc-sync stage pathspec"
    spec = stage.group(1)
    assert "lambdas/web/platform_counts.py" in spec
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
    real = sync._count_test_functions()
    assert real is not None
    # Substitute over the MATCHED literal, never over an assumed value: the committed
    # number is allowed to lag reality between the reconcile bot's runs, and a mutation
    # test that silently no-ops when it does is the vacuous-gate class this file exists
    # to prevent. `real + 1` is wrong by construction whatever was there before.
    wrong = f'"test_count": {real + 1}'
    body, n = re.subn(r'"test_count":\s*\d+', wrong, src, count=1)
    assert n == 1, "no test_count literal in platform_counts.py — the literal shape drifted"
    mutated.write_text(body, encoding="utf-8")

    monkeypatch.setattr(sync, "_PLATFORM_COUNTS_PATH", mutated)
    changes = sync._sync_platform_counts(dict(sync.PLATFORM_FACTS), dry_run=True)
    drift = [c for c in changes if c.startswith("  ~") and "test_count" in c]
    assert drift, f"--check would NOT have caught a wrong test_count: {changes}"
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
        stripped.write_text(re.sub(r'^\s*"test_count":\s*\d+,\s*$\n', "", src, flags=re.M), encoding="utf-8")
        original = sync._PLATFORM_COUNTS_PATH
        try:
            sync._PLATFORM_COUNTS_PATH = stripped
            changes = sync._sync_platform_counts(dict(sync.PLATFORM_FACTS), dry_run=True)
        finally:
            sync._PLATFORM_COUNTS_PATH = original
    assert any(c.startswith("  !") and "test_count" in c for c in changes), f"a deleted counter was not reported: {changes}"
