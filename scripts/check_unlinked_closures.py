#!/usr/bin/env python3
"""scripts/check_unlinked_closures.py — detector C of the closure contract (#3318/#3812): the close that never happened.

THE CLASS — the direction nothing was watching
  Detector B (`check_pr_closing_set.py`) catches a PR that closes TOO MUCH: a stray
  `Fixes #N` closing an issue whose work is not in the diff. Nothing caught the opposite,
  and the opposite is the one that has actually been costing the backlog its honesty.

  Session AF (2026-09-15) swept 40 open issues by hand and found **11 that no longer
  reproduced** — every one already fixed by a merged PR, open 7–17 days. **Ten of the eleven
  named the issue in the merge commit's own subject line with no closing keyword.** The
  work shipped; the keyword did not; the issue sat open until a human happened to re-read
  it. ~84 more of the open corpus had never been swept at all (#3812).

  That is a mechanical signal sitting in data the repo already has. This file reads it.

WHAT THIS DOES (pure `evaluate`, thin `main`)
  For every commit on `main` in the window, parse three sets from subject + body:

    closing    every closing keyword + ref (`cc.CLOSING_REF_RE` — the grammar defined ONCE
               in closure_contract.py, imported here, never re-typed)
    subject    every `#N` in the SUBJECT line, minus the trailing squash `(#PR)` GitHub
               appends — this repo's convention is `fix(area): … (#issue) (#pr)`, so a `#N`
               in the subject is a claim that this commit addresses N
    body       every other `#N` — `Refs`, `**Epic:** #N`, a cited sha's context

  A finding is raised for a SUBJECT ref to a STILL-OPEN issue with no closing keyword
  anywhere in the message. Body-only refs are deliberately NOT findings: `Refs #N` and
  `**Epic:** #N` are correct, common, and would bury the signal (43 raw mentions in the
  60-day window collapse to 20 subject-level ones, and the 11 AF found by hand are all in
  the 20).

SUPPRESSIONS — each one is a documented correct behaviour, not a mute
  1. `closure:live-proof` on the issue, or `**Closure class:** instrument` in the message.
     An instrument closes on its first non-degraded LIVE output, never on the merge
     (contract requirement `live-proof-before-close`, #3595). A `Refs #N` on those is the
     rule working. Reported separately under `--show-held`, never as a finding.
  2. `type:epic`. An epic closes on its Outcome sentence after its child set reconciles
     (requirement `epic-after-children`), never on a keyword — detector B already names an
     epic in a closing set as a finding, so raising one here would ask for the thing B
     forbids.
  3. The dated exemption ledger `DISPOSITIONED` below (charter primitive 3, the ratchet):
     an issue whose subject mention is genuinely context, entered with a date and a reason.

  A finding is a QUESTION, never a closure. It says "this commit claims to address an open
  issue"; whether the defect still reproduces is a judgement a human makes against the live
  tree. That distinction is the whole safety story: `--json` feeds a sweep, not a bot.

POSTURE
  Advisory (`warn`) by design and not on a flip path. Its false positive is a re-read; its
  true positive is a closure nobody would otherwise make. Registered in
  `closure_contract.CLOSURE_CONTRACT` as `close-the-shipped` / `unlinked-shipped-fix`.

USAGE
  python3 scripts/check_unlinked_closures.py                  # live, read-only, 60-day window
  python3 scripts/check_unlinked_closures.py --since 2026-08-01 --show-held
  python3 scripts/check_unlinked_closures.py --json out.json
  python3 scripts/check_unlinked_closures.py --fixture FILE   # offline {commits:[…], issues:[…]}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "averagejoematt/life-platform"
DEFAULT_WINDOW_DAYS = 60


def _closure_contract():
    """scripts/closure_contract.py — the registry. Imported by path so this runs from any cwd."""
    path = Path(__file__).resolve().parent / "closure_contract.py"
    spec = importlib.util.spec_from_file_location("_closure_contract_3812", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclasses resolve __module__ through sys.modules
    spec.loader.exec_module(mod)
    return mod


cc = _closure_contract()

ISSUE_REF_RE = re.compile(r"#(\d+)")
# GitHub's squash appends ` (#PR)` to the subject. The LAST parenthesised ref on a subject
# that ends in `)` is that PR number, not an issue — dropping it is what keeps the PR's own
# number out of the finding set.
TRAILING_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
EPIC_LABEL = "type:epic"

# ── the ratchet: subject mentions dispositioned as context, dated, with a reason ──────────
# Entries are removed, never edited, when the issue closes. A growing ledger is the signal
# that the convention is drifting; that is the point of keeping it visible.
DISPOSITIONED: dict = {
    # 3042: "[EPIC] The A-Grade Program" — also caught by the type:epic suppression; kept
    # here because the diligence docs name it in subjects as the PROGRAM, not as a fix.
}


@dataclass(frozen=True)
class Finding:
    code: str
    issue: int
    detail: str


@dataclass(frozen=True)
class Commit:
    sha: str
    when: str  # YYYY-MM-DD, UTC
    subject: str
    body: str

    @property
    def message(self) -> str:
        return f"{self.subject}\n{self.body}"


@dataclass(frozen=True)
class IssueFacts:
    number: int
    title: str
    labels: frozenset

    @property
    def is_epic(self) -> bool:
        return EPIC_LABEL in self.labels

    @property
    def held_for_live_proof(self) -> bool:
        return cc.INSTRUMENT_LABEL in self.labels


def parse_refs(commit: Commit) -> tuple:
    """(closing, subject_refs, body_refs) for one commit. Pure, and the only place the
    subject/body split is decided."""
    closing = set()
    for m in cc.CLOSING_REF_RE.finditer(commit.message):
        num = m.group("num") or m.group("url_num")
        if num:
            closing.add(int(num))
    subject = commit.subject
    trailing = TRAILING_PR_RE.search(subject)
    pr_number = int(trailing.group(1)) if trailing else None
    subject_refs = {int(m.group(1)) for m in ISSUE_REF_RE.finditer(subject)}
    if pr_number is not None:
        subject_refs.discard(pr_number)
    body_refs = {int(m.group(1)) for m in ISSUE_REF_RE.finditer(commit.body)} - subject_refs
    return closing, subject_refs, body_refs


def evaluate(commits: list, open_issues: dict) -> tuple:
    """Pure. → (findings, held) where `held` is the correctly-suppressed live-proof set.

    `open_issues` maps number → IssueFacts for every OPEN issue. A ref to a closed issue is
    silent by construction: the close already happened, however it was spelled.
    """
    findings: list = []
    held: list = []
    seen: dict = {}
    held_seen: dict = {}
    for commit in commits:
        closing, subject_refs, _body = parse_refs(commit)
        declared, _reason = cc.declared_closure_class(commit.message)
        for number in sorted(subject_refs - closing):
            issue = open_issues.get(number)
            if issue is None or issue.is_epic or number in DISPOSITIONED:
                continue
            where = f"{commit.sha[:9]} {commit.when} {commit.subject[:88]}"
            if issue.held_for_live_proof or declared == "instrument":
                held_seen.setdefault(number, []).append(where)
                continue
            seen.setdefault(number, []).append(where)
    for number, wheres in sorted(seen.items(), reverse=True):
        issue = open_issues[number]
        findings.append(
            Finding(
                "unlinked-shipped-fix",
                number,
                (
                    f"{len(wheres)} merged commit(s) name #{number} in the subject with no closing keyword, "
                    f"and it is still open — {issue.title[:70]!r}. Latest: {wheres[0]}"
                ),
            )
        )
    for number, wheres in sorted(held_seen.items(), reverse=True):
        held.append((number, open_issues[number].title, wheres))
    return findings, held


# ── live readers (thin; everything above is pure) ────────────────────────────────────────
def _run(cmd: list) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=str(ROOT)).stdout


def fetch_commits(since: str, ref: str = "origin/main") -> list:
    """Commits on `ref` since `since` (YYYY-MM-DD), newest first."""
    sep, rec = "\x01", "\x1e"
    out = _run(["git", "log", ref, f"--since={since}", f"--pretty=%H{sep}%cI{sep}%s{sep}%b{rec}"])
    commits: list = []
    for chunk in out.split(rec):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, when, subject, body = (chunk.split(sep, 3) + ["", "", "", ""])[:4]
        commits.append(Commit(sha=sha, when=when[:10], subject=subject, body=body))
    return commits


def fetch_open_issues(repo: str) -> dict:
    raw = _run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "500", "--json", "number,title,labels"])
    facts = {}
    for node in json.loads(raw):
        facts[int(node["number"])] = IssueFacts(
            number=int(node["number"]),
            title=node.get("title") or "",
            labels=frozenset(lbl["name"] for lbl in node.get("labels") or []),
        )
    return facts


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Unlinked-shipped-fix sweep over merged commits (#3812, detector C).")
    ap.add_argument("--since", help=f"window start YYYY-MM-DD (default: {DEFAULT_WINDOW_DAYS} days ago)")
    ap.add_argument("--ref", default="origin/main", help="git ref to read (default origin/main)")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--show-held", action="store_true", help="also list the correctly-held live-proof refs")
    ap.add_argument("--json", help="write findings JSON here")
    ap.add_argument("--fixture", help="offline: JSON {commits:[{sha,when,subject,body}], issues:[{number,title,labels}]}")
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.fixture:
        raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        commits = [
            Commit(sha=c["sha"], when=c.get("when", ""), subject=c.get("subject", ""), body=c.get("body", "")) for c in raw["commits"]
        ]
        open_issues = {
            int(i["number"]): IssueFacts(number=int(i["number"]), title=i.get("title", ""), labels=frozenset(i.get("labels") or []))
            for i in raw["issues"]
        }
        window = f"fixture:{Path(args.fixture).name}"
    else:
        since = args.since or (datetime.now(timezone.utc) - timedelta(days=DEFAULT_WINDOW_DAYS)).date().isoformat()
        commits = fetch_commits(since, args.ref)
        open_issues = fetch_open_issues(args.repo)
        window = f"{args.ref} since {since}"

    findings, held = evaluate(commits, open_issues)

    for f in findings:
        print(f"  {f.code}  #{f.issue}  {f.detail}")
    if args.show_held:
        for number, title, wheres in held:
            print(f"  held(live-proof)  #{number}  {len(wheres)} subject ref(s), correctly unlinked — {title[:70]!r}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "window": window,
                    "commits": len(commits),
                    "findings": [{"code": f.code, "issue": f.issue, "detail": f.detail} for f in findings],
                    "held": [{"issue": n, "title": t, "commits": w} for n, t, w in held],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    mode = cc.arming_for("unlinked-shipped-fix")
    print(
        f"UNLINKED-CLOSURE VERDICT {'OK' if not findings else 'NONGREEN'} mode={mode} "
        f"window={window} commits={len(commits)} findings={len(findings)} held={len(held)}"
    )
    return 1 if (findings and mode == "block") else 0


if __name__ == "__main__":
    raise SystemExit(main())
