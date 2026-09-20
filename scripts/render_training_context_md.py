#!/usr/bin/env python3
"""render_training_context_md.py — render TRAINING_CONTEXT.md FROM the registry (#3715).

The document lives at the owner-only S3 prefix `s3://matthew-life-platform/config/
coaching/TRAINING_CONTEXT.md` (see `lambdas/training/training_context_registry.py` for
why it is not a tracked file). This script exists so that S3 object is never a hand-typed
second copy of `RECORDED_CONSTRAINTS` — it derives, one executable source of truth, per
the charter's registry primitive.

This script does NOT touch AWS. It only prints markdown to stdout. A human with owner S3
write credentials reviews the printed content, then uploads it:

    python3 scripts/render_training_context_md.py | \\
        aws s3 cp - s3://matthew-life-platform/config/coaching/TRAINING_CONTEXT.md

gate:owner (#3715, acceptance box 5): the printed document is stamped UNCONFIRMED until
`lambdas/training/training_context_registry.CONFIRMED_BY_OWNER` is flipped to True in a
follow-up, owner-reviewed change — this script does not and cannot make that call.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from training import training_context_registry as reg  # noqa: E402


def render() -> str:
    lines = [
        "# TRAINING_CONTEXT.md",
        "",
        "> Rendered from `lambdas/training/training_context_registry.py` "
        f"({reg.ISSUE}) — do not hand-edit this file; edit the registry and re-render.",
        "",
        f"**Status: {'CONFIRMED' if reg.CONFIRMED_BY_OWNER else 'UNCONFIRMED — gate:owner, ' + reg.ISSUE}**",
        "",
    ]
    if reg.CONFIRMED_BY_OWNER:
        lines.append(f"Owner-reviewed: {reg.LAST_REVIEWED_BY_OWNER}.")
    else:
        lines.append(
            "The list below is drafted from the platform's own recorded history, not yet reviewed by the "
            "owner. A coach session must not treat it as cleared — read `format_unconfirmed_notice()` in the "
            "registry for the exact disclosure to give if this file cannot be read at all."
        )
    lines += ["", "## Standing constraints", ""]
    for c in reg.RECORDED_CONSTRAINTS:
        status = c.get("status", "active")
        resolved = f", {status} {c['resolved_on']} ({c['resolution_source']})" if status == "resolved" else ""
        lines.append(f"### {c['id']} ({c['kind']}) — dated {c['dated']}, confirmed={c['confirmed']}{resolved}")
        lines.append("")
        lines.append(c["detail"])
        lines.append("")
        lines.append(f"Source: {c['source']}")
        lines.append("")
    if not reg.RECORDED_CONSTRAINTS:
        lines.append("(none recorded)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render())
