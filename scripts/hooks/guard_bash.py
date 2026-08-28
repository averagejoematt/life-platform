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

    if _DEPLOY.search(cmd):
        code, top = git("rev-parse", "--show-toplevel")
        code2, common = git("rev-parse", "--git-common-dir")
        # A worktree's git dir differs from its common dir; the main checkout's does not.
        if code == 0 and code2 == 0 and common not in ("", ".git") and not common.endswith("/.git"):
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
