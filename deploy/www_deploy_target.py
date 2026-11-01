#!/usr/bin/env python3
"""deploy/www_deploy_target.py — which target does this v9 deploy run write? (#5534, epic #5529)

The one decision web-preview-deploy.yml makes, held in a tested entrypoint instead of workflow shell:

  event      input      live_at_root   → target
  push       —          false            preview   (every www/** merge, as since #5530)
  push       —          true             root      (after the cut-over: every www/** merge rebuilds /)
  dispatch   preview    any              preview   (a manual re-run of the preview)
  dispatch   root       true             root      (a manual re-run of the root deploy)
  dispatch   root       false            REFUSED   (exit 2 — the switch is the one-line merge that
                                                    sets live_at_root in www/owned_paths.json; a
                                                    dispatch cannot launch ahead of the repo)
  dispatch   (empty)    any              preview   (the dispatch default)

`live_at_root` is read from www/owned_paths.json through deploy/www_owned_paths.py — the same bit
qa/qa_manifest.py, scripts/v4_build_sitemap.py and the reach ratchet read, so the sweeps that judge a
root deploy already describe `/` as the v9 page set when the deploy is allowed to happen.

Usage:  python3 deploy/www_deploy_target.py [--event push|workflow_dispatch] [--input preview|root]
Prints `target=<preview|root>` and appends it to $GITHUB_OUTPUT when set. Exit 0 resolved · 2 refused.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deploy import www_owned_paths  # noqa: E402

PREVIEW, ROOT = "preview", "root"


def resolve(event: str, requested: str, live: bool) -> tuple[str | None, str]:
    """(target or None, reason). Pure — the rule above, nothing read."""
    requested = (requested or "").strip() or PREVIEW
    if event == "push":
        return (ROOT if live else PREVIEW), (
            "push to main: live_at_root=true → the root rebuilds on every www/** merge"
            if live
            else "push to main: live_at_root=false → the noindex preview at /next/v9/"
        )
    if requested == PREVIEW:
        return PREVIEW, "dispatch: preview requested"
    if requested == ROOT:
        if live:
            return ROOT, "dispatch: root requested and www/owned_paths.json says live_at_root=true"
        return None, (
            "dispatch: root requested but www/owned_paths.json has live_at_root=false — REFUSED. "
            "The switch is the one-line merge that sets live_at_root (python3 scripts/www_cutover_switch.py --live, then a PR); "
            "a dispatch cannot launch ahead of the repo (#5534)."
        )
    return None, f"dispatch: unknown target {requested!r} (preview|root)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "push"))
    ap.add_argument("--input", default=os.environ.get("WWW_TARGET_INPUT", ""), help="the workflow_dispatch `target` input")
    args = ap.parse_args(argv)
    live = www_owned_paths.live_at_root()
    target, reason = resolve(args.event, args.input, live)
    print(f"www_deploy_target: {reason}")
    if target is None:
        return 2
    print(f"target={target}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"target={target}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
