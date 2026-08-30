#!/usr/bin/env python3
"""scripts/check_pr_closing_set.py — detector B of the closure contract (#3318): the closing set, asserted at merge.

THE CLASS
  A `Fixes #N` closes N on merge whether or not N's work is in the PR. It has fired from three
  directions: two lanes writing `pr_body.md` to one shared scratchpad and publishing each
  other's `Fixes` (#3222 via PR #3226, both directions); a PR body that named a box as
  "not satisfied" and carried `Fixes #2848` anyway (PR #3253); a negated or past-tense
  keyword ("does NOT close #2921", "closed #2921 by accident") that GitHub's parser reads as
  a close. Every one was found by a human, days later, reading closed issues.

WHAT THIS DOES (pure `evaluate`, thin `main`)
  Enumerates the closing set from FOUR places and asserts they agree:
    body       every closing keyword + ref in the PR description
    commits    the same, across every commit message on the PR (a `Fixes` in a commit
               travels with the squash and beats a corrected body — OPERATING_DISCIPLINE §2.5)
    declared   the lane's target from the `issue-<N>-<slug>` branch name (or `--target N`)
    github     GitHub's OWN linked set (`closingIssuesReferences`) — the wire truth about what
               the merge will close; a disagreement with the parse is a parser blind spot,
               reported in both directions
  and names: an epic in the set, an unchecked acceptance box next to a closing keyword, and a
  negated keyword. Finding codes are registered in scripts/closure_contract.py.

THE SEAM
  deploy/wait_pr_green.sh runs this on every merge-eligible verdict (exit 0 / 4) — the ONLY
  sanctioned pre-merge watcher (#3103), so it reads the PR body as it is AT THE MOMENT BEFORE
  THE MERGE. pr-checks.yml was rejected as the seam because it fires on push, not on a body
  edit (`pull_request` without `types: [edited]`), and the stray-Fixes class arrives via
  `gh pr edit`. scripts/assert_pr_green.py (the other assertion the hook layer accepts before
  `gh pr merge`) runs it too, so neither path can bypass it.

POSTURE (closure_contract.mode(): `warn` today)
  Always prints the set, then one machine-readable last line:
    CLOSING-SET VERDICT OK|NONGREEN|UNAVAILABLE mode=<warn|block> declared=… body=… commits=… github=…
  warn → exit 0 always. block → NONGREEN exits 1, UNAVAILABLE exits 2.

USAGE
  python3 scripts/check_pr_closing_set.py <PR>            # live, read-only
  python3 scripts/check_pr_closing_set.py --fixture FILE  # offline (gh pr view --json shape + issue_labels)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure_contract as cc  # noqa: E402  (same directory; the ONE registry, #3318)

REPO = "averagejoematt/life-platform"
PR_VIEW_FIELDS = "number,body,headRefName,commits,closingIssuesReferences"


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str


@dataclass
class Report:
    declared: int | None
    body: set
    commits: set
    github: set | None  # None when the wire set was not available (fixture without it, or gh failed)
    findings: list = field(default_factory=list)

    @property
    def parsed(self) -> set:
        return self.body | self.commits

    @property
    def ok(self) -> bool:
        return not self.findings


def _fmt(s) -> str:
    if s is None:
        return "n/a"
    return "{" + ",".join(f"#{n}" for n in sorted(s, key=lambda x: (isinstance(x, str), x))) + "}" if s else "{}"


def evaluate(
    body: str,
    commit_messages: list,
    branch: str | None,
    issue_labels: dict | None = None,
    github_closing: list | None = None,
    declared: int | None = None,
    repo: str = REPO,
) -> Report:
    """Pure. `issue_labels` = {issue_number: [label names]} for every referenced issue you could read."""
    body_refs = cc.closing_refs(body or "", repo)
    commit_refs = [r for msg in (commit_messages or []) for r in cc.closing_refs(msg or "", repo)]
    body_set = {n for n, _ in body_refs}
    commit_set = {n for n, _ in commit_refs}
    if declared is None:
        declared = cc.declared_target(branch)
    github_set = None if github_closing is None else {int(n) for n in github_closing}
    rep = Report(declared=declared, body=body_set, commits=commit_set, github=github_set)
    parsed = rep.parsed

    if body_set and commit_set and body_set != commit_set:
        rep.findings.append(Finding("body-commits-disagree", f"body closes {_fmt(body_set)} but commit messages close {_fmt(commit_set)}"))
    elif commit_set - body_set:
        rep.findings.append(
            Finding(
                "body-commits-disagree",
                f"commit message(s) close {_fmt(commit_set - body_set)} that the PR body does not — the squash carries them",
            )
        )

    if declared is not None and parsed and parsed != {declared}:
        rep.findings.append(Finding("declared-target-mismatch", f"branch declares #{declared} but the PR closes {_fmt(parsed)}"))

    if github_set is not None and github_set != {n for n in parsed if isinstance(n, int)}:
        rep.findings.append(
            Finding(
                "github-parse-disagree",
                f"GitHub will close {_fmt(github_set)} but this parse found {_fmt(parsed)} — trust GitHub, fix the parser",
            )
        )

    labels = issue_labels or {}
    for n in sorted(x for x in parsed | (github_set or set()) if isinstance(x, int)):
        if cc.EPIC_LABEL in (labels.get(n) or labels.get(str(n)) or []):
            rep.findings.append(
                Finding("epic-in-closing-set", f"#{n} is a `{cc.EPIC_LABEL}` — epics close by hand after their child set is reconciled")
            )

    if parsed and cc.UNCHECKED_BOX_RE.search(body or ""):
        rep.findings.append(
            Finding(
                "partial-acceptance-close",
                "the body still has an unchecked `- [ ]` box AND a closing keyword — partial acceptance is not a close",
            )
        )

    for text in [body or "", *(commit_messages or [])]:
        m = cc.NEGATED_CLOSING_RE.search(text)
        if m:
            rep.findings.append(
                Finding("negated-closing-keyword", f"{m.group(0)[:60]!r} still closes — GitHub reads neither negation nor tense")
            )
            break
    return rep


def render(rep: Report, mode: str, pr_label: str = "") -> tuple:
    """(exit_code, lines). Pure."""
    lines = [
        f"CLOSING-SET {pr_label}declared={_fmt({rep.declared} if rep.declared else None)} body={_fmt(rep.body)} commits={_fmt(rep.commits)} github={_fmt(rep.github)}"
    ]
    if not rep.parsed and not rep.github:
        lines.append(
            "CLOSING-SET NOTE this PR closes nothing (no closing keyword anywhere) — fine for a partial; say so in the closing comment"
        )
    for f in rep.findings:
        lines.append(f"CLOSING-SET FINDING {f.code}: {f.detail}")
    verdict = "OK" if rep.ok else "NONGREEN"
    lines.append(
        f"CLOSING-SET VERDICT {verdict} mode={mode} declared={_fmt({rep.declared} if rep.declared else None)} parsed={_fmt(rep.parsed)} github={_fmt(rep.github)}"
    )
    if verdict == "NONGREEN" and mode == "block":
        return 1, lines
    return 0, lines


# ── live (read-only) ─────────────────────────────────────────────────────────────────────
def _gh_json(args: list):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed (exit {p.returncode}): {p.stderr.strip()[:200]}")
    return json.loads(p.stdout)


def fetch_pr(pr: str, repo: str) -> dict:
    return _gh_json(["pr", "view", pr, "-R", repo, "--json", PR_VIEW_FIELDS])


def fetch_labels(numbers, repo: str) -> dict:
    out: dict = {}
    for n in numbers:
        try:
            data = _gh_json(["issue", "view", str(n), "-R", repo, "--json", "labels"])
            out[int(n)] = [lbl["name"] for lbl in data.get("labels") or []]
        except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            out[int(n)] = []  # unreadable labels are reported as none — the mismatch legs still run
    return out


def report_from_pr_json(data: dict, repo: str, declared: int | None = None) -> Report:
    """`gh pr view --json` shape (+ optional `issue_labels` in fixtures) → Report."""
    commits = [(c.get("messageHeadline") or "") + "\n" + (c.get("messageBody") or "") for c in data.get("commits") or []]
    github = [ref["number"] for ref in data.get("closingIssuesReferences") or []] if "closingIssuesReferences" in data else None
    labels = data.get("issue_labels")
    if labels is None and not data.get("_offline"):
        candidates = {n for n, _ in cc.closing_refs(data.get("body") or "", repo) if isinstance(n, int)}
        candidates |= {n for m in commits for n, _ in cc.closing_refs(m, repo) if isinstance(n, int)}
        candidates |= set(github or [])
        labels = fetch_labels(sorted(candidates), repo)
    return evaluate(data.get("body") or "", commits, data.get("headRefName"), labels, github, declared, repo)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Assert a PR's closing set against the lane's declared target (#3318, detector B).")
    ap.add_argument("pr", nargs="?", help="PR number")
    ap.add_argument("--pr", dest="pr_opt", help="PR number (option form — lets a wrapper append it last)")
    ap.add_argument("--fixture", help="offline: gh pr view --json shape, plus `issue_labels` {n: [labels]}")
    ap.add_argument("--target", type=int, help="override the declared target (default: from the issue-<N>-* branch name)")
    ap.add_argument("--repo", default=REPO)
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    mode = cc.mode()
    pr = args.pr or args.pr_opt
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        data.setdefault("_offline", True)
        if "issue_labels" not in data:
            data["issue_labels"] = {}
        rep = report_from_pr_json(data, args.repo, args.target)
        label = f"fixture={Path(args.fixture).name} "
    elif pr:
        try:
            data = fetch_pr(pr, args.repo)
        except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
            print(f"CLOSING-SET VERDICT UNAVAILABLE mode={mode} — could not read PR #{pr}: {e}")
            return 2 if mode == "block" else 0
        rep = report_from_pr_json(data, args.repo, args.target)
        label = f"PR #{pr} "
    else:
        print("give a PR number or --fixture FILE", file=sys.stderr)
        return 2
    code, lines = render(rep, mode, label)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
