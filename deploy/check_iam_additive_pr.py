#!/usr/bin/env python3
"""deploy/check_iam_additive_pr.py — the additive-IAM gate at PR time (#5221).

WHY
  `deploy/iam_additive_gate.py` (#2834) runs only in main's `Plan deployments`, after merge.
  A PR whose CDK change reads OWNER-REQUIRED passed every PR check, merged, and stranded
  every deploy behind it (2026-10-20: PR #5217's evening check-in rule made CloudFormation's
  implicit `AWS::Lambda::Permission`, Plan red for ~70 min). This runs the SAME gate on the
  PR, so the merge decision is made knowing it.

WHAT IT COMPARES — the PR's own delta, no AWS
  Head side: the PR's tree (the `pull_request` merge ref) synthesized.
  Base side: the base branch tip (`git archive <base-sha>`) synthesized the same way, passed
  to the gate as `--deployed-dir`. The question is "does THIS PR add an owner-required
  delta", not "is main already carrying one" — a held owner PR's drift on main is main's
  Plan's red to report, not every later PR's. It needs no credentials, so it runs on every
  PR (a fork or Dependabot PR gets no OIDC token at all). What it gives up against `--live`:
  drift between main and what is deployed, which main's Plan still reports.
  Measured on the specimen (2026-10-20): synth of 94b69434f against f730b4e41 reads
  `LifePlatformServe OWNER-REQUIRED ✗ new-iam-resource TelegramEveningCheckinAllowEventRule…:
  AWS::Lambda::Permission` — the exact line main's Plan printed with `--live`.

RED, OR A NAMED WARNING
  Red by default — the precedent is main's Plan, which fails closed on the same verdict.
  An INTENDED owner-required change (a held owner PR like #5218) must stay mergeable by the
  owner: the PR label `owner-required-ack` turns the red into a `::warning` that still
  names every stack + statement. A gate that could not evaluate (synth failure, missing
  stack on the base side = a new stack) is OWNER-REQUIRED too, exactly as on main.

USAGE
  python3 deploy/check_iam_additive_pr.py --base-sha <sha> [--ack] [--work DIR] [--step-summary FILE]
  python3 deploy/check_iam_additive_pr.py --head-synth DIR --base-synth DIR [--ack]   # pre-synthesized
  Exit 0: every stack NO-IAM-CHANGE / ALLOW-ADDITIVE, or OWNER-REQUIRED acknowledged.
  Exit 1: OWNER-REQUIRED (or unevaluable) and not acknowledged.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "deploy" / "iam_additive_gate.py"
ACK_LABEL = "owner-required-ack"
OWNER = "OWNER-REQUIRED"


def synth(tree: Path, out: Path) -> None:
    """`cdk synth --all` of the CDK app under `tree/cdk` into `out` (offline: the app makes no lookups)."""
    proc = subprocess.run(
        ["npx", "cdk", "synth", "--all", "--quiet", "-o", str(out)], cwd=tree / "cdk", capture_output=True, text=True, timeout=900
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cdk synth failed in {tree}: {(proc.stderr or proc.stdout).strip()[-600:]}")


def export_tree(sha: str, dest: Path) -> None:
    """The base branch tip as a plain tree — `git archive`, so no second worktree is registered."""
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", sha], capture_output=True, timeout=300)
    if archive.returncode != 0:
        raise RuntimeError(f"git archive {sha} failed: {archive.stderr.decode(errors='replace').strip()[:300]}")
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True, timeout=300)


def run_gate(head_synth: Path, base_synth: Path, record: Path, step_summary: Path | None) -> int:
    """The #2834 gate itself, unchanged, with the base synth standing in for the deployed side."""
    cmd = [sys.executable, str(GATE), "--synth-dir", str(head_synth), "--deployed-dir", str(base_synth), "--json", str(record)]
    if step_summary is not None:
        cmd += ["--step-summary", str(step_summary)]
    return subprocess.run(cmd, timeout=600).returncode


def findings(record: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """(stack, kind, logical_id, detail) for every finding on an OWNER-REQUIRED stack."""
    out = []
    for stack, v in sorted((record.get("stacks") or {}).items()):
        if v.get("verdict") != OWNER:
            continue
        for f in v.get("findings") or [{"kind": "unevaluable", "logical_id": stack, "detail": v.get("unevaluable") or "?"}]:
            out.append((stack, str(f.get("kind")), str(f.get("logical_id")), str(f.get("detail"))))
    return out


def decide(gate_exit: int, record: dict[str, Any] | None, ack: bool) -> tuple[int, list[str]]:
    """The PR-time verdict: (exit code, GitHub annotation lines). Pure — the unit-tested seam."""
    if gate_exit == 0:
        return 0, ["IAM additive gate (PR delta, #5221): no stack reads OWNER-REQUIRED."]
    broken = [s for s in (record or {}).get("stacks", {}) if s.startswith("<")]  # `<manifest>` / `<stacks>`: no stack was read
    if record is None or broken:  # synth or the gate itself broke: nothing was decided, so the label cannot excuse it
        what = ", ".join(broken) or "no decision record"
        return 1, [f"::error title=IAM gate unevaluable::gate exit {gate_exit}, {what} — fails closed; `{ACK_LABEL}` does not apply."]
    rows = findings(record) or [("<all>", "unevaluable", "<gate>", f"gate exit {gate_exit} with no OWNER-REQUIRED stack named")]
    level = "warning" if ack else "error"
    lines = [f"::{level} title=IAM gate {OWNER}: {stack}::{kind} {logical_id}: {detail}"[:1500] for stack, kind, logical_id, detail in rows]
    stacks = sorted({r[0] for r in rows})
    if ack:
        lines.append(
            f"::warning title=IAM gate acknowledged::label `{ACK_LABEL}` is set — merging this strands main's Plan until the owner "
            f"runs `bash deploy/cdk_deploy.sh <Stack>` for {', '.join(stacks)}."
        )
        return 0, lines
    lines.append(
        f"::error title=IAM gate {OWNER}::{', '.join(stacks)} — this PR would strand main's Plan deployments (#5221). Move the "
        f"named change into an owner PR applied with `bash deploy/cdk_deploy.sh <Stack>`, or, if that IS this PR, add the "
        f"`{ACK_LABEL}` label."
    )
    return 1, lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-sha", help="base branch tip to synthesize as the comparison side")
    ap.add_argument("--head-synth", type=Path, help="pre-synthesized head cdk.out (skips the head synth)")
    ap.add_argument("--base-synth", type=Path, help="pre-synthesized base cdk.out (skips the base export + synth)")
    ap.add_argument(
        "--ack",
        action="store_true",
        default=os.environ.get("IAM_GATE_ACK") == "true",
        help=f"the PR carries the `{ACK_LABEL}` label (or IAM_GATE_ACK=true): warn, never red",
    )
    ap.add_argument("--work", type=Path, help="scratch directory (default: a fresh temp dir)")
    ap.add_argument("--step-summary", type=Path, help="append the gate's table here ($GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv[1:])
    if args.base_synth is None and not args.base_sha:
        ap.error("give --base-sha or --base-synth")
    work = args.work or Path(tempfile.mkdtemp(prefix="iam-gate-pr-5221-"))
    work.mkdir(parents=True, exist_ok=True)
    record_path = work / "iam_gate_pr_5221.json"
    try:
        head = args.head_synth or work / "head.out"
        if args.head_synth is None:
            synth(ROOT, head)
        base = args.base_synth or work / "base.out"
        if args.base_synth is None:
            export_tree(args.base_sha, work / "base-tree")
            synth(work / "base-tree", base)
        gate_exit = run_gate(head, base, record_path, args.step_summary)
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
    except Exception as exc:  # noqa: BLE001 — fail closed, as the gate does on main
        print(f"::error title=IAM gate unevaluable::{type(exc).__name__}: {exc}"[:1500])
        gate_exit, record = 2, None
    code, lines = decide(gate_exit, record, args.ack)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
