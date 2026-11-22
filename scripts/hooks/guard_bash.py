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
   content. Deploys run from the main checkout, after merge. #4260: fires only when a
   deploy script is EXECUTED (not when a read-only `grep`/`cat`/`sed` names a deploy/
   path), and stays silent in a worktree DETACHED at origin/main's tip.

3. FORCE-PUSH, ANY BRANCH — REFUSED IN EVERY MODE (#6157)
   A lane agent force-pushed its own PR branch unasked (2026-11-16). Every force form of
   `git push` (and `git send-pack`) is a hard deny regardless of CLAUDE_HOOK_MODE: --force, -f
   (alone or in a combined short flag; `-o<value>` is a push option, not a cluster),
   --force-with-lease[=..], --force-if-includes, --mirror, a `+refspec` — behind `git -C <dir>` /
   `--git-dir=` / `cd x &&`, shell grammar words (`if`/`do`/`{`/`!`), wrappers with their own
   options (`timeout -s KILL 60`, `sudo -u me`, `find -exec`, `watch`), `eval`, a `-c` string of
   any shell, a here-doc FED TO a shell, and `$(...)`/backticks even inside double quotes. The
   command is TOKENISED (shlex), never substring-matched: a `gh issue create --body "...force-
   push..."`, a here-doc body fed to `cat`/`gh`/`git commit -F -`, or a trailing `# comment` that
   merely talks about force-pushing is data, not a git push. What a client hook cannot see — git
   aliases, script files, interpreters, `$VAR` as the command, `gh api` ref updates — is the
   server ruleset's job (PR #6160 "residual risk").

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
import shlex
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
#: A deploy the command EXECUTES — the script (or `aws lambda update-function-code`) must be the
#: command word of a segment: at the start, or after `;` `&` `|` `(` `$(` or a newline, behind
#: optional `VAR=x` assignments, `env`/`nohup`/`time`/`timeout N`, and `bash`/`sh`/`zsh`/`source`
#: (with flags), with any path prefix (`./`, an absolute worktree path). #4260: a read-only
#: `grep -n x deploy/deploy_fleet.sh` / `cat` / `sed -n` merely MENTIONS the path and is silent.
_DEPLOY = re.compile(
    r"(?:^|[;&|(\n]|\$\()\s*"
    r"(?:\w+=\S*\s+)*"
    r"(?:(?:env|nohup|time|timeout\s+\S+)\s+(?:\w+=\S*\s+)*)*"
    r"(?:(?:bash|sh|zsh|source|\.)\s+(?:-\S+\s+)*)?"
    r"(?P<hit>(?:\S*/)?deploy/(?:deploy_|cdk_deploy|sync_site_to_s3)[\w.]*\.sh|aws\s+lambda\s+update-function-code)\b"
)
#: Long options that rewrite remote history. git accepts any unambiguous prefix of a long option
#: (`--force-w`), so a prefix of one of these names counts.
_FORCE_LONG = ("force", "force-with-lease", "force-if-includes", "mirror")
#: `git push` options whose value is the NEXT token when not attached (`-o x`, `--repo origin`).
_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
#: Commands that run another command from their own arguments. Their options are NOT parsed
#: (value-taking ones vary per tool: `timeout -s KILL 60`, `sudo -u me`, `nice -n 5`); instead every
#: later token that names git / a shell / eval is checked as the start of a command.
_WRAPPERS = {
    "env", "nohup", "time", "command", "builtin", "exec", "sudo", "doas", "xargs", "nice", "ionice",
    "timeout", "gtimeout", "stdbuf", "caffeinate", "watch", "setsid", "unbuffer", "find", "flock",
    "chronic", "parallel", "chroot", "taskset", "nsenter", "script",
}  # fmt: skip
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "fish", "csh", "tcsh", "ash", "yash", "busybox"}
#: Shell grammar words that can lead a simple command; the command proper follows them.
_CONTROL = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "!"}
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_PIPE_TO_SHELL = re.compile(r"\|\s*(?:\S*/)?(?:" + "|".join(sorted(_SHELLS)) + r")\b")
#: git's global options that consume the NEXT token as their value.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
#: A merge that SUPPLIES its own commit text. `--body-file`, `--body`, `--subject` (and the
#: `-F`/`-b`/`-t` short forms `gh` accepts for them).
_SUPPLIED_MSG = re.compile(r"(?:^|\s)(--body-file|--body|--subject|-F|-b|-t)(?:[=\s]|$)")


def _feeds_shell(line: str, at: int, end: int) -> bool:
    """A here-doc whose receiving command is a shell (`bash <<EOF`, `sudo sh -s <<EOF`), or whose
    command pipes straight into one (`cat <<EOF | bash`): its body is COMMANDS, not data."""
    segs = _segments(line[:at])
    if segs and any(t.rsplit("/", 1)[-1] in _SHELLS for t in segs[-1]):
        return True
    return bool(_PIPE_TO_SHELL.search(line[end:]))


def _strip_heredocs(cmd: str) -> tuple[str, list[str]]:
    """Drop heredoc BODIES: text fed to a command on stdin is data, not commands — unless that
    command is a shell, whose stdin IS commands. Returns (cmd without bodies, shell-fed bodies)."""
    out: list[str] = []
    shell_bodies: list[str] = []
    delim, dash, body, to_shell = None, False, [], False
    for line in cmd.split("\n"):
        if delim is not None:
            if (line.strip() if dash else line) == delim:
                if to_shell:
                    shell_bodies.append("\n".join(body))
                delim, body = None, []
            else:
                body.append(line)
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            delim, dash = m.group(2), "<<-" in line[m.start() : m.start() + 3]
            to_shell = _feeds_shell(line, m.start(), m.end())
    if delim is not None and to_shell:  # unterminated: bash reads to EOF
        shell_bodies.append("\n".join(body))
    return "\n".join(out), shell_bodies


def _close_paren(cmd: str, i: int) -> int:
    """Index of the `)` closing a `$(` whose body starts at i (quote-aware), else len(cmd)."""
    depth, q, n = 1, None, len(cmd)
    while i < n:
        c = cmd[i]
        if q == "'":
            q = None if c == "'" else q
        elif c == "\\":
            i += 1
        elif q == '"':
            q = None if c == '"' else q
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _scan(cmd: str) -> tuple[str, list[str]]:
    """Quote-aware pass: drop `# comments` (a `#` that starts a word, outside quotes) and collect
    the bodies of `$(...)` and backtick substitutions — INCLUDING those inside double quotes,
    which the shell still executes (`echo "$(git push -f)"`). Single-quoted text is literal."""
    out: list[str] = []
    subs: list[str] = []
    q, i, n = None, 0, len(cmd)
    while i < n:
        c = cmd[i]
        if q == "'":
            q = None if c == "'" else q
        elif c == "\\" and i + 1 < n:
            out.append(cmd[i : i + 2])
            i += 2
            continue
        elif c == "$" and cmd.startswith("$(", i):
            j = _close_paren(cmd, i + 2)
            subs.append(cmd[i + 2 : j])
            out.append(cmd[i : j + 1])
            i = j + 1
            continue
        elif c == "`":
            j = i + 1
            while j < n and cmd[j] != "`":
                j += 2 if cmd[j] == "\\" else 1
            subs.append(cmd[i + 1 : j].replace("\\`", "`"))
            out.append(cmd[i : j + 1])
            i = j + 1
            continue
        elif q == '"':
            q = None if c == '"' else q
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|()"):
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out), subs


def _segments(cmd: str) -> list[list[str]]:
    """Token lists, one per simple command (split on ; & | ( ) ` and unquoted newlines)."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()`\n")
        lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
        tokens = list(lex)
    except ValueError:  # unbalanced quote: refuse to guess, fall back to whitespace tokens
        tokens = cmd.replace(";", " ; ").replace("&", " ; ").replace("|", " ; ").split()
    segs: list[list[str]] = [[]]
    for t in tokens:
        if t and set(t) <= set(";&|()`\n"):
            segs.append([])
        else:
            segs[-1].append(t)
    return [s for s in segs if s]


def _push_args_force(args: list[str]) -> str | None:
    """The first history-rewriting argument of a `git push` / `git send-pack`, else None."""
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            continue
        if a.startswith("--"):
            name = a[2:].split("=", 1)[0]
            if name and any(o.startswith(name) for o in _FORCE_LONG):
                return a
            skip = a in _PUSH_VALUE_OPTS
        elif a.startswith("-") and len(a) > 1:
            cluster = a[1:]
            if "o" in cluster:  # `-o<value>`: everything after the o is the push option's value
                cluster, attached = cluster.split("o", 1)
                skip = attached == ""
            if "f" in cluster:
                return a
        elif a.startswith("+") and len(a) > 1:
            return a
    return None


def _word(t: str) -> str:
    return t.rsplit("/", 1)[-1]


def _command_force(rest: list[str], depth: int) -> list[str]:
    """Force-pushes in ONE simple command (its tokens, leading assignments already included)."""
    i = 0
    while i < len(rest) and (rest[i] in _CONTROL or re.fullmatch(r"\w+=.*", rest[i])):
        i += 1
    rest = rest[i:]
    if not rest or depth > 4:
        return []
    word = _word(rest[0])
    if word in ("for", "select", "case"):
        return []
    if word == "eval":
        return force_pushes(" ".join(rest[1:]), depth + 1)
    if word in _SHELLS:
        for j, a in enumerate(rest[1:], 1):
            if a == "-c" or (a.startswith("-") and not a.startswith("--") and "c" in a):
                k = j + 1
                if k < len(rest) and rest[k] == "--":
                    k += 1
                return force_pushes(rest[k], depth + 1) if k < len(rest) else []
            if not a.startswith("-") and not a.startswith("+"):
                break  # a script FILE: out of reach (see the PR's residual risk)
        return []
    if word in _WRAPPERS:
        found: list[str] = []
        if word == "watch":  # watch joins its arguments and runs them through `sh -c`
            found += force_pushes(" ".join(rest[1:]), depth + 1)
        for j, a in enumerate(rest[1:], 1):  # `env -S "cmd args"` splits a STRING into a command
            if word == "env" and a in ("-S", "--split-string") and j + 1 < len(rest):
                found += force_pushes(rest[j + 1], depth + 1)
            elif word == "env" and (a.startswith("-S") or a.startswith("--split-string=")) and len(a) > 2:
                found += force_pushes(a.split("=", 1)[1] if a.startswith("--") else a[2:], depth + 1)
        for j in range(1, len(rest)):
            if _word(rest[j]) in {"git", "eval"} | _SHELLS:
                found += _command_force(rest[j:], depth + 1)
        return found
    if word != "git":
        return []
    k = 1
    while k < len(rest) and rest[k].startswith("-"):
        k += 2 if rest[k] in _GIT_VALUE_OPTS else 1
    if k < len(rest) and rest[k] in ("push", "send-pack"):
        hit = _push_args_force(rest[k + 1 :])
        if hit:
            return [hit]
    return []


def force_pushes(cmd: str, depth: int = 0) -> list[str]:
    """Every force-form `git push` in `cmd`, as the offending argument. Parses tokens."""
    if depth > 4:
        return []
    stripped, shell_bodies = _strip_heredocs(cmd)
    text, subs = _scan(stripped)
    found: list[str] = []
    for seg in _segments(text):
        found += _command_force(seg, depth)
    for body in subs + shell_bodies:
        found += force_pushes(body, depth + 1)
    return list(dict.fromkeys(found))


def _detached_at_main(where) -> bool:
    """#4260: a worktree DETACHED at origin/main's tip is the sanctioned deploy posture (a
    CDK deploy re-bundles from the checkout tip), so it is silent. A lane BRANCH, a detached
    non-main sha, or an unresolvable origin/main still fires."""
    detached = git("symbolic-ref", "-q", "HEAD", cwd=where)[0] != 0
    code, head = git("rev-parse", "HEAD", cwd=where)
    code2, main_tip = git("rev-parse", "--verify", "-q", "refs/remotes/origin/main", cwd=where)
    return detached and code == 0 and code2 == 0 and head != "" and head == main_tip


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
        where = command_cwd(cmd, d.start("hit"), git_c=False)
        code, top = git("rev-parse", "--show-toplevel", cwd=where)
        code2, gitdir = git("rev-parse", "--git-dir", cwd=where)
        # `--git-common-dir` ALWAYS resolves to the main checkout's `.git` — from inside a
        # worktree too — so it can never distinguish the two (measured, #3262). `--git-dir`
        # is the one that differs: `.git` (or `.../.git`) in the main checkout, vs.
        # `.../.git/worktrees/<name>` inside a worktree. #4260: asked in the directory the
        # deploy RUNS in (payload cwd, or the command's own `cd`), not the hook's checkout.
        if code == 0 and code2 == 0 and gitdir not in ("", ".git") and not gitdir.endswith("/.git") and not _detached_at_main(where):
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

    forced = force_pushes(cmd)
    if forced:
        return emit(
            "force-push refused",
            [
                f"`git push` carries a history-rewriting form ({', '.join(forced)}). Force-pushing ANY branch is refused (#6157).",
                "Push a new commit (merge, never rebase-and-force) or a new branch name; ask the owner if a pushed branch truly must be rewritten.",
            ],
            event="PreToolUse",
            mode="block",
        )

    if not findings:
        return ok()
    title = findings[0][0] if len(findings) == 1 else " + ".join(t for t, _ in findings)
    lines = [ln for i, (t, body) in enumerate(findings) for ln in ([f"— {t}"] if len(findings) > 1 else []) + body]
    return emit(title, lines, event="PreToolUse")


if __name__ == "__main__":
    sys.exit(main())
