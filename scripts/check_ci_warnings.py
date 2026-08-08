#!/usr/bin/env python3
"""scripts/check_ci_warnings.py — the /wrap standing-warning triage gate (#1966).

THE PROBLEM
  #1349 gave the suite-duration budget (and the coverage floor before it) a
  self-reminding `::warning::` annotation, but nothing OBLIGATED anyone to act
  on it once it fired. #1966's own finding is the proof: the duration warner
  tripped on a green main run (520s over the 480s budget) and the "optimize or
  raise" decision sat unactioned — a `::warning::` on an otherwise-green run is
  easy to treat as noise precisely BECAUSE main still reads green. Same
  normalization risk #1959 named for the CloudWatch alarm board, just applied
  to CI annotations instead of alarms.

THE FIX
  A deterministic, read-only gate mirroring check_main_green.py's decode
  contract: read the check-run annotations GitHub attaches to the latest
  completed CI/CD run on main (`gh api .../commits/{sha}/check-runs` +
  `.../check-runs/{id}/annotations`), filter to `annotation_level == "warning"`,
  and require the session to either file an issue for each NEW one or record an
  explicit deliberate-no-action decision in the handover — the SAME session the
  warning is surfaced in. `--decoded` unblocks the wrap once that's written,
  exactly like check_main_green.py's contract.

  This gate intentionally does NOT persist a citation registry the way #1959's
  alarm-citation gate does: a CloudWatch alarm ages silently across many
  sessions so its gate needs memory of what's already been triaged, but a CI
  `::warning::` is scoped to ONE run — the live annotation set on the latest
  green run IS the whole state each wrap needs to see. Nothing to store between
  sessions; the obligation is "was THIS run's warning set looked at this wrap",
  not "has this alarm been red for N days across M sessions".

  Only checks a GREEN run on purpose — a red/stranded main is
  check_main_green.py's gate; triaging warnings on a run that isn't even green
  yet would be solving the wrong problem first.

DEGRADE HONESTLY
  Any `gh`/API failure (no auth, rate limit, network, offline) prints an
  UNVERIFIED notice and exits 0 — a gate that can't read GitHub must not claim
  a clean warning board (same fail-open shape as check_alarm_citations.py /
  check_backlog_hygiene.py).

USAGE
  python3 scripts/check_ci_warnings.py             # gate: untriaged warning(s) -> exit 1
  python3 scripts/check_ci_warnings.py --decoded    # operator named the triage; exit 0
"""

import json
import subprocess
import sys


def _gh_json(args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def warning_annotations(check_runs, annotations_by_id):
    """[(job_name, title, message)] for every `annotation_level == "warning"`
    annotation across `check_runs`. `annotations_by_id` maps a check-run's `id`
    to its already-fetched annotations list — injected rather than fetched here
    so this stays pure and offline-testable (mirrors check_alarm_citations.py's
    uncited_long_reds() split between pure logic and live I/O).
    """
    out = []
    for run in check_runs:
        if not (run.get("output") or {}).get("annotations_count"):
            continue
        for a in annotations_by_id.get(run.get("id"), []):
            if a.get("annotation_level") == "warning":
                out.append((run.get("name") or "?", a.get("title") or "", a.get("message") or ""))
    return out


def latest_green_main_info():
    """(sha, error) for main's newest completed, non-cancelled CI/CD run.

    `sha` is the run's headSha when that run is green (conclusion == "success"),
    else None — a not-yet-green newest run is check_main_green.py's problem, not
    this gate's, so it reads as "nothing to triage" rather than an error.
    `error` is a human string on any `gh` failure, in which case `sha` is always
    None and the caller must treat the result as UNVERIFIED, never as clean.
    """
    try:
        runs = _gh_json(["run", "list", "--branch", "main", "--workflow", "CI/CD", "--limit", "20", "--json", "status,conclusion,headSha"])
    except Exception as e:  # noqa: BLE001 — any gh/network/auth failure must degrade, not crash
        return None, str(e)
    for r in runs:
        if r.get("status") != "completed" or r.get("conclusion") == "cancelled":
            continue
        return (r.get("headSha") if r.get("conclusion") == "success" else None), None
    return None, None


def fetch_warnings_for_sha(sha):
    """Live fetch: (warnings, error) for `sha` via the GitHub check-runs API.

    `error` is a human string on any failure, in which case `warnings` is always
    `[]` — callers must treat that as UNVERIFIED, never as a clean board.
    """
    try:
        check_runs = _gh_json(["api", f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs", "--jq", ".check_runs"])
        annotations_by_id = {}
        for run in check_runs:
            if (run.get("output") or {}).get("annotations_count"):
                annotations_by_id[run["id"]] = _gh_json(["api", f"repos/{{owner}}/{{repo}}/check-runs/{run['id']}/annotations"])
        return warning_annotations(check_runs, annotations_by_id), None
    except Exception as e:  # noqa: BLE001
        return [], str(e)


def render(warnings, sha, unreachable_error):
    """(exit_code, message) for a computed result. Pure — unit-tested offline."""
    if unreachable_error is not None:
        return 0, (
            f"⚠️  check_ci_warnings: GitHub unreachable ({unreachable_error}) — CI-warning "
            "triage UNVERIFIED this run. Note that explicitly in the handover "
            "(`**CI warnings:** unverified — GitHub unreachable`) rather than claiming a clean board."
        )
    if sha is None:
        return (
            0,
            "ℹ️  check_ci_warnings: latest completed main run isn't green (or none found) — check_main_green.py owns that; nothing to triage here yet.",
        )
    if not warnings:
        return 0, f"✅ no ::warning:: annotations on the latest green main run ({sha[:8]})."
    lines = [f"❌ {len(warnings)} ::warning:: annotation(s) on the latest green main run ({sha[:8]}):"]
    for job, title, message in warnings:
        label = f"{job}: {title}" if title else job
        lines.append(f"   - [{label}] {message}")
    lines.append(
        "   For each one: file an issue (`gh issue create ...`, cite it in the handover) or "
        "make the deliberate no-action call THIS session and write it into the handover "
        "(`**CI warnings:** <N> — <one-line triage per warning>`), then re-run with --decoded. "
        "A ::warning:: on green main may not silently normalize into background noise (#1966)."
    )
    return 1, "\n".join(lines)


def main() -> int:
    decoded = "--decoded" in sys.argv
    sha, err = latest_green_main_info()
    warnings = []
    if err is None and sha is not None:
        warnings, err = fetch_warnings_for_sha(sha)
    code, message = render(warnings, sha, err)
    print(message)
    if code == 0:
        return 0
    if decoded:
        print("   --decoded acknowledged: the handover MUST name each warning's triage explicitly.")
        return 0
    print("   The wrap may not report a clean CI-warning board over this. File issues / decide, then --decoded after naming the triage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
