#!/usr/bin/env python3
"""scripts/hooks/guard_bash.py — PreToolUse guard for Bash calls.

Three checks, each a measured incident class. Advisory by default (see _hooklib).

1. MERGE WITHOUT A NAMED-CHECK ASSERTION
   `gh pr checks | grep -c fail` returning zero is not green — an empty rollup, or a lane
   that has not ATTACHED yet, both read as zero. That merged a PR with a red pre-merge
   lane, and merged two more past a red full suite because the slow lane was sampled
   before it appeared. The repo's own tools (deploy/wait_pr_green.sh,
   scripts/assert_pr_green.py) assert the expected check SET by name; a hand-rolled
   grep does not.

   #4260: the watcher must run in its OWN, earlier command, and the merge in another —
   `wait_pr_green.sh:20-23` names the chained form (`watcher && gh pr merge`) as an
   incident cause: the merge fires past a verdict nobody read. So the guard RECORDS each
   watcher call (state: `watchers.json`, the last WATCHER_KEEP of them) and a merge is
   silent only when a watcher for the same PR (or any watcher, if the merge names no PR)
   was observed within WATCHER_WINDOW_S. A watcher in the SAME command as the merge is a
   finding of its own. The state file is touched only on a watcher or merge command.

2. DEPLOY FROM A WORKTREE
   The tell is a deceptive 0-diff: the deploy appears to succeed and ships main's old
   content. Deploys run from the main checkout, after merge.

3. FORCE-PUSH TO MAIN
   Distinct from the settings.json `ask` rule, which prompts a human. This names the
   branch in the warning so the answer is not a reflex.

4. A SQUASH MESSAGE NO GUARD HAS SEEN (#3863)
   `scripts/check_pr_closing_set.py` validates three texts and all three are PRE-merge: the
   PR body, the branch commits, and GitHub's computed closing set. `gh pr merge --squash
   --body-file`/`--body`/`--subject` supplies a FOURTH text that exists only at merge time.
   On 2026-09-17 that path retired an owner-gated issue: the custom body's note explaining
   that the offending phrase had been removed QUOTED the phrase, and GitHub closed 3715.
   The custom body was chosen specifically to be SAFER, which is what makes this a guard
   rather than a lint — the bespoke path is reached for precisely when the stakes feel high.
   The sanctioned path (`deploy/merge_train.sh`) merges with a bare `--squash`, whose message
   GitHub composes from text the pre-merge guard already validated.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import json  # noqa: E402
import time  # noqa: E402

from _hooklib import bash_command, command_cwd, emit, git, ok, read_payload, state_path  # noqa: E402

_MERGE = re.compile(r"\bgh\s+pr\s+merge\b")
_ASSERTED = re.compile(r"assert_pr_green|wait_pr_green|--required|checks?\s+--watch")
#: The PR a merge or watcher names: the first bare number after the verb.
_MERGE_PR = re.compile(r"\bgh\s+pr\s+merge\s+(?:-\S+\s+)*#?(\d+)\b")
_WATCH_PR = re.compile(r"(?:assert_pr_green\S*|wait_pr_green\S*|gh\s+pr\s+checks)\s+(?:-\S+\s+)*#?(\d+)\b")
WATCHERS = "watchers.json"
WATCHER_KEEP = 20  # the last N watcher calls the guard remembers
WATCHER_WINDOW_S = 3600  # a verdict older than an hour is not the verdict for this merge
_DEPLOY = re.compile(r"\b(deploy/(deploy_|cdk_deploy|sync_site_to_s3)[\w.]*\.sh|aws\s+lambda\s+update-function-code)\b")
_FORCE = re.compile(r"\bgit\s+push\b.*(--force\b|-f\b)")
#: A merge that SUPPLIES its own commit text. `--body-file`, `--body`, `--subject` (and the
#: `-F`/`-b`/`-t` short forms `gh` accepts for them).
_SUPPLIED_MSG = re.compile(r"(?:^|\s)(--body-file|--body|--subject|-F|-b|-t)(?:[=\s]|$)")


def _load_watchers() -> list[dict]:
    try:
        rows = json.loads(state_path(WATCHERS).read_text())
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _record_watcher(pr: str | None, now: float) -> None:
    try:
        rows = _load_watchers() + [{"pr": pr, "at": now}]
        state_path(WATCHERS).write_text(json.dumps(rows[-WATCHER_KEEP:]))
    except Exception:
        pass  # fail open: a lost record costs one extra advisory line, never a session


def _watched(pr: str | None, now: float) -> bool:
    for row in _load_watchers():
        if now - float(row.get("at", 0)) > WATCHER_WINDOW_S:
            continue
        if pr is None or row.get("pr") in (None, pr):
            return True
    return False


def _merge_findings(cmd: str, now: float) -> list[tuple[str, list[str]]]:
    findings: list[tuple[str, list[str]]] = []
    m = _MERGE.search(cmd)
    pr_m = _MERGE_PR.search(cmd)
    pr = pr_m.group(1) if pr_m else None
    if _ASSERTED.search(cmd[: m.start()]):
        findings.append(
            (
                "watcher chained into the merge",
                [
                    "The watcher and `gh pr merge` are in ONE command, so the merge fires past a verdict",
                    "nobody has read (deploy/wait_pr_green.sh:20-23 — twice an incident).",
                    "Run the watcher on its own, read its verdict, then merge in a separate command.",
                ],
            )
        )
    elif not _watched(pr, now):
        findings.append(
            (
                "merge without a named-check assertion",
                [
                    f"No watcher for PR {pr or '(unnamed)'} was observed in this session's last {WATCHER_KEEP} watcher calls",
                    f"within {WATCHER_WINDOW_S // 60} min. An empty rollup and a not-yet-attached lane both read as zero failures.",
                    "Use: python3 scripts/assert_pr_green.py <PR>   (or bash deploy/wait_pr_green.sh <PR>)",
                    "in its OWN command, unpiped, and read its verdict before merging.",
                ],
            )
        )
    if _SUPPLIED_MSG.search(cmd[m.start() :]):
        findings.append(
            (
                "merge with a squash message no guard has validated",
                [
                    "`gh pr merge` here supplies its own commit text (--body-file / --body / --subject).",
                    "That text is a FOURTH text: check_pr_closing_set.py validates the PR body, the branch",
                    "commits and GitHub's computed closing set — all of them BEFORE the merge. A message",
                    "supplied at merge time is seen by nothing, and on 2026-09-17 one retired an owner-gated",
                    "issue because the note explaining a removed closing phrase quoted the phrase.",
                    "Use a bare `gh pr merge --squash`: GitHub composes the message from already-validated text.",
                    "If the message genuinely must be custom, parse it first:",
                    "  python3 scripts/check_merge_commit_closures.py --sha <merge sha>   (the post-merge backstop)",
                ],
            )
        )
    return findings


def main() -> int:
    cmd = bash_command(read_payload())
    if not cmd:
        return ok()
    now = time.time()
    findings: list[tuple[str, list[str]]] = []

    merge = _MERGE.search(cmd)
    if merge:
        findings += _merge_findings(cmd, now)
    elif _ASSERTED.search(cmd):
        # A bare `gh pr checks N` is NOT recorded: it is the fail-filter idiom check 1 exists for.
        w = _WATCH_PR.search(cmd)
        _record_watcher(w.group(1) if w else None, now)

    d = _DEPLOY.search(cmd)
    if d:
        where = command_cwd(cmd, d.start(), git_c=False)
        code, top = git("rev-parse", "--show-toplevel", cwd=where)
        code2, gitdir = git("rev-parse", "--git-dir", cwd=where)
        # `--git-common-dir` ALWAYS resolves to the main checkout's `.git` — from inside a
        # worktree too — so it can never distinguish the two (measured, #3262). `--git-dir`
        # is the one that differs: `.git` (or `.../.git`) in the main checkout, vs.
        # `.../.git/worktrees/<name>` inside a worktree. #4260: asked in the directory the
        # deploy RUNS in (payload cwd, or the command's own `cd`), not the hook's checkout.
        if code == 0 and code2 == 0 and gitdir not in ("", ".git") and not gitdir.endswith("/.git"):
            findings.append(
                (
                    "deploy from a worktree",
                    [
                        f"cwd resolves to a git WORKTREE ({top}), not the main checkout.",
                        "A deploy from a worktree branch shows a deceptive 0-diff and ships stale content.",
                        "Deploy from the main checkout, from main, after merge.",
                    ],
                )
            )

    f = _FORCE.search(cmd)
    if f:
        code, branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=command_cwd(cmd, f.start()))
        if code == 0 and branch in ("main", "master"):
            findings.append(("force-push to main", [f"This force-pushes `{branch}`. Confirm this is deliberate."]))

    if not findings:
        return ok()
    title = findings[0][0] if len(findings) == 1 else " + ".join(t for t, _ in findings)
    lines = [ln for i, (t, body) in enumerate(findings) for ln in ([f"— {t}"] if len(findings) > 1 else []) + body]
    return emit(title, lines, event="PreToolUse")


if __name__ == "__main__":
    sys.exit(main())
