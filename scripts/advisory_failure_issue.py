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
                  Found → comment the new run link on it (one open issue per
                  workflow — repeats never spam duplicates). Not found →
                  create one, ADR-099-shaped body (what failed, run link,
                  first-failure timestamp).
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

Error posture: in file mode an API failure exits 1 (the run is already red —
the annotation shows filing failed rather than faking success); in recover
mode it warns and exits 0 (a filing hiccup must never red a green advisory
run — that would recreate the class this fixes).
"""

import argparse
import json
import os
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
filing duplicates — one open issue per workflow. Closing by hand without
fixing just means the next failure files a fresh issue.

**outcome_if_fixed:** this advisory surface is back to silently green instead of silently red.

{issue_marker(slug)}
"""


def build_failure_comment(run_url, ts, event_name, summary=""):
    lines = [f"Still failing — {ts} (trigger: `{event_name}`): {run_url}"]
    if summary:
        lines.append(f"\n{summary}")
    return "\n".join(lines)


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
    """Orchestrate one file/recover pass. Returns 'created:N' | 'commented:N' | 'closed:N' | 'noop'."""
    if mode not in ("file", "recover"):
        raise ValueError(f"unknown mode: {mode!r}")
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = find_open_issue(client.list_open_issues(MARKER_LABEL), slug)

    if mode == "file":
        if existing is not None:
            client.comment(existing["number"], build_failure_comment(run_url, now_iso, event_name, summary))
            return f"commented:{existing['number']}"
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
