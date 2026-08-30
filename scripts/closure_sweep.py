#!/usr/bin/env python3
"""scripts/closure_sweep.py — detector A of the closure contract (#3318): the close, audited.

WHAT IT FINDS (each code is registered in scripts/closure_contract.py — the ONE vocabulary)
  post-close-comment     STRUCTURAL: a non-bot comment later than `closedAt` + the grace window
                         that is not the ADR-099 verdict (`**Outcome:**`). A timestamp
                         comparison, no words read — this is what would have caught #2848 and
                         #2670 the night they happened.
  post-close-assertion   LEXICAL (secondary, named as such): a post-close comment saying the
                         close was wrong ("stays OPEN", "reopen", "not met", …).
  unhomed-residual       the closing verdict names a residual with no carrier `#N`, fold `#N`,
                         or `not-work — <home>` — the handover's (e4) rule, applied to the close.
  no-outcome-verdict     a COMPLETED close after the ADR-099 amendment with no verdict comment.
  epic-children-open     a closed `type:epic` while an open issue still declares `**Epic:** #N`.

TWO MODES, ONE PARSER
  --fixture FILE   offline: FILE is `{"issues": [<GraphQL Issue node>...], "open_issues":
                   [{"number", "body"}...]}` — the SAME node shape the live query returns
                   (tests/fixtures/closure_contract/*.json are captured from the real wire).
  live (default)   `gh api graphql` — closed issues via the search API (the same
                   `closed:>=DATE` query wrap step (e8) already runs) plus the open corpus
                   for the epic-children check. Read-only.

  --session        window = closed since today 00:00 UTC (the wrap's own scope; ~5 issues)
  --since DATE     window = closed since DATE (the audit shape: `--since 2026-08-16`)
  --last N         window = the N most recently closed (the /sdlc-review sample)

POSTURE (closure_contract.mode(): `warn` today)
  warn   every finding printed; exit 0. A fetch failure prints UNVERIFIED and exits 0 — the
         same fail-open-noted-in-handover shape as the (e7) hygiene gate.
  block  findings exit 1; a fetch failure exits 2 ("could not look" is never a pass).
  The last line is always machine-readable:
    CLOSURE-SWEEP scanned=<n> window=<…> hits=<k> dispositioned=<d> mode=<warn|block>
  (or `CLOSURE-SWEEP UNVERIFIED — <reason>`), so scripts/wrap_gates.py fills the
  `**Closure DoD:**` draft line from it without phrase-matching prose.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closure_contract as cc  # noqa: E402  (same directory; the ONE registry, #3318)

REPO = "averagejoematt/life-platform"
GRAPHQL_PAGE = 50


@dataclass(frozen=True)
class Finding:
    code: str
    issue: int
    detail: str


@dataclass
class Issue:
    number: int
    title: str
    closed_at: datetime | None
    state_reason: str
    labels: tuple
    comments: list  # [(created_at: datetime, login: str, body: str)] in ascending time


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_issue(node: dict) -> Issue:
    """One GraphQL Issue node (the wire shape) → Issue. Used by BOTH fixture and live paths."""
    labels = tuple(lbl["name"] for lbl in (node.get("labels") or {}).get("nodes") or [])
    comments = []
    for c in (node.get("comments") or {}).get("nodes") or []:
        login = ((c.get("author") or {}).get("login")) or ""
        comments.append((_ts(c.get("createdAt")), login, c.get("body") or ""))
    comments.sort(key=lambda t: t[0] or datetime.min.replace(tzinfo=timezone.utc))
    return Issue(
        number=int(node["number"]),
        title=node.get("title") or "",
        closed_at=_ts(node.get("closedAt")),
        state_reason=(node.get("stateReason") or "").upper(),
        labels=labels,
        comments=comments,
    )


def evaluate_issue(issue: Issue, open_children: tuple = ()) -> list:
    """Pure. Findings for one closed issue against the contract."""
    findings: list = []
    if issue.closed_at is None:
        return findings  # not closed (or reopened) — nothing to audit
    grace_end = issue.closed_at + timedelta(minutes=cc.POST_CLOSE_GRACE_MINUTES)
    human = [(t, login, body) for (t, login, body) in issue.comments if t is not None and not cc.is_bot(login)]
    post = [(t, login, body) for (t, login, body) in human if t > issue.closed_at]
    verdicts = [(t, body) for (t, _login, body) in human if cc.has_verdict(body)]

    for t, _login, body in post:
        delay = t - issue.closed_at
        mins = int(delay.total_seconds() // 60)
        if not cc.has_verdict(body) and t > grace_end:
            findings.append(Finding("post-close-comment", issue.number, f"+{mins}m after close: {body.strip().splitlines()[0][:90]!r}"))
        m = cc.REOPEN_PHRASE_RE.search(body)
        if m:
            findings.append(Finding("post-close-assertion", issue.number, f"+{mins}m after close says {m.group(0)!r}"))

    if issue.state_reason == "COMPLETED" and issue.closed_at.date().isoformat() >= cc.CONTRACT_SINCE:
        if not verdicts:
            findings.append(Finding("no-outcome-verdict", issue.number, "no comment carries the ADR-099 `**Outcome:**` verdict"))

    # The closing verdict = the LAST verdict-shaped comment (a correction supersedes).
    if verdicts:
        _t, body = verdicts[-1]
        for block in cc.unhomed_residuals(body):
            findings.append(Finding("unhomed-residual", issue.number, f"names a residual with no home: {block.splitlines()[0][:100]!r}"))

    if cc.EPIC_LABEL in issue.labels and open_children:
        kids = ", ".join(f"#{n}" for n in sorted(open_children))
        findings.append(Finding("epic-children-open", issue.number, f"closed epic with open children still declaring it: {kids}"))
    return findings


def open_children_index(open_issues: list) -> dict:
    """{epic_number: (child numbers…)} from the OPEN corpus's `**Epic:** #N` lines."""
    idx: dict = {}
    for o in open_issues or []:
        parent = cc.epic_parent(o.get("body") or "")
        if parent is not None:
            idx.setdefault(parent, []).append(int(o["number"]))
    return {k: tuple(v) for k, v in idx.items()}


def sweep(issues: list, open_issues: list | None = None) -> dict:
    """Pure over parsed issues. Returns {'findings', 'dispositioned', 'scanned'}."""
    children = open_children_index(open_issues or [])
    findings: list = []
    dispositioned: list = []
    for issue in issues:
        f = evaluate_issue(issue, children.get(issue.number, ()))
        if not f:
            continue
        if issue.number in cc.DISPOSITIONED_ESCAPES:
            dispositioned.append((issue.number, f))
        else:
            findings.extend(f)
    return {"findings": findings, "dispositioned": dispositioned, "scanned": len(issues)}


def render(result: dict, window: str, mode: str) -> tuple:
    """(exit_code, lines). Pure."""
    lines: list = []
    by_issue: dict = {}
    for f in result["findings"]:
        by_issue.setdefault(f.issue, []).append(f)
    for num in sorted(by_issue):
        lines.append(f"HIT #{num}")
        for f in by_issue[num]:
            lines.append(f"   - {f.code}: {f.detail}")
    for num, fs in result["dispositioned"]:
        d = cc.DISPOSITIONED_ESCAPES[num]
        lines.append(f"DISPOSITIONED #{num} ({d.date}: {d.reason[:80]}) — {len(fs)} finding(s) suppressed")
    hits = len(by_issue)
    lines.append(
        f"CLOSURE-SWEEP scanned={result['scanned']} window={window} hits={hits} findings={len(result['findings'])} "
        f"dispositioned={len(result['dispositioned'])} mode={mode}"
    )
    if hits and mode == "block":
        return 1, lines
    return 0, lines


# ── live fetch (read-only) ───────────────────────────────────────────────────────────────
_ISSUE_FIELDS = """
  number title closedAt stateReason
  labels(first: 20) { nodes { name } }
  comments(last: 30) { totalCount nodes { createdAt author { login } body } }
"""


def _gh_graphql(query: str, variables: dict) -> dict:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        cmd += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"gh api graphql failed (exit {p.returncode}): {p.stderr.strip()[:300]}")
    data = json.loads(p.stdout)
    if data.get("errors"):
        raise RuntimeError(f"graphql errors: {json.dumps(data['errors'])[:300]}")
    return data["data"]


def fetch_closed(repo: str, since: str | None, last: int | None) -> list:
    """Closed issue nodes via the search API — `closed:>=DATE` is the same filter (e8) uses."""
    q = f"repo:{repo} is:issue is:closed" + (f" closed:>={since}" if since else "")
    query = (
        "query($q: String!, $n: Int!, $after: String) {"
        " search(query: $q, type: ISSUE, first: $n, after: $after) {"
        "  issueCount pageInfo { hasNextPage endCursor }"
        "  nodes { ... on Issue { " + _ISSUE_FIELDS + " } } } }"
    )
    nodes: list = []
    after = None
    want = last or 10_000
    while len(nodes) < want:
        variables = {"q": q + " sort:updated-desc", "n": min(GRAPHQL_PAGE, want - len(nodes))}
        if after:
            variables["after"] = after
        data = _gh_graphql(query, variables)["search"]
        nodes.extend(n for n in data["nodes"] if n)
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    if last:
        nodes.sort(key=lambda n: n.get("closedAt") or "", reverse=True)
        nodes = nodes[:last]
    return nodes


def fetch_open(repo: str) -> list:
    owner, name = repo.split("/", 1)
    query = (
        "query($owner: String!, $name: String!, $after: String) {"
        " repository(owner: $owner, name: $name) {"
        "  issues(states: OPEN, first: 100, after: $after) {"
        "   pageInfo { hasNextPage endCursor } nodes { number body } } } }"
    )
    out: list = []
    after = None
    while True:
        variables = {"owner": owner, "name": name}
        if after:
            variables["after"] = after
        data = _gh_graphql(query, variables)["repository"]["issues"]
        out.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Closure-contract sweep over closed issues (#3318, detector A).")
    ap.add_argument("--fixture", help="offline: JSON {issues:[GraphQL nodes], open_issues:[{number,body}]}")
    ap.add_argument("--session", action="store_true", help="window = closed since today 00:00 UTC (the wrap's scope)")
    ap.add_argument("--since", help="window = closed since YYYY-MM-DD")
    ap.add_argument("--last", type=int, help="window = the N most recently closed")
    ap.add_argument("--json", help="write findings JSON here")
    ap.add_argument("--repo", default=REPO)
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    mode = cc.mode()

    if args.fixture:
        raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        nodes, open_issues = raw.get("issues") or [], raw.get("open_issues") or []
        window = f"fixture:{Path(args.fixture).name}"
    else:
        since = args.since
        if args.session:
            since = datetime.now(timezone.utc).date().isoformat()
        if not since and not args.last:
            print("choose a window: --session | --since DATE | --last N | --fixture FILE", file=sys.stderr)
            return 2
        window = f"closed>={since}" if since else f"last{args.last}"
        try:
            nodes = fetch_closed(args.repo, since, args.last)
            open_issues = fetch_open(args.repo)
        except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
            print(f"CLOSURE-SWEEP UNVERIFIED — could not read GitHub: {e}")
            return 2 if mode == "block" else 0

    issues = [parse_issue(n) for n in nodes]
    if not args.fixture and args.since:
        issues = [i for i in issues if i.closed_at and i.closed_at.date().isoformat() >= args.since]
    result = sweep(issues, open_issues)
    code, lines = render(result, window, mode)
    print("\n".join(lines))
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "window": window,
                    "mode": mode,
                    "scanned": result["scanned"],
                    "findings": [f.__dict__ for f in result["findings"]],
                    "dispositioned": {str(n): [f.__dict__ for f in fs] for n, fs in result["dispositioned"]},
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
