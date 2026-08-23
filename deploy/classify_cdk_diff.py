#!/usr/bin/env python3
"""Classify a `cdk diff` transcript: code-only churn vs Lambda config drift CI cannot ship.

Extracted from the Plan job's inline awk (R20-F02, 2026-06-08) by #2993.

CI deploys Lambda CODE only (deploy_lambda.sh). Config properties — Handler, Runtime,
MemorySize, Timeout, Environment, Layers, Architectures — ship ONLY via `cdk deploy`,
so a merged config change silently does NOT reach AWS until someone runs it (the
og-image handler fix sat undeployed ~3 months). That warning must stay loud — but it
must only fire on properties CI genuinely cannot ship:

- **Asset-hash churn is not config.** `Code.S3Key` (and the paired `aws:asset:*`
  metadata) moves on every bundle rebuild by construction (#781: one bundle, ~90
  functions). Anything under the `Code` property is the class CI's code-deploy path
  exists to ship, and it ships it. Ignored here, per function, by property path.
- **Toolchain-chosen values are not merged config.** The CDK-internal LogRetention
  singleton's `Runtime` is picked by aws-cdk-lib's regionalFact (#2468: 2.244.0 →
  nodejs22.x, 2.263.0 → nodejs24.x), so a lib pin bump skews it against the deployed
  template with zero operator edits — this was the live trigger behind #2993's false
  "Lambda config change" advisories (run 5f5069f6 / 32637512129: both flagged stacks'
  only config-property diff was LogRetention Runtime nodejs22.x → nodejs24.x). It
  still converges only via `cdk deploy`, so it surfaces as a ::notice with an honest
  cause — not a ::warning demanding a manual production deploy of a "config change"
  that no merge made.

A residual config-property diff on a real function still emits the same
`::warning title=Run: cdk deploy <stack>` as before, now naming the exact
function(s) and property(ies) so obeying it stays cheap and ignoring it stays wrong.

Usage: python3 deploy/classify_cdk_diff.py /tmp/cdk_diff.txt
Always exits 0 — this is an advisory classifier, not a gate (unchanged from the awk).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

# The trigger set — identical to the awk it replaces (guard the SET: additions here
# widen what demands a manual prod deploy; removals silently hide undeployed config).
CONFIG_PROPS = frozenset({"Handler", "Runtime", "MemorySize", "Timeout", "Environment", "Layers", "Architectures"})

_STACK_RE = re.compile(r"^Stack (\S+)")
_LAMBDA_RE = re.compile(r"^\[[~+-]\] AWS::Lambda::Function (\S+)")
# Top-level property line under a resource: exactly one leading space, then ├─/└─.
# Deeper levels (e.g. Code └─ .S3Key, Environment └─ .Variables) are indented further
# and dot-prefixed; they never match.
_PROP_RE = re.compile(r"^ [├└]─ \[[~+-]\] (\S+)")


@dataclass
class StackVerdict:
    """Per-stack classification of a cdk diff."""

    config_changes: list[tuple[str, str]] = field(default_factory=list)  # (function, property)
    toolchain_skew: list[tuple[str, str]] = field(default_factory=list)  # LogRetention Runtime class


def classify(diff_text: str) -> dict[str, StackVerdict]:
    """Parse a `cdk diff --all` transcript into per-stack verdicts.

    Only stacks with at least one classified (non-ignored) Lambda property change
    appear in the result — a stack whose diff is pure Code/asset churn is absent,
    i.e. code-only, i.e. the deploy pipeline handles it.
    """
    verdicts: dict[str, StackVerdict] = {}
    stack: str | None = None
    function: str | None = None

    for line in diff_text.splitlines():
        m = _STACK_RE.match(line)
        if m:
            stack = m.group(1)
            function = None
            continue
        m = _LAMBDA_RE.match(line)
        if m:
            function = m.group(1)
            continue
        if line[:1] not in (" ", ""):
            # Any other column-0 content (another resource type, section headers like
            # Resources/Parameters/Outputs) ends the current Lambda block — property
            # lines under non-Lambda resources must never classify.
            function = None
            continue
        if function is None or stack is None:
            continue
        m = _PROP_RE.match(line)
        if not m:
            continue
        prop = m.group(1).rstrip(":")
        if prop not in CONFIG_PROPS:
            continue  # Code (S3Key/S3Bucket asset hash), Metadata aws:asset:*, Tags, …
        verdict = verdicts.setdefault(stack, StackVerdict())
        if prop == "Runtime" and function.startswith("LogRetention"):
            verdict.toolchain_skew.append((function, prop))
        else:
            verdict.config_changes.append((function, prop))

    return verdicts


def emit(verdicts: dict[str, StackVerdict]) -> list[str]:
    """Render GitHub Actions annotations + operator banner lines."""
    out: list[str] = []
    flagged = {s: v for s, v in verdicts.items() if v.config_changes}
    skewed = {s: v for s, v in verdicts.items() if v.toolchain_skew and not v.config_changes}

    if flagged:
        out.append("════════════════════════════════════════════════════════════")
        out.append("  ⚠️  MERGED LAMBDA CONFIG CHANGES NOT DEPLOYED BY CI")
        out.append("  (CI ships CODE only — config needs a manual cdk deploy)")
        out.append("════════════════════════════════════════════════════════════")
        for stack, verdict in flagged.items():
            detail = ", ".join(f"{fn}.{prop}" for fn, prop in verdict.config_changes)
            out.append(f"  • {stack}   →   cd cdk && npx cdk deploy {stack}   ({detail})")
            out.append(
                f"::warning title=Run: cdk deploy {stack}::{stack} has a Lambda config change "
                f"({detail}) that CI's code-deploy cannot ship. "
                f"Run locally: cd cdk && npx cdk deploy {stack}"
            )
        out.append("════════════════════════════════════════════════════════════")

    for stack, verdict in skewed.items():
        fns = ", ".join(fn for fn, _ in verdict.toolchain_skew)
        out.append(
            f"::notice title=LogRetention runtime skew ({stack})::{stack}: the CDK-internal "
            f"LogRetention singleton's Runtime differs from the deployed template ({fns}) — "
            f"chosen by aws-cdk-lib's regionalFact (#2468), it moves with the lib pin, not with "
            f"any merged config. It converges on the next cdk deploy of {stack}; no action "
            f"required by this merge."
        )

    if not flagged:
        out.append("✅ No undeployed Lambda config drift (asset-hash/code churn is code-only; CI ships it)")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <cdk-diff-transcript>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8", errors="replace") as fh:
        diff_text = fh.read()
    for line in emit(classify(diff_text)):
        print(line)
    return 0  # advisory, never gates (unchanged from the awk it replaces)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
