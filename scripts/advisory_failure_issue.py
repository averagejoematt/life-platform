"""
scripts/advisory_failure_issue.py — deduped GitHub-issue filing for advisory
scheduled workflows (#1447).

The advisory scheduled workflows (standalone visual-qa, golden-brief eval,
fresh-eyes discovery) red into the Actions run history and evaporate — the
exact silent-failure class that let a red sit unnoticed ~26h
(docs/INCIDENT_LOG.md, 2026-07-11). This script turns those reds into tracked
work items:

  --mode file     (the workflow FAILED) Search open issues carrying the
                  MARKER_LABEL for this workflow's HTML-comment marker.
                  Found → ONCE PER EPISODE (#5821): rewrite the issue
                  body's `Last failing run:` line (a body edit sends no
                  notification) and comment only when the failure summary
                  CHANGED since the last recorded one. Not found → create
                  one, ADR-099-shaped body (what failed, run link,
                  first-failure timestamp). One open issue per workflow —
                  repeats never spam duplicates.
  --mode recover  (the workflow SUCCEEDED) If this workflow's auto-filed
                  issue is open, comment the recovery run link and CLOSE it;
                  otherwise no-op. This is the documented close policy: an
                  auto-filed issue auto-closes on the next green run of the
                  same workflow (scheduled or manual dispatch). A later
                  failure files a fresh issue, so the history stays legible.

Called by the composite action .github/actions/advisory-failure-issue (which
maps job.status → mode). Stdlib-only (urllib, repo convention); the GitHub
token comes from env GITHUB_TOKEN (needs issues:write). The dedup/orchestration
logic is pure and offline-tested in tests/test_advisory_failure_issue.py.

ONE NOTIFICATION PER EPISODE (#5821, owner ruling 2026-11-11). Until #5821 every
repeat failure commented `Still failing — <ts>` on the open tracker, so a nightly
workflow that stayed red sent the owner one GitHub notification a day for the life
of the episode (#5558: a comment every day for ten days). The first filing and the
recovery comment carry the information; a repeat is the same message with a new run
link. So a repeat now edits a marker-delimited block in the BODY instead
(`LAST_RUN_START`..`LAST_RUN_END`: last failing run, trigger, failing runs counted
this episode), and records a short hash of the summary (`summary_marker`). It
comments again only when the summary changes (a different failure inside the same
open episode), on recovery, or on a NEW episode (the issue was closed, so the next
red files a fresh one). A tracker filed before #5821 carries no hash: its summary
counts as unchanged when the body already holds it (`**What failed:** …`).

Error posture: in file mode an API failure exits 1 (the run is already red —
the annotation shows filing failed rather than faking success); in recover
mode it warns and exits 0 (a filing hiccup must never red a green advisory
run — that would recreate the class this fixes).

THE BODY DELIBERATELY DOES **NOT** CARRY THE ADR-099 FILING SHAPE (#3065,
decided 2026-08-26). #3064 survived to a wrap and red the blocking hygiene
gate, so the fix had two candidate homes. Design (b) — teach THIS module to
emit `type:*`/`model:*`/`prio:*`/a milestone/a `**Score:**` line/an `**Epic:**`
line — was **rejected**: it would mint a fabricated score and milestone for a
row a machine closes within hours, feeding `backlog_next.py`'s ranked corpus
and inflating `check_backlog_hygiene.rule_now_liveness`'s "is the queue alive"
count with ops trackers. Design (a) shipped instead: the linter carves this
exact set out (`check_backlog_hygiene.is_tracker`) and holds it to a narrower
tracker contract. The full argument is in that module's docstring.

Two consequences for anyone editing `build_issue_body` below:
  * KEEP the `**Close policy:**` block. `rule_tracker_close_policy` requires it —
    the carve-out is granted BECAUSE the lifecycle is stated in the body, and a
    tracker with neither the backlog contract nor a close policy is an issue with
    no contract at all.
  * KEEP the `MARKER_LABEL` label and the `issue_marker()` comment together. They
    are this module's dedup/ownership pair AND the first two thirds of the
    linter's carve-out predicate; dropping either sends these issues back through
    the full ADR-099 contract and reds the next wrap.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MARKER_LABEL = "auto-filed"
MARKER_LABEL_COLOR = "B60205"
MARKER_LABEL_DESCRIPTION = "Auto-filed by an advisory scheduled workflow on failure (#1447); auto-closes on recovery"
API_ROOT = "https://api.github.com"


# ── pure pieces (offline-tested) ─────────────────────────────────────────────


def issue_marker(slug):
    """Stable per-workflow dedup key, embedded as an HTML comment in the issue body."""
    return f"<!-- advisory-failure: {slug} -->"


def find_open_issue(issues, slug):
    """Return the open auto-filed issue for this workflow slug, or None.

    `issues` is the label-filtered open-issue list from the API. Matching is
    by the body marker (stable across title edits); PRs (which the issues API
    also returns) are skipped.
    """
    marker = issue_marker(slug)
    for issue in issues:
        if "pull_request" in issue:
            continue
        if marker in (issue.get("body") or ""):
            return issue
    return None


def build_issue_title(workflow_name):
    return f"[auto-filed] {workflow_name}: scheduled advisory run failing"


def build_issue_body(slug, workflow_name, run_url, first_failure_ts, event_name, summary=""):
    summary_block = f"\n**What failed:** {summary}\n" if summary else "\n"
    return f"""Auto-filed by the **{workflow_name}** (`{slug}`) advisory scheduled workflow — its run failed and this
workflow gates nothing, so without this issue the red would only exist in the
Actions run history (the silent-failure class in docs/INCIDENT_LOG.md,
2026-07-11: a red sat unnoticed ~26h).
{summary_block}
**Evidence:** failing run (trigger: `{event_name}`): {run_url}
**First failure:** {first_failure_ts}

**Acceptance criteria:**
- [ ] The underlying failure is diagnosed and fixed (or explicitly dispositioned).
- [ ] A subsequent run of `{slug}` is green — this issue then auto-closes with a recovery comment.

**Close policy:** auto-closes on the next green run of this workflow
(scheduled or `workflow_dispatch`). Repeat failures comment here instead of
filing duplicates — one open issue per workflow — and only when the failure
changes; an unchanged repeat updates a `Last failing run:` line in this body. Closing by hand without
fixing just means the next failure files a fresh issue.

**outcome_if_fixed:** this advisory surface is back to silently green instead of silently red.

{issue_marker(slug)}
{summary_marker(summary)}
"""


def build_failure_comment(run_url, ts, event_name, summary=""):
    lines = [f"Still failing, with a changed failure — {ts} (trigger: `{event_name}`): {run_url}"]
    if summary:
        lines.append(f"\n{summary}")
    return "\n".join(lines)


# ── #5821: one notification per episode — the body carries the repeats ──────

LAST_RUN_START = "<!-- advisory-last-run:start -->"
LAST_RUN_END = "<!-- advisory-last-run:end -->"
_SUMMARY_MARKER_RE = re.compile(r"<!-- advisory-summary: ([0-9a-f]+) -->")
_RUN_COUNT_RE = re.compile(r"failing runs counted here: (\d+)")


def _normalise(text):
    return " ".join((text or "").split())


def summary_hash(summary):
    """A short, whitespace-insensitive fingerprint of the failure summary."""
    return hashlib.sha256(_normalise(summary).encode()).hexdigest()[:16]


def summary_marker(summary):
    return f"<!-- advisory-summary: {summary_hash(summary)} -->"


def summary_changed(body, summary):
    """Did the failure summary change since the last one this issue recorded?

    Reads the hash marker; a pre-#5821 tracker has none, and then its summary is
    unchanged iff the body already contains it (`**What failed:** <summary>`), so the
    first repeat after this lands edits the body instead of commenting.
    """
    body = body or ""
    m = _SUMMARY_MARKER_RE.search(body)
    if m:
        return m.group(1) != summary_hash(summary)
    if not _normalise(summary):
        return False
    return _normalise(summary) not in _normalise(body)


def _runs_so_far(body):
    block = _last_run_block_of(body)
    m = _RUN_COUNT_RE.search(block) if block else None
    return int(m.group(1)) if m else 1  # the filing run itself is run 1


def _last_run_block_of(body):
    body = body or ""
    i, j = body.find(LAST_RUN_START), body.find(LAST_RUN_END)
    return body[i : j + len(LAST_RUN_END)] if 0 <= i < j else ""


def build_last_run_block(run_url, ts, event_name, runs):
    return (
        f"{LAST_RUN_START}\n"
        f"**Last failing run:** {ts} (trigger: `{event_name}`): {run_url} — failing runs counted here: {runs}. "
        "_Updated in place on every repeat failure (a body edit sends no notification, #5821); "
        "a comment is posted only when the failure changes, and on recovery._\n"
        f"{LAST_RUN_END}"
    )


def update_body_for_repeat(body, run_url, ts, event_name, summary):
    """The issue body with its last-run block and summary marker rewritten in place."""
    body = body or ""
    block = build_last_run_block(run_url, ts, event_name, _runs_so_far(body) + 1)
    old = _last_run_block_of(body)
    body = body.replace(old, block) if old else body.rstrip("\n") + "\n\n" + block + "\n"
    marker = summary_marker(summary)
    if _SUMMARY_MARKER_RE.search(body):
        body = _SUMMARY_MARKER_RE.sub(marker, body, count=1)
    else:
        body = body.rstrip("\n") + "\n" + marker + "\n"
    return body


def build_recovery_comment(run_url, ts):
    return (
        f"Recovered — green run at {ts}: {run_url}\n\n"
        "Auto-closing per the close policy (one green run of the same workflow closes the auto-filed issue)."
    )


def exit_code_for_error(mode):
    """file → 1 (run is already red; surface the filing failure honestly);
    recover → 0 (never red a green advisory run over a filing hiccup)."""
    return 0 if mode == "recover" else 1


def run(mode, slug, workflow_name, summary, run_url, event_name, client, now_iso=None):
    """Orchestrate one file/recover pass.

    Returns 'created:N' | 'updated:N' (repeat, body edited, no notification) |
    'commented:N' (repeat with a changed failure) | 'closed:N' | 'noop'.
    """
    if mode not in ("file", "recover"):
        raise ValueError(f"unknown mode: {mode!r}")
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = find_open_issue(client.list_open_issues(MARKER_LABEL), slug)

    if mode == "file":
        if existing is not None:
            number = existing["number"]
            body = existing.get("body") or ""
            changed = summary_changed(body, summary)
            client.update_issue_body(number, update_body_for_repeat(body, run_url, now_iso, event_name, summary))
            if changed:
                client.comment(number, build_failure_comment(run_url, now_iso, event_name, summary))
                return f"commented:{number}"
            return f"updated:{number}"
        client.ensure_label(MARKER_LABEL, MARKER_LABEL_COLOR, MARKER_LABEL_DESCRIPTION)
        created = client.create_issue(
            title=build_issue_title(workflow_name),
            body=build_issue_body(slug, workflow_name, run_url, now_iso, event_name, summary),
            labels=[MARKER_LABEL, "area:infra"],
        )
        return f"created:{created['number']}"

    # recover
    if existing is None:
        return "noop"
    client.comment(existing["number"], build_recovery_comment(run_url, now_iso))
    client.close_issue(existing["number"])
    return f"closed:{existing['number']}"


# ── thin urllib GitHub client (only runs inside the workflows) ───────────────


class GitHubClient:
    def __init__(self, repo, token):
        self.repo = repo
        self.token = token

    def _request(self, method, path, payload=None):
        url = f"{API_ROOT}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "life-platform-advisory-failure-issue",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
        return json.loads(body) if body else {}

    def list_open_issues(self, label):
        q = urllib.parse.urlencode({"state": "open", "labels": label, "per_page": 100})
        return self._request("GET", f"/repos/{self.repo}/issues?{q}")

    def ensure_label(self, name, color, description):
        try:
            self._request("GET", f"/repos/{self.repo}/labels/{urllib.parse.quote(name)}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            self._request("POST", f"/repos/{self.repo}/labels", {"name": name, "color": color, "description": description})

    def create_issue(self, title, body, labels):
        return self._request("POST", f"/repos/{self.repo}/issues", {"title": title, "body": body, "labels": labels})

    def comment(self, number, body):
        return self._request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def update_issue_body(self, number, body):
        return self._request("PATCH", f"/repos/{self.repo}/issues/{number}", {"body": body})

    def close_issue(self, number):
        return self._request("PATCH", f"/repos/{self.repo}/issues/{number}", {"state": "closed"})


# ── CLI entrypoint (composite action calls this) ─────────────────────────────


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--mode", required=True, choices=["file", "recover"])
    parser.add_argument("--workflow-slug", required=True, help="stable slug, the dedup key (e.g. visual-qa-standalone)")
    parser.add_argument("--workflow-name", required=True, help="human name for the issue title")
    parser.add_argument("--summary", default="", help="one-paragraph what-failed context for the issue body/comment")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")
    if not token:
        level = "warning" if args.mode == "recover" else "error"
        print(f"::{level}::GITHUB_TOKEN is not set — cannot file/resolve the advisory failure issue")
        return exit_code_for_error(args.mode)

    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    run_url = f"{server}/{repo}/actions/runs/{run_id}"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")

    client = GitHubClient(repo, token)
    try:
        result = run(args.mode, args.workflow_slug, args.workflow_name, args.summary, run_url, event_name, client)
    except Exception as e:  # noqa: BLE001 — deliberate: posture differs by mode, see module docstring
        level = "warning" if args.mode == "recover" else "error"
        print(f"::{level}::advisory_failure_issue --mode {args.mode} failed: {e}")
        return exit_code_for_error(args.mode)
    print(f"advisory_failure_issue: mode={args.mode} slug={args.workflow_slug} -> {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
