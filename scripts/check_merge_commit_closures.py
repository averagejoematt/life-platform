#!/usr/bin/env python3
"""scripts/check_merge_commit_closures.py — detector D of the closure contract (#3863).

THE CLASS — the FOURTH text
  Detector B (`check_pr_closing_set.py`) validates three texts, and every one of them is
  PRE-merge: the PR body, the branch's commit messages, and GitHub's computed
  `closingIssuesReferences`. Its own header states the assumption that makes three enough:

      "a closing keyword in a commit travels with the squash and beats a corrected body"

  True while the squash message is DERIVED from the commits or the body. It is not derived
  when the merger supplies one: `gh pr merge --squash --body-file <f>` (or `--subject`, or
  the web UI's editable squash box) writes a message that exists only at merge time and
  that no pre-merge guard has ever seen.

  2026-09-17, PR #3862: the pre-merge run reported `commits={3715}` `github={3861}` and
  raised a body-commits-disagree WARN. That was read as "GitHub does not parse the colon
  form, so 3715 is safe" — a reading of the PR BODY treated as a fact about text that did
  not yet exist. The merge then supplied a custom body whose note explaining the removal of
  the offending phrase QUOTED the phrase, and GitHub retired an owner-gated issue at
  02:37:30Z. It was restored ~90s later, unchanged.

  The bitter part, and the reason this file is a backstop rather than a lint: **the custom
  squash body was used specifically to be safer.** Reaching for the bespoke path to avoid a
  hazard is exactly what left the coverage.

WHAT THIS DOES
  Read the merge commits on `main` in a window. For each, derive:

    committed   the closing set of the message that was ACTUALLY committed
                (`cc.CLOSING_REF_RE` — the grammar defined ONCE in closure_contract.py)
    declared    the closing set the PR carried pre-merge: its body, plus its branch
                commits, plus GitHub's own `closingIssuesReferences`

  A finding is raised for any issue in `committed` that is NOT in `declared` — an issue the
  merge closed that the PR never said it would. That is the only direction this detector
  owns; the opposite (shipped but unlinked) is detector C's, and "closes too much but said
  so" is detector B's.

WHY IT IS A POST-MERGE ASSERTION AND NOT A PRE-MERGE REFUSAL
  Both exist and they cover different sets. The pre-merge half is
  `scripts/hooks/guard_bash.py`, which now refuses `--body-file`/`--body`/`--subject` on
  `gh pr merge` so the sanctioned path cannot mint an unvalidated text at all. That guard
  cannot see the web UI, another machine, or a human merging by hand. This can — it reads
  what landed, so it is the only leg that covers EVERY member of the Set.

THE SELF-REFERENCE HAZARD, HANDLED
  This module is about closing keywords, so its own prose would be parsed as closing
  keywords by its own grammar (and by GitHub, and by the repo's own guards — #3812 blocked
  the PR that fixed exactly this). Every example string below is ASSEMBLED from fragments
  by `_lit()` and never written whole, for the same reason
  `scripts/gate_census_mutations.py` assembles its probe payloads.

POSTURE
  Advisory (`warn`) by design, like detectors B and C: its false positive is a re-read, and
  it runs after the fact, so blocking would have nothing left to block. Registered in
  `closure_contract.CLOSURE_CONTRACT` as `validated-merge-text` / `unvalidated-merge-closure`.

USAGE
  python3 scripts/check_merge_commit_closures.py                 # live, read-only, 30-day window
  python3 scripts/check_merge_commit_closures.py --days 60
  python3 scripts/check_merge_commit_closures.py --sha <sha>     # one merge commit
  python3 scripts/check_merge_commit_closures.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure_contract as cc  # noqa: E402  (the ONE registry, #3318)

REPO = "averagejoematt/life-platform"

#: The trailing `(#PR)` GitHub appends to a squash subject. A PR number is NOT an issue
#: reference and must never be counted as one.
_SQUASH_PR_SUFFIX = re.compile(r"\(#(\d+)\)\s*$")


def _lit(*parts: str) -> str:
    """Assemble a string that must not appear whole in this file — see the self-reference
    note in the header. Splitting it is the point; joining it here is not a bug."""
    return "".join(parts)


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str


@dataclass
class MergeAudit:
    sha: str
    subject: str
    pr: int | None
    committed: set
    declared: set | None  # None => the PR's pre-merge texts could not be read (reported, never silent)
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def closing_set(text: str) -> set:
    """Every issue number a closing keyword in `text` would close, per the ONE grammar.

    Deliberately identical to what GitHub itself acts on, including the forms a human
    reads as harmless: the colon form, and a keyword inside a code span or a quotation.
    GitHub ignores neither. Neither does this."""
    out: set = set()
    for m in cc.CLOSING_REF_RE.finditer(text or ""):
        num = m.group("num") or m.group("url_num")
        repo = m.group("repo") or m.group("url_repo")
        if num and (repo in (None, "", REPO)):
            out.add(int(num))
    return out


def subject_pr_number(subject: str) -> int | None:
    """The PR number from a squash subject's trailing `(#N)`, or None."""
    m = _SQUASH_PR_SUFFIX.search(subject or "")
    return int(m.group(1)) if m else None


def evaluate(
    committed_message: str, declared: set | None, sha: str = "", pr: int | None = None, commit_only: set | None = None
) -> MergeAudit:
    """PURE. `committed_message` is the full message that landed; `declared` is the PR BODY plus
    GitHub's computed closing set (None when they could not be read); `commit_only` is the refs that
    appeared ONLY in branch commits — named in a finding, never counted as a declaration."""
    subject = (committed_message or "").splitlines()[0] if committed_message else ""
    committed = closing_set(committed_message)
    # The squash's own `(#PR)` suffix is a PR ref, never an issue closure — but a closing
    # KEYWORD naming the PR number would still be picked up above, which is correct.
    audit = MergeAudit(
        sha=sha, subject=subject, pr=pr if pr is not None else subject_pr_number(subject), committed=committed, declared=declared
    )
    if declared is None:
        audit.notes.append(
            f"{sha[:9]}: the PR's pre-merge texts could not be read, so the committed closing set "
            f"{_fmt(committed)} was NOT compared. Unmeasured, not clean."
        )
        return audit
    extra = committed - declared
    if extra:
        via = ""
        if commit_only:
            carried = sorted(extra & commit_only)
            if carried:
                via = (
                    f" {_fmt(set(carried))} reached the merge text from a BRANCH COMMIT that the PR body and "
                    "GitHub's computed set both disagreed with — the shape detector B raises as "
                    "body-commits-disagree, and the shape that retired an owner-gated issue on 2026-09-17."
                )
        audit.findings.append(
            Finding(
                code="unvalidated-merge-closure",
                detail=(
                    f"{sha[:9]} ({subject[:70]}) closed {_fmt(extra)}, which the PR never declared "
                    f"(committed={_fmt(committed)} declared={_fmt(declared)}).{via} The message that landed was "
                    "not the message any pre-merge guard validated — the #3863 class. If that closure was "
                    "intended, say so in the PR; if it was not, reopen and add a dated line to "
                    "DISPOSITIONED_MERGE_TEXT."
                ),
            )
        )
    return audit


def _fmt(s) -> str:
    if s is None:
        return "n/a"
    return "{" + ",".join(f"#{n}" for n in sorted(s)) + "}" if s else "{}"


# ── the dated exemption ledger (charter primitive 3 — the ratchet) ───────────────────────
# A merge whose committed closing set legitimately exceeded the declared one, entered with a
# date and a reason. Keyed by sha. An empty ledger is the healthy state.
DISPOSITIONED_MERGE_TEXT: dict = {}


# ── live readers (thin; everything above is pure) ────────────────────────────────────────


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def _gh_json(*args: str):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def declared_set_for_pr(pr: int) -> tuple | None:
    """`(declared, commit_only)` for a PR, or None if its texts are unreadable.

    WHY THIS IS NOT ONE UNION — and this is the correction #3863's own incident forces.

    The obvious reading of that issue's box 2 is "compare the merge commit's closing set
    against the union of the PR's three pre-merge texts, red on any extra." Measured against
    the incident it was written for, PR #3862, that reading yields ZERO findings:

        body={3861}  commits={3715}  github={3861}   committed={3715,3861}
        committed - (body | commits | github) = {}        <- catches nothing
        committed - (body | github)           = {3715}    <- catches it exactly

    The branch commits are not a DECLARATION. They are the raw material detector B already
    reports on when they disagree with the body — `commits={3715} github={3861}` is precisely
    the body-commits-disagree WARN that was raised, and reasoned past, ninety seconds before
    an owner-gated issue was retired. Folding that set into "declared" would make this
    detector agree with the mistake by construction.

    So `declared` is BODY + GitHub's own computed set — the two texts that represent what the
    PR says it will close and what GitHub says it will close. The commit-only refs come back
    separately so they can be NAMED in the finding rather than silently deciding it."""
    data = _gh_json("pr", "view", str(pr), "--repo", REPO, "--json", "body,commits,closingIssuesReferences")
    if data is None:
        return None
    body = closing_set(data.get("body") or "")
    commits: set = set()
    for c in data.get("commits") or []:
        commits |= closing_set(c.get("messageHeadline", "") + "\n" + (c.get("messageBody") or ""))
    github = {int(r["number"]) for r in (data.get("closingIssuesReferences") or []) if r.get("number")}
    declared = body | github
    return declared, (commits - declared)


def pr_for_commit(sha: str) -> tuple:
    """(pr_number, how) for a merge commit, resolved from GitHub's own commit->PR association
    FIRST and only then from the subject's trailing `(#N)`.

    THE ORDERING IS THE POINT, and #3863's own incident is why. A squash subject supplied with
    `--subject` can put ANY number in that slot: `d681aecc6` reads
    `feat(backlog): ... (#3861)` where GitHub would have appended `(#3862)` — 3861 is the
    ISSUE. Parsing the subject there resolves to an issue number, `gh pr view` fails, and the
    audit degrades to "could not read" on the ONE commit this detector exists for. The merge
    path that mints an unvalidated text also erases the handle back to the text that should
    have validated it, so the handle must come from somewhere the merger did not author.

    This repo's convention is `fix(area): ... (#issue) (#pr)`, so a lone `(#N)` is ambiguous
    by construction even on the honest path. The subject parse stays only as the offline
    fallback (a fixture, or no network), and it says which one it used."""
    data = _gh_json("api", f"repos/{REPO}/commits/{sha}/pulls", "--jq", "[.[] | .number]")
    if isinstance(data, list) and data:
        return int(data[0]), "github-association"
    m = _SQUASH_PR_SUFFIX.search(_git("log", "-1", "--format=%s", sha).strip())
    return (int(m.group(1)), "subject-suffix") if m else (None, "unresolved")


def closure_effect(issue: int, sha: str) -> str:
    """Did this commit actually retire that issue? One of `closed-by-this-commit`,
    `no-effect` or `unknown`.

    WHY A FINDING CARRIES ITS EFFECT. Measured over a 30-day window, 6 of 100 merge commits
    carried an undeclared closing ref — and the two halves are not the same event:

      * 2b4d09aff retired #3535/#3537/#3538/#3539 and 1316cec12 retired #2846 — real state
        changes, by that commit, that no PR body or GitHub computed set declared;
      * ccf24a1c8/#3222, c1ef4e348/#3139 and a057c47d3/#1921 wrote a keyword at an issue that
        was ALREADY closed (a057c47d3's text is literally the narrative phrase "the closed
        #1921"), so GitHub's grammar matched and there was nothing left to act on.

    Both are the same defect in the text and only the first is an incident. Reporting them
    identically is how a detector earns the reputation that gets it skipped — the class
    recorded in `a_gate_that_cannot_be_satisfied_trains_readers_to_skip_it`. So the effect is
    MEASURED and printed rather than used to suppress: nothing is muted, and a reader can see
    at a glance which line needs a human today."""
    # `gh api --jq` emits a BARE string here, not JSON, so this reads stdout as text rather
    # than through _gh_json — a json.loads on `2b4d09aff2a03...` raises and the whole finding
    # would silently degrade to "unknown", which is the quiet-failure shape this file is about.
    p = subprocess.run(
        # EVERY close event, not `.[-1]`. An issue closed by this commit and then REOPENED has a
        # later close (or none) on top, so "the last close" reports no-effect on exactly the
        # incident this file exists for: 3715 was retired by d681aecc6 at 02:37:30Z and restored
        # ~90s later. "Was it ever closed by this commit" is the question; "is it closed now" is not.
        [
            "gh",
            "api",
            f"repos/{REPO}/issues/{issue}/timeline",
            "--paginate",
            "--jq",
            '[.[] | select(.event=="closed") | .commit_id] | join(" ")',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        return "unknown"
    cids = [c.strip('"') for line in p.stdout.splitlines() for c in line.split() if c and c != "null"]
    if any(c[:9] == sha[:9] for c in cids):
        return "closed-by-this-commit"
    return "no-effect"


def merge_commits(days: int, sha: str | None) -> list:
    """(sha, full message) for each commit in the window, newest first."""
    if sha:
        msg = _git("log", "-1", "--format=%B", sha)
        return [(sha, msg)] if msg else []
    raw = _git("log", f"--since={days} days ago", "--first-parent", "--format=%H%x00%B%x1e", "origin/main")
    out = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        h, _, body = record.partition("\x00")
        if h.strip():
            out.append((h.strip(), body))
    return out


def run(days: int = 30, sha: str | None = None) -> list:
    audits = []
    for h, msg in merge_commits(days, sha):
        committed = closing_set(msg)
        if not committed:
            continue  # nothing was closed by this commit — detector C owns the other direction
        pr, how = pr_for_commit(h)
        pair = declared_set_for_pr(pr) if pr else None
        declared, commit_only = pair if pair else (None, None)
        audit = evaluate(msg, declared, sha=h, pr=pr, commit_only=commit_only)
        if how == "subject-suffix":
            audit.notes.append(
                f"{h[:9]}: PR resolved from the SUBJECT suffix, not GitHub's association — a supplied --subject can write any number there."
            )
        elif how == "unresolved":
            audit.notes.append(
                f"{h[:9]}: no PR is associated with this commit (a direct push to main). Its closing set {_fmt(committed)} was never PR-validated by construction."
            )
        for f in audit.findings:
            effects = {n: closure_effect(n, h) for n in sorted(committed - (declared or set()))}
            if effects:
                audit.notes.append(f"{h[:9]}: measured effect per undeclared ref — " + ", ".join(f"#{n}:{e}" for n, e in effects.items()))
        if h in DISPOSITIONED_MERGE_TEXT:
            audit.notes.append(f"{h[:9]}: dispositioned — {DISPOSITIONED_MERGE_TEXT[h]}")
            audit.findings = []
        audits.append(audit)
    return audits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sha")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    audits = run(days=args.days, sha=args.sha)
    findings = [f for a in audits for f in a.findings]
    notes = [n for a in audits for n in a.notes]

    if args.json:
        print(
            json.dumps(
                {
                    "audited": len(audits),
                    "findings": [{"sha": a.sha, "code": f.code, "detail": f.detail} for a in audits for f in a.findings],
                    "notes": notes,
                },
                indent=2,
            )
        )
        return 0

    print(f"MERGE-TEXT CLOSING SET — {len(audits)} merge commit(s) with a closing set in the window")
    for a in audits:
        mark = "FINDING" if a.findings else "ok"
        print(f"  [{mark:7s}] {a.sha[:9]}  PR #{a.pr}  committed={_fmt(a.committed)} declared={_fmt(a.declared)}")
    for n in notes:
        print(f"  NOTE  {n}")
    for f in findings:
        print(f"  {f.code}: {f.detail}")
    print(f"\n{len(findings)} finding(s). Posture: advisory (warn) — see closure_contract.CLOSURE_CONTRACT['validated-merge-text'].")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
