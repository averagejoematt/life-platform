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
from _hooklib import bash_command, emit, git, ok, read_payload  # noqa: E402

_MERGE = re.compile(r"\bgh\s+pr\s+merge\b")
_ASSERTED = re.compile(r"assert_pr_green|wait_pr_green|--required|checks?\s+--watch")
_DEPLOY = re.compile(r"\b(deploy/(deploy_|cdk_deploy|sync_site_to_s3)[\w.]*\.sh|aws\s+lambda\s+update-function-code)\b")
_FORCE = re.compile(r"\bgit\s+push\b.*(--force\b|-f\b)")
#: A merge that SUPPLIES its own commit text. `--body-file`, `--body`, `--subject` (and the
#: `-F`/`-b`/`-t` short forms `gh` accepts for them).
_SUPPLIED_MSG = re.compile(r"(?:^|\s)(--body-file|--body|--subject|-F|-b|-t)(?:[=\s]|$)")


def main() -> int:
    cmd = bash_command(read_payload())
    if not cmd:
        return ok()

    if _MERGE.search(cmd) and not _ASSERTED.search(cmd):
        return emit(
            "merge without a named-check assertion",
            [
                "`gh pr merge` here is not preceded by an assertion of the expected check SET.",
                "An empty rollup and a not-yet-attached lane both read as zero failures.",
                "Use: python3 scripts/assert_pr_green.py <PR>   (or bash deploy/wait_pr_green.sh)",
                "and read its verdict in its OWN command, unpiped.",
            ],
        )

    if _MERGE.search(cmd) and _SUPPLIED_MSG.search(cmd):
        return emit(
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

    if _DEPLOY.search(cmd):
        code, top = git("rev-parse", "--show-toplevel")
        code2, gitdir = git("rev-parse", "--git-dir")
        # `--git-common-dir` ALWAYS resolves to the main checkout's `.git` — from inside a
        # worktree too — so it can never distinguish the two (measured, #3262). `--git-dir`
        # is the one that differs: `.git` (or `.../.git`) in the main checkout, vs.
        # `.../.git/worktrees/<name>` inside a worktree.
        if code == 0 and code2 == 0 and gitdir not in ("", ".git") and not gitdir.endswith("/.git"):
            return emit(
                "deploy from a worktree",
                [
                    f"cwd resolves to a git WORKTREE ({top}), not the main checkout.",
                    "A deploy from a worktree branch shows a deceptive 0-diff and ships stale content.",
                    "Deploy from the main checkout, from main, after merge.",
                ],
            )

    if _FORCE.search(cmd):
        code, branch = git("rev-parse", "--abbrev-ref", "HEAD")
        if code == 0 and branch in ("main", "master"):
            return emit("force-push to main", [f"This force-pushes `{branch}`. Confirm this is deliberate."])

    return ok()


if __name__ == "__main__":
    sys.exit(main())
