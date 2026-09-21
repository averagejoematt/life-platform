"""#3005 / #3328 — the no-tool-attribution guard.

The owner's 2026-08-12 authorship decision (CLAUDE.md "Authorship") bans
tool-attribution trailers on commits and PRs. Four tracked files were found still
instructing the old convention — one of them driving the unattended remediation
agent — and nothing enforced the ban: it held only because CLAUDE.md is in context
at interactive sessions.

The rule bans THREE forms, and since #3328 the guard matches all three (it shipped
matching one — the co-author trailer — and the #2999 mutation census recorded the
other two as a scope gap):

  form 1  `Co-Authored-By: Claude …`            a commit-message trailer
  form 2  `Claude-Session: …`                    a commit-message trailer
  form 3  `🤖 Generated with [Claude Code]…` /    a PR-body footer, with the
          `claude.ai/code/session_…`             session link it carries

Guard choice (recorded per the issue's acceptance): a TEST, not a commit-msg hook
or CI step — it runs in every lane including the #3025 pre-merge full suite, needs
no per-clone hook installation (the hook is generated and untracked, so a hook
check protects only clones that re-ran install_hooks.sh), and mutation-proves at
the predicate level.

Three sweeps:
1. Instruction surface — no tracked file outside the allowlist may mention ANY of
   the three forms at all. The allowlist is exactly the files that state the BAN.
2. Reachable history — no commit message on the current branch since the decision
   date may carry any of the three forms. Form 3 is a PR-body form, but the merge
   train squash-merges with a bare `gh pr merge --squash`, which lets GitHub copy
   the PR body into the squash commit — so a footer in a commit message is the same
   attribution one hop later, and the history scan matches it too.
3. PR body — when a PR body is reachable, it may carry none of the three forms.
   The pre-merge lane (`.github/workflows/pr-checks.yml`, `on: pull_request`) runs
   this file in BOTH its jobs (it is in conftest's `_PREMERGE_EXTRA_FILES`, and the
   #3025 full suite runs everything), and GitHub hands every step the event payload
   at `$GITHUB_EVENT_PATH` with `pull_request.body` inside — that is the scan's
   input, no extra plumbing. HONEST LIMITS: outside a `pull_request` run there is no
   PR body and the test SKIPS with that reason (it does not silently pass as
   "commits only"); and the payload is the body as of the last open/reopen/push —
   a footer added by EDITING the body afterwards is not re-checked until the next
   push, because `edited` is not a default `pull_request` activity type.
   `PR_BODY_UNDER_TEST` supplies a body by hand (the mutation proof uses it).

`.claude/worktrees/**` copies are deliberately out of scope: they are separate
worktree checkouts (never listed by `git ls-files` here), stale snapshots of old
briefs, not a live instruction surface.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = str(Path(__file__).resolve().parents[1])

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files allowed to contain the banned strings because they STATE the ban.
ALLOWLIST = {
    "CLAUDE.md",  # the owner decision itself, which quotes all three banned forms
    "tests/test_no_tool_attribution_3005.py",  # this guard
    # #3645: the "attribution footer"/"attribution trailer" PARAPHRASE sweep (added
    # below) makes every file that merely NAMES the ban to describe or restate it —
    # never to instruct adding one — a new offender unless allowlisted. All of these
    # state the ban; none instructs it.
    ".claude/README.md",
    "CONTRIBUTING.md",
    "docs/CONVENTIONS.md",
    "remediation/prompt.md",
    "scripts/gate_census_mutations.py",
    "scripts/install_hooks.sh",  # the commit-msg hook that REFUSES the forms names them to grep for them (#4000 fix-forward)
    "handovers/HANDOVER_LATEST.md",  # a session's own incident narrative, not an instruction
    # #3645: worktree-implementer.md's step 9 now STATES the three banned forms by name
    # (so an agent reading it recognizes what to refuse) instead of instructing one —
    # PR #3639 shipped a footer under a prior version of this step that said to keep it.
    ".claude/agents/worktree-implementer.md",
    # #3645: this repo's own regression test for the fix above states (never instructs)
    # the same three literal forms, in docstrings and string literals, to test that the
    # paraphrase detector catches them — see tests/test_worktree_implementer_no_footer_instruction_3645.py.
    "tests/test_worktree_implementer_no_footer_instruction_3645.py",
}

BAN_DATE = "2026-08-12"

# ── The three forms, one predicate each ───────────────────────────────────────
# Kept separate (not one alternation) so each form has its OWN mutation proof and
# a failure names the form it saw. `_MENTION` / `_TRAILER` below are the unions
# the sweeps use; the census (scripts/gate_census_mutations.py) and #3328 refer
# to them by those names.

# Instruction-surface patterns: any MENTION of the form's name / literal.
_MENTION_FORMS = {
    "co-author trailer": re.compile(r"co-authored-by", re.IGNORECASE),
    "session trailer": re.compile(r"claude-session", re.IGNORECASE),
    # Two spellings of form 3: the footer text and the link it carries. The link
    # is pinned to `/code/session` on purpose — `claude.ai/code/artifact/…` links
    # (portrait contact sheets under config/portraits/) are not attribution.
    "generated-with footer / session link": re.compile(r"generated with \[claude code\]|claude\.ai/code/session", re.IGNORECASE),
    # #3645: "attribution footer" survives sweep 1 as a PARAPHRASE — a prior version
    # of worktree-implementer.md step 9 said "ends with the attribution footer the
    # driver brief supplies", which names none of the three literal forms above and
    # so passed this sweep clean while still instructing a lane to add one. PR #3639
    # is the live positive control: a sonnet lane briefed "no tool-attribution
    # trailers" still emitted the footer + session link because this step told it
    # to keep one. An instruction can no longer say "attribution footer" or
    # "attribution trailer" without saying the FORM (which then trips the ban
    # directly) or being a ban-STATING file on the allowlist.
    "attribution footer/trailer paraphrase": re.compile(r"attribution (?:footer|trailer)", re.IGNORECASE),
}

# Message/body patterns: an ACTUAL attribution, not a mention.
_TRAILER_FORMS = {
    # A co-author trailer crediting a Claude model. A non-Claude co-author is a
    # human credit and stays legal.
    "co-author trailer": re.compile(r"^\s*co-authored-by:.*\bclaude\b", re.IGNORECASE | re.MULTILINE),
    # The session trailer — the key alone is the attribution, whatever the value.
    "session trailer": re.compile(r"^\s*claude-session:", re.IGNORECASE | re.MULTILINE),
    # The footer / session link, anywhere in the text (it is not a `key:` trailer).
    "generated-with footer / session link": re.compile(r"generated with \[claude code\]|claude\.ai/code/session", re.IGNORECASE),
}

# The unions — what the sweeps actually run.
_MENTION = re.compile("|".join(p.pattern for p in _MENTION_FORMS.values()), re.IGNORECASE)
_TRAILER = re.compile("|".join(f"(?:{p.pattern})" for p in _TRAILER_FORMS.values()), re.IGNORECASE | re.MULTILINE)

_TEXT_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml", ".txt", ".json", ".toml", ".cfg", ".ini"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def trailer_forms(message: str) -> list[str]:
    """The banned forms a commit message / PR body actually carries (empty = clean)."""
    return [name for name, pattern in _TRAILER_FORMS.items() if pattern.search(message)]


def mention_forms(text: str) -> list[str]:
    """The banned forms a file's content mentions at all (empty = clean)."""
    return [name for name, pattern in _MENTION_FORMS.items() if pattern.search(text)]


def message_carries_trailer(message: str) -> bool:
    """True when a commit message (or PR body) carries any Claude tool-attribution form."""
    return bool(_TRAILER.search(message))


def file_mentions_trailer(text: str) -> bool:
    """True when file content mentions any of the banned forms at all."""
    return bool(_MENTION.search(text))


def pr_body_under_test() -> "str | None":
    """The PR body this run can see, or None when there is no PR to see.

    `PR_BODY_UNDER_TEST` wins when set (a hand-supplied body; the mutation proof).
    Otherwise the GitHub Actions event payload at `$GITHUB_EVENT_PATH` is read and
    `pull_request.body` returned — present only on `pull_request` runs. Anything
    unreadable or non-PR-shaped is None: no PR body, not an empty one.
    """
    override = os.environ.get("PR_BODY_UNDER_TEST")
    if override is not None:
        return override
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pull_request, dict):
        return None
    return pull_request.get("body") or ""


# ── Mutation proofs: one per form, each sweep (CONVENTIONS §9) ────────────────
# Independent assertions, not one combined — a regression that drops ONE form
# must red exactly its own proof.


def test_form1_co_author_trailer_is_detected():
    planted = "fix(x): a change\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n"
    assert trailer_forms(planted) == ["co-author trailer"]
    assert message_carries_trailer("subject\n\nco-authored-by: CLAUDE opus <x@y>")
    assert mention_forms("changes carry a `Co-Authored-By` trailer") == ["co-author trailer"]


def test_form2_session_trailer_is_detected():
    planted = "fix(x): a change\n\nClaude-Session: https://claude.ai/code/session_01ABC\n"
    # The session trailer's value happens to be the form-3 link too; the KEY is form 2.
    assert "session trailer" in trailer_forms(planted)
    assert message_carries_trailer("subject\n\n  claude-session: anything-at-all")
    assert mention_forms("end the commit with a `Claude-Session` line") == ["session trailer"]


def test_form3_generated_with_footer_is_detected():
    footer = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    link = "see https://claude.ai/code/session_01YHguRpkCbgmfZCaqeS3svP for the run"
    assert trailer_forms(footer) == ["generated-with footer / session link"]
    assert trailer_forms(link) == ["generated-with footer / session link"]
    assert mention_forms("PR bodies end with `🤖 Generated with [Claude Code]`") == ["generated-with footer / session link"]
    assert mention_forms("append the claude.ai/code/session_ link") == ["generated-with footer / session link"]


def test_unions_agree_with_the_per_form_predicates():
    # The sweeps run the unions; the proofs above run the parts. Keep them the same set.
    samples = [
        "Co-Authored-By: Claude X <x@y>",
        "Claude-Session: z",
        "🤖 Generated with [Claude Code]",
        "https://claude.ai/code/session_1",
        "a clean message",
    ]
    for sample in samples:
        assert message_carries_trailer(sample) == bool(trailer_forms(sample)), sample
        assert file_mentions_trailer(sample) == bool(mention_forms(sample)), sample


def test_predicates_pass_benign_content():
    assert not message_carries_trailer("fix(x): co-authored the design doc with the team")
    # A non-Claude co-author trailer is a human credit, not a tool attribution.
    assert not message_carries_trailer("subject\n\nCo-Authored-By: Jane Doe <jane@example.com>")
    # A session mentioned in prose, or the key not at line start, is not the trailer.
    assert not message_carries_trailer("fix(x): the Claude session ran long; see the claude-session log")
    # A contact-sheet artifact link is a `claude.ai/code/artifact/…` URL, not a session link.
    assert not message_carries_trailer("sheet: https://claude.ai/code/artifact/6d473337-c9cf")
    assert not file_mentions_trailer("commits carry the work, not the tooling")
    assert not file_mentions_trailer("generated with Pillow from the daily metrics")
    assert not file_mentions_trailer("https://claude.ai/code/artifact/6d473337-c9cf")


def test_pr_body_reader_prefers_override_then_event_payload(tmp_path, monkeypatch):
    monkeypatch.delenv("PR_BODY_UNDER_TEST", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert pr_body_under_test() is None
    # A push event (no pull_request key) is "no PR body", not an empty body.
    push_event = tmp_path / "push.json"
    push_event.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(push_event))
    assert pr_body_under_test() is None
    pr_event = tmp_path / "pr.json"
    pr_event.write_text(json.dumps({"pull_request": {"number": 1, "body": "what/why\n\nFixes #1"}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(pr_event))
    assert pr_body_under_test() == "what/why\n\nFixes #1"
    pr_event.write_text(json.dumps({"pull_request": {"number": 1, "body": None}}), encoding="utf-8")
    assert pr_body_under_test() == ""
    monkeypatch.setenv("PR_BODY_UNDER_TEST", "hand-supplied")
    assert pr_body_under_test() == "hand-supplied"


# ── The sweeps ────────────────────────────────────────────────────────────────


def test_no_tracked_file_instructs_the_trailer():
    try:
        tracked = _git("ls-files").splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = []
    for rel in tracked:
        if rel in ALLOWLIST or Path(rel).suffix not in _TEXT_SUFFIXES:
            continue
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        forms = mention_forms(text)
        if forms:
            offenders.append(f"{rel} ({', '.join(forms)})")
    assert not offenders, (
        f"tracked files mention a banned tool-attribution form: {offenders} — "
        "the owner decision (CLAUDE.md 'Authorship', 2026-08-12) bans instructing it; "
        "state the ban without the literal, or add a ban-stating file to ALLOWLIST"
    )


# Post-ban commits that DO carry a form and cannot be removed: rewriting `main` is forbidden
# (CLAUDE.md 'Authorship' — "the cost is real and the erasure is not"), so the honest record
# is a dated entry naming how the trailer got in and the guard that now stops the next one.
# Each entry is verified below: the sha must exist AND must carry a form (an allowlisted
# clean commit is a rotten entry, and a missing sha is a typo).
POST_BAN_HISTORY_OFFENDERS = {
    "9257341db35f7b0b4b3c9e5b5d1d0a4c4b0a1f2e"[:12]: (
        "2026-09-20 — the squash-merge of PR #4000 (#3900's lane). The repo squashes with "
        "COMMIT_MESSAGES, so the lane's own commit trailers (the harness reminder's "
        "Claude-Session / Co-authored-by lines) became main's message. The PR-body check "
        "passed because the body was clean; nothing checked the commits. Guards added in the "
        "same fix-forward: the commit-msg hook refuses the forms, and pr-checks scans every PR "
        "commit's message (PR_COMMITS_FILE_UNDER_TEST)."
    ),
}


def _history_entries(log: str):
    for entry in log.split("\x00"):
        entry = entry.strip()
        if not entry:
            continue
        sha, _, body = entry.partition("\n")
        yield sha, body


def test_reachable_history_carries_no_trailer_since_ban():
    try:
        log = _git("log", f"--since={BAN_DATE}", "--format=%H%n%B%x00")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = []
    seen_allowlisted = set()
    for sha, body in _history_entries(log):
        forms = trailer_forms(body)
        if not forms:
            continue
        if sha[:12] in POST_BAN_HISTORY_OFFENDERS:
            seen_allowlisted.add(sha[:12])
            continue
        offenders.append(f"{sha[:12]} ({', '.join(forms)})")
    assert not offenders, (
        f"commits since {BAN_DATE} carry a Claude tool-attribution form: {offenders} — "
        "banned by the owner decision recorded in CLAUDE.md 'Authorship'; a commit that cannot be "
        "rewritten is recorded in POST_BAN_HISTORY_OFFENDERS with how it got in"
    )


def test_every_allowlisted_offender_exists_and_still_carries_a_form():
    """The allowlist cannot rot: a sha that is not in history is a typo, and a sha whose message
    is clean is an entry that hides nothing and should be deleted."""
    try:
        log = _git("log", f"--since={BAN_DATE}", "--format=%H%n%B%x00")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    by_prefix = {sha[:12]: body for sha, body in _history_entries(log)}
    for prefix, reason in POST_BAN_HISTORY_OFFENDERS.items():
        assert reason.startswith("20"), f"{prefix}: the allowlist reason must start with a date"
        if prefix not in by_prefix:
            pytest.skip(f"{prefix} is not reachable from this checkout (shallow clone or a branch that predates it)")
        assert trailer_forms(by_prefix[prefix]), f"{prefix} is allowlisted but carries no form — delete the entry"


def pr_commit_messages_under_test() -> "list[str] | None":
    """Every commit message of the PR under test, or None when there is no PR to see.

    `PR_COMMITS_FILE_UNDER_TEST` names a file whose entries are separated by a line of
    exactly `---`; pr-checks writes it from `gh pr view --json commits` before the lanes run
    (a PR checkout is the MERGE commit at depth 1 — `git log` cannot see the branch's own
    commits, which is how #4000's trailers reached main through a green PR)."""
    path = os.environ.get("PR_COMMITS_FILE_UNDER_TEST")
    if not path or not os.path.exists(path):
        return None
    text = Path(path).read_text(encoding="utf-8")
    return [m.strip() for m in text.split("\n---\n") if m.strip()]


def test_pr_commits_under_test_carry_no_attribution():
    messages = pr_commit_messages_under_test()
    if messages is None:
        pytest.skip("no PR commit messages to see (not a pull_request run, or the file was not written)")
    offenders = [f"commit {i + 1} ({', '.join(trailer_forms(m))})" for i, m in enumerate(messages) if trailer_forms(m)]
    assert not offenders, (
        f"PR commit message(s) carry a Claude tool-attribution form: {offenders} — the repo squashes "
        "with COMMIT_MESSAGES, so this would land on main verbatim (#4000). Amend the commits; the "
        "commit-msg hook refuses them locally."
    )


def test_pr_commits_scan_catches_a_planted_trailer(tmp_path, monkeypatch):
    """Mutation control for the scan above: a planted trailer in the second message reds."""
    f = tmp_path / "commits.txt"
    f.write_text("feat: clean\n\nbody\n---\nfix: dirty\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>\n", encoding="utf-8")
    monkeypatch.setenv("PR_COMMITS_FILE_UNDER_TEST", str(f))
    msgs = pr_commit_messages_under_test()
    assert msgs and len(msgs) == 2 and not trailer_forms(msgs[0]) and trailer_forms(msgs[1])
    with pytest.raises(AssertionError):
        test_pr_commits_under_test_carry_no_attribution()


def test_the_commit_msg_hook_refuses_a_trailer(tmp_path):
    """Drives the REAL commit-msg heredoc out of install_hooks.sh (never a hand copy): a message
    carrying a banned form is refused before the Conventional-Commit subject check."""
    import re as _re
    import stat as _stat

    installer = Path(REPO) / "scripts" / "install_hooks.sh"
    m = _re.search(r"cat > \"\$MSG_HOOK_FILE\" << 'MSGEOF'\n(.*?)\nMSGEOF\n", installer.read_text(encoding="utf-8"), _re.S)
    assert m, "install_hooks.sh commit-msg heredoc markers not found"
    repo = tmp_path / "hookrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "deploy" / "lib").mkdir(parents=True)
    (repo / "deploy" / "lib" / "commit_subject_pattern.sh").write_text(
        (Path(REPO) / "deploy" / "lib" / "commit_subject_pattern.sh").read_text(encoding="utf-8"), encoding="utf-8"
    )
    hook = repo / "hook.sh"
    hook.write_text(m.group(1), encoding="utf-8")
    hook.chmod(hook.stat().st_mode | _stat.S_IXUSR)

    def run(msg):
        mf = repo / "MSG"
        mf.write_text(msg, encoding="utf-8")
        return subprocess.run(["bash", str(hook), str(mf)], cwd=str(repo), capture_output=True, text=True)

    clean = run("fix(x): a clean subject\n\nbody\n")
    assert clean.returncode == 0, clean.stderr
    dirty = run("fix(x): a clean subject\n\nClaude-Session: https://claude.ai/code/session_x\n")
    assert dirty.returncode == 1 and "attribution" in dirty.stderr.lower(), dirty.stderr
    dirty2 = run("fix(x): a clean subject\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n")
    assert dirty2.returncode == 1, dirty2.stderr


def test_pr_body_carries_no_attribution():
    body = pr_body_under_test()
    if body is None:
        pytest.skip(
            "no PR body reachable — this sweep runs on `pull_request` events (pr-checks.yml), where "
            "$GITHUB_EVENT_PATH carries pull_request.body; set PR_BODY_UNDER_TEST to check one by hand"
        )
    forms = trailer_forms(body)
    assert not forms, (
        f"the PR body carries a Claude tool-attribution form: {forms} — "
        "banned by the owner decision recorded in CLAUDE.md 'Authorship' (2026-08-12); "
        "remove the footer/trailer and push again (the body is re-read on the next push)"
    )
